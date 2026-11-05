"""Unit tests of the disk layer with a fake drive: no hardware, no FUSE.

What they pin down is what keeps a disk safe: no write until track 0 has decoded on this
drive, nothing pending survives a swap, a failed write marks the disk broken, and a
covered notch is honoured.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from greaseweazle import error
from greaseweazle.usb import Ack, CmdError

import floppy_drive
from floppy_drive import DiskError, GwBackend, GwBoard, ImageBackend, TrackDisk, is_standard
from d88 import Sector

fails = 0


def check(ok: bool, what: str) -> None:
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + what, flush=True)


class FakeDrive:
    """A two-track-per-cylinder drive whose tracks can be made unreadable or unwritable."""
    cyls, heads, track_bytes, sector_n = 4, 2, 1024, 3

    def __init__(self) -> None:
        self.data: Dict[Tuple[int, int], bytes] = {(c, h): bytes([c * 2 + h]) * self.track_bytes
                                                   for c in range(self.cyls) for h in range(self.heads)}
        self.unreadable: set[Tuple[int, int]] = set()
        self.unwritable: set[Tuple[int, int]] = set()
        self.odd: set[Tuple[int, int]] = set()
        self.extra: Dict[Tuple[int, int], List[Sector]] = {}
        self.changed = False
        self.writes = 0
        self.reads = 0
        self.order: List[Tuple[int, int]] = []
        self.proven = True

    def read_track(self, cyl: int, head: int) -> Optional[bytes]:
        self.reads += 1
        return None if (cyl, head) in self.unreadable else self.data[(cyl, head)]

    def standard_track(self, cyl: int, head: int) -> bool:
        return (cyl, head) not in self.odd

    def sectors(self, cyl: int, head: int) -> Optional[List[Sector]]:
        return self.extra.get((cyl, head))

    def why_unreadable(self, cyl: int, head: int) -> str:
        return ""

    def write_track(self, cyl: int, head: int, data: bytes) -> bool:
        if (cyl, head) in self.unwritable:
            return False
        self.data[(cyl, head)] = bytes(data)
        self.writes += 1
        self.order.append((cyl, head))
        return True

    def disk_changed(self) -> bool:
        return self.changed

    def poll_change(self) -> bool:
        c, self.changed = self.changed, False
        return c

    def has_disk(self) -> bool:
        return True

    def write_protected(self) -> bool:
        return False

    def idle(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeUSB:
    """The board's view of a drive: pin 34 is the latch a step clears when a disk is in."""

    def __init__(self, disk: bool) -> None:
        self.disk = disk
        self.latch = False
        self.fail_seek = False
        self.motor = False
        self.home = False
        self.steps = 0
        self.old_firmware = False
        self.lost = False
        self.resets = 0

    def get_pin(self, n: int) -> bool:
        if n == 26:
            return not self.home
        return not self.latch if n == 34 else True

    def _send_cmd(self, cmd: bytes) -> None:
        if self.old_firmware:
            raise CmdError(cmd, Ack.BadCommand)
        self.latch = not self.disk             # a step the drive ignores: nothing moved

    def power_on_reset(self) -> None:
        self.resets += 1
        self.lost = self.motor = False

    def seek(self, cyl: int, head: int) -> None:
        if self.lost:
            raise error.Fatal("Track0 signal absent after seek to cylinder 0")
        self.latch = not self.disk             # the step clears it, whatever happens next
        self.steps += 1
        if self.fail_seek:
            raise OSError("USB went away")

    def set_bus_type(self, bus: int) -> None:
        pass

    def drive_select(self, unit: int) -> None:
        pass

    def drive_deselect(self) -> None:
        pass

    def drive_motor(self, unit: int, on: bool) -> None:
        self.motor = on


def gw_backend(usb: FakeUSB, proven: bool, used: bool = False) -> GwBackend:
    """A real GwBackend's swap logic on a fake board."""
    class Board:
        selected = None
        lock = threading.RLock()
        backends: List[GwBackend] = []
        rehome: Any = classmethod(GwBoard.rehome)       # type: ignore[arg-type]

    class Bus:
        value = 1

    class Unit:
        unit_id = 0
        bus = Bus

    Board.usb = usb                                    # type: ignore[attr-defined]
    be = GwBackend.__new__(GwBackend)
    Board.backends.append(be)
    fields: Dict[str, Any] = dict(_board=Board, _usb=usb, _lock=Board.lock, _drive=Unit, _cyl_offset=0, _active=False,
                                  _last_use=1.0 if used else 0.0, _ticks_per_rev=0.0, _changed=False,
                                  _new_change=False, _empty=False, _empty_seen=0.0, proven=proven, _pins=True,
                                  _quiet_step=True, _odd=set(), _extra={}, _why={}, sector_n=3,
                                  track_bytes=8192)
    be.__dict__.update(fields)
    return be


def main() -> int:
    floppy_drive.RETRY_SECONDS = 0.0             # the first tests clear faults and go straight on
    # 1. No write until track 0 decodes on this drive.
    d = FakeDrive()
    d.unreadable.add((0, 0))
    disk = TrackDisk(d)
    try:
        disk.write_at(3 * 1024, b"x" * 16)
        check(False, "write refused while track 0 is unreadable")
    except DiskError as e:
        check(e.errno == 30, "write refused while track 0 is unreadable")
    check(disk.dirty_tracks == 0, "nothing marked dirty by the refused write")

    # 2. Once track 0 reads, writes are accepted and reach the disk on flush, verified.
    d.unreadable.clear()
    disk.write_at(3 * 1024, b"x" * 16)
    check(disk.verified and disk.dirty_tracks == 1, "write accepted after track 0 decoded")
    check(disk.flush_to_disk() == 1 and d.data[(1, 1)][:16] == b"x" * 16, "flush writes the one dirty track")

    # 3. A swap drops pending writes; they never land on the new disk.
    disk.write_at(5 * 1024, b"y" * 8)
    before = d.writes
    lost = disk.new_disk()
    check(lost == 1 and disk.dirty_tracks == 0 and d.writes == before, "pending write dropped on swap")
    check(not disk.verified, "a new disk must prove its track 0 again")

    # 4. A swap seen at flush time refuses the write and marks the disk broken.
    disk.write_at(2 * 1024, b"z" * 8)
    d.changed = True
    try:
        disk.flush_to_disk()
        check(False, "flush refused when the disk changed underneath")
    except DiskError:
        check(disk.broken is not None, "flush refused when the disk changed underneath")

    # 4b. Once the swap is acknowledged and the disk started over, saving to the NEW disk works.
    check(d.poll_change() is True and d.poll_change() is False, "a swap is reported once, then acknowledged")
    disk.new_disk()
    disk.write_at(2 * 1024, b"n" * 8)
    check(disk.flush_to_disk() == 1 and d.data[(1, 0)][:8] == b"n" * 8, "saves after a swap reach the new disk")

    # 4c. A swap noticed between write and flush refuses the write too.
    d.changed = True
    try:
        disk.write_at(0, b"late")
        check(False, "a write after an unacknowledged swap is refused")
    except DiskError:
        check(True, "a write after an unacknowledged swap is refused")
    d.poll_change()
    disk.new_disk()

    # 5. A write that can't be verified marks the disk broken; later writes are refused.
    d2 = FakeDrive()
    disk2 = TrackDisk(d2)
    disk2.write_at(16, b"q" * 8)
    d2.unwritable.add((0, 0))
    try:
        disk2.flush_to_disk()
        check(False, "unverifiable write marks the disk broken")
    except DiskError:
        check(disk2.broken is not None, "unverifiable write marks the disk broken")
    try:
        disk2.write_at(0, b"r")
        check(False, "no writes after the disk is broken")
    except DiskError:
        check(True, "no writes after the disk is broken")

    # 5b. A write spanning several tracks changes nothing when one of them can't be read.
    d3 = FakeDrive()
    disk3 = TrackDisk(d3)
    d3.unreadable.add((1, 0))                # track index 2
    try:
        disk3.write_at(1024 + 512, b"w" * 1024)   # starts in track 1, runs into track 2
        check(False, "a multi-track write stops before changing anything if a track is unreadable")
    except DiskError:
        check(disk3.dirty_tracks == 0 and disk3._cache.get(1) is None or disk3._cache[1][512:] != b"w" * 512,
              "a multi-track write stops before changing anything if a track is unreadable")
    d3.unreadable.clear()
    try:
        disk3.write_at(1024 + 512, b"w" * 1024)
        check(False, "a track that failed earlier can't be written, even if it reads now")
    except DiskError:
        check(disk3.dirty_tracks == 0, "a track that failed earlier can't be written, even if it reads now")
    disk3.new_disk()
    disk3.write_at(1024 + 512, b"w" * 1024)
    check(disk3.dirty_tracks == 2, "the next disk starts clean")

    # 6. A read-only image file counts as write-protected, like a covered notch.
    import os
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="drivetest"), "a.img")
    with open(path, "wb") as f:
        f.write(b"\0" * (4 * 2 * 1024))
    os.chmod(path, 0o444)
    check(ImageBackend(path, 4, 2, 1024).write_protected(), "read-only image counts as write-protected")
    os.chmod(path, 0o644)
    check(not ImageBackend(path, 4, 2, 1024).write_protected(), "writable image counts as writable")
    os.remove(path)

    # 7. A bad track isn't hammered: a retry within the window doesn't touch the drive.
    floppy_drive.RETRY_SECONDS = 30.0
    d4 = FakeDrive()
    disk4 = TrackDisk(d4)
    d4.unreadable.add((2, 0))
    for _ in range(5):
        try:
            disk4.read_at(4 * 1024, 16)
        except DiskError:
            pass
    check(d4.reads == 1, "five reads of a bad track reach the drive once")

    # 8. A track holding more than plain sectors reads fine but can't be rewritten.
    d5 = FakeDrive()
    d5.odd.add((1, 0))
    disk5 = TrackDisk(d5)
    same = disk5.read_at(2 * 1024, 16)
    disk5.write_at(2 * 1024, same)
    check(disk5.dirty_tracks == 0, "writing a non-standard track's own bytes back changes nothing")
    try:
        disk5.write_at(2 * 1024, b"s" * 16)
        check(False, "a real write to a non-standard track is refused")
    except DiskError as e:
        check(e.errno == 30 and disk5.dirty_tracks == 0, "a real write to a non-standard track is refused")
    disk5.write_at(3 * 1024, b"s" * 16)
    check(disk5.dirty_tracks == 1, "its neighbours stay writable")

    # 9. A write that changes the disk's own name is another disk's image: stop it at once.
    d6 = FakeDrive()
    disk6 = TrackDisk(d6)
    disk6.write_at(0, b"\x11\x22\x33")
    disk6.write_at(11, b"after the name")
    check(disk6.dirty_tracks == 1, "writes beside the disk's name are fine")
    disk6.write_at(3, disk6.read_at(3, 8))
    check(disk6.broken is None, "rewriting the same name is fine")
    try:
        disk6.write_at(0, b"AB" + b"OTHERDISK" + bytes(1013))
        check(False, "a write changing the disk's name is refused")
    except DiskError:
        check(disk6.broken is not None, "a write changing the disk's name is refused")
    try:
        disk6.write_at(4 * 1024, b"rest of that image")
        check(False, "the rest of that image is refused too")
    except DiskError:
        check(True, "the rest of that image is refused too")
    disk6.new_disk()
    disk6.write_at(4 * 1024, b"the next disk")
    check(disk6.dirty_tracks == 1, "the next disk can be written")

    # 10. The last track goes first, so a directory can't name data not yet written.
    d7 = FakeDrive()
    disk7 = TrackDisk(d7)
    for t in (1, 5, 3):
        disk7.write_at(t * 1024, b"o" * 8)
    disk7.flush_to_disk()
    check(d7.order == [(2, 1), (1, 1), (0, 1)], "saves are written last track first")

    # 11. A drive that has never shown it can report a swap stays read-only.
    usb = FakeUSB(disk=True)
    be = gw_backend(usb, proven=False)
    be.has_disk()
    check(be.write_protected(), "a drive not yet proven is read-only")
    usb.disk = False
    usb.latch = True
    be.has_disk()
    check(be.proven and not be.write_protected(), "seeing the drive empty proves it")
    check(not gw_backend(FakeUSB(disk=True), proven=True).write_protected(), "a proven drive stays proven")

    # 12. A swap is remembered even if the check itself fails after clearing the latch.
    usb = FakeUSB(disk=True)
    be = gw_backend(usb, proven=True, used=True)
    usb.latch, usb.fail_seek = True, True
    try:
        be.disk_changed()
    except OSError:
        pass
    usb.fail_seek = False
    check(not usb.latch and be.poll_change(), "a swap survives a check that failed halfway")
    check(not be.poll_change(), "and is reported once")

    # 13. Only a track that rewriting would keep intact counts as standard.
    from greaseweazle.codec import codec
    from greaseweazle.codec.ibm.ibm import IDAM, Mark, Sector
    disk_def = codec.get_diskdef("pc98.2hd")
    assert disk_def is not None
    made = disk_def.mk_track(10, 0)
    assert made is not None
    made.set_img_track(bytes(range(256)) * 32)
    plain = disk_def.decode_flux(10, 0, made.master_track().flux())
    check(plain is not None and plain.nr_missing() == 0 and is_standard(plain), "a plain track is standard")
    r = plain.raw.sectors[0]
    plain.raw.sectors.append(Sector(IDAM(0, 1, 0, 10, 0, 9, 3), r.dam))
    check(not is_standard(plain), "an extra sector is not standard")
    plain.raw.sectors.pop()
    plain.raw.sectors.append(Sector(IDAM(0, 1, 0, r.idam.c, r.idam.h, r.idam.r, r.idam.n), r.dam))
    check(not is_standard(plain), "a duplicate sector is not standard")
    plain.raw.sectors.pop()
    r.dam.mark = Mark.DDAM
    check(not is_standard(plain), "a deleted-data mark is not standard")

    # 14. Enough failed reads and the disk is left alone until it's changed.
    floppy_drive.RETRY_SECONDS = 0.0
    d = FakeDrive()
    d.unreadable.add((1, 0))
    disk = TrackDisk(d)
    good = disk.read_at(0, 16)

    def bad_read() -> str:
        try:
            disk.read_at(2 * 1024, 16)
            return ""
        except DiskError as e:
            return str(e.strerror)
    for _ in range(7):
        bad_read()
    check(not disk.left_alone, "seven failed reads are still tolerated")
    before = d.reads
    bad_read()
    check(disk.left_alone and d.reads == before + 1, "the eighth leaves the disk alone")
    check("Clean the heads" in bad_read() and d.reads == before + 1, "no more reads after that, and it says why")
    check(disk.read_at(0, 16) == good, "what's in memory still reads")
    try:
        disk.write_at(0, b"x" * 16)
        check(False, "no writes either")
    except DiskError:
        check(True, "no writes either")
    disk.new_disk()
    d.unreadable.clear()
    check(not disk.left_alone and not disk.broken and disk.read_at(2 * 1024, 4) == d.data[(1, 0)][:4],
          "the disk coming out clears it")

    # 15. A protection check's one bad track, now and then, never adds up.
    limit = floppy_drive.GIVE_UP_SECONDS
    floppy_drive.GIVE_UP_SECONDS = 0.0
    d = FakeDrive()
    d.unreadable.add((1, 0))
    disk = TrackDisk(d)
    for _ in range(20):
        bad_read()
    check(not disk.left_alone, "failures spread out over time don't add up")
    floppy_drive.GIVE_UP_SECONDS = limit

    # 16. Backups keep the head still: no re-seat on their two tries.
    class Flux:
        _ticks_per_rev = 0.0

    class Undecodable:
        def nr_missing(self) -> int:
            return 1

        def decode_flux(self, flux: Any, pll: Any) -> None:
            pass

    class Fmt:
        def decode_flux(self, cyl: int, head: int, flux: Any) -> Any:
            return Undecodable()

        def mk_track(self, cyl: int, head: int) -> Any:
            return None                               # no raw decode: nothing of the track read at all

    def tries(attempts: int) -> int:
        usb = FakeUSB(disk=True)
        seeks: List[int] = []
        usb.seek = lambda cyl, head: seeks.append(cyl)      # type: ignore[method-assign]
        usb.read_track = lambda revs=2, ticks=0: Flux()     # type: ignore[attr-defined]
        be = gw_backend(usb, proven=True)
        be.__dict__.update(_ticks_per_rev=1.0, _active=True, _disk=Fmt(), _plls=[], READ_ATTEMPTS=attempts)
        check(be.read_track(40, 0) is None, f"{attempts} tries on a bad track give up")
        return len(seeks)
    check(tries(2) == 1, "a backup doesn't move the head on a bad track")
    check(tries(4) == 3, "playing re-seats it once")

    # 17. The motor stops soon after the last read.
    usb = FakeUSB(disk=True)
    usb.motor = True
    be = gw_backend(usb, proven=True)
    be.__dict__.update(_active=True, _last_use=time.monotonic())
    be.idle()
    check(usb.motor, "the motor runs on just after a read")
    be._last_use = time.monotonic() - 1.8
    be.idle()
    check(not usb.motor and not be._active, "and stops within two seconds")

    # 18. At track 0, finding out whether a disk is in moves nothing.
    usb = FakeUSB(disk=False)
    usb.home = usb.latch = True
    be = gw_backend(usb, proven=True)
    check(not be.has_disk() and usb.steps == 0, "an empty drive is found empty with the head still")
    usb.disk = True
    be._empty_seen = 0.0
    check(be.has_disk() and usb.steps == 0, "and a disk going in is found the same way")
    usb = FakeUSB(disk=False)
    usb.latch = True
    be = gw_backend(usb, proven=True)
    be.has_disk()
    check(usb.steps == 2, "away from track 0 it takes a real step")
    usb = FakeUSB(disk=True)
    usb.home = usb.latch = usb.old_firmware = True
    be = gw_backend(usb, proven=True)
    check(be.has_disk() and usb.steps == 2 and not be._quiet_step, "older firmware falls back to a real step")

    # 19. A head off track 0 is sent home, and the read carries on.
    usb = FakeUSB(disk=True)
    usb.motor = True
    be = gw_backend(usb, proven=True)
    be.__dict__.update(_active=True, _ticks_per_rev=1.0)
    usb.lost = True
    be._seek(0, 0)
    check(usb.resets == 1 and usb.steps == 1, "a head that lost its place is sent home and the seek goes on")
    check(usb.motor and be._active, "and the motor is running again")
    usb.lost = True
    usb.power_on_reset = lambda: None                  # type: ignore[method-assign]
    try:
        be._seek(0, 0)
        check(False, "a head that won't go home is an error, not a retry forever")
    except error.Fatal:
        check(True, "a head that won't go home is an error, not a retry forever")

    # 20. A write looks at the headers first: a head off its place writes nothing astray.
    from greaseweazle import track as gwtrack
    blank = bytes(len(made.get_img_track()))

    class Shelf(FakeUSB):
        """Real tracks under the head: a seek lands `slip` tracks off what the board thinks.
        Going home stops at track 0 for a head too far out, and fails for one too far in."""
        def __init__(self, slip: int, stuck: bool = False) -> None:
            super().__init__(disk=True)
            self.slip, self.stuck, self.pos = slip, stuck, 0
            self.wrote: List[int] = []

        def power_on_reset(self) -> None:
            super().power_on_reset()
            self.slip = self.slip if self.stuck else 0

        def seek(self, cyl: int, head: int) -> None:
            if cyl == 0 and not self.stuck:
                if self.slip > 0:
                    self.lost = True             # it never reaches the track 0 sensor
                else:
                    self.slip = 0                # steps out past track 0 are ignored
            super().seek(cyl, head)
            self.pos = cyl + self.slip

        def read_track(self, revs: int = 2, ticks: int = 0) -> Any:
            t = disk_def.mk_track(self.pos, 0)
            assert t is not None
            t.set_img_track(blank)
            return t.master_track().flux()

        def write_track(self, **kw: Any) -> None:
            self.wrote.append(self.pos)

    def write(usb: Shelf) -> str:
        be = gw_backend(usb, proven=True)
        flux = usb.read_track()
        be.__dict__.update(_active=True, _disk=disk_def, _plls=gwtrack.plls, _ticks_per_rev=float(flux.ticks_per_rev))
        try:
            return "written" if be.write_track(40, 0, blank) else "not written"
        except DiskError as e:
            return str(e.strerror)
    usb = Shelf(0)
    check(write(usb) == "written" and usb.wrote == [40] and usb.resets == 0, "a head in place writes, with no going home")
    usb = Shelf(1)
    check(write(usb) == "written" and usb.wrote == [40] and usb.resets == 1, "a head one track in goes home, then writes the right track")
    usb = Shelf(-1)
    check(write(usb) == "written" and usb.wrote == [40], "a head one track out goes home, then writes the right track")
    usb = Shelf(2, stuck=True)
    check("nothing was written" in write(usb) and usb.wrote == [], "a head that stays off writes nothing")
    d = FakeDrive()
    disk = TrackDisk(d)
    disk.write_at(3 * 1024, b"x" * 16)

    def off_track(cyl: int, head: int, data: bytes) -> bool:
        raise DiskError(11, f"the head isn't over track {cyl}.{head}")
    d.write_track = off_track  # type: ignore[method-assign]
    try:
        disk.flush_to_disk()
    except DiskError:
        pass
    check(disk.dirty_tracks == 1 and not disk.broken, "and the save waits for the next try, the disk not given up on")

    d88_tests()
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


def d88_tests() -> None:
    """The D88 layer: images keep odd sectors, the emulator's search finds every one, a
    track read from flux keeps what a controller would see, and a drive that is tracks off
    says so."""
    import io
    import os
    import tempfile
    import d88
    # 30. A file round trip keeps every sector, and the layout suits Neko Project II.
    tracks = [d88.plain_sectors(c, h, bytes([c, h]) * 4096, 3) for c in range(3) for h in range(2)]
    long_ones = [d88.Sector(1, 0, 0xF0 + k, 4, bytes([k]) * 2048, d88.CRC_ERROR) for k in range(11)]
    tracks[2] = tracks[2][:4] + long_ones + tracks[2][4:]
    tracks[3][0] = d88.Sector(1, 1, 1, 3, tracks[3][0].data, 0, True)
    img = d88.Image.from_bytes(d88.Image("TEST", 0x20, True, tracks).to_bytes())
    check(img.name == "TEST" and img.protected and img.media == 0x20, "a D88's header round-trips")
    check([s.id for s in img.tracks[2]] == [s.id for s in tracks[2]], "a protected track keeps its sectors in order")
    check(img.tracks[3][0].deleted and not d88.is_plain(img.tracks[3], 1, 1, 8192, 3), "a deleted mark is kept")
    pos, ok = 0, True
    for sec in img.tracks[2]:
        ok = ok and pos + 16 + sec.full <= d88.SLOT
        pos += 16 + len(sec.data)
    check(ok and all(len(x.data) >= 768 for x in img.tracks[2] if x.status), "long sectors fit the emulator's search")
    check(d88.is_plain(img.tracks[0], 0, 0, 8192, 3) and not d88.is_plain(img.tracks[2], 1, 0, 8192, 3),
          "plain and protected tracks are told apart")
    turned = img.tracks[0][1:] + img.tracks[0][:1]
    check(d88.is_plain(turned, 0, 0, 8192, 3) and not d88.is_plain(turned + turned[:1], 0, 0, 8192, 3),
          "a plain track's sectors may come round in any order, but each only once")
    check(d88.image_of(img.tracks[2], 1, 0, 8192, 3) == bytes([1, 0]) * 4096, "a protected track's plain sectors make its image")
    raw = d88.Image("TEST", 0x20, False, tracks).to_bytes()
    check(d88.boot_sector_start(io.BytesIO(raw), True) == bytes([0, 0]) * 8, "a D88's boot sector is found")
    check(d88.boot_sector_start(io.BytesIO(b"ABCDEFGHIJKLMNOPQ"), False) == b"ABCDEFGHIJKLMNOP", "and a sector image's")

    # 31. A D88 standing in for a drive saves into its plain sectors, in place.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.d88")
        open(path, "wb").write(raw)
        be = floppy_drive.D88Backend(path, 3, 2, 8192)
        check(be.standard_track(0, 0) and not be.standard_track(1, 0), "a D88 backend knows its protected track")
        check(be.sectors(1, 0) is not None and be.sectors(0, 0) is None, "and gives its sectors")
        new = bytearray(be.read_track(2, 1) or b"")
        new[1024:1032] = b"SAVEDATA"
        be.write_track(2, 1, bytes(new))
        again = d88.Image.from_bytes(open(path, "rb").read())
        check(again.tracks[5][1].data[:8] == b"SAVEDATA" and len(open(path, "rb").read()) == len(raw),
              "a save lands in the file in place")
        disk = TrackDisk(be)
        check([x.r for x in disk.sectors(2)] == [x.r for x in tracks[2]], "the disk layer serves all its sectors")
        try:
            disk.write_at(2 * 8192, b"z" * 8)
            check(False, "a write to the protected track is refused")
        except DiskError:
            check(True, "a write to the protected track is refused")

    # 32. Every sector a controller would find, from one read, plain ones as decoded.
    from greaseweazle.codec.ibm import ibm
    import greaseweazle.track
    def area(start: int, c: int, r: int, n: int, crc: int, mark: int = ibm.Mark.DAM) -> Any:
        return ibm.Sector(ibm.IDAM(start, start + 10, 0, c=c, h=0, r=r, n=n),
                          ibm.DAM(start + 20, start + 40, crc, mark=mark, data=bytes([r]) * (128 << n)))
    areas = [area(900, 1, 0xF5, 4, 1), area(100, 1, 1, 3, 1), area(500, 1, 0xF0, 4, 1), area(510, 1, 0xF0, 4, 1),
             area(700, 1, 2, 3, 0, ibm.Mark.DDAM)]
    class Flux:
        def cue_at_index(self) -> None:
            pass
    class Template:
        mode, time_per_rev, clock = ibm.Mode.MFM, 0.2, 1e-6
    saved = ibm.IBMTrack.mfm_decode_raw, greaseweazle.track.PLLTrack
    ibm.IBMTrack.mfm_decode_raw = staticmethod(lambda raw: areas)
    class NoTurns:
        revolutions: List[Any] = []
    greaseweazle.track.PLLTrack = lambda **kw: NoTurns()
    try:
        image = bytes([7]) * 2048
        got = floppy_drive.all_sectors(Template(), Flux(), image, 1, 0, 2048, 3)
    finally:
        ibm.IBMTrack.mfm_decode_raw, greaseweazle.track.PLLTrack = saved
    check([x.r for x in got] == [1, 0xF0, 2, 0xF5], "sectors come in the order the head meets them, each once")
    check(got[0].data == bytes([7]) * 1024 and got[0].status == 0, "a plain sector keeps what the format's decoder read")
    check(got[1].status == d88.CRC_ERROR and len(got[1].data) == 2048, "a bad data CRC is kept as its status")
    check(got[2].deleted, "a deleted data mark is kept")

    # 32b. A sector with the same ID elsewhere on the track is another sector, and is kept.
    areas[:] = [area(100, 1, 1, 3, 0), area(5000, 1, 0xF0, 4, 1), area(166000 + 5030, 1, 0xF0, 4, 1),
                area(40000, 1, 0xF0, 4, 0)]
    class Rev:
        nr_bits = 166000
    class OneTurn:
        revolutions = [Rev()]
    ibm.IBMTrack.mfm_decode_raw = staticmethod(lambda raw: areas)
    greaseweazle.track.PLLTrack = lambda **kw: OneTurn()
    try:
        got = floppy_drive.all_sectors(Template(), Flux(), None, 1, 0, 2048, 3)
    finally:
        ibm.IBMTrack.mfm_decode_raw, greaseweazle.track.PLLTrack = saved
    check([(x.r, x.status) for x in got] == [(1, 0), (0xF0, d88.CRC_ERROR), (0xF0, 0)],
          "the same sector on the next turn counts once; one with the same ID elsewhere is kept")

    # 32b2. From a drive: a track whose own sector 5 never reads is served with that error;
    #       one whose sectors all name another cylinder is the head in the wrong place.
    class Half:
        raw = None
        def nr_missing(self) -> int:
            return 1
        def decode_flux(self, flux: Any, pll: Any) -> None:
            pass
    class Fmt88:
        def decode_flux(self, cyl: int, head: int, flux: Any) -> Any:
            return Half()
        def mk_track(self, cyl: int, head: int) -> Any:
            return Template()
    def from_drive(c: int) -> Tuple[Optional[bytes], GwBackend]:
        usb = FakeUSB(disk=True)
        usb.read_track = lambda revs=2, ticks=0: Flux()     # type: ignore[attr-defined]
        g = gw_backend(usb, proven=True)
        g.__dict__.update(_ticks_per_rev=1.0, _active=True, _disk=Fmt88(), _plls=[], READ_ATTEMPTS=2)
        areas[:] = [area(1000 * r, c, r, 3, 1 if r == 5 else 0) for r in range(1, 9)]
        ibm.IBMTrack.mfm_decode_raw = staticmethod(lambda raw: areas)
        greaseweazle.track.PLLTrack = lambda **kw: OneTurn()
        try:
            return g.read_track(40, 0), g
        finally:
            ibm.IBMTrack.mfm_decode_raw, greaseweazle.track.PLLTrack = saved
    got40, drv = from_drive(40)
    served = drv.sectors(40, 0) or []
    check(got40 is not None and not drv.standard_track(40, 0) and
          [(x.r, x.status) for x in served] == [(r, d88.CRC_ERROR if r == 5 else 0) for r in range(1, 9)],
          "a track whose sector 5 never reads is served with that sector's error, and can't be written")
    got44, drv = from_drive(44)
    check(got44 is None and drv.sectors(40, 0) is None, "a track whose sectors all name another cylinder doesn't read")

    # 32c. Protection the search can't all reach still keeps the start of its data.
    odd_track = d88.plain_sectors(1, 0, bytes(8192), 3) + [d88.Sector(1, 0, 0xF0, 4, bytes(2048), d88.CRC_ERROR),
                                                           d88.Sector(1, 0, 0xF1, 7, bytes(16384), d88.CRC_ERROR)]
    fitted = d88.fit(odd_track)
    check(len(fitted[8].data) > 0, "one sector too big to reach doesn't cost the others their data")

    # 33. Sectors from another cylinder: the drive is that many tracks off, and says so.
    class Idam:
        def __init__(self, c: int) -> None:
            self.c, self.crc = c, 0
    class Raw:
        sectors = [type("S", (), {"idam": Idam(4)})() for _ in range(8)]
    class Dat:
        raw = Raw()
    said = floppy_drive.elsewhere(Dat(), 0)
    check("cylinder 4" in said and "4 tracks in" in said, "a head 4 tracks in is named as such")
    check(floppy_drive.elsewhere(Dat(), 4) == "", "the right cylinder is no complaint")


if __name__ == "__main__":
    sys.exit(main())
