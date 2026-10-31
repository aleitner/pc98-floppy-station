# Floppy bridge: play from the real drives

`floppy_bridge.py` shows the drives as two disk-image files, so an emulator reads and
writes the real floppies. Use copy disks: playing reads a disk over and over.

Status: tested on Linux (SteamOS). **Not yet run on Windows or macOS.**

## Install

All systems need Python 3 and the Python packages:

    python3 -m pip install mfusepy git+https://github.com/keirf/greaseweazle@latest

The Greaseweazle package contains C code, so that step needs a compiler unless a build for
your Python version is already available.

| | Filesystem layer | Compiler for the step above |
|---|---|---|
| Linux | built in (libfuse) | gcc; on SteamOS build the wheel in a container, see below |
| Windows | install WinFsp | Microsoft C++ Build Tools |
| macOS | install FUSE-T, or macFUSE (Apple Silicon needs a reduced-security boot for macFUSE) | `xcode-select --install` |

SteamOS has no compiler: build wheels in a `python:3.14` podman container into
`~/gw-wheel/py314` and install from there. Redo this whenever a system update changes the
Python version, or `gw` fails with "No module named greaseweazle".

The emulator is RetroArch with the Neko Project II kai core, plus the BIOS and font files in
its `system/np2kai` folder.

## Play

    python3 floppy_bridge.py

Left drive (A) becomes FD1, right drive (B) becomes FD2. Swap them with `--fd1 B --fd2 A`, or
use one drive with `--fd2 none`. The files appear in `~/PC98Drives`, or `P:` on Windows.

Then, with the bridge running, load `play.cmd` from that folder in RetroArch using the core:

    flatpak run org.libretro.RetroArch -L ~/.var/app/org.libretro.RetroArch/config/retroarch/cores/np2kai_libretro.so ~/PC98Drives/play.cmd

Start the bridge first: a sandboxed emulator only sees a folder that was already there.

To swap a disk, open the lever, change the disk and close the lever, then answer the game.
Wait a couple of seconds after a save before opening a lever: changes reach the disk about a
second after the game stops writing. If a disk comes out first, those changes are dropped,
never written to the next disk, and the bridge reports it.

Stop: quit the emulator, then `fusermount3 -u ~/PC98Drives` on Linux, or Ctrl-C elsewhere.
Anything unsaved is written first.

## A drive that is off by some cylinders

If a drive reads only noise at the start of a disk but clean data further in, its idea of
track 0 has moved. `--offset B=4` adds 4 steps on drive B, so reads and writes land on the
right tracks. `gw` itself doesn't know about this offset: don't write to
such a drive with `gw`, because the data lands on the wrong tracks.

## Test

`test_bridge.py` runs the bridge end to end on image files, with no drives (Linux).
