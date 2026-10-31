"""A floppy in a Greaseweazle drive, as a seekable, writable file-like object.

The disk is presented as its sector image (e.g. 1,261,568 bytes for PC-98 2HD),
so the FAT library can sit on top of it unchanged. Underneath, it works a whole
track at a time, because a floppy can only be written a track at a time:

  read   -> the track is read from the disk once and kept in memory
  write  -> the track in memory is changed and marked dirty
  flush  -> each dirty track is written to the disk and verified

TrackDisk is backend-agnostic: GwBackend drives the real hardware through the
Greaseweazle library; ImageBackend uses an image file and exists for testing.
"""
from __future__ import annotations

import io
import os
import threading
import time
from typing import Callable, Dict, Optional, Protocol, Set, Tuple


class DiskError(OSError):
    """A track could not be read or written, or the disk was changed."""


class Backend(Protocol):
    cyls: int
    heads: int
    track_bytes: int

    def read_track(self, cyl: int, head: int) -> Optional[bytes]: ...
    def write_track(self, cyl: int, head: int, data: bytes) -> bool: ...
    def disk_changed(self) -> bool: ...
    def poll_change(self) -> bool: ...
    def has_disk(self) -> bool: ...
    def write_protected(self) -> bool: ...
    def idle(self) -> None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------- backends
class ImageBackend:
    """Tracks stored in an image file. For tests; never touches hardware."""

    def __init__(self, path: str, cyls: int, heads: int, track_bytes: int,
                 fail_reads: Optional[Set[Tuple[int, int]]] = None) -> None:
        self.path, self.cyls, self.heads, self.track_bytes = path, cyls, heads, track_bytes
        self.fail_reads: Set[Tuple[int, int]] = fail_reads or set()
        self.reads = 0
        self.writes = 0
        self.changed = False
        self.readonly = False
        self._ino = self._inode()

    def _inode(self) -> int:
        try:
            return os.stat(self.path).st_ino
        except OSError:
            return 0

    def _offset(self, cyl: int, head: int) -> int:
        return (cyl * self.heads + head) * self.track_bytes

    def read_track(self, cyl: int, head: int) -> Optional[bytes]:
        self.reads += 1
        if (cyl, head) in self.fail_reads:
            return None
        with open(self.path, "rb") as f:
            f.seek(self._offset(cyl, head))
            return f.read(self.track_bytes)

    def write_track(self, cyl: int, head: int, data: bytes) -> bool:
        self.writes += 1
        with open(self.path, "r+b") as f:
            f.seek(self._offset(cyl, head))
            f.write(data)
        return True

    def disk_changed(self) -> bool:
        return self.changed

    def poll_change(self) -> bool:
        """True once after the image was replaced, which is how tests swap a disk."""
        ino = self._inode()
        if ino == self._ino:
            return False
        self._ino = ino
        return True

    def has_disk(self) -> bool:
        return os.path.exists(self.path)

    def write_protected(self) -> bool:
        return self.readonly

    def idle(self) -> None:
        pass

    def close(self) -> None:
        pass


class GwBoard:
    """One Greaseweazle, shared by the drives on its ribbon: only one can be selected at a time."""

    def __init__(self, port: Optional[str] = None) -> None:
        from greaseweazle.tools import util
        self.usb = util.usb_open(port)
        self.lock = threading.RLock()
        self.selected: Optional["GwBackend"] = None

    def close(self) -> None:
        self.usb.ser.close()


class GwBackend:
    """One drive on a Greaseweazle, reading and writing whole tracks in a given format.

    The drive is selected and its motor started on first use, and switched off
    again after IDLE_SECONDS without activity (idle() is called by a timer).
    Pass a shared GwBoard to run two drives from one board.
    """
    IDLE_SECONDS = 3.0
    READ_ATTEMPTS = 4
    WRITE_ATTEMPTS = 3

    def __init__(self, drive_letter: str, fmt_name: str, port: Optional[str] = None,
                 board: Optional[GwBoard] = None, cyl_offset: int = 0) -> None:
        # Imported here so tests that only use ImageBackend don't need the hardware stack.
        from greaseweazle.tools import util
        from greaseweazle.codec import codec
        from greaseweazle import track as gwtrack

        disk = codec.get_diskdef(fmt_name)
        if disk is None:
            raise ValueError(f"unknown format {fmt_name}")
        self._disk = disk
        self._plls = gwtrack.plls
        assert disk.cyls is not None and disk.heads is not None
        self.cyls, self.heads = int(disk.cyls), int(disk.heads)
        probe = disk.mk_track(0, 0)
        assert probe is not None
        self.track_bytes = len(probe.get_img_track())

        self._cyl_offset = cyl_offset      # steps from where this drive thinks track 0 is to the real one
        self._owns_board = board is None
        self._board = board or GwBoard(port)
        self._usb = self._board.usb
        self._drive = util.Drive()(drive_letter)
        self._lock = self._board.lock
        self._active = False
        self._last_use = 0.0
        self._ticks_per_rev = 0.0
        self._changed = False        # a swap not yet acknowledged by poll_change()
        self._new_change = False
        self._empty = False
        self._empty_seen = 0.0
        self._pins = self._pins_supported()

    def _pins_supported(self) -> bool:
        """Can this firmware read input pins? Decided once, so a later read error is an error."""
        from greaseweazle.usb import Ack, CmdError
        with self._lock:
            self._select()
            try:
                self._usb.get_pin(34)
                return True
            except CmdError as e:
                if e.code == Ack.BadCommand:
                    return False
                raise
            finally:
                self._deselect()

    # selection and motor --------------------------------------------------
    def _select(self) -> None:
        if self._board.selected is self:
            return
        self._usb.set_bus_type(self._drive.bus.value)
        self._usb.drive_select(self._drive.unit_id)
        self._board.selected = self

    def _deselect(self) -> None:
        if self._board.selected is self:
            self._usb.drive_deselect()
            self._board.selected = None

    def _activate(self) -> None:
        self._select()
        if self._active:
            return
        self._usb.drive_motor(self._drive.unit_id, True)
        try:
            if not self._ticks_per_rev:
                self._ticks_per_rev = float(self._usb.read_track(2).ticks_per_rev)
            self._check_change()
        except Exception:
            self._usb.drive_motor(self._drive.unit_id, False)   # no disk, or no answer: not active
            raise
        self._active = True

    def _check_change(self) -> None:
        """Pin 34 is DISK CHANGE (DC jumper): low after the door opens, until the next step.
        A failed pin read is an error, not "no change": the caller must not write on it."""
        if not self._pins:
            return                       # older firmware without pin reads: no detection
        if not self._usb.get_pin(34):
            # a step clears the latch; if it reads low again there is no disk at all
            if self._empty and time.monotonic() - self._empty_seen < 2.0:
                return                   # known empty: don't step the head on every poll
            self._usb.seek(1, 0)
            self._usb.seek(0, 0)
            was_empty = self._empty
            self._empty = not self._usb.get_pin(34)
            self._empty_seen = time.monotonic()
            if self._last_use and not (was_empty and self._empty):
                self._changed = True
                self._new_change = True
        else:
            self._empty = False

    def idle(self) -> None:
        with self._lock:
            if self._active and time.monotonic() - self._last_use > self.IDLE_SECONDS:
                self._usb.drive_motor(self._drive.unit_id, False)
                self._deselect()
                self._active = False

    def disk_changed(self) -> bool:
        """A swap happened that poll_change() hasn't acknowledged yet. Read fresh."""
        with self._lock:
            self._select()
            self._check_change()
            if not self._active:
                self._deselect()
            return self._changed

    def poll_change(self) -> bool:
        """True once per disk change, and acknowledges it: the caller starts over with the
        new disk. Works with the motor off, so a swap is seen even when everything being
        read is already in the cache."""
        with self._lock:
            self._select()
            self._check_change()
            if not self._active:
                self._deselect()
            new, self._new_change = self._new_change, False
            if new:
                self._changed = False
            return new

    def has_disk(self) -> bool:
        with self._lock:
            self._select()
            self._check_change()
            if not self._active:
                self._deselect()
            return not self._empty

    def write_protected(self) -> bool:
        """Pin 28 is WRITE PROTECT: low when the notch is covered or missing."""
        with self._lock:
            self._select()
            try:
                return not self._pins or not self._usb.get_pin(28)
            finally:
                if not self._active:
                    self._deselect()

    # tracks --------------------------------------------------------------
    def read_track(self, cyl: int, head: int) -> Optional[bytes]:
        with self._lock:
            self._activate()
            self._check_change()         # a seek would clear the latch: look before every one
            if self._changed:
                return None              # whatever is in the drive now isn't the disk being read
            self._last_use = time.monotonic()
            self._usb.seek(cyl + self._cyl_offset, head)
            self._ticks_per_rev = self._ticks_per_rev or float(self._usb.read_track(2).ticks_per_rev)
            dat = None
            for attempt in range(self.READ_ATTEMPTS):
                flux = self._usb.read_track(revs=2 if attempt == 0 else 3)
                flux._ticks_per_rev = self._ticks_per_rev
                if dat is None:
                    dat = self._disk.decode_flux(cyl, head, flux)
                    if dat is None:
                        return None
                for pll in self._plls:
                    if dat.nr_missing() == 0:
                        break
                    dat.decode_flux(flux, pll)
                if dat.nr_missing() == 0:
                    self._last_use = time.monotonic()
                    return bytes(dat.get_img_track())
                if attempt == self.READ_ATTEMPTS - 2:   # re-seat the head before the last try
                    self._usb.seek(0, 0)
                    self._usb.seek(cyl + self._cyl_offset, head)
            return None

    def write_track(self, cyl: int, head: int, data: bytes) -> bool:
        from greaseweazle.track import MasterTrack
        with self._lock:
            self._activate()
            self._check_change()         # never write to a disk that was just swapped in
            if self._changed:
                return False
            assert self._ticks_per_rev > 0
            self._last_use = time.monotonic()
            t = self._disk.mk_track(cyl, head)
            assert t is not None
            t.set_img_track(data)
            master = t.master_track()
            assert isinstance(master, MasterTrack)
            wflux = master.flux_for_writeout(cue_at_index=True)
            factor = self._ticks_per_rev / wflux.ticks_to_index
            rem, flux_list = 0.0, []
            for x in wflux.list:                      # convert to Greaseweazle sample ticks
                y = x * factor + rem
                v = round(y)
                rem = y - v
                flux_list.append(v)
            self._usb.seek(cyl + self._cyl_offset, head)
            verify = master.verify
            for attempt in range(self.WRITE_ATTEMPTS):
                if attempt:
                    self._check_change()
                    if self._changed:
                        return False
                self._usb.write_track(flux_list=flux_list, cue_at_index=wflux.index_cued,
                                      terminate_at_index=wflux.terminate_at_index, hard_sector_ticks=0)
                if verify is None:
                    return True
                v_revs, v_ticks = verify.verify_revs, 0
                if isinstance(v_revs, float):
                    v_ticks = int(self._ticks_per_rev * v_revs)
                    v_revs = 2
                v_flux = self._usb.read_track(revs=v_revs, ticks=v_ticks)
                v_flux._ticks_per_rev = self._ticks_per_rev
                if verify.verify_track(v_flux):
                    self._last_use = time.monotonic()
                    return True
            return False

    def close(self) -> None:
        with self._lock:
            try:
                if self._active:
                    self._select()
                    self._usb.drive_motor(self._drive.unit_id, False)
                    self._deselect()
            finally:
                self._active = False
                if self._owns_board:
                    self._board.close()


# --------------------------------------------------------------------------- the disk
class TrackDisk(io.RawIOBase):
    """The whole disk as one seekable file, backed by a track cache over a Backend.

    Thread-safe. Writes land in the cache and are written to the disk by flush(),
    which the owner calls after a quiet period and before unmounting.
    """

    def __init__(self, backend: Backend, log: Callable[[str], None] = lambda s: None) -> None:
        super().__init__()
        self.b = backend
        self.size = backend.cyls * backend.heads * backend.track_bytes
        self._cache: Dict[int, bytearray] = {}
        self._dirty: Set[int] = set()
        self._pos = 0
        self._lock = threading.RLock()
        self._log = log
        self.last_write = 0.0
        self.broken: Optional[str] = None     # set once the disk is unsafe to write
        self.verified = False                 # track 0 of this disk has decoded on this drive

    # io plumbing ----------------------------------------------------------
    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def truncate(self, size: Optional[int] = None) -> int:
        return self.size          # a floppy has a fixed size

    # tracks ---------------------------------------------------------------
    def _track(self, idx: int) -> bytearray:
        t = self._cache.get(idx)
        if t is None:
            cyl, head = divmod(idx, self.b.heads)
            data = self.b.read_track(cyl, head)
            if data is None:
                raise DiskError(5, f"can't read track {cyl}.{head}")
            t = bytearray(data)
            self._cache[idx] = t
            if idx == 0:
                self.verified = True
        return t

    def readinto(self, buf: "memoryview | bytearray") -> int:   # type: ignore[override]
        with self._lock:
            n = min(len(buf), max(0, self.size - self._pos))
            done = 0
            tb = self.b.track_bytes
            while done < n:
                idx, off = divmod(self._pos + done, tb)
                chunk = min(n - done, tb - off)
                buf[done:done + chunk] = self._track(idx)[off:off + chunk]
                done += chunk
            self._pos += n
            return n

    def write(self, data: "bytes | bytearray | memoryview") -> int:  # type: ignore[override]
        with self._lock:
            if self.broken:
                raise DiskError(5, self.broken)
            if self.b.disk_changed():
                raise DiskError(5, "the disk was changed; this write belongs to the old disk")
            if not self.verified:
                # Before the first write, track 0 must decode with the sector headers the
                # decoder expects. That proves this drive's track 0 is the disk's track 0; a
                # drive whose home position has slipped would otherwise write every track to
                # the wrong place and ruin the disk for every other drive.
                try:
                    self._track(0)
                except DiskError:
                    raise DiskError(30, "track 0 can't be read on this drive, so writing is refused "
                                        "(blank disk, dirty heads, or a drive that has lost its track 0)")
            mv = memoryview(data).cast("B")
            n = min(len(mv), max(0, self.size - self._pos))
            tb = self.b.track_bytes
            if n:
                for idx in range(self._pos // tb, (self._pos + n - 1) // tb + 1):
                    self._track(idx)         # read every track touched first: all or nothing
            done = 0
            while done < n:
                idx, off = divmod(self._pos + done, tb)
                chunk = min(n - done, tb - off)
                t = self._track(idx)
                if t[off:off + chunk] != mv[done:done + chunk]:
                    t[off:off + chunk] = mv[done:done + chunk]
                    self._dirty.add(idx)
                done += chunk
            self._pos += n
            self.last_write = time.monotonic()
            return n

    @property
    def dirty_tracks(self) -> int:
        return len(self._dirty)

    def flush_to_disk(self) -> int:
        """Write every dirty track and verify it. Returns how many were written.

        Raises DiskError if a track can't be written or the disk was swapped; after that
        the disk is marked broken and no further writes are accepted."""
        with self._lock:
            if not self._dirty:
                return 0
            try:
                changed = self.b.disk_changed()
            except Exception as e:           # couldn't ask the drive: nothing written, try later
                raise DiskError(11, f"couldn't check the drive before saving ({e})")
            if changed:
                self.broken = ("the disk was changed while open; unsaved changes were NOT written "
                               "to the new disk")
                raise DiskError(5, self.broken)
            written = 0
            for idx in sorted(self._dirty):
                cyl, head = divmod(idx, self.b.heads)
                if not self.b.write_track(cyl, head, bytes(self._cache[idx])):
                    self.broken = f"track {cyl}.{head} could not be written and verified"
                    raise DiskError(5, self.broken)
                self._dirty.discard(idx)
                written += 1
                self._log(f"wrote track {cyl}.{head}")
            return written

    def drop_cache(self) -> None:
        with self._lock:
            if self._dirty:
                raise DiskError(5, "unsaved changes")
            self._cache.clear()

    def new_disk(self) -> int:
        """A different disk is in the drive: forget the old one. Returns how many unsaved
        tracks were lost; they belong to the old disk and must never go onto this one."""
        with self._lock:
            lost = len(self._dirty)
            self._cache.clear()
            self._dirty.clear()
            self.broken = None
            self.verified = False
            return lost

    def close(self) -> None:          # the owner closes the backend explicitly
        pass
