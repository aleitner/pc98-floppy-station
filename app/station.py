"""PC-98 Floppy Station: a window for the floppy bridge, no command line needed.

Double-click it (or run `python3 station.py`). A window shows the Greaseweazle and both
drives, Start/Stop, the two image files an emulator opens, and a Play button when
RetroArch with the PC-98 core is installed. Each drive can be backed up to an image file,
and a backup can stand in for a drive: then the game plays from that file instead.

The bridge itself runs as a child process (floppy_bridge.py), so a drive fault can never
take the window down. Settings live in the user's config folder.

    station.py                 open the window (its own window where the system allows,
                               otherwise a bare browser window, otherwise a browser tab)
    station.py --no-browser    serve only; open http://127.0.0.1:9801 yourself
    station.py --bridge ...    run the bridge (used internally when packaged)
"""
from __future__ import annotations

import collections
import glob
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
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from bridge_paths import EXT, cmd_path, default_mountpoint

SYSTEM = platform.system()
PORT = 9801
APP_NAME = "PC-98 Floppy Station"
VERSION = "0.2.0"
FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "static")
SLOTS = ("FD1", "FD2")

WINFSP_URL = "https://winfsp.dev/rel/"
FUSET_URL = "https://www.fuse-t.org/"


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
    base = docs if os.path.isdir(docs) else os.path.expanduser("~")
    return os.path.join(base, "PC98 Floppies")


@dataclass
class Config:
    left: str = ""                 # "A" or "B": which drive is the left one; "" = not yet identified
    format: str = "pc98.2hd"
    mountpoint: str = field(default_factory=default_mountpoint)   # where the bridge puts the files
    library: str = ""              # where backups live; "" = Documents/PC98 Floppies
    offsets: Dict[str, int] = field(default_factory=dict)
    emulator_command: str = ""     # custom launch command with {play} {fd1} {fd2}; "" = find RetroArch
    images: Dict[str, str] = field(default_factory=dict)   # FD1/FD2 -> image file standing in for the drive

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


def safe_name(text: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ " else "_" for c in text).strip()
    return keep or "disk"


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


# -- hardware checks (only while nothing is running: the bridge owns the board) ------
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
            args = ["--bridge", "--control-stdin", "--format", cfg.format, "--mountpoint", cfg.mountpoint,
                    "--fd1", cfg.left or "none", "--fd2", cfg.right or "none"]
            for letter, n in cfg.offsets.items():
                if n:
                    args += ["--offset", f"{letter}={n}"]
            for name, path in cfg.images.items():
                if path:
                    args += ["--image", f"{name}={path}"]
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
        elif " is drive " in line or " is /" in line or (" is " in line and "(" in line and line.startswith("FD")):
            # "FD1.hdm is drive A (writable)"  or  "FD1.hdm is /path/to/image.hdm (write-protected)"
            name = line.split(".", 1)[0]
            state = line.rsplit("(", 1)[1].rstrip(")")
            self.slots[name] = {"disk": state != "no disk", "protected": state == "write-protected"}
        elif ": disk changed (" in line or ": now " in line:
            name = line.split(":", 1)[0]
            state = line.rsplit("(", 1)[1].rstrip(")") if "(" in line else line.rsplit(" now ", 1)[1]
            slot = self.slots.setdefault(name, {})
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


# -- playing from image files only: plain files, no driver -------------------------------
def files_folder() -> str:
    return os.path.expanduser("~/PC98Drives")


class ImagePlay:
    """Both drives stand in as images: put the two files where the emulator looks, as links
    where the system allows and copies otherwise, so no driver is involved at all."""

    def __init__(self, cfg: Config, log: Callable[[str], None]) -> None:
        self.cfg = cfg
        self.log = log
        self.folder = files_folder()
        self.copies: Dict[str, str] = {}      # target -> source, for files that had to be copied
        self.active = False

    def start(self) -> str:
        ext = EXT[self.cfg.format]
        os.makedirs(self.folder, exist_ok=True)
        for name in SLOTS:
            src = self.cfg.images.get(name, "")
            target = os.path.join(self.folder, name + ext)
            self._remove(target)
            if not src:
                continue
            if not os.path.isfile(src):
                return f"{name}: the image {src} doesn't exist"
            try:
                if SYSTEM == "Windows":
                    os.link(src, target)
                else:
                    os.symlink(os.path.abspath(src), target)
            except OSError:
                shutil.copy2(src, target)
                self.copies[target] = src
            self.log(f"{name}: {os.path.basename(src)}" +
                     (" (write-protected)" if not os.access(src, os.W_OK) else ""))
        names = " ".join(cmd_path(self.folder, n + ext) for n in SLOTS if self.cfg.images.get(n))
        with open(os.path.join(self.folder, "play.cmd"), "w") as f:
            f.write(f"np2kai {names}\n")
        self.active = True
        self.log("ready")
        return "starting"

    def stop(self) -> str:
        ext = EXT[self.cfg.format]
        for target, src in self.copies.items():
            try:
                if os.access(src, os.W_OK) and open(target, "rb").read() != open(src, "rb").read():
                    shutil.copy2(target, src)
                    self.log(f"{os.path.basename(src)} updated with the game's changes")
            except OSError as e:
                self.log(f"error couldn't write back to {src}: {e}")
        for name in SLOTS:
            self._remove(os.path.join(self.folder, name + ext))
        self._remove(os.path.join(self.folder, "play.cmd"))
        self.copies = {}
        self.active = False
        return "stopped"

    @staticmethod
    def _remove(path: str) -> None:
        try:
            if os.path.lexists(path):
                os.remove(path)
        except OSError:
            pass


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


def launch_emulator(cfg: Config, where: str) -> str:
    play = cmd_path(where, "play.cmd")
    ext = EXT[cfg.format]
    fd1 = cmd_path(where, "FD1" + ext)
    fd2 = cmd_path(where, "FD2" + ext)
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
        self.files: Optional[ImagePlay] = None
        self.token = secrets.token_urlsafe(16)
        self.driver_ok, self.driver_msg = driver_check()
        self.probe: Dict[str, Dict[str, Any]] = {}
        self.probe_error = ""
        self.message = ""
        self.last_seen = 0.0           # when the page last asked for the state
        self.seen_once = False
        self.page_gone = 0.0           # when the page said goodbye (window closed)
        self.job: Dict[str, Any] = {}  # the backup in progress, or the last one
        self.events: Deque[str] = collections.deque(maxlen=60)

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
        return self.bridge.running or self.files is not None

    @property
    def ready(self) -> bool:
        return self.files is not None or self.bridge.ready

    @property
    def where(self) -> str:
        return files_folder() if self.files is not None else self.cfg.mountpoint

    def refresh_probe(self) -> None:
        if self.running:
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
        if self.message == "starting" and self.ready:
            self.message = "running"
        cfg = self.cfg
        ext = EXT[cfg.format]
        board = None if self.running else board_port()
        where = self.where
        drives: Dict[str, Any] = {}
        for name in SLOTS:
            letter = cfg.letter(name)
            image = cfg.images.get(name, "")
            info: Dict[str, Any] = {"drive": letter, "side": "left" if name == "FD1" else "right",
                                    "file": cmd_path(where, name + ext),
                                    "image": image, "image_name": os.path.basename(image) if image else ""}
            if image:
                info.update({"disk": os.path.isfile(image), "protected": not os.access(image, os.W_OK),
                             "label": disk_label(image)})
            elif self.bridge.running:
                info.update(self.bridge.slots.get(name, {}))
                if self.bridge.ready and info.get("disk"):
                    info["label"] = disk_label(str(info["file"]))
            elif letter in self.probe:
                info.update(self.probe[letter])
            drives[name] = info
        emu = find_retroarch()
        needs_driver = not self.all_images
        return {
            "app": APP_NAME, "version": VERSION, "system": SYSTEM,
            "board": {"present": self.running or board is not None, "port": board},
            "driver": {"ok": self.driver_ok, "needed": needs_driver,
                       "hint": "" if self.driver_ok else driver_hint(), "detail": self.driver_msg},
            "running": self.running, "ready": self.ready, "error": self.bridge.error if self.files is None else "",
            "identified": cfg.left in ("A", "B"),
            "mountpoint": where, "play": cmd_path(where, "play.cmd"),
            "drives": drives, "probe_error": self.probe_error,
            "library": {"folder": self.library, "images": list_library(self.library, ext)},
            "emulator": {"found": emu is not None, "custom": bool(cfg.emulator_command.strip()),
                         "name": "RetroArch, Neko Project II kai core" if emu else ""},
            "log": sorted(list(self.bridge.log) + list(self.events))[-60:], "message": self.message,
            "job": self.job,
            "config": asdict(cfg),
        }

    # actions
    def start(self) -> str:
        if self.running:
            return "already running"
        for name in SLOTS:
            img = self.cfg.images.get(name)
            if img and not os.path.isfile(img):
                return f"{name}: the image {os.path.basename(img)} is missing"
        self.events.clear()
        if self.all_images:
            self.files = ImagePlay(self.cfg, self.note)
            msg = self.files.start()
            if msg != "starting":
                self.files.stop()
                self.files = None
            return msg
        if not self.cfg.left:
            return "identify the left drive first"
        if not self.driver_ok:
            return driver_hint()
        if not board_port():
            return "the Greaseweazle isn't connected"
        self.probe = {}
        return self.bridge.start(self.cfg)

    def stop(self) -> str:
        if self.files is not None:
            msg = self.files.stop()
            self.files = None
        else:
            msg = self.bridge.stop(self.cfg.mountpoint)
        self.refresh_probe()
        return msg

    def identify(self) -> Dict[str, Any]:
        """The user has put a disk in the LEFT drive only: whichever unit holds a disk is left."""
        if self.running:
            return {"ok": False, "message": "stop first"}
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
        if "format" in data and data["format"] in EXT:
            self.cfg.format = str(data["format"])
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
                    self.cfg.images[name] = value
                else:
                    self.cfg.images.pop(name, None)
        self.cfg.save()
        return "saved"

    def backup(self, name: str) -> str:
        """Read the whole disk in FD1 or FD2 into an image file, once, track by track."""
        if self.cfg.images.get(name):
            return f"{name} is playing from an image already"
        if self.running:
            return "stop first"
        if self.job and not self.job.get("done"):
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
            board = GwBoard(None)
            try:
                be = GwBackend(letter, self.cfg.format, board=board, cyl_offset=self.cfg.offsets.get(letter, 0))
                be.READ_ATTEMPTS = 2            # an original gets few passes; the image shows what was weak
                try:
                    if not be.has_disk():
                        raise RuntimeError("no disk in the drive")
                    total = be.cyls * be.heads
                    job["total"] = total
                    chunks: List[bytes] = []
                    label = ""
                    for cyl in range(be.cyls):
                        for head in range(be.heads):
                            data = be.read_track(cyl, head)
                            if data is None:
                                job["bad"].append(f"{cyl}.{head}")
                                data = b"\0" * be.track_bytes
                            if cyl == 0 and head == 0:
                                label = label_of(data)
                            chunks.append(data)
                            job["track"] = cyl * be.heads + head + 1
                    path = store_image(self.library, b"".join(chunks), label, ext)
                    job["file"] = path
                    bad = len(job["bad"])
                    self.note(f"{name}: saved {os.path.basename(path)}" + (f", {bad} track(s) unreadable" if bad else ""))
                finally:
                    be.close()
            finally:
                board.close()
        except Exception as e:
            job["error"] = str(e)
            self.note(f"{name}: backup failed: {e}")
        job["done"] = True
        self.refresh_probe()


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
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data: Dict[str, Any] = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                data = {}
            if st.token not in (self.headers.get("X-Token"), data.get("token")):
                self.send_error(403)
                return
            path = urlparse(self.path).path
            if path == "/api/bye":                      # sent by the page as it closes
                st.page_gone = time.monotonic()
                self._json({"message": "bye"})
                return
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
                st.message = launch_emulator(st.cfg, st.where)
            elif path == "/api/backup":
                st.message = st.backup(str(data.get("name", "")))
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


# -- the window -----------------------------------------------------------------------
def existing_instance(port: int) -> Optional[str]:
    """The address of a Floppy Station already running on this machine, if any."""
    import urllib.request
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url + "api/state", timeout=2) as r:
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


def open_window(url: str) -> str:
    """Show the page. Best: the system's own web engine in a window of ours (pywebview).
    Next: a Chromium-family browser in app mode, which is a bare window. Last: a browser tab.
    Returns which one happened; "webview" means the caller must run webview.start() itself."""
    try:
        import webview  # noqa: F401
        if SYSTEM != "Linux" or _gtk_webkit_available():
            return "webview"
    except Exception:
        pass
    cmd = app_mode_browser()
    if cmd:
        try:
            subprocess.Popen(cmd + [f"--app={url}", "--window-size=1040,980"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=(SYSTEM != "Windows"))
            return "app"
        except OSError:
            pass
    webbrowser.open(url)
    return "browser"


def _gtk_webkit_available() -> bool:
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import Gtk, WebKit2  # noqa: F401
        return True
    except Exception:
        return False


def make_tray(st: Station, on_open: Callable[[], None], on_quit: Callable[[], None]) -> Optional[Any]:
    """A tray icon with Open / Start or Stop / Play / Quit, where the desktop can show one.
    Windows and desktops with an app-indicator service can; a Wayland desktop without that
    service, such as the Steam Deck's, cannot, and macOS is left to its window for now."""
    if SYSTEM == "Darwin":
        return None
    try:
        import pystray
        from PIL import Image
    except Exception:
        return None
    if pystray.Icon.__module__.endswith("_xorg"):          # legacy tray: modern desktops ignore it
        return None
    try:
        image = Image.open(os.path.join(HERE, "icon.png"))
    except OSError:
        return None

    def toggle(icon: Any, item: Any) -> None:
        st.message = st.stop() if st.running else st.start()

    def play(icon: Any, item: Any) -> None:
        st.message = launch_emulator(st.cfg, st.where)

    menu = pystray.Menu(
        pystray.MenuItem("Open", lambda icon, item: on_open(), default=True),
        pystray.MenuItem(lambda item: "Stop" if st.running else "Start", toggle),
        pystray.MenuItem("Play", play, enabled=lambda item: st.ready),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: on_quit()),
    )
    icon = pystray.Icon("pc98-floppy-station", image, APP_NAME, menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def serve(show: str) -> int:
    """show: 'window' opens the page in a window, 'none' only serves (prints the address)."""
    st = Station()
    threading.Thread(target=st.refresh_probe, daemon=True).start()
    port = free_port(PORT)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(st))
    url = f"http://127.0.0.1:{port}/"
    print(f"{APP_NAME}: {url}", flush=True)
    quitting = threading.Event()

    def finish() -> None:
        if st.running:
            st.stop()

    mode = open_window(url) if show == "window" else "none"
    if mode == "webview":
        import webview
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        window = webview.create_window(APP_NAME, url, width=1040, height=980, background_color="#1414b4")
        assert window is not None

        def quit_webview() -> None:
            quitting.set()
            window.destroy()

        def hide_instead_of_close() -> bool:
            # With a tray, closing the window only hides it; Quit in the tray ends the program.
            if quitting.is_set():
                return True
            window.hide()
            return False

        tray = make_tray(st, window.show, quit_webview)
        if tray:
            window.events.closing += hide_instead_of_close
        webview.start()                       # returns when the window is destroyed
        if tray:
            tray.stop()
        finish()
        httpd.shutdown()
        return 0

    def reopen() -> None:
        open_window(url)

    def quit_server() -> None:
        quitting.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    tray = make_tray(st, reopen, quit_server) if mode != "none" else None

    def watch_page() -> None:
        # The page asks for the state every second and says goodbye when it closes. Without a
        # tray, the program ends when the page has gone and nothing is running. A browser
        # slows a hidden tab's timers right down, so the fallback wait is generous.
        while not tray:
            time.sleep(2)
            if st.running:
                continue
            now = time.monotonic()
            said_bye = st.page_gone and now - st.page_gone > 3 and st.last_seen < st.page_gone
            quiet = st.seen_once and now - st.last_seen > 150
            if said_bye or quiet:
                httpd.shutdown()
                return
    threading.Thread(target=watch_page, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if tray:
            tray.stop()
        finish()
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
    if "--no-browser" in args:
        return serve("none")
    running = existing_instance(PORT)
    if running:                               # one program, one window: just show it again
        if open_window(running) == "webview":
            import webview
            webview.create_window(APP_NAME, running, width=1040, height=980, background_color="#1414b4")
            webview.start()
        return 0
    return serve("window")


if __name__ == "__main__":
    sys.exit(main())
