"""Measured, responsive information cards; bounded text pagination on small panels."""

import math

from .layout import split_row


class ContentCardsMixin:
    def content_cards(self, box, sections):
        a, b, c, d = box
        columns = 2 if c - a >= 660 and len(sections) > 1 else 1
        measured = []
        for index, (_, value) in enumerate(sections):
            used = min(columns, len(sections) - index // columns * columns)
            width = (c - a - 12 * (used - 1)) / used
            measured.append(self.wrap_lines(value, width - 32, 10))
        rows = math.ceil(len(sections) / columns)
        heights = [
            max(76, 48 + 20 * max(len(v) for v in measured[i : i + columns]))
            for i in range(0, len(sections), columns)
        ]
        needed = sum(heights) + 12 * (rows - 1)
        if needed > d - b:
            # Same content, no tiny type or clipping. Existing touch pagination
            # keeps headings and body together and never uses a desktop scrollbar.
            self.paragraph_page(box, sections)
            return
        self.modal["layout_page"], self.modal["layout_pages"] = 0, 1
        extra = min(28, max(0, (d - b - needed) / rows))
        top = b
        for row, height in enumerate(heights):
            start = row * columns
            count = min(columns, len(sections) - start)
            for index, rect in enumerate(
                split_row((a, top, c, top + height + extra), count, gap=12), start
            ):
                x, y, right, _bottom = rect
                self.rounded(*rect, 18, self.CARD, self.BORDER)
                self.rounded(x + 14, y + 16, x + 18, y + 32, 2, self.BLUE)
                self.row_label(
                    (x + 28, y + 10, right - 16, y + 38),
                    sections[index][0],
                    10,
                    self.BLUE,
                )
                for line, value in enumerate(measured[index]):
                    self.text(
                        x + 16, y + 44 + line * 20, value, 10, self.TEXT, "normal"
                    )
            top += height + extra + 12
