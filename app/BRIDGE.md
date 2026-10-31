# Playing from the real drives

Two programs here, one job: show the two floppy drives to an emulator as disk image files,
so a game runs from the real disks, with real swaps and real saves.

- `station.py` is the window: drives, Start/Stop, a Play button. This is what most people run.
- `floppy_bridge.py` is the bridge itself, a command-line program the window starts for you.

Use copy disks, not originals. Playing reads a disk over and over.

Status: tested on Linux (SteamOS). **Not yet run on Windows or macOS.**

## Install

A filesystem layer and Python with two packages.

| | Filesystem layer | Compiler for the Python step |
|---|---|---|
| Linux | built in (libfuse, the `fusermount3` command) | gcc; on SteamOS build the wheel in a container, see below |
| Windows | install [WinFsp](https://winfsp.dev/rel/) | Microsoft C++ Build Tools |
| macOS | install [FUSE-T](https://www.fuse-t.org/), or macFUSE (Apple Silicon needs a reduced-security boot for macFUSE) | `xcode-select --install` |

    python3 -m pip install mfusepy git+https://github.com/keirf/greaseweazle@latest

The Greaseweazle package contains C code, so that step needs a compiler unless a build for
your Python version is already available. SteamOS has no compiler: build wheels in a
`python:3.14` podman container into `~/gw-wheel/py314` and install from there. Redo this
whenever a system update changes the Python version.

## The window

    python3 station.py

A page opens in your browser at `http://127.0.0.1:9801` (another port if that one is busy;
the program prints the address). It shows whether the Greaseweazle and the filesystem layer
were found, both drives with their disk state, and a Start button.

**First run:** put a disk in the LEFT drive only, close its lever and press Check. The unit
that holds a disk is remembered as the left drive; it becomes `FD1`. If you ever move the
ribbon, press "Swap left and right".

**Every run:** press one of the two start buttons. The drives appear as `FD1.hdm` and
`FD2.hdm`, with a `play.cmd` beside them. A disk whose write notch is covered shows as
write-protected and the file is read-only, so the game can never write to it.

- **Load into memory** (`loaded_mode.py`) reads each disk in full into `~/PC98Drives` as an
  ordinary file, then watches the files: a save is written back to the floppy, verified,
  about a second after the game stops writing; a swapped disk is read in and its file
  replaced. No driver is needed. The first time a write-protected disk is loaded, its image
  is saved under the disk's own name in `Documents/PC98 Floppies`, the same folder the Back
  up button uses; next time the disk is found there by its first track, spot-checked against
  the drive, and starts in seconds. A writable disk is always read afresh, because stale save
  data must never go back onto it.
- **Play from disk** runs the bridge below: the files are the drives themselves, every read
  goes to the floppy. It needs the driver from the table above. The files appear in
  `~/PC98Drives` (`P:` on Windows).

**Play:** if RetroArch with the Neko Project II kai core is installed, the Play button starts
it with both drives loaded. For any other emulator, open the two files in its first and
second drive as you would any disk image, or enter a command to run under "Use another
emulator", with `{fd1}`, `{fd2}` and `{play}` standing for the files.

Swap a disk by opening the lever, changing the disk and closing the lever, then answer the
game. Wait a couple of seconds after a save before opening a lever: changes reach the disk
about a second after the game stops writing. If a disk comes out first, those changes are
dropped, never written to the next disk, and the log says so.

Stop the bridge before closing the window. Anything unsaved is written first. Once the bridge
is stopped and the window closed, the program ends by itself.

Settings are kept in `~/.config/pc98-floppy-station/settings.json` (Linux),
`%APPDATA%\PC-98 Floppy Station` (Windows) or `~/Library/Application Support/PC-98 Floppy Station` (macOS).

## The bridge on its own

    python3 floppy_bridge.py

Drive A becomes FD1 and drive B FD2. Swap them with `--fd1 B --fd2 A`, or use one drive with
`--fd2 none`. Then, with the bridge running, load `play.cmd` in RetroArch with the core:

    flatpak run org.libretro.RetroArch -L ~/.var/app/org.libretro.RetroArch/config/retroarch/cores/np2kai_libretro.so ~/PC98Drives/play.cmd

Start the bridge first: a sandboxed emulator only sees a folder that was already there.
Stop: quit the emulator, then `fusermount3 -u ~/PC98Drives` on Linux, or Ctrl-C elsewhere.
Progress goes to stdout as lines starting with `STATUS`.

### A drive that is off by some cylinders

If a drive reads only noise at the start of a disk but clean data further in, its idea of
track 0 has moved; the fix is mechanical (the control board has slid). Until it's fixed,
`--offset B=4` adds 4 steps on drive B so reads and writes land on the right tracks. `gw`
itself doesn't know about this offset: don't write to such a drive with `gw`, because the
data lands on the wrong tracks.

## Test

`test_bridge.py` runs the bridge end to end on image files, with no drives (Linux).
