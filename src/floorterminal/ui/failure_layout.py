"""Bounded visible work for arbitrarily sized per-station reason catalogues."""

import math

from .layout import equal_grid


def reason_page(box, matches, page, *, searching=False):
    """Lay out one touch page, reserving a visible slot for automatic Others.

    Only visible cards are constructed. Search and page changes preserve the
    separate selection set. The footer belongs to the enclosing dialog, so no
    catalogue can push Report or Deselect off-screen.
    """
    a, b, c, d = box
    top = b + 28
    columns = max(2, min(4, int((c - a) / 220)))
    bottom = d - 56
    rows = max(1, int((bottom - top + 8) / 52))
    # Keep a small catalogue on one screen even at the compact minimum. Prefer
    # wider cards, but use another column before adding a page unnecessarily.
    maximum_columns = max(columns, min(4, int((c - a + 8) / 96)))
    if len(matches) + 1 <= rows * maximum_columns:
        columns = max(columns, math.ceil((len(matches) + 1) / rows))
    capacity = max(1, rows * columns - 1)
    pages = max(1, math.ceil(len(matches) / capacity))
    page = max(0, min(page, pages - 1))
    visible = list(matches[page * capacity : (page + 1) * capacity])
    count = len(visible) + 1
    columns = min(columns, count)
    slots = equal_grid((a, top, c, bottom), count, columns)
    controls = (a, d - 48, c, d)
    return visible, slots, page, pages, controls
