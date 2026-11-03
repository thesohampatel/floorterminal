"""Bounded visible work for arbitrarily sized per-station reason catalogues."""

import math

from .layout import split_row


def reason_page(box, matches, page, *, searching=False):
    """Lay out one touch page, reserving a visible slot for automatic Others.

    Only visible cards are constructed. Search and page changes preserve the
    separate selection set. The footer belongs to the enclosing dialog, so no
    catalogue can push Report or Deselect off-screen.
    """
    a, b, c, d = box
    top = b + 28
    columns = max(2, min(4, int((c - a) / 220)))
    compact = (
        not searching and len(matches) + 2 <= max(1, int((d - top + 8) / 52)) * columns
    )
    bottom = d if compact else d - 56
    rows = max(1, int((bottom - top + 8) / 52))
    capacity = max(1, rows * columns - (2 if compact else 1))
    pages = max(1, math.ceil(len(matches) / capacity))
    page = max(0, min(page, pages - 1))
    visible = list(matches[page * capacity : (page + 1) * capacity])
    count = len(visible) + (2 if compact else 1)
    columns = min(columns, count)
    used_rows = math.ceil(count / columns)
    height = min(100, (bottom - top - (used_rows - 1) * 8) / used_rows)
    slots = [
        rect
        for row in range(used_rows)
        for rect in split_row(
            (a, top + row * (height + 8), c, top + row * (height + 8) + height),
            min(columns, count - row * columns),
        )
    ]
    controls = slots.pop() if compact else (a, d - 48, c, d)
    return visible, slots, page, pages, controls
