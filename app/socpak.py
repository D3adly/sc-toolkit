"""Reader for .socpak object containers (level chunks) found inside
Data.p4k. They are ordinary zip archives, but CIG writes backslash paths in
the local headers and forward slashes in the directory, which the stdlib
`zipfile` refuses to open — so entries are located through the directory
and decompressed here.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Iterator
from compression import zstd

_METHOD_STORE, _METHOD_DEFLATE, _METHOD_ZSTD = 0, 8, 100


def entries(data: bytes, want=lambda name: True) -> Iterator[tuple[str, bytes]]:
    for info in zipfile.ZipFile(io.BytesIO(data)).infolist():
        if not want(info.filename):
            continue
        name_len, extra_len = struct.unpack_from("<HH", data, info.header_offset + 26)
        start = info.header_offset + 30 + name_len + extra_len
        raw = data[start:start + info.compress_size]
        if info.compress_type == _METHOD_STORE:
            yield info.filename, raw
        elif info.compress_type == _METHOD_DEFLATE:
            yield info.filename, zlib.decompress(raw, -15)
        elif info.compress_type == _METHOD_ZSTD:
            yield info.filename, zstd.decompress(raw)
