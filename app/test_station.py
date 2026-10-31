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
    json.dump({"left": "A", "mountpoint": m}, open(os.path.join(cfgdir, "settings.json"), "w"))
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
