"""Short, action-oriented kiosk sheets: no routine next/previous wizard pages."""

import time

from .failure_layout import reason_page
from .layout import split_row


class OperationalDialogMixin:
    def operation_actions(self, box, actions):
        """A consistent two-by-two action area for report/optional choices."""
        a, b, c, _d = box
        for start in (0, 2):
            for (key, label, fill, color), rect in zip(
                actions[start : start + 2],
                split_row((a, b + start * 28, c, b + start * 28 + 48), 2),
            ):
                self.kiosk_button(key, rect, label, fill, fg=color)

    def impact_label(self, *, active=False):
        scope = (
            self.state.get("incident_scope")
            if active
            else (self.preview_scope() if self.has_zone_selection() else None)
        )
        if not scope:
            return "Select affected stations before reporting"
        count = len(scope["affected_stations"])
        if scope["impact"] == "line":
            return (
                f"Resume entire line • {count} stations"
                if active
                else f"Entire line stops • {count} stations affected"
            )
        return (
            f"Resume {len(scope['groups'])} group(s) • {count} stations"
            if active
            else f"{len(scope['groups'])} group(s) stop • {count} stations affected"
        )

    def operation_summary(self, box, *, active=False, safety="", note=""):
        """Show actual scope and short safety instructions without paginating them."""
        a, b, c, d = box
        self.rounded(a, b, c, d, 16, "#F5F8FC", self.BORDER)
        selected = self.selected_zones()
        title = (
            selected[0]
            if len(selected) == 1
            else f"{len(selected)} fault stations selected"
        )
        self.row_label((a + 12, b + 8, c - 12, b + 38), title, 13, self.BLUE)
        y = b + 44
        for value, color in (
            (self.impact_label(active=active), self.TEXT),
            (safety, self.TEXT),
            (note, self.ORANGE),
        ):
            if not value:
                continue
            lines = self.wrap_lines(value, c - a - 24, 10)
            for line in lines:
                if y + 20 > d - 8:
                    # Long optional data is not an operational confirmation. The
                    # concise scope/safety text above always takes priority.
                    return
                self.row_label((a + 12, y, c - 12, y + 20), line, 10, color, "normal")
                y += 20
            y += 6

    def report_choice_dialog(self):
        body, footer = self.dialog_shell(
            "REPORT A STOPPAGE",
            "Choose the response • this records the stop",
            footer_rows=2,
        )
        self.operation_summary(
            body,
            safety="Engineering: request help. Self-fix: only work you are trained and permitted to do.",
        )
        self.operation_actions(
            footer,
            [
                (
                    "confirm",
                    "Report • Engineering",
                    self.RED,
                    self.label_color(self.RED, "white"),
                ),
                ("operator_self_fix", "Start self-fix", self.PALE_BLUE, self.BLUE),
                ("operator_details", "Optional name / details", None, self.TEXT),
                ("cancel", "Back", None, self.TEXT),
            ],
        )

    def completion_dialog(self):
        body, footer = self.dialog_shell(
            "READY TO RESUME?", "Confirm the actual production release"
        )
        self.operation_summary(
            body,
            active=True,
            safety="Work complete. Guards restored. Safe to run. Other group responses stay unchanged.",
            note=self.modal.get("note", ""),
        )
        self.dialog_actions(
            footer,
            [
                ("cancel", "Not yet", None, self.TEXT),
                (
                    "confirm",
                    "Confirm • resume",
                    self.GREEN,
                    self.label_color(self.GREEN, "white"),
                ),
            ],
        )

    def failures_dialog(self):
        station = self.modal["station"]
        body, footer = self.dialog_shell(
            "REPORT • " + station,
            self.impact_label() + " • Self-fix: trained and permitted work only",
            footer_rows=2,
        )
        a, b, c, _d = body
        selected, options = self.modal["selected"], self.modal["options"]
        matches = self.modal.get("matches", range(max(0, len(options) - 1)))
        visible, slots, page, pages, controls = reason_page(
            body,
            matches,
            self.modal.get("page", 0),
            searching=bool(self.modal.get("filter")),
        )
        self.modal["page"] = page
        self.modal["reason_pages"] = pages
        self.row_label(
            (a, b, c, b + 24),
            f"{len(selected)} selected • optional • {len(matches)} custom reasons"
            + (f" • page {page + 1}/{pages}" if pages > 1 else "")
            + (" • filtered" if self.modal.get("filter") else ""),
            9,
            self.MUTED,
            "normal",
        )
        for index, rect in zip([*visible, len(options) - 1], slots):
            option = options[index]
            chosen = option in selected
            self.kiosk_button(
                f"failure_{index}",
                rect,
                ("✓  " if chosen else "") + option[:240],
                self.PALE_BLUE if chosen else None,
                selected=chosen,
            )
        actions = [("failure_all", "All"), ("failure_clear", "None")]
        if pages > 1 or self.modal.get("filter"):
            actions += [("failure_search", "Find")]
        if pages > 1:
            actions += [("failure_previous", "‹ Back"), ("failure_next", "Next ›")]
        for (key, label), rect in zip(actions, split_row(controls, len(actions))):
            self.kiosk_button(key, rect, label)
        self.modal["layout_page"], self.modal["layout_pages"] = 0, 1
        self.operation_actions(
            footer,
            [
                (
                    "failure_report",
                    "Report • Engineering",
                    self.RED,
                    self.label_color(self.RED, "white"),
                ),
                ("failure_self_fix", "Start self-fix", self.PALE_BLUE, self.BLUE),
                (
                    "failure_done",
                    "Note / more stations"
                    if "Others" in selected
                    else "Keep selection / more stations",
                    None,
                    self.TEXT,
                ),
                ("failure_remove", "Deselect station", None, self.TEXT),
            ],
        )

    def crew_dialog(self):
        context = self.modal.get("context", {}).get("kind")
        editing = context == "edit"
        batch = self.modal.get("batch", False)
        body, footer = self.dialog_shell(
            "UPDATE CREW"
            if editing
            else "START PLANNED WORK"
            if context == "planned"
            else "ENGINEERING HAS ARRIVED",
            "Choose several names, then Apply"
            if batch
            else "Tap a name to join or leave"
            if editing
            else "Tap your name to start work • saves immediately",
        )
        a, b, c, d = body
        members, selected = self.modal["members"], self.modal["selected"]
        columns = max(1, min(4, len(members) or 1, int((c - a) / 230)))
        rows = max(1, int((d - b - 28) / 64))
        capacity = rows * columns
        visible = members[:capacity]
        self.modal["page"], self.modal["members_per_page"] = 0, capacity
        self.modal["visible_member_count"] = len(visible)
        detail = (
            f"{len(members)} matching names"
            if self.modal.get("filter")
            else f"{len(members)} team members • current crew first"
        )
        if len(members) > capacity:
            detail = f"Showing {capacity} of {len(members)} • use Find name to narrow"
        elif self.modal.get("cached_at"):
            minutes = max(0, int((time.time() - self.modal["cached_at"]) / 60))
            detail = f"{len(members)} names • saved roster {minutes}m ago"
        self.row_label((a, b, c, b + 24), detail, 9, self.MUTED, "normal")
        if not visible:
            self.row_label((a, b + 32, c, b + 76), self.t("no_engineers_match"), 10)
        used_rows = max(1, (len(visible) + columns - 1) // columns)
        row_height = min(112, (d - b - 28) / used_rows)
        grid_width = min(c - a, columns * 360)
        left, right = (a + c - grid_width) / 2, (a + c + grid_width) / 2
        for index, member in enumerate(visible):
            row, column = divmod(index, columns)
            rect = split_row(
                (
                    left,
                    b + 28 + row * row_height,
                    right,
                    b + 28 + (row + 1) * row_height - 8,
                ),
                columns,
            )[column]
            chosen = str(member["id"]) in selected
            action = "✓ Selected" if chosen else "Select"
            if not batch:
                action = ("Leave" if chosen else "Join") if editing else "Start work"
            self.kiosk_button(
                f"member_{index}",
                rect,
                "",
                self.PALE_BLUE if chosen else None,
                selected=chosen,
            )
            x1, y1, x2, y2 = rect
            fill = self.PALE_BLUE if chosen else "#EAF0F8"
            center = (y1 + y2) / 2
            with self.surface(fill):
                self.canvas.create_oval(
                    x1 + 12,
                    center - 16,
                    x1 + 44,
                    center + 16,
                    fill="white",
                    outline=self.BLUE if chosen else self.BORDER,
                )
            initials = "".join(
                part[0] for part in member["displayName"].split()[:2]
            ).upper()
            self.row_label(
                (x1 + 14, center - 14, x1 + 42, center + 14),
                initials,
                9,
                self.BLUE,
                anchor="center",
            )
            self.row_label(
                (x1 + 54, center - 24, x2 - 10, center + 2), member["displayName"], 12
            )
            self.row_label(
                (x1 + 54, center + 2, x2 - 10, center + 24),
                action,
                10,
                self.BLUE if chosen else self.MUTED,
                "normal",
            )
        actions = (
            [
                (
                    "start_engineers",
                    "Apply",
                    self.GREEN,
                    self.label_color(self.GREEN, "white"),
                ),
                ("members_search", "Find name", None, self.TEXT),
                ("members_mode", "Single tap", None, self.TEXT),
                ("cancel", "Back", None, self.TEXT),
            ]
            if batch
            else [
                ("members_search", "Find name", None, self.TEXT),
                ("members_mode", "Select several", None, self.TEXT),
                ("cancel", "Back", None, self.TEXT),
            ]
        )
        for (key, label, fill, color), rect in zip(
            actions, split_row(footer, len(actions))
        ):
            self.kiosk_button(key, rect, label, fill, fg=color)
