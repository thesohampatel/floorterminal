"""Header update indicator and the Software Update panel.

The indicator is one small control beside the information button. It is purely
informational: whatever colour it shows, every reporting, timing, connector, and
Settings function behaves exactly as it does when the update subsystem is absent.
The panel it opens explains, in plain language, which version is running, what that
version contains, whether a newer one exists, and how a site performs the offline
update itself.
"""

from __future__ import annotations

from ..update import LEVEL_ATTENTION, LEVEL_OK, LEVEL_UNKNOWN, UpdateStatus

#: Shown when the update subsystem could not be constructed at all. Every drawing
#: path therefore has a complete, safe snapshot to render.
UNAVAILABLE_STATUS = UpdateStatus(
    level=LEVEL_UNKNOWN,
    headline="Update status is unavailable",
    detail=(
        "The update subsystem could not be started on this terminal. Reporting, "
        "timers, connectors, and Settings are unaffected."
    ),
)

TAB_KEYS = ("status", "version", "changes", "activity")
#: Catalogue keys for each tab and each recorded activation action. Diagnostic
#: text produced by the update service itself stays in English, as error text does
#: elsewhere in the console.
TAB_LABELS = {key: f"update_tab_{key}" for key in TAB_KEYS}
_ACTION_LABELS = {
    "activated": "update_action_activated",
    "rolled_back": "update_action_rolled_back",
    "watchdog_rollback": "update_action_watchdog",
    "confirmed": "update_action_confirmed",
    "reconciled": "update_action_reconciled",
}


def _clip(value, limit):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _stamp(value):
    """Render a journal timestamp as a readable UTC instant."""
    text = str(value or "")
    if len(text) >= 16 and text[10] == "T":
        return f"{text[:10]}  {text[11:16]} UTC"
    return _clip(text, 22)


class UpdateViewMixin:
    """Drawing for the software-update indicator and its panel."""

    def update_status(self):
        """Return the current update snapshot, or a safe placeholder."""
        service = getattr(self, "update_service", None)
        if service is None:
            return UNAVAILABLE_STATUS
        return service.status()

    def update_level_style(self, level):
        """Return the accent colour, surface tint, and glyph for one level."""
        return {
            LEVEL_OK: (self.GREEN, "#EAF7F0", "check"),
            LEVEL_ATTENTION: (self.ORANGE, "#FFF5E8", "download"),
            LEVEL_UNKNOWN: (self.RED, "#FDECEE", "question"),
        }.get(level, (self.MUTED, "#F1F4F8", "question"))

    def draw_update_glyph(self, cx, cy, glyph, color, scale=1.0):
        """Draw a vector status mark so no platform emoji font is required."""
        stroke = max(1, round(2 * scale))
        if glyph == "check":
            self.canvas.create_line(
                cx - 5 * scale, cy,
                cx - 1.5 * scale, cy + 4 * scale,
                cx + 5.5 * scale, cy - 4.5 * scale,
                fill=color, width=stroke + 1, capstyle="round", joinstyle="round",
            )
        elif glyph == "download":
            self.canvas.create_line(
                cx, cy - 6 * scale, cx, cy + 2.5 * scale,
                fill=color, width=stroke, capstyle="round",
            )
            self.canvas.create_line(
                cx - 4 * scale, cy - 1.5 * scale,
                cx, cy + 3 * scale,
                cx + 4 * scale, cy - 1.5 * scale,
                fill=color, width=stroke, capstyle="round", joinstyle="round",
            )
            self.canvas.create_line(
                cx - 5.5 * scale, cy + 6 * scale, cx + 5.5 * scale, cy + 6 * scale,
                fill=color, width=stroke, capstyle="round",
            )
        else:
            self.canvas.create_arc(
                cx - 4.6 * scale, cy - 8 * scale, cx + 4.6 * scale, cy + 1.2 * scale,
                start=210, extent=-240, style="arc", outline=color,
                width=stroke + 0.6,
            )
            self.canvas.create_line(
                cx, cy - 0.6 * scale, cx, cy + 2.6 * scale,
                fill=color, width=stroke + 0.6, capstyle="round",
            )
            self.canvas.create_oval(
                cx - 1.3 * scale, cy + 4.8 * scale,
                cx + 1.3 * scale, cy + 7.4 * scale,
                fill=color, outline="",
            )

    def draw_update_indicator(self, box):
        """Draw the small header control and register its touch target."""
        status = self.update_status()
        accent, tint, glyph = self.update_level_style(status.level)
        x1, y1, x2, y2 = box
        pressed = self.pressed == "software_update"
        offset = 2 if pressed else 0
        self.rounded(x1, y1 + offset, x2, y2 + offset, 11, tint, accent, 1)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2 + offset
        self.canvas.create_oval(
            cx - 10, cy - 10, cx + 10, cy + 10, fill=accent, outline=""
        )
        self.draw_update_glyph(cx, cy, glyph, "#FFFFFF", 1.05)
        if status.level != LEVEL_OK:
            # A second redundant cue so the control is not identified by colour
            # alone, matching the accessibility rule used across the console.
            self.canvas.create_oval(
                x2 - 9, y1 + offset + 1, x2 - 1, y1 + offset + 9,
                fill=accent, outline="#FFFFFF", width=1,
            )
        self.hitboxes["software_update"] = box

    # ------------------------------------------------------------------ panel

    def draw_update_panel(self):
        """Route every screen size through the shared adaptive dialog layout."""
        self.adaptive_update_dialog()

    def _installed_catalog_entry(self):
        from ..update import installed_entry

        return installed_entry()
