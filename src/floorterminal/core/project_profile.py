"""Validated project metadata and administrator-access policy."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import RUNTIME_ROOT


class ProjectProfileError(ValueError):
    """Raised when the immutable project metadata is missing or unsafe."""


@dataclass(frozen=True)
class ProjectProfile:
    schema_version: int
    product_name: str
    product_short_name: str
    product_tagline: str
    maintainer_name: str
    distribution_name: str
    support_contact: str
    license_name: str
    license_identifier: str
    license_version: str
    license_summary: str
    copyright_notice: str
    legal_notice: str
    settings_password_hash: str


_LIMITS = {
    "product_name": 64,
    "product_short_name": 28,
    "product_tagline": 72,
    "maintainer_name": 64,
    "distribution_name": 80,
    "support_contact": 100,
    "license_name": 48,
    "license_identifier": 80,
    "license_version": 16,
    "license_summary": 180,
    "copyright_notice": 120,
    "legal_notice": 360,
}
_COMMON_FIELDS = {"schema_version", *_LIMITS}
_SOURCE_PASSWORD_FIELD = "settings_password"
_EMBEDDED_PASSWORD_FIELD = "settings_password_hash"
_PASSWORD_ENV = "FLOORTERMINAL_SETTINGS_PASSWORD"
_PASSWORD_PLACEHOLDER = "${FLOORTERMINAL_SETTINGS_PASSWORD}"
# Public key-derivation metadata, not password material.
_KDF_SCHEME = "pbkdf2_sha256"
_KDF_ITERATIONS = 600_000
_FORBIDDEN_PASSWORDS = {"CHANGE_THIS_BEFORE_BUILD"}


def hash_settings_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _KDF_ITERATIONS
    )
    return f"{_KDF_SCHEME}${_KDF_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_settings_password(password, encoded):
    try:
        scheme, iterations, salt, expected = encoded.split("$", 3)
        if scheme != _KDF_SCHEME or int(iterations) != _KDF_ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        ).hex()
    except (TypeError, ValueError):
        return False
    return secrets.compare_digest(actual, expected)


def project_profile_path() -> Path:
    override = os.environ.get("FLOORTERMINAL_PROJECT_PROFILE_FILE")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle / "project_profile.json"
    return RUNTIME_ROOT / "project_profile.json"


def load_project_profile(path=None) -> ProjectProfile:
    source = Path(path) if path is not None else project_profile_path()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectProfileError(
            f"Cannot read project profile {source}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ProjectProfileError(
            f"Invalid project profile JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not isinstance(data, dict):
        raise ProjectProfileError("Project profile must contain one JSON object")
    if data.get("schema_version") != 1:
        raise ProjectProfileError("Unsupported project profile schema_version; expected 1")

    has_source_password = _SOURCE_PASSWORD_FIELD in data
    has_embedded_hash = _EMBEDDED_PASSWORD_FIELD in data
    if has_source_password == has_embedded_hash:
        raise ProjectProfileError(
            "Project profile must contain exactly one settings password field"
        )
    expected = _COMMON_FIELDS | {
        _SOURCE_PASSWORD_FIELD if has_source_password else _EMBEDDED_PASSWORD_FIELD
    }
    missing = sorted(expected - set(data))
    unknown = sorted(set(data) - expected)
    if missing:
        raise ProjectProfileError("Project profile is missing: " + ", ".join(missing))
    if unknown:
        raise ProjectProfileError(
            "Project profile contains unsupported fields: " + ", ".join(unknown)
        )

    values = {"schema_version": 1}
    for key, maximum in _LIMITS.items():
        value = str(data[key]).strip()
        if not value:
            raise ProjectProfileError(f"ProjectProfile field {key} cannot be empty")
        if len(value) > maximum:
            raise ProjectProfileError(f"ProjectProfile field {key} exceeds {maximum} characters")
        if any(ord(character) < 32 and character not in "\t" for character in value):
            raise ProjectProfileError(f"ProjectProfile field {key} contains control characters")
        values[key] = value
    if values["license_identifier"] != "MIT" or values["license_name"] != "MIT License":
        raise ProjectProfileError("Open-source builds must use the MIT license identity")

    if has_source_password:
        password = data[_SOURCE_PASSWORD_FIELD]
        if not isinstance(password, str):
            raise ProjectProfileError("settings_password must be a string")
        if password == _PASSWORD_PLACEHOLDER:
            password = os.environ.get(_PASSWORD_ENV, "")
            if not password:
                raise ProjectProfileError(
                    f"Set {_PASSWORD_ENV} before running or building the application"
                )
        if password in _FORBIDDEN_PASSWORDS:
            raise ProjectProfileError(
                "Replace the placeholder settings_password before running or building"
            )
        if password != password.strip():
            raise ProjectProfileError("settings_password cannot start or end with whitespace")
        if not 8 <= len(password) <= 128:
            raise ProjectProfileError("settings_password must contain 8 to 128 characters")
        if any(ord(character) < 33 or ord(character) == 127 for character in password):
            raise ProjectProfileError("settings_password contains unsupported characters")
        values[_EMBEDDED_PASSWORD_FIELD] = hash_settings_password(password)
    else:
        password_hash = str(data[_EMBEDDED_PASSWORD_FIELD])
        pattern = rf"{_KDF_SCHEME}\${_KDF_ITERATIONS}\$[0-9a-f]{{32}}\$[0-9a-f]{{64}}"
        if not re.fullmatch(pattern, password_hash):
            raise ProjectProfileError("settings_password_hash must be a valid PBKDF2 hash")
        values[_EMBEDDED_PASSWORD_FIELD] = password_hash
    return ProjectProfile(**values)
