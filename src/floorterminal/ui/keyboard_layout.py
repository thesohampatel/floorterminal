"""Familiar keyboard rows, stable key sizes and bounded compact-screen paging."""

import math
import string


def keyboard_page(box, page=0, *, symbols=False):
    a, b, c, d = box
    columns = max(1, min(10, int((c - a + 6) // 50)))
    if columns < 10:
        # Split QWERTY rows into balanced halves instead of stranding one or
        # two letters beneath an almost-complete row on a portrait kiosk.
        columns = min(5, columns)
    source = (
        tuple(string.punctuation[i : i + 10] for i in range(0, 32, 10))
        if symbols
        else ("1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")
    )
    rows = []
    for row in source:
        chunk = math.ceil(len(row) / math.ceil(len(row) / columns))
        rows.extend(row[i : i + chunk] for i in range(0, len(row), chunk))
    available = max(1, int((d - b + 6) // 50))
    paged = len(rows) > available
    if paged:
        available = max(1, int((d - b - 50 + 6) // 50))
    pages = max(1, math.ceil(len(rows) / available))
    page = max(0, min(page, pages - 1))
    visible = rows[page * available : (page + 1) * available]
    bottom = d - 50 if paged else d
    key_width = min(72, (c - a - (columns - 1) * 6) / columns)
    used_rows = min(available, len(rows))
    key_height = min(56, (bottom - b - (used_rows - 1) * 6) / used_rows)
    keys = []
    for index, row in enumerate(visible):
        left = (a + c - len(row) * key_width - (len(row) - 1) * 6) / 2
        top = b + index * (key_height + 6)
        for offset, character in enumerate(row):
            x = left + offset * (key_width + 6)
            keys.append((character, (x, top, x + key_width, top + key_height)))
    return keys, page, pages, (a, d - 44, c, d) if paged else None
