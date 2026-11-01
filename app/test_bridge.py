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


def main() -> int:
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
        check(cmd == f"np2kai {fd1} {fd2}\n", "play.cmd names both drives")

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
        with open(fd1, "rb") as f:
            f.seek(40 * 1024)
            check(f.read(1024) == new, "the write reads back through the bridge")

        # swap, while the old contents are cached
        swapped = os.urandom(SIZE)
        tmp = a + ".new"
        open(tmp, "wb").write(swapped)
        time.sleep(0.6)
        os.replace(tmp, a)
        time.sleep(0.6)
        check(open(fd1, "rb").read(1024) == swapped[:1024], "swap seen, even though the track was cached")

        # a pending write must not land on a disk swapped in underneath it
        with open(fd1, "r+b", buffering=0) as f:
            f.seek(80 * 1024)
            f.write(b"PENDING!" * 128)
        third = os.urandom(SIZE)
        open(tmp, "wb").write(third)
        os.replace(tmp, a)
        time.sleep(2.0)
        check(open(a, "rb").read() == third, "pending write never reaches the new disk")
        log.flush()
        check("NOT written" in open(log.name).read(), "the lost write is reported")

        # a program that held the file open across a swap can't write to the new disk
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
        time.sleep(1.5)
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
    shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
