"""Loaded mode: the drives as ordinary image files, no driver needed.

At start each disk is read in full into memory and written out as a plain file the
emulator opens like any image. From then on the files are watched: when the game writes
a save, the changed tracks are written back to the real floppy, verified, after a quiet
moment. When a disk is swapped, the new one is read in and the file replaced.

A write-protected disk can't have changed since it was last read, so its image is kept
in a cache and only spot-checked, which makes later starts quick. A writable disk is
always read in full: stale save data must never be written back.

The same TrackDisk does the caching, the track-0 write guard, the verified writes and the
swap bookkeeping as in live mode.
"""
from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from bridge_paths import EXT, cmd_path
from floppy_drive import Backend, DiskError, TrackDisk

QUIET_SECONDS = 1.0
POLL_SECONDS = 0.5
SPOT_CHECK = (0, 1, 2)          # cylinders re-read to trust a cached image (plus the last one)


@dataclass
class Loaded:
    """One drive in loaded mode."""
    name: str
    backend: Backend
    disk: TrackDisk
    path: str
    protected: bool = False
    phase: str = "reading"       # reading | ready | swapped | error
    track: int = 0
    total: int = 0
    label: str = ""
    error: str = ""
    mtime: float = 0.0
    image: bytes = b""           # what the file held when we last wrote or read it
    lock: threading.RLock = field(default_factory=threading.RLock)

    def state(self) -> Dict[str, Any]:
        return {"phase": self.phase, "track": self.track, "total": self.total, "label": self.label,
                "error": self.error, "protected": self.protected, "file": self.path}


def label_of(sector: bytes) -> str:
    text = sector[3:11].decode("ascii", "replace").strip("\0 ")
    return text if text.isprintable() and text else ""


class LoadedDrives:
    def __init__(self, folder: str, fmt: str, cache_dir: str, log: Callable[[str], None]) -> None:
        self.folder = folder
        self.ext = EXT[fmt]
        self.cache_dir = cache_dir
        self.log = log
        self.slots: Dict[str, Loaded] = {}
        self.oplock = threading.RLock()          # one drive operation at a time: one board
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.closer: Callable[[], None] = lambda: None

    # -- lifecycle -----------------------------------------------------------
    def start(self, backends: Dict[str, Backend], closer: Callable[[], None]) -> None:
        os.makedirs(self.folder, exist_ok=True)
        self.closer = closer
        for name, be in backends.items():
            path = os.path.join(self.folder, name + self.ext)
            self.slots[name] = Loaded(name, be, TrackDisk(be), path, total=be.cyls * be.heads)
        names = " ".join(cmd_path(self.folder, n + self.ext) for n in backends)
        with open(os.path.join(self.folder, "play.cmd"), "w") as f:
            f.write(f"np2kai {names}\n")
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> bool:
        """Write anything pending, release the drives. True if nothing was lost."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=60)
        ok = True
        with self.oplock:
            for s in self.slots.values():
                ok &= self._flush(s)
                try:
                    s.backend.close()
                except Exception:
                    pass
            self.closer()
        return ok

    @property
    def ready(self) -> bool:
        return bool(self.slots) and all(s.phase == "ready" for s in self.slots.values())

    def state(self) -> Dict[str, Any]:
        return {n: s.state() for n, s in self.slots.items()}

    # -- the loop ---------------------------------------------------------------
    def _run(self) -> None:
        for s in self.slots.values():
            if self.stop_event.is_set():
                return
            self._load(s)
        while not self.stop_event.wait(POLL_SECONDS):
            for s in self.slots.values():
                try:
                    self._tick(s)
                except Exception as e:
                    s.phase, s.error = "error", str(e)
                    self.log(f"error {s.name}: {e}")

    def _tick(self, s: Loaded) -> None:
        with self.oplock:
            if s.backend.poll_change():
                lost = s.disk.new_disk()
                if lost:
                    self.log(f"error {s.name}: disk changed with {lost} track(s) not yet saved; "
                             "they were NOT written to the new disk")
                s.phase = "swapped"
                self.log(f"{s.name}: disk changed, reading the new one")
                self._load(s)
                return
            if s.phase != "ready":
                return
            s.backend.idle()
            self._absorb_file_changes(s)
            if s.disk.dirty_tracks and time.monotonic() - s.disk.last_write > QUIET_SECONDS:
                self._flush(s)

    # -- reading a disk in ------------------------------------------------------
    def _load(self, s: Loaded) -> None:
        with self.oplock:
            s.phase, s.track, s.error = "reading", 0, ""
            be = s.backend
            if not be.has_disk():
                s.phase, s.error = "error", "no disk"
                self.log(f"{s.name}: no disk")
                return
            s.protected = be.write_protected()
            try:
                image = self._read_disk(s)
            except DiskError as e:
                s.phase, s.error = "error", e.strerror or str(e)
                self.log(f"error {s.name}: {s.error}")
                return
            s.label = label_of(image[:16])
            self._write_file(s, image)
            s.phase = "ready"
            self.log(f"{s.name}: ready" + (f", {s.label}" if s.label else "") +
                     (", write-protected" if s.protected else ", writable"))

    def _read_disk(self, s: Loaded) -> bytes:
        """The whole disk, from the cache when it's a protected disk we've seen, else from
        the drive. Everything read goes through the TrackDisk so later writes use its cache."""
        be, disk = s.backend, s.disk
        tb, heads, cyls = be.track_bytes, be.heads, be.cyls
        first = be.read_track(0, 0)
        if first is None:
            raise DiskError(5, "track 0 can't be read")
        disk._cache[0] = bytearray(first)
        disk.verified = True
        s.track = 1
        cached = self._cached_image(s, first) if s.protected else None
        if cached is not None:
            for idx in range(1, cyls * heads):
                disk._cache[idx] = bytearray(cached[idx * tb:(idx + 1) * tb])
            s.track = s.total
            self.log(f"{s.name}: known disk, loaded from the cache")
            return cached
        chunks: List[bytes] = [first]
        for idx in range(1, cyls * heads):
            if self.stop_event.is_set():
                raise DiskError(5, "stopped while reading")
            cyl, head = divmod(idx, heads)
            data = be.read_track(cyl, head)
            if data is None:
                raise DiskError(5, f"track {cyl}.{head} can't be read")
            disk._cache[idx] = bytearray(data)
            chunks.append(data)
            s.track = idx + 1
        image = b"".join(chunks)
        if s.protected:
            self._store_cache(s, first, image)
        return image

    def _cache_path(self, first: bytes) -> str:
        return os.path.join(self.cache_dir, hashlib.sha1(first).hexdigest() + self.ext)

    def _cached_image(self, s: Loaded, first: bytes) -> Optional[bytes]:
        path = self._cache_path(first)
        try:
            with open(path, "rb") as f:
                image = f.read()
        except OSError:
            return None
        be = s.backend
        if len(image) != be.cyls * be.heads * be.track_bytes:
            return None
        checks = [(c, h) for c in (*SPOT_CHECK, be.cyls - 1) for h in range(be.heads) if 0 < c < be.cyls]
        for cyl, head in checks:
            idx = cyl * be.heads + head
            data = be.read_track(cyl, head)
            if data is None or data != image[idx * be.track_bytes:(idx + 1) * be.track_bytes]:
                self.log(f"{s.name}: cached image doesn't match track {cyl}.{head}, reading the disk")
                return None
        return image

    def _store_cache(self, s: Loaded, first: bytes, image: bytes) -> None:
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = self._cache_path(first) + ".part"
            with open(tmp, "wb") as f:
                f.write(image)
            os.replace(tmp, self._cache_path(first))
        except OSError as e:
            self.log(f"{s.name}: couldn't keep a copy in the cache: {e}")

    # -- the file the emulator sees -------------------------------------------------
    def _write_file(self, s: Loaded, image: bytes) -> None:
        tmp = s.path + ".part"
        with open(tmp, "wb") as f:
            f.write(image)
        os.chmod(tmp, 0o444 if s.protected else 0o644)
        os.replace(tmp, s.path)
        s.image = image
        s.mtime = os.stat(s.path).st_mtime

    def _absorb_file_changes(self, s: Loaded) -> None:
        """If the emulator wrote to the file, put the changed tracks into the disk cache,
        which marks them dirty for the next flush."""
        try:
            st = os.stat(s.path)
        except OSError:
            return
        if st.st_mtime == s.mtime and st.st_size == len(s.image):
            return
        with open(s.path, "rb") as f:
            now = f.read()
        s.mtime = st.st_mtime
        if len(now) != len(s.image):
            self.log(f"error {s.name}: the file was resized; the disk keeps its size, changes ignored")
            self._write_file(s, s.image)
            return
        if s.protected:
            if now != s.image:
                self.log(f"{s.name}: the disk is write-protected; the file was put back")
                self._write_file(s, s.image)
            return
        tb = s.backend.track_bytes
        changed = 0
        for idx in range(len(now) // tb):
            a, b = now[idx * tb:(idx + 1) * tb], s.image[idx * tb:(idx + 1) * tb]
            if a != b:
                s.disk.seek(idx * tb)
                s.disk.write(a)
                changed += 1
        s.image = now
        if changed:
            self.log(f"{s.name}: {changed} track(s) changed by the game")

    def _flush(self, s: Loaded) -> bool:
        n = s.disk.dirty_tracks
        if not n or s.disk.broken:
            return not s.disk.broken
        self.log(f"{s.name}: saving {n} track(s)")
        try:
            s.disk.flush_to_disk()
        except DiskError as e:
            self.log(f"error {s.name}: {e.strerror}")
            return False
        self.log(f"{s.name}: saved")
        return True

    def remove_files(self) -> None:
        for s in self.slots.values():
            for p in (s.path, s.path + ".part"):
                try:
                    os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
                    os.remove(p)
                except OSError:
                    pass
        try:
            os.remove(os.path.join(self.folder, "play.cmd"))
        except OSError:
            pass
