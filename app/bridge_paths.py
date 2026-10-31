"""Names and places shared by the bridge and its window. Imports nothing that needs a driver."""
from __future__ import annotations

import errno
import os
import platform

SYSTEM = platform.system()

# cylinders, heads, bytes per track
GEOMETRY = {"pc98.2hd": (77, 2, 8 * 1024), "pc98.2dd": (80, 2, 8 * 512)}
EXT = {"pc98.2hd": ".hdm", "pc98.2dd": ".img"}


def default_mountpoint() -> str:
    return "P:" if SYSTEM == "Windows" else os.path.expanduser("~/PC98Drives")


def cmd_path(mountpoint: str, name: str) -> str:
    if SYSTEM == "Windows":
        return f"{mountpoint}\\{name}"
    return os.path.join(mountpoint, name)


def plain_words(e: BaseException) -> str:
    """A board or drive failure in plain words. The libraries raise system errors as they
    come: a bare errno tuple, a serial exception."""
    text = str(e)
    code = getattr(e, "errno", None)
    if code is None and len(e.args) == 2 and isinstance(e.args[0], int):
        code = e.args[0]                      # termios.error carries (errno, text)
    if "Cannot find" in text or "could not open port" in text or code == errno.ENOENT:
        return "the Greaseweazle isn't connected"
    if code in (errno.EBUSY, errno.EAGAIN) or "busy" in text.lower() or "in use" in text.lower():
        return "the Greaseweazle is in use by another program (gw, or another copy of this one)"
    if code == errno.EACCES or "Permission denied" in text:
        return "no permission to use the Greaseweazle's port" + \
            ("; add yourself to the dialout (or uucp) group and log in again" if SYSTEM == "Linux" else "")
    if code in (errno.EINVAL, errno.ENODEV, errno.EIO, errno.ENXIO):
        return "the Greaseweazle didn't answer; unplug it, plug it in again and try once more"
    return f"couldn't talk to the drives: {text or type(e).__name__}"


def unmount(mountpoint: str) -> None:
    """Ask the system to unmount a bridge folder (used when the bridge can't be told to stop)."""
    import shutil
    import subprocess
    if SYSTEM == "Windows":
        return                                 # WinFsp drops the volume when the process ends
    tool = shutil.which("fusermount3") or shutil.which("fusermount")
    cmd = [tool, "-u", mountpoint] if tool else ["umount", mountpoint]
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
