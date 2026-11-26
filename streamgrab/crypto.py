"""AES decryption for encrypted HLS (``EXT-X-KEY:METHOD=AES-128``).

If :mod:`cryptography` is installed we use its vetted AES implementation.
Otherwise a small, self-contained pure-Python AES-128/192/256 implementation
is used so the tool still works with zero dependencies. The pure-Python path
is slow but correct; for large libraries install the ``crypto`` extra.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Sequence, Tuple

try:  # pragma: no cover - exercised implicitly when available
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    _HAVE_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover
    _HAVE_CRYPTOGRAPHY = False


# ---------------------------------------------------------------------------
# Pure-Python AES
# ---------------------------------------------------------------------------

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76"
    "ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d83115"
    "04c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f84"
    "53d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa8"
    "51a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d1973"
    "60814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479"
    "e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a"
    "703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df"
    "8ca1890dbfe6426841992d0fb054bb16"
)

_INV_SBOX = bytes(256)
_sbox_mut = bytearray(_INV_SBOX)
for _i, _v in enumerate(_SBOX):
    _sbox_mut[_v] = _i
_INV_SBOX = bytes(_sbox_mut)
del _sbox_mut, _i, _v

_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36,
         0x6C, 0xD8, 0xAB, 0x4D]


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gmul(a: int, b: int) -> int:
    """Multiply in GF(2^8)."""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _expand_key(key: bytes) -> Tuple[List[List[List[int]]], int]:
    nk = len(key) // 4
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16, 24 or 32 bytes")
    nr = nk + 6
    words = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    total = 4 * (nr + 1)
    for i in range(nk, total):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    round_keys: List[List[List[int]]] = []
    for r in range(nr + 1):
        rk = [[0] * 4 for _ in range(4)]
        for c in range(4):
            w = words[4 * r + c]
            for rr in range(4):
                rk[rr][c] = w[rr]
        round_keys.append(rk)
    return round_keys, nr


def _to_state(block: bytes) -> List[List[int]]:
    return [[block[r + 4 * c] for c in range(4)] for r in range(4)]


def _from_state(state: List[List[int]]) -> bytes:
    return bytes(state[r][c] for c in range(4) for r in range(4))


def _add_round_key(state: List[List[int]], rk: List[List[int]]) -> None:
    for r in range(4):
        for c in range(4):
            state[r][c] ^= rk[r][c]


def _sub_bytes(state: List[List[int]]) -> None:
    for r in range(4):
        for c in range(4):
            state[r][c] = _SBOX[state[r][c]]


def _inv_sub_bytes(state: List[List[int]]) -> None:
    for r in range(4):
        for c in range(4):
            state[r][c] = _INV_SBOX[state[r][c]]


def _shift_rows(state: List[List[int]]) -> None:
    for r in range(1, 4):
        state[r] = state[r][r:] + state[r][:r]


def _inv_shift_rows(state: List[List[int]]) -> None:
    for r in range(1, 4):
        state[r] = state[r][-r:] + state[r][:-r]


def _mix_columns(state: List[List[int]]) -> None:
    for c in range(4):
        a0, a1, a2, a3 = state[0][c], state[1][c], state[2][c], state[3][c]
        state[0][c] = _gmul(a0, 2) ^ _gmul(a1, 3) ^ a2 ^ a3
        state[1][c] = a0 ^ _gmul(a1, 2) ^ _gmul(a2, 3) ^ a3
        state[2][c] = a0 ^ a1 ^ _gmul(a2, 2) ^ _gmul(a3, 3)
        state[3][c] = _gmul(a0, 3) ^ a1 ^ a2 ^ _gmul(a3, 2)


def _inv_mix_columns(state: List[List[int]]) -> None:
    for c in range(4):
        a0, a1, a2, a3 = state[0][c], state[1][c], state[2][c], state[3][c]
        state[0][c] = _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
        state[1][c] = _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
        state[2][c] = _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
        state[3][c] = _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)


def encrypt_block(key: bytes, block: bytes) -> bytes:
    round_keys, nr = _expand_key(key)
    state = _to_state(block)
    _add_round_key(state, round_keys[0])
    for rnd in range(1, nr):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, round_keys[rnd])
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, round_keys[nr])
    return _from_state(state)


def decrypt_block(key: bytes, block: bytes) -> bytes:
    round_keys, nr = _expand_key(key)
    state = _to_state(block)
    _add_round_key(state, round_keys[nr])
    for rnd in range(nr - 1, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, round_keys[rnd])
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, round_keys[0])
    return _from_state(state)


# ---------------------------------------------------------------------------
# Public CBC API
# ---------------------------------------------------------------------------

def _cbc_decrypt_pure(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(iv) != 16:
        raise ValueError("AES-CBC IV must be 16 bytes")
    usable = len(data) - (len(data) % 16)
    out = bytearray()
    prev = iv
    for offset in range(0, usable, 16):
        block = data[offset:offset + 16]
        dec = decrypt_block(key, block)
        out.extend(a ^ b for a, b in zip(dec, prev))
        prev = block
    return bytes(out)


def _cbc_decrypt_cryptography(key: bytes, iv: bytes, data: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CBC decrypt ``data`` with ``key``/``iv`` (no padding removal)."""
    if _HAVE_CRYPTOGRAPHY:
        return _cbc_decrypt_cryptography(key, iv, data)
    return _cbc_decrypt_pure(key, iv, data)


def pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad = block_size - (len(data) % block_size)
    return data + bytes([pad]) * pad


def cbc_encrypt(key: bytes, iv: bytes, data: bytes, pad: bool = True) -> bytes:
    """AES-CBC encrypt ``data``. Mainly useful for tests and fixtures."""
    if len(iv) != 16:
        raise ValueError("AES-CBC IV must be 16 bytes")
    if pad:
        data = pkcs7_pad(data)
    usable = len(data) - (len(data) % 16)
    out = bytearray()
    prev = iv
    for offset in range(0, usable, 16):
        block = bytes(a ^ b for a, b in zip(data[offset:offset + 16], prev))
        enc = encrypt_block(key, block)
        out.extend(enc)
        prev = enc
    return bytes(out)


def pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
    """Strip PKCS#7 padding if present; leave data untouched otherwise."""
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= block_size and len(data) >= pad and data[-pad:] == bytes([pad]) * pad:
        return data[:-pad]
    return data


def sequence_iv(sequence_number: int) -> bytes:
    """HLS default IV: the 16-byte big-endian media sequence number."""
    return struct.pack(">QQ", 0, sequence_number & 0xFFFFFFFFFFFFFFFF)


def parse_iv(value: str) -> Optional[bytes]:
    """Parse ``0x...`` (or bare hex) IV text into bytes."""
    if not value:
        return None
    text = value.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    if len(text) % 2:
        text = "0" + text
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None


def xor_bytes(a: Sequence[int], b: Sequence[int]) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


__all__ = [
    "cbc_decrypt",
    "cbc_encrypt",
    "pkcs7_pad",
    "encrypt_block",
    "decrypt_block",
    "pkcs7_unpad",
    "sequence_iv",
    "parse_iv",
    "xor_bytes",
]
