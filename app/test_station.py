"""End-to-end test of the window's server: no hardware is touched.

Starts station.py with a temporary settings folder and library, points both drives at
backup images, and drives the server through its own API the way the page does: state,
start (the bridge then serves the images through FUSE), reads and a save through the files,
the drive state it reports, stop, goodbye, and the program ending by itself.
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
from typing import Any, Callable, Dict, List

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


class Alive:
    def poll(self) -> None:
        return None


def label_read_once(d: str) -> None:
    """The window refreshes every second; an unreadable disk must not be read every time."""
    os.environ.update(XDG_CONFIG_HOME=d, APPDATA=d, HOME=d, USERPROFILE=d)
    import station
    reads: List[str] = []

    def unreadable(path: str) -> str:
        reads.append(path)
        return ""
    station.disk_label = unreadable
    st = station.Station()
    st.bridge.proc = Alive()  # type: ignore[assignment]
    st.bridge._parse("ready")
    st.bridge._parse("slot FD1 disk=1 protected=0")
    st.bridge._parse("slot FD2 disk=0 protected=0")
    st.state()
    st.state()
    st.state()
    check(len(reads) == 1, "an unreadable disk is read once, not on every refresh")
    st.bridge._parse("slot FD1 disk=1 protected=0")
    st.state()
    check(len(reads) == 2, "a new disk gets its one read")


def main() -> int:
    label_read_once(tempfile.mkdtemp(prefix="stationlabel"))
    import station
    base = tempfile.mkdtemp(prefix="stationra")
    open(os.path.join(base, "np2kai_libretro.so"), "w").close()
    open(os.path.join(base, "np2kai_libretro.dll"), "w").close()
    open(os.path.join(base, "np2kai_libretro.dylib"), "w").close()
    station.find_retroarch = lambda: station.RetroArch(["retroarch"], base, base)
    cmd = station.emulator_command(station.Config.load())
    assert isinstance(cmd, list)
    extra = next((c.split("=", 1)[1] for c in cmd if c.startswith("--appendconfig=")), "")
    check(cmd[-1].endswith("play.cmd") and os.path.isfile(extra), "RetroArch starts with this launch's own settings")
    check('input_auto_game_focus = "1"' in open(extra).read() and "config_save_on_exit" in open(extra).read(),
          "the keyboard goes to the game, and the user's own settings stay as they are")
    shutil.rmtree(base, ignore_errors=True)
    d = tempfile.mkdtemp(prefix="stationtest")
    lib = os.path.join(d, "library")
    os.makedirs(lib)
    m = os.path.join(d, "m")
    a, b = os.path.join(lib, "TEST-No1.hdm"), os.path.join(lib, "TEST-No2.hdm")
    da, db = disk(b"TEST-No1"), disk(b"TEST-No2")
    open(a, "wb").write(da)
    open(b, "wb").write(db)
    os.chmod(a, 0o444)                                   # a covered notch
    cfgdir = os.path.join(d, "cfg", "PC-98 Floppy Station" if sys.platform == "win32" else "pc98-floppy-station")
    os.makedirs(cfgdir)
    json.dump({"mountpoint": m, "library": lib}, open(os.path.join(cfgdir, "settings.json"), "w"))
    env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(d, "cfg"), APPDATA=os.path.join(d, "cfg"), HOME=d,
               USERPROFILE=d, PC98_STATION_PORT="9811")
    log = open(os.path.join(d, "log"), "w+")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "station.py"), "--no-browser"],
                         stdout=log, stderr=subprocess.STDOUT, env=env)
    url = ""
    try:
        def got_url() -> bool:
            nonlocal url
            log.flush()
            found = re.findall(r"http://[^\s]+", open(log.name).read())
            url = found[-1] if found else ""
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

        def post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
            req = urllib.request.Request(url + path, data=json.dumps(body).encode(),
                                         headers={"X-Token": token, "Content-Type": "application/json"})
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
        bad = urllib.request.Request(url + "api/start", data=b"{}", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(bad, timeout=5)
            check(False, "actions need the token")
        except urllib.error.HTTPError as e:
            check(e.code == 403, "actions need the token")

        s = get("api/state")
        check(s.get("app") == "PC-98 Floppy Station" and bool(s.get("version")), "state names the program and version")
        check(s["running"] is False and s["driver"]["ok"] is True, "idle at start, driver found")
        check(s["library"]["images"] == ["TEST-No1.hdm", "TEST-No2.hdm"], "the library lists its images")
        check(post("api/start", {}).get("message") == "identify the left drive first", "no start before the drives are known")

        # backups standing in for both drives: by name from the library, and by full path
        check("isn't in the library" in post("api/settings", {"image": {"FD1": "nothing.hdm"}})["message"],
              "an unknown image is refused")
        check("same image" in post("api/settings", {"image": {"FD1": "TEST-No1.hdm", "FD2": "TEST-No1.hdm"}})["message"],
              "both drives on one image is refused")
        check(post("api/settings", {"image": {"FD1": "TEST-No1.hdm", "FD2": b}})["message"] == "saved", "images chosen")
        s = get("api/state")
        check(s["drives"]["FD1"]["image_name"] == "TEST-No1.hdm" and s["drives"]["FD1"]["protected"] is True and
              s["drives"]["FD1"]["label"] == "TEST-No1", "a drive shows the image it plays from")
        check(s["drives"]["FD2"]["protected"] is False, "a writable image shows as writable")
        check(post("api/backup", {"name": "FD1"})["message"].endswith("playing from an image already"),
              "no backup of a drive that plays from an image")

        check(post("api/start", {}).get("message") == "starting", "start accepted without drives to identify")
        check(wait_for(lambda: get("api/state")["ready"] is True), "the bridge reports ready")
        s = get("api/state")
        fd1, fd2 = s["drives"]["FD1"]["file"], s["drives"]["FD2"]["file"]
        check(os.path.isfile(fd1) and os.path.isfile(fd2), "both drive files exist in the mount")
        check(open(fd1, "rb").read() == da, "FD1 reads as its image")
        if sys.platform != "win32":                      # WinFsp refuses the open instead, checked below
            check(os.stat(fd1).st_mode & 0o222 == 0, "the protected image gives a read-only file")
        check(open(s["play"]).read() == f"np2kai {fd1} {fd2}\n", "play.cmd names both files")
        check("stop before changing" in post("api/settings", {"image": {"FD1": ""}})["message"],
              "images can't be changed while running")

        save = b"SAVEGAME" * 128
        with open(fd2, "r+b", buffering=0) as f:
            f.seek(40 * 1024)
            f.write(save)
        check(open(b, "rb").read()[40 * 1024:41 * 1024] == db[40 * 1024:41 * 1024], "a save isn't on the image at once")
        check(wait_for(lambda: open(b, "rb").read()[40 * 1024:41 * 1024] == save, 10), "a save reaches the image after the quiet moment")
        check(open(b, "rb").read()[:40 * 1024] == db[:40 * 1024], "only the changed track was written")
        try:
            with open(fd1, "r+b", buffering=0) as f:
                f.write(b"x")
            check(False, "a protected image refuses writes")
        except OSError:
            check(True, "a protected image refuses writes")

        check(post("api/stop", {}).get("message") == "stopped", "stop accepted")
        check(wait_for(lambda: get("api/state")["running"] is False), "stopped")
        check(not os.path.exists(fd1), "the mount is gone after stop")
        check(open(a, "rb").read() == da, "the protected image is untouched")

        check(post("api/settings", {"image": {"FD1": "", "FD2": ""}})["message"] == "saved", "back to the drives")
        check(get("api/state")["drives"]["FD1"]["image"] == "", "drives are drives again")

        if sys.platform == "linux":
            def item(name: str) -> Dict[str, Any]:
                return next((t for t in get("api/state")["setup"] if t["name"] == name), {})
            if not os.path.isdir("/var/lib/flatpak/app/org.libretro.RetroArch"):
                check(item("RetroArch").get("ok") is False and "retroarch.com" in item("RetroArch")["how"],
                      "a missing RetroArch is listed with where to get it")
            base = os.path.join(d, ".var/app/org.libretro.RetroArch/config/retroarch")
            os.makedirs(os.path.join(d, ".local/share/flatpak/app/org.libretro.RetroArch"))
            check(item("PC-98 core").get("ok") is False, "next, a missing core is listed")
            bios = os.path.join(d, "own bios")
            os.makedirs(os.path.join(base, "cores"))
            with open(os.path.join(base, "retroarch.cfg"), "w") as cfg:
                cfg.write(f'system_directory = "{bios}"\n')
            open(os.path.join(base, "cores", "np2kai_libretro.so"), "w").close()
            check(item("PC-98 core").get("ok") is True, "the core's line clears once it's there")
            how = item("BIOS files").get("how", "")
            check(os.path.join(bios, "np2kai") in how and "FONT.ROM" in how,
                  "missing BIOS files are named, with the folder RetroArch's own settings give")
            os.makedirs(os.path.join(bios, "np2kai"))
            for n in ("bios.rom", "ITF.ROM", "sound.rom", "font.bmp"):
                open(os.path.join(bios, "np2kai", n), "w").close()
            check(item("BIOS files").get("ok") is True, "BIOS files are found in either case, with either font")
            check(get("api/state")["emulator"]["found"] is True, "the emulator counts as set up")

        post("api/bye", {"token": token})
        check(wait_for(lambda: p.poll() is not None, 15), "program ends after the page says goodbye")
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait(10)
        if sys.platform != "win32":
            subprocess.run(["fusermount3", "-u", m], check=False, stderr=subprocess.DEVNULL)
    log.flush()
    print("".join("  " + line for line in open(log.name) if "error" in line.lower()))
    shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
