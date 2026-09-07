"""Validated user-interface locale resources with guaranteed English fallback."""

from __future__ import annotations

import json
from importlib.resources import files


def available_languages():
    """Return packaged locale identifiers in deterministic order."""
    try:
        values = sorted(
            item.name.removesuffix(".json")
            for item in files(__package__).iterdir()
            if item.name.endswith(".json")
        )
    except (FileNotFoundError, OSError):
        values = []
    return tuple(dict.fromkeys(("en", *values)))


def load_translator(language="en"):
    """Return a safe formatter; missing locale keys always fall back to English."""
    english = json.loads(
        files(__package__).joinpath("en.json").read_text(encoding="utf-8")
    )
    selected = english
    if language != "en":
        try:
            candidate = json.loads(
                files(__package__)
                .joinpath(f"{language}.json")
                .read_text(encoding="utf-8")
            )
            if isinstance(candidate, dict):
                selected = english | candidate
        except (FileNotFoundError, OSError, ValueError):
            selected = english

    # Positional-only, so a catalogue entry is free to use any placeholder name
    # — including "key" — without colliding with this parameter.
    def translate(key, /, **values):
        template = str(selected.get(key, english.get(key, key)))
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return str(english.get(key, key))

    return translate
