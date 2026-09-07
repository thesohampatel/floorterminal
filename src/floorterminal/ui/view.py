"""Canvas rendering for the line reporting console."""

from __future__ import annotations

import math
import time
from datetime import datetime

from .. import __version__
from .contrast import TEXT_MINIMUM, contrast_ratio, readable_label, text_variant

#: Responders shown per page. Four keeps every row a full-size touch target on
#: the smallest supported panel; longer rosters page.
RESPONDER_PAGE_SIZE = 4
from .update_view import UpdateViewMixin


class OperatorViewMixin(UpdateViewMixin):
    @staticmethod
    def font(size, weight="normal"):
        return ("Helvetica", size, weight)

    def rounded(
        self, x1, y1, x2, y2, radius=16, fill="white", outline="", width=1, tags=()
    ):
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.canvas.create_polygon(
            points,
            smooth=True,
            splinesteps=20,
            fill=fill,
            outline=outline,
            width=width,
            tags=tags,
        )

    #: Below this point size text is judged against the normal-text contrast
    #: threshold rather than the large-text one.
    SMALL_TEXT_SIZE = 10

    def text(
        self, x, y, value, size=12, color=None, weight="normal", anchor="nw", **kwargs
    ):
        return self.canvas.create_text(
            x,
            y,
            text=value,
            font=self.font(size, weight),
            fill=self.readable_text(color or self.TEXT, size),
            anchor=anchor,
            **kwargs,
        )

    def draw_brand_mark(self, x, y, logical_size):
        """Draw the closest packaged logo size for the active display scale."""
        images = getattr(self, "brand_images", {})
        if not images:
            return False
        target = logical_size * getattr(self.canvas, "scale_factor", 1.0)
        size = min(images, key=lambda candidate: abs(candidate - target))
        self.canvas.create_image(x, y, image=images[size], anchor="center")
        return True

    def readable_text(self, color, size):
        """Darken a palette status colour used as small text until it is readable.

        A palette colour has to serve both as a status fill, where the spread of
        lightness is what keeps the colours apart, and as small text, where a high
        ratio against a pale surface is required. Only the text role is adjusted,
        and only the lightness moves, so fills and their meaning are untouched.

        The substitution is deliberately limited to the five status colours and the
        muted colour. Anything else — white on a filled control, the dark text
        colour, a one-off tint — is drawn exactly as the caller asked, because only
        the caller knows what surface it sits on.
        """
        if size >= self.SMALL_TEXT_SIZE:
            return color
        adjustable = getattr(self, "_adjustable_text", None)
        if adjustable is None or self._adjustable_for != self.BG:
            adjustable = self._adjustable_text = {
                self.MUTED,
                self.RED,
                self.GREEN,
                self.BLUE,
                self.ORANGE,
                self.PURPLE,
            }
            self._adjustable_for = self.BG
            self._text_variants = {}
        if color not in adjustable:
            return color
        if color not in self._text_variants:
            try:
                self._text_variants[color] = (
                    color
                    if contrast_ratio(color, self.BG) >= TEXT_MINIMUM
                    else text_variant(color, self.BG)
                )
            except ValueError:
                self._text_variants[color] = color
        return self._text_variants[color]

    def button(self, key, box, label, fill, icon="", fg="white"):
        x1, y1, x2, y2 = box
        pressed = self.pressed == key
        offset = 2 if pressed else 0
        width = x2 - x1
        height = y2 - y1
        secondary = fg != "white"
        light_surfaces = {"#EEF2F7", "#E9EEF5", "#E9EDF3"}
        if secondary and fill in light_surfaces:
            fill = "#E1E9F4"
        destructive = secondary and fg == self.RED
        shadow = "#E4BFC3" if destructive else ("#BCC8D7" if secondary else "#D7DEE8")
        outline = "#DEA0A7" if destructive else ("#AEBED1" if secondary else "")
        if not pressed:
            self.rounded(x1, y1 + 3, x2, y2 + 3, 13, shadow)
        self.rounded(x1, y1 + offset, x2, y2 + offset, 13, fill, outline, 1)
        label_x = (x1 + x2) / 2
        label_size = 11 if height >= 44 else (9 if height >= 34 else 8)
        if len(label) > 30 and width < 400:
            label_size = max(7, label_size - 1)
        # The icon sits in a fixed left lane while the label stays centred, so a
        # long label on a narrow control would run into the badge. The label is
        # the information and the badge is decoration, so the badge gives way.
        # 0.78 em is the measured average advance of the bold interface face.
        badge_right = 10 + 2 * min(17, max(9, (height - 12) / 2))
        label_left = width / 2 - (len(label) * label_size * 0.78) / 2
        if icon and label_left < badge_right + 8:
            icon = ""
        if icon:
            radius = min(17, max(9, (height - 12) / 2))
            badge_x = x1 + radius + 10
            badge_y = (y1 + y2) / 2 + offset
            self.canvas.create_oval(
                badge_x - radius,
                badge_y - radius,
                badge_x + radius,
                badge_y + radius,
                fill="#FFFFFF",
                outline="#E1E7F0",
                width=1,
            )
            self.draw_button_icon(
                badge_x,
                badge_y,
                icon,
                fill if fg == "white" else self.TEXT,
                radius,
            )
            # Icons have their own fixed lane; labels remain centered on every
            # button, so controls align consistently across the whole screen.
        if label:
            self.text(
                label_x,
                (y1 + y2) / 2 + offset,
                label,
                label_size,
                self.label_color(fill, fg),
                "bold",
                "center",
            )
        self.hitboxes[key] = box

    def label_color(self, fill, requested):
        """Keep a control label legible on its own fill.

        The requested colour is honoured whenever it is readable, so the
        established appearance is unchanged. A white label is replaced with the
        dark text colour only where white would fall below the minimum ratio for
        a bold control label — which is what happens on the amber surfaces, and
        what would otherwise happen on a pale deployment-chosen custom palette.
        """
        if requested != "white":
            return requested
        return readable_label(fill, self.TEXT)

    def draw_button_icon(self, cx, cy, icon, color, radius):
        """Draw crisp font-independent action symbols with a text fallback."""
        scale = radius / 17
        stroke = max(1, round(2 * scale))
        if icon in {"OK", "✓"}:
            self.canvas.create_line(
                cx - 7 * scale,
                cy,
                cx - 2 * scale,
                cy + 5 * scale,
                cx + 8 * scale,
                cy - 6 * scale,
                fill=color,
                width=stroke + 1,
                capstyle="round",
                joinstyle="round",
            )
        elif icon == "!":
            self.canvas.create_line(
                cx,
                cy - 8 * scale,
                cx,
                cy + 2 * scale,
                fill=color,
                width=stroke + 1,
                capstyle="round",
            )
            self.canvas.create_oval(
                cx - 1.7 * scale,
                cy + 6 * scale,
                cx + 1.7 * scale,
                cy + 9.4 * scale,
                fill=color,
                outline="",
            )
        elif icon == ">":
            # Wrench: the engineer-arrival action means work is starting, not
            # merely navigation to another page.
            self.canvas.create_line(
                cx - 6 * scale,
                cy + 7 * scale,
                cx + 5 * scale,
                cy - 4 * scale,
                fill=color,
                width=stroke + 2,
                capstyle="round",
            )
            self.canvas.create_arc(
                cx + 1 * scale,
                cy - 10 * scale,
                cx + 11 * scale,
                cy,
                start=35,
                extent=230,
                style="arc",
                outline=color,
                width=stroke,
            )
            self.canvas.create_oval(
                cx - 9 * scale,
                cy + 4 * scale,
                cx - 4 * scale,
                cy + 9 * scale,
                outline=color,
                width=stroke,
            )
        elif icon == "R":
            self.canvas.create_arc(
                cx - 8 * scale,
                cy - 8 * scale,
                cx + 8 * scale,
                cy + 8 * scale,
                start=35,
                extent=285,
                style="arc",
                outline=color,
                width=stroke,
            )
            self.canvas.create_line(
                cx + 5 * scale,
                cy - 8 * scale,
                cx + 9 * scale,
                cy - 7 * scale,
                cx + 8 * scale,
                cy - 3 * scale,
                fill=color,
                width=stroke,
            )
        elif icon == "+":
            # Two people with a plus sign for crew changes.
            for dx in (-5, 2):
                self.canvas.create_oval(
                    cx + (dx - 2) * scale,
                    cy - 8 * scale,
                    cx + (dx + 2) * scale,
                    cy - 4 * scale,
                    outline=color,
                    width=stroke,
                )
                self.canvas.create_arc(
                    cx + (dx - 4) * scale,
                    cy - 2 * scale,
                    cx + (dx + 4) * scale,
                    cy + 7 * scale,
                    start=0,
                    extent=180,
                    style="arc",
                    outline=color,
                    width=stroke,
                )
            self.canvas.create_line(
                cx + 7 * scale,
                cy + 3 * scale,
                cx + 12 * scale,
                cy + 3 * scale,
                fill=color,
                width=stroke,
            )
            self.canvas.create_line(
                cx + 9.5 * scale,
                cy + 0.5 * scale,
                cx + 9.5 * scale,
                cy + 5.5 * scale,
                fill=color,
                width=stroke,
            )
        elif icon == "P":
            self.rounded(
                cx - 8 * scale,
                cy - 7 * scale,
                cx + 8 * scale,
                cy + 8 * scale,
                max(2, 3 * scale),
                "",
                color,
                stroke,
            )
            self.canvas.create_line(
                cx - 8 * scale,
                cy - 2 * scale,
                cx + 8 * scale,
                cy - 2 * scale,
                fill=color,
                width=stroke,
            )
            self.canvas.create_oval(
                cx - 2 * scale,
                cy + 2 * scale,
                cx + 2 * scale,
                cy + 6 * scale,
                fill=color,
                outline="",
            )
        elif icon == "PROD":
            # Factory/line symbol, distinct from the planned-work calendar.
            self.canvas.create_line(
                cx - 9 * scale,
                cy + 7 * scale,
                cx - 9 * scale,
                cy - 1 * scale,
                cx - 3 * scale,
                cy + 2 * scale,
                cx + 2 * scale,
                cy - 2 * scale,
                cx + 7 * scale,
                cy + 1 * scale,
                cx + 7 * scale,
                cy + 7 * scale,
                cx - 9 * scale,
                cy + 7 * scale,
                fill=color,
                width=stroke,
                joinstyle="round",
            )
            self.canvas.create_line(
                cx + 4 * scale,
                cy - 3 * scale,
                cx + 4 * scale,
                cy - 9 * scale,
                cx + 8 * scale,
                cy - 9 * scale,
                cx + 8 * scale,
                cy + 7 * scale,
                fill=color,
                width=stroke,
            )
            for window_x in (-5, 0, 5):
                self.canvas.create_rectangle(
                    cx + (window_x - 1.2) * scale,
                    cy + 3 * scale,
                    cx + (window_x + 1.2) * scale,
                    cy + 5.5 * scale,
                    fill=color,
                    outline="",
                )
        else:
            icon_size = 15 if radius >= 16 else (11 if radius >= 12 else 9)
            self.text(cx, cy, icon, icon_size, color, "bold", "center")

    def status_face(self, cx, cy, status, phase, radius=16):
        """Draw a lightweight, font-independent animated status expression."""
        palette = {
            "RUNNING": ("#E7F7EF", self.GREEN),
            "DOWN": ("#FDECEE", self.RED),
            "REPAIRING": ("#FFF3E5", self.ORANGE),
            "ENGINEERING": ("#F0EBFF", self.PURPLE),
        }
        fill, accent = palette[status]
        scale = radius / 16
        stroke = max(1, round(2 * scale))
        self.canvas.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            fill=fill,
            outline=accent,
            width=stroke,
        )
        blink = int(phase * 2.2) % 9 == 0
        if blink:
            self.canvas.create_line(
                cx - 8 * scale,
                cy - 5 * scale,
                cx - 3 * scale,
                cy - 5 * scale,
                fill=accent,
                width=stroke,
            )
            self.canvas.create_line(
                cx + 3 * scale,
                cy - 5 * scale,
                cx + 8 * scale,
                cy - 5 * scale,
                fill=accent,
                width=stroke,
            )
        else:
            self.canvas.create_oval(
                cx - 7 * scale,
                cy - 7 * scale,
                cx - 3 * scale,
                cy - 3 * scale,
                fill=accent,
                outline="",
            )
            self.canvas.create_oval(
                cx + 3 * scale,
                cy - 7 * scale,
                cx + 7 * scale,
                cy - 3 * scale,
                fill=accent,
                outline="",
            )
        if status == "RUNNING":
            # Smooth path renders reliably across macOS and Raspberry Pi Tk.
            self.canvas.create_line(
                cx - 8 * scale,
                cy + 1 * scale,
                cx - 5 * scale,
                cy + 5 * scale,
                cx,
                cy + 7 * scale,
                cx + 5 * scale,
                cy + 5 * scale,
                cx + 8 * scale,
                cy + 1 * scale,
                smooth=True,
                splinesteps=16,
                fill=accent,
                width=stroke,
                capstyle="round",
            )
        elif status == "DOWN":
            self.canvas.create_arc(
                cx - 9 * scale,
                cy + 3 * scale,
                cx + 9 * scale,
                cy + 15 * scale,
                start=20,
                extent=140,
                style="arc",
                outline=accent,
                width=stroke,
            )
        elif status == "REPAIRING":
            self.canvas.create_line(
                cx - 7 * scale,
                cy + 7 * scale,
                cx + 7 * scale,
                cy + 7 * scale,
                fill=accent,
                width=stroke,
            )
            self.canvas.create_line(
                cx - 10 * scale,
                cy - 10 * scale,
                cx - 3 * scale,
                cy - 8 * scale,
                fill=accent,
                width=1,
            )
            self.canvas.create_line(
                cx + 3 * scale,
                cy - 8 * scale,
                cx + 10 * scale,
                cy - 10 * scale,
                fill=accent,
                width=1,
            )
        else:
            self.canvas.create_arc(
                cx - 8 * scale,
                cy,
                cx + 8 * scale,
                cy + 10 * scale,
                start=200,
                extent=140,
                style="arc",
                outline=accent,
                width=stroke,
            )

    def toast_showing(self):
        """Whether transient feedback currently owns the centre of the header."""
        return time.monotonic() < getattr(self, "toast_until", 0)

    def draw_header(self):
        self.canvas.create_rectangle(0, 0, 800, 64, fill=self.CARD, outline="")
        brand_drawn = self.draw_brand_mark(30, 32, 34)
        heading_x = 54 if brand_drawn else 18
        self.text(heading_x, 14, self.t("app_heading"), 9, self.BLUE, "bold")
        line_name = str(self.config["line_name"])
        header_name = line_name if len(line_name) <= 18 else line_name[:17] + "…"
        self.text(heading_x, 29, header_name, 17, self.TEXT, "bold")
        station_count = len(
            [zone for zone in self.config.get("zones", []) if str(zone).strip()]
        )
        self.text(
            624,
            31,
            datetime.now().astimezone().strftime("%H:%M"),
            13,
            self.TEXT,
            "bold",
            "e",
        )
        self.draw_update_indicator((630, 8, 678, 56))
        self.draw_header_controls()
        # The centre of the header is reserved for transient feedback. While a
        # message is showing it owns that space, so the ambient chips step aside
        # instead of being drawn underneath it. The clock, the update indicator,
        # Information and Settings are drawn above and always remain available.
        if self.toast_showing():
            return
        self.rounded(286, 19, 374, 43, 8, "#F4F6FA", self.BORDER)
        self.text(330, 31, f"{station_count} STATIONS", 7, self.TEXT, "bold", "center")
        if self.state.get("pending_response_record") or self.state.get(
            "pending_planned_work"
        ):
            self.rounded(380, 19, 474, 43, 8, "#FFF3E5", self.ORANGE)
            self.text(
                427,
                31,
                f"↻  {self.t('sync_pending')}",
                6,
                self.ORANGE,
                "bold",
                "center",
            )
            self.hitboxes["sync_pending"] = (380, 19, 474, 43)
        elif self.state.get("escalated_at") and self.state.get("status") == "DOWN":
            self.rounded(380, 19, 474, 43, 8, "#FDECEE", self.RED)
            self.text(
                427, 31, f"!  {self.t('escalated')}", 6, self.RED, "bold", "center"
            )
        online = self.provider.connected
        self.rounded(480, 19, 572, 43, 8, "#EDF8F3" if online else "#FFF0F1")
        self.canvas.create_oval(
            488, 27, 496, 35, fill=self.GREEN if online else self.RED, outline=""
        )
        api_text = (
            (self.provider.identity_name or self.t("connected"))
            if online
            else self.t("setup_needed")
        )
        limit = 10 if online else 12
        if len(api_text) > limit:
            api_text = api_text[: limit - 1] + "…"
        self.text(
            501,
            31,
            api_text,
            6 if not online else 7,
            self.GREEN if online else self.RED,
            "bold",
            "w",
        )

        return

    def draw_header_controls(self):
        """Information and Settings; always available, never hidden by feedback."""
        self.rounded(684, 8, 732, 56, 12, "#EEF1F6", self.BORDER)
        self.canvas.create_oval(701, 24, 715, 38, fill="", outline=self.BLUE, width=2)
        self.text(708, 31, "i", 10, self.BLUE, "bold", "center")
        self.hitboxes["about"] = (684, 8, 732, 56)
        self.rounded(738, 8, 786, 56, 12, "#EEF1F6", self.BORDER)
        # A simple three-slider mark renders consistently on Raspberry Pi's
        # bundled fonts and remains recognizable at small scale.
        for sy, knob_x in ((24, 754), (32, 768), (40, 760)):
            self.canvas.create_line(748, sy, 776, sy, fill=self.TEXT, width=2)
            self.canvas.create_oval(
                knob_x - 2, sy - 2, knob_x + 2, sy + 2, fill=self.BLUE, outline=""
            )
        self.hitboxes["settings"] = (738, 8, 786, 56)

    def draw_machine_card(self, phase):
        self.rounded(14, 68, 786, 318, 18, self.CARD, self.BORDER)
        status = self.state["status"]
        data = {
            "RUNNING": (
                self.t("production_active"),
                self.t("production_active_detail"),
                self.GREEN,
            ),
            "DOWN": (
                self.t("downtime_reported"),
                self.t("downtime_reported_detail"),
                self.RED,
            ),
            "REPAIRING": (
                self.t("repair_in_progress"),
                self.t("repair_in_progress_detail"),
                self.ORANGE,
            ),
            "ENGINEERING": (
                self.t("line_reserved"),
                self.state.get("work_label", "Planned work in progress"),
                self.PURPLE,
            ),
        }[status]
        title, subtitle, color = data
        pulse = (1 + math.sin(phase * 3)) / 2
        halo = 16 + pulse * 2
        self.canvas.create_oval(
            33 - halo,
            91 - halo,
            33 + halo,
            91 + halo,
            fill="",
            outline=color if pulse > 0.5 else self.BORDER,
            width=1,
        )
        self.status_face(33, 91, status, phase, radius=13)
        self.text(56, 79, title, 11, self.TEXT, "bold")
        self.text(56, 99, subtitle, 8, self.MUTED)
        record_id = self.state.get("response_record_id")
        if record_id:
            self.rounded(615, 78, 766, 104, 9, "#F1F4F8")
            self.text(690, 91, f"RESPONSE RECORD  #{record_id}", 8, self.MUTED, "bold", "center")
        else:
            overview = {
                "RUNNING": "FLOWING",
                "DOWN": "FLOW STOPPED",
                "REPAIRING": "REPAIR ACTIVE",
                "ENGINEERING": "LINE RESERVED",
            }[status]
            station_count = len(
                [zone for zone in self.config.get("zones", []) if str(zone).strip()]
            )
            self.rounded(
                615,
                78,
                766,
                104,
                9,
                "#EDF8F3" if status == "RUNNING" else "#F1F4F8",
                self.BORDER,
            )
            self.text(
                690,
                91,
                f"{station_count} STATIONS  •  {overview}",
                7,
                color,
                "bold",
                "center",
            )

        zones = [
            str(zone).strip()
            for zone in self.config.get("zones", [])
            if str(zone).strip()
        ] or ["LINE"]
        selected = set(self.selected_zones())
        # One-touch whole-line selection.
        all_selected = "ENTIRE LINE" in selected
        whole_fill = "#EAF1FF" if not all_selected else self.BLUE
        self.rounded(
            294,
            73,
            506,
            120,
            11,
            whole_fill,
            self.BLUE if all_selected else "#CAD8EE",
            1,
        )
        self.canvas.create_oval(
            309, 91, 321, 103, fill="white" if all_selected else "#B8C9E2", outline=""
        )
        self.text(
            315,
            97,
            "✓" if all_selected else "",
            7,
            self.BLUE if all_selected else "white",
            "bold",
            "center",
        )
        self.text(
            400,
            97,
            self.t("entire_line_selected")
            if all_selected
            else self.t("select_entire_line"),
            8,
            "white" if all_selected else self.BLUE,
            "bold",
            "center",
        )
        self.hitboxes["zone_all"] = (294, 73, 506, 120)

        # One-way production map. Every configured station stays in process order
        # on one straight input-to-output axis, even when stations are added.
        per_page = 11
        pages = max(1, (len(zones) + per_page - 1) // per_page)
        self.station_page = max(0, min(getattr(self, "station_page", 0), pages - 1))
        page_start = self.station_page * per_page
        visible_zones = zones[page_start : page_start + per_page]
        line_left, line_right = (86, 714) if pages > 1 else (72, 728)
        cy = 174
        belt_y = 232
        count = len(visible_zones)
        step = (line_right - line_left) / (count - 1) if count > 1 else 0
        centers = [(line_left + index * step, cy) for index in range(count)]
        cell_width = min(56, max(40, (line_right - line_left) / max(count, 1) - 4))
        if pages > 1:
            self.text(
                400,
                120,
                f"STATIONS {page_start + 1}–{page_start + count} OF {len(zones)}  •  PAGE {self.station_page + 1}/{pages}",
                7,
                self.MUTED,
                "bold",
                "center",
            )
            if self.station_page > 0:
                self.rounded(18, 151, 53, 213, 11, "#E1E9F4", "#AEBED1")
                self.text(35.5, 182, "<", 15, self.BLUE, "bold", "center")
                self.hitboxes["stations_prev"] = (18, 151, 53, 213)
            if self.station_page < pages - 1:
                self.rounded(747, 151, 782, 213, 11, "#E1E9F4", "#AEBED1")
                self.text(764.5, 182, ">", 15, self.BLUE, "bold", "center")
                self.hitboxes["stations_next"] = (747, 151, 782, 213)

        # The conveyor sits below the workcells, keeping products and its full
        # mechanical profile visible. Motion comes from rotating rollers and
        # travelling belt seams; there is no static direction marker.
        if count > 1:
            belt_left, belt_right = 42, 758
            top, bottom = belt_y + 2, belt_y + 23
            # Soft shadow, rubber loop, steel rails, and visible end pulleys
            # read as a conveyor instead of a flat progress indicator.
            self.rounded(
                belt_left - 2, bottom + 2, belt_right + 2, bottom + 6, 3, "#D8E0EA"
            )
            self.rounded(
                belt_left, top, belt_right, bottom, 10, "#DCE4ED", "#8294A8", 1
            )
            self.canvas.create_rectangle(
                belt_left + 9,
                top + 3,
                belt_right - 9,
                bottom - 3,
                fill="#AEBCCC",
                outline="",
            )
            self.canvas.create_line(
                belt_left + 9, top + 3, belt_right - 9, top + 3, fill="#657A91", width=2
            )
            self.canvas.create_line(
                belt_left + 9,
                bottom - 3,
                belt_right - 9,
                bottom - 3,
                fill="#657A91",
                width=2,
            )
            moving = status == "RUNNING"
            roller_angle = phase * 8 if moving else 0
            roller_dx = 3.4 * math.cos(roller_angle)
            roller_dy = 3.4 * math.sin(roller_angle)
            # Fewer, larger rollers read as a mechanism at a glance; the dense
            # row they replaced reduced to visual noise on a 7-inch panel.
            for roller in range(58, 752, 30):
                roller_cy = (top + bottom) / 2
                self.canvas.create_oval(
                    roller - 6.5,
                    roller_cy - 6.5,
                    roller + 6.5,
                    roller_cy + 6.5,
                    fill="#E4EAF1",
                    outline="#7F92A8",
                    width=1,
                )
                # A fixed highlight on every roller gives the cylinders a
                # consistent light source instead of reading as flat discs.
                self.canvas.create_arc(
                    roller - 4.6,
                    roller_cy - 4.6,
                    roller + 4.6,
                    roller_cy + 4.6,
                    start=55,
                    extent=95,
                    style="arc",
                    outline="#FFFFFF",
                    width=1,
                )
                self.canvas.create_line(
                    roller + roller_dx * 0.35,
                    roller_cy + roller_dy * 0.35,
                    roller + roller_dx * 1.35,
                    roller_cy + roller_dy * 1.35,
                    fill="#6B8098",
                    width=1.2,
                    capstyle="round",
                )
                self.canvas.create_oval(
                    roller - 1,
                    roller_cy - 1,
                    roller + 1,
                    roller_cy + 1,
                    fill="#50667E",
                    outline="",
                )
            # Travelling seams show left-to-right belt motion without a solid
            # triangle, arrow, or other static direction marker.
            seam_offset = (phase * 46) % 30 if moving else 0
            for seam in range(belt_left - 30, belt_right + 30, 30):
                x = seam + seam_offset
                if belt_left + 12 < x < belt_right - 14:
                    self.canvas.create_line(
                        x, top + 4, x + 6, bottom - 4, fill="#7C8FA5", width=1.4
                    )
            for support in (112, 264, 416, 568, 720):
                self.canvas.create_line(
                    support, bottom, support - 3, bottom + 10, fill="#71859B", width=2
                )
                self.canvas.create_line(
                    support - 9,
                    bottom + 10,
                    support + 4,
                    bottom + 10,
                    fill="#71859B",
                    width=2,
                )

            # A driven end motor makes the motion mechanically meaningful.
            # Its fan rotates only while Production is running.
            motor_x, motor_y = belt_right + 12, (top + bottom) / 2
            self.rounded(
                motor_x - 12,
                motor_y - 8,
                motor_x + 12,
                motor_y + 8,
                4,
                "#40566E",
                "#2D4157",
            )
            self.canvas.create_oval(
                motor_x - 6,
                motor_y - 6,
                motor_x + 6,
                motor_y + 6,
                fill="#DCE4ED",
                outline="#7F92A8",
            )
            fan_angle = phase * 7 if moving else math.pi / 4
            for blade in range(3):
                angle = fan_angle + blade * (2 * math.pi / 3)
                self.canvas.create_line(
                    motor_x,
                    motor_y,
                    motor_x + 5 * math.cos(angle),
                    motor_y + 5 * math.sin(angle),
                    fill="#415A73",
                    width=2,
                    capstyle="round",
                )

            # Sequential indicator lamps reinforce the one-way process without
            # relying on a static arrow or decorative motion.
            lamp_offset = int(phase * 5) % 8 if moving else -1
            for lamp_index, lamp_x in enumerate(range(105, 706, 78)):
                active = moving and lamp_index == lamp_offset
                self.canvas.create_oval(
                    lamp_x - 2,
                    top - 6,
                    lamp_x + 2,
                    top - 2,
                    fill=self.GREEN if active else "#B9C5D2",
                    outline="",
                )

        # Cartons are also a status indicator: only a healthy line moves product.
        # Paused cartons remain visible and pulse their state-coloured border.
        if count > 1:
            travel = 700
            # Package fill colours are product identity, never status. Machine
            # state is communicated exclusively by the animated outer border.
            product_colors = ("#E6CF9F",) * 3
            strong_border = {
                "RUNNING": self.GREEN,
                "DOWN": self.RED,
                "REPAIRING": self.ORANGE,
                "ENGINEERING": "#8D99AA",
            }[status]
            soft_border = {
                "RUNNING": "#91D4B7",
                "DOWN": "#E9A8AE",
                "REPAIRING": "#F2C27D",
                "ENGINEERING": "#C4CBD5",
            }[status]
            product_border = strong_border if pulse > 0.38 else soft_border
            for marker, color_box in enumerate(product_colors):
                fx = (
                    50 + ((phase * 48 + marker * travel / 3) % travel)
                    if status == "RUNNING"
                    else 50 + (marker + 0.5) * travel / 3
                )
                bob = (
                    0.6 * math.sin(phase * 6 + marker * 1.7)
                    if status == "RUNNING"
                    else 0
                )
                # Kept clear of the workcell cards above: the cards end at
                # cy + 39 and the carton must not reach them as it bobs.
                # The carton rests on the belt's upper surface and stays clear
                # of the workcell cards above it.
                top_box = belt_y - 12 + bob
                bottom_box = belt_y + 8 + bob
                # A contact shadow on the belt, a lit top face, and a seam give
                # the carton depth without animating anything inside it.
                self.canvas.create_oval(
                    fx - 15,
                    bottom_box + 1,
                    fx + 15,
                    bottom_box + 5,
                    fill="#B9C5D3",
                    outline="",
                )
                self.rounded(
                    fx - 14,
                    top_box,
                    fx + 14,
                    bottom_box,
                    4,
                    color_box,
                    product_border,
                    2,
                )
                self.rounded(
                    fx - 14,
                    top_box,
                    fx + 14,
                    top_box + 6,
                    4,
                    "#F2E3BF",
                    "",
                )
                self.canvas.create_line(
                    fx, top_box + 2, fx, bottom_box - 2, fill="#FBF6EA", width=2
                )
                self.canvas.create_line(
                    fx - 12,
                    top_box + 6,
                    fx + 12,
                    top_box + 6,
                    fill="#D9C08A",
                    width=1,
                )


        for local_index, (label, (cx, cy)) in enumerate(zip(visible_zones, centers)):
            index = page_start + local_index
            half = cell_width / 2
            x1 = cx - half
            x2 = cx + half
            y1 = cy - 39
            y2 = cy + 39
            self.hitboxes[f"zone_{index}"] = (x1, y1, x2, y2)
            chosen = label in selected or all_selected
            shadow = "#C5CFDC"
            fill = self.PALE_BLUE if chosen else "#F8FAFC"
            self.rounded(x1, y1 + 3, x2, y2 + 3, 10, shadow)
            self.rounded(
                x1,
                y1,
                x2,
                y2,
                10,
                fill,
                self.BLUE if chosen else self.BORDER,
                2 if chosen else 1,
            )
            # Process number, machine body and station name form one clear touch target.
            self.text(
                cx,
                y1 + 9,
                f"{index + 1:02}",
                6,
                self.BLUE if chosen else self.MUTED,
                "bold",
                "center",
            )
            self.rounded(
                cx - 13,
                cy - 16,
                cx + 13,
                cy + 7,
                5,
                "#29415F" if not chosen else self.BLUE,
            )
            self.canvas.create_rectangle(
                cx - 8, cy - 11, cx + 8, cy - 6, fill="#9CC2FF", outline=""
            )
            # Animated spindle/status window: healthy stations visibly cycle;
            # stopped or reserved stations hold position.
            spindle_angle = phase * 5 + index * 0.7 if status == "RUNNING" else 0
            spindle_x, spindle_y = cx, cy - 1
            self.canvas.create_oval(
                spindle_x - 4,
                spindle_y - 4,
                spindle_x + 4,
                spindle_y + 4,
                fill="#DCE9FF",
                outline="",
            )
            self.canvas.create_line(
                spindle_x - 3 * math.cos(spindle_angle),
                spindle_y - 3 * math.sin(spindle_angle),
                spindle_x + 3 * math.cos(spindle_angle),
                spindle_y + 3 * math.sin(spindle_angle),
                fill=self.BLUE if chosen else "#46698E",
                width=1,
            )
            self.canvas.create_line(
                cx - 9, cy + 12, cx + 9, cy + 12, fill="#637993", width=2
            )
            self.canvas.create_line(
                cx - 6,
                cy + 7,
                cx - 6,
                cy + 15,
                cx + 6,
                cy + 15,
                cx + 6,
                cy + 7,
                fill="#637993",
                width=2,
            )
            self.text(cx, y2 - 9, label, 7, self.TEXT, "bold", "center")
            if status == "RUNNING" and not selected:
                beacon = self.GREEN
            else:
                beacon = (
                    self.RED
                    if status == "DOWN" and chosen
                    else (
                        self.ORANGE
                        if status in ("REPAIRING", "ENGINEERING") and chosen
                        else self.GREEN
                    )
                )
            br = 4 + (2 if chosen and pulse > 0.5 else 0)
            self.canvas.create_oval(
                cx - br,
                y1 - br - 5,
                cx + br,
                y1 + br - 5,
                fill=beacon,
                outline="white",
                width=1,
            )
            glyph = {
                "RUNNING": "✓",
                "DOWN": "!",
                "REPAIRING": "W",
                "ENGINEERING": "P",
            }[status]
            self.text(
                cx,
                y1 - 5,
                glyph,
                5 if status in {"REPAIRING", "ENGINEERING"} else 6,
                "white",
                "bold",
                "center",
            )
            failure_count = len(self.state.get("failure_selections", {}).get(label, []))
            if chosen and failure_count:
                self.canvas.create_oval(
                    x2 - 16,
                    y1 + 4,
                    x2 - 2,
                    y1 + 18,
                    fill=self.BLUE,
                    outline="white",
                    width=1,
                )
                self.text(
                    x2 - 9, y1 + 11, str(failure_count), 7, "white", "bold", "center"
                )

        if status != "RUNNING" and selected:
            selected_label = (
                "ENTIRE LINE"
                if all_selected
                else f"{len(selected)} STATION{'S' if len(selected) != 1 else ''} SELECTED"
            )
            self.rounded(
                286, 268, 514, 289, 7, "#FFF1F2" if status == "DOWN" else self.PALE_BLUE
            )
            self.text(
                400,
                278,
                f"FLOW PAUSED  •  {selected_label}",
                7,
                self.RED if status == "DOWN" else self.BLUE,
                "bold",
                "center",
            )
        elif selected:
            selected_label = (
                "ENTIRE LINE"
                if all_selected
                else f"{len(selected)} STATION{'S' if len(selected) != 1 else ''}"
            )
            self.rounded(286, 268, 514, 289, 7, "#EDF8F3")
            self.text(
                400,
                278,
                f"{selected_label} SELECTED  •  READY TO REPORT",
                7,
                self.GREEN,
                "bold",
                "center",
            )
        elif not selected:
            # On the same baseline as the selection chips, clear of the
            # conveyor's support legs.
            self.text(
                400,
                278,
                self.t("touch_stations_prompt"),
                7,
                self.MUTED,
                "bold",
                "center",
            )
        # Compact timing/status strip.
        if status == "RUNNING":
            timer_text = "READY"
            caption = "Select a station before reporting"
        else:
            timer_text = self.format_duration(self.elapsed_seconds())
            caption = {
                "DOWN": "Downtime",
                "REPAIRING": "Repair active",
                "ENGINEERING": "Engineering possession",
            }[status]
        if any(
            (
                self.state.get("asset_status_sync_pending"),
                self.state.get("pending_response_status"),
                self.state.get("pending_participant_assignment"),
            )
        ):
            caption += " • External sync queued"
        self.text(31, 298, timer_text, 12, color, "bold")
        self.text(124, 299, caption, 8, self.MUTED, "normal")
        crew = ", ".join(self.state.get("engineer_names", []))
        if crew:
            self.text(766, 299, ("CREW  " + crew)[:58], 8, self.MUTED, "bold", "e")

    def draw_bottom(self):
        status = self.state["status"]
        if status == "DOWN" and (
            self.state.get("pending_response_record") or not self.state.get("response_record_id")
        ):
            info = (
                "SYNC RECORDED DOWNTIME",
                "Downtime timer is active locally • touch to retry external synchronization",
                self.ORANGE,
                "R",
            )
        else:
            info = {
                "RUNNING": (
                    self.t("report_problem"),
                    "Creates a high-priority Engineering response record",
                    self.RED,
                    "!",
                ),
                "DOWN": (
                    "ENGINEER HAS ARRIVED",
                    "Moves response record to In Progress and starts repair",
                    self.BLUE,
                    ">",
                ),
                "REPAIRING": (
                    "REPAIR COMPLETE",
                    "Closes response record and resumes production",
                    self.GREEN,
                    "OK",
                ),
                "ENGINEERING": (
                    "PLANNED WORK COMPLETE",
                    "Releases the line back to Production",
                    self.GREEN,
                    "OK",
                ),
            }[status]
        title, subtitle, color, icon = info
        if status == "RUNNING" and not self.provider.INFO.supports_response_records:
            title, subtitle, color, icon = (
                "RECORD A PROBLEM LOCALLY",
                "Starts the downtime timer now • synchronizes when integration is available",
                self.RED,
                "!",
            )
        # Context guidance always points the user to the next valid action.
        zone = self.zone_summary("")
        zone_label = (
            zone if len(zone) < 34 else f"{len(self.selected_zones())} stations"
        )
        if status == "RUNNING" and not zone:
            guide = (
                "STEP 1  •  Touch the affected station above — or select Entire Line"
            )
        elif status == "RUNNING":
            guide = f"STEP 2  •  {zone_label} selected — report a problem or choose planned work"
        elif status == "DOWN" and self.state.get("pending_response_record"):
            guide = "SYNC PENDING  •  Downtime is safely recorded locally — touch Retry or wait for automatic synchronization"
        elif status == "DOWN":
            guide = (
                "NEXT  •  When Engineering arrives, tap Engineer Has Arrived and select the crew"
                if self.provider.INFO.supports_team_directory
                else "NEXT  •  When Engineering arrives, tap Engineer Has Arrived to start repair"
            )
        elif status == "REPAIRING":
            guide = (
                "WORK ACTIVE  •  Update the crew as engineers join or leave; complete only when safe"
                if self.provider.INFO.supports_team_directory
                else "WORK ACTIVE  •  Complete repair only after the line is verified safe"
            )
        else:
            guide = "ENGINEERING CONTROL  •  Update the crew as people join or leave; release only when safe"
        if status in {"REPAIRING", "ENGINEERING"} and any(
            (
                self.state.get("asset_status_sync_pending"),
                self.state.get("pending_response_status"),
                self.state.get("pending_participant_assignment"),
            )
        ):
            guide += " • external update queued"
        pulse = (1 + math.sin((time.monotonic() - self.animation_start) * 4)) / 2
        self.rounded(14, 319, 493, 344, 8, "#EDF3FF")
        self.canvas.create_oval(
            24, 327, 34, 337, fill=self.BLUE if pulse > 0.35 else "#AFC7FF", outline=""
        )
        self.text(43, 332, guide, 8, self.TEXT, "bold", "w", width=438)
        # Treat the primary title and subtitle as one vertically centered group.
        # Drawing the title at the button midpoint and then adding a subtitle
        # below made the complete label appear visibly too low.
        self.button("primary", (14, 350, 493, 410), "", color, icon)
        primary_offset = 2 if self.pressed == "primary" else 0
        # The primary control carries the whole next action, so its own text is
        # drawn here rather than as a button label; it uses the same readability
        # rule so an amber "retry synchronization" state stays legible.
        primary_label = self.label_color(color, "white")
        self.text(253.5, 372 + primary_offset, title, 11, primary_label, "bold", "center")
        self.text(
            253.5, 391 + primary_offset, subtitle, 7, primary_label, "normal", "center"
        )
        if status == "RUNNING" and self.provider.INFO.supports_response_records:
            self.button(
                "planned_work",
                (14, 418, 493, 462),
                self.t("engineering_planned_work"),
                self.PURPLE,
                "P",
            )
        elif (
            status in ("REPAIRING", "ENGINEERING")
            and self.provider.INFO.supports_team_directory
        ):
            active_count = len(self.state.get("engineer_ids", []))
            self.button(
                "crew",
                (14, 418, 493, 462),
                f"UPDATE ENGINEERING CREW  •  {active_count} ACTIVE",
                self.BLUE,
                "+",
            )
        self.text(
            515,
            330,
            "CALL SUPPORT"
            if self.provider.INFO.supports_messaging
            else "MESSAGING NOT CONFIGURED",
            7,
            self.MUTED,
            "bold",
        )
        teams = (
            (self.t("engineering"), "engineering", self.BLUE),
            (self.t("quality"), "quality", self.PURPLE),
            (self.t("production"), "production", self.ORANGE),
        )
        for index, (label, key, team_color) in enumerate(teams):
            y = 350 + index * 38
            support_icon = {
                "engineering": "E",
                "quality": "Q",
                "production": "PROD",
            }[key]
            if self.provider.INFO.supports_messaging:
                self.button(
                    key,
                    (505, y, 786, y + 31),
                    label,
                    "#EEF2F7",
                    support_icon,
                    fg=self.TEXT,
                )
            else:
                self.rounded(505, y, 786, y + 31, 8, "#F3F5F8", self.BORDER)
                self.text(
                    646,
                    y + 15.5,
                    f"{label} • UNAVAILABLE",
                    8,
                    "#9AA5B5",
                    "bold",
                    "center",
                )
            self.canvas.create_rectangle(
                505, y + 8, 509, y + 23, fill=team_color, outline=""
            )
        # Animated focus ring identifies the next primary control.
        if not (status == "RUNNING" and not zone):
            ring = "#8EB2FF" if pulse > 0.45 else self.BORDER
            self.rounded(11, 347, 496, 413, 15, "", ring, 2)

    def draw_toast(self):
        if time.monotonic() >= self.toast_until:
            return
        colors = {
            "success": ("#EAF8F2", self.GREEN, "✓"),
            "error": ("#FFF0F1", self.RED, "!"),
            "info": ("#EDF3FF", self.BLUE, "i"),
        }
        fill, accent, symbol = colors.get(self.toast_kind, colors["info"])
        # The center of the header is intentionally reserved for temporary
        # feedback, leaving workflow guidance, line details and controls visible.
        x1, x2 = 272, 542
        display = (
            self.toast_text
            if len(self.toast_text) <= 44
            else self.toast_text[:43] + "…"
        )
        self.rounded(x1, 16, x2, 54, 11, "#D2DAE5")
        self.rounded(x1, 13, x2, 51, 11, fill, accent, 1)
        self.canvas.create_oval(x1 + 12, 21, x1 + 34, 43, fill=accent, outline="")
        self.text(x1 + 23, 32, symbol, 9, "white", "bold", "center")
        self.text(x1 + 44, 32, display, 8, self.TEXT, "bold", "w", width=x2 - x1 - 54)

    def draw_modal(self):
        if not self.modal:
            return
        self.canvas.create_rectangle(
            0, 0, 800, 480, fill="#E9EEF5", outline=""
        )
        if self.modal["kind"] == "failures":
            station = self.modal["station"]
            options = self.modal["options"]
            selected = self.modal["selected"]
            self.rounded(88, 38, 712, 442, 24, self.CARD)
            self.rounded(116, 62, 176, 112, 15, "#EAF1FF")
            zones = self.config.get("zones", [])
            index_label = f"{zones.index(station) + 1:02}" if station in zones else "—"
            self.text(146, 87, index_label, 16, self.BLUE, "bold", "center")
            self.text(194, 62, self.t("pinpoint_issue"), 8, self.BLUE, "bold")
            self.text(194, 81, f"Common failures at {station}", 17, self.TEXT, "bold")
            self.text(
                194,
                106,
                "Optional • select one, several, all, or leave everything clear",
                9,
                self.MUTED,
            )

            positions = (
                (116, 137, 392, 191),
                (408, 137, 684, 191),
                (116, 201, 392, 255),
                (408, 201, 684, 255),
                (116, 265, 684, 319),
            )
            for index, (option, box) in enumerate(zip(options, positions)):
                x1, y1, x2, y2 = box
                chosen = option in selected
                self.rounded(
                    x1,
                    y1,
                    x2,
                    y2,
                    13,
                    self.PALE_BLUE if chosen else "#F6F8FB",
                    self.BLUE if chosen else self.BORDER,
                    2 if chosen else 1,
                )
                self.canvas.create_oval(
                    x1 + 16,
                    y1 + 16,
                    x1 + 38,
                    y1 + 38,
                    fill=self.BLUE if chosen else "#D9E2EE",
                    outline="",
                )
                self.text(
                    x1 + 27,
                    y1 + 27,
                    "✓" if chosen else "",
                    9,
                    "white",
                    "bold",
                    "center",
                )
                self.text(
                    x1 + 50,
                    (y1 + y2) / 2,
                    option,
                    10,
                    self.TEXT,
                    "bold",
                    "w",
                    width=x2 - x1 - 62,
                )
                self.hitboxes[f"failure_{index}"] = box

            self.text(
                116,
                337,
                f"{len(selected)} SELECTED",
                8,
                self.BLUE if selected else self.MUTED,
                "bold",
                "w",
            )
            self.button(
                "failure_all",
                (238, 320, 350, 367),
                self.t("select_all"),
                "#EEF2F7",
                fg=self.TEXT,
            )
            self.button(
                "failure_clear",
                (360, 320, 458, 367),
                self.t("clear"),
                "#EEF2F7",
                fg=self.TEXT,
            )
            self.button(
                "failure_remove",
                (116, 371, 304, 418),
                self.t("deselect_station"),
                "#FDECEE",
                fg=self.RED,
            )
            self.button(
                "failure_done",
                (324, 371, 684, 418),
                self.t("save_failure_details"),
                self.GREEN,
                "OK",
            )
            return
        if self.modal["kind"] == "update":
            self.draw_update_panel()
            return
        if self.modal["kind"] == "about":
            self.rounded(58, 18, 742, 462, 25, self.CARD)

            # Product identity and version are visually separate from legal and
            # operational responsibilities, making the panel easy to scan.
            self.rounded(77, 35, 141, 99, 19, "#F7F9FC", self.BORDER)
            if not self.draw_brand_mark(109, 67, 56):
                self.canvas.create_oval(
                    98, 56, 120, 78, fill="", outline=self.BLUE, width=2
                )
                self.text(109, 67, "i", 11, self.BLUE, "bold", "center")
            self.text(154, 42, "SOFTWARE INFORMATION", 7, self.BLUE, "bold")
            self.text(
                154,
                60,
                self.project_profile.product_name,
                15,
                self.TEXT,
                "bold",
                width=470,
            )
            self.text(154, 84, self.project_profile.product_tagline, 7, self.MUTED, width=470)
            self.rounded(647, 45, 716, 71, 9, "#F3F6FA", self.BORDER)
            self.text(681.5, 58, f"v{__version__}", 7, self.MUTED, "bold", "center")

            # Ownership and contact are distinct records instead of one dense line.
            self.rounded(82, 108, 386, 171, 13, "#F7F9FC", self.BORDER)
            self.canvas.create_oval(99, 123, 125, 149, fill="#EAF1FF", outline="")
            self.text(112, 136, "S", 9, self.BLUE, "bold", "center")
            self.text(139, 120, "CREATED & MAINTAINED BY", 6, self.MUTED, "bold")
            self.text(
                139, 140, self.project_profile.maintainer_name, 11, self.TEXT, "bold", width=225
            )
            self.rounded(398, 108, 718, 171, 13, "#F7F9FC", self.BORDER)
            self.canvas.create_oval(415, 123, 441, 149, fill="#EAF8F2", outline="")
            self.text(428, 136, "@", 9, self.GREEN, "bold", "center")
            self.text(455, 120, "SUPPORT CONTACT", 6, self.MUTED, "bold")
            self.text(
                455,
                139,
                self.project_profile.support_contact,
                8,
                self.TEXT,
                "bold",
                width=245,
            )
            self.text(455, 155, self.project_profile.distribution_name, 6, self.MUTED, width=245)

            # A two-column license summary answers the practical questions:
            # what may users do, and what is outside this license?
            self.rounded(82, 184, 718, 292, 14, "#EEF6FF", "#BCD5F5")
            self.text(102, 198, "MIT OPEN-SOURCE LICENSE", 8, self.BLUE, "bold")
            self.text(
                697,
                198,
                self.project_profile.license_identifier,
                7,
                self.BLUE,
                "bold",
                "e",
            )
            self.canvas.create_line(400, 219, 400, 273, fill="#C8DDF7", width=1)
            self.text(102, 221, "YOU MAY", 6, self.GREEN, "bold")
            self.text(
                102,
                239,
                "Use • copy • modify • merge\npublish • distribute • sublicense • sell",
                7,
                self.TEXT,
                "bold",
                width=274,
            )
            self.text(420, 221, "NOT INCLUDED", 6, self.RED, "bold")
            self.text(
                420,
                239,
                "External-service access • credentials\ndeployment data • trademarks • third-party rights",
                7,
                self.TEXT,
                "bold",
                width=274,
            )
            self.text(
                102,
                279,
                "Condition: retain the copyright and MIT license notice in copies or substantial portions.",
                6,
                self.MUTED,
                "bold",
                width=590,
            )

            # Safety is the final decision-relevant section, with three explicit
            # responsibility groups instead of a single legal paragraph.
            self.rounded(82, 305, 718, 394, 14, "#FFF7E8", "#F2D59B")
            self.canvas.create_oval(100, 320, 126, 346, fill=self.ORANGE, outline="")
            self.text(113, 333, "!", 11, "white", "bold", "center")
            self.text(
                141,
                318,
                "DEPLOYMENT RESPONSIBILITY • PROVIDED AS-IS",
                8,
                "#8A5A00",
                "bold",
            )
            responsibilities = (
                ("SAFETY", "Trained people, guarding, E-stops, LOTO and permits"),
                (
                    "SYSTEM",
                    "Connector accuracy, credentials, networks, updates and backups",
                ),
                ("DATA", "Log access, retention, personal data and lawful processing"),
            )
            for index, (heading, detail) in enumerate(responsibilities):
                x = 102 + index * 202
                self.text(x, 354, heading, 6, "#8A5A00", "bold")
                self.text(x, 369, detail, 6, self.TEXT, width=184)

            self.text(
                400,
                401,
                self.project_profile.copyright_notice,
                6,
                self.MUTED,
                "bold",
                "center",
            )
            self.button(
                "cancel",
                (264, 412, 536, 459),
                self.t("close"),
                "#E1E9F4",
                "X",
                fg=self.TEXT,
            )
            return
        if self.modal["kind"] == "engineers":
            self.rounded(100, 44, 700, 456, 22, self.CARD)
            editing = self.modal.get("context", {}).get("kind") == "edit"
            self.text(
                132,
                76,
                "UPDATE ACTIVE ENGINEERING CREW"
                if editing
                else "WHO IS WORKING ON THE LINE?",
                15,
                self.TEXT,
                "bold",
            )
            selected = self.modal["selected"]
            members = self.modal["members"]
            self.text(668, 56, f"{len(selected)} SELECTED", 8, self.BLUE, "bold", "e")
            self.text(
                132,
                104,
                "Select everyone currently working; deselect anyone who has left"
                if editing
                else "Select one or more Engineering team members",
                9,
                self.MUTED,
            )
            filter_text = self.modal.get("filter", "")
            self.button(
                "members_search",
                (500, 82, 670, 129),
                (
                    f"FILTER: {filter_text[:12]}"
                    if filter_text
                    else self.t("search_names")
                ),
                "#E1E9F4",
                "⌕",
                fg=self.TEXT,
            )
            page = self.modal.get("page", 0)
            per_page = RESPONDER_PAGE_SIZE
            visible = members[page * per_page : (page + 1) * per_page]
            if not visible:
                self.text(
                    400,
                    230,
                    self.t("no_engineers_match"),
                    10,
                    self.MUTED,
                    "bold",
                    "center",
                )
            for index, member in enumerate(visible):
                key = f"member_{index}"
                y = 132 + index * 52
                chosen = member["id"] in selected
                fill = self.PALE_BLUE if chosen else "#F5F7FA"
                self.rounded(
                    130,
                    y,
                    670,
                    y + 47,
                    11,
                    fill,
                    self.BLUE if chosen else self.BORDER,
                    2 if chosen else 1,
                )
                self.canvas.create_oval(
                    146,
                    y + 10,
                    164,
                    y + 28,
                    fill=self.BLUE if chosen else "#DDE3EC",
                    outline="",
                )
                self.text(
                    155, y + 19, "✓" if chosen else "", 8, "white", "bold", "center"
                )
                self.text(
                    176, y + 19, member["displayName"], 10, self.TEXT, "bold", "w"
                )
                self.text(
                    650,
                    y + 19,
                    member.get("teamRole", "MEMBER"),
                    7,
                    self.MUTED,
                    "bold",
                    "e",
                )
                self.hitboxes[key] = (130, y, 670, y + 47)
            pages = max(1, (len(members) + per_page - 1) // per_page)
            if pages > 1:
                self.text(
                    400,
                    371,
                    f"PAGE {page + 1} OF {pages}",
                    8,
                    self.MUTED,
                    "bold",
                    "center",
                )
                self.button(
                    "members_prev",
                    (130, 343, 230, 390),
                    "PREVIOUS",
                    "#EEF2F7",
                    fg=self.BLUE,
                )
                self.button(
                    "members_next",
                    (570, 343, 670, 390),
                    "NEXT",
                    "#EEF2F7",
                    fg=self.BLUE,
                )
            self.button(
                "cancel",
                (130, 398, 294, 445),
                self.t("cancel"),
                "#E9EDF3",
                fg=self.TEXT,
            )
            self.button(
                "start_engineers",
                (310, 398, 670, 445),
                "SAVE ACTIVE CREW" if editing else "START WORK",
                self.GREEN,
                "OK" if editing else ">",
            )
            return
        if self.modal["kind"] in {"password", "text_input"}:
            self.rounded(70, 28, 730, 452, 22, self.CARD)
            self.text(
                400,
                55,
                self.modal.get("title", "ADMINISTRATOR AUTHORIZATION"),
                15,
                self.TEXT,
                "bold",
                "center",
            )
            self.text(
                400,
                78,
                self.modal.get("prompt", "Enter administrator name or ID"),
                9,
                self.MUTED,
                "normal",
                "center",
            )
            value = self.modal.get("value", "")
            password_stage = (
                self.modal["kind"] == "password"
                and self.modal.get("stage") != "identity"
            )
            masked = value
            if password_stage:
                masked = (
                    ("● " * len(value))
                    if len(value) <= 18
                    else f"● ● ● ...  ({len(value)} characters)"
                )
            self.rounded(205, 94, 595, 132, 11, "#F4F6FA", self.BORDER)
            self.text(400, 113, masked or "—", 13, self.TEXT, "bold", "center")
            rows = ("1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM@")
            shifted = self.modal.get("shift", True)
            for row, characters in enumerate(rows):
                start = 400 - (len(characters) * 54) / 2
                for col, character in enumerate(characters):
                    display = (
                        character
                        if shifted or not character.isalpha()
                        else character.lower()
                    )
                    x1 = start + col * 54
                    y1 = 134 + row * 50
                    self.button(
                        f"pwd_{ord(display)}",
                        (x1, y1, x1 + 48, y1 + 47),
                        display,
                        "#EEF2F7",
                        fg=self.TEXT,
                    )
            self.button(
                "pwd_shift",
                (105, 337, 205, 384),
                "SHIFT",
                self.BLUE if shifted else "#E9EDF3",
                fg="white" if shifted else self.TEXT,
            )
            self.button(
                "pwd_space", (217, 337, 377, 384), "SPACE", "#E9EDF3", fg=self.TEXT
            )
            self.button(
                "pwd_back", (389, 337, 509, 384), "BACK", "#E9EDF3", fg=self.TEXT
            )
            self.button(
                "pwd_enter",
                (521, 337, 695, 384),
                (
                    ("SAVE PASSWORD" if self.modal.get("stage") == "confirm_password" else "CONTINUE")
                    if self.modal.get("purpose") == "password_change"
                    else "VERIFY"
                    if password_stage
                    else (
                        "CONTINUE"
                        if self.modal["kind"] == "password"
                        else self.t("save_continue")
                    )
                ),
                self.GREEN,
                ">",
            )
            if self.modal.get("error"):
                self.text(400, 394, self.modal["error"], 8, self.RED, "bold", "center", width=620)
            self.button(
                "cancel",
                (330, 403, 470, 450),
                self.t("cancel"),
                "#E9EDF3",
                fg=self.TEXT,
            )
            return
        if self.modal["kind"] == "planned":
            self.rounded(120, 76, 680, 404, 22, self.CARD)
            self.canvas.create_oval(368, 94, 432, 158, fill="#F0EBFF", outline="")
            self.text(400, 126, "P", 20, self.PURPLE, "bold", "center")
            self.text(
                400, 181, "Engineering take line", 18, self.TEXT, "bold", "center"
            )
            self.text(
                400,
                210,
                "Choose the type of planned work. Production will be paused.",
                9,
                self.MUTED,
                "normal",
                "center",
            )
            self.button(
                "planned_preventive",
                (154, 239, 646, 289),
                "PREVENTIVE MAINTENANCE",
                self.BLUE,
                "PM",
            )
            self.button(
                "planned_change",
                (154, 300, 646, 350),
                "MODIFICATION / CHANGE",
                self.PURPLE,
                "M",
            )
            self.button(
                "cancel",
                (330, 360, 470, 395),
                self.t("cancel"),
                "#E9EDF3",
                fg=self.TEXT,
            )
            return
        self.rounded(160, 112, 640, 368, 22, self.CARD)
        color = self.GREEN if self.modal["kind"] == "done" else self.RED
        self.canvas.create_oval(
            368,
            132,
            432,
            196,
            fill="#EAF8F2" if color == self.GREEN else "#FDECEE",
            outline="",
        )
        self.text(
            400, 164, "✓" if color == self.GREEN else "!", 24, color, "bold", "center"
        )
        self.text(400, 218, self.modal["title"], 18, self.TEXT, "bold", "center")
        self.text(
            400,
            249,
            self.modal["message"],
            10,
            self.MUTED,
            "normal",
            "center",
            width=390,
        )
        self.button(
            "cancel", (190, 298, 388, 346), self.t("not_yet"), "#E9EDF3", fg=self.TEXT
        )
        confirm_label = (
            self.t("yes_line_down")
            if self.modal["kind"] == "confirm_downtime"
            else self.t("yes_confirm")
        )
        self.button("confirm", (412, 298, 610, 346), confirm_label, color, "✓")

    def render(self):
        self.canvas.delete("all")
        self.hitboxes = {}
        phase = time.monotonic() - self.animation_start
        self.draw_header()
        self.draw_machine_card(phase)
        self.draw_bottom()
        if self.busy:
            self.rounded(325, 428, 475, 458, 10, self.TEXT)
            dots = "." * (1 + int(phase * 3) % 3)
            self.text(400, 443, "Syncing" + dots, 9, "white", "bold", "center")
        self.draw_toast()
        self.draw_modal()

    def animate(self):
        self.render()
        self.root.after(int(self.config.get("animation_interval_ms", 80)), self.animate)
