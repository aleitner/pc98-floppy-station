"""End-to-end test of floppy_bridge.py on image files: no hardware is touched.

Mounts two images, then checks what an emulator depends on: reads match, writes reach
the image and are not seen until the bridge saves them, a swap is seen even for data
already cached, a pending write never lands on the new disk, and unmounting saves.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List

SIZE = 1232 * 1024
HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0


def check(ok: bool, what: str) -> None:
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + what, flush=True)


def wait_for(cond, seconds: float = 5.0) -> bool:  # type: ignore[no-untyped-def]
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def early_disk() -> None:
    """A disk put in before anything has read the drive is reported, though it isn't a swap."""
    import floppy_bridge
    from floppy_drive import TrackDisk
    from test_drive import FakeUSB, gw_backend
    usb = FakeUSB(disk=False)
    usb.latch = True
    be = gw_backend(usb, proven=True)
    be.cyls, be.heads, be.track_bytes = 77, 2, 8192
    slot = floppy_bridge.Slot("FD2", be, TrackDisk(be))
    slot.reported = floppy_bridge.slot_line(slot)
    fs = floppy_bridge.BridgeFS({"/FD2.hdm": slot}, b"")
    said: List[str] = []
    floppy_bridge.status = said.append                 # type: ignore[assignment]
    fs._refresh(slot, force=True)
    check(said == [], "an empty drive stays quiet")
    usb.disk = True
    be._empty_seen = 0.0                               # past the wait between steps
    slot.seen_disk = False
    slot.present = False
    fs._refresh(slot, force=True)
    check(slot.away and said == [], "a disk put in keeps the file away for a moment")
    slot.out_until = 0.0
    fs._refresh(slot, force=True)
    check(said == ["slot FD2 disk=1 protected=0 proven=1"], "and is then reported")
    check(slot.generation == 1, "and doesn't count as a swap")
    check(floppy_bridge.play_line("a b", [slot]) == "np2kai -l a b\n", "a real drive asks for live mode")
    fs._refresh(slot, force=True)
    check(len(said) == 1, "once")
    slot.live, slot.told, slot.out_until = True, False, 0.0
    held = slot.generation
    try:
        fs.write("/FD2.hdm", b"x", 0, held)
        check(False, "a game that missed a swap can't write")
    except Exception:
        check(True, "a game that missed a swap can't write")
    slot.out_until = time.monotonic() + 5
    try:
        fs.getattr("/FD2.hdm")
    except Exception:
        pass
    check(slot.told, "seeing the file gone counts as being told")
    slot.out_until = 0.0


def main() -> int:
    early_disk()
    import floppy_bridge
    from floppy_drive import DiskError
    check("Stop, then Start" in floppy_bridge.said(RuntimeError("Track0 signal absent after seek to cylinder 0\n 1. Try")),
          "a head that lost its place says what to do")
    check(floppy_bridge.said(DiskError(5, "can't read track 3.0")) == "can't read track 3.0", "a disk error says itself")
    check("in use" in floppy_bridge.said(RuntimeError("could not open port 'COM5': PermissionError(13, 'Access is denied.', None, 5)")),
          "a COM port held by another program says so")
    d = tempfile.mkdtemp(prefix="bridgetest")
    m = os.path.join(d, "m")
    a, b = os.path.join(d, "a.hdm"), os.path.join(d, "b.hdm")
    da, db = os.urandom(SIZE), os.urandom(SIZE)
    open(a, "wb").write(da)
    open(b, "wb").write(db)
    log = open(os.path.join(d, "log"), "w+")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "floppy_bridge.py"), "--image", f"FD1={a}",
                          "--image", f"FD2={b}", "--mountpoint", m, "--control-stdin"],
                         stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
    fd1, fd2 = os.path.join(m, "FD1.hdm"), os.path.join(m, "FD2.hdm")
    try:
        check(wait_for(lambda: os.path.exists(fd1)), "files appear")
        check(sorted(os.listdir(m)) == ["FD1.hdm", "FD2.hdm", "play.cmd"], "folder lists both drives and play.cmd")
        check(os.path.getsize(fd1) == SIZE, "file has the disk's exact size")
        cmd = open(os.path.join(m, "play.cmd")).read()
        check(cmd == f"np2kai {fd1} {fd2}\n", "play.cmd names both drives, with no -l for backups")

        # reads, sector by sector like an emulator, across a track boundary
        with open(fd1, "rb", buffering=0) as f:
            f.seek(8192 - 512)
            check(f.read(1024) == da[8192 - 512:8192 + 512], "read across a track boundary")
        check(open(fd2, "rb").read() == db, "whole disk reads back identical")

        # a write lands after the quiet period, and only where it should
        new = b"SAVEGAME" * 128
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(40 * 1024)
            f.write(new)
        check(open(a, "rb").read()[40 * 1024:41 * 1024] == da[40 * 1024:41 * 1024], "write isn't on the disk at once")
        check(wait_for(lambda: open(a, "rb").read()[40 * 1024:41 * 1024] == new), "write reaches the disk")
        cur = open(a, "rb").read()
        check(cur[:40 * 1024] == da[:40 * 1024] and cur[41 * 1024:] == da[41 * 1024:], "nothing else changed")
        with open(fd1, "rb", buffering=0) as f:
            f.seek(40 * 1024)
            check(f.read(1024) == new, "the write reads back through the bridge")

        # swap, while the old contents are cached
        swapped = os.urandom(SIZE)
        tmp = a + ".new"
        open(tmp, "wb").write(swapped)
        time.sleep(0.6)
        os.replace(tmp, a)
        time.sleep(0.6)
        try:
            open(fd1, "rb")
            check(False, "the file is away just after a swap")
        except OSError:
            check(True, "the file is away just after a swap")
        time.sleep(2.2)
        check(open(fd1, "rb").read(1024) == swapped[:1024], "swap seen, even though the track was cached")

        # a pending write must not land on a disk swapped in underneath it
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(80 * 1024)
            f.write(b"PENDING!" * 128)
        third = os.urandom(SIZE)
        open(tmp, "wb").write(third)
        os.replace(tmp, a)
        time.sleep(3.0)
        check(open(a, "rb").read() == third, "pending write never reaches the new disk")
        log.flush()
        check("NOT written" in open(log.name).read(), "the lost write is reported")

        # a program that held the file open across a swap can't write to the new disk
        time.sleep(2.2)
        held = open(fd1, "r+b", buffering=0)
        held.seek(40 * 1024)
        held.read(16)
        fourth = os.urandom(SIZE)
        open(tmp, "wb").write(fourth)
        os.replace(tmp, a)
        time.sleep(0.7)
        try:
            held.seek(40 * 1024)
            held.write(b"OLD-DISK" * 128)
            check(False, "a file opened before a swap can't write")
        except OSError:
            check(True, "a file opened before a swap can't write")
        held.close()
        time.sleep(2.5)
        check(open(a, "rb").read() == fourth, "the new disk is untouched")
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(40 * 1024)
            f.write(b"NEWSAVE!" * 128)
        check(wait_for(lambda: open(a, "rb").read()[40 * 1024:41 * 1024] == b"NEWSAVE!" * 128, 5),
              "a file opened after the swap saves normally")

        # a whole image of another disk stops at its first sector
        with open(fd1, "r+b", buffering=0) as f:
            try:
                f.write(b"\xeb\x3cOTHERDISK" + bytes(1024 - 12))
                check(False, "a write changing the disk's name is refused")
            except OSError:
                check(True, "a write changing the disk's name is refused")

        # with nothing reading, a disk leaving and coming back is still seen
        def seen(text: str, times: int = 1) -> bool:
            log.flush()
            return open(log.name).read().count(text) >= times
        os.rename(b, b + ".out")
        check(wait_for(lambda: seen("slot FD2 disk=0"), 8), "a disk taken out is seen with nothing reading")
        os.rename(b + ".out", b)
        check(wait_for(lambda: seen("slot FD2 disk=1", 2), 10), "and so is one put back")
        time.sleep(0.5)

        # unmounting saves what is still waiting
        with open(fd2, "r+b", buffering=0) as f:
            f.seek(1024)
            f.write(b"LASTSAVE" * 128)
    finally:
        if sys.platform == "win32":                    # no unmount command there
            p.communicate(b"stop\n", timeout=10)
        else:
            subprocess.run(["fusermount3", "-u", m], check=False)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
    check(open(b, "rb").read(2048)[1024:] == b"LASTSAVE" * 128, "unmounting saves pending writes")
    log.flush()
    print("".join("  " + line for line in open(log.name) if "error" in line.lower()))

    # a save that finds the head off its track waits for a later try, and isn't tried every tick
    import floppy_bridge
    from floppy_drive import DiskError, ImageBackend, TrackDisk
    img = os.path.join(d, "waits.hdm")
    open(img, "wb").write(bytes(SIZE))
    be = ImageBackend(img, 77, 2, 8192)

    def off_track(cyl: int, head: int, data: bytes) -> bool:
        raise DiskError(11, f"the head isn't over track {cyl}.{head}; nothing was written")
    be.write_track = off_track                         # type: ignore[method-assign]
    disk = TrackDisk(be)
    disk.write_at(8192 * 10, b"y" * 16)
    slot = floppy_bridge.Slot("FD1", be, disk)
    fs = floppy_bridge.BridgeFS({"/FD1.hdm": slot}, b"")
    check(not fs.flush_now(slot) and disk.dirty_tracks == 1 and not disk.broken, "an off-track save is kept for later")
    check(slot.retry_at - time.monotonic() > floppy_bridge.SAVE_RETRY_SECONDS - 5, "and the next try waits")
    shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
