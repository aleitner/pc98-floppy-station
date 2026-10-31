"""End-to-end test of the window's server on image files: no hardware is touched.

Starts station.py with two image files standing in for the drives, then drives it through
its own API the way the page does: state, start, read through the mount, write and see it
reach the image, stop, goodbye, and the program ending by itself.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict

SIZE = 1232 * 1024
HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0


def check(ok: bool, what: str) -> None:
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + what, flush=True)


def wait_for(cond: Callable[[], bool], seconds: float = 10.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def main() -> int:
    d = tempfile.mkdtemp(prefix="stationtest")
    m = os.path.join(d, "m")
    a, b = os.path.join(d, "a.hdm"), os.path.join(d, "b.hdm")
    da, db = os.urandom(SIZE), os.urandom(SIZE)
    open(a, "wb").write(da)
    open(b, "wb").write(db)
    cfgdir = os.path.join(d, "cfg", "pc98-floppy-station")
    os.makedirs(cfgdir)
    lib = os.path.join(d, "library")
    json.dump({"left": "A", "mountpoint": m, "folder": os.path.join(d, "f"), "library": lib},
              open(os.path.join(cfgdir, "settings.json"), "w"))
    env = dict(os.environ, PC98_STATION_IMAGES=f"FD1={a},FD2={b}", XDG_CONFIG_HOME=os.path.join(d, "cfg"))
    log = open(os.path.join(d, "log"), "w+")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "station.py"), "--no-browser"],
                         stdout=log, stderr=subprocess.STDOUT, env=env)
    url = ""
    try:
        def got_url() -> bool:
            nonlocal url
            log.flush()
            mt = re.search(r"http://[^\s]+", open(log.name).read())
            url = mt.group(0) if mt else ""
            return bool(url)
        check(wait_for(got_url), "server starts and prints its address")

        def get(path: str) -> Dict[str, Any]:
            with urllib.request.urlopen(url + path, timeout=5) as r:
                return dict(json.loads(r.read()))

        page = urllib.request.urlopen(url, timeout=5).read().decode()
        tok = re.search(r'TOKEN = "([^"]+)"', page)
        check(tok is not None and "__TOKEN__" not in page, "page carries its token")
        token = tok.group(1) if tok else ""

        def post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
            data = json.dumps(body).encode()
            req = urllib.request.Request(url + path, data=data, headers={"X-Token": token, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return dict(json.loads(r.read()))

        s = get("api/state")
        check(s.get("app") == "PC-98 Floppy Station" and bool(s.get("version")), "state names the program and version")
        check(s["running"] is False and s["driver"]["ok"] is True, "idle at start, driver found")

        bad = urllib.request.Request(url + "api/start", data=b"{}", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(bad, timeout=5)
            check(False, "actions need the token")
        except urllib.error.HTTPError as e:
            check(e.code == 403, "actions need the token")

        check(post("api/start", {}).get("message") == "starting", "start accepted")
        check(wait_for(lambda: get("api/state")["ready"] is True), "bridge reports ready")
        s = get("api/state")
        fd1, fd2 = s["drives"]["FD1"]["file"], s["drives"]["FD2"]["file"]
        check(os.path.exists(fd1) and os.path.exists(fd2), "both drive files exist")
        check(open(fd1, "rb").read(4096) == da[:4096], "reading FD1 gives the disk's bytes")
        check(s["drives"]["FD1"].get("label", "") == "", "a random disk has no name")

        new = b"SAVEGAME" * 128
        with open(fd2, "r+b", buffering=0) as f:
            f.seek(40 * 1024)
            f.write(new)
        check(wait_for(lambda: open(b, "rb").read()[40 * 1024:41 * 1024] == new), "a write reaches the disk image")
        check(open(a, "rb").read() == da, "the other disk is untouched")

        check(post("api/stop", {}).get("message") == "stopped", "stop accepted")
        check(wait_for(lambda: get("api/state")["running"] is False), "bridge stopped")
        check(not os.path.exists(fd1), "files gone after stop")

        # ---- loaded mode: plain files, no driver. a is made read-only = a covered notch.
        da = open(a, "rb").read()
        db = open(b, "rb").read()
        os.chmod(a, 0o444)
        check(post("api/start", {"mode": "loaded"}).get("message") == "reading the disks", "loaded mode starts")
        check(wait_for(lambda: get("api/state")["ready"] is True, 30), "both disks read into memory")
        s = get("api/state")
        lf1, lf2 = s["drives"]["FD1"]["file"], s["drives"]["FD2"]["file"]
        check(s["mode"] == "loaded" and os.path.isfile(lf1) and os.path.isfile(lf2), "plain files exist")
        check(open(lf1, "rb").read() == da and open(lf2, "rb").read() == db, "files hold the disks' bytes")
        check(s["drives"]["FD1"]["protected"] is True and not os.access(lf1, os.W_OK), "protected disk gives a read-only file")
        kept = [p for p in os.listdir(lib) if p.endswith(".hdm")] if os.path.isdir(lib) else []
        check(len(kept) == 1 and open(os.path.join(lib, kept[0]), "rb").read() == da, "the protected disk's image is kept in the library")
        check(not any(open(os.path.join(lib, p), "rb").read() == db for p in kept), "the writable disk is not kept")
        save = b"MEMSAVE!" * 128
        with open(lf2, "r+b", buffering=0) as f:
            f.seek(100 * 1024)
            f.write(save)
        check(wait_for(lambda: open(b, "rb").read()[100 * 1024:101 * 1024] == save, 10), "a save in the file reaches the disk")
        check(open(b, "rb").read()[:100 * 1024] == db[:100 * 1024], "only the changed track was written")
        # swap FD1: a new image under the same name (new inode) is a new disk
        os.chmod(a, 0o644)
        swapped = os.urandom(SIZE)
        tmp = a + ".new"
        open(tmp, "wb").write(swapped)
        os.replace(tmp, a)
        check(wait_for(lambda: open(lf1, "rb").read(1024) == swapped[:1024], 30), "a swapped disk is read in and the file replaced")
        check(wait_for(lambda: get("api/state")["ready"] is True, 30), "ready again after the swap")
        check(post("api/stop", {}).get("message") == "stopped", "loaded mode stops cleanly")
        check(not os.path.exists(lf1) and not os.path.exists(lf2), "loaded files removed after stop")

        post("api/bye", {"token": token})
        check(wait_for(lambda: p.poll() is not None, 15), "program ends after the page says goodbye")
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait(10)
        subprocess.run(["fusermount3", "-u", m], check=False, stderr=subprocess.DEVNULL)
    log.flush()
    print("".join("  " + line for line in open(log.name) if "error" in line.lower()))
    shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
