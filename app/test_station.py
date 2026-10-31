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
        starts = 1

        def got_url() -> bool:
            # the log keeps every address ever printed; the newest server is the last one
            nonlocal url
            log.flush()
            found = re.findall(r"http://[^\s]+", open(log.name).read())
            url = found[-1] if len(found) >= starts else ""
            return bool(url)
        check(wait_for(got_url), "server starts and prints its address")

        page = urllib.request.urlopen(url, timeout=5).read().decode()
        tok = re.search(r'TOKEN = "([^"]+)"', page)
        check(tok is not None and "__TOKEN__" not in page, "page carries its token")
        token = tok.group(1) if tok else ""

        def get(path: str, with_token: bool = True) -> Dict[str, Any]:
            req = urllib.request.Request(url + path, headers={"X-Token": token} if with_token else {})
            with urllib.request.urlopen(req, timeout=5) as r:
                return dict(json.loads(r.read()))

        check(get("api/ping", with_token=False).get("app") == "PC-98 Floppy Station", "ping answers without a token")
        try:
            get("api/state", with_token=False)
            check(False, "state needs the token")
        except urllib.error.HTTPError as e:
            check(e.code == 403, "state needs the token")
        wrong = urllib.request.Request(url + "api/ping", headers={"Host": "evil.example:9801"})
        try:
            urllib.request.urlopen(wrong, timeout=5)
            check(False, "a request for another host name is refused")
        except urllib.error.HTTPError as e:
            check(e.code == 421, "a request for another host name is refused")

        def post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
            data = json.dumps(body).encode()
            req = urllib.request.Request(url + path, data=data, headers={"X-Token": token, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return dict(json.loads(r.read()))

        s = get("api/state")
        check(s.get("app") == "PC-98 Floppy Station" and bool(s.get("version")), "state names the program and version")
        check(s["running"] is False, "idle at start")
        check(wait_for(lambda: get("api/state")["driver"]["checked"] is True, 60), "driver check finishes")
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
        check("same image" in post("api/settings", {"image": {"FD1": "TEST-No1.hdm", "FD2": "TEST-No1.hdm"}})["message"],
              "both drives on one image is refused")
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
        time.sleep(0.5)
        check(open(b, "rb").read() == db, "the library image is untouched while playing (the copy holds the save)")
        check("stop before changing" in post("api/settings", {"image": {"FD1": ""}})["message"],
              "images can't be changed while running")

        check(post("api/stop", {}).get("message") == "stopped", "stop accepted")
        check(wait_for(lambda: get("api/state")["running"] is False), "stopped")
        check(not os.path.lexists(fd1) and not os.path.lexists(fd2), "files gone after stop")
        after = open(b, "rb").read()
        check(after[40 * 1024:41 * 1024] == save and after[:40 * 1024] == db[:40 * 1024], "the save is written back to the library image on stop")
        check(open(a, "rb").read() == da, "the protected image is untouched")

        # a run that never reached Stop: leftover copy with changes is written back at the next start
        check(post("api/start", {}).get("message") == "starting", "start again")
        check(wait_for(lambda: get("api/state")["ready"] is True), "ready again")
        crash_save = b"CRASHSAV" * 128
        with open(fd2, "r+b", buffering=0) as f:
            f.seek(60 * 1024)
            f.write(crash_save)
        p.kill()
        p.wait(10)
        check(os.path.isfile(fd2), "the changed copy survives a crash")
        log.flush()
        p = subprocess.Popen([sys.executable, os.path.join(HERE, "station.py"), "--no-browser"],
                             stdout=log, stderr=subprocess.STDOUT, env=env)
        url = ""
        starts = 2
        check(wait_for(got_url), "server starts again")
        page = urllib.request.urlopen(url, timeout=5).read().decode()
        tok = re.search(r'TOKEN = "([^"]+)"', page)
        token = tok.group(1) if tok else ""
        check(post("api/start", {}).get("message") == "starting", "start after the crash")
        check(wait_for(lambda: get("api/state")["ready"] is True), "ready after the crash")
        check(open(b, "rb").read()[60 * 1024:61 * 1024] == crash_save, "the crashed run's save was recovered into the image")
        check(open(fd2, "rb").read()[60 * 1024:61 * 1024] == crash_save, "and the new copy starts from it")
        check(post("api/stop", {}).get("message") == "stopped", "stop again")

        # write-back that cannot happen: the library folder is made read-only before Stop.
        # The changed copy must survive, and go back once the folder is writable again.
        check(post("api/start", {}).get("message") == "starting", "start for the write-back failure")
        check(wait_for(lambda: get("api/state")["ready"] is True), "ready for the write-back failure")
        blocked = b"BLOCKED!" * 128
        with open(fd2, "r+b", buffering=0) as f:
            f.seek(70 * 1024)
            f.write(blocked)
        os.chmod(lib, 0o555)
        try:
            msg = post("api/stop", {}).get("message", "")
            check("could not be written back" in msg, "stop says the save could not be written back")
            check(os.path.isfile(fd2) and open(fd2, "rb").read()[70 * 1024:71 * 1024] == blocked, "the changed copy is kept")
            check(open(b, "rb").read()[70 * 1024:71 * 1024] != blocked, "the library image is untouched")
        finally:
            os.chmod(lib, 0o755)
        check(post("api/start", {}).get("message") == "starting", "start after the folder is writable again")
        check(wait_for(lambda: get("api/state")["ready"] is True), "ready after recovery")
        check(open(b, "rb").read()[70 * 1024:71 * 1024] == blocked, "the kept copy was written back at the next start")
        check(post("api/stop", {}).get("message") == "stopped", "stop cleanly after recovery")

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
