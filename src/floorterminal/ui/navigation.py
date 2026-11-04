"""Settings page selector that remains usable when six tabs cannot fit."""

import time
import tkinter as tk

from .touch_button import TouchButton


class PageBook(tk.Frame):
    """Retain form widgets through resize; never hide an unreachable tab."""

    def __init__(self, parent, *, background, foreground, font):
        super().__init__(parent, bg=background)
        self.pages, self.current = [], 0
        self.foreground, self.font = foreground, font
        self._transition_after = None
        self._transition_started = 0
        self.nav = tk.Frame(self, bg=background, height=52)
        self.nav.pack(fill="x")
        self.nav.pack_propagate(False)
        self.body = tk.Frame(self, bg=background)
        self.body.pack(fill="both", expand=True)
        self.previous = self._button(
            "‹", lambda: self.select((self.current - 1) % len(self.pages))
        )
        self.next = self._button(
            "›", lambda: self.select((self.current + 1) % len(self.pages))
        )
        self.caption = tk.Label(self.nav, bg=background, fg=foreground, font=font)
        self.indicator = tk.Frame(self.nav, bg="#246BFD", height=3)
        self.previous.refresh_surface(46, 46)
        self.next.refresh_surface(46, 46)
        self.bind(
            "<Configure>",
            lambda event: self._layout() if event.widget is self else None,
        )
        self.bind("<Destroy>", self._destroyed, add="+")

    def _destroyed(self, event):
        if event.widget is self and self._transition_after is not None:
            self.after_cancel(self._transition_after)
            self._transition_after = None

    def _button(self, label, command):
        return TouchButton(
            self.nav,
            text=label,
            command=command,
            font=self.font,
            bg="#E5EDF8",
            fg=self.foreground,
            padx=8,
            pady=10,
        )

    def add(self, page, text):
        index = len(self.pages)
        button = self._button(text, lambda: self.select(index))
        self.pages.append((page, text, button))
        self.select(self.current)

    def tabs(self):
        return tuple(str(page) for page, _, _ in self.pages)

    def index(self, value):
        if value == "current":
            return self.current
        return value if isinstance(value, int) else self.tabs().index(str(value))

    def select(self, value=None):
        if value is None:
            return self.tabs()[self.current]
        previous = self.current
        self.current = self.index(value)
        for index, (page, _, _) in enumerate(self.pages):
            if index == self.current:
                page.place(in_=self.body, x=0, y=0, relwidth=1, relheight=1)
            else:
                page.place_forget()
        self._layout()
        if previous != self.current and self.winfo_viewable():
            if self._transition_after is not None:
                self.after_cancel(self._transition_after)
            self._transition_started = time.monotonic()
            self._animate_indicator(previous)

    def _animate_indicator(self, previous):
        self._transition_after = None
        progress = min(1, (time.monotonic() - self._transition_started) / 0.18)
        eased = 1 - (1 - progress) ** 3
        # Keep native controls stationary: only the navigation accent moves.
        # Sliding hundreds of widgets can saturate XWayland with redraws.
        width = self.winfo_width()
        if width >= 720:
            cell = width / len(self.pages)
            x = (previous + (self.current - previous) * eased) * cell
            self.indicator.place(
                x=round(x + 12), y=49, width=max(1, round(cell - 30)), height=3
            )
        if progress < 1:
            self._transition_after = self.after(
                16, lambda: self._animate_indicator(previous)
            )

    def bbox(self, index):
        widget = self.pages[index][2] if self.winfo_width() >= 720 else self.caption
        return (
            widget.winfo_x(),
            widget.winfo_y(),
            widget.winfo_width(),
            widget.winfo_height(),
        )

    def _layout(self):
        width = self.winfo_width()
        if not self.pages:
            return
        for widget in (self.previous, self.next, self.caption):
            widget.place_forget()
        for _, _, button in self.pages:
            button.place_forget()
        if width >= 720:
            cell = width / len(self.pages)
            for index, (_, _, button) in enumerate(self.pages):
                size = (max(1, round(cell) - 8), 46)
                if size != getattr(button, "_surface_size", None):
                    button.refresh_surface(*size)
                button.configure(
                    fg="#205BD7" if index == self.current else self.foreground
                )
                color = "#DDEAFF" if index == self.current else "#EDF2F9"
                if button.face_color != color:
                    button.face_color = color
                    button.refresh_surface(*size)
                button.configure(wraplength=max(1, round(cell) - 20))
                button.place(
                    x=round(index * cell), y=2, width=round(cell) - 6, height=48
                )
            self.indicator.place(
                x=round(self.current * cell + 12),
                y=49,
                width=max(1, round(cell - 30)),
                height=3,
            )
            self.indicator.lift()
        else:
            self.indicator.place_forget()
            self.previous.place(x=0, y=2, width=48, height=48)
            self.next.place(x=max(0, width - 48), y=2, width=48, height=48)
            self.caption.configure(
                text=f"{self.current + 1}/{len(self.pages)}  ·  {self.pages[self.current][1]}"
            )
            self.caption.configure(wraplength=max(1, width - 116))
            self.caption.place(x=54, y=2, width=max(1, width - 108), height=48)
