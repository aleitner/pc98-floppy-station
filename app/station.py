"""PC-98 Floppy Station: a window for the floppy bridge, no command line needed.

Double-click it (or run `python3 station.py`). It opens a page in the browser that shows
the Greaseweazle and both drives, a Start/Stop for the bridge, the two image files an
emulator opens, and a Play button when RetroArch with the PC-98 core is installed.

The bridge itself runs as a child process (floppy_bridge.py), so a drive fault can never
take the window down. Settings live in the user's config folder.

    station.py                 open the window
    station.py --no-browser    serve only; open http://127.0.0.1:9801 yourself
    station.py --bridge ...    run the bridge (used internally when packaged)
"""
from __future__ import annotations

import collections
import http.server
import json
import mimetypes
import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from bridge_paths import EXT, GEOMETRY, cmd_path, default_mountpoint

SYSTEM = platform.system()
PORT = 9801
APP_NAME = "PC-98 Floppy Station"
FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "static")

WINFSP_URL = "https://winfsp.dev/rel/"
FUSET_URL = "https://www.fuse-t.org/"
NP2KAI_URL = "https://github.com/AZO234/NP2kai"


# -- settings -------------------------------------------------------------------
def config_dir() -> str:
    if SYSTEM == "Windows":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    if SYSTEM == "Darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                        "pc98-floppy-station")


@dataclass
class Config:
    left: str = ""                 # "A" or "B": which drive is the left one; "" = not yet identified
    format: str = "pc98.2hd"
    mountpoint: str = field(default_factory=default_mountpoint)
    offsets: Dict[str, int] = field(default_factory=dict)
    emulator_command: str = ""     # custom launch command with {play} {fd1} {fd2}; "" = find RetroArch

    @property
    def right(self) -> str:
        return {"A": "B", "B": "A"}.get(self.left, "")

    @staticmethod
    def path() -> str:
        return os.path.join(config_dir(), "settings.json")

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(cls.path(), encoding="utf-8") as f:
                data = json.load(f)
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        os.makedirs(config_dir(), exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)


# -- hardware checks (only while the bridge is not running: it owns the board) ----
def board_port() -> Optional[str]:
    try:
        from greaseweazle.tools import util
        port: str = util.find_port()
        return port
    except Exception:
        return None


def driver_check() -> Tuple[bool, str]:
    """Can the FUSE layer be loaded? Runs in a child so a later install is seen without a restart."""
    try:
        out = subprocess.run(self_command(["--check-driver"]), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return out.returncode == 0, out.stdout.strip() or out.stderr.strip()


def driver_hint() -> str:
    if SYSTEM == "Windows":
        return f"Install WinFsp from {WINFSP_URL} and start this program again."
    if SYSTEM == "Darwin":
        return f"Install FUSE-T from {FUSET_URL} (or macFUSE) and start this program again."
    return "Install your distribution's fuse3 package (the fusermount3 command) and start again."


def probe_drives(cfg: Config) -> Dict[str, Dict[str, Any]]:
    """Disk present and write-protect state of both drives, by letter."""
    from floppy_drive import GwBackend, GwBoard
    board = GwBoard(None)
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for letter in ("A", "B"):
            be = GwBackend(letter, cfg.format, board=board, cyl_offset=cfg.offsets.get(letter, 0))
            try:
                out[letter] = {"disk": be.has_disk(), "protected": be.write_protected()}
            finally:
                be.close()
    finally:
        board.close()
    return out


# -- the bridge as a child process ------------------------------------------------
def self_command(args: List[str]) -> List[str]:
    """How to run this program again: the frozen executable, or the interpreter on this file."""
    if FROZEN:
        return [sys.executable] + args
    return [sys.executable, os.path.abspath(__file__)] + args


class Bridge:
    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen[str]] = None
        self.log: Deque[str] = collections.deque(maxlen=60)
        self.ready = False
        self.slots: Dict[str, Dict[str, Any]] = {}
        self.error = ""
        self.lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, cfg: Config) -> str:
        with self.lock:
            if self.running:
                return "already running"
            args = ["--bridge", "--control-stdin", "--fd1", cfg.left, "--fd2", cfg.right,
                    "--format", cfg.format, "--mountpoint", cfg.mountpoint]
            for letter, n in cfg.offsets.items():
                if n:
                    args += ["--offset", f"{letter}={n}"]
            self.log.clear()
            self.slots = {}
            self.error = ""
            self.ready = False
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if SYSTEM == "Windows" else 0  # type: ignore[attr-defined]
            self.proc = subprocess.Popen(self_command(args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, bufsize=1, creationflags=flags)
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
            return "starting"

    def _reader(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if line.startswith("STATUS "):
                line = line[7:]
            self.log.append(time.strftime("%H:%M:%S ") + line)
            self._parse(line)
        code = proc.wait()
        self.ready = False
        if code not in (0, None) and not self.error:
            self.error = f"the bridge stopped with code {code}"
        self.log.append(time.strftime("%H:%M:%S ") + "bridge exited")

    def _parse(self, line: str) -> None:
        if line == "ready":
            self.ready = True
        elif line.startswith("error "):
            self.error = line[6:]
        elif " is drive " in line:                      # "FD1.hdm is drive A (writable)"
            name = line.split(".", 1)[0]
            drive = line.split(" is drive ", 1)[1].split(" ", 1)[0]
            state = line.rsplit("(", 1)[1].rstrip(")")
            self.slots[name] = {"drive": drive, "disk": state != "no disk", "protected": state == "write-protected"}
        elif ": disk changed (" in line or ": now " in line:
            name = line.split(":", 1)[0]
            state = line.rsplit("(", 1)[1].rstrip(")") if "(" in line else line.rsplit(" now ", 1)[1]
            slot = self.slots.setdefault(name, {"drive": "?"})
            slot["disk"] = state != "no disk"
            slot["protected"] = state == "write-protected"

    def stop(self, mountpoint: str) -> str:
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                return "not running"
            try:
                assert proc.stdin is not None
                proc.stdin.write("stop\n")
                proc.stdin.flush()
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                if SYSTEM != "Windows":
                    tool = shutil.which("fusermount3") or shutil.which("fusermount") or "umount"
                    subprocess.run([tool, "-u", mountpoint] if tool != "umount" else [tool, mountpoint], check=False)
                    try:
                        proc.wait(10)
                    except subprocess.TimeoutExpired:
                        proc.terminate()
                else:
                    proc.terminate()
            return "stopped"


# -- emulator ------------------------------------------------------------------------
def find_retroarch() -> Optional[Tuple[List[str], str]]:
    """(command prefix, core path) for RetroArch with the Neko Project II kai core, if installed."""
    home = os.path.expanduser("~")
    if SYSTEM == "Linux":
        for base in (os.path.join(home, ".local/share/flatpak/app/org.libretro.RetroArch"),
                     "/var/lib/flatpak/app/org.libretro.RetroArch"):
            core = os.path.join(home, ".var/app/org.libretro.RetroArch/config/retroarch/cores/np2kai_libretro.so")
            if os.path.isdir(base) and os.path.isfile(core):
                return ["flatpak", "run", "org.libretro.RetroArch"], core
        exe = shutil.which("retroarch")
        core = os.path.join(home, ".config/retroarch/cores/np2kai_libretro.so")
        if exe and os.path.isfile(core):
            return [exe], core
    elif SYSTEM == "Windows":
        appdata = os.environ.get("APPDATA", "")
        for exe in (os.path.join(appdata, "RetroArch", "retroarch.exe"),
                    r"C:\RetroArch-Win64\retroarch.exe",
                    r"C:\Program Files (x86)\Steam\steamapps\common\RetroArch\retroarch.exe"):
            core = os.path.join(os.path.dirname(exe), "cores", "np2kai_libretro.dll")
            if os.path.isfile(exe) and os.path.isfile(core):
                return [exe], core
    elif SYSTEM == "Darwin":
        exe = "/Applications/RetroArch.app/Contents/MacOS/RetroArch"
        core = os.path.join(home, "Library/Application Support/RetroArch/cores/np2kai_libretro.dylib")
        if os.path.isfile(exe) and os.path.isfile(core):
            return [exe], core
    return None


def launch_emulator(cfg: Config) -> str:
    play = cmd_path(cfg.mountpoint, "play.cmd")
    ext = EXT[cfg.format]
    fd1 = cmd_path(cfg.mountpoint, "FD1" + ext)
    fd2 = cmd_path(cfg.mountpoint, "FD2" + ext)
    if cfg.emulator_command.strip():
        import shlex
        cmd = [a.format(play=play, fd1=fd1, fd2=fd2) for a in shlex.split(cfg.emulator_command, posix=SYSTEM != "Windows")]
    else:
        found = find_retroarch()
        if not found:
            return "RetroArch with the Neko Project II kai core was not found; open the two files in your emulator"
        prefix, core = found
        cmd = prefix + ["-L", core, play]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=(SYSTEM != "Windows"))
    except OSError as e:
        return f"couldn't start the emulator: {e}"
    return "emulator started"


# -- the local web app ----------------------------------------------------------------
class Station:
    def __init__(self) -> None:
        self.cfg = Config.load()
        self.bridge = Bridge()
        self.token = secrets.token_urlsafe(16)
        self.driver_ok, self.driver_msg = driver_check()
        self.probe: Dict[str, Dict[str, Any]] = {}
        self.probe_error = ""
        self.message = ""
        self.last_seen = 0.0           # when the page last asked for the state
        self.seen_once = False

    def refresh_probe(self) -> None:
        if self.bridge.running:
            return
        try:
            self.probe = probe_drives(self.cfg)
            self.probe_error = ""
        except Exception as e:
            self.probe = {}
            self.probe_error = str(e)

    def state(self) -> Dict[str, Any]:
        self.last_seen = time.monotonic()
        self.seen_once = True
        if self.message == "starting" and self.bridge.ready:
            self.message = "running"
        cfg = self.cfg
        ext = EXT[cfg.format]
        board = None if self.bridge.running else board_port()
        drives: Dict[str, Any] = {}
        for name, letter in (("FD1", cfg.left), ("FD2", cfg.right)):
            info: Dict[str, Any] = {"drive": letter, "side": "left" if name == "FD1" else "right",
                                    "file": cmd_path(cfg.mountpoint, name + ext)}
            if self.bridge.running:
                info.update(self.bridge.slots.get(name, {}))
            elif letter in self.probe:
                info.update(self.probe[letter])
            drives[name] = info
        emu = find_retroarch()
        return {
            "system": SYSTEM,
            "board": {"present": self.bridge.running or board is not None, "port": board},
            "driver": {"ok": self.driver_ok, "hint": "" if self.driver_ok else driver_hint(), "detail": self.driver_msg},
            "running": self.bridge.running, "ready": self.bridge.ready, "error": self.bridge.error,
            "identified": cfg.left in ("A", "B"),
            "mountpoint": cfg.mountpoint, "play": cmd_path(cfg.mountpoint, "play.cmd"),
            "drives": drives, "probe_error": self.probe_error,
            "emulator": {"found": emu is not None, "custom": bool(cfg.emulator_command.strip()),
                         "name": "RetroArch, Neko Project II kai core" if emu else ""},
            "log": list(self.bridge.log), "message": self.message,
            "config": asdict(cfg),
        }

    # actions
    def start(self) -> str:
        if not self.cfg.left:
            return "identify the left drive first"
        if not self.driver_ok:
            return driver_hint()
        if not board_port():
            return "the Greaseweazle isn't connected"
        self.probe = {}
        return self.bridge.start(self.cfg)

    def stop(self) -> str:
        msg = self.bridge.stop(self.cfg.mountpoint)
        self.refresh_probe()
        return msg

    def identify(self) -> Dict[str, Any]:
        """The user has put a disk in the LEFT drive only: whichever unit holds a disk is left."""
        if self.bridge.running:
            return {"ok": False, "message": "stop the bridge first"}
        try:
            probe = probe_drives(self.cfg)
        except Exception as e:
            return {"ok": False, "message": f"couldn't talk to the drives: {e}"}
        self.probe = probe
        with_disk = [k for k, v in probe.items() if v["disk"]]
        if len(with_disk) != 1:
            return {"ok": False, "message": "no disk found" if not with_disk else
                    "both drives hold a disk; leave only the left one in"}
        self.cfg.left = with_disk[0]
        self.cfg.save()
        return {"ok": True, "message": f"the left drive is unit {self.cfg.left}; the right one is {self.cfg.right}"}

    def settings(self, data: Dict[str, Any]) -> str:
        if "emulator_command" in data:
            self.cfg.emulator_command = str(data["emulator_command"])
        if data.get("swap"):
            self.cfg.left = self.cfg.right
        if data.get("left") in ("A", "B"):             # for people who already know their ribbon
            self.cfg.left = str(data["left"])
        if "format" in data and data["format"] in GEOMETRY:
            self.cfg.format = str(data["format"])
        self.cfg.save()
        return "saved"


def make_handler(st: Station) -> type:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _json(self, obj: Any, code: int = 200) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: str, subst: bool = False) -> None:
            full = os.path.normpath(os.path.join(STATIC, path))
            if not full.startswith(STATIC) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as f:
                body = f.read()
            if subst:
                body = body.replace(b"__TOKEN__", st.token.encode())
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if subst else "max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._file("index.html", subst=True)
            elif path.startswith("/static/"):
                self._file(path[len("/static/"):])
            elif path == "/api/state":
                self._json(st.state())
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.headers.get("X-Token") != st.token:
                self.send_error(403)
                return
            n = int(self.headers.get("Content-Length") or 0)
            data: Dict[str, Any] = json.loads(self.rfile.read(n) or b"{}") if n else {}
            path = urlparse(self.path).path
            if path == "/api/start":
                st.message = st.start()
            elif path == "/api/stop":
                st.message = st.stop()
            elif path == "/api/identify":
                self._json(st.identify())
                return
            elif path == "/api/probe":
                st.refresh_probe()
                st.message = st.probe_error or "drives checked"
            elif path == "/api/launch":
                st.message = launch_emulator(st.cfg)
            elif path == "/api/settings":
                st.message = st.settings(data)
            elif path == "/api/driver":
                st.driver_ok, st.driver_msg = driver_check()
                st.message = "driver found" if st.driver_ok else driver_hint()
            else:
                self.send_error(404)
                return
            self._json({"message": st.message})
    return Handler


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return int(s.getsockname()[1])
            except OSError:
                continue
    return preferred


def serve(open_browser: bool) -> int:
    st = Station()
    threading.Thread(target=st.refresh_probe, daemon=True).start()
    port = free_port(PORT)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(st))
    url = f"http://127.0.0.1:{port}/"
    print(f"{APP_NAME}: {url}", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    def watch_page() -> None:
        # The page asks for the state every second. When it has gone for a while and the
        # bridge isn't running, the window was closed: end the program. Browsers slow a
        # hidden tab's timers right down, so the wait is generous.
        while True:
            time.sleep(5)
            idle = time.monotonic() - st.last_seen
            if st.seen_once and not st.bridge.running and idle > 150:
                httpd.shutdown()
                return
    threading.Thread(target=watch_page, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if st.bridge.running:
            st.bridge.stop(st.cfg.mountpoint)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--bridge"]:
        import floppy_bridge                  # needs the FUSE driver; the window itself doesn't
        return floppy_bridge.main(args[1:])
    if args[:1] == ["--check-driver"]:
        try:
            import mfusepy  # noqa: F401
        except Exception as e:
            print(str(e))
            return 1
        print("ok")
        return 0
    return serve(open_browser="--no-browser" not in args)


if __name__ == "__main__":
    sys.exit(main())
