"""Viewport-bounded dialogs with fixed action footers and paged long content."""

import math
import string
import time

from .. import __version__
from ..update import trust
from .layout import split_row
from .operational_dialogs import OperationalDialogMixin


class AdaptiveDialogMixin(OperationalDialogMixin):
    def dialog_shell(self, title, detail="", *, footer_rows=1):
        view = self.viewport()
        # Full kiosk page, not a floating desktop dialog. Keep long text readable
        # on wide displays while the background, header and footer own the screen.
        w, h = min(1100, view.width - 8), view.height - 8
        x, y = (view.width - w) / 2, 4
        self.canvas.create_rectangle(
            0, 0, view.width, view.height, fill=self.BG, outline=""
        )
        inner = (x + 16, y + 14, x + w - 16, y + h - 14)
        a, b, c, d = inner
        self.row_label((a, b, c, b + 30), title, 14)
        self.row_label((a, b + 30, c, b + 54), detail, 9, self.MUTED, "normal")
        self.canvas.create_line(a, b + 56, c, b + 56, fill=self.BORDER)
        footer = d - footer_rows * 56 + 8
        return (a, b + 62, c, footer - 8), (a, footer, c, d)

    def dialog_actions(self, box, actions):
        """At most two actions per row on narrow panels, no cramped footer."""
        a, b, c, _d = box
        columns = 2 if c - a < 560 else min(4, len(actions))
        for start in range(0, len(actions), columns):
            row = actions[start : start + columns]
            top = b + (start // columns) * 56
            for (key, label, fill, fg), rect in zip(
                row, split_row((a, top, c, top + 48), len(row))
            ):
                self.kiosk_button(key, rect, label, fill, fg=fg)

    def wrap_lines(self, value, width, size=10, weight="normal"):
        """Pixel-measured wrapping, including unbroken IDs/URLs and Unicode."""
        lines = []
        for paragraph in str(value).split("\n"):
            line = ""
            for word in paragraph.split():
                if line and self.measure_label(line + " " + word, size, weight) > width:
                    lines.append(line)
                    line = ""
                while self.measure_label(word, size, weight) > width and len(word) > 1:
                    low, high = 1, len(word)
                    while low < high:
                        mid = (low + high + 1) // 2
                        if self.measure_label(word[:mid], size, weight) <= width:
                            low = mid
                        else:
                            high = mid - 1
                    lines.append(word[:low])
                    word = word[low:]
                line = (line + " " + word).strip()
            lines.append(line)
        return lines

    def paragraph_page(self, box, paragraphs, owner=None):
        owner = owner if owner is not None else self.modal
        a, b, c, d = box
        lines = []
        for title, value in paragraphs:
            if title:
                lines.append((self.fit_label(title, c - a - 24, 10), True))
            lines.extend((line, False) for line in self.wrap_lines(value, c - a - 24))
            lines.append(("", False))
        available = max(1, int((d - b - 16) / 20))
        pages = (
            1
            if len(lines) <= available
            else math.ceil(len(lines) / max(1, available - 3))
        )
        per_page = available if pages == 1 else max(1, available - 3)
        page = max(0, min(owner.get("layout_page", 0), pages - 1))
        owner["layout_page"], owner["layout_pages"] = page, pages
        self.rounded(a, b, c, d, 14, "#F5F8FC", self.BORDER)
        for index, (value, heading) in enumerate(
            lines[page * per_page : (page + 1) * per_page]
        ):
            self.text(
                a + 12,
                b + 8 + index * 20,
                value,
                10,
                self.BLUE if heading else self.TEXT,
                "bold" if heading else "normal",
            )
        if pages > 1:
            self.kiosk_button("ui_page_prev", (a + 4, d - 50, a + 84, d - 2), "Prev")
            self.row_label(
                (a + 90, d - 50, c - 90, d - 2),
                f"{page + 1} / {pages}",
                9,
                anchor="center",
            )
            self.kiosk_button("ui_page_next", (c - 84, d - 50, c - 4, d - 2), "Next")

    def draw_adaptive_dialog(self):
        kind = self.modal["kind"]
        if kind == "groups":
            self.draw_group_overview()
            return
        if kind == "confirm_downtime":
            return self.report_choice_dialog()
        if kind in {"done", "confirm_done"}:
            return self.completion_dialog()
        if kind == "operator_setup":
            body, footer = self.dialog_shell(
                "OPERATOR SELF-FIX",
                "Minor stoppage • production remains stopped until you confirm release",
                footer_rows=2 if self.viewport().width < 600 else 1,
            )
            self.paragraph_page(
                body,
                [
                    ("STATIONS", self.zone_summary()),
                    (
                        "OPERATOR",
                        self.modal.get("name") or "Name not recorded (optional)",
                    ),
                    (
                        "WORK SAFELY",
                        "Proceed only within your training and site procedures. Never bypass guarding or isolation. If the issue cannot be resolved, request Engineering from the same screen.",
                    ),
                ],
            )
            self.dialog_actions(
                footer,
                [
                    ("operator_name", "Add / edit name", None, self.TEXT),
                    (
                        "operator_start",
                        "Start self-fix",
                        self.BLUE,
                        self.label_color(self.BLUE, "white"),
                    ),
                    ("cancel", "Back", None, self.TEXT),
                ],
            )
            return
        if kind == "operator_options":
            body, footer = self.dialog_shell(
                "SAME INCIDENT • NEXT STEP",
                "The original downtime timer continues through a handover",
                footer_rows=2 if self.viewport().width < 600 else 1,
            )
            response = self.state.get("operator_response") or {}
            self.paragraph_page(
                body,
                [
                    (
                        "STATUS",
                        "Engineering has been requested."
                        if response.get("requested_at")
                        else "Operator is attempting a self-fix.",
                    ),
                    (
                        "CHOOSE THE ACTUAL SITUATION",
                        "Request help if you cannot resolve it. When Engineering arrives, select the crew and continue the normal repair process. If you resolve it before they arrive, confirm self-fix completion.",
                    ),
                ],
            )
            actions = (
                []
                if response.get("requested_at")
                else [
                    ("operator_help", "Request Engineering", self.PALE_BLUE, self.BLUE)
                ]
            )
            actions += [
                ("operator_arrived", "Engineer arrived", self.PALE_BLUE, self.BLUE),
                ("operator_done", "Self-fix complete", None, self.GREEN),
                ("cancel", "Back", None, self.TEXT),
            ]
            self.dialog_actions(footer, actions)
            return
        if kind == "delivery":
            entries = self.state.get("delivery_outbox", [])
            index = min(self.modal.get("item", 0), max(0, len(entries) - 1))
            item = entries[index] if entries else None
            self.modal["selected_id"] = item["id"] if item else None
            can_link = (
                item
                and item["phase"] == "attention"
                and item["method"] == "create_response_record"
            )
            can_confirm_asset = (
                item
                and item["phase"] == "attention"
                and item["method"] == "set_asset_status"
            )
            rows = (
                3
                if (can_link or can_confirm_asset) and self.viewport().width < 620
                else 2
            )
            body, footer = self.dialog_shell(
                "SAVED UPDATES",
                f"{index + 1 if entries else 0} / {len(entries)} • local workflow stays available",
                footer_rows=rows,
            )
            paragraphs = [
                ("DELIVERY", "No external deliveries remain in this journal.")
            ]
            if item:
                paragraphs = [
                    (
                        item["method"].replace("_", " ").upper(),
                        f"State: {item['phase']} • attempts: {item['attempts']}",
                    ),
                    ("DETAILS", self.delivery.explanation(item)),
                    ("IDENTIFIER", item["id"]),
                    (
                        "REVIEW",
                        "After verifying the connected system and correcting configuration, an administrator may authorize a retry. An uncertain non-idempotent request can create duplicates if retried without checking.",
                    ),
                ]
            self.paragraph_page(body, paragraphs)
            actions = [
                ("ui_delivery_prev", "Previous item", None, self.TEXT),
                ("ui_delivery_next", "Next item", None, self.TEXT),
            ]
            if item and item["phase"] == "attention" and item["expires_at"] is None:
                actions.append(
                    ("ui_delivery_retry", "Review / retry", self.PALE_BLUE, self.BLUE)
                )
            elif (
                item
                and item["phase"] == "attention"
                and item["expires_at"] <= time.time()
            ):
                actions.append(
                    (
                        "ui_delivery_archive",
                        "Acknowledge expiry",
                        self.PALE_BLUE,
                        self.BLUE,
                    )
                )
            if can_link:
                actions.append(
                    (
                        "ui_delivery_link",
                        "Link existing record",
                        self.PALE_BLUE,
                        self.BLUE,
                    )
                )
            if can_confirm_asset:
                actions.append(
                    (
                        "ui_delivery_asset_confirm",
                        "Verify existing event",
                        self.PALE_BLUE,
                        self.BLUE,
                    )
                )
            actions.append(("cancel", "Close", None, self.TEXT))
            self.dialog_actions(footer, actions)
            return
        if kind == "offline_crew":
            body, footer = self.dialog_shell(
                "ENGINEERING TEAM",
                "Local response does not depend on directory availability",
                footer_rows=2,
            )
            self.paragraph_page(body, [("TEAM LIST", self.modal["message"])])
            actions = [
                ("ui_roster_refresh", "Refresh list", self.PALE_BLUE, self.BLUE),
                ("cancel", "Back", None, self.TEXT),
            ]
            if self.modal["context"]["kind"] != "edit":
                actions.append(
                    ("ui_roster_skip", "Continue without names", None, self.TEXT)
                )
            self.dialog_actions(footer, actions)
            return
        if kind in {"password", "text_input"}:
            return self.keyboard_dialog()
        if kind == "failures":
            return self.failures_dialog()
        if kind == "engineers":
            return self.crew_dialog()
        if kind == "notice":
            body, footer = self.dialog_shell(
                "OPERATOR MESSAGE",
                "Reporting and synchronization continue in the background",
            )
            self.paragraph_page(body, [("DETAILS", self.modal.get("message", ""))])
            self.dialog_actions(footer, [("cancel", "Close", None, self.TEXT)])
            return
        if kind == "about":
            profile = self.project_profile
            body, footer = self.dialog_shell(
                profile.product_name, f"Version {__version__} • Software information"
            )
            self.paragraph_page(
                body,
                [
                    (
                        "CREATED & MAINTAINED BY",
                        profile.maintainer_name + "\n" + profile.support_contact,
                    ),
                    ("ABOUT", profile.product_tagline),
                    (
                        "MIT OPEN-SOURCE LICENSE",
                        "You may use, copy, modify, merge, publish, distribute, sublicense and sell this software. Retain the copyright and MIT license notice in copies or substantial portions.",
                    ),
                    (
                        "NOT INCLUDED",
                        "External-service access, credentials, deployment data, trademarks and third-party rights.",
                    ),
                    (
                        "DEPLOYMENT RESPONSIBILITY • PROVIDED AS-IS",
                        "Trained people remain responsible for guarding, E-stops, lockout/tagout and permits. This console is not a machine safety controller. Verify connectors, credentials, networks, updates and backups. Protect logs, personal data and retention according to your site's requirements.",
                    ),
                    ("COPYRIGHT", profile.copyright_notice),
                ],
            )
            self.dialog_actions(footer, [("cancel", self.t("close"), None, self.TEXT)])
            return
        if kind == "update":
            return self.adaptive_update_dialog()
        if kind == "update_actions":
            status = self.update_status()
            body, footer = self.dialog_shell(
                "INSTALL OR RESTORE", "Administrator authorization is required"
            )
            a, b, c, _d = body
            if status.can_install:
                self.kiosk_button(
                    "update_install",
                    (a, b, c, b + 48),
                    "Install " + status.staged.version,
                    "#FFF3E5",
                    fg=self.TEXT,
                )
            if status.can_rollback:
                self.kiosk_button(
                    "update_rollback",
                    (a, b + 56, c, b + 104),
                    "Restore " + status.rollback_version,
                    "#FDECEE",
                    fg=self.RED,
                )
            self.dialog_actions(
                footer, [("cancel", "Back to updates", None, self.TEXT)]
            )
            return
        if kind == "support":
            body, footer = self.dialog_shell(
                "CALL SUPPORT", "Messages only • no new response record"
            )
            a, b, c, _d = body
            self.kiosk_support(
                [(a, b + i * 56, c, b + i * 56 + 48) for i in range(3)], modal=True
            )
            self.dialog_actions(footer, [("cancel", self.t("cancel"), None, self.TEXT)])
            return
        if kind == "planned":
            impact = "Choose the work type • Production will be paused"
            if self.config.get("station_groups") and self.has_zone_selection():
                scope = self.preview_scope()
                impact = (
                    f"Whole-line stop • all {len(scope['affected_stations'])} stations"
                    if scope["impact"] == "line"
                    else f"Stops {len(scope['groups'])} group(s), {len(scope['affected_stations'])} stations • other groups keep running"
                )
            body, footer = self.dialog_shell(
                "ENGINEERING PLANNED WORK",
                impact,
            )
            a, b, c, _d = body
            self.kiosk_button(
                "planned_preventive",
                (a, b, c, b + 56),
                "PREVENTIVE MAINTENANCE",
                "#EAF1FF",
                "P",
                self.BLUE,
            )
            self.kiosk_button(
                "planned_change",
                (a, b + 68, c, b + 124),
                "MODIFICATION / CHANGE",
                "#F0EBFF",
                "P",
                self.PURPLE,
            )
            self.dialog_actions(footer, [("cancel", self.t("cancel"), None, self.TEXT)])
            return
        body, footer = self.dialog_shell(
            self.modal.get("title", "CONFIRM ACTION"),
            "Check the line before confirming",
        )
        paragraphs = [("PLEASE CONFIRM", self.modal.get("message", ""))]
        if self.modal.get("note"):
            paragraphs.append(("RECORDED RELEASE TIME", self.modal["note"]))
        self.paragraph_page(body, paragraphs)
        downtime = kind == "confirm_downtime"
        color = self.RED if downtime else self.GREEN
        self.dialog_actions(
            footer,
            [
                ("cancel", self.t("not_yet"), None, self.TEXT),
                (
                    "confirm",
                    self.t("yes_line_down") if downtime else self.t("yes_confirm"),
                    color,
                    self.label_color(color, "white"),
                ),
            ],
        )

    def keyboard_dialog(self):
        modal = self.modal
        body, footer = self.dialog_shell(
            modal.get("title", "ADMINISTRATOR AUTHORIZATION"),
            modal.get("prompt", "Enter administrator name or ID"),
            footer_rows=2,
        )
        a, b, c, d = body
        password = modal["kind"] == "password" and modal.get("stage") != "identity"
        value = modal.get("value", "")
        shown = "●" * min(24, len(value)) if password else value
        self.rounded(a, b, c, b + 40, 12, "#EFF4FA", self.BORDER)
        self.row_label((a + 10, b, c - 10, b + 40), shown or "—", 12, anchor="center")
        b += 48
        columns = max(1, min(10, int((c - a + 6) // 50)))
        rows = max(1, int((d - b) // 50))
        characters = (
            "1234567890QWERTYUIOPASDFGHJKLZXCVBNM@"
            + string.punctuation.replace("@", "")
        )
        capacity = columns * rows
        pages = math.ceil(len(characters) / capacity)
        if pages > 1:
            rows = max(1, int((d - b - 52) // 50))
            capacity = columns * rows
            pages = math.ceil(len(characters) / capacity)
        page = min(modal.get("keys_page", 0), pages - 1)
        modal["keys_page"], modal["keys_pages"] = page, pages
        chars = characters[page * capacity : (page + 1) * capacity]
        for row in range(rows):
            group = chars[row * columns : (row + 1) * columns]
            if not group:
                break
            for char, box in zip(
                group, split_row((a, b + row * 50, c, b + row * 50 + 44), columns, 6)
            ):
                display = char if modal.get("shift", True) else char.lower()
                self.kiosk_button(f"pwd_{ord(display)}", box, display)
        if pages > 1:
            for key, label, box in zip(
                ("ui_keys_prev", "ui_keys_next"),
                ("‹ Keys", "More keys ›"),
                split_row((a, d - 48, c, d), 2),
            ):
                self.kiosk_button(key, box, label)
        # Typing actions have their own row; submit/cancel always remain visible.
        x1, y1, x2, y2 = footer
        for key, label, box in zip(
            ("pwd_shift", "pwd_space", "pwd_back"),
            ("Shift", "Space", "Back"),
            split_row((x1, y1, x2, y1 + 48), 3),
        ):
            self.kiosk_button(key, box, label)
        self.dialog_actions(
            (x1, y1 + 56, x2, y2),
            [
                ("cancel", self.t("cancel"), None, self.TEXT),
                (
                    "pwd_enter",
                    "Save password"
                    if modal.get("stage") == "confirm_password"
                    else "Continue",
                    self.GREEN,
                    self.label_color(self.GREEN, "white"),
                ),
            ],
        )
        if modal.get("error"):
            # Replace the header hint, never draw over the entered value or keys.
            top = body[1] - 32
            self.rounded(a, top, c, top + 24, 4, "#FFF0F1")
            self.row_label(
                (a + 6, top, c - 6, top + 24),
                modal["error"],
                9,
                self.RED,
            )

    def draw_adaptive_error(self):
        panel = self.error_panel
        body, footer = self.dialog_shell(
            panel.get("title", "Operation did not finish"),
            panel.get("operation", "") + " • " + panel.get("time", ""),
        )
        self.paragraph_page(
            body,
            [
                ("WHAT HAPPENED", panel.get("message", "")),
                ("SAVED LINE STATUS", self.state.get("status", "UNKNOWN")),
                (
                    "NEXT STEP",
                    "The screen shows the saved state. Check the reason above, then try again. If this repeats, note the time and contact support.",
                ),
            ],
            owner=panel,
        )
        self.dialog_actions(
            footer,
            [
                (
                    "error_dismiss",
                    "OK, continue",
                    self.BLUE,
                    self.label_color(self.BLUE, "white"),
                )
            ],
        )

    def adaptive_update_dialog(self):
        status = self.update_status()
        extra = status.can_install and status.can_rollback and not self.busy
        compact_actions = extra and self.viewport().width < 616
        rows = 2
        detail = status.headline
        if self.busy:
            elapsed = max(
                0,
                int(time.monotonic() - getattr(self, "busy_started", time.monotonic())),
            )
            detail = (
                f"Working • {elapsed}s • {getattr(self, 'busy_message', 'Please wait')}"
            )
        body, footer = self.dialog_shell("SOFTWARE UPDATE", detail, footer_rows=rows)
        a, b, c, d = body
        pages = ("status", "version", "changes", "activity")
        page = self.modal.get("page", "status")
        for key, box in zip(pages, split_row((a, b, c, b + 48), 4)):
            self.kiosk_button(
                "update_tab_" + key, box, key.title(), selected=page == key
            )
        text_box = (a, b + 56, c, d)
        paragraphs = []
        if page == "status":
            paragraphs = [
                ("STATUS", status.detail),
                ("INSTALLED", status.installed_version),
                ("LATEST PUBLISHED", status.latest_version or "Not confirmed"),
                (
                    "OFFLINE UPDATES",
                    "Download the signed update package from "
                    + trust.RELEASES_URL
                    + f". Label the drive {trust.UPDATE_VOLUME_LABELS[0]}, put the package in {trust.UPDATE_PACKAGE_DIRNAME}, insert the drive, then choose Scan drive. Installation requires administrator authorization. Reporting continues independently of update availability.",
                ),
                ("SUPPORT", trust.MAINTAINER_NAME + " • " + trust.MAINTAINER_EMAIL),
            ]
        elif page == "version":
            entry = self._installed_catalog_entry()
            paragraphs = [
                ("THIS VERSION", entry.summary if entry else status.installed_version),
                ("CAPABILITIES", "\n".join(status.installed_features)),
            ]
        elif page == "changes":
            staged, channel = status.staged, status.channel
            candidate = staged or (channel if status.update_available else None)
            if candidate:
                highlights = staged.highlights if staged else channel.highlights()
                paragraphs = [
                    (candidate.release_title, candidate.release_summary),
                    (
                        "CHANGES",
                        "\n".join(f"{kind}: {value}" for kind, value in highlights),
                    ),
                ]
                if staged:
                    paragraphs.append(
                        (
                            "VERIFIED",
                            "Signing key: "
                            + staged.signing_key_id
                            + "\nSHA256: "
                            + staged.artifact_sha256,
                        )
                    )
            else:
                paragraphs = [
                    ("NO NEW VERSION CONFIRMED", self.t("update_none_known_detail"))
                ]
        else:
            paragraphs = [
                (
                    str(entry.get("action", "Update")),
                    " • ".join(
                        str(entry.get(key, ""))
                        for key in (
                            "from_version",
                            "to_version",
                            "authorized_by",
                            "at_utc",
                            "outcome",
                        )
                    ),
                )
                for entry in reversed(status.history)
            ] or [("ACTIVITY", self.t("update_no_activity_detail"))]
        if self.busy:
            paragraphs.insert(
                0,
                (
                    "WORKING",
                    getattr(self, "busy_message", "Working…")
                    + f" • {max(0, int(time.monotonic() - getattr(self, 'busy_started', time.monotonic())))}s",
                ),
            )
        self.paragraph_page(text_box, paragraphs)
        actions = [("cancel", self.t("close_panel"), None, self.TEXT)]
        if not self.busy:
            actions.extend(
                [
                    ("update_check", "Check again", None, self.TEXT),
                    ("update_scan", "Scan drive", None, self.TEXT),
                ]
            )
            if status.can_install:
                actions.append(
                    (
                        "update_install",
                        "Install " + status.staged.version,
                        "#FFF3E5",
                        self.ORANGE,
                    )
                )
            if status.can_rollback:
                actions.append(
                    (
                        "update_rollback",
                        "Restore " + status.rollback_version,
                        "#FDECEE",
                        self.RED,
                    )
                )
        if compact_actions:
            actions = actions[:3] + [
                ("ui_version_actions", "Install / restore", "#FFF3E5", self.TEXT)
            ]
        self.dialog_actions(footer, actions)
