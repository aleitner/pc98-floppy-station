"""Show the real floppy drives as disk-image files, so an emulator plays straight from them.

  floppy_bridge.py                          left drive = FD1.hdm, right drive = FD2.hdm
  floppy_bridge.py --fd1 A --fd2 none       one drive only
  floppy_bridge.py --offset B=4             drive B's real track 0 is 4 steps in
  floppy_bridge.py --image FD1=a.hdm --image FD2=b.hdm --mountpoint /tmp/m     (testing)

The files appear in a folder (a drive letter on Windows) along with play.cmd, which
loads both drives in RetroArch's Neko Project II kai core. Every read goes to the disk
a track at a time; every write is put on the disk about a second after the game stops
writing, and verified. Swap a disk by opening the lever and changing it: the bridge sees
the change and drops what it remembers of the old disk.

Use copy disks, not originals. Playing reads the disk over and over, and a weak track
is retried.

Runs until unmounted (Linux: fusermount3 -u FOLDER; elsewhere Ctrl-C), then writes any
remaining changes and exits. Works through FUSE: built in on Linux, WinFsp on Windows,
macFUSE or FUSE-T on a Mac. Progress goes to stdout as lines starting with "STATUS ".
"""
from __future__ import annotations

import argparse
import errno
import os
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar

import mfusepy

from bridge_paths import EXT, GEOMETRY, SYSTEM, cmd_path, default_mountpoint
from floppy_drive import Backend, DiskError, GwBackend, GwBoard, ImageBackend, TrackDisk

QUIET_SECONDS = 1.0       # the game has stopped writing: put it on the disk
POLL_SECONDS = 0.5        # how often to look for a swap while the game is reading
FLUSH_TICK = 0.25
T = TypeVar("T")


def status(msg: str) -> None:
    print("STATUS " + msg, flush=True)


@dataclass
class Slot:
    """One emulated drive: FD1 or FD2."""
    name: str
    backend: Backend
    disk: TrackDisk
    protected: bool = False
    changed_at: float = field(default_factory=time.time)
    polled: float = 0.0


class BridgeFS(mfusepy.Operations):
    use_ns = True

    def __init__(self, slots: Dict[str, Slot], play_cmd: bytes) -> None:
        self.slots = slots                    # keyed by "/FD1.hdm"
        self.play_cmd = play_cmd
        self._oplock = threading.RLock()      # one drive operation at a time: there's one board
        self.uid = getattr(os, "getuid", lambda: 0)()
        self.gid = getattr(os, "getgid", lambda: 0)()
        self.started = time.time()
        self.stop = threading.Event()
        self.quit = threading.Event()         # set by the controller; acted on inside a FUSE call
        self.flusher = threading.Thread(target=self._flush_loop, daemon=True)

    # -- errors: a failed drive operation must never take the mount down ----
    def _run(self, slot: Slot, fn: Callable[[], T]) -> T:
        with self._oplock:
            try:
                self._refresh(slot)
                return fn()
            except mfusepy.FuseOSError:
                raise
            except Exception as e:
                status(f"error {slot.name}: {e}")
                raise mfusepy.FuseOSError(errno.EIO)

    def _slot(self, path: str) -> Slot:
        slot = self.slots.get(path)
        if slot is None:
            raise mfusepy.FuseOSError(errno.ENOENT)
        return slot

    # -- swaps ---------------------------------------------------------------
    def _refresh(self, slot: Slot, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - slot.polled < POLL_SECONDS:
            return
        slot.polled = now
        changed = slot.backend.poll_change()
        if changed:
            lost = slot.disk.new_disk()
            if lost:
                status(f"error {slot.name}: disk changed with {lost} track(s) not yet saved; "
                       "they were NOT written to the new disk")
            slot.changed_at = time.time()
        was = slot.protected
        slot.protected = slot.backend.write_protected()   # pin 28 can settle after the swap
        if changed:
            status(f"{slot.name}: disk changed ({disk_state(slot)})")
        elif slot.protected != was:
            status(f"{slot.name}: now {disk_state(slot)}")

    # -- writing back --------------------------------------------------------
    def _flush_loop(self) -> None:
        while not self.stop.wait(FLUSH_TICK):
            for slot in self.slots.values():
                if slot.disk.dirty_tracks and time.monotonic() - slot.disk.last_write > QUIET_SECONDS:
                    self.flush_now(slot)
                with self._oplock:
                    try:
                        slot.backend.idle()
                    except Exception as e:
                        status(f"error {slot.name}: {e}")

    def flush_now(self, slot: Slot) -> bool:
        with self._oplock:
            n = slot.disk.dirty_tracks
            if not n or slot.disk.broken:
                return not slot.disk.broken
            status(f"{slot.name}: saving {n} track(s)")
            try:
                self._refresh(slot, force=True)      # a swap must never write to the wrong disk
            except Exception as e:
                status(f"error {slot.name}: couldn't check the drive before saving ({e}); will retry")
                return False
            if slot.disk.dirty_tracks == 0:
                status(f"{slot.name}: nothing saved: the disk had been changed")
                return True
            try:
                slot.disk.flush_to_disk()
            except DiskError as e:
                status(f"error {slot.name}: {e.strerror}")
                return False
            except Exception as e:
                slot.disk.broken = str(e)
                status(f"error {slot.name}: {e}")
                return False
            if slot.disk.dirty_tracks == 0:
                status(f"{slot.name}: saved")
            return True

    # -- lifecycle ----------------------------------------------------------
    def init(self, path: str) -> None:
        self.flusher.start()
        status("ready")

    def destroy(self, path: str) -> None:
        self.stop.set()
        ok = all([self.flush_now(s) for s in self.slots.values()])
        status("stopped" if ok else "stopped WITH UNSAVED CHANGES")

    # -- files ---------------------------------------------------------------
    def getattr(self, path: str, fh: Optional[int] = None) -> Dict[str, Any]:
        if self.quit.is_set():
            mfusepy.fuse_exit()               # only valid from inside a FUSE call, hence here
        started = int(self.started * 1e9)             # use_ns: everything in nanoseconds
        base = dict(st_uid=self.uid, st_gid=self.gid, st_atime=started, st_ctime=started)
        if path == "/":
            return dict(base, st_mode=stat.S_IFDIR | 0o755, st_nlink=2, st_size=0, st_mtime=started)
        if path == "/play.cmd":
            return dict(base, st_mode=stat.S_IFREG | 0o444, st_nlink=1, st_size=len(self.play_cmd),
                        st_mtime=started)
        slot = self._slot(path)
        self._run(slot, lambda: None)
        mode = 0o444 if slot.protected else 0o644     # how an emulator learns of the write notch
        return dict(base, st_mode=stat.S_IFREG | mode, st_nlink=1, st_size=slot.disk.size,
                    st_mtime=int(slot.changed_at * 1e9))

    def readdir(self, path: str, fh: int) -> List[str]:
        return [".", "..", "play.cmd"] + [p[1:] for p in self.slots]

    def open(self, path: str, flags: int) -> int:
        if path == "/play.cmd":
            return 0
        slot = self._slot(path)
        self._run(slot, lambda: None)
        if flags & (os.O_WRONLY | os.O_RDWR) and (slot.protected or slot.disk.broken):
            raise mfusepy.FuseOSError(errno.EROFS)
        return 0

    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        if path == "/play.cmd":
            return self.play_cmd[offset:offset + size]
        slot = self._slot(path)

        def go() -> bytes:
            slot.disk.seek(offset)
            return bytes(slot.disk.read(size) or b"")
        return self._run(slot, go)

    def write(self, path: str, data: bytes, offset: int, fh: int) -> int:
        slot = self._slot(path)

        def go() -> int:
            if slot.protected or slot.disk.broken:
                raise mfusepy.FuseOSError(errno.EROFS)
            slot.disk.seek(offset)
            return int(slot.disk.write(data))
        return self._run(slot, go)

    def fsync(self, path: str, datasync: int, fh: int) -> int:
        slot = self.slots.get(path)
        return 0 if slot is None or self.flush_now(slot) else -errno.EIO

    def statfs(self, path: str) -> Dict[str, int]:
        return dict(f_bsize=1024, f_frsize=1024, f_blocks=2464, f_bfree=0, f_bavail=0, f_namemax=255)

    # An image has a fixed size and no owner to change; these only keep programs happy.
    def truncate(self, path: str, length: int, fh: Optional[int] = None) -> None:
        pass

    def utimens(self, path: str, times: Optional[Any] = None) -> None:
        pass

    def chmod(self, path: str, mode: int) -> int:
        return 0

    def chown(self, path: str, uid: int, gid: int) -> int:
        return 0

    def flush(self, path: str, fh: int) -> int:
        return 0

    def release(self, path: str, fh: int) -> int:
        return 0


def slot_logger(name: str) -> Callable[[str], None]:
    def log(msg: str) -> None:
        status(f"{name}: {msg}")
    return log


def disk_state(slot: Slot) -> str:
    if not slot.backend.has_disk():
        return "no disk"
    return "write-protected" if slot.protected else "writable"


def watch_stdin(ops: BridgeFS, mountpoint: str) -> None:
    """Stop when the controlling program says 'stop' or goes away (stdin closes)."""
    for line in sys.stdin:
        if line.strip() == "stop":
            break
    ops.quit.set()
    try:
        os.stat(mountpoint + ("\\" if SYSTEM == "Windows" else ""))   # wakes the FUSE loop
    except OSError:
        pass


def mount_options(name: str) -> Dict[str, Any]:
    """Nothing may be cached by the system: after a swap the same file holds a different disk."""
    if SYSTEM == "Windows":
        return dict(FileInfoTimeout=0, uid=-1, gid=-1)
    opts: Dict[str, Any] = dict(fsname=name, direct_io=True, attr_timeout=0, entry_timeout=0)
    if SYSTEM == "Darwin":
        opts.update(volname="PC98 Drives", noappledouble=True, noapplexattr=True)
    return opts


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--fd1", default="A", help="drive shown as FD1: A, B or none (default A, the left one)")
    ap.add_argument("--fd2", default="B", help="drive shown as FD2: A, B or none (default B, the right one)")
    ap.add_argument("--format", default="pc98.2hd", choices=sorted(GEOMETRY))
    ap.add_argument("--mountpoint", default=default_mountpoint())
    ap.add_argument("--offset", action="append", default=[], metavar="B=4",
                    help="steps from where a drive thinks track 0 is to the real one")
    ap.add_argument("--port", help="the board's serial port, if it isn't found by itself")
    ap.add_argument("--image", action="append", default=[], metavar="FD1=PATH",
                    help="use an image file instead of a drive (testing)")
    ap.add_argument("--control-stdin", action="store_true",
                    help="stop when 'stop' arrives on stdin or stdin closes (for a controlling program)")
    args = ap.parse_args(argv)

    mountpoint = os.path.abspath(args.mountpoint) if SYSTEM != "Windows" else args.mountpoint
    if " " in mountpoint:
        status("error the emulator's play.cmd can't handle spaces; choose a folder without any")
        return 2
    if SYSTEM != "Windows":
        os.makedirs(mountpoint, exist_ok=True)
        if os.listdir(mountpoint):
            status(f"error {mountpoint} isn't empty; is the bridge already running?")
            return 2

    ext = EXT[args.format]
    images = dict(i.split("=", 1) for i in args.image)
    wanted = {"FD1": args.fd1.upper(), "FD2": args.fd2.upper()}
    board: Optional[GwBoard] = None
    slots: Dict[str, Slot] = {}
    try:
        # Each slot is a drive or an image file; they can be mixed.
        cyls, heads, tb = GEOMETRY[args.format]
        offsets = {d.upper(): int(n) for d, n in (o.split("=", 1) for o in args.offset)}
        backends: Dict[str, Backend] = {}
        for name in ("FD1", "FD2"):
            if name in images:
                img = ImageBackend(images[name], cyls, heads, tb)
                img.readonly = not os.access(images[name], os.W_OK)
                backends[name] = img
            elif wanted[name] != "NONE":
                if board is None:
                    board = GwBoard(args.port)
                backends[name] = GwBackend(wanted[name], args.format, board=board,
                                           cyl_offset=offsets.get(wanted[name], 0))
        for name, backend in backends.items():
            slot = Slot(name, backend, TrackDisk(backend, log=slot_logger(name)))
            slot.protected = backend.write_protected()
            slots[f"/{name}{ext}"] = slot
            where = images.get(name) or f"drive {wanted[name]}"
            state = "no disk" if not backend.has_disk() else \
                "write-protected" if slot.protected else "writable"
            status(f"{name}{ext} is {where} ({state})")
    except Exception as e:
        status(f"error can't open the drives: {e}")
        return 2

    names = " ".join(cmd_path(mountpoint, p[1:]) for p in slots)
    ops = BridgeFS(slots, f"np2kai {names}\n".encode())
    status(f"load {cmd_path(mountpoint, 'play.cmd')} in RetroArch with the Neko Project II kai core")
    if args.control_stdin:
        threading.Thread(target=watch_stdin, args=(ops, mountpoint), daemon=True).start()
    try:
        mfusepy.FUSE(ops, mountpoint, foreground=True, nothreads=True, **mount_options("pc98drives"))
    except Exception as e:
        status(f"error couldn't mount {mountpoint}: {e}")
        return 2
    finally:
        for s in slots.values():
            s.backend.close()
        if board:
            board.close()
    return 0 if not any(s.disk.broken for s in slots.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
