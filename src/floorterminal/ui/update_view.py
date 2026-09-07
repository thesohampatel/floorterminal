"""Header update indicator and the Software Update panel.

The indicator is one small control beside the information button. It is purely
informational: whatever colour it shows, every reporting, timing, connector, and
Settings function behaves exactly as it does when the update subsystem is absent.
The panel it opens explains, in plain language, which version is running, what that
version contains, whether a newer one exists, and how a site performs the offline
update itself.
"""

from __future__ import annotations

from .. import __version__
from ..update import LEVEL_ATTENTION, LEVEL_OK, LEVEL_UNKNOWN, UpdateStatus
from ..update import trust as update_trust

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

PANEL = (46, 14, 754, 466)
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
        status = self.update_status()
        accent, tint, glyph = self.update_level_style(status.level)
        page = self.modal.get("page", "status")
        x1, y1, x2, y2 = PANEL
        self.rounded(x1, y1, x2, y2, 25, self.CARD)

        self.canvas.create_oval(70, 32, 118, 80, fill=tint, outline=accent, width=2)
        self.draw_update_glyph(94, 56, glyph, accent, 1.9)
        self.text(134, 30, self.t("update_heading"), 7, self.BLUE, "bold")
        self.text(134, 46, _clip(status.headline, 62), 12, self.TEXT, "bold", width=470)
        self.rounded(618, 32, 736, 60, 9, "#F3F6FA", self.BORDER)
        self.text(
            677,
            46,
            self.t("update_running_version", version=__version__),
            7,
            self.TEXT,
            "bold",
            "center",
        )

        for index, key in enumerate(TAB_KEYS):
            left = 68 + index * 169
            box = (left, 84, left + 161, 131)
            active = page == key
            self.rounded(
                *box, 9, self.PALE_BLUE if active else "#F4F6FA",
                self.BLUE if active else self.BORDER, 2 if active else 1,
            )
            self.text(
                (box[0] + box[2]) / 2, 107, self.t(TAB_LABELS[key]), 7,
                self.BLUE if active else self.MUTED, "bold", "center",
            )
            self.hitboxes[f"update_tab_{key}"] = box

        drawing = {
            "status": self._update_status_page,
            "version": self._update_version_page,
            "changes": self._update_changes_page,
            "activity": self._update_activity_page,
        }[page]
        drawing(status, accent, tint)
        self._update_footer(status)

    def _update_status_page(self, status, accent, tint):
        self.rounded(68, 139, 736, 187, 12, tint, accent, 1)
        self.text(
            88, 149,
            _clip(status.detail, 300) or self.t("update_no_detail"),
            8, self.TEXT, width=630,
        )

        self.rounded(68, 192, 396, 294, 12, "#F7F9FC", self.BORDER)
        self.text(88, 204, self.t("update_installed_here"), 6, self.MUTED, "bold")
        self.text(
            88,
            220,
            self.t("update_version_number", version=status.installed_version),
            14,
            self.TEXT,
            "bold",
        )
        entry = self._installed_catalog_entry()
        self.text(
            88, 244,
            self.t("update_released_on", date=entry.released_utc[:10])
            if entry
            else self.t("update_release_date_unknown"),
            7, self.MUTED,
        )
        self.text(88, 260, self.t("update_installation"), 6, self.MUTED, "bold")
        self.text(
            88, 272,
            self.t("update_slots_with_rollback")
            if status.can_rollback
            else (
                self.t("update_slots")
                if status.managed
                else self.t("update_standard_install")
            ),
            7, self.TEXT, "bold", width=290,
        )

        self.rounded(408, 192, 736, 294, 12, "#F7F9FC", self.BORDER)
        self.text(428, 204, self.t("update_latest_published"), 6, self.MUTED, "bold")
        channel = status.channel
        if status.latest_version:
            self.text(
                428,
                220,
                self.t("update_version_number", version=status.latest_version),
                14,
                self.TEXT,
                "bold",
            )
            self.text(
                428,
                244,
                self.t("update_released_on", date=channel.released_utc[:10]),
                7,
                self.MUTED,
            )
            self.text(428, 260, self.t("update_published_release"), 6, self.MUTED, "bold")
            self.text(
                428, 272, _clip(channel.release_title, 44), 7, self.TEXT, "bold", width=290
            )
        else:
            self.text(428, 220, self.t("update_not_known"), 14, self.MUTED, "bold")
            self.text(
                428, 246,
                self.t("update_publish_unconfirmed"),
                7, self.MUTED, width=290,
            )

        self.rounded(68, 302, 736, 396, 12, "#EEF6FF", "#BCD5F5")
        self.text(88, 312, self.t("update_how_to"), 7, self.BLUE, "bold")
        self.text(
            88, 330,
            self.t("update_step_download", url=update_trust.RELEASES_URL),
            7, self.TEXT, width=630,
        )
        self.text(
            88, 348,
            self.t(
                "update_step_prepare",
                label=update_trust.UPDATE_VOLUME_LABELS[0],
                folder=update_trust.UPDATE_PACKAGE_DIRNAME,
            ),
            7, self.TEXT, width=630,
        )
        self.text(
            88, 366,
            self.t("update_step_insert"),
            7, self.TEXT, width=630,
        )
        self.text(
            88, 384,
            self.t(
                "update_need_help",
                maintainer=update_trust.MAINTAINER_NAME,
                email=update_trust.MAINTAINER_EMAIL,
            ),
            7, self.MUTED, "bold", width=630,
        )

    def _installed_catalog_entry(self):
        from ..update import installed_entry

        return installed_entry()

    def _update_version_page(self, status, accent, tint):
        entry = self._installed_catalog_entry()
        self.rounded(68, 139, 736, 187, 12, "#F7F9FC", self.BORDER)
        self.text(
            88, 147,
            entry.title if entry else f"FloorTerminal {status.installed_version}",
            11, self.TEXT, "bold", width=630,
        )
        self.text(
            88, 165,
            entry.summary if entry else self.t("update_no_capabilities"),
            7, self.MUTED, width=630,
        )
        self.text(88, 194, self.t("update_capabilities"), 6, self.BLUE, "bold")
        features = list(status.installed_features)[:12]
        for index, feature in enumerate(features):
            column, row = divmod(index, 6)
            x = 88 + column * 334
            y = 212 + row * 26
            self.canvas.create_oval(x, y + 3, x + 7, y + 10, fill=self.GREEN, outline="")
            self.text(x + 15, y, _clip(feature, 56), 7, self.TEXT)
        if not features:
            self.text(
                88, 212,
                self.t("update_no_capabilities"),
                8, self.MUTED,
            )
        self.rounded(68, 368, 736, 396, 9, "#F4F6FA", self.BORDER)
        self.text(
            88, 375,
            self.t(
                "update_maintained_by",
                maintainer=update_trust.MAINTAINER_NAME,
                email=update_trust.MAINTAINER_EMAIL,
                url=update_trust.PROJECT_URL,
            ),
            6, self.MUTED, "bold", width=630,
        )

    def _update_changes_page(self, status, accent, tint):
        staged, channel = status.staged, status.channel
        if staged:
            title = self.t("update_ready_title", version=staged.version)
            summary = staged.release_summary
            heading = staged.release_title
            highlights = staged.highlights
        elif status.update_available and channel:
            title = self.t("update_available_title", version=channel.version)
            summary = channel.release_summary
            heading = channel.release_title
            highlights = channel.highlights()
        else:
            self.rounded(68, 139, 736, 396, 12, "#F7F9FC", self.BORDER)
            self.text(88, 158, self.t("update_none_known"), 13, self.TEXT, "bold")
            self.text(
                88, 186,
                self.t("update_none_known_detail"),
                8, self.MUTED, width=630,
            )
            self.text(88, 250, self.t("update_where_from"), 6, self.BLUE, "bold")
            self.text(
                88, 268,
                self.t(
                    "update_where_from_detail",
                    maintainer=update_trust.MAINTAINER_NAME,
                    url=update_trust.RELEASES_URL,
                ),
                8, self.TEXT, width=630,
            )
            return
        self.rounded(68, 139, 736, 197, 12, "#FFF5E8", self.ORANGE, 1)
        self.text(88, 146, title, 11, self.TEXT, "bold", width=630)
        self.text(88, 164, _clip(heading, 78), 8, "#8A5A00", "bold", width=630)
        self.text(88, 178, _clip(summary, 190), 7, self.TEXT, width=630)
        self.text(88, 206, self.t("update_changes_heading"), 6, self.BLUE, "bold")
        palette = {"NEW": self.GREEN, "FIX": self.BLUE, "SECURITY": self.RED}
        # Six rows leave the verification band clear at the foot of the panel.
        for index, (kind, item) in enumerate(highlights[:6]):
            y = 224 + index * 23
            self.rounded(88, y, 148, y + 16, 6, "#F1F4F8", self.BORDER)
            self.text(
                118,
                y + 8,
                self.t(f"update_change_{kind.lower()}"),
                6,
                palette.get(kind, self.MUTED),
                "bold",
                "center",
            )
            self.text(158, y + 1, _clip(item, 92), 7, self.TEXT, width=560)
        if staged:
            self.rounded(68, 368, 736, 396, 9, "#EAF7F0", self.GREEN)
            self.text(
                88, 375,
                self.t(
                    "update_verified_here",
                    key=staged.signing_key_id,
                    digest=staged.artifact_sha256[:16],
                ),
                6, self.TEXT, "bold", width=630,
            )

    def _update_activity_page(self, status, accent, tint):
        self.text(88, 140, self.t("update_recent_activity"), 6, self.BLUE, "bold")
        history = list(reversed(status.history))[:8]
        if not history:
            self.rounded(68, 158, 736, 396, 12, "#F7F9FC", self.BORDER)
            self.text(88, 180, self.t("update_no_activity"), 12, self.TEXT, "bold")
            self.text(
                88, 206,
                self.t("update_no_activity_detail"),
                8, self.MUTED, width=630,
            )
            return
        for index, entry in enumerate(history):
            y = 158 + index * 30
            outcome = str(entry.get("outcome", "ok"))
            color = self.GREEN if outcome == "ok" else self.ORANGE
            self.rounded(68, y, 736, y + 26, 8, "#F7F9FC", self.BORDER)
            self.canvas.create_oval(82, y + 10, 90, y + 18, fill=color, outline="")
            self.text(
                100, y + 8,
                self.t(_ACTION_LABELS[str(entry.get("action"))])
                if str(entry.get("action")) in _ACTION_LABELS
                else str(entry.get("action"))[:28],
                7, self.TEXT, "bold",
            )
            versions = " → ".join(
                part for part in (entry.get("from_version"), entry.get("to_version")) if part
            )
            self.text(258, y + 8, _clip(versions, 20), 7, self.MUTED, "bold")
            self.text(
                386, y + 8,
                _clip(entry.get("authorized_by") or entry.get("source") or "system", 30),
                7, self.MUTED,
            )
            self.text(722, y + 8, _stamp(entry.get("at_utc")), 6, self.MUTED, "bold", "e")

    def _update_footer(self, status):
        self.button(
            "cancel", (68, 403, 196, 450), self.t("close_panel"), "#E1E9F4", "X", fg=self.TEXT
        )
        self.button(
            "update_check",
            (204, 403, 332, 450),
            self.t("update_checking") if status.checking else self.t("update_check_again"),
            "#E1E9F4",
            fg=self.TEXT,
        )
        self.button(
            "update_scan",
            (340, 403, 468, 450),
            self.t("update_scan_drive"),
            "#E1E9F4",
            fg=self.TEXT,
        )
        if status.can_install and status.can_rollback:
            self.button(
                "update_install", (492, 403, 612, 450), self.t("update_install"), self.ORANGE, "OK"
            )
            self.button(
                "update_rollback",
                (620, 403, 736, 450),
                self.t("update_restore"),
                "#FDECEE",
                fg=self.RED,
            )
        elif status.can_install:
            self.button(
                "update_install",
                (492, 403, 736, 450),
                self.t("update_install_version", version=status.staged.version),
                self.ORANGE,
                "OK",
            )
        elif status.can_rollback:
            self.button(
                "update_rollback",
                (492, 403, 736, 450),
                self.t("update_restore_version", version=status.rollback_version),
                "#FDECEE",
                fg=self.RED,
            )
        else:
            self.rounded(492, 403, 736, 450, 11, "#F4F6FA", self.BORDER)
            self.text(
                614, 427,
                self.t("update_no_action"),
                7, self.MUTED, "bold", "center",
            )
