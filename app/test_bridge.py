"""End-to-end test of floppy_bridge.py on image files: no hardware is touched.

Mounts two images, then checks what an emulator depends on: reads match, writes reach
the image and are not seen until the bridge saves them, a swap is seen even for data
already cached, a pending write never lands on the new disk, and unmounting saves. The
drives are served as D88 files; a D88 backup with copy protection on it comes through
whole, and a write can't touch the protected sectors.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List

import d88

SIZE = 1232 * 1024
HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0


def check(ok: bool, what: str) -> None:
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + what, flush=True)


def at(x: int) -> int:
    """Where byte x of the sector image is in a served D88 file: each track has a fixed slot,
    and a plain track's sectors sit in it in order, each after its 16-byte header."""
    idx, off = divmod(x, 8192)
    r, inside = divmod(off, 1024)
    return d88.HEADER + idx * d88.SLOT + r * (16 + 1024) + 16 + inside


def as_image(path: str) -> bytes:
    """A served or saved D88 read back as the sector image it holds."""
    img = d88.Image.from_bytes(open(path, "rb").read())
    return b"".join(d88.image_of(t, i // 2, i % 2, 8192, 3) for i, t in enumerate(img.tracks[:154]))


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
    fs = floppy_bridge.BridgeFS({"/FD2.d88": slot}, b"")
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
        fs.write("/FD2.d88", b"x", 0, held)
        check(False, "a game that missed a swap can't write")
    except Exception:
        check(True, "a game that missed a swap can't write")
    slot.out_until = time.monotonic() + 5
    try:
        fs.getattr("/FD2.d88")
    except Exception:
        pass
    check(slot.told, "seeing the file gone counts as being told")
    slot.out_until = 0.0
    slot.read_since = False
    try:
        fs.read("/FD2.d88", 16, 0, slot.generation + 1)
    except Exception:
        pass
    check(not slot.read_since, "a read through a file opened before the swap doesn't count as reading the new disk")
    real = floppy_bridge.from_window
    fs.window_pid = os.getpid()
    floppy_bridge.from_window = lambda pid: pid == os.getpid()
    try:
        fs.read("/FD2.d88", 16, 0, slot.generation)
    except Exception:
        pass
    floppy_bridge.from_window = real
    fs.window_pid = 0
    check(not slot.read_since, "nor does the window reading the disk's name")
    slot.read_since = True
    reads = usb.steps
    slot.present = False
    check(len(fs.read("/FD2.d88", 65536, 0, slot.generation)) == d88.HEADER and usb.steps == reads,
          "a read of an empty drive from its start gets the header only, without touching the drive")
    try:
        fs.read("/FD2.d88", 1024, d88.HEADER, slot.generation)
        check(False, "an empty drive's file can't be read")
    except Exception:
        check(usb.steps == reads, "an empty drive's file reads as not ready, without touching the drive")
    slot.present = True


def protected_backup(d: str) -> None:
    """A D88 backup with copy protection on cylinder 1: served whole, each sector where the
    emulator will find it; a save to a plain track lands in the file; the protection can't
    be written."""
    plain = os.urandom(SIZE)
    tracks = [d88.plain_sectors(i // 2, i % 2, plain[i * 8192:(i + 1) * 8192], 3) for i in range(154)]
    extra = [d88.Sector(1, 0, 0xF0 + k, 4, os.urandom(2048), d88.CRC_ERROR) for k in range(10)]
    tracks[2] = tracks[2][:4] + extra[:5] + tracks[2][4:] + extra[5:]
    path = os.path.join(d, "protected.d88")
    open(path, "wb").write(d88.Image("XAK", 0x20, False, tracks).to_bytes())
    m = os.path.join(d, "m2")
    log = open(os.path.join(d, "log2"), "w+")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "floppy_bridge.py"), "--image", f"FD1={path}",
                          "--fd2", "none", "--mountpoint", m, "--control-stdin"],
                         stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
    fd1 = os.path.join(m, "FD1.d88")
    try:
        check(wait_for(lambda: os.path.exists(fd1)), "a D88 backup is served")
        with open(fd1, "rb", buffering=0) as f:
            f.seek(d88.HEADER + 2 * d88.SLOT)
            served = d88.decode_track(f.read(d88.SLOT))
        check([s.r for s in served] == [1, 2, 3, 4, 0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 5, 6, 7, 8] + list(range(0xF5, 0xFA)),
              "the protected track keeps every sector, in order")
        check(all(s.status == d88.CRC_ERROR for s in served if s.n == 4), "and their CRC errors")
        check(all(s.data == e.data[:len(s.data)] and len(s.data) >= 768 for s, e in
                  zip([s for s in served if s.n == 4], extra[:5] + extra[5:])), "and the start of their data")
        pos, ok = 0, True
        for s in served:                       # Neko Project II looks at a sector only with room for it after
            ok = ok and pos + 16 + s.full <= d88.SLOT
            pos += 16 + len(s.data)
        check(ok, "every sector is where the emulator's search reaches it")
        check(as_image(fd1)[8192 * 2:8192 * 3] == plain[8192 * 2:8192 * 3], "its plain sectors read too")
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(d88.HEADER + 2 * d88.SLOT + 4 * 1040 + 16)
            try:
                f.write(b"CRACKED!")
                check(False, "a write to a protection sector is refused")
            except OSError:
                check(True, "a write to a protection sector is refused")
            before = open(path, "rb").read()
            f.seek(d88.HEADER + 1 * d88.SLOT)                  # track 0.1, plain, then into 1.0, protected
            whole = bytearray(f.read(2 * d88.SLOT))
            whole[16:24] = b"HALFSAVE"
            whole[d88.SLOT + 4 * 1040 + 16:d88.SLOT + 4 * 1040 + 24] = b"CRACKED!"
            f.seek(d88.HEADER + 1 * d88.SLOT)
            try:
                f.write(whole)
                check(False, "a write spanning a plain and a protected track is refused")
            except OSError:
                check(True, "a write spanning a plain and a protected track is refused")
            time.sleep(1.6)
            f.seek(d88.HEADER + 1 * d88.SLOT + 16)
            check(f.read(8) != b"HALFSAVE" and open(path, "rb").read() == before,
                  "and none of it lands, not even the plain part")
            f.seek(at(20 * 8192 + 3 * 1024))
            f.write(b"D88SAVE!" * 128)
        check(wait_for(lambda: as_image(path)[20 * 8192 + 3 * 1024:20 * 8192 + 4 * 1024] == b"D88SAVE!" * 128),
              "a save reaches the D88 file in place")
        check(d88.Image.from_bytes(open(path, "rb").read()).tracks[2] == d88.Image.from_bytes(
            d88.Image("XAK", 0x20, False, tracks).to_bytes()).tracks[2], "the file keeps its protected track")
    finally:
        if sys.platform == "win32":
            p.communicate(b"stop\n", timeout=10)
        else:
            subprocess.run(["fusermount3", "-u", m], check=False)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


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
    fd1, fd2 = os.path.join(m, "FD1.d88"), os.path.join(m, "FD2.d88")
    try:
        check(wait_for(lambda: os.path.exists(fd1)), "files appear")
        check(sorted(os.listdir(m)) == ["FD1.d88", "FD2.d88", "play.cmd"], "folder lists both drives and play.cmd")
        check(os.path.getsize(fd1) == d88.HEADER + 154 * d88.SLOT, "file has a slot for every track")
        cmd = open(os.path.join(m, "play.cmd")).read()
        check(cmd == f"np2kai {fd1} {fd2}\n", "play.cmd names both drives, with no -l for backups")

        # reads, sector by sector like an emulator, and the header
        with open(fd1, "rb", buffering=0) as f:
            head = f.read(d88.HEADER)
            check(head[0x1B] == 0x20 and head[0x1A] == 0 and head[:3] == b"FD1", "the header says 2HD, writable")
            f.seek(at(8192 + 1024))
            check(f.read(1024) == da[8192 + 1024:8192 + 2048], "a sector reads at its place in its track's slot")
        check(as_image(fd2) == db, "whole disk reads back identical")

        # a write lands after the quiet period, and only where it should
        new = b"SAVEGAME" * 128
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(at(40 * 1024))
            f.write(new)
        check(open(a, "rb").read()[40 * 1024:41 * 1024] == da[40 * 1024:41 * 1024], "write isn't on the disk at once")
        check(wait_for(lambda: open(a, "rb").read()[40 * 1024:41 * 1024] == new), "write reaches the disk")
        cur = open(a, "rb").read()
        check(cur[:40 * 1024] == da[:40 * 1024] and cur[41 * 1024:] == da[41 * 1024:], "nothing else changed")
        with open(fd1, "rb", buffering=0) as f:
            f.seek(at(40 * 1024))
            check(f.read(1024) == new, "the write reads back through the bridge")

        # Neko Project II saves by writing a whole track's slot back
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(d88.HEADER + 6 * d88.SLOT)
            whole = bytearray(f.read(d88.SLOT))
            whole[16 + 1040 * 2:16 + 1040 * 2 + 8] = b"WHOLESLT"
            f.seek(d88.HEADER + 6 * d88.SLOT)
            f.write(whole)
        check(wait_for(lambda: open(a, "rb").read()[6 * 8192 + 2048:6 * 8192 + 2056] == b"WHOLESLT"),
              "a whole slot written back saves the sector it changed")
        with open(fd1, "r+b", buffering=0) as f:
            for where, what, why in ((0x1A, b"\x10", "the header"), (d88.HEADER + 7 * d88.SLOT + 2, b"\x09", "a sector's ID"),
                                     (d88.HEADER + 7 * d88.SLOT + 1040 + 6, b"\x40", "a sector's density")):
                try:
                    f.seek(where)
                    f.write(what)
                    check(False, f"a write changing {why} is refused")
                except OSError:
                    check(True, f"a write changing {why} is refused")

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
        with open(fd1, "rb", buffering=0) as f:
            f.seek(at(0))
            check(f.read(1024) == swapped[:1024], "swap seen, even though the track was cached")

        # a pending write must not land on a disk swapped in underneath it
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(at(80 * 1024))
            f.write(b"PENDING!" * 128)
        third = os.urandom(SIZE)
        open(tmp, "wb").write(third)
        os.replace(tmp, a)
        time.sleep(3.0)
        check(open(a, "rb").read() == third, "pending write never reaches the new disk")
        log.flush()
        check("NOT written" in open(log.name).read(), "the lost write is reported")

        # an emulator putting back a track it kept from the old disk, as it ejects it, is refused
        time.sleep(2.2)
        fifth = os.urandom(SIZE)
        open(tmp, "wb").write(fifth)
        os.replace(tmp, a)
        time.sleep(2.7)
        try:
            with open(fd1, "r+b", buffering=0) as f:
                f.seek(at(40 * 1024))
                f.write(b"KEPTBACK" * 128)
            check(False, "a write before anything was read from the new disk is refused")
        except OSError:
            check(True, "a write before anything was read from the new disk is refused")
        time.sleep(1.5)
        check(open(a, "rb").read() == fifth, "and the new disk is untouched")

        # a program that held the file open across a swap can't write to the new disk
        time.sleep(2.2)
        held = open(fd1, "r+b", buffering=0)
        held.seek(at(40 * 1024))
        held.read(16)
        fourth = os.urandom(SIZE)
        open(tmp, "wb").write(fourth)
        os.replace(tmp, a)
        time.sleep(0.7)
        try:
            held.seek(at(40 * 1024))
            held.write(b"OLD-DISK" * 128)
            check(False, "a file opened before a swap can't write")
        except OSError:
            check(True, "a file opened before a swap can't write")
        held.close()
        time.sleep(2.5)
        check(open(a, "rb").read() == fourth, "the new disk is untouched")
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(at(40 * 1024))
            f.read(16)                                 # a game reads before it saves
            f.seek(at(40 * 1024))
            f.write(b"NEWSAVE!" * 128)
        check(wait_for(lambda: open(a, "rb").read()[40 * 1024:41 * 1024] == b"NEWSAVE!" * 128, 5),
              "a file opened after the swap saves normally")

        # a whole image of another disk stops at its first sector
        with open(fd1, "r+b", buffering=0) as f:
            try:
                f.seek(at(0))
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
            f.seek(at(1024))
            f.read(16)
            f.seek(at(1024))
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
    fs = floppy_bridge.BridgeFS({"/FD1.d88": slot}, b"")
    check(not fs.flush_now(slot) and disk.dirty_tracks == 1 and not disk.broken, "an off-track save is kept for later")
    check(slot.retry_at - time.monotonic() > floppy_bridge.SAVE_RETRY_SECONDS - 5, "and the next try waits")
    protected_backup(d)
    shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
