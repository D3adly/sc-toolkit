"""AES-128 decryption (CBC), just enough to read Data.p4k's encrypted entries
(see app.p4k). Pure Python so the launcher needs no crypto package: the
encrypted files are small (vehicle definitions, a few MB per patch).

Table-driven inverse cipher after FIPS-197: the inverse round is one lookup
per byte into four 32-bit tables.
"""

from __future__ import annotations

import struct

_SBOX = bytearray(256)
_INV = bytearray(256)


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    out = 0
    while b:
        if b & 1:
            out ^= a
        a = _xtime(a)
        b >>= 1
    return out


def _build_sbox() -> None:
    p = q = 1
    while True:
        p ^= _xtime(p)                                   # p *= 3
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4                                      # q /= 3
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        _SBOX[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    _SBOX[0] = 0x63
    for i, v in enumerate(_SBOX):
        _INV[v] = i


_build_sbox()

# Inverse round tables: InvMixColumns of an InvSubBytes'd byte, one per byte position.
_T = [[0] * 256 for _ in range(4)]
for _i in range(256):
    _s = _INV[_i]
    _w = (_mul(_s, 14) << 24) | (_mul(_s, 9) << 16) | (_mul(_s, 13) << 8) | _mul(_s, 11)
    for _k in range(4):
        _T[_k][_i] = ((_w >> (8 * _k)) | (_w << (32 - 8 * _k))) & 0xFFFFFFFF
_T0, _T1, _T2, _T3 = _T


def _expand(key: bytes) -> list[int]:
    if len(key) != 16:
        raise ValueError("AES-128 needs a 16-byte key")
    w = list(struct.unpack(">4I", key))
    rcon = 1
    for i in range(4, 44):
        t = w[i - 1]
        if i % 4 == 0:
            t = ((t << 8) | (t >> 24)) & 0xFFFFFFFF
            t = (_SBOX[t >> 24] << 24) | (_SBOX[(t >> 16) & 0xFF] << 16) | (_SBOX[(t >> 8) & 0xFF] << 8) | _SBOX[t & 0xFF]
            t ^= rcon << 24
            rcon = _xtime(rcon)
        w.append(w[i - 4] ^ t)
    return w


def _decrypt_keys(key: bytes) -> list[list[int]]:
    """Round keys for the equivalent inverse cipher (middle rounds pass through InvMixColumns)."""
    w = _expand(key)
    rounds = [w[4 * r:4 * r + 4] for r in range(11)][::-1]
    for r in range(1, 10):
        rounds[r] = [_T0[_SBOX[k >> 24]] ^ _T1[_SBOX[(k >> 16) & 0xFF]] ^ _T2[_SBOX[(k >> 8) & 0xFF]] ^ _T3[_SBOX[k & 0xFF]]
                     for k in rounds[r]]
    return rounds


def decrypt_cbc(key: bytes, data: bytes, iv: bytes = bytes(16)) -> bytes:
    """AES-128-CBC decryption without unpadding (callers know their format)."""
    if len(data) % 16:
        raise ValueError("AES data must be a whole number of 16-byte blocks")
    rk = _decrypt_keys(key)
    inv = _INV
    out = bytearray(len(data))
    prev = struct.unpack(">4I", iv)
    for off in range(0, len(data), 16):
        c = struct.unpack_from(">4I", data, off)
        k = rk[0]
        s0, s1, s2, s3 = c[0] ^ k[0], c[1] ^ k[1], c[2] ^ k[2], c[3] ^ k[3]
        for r in range(1, 10):
            k = rk[r]
            s0, s1, s2, s3 = (
                _T0[s0 >> 24] ^ _T1[(s3 >> 16) & 0xFF] ^ _T2[(s2 >> 8) & 0xFF] ^ _T3[s1 & 0xFF] ^ k[0],
                _T0[s1 >> 24] ^ _T1[(s0 >> 16) & 0xFF] ^ _T2[(s3 >> 8) & 0xFF] ^ _T3[s2 & 0xFF] ^ k[1],
                _T0[s2 >> 24] ^ _T1[(s1 >> 16) & 0xFF] ^ _T2[(s0 >> 8) & 0xFF] ^ _T3[s3 & 0xFF] ^ k[2],
                _T0[s3 >> 24] ^ _T1[(s2 >> 16) & 0xFF] ^ _T2[(s1 >> 8) & 0xFF] ^ _T3[s0 & 0xFF] ^ k[3],
            )
        k = rk[10]
        p = (
            (inv[s0 >> 24] << 24 | inv[(s3 >> 16) & 0xFF] << 16 | inv[(s2 >> 8) & 0xFF] << 8 | inv[s1 & 0xFF]) ^ k[0],
            (inv[s1 >> 24] << 24 | inv[(s0 >> 16) & 0xFF] << 16 | inv[(s3 >> 8) & 0xFF] << 8 | inv[s2 & 0xFF]) ^ k[1],
            (inv[s2 >> 24] << 24 | inv[(s1 >> 16) & 0xFF] << 16 | inv[(s0 >> 8) & 0xFF] << 8 | inv[s3 & 0xFF]) ^ k[2],
            (inv[s3 >> 24] << 24 | inv[(s2 >> 16) & 0xFF] << 16 | inv[(s1 >> 8) & 0xFF] << 8 | inv[s0 & 0xFF]) ^ k[3],
        )
        struct.pack_into(">4I", out, off, p[0] ^ prev[0], p[1] ^ prev[1], p[2] ^ prev[2], p[3] ^ prev[3])
        prev = c
    return bytes(out)
