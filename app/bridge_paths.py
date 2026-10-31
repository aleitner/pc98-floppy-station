"""Names and places shared by the bridge and its window. Imports nothing that needs a driver."""
from __future__ import annotations

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
