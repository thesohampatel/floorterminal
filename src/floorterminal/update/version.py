"""Strict release-version parsing and ordering for the update subsystem."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Deliberately narrower than full SemVer: build metadata and long pre-release
# chains create ambiguous operator-visible ordering on a production terminal.
_PATTERN = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-(rc\.(?:[1-9]\d{0,2})))?$")


class VersionError(ValueError):
    """Raised when a version string is absent, malformed, or out of range."""


@dataclass(frozen=True, order=True)
class Version:
    """One comparable release identifier such as ``1.2.3`` or ``1.2.3-rc.4``."""

    major: int
    minor: int
    patch: int
    # 0 marks a release candidate and 1 marks the final release, so ``1.2.3-rc.4``
    # sorts before ``1.2.3`` while both remain comparable with plain tuples.
    release_rank: int = 1
    candidate: int = 0

    @classmethod
    def parse(cls, value) -> Version:
        text = str(value or "").strip()
        match = _PATTERN.fullmatch(text)
        if not match:
            raise VersionError(f"Unsupported version identifier: {value!r}")
        major, minor, patch, candidate = match.groups()
        if any(
            len(part) > 1 and part.startswith("0") for part in (major, minor, patch)
        ):
            raise VersionError(f"Version components must be canonical: {value!r}")
        if candidate is None:
            return cls(int(major), int(minor), int(patch), 1, 0)
        return cls(int(major), int(minor), int(patch), 0, int(candidate.split(".")[1]))

    def __str__(self):
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.release_rank else f"{base}-rc.{self.candidate}"


def parse(value) -> Version:
    """Parse ``value`` or raise :class:`VersionError`."""
    return Version.parse(value)


def try_parse(value):
    """Parse ``value`` and return ``None`` instead of raising for unusable text."""
    try:
        return Version.parse(value)
    except VersionError:
        return None


def is_newer(candidate, installed) -> bool:
    """Return whether ``candidate`` is a strictly newer release than ``installed``."""
    return parse(candidate) > parse(installed)


def compare(left, right) -> int:
    """Return -1, 0, or 1 for the ordering of two release identifiers."""
    first, second = parse(left), parse(right)
    return (first > second) - (first < second)
