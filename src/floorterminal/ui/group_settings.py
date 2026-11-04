"""Station grouping editor using the existing touch-paged Settings form."""

import tkinter as tk
import uuid

from ..core.config import ConfigurationError
from ..core.topology import groups_for
from .choices import TouchChoice


class GroupSettingsMixin:
    def load_groups(self):
        self.group_ids = {}
        for group in groups_for(self.app.config):
            self.group_ids[group["name"]] = group["id"]
            for station in self.stations:
                if station["name"] in group["stations"]:
                    station.update(group=group["name"], scope=group["stop_scope"])

    def group_form(self, parent):
        self.group_name = tk.StringVar()
        self.group_scope = tk.StringVar()
        self.group_hint = tk.StringVar()
        tk.Label(
            parent,
            text=self.t("group_heading"),
            font=self.font(9, "bold"),
            bg="white",
            fg=self.app.TEXT,
        ).pack(anchor="w", pady=(8, 3))
        self.group_entry = TouchChoice(
            parent,
            title=self.t("group_heading"),
            textvariable=self.group_name,
            values=tuple(self.group_ids),
            font=self.font(12),
            style="Settings.TCombobox",
        )
        self.group_entry.pack(fill="x", ipady=8)
        guidance = tk.Label(
            parent,
            text=self.t("group_guidance"),
            wraplength=260,
            justify="left",
            font=self.font(9),
            bg="white",
            fg=self.app.MUTED,
        )
        self._autowrap(guidance, parent, 40).pack(fill="x", pady=5)
        tk.Label(
            parent,
            text=self.t("group_impact"),
            font=self.font(9, "bold"),
            bg="white",
            fg=self.app.TEXT,
        ).pack(anchor="w", pady=(6, 3))
        TouchChoice(
            parent,
            title=self.t("group_impact"),
            textvariable=self.group_scope,
            values=(self.t("group_only"), self.t("group_whole_line")),
            state="readonly",
            font=self.font(12),
            style="Settings.TCombobox",
        ).pack(fill="x", ipady=8)
        hint = tk.Label(
            parent,
            textvariable=self.group_hint,
            wraplength=260,
            justify="left",
            font=self.font(9),
            bg="white",
            fg=self.app.BLUE,
        )
        self._autowrap(hint, parent, 40).pack(fill="x", pady=(8, 14))
        self.group_entry.bind("<<ComboboxSelected>>", self.select_group)
        self.group_name.trace_add("write", self.show_group_hint)
        self.group_scope.trace_add("write", self.show_group_hint)

    def select_group(self, _event=None):
        name = self.group_name.get().strip()
        for station in self.stations:
            if station.get("group") == name:
                self.group_scope.set(
                    self.t("group_whole_line")
                    if station.get("scope") == "line"
                    else self.t("group_only")
                )
                break

    def show_group_hint(self, *_args):
        name = self.group_name.get().strip()
        members = [s["name"] for s in self.stations if s.get("group") == name]
        key = self.group_ids.get(name, "Assigned when saved")
        impact = (
            "All stations stop"
            if self.group_scope.get() == self.t("group_whole_line")
            else "Other groups keep running"
        )
        target = self.app.group_targets().get(key, {}).get("asset_id")
        mapping = (
            "Asset mapping present"
            if target
            else "No group asset mapping • local group status only"
        )
        self.group_hint.set(
            f"{impact}\nConnector group ID: {key}\n{mapping}\nLinked: {', '.join(members[:6]) or 'New group'}"
            + (f" (+{len(members) - 6})" if len(members) > 6 else "")
        )

    def store_group(self):
        name = self.group_name.get().strip()
        scope = (
            "line" if self.group_scope.get() == self.t("group_whole_line") else "group"
        )
        if name not in self.group_ids:
            self.group_ids[name] = "group-" + uuid.uuid4().hex[:12]
        for station in self.stations:
            if station.get("group") == name:
                station["scope"] = scope
        self.group_entry.configure(values=tuple(self.group_ids))
        return {"group": name, "scope": scope}

    def configured_groups(self):
        groups = {}
        for station in self.stations:
            name = station.get("group", "")
            if not name:
                raise ConfigurationError("Each station needs a production group name")
            group = groups.setdefault(
                name,
                {
                    "id": self.group_ids[name],
                    "name": name,
                    "stop_scope": station["scope"],
                    "stations": [],
                },
            )
            group["stations"].append(station["name"])
        result = list(groups.values())
        # Do not turn an unchanged legacy setup into a new routing topology.
        if (
            not self.app.config.get("station_groups")
            and len(result) == 1
            and result[0]["id"] == "line"
            and result[0]["stop_scope"] == "line"
        ):
            return []
        return result
