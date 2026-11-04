"""App-owned rounded panels, bounded by their parent rather than the desktop."""

import time
import tkinter as tk

from .responsive import ResponsiveCanvas
from .touch_button import TouchButton


class AppPanel(tk.Frame):
    """A modal page inside the kiosk, with no independent OS window chrome."""

    def __init__(self, parent, *, background, border, on_visibility=None):
        super().__init__(parent, bg=background, borderwidth=0, highlightthickness=0)
        self.on_visibility = on_visibility
        self._visible = False
        self.backdrop = ResponsiveCanvas(self, bg=background, highlightthickness=0)
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self.content = tk.Frame(self, bg="white")
        self.content.place(x=8, y=8, relwidth=1, width=-16, relheight=1, height=-16)
        self.border = border
        self._reveal_after = None
        self._ready = False
        # This cover is mapped before any form controls are created. Geometry
        # settling and font/raster work never expose a half-built Settings page.
        self.cover = tk.Frame(self, bg=background)
        self.cover.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Label(
            self.cover,
            text="Preparing controls…",
            bg=background,
            fg="#334B69",
            font=("Helvetica", 16, "bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")
        self.loading_progress = tk.Frame(self.cover, bg="#246BFD", height=4)
        TouchButton(
            self.cover,
            text="Back",
            command=self.destroy,
            font=("Helvetica", 12, "bold"),
            fg="#174EAE",
            bg="#E4EDFA",
            padx=24,
            pady=14,
        ).place(relx=0.5, rely=0.5, y=50, anchor="n")
        self.reveal_rail = tk.Frame(self, bg="#246BFD", height=3)
        self.backdrop.bind("<Configure>", self._resize)
        self.deiconify()

    def set_loading_progress(self, fraction):
        self.loading_progress.place(
            relx=0.35, rely=0.5, y=30, relwidth=0.3 * min(1, max(0, fraction)), height=4
        )

    def _resize(self, event):
        canvas = self.backdrop
        canvas.logical_width, canvas.logical_height = event.width, event.height
        canvas.set_viewport(event.width, event.height)
        canvas.aa_backdrop = self.cget("background")
        canvas.begin_frame()
        try:
            # Rasterise only the four tiny corners, not a screen-sized image.
            # At kiosk resolutions a full-panel raster needlessly stalls the
            # event loop and consumes megabytes whenever the viewport changes.
            w, h = max(2, event.width - 1), max(2, event.height - 1)
            radius = min(18, (w - 1) / 2, (h - 1) / 2)
            for x, y in (
                (1, 1),
                (w - 2 * radius, 1),
                (1, h - 2 * radius),
                (w - 2 * radius, h - 2 * radius),
            ):
                if (
                    canvas.create_rounded(
                        x,
                        y,
                        x + 2 * radius,
                        y + 2 * radius,
                        radius,
                        "white",
                        self.border,
                        1,
                    )
                    is None
                ):
                    canvas.create_oval(
                        x,
                        y,
                        x + 2 * radius,
                        y + 2 * radius,
                        fill="white",
                        outline=self.border,
                        width=1,
                    )
            canvas.create_rectangle(
                1 + radius, 1, w - radius, h, fill="white", outline=""
            )
            canvas.create_rectangle(
                1, 1 + radius, w, h - radius, fill="white", outline=""
            )
            for coords in (
                (1 + radius, 1, w - radius, 1),
                (1 + radius, h, w - radius, h),
                (1, 1 + radius, 1, h - radius),
                (w, 1 + radius, w, h - radius),
            ):
                canvas.create_line(*coords, fill=self.border, width=1)
        finally:
            canvas.end_frame()

    def deiconify(self):
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self._visible = True
        self.lift()
        if self.on_visibility:
            self.on_visibility(True)

    def present(self):
        """Reveal only after layout has settled; never move a touch target.

        Animate only a small accent, not a full native-widget tree. Moving the
        form generates Configure/redraw storms on high-resolution Pi panels.
        Input targets stay fixed, with only one cancellable timer.
        """
        self.update_idletasks()
        self._ready = True
        self.cover.place_forget()
        self._cancel_reveal()
        started = time.monotonic()

        def frame():
            self._reveal_after = None
            progress = min(1, (time.monotonic() - started) / 0.20)
            if progress >= 1 or not self._visible:
                self.reveal_rail.place_forget()
                return
            self.reveal_rail.place(x=8, y=8, relwidth=1 - progress, height=3)
            self.reveal_rail.lift()
            self._reveal_after = self.after(16, frame)

        frame()

    def _cancel_reveal(self):
        if self._reveal_after is not None:
            self.after_cancel(self._reveal_after)
            self._reveal_after = None
        self.content.place_configure(x=8)

    def withdraw(self):
        self._cancel_reveal()
        self.grab_release()
        self.place_forget()
        self._visible = False
        if self.on_visibility:
            self.on_visibility(False)

    def state(self):
        return "normal" if self._visible else "withdrawn"

    def overrideredirect(self, _value=None):
        # Compatibility for screenshot tooling: app-owned pages have no OS frame.
        return True

    def destroy(self):
        self.withdraw()
        super().destroy()
        if isinstance(self.master, AppPanel) and self.master.winfo_viewable():
            self.master.grab_set()
