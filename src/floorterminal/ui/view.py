"""Canvas rendering for the line reporting console."""

from __future__ import annotations

import time
import tkinter as tk
from contextlib import nullcontext

from .contrast import TEXT_MINIMUM, contrast_ratio, readable_label, text_variant
from .dialogs import AdaptiveDialogMixin
from .images import opaque_photo
from .kiosk import KioskViewMixin
from .update_view import UpdateViewMixin

#: Visual radius of an anti-aliased corner relative to the design radius.
ROUNDED_ARC_RATIO = 0.55
#: Opaque backdrop drawn behind every dialog.
MODAL_SCRIM = "#E9EEF5"


class OperatorViewMixin(KioskViewMixin, AdaptiveDialogMixin, UpdateViewMixin):
    @staticmethod
    def font(size, weight="normal"):
        return ("Helvetica", size, weight)

    def rounded(
        self, x1, y1, x2, y2, radius=16, fill="white", outline="", width=1, tags=()
    ):
        create_rounded = getattr(self.canvas, "create_rounded", None)
        if create_rounded is not None:
            # A Tk smoothed polygon rounds a corner over about half of the
            # control radius; the true arc uses the same visual radius.
            item = create_rounded(
                x1,
                y1,
                x2,
                y2,
                radius * ROUNDED_ARC_RATIO,
                fill=fill,
                outline=outline,
                width=width,
                tags=tags,
            )
            if item is not None:
                return item
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

    def surface(self, color):
        """Context in which anti-aliased edges blend with ``color``."""
        factory = getattr(self.canvas, "surface", None)
        return factory(color) if factory is not None else nullcontext()

    def modal_card(self, x1, y1, x2, y2, radius, outline=""):
        """Draw a dialog card over the scrim; later shapes sit on the card."""
        with self.surface(MODAL_SCRIM):
            self.rounded(x1, y1, x2, y2, radius, self.CARD, outline, 1)
        if hasattr(self.canvas, "aa_backdrop"):
            self.canvas.aa_backdrop = self.CARD

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
        cache = getattr(self, "_opaque_brand_images", None)
        if cache is None:
            cache = self._opaque_brand_images = {}
        key = (size, self.CARD)
        if key not in cache:
            if len(cache) >= 8:
                cache.clear()
            cache[key] = opaque_photo(images[size], self.CARD, self.root)
        # The identity is static. Keep it outside the repeatedly invalidated
        # canvas drawable: XWayland can otherwise serialize the whole animated
        # canvas around an image copy even when its RGB pixels are unchanged.
        label = getattr(self, "_brand_label", None)
        if label is None:
            label = self._brand_label = tk.Label(
                self.canvas,
                borderwidth=0,
                highlightthickness=0,
                padx=0,
                pady=0,
                takefocus=False,
            )
        image = cache[key]
        signature = (
            key,
            x,
            y,
            self.canvas.scale_factor,
            self.canvas.offset_x,
            self.canvas.offset_y,
        )
        if (
            signature != getattr(self, "_brand_placement", None)
            or not label.winfo_manager()
        ):
            label.configure(image=image, bg=self.CARD)
            px = x * self.canvas.scale_factor + self.canvas.offset_x
            py = y * self.canvas.scale_factor + self.canvas.offset_y
            label.place(
                x=round(px - image.width() / 2),
                y=round(py - image.height() / 2),
                width=image.width(),
                height=image.height(),
            )
            self._brand_placement = signature
        self._brand_drawn = True
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
        palette = (
            self.BG,
            self.MUTED,
            self.RED,
            self.GREEN,
            self.BLUE,
            self.ORANGE,
            self.PURPLE,
        )
        if adjustable is None or self._adjustable_for != palette:
            adjustable = self._adjustable_text = {
                self.MUTED,
                self.RED,
                self.GREEN,
                self.BLUE,
                self.ORANGE,
                self.PURPLE,
            }
            self._adjustable_for = palette
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
        blink = phase % 5.5 < 0.12
        for dx in (-5, 5):
            self.rounded(
                cx + (dx - 2) * scale,
                cy - (5.5 if blink else 7) * scale,
                cx + (dx + 2) * scale,
                cy - (4.5 if blink else 3) * scale,
                2 * scale,
                accent,
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
                cy - 9 * scale,
                cx - 3 * scale,
                cy - 9 * scale,
                fill=accent,
                width=1,
            )
            self.canvas.create_line(
                cx + 3 * scale,
                cy - 9 * scale,
                cx + 10 * scale,
                cy - 9 * scale,
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

    def render(self):
        if getattr(self, "settings_visible", False):
            return
        page = (self.modal or {}).get("kind", "main")
        if page != getattr(self, "_presented_page", None):
            self._presented_page = page
            self._page_transition_until = time.monotonic() + 0.20
        self.canvas.begin_frame()
        self._brand_drawn = False
        try:
            self._render_frame()
            remaining = getattr(self, "_page_transition_until", 0) - time.monotonic()
            if remaining > 0:
                # Stable touch geometry throughout: animate the page accent,
                # never the button hitboxes or full-screen bitmap snapshots.
                width = self.viewport().width
                self.canvas.create_line(
                    16,
                    3,
                    16 + (width - 32) * min(1, remaining / 0.20),
                    3,
                    fill=self.BLUE,
                    width=3,
                )
        finally:
            self.canvas.end_frame()
            label = getattr(self, "_brand_label", None)
            if label is not None and not self._brand_drawn and label.winfo_manager():
                label.place_forget()

    def _render_frame(self):
        self.draw_kiosk_frame()

    def animate(self):
        if getattr(self, "_closing", False):
            return
        # At most one timer: explicit restarts and resize/touch repaints must
        # never accumulate independent animation loops over a long deployment.
        scheduled = getattr(self, "_animation_after", None)
        if scheduled is not None:
            self.root.after_cancel(scheduled)
        self._animation_after = None
        started = time.monotonic()
        visible = (
            self.root.winfo_viewable() if hasattr(self.root, "winfo_viewable") else True
        )
        try:
            if visible and not getattr(self, "render_blocked", False):
                self.render()
        finally:
            interval = int(self.config.get("animation_interval_ms", 33))
            if (
                not visible
                or getattr(self, "settings_visible", False)
                or getattr(self, "render_blocked", False)
            ):
                interval = max(250, interval)
            elif getattr(self, "modal", None) or getattr(self, "error_panel", None):
                touch = getattr(self, "touch_feedback", None)
                if time.monotonic() < getattr(self, "_page_transition_until", 0):
                    pass
                elif touch and time.monotonic() - touch[2] < 0.24:
                    pass  # Preserve the brief contact ring at the normal rate.
                elif getattr(self, "busy", False):
                    interval = max(100, interval)
                else:
                    # Static sheets need only a slow fallback refresh. Input,
                    # async results and resize already request immediate paint.
                    interval = max(1000, interval)
            spent = (time.monotonic() - started) * 1000
            # No catch-up bursts. Leave event-loop time for touch/network events
            # even on an overloaded or thermally throttled device.
            delay = max(10, round(interval - spent), round(spent * 0.25))
            self._animation_after = self.root.after(delay, self.animate)
