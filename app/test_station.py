"""End-to-end test of the window's server: no hardware is touched.

Starts station.py with a temporary settings folder and library, then drives it through its
own API the way the page does: state, choosing backup images for both drives, start (which
needs no driver when both drives are images), reads and a save through the files, stop,
goodbye, and the program ending by itself.
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


def disk(name: bytes) -> bytes:
    body = bytearray(os.urandom(SIZE))
    body[0:3] = b"\xeb\x3c\x90"
    body[3:11] = name.ljust(8)
    return bytes(body)


def main() -> int:
    d = tempfile.mkdtemp(prefix="stationtest")
    lib = os.path.join(d, "library")
    os.makedirs(lib)
    a, b = os.path.join(lib, "TEST-No1.hdm"), os.path.join(lib, "TEST-No2.hdm")
    da, db = disk(b"TEST-No1"), disk(b"TEST-No2")
    open(a, "wb").write(da)
    open(b, "wb").write(db)
    os.chmod(a, 0o444)                                   # a covered notch
    cfgdir = os.path.join(d, "cfg", "pc98-floppy-station")
    os.makedirs(cfgdir)
    json.dump({"left": "A", "mountpoint": os.path.join(d, "m"), "library": lib},
              open(os.path.join(cfgdir, "settings.json"), "w"))
    env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(d, "cfg"), HOME=d)
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
        check(s["running"] is False, "idle at start")
        check(s["library"]["images"] == ["TEST-No1.hdm", "TEST-No2.hdm"], "the library lists its images")

        bad = urllib.request.Request(url + "api/start", data=b"{}", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(bad, timeout=5)
            check(False, "actions need the token")
        except urllib.error.HTTPError as e:
            check(e.code == 403, "actions need the token")

        # choose backups for both drives: by name from the library, and by full path
        check("isn't in the library" in post("api/settings", {"image": {"FD1": "nothing.hdm"}})["message"],
              "an unknown image is refused")
        check(post("api/settings", {"image": {"FD1": "TEST-No1.hdm", "FD2": b}})["message"] == "saved", "images chosen")
        s = get("api/state")
        check(s["drives"]["FD1"]["image_name"] == "TEST-No1.hdm" and s["drives"]["FD1"]["protected"] is True and
              s["drives"]["FD1"]["label"] == "TEST-No1", "a drive shows the image it plays from")
        check(s["drives"]["FD2"]["protected"] is False, "a writable image shows as writable")
        check(s["driver"]["needed"] is False, "no driver needed when both drives are images")

        check(post("api/start", {}).get("message") == "starting", "start accepted")
        check(wait_for(lambda: get("api/state")["ready"] is True), "ready")
        s = get("api/state")
        fd1, fd2 = s["drives"]["FD1"]["file"], s["drives"]["FD2"]["file"]
        check(os.path.isfile(fd1) and os.path.isfile(fd2), "both drive files exist")
        check(open(fd1, "rb").read() == da, "FD1 reads as its image")
        check(not os.access(fd1, os.W_OK), "the protected image gives a read-only file")
        play = open(s["play"]).read()
        check(play == f"np2kai {fd1} {fd2}\n", "play.cmd names both files")
        check(post("api/backup", {"name": "FD1"})["message"].endswith("playing from an image already"),
              "no backup of a drive that plays from an image")

        save = b"SAVEGAME" * 128
        with open(fd2, "r+b", buffering=0) as f:
            f.seek(40 * 1024)
            f.write(save)
        check(wait_for(lambda: open(b, "rb").read()[40 * 1024:41 * 1024] == save, 5), "a save reaches the image")
        check(open(b, "rb").read()[:40 * 1024] == db[:40 * 1024], "the rest of the image is untouched")
        check("stop before changing" in post("api/settings", {"image": {"FD1": ""}})["message"],
              "images can't be changed while running")

        check(post("api/stop", {}).get("message") == "stopped", "stop accepted")
        check(wait_for(lambda: get("api/state")["running"] is False), "stopped")
        check(not os.path.lexists(fd1) and not os.path.lexists(fd2), "files gone after stop")
        check(open(b, "rb").read()[40 * 1024:41 * 1024] == save, "the save stays in the library image")

        check(post("api/settings", {"image": {"FD1": "", "FD2": ""}})["message"] == "saved", "back to the drives")
        s = get("api/state")
        check(s["drives"]["FD1"]["image"] == "" and s["driver"]["needed"] is True, "drives need the driver again")

        post("api/bye", {"token": token})
        check(wait_for(lambda: p.poll() is not None, 15), "program ends after the page says goodbye")
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait(10)
    log.flush()
    print("".join("  " + line for line in open(log.name) if "error" in line.lower()))
    shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
