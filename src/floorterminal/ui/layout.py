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
