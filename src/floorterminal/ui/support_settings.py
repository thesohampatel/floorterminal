"""Administrator-owned support shortcut labels and message destinations."""

import tkinter as tk

from ..core.support import support_buttons


class SupportSettingsMixin:
    def build_support_settings(self, body, conversations):
        self.support_enabled = []
        for index, button in enumerate(support_buttons(self.app.config)):
            section = self._section(
                body,
                f"Home support button {index + 1}",
                "Message only. Does not change incident assignment or automatic activity notifications.",
            )
            enabled = tk.BooleanVar(value=button["enabled"])
            self.support_enabled.append(enabled)
            self._checkbox(section, "Show this button", enabled).grid(
                row=0, column=1, sticky="w", padx=(16, 0), pady=6
            )
            self._field(
                section,
                1,
                "Button label",
                f"integration_support_{index}_label",
                value=button["label"],
            )
            self._field(
                section,
                2,
                "Chat / person destination",
                f"integration_support_{index}_destination",
                value=button["destination"],
                choices=conversations,
                editable=True,
            )

    def support_settings_value(self):
        return [
            {
                "enabled": enabled.get(),
                "label": self.vars[f"integration_support_{index}_label"].get().strip(),
                "destination": self.vars[f"integration_support_{index}_destination"]
                .get()
                .strip(),
            }
            for index, enabled in enumerate(self.support_enabled)
        ]
