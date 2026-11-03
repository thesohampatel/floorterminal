"""Bounded, regular-file-only JSON input at deployment trust boundaries."""

import json
import math
import os
import stat


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            # Do not put possibly sensitive field names/values in diagnostics.
            raise ValueError("Duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("JSON numbers must be finite")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        return _invalid_constant(value)
    return number


def read_bounded_bytes(path, *, max_bytes, private=False):
    """Read once through a checked descriptor; never follow a final symlink.

    NONBLOCK prevents named-pipe startup hangs. Parent directories are part of
    the trusted installation boundary, not an application sandbox.
    """
    if path.is_symlink():
        raise ValueError("Runtime JSON must not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("Runtime JSON must be a regular file without hard links")
        if metadata.st_size > max_bytes:
            raise ValueError(
                f"Runtime JSON exceeds the {max_bytes // 1024} KiB safety limit"
            )
        if private and hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("Runtime JSON grew beyond its safety limit")
        return payload
    finally:
        os.close(descriptor)


def read_bounded_json(path, *, max_bytes, private=False):
    payload = read_bounded_bytes(path, max_bytes=max_bytes, private=private)
    return decode_strict_json(payload)


def decode_strict_json(payload):
    """Decode already size-bounded JSON from either a file or an HTTP response."""
    try:
        return json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
            parse_float=_finite_float,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds safe parsing depth") from exc
