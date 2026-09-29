"""Minimal reader for Star Citizen's Data.p4k archive — just enough to pull
a handful of known files out of it.

Data.p4k is a ZIP64 archive, but CIG stores custom extra fields that the
stdlib `zipfile` rejects as corrupt, so the central directory is parsed by
hand here. The files we need (defaultProfile.xml, global.ini) use
compression method 100 (zstd) and are not encrypted; stdlib
`compression.zstd` (Python 3.14+) handles them.

Rather than walking all ~1.4M central-directory records in Python, the
directory is scanned in chunks for the exact entry names we want — CIG
stores them with backslashes and fixed casing — which takes a fraction of
a second on a 157 GB archive.
"""

from __future__ import annotations

import struct
from compression import zstd
from collections.abc import Iterator
from pathlib import Path

_EOCD64_LOCATOR = b"PK\x06\x07"
_EOCD64 = b"PK\x06\x06"
_CENTRAL_HEADER = b"PK\x01\x02"
_METHOD_STORE = 0
_METHOD_ZSTD = 100
_CHUNK = 32 * 1024 * 1024


class P4kError(Exception):
    pass


def _central_directory(f) -> tuple[int, int]:
    f.seek(0, 2)
    size = f.tell()
    tail_len = min(size, 65536 + 22 + 20)
    f.seek(size - tail_len)
    tail = f.read()
    loc = tail.rfind(_EOCD64_LOCATOR)
    if loc < 0:
        raise P4kError("ZIP64 end-of-central-directory locator not found")
    (eocd64_offset,) = struct.unpack_from("<Q", tail, loc + 8)
    f.seek(eocd64_offset)
    eocd64 = f.read(56)
    if eocd64[:4] != _EOCD64:
        raise P4kError("ZIP64 end-of-central-directory record not found")
    cd_size, cd_offset = struct.unpack_from("<QQ", eocd64, 40)
    return cd_offset, cd_size


def _find_headers(f, cd_offset: int, cd_size: int, names: list[bytes]) -> dict[bytes, int]:
    """Returns {name: absolute offset of its central-directory header}."""
    found: dict[bytes, int] = {}
    overlap = max(len(n) for n in names) + 46
    pos = 0
    while pos < cd_size and len(found) < len(names):
        f.seek(cd_offset + pos)
        chunk = f.read(min(_CHUNK + overlap, cd_size - pos))
        for name in names:
            if name in found:
                continue
            i = chunk.find(name)
            while i >= 0:
                hdr = i - 46
                if hdr >= 0 and chunk[hdr:hdr + 4] == _CENTRAL_HEADER:
                    (name_len,) = struct.unpack_from("<H", chunk, hdr + 28)
                    if name_len == len(name):
                        found[name] = cd_offset + pos + hdr
                        break
                i = chunk.find(name, i + 1)
        pos += _CHUNK
    return found


def _read_entry(f, header_offset: int) -> bytes:
    f.seek(header_offset)
    hdr = f.read(46)
    method, = struct.unpack_from("<H", hdr, 10)
    csize, usize = struct.unpack_from("<II", hdr, 20)
    name_len, extra_len, _comment_len = struct.unpack_from("<HHH", hdr, 28)
    (local_offset,) = struct.unpack_from("<I", hdr, 42)
    f.seek(header_offset + 46 + name_len)
    extra = f.read(extra_len)

    # ZIP64 extra field (0x0001) carries whichever of usize/csize/offset
    # overflowed 32 bits, in that order.
    q = 0
    while q + 4 <= len(extra):
        tag, length = struct.unpack_from("<HH", extra, q)
        if tag == 0x0001:
            vals = list(struct.unpack_from(f"<{length // 8}Q", extra, q + 4))
            if usize == 0xFFFFFFFF and vals:
                usize = vals.pop(0)
            if csize == 0xFFFFFFFF and vals:
                csize = vals.pop(0)
            if local_offset == 0xFFFFFFFF and vals:
                local_offset = vals.pop(0)
            break
        q += 4 + length

    f.seek(local_offset)
    local = f.read(30)
    local_name_len, local_extra_len = struct.unpack_from("<HH", local, 26)
    f.seek(local_offset + 30 + local_name_len + local_extra_len)
    data = f.read(csize)

    if method == _METHOD_ZSTD:
        return zstd.decompress(data)
    if method == _METHOD_STORE:
        return data
    raise P4kError(f"Unsupported compression method {method}")


def extract(p4k_path: Path, names: list[str]) -> dict[str, bytes]:
    """Extracts the given entries (backslash paths, exact case, e.g.
    'Data\\Libs\\Config\\defaultProfile.xml'). Missing entries are simply
    absent from the result.
    """
    encoded = [n.encode() for n in names]
    out: dict[str, bytes] = {}
    with open(p4k_path, "rb") as f:
        cd_offset, cd_size = _central_directory(f)
        headers = _find_headers(f, cd_offset, cd_size, encoded)
        for name, raw in zip(names, encoded):
            if raw in headers:
                out[name] = _read_entry(f, headers[raw])
    return out


def iter_matching(p4k_path: Path, want) -> Iterator[tuple[str, bytes]]:
    """Walks the whole central directory once (a few seconds) and yields
    (name, data) for every entry whose name satisfies `want(name)`. Use
    this when the names aren't known up front; `extract` is faster when
    they are.
    """
    with open(p4k_path, "rb") as f:
        cd_offset, cd_size = _central_directory(f)
        matches: list[tuple[str, int]] = []
        buf, buf_start, pos = b"", 0, 0  # buf holds cd[buf_start:...]
        while True:
            rel = pos - buf_start
            if rel + 46 > len(buf):
                if buf_start + len(buf) >= cd_size:
                    break
                f.seek(cd_offset + pos)
                buf, buf_start = f.read(min(_CHUNK, cd_size - pos)), pos
                continue
            if buf[rel:rel + 4] != _CENTRAL_HEADER:
                raise P4kError("Corrupt central directory")
            name_len, extra_len, comment_len = struct.unpack_from("<HHH", buf, rel + 28)
            size = 46 + name_len + extra_len + comment_len
            if rel + size > len(buf):
                f.seek(cd_offset + pos)
                buf, buf_start = f.read(min(_CHUNK, cd_size - pos)), pos
                continue
            name = buf[rel + 46:rel + 46 + name_len].decode("utf-8", "replace")
            if want(name):
                matches.append((name, cd_offset + pos))
            pos += size
        for name, header_offset in matches:
            yield name, _read_entry(f, header_offset)
