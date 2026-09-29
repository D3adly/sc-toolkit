"""Decoder for CryEngine's binary XML ("CryXmlB") format, used for most
XML files inside Data.p4k.

Layout: an 8-byte magic, then nine little-endian u32s (file length, then
offset/count pairs for the node, attribute and child-index tables, then the
string-data offset/size). Every name and value is an offset into the
string-data block.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET

MAGIC = b"CryXmlB\x00"
_NODE = struct.Struct("<IIHHiiii")
_ATTR = struct.Struct("<II")


def is_cryxml(data: bytes) -> bool:
    return data[:8] == MAGIC


def parse(data: bytes) -> ET.Element:
    if not is_cryxml(data):
        return ET.fromstring(data)

    (_length, node_off, node_count, attr_off, attr_count,
     child_off, child_count, str_off, _str_size) = struct.unpack_from("<9I", data, 8)

    strings: dict[int, str] = {}

    def s(offset: int) -> str:
        cached = strings.get(offset)
        if cached is None:
            start = str_off + offset
            cached = data[start:data.index(b"\x00", start)].decode("utf-8", "replace")
            strings[offset] = cached
        return cached

    nodes = [_NODE.unpack_from(data, node_off + i * _NODE.size) for i in range(node_count)]
    attrs = [_ATTR.unpack_from(data, attr_off + i * _ATTR.size) for i in range(attr_count)]
    children = struct.unpack_from(f"<{child_count}i", data, child_off)

    def build(index: int) -> ET.Element:
        tag, content, n_attrs, n_children, _parent, first_attr, first_child, _ = nodes[index]
        el = ET.Element(s(tag), {s(k): s(v) for k, v in attrs[first_attr:first_attr + n_attrs]})
        text = s(content)
        if text:
            el.text = text
        for child in children[first_child:first_child + n_children]:
            el.append(build(child))
        return el

    return build(0)
