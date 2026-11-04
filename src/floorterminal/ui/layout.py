"""Pure, content-driven kiosk geometry (no monitor/model lookup table).

Coordinates are density-independent layout units. Small screens reflow instead
of shrinking touch targets; large screens grow gently, leaving room for content.
Physical touch calibration still belongs to deployment commissioning.
"""

from dataclasses import dataclass

TOUCH = 48
GAP = 8


@dataclass(frozen=True)
class Viewport:
    width: float
    height: float
    scale: float

    @classmethod
    def from_pixels(cls, width, height):
        width, height = max(1, width), max(1, height)
        # A tall kiosk should have physically larger controls, not a landscape
        # density with an enormous blank diagram. Choose density by orientation;
        # the resulting content dimensions still follow the actual viewport.
        portrait = height > width * 1.12
        scale = max(
            1.0,
            min(
                width / (480 if portrait else 800),
                height / (800 if portrait else 600),
                2.5,
            ),
        )
        return cls(width / scale, height / scale, scale)

    @property
    def stacked(self):
        return self.width < 720 or self.height > self.width * 1.12

    @property
    def paged(self):
        return self.height < (640 if self.stacked else 450)

    @property
    def usable(self):
        return self.width >= 320 and self.height >= 400


def split_row(box, count, gap=GAP):
    """Equal, non-overlapping controls, in reading order."""
    x1, y1, x2, y2 = box
    width = (x2 - x1 - gap * (count - 1)) / count
    return [
        (x1 + i * (width + gap), y1, x1 + i * (width + gap) + width, y2)
        for i in range(count)
    ]


def station_capacity(width):
    """Reserve navigation space, then fit readable 88-unit station cards."""
    return max(1, int((width - 112) // 96))


def header_regions(width):
    """Clock never shares text space with the line name or connection notice."""
    controls = (width - 172, 7, width - 12, 55)
    if width >= 680:
        clock = (width - 312, 7, width - 184, 55)
        title_right, feedback_right = clock[0] - 12, width - 12
    else:
        clock = (width - 136, 64, width - 12, 104)
        title_right, feedback_right = controls[0] - 12, clock[0] - 8
    return controls, clock, title_right, feedback_right


def equal_grid(box, count, columns, *, gap=8, max_height=100):
    """Equal-size cards, including the last row; centre an incomplete row."""
    if count <= 0:
        return []
    a, b, c, d = box
    columns = min(columns, count)
    rows = (count + columns - 1) // columns
    width = (c - a - (columns - 1) * gap) / columns
    height = min(max_height, (d - b - (rows - 1) * gap) / rows)
    rectangles = []
    for row in range(rows):
        used = min(columns, count - row * columns)
        left = (a + c - used * width - (used - 1) * gap) / 2
        top = b + row * (height + gap)
        rectangles.extend(
            (
                left + i * (width + gap),
                top,
                left + i * (width + gap) + width,
                top + height,
            )
            for i in range(used)
        )
    return rectangles


def text_pages(lines, capacity):
    """Page measured text without leaving a section heading at the bottom.

    Blank separator lines may be trimmed at page boundaries, never actual text.
    A one-line viewport cannot keep a heading/body pair, but still makes forward
    progress and preserves all content.
    """
    capacity = max(1, capacity)
    pages, start = [], 0
    while start < len(lines):
        if not lines[start][0]:
            start += 1
            continue
        end = min(len(lines), start + capacity)
        if end < len(lines) and lines[end - 1][1] and end - start > 1:
            end -= 1
        page = list(lines[start:end])
        while page and not page[-1][0]:
            page.pop()
        pages.append(page)
        start = end
    return pages or [[]]
