"""Unit tests of the disk layer with a fake drive: no hardware, no FUSE.

What they pin down is what keeps a disk safe: no write until track 0 has decoded on this
drive, nothing pending survives a swap, a failed write marks the disk broken, and a
covered notch is honoured.
"""
from __future__ import annotations

import sys
from typing import Dict, Optional, Tuple

from floppy_drive import DiskError, ImageBackend, TrackDisk

fails = 0


def check(ok: bool, what: str) -> None:
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + what, flush=True)


class FakeDrive:
    """A two-track-per-cylinder drive whose tracks can be made unreadable or unwritable."""
    cyls, heads, track_bytes = 4, 2, 1024

    def __init__(self) -> None:
        self.data: Dict[Tuple[int, int], bytes] = {(c, h): bytes([c * 2 + h]) * self.track_bytes
                                                   for c in range(self.cyls) for h in range(self.heads)}
        self.unreadable: set[Tuple[int, int]] = set()
        self.unwritable: set[Tuple[int, int]] = set()
        self.changed = False
        self.writes = 0

    def read_track(self, cyl: int, head: int) -> Optional[bytes]:
        return None if (cyl, head) in self.unreadable else self.data[(cyl, head)]

    def write_track(self, cyl: int, head: int, data: bytes) -> bool:
        if (cyl, head) in self.unwritable:
            return False
        self.data[(cyl, head)] = bytes(data)
        self.writes += 1
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


def main() -> int:
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
    disk2.write_at(0, b"q" * 8)
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
    disk3.write_at(1024 + 512, b"w" * 1024)
    check(disk3.dirty_tracks == 2, "the same write succeeds once every track reads")

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

    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
