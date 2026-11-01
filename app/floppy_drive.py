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

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple


class DiskError(OSError):
    """A track could not be read or written, or the disk was changed."""


RETRY_SECONDS = 30.0                      # how soon a track that wouldn't read is tried again
LABEL_START, LABEL_END = 3, 11            # where a boot sector holds the disk's name


class Backend(Protocol):
    cyls: int
    heads: int
    track_bytes: int
    proven: bool                          # a swap on this drive is known to be seen

    def read_track(self, cyl: int, head: int) -> Optional[bytes]: ...
    def standard_track(self, cyl: int, head: int) -> bool: ...
    def write_track(self, cyl: int, head: int, data: bytes) -> bool: ...
    def disk_changed(self) -> bool: ...
    def poll_change(self) -> bool: ...
    def has_disk(self) -> bool: ...
    def write_protected(self) -> bool: ...
    def idle(self) -> None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------- backends
class ImageBackend:
    """Tracks stored in an image file: a backup standing in for a drive. A file that can't
    be written counts as write-protected, like a covered notch."""

    def __init__(self, path: str, cyls: int, heads: int, track_bytes: int) -> None:
        self.path, self.cyls, self.heads, self.track_bytes = path, cyls, heads, track_bytes
        self.changed = False
        self.proven = True
        self.readonly = not os.access(path, os.W_OK)
        self._ino = self._inode()

    def _inode(self) -> int:
        try:
            return os.stat(self.path).st_ino
        except OSError:
            return 0

    def _offset(self, cyl: int, head: int) -> int:
        return (cyl * self.heads + head) * self.track_bytes

    def read_track(self, cyl: int, head: int) -> Optional[bytes]:
        with open(self.path, "rb") as f:
            f.seek(self._offset(cyl, head))
            return f.read(self.track_bytes)

    def standard_track(self, cyl: int, head: int) -> bool:
        return True

    def write_track(self, cyl: int, head: int, data: bytes) -> bool:
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


def is_standard(dat: Any) -> bool:
    """Is a decoded track exactly what rewriting it would produce? A write rebuilds the whole
    track from the format's plain layout, which would erase anything else on it: the extra
    or duplicate sectors and deleted-data marks that copy protection uses, for one."""
    from greaseweazle.codec.ibm.ibm import Mark
    raw = getattr(dat, "raw", None)
    if raw is None:
        return False
    expected = {(s.idam.c, s.idam.h, s.idam.r, s.idam.n) for s in dat.sectors}
    seen = set()
    for r in raw.sectors:
        if r.idam.crc != 0:
            continue
        sector = (r.idam.c, r.idam.h, r.idam.r, r.idam.n)
        if sector not in expected or sector in seen or (r.dam.crc == 0 and r.dam.mark != Mark.DAM):
            return False
        seen.add(sector)
    return True


class GwBoard:
    """One Greaseweazle, shared by the drives on its ribbon: only one can be selected at a time."""

    def __init__(self) -> None:
        from greaseweazle.tools import util
        # Merely opening the board stops whatever it's doing, a write included, so another
        # copy of this program must be turned away first and everything else kept out after.
        port = util.find_port()
        self._lock_fd: Optional[int] = None
        try:
            import fcntl
            self._lock_fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:                   # Windows: a COM port can be opened only once anyway
            pass
        except OSError:
            self._unlock()
            raise
        try:
            self.usb = util.usb_open(port)
        except SystemExit:                    # the library prints and exits on a firmware problem
            self._unlock()
            raise RuntimeError("the Greaseweazle's firmware is too old or was interrupted; update it "
                               "with the Greaseweazle tools: https://github.com/keirf/greaseweazle/wiki/")
        except Exception:
            self._unlock()
            raise
        if self._lock_fd is not None:
            import termios
            fcntl.ioctl(self.usb.ser.fileno(), termios.TIOCEXCL)
        # The board remembers each head's position between programs, and a wrong memory puts
        # every track off by that much. A reset makes the first seek find track 0 by its sensor.
        self.usb.power_on_reset()
        self.lock = threading.RLock()
        self.selected: Optional["GwBackend"] = None

    def _unlock(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def close(self) -> None:
        self.usb.ser.close()
        self._unlock()

    def __enter__(self) -> "GwBoard":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class GwBackend:
    """One drive on a Greaseweazle, reading and writing whole tracks in a given format.

    The drive is selected and its motor started on first use, and switched off
    again after IDLE_SECONDS without activity (idle() is called by a timer).
    Pass a shared GwBoard to run two drives from one board.
    """
    IDLE_SECONDS = 3.0
    READ_ATTEMPTS = 4
    WRITE_ATTEMPTS = 3

    def __init__(self, drive_letter: str, fmt_name: str, board: GwBoard, cyl_offset: int = 0,
                 proven: bool = False) -> None:
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
        self._board = board
        self._usb = board.usb
        self._drive = util.Drive()(drive_letter)
        self._lock = self._board.lock
        self._active = False
        self._last_use = 0.0
        self._ticks_per_rev = 0.0
        self._changed = False        # a swap not yet acknowledged by poll_change()
        self._new_change = False
        self._empty = False
        self._empty_seen = 0.0
        self.proven = proven         # pin 34 has been seen low: a swap on this drive will be noticed
        self._odd: Set[Tuple[int, int]] = set()   # tracks a write would rebuild into something else
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
            self.proven = True
            # a step clears the latch; if it reads low again there is no disk at all
            if self._empty and time.monotonic() - self._empty_seen < 2.0:
                return                   # known empty: don't step the head on every poll
            before = self._changed, self._new_change
            if self._last_use:           # first: the steps clear the latch and may then fail
                self._changed = self._new_change = True
            was_empty = self._empty
            self._usb.seek(1, 0)
            self._usb.seek(0, 0)
            self._empty = not self._usb.get_pin(34)
            self._empty_seen = time.monotonic()
            if was_empty and self._empty:
                self._changed, self._new_change = before
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
                # A drive that can't report a swap would get the old disk's saves on the new one.
                return not self._pins or not self.proven or not self._usb.get_pin(28)
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
                    if is_standard(dat):
                        self._odd.discard((cyl, head))
                    else:
                        self._odd.add((cyl, head))
                    return bytes(dat.get_img_track())
                if attempt == self.READ_ATTEMPTS - 2:   # re-seat the head before the last try
                    self._check_change()                # these seeks would clear the latch
                    if self._changed:
                        return None
                    self._usb.seek(0, 0)
                    self._usb.seek(cyl + self._cyl_offset, head)
            return None

    def standard_track(self, cyl: int, head: int) -> bool:
        """After a read of that track: would rewriting it keep everything on it?"""
        return (cyl, head) not in self._odd

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

    def __enter__(self) -> "GwBackend":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------- the disk
class TrackDisk:
    """The whole disk as one addressable block, backed by a track cache over a Backend.

    Thread-safe. Writes land in the cache and go to the disk in flush_to_disk(),
    which the owner calls after a quiet period and before unmounting.
    """

    def __init__(self, backend: Backend, log: Callable[[str], None] = lambda s: None) -> None:
        self.b = backend
        self.size = backend.cyls * backend.heads * backend.track_bytes
        self._cache: Dict[int, bytearray] = {}
        self._dirty: Set[int] = set()
        self._lock = threading.RLock()
        self._log = log
        self.last_write = 0.0
        self.broken: Optional[str] = None     # set once the disk is unsafe to write
        self.verified = False                 # track 0 of this disk has decoded on this drive
        self._failed: Dict[int, float] = {}   # tracks that wouldn't read, and when they last failed
        self._odd: Set[int] = set()           # tracks a write would rebuild into something else

    # tracks ---------------------------------------------------------------
    def _track(self, idx: int) -> bytearray:
        t = self._cache.get(idx)
        if t is None:
            cyl, head = divmod(idx, self.b.heads)
            # A game or BIOS can retry a bad spot forever, with the head on it each time.
            if time.monotonic() - self._failed.get(idx, -RETRY_SECONDS) < RETRY_SECONDS:
                raise DiskError(5, f"can't read track {cyl}.{head}")
            data = self.b.read_track(cyl, head)
            if data is None:
                self._failed[idx] = time.monotonic()
                raise DiskError(5, f"can't read track {cyl}.{head}")
            if not self.b.standard_track(cyl, head):
                self._odd.add(idx)
            t = bytearray(data)
            self._cache[idx] = t
            if idx == 0:
                self.verified = True
        return t

    def read_at(self, offset: int, size: int) -> bytes:
        """`size` bytes from `offset`, reading tracks from the disk as needed."""
        with self._lock:
            n = min(size, max(0, self.size - offset))
            out = bytearray()
            tb = self.b.track_bytes
            while len(out) < n:
                idx, off = divmod(offset + len(out), tb)
                chunk = min(n - len(out), tb - off)
                out += self._track(idx)[off:off + chunk]
            return bytes(out)

    def write_at(self, offset: int, data: "bytes | bytearray | memoryview") -> int:
        """Put `data` at `offset` into the cache, marking changed tracks for the next flush."""
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
            n = min(len(mv), max(0, self.size - offset))
            tb = self.b.track_bytes
            changes: List[Tuple[int, int, int, int]] = []
            done = 0
            while done < n:                  # read every track touched first: all or nothing
                idx, off = divmod(offset + done, tb)
                chunk = min(n - done, tb - off)
                if self._track(idx)[off:off + chunk] != mv[done:done + chunk]:
                    self._check_writable(idx)
                    changes.append((idx, off, done, chunk))
                done += chunk
            if changes and offset < LABEL_END and offset + n > LABEL_START:
                self._check_label(offset, mv[:n])
            for idx, off, pos, chunk in changes:
                self._cache[idx][off:off + chunk] = mv[pos:pos + chunk]
                self._dirty.add(idx)
            self.last_write = time.monotonic()
            return n

    def _check_writable(self, idx: int) -> None:
        cyl, head = divmod(idx, self.b.heads)
        if idx in self._odd:
            raise DiskError(30, f"track {cyl}.{head} holds more than a plain track can, probably copy "
                                "protection; writing it would erase that, so the write is refused")
        if idx in self._failed:
            raise DiskError(30, f"track {cyl}.{head} failed to read earlier, so what's being written "
                                "may be a blank stand-in for it; the write is refused")

    def _check_label(self, offset: int, data: memoryview) -> None:
        """A disk's boot sector names it, and nothing a game does to a disk changes that. A write
        that does is a whole image of another disk, from a program that missed a swap: stop it
        here, at its first sector, before the rest of the image lands on this disk."""
        label = bytearray(self._track(0)[LABEL_START:LABEL_END])
        for i in range(max(offset, LABEL_START), min(offset + len(data), LABEL_END)):
            label[i - LABEL_START] = data[i - offset]
        if label != self._track(0)[LABEL_START:LABEL_END]:
            self.broken = "a write tried to change the disk's own name, so it's meant for another disk"
            raise DiskError(30, self.broken)

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
            # Last track first: a directory near the start must not name data not yet written.
            for idx in sorted(self._dirty, reverse=True):
                cyl, head = divmod(idx, self.b.heads)
                if not self.b.write_track(cyl, head, bytes(self._cache[idx])):
                    self.broken = f"track {cyl}.{head} could not be written and verified"
                    raise DiskError(5, self.broken)
                self._dirty.discard(idx)
                written += 1
                self._log(f"wrote track {cyl}.{head}")
            return written

    def new_disk(self) -> int:
        """A different disk is in the drive: forget the old one. Returns how many unsaved
        tracks were lost; they belong to the old disk and must never go onto this one."""
        with self._lock:
            lost = len(self._dirty)
            self._cache.clear()
            self._dirty.clear()
            self._failed.clear()
            self._odd.clear()
            self.broken = None
            self.verified = False
            return lost

