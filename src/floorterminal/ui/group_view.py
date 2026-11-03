"""Bounded group overview and per-station operational status."""

from ..storage.incidents import all_incidents
from .conveyor import GROUP_COLORS
from .layout import split_row


class GroupViewMixin:
    def station_statuses(self):
        result = {}
        for incident in all_incidents(self.state):
            scope = incident.get("incident_scope")
            for station in (
                scope["affected_stations"] if scope else self.config["zones"]
            ):
                result[station] = (
                    incident["status"]
                    if incident["status"] != "RUNNING"
                    else "ENGINEERING"
                )
        return result

    def draw_group_overview(self):
        body, footer = self.dialog_shell(
            "PRODUCTION GROUPS",
            self.modal.get(
                "group_notice",
                "Tap a running group to report • tap a stopped group to continue",
            ),
        )
        a, b, c, d = body
        query = self.modal.get("filter", "").casefold()
        groups = [
            (i, g)
            for i, g in enumerate(self.station_groups())
            if not query
            or query in " ".join([g["name"], g["id"], *g["stations"]]).casefold()
        ]
        columns = max(1, min(4, len(groups) or 1, int((c - a) / 240)))
        rows = max(1, int((d - b - 28) / 64))
        capacity = rows * columns
        self.row_label(
            (a, b, c, b + 24),
            f"{len(groups)} groups • Group / Line = stop impact"
            if len(groups) <= capacity
            else f"Showing {capacity} of {len(groups)} • Find group to narrow",
            9,
            self.MUTED,
            "normal",
        )
        states = self.station_statuses()
        if not groups:
            self.row_label(
                (a, b + 32, c, b + 76), "No matching groups • change Find group", 10
            )
        used_rows = max(1, (min(len(groups), capacity) + columns - 1) // columns)
        row_height = min(112, (d - b - 28) / used_rows)
        for i, (index, group) in enumerate(groups[:capacity]):
            stopped = sum(s in states for s in group["stations"])
            incident = next(
                (
                    self.incident_for_station(s)
                    for s in group["stations"]
                    if self.incident_for_station(s)
                ),
                None,
            )
            status = (
                "RUN"
                if not stopped
                else {
                    "DOWN": "STOP",
                    "REPAIRING": "WORK",
                    "ENGINEERING": "PLAN",
                    "RUNNING": "PLAN",
                }[incident["status"]]
            )
            row, col = divmod(i, columns)
            rect = split_row(
                (a, b + 28 + row * row_height, c, b + 28 + (row + 1) * row_height - 8),
                columns,
            )[col]
            accent, tint = GROUP_COLORS[index % len(GROUP_COLORS)]
            self.kiosk_button(
                f"ui_group_pick_{index}",
                rect,
                f"{index + 1:02}  {group['name']}\n{status} · {len(group['stations'])} stations · {'Line stop' if group['stop_scope'] == 'line' else 'Group stop'}",
                "#FFF0E8" if stopped else tint,
                fg=self.TEXT,
                selected=incident is self.state,
            )
            self.canvas.create_line(
                rect[0] + 12,
                rect[1] + 12,
                rect[0] + 12,
                rect[3] - 12,
                fill=accent,
                width=3,
            )
        for (key, label), rect in zip(
            [
                ("ui_group_search", "Find group"),
                ("ui_group_whole", "Whole line"),
                ("cancel", "Back"),
            ],
            split_row(footer, 3),
        ):
            self.kiosk_button(key, rect, label)

    def group_control(self, key):
        if self.busy or self.error_panel:
            return
        if key == "ui_groups" and not self.modal:
            self.modal = {"kind": "groups", "group_page": 0}
            return
        if not self.modal or self.modal.get("kind") != "groups":
            return
        if key == "ui_group_search":
            previous = self.modal
            self.open_text_input(
                "group_search",
                "FIND PRODUCTION GROUP",
                "Group name, ID or station",
                previous.get("filter", ""),
                return_modal=previous,
                max_length=64,
            )
        elif key == "ui_group_whole":
            if any(all_incidents(self.state)):
                self.modal["group_notice"] = (
                    "Finish open group responses before starting a whole-line stop"
                )
                return
            self.modal = None
            self.select_issue_zone("all")
        elif key.startswith("ui_group_pick_"):
            group = self.station_groups()[int(key.removeprefix("ui_group_pick_"))]
            incident = next(
                (
                    self.incident_for_station(s)
                    for s in group["stations"]
                    if self.incident_for_station(s)
                ),
                None,
            )
            self.modal = None
            if incident:
                if incident is not self.state:
                    identifier = incident["incident_id"]
                    self.perform(
                        "Opening group response",
                        lambda: self.focus_incident(identifier),
                    )
            else:

                def select():
                    self.focus_incident()
                    self.state["issue_zones"] = list(group["stations"])
                    self.save_state()

                self.perform(
                    "Selecting production group",
                    select,
                    lambda _: self.primary_action(),
                )
