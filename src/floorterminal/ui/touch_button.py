"""Native accessible Tk button with a cached, rounded touch surface."""

import tkinter as tk
from collections import OrderedDict
from tkinter import font as tkfont

from .raster import rounded_rectangle_png


class TouchButton(tk.Button):
    """Keep native focus, keyboard, disabled and invoke behaviour; style the face.

    Exactly three small images are owned by each button. No per-frame painting,
    fonts dependent on emoji availability, or external drawing library is used.
    """

    def __init__(self, parent, *, text, command, font, bg, fg, padx=16, pady=10):
        backdrop = parent.cget("background")
        super().__init__(
            parent,
            text=text,
            command=command,
            font=font,
            fg=fg,
            bg=backdrop,
            activebackground=backdrop,
            activeforeground=fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=backdrop,
            highlightcolor="#246BFD",
            compound="center",
            padx=0,
            pady=0,
            cursor="hand2",
            takefocus=True,
        )
        self.face_color, self.face_backdrop = bg, backdrop
        self.face_padding = (padx, pady)
        self._release_after = None
        self.refresh_surface()
        self.bind("<Enter>", lambda _event: self._face("active"), add="+")
        self.bind("<Leave>", lambda _event: self._face("normal"), add="+")
        self.bind("<ButtonPress-1>", lambda _event: self._face("pressed"), add="+")
        self.bind("<ButtonRelease-1>", self._release_face, add="+")
        self.bind("<KeyPress-space>", lambda _event: self._face("pressed"), add="+")
        self.bind("<KeyRelease-space>", self._release_face, add="+")
        self.bind("<Destroy>", self._cancel_release, add="+")

    def refresh_surface(self, width=None, height=None):
        """Resize only on layout/font changes, never on the animation clock."""
        measure = tkfont.Font(root=self, font=self.cget("font"))
        padx, pady = self.face_padding
        width = width or max(44, measure.measure(self.cget("text")) + int(padx) * 2)
        height = height or max(44, measure.metrics("linespace") + int(pady) * 2)
        width, height = round(width), round(height)
        self._surface_size = (width, height)
        base = tuple(value // 257 for value in self.winfo_rgb(self.face_color))
        surface = tuple(value // 257 for value in self.winfo_rgb(self.face_backdrop))
        signature = (width, height, base, surface)
        if signature == getattr(self, "_face_signature", None):
            return
        self._face_signature = signature
        # Share identical faces within this Tcl interpreter only. Retain a
        # bounded LRU; live buttons keep their own references after eviction.
        root = self._root()
        cache = getattr(root, "_touch_faces", None)
        if cache is None:
            cache = root._touch_faces = OrderedDict()
            root._touch_face_bytes = 0
        if signature in cache:
            self.faces = cache[signature]
            cache.move_to_end(signature)
            self.configure(image=self.faces["normal"])
            return
        self.faces = {}
        for key, factor in (("normal", 1), ("active", 0.96), ("pressed", 0.88)):
            fill = tuple(round(value * factor) for value in base)
            png = rounded_rectangle_png(
                width,
                height,
                min(12, height / 4),
                fill,
                tuple(round(v * 0.82) for v in base),
                1,
                surface,
            )
            self.faces[key] = tk.PhotoImage(master=self, data=png, format="png")
        self.configure(image=self.faces["normal"])
        cost = width * height * 4 * 3
        if cost <= 8 * 1024 * 1024:
            cache[signature] = self.faces
            root._touch_face_bytes += cost
            while len(cache) > 48 or root._touch_face_bytes > 8 * 1024 * 1024:
                (w, h, _base, _surface), _images = cache.popitem(last=False)
                root._touch_face_bytes -= w * h * 4 * 3

    def _face(self, name):
        if name == "pressed":
            self._cancel_release()
        if str(self.cget("state")) != "disabled":
            self.configure(image=self.faces[name])

    def _cancel_release(self, _event=None):
        if self._release_after is not None:
            self.after_cancel(self._release_after)
            self._release_after = None

    def _release_face(self, _event=None):
        self._cancel_release()
        if str(self.cget("state")) == "disabled":
            return
        self._face("active")

        def settled():
            self._release_after = None
            self._face("normal")

        self._release_after = self.after(120, settled)
