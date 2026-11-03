"""Reusable, bounded-widget editor for each station's custom failure reasons."""

import math
import tkinter as tk
from tkinter import ttk


class FailureSettingsMixin:
    FAILURE_ROWS = 4  # Visible editor rows, never a catalogue-size limit.

    def build_failure_editor(self, parent):
        self._failure_draft, self._failure_page = [], 0
        self.failure_vars = [tk.StringVar() for _ in range(self.FAILURE_ROWS)]
        self.failure_numbers, self.failure_entries = [], []
        self.failure_count = tk.StringVar()
        tk.Label(
            parent,
            textvariable=self.failure_count,
            font=self.font(9, "bold"),
            fg=self.app.BLUE,
            bg="white",
            anchor="w",
        ).pack(fill="x", pady=(4, 4))
        for index, variable in enumerate(self.failure_vars):
            row = tk.Frame(parent, bg="white")
            row.pack(fill="x", pady=3)
            number = tk.StringVar()
            self.failure_numbers.append(number)
            tk.Label(
                row,
                textvariable=number,
                font=self.font(9, "bold"),
                fg=self.app.BLUE,
                bg="#EAF1FF",
                width=4,
            ).pack(side="left")
            entry = ttk.Entry(
                row,
                textvariable=variable,
                font=self.font(10),
                style="Settings.TEntry",
            )
            entry.pack(side="left", fill="x", expand=True, ipady=4, padx=7)
            self.failure_entries.append(entry)
            self._button(
                row,
                "Remove",
                lambda i=index: self.remove_failure(i),
                "#EAF0F8",
                self.app.TEXT,
            ).pack(side="right")
        controls = tk.Frame(parent, bg="white")
        controls.pack(fill="x", pady=(8, 4))
        for label, command in (
            ("Previous", lambda: self.change_failure_page(-1)),
            ("Add reason", self.add_failure),
            ("Next", lambda: self.change_failure_page(1)),
        ):
            self._button(controls, label, command, "#EAF1FF", self.app.BLUE).pack(
                side="left",
                fill="x",
                expand=True,
                padx=2,
            )
        self._autowrap(
            tk.Label(
                parent,
                text=self.t("settings_leave_unused_rows_blank_at_least"),
                font=self.font(8, "bold"),
                fg=self.app.GREEN,
                bg="white",
                justify="left",
                anchor="w",
            ),
            parent,
            40,
        ).pack(anchor="w", fill="x", pady=(6, 0))

    def _store_failure_page(self):
        start = self._failure_page * self.FAILURE_ROWS
        for offset, var in enumerate(self.failure_vars):
            index, value = start + offset, var.get().strip()
            if index < len(self._failure_draft):
                self._failure_draft[index] = value
            elif value:
                self._failure_draft.extend([""] * (index - len(self._failure_draft)))
                self._failure_draft.append(value)

    def _collect_failures(self):
        self._store_failure_page()
        return [value for value in self._failure_draft if value]

    def _load_failures(self, values):
        self._failure_draft, self._failure_page = list(values), 0
        self._show_failure_page()

    def _show_failure_page(self):
        pages = max(1, math.ceil(len(self._failure_draft) / self.FAILURE_ROWS))
        self._failure_page = min(max(0, self._failure_page), pages - 1)
        start = self._failure_page * self.FAILURE_ROWS
        for offset, var in enumerate(self.failure_vars):
            index = start + offset
            var.set(
                self._failure_draft[index] if index < len(self._failure_draft) else ""
            )
            self.failure_numbers[offset].set(str(index + 1))
        count = sum(bool(value) for value in self._failure_draft)
        self.failure_count.set(
            f"{count} custom + Others • editor page {self._failure_page + 1}/{pages}"
        )

    def change_failure_page(self, delta):
        self._store_failure_page()
        self._failure_page += delta
        self._show_failure_page()

    def add_failure(self):
        self._store_failure_page()
        # Reuse an empty draft row; repeated touches never append blank pages.
        index = next(
            (i for i, value in enumerate(self._failure_draft) if not value),
            len(self._failure_draft),
        )
        if index == len(self._failure_draft):
            self._failure_draft.append("")
        self._failure_page = index // self.FAILURE_ROWS
        self._show_failure_page()
        self.failure_entries[index % self.FAILURE_ROWS].focus_set()

    def remove_failure(self, offset):
        self._store_failure_page()
        index = self._failure_page * self.FAILURE_ROWS + offset
        if index < len(self._failure_draft):
            self._failure_draft.pop(index)
        self._show_failure_page()
