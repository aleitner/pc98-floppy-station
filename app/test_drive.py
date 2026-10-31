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
        c, self.changed = self.changed, False
        return c

    def poll_change(self) -> bool:
        return self.disk_changed()

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
    disk.seek(3 * 1024)
    try:
        disk.write(b"x" * 16)
        check(False, "write refused while track 0 is unreadable")
    except DiskError as e:
        check(e.errno == 30, "write refused while track 0 is unreadable")
    check(disk.dirty_tracks == 0, "nothing marked dirty by the refused write")

    # 2. Once track 0 reads, writes are accepted and reach the disk on flush, verified.
    d.unreadable.clear()
    disk.seek(3 * 1024)
    disk.write(b"x" * 16)
    check(disk.verified and disk.dirty_tracks == 1, "write accepted after track 0 decoded")
    check(disk.flush_to_disk() == 1 and d.data[(1, 1)][:16] == b"x" * 16, "flush writes the one dirty track")

    # 3. A swap drops pending writes; they never land on the new disk.
    disk.seek(5 * 1024)
    disk.write(b"y" * 8)
    before = d.writes
    lost = disk.new_disk()
    check(lost == 1 and disk.dirty_tracks == 0 and d.writes == before, "pending write dropped on swap")
    check(not disk.verified, "a new disk must prove its track 0 again")

    # 4. A swap seen at flush time refuses the write and marks the disk broken.
    disk.seek(2 * 1024)
    disk.write(b"z" * 8)
    d.changed = True
    try:
        disk.flush_to_disk()
        check(False, "flush refused when the disk changed underneath")
    except DiskError:
        check(disk.broken is not None, "flush refused when the disk changed underneath")

    # 5. A write that can't be verified marks the disk broken; later writes are refused.
    d2 = FakeDrive()
    disk2 = TrackDisk(d2)
    disk2.seek(0)
    disk2.write(b"q" * 8)
    d2.unwritable.add((0, 0))
    try:
        disk2.flush_to_disk()
        check(False, "unverifiable write marks the disk broken")
    except DiskError:
        check(disk2.broken is not None, "unverifiable write marks the disk broken")
    try:
        disk2.write(b"r")
        check(False, "no writes after the disk is broken")
    except DiskError:
        check(True, "no writes after the disk is broken")

    # 6. An image opened read-only reports write protection, like a covered notch.
    import os
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="drivetest"), "a.img")
    with open(path, "wb") as f:
        f.write(b"\0" * (4 * 2 * 1024))
    img = ImageBackend(path, 4, 2, 1024)
    img.readonly = True
    check(img.write_protected(), "read-only image reports write protection")
    os.remove(path)

    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
