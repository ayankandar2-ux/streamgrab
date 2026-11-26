"""Tests for the pure-Python AES / HLS crypto helpers."""

from streamgrab import crypto


def test_aes128_fips197_block():
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
    ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    assert crypto.encrypt_block(key, plaintext) == ciphertext
    assert crypto.decrypt_block(key, ciphertext) == plaintext


def test_aes256_fips197_block():
    key = bytes.fromhex(
        "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
    )
    plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
    ciphertext = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
    assert crypto.encrypt_block(key, plaintext) == ciphertext
    assert crypto.decrypt_block(key, ciphertext) == plaintext


def test_aes128_cbc_nist_vector():
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    ciphertext = bytes.fromhex("7649abac8119b246cee98e9b12e9197d")
    expected = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    assert crypto.cbc_decrypt(key, iv, ciphertext) == expected


def test_sequence_iv_is_big_endian():
    assert crypto.sequence_iv(0) == b"\x00" * 16
    assert crypto.sequence_iv(1) == b"\x00" * 15 + b"\x01"
    assert crypto.sequence_iv(0x0102) == b"\x00" * 14 + b"\x01\x02"


def test_parse_iv():
    assert crypto.parse_iv("0x000102030405060708090a0b0c0d0e0f") == bytes(range(16))
    assert crypto.parse_iv("0102030405060708090a0b0c0d0e0f") == bytes(range(1, 16))
    assert crypto.parse_iv("") is None


def test_pkcs7_unpad():
    assert crypto.pkcs7_unpad(b"abc" + b"\x05" * 5) == b"abc"
    assert crypto.pkcs7_unpad(b"abc") == b"abc"
    assert crypto.pkcs7_unpad(b"") == b""
