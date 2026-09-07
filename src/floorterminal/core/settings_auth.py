"""Installation-local Settings credentials, independent of signed build identity.

The build password is bootstrap access, never a fallback when a local verifier
exists. File-system administrators remain trusted: this is not an OS login lock.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from pathlib import Path

from .config import write_json
from .paths import RUNTIME_ROOT
from .project_profile import hash_settings_password, verify_settings_password

SETTINGS_AUTH_FILE = RUNTIME_ROOT / "settings_auth.json"
_HASH = re.compile(r"pbkdf2_sha256\$600000\$[0-9a-f]{32}\$[0-9a-f]{64}")


class SettingsAuthError(ValueError):
    """The local credential cannot safely be read or replaced."""


def validate_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise SettingsAuthError("Use 8–128 characters; 12 or more is recommended")
    if not password.isprintable() or any(character.isspace() for character in password):
        raise SettingsAuthError("Use printable characters without spaces")


class SettingsCredentials:
    def __init__(self, initial_hash, path=SETTINGS_AUTH_FILE):
        if not isinstance(initial_hash, str) or not _HASH.fullmatch(initial_hash):
            raise SettingsAuthError("The initial Settings credential is invalid")
        self.initial_hash = initial_hash
        self.path = Path(path)

    def current_hash(self):
        """Reload on each authorization; never cache an obsolete credential."""
        try:
            if self.path.is_symlink():
                raise SettingsAuthError(
                    "Settings credential must not be a symbolic link"
                )
            descriptor = os.open(
                self.path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
        except FileNotFoundError:
            return self.initial_hash
        except OSError as exc:
            raise SettingsAuthError(
                "Cannot read settings_auth.json; ask the system administrator"
            ) from exc
        try:
            with os.fdopen(descriptor, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
                    raise ValueError("invalid credential file")
                if hasattr(os, "fchmod"):
                    os.fchmod(stream.fileno(), 0o600)
                data = json.loads(stream.read(4097))
            if (
                not isinstance(data, dict)
                or set(data) != {"schema_version", "settings_password_hash"}
                or type(data["schema_version"]) is not int
                or data["schema_version"] != 1
                or not isinstance(data["settings_password_hash"], str)
                or not _HASH.fullmatch(data["settings_password_hash"])
            ):
                raise ValueError("invalid credential document")
            return data["settings_password_hash"]
        except (OSError, ValueError, UnicodeError) as exc:
            raise SettingsAuthError(
                "Settings credential cannot be trusted; restore settings_auth.json from a secure backup"
            ) from exc

    def verify(self, password):
        return verify_settings_password(password, self.current_hash())

    def replace(self, password, *, authorized_hash):
        """Commit only after fresh authorization; failed saves retain old access."""
        validate_password(password)
        current = self.current_hash()
        if not secrets.compare_digest(current, authorized_hash):
            raise SettingsAuthError("The password changed; cancel and authorize again")
        if verify_settings_password(password, current):
            raise SettingsAuthError("Choose a different password from the current one")
        if verify_settings_password(password, self.initial_hash):
            raise SettingsAuthError(
                "Choose a password different from the initial build password"
            )
        try:
            write_json(
                self.path,
                {
                    "schema_version": 1,
                    "settings_password_hash": hash_settings_password(password),
                },
            )
        except OSError as exc:
            raise SettingsAuthError(
                "Password not saved; check storage permissions and free space"
            ) from exc
