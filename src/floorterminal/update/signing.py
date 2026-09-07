"""Dependency-free Ed25519 (RFC 8032) verification for signed update metadata.

The console ships with no third-party packages, so release authenticity is proved
with a self-contained implementation of the RFC 8032 reference algorithm. Only
``verify`` runs on a deployed terminal; it processes public values exclusively, so
the absence of constant-time field arithmetic is not a key-recovery exposure.
``sign`` exists for the maintainer-side release tooling documented in
``docs/software-updates.md`` and must only be run on an offline signing host.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

# RFC 8032 section 5.1 domain parameters for edwards25519.
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_MINUS_ONE = pow(2, (_P - 1) // 4, _P)
_BASE_Y = 4 * pow(5, _P - 2, _P) % _P

SIGNATURE_BYTES = 64
PUBLIC_KEY_BYTES = 32
PRIVATE_SEED_BYTES = 32


class SignatureError(ValueError):
    """Raised when key or signature material is structurally unusable."""


def _sha512_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _point_add(first, second):
    """Add two extended homogeneous points (X, Y, Z, T) on edwards25519."""
    x1, y1, z1, t1 = first
    x2, y2, z2, t2 = second
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = 2 * t1 * t2 * _D % _P
    d = 2 * z1 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _point_multiply(scalar: int, point):
    result = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
        scalar >>= 1
    return result


def _point_equal(first, second) -> bool:
    x1, y1, z1, _ = first
    x2, y2, z2, _ = second
    return (x1 * z2 - x2 * z1) % _P == 0 and (y1 * z2 - y2 * z1) % _P == 0


_BASE_POINT = None
_IDENTITY = (0, 1, 1, 0)


def _recover_x(y: int, sign: int):
    """Recover the affine x coordinate for ``y`` or return ``None`` off the curve."""
    if y >= _P:
        return None
    square = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if square == 0:
        return None if sign else 0
    x = pow(square, (_P + 3) // 8, _P)
    if (x * x - square) % _P != 0:
        x = x * _SQRT_MINUS_ONE % _P
    if (x * x - square) % _P != 0:
        return None
    return _P - x if x & 1 != sign else x


def _base_point():
    global _BASE_POINT
    if _BASE_POINT is None:
        y = _BASE_Y
        x = _recover_x(y, 0)
        _BASE_POINT = (x, y, 1, x * y % _P)
    return _BASE_POINT


def _decompress(data: bytes):
    if len(data) != PUBLIC_KEY_BYTES:
        return None
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _compress(point) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, _P - 2, _P)
    x, y = x * inverse % _P, y * inverse % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return whether ``signature`` is a valid Ed25519 signature over ``message``."""
    if (
        not isinstance(public_key, (bytes, bytearray))
        or not isinstance(signature, (bytes, bytearray))
        or len(public_key) != PUBLIC_KEY_BYTES
        or len(signature) != SIGNATURE_BYTES
    ):
        return False
    public_key, signature = bytes(public_key), bytes(signature)
    point = _decompress(public_key)
    if point is None:
        return False
    encoded_r = signature[:32]
    commitment = _decompress(encoded_r)
    if commitment is None:
        return False
    # Strict verification rejects identity and non-prime-subgroup encodings.
    # This closes the small-order acceptance edge cases deliberately left open
    # by some compact implementations of the RFC reference equation.
    if (
        _point_equal(point, _IDENTITY)
        or not _point_equal(_point_multiply(_L, point), _IDENTITY)
        or _point_equal(commitment, _IDENTITY)
        or not _point_equal(_point_multiply(_L, commitment), _IDENTITY)
    ):
        return False
    scalar = int.from_bytes(signature[32:], "little")
    if scalar >= _L:
        return False
    challenge = _sha512_int(encoded_r + public_key + bytes(message)) % _L
    left = _point_multiply(scalar, _base_point())
    right = _point_add(commitment, _point_multiply(challenge, point))
    return _point_equal(left, right)


def _clamp(seed_hash: bytes) -> int:
    scalar = bytearray(seed_hash[:32])
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    return int.from_bytes(scalar, "little")


def public_key_from_seed(seed: bytes) -> bytes:
    """Derive the 32-byte public key for a 32-byte private seed."""
    if len(seed) != PRIVATE_SEED_BYTES:
        raise SignatureError("Ed25519 private seed must be exactly 32 bytes")
    digest = hashlib.sha512(bytes(seed)).digest()
    return _compress(_point_multiply(_clamp(digest), _base_point()))


def sign(seed: bytes, message: bytes) -> bytes:
    """Produce a detached signature. Maintainer tooling only; never run on a kiosk."""
    if len(seed) != PRIVATE_SEED_BYTES:
        raise SignatureError("Ed25519 private seed must be exactly 32 bytes")
    message = bytes(message)
    digest = hashlib.sha512(bytes(seed)).digest()
    secret, prefix = _clamp(digest), digest[32:]
    public_key = _compress(_point_multiply(secret, _base_point()))
    nonce = _sha512_int(prefix + message) % _L
    encoded_r = _compress(_point_multiply(nonce, _base_point()))
    challenge = _sha512_int(encoded_r + public_key + message) % _L
    scalar = (nonce + challenge * secret) % _L
    return encoded_r + scalar.to_bytes(32, "little")


def decode_key(value) -> bytes:
    """Decode a base64 public key and reject anything that is not a curve point."""
    try:
        raw = base64.b64decode(str(value).strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("Trusted key is not valid base64") from exc
    if len(raw) != PUBLIC_KEY_BYTES or _decompress(raw) is None:
        raise SignatureError("Trusted key is not a valid Ed25519 public key")
    return raw


def decode_signature(value) -> bytes:
    """Decode a base64 detached signature without raising on hostile input."""
    try:
        raw = base64.b64decode(str(value).strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("Signature is not valid base64") from exc
    if len(raw) != SIGNATURE_BYTES:
        raise SignatureError("Signature must decode to exactly 64 bytes")
    return raw
