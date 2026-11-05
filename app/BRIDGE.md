# Playing from the real drives

Two programs here, one job: show the two floppy drives to an emulator as disk image files,
so a game runs from the real disks, with real swaps and real saves.

- `station.py` is the window: drives, Start/Stop, a Play button. This is what most people run.
- `floppy_bridge.py` is the bridge itself, a command-line program the window starts for you.

Use copy disks, not originals. Playing reads a disk over and over.

Status: on Linux (SteamOS), playing, saving and loading work from real disks. On Windows 11,
playing and disk swaps have worked, but **saving to a real disk hasn't been tested yet**.
**Not yet run on macOS.**

## Install

A filesystem layer and Python with a few packages.

| | Filesystem layer | Compiler for the Python step |
|---|---|---|
| Linux | built in (libfuse, the `fusermount3` command) | gcc; on SteamOS build the wheel in a container, see below |
| Windows | install [WinFsp](https://winfsp.dev/rel/) | Microsoft C++ Build Tools |
| macOS | install [FUSE-T](https://www.fuse-t.org/), or macFUSE (Apple Silicon needs a reduced-security boot for macFUSE) | `xcode-select --install` |

    python3 -m pip install git+https://github.com/pyserial/pyserial@70d188643b031d10d2a2b9ea880bd56789fdb1f6
    python3 -m pip install mfusepy git+https://github.com/keirf/greaseweazle@latest

The first line matters on a system with glibc 2.42 or newer (SteamOS, Arch, Fedora 43…): the
released pyserial 3.5 can't set the control baud rates the board listens for there, and every
attempt to open the drives ends in "(22, 'Invalid argument')". The Greaseweazle package
contains C code, so the second step needs a compiler unless a build for
your Python version is already available. SteamOS has no compiler: build wheels in a
`python:3.14` podman container into `~/gw-wheel/py314` and install from there. Redo this
whenever a system update changes the Python version.

## The window

    python3 station.py

A window opens: a bare browser window where a Chromium-family browser is installed, otherwise
a browser tab, at `http://127.0.0.1:9801`. It shows whether the Greaseweazle and the filesystem
layer were found, both drives with their disk state, and a Start button. Anything missing,
including RetroArch, the core and the BIOS files, is listed at the top with what to do, and
its line turns OK by itself once it's done. Starting the
program a second time only brings the window back.

**First run:** put a disk in the LEFT drive only, close its lever and press Check. The unit
that holds a disk is remembered as the left drive; it becomes `FD1`. If you ever move the
ribbon, press "Swap left and right".

**Every run:** press Start. The drives appear as `FD1.d88` and `FD2.d88` in `~/PC98Drives`
(`P:` on Windows), with a `play.cmd` beside them. A D88 image keeps every sector with its ID
and the status a read of it gives, so a disk's copy protection reaches the game the way it
reaches a real PC-98; a plain `.hdm` can't, and a game that checks then refuses to go on.
A disk whose write notch is covered shows as write-protected and the file is read-only, so the
game can never write to it. On Windows the file doesn't carry the read-only flag: opening it for
writing is refused instead. The RetroArch core tests exactly that, but an emulator that only
reads the flag will show the disk as writable and report an error on a save.

**Backups:** each drive has *Back up this disk*, which reads every track once, a few turns of
it, and keeps that read twice over: a D88 image under the disk's own name, and beside it the
raw flux (`.scp`, everything the head picked up, so nothing ever needs reading from the
original again). Each game has a folder in `Documents/PC98 Floppies`: a backup goes in
the one holding that game's other disks (`Xak2-No3` joins `Xak2-No1` and `Xak2-No2`), or a
new one named for the game. The read goes three cylinders past the format's last, where
protection sometimes hides. *Use a backup instead* lists the images in the library and its
game folders, `.d88` and `.hdm` alike, a game's `Saves` folder included: pick an image and the
drive plays from the file rather than the floppy; saves then land in the file. *Use the drive* switches back.
An image goes through the same bridge as a drive, so the emulator always sees the same two
files, and a read-only image shows as a write-protected disk.

A backup whose read had unreadable tracks is named for it, e.g. `Xak2-No2 (3 unreadable
tracks).d88`, with only the sectors that did read in those tracks, so it is never mistaken
for a clean one. If track 0's sectors say they belong to another cylinder, the backup stops at
once: the drive's head is that far off, and a disk made on another machine won't read until
the drive is realigned.

**Play:** if RetroArch with the Neko Project II kai core is installed, the Play button starts
it with both drives loaded. For any other emulator, open the two files in its first and
second drive as you would any disk image, or enter a command to run under "Use another
emulator", with `{fd1}`, `{fd2}` and `{play}` standing for the files.

Swap a disk by opening the lever, changing the disk and closing the lever, then answer the
game. Wait a couple of seconds after a save before opening a lever: changes reach the disk
about a second after the game stops writing. If a disk comes out first, those changes are
dropped, never written to the next disk, and the log says so.

Games started with Play get the whole keyboard, since PC-98 games use keys RetroArch keeps for
itself: F10 hands it back to RetroArch and F10 again returns it. Without a core that has `-l`,
reads stop the sound and picture for a moment, and a game waiting for a disk change may need
the emulator's own menu: F12, FDD, FDD1, Open, `FD1.d88`.

Stop writes anything unsaved first. Closing the window ends the program a few seconds later;
the drives are stopped first, with anything pending written. Ctrl-C in a terminal does the
same, and the window closes by itself.

Settings are kept in `~/.config/pc98-floppy-station/settings.json` (Linux), with `station.log` beside it,
`%APPDATA%\PC-98 Floppy Station` (Windows) or `~/Library/Application Support/PC-98 Floppy Station` (macOS).
A drive whose track 0 has drifted (below) gets its steps there too: `"offsets": {"B": 4}`.

## What protects your disks

- A covered write notch is enforced by the drive itself. The bridge also shows such a disk as
  a read-only file, so an emulator never tries.
- The first write to a disk is only accepted after the drive has read that disk's track 0 with
  the headers the decoder expects. A drive whose home position has slipped is refused.
- Before a track is written, the headers under the head are read, as the PC-98's own controller
  did before every sector. If they belong to another track, the head is sent home and looked at
  again; if it's still off, nothing is written and the save waits 30 seconds for another try.
- Every written track is read back. If it doesn't match, the disk is marked broken and no more
  writes go to it.
- Changes that haven't reached the disk yet are never written to a disk swapped in underneath them.
  The file goes away while no disk is in, and for two seconds after a swap, like a drive that
  isn't ready, so nothing can write in that gap. A file opened before a swap can't write
  afterwards, and a write that would change the disk's own name in its boot sector is refused,
  along with everything after it, until the next swap.
- After a swap, nothing is written until the emulator has read from the new disk. A game reads
  a disk before saving to it; an emulator that kept a changed track of the old disk in memory
  puts it back as it lets go of that disk, and that write would land on the new one.
- A track some of whose sectors won't read is served as it reads, each bad sector with the
  error a PC-98 would get, since that is what copy protection often is. Such a track is never
  written. A track whose sectors all name another cylinder is the head in the wrong place, and
  reads as an error.

Two limits. The drives are served as cylinders 0 to 76, the format's own, so anything a backup
found past them isn't played. And Neko Project II keeps a changed D88 track in memory and writes
it to the file later, so when the bridge has to refuse that write, the game has already been
told the save worked: the window's log is where a refused save shows. Without `-l` the core
writes the track back only when the game moves to another track or the disk is ejected, which
is why a save made shortly before a swap is refused on a core without it.
- Eight failed reads within ten minutes point at dirty heads or a failing disk, so that disk is
  left alone, no more reads or writes, until it's taken out and put back.
- A drive stays read-only until it has been seen empty once, which proves it can report a swap.
  With the bridge on its own, name proven drives with `--proven AB`.
- A write rebuilds a whole track, so a track holding more than plain sectors, usually copy
  protection, can't be written. The D88 file shows it whole; a write that would change anything
  but a plain sector's data, a sector's ID, the layout or the header, is refused.
- A track that wouldn't read isn't tried again for 30 seconds and can't be written until the disk
  is changed. A backup stops after 8 unreadable tracks in a row.
- Saves are written last track first, so an interrupted save can't leave a directory naming
  data that isn't there yet.
- Backup only reads. The bridge writes only tracks the emulator changed.

Software can't protect against a dirty or damaged head, which scratches a disk in a few passes.
Clean both heads with 90 % or stronger isopropyl alcohol and let them dry, test on a blank, and
read an original once.

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

`test_drive.py` checks the disk layer with a fake drive, `test_bridge.py` runs the bridge end to
end on image files through the driver, and `test_station.py` drives the window's server through
its API with backups standing in for both drives, through the real bridge. None touches
hardware. All three run in CI.
