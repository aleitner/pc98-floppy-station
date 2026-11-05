"""D88 disk images: every sector with its own header, as the PC-98 emulators keep them.

A plain sector image (.hdm) is just the sectors' bytes one after another. A D88 also keeps
each sector's ID (cylinder, head, number, size code), whether its data mark was deleted,
and the status the disk controller reported reading it, such as a data CRC error. Copy
protection lives in exactly those things: extra sectors with odd numbers, sectors claiming
to be larger than the space they have, data that never reads without an error. A game
that checks for them only runs from an image that keeps them.

  header    688 bytes: name, write-protect flag, media type, size, 164 track offsets
  track     its sectors back to back, each a 16-byte header and its data
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Dict, List, Protocol, Sequence, Tuple

HEADER = 0x2B0
TRACKS = 164
SLOT = 0x6000                  # what Neko Project II reads of one track at most
MEDIA = {"pc98.2hd": 0x20, "pc98.2dd": 0x10}
SIZE_CODE = {"pc98.2hd": 3, "pc98.2dd": 2}
PROTECT = 0x10
DELETED = 0x10
CRC_ERROR = 0xB0               # the PC-98 BIOS's code for a data CRC error
_SEC = struct.Struct("<4BHBBB5xH")


@dataclass
class Sector:
    c: int
    h: int
    r: int
    n: int
    data: bytes
    status: int = 0
    deleted: bool = False

    @property
    def id(self) -> Tuple[int, int, int, int]:
        return self.c, self.h, self.r, self.n

    @property
    def full(self) -> int:
        """The size its N claims, which an emulator looks for room for."""
        return 128 << min(self.n, 8)


def plain_sectors(cyl: int, head: int, image: bytes, n: int) -> List[Sector]:
    """A plain track's sectors, numbered from 1, cut from its image bytes."""
    size = 128 << n
    return [Sector(cyl, head, i + 1, n, bytes(image[i * size:(i + 1) * size])) for i in range(len(image) // size)]


def plain_ids(cyl: int, head: int, track_bytes: int, n: int) -> List[Tuple[int, int, int, int]]:
    return [(cyl, head, r, n) for r in range(1, track_bytes // (128 << n) + 1)]


def is_plain(sectors: Sequence[Sector], cyl: int, head: int, track_bytes: int, n: int) -> bool:
    """Exactly the format's sectors, each once, readable and not deleted: what a sector image
    holds. In whatever order they come round; some disks have one out of turn."""
    return (sorted(s.id for s in sectors) == plain_ids(cyl, head, track_bytes, n) and
            all(s.status == 0 and not s.deleted and len(s.data) == s.full for s in sectors))


def image_of(sectors: Sequence[Sector], cyl: int, head: int, track_bytes: int, n: int) -> bytes:
    """The plain sectors' bytes as a sector image holds them; any that are missing read as zeros."""
    size = 128 << n
    out = bytearray(track_bytes)
    for s in sectors:
        if s.c == cyl and s.h == head and s.n == n and 1 <= s.r <= track_bytes // size and s.status == 0:
            out[(s.r - 1) * size:s.r * size] = s.data[:size].ljust(size, b"\0")
    return bytes(out)


def fit(sectors: Sequence[Sector]) -> List[Sector]:
    """Sectors laid out so that Neko Project II finds every one. It reads at most SLOT bytes of
    a track, and only looks at a sector if a whole one of the size asked for would still fit
    after it. A protection sector claiming more than it has keeps only as much of its data as
    leaves room; the game's check reads the start of it."""
    def reached(keep: int) -> int:
        """How many sectors the search reaches with protection sectors cut to `keep` bytes."""
        pos, n = 0, 0
        for s in sectors:
            n += pos + 16 + s.full <= SLOT
            pos += 16 + (min(len(s.data), keep) if s.status else len(s.data))
        return n if pos <= SLOT else -1
    longest = max((len(s.data) for s in sectors if s.status), default=0)
    keep, most = longest, reached(longest)
    for k in list(range(longest - 128, 0, -128)) + [0]:     # the longest that reaches the most
        if most == len(sectors):
            break
        n = reached(k)
        if n > most:
            keep, most = k, n
    return [Sector(s.c, s.h, s.r, s.n, s.data[:keep] if s.status else s.data, s.status, s.deleted) for s in sectors]


def encode_track(sectors: Sequence[Sector]) -> bytes:
    out = bytearray()
    for s in sectors:
        out += _SEC.pack(s.c, s.h, s.r, s.n, len(sectors), 0x00, DELETED if s.deleted else 0, s.status, len(s.data))
        out += s.data
    return bytes(out)


def decode_track(buf: bytes) -> List[Sector]:
    out: List[Sector] = []
    pos, count = 0, None
    while pos + 16 <= len(buf):
        c, h, r, n, nsec, _density, deleted, status, size = _SEC.unpack_from(buf, pos)
        if count is None:
            count = nsec
        if len(out) >= count or pos + 16 + size > len(buf):
            break
        out.append(Sector(c, h, r, n, bytes(buf[pos + 16:pos + 16 + size]), status, bool(deleted & DELETED)))
        pos += 16 + size
    return out


def header(name: str, protected: bool, media: int, offsets: Sequence[int], size: int) -> bytes:
    table = list(offsets) + [0] * (TRACKS - len(offsets))
    return (name.encode("ascii", "replace")[:16].ljust(17, b"\0") + bytes(9) +
            bytes([PROTECT if protected else 0, media]) + struct.pack("<I", size) + struct.pack("<164I", *table))


@dataclass
class Image:
    """A whole D88 file in memory: one list of sectors per track, by cylinder * 2 + head."""
    name: str
    media: int
    protected: bool
    tracks: List[List[Sector]]

    def to_bytes(self) -> bytes:
        while self.tracks and not self.tracks[-1]:
            self.tracks.pop()
        bodies = [encode_track(fit(t)) if t else b"" for t in self.tracks]
        offsets, pos = [], HEADER
        for body in bodies:
            offsets.append(pos if body else 0)
            pos += len(body)
        return header(self.name, self.protected, self.media, offsets, pos) + b"".join(bodies)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Image":
        if len(data) < HEADER:
            raise ValueError("too short for a D88 image")
        size = min(struct.unpack_from("<I", data, 0x1C)[0] or len(data), len(data))
        offsets = struct.unpack_from("<164I", data, 0x20)
        starts = sorted({o for o in offsets if 0 < o < size})
        tracks: List[List[Sector]] = []
        for off in offsets:
            if not 0 < off < size:
                tracks.append([])
                continue
            end = next((o for o in starts if o > off), size)
            tracks.append(decode_track(data[off:min(end, off + SLOT)]))
        while tracks and not tracks[-1]:
            tracks.pop()
        name = data[:17].split(b"\0", 1)[0].decode("ascii", "replace")
        return cls(name, data[0x1B], bool(data[0x1A] & PROTECT), tracks)

    def data_offsets(self, raw: bytes) -> Dict[Tuple[int, int], Dict[Tuple[int, int, int, int], int]]:
        """Where each sector's data sits in the file it was read from, for writing in place."""
        out: Dict[Tuple[int, int], Dict[Tuple[int, int, int, int], int]] = {}
        offsets = struct.unpack_from("<164I", raw, 0x20)
        for t, off in enumerate(offsets[:len(self.tracks)]):
            if not off:
                continue
            pos = off
            where: Dict[Tuple[int, int, int, int], int] = {}
            for s in self.tracks[t]:
                where.setdefault(s.id, pos + 16)
                pos += 16 + len(s.data)
            out[divmod(t, 2)] = where
        return out


def boot_sector_start(f: "BinaryFile", d88: bool) -> bytes:
    """The first 16 bytes of a disk's first sector (cylinder 0, head 0, sector 1), from a D88
    or from a sector image, where it is simply the start."""
    f.seek(0)
    if not d88:
        return f.read(16)
    head = f.read(HEADER)
    if len(head) < HEADER:
        return b""
    first = struct.unpack_from("<I", head, 0x20)[0]
    if not first:
        return b""
    f.seek(first)
    for s in decode_track(f.read(SLOT)):
        if s.r == 1:
            return s.data[:16]
    return b""


class BinaryFile(Protocol):
    def seek(self, offset: int) -> int: ...
    def read(self, size: int = -1) -> bytes: ...


class View:
    """A disk as a D88 file with a fixed slot per track, so its layout is known before any
    track has been read. Reads build a track's slot from what the drive returned; a write is
    let through only where it changes the data of a plain sector, the one thing a game
    writing a save changes. Everything else would be a different disk layout."""

    def __init__(self, disk: "TrackSource", name: str, media: int, protected: Callable[[], bool]) -> None:
        self.disk = disk
        self.name = name
        self.media = media
        self.protected = protected
        self.tracks = disk.size // disk.b.track_bytes
        self.size = HEADER + self.tracks * SLOT
        self._built: Dict[int, Tuple[int, bytes]] = {}

    def header(self) -> bytes:
        return header(self.name, self.protected(), self.media,
                      [HEADER + t * SLOT for t in range(self.tracks)], self.size)

    def _slot(self, idx: int) -> bytes:
        cached = self._built.get(idx)
        if cached is not None and cached[0] == self.disk.epoch:
            return cached[1]
        body = encode_track(fit(self.disk.sectors(idx))).ljust(SLOT, b"\0")[:SLOT]
        self._built[idx] = (self.disk.epoch, body)
        return body

    def read_at(self, offset: int, size: int) -> bytes:
        out = bytearray()
        end = min(offset + size, self.size)
        pos = offset
        while pos < end:
            if pos < HEADER:
                chunk = self.header()[pos:min(end, HEADER)]
            else:
                idx, off = divmod(pos - HEADER, SLOT)
                chunk = self._slot(idx)[off:min(SLOT, off + end - pos)]
            out += chunk
            pos += len(chunk)
        return bytes(out)

    def write_at(self, offset: int, data: bytes) -> int:
        from floppy_drive import DiskError
        n = max(0, min(len(data), self.size - offset))
        if offset < HEADER:
            part = data[:max(0, min(n, HEADER - offset))]
            if part != self.header()[offset:offset + len(part)]:
                raise DiskError(30, "a write tried to change the image's header, which a game never does")
        writes: List[Tuple[int, bytes]] = []
        pos = max(offset, HEADER)
        while pos < offset + n:
            idx, off = divmod(pos - HEADER, SLOT)
            take = min(SLOT - off, offset + n - pos)
            old = self._slot(idx)
            new = old[:off] + data[pos - offset:pos - offset + take] + old[off + take:]
            if new != old:
                writes += self._changes(idx, old, new)
            pos += take
        if writes:
            # One write to the disk underneath, so a refusal anywhere means nothing changed.
            start = min(at for at, _ in writes)
            end = max(at + len(chunk) for at, chunk in writes)
            span = bytearray(self.disk.read_at(start, end - start))
            for at, chunk in writes:
                span[at - start:at - start + len(chunk)] = chunk
            tb = self.disk.b.track_bytes
            try:
                self.disk.write_at(start, bytes(span))
            finally:
                for idx in range(start // tb, (end - 1) // tb + 1):
                    self._built.pop(idx, None)
        return n

    def _changes(self, idx: int, old: bytes, new: bytes) -> List[Tuple[int, bytes]]:
        """Where in the sector image the changed sectors of one track go."""
        from floppy_drive import DiskError
        was, now = decode_track(old), decode_track(new)
        heads, pos = [], 0
        for s in was:
            heads.append(pos)
            pos += 16 + len(s.data)
        if (len(now) != len(was) or new[pos:] != old[pos:] or
                any(new[h:h + 16] != old[h:h + 16] for h in heads)):
            raise DiskError(30, "a write tried to change a track's layout, which a game saving never does")
        cyl, head = divmod(idx, self.disk.b.heads)
        tb, n = self.disk.b.track_bytes, self.disk.b.sector_n
        plain = set(plain_ids(cyl, head, tb, n))
        out = []
        for a, b in zip(was, now):
            if a.data == b.data:
                continue
            if a.id not in plain or a.status or a.deleted:
                raise DiskError(30, f"track {cyl}.{head}: a write tried to change sector {a.r}, "
                                    "which isn't a plain one; writing it would erase what's special about it")
            out.append((idx * tb + (a.r - 1) * (128 << n), b.data))
        return out


class SourceBackend(Protocol):
    track_bytes: int
    heads: int
    sector_n: int


class TrackSource(Protocol):
    """What View needs of the disk underneath: floppy_drive.TrackDisk."""
    size: int
    epoch: int

    @property
    def b(self) -> SourceBackend: ...
    def sectors(self, idx: int) -> List[Sector]: ...
    def read_at(self, offset: int, size: int) -> bytes: ...
    def write_at(self, offset: int, data: bytes) -> int: ...
