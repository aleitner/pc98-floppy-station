"""A floppy in a Greaseweazle drive, as a seekable, writable file-like object.

The disk is presented as its sector image (e.g. 1,261,568 bytes for PC-98 2HD),
so the FAT library can sit on top of it unchanged. Underneath, it works a whole
track at a time, because a floppy can only be written a track at a time:

  read   -> the track is read from the disk once and kept in memory
  write  -> the track in memory is changed and marked dirty
  flush  -> each dirty track is written to the disk and verified

TrackDisk is backend-agnostic: GwBackend drives the real hardware through the
Greaseweazle library; ImageBackend and D88Backend use image files standing in for a drive.
A track that holds more than plain sectors (copy protection) is kept as all its sectors
too, for d88.View to serve.
"""
from __future__ import annotations

import os
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple

import d88
from d88 import Sector


class DiskError(OSError):
    """A track could not be read or written, or the disk was changed."""


RETRY_SECONDS = 30.0                      # how soon a track that wouldn't read is tried again
GIVE_UP_READS, GIVE_UP_SECONDS = 8, 600.0  # this many failed reads this quickly: stop touching the disk
LABEL_START, LABEL_END = 3, 11            # where a boot sector holds the disk's name


class Backend(Protocol):
    cyls: int
    heads: int
    track_bytes: int
    sector_n: int                         # size code of the format's sectors: 3 is 1024 bytes
    proven: bool                          # a swap on this drive is known to be seen

    def read_track(self, cyl: int, head: int) -> Optional[bytes]: ...
    def standard_track(self, cyl: int, head: int) -> bool: ...
    def sectors(self, cyl: int, head: int) -> Optional[List[Sector]]: ...
    def why_unreadable(self, cyl: int, head: int) -> str: ...
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

    def __init__(self, path: str, cyls: int, heads: int, track_bytes: int, sector_n: int = 3) -> None:
        self.path, self.cyls, self.heads, self.track_bytes = path, cyls, heads, track_bytes
        self.sector_n = sector_n
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

    def sectors(self, cyl: int, head: int) -> Optional[List[Sector]]:
        return None                       # a sector image holds plain tracks only

    def why_unreadable(self, cyl: int, head: int) -> str:
        return ""

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


class D88Backend(ImageBackend):
    """A D88 file standing in for a drive: protected tracks and all. A save is written into
    the file in place, sector by sector; only plain sectors are ever written."""

    def __init__(self, path: str, cyls: int, heads: int, track_bytes: int, sector_n: int = 3) -> None:
        super().__init__(path, cyls, heads, track_bytes, sector_n)
        self._load()

    def _load(self) -> None:
        with open(self.path, "rb") as f:
            raw = f.read()
        self.image = d88.Image.from_bytes(raw)
        self.where = self.image.data_offsets(raw)
        self.readonly = self.readonly or self.image.protected

    def _track(self, cyl: int, head: int) -> List[Sector]:
        idx = cyl * self.heads + head
        return self.image.tracks[idx] if idx < len(self.image.tracks) else []

    def poll_change(self) -> bool:
        new = super().poll_change()
        if new and self.has_disk():
            self._load()
        return new

    def read_track(self, cyl: int, head: int) -> Optional[bytes]:
        secs = self._track(cyl, head)
        if not secs:
            return None
        return d88.image_of(secs, cyl, head, self.track_bytes, self.sector_n)

    def standard_track(self, cyl: int, head: int) -> bool:
        return d88.is_plain(self._track(cyl, head), cyl, head, self.track_bytes, self.sector_n)

    def sectors(self, cyl: int, head: int) -> Optional[List[Sector]]:
        return None if self.standard_track(cyl, head) else list(self._track(cyl, head))

    def write_track(self, cyl: int, head: int, data: bytes) -> bool:
        size = 128 << self.sector_n
        where = self.where.get((cyl, head), {})
        secs = self._track(cyl, head)
        with open(self.path, "r+b") as f:
            for i, s in enumerate(secs):
                if s.id not in d88.plain_ids(cyl, head, self.track_bytes, self.sector_n) or s.status:
                    continue
                new = data[(s.r - 1) * size:s.r * size]
                if new != s.data:
                    f.seek(where[s.id])
                    f.write(new)
                    secs[i] = Sector(s.c, s.h, s.r, s.n, new, s.status, s.deleted)
        return True


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
        self.backends: List["GwBackend"] = []

    def rehome(self) -> None:
        """A head isn't where the board remembers. The reset makes the next seek on each drive
        find track 0 by its sensor; it also stops the motors, which restart on next use."""
        for backend in self.backends:
            backend._active = False
        self.selected = None
        self.usb.power_on_reset()

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
    IDLE_SECONDS = 1.7       # about 10 turns: the heads ride a spinning disk the whole time
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
        self.sector_n = int(probe.sectors[0].idam.n) if probe.sectors else 3

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
        self._extra: Dict[Tuple[int, int], List[Sector]] = {}   # all the sectors of each of those
        self._why: Dict[Tuple[int, int], str] = {}
        self._quiet_step = True
        board.backends.append(self)
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
        except Exception as e:
            self._usb.drive_motor(self._drive.unit_id, False)   # no disk, or no answer: not active
            if "No Index" in str(e):
                raise DiskError(6, "no disk in the drive, or its lever is open") from e
            raise
        self._usb.drive_motor(self._drive.unit_id, True)        # sending a head home stops it
        self._active = True

    def _check_change(self) -> None:
        """Pin 34 is DISK CHANGE (DC jumper): low after the door opens, until the next step.
        A failed pin read is an error, not "no change": the caller must not write on it."""
        if not self._pins:
            return                       # older firmware without pin reads: no detection
        if not self._usb.get_pin(34):
            self.proven = True
            # a step clears the latch; if it reads low again there is no disk at all
            if self._empty and time.monotonic() - self._empty_seen < (2.0 if self._quiet_step else 60.0):
                return                   # known empty: don't step the head on every poll
            before = self._changed, self._new_change
            if self._last_use:           # first: the steps clear the latch and may then fail
                self._changed = self._new_change = True
            was_empty = self._empty
            self._clear_latch()
            self._empty = not self._usb.get_pin(34)
            self._empty_seen = time.monotonic()
            if was_empty and self._empty:
                self._changed, self._new_change = before
        else:
            self._empty = False

    def _clear_latch(self) -> None:
        """Any step clears the latch if a disk is in. At track 0 the drive ignores a step outward,
        so the head stays put; an empty drive is always there, and never moves."""
        from greaseweazle.usb import Ack, Cmd, CmdError
        if self._quiet_step and not self._usb.get_pin(26):
            try:
                self._usb._send_cmd(struct.pack("2B", Cmd.NoClickStep, 2))
                return
            except CmdError as e:
                if e.code not in (Ack.BadCommand, Ack.BadCylinder):
                    raise
                self._quiet_step = False         # older firmware, or this drive obeyed the step
        self._seek(1, 0)
        self._seek(0, 0)

    def _seek(self, cyl: int, head: int) -> None:
        """A disk going in can knock a head off track 0, and every track after that would be
        out by as much. The board finds out at track 0: send the head home and carry on. Every
        write first looks at the headers under the head, so none before can have gone astray."""
        from greaseweazle import error
        try:
            self._usb.seek(cyl, head)
        except error.Fatal as e:
            if "Track0" not in str(e):
                raise
            spinning = self._active
            self._board.rehome()
            self._select()
            if spinning:
                self._activate()
            self._usb.seek(cyl, head)

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
            self._seek(cyl + self._cyl_offset, head)
            if self._changed:
                return None              # seen while sending the head home
            self._ticks_per_rev = self._ticks_per_rev or float(self._usb.read_track(2).ticks_per_rev)
            dat = None
            for attempt in range(self.READ_ATTEMPTS):
                flux = self._usb.read_track(revs=1 if attempt == 0 else 3)
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
                    self._why.pop((cyl, head), None)
                    image = bytes(dat.get_img_track())
                    if is_standard(dat):
                        self._odd.discard((cyl, head))
                        self._extra.pop((cyl, head), None)
                    else:
                        self._odd.add((cyl, head))
                        self._extra[(cyl, head)] = self._all_sectors(cyl, head, image)
                    return image
                if 0 < attempt == self.READ_ATTEMPTS - 2:   # re-seat the head before the last try
                    self._check_change()                # these seeks would clear the latch
                    if self._changed:
                        return None
                    self._seek(0, 0)
                    self._seek(cyl + self._cyl_offset, head)
            # Not every sector read. If the ones that did are this track's own, the rest are
            # what copy protection often is, a sector whose data never reads without an error:
            # serve the track as it reads, errors and all. Sectors that all say another
            # cylinder mean the head is in the wrong place, and are no track of this disk.
            found = all_sectors(self._disk.mk_track(cyl, head), flux, None, cyl, head, self.track_bytes,
                                self.sector_n)
            if any(x.c == cyl and x.h == head for x in found):
                self._why.pop((cyl, head), None)
                self._odd.add((cyl, head))
                self._extra[(cyl, head)] = found
                return d88.image_of(found, cyl, head, self.track_bytes, self.sector_n)
            self._why[(cyl, head)] = elsewhere(dat, cyl)
            return None

    def standard_track(self, cyl: int, head: int) -> bool:
        """After a read of that track: would rewriting it keep everything on it?"""
        return (cyl, head) not in self._odd

    def sectors(self, cyl: int, head: int) -> Optional[List[Sector]]:
        """After a read of a track that isn't plain: every sector on it, in the order the head
        meets them, each with its ID, its status and the bytes a read of it returns."""
        return self._extra.get((cyl, head))

    def why_unreadable(self, cyl: int, head: int) -> str:
        return self._why.get((cyl, head), "")

    def capture(self, cyl: int, head: int, attempts: int = 2) -> Tuple[Any, Optional[bytes], List[Sector], bool]:
        """One track for a backup, in as few turns of the disk as will do: the flux of a read
        of a few turns, the plain image if every sector decoded, every sector found, and
        whether the track is a plain one. Everything is decoded from that same read, so the
        flux kept is exactly what the rest was made from. A second read only if sectors
        were missing."""
        with self._lock:
            self._activate()
            self._check_change()
            if self._changed:
                raise DiskError(5, "the disk was changed")
            self._last_use = time.monotonic()
            self._seek(cyl + self._cyl_offset, head)
            flux: Any = None
            dat: Any = None
            for _ in range(attempts):
                flux = self._usb.read_track(revs=3)
                flux._ticks_per_rev = self._ticks_per_rev
                dat = self._disk.decode_flux(cyl, head, flux) if cyl < self.cyls else None
                for pll in self._plls:
                    if dat is None or dat.nr_missing() == 0:
                        break
                    dat.decode_flux(flux, pll)
                if dat is None or dat.nr_missing() == 0:
                    break                        # complete, or past the format: no second read
            self._last_use = time.monotonic()
            image = bytes(dat.get_img_track()) if dat is not None and dat.nr_missing() == 0 else None
            template = self._disk.mk_track(min(cyl, self.cyls - 1), head)
            found = all_sectors(template, flux, image, cyl, head, self.track_bytes, self.sector_n)
            self._why[(cyl, head)] = "" if image is not None else elsewhere(dat, cyl)
            return flux, image, found, image is not None and is_standard(dat)

    def _all_sectors(self, cyl: int, head: int, image: bytes) -> List[Sector]:
        """Read the track again, a few turns this time, and keep everything on it. Sectors
        whose data runs past the index need the turn after it. The plain sectors keep the
        bytes the format's decoder settled on, which may have taken several tries."""
        flux = self._usb.read_track(revs=3)
        flux._ticks_per_rev = self._ticks_per_rev
        return all_sectors(self._disk.mk_track(cyl, head), flux, image, cyl, head, self.track_bytes, self.sector_n)

    def _over_track(self, cyl: int, head: int) -> bool:
        """Is the head over the track about to be rewritten? The PC-98's controller found each
        sector's header before writing it. A whole-track write has to look first, or a head
        knocked off its place would write over the track next door."""
        flux = self._usb.read_track(revs=1)
        flux._ticks_per_rev = self._ticks_per_rev
        dat = self._disk.decode_flux(cyl, head, flux)
        raw = getattr(dat, "raw", None)
        if raw is None:
            return False
        want = {(s.idam.c, s.idam.h) for s in dat.sectors}
        seen = {(s.idam.c, s.idam.h) for s in raw.sectors if s.idam.crc == 0}
        return bool(seen) and seen <= want

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
            self._seek(cyl + self._cyl_offset, head)
            if not self._over_track(cyl, head):
                self._check_change()             # these seeks would clear the latch
                if self._changed:
                    return False
                self._seek(0, 0)                 # a head that lost its place is sent home
                self._seek(cyl + self._cyl_offset, head)
                if not self._over_track(cyl, head):
                    raise DiskError(11, f"the head isn't over track {cyl}.{head}, even after going "
                                        "home; nothing was written, and it will try again")
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


def all_sectors(track: Any, flux: Any, image: Optional[bytes], cyl: int, head: int, track_bytes: int,
                n: int) -> List[Sector]:
    """Every sector in a read of one track: what a disk controller would find, odd ones
    included. A data CRC error is kept as the status a PC-98 reports for it."""
    from greaseweazle.codec.ibm.ibm import IBMTrack, Mark, Mode
    from greaseweazle.codec.ibm.ibm import Sector as GwSector
    from greaseweazle.track import PLLTrack
    plain = {s.id: s for s in d88.plain_sectors(cyl, head, image, n)} if image is not None else {}
    found: List[Tuple[int, Sector]] = []
    if getattr(track, "mode", None) is Mode.MFM:
        flux.cue_at_index()
        raw = PLLTrack(time_per_rev=track.time_per_rev, clock=track.clock, data=flux)
        turn = raw.revolutions[0].nr_bits if raw.revolutions else 0
        for a in sorted(IBMTrack.mfm_decode_raw(raw), key=lambda a: a.start):
            if not isinstance(a, GwSector) or a.idam.crc != 0:
                continue
            i = a.idam
            sec = Sector(i.c, i.h, i.r, i.n, bytes(a.dam.data), d88.CRC_ERROR if a.dam.crc else 0,
                         a.dam.mark == Mark.DDAM)
            # The same sector comes round on every turn; one with the same ID somewhere else
            # on the track is another sector, which copy protection uses too.
            if any(k.id == sec.id and same_place(start, a.start, turn) for start, k in found):
                continue
            found.append((a.start, sec))
    out = [sec for _, sec in sorted(found, key=lambda x: x[0])]
    swapped: Set[Tuple[int, int, int, int]] = set()      # the first of each ID takes the decoder's bytes
    for k, s in enumerate(out):
        if s.id in plain and not s.deleted and s.id not in swapped:
            out[k] = plain[s.id]
            swapped.add(s.id)
    seen = {s.id for s in out}
    return out + [s for k, s in plain.items() if k not in seen]


def same_place(a: int, b: int, turn: int) -> bool:
    """Two positions on a track, in bit cells from the index, within a sector header of each other."""
    d = abs(a - b) % turn if turn else abs(a - b)
    return min(d, turn - d) < 1000 if turn else d < 1000


def elsewhere(dat: Any, cyl: int) -> str:
    """A track that won't read because its sectors say they belong to another cylinder: the
    drive's track 0 isn't the disk's, and every track is out by as much."""
    raw = getattr(dat, "raw", None)
    if raw is None:
        return ""
    found = {s.idam.c for s in raw.sectors if s.idam.crc == 0}
    if len(found) != 1 or cyl in found or sum(s.idam.crc == 0 for s in raw.sectors) < 4:
        return ""
    other = found.pop()
    return (f"this track's sectors say they're cylinder {other}: the drive's head is {abs(other - cyl)} "
            f"track{'s' if abs(other - cyl) > 1 else ''} {'in' if other > cyl else 'out'} from where it "
            "should be. If the disk was made on another machine, the drive needs realigning")


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
        self._extra: Dict[int, List[Sector]] = {}   # all the sectors of those, for a D88 view
        self.epoch = 0                        # counts disks: a view's cache belongs to one
        self._failures: List[float] = []      # when reads failed lately
        self.left_alone = False               # too many failed: no more reads until the disk comes out

    # tracks ---------------------------------------------------------------
    def _track(self, idx: int) -> bytearray:
        t = self._cache.get(idx)
        if t is None:
            cyl, head = divmod(idx, self.b.heads)
            if self.left_alone:
                raise DiskError(5, str(self.broken))
            # A game or BIOS can retry a bad spot forever, with the head on it each time.
            if time.monotonic() - self._failed.get(idx, -RETRY_SECONDS) < RETRY_SECONDS:
                raise DiskError(5, f"can't read track {cyl}.{head}")
            data = self.b.read_track(cyl, head)
            if data is None:
                self._failed[idx] = time.monotonic()
                self._note_failure()
                why = self.b.why_unreadable(cyl, head)
                raise DiskError(5, f"can't read track {cyl}.{head}" + (f": {why}" if why else ""))
            if not self.b.standard_track(cyl, head):
                self._odd.add(idx)
                extra = self.b.sectors(cyl, head)
                if extra is not None:
                    self._extra[idx] = extra
                    plain = set(d88.plain_ids(cyl, head, self.b.track_bytes, self.b.sector_n))
                    odd = [x for x in extra if x.id not in plain]
                    weak = [f"{x.r}" for x in extra if x.id in plain and x.status]
                    if odd:
                        self._log(f"track {cyl}.{head}: copy protection, {len(odd)} extra "
                                  f"sector{'s' if len(odd) > 1 else ''}, served as on the disk")
                    if weak:
                        # A plain sector that won't read can be protection too, but also a weak spot
                        # on the disk or dirty heads: worth knowing about.
                        self._log(f"track {cyl}.{head}: sector{'s' if len(weak) > 1 else ''} {', '.join(weak)} "
                                  "read with an error; served that way, and the track isn't written. If this "
                                  "isn't copy protection, clean the heads and look the disk over")
            t = bytearray(data)
            self._cache[idx] = t
            if idx == 0:
                self.verified = True
        return t

    def _note_failure(self) -> None:
        """Failed reads mean dirt on the heads or a failing disk, where every turn can do harm.
        A protection check's one bad track, read now and then, never adds up to this."""
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < GIVE_UP_SECONDS] + [now]
        if len(self._failures) >= GIVE_UP_READS:
            self.left_alone = True
            self.broken = ("too many tracks won't read, so this disk is being left alone. Clean the "
                           "heads, look the disk over, then take it out and put it back")

    def sectors(self, idx: int) -> List[Sector]:
        """One track as sectors, for a D88 view: all of them if it held more than a plain
        track, else the plain ones, with any change not yet saved."""
        with self._lock:
            image = bytes(self._track(idx))
            extra = self._extra.get(idx)
            if extra is not None:
                return list(extra)
            cyl, head = divmod(idx, self.b.heads)
            return d88.plain_sectors(cyl, head, image, self.b.sector_n)

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
            self._extra.clear()
            self.epoch += 1
            self._failures.clear()
            self.left_alone = False
            self.broken = None
            self.verified = False
            return lost

