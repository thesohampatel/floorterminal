"""Reflowing operator workspace, shared touch controls and text measurement."""

import math
import time
from datetime import datetime

from ..core.support import support_buttons
from .contrast import readable_label
from .conveyor import GROUP_COLORS, advance_motion, belt_point, station_slots
from .group_view import GroupViewMixin
from .layout import GAP, Viewport, header_regions, split_row, station_capacity


class KioskViewMixin(GroupViewMixin):
    def viewport(self):
        return Viewport(
            self.canvas.logical_width,
            self.canvas.logical_height,
            self.canvas.scale_factor,
        )

    def measure_label(self, value, size=10, weight="normal"):
        cache = getattr(self, "_label_metrics", None)
        if cache is None:
            cache = self._label_metrics = {}
        scale = self.canvas.scale_factor
        key = (str(value), size, weight, scale)
        if key not in cache:
            if len(cache) >= 2048:
                cache.clear()
            font = ("Helvetica", max(1, round(size * scale)), weight)
            cache[key] = (
                float(self.canvas.tk.call("font", "measure", font, str(value))) / scale
            )
        return cache[key]

    def fit_label(self, value, width, size=10, weight="bold"):
        value = " ".join(str(value or "").split())
        if self.measure_label(value, size, weight) <= width:
            return value
        low, high = 0, len(value)
        while low < high:
            mid = (low + high + 1) // 2
            if self.measure_label(value[:mid] + "…", size, weight) <= width:
                low = mid
            else:
                high = mid - 1
        return value[:low] + "…"

    def row_label(self, box, value, size=10, color=None, weight="bold", anchor="w"):
        x1, y1, x2, y2 = box
        x = (x1 + x2) / 2 if anchor == "center" else x1
        return self.text(
            x,
            (y1 + y2) / 2,
            self.fit_label(value, max(1, x2 - x1 - 2), size, weight),
            size,
            color or self.TEXT,
            weight,
            anchor,
        )

    def kiosk_button(
        self, key, box, label, fill=None, icon="", fg=None, selected=False
    ):
        """One visual/input rectangle; measured labels never collide with icons."""
        x1, y1, x2, y2 = box
        fill = fill or "#EAF0F8"
        fg = fg or self.TEXT
        pressed = self.pressed == key
        released = getattr(self, "_released_control", None)
        pulse = bool(
            released and released[0] == key and time.monotonic() - released[1] < 0.16
        )
        if pressed:
            fill = self.blend_color(fill, self.TEXT, 0.10)
            x1, y1, x2, y2 = x1 + 1, y1 + 1, x2 - 1, y2 - 1
        elif pulse:
            fill = self.blend_color(fill, "#FFFFFF", 0.12)
        if fg == "white":
            fg = readable_label(fill, self.TEXT)
        offset = 0
        border = self.BLUE if selected else "#B7C6D9"
        self.rounded(
            x1,
            y1,
            x2,
            y2,
            18,
            fill,
            self.BLUE if pressed or pulse else border,
            2 if selected else 1,
        )
        left, right = x1 + 12, x2 - 12
        if icon and x2 - x1 > 220:
            with self.surface(fill):
                self.draw_button_icon(x1 + 25, (y1 + y2) / 2 + offset, icon, fg, 13)
            left += 36
        size = 11 if y2 - y1 >= 56 else 10
        lines = self.wrap_lines(label, right - left, size, "bold")
        if len(lines) > 1:
            lines = [lines[0], self.fit_label(" ".join(lines[1:]), right - left, size)]
            self.text(
                (left + right) / 2,
                (y1 + y2) / 2 + offset,
                "\n".join(lines),
                size,
                fg,
                "bold",
                "center",
                justify="center",
            )
        else:
            self.row_label(
                (left, y1 + offset, right, y2 + offset),
                label,
                size,
                fg,
                anchor="center",
            )
        self.hitboxes[key] = box

    @staticmethod
    def blend_color(first, second, fraction):
        values = [
            round(
                int(first[i : i + 2], 16) * (1 - fraction)
                + int(second[i : i + 2], 16) * fraction
            )
            for i in (1, 3, 5)
        ]
        return "#" + "".join(f"{value:02x}" for value in values)

    def handle_layout_control(self, key):
        if (
            key.startswith("ui_about_")
            and self.modal
            and self.modal.get("kind") == "about"
        ):
            self.modal.update(about_page=key.removeprefix("ui_about_"), layout_page=0)
            return
        if key == "ui_groups" or key.startswith("ui_group_"):
            self.group_control(key)
            return
        if (
            key == "operator_self_fix"
            and self.modal
            and self.modal["kind"] == "confirm_downtime"
        ):

            def saved(result):
                self.modal = None
                self.notify(result or "Operator self-fix recorded", "success", 5)

            self.perform(
                "Recording operator self-fix",
                lambda: self.report_downtime(operator_name=""),
                saved,
            )
        elif (
            key == "operator_details"
            and self.modal
            and self.modal["kind"] == "confirm_downtime"
        ):
            self.modal = {"kind": "operator_setup", "name": ""}
        elif (
            key in {"operator_request", "operator_join"}
            and not self.modal
            and self.operator_resolving()
        ):
            if key == "operator_request":
                self.perform(
                    "Requesting Engineering", self.request_engineering_handover
                )
            elif self.provider.INFO.supports_team_directory:
                self.load_engineers({"kind": "repair"})
            else:
                self.perform(
                    "Recording Engineering arrival", lambda: self.start_repair(None, [])
                )
        elif (
            key == "operator_name"
            and self.modal
            and self.modal["kind"] == "operator_setup"
        ):
            previous = self.modal
            self.open_text_input(
                "operator_name",
                "OPERATOR NAME (OPTIONAL)",
                "Operational record only • not a sign-in or authorization",
                previous.get("name", ""),
                return_modal=previous,
                max_length=120,
            )
        elif (
            key == "operator_start"
            and self.modal
            and self.modal["kind"] == "operator_setup"
            and not self.busy
        ):
            name = self.modal.get("name", "")
            self.modal = None
            self.perform(
                "Recording operator self-fix",
                lambda: self.report_downtime(operator_name=name),
            )
        elif key == "operator_options" and not self.modal and self.operator_resolving():
            self.modal = {"kind": "operator_options"}
        elif (
            key in {"operator_help", "operator_arrived", "operator_done"}
            and self.modal
            and self.modal["kind"] == "operator_options"
            and not self.busy
        ):
            self.modal = None
            if key == "operator_help":
                self.perform(
                    "Requesting Engineering for this incident",
                    self.request_engineering_handover,
                )
            elif key == "operator_arrived":
                if self.provider.INFO.supports_team_directory:
                    self.load_engineers({"kind": "repair"})
                else:
                    self.perform(
                        "Recording Engineering handover",
                        lambda: self.start_repair(None, []),
                    )
            else:
                self.confirm_done()
        elif key == "ui_delivery" and not self.modal and not self.error_panel:
            self.modal = {"kind": "delivery", "item": 0}
        elif (
            key in {"ui_delivery_prev", "ui_delivery_next"}
            and self.modal
            and self.modal["kind"] == "delivery"
        ):
            self.modal["item"] = max(
                0, self.modal.get("item", 0) + (-1 if key.endswith("prev") else 1)
            )
            self.modal["layout_page"] = 0
        elif (
            key in {"ui_delivery_link", "ui_delivery_asset_confirm"}
            and self.modal
            and self.modal["kind"] == "delivery"
        ):
            previous = self.modal
            asset = key == "ui_delivery_asset_confirm"
            self.open_text_input(
                "delivery_asset_confirm" if asset else "delivery_link",
                "VERIFY EXISTING ASSET EVENT" if asset else "LINK EXISTING RECORD",
                "Check the exact asset, state and event time. Enter its event ID or audit reference."
                if asset
                else "Verify this event in the external system, then enter its record ID.",
                return_modal=previous,
                max_length=200,
            )
            self.modal["delivery_id"] = previous.get("selected_id")
        elif (
            key in {"ui_delivery_retry", "ui_delivery_archive", "ui_delivery_dismiss"}
            and self.modal
            and self.modal["kind"] == "delivery"
        ):
            item_id = self.modal.get("selected_id")
            self.modal = None
            self.request_admin_access(key.removeprefix("ui_"))
            if self.modal is None:
                # The signed-update health trial can temporarily block admin
                # actions. Keep that protection without dereferencing no dialog.
                return
            self.modal["delivery_id"] = item_id
            self.modal["prompt"] = (
                "Acknowledge this expired help request; it will not be sent."
                if key.endswith("archive")
                else "Check the external chat first. Dismiss this notice without sending; retain its audit record."
                if key.endswith("dismiss")
                else "Verify the remote system first. Retrying an uncertain write can duplicate it."
            )
        elif (
            key in {"ui_roster_refresh", "ui_roster_skip"}
            and self.modal
            and self.modal["kind"] == "offline_crew"
        ):
            if key.endswith("refresh"):
                self.modal["message"] = self.delivery.request_roster()
            else:
                context = self.modal["context"]
                self.modal = None
                if context["kind"] == "repair":
                    self.perform(
                        "Recording repair start", lambda: self.start_repair(None, [])
                    )
                elif context["kind"] == "planned":
                    self.perform(
                        "Recording planned work",
                        lambda: self.start_planned_work(
                            context["work_label"], context["work_type"], None, []
                        ),
                    )
        elif key == "ui_feedback" and not self.modal and not self.error_panel:
            self.modal = {
                "kind": "notice",
                "message": self.busy_message if self.busy else self.toast_text,
            }
        elif (
            key == "ui_version_actions"
            and self.modal
            and self.modal.get("kind") == "update"
        ):
            self.modal = {"kind": "update_actions", "return_modal": self.modal}
        elif key == "ui_support" and not self.modal and not self.error_panel:
            self.modal = {"kind": "support"}
        elif (
            key.startswith("ui_call_")
            and self.modal
            and self.modal.get("kind") == "support"
        ):
            team = key.removeprefix("ui_call_")
            self.modal = None
            if not self.busy:
                self.call_team(team.title())
        elif key in {"ui_page_prev", "ui_page_next"}:
            owner = self.error_panel or self.modal
            if owner is not None:
                step = -1 if key.endswith("prev") else 1
                owner["layout_page"] = max(
                    0,
                    min(
                        owner.get("layout_pages", 1) - 1,
                        owner.get("layout_page", 0) + step,
                    ),
                )
        elif key in {"ui_keys_prev", "ui_keys_next"} and self.modal:
            step = -1 if key.endswith("prev") else 1
            self.modal["keys_page"] = max(
                0,
                min(
                    self.modal.get("keys_pages", 1) - 1,
                    self.modal.get("keys_page", 0) + step,
                ),
            )

    def draw_kiosk_frame(self):
        view = self.viewport()
        self.hitboxes = {}
        self.canvas.aa_backdrop = self.BG
        if not view.usable:
            self.canvas.create_rectangle(
                0, 0, view.width, view.height, fill=self.BG, outline=""
            )
            self.row_label((8, 4, view.width - 8, 52), "More display space needed", 11)
            self.text(
                12,
                62,
                "Enlarge this window or rotate the display.\nLine state and queued updates are preserved.",
                9,
                self.TEXT,
                width=max(1, view.width - 24),
            )
            return
        phase = time.monotonic() - self.animation_start
        # Dialogs are opaque full-viewport pages. Drawing/animating the entire
        # production map behind them wastes CPU and raster work on a kiosk.
        if self.error_panel or self.modal:
            if self.error_panel:
                self.draw_adaptive_error()
            else:
                self.draw_adaptive_dialog()
            self.draw_touch_feedback()
            return
        self.kiosk_header()
        self.kiosk_feedback()
        width = min(view.width - 24, 1440)
        left = (view.width - width) / 2
        top, bottom = 112, view.height - 12
        if view.paged:
            # Keep scope and workflow visible together, even on short windows.
            # A smaller station diagram is preferable to an extra Actions page.
            line_bottom = bottom - 144 - GAP
            self.kiosk_line((left, top, left + width, line_bottom), phase)
            self.kiosk_actions(
                (left, line_bottom + GAP, left + width, bottom), compact=True
            )
        else:
            support_count = sum(
                item["enabled"] for item in support_buttons(self.config)
            )
            actions_height = (150 + support_count * 56) if view.stacked else 150
            line_bottom = bottom - actions_height - GAP
            self.kiosk_line((left, top, left + width, line_bottom), phase)
            self.kiosk_actions((left, line_bottom + GAP, left + width, bottom))
        self.draw_touch_feedback()

    def draw_touch_feedback(self):
        touch = getattr(self, "touch_feedback", None)
        if touch:
            x, y, started = touch
            age = time.monotonic() - started
            if age < 0.24:
                radius = 5 + 7 * age / 0.24
                self.canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill="",
                    outline=self.blend_color(self.BLUE, self.BG, age / 0.24),
                    width=1.5,
                )
            else:
                self.touch_feedback = None

    def kiosk_header(self):
        w = self.viewport().width
        self.canvas.create_rectangle(0, 0, w, 62, fill=self.CARD, outline="")
        controls, clock, title_right, _feedback_right = header_regions(w)
        boxes = split_row(controls, 3)
        self.draw_update_indicator(boxes[0])
        for key, box in (("about", boxes[1]), ("settings", boxes[2])):
            self.kiosk_button(key, box, "")
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            if key == "about":
                self.canvas.create_oval(
                    cx - 10,
                    cy - 10,
                    cx + 10,
                    cy + 10,
                    fill="",
                    outline=self.BLUE,
                    width=2,
                )
                self.text(cx, cy, "i", 12, self.BLUE, "bold", "center")
            else:
                for dy, dx in ((-8, -5), (0, 6), (8, -2)):
                    self.canvas.create_line(
                        cx - 12, cy + dy, cx + 12, cy + dy, fill=self.TEXT, width=2
                    )
                    self.canvas.create_oval(
                        cx + dx - 3,
                        cy + dy - 3,
                        cx + dx + 3,
                        cy + dy + 3,
                        fill=self.BLUE,
                        outline="",
                    )
        x = 14
        if title_right > 240 and self.draw_brand_mark(30, 31, 34):
            x = 56
        self.row_label((x, 8, title_right, 26), "FLOORTERMINAL", 8, self.BLUE)
        self.row_label((x, 27, title_right, 54), self.config["line_name"], 15)
        self.draw_digital_clock(clock)

    def draw_digital_clock(self, box):
        a, b, c, d = box
        self.rounded(a, b, c, d, 14, "#EDF3FC", "#DCE6F5")
        self.row_label(
            (a + 6, b + 1, c - 6, b + 14), "LOCAL TIME", 7, self.MUTED, anchor="center"
        )
        self.canvas.create_text(
            (a + c) / 2,
            (b + 14 + d) / 2,
            text=datetime.now().astimezone().strftime("%H:%M:%S"),
            font=("Courier", 17, "bold"),
            fill=self.TEXT,
            anchor="center",
        )

    def kiosk_feedback(self):
        w = self.viewport().width
        right = header_regions(w)[3]
        entries = self.state.get("delivery_outbox", [])
        held = sum(item["phase"] == "attention" for item in entries)
        show_delivery = bool(getattr(self, "delivery", None)) and (
            self.provider.connected or self.has_queued_sync()
        )
        feedback_right = right
        if show_delivery:
            size = 136 if right > 440 else 64
            feedback_right = right - size - 8
            label = (
                (
                    f"Review · {held}"
                    if held
                    else f"Delivery · {len(entries)}"
                    if entries
                    else "Delivery"
                )
                if size > 64
                else (
                    f"! {held}" if held else f"↑ {len(entries)}" if entries else "Sync"
                )
            )
            self.kiosk_button(
                "ui_delivery",
                (right - size, 62, right, 106),
                label,
                "#FFF2E0" if held else self.PALE_BLUE,
                fg=self.TEXT if held else self.BLUE,
            )
        syncing = bool(getattr(getattr(self, "delivery", None), "active", None))
        busy = self.busy and getattr(self, "busy_message", "")
        toast = time.monotonic() < self.toast_until
        if busy:
            elapsed = max(
                0,
                int(time.monotonic() - getattr(self, "busy_started", time.monotonic())),
            )
            message = f"{elapsed}s • {self.busy_message}"
            accent = self.BLUE
        elif toast:
            message = self.toast_text
            accent = {"error": self.RED, "success": self.GREEN}.get(
                self.toast_kind, self.BLUE
            )
        elif self.state.get("escalated_at") and self.state["status"] == "DOWN":
            message, accent = self.t("escalated"), self.RED
        else:
            message = (
                (self.provider.identity_name or self.t("connected"))
                if self.provider.connected
                else "Connection not configured • local reporting available"
            )
            accent = self.GREEN if self.provider.connected else self.MUTED
            if self.config.get("reporting_mode") == "local":
                message, accent = (
                    "Standalone reporting • saved on this terminal • no external delivery",
                    self.GREEN,
                )
        if busy or toast:
            self.rounded(12, 64, feedback_right, 104, 12, "#F0F4FA", self.BORDER)
        if busy or syncing:
            self.canvas.create_arc(
                24,
                75,
                42,
                93,
                start=-(time.monotonic() * 180) % 360,
                extent=260,
                style="arc",
                outline=accent,
                width=2,
            )
        else:
            self.canvas.create_oval(28, 80, 36, 88, fill=accent, outline="")
        self.row_label(
            (46, 64, feedback_right - 8, 104), message, 9, self.TEXT, "normal"
        )
        if busy or toast:
            self.hitboxes["ui_feedback"] = (12, 60, feedback_right, 108)

    def kiosk_line(self, box, phase):
        x1, y1, x2, y2 = box
        self.rounded(*box, 18, self.CARD, self.BORDER)
        self.canvas.aa_backdrop = self.CARD
        status = self.state["status"]
        station_states = self.station_statuses()
        grouped = bool(self.config.get("station_groups"))
        color = {
            "RUNNING": self.GREEN,
            "DOWN": self.RED,
            "REPAIRING": self.ORANGE,
            "ENGINEERING": self.PURPLE,
        }[status]
        title = {
            "RUNNING": self.t("production_active"),
            "DOWN": self.t("downtime_reported"),
            "REPAIRING": self.t("repair_in_progress"),
            "ENGINEERING": self.t("line_reserved"),
        }[status]
        if self.operator_resolving():
            title = (
                "OPERATOR SELF-FIX"
                if status == "REPAIRING"
                else "ENGINEERING REQUESTED"
            )
        if grouped:
            stopped = len(station_states)
            title = f"{len(self.config['zones']) - stopped} RUNNING · {stopped} STOPPED"
        narrow = x2 - x1 < 580
        compact = y2 - y1 < (220 if narrow else 164)
        if compact:
            title = (
                f"{len(self.config['zones']) - len(station_states)} RUN · {len(station_states)} STOP"
                if grouped
                else {
                    "RUNNING": "RUNNING",
                    "DOWN": "STOPPED",
                    "REPAIRING": "WORKING",
                    "ENGINEERING": "PLANNED",
                }[status]
            )
        whole_width = 132 if narrow else 190
        face_status = (
            (
                "DOWN"
                if len(station_states) == len(self.config["zones"])
                else "REPAIRING"
                if station_states
                else "RUNNING"
            )
            if grouped
            else status
        )
        self.status_face(x1 + 28, y1 + 28, face_status, phase, 15)
        title_right = x2 - 12 if narrow and not compact else x2 - whole_width - 18
        self.row_label((x1 + 54, y1 + 4, title_right, y1 + 29), title, 10)
        detail = (
            "Select affected stations"
            if status == "RUNNING"
            else "Elapsed " + self.format_duration(self.elapsed_seconds())
        )
        if status != "RUNNING" and self.state.get("response_record_id"):
            record = self.state["response_record_id"]
            detail += (
                " • saved locally"
                if str(record).startswith("local:")
                else f" • Record #{record}"
            )
        if grouped:
            scope = self.state.get("incident_scope")
            detail = (
                (
                    ", ".join(g["name"] for g in scope["groups"])
                    + " · "
                    + status.title()
                    + " · "
                    + self.format_duration(self.elapsed_seconds())
                )
                if scope and status != "RUNNING"
                else "Tap a running station to report • stopped station to respond"
            )
        self.row_label(
            (x1 + 54, y1 + 28, title_right, y1 + 49), detail, 9, self.MUTED, "normal"
        )
        selected = set(self.selected_zones())
        entire = "ENTIRE LINE" in selected
        whole_box = (
            (x1 + 8, y1 + 56, x2 - 8, y1 + 104)
            if narrow and not compact
            else (x2 - whole_width - 8, y1 + 4, x2 - 8, y1 + 52)
        )
        self.kiosk_button(
            "ui_groups" if grouped else "zone_all",
            whole_box,
            "Groups / whole line"
            if grouped
            else "✓  Whole line"
            if entire
            else "Select whole line",
            self.PALE_BLUE if entire else "#EAF0F8",
            selected=entire,
        )
        zones = [
            str(z).strip() for z in self.config.get("zones", []) if str(z).strip()
        ] or ["LINE"]
        station_indexes = {zone: i for i, zone in enumerate(zones)}
        group_by_station = {s: g for g in self.station_groups() for s in g["stations"]}
        if grouped:
            zones = [s for g in self.station_groups() for s in g["stations"]]
        capacity = station_capacity(x2 - x1)
        old_capacity = getattr(self, "_station_capacity", capacity)
        if old_capacity != capacity:
            self.station_page = self.station_page * old_capacity // capacity
        self._station_capacity = capacity
        pages = max(1, math.ceil(len(zones) / capacity))
        self.station_page = max(0, min(self.station_page, pages - 1))
        first = self.station_page * capacity
        visible = zones[first : first + capacity]
        roomy = y2 - y1 >= (270 if narrow else 196)
        group_headers = grouped and y2 - y1 >= (320 if narrow else 240)
        station_top = y1 + (116 if narrow and not compact else 60)
        station_top += 32 if group_headers else 0
        station_bottom = min(station_top + 180, y2 - (94 if roomy else 12))
        station_bottom = max(station_top + 48, station_bottom)
        nav_y = station_top + max(0, (station_bottom - station_top - 48) / 2)
        if self.station_page:
            self.kiosk_button(
                "stations_prev", (x1 + 6, nav_y, x1 + 54, nav_y + 48), "‹"
            )
        if self.station_page < pages - 1:
            self.kiosk_button(
                "stations_next", (x2 - 54, nav_y, x2 - 6, nav_y + 48), "›"
            )
        inset = 62 if pages > 1 else 16
        slots = station_slots(
            visible,
            group_by_station,
            (x1 + inset, station_top, x2 - inset, station_bottom),
            grouped,
        )
        runs = []
        group_indices = {g["id"]: i for i, g in enumerate(self.station_groups())}
        if grouped:
            for zone, slot in zip(visible, slots):
                group = group_by_station[zone]
                if runs and runs[-1][0]["id"] == group["id"]:
                    runs[-1][2] = slot[2]
                    runs[-1][4] += 1
                else:
                    runs.append(
                        [
                            group,
                            slot[0],
                            slot[2],
                            station_states.get(zone, "RUNNING"),
                            1,
                        ]
                    )
            for group, left, right, _status, count in runs:
                number = group_indices[group["id"]]
                accent, tint = GROUP_COLORS[number % len(GROUP_COLORS)]
                top = station_top - (32 if group_headers else 4)
                bottom = y2 - 30 if roomy else station_bottom + 4
                self.rounded(left - 5, top, right + 5, bottom, 12, tint, accent)
                if group_headers:
                    self.row_label(
                        (left + 6, top + 1, right - 6, top + 18),
                        f"{number + 1:02}  {group['name']}",
                        9,
                        accent,
                    )
                    impact = (
                        "Stops whole line"
                        if group["stop_scope"] == "line"
                        else "Independent group"
                    )
                    if count < len(group["stations"]):
                        impact = f"{count}/{len(group['stations'])} shown · {impact}"
                    self.row_label(
                        (left + 6, top + 17, right - 6, top + 30),
                        impact,
                        8,
                        self.MUTED,
                        "normal",
                    )
        for i, (zone, slot) in enumerate(zip(visible, slots)):
            a, b, c, d = slot
            chosen = entire or zone in selected
            fill = self.PALE_BLUE if chosen else "#F4F7FB"
            station_status = station_states.get(zone, "RUNNING")
            station_color = {
                "RUNNING": self.GREEN,
                "DOWN": self.RED,
                "REPAIRING": self.ORANGE,
                "ENGINEERING": self.PURPLE,
            }[station_status]
            if grouped and station_status != "RUNNING" and not chosen:
                fill = "#FFF4EC"
            self.rounded(
                *slot,
                16,
                fill,
                self.BLUE if chosen else station_color if grouped else "#BBCADA",
                2 if chosen or grouped else 1,
            )
            self.hitboxes[f"zone_{station_indexes[zone]}"] = slot
            if grouped and d - b < 90:
                self.row_label(
                    (a + 4, b + 2, c - 4, b + 22),
                    (
                        "RUN"
                        if station_status == "RUNNING"
                        else "STOP"
                        if station_status == "DOWN"
                        else "WORK"
                    )
                    + " · "
                    + (
                        f"G{group_indices[group_by_station[zone]['id']] + 1}"
                        if group_headers
                        else group_by_station[zone]["name"]
                    ),
                    8,
                    station_color,
                    anchor="center",
                )
            if d - b >= 90:
                self.row_label(
                    (a + 6, b + 4, c - 6, b + 24),
                    (
                        f"G{group_indices[group_by_station[zone]['id']] + 1} · {first + i + 1:02}"
                        if group_headers
                        else group_by_station[zone]["name"]
                    )
                    if grouped
                    else f"{first + i + 1:02}  {'✓' if chosen else ''}",
                    8,
                    station_color if grouped else self.BLUE,
                )
                cx, cy = (a + c) / 2, (b + d) / 2 - 6
                self.rounded(cx - 17, cy - 14, cx + 17, cy + 14, 6, "#2A405B")
                self.canvas.create_rectangle(
                    cx - 11,
                    cy - 8,
                    cx + 11,
                    cy + 1,
                    fill=station_color if grouped else "#A9C9F4",
                    outline="",
                )
                if grouped and d - b >= 115:
                    self.row_label(
                        (a + 3, b + 25, c - 3, b + 42),
                        "RUN"
                        if station_status == "RUNNING"
                        else "STOP"
                        if station_status == "DOWN"
                        else "WORK",
                        8,
                        station_color,
                        anchor="center",
                    )
                self.canvas.create_line(
                    cx - 12,
                    cy + 15,
                    cx - 12,
                    cy + 20,
                    cx + 12,
                    cy + 20,
                    cx + 12,
                    cy + 15,
                    fill="#6D839C",
                    width=2,
                )
            self.row_label(
                (a + 4, d - 32 if d - b >= 90 else b + 22 if grouped else b, c - 4, d),
                ("✓ " if chosen and d - b < 90 else "") + zone,
                10,
                self.BLUE if chosen else self.TEXT,
                anchor="center",
            )
        if roomy:
            belt = (x1 + 24, y2 - 62, x2 - 24, y2 - 36)
            if grouped:
                for group, left, right, group_status, _count in runs:
                    group_color = {
                        "RUNNING": self.GREEN,
                        "DOWN": self.RED,
                        "REPAIRING": self.ORANGE,
                        "ENGINEERING": self.PURPLE,
                    }[group_status]
                    self.kiosk_conveyor(
                        (left, belt[1], right, belt[3]),
                        phase,
                        group_status,
                        group_color,
                        group["id"],
                    )
            else:
                self.kiosk_conveyor(belt, phase, status, color)
            summary = (
                "Whole line selected"
                if entire
                else f"{len(selected)} selected • {len(zones)} stations"
            )
            self.row_label(
                (x1 + 16, y2 - 27, x2 - 16, y2 - 4),
                f"{summary}    ·    {self.station_page + 1}/{pages}",
                9,
                self.MUTED,
                "normal",
                "center",
            )
        self.canvas.aa_backdrop = self.BG

    def kiosk_conveyor(self, box, phase, status, color, motion_key="line"):
        x1, y1, x2, y2 = box
        clocks = getattr(self, "_belt_clocks", {})
        radius = max(2, (y2 - y1) / 2 - 2)
        left, right, cy = x1 + radius + 2, x2 - radius - 2, (y1 + y2) / 2
        straight = max(1, right - left)
        circumference = 2 * (straight + math.pi * radius)
        travel = max(1, x2 - x1 - 36)
        motion = advance_motion(
            clocks.get(motion_key),
            phase,
            status == "RUNNING",
            circumference,
            travel,
            radius,
        )
        clocks[motion_key] = motion
        _, advance, parcel, rotation, _running = motion
        # Configuration changes and paging must not retain obsolete group clocks.
        valid = {g["id"] for g in self.station_groups()} | {"line"}
        self._belt_clocks = {
            key: value for key, value in clocks.items() if key in valid
        }
        self.rounded(*box, radius + 2, "#D9E2EB", "#627991", 1.5)
        self.rounded(left, y1 + 7, right, y2 - 7, 4, "#B5C4D3")
        # The return run is visible beneath the supporting idlers; a side-on
        # chassis and feet distinguish this from an abstract progress bar.
        idlers = max(1, min(18, int(straight / 42)))
        for i in range(idlers):
            x = left + (i + 1) * straight / (idlers + 1)
            self.canvas.create_oval(
                x - 4, cy - 4, x + 4, cy + 4, fill="#E6EDF4", outline="#7D92A8"
            )
            self.canvas.create_line(
                x - 3 * math.cos(rotation),
                cy - 3 * math.sin(rotation),
                x + 3 * math.cos(rotation),
                cy + 3 * math.sin(rotation),
                fill="#7D92A8",
                width=1,
            )
        for x in (left + straight * 0.16, left + straight * 0.84):
            self.canvas.create_line(x, y2 + 1, x, y2 + 5, fill="#627991", width=3)
        seam_count = max(6, min(52, int(circumference / 22)))
        for i in range(seam_count):
            x, y, nx, ny = belt_point(
                i * circumference / seam_count + advance, straight, radius
            )
            self.canvas.create_line(
                left + x - nx * 1.5,
                cy + y - ny * 1.5,
                left + x + nx * 1.5,
                cy + y + ny * 1.5,
                fill="#667F98",
                width=1.5,
            )
        for x in (left, right):
            self.canvas.create_oval(
                x - 7, cy - 7, x + 7, cy + 7, fill="#EEF3F8", outline="#70869C"
            )
            for spoke in range(3):
                angle = rotation + spoke * math.tau / 3
                self.canvas.create_line(
                    x,
                    cy,
                    x + 5 * math.cos(angle),
                    cy + 5 * math.sin(angle),
                    fill="#70869C",
                    width=1.5,
                )
            self.canvas.create_oval(
                x - 2, cy - 2, x + 2, cy + 2, fill="#526B84", outline=""
            )
        count = max(1, min(6, int(travel / 130)))
        for i in range(count):
            x = x1 + 18 + ((parcel + i * travel / count) % travel)
            # Consistent carton colour. Status belongs to its outline, not an
            # animated fill; the static fold and side face communicate volume.
            self.rounded(x - 13, y1 - 27, x + 13, y1 - 2, 3, "#E9CF9C", color, 2)
            self.canvas.create_rectangle(
                x + 7, y1 - 24, x + 11, y1 - 4, fill="#D5B880", outline=""
            )
            self.canvas.create_line(
                x - 10, y1 - 20, x + 6, y1 - 20, fill="#FAEACB", width=2
            )
            self.canvas.create_line(
                x - 2, y1 - 25, x - 2, y1 - 4, fill="#FAEACB", width=2
            )

    def kiosk_actions(self, box, compact=False):
        x1, y1, x2, _y2 = box
        status = self.state["status"]
        has_support = any(item["enabled"] for item in support_buttons(self.config))
        selected = bool(self.selected_zones())
        pending = status == "DOWN" and (
            self.state.get("pending_response_record")
            or not self.state.get("response_record_id")
        )
        title, color, icon = {
            "RUNNING": (self.t("report_problem"), self.RED, "!"),
            "DOWN": ("ENGINEER HAS ARRIVED", self.BLUE, ">"),
            "REPAIRING": ("REPAIR COMPLETE", self.GREEN, "OK"),
            "ENGINEERING": ("PLANNED WORK COMPLETE", self.GREEN, "OK"),
        }[status]
        if pending:
            title, color, icon = "SYNC RECORDED DOWNTIME", self.ORANGE, "R"
        elif self.operator_resolving() and status == "REPAIRING":
            title = "SELF-FIX COMPLETE"
        if status == "RUNNING" and not self.provider.INFO.supports_response_records:
            title = "RECORD A PROBLEM LOCALLY"
        can_select_crew = self.provider.INFO.supports_team_directory
        can_plan = self.provider.INFO.supports_response_records or getattr(
            self.provider, "deferred_writes", False
        )
        guide = (
            (
                "1  •  Select affected stations, then report a problem"
                if not selected
                else "2  •  Report a problem or choose planned work"
                if can_plan
                else "2  •  Record the problem on this terminal"
            )
            if status == "RUNNING"
            else (
                "Downtime is saved locally • retry synchronization"
                if pending
                else (
                    "Next • select the arriving crew"
                    if can_select_crew
                    else "Next • confirm Engineering has arrived"
                )
                if status == "DOWN"
                else (
                    "Update the crew as needed • complete only when safe"
                    if can_select_crew
                    else "Complete only when affected stations are verified safe"
                )
            )
        )
        stacked = self.viewport().stacked or compact
        if self.operator_resolving():
            guide = "Same incident • complete safely or hand over to Engineering"
        primary_right = x2 if stacked or not has_support else x1 + (x2 - x1) * 0.62
        self.row_label(
            (x1 + 4, y1, primary_right - 4, y1 + 28), guide, 9, self.TEXT, "normal"
        )
        y1 += 32
        primary_height = 52 if compact else 60
        if compact and has_support:
            primary_right = x2 - 120
        self.kiosk_button(
            "primary",
            (x1, y1, primary_right, y1 + primary_height),
            title,
            color,
            icon,
            self.label_color(color, "white"),
        )
        if compact and has_support:
            self.kiosk_button(
                "ui_support", (x2 - 112, y1, x2, y1 + primary_height), "Support"
            )
            primary_right = x2
        secondary_y = y1 + primary_height + 8
        if status == "RUNNING" and can_plan:
            self.kiosk_button(
                "planned_work",
                (x1, secondary_y, primary_right, secondary_y + 48),
                self.t("engineering_planned_work"),
                "#F0EBFF",
                "P",
                self.PURPLE,
            )
        elif self.operator_resolving():
            requested = bool(
                self.state.get("operator_response", {}).get("requested_at")
            )
            actions = [("operator_join", "ENGINEER ARRIVED")]
            if not requested:
                actions.insert(0, ("operator_request", "REQUEST ENGINEERING"))
            for (key, label), rect in zip(
                actions,
                split_row(
                    (x1, secondary_y, primary_right, secondary_y + 48), len(actions)
                ),
            ):
                self.kiosk_button(key, rect, label, self.PALE_BLUE, fg=self.BLUE)
        elif (
            status in {"REPAIRING", "ENGINEERING"}
            and self.provider.INFO.supports_team_directory
        ):
            self.kiosk_button(
                "crew",
                (x1, secondary_y, primary_right, secondary_y + 48),
                f"UPDATE CREW  •  {len(self.state.get('engineer_ids', []))} ACTIVE",
                "#EAF1FF",
                "+",
                self.BLUE,
            )
        if compact or not has_support:
            return
        if stacked:
            self.kiosk_support(
                [
                    (x1, secondary_y + 56 + i * 56, x2, secondary_y + 104 + i * 56)
                    for i in range(3)
                ]
            )
        else:
            right = primary_right + 12
            self.kiosk_support(
                [(right, y1 - 32 + i * 51, x2, y1 + 16 + i * 51) for i in range(3)]
            )

    def kiosk_support(self, boxes, modal=False):
        buttons = [item for item in support_buttons(self.config) if item["enabled"]]
        for button, box in zip(buttons, boxes):
            label, key = button["label"], button["key"]
            standalone = self.config.get("reporting_mode") == "local"
            if (
                not standalone
                and self.provider.INFO.supports_messaging
                and button["destination"].strip()
            ):
                self.kiosk_button(
                    ("ui_call_" if modal else "") + key,
                    box,
                    "Call " + label,
                    "#EAF0F8",
                    "CALL",
                    self.TEXT,
                )
            else:
                self.rounded(*box, 14, "#F1F4F8", self.BORDER)
                self.row_label(
                    (box[0] + 6, box[1], box[2] - 6, box[3]),
                    label + (" · Standalone" if standalone else " · Not set up"),
                    9,
                    self.MUTED,
                    anchor="center",
                )
