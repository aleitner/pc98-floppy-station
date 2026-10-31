"""PC-98 Floppy Station: a window for the floppy bridge, no command line needed.

Double-click it (or run `python3 station.py`). A window shows the Greaseweazle and both
drives, Start/Stop, the two image files an emulator opens, and a Play button when
RetroArch with the PC-98 core is installed. Each drive can be backed up to an image file,
and a backup can stand in for a drive: the bridge then serves that file instead.

The bridge runs as a child process (floppy_bridge.py), so a drive fault can never take the
window down. Settings and a log live in the user's config folder.

    station.py                 open the window (a bare browser window, or a browser tab)
    station.py --no-browser    serve only; open http://127.0.0.1:9801 yourself
    station.py --bridge ...    run the bridge (used internally when packaged)
"""
from __future__ import annotations

import collections
import glob
import http.server
import json
import logging
import mimetypes
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from bridge_paths import EXT, cmd_path, default_mountpoint, unmount

SYSTEM = platform.system()
PORT = 9801
APP_NAME = "PC-98 Floppy Station"
VERSION = "0.2.0"
FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.realpath(os.path.join(HERE, "static"))
SLOTS = ("FD1", "FD2")
MAX_BODY = 64 * 1024

log = logging.getLogger("station")


# -- settings -------------------------------------------------------------------
def config_dir() -> str:
    if SYSTEM == "Windows":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    if SYSTEM == "Darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                        "pc98-floppy-station")


def default_library() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs if os.path.isdir(docs) else os.path.expanduser("~"), "PC98 Floppies")


@dataclass
class Config:
    left: str = ""                 # "A" or "B": which drive is the left one; "" = not yet identified
    format: str = "pc98.2hd"
    mountpoint: str = field(default_factory=default_mountpoint)
    library: str = ""              # where backups live; "" = Documents/PC98 Floppies
    offsets: Dict[str, int] = field(default_factory=dict)      # drive letter -> steps, for a drive whose track 0 slipped
    emulator_command: str = ""     # own launch command with {play} {fd1} {fd2}; "" = find RetroArch
    images: Dict[str, str] = field(default_factory=dict)       # FD1/FD2 -> image file standing in for the drive

    @property
    def right(self) -> str:
        return {"A": "B", "B": "A"}.get(self.left, "")

    def letter(self, name: str) -> str:
        return self.left if name == "FD1" else self.right

    @staticmethod
    def path() -> str:
        return os.path.join(config_dir(), "settings.json")

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            with open(cls.path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cfg
        if not isinstance(data, dict):
            return cfg
        if data.get("left") in ("A", "B"):
            cfg.left = str(data["left"])
        if data.get("format") in EXT:
            cfg.format = str(data["format"])
        for key in ("mountpoint", "library", "emulator_command"):
            if isinstance(data.get(key), str) and (data[key] or key != "mountpoint"):
                setattr(cfg, key, data[key])
        if isinstance(data.get("offsets"), dict):
            cfg.offsets = {str(k): int(v) for k, v in data["offsets"].items()
                           if str(k) in ("A", "B") and isinstance(v, int)}
        if isinstance(data.get("images"), dict):
            cfg.images = {str(k): str(v) for k, v in data["images"].items() if str(k) in SLOTS and v}
        return cfg

    def save(self) -> None:
        os.makedirs(config_dir(), exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)


# -- disk images ---------------------------------------------------------------------
def label_of(sector: bytes) -> str:
    """What the disk calls itself: the maker field of its boot sector, where PC-98 games
    usually put their name and disk number (e.g. "Xak2-No1")."""
    text = sector[3:11].decode("ascii", "replace").strip("\0 ")
    return text if text.isprintable() and text else ""


def disk_label(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return label_of(f.read(16))
    except OSError:
        return ""


RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_name(text: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ ()" else "_" for c in text).strip()
    if not keep:
        return "disk"
    if keep.upper() in RESERVED:            # Windows device names can't be file names
        keep = "disk " + keep
    return keep


def store_image(library: str, image: bytes, label: str, ext: str) -> str:
    """Save an image under the disk's own name, never over a different disk's file."""
    os.makedirs(library, exist_ok=True)
    stem = safe_name(label) if label else time.strftime("disk %Y-%m-%d %H%M")
    path = os.path.join(library, stem + ext)
    n = 2
    while os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == image:
                return path                   # already there
        path = os.path.join(library, f"{stem} ({n}){ext}")
        n += 1
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(image)
    os.replace(tmp, path)
    return path


def list_library(library: str, ext: str) -> List[str]:
    try:
        names = [os.path.basename(p) for p in glob.glob(os.path.join(glob.escape(library), "*" + ext))]
    except OSError:
        return []
    return sorted(names, key=str.lower)


# -- running other programs ------------------------------------------------------------
def external_env() -> Dict[str, str]:
    """The environment for programs that are not ours. The packaged build points
    LD_LIBRARY_PATH at its own bundled libraries, which breaks system programs such as the
    browser or flatpak when they inherit it; hand them the environment we were started with."""
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("_PYI_")]:
        env.pop(key, None)
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        orig = env.pop(var + "_ORIG", None)
        if orig is not None:
            env[var] = orig
        elif FROZEN:
            env.pop(var, None)
    return env


def run_external(cmd: Union[List[str], str]) -> None:
    subprocess.Popen(cmd, env=external_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=(SYSTEM != "Windows"))


def open_in_browser(url: str) -> None:
    try:
        if SYSTEM == "Windows":
            os.startfile(url)  # type: ignore[attr-defined]
        elif SYSTEM == "Darwin":
            run_external(["open", url])
        else:
            run_external(["xdg-open", url])
    except OSError:
        webbrowser.open(url)


def self_command(args: List[str]) -> List[str]:
    """How to run this program again: the frozen executable, or the interpreter on this file."""
    if FROZEN:
        return [sys.executable] + args
    return [sys.executable, os.path.abspath(__file__)] + args


# -- hardware checks (only while nothing owns the board) ----------------------------------
_board_cache: Tuple[float, Optional[str]] = (0.0, None)


def board_port(max_age: float = 3.0) -> Optional[str]:
    """The board's serial port, looked up at most every few seconds: the page asks often."""
    global _board_cache
    when, port = _board_cache
    if time.monotonic() - when < max_age:
        return port
    try:
        from greaseweazle.tools import util
        found: Optional[str] = util.find_port()
    except Exception:
        found = None
    _board_cache = (time.monotonic(), found)
    return found


def driver_check() -> Tuple[bool, str]:
    """Can the FUSE layer be loaded? Decided once per start: installing it means restarting."""
    try:
        import mfusepy  # noqa: F401
        return True, "ok"
    except Exception as e:
        return False, str(e)


def driver_hint() -> str:
    if SYSTEM == "Windows":
        return "Install WinFsp from https://winfsp.dev/rel/ and start this program again."
    if SYSTEM == "Darwin":
        return "Install FUSE-T from https://www.fuse-t.org/ (or macFUSE) and start this program again."
    return "Install your distribution's fuse3 package (the fusermount3 command) and start this program again."


def probe_drives(cfg: Config) -> Dict[str, Dict[str, Any]]:
    """Disk present and write-protect state of both drives, by letter."""
    from floppy_drive import GwBackend, GwBoard
    out: Dict[str, Dict[str, Any]] = {}
    with GwBoard() as board:
        for letter in ("A", "B"):
            with GwBackend(letter, cfg.format, board, cfg.offsets.get(letter, 0)) as be:
                out[letter] = {"disk": be.has_disk(), "protected": be.write_protected()}
    return out


# -- the bridge as a child process ------------------------------------------------
class Bridge:
    def __init__(self, note: Callable[[str], None]) -> None:
        self.proc: Optional[subprocess.Popen[str]] = None
        self.note = note
        self.lines = 0                       # every line ever read: progress, for stop()
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
            args = ["--bridge", "--control-stdin", "--format", cfg.format, "--mountpoint", cfg.mountpoint,
                    "--fd1", cfg.left or "none", "--fd2", cfg.right or "none"]
            for letter, n in cfg.offsets.items():
                if n:
                    args += ["--offset", f"{letter}={n}"]
            for name, path in cfg.images.items():
                args += ["--image", f"{name}={path}"]
            self.slots = {}
            self.error = ""
            self.ready = False
            self.proc = subprocess.Popen(self_command(args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, bufsize=1,
                                         encoding="utf-8", errors="replace")
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
            return "starting"

    def _reader(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            self.lines += 1
            if not line.startswith("STATUS "):
                log.info("bridge: %s", line)       # a traceback or a library warning
                continue
            line = line[7:]
            try:
                self._parse(line)
            except Exception:
                log.exception("bridge line not understood: %r", line)
            if not line.startswith("slot "):
                self.note(line)
        code = proc.wait()
        self.ready = False
        if code != 0 and not self.error:
            self.error = f"the bridge stopped with code {code}"
        self.note("bridge exited")

    def _parse(self, line: str) -> None:
        if line == "ready":
            self.ready = True
        elif line.startswith("error "):
            self.error = line[6:]
        elif line.startswith("slot "):                 # "slot FD1 disk=1 protected=0"
            parts = line.split()
            fields = dict(p.split("=", 1) for p in parts[2:])
            self.slots[parts[1]] = {"disk": fields.get("disk") == "1", "protected": fields.get("protected") == "1"}

    def stop(self, mountpoint: str) -> str:
        """Ask the bridge to stop and wait while it is still saving; it prints progress for
        every track written, so only silence means it is stuck."""
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
            if self._wait_while_busy(proc):
                return "stopped"
            unmount(mountpoint)                 # the system's unmount also makes it write and exit
            if self._wait_while_busy(proc):
                return "stopped"
            proc.kill()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                return "the bridge did not stop; anything unsaved may be lost"
            return "stopped by force; anything unsaved may be lost"

    def _wait_while_busy(self, proc: "subprocess.Popen[str]") -> bool:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            seen = self.lines
            try:
                proc.wait(20)
                return True
            except subprocess.TimeoutExpired:
                if self.lines == seen:
                    return False                # nothing for 20 s: it isn't saving, it's stuck
        return False


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
                    r"C:\RetroArch-Win64\retroarch.exe", r"C:\RetroArch\retroarch.exe",
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


def emulator_command(cfg: Config) -> Union[List[str], str, None]:
    """What to run: the user's own command with the files filled in (a string on Windows, where
    the system parses command lines itself), RetroArch's command, or None if nothing is known."""
    play = cmd_path(cfg.mountpoint, "play.cmd")
    fd1 = cmd_path(cfg.mountpoint, "FD1" + EXT[cfg.format])
    fd2 = cmd_path(cfg.mountpoint, "FD2" + EXT[cfg.format])
    custom = cfg.emulator_command.strip()
    if custom:
        filled = custom.replace("{play}", play).replace("{fd1}", fd1).replace("{fd2}", fd2)
        if SYSTEM == "Windows":
            return filled
        import shlex
        return shlex.split(filled)
    found = find_retroarch()
    if not found:
        return None
    prefix, core = found
    return prefix + ["-L", core, play]


def launch_emulator(cfg: Config) -> str:
    try:
        cmd = emulator_command(cfg)
    except ValueError as e:
        return f"the emulator command can't be read: {e}"
    if cmd is None:
        return "RetroArch with the Neko Project II kai core was not found; open the two files in your emulator"
    try:
        run_external(cmd)
    except OSError as e:
        return f"couldn't start the emulator: {e}"
    return "emulator started"


# -- the local web app ----------------------------------------------------------------
class Station:
    def __init__(self) -> None:
        self.cfg = Config.load()
        self.events: Deque[str] = collections.deque(maxlen=60)
        self.bridge = Bridge(self.note)
        self.token = secrets.token_urlsafe(16)
        self.driver_ok, self.driver_msg = driver_check()
        self.probe: Dict[str, Dict[str, Any]] = {}
        self.probe_error = ""
        self.probing = False
        self.message = ""
        self.last_seen = 0.0           # when the page last asked for the state
        self.seen_once = False
        self.page_gone = 0.0           # when the page said goodbye (window closed)
        self.job: Dict[str, Any] = {}  # the backup in progress, or the last one
        self.lock = threading.RLock()  # one action at a time

    def note(self, msg: str) -> None:
        self.events.append(time.strftime("%H:%M:%S ") + msg)

    @property
    def library(self) -> str:
        return self.cfg.library or default_library()

    @property
    def all_images(self) -> bool:
        return all(self.cfg.images.get(n) for n in SLOTS)

    @property
    def running(self) -> bool:
        return self.bridge.running

    @property
    def backing_up(self) -> bool:
        return bool(self.job) and not self.job.get("done", False)

    @property
    def busy(self) -> bool:
        """Something owns the board: the bridge, a backup, or a probe."""
        return self.running or self.backing_up or self.probing

    def refresh_probe(self) -> None:
        with self.lock:                        # a probe owns the board; nothing starts meanwhile
            if self.running or self.backing_up:
                return
            self.probing = True
            try:
                self.probe = probe_drives(self.cfg)
                self.probe_error = ""
            except Exception as e:
                self.probe = {}
                self.probe_error = str(e)
            finally:
                self.probing = False

    def state(self) -> Dict[str, Any]:
        self.last_seen = time.monotonic()
        self.seen_once = True
        if self.message == "starting" and self.bridge.ready:
            self.message = "running"
        cfg = self.cfg
        ext = EXT[cfg.format]
        board = None if self.busy else board_port()
        drives: Dict[str, Any] = {}
        for name in SLOTS:
            letter = cfg.letter(name)
            image = cfg.images.get(name, "")
            info: Dict[str, Any] = {"drive": letter, "side": "left" if name == "FD1" else "right",
                                    "file": cmd_path(cfg.mountpoint, name + ext),
                                    "image": image, "image_name": os.path.basename(image) if image else ""}
            if image:
                present = os.path.isfile(image)
                info.update({"disk": present, "protected": present and not os.access(image, os.W_OK),
                             "label": disk_label(image) if present else ""})
            elif self.running:
                info.update(self.bridge.slots.get(name, {}))
                if self.bridge.ready and info.get("disk"):
                    info["label"] = disk_label(str(info["file"]))
            elif letter in self.probe:
                info.update(self.probe[letter])
            drives[name] = info
        emu = find_retroarch()
        return {
            "app": APP_NAME, "version": VERSION, "system": SYSTEM,
            "board": {"present": self.busy or board is not None, "port": board},
            "driver": {"ok": self.driver_ok, "hint": "" if self.driver_ok else driver_hint(), "detail": self.driver_msg},
            "running": self.running, "busy": self.busy, "ready": self.bridge.ready, "error": self.bridge.error,
            "identified": cfg.left in ("A", "B"), "all_images": self.all_images,
            "mountpoint": cfg.mountpoint, "play": cmd_path(cfg.mountpoint, "play.cmd"),
            "drives": drives, "probe_error": self.probe_error,
            "library": {"folder": self.library, "images": list_library(self.library, ext)},
            "emulator": {"found": emu is not None, "custom": bool(cfg.emulator_command.strip()),
                         "name": "RetroArch, Neko Project II kai core" if emu else ""},
            "log": list(self.events), "message": self.message, "job": self.job,
            "config": asdict(cfg),
        }

    # actions
    def start(self) -> str:
        with self.lock:
            if self.running:
                return "already running"
            if self.backing_up:
                return "wait for the backup to finish"
            if not self.driver_ok:
                return driver_hint()
            for name in SLOTS:
                img = self.cfg.images.get(name)
                if img and not os.path.isfile(img):
                    return f"{name}: the image {os.path.basename(img)} is missing"
            if not self.all_images:
                if not self.cfg.left:
                    return "identify the left drive first"
                if not board_port(0):
                    return "the Greaseweazle isn't connected"
            self.events.clear()
            self.probe = {}
            return self.bridge.start(self.cfg)

    def stop(self) -> str:
        with self.lock:
            msg = self.bridge.stop(self.cfg.mountpoint)
        self.refresh_probe()
        return msg

    def identify(self) -> str:
        """The user has put a disk in the LEFT drive only: whichever unit holds a disk is left."""
        with self.lock:
            if self.busy:
                return "stop first" if self.running else "wait for the backup to finish"
            try:
                probe = probe_drives(self.cfg)
            except Exception as e:
                return f"couldn't talk to the drives: {e}"
            self.probe = probe
            with_disk = [k for k, v in probe.items() if v["disk"]]
            if len(with_disk) != 1:
                return "no disk found" if not with_disk else "both drives hold a disk; leave only the left one in"
            self.cfg.left = with_disk[0]
            self.cfg.save()
            return f"the left drive is unit {self.cfg.left}; the right one is {self.cfg.right}"

    def settings(self, data: Dict[str, Any]) -> str:
        """Check everything first, then apply, then save: a refused change changes nothing."""
        with self.lock:
            changes: Dict[str, Any] = {}
            if "emulator_command" in data:
                changes["emulator_command"] = str(data["emulator_command"])
            if data.get("swap"):
                if self.running:
                    return "stop before swapping the drives"
                changes["left"] = self.cfg.right
            images = dict(self.cfg.images)
            if isinstance(data.get("image"), dict):
                if self.running:
                    return "stop before changing what a drive plays from"
                for name, value in data["image"].items():
                    if name not in SLOTS:
                        continue
                    value = str(value or "")
                    if value and not os.path.isabs(value):
                        value = os.path.join(self.library, value)
                    if value and not os.path.isfile(value):
                        return f"{os.path.basename(value)} isn't in the library"
                    if value:
                        images[name] = value
                    else:
                        images.pop(name, None)
                paths = [os.path.realpath(p) for p in images.values()]
                if len(paths) != len(set(paths)):
                    return "both drives can't play from the same image"
            for key, value in changes.items():
                setattr(self.cfg, key, value)
            self.cfg.images = images
            self.cfg.save()
            return "saved"

    def backup(self, name: str) -> str:
        """Read the whole disk in FD1 or FD2 into an image file, once, track by track."""
        with self.lock:
            if name not in SLOTS:
                return "unknown drive"
            if self.cfg.images.get(name):
                return f"{name} is playing from an image already"
            if self.running:
                return "stop first"
            if self.backing_up:
                return "a backup is already running"
            letter = self.cfg.letter(name)
            if letter not in ("A", "B"):
                return "identify the left drive first"
            self.job = {"name": name, "track": 0, "total": 0, "bad": [], "done": False, "error": "", "file": ""}
            threading.Thread(target=self._backup_worker, args=(name, letter), daemon=True).start()
            return "backing up " + name

    def _backup_worker(self, name: str, letter: str) -> None:
        from floppy_drive import GwBackend, GwBoard
        job = self.job
        ext = EXT[self.cfg.format]
        try:
            with GwBoard() as board, GwBackend(letter, self.cfg.format, board, self.cfg.offsets.get(letter, 0)) as be:
                be.READ_ATTEMPTS = 2            # an original gets few passes; the image shows what was weak
                if not be.has_disk():
                    raise RuntimeError("no disk in the drive")
                job["total"] = be.cyls * be.heads
                chunks: List[bytes] = []
                label = ""
                for cyl in range(be.cyls):
                    for head in range(be.heads):
                        data = be.read_track(cyl, head)
                        if data is None:
                            if be.disk_changed():
                                raise RuntimeError("the disk was changed during the backup; nothing saved")
                            job["bad"].append(f"{cyl}.{head}")
                            data = b"\0" * be.track_bytes
                        if cyl == 0 and head == 0:
                            label = label_of(data)
                        chunks.append(data)
                        job["track"] = cyl * be.heads + head + 1
                if be.disk_changed():
                    raise RuntimeError("the disk was changed during the backup; nothing saved")
                bad = len(job["bad"])
                stem = (label or "disk") + (f" ({bad} unreadable tracks)" if bad else "")
                path = store_image(self.library, b"".join(chunks), stem, ext)
                job["file"] = path
                self.note(f"{name}: saved {os.path.basename(path)}" + (f", {bad} track(s) unreadable" if bad else ""))
        except Exception as e:
            job["error"] = str(e)
            self.note(f"{name}: backup failed: {e}")
        job["done"] = True
        self.refresh_probe()


def make_handler(st: Station, port: int) -> type:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 10                          # a stalled client can't park a thread for good

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
            full = os.path.realpath(os.path.join(STATIC, path))
            try:
                inside = os.path.commonpath([full, STATIC]) == STATIC
            except ValueError:               # different drives on Windows
                inside = False
            if not inside or not os.path.isfile(full):
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

        def _host_ok(self) -> bool:
            # A page on another site can't read our answers, but with a rebinding trick it could
            # pretend to be us; only accept requests addressed to this machine by name.
            if self.headers.get("Host", "") in allowed_hosts:
                return True
            self.send_error(421)
            return False

        def _token_ok(self, data: Dict[str, Any], allow_body: bool) -> bool:
            given = self.headers.get("X-Token") or (str(data.get("token", "")) if allow_body else "")
            return bool(given) and secrets.compare_digest(given, st.token)

        def do_GET(self) -> None:
            try:
                if not self._host_ok():
                    return
                path = urlparse(self.path).path
                if path == "/":
                    self._file("index.html", subst=True)
                elif path.startswith("/static/"):
                    self._file(path[len("/static/"):])
                elif path == "/api/ping":
                    self._json({"app": APP_NAME, "version": VERSION})
                elif path == "/api/state":
                    if not self._token_ok({}, False):
                        self.send_error(403)
                        return
                    self._json(st.state())
                else:
                    self.send_error(404)
            except (BrokenPipeError, ConnectionResetError):
                return                         # the page reloaded mid-answer
            except Exception:
                log.exception("GET %s failed", self.path)
                self.send_error(500)

        def do_POST(self) -> None:
            try:
                if not self._host_ok():
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = 0
                if n < 0 or n > MAX_BODY:
                    self.send_error(413)
                    return
                raw = self.rfile.read(n) if n else b""
                try:
                    parsed = json.loads(raw or b"{}")
                except ValueError:
                    parsed = {}
                data: Dict[str, Any] = parsed if isinstance(parsed, dict) else {}
                path = urlparse(self.path).path
                if not self._token_ok(data, allow_body=(path == "/api/bye")):
                    self.send_error(403)
                    return
                if path == "/api/bye":                      # sent by the page as it closes
                    st.page_gone = time.monotonic()
                    self._json({"message": "bye"})
                    return
                actions: Dict[str, Callable[[], str]] = {
                    "/api/start": st.start,
                    "/api/stop": st.stop,
                    "/api/identify": st.identify,
                    "/api/launch": lambda: launch_emulator(st.cfg),
                    "/api/backup": lambda: st.backup(str(data.get("name", ""))),
                    "/api/settings": lambda: st.settings(data),
                }
                if path == "/api/probe":
                    if st.busy:
                        st.message = "busy"
                    else:
                        st.refresh_probe()
                        st.message = st.probe_error or "drives checked"
                elif path in actions:
                    st.message = actions[path]()
                else:
                    self.send_error(404)
                    return
                self._json({"message": st.message})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                log.exception("POST %s failed", self.path)
                self.send_error(500)
    return Handler


# -- the window -----------------------------------------------------------------------
def existing_instance() -> Optional[str]:
    """The address of a Floppy Station already running on this machine, if any."""
    import urllib.request
    url = f"http://127.0.0.1:{PORT}/"
    try:
        with urllib.request.urlopen(url + "api/ping", timeout=2) as r:
            data = json.loads(r.read())
        return url if data.get("app") == APP_NAME else None
    except Exception:
        return None


def app_mode_browser() -> Optional[List[str]]:
    """A Chromium-family browser that can open a page as a plain window, without tabs or bars."""
    home = os.path.expanduser("~")
    names = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser",
             "brave", "microsoft-edge", "microsoft-edge-stable", "vivaldi"]
    if SYSTEM == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.join(local, r"Google\Chrome\Application\chrome.exe")):
            if os.path.isfile(exe):
                return [exe]
    elif SYSTEM == "Darwin":
        for app in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    "/Applications/Chromium.app/Contents/MacOS/Chromium",
                    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"):
            if os.path.isfile(app):
                return [app]
    for n in names:
        found = shutil.which(n)
        if found:
            return [found]
    if SYSTEM == "Linux" and shutil.which("flatpak"):
        for fid in ("com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser", "com.microsoft.Edge"):
            for base in (os.path.join(home, ".local/share/flatpak/app"), "/var/lib/flatpak/app"):
                if os.path.isdir(os.path.join(base, fid)):
                    return ["flatpak", "run", fid]
    return None


def linux_desktop_entry() -> None:
    """Make the window ours in the task bar on Linux. The window is a browser's, so the
    desktop would file it under the browser's icon; a desktop entry with our icon and, on
    KDE, a window rule matching the window's title give it its own entry. Idempotent."""
    if SYSTEM != "Linux":
        return
    home = os.path.expanduser("~")
    try:
        apps = os.path.join(home, ".local/share/applications")
        icons = os.path.join(home, ".local/share/icons/hicolor/256x256/apps")
        os.makedirs(apps, exist_ok=True)
        os.makedirs(icons, exist_ok=True)
        shutil.copyfile(os.path.join(HERE, "icon.png"), os.path.join(icons, "pc98-floppy-station.png"))
        # inside an AppImage the running file is a temporary mount; the entry must name the AppImage
        appimage = os.environ.get("APPIMAGE")
        exe = f'"{appimage}"' if appimage else " ".join(f'"{a}"' for a in self_command([]))
        with open(os.path.join(apps, "pc98-floppy-station.desktop"), "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\nName=PC-98 Floppy Station\n"
                    "Comment=Play PC-98 games from the real floppy drives\n"
                    f"Exec={exe}\nIcon=pc98-floppy-station\nTerminal=false\nCategories=Game;Emulator;\n"
                    "StartupWMClass=pc98-floppy-station\n")
    except Exception as e:
        log.info("desktop entry not installed: %s", e)
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
        return
    try:
        import configparser
        path = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config")), "kwinrulesrc")
        c = configparser.RawConfigParser()
        c.optionxform = str  # type: ignore[assignment]
        c.read(path, encoding="utf-8")
        key = "pc98-floppy-station"
        if c.has_section(key):
            return
        if not c.has_section("General"):
            c.add_section("General")
        rules = [r for r in c.get("General", "rules", fallback="").split(",") if r] + [key]
        c.set("General", "rules", ",".join(rules))
        c.set("General", "count", str(len(rules)))
        c.add_section(key)
        for k, v in (("Description", "PC-98 Floppy Station window"), ("title", APP_NAME),
                     ("titlematch", "1"), ("desktopfile", key), ("desktopfilerule", "2")):
            c.set(key, k, v)
        with open(path, "w", encoding="utf-8") as f:
            c.write(f, space_around_delimiters=False)
        for tool in ("qdbus6", "qdbus-qt6", "qdbus"):
            if shutil.which(tool):
                subprocess.run([tool, "org.kde.KWin", "/KWin", "reconfigure"], check=False, env=external_env(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                break
    except Exception as e:
        log.info("window rule not installed: %s", e)


def open_window(url: str) -> None:
    """A bare browser window where a Chromium-family browser exists, otherwise a browser tab."""
    cmd = app_mode_browser()
    if cmd:
        linux_desktop_entry()
        try:
            run_external(cmd + [f"--app={url}", "--window-size=1040,980"])
            return
        except OSError:
            pass
    open_in_browser(url)


def serve(show_window: bool) -> int:
    st = Station()
    threading.Thread(target=st.refresh_probe, daemon=True).start()
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(st, PORT))
    except OSError:
        running = existing_instance()
        if running and show_window:            # one program, one window: just show it again
            open_window(running)
            return 0
        print(f"{APP_NAME}: port {PORT} is in use" + (" by another copy of this program" if running else ""))
        return 1
    url = f"http://127.0.0.1:{PORT}/"
    print(f"{APP_NAME}: {url}", flush=True)
    log.info("serving %s", url)
    if show_window:
        open_window(url)

    def watch_page() -> None:
        # The page asks for the state every second and says goodbye as it closes; a reload
        # also says goodbye but polls again at once, so goodbye counts only after a short
        # grace, longer while the drives are in use. A page that just falls silent (a browser
        # slows a hidden tab right down) ends the program only when nothing is running.
        while True:
            time.sleep(0.5)
            now = time.monotonic()
            grace = 3.0 if st.running else 1.2
            said_bye = st.page_gone and now - st.page_gone > grace and st.last_seen < st.page_gone
            quiet = st.seen_once and now - st.last_seen > 150 and not st.busy
            if (said_bye or quiet) and not st.backing_up:
                httpd.shutdown()
                return
    threading.Thread(target=watch_page, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if st.running:
            st.stop()                          # writes anything pending first
    return 0


def setup_logging() -> None:
    """A log file in the settings folder: the packaged program has no console to print to."""
    try:
        os.makedirs(config_dir(), exist_ok=True)
        logging.basicConfig(filename=os.path.join(config_dir(), "station.log"), level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO)

    def hook(exc_type: Any, exc: Any, tb: Any) -> None:
        log.error("uncaught: %s", "".join(traceback.format_exception(exc_type, exc, tb)))
    sys.excepthook = hook


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--bridge"]:
        for stream in (sys.stdout, sys.stderr):   # the parent reads UTF-8 whatever the system code page
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        import floppy_bridge                  # needs the FUSE driver; the window itself doesn't
        return floppy_bridge.main(args[1:])
    setup_logging()
    return serve(show_window="--no-browser" not in args)


if __name__ == "__main__":
    sys.exit(main())
