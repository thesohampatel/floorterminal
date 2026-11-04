"""Touch-sized, in-app choices; preserve native entry and variable semantics."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .panels import AppPanel
from .touch_button import TouchButton


class TouchChoice(ttk.Combobox):
    """Editable suggestions or fixed choices without a desktop popup menu.

    Typing still works in editable fields. Read-only fields open anywhere;
    editable fields open via the arrow, F4 or Alt+Down. Selection commits once,
    emits the normal virtual event and restores the enclosing modal grab.
    """

    def __init__(self, parent, *, title="Choose an option", **kwargs):
        super().__init__(parent, **kwargs)
        self.choice_title = title
        self.picker = None
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<F4>", self._open)
        self.bind("<Alt-Down>", self._open)
        self.bind("<Down>", self._open)
        self.bind("<space>", self._space)

    def _space(self, event):
        if str(self.cget("state")) == "readonly":
            return self._open(event)

    def _press(self, event):
        if str(self.cget("state")) == "readonly" or "arrow" in self.identify(
            event.x, event.y
        ):
            return self._open(event)

    def _open(self, _event=None):
        if str(self.cget("state")) == "disabled":
            return "break"
        if self.picker is not None and self.picker.winfo_exists():
            return "break"
        parent = self.master
        while not isinstance(parent, AppPanel) and parent.master is not None:
            parent = parent.master
        panel = self.picker = AppPanel(parent, background="#F3F6FB", border="#C8D5E5")
        font = tkfont.Font(root=panel, font=self.cget("font"))
        size = font.actual("size")
        font.configure(size=max(12, abs(size)) * (-1 if size < 0 else 1))
        heading_font = tkfont.Font(root=panel, font=font)
        heading_font.configure(weight="bold")
        # Own these fonts for the entire panel lifetime, including after _open
        # returns; Tcl widgets refer to a font name, not its Python owner.
        panel._choice_fonts = (font, heading_font)
        title = (
            self.choice_title.get()
            if isinstance(self.choice_title, tk.Variable)
            else self.choice_title
        )
        tk.Label(
            panel.content,
            text=title,
            bg="white",
            fg="#14213D",
            font=heading_font,
            anchor="w",
            padx=20,
            pady=14,
        ).pack(fill="x")
        search = tk.StringVar(panel)
        field = tk.Entry(
            panel.content,
            textvariable=search,
            font=font,
            relief="flat",
            bg="#EDF3FC",
            fg="#14213D",
            highlightthickness=1,
            highlightbackground="#BDCEE4",
            highlightcolor="#246BFD",
        )
        values = tuple(str(value) for value in self.cget("values"))
        if len(values) > 12:
            field.pack(fill="x", padx=20, pady=(0, 12), ipady=10)
        footer = tk.Frame(panel.content, bg="white")
        footer.pack(side="bottom", fill="x", padx=20, pady=12)
        grid = tk.Frame(panel.content, bg="white")
        grid.pack(fill="both", expand=True, padx=16, pady=8)
        page, pending = [0], [None]

        def close():
            if pending[0] is not None:
                panel.after_cancel(pending[0])
                pending[0] = None
            panel.destroy()
            self.picker = None
            if self.winfo_exists():
                self.focus_set()

        def choose(value):
            self.set(value)
            close()
            self.event_generate("<<ComboboxSelected>>")

        def button(container, text, command, selected=False):
            return TouchButton(
                container,
                text=text,
                command=command,
                font=font,
                bg="#DDEAFF" if selected else "#EDF3FC",
                fg="#174EAE",
            )

        previous = button(footer, "Previous", lambda: turn(-1))
        previous.pack(side="left")
        next_button = button(footer, "Next", lambda: turn(1))
        next_button.pack(side="left", padx=8)
        button(footer, "Back", close).pack(side="right")
        count = tk.Label(footer, font=font, bg="white", fg="#526780")
        count.pack(side="right", padx=12)

        def draw():
            pending[0] = None
            matches = [v for v in values if search.get().casefold() in v.casefold()]
            width, height = grid.winfo_width(), grid.winfo_height()
            previous.configure(text="‹" if width < 650 else "Previous")
            next_button.configure(text="›" if width < 650 else "Next")
            previous.refresh_surface()
            next_button.refresh_surface()
            columns = max(1, min(3, width // 270))
            row_height = max(60, field.winfo_reqheight() + 28)
            rows = max(1, min(6, height // row_height))
            capacity = rows * columns
            pages = max(1, (len(matches) + capacity - 1) // capacity)
            page[0] = max(0, min(page[0], pages - 1))
            visible = matches[page[0] * capacity : (page[0] + 1) * capacity]
            used_rows = max(1, (len(visible) + columns - 1) // columns)
            tile_height = max(row_height, min(104, height // used_rows))
            for widget in grid.winfo_children():
                widget.destroy()
            for index, value in enumerate(visible):
                row, col = divmod(index, columns)
                w = max(44, width // columns - 8)
                display = value
                while (
                    len(display) > 1
                    and int(self.tk.call("font", "measure", font, display)) > w - 28
                ):
                    display = display[:-1]
                if display != value:
                    display = display[:-1] + "…"
                item = button(
                    grid, display, lambda v=value: choose(v), value == self.get()
                )
                item.refresh_surface(w - 2, tile_height - 10)
                item.configure(wraplength=w - 24)
                item.place(
                    x=col * width // columns + 4,
                    y=row * tile_height,
                    width=w,
                    height=tile_height - 6,
                )
            if not matches:
                tk.Label(grid, text="No matching options", font=font, bg="white").place(
                    relx=0.5, rely=0.5, anchor="center"
                )
            count.configure(
                text=f"{page[0] + 1} / {pages}"
                if pages > 1
                else f"{len(matches)} options"
            )
            if pages > 1:
                previous.pack(side="left", before=count)
                next_button.pack(side="left", padx=8, before=count)
            else:
                previous.pack_forget()
                next_button.pack_forget()
            previous.configure(state="normal" if page[0] else "disabled")
            next_button.configure(state="normal" if page[0] + 1 < pages else "disabled")

        def schedule(_event=None):
            if pending[0] is None:
                pending[0] = panel.after_idle(draw)

        def turn(delta):
            page[0] += delta
            schedule()

        def filter_changed(*_args):
            page[0] = 0
            schedule()

        search_trace = search.trace_add("write", filter_changed)
        grid.bind("<Configure>", schedule)

        def destroyed(event):
            if event.widget is panel:
                # Tcl owns trace callbacks independently of the widget tree.
                # Remove the closure explicitly so repeated opening cannot keep
                # old panels, variables and fonts alive for a long kiosk session.
                search.trace_remove("write", search_trace)
                if pending[0] is not None:
                    panel.after_cancel(pending[0])
                    pending[0] = None
                if self.picker is panel:
                    self.picker = None

        panel.bind("<Destroy>", destroyed, add="+")
        panel.bind("<Escape>", lambda _e: close())
        panel.update_idletasks()
        draw()
        panel.grab_set()
        panel.present()
        panel.focus_set()
        return "break"
