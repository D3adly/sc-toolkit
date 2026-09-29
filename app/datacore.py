"""Reader for Star Citizen's DataCore database (`Data\\Game2.dcb` inside
Data.p4k) — the binary store behind every game record: entities, loadouts,
contracts, tags.

Layout (version 8, as of 4.10): a header of counts, then the struct,
property, enum, data-mapping and record tables, then one flat array per
value type (used by array properties), then two string tables (values and
file names first; type/property/record names second), then the instance
data — every struct type's instances stored back to back.

Only what the launcher needs is decoded: records by name, instances as
plain dicts (references become '@RecordName', weak pointers a short
marker), plus a fast path for an entity's tag list.
"""

from __future__ import annotations

import struct

_HEADER = struct.Struct("<2I4H26I")
_RECORD = struct.Struct("<IIII16sHH")  # v8 records carry one extra u32

# Property data types.
_BOOL, _I8, _I16, _I32, _I64 = 1, 2, 3, 4, 5
_U8, _U16, _U32, _U64 = 6, 7, 8, 9
_STRING, _FLOAT, _DOUBLE, _LOCALE, _GUID, _ENUM = 10, 11, 12, 13, 14, 15
_CLASS, _STRONG, _WEAK, _REF = 0x10, 0x110, 0x210, 0x310

_SCALAR = {
    _BOOL: struct.Struct("<?"), _I8: struct.Struct("<b"), _I16: struct.Struct("<h"),
    _I32: struct.Struct("<i"), _I64: struct.Struct("<q"), _U8: struct.Struct("<B"),
    _U16: struct.Struct("<H"), _U32: struct.Struct("<I"), _U64: struct.Struct("<Q"),
    _FLOAT: struct.Struct("<f"), _DOUBLE: struct.Struct("<d"),
}
_SIZE = {
    _BOOL: 1, _I8: 1, _I16: 2, _I32: 4, _I64: 8, _U8: 1, _U16: 2, _U32: 4, _U64: 8,
    _STRING: 4, _FLOAT: 4, _DOUBLE: 8, _LOCALE: 4, _GUID: 16, _ENUM: 4,
    _STRONG: 8, _WEAK: 8, _REF: 20,
}
# Value-array order in the file, with the data type each one backs.
_ARRAYS = [
    (_I8, 1), (_I16, 2), (_I32, 4), (_I64, 8), (_U8, 1), (_U16, 2), (_U32, 4),
    (_U64, 8), (_BOOL, 1), (_FLOAT, 4), (_DOUBLE, 8), (_GUID, 16), (_STRING, 4),
    (_LOCALE, 4), (_ENUM, 4), (_STRONG, 8), (_WEAK, 8), (_REF, 20), (None, 4),
]
_NO_PARENT = 0xFFFFFFFF


class DataCoreError(Exception):
    pass


class DataCore:
    def __init__(self, data: bytes):
        self.b = data
        self._props_memo: dict[int, tuple] = {}
        self._size_memo: dict[int, int] = {}
        h = _HEADER.unpack_from(data, 0)
        if h[1] != 8:
            raise DataCoreError(f"Unsupported DataCore version {h[1]}")
        (n_struct, n_prop, n_enum, n_map, n_rec,
         c_bool, c_i8, c_i16, c_i32, c_i64, c_u8, c_u16, c_u32, c_u64,
         c_f, c_d, c_guid, c_str, c_loc, c_enum, c_strong, c_weak, c_ref, c_eo,
         text_len, blob_len) = h[6:]
        counts = {
            _I8: c_i8, _I16: c_i16, _I32: c_i32, _I64: c_i64, _U8: c_u8, _U16: c_u16,
            _U32: c_u32, _U64: c_u64, _BOOL: c_bool, _FLOAT: c_f, _DOUBLE: c_d,
            _GUID: c_guid, _STRING: c_str, _LOCALE: c_loc, _ENUM: c_enum,
            _STRONG: c_strong, _WEAK: c_weak, _REF: c_ref, None: c_eo,
        }

        o = _HEADER.size
        self.structs = list(struct.iter_unpack("<IIHHI", data[o:o + 16 * n_struct]))
        o += 16 * n_struct
        self.props = list(struct.iter_unpack("<IHHHH", data[o:o + 12 * n_prop]))
        o += 12 * n_prop + 8 * n_enum
        mappings = list(struct.iter_unpack("<II", data[o:o + 8 * n_map]))
        o += 8 * n_map
        self._rec_off = o
        self.n_records = n_rec
        o += _RECORD.size * n_rec

        self._arr: dict[int | None, int] = {}
        for dtype, size in _ARRAYS:
            self._arr[dtype] = o
            o += size * counts[dtype]
        self._text = o
        self._blob = o + text_len
        o = self._blob + blob_len

        self._block: dict[int, int] = {}
        for count, si in mappings:
            self._block[si] = o
            o += count * self.struct_size(si)
        if o != len(data):
            raise DataCoreError("DataCore layout mismatch — unsupported game build?")

        self._by_name: dict[str, tuple] | None = None
        self._by_guid: dict[bytes, tuple] | None = None

    # -- strings ------------------------------------------------------------
    def _cstr(self, base: int, off: int) -> str:
        start = base + off
        return self.b[start:self.b.index(b"\0", start)].decode("utf-8", "replace")

    def text(self, off: int) -> str:
        return self._cstr(self._text, off)

    def name(self, off: int) -> str:
        return self._cstr(self._blob, off)

    # -- structure layout ---------------------------------------------------
    def struct_props(self, si: int) -> tuple:
        found = self._props_memo.get(si)
        if found is not None:
            return found
        key, chain = si, []
        while si != _NO_PARENT:
            chain.append(si)
            si = self.structs[si][1]
        out = []
        for s in reversed(chain):
            _, _, count, first, _ = self.structs[s]
            out.extend(self.props[first:first + count])
        self._props_memo[key] = found = tuple(out)
        return found

    def struct_size(self, si: int) -> int:
        found = self._size_memo.get(si)
        if found is None:
            found = self._size_memo[si] = sum(
                8 if conv else (_SIZE.get(dtype) or self.struct_size(idx))
                for _, idx, dtype, conv, _ in self.struct_props(si)
            )
        return found

    def struct_name(self, si: int) -> str:
        return self.name(self.structs[si][0])

    # -- records --------------------------------------------------------------
    def records(self):
        """Yields (name, struct_index, instance_index, guid)."""
        for name_off, _file, _x, si, guid, ii, _ in struct.iter_unpack(
            _RECORD.format, self.b[self._rec_off:self._rec_off + _RECORD.size * self.n_records]
        ):
            yield self.name(name_off), si, ii, guid

    def _index(self) -> None:
        by_name, by_guid = {}, {}
        for rec in self.records():
            by_name[rec[0]] = rec
            by_guid[rec[3]] = rec
        self._by_name, self._by_guid = by_name, by_guid

    def record_names(self, prefix: str) -> list[str]:
        if self._by_name is None:
            self._index()
        return [n for n in self._by_name if n.startswith(prefix)]

    def record(self, name: str, max_depth: int = 64) -> dict | None:
        if self._by_name is None:
            self._index()
        rec = self._by_name.get(name)
        return None if rec is None else self.instance(rec[1], rec[2], max_depth)

    def _ref_name(self, off: int) -> str | None:
        if self._by_guid is None:
            self._index()
        rec = self._by_guid.get(self.b[off + 4:off + 20])
        return "@" + rec[0] if rec else None

    # -- instances --------------------------------------------------------------
    def instance(self, si: int, ii: int, max_depth: int = 64) -> dict:
        return self._struct_at(si, self._block[si] + ii * self.struct_size(si), max_depth)

    def _pointer(self, off: int, depth: int, weak: bool):
        si, ii = struct.unpack_from("<II", self.b, off)
        if si == _NO_PARENT:
            return None
        if weak or depth <= 0:
            return f"<{self.struct_name(si)}#{ii}>"
        return self.instance(si, ii, depth - 1)

    def _value(self, dtype: int, off: int, depth: int):
        if dtype in _SCALAR:
            return _SCALAR[dtype].unpack_from(self.b, off)[0]
        if dtype in (_STRING, _LOCALE, _ENUM):
            return self.text(struct.unpack_from("<I", self.b, off)[0])
        if dtype == _GUID:
            return self.b[off:off + 16].hex()
        if dtype == _REF:
            return self._ref_name(off)
        if dtype in (_STRONG, _WEAK):
            return self._pointer(off, depth, dtype == _WEAK)
        raise DataCoreError(f"Unknown data type {dtype:#x}")

    def _struct_at(self, si: int, off: int, depth: int) -> dict:
        out = {"_type": self.struct_name(si)}
        for name_off, idx, dtype, conv, _ in self.struct_props(si):
            key = self.name(name_off)
            if conv:
                count, first = struct.unpack_from("<II", self.b, off)
                off += 8
                if dtype == _CLASS:
                    out[key] = (
                        [self.instance(idx, first + k, depth - 1) for k in range(count)]
                        if depth > 0 else f"<{count} items>"
                    )
                else:
                    base, size = self._arr[dtype], _SIZE[dtype]
                    out[key] = [self._value(dtype, base + (first + k) * size, depth)
                                for k in range(count)]
            elif dtype == _CLASS:
                out[key] = self._struct_at(idx, off, depth - 1) if depth > 0 else "<...>"
                off += self.struct_size(idx)
            else:
                out[key] = self._value(dtype, off, depth)
                off += _SIZE[dtype]
        return out

    # -- fast paths ---------------------------------------------------------------
    def tag_refs(self, name: str) -> list[str]:
        """The top-level `tags` list of a record (e.g. an entity class) as
        '@Tag.<guid>' names, without decoding the rest of the record.
        """
        if self._by_name is None:
            self._index()
        rec = self._by_name.get(name)
        if rec is None:
            return []
        si = rec[1]
        off = self._block[si] + rec[2] * self.struct_size(si)
        for name_off, idx, dtype, conv, _ in self.struct_props(si):
            if self.name(name_off) == "tags" and conv and dtype == _REF:
                count, first = struct.unpack_from("<II", self.b, off)
                base = self._arr[_REF]
                refs = (self._ref_name(base + (first + k) * 20) for k in range(count))
                return [r for r in refs if r]
            off += 8 if conv else (_SIZE.get(dtype) or self.struct_size(idx))
        return []
