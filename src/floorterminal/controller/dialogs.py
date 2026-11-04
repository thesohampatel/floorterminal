"""Operator dialogs, station and failure selection, and protected access.

These are the touchscreen interactions that gather intent before the workflow
acts on it: the on-screen keyboard, the per-station failure picker, whole-line
selection, and the administrator identity and password challenge that guards
Settings, the kiosk controls, and every software-version change.
"""

from __future__ import annotations

import time

from ..core.config import STATION_FAILURE_FALLBACK
from ..core.project_profile import verify_settings_password
from ..core.settings_auth import SettingsAuthError, validate_password


class DialogMixin:
    def open_text_input(
        self,
        purpose,
        title,
        prompt,
        value="",
        *,
        return_modal=None,
        max_length=240,
    ):
        self.modal = {
            "kind": "text_input",
            "purpose": purpose,
            "title": title,
            "prompt": prompt,
            "value": str(value)[:max_length],
            "shift": True,
            "max_length": max_length,
            "return_modal": return_modal,
        }

    def submit_text_input(self):
        purpose = self.modal.get("purpose")
        maximum = int(self.modal.get("max_length", 240))
        value = " ".join(self.modal.get("value", "").strip().split())[:maximum]
        previous = self.modal.get("return_modal")
        if purpose == "operator_name" and previous:
            previous["name"] = value
            self.modal = previous
            return
        if purpose == "group_search" and previous:
            previous["filter"] = value
            self.modal = previous
            return
        if purpose == "failure_search" and previous:
            previous["filter"] = value
            needle = value.casefold()
            previous["matches"] = [
                index
                for index, option in enumerate(previous["options"][:-1])
                if needle in option.casefold()
            ]
            previous["page"] = 0
            self.modal = previous
            return
        if purpose in {"delivery_link", "delivery_asset_confirm"}:
            if not value or value.startswith("local:"):
                self.modal["error"] = (
                    "Enter the verified external event ID or audit reference"
                    if purpose == "delivery_asset_confirm"
                    else "Enter the existing external record ID"
                )
                return
            delivery_id = self.modal.get("delivery_id")
            self.modal = None
            self.request_admin_access(purpose)
            self.modal.update(delivery_id=delivery_id, record_id=value)
            return
        if purpose == "failure_note":
            station = self.modal["station"]

            def save():
                notes = self.state.setdefault("failure_notes", {})
                if value:
                    notes[station] = value
                else:
                    notes.pop(station, None)
                self.save_state()

            def saved(_result):
                self.logger.log(
                    "failure_note_saved", station=station, note_present=bool(value)
                )
                self.modal = None
                self.notify(f"{station} failure details saved", "success")

            self.perform("Saving failure details", save, saved)
            return
        if purpose == "engineer_search" and previous:
            members = previous.get("full_members", previous.get("members", []))
            previous["filter"] = value
            previous["members"] = [
                member
                for member in members
                if value.casefold() in member["displayName"].casefold()
                or value.casefold() in str(member["id"]).casefold()
            ]
            previous["page"] = 0
            self.modal = previous

    def failure_options(self, station):
        overrides = self.config.get("station_failure_types", {})
        if not isinstance(overrides, dict):
            overrides = {}
        configured = overrides.get(station)
        sources = (
            configured if isinstance(configured, list) else STATION_FAILURE_FALLBACK
        )
        options, seen = [], set()
        for value in sources:
            label = str(value).strip()
            if (
                label
                and label.casefold() not in ("other", "others")
                and label.casefold() not in seen
            ):
                options.append(label)
                seen.add(label.casefold())
        return options + ["Others"]

    def open_failure_selection(self, station):
        options = self.failure_options(station)
        allowed = set(options)
        current = self.state.setdefault("failure_selections", {}).get(station, [])
        self.modal = {
            "kind": "failures",
            "station": station,
            "options": options,
            "selected": {value for value in current if value in allowed},
            "page": 0,
            "matches": list(range(len(options) - 1)),
        }
        self.logger.log(
            "failure_picker_opened", station=station, option_count=len(options)
        )

    def save_failure_selection(self):
        station = self.modal["station"]
        ordered = [
            option
            for option in self.modal["options"]
            if option in self.modal["selected"]
        ]

        def save():
            self.apply_failure_choices(station, ordered)
            self.save_state()

        def saved(_result):
            if "Others" in ordered:
                self.open_text_input(
                    "failure_note",
                    f"OTHER FAILURE • {station}",
                    "Optional short description • leave blank to continue",
                    self.state.get("failure_notes", {}).get(station, ""),
                    max_length=240,
                )
                self.modal["station"] = station
            else:
                self.modal = None
            self.notify(
                f"{station}: {len(ordered)} failure type{'s' if len(ordered) != 1 else ''} selected",
                "success",
            )
            self.logger.log(
                "failure_selection_saved", station=station, failure_types=ordered
            )

        self.perform("Saving failure selection", save, saved)

    def apply_failure_choices(self, station, ordered):
        """Apply a captured draft inside the caller's durable transaction."""
        if station not in self.selected_zones():
            raise RuntimeError("This station is no longer selected; choose it again")
        failures = self.state.setdefault("failure_selections", {})
        if ordered:
            failures[station] = list(ordered)
        else:
            failures.pop(station, None)
        if "Others" not in ordered:
            self.state.setdefault("failure_notes", {}).pop(station, None)

    def report_from_failure_picker(self, *, self_fix=False):
        """The labelled report button is the final confirmation, not a wizard."""
        station = self.modal["station"]
        choices = [v for v in self.modal["options"] if v in self.modal["selected"]]

        def report():
            self.apply_failure_choices(station, choices)
            return self.report_downtime(operator_name="" if self_fix else None)

        def saved(result):
            self.modal = None
            self.notify(result or "Stoppage saved on this terminal", "success", 5)

        self.perform(
            "Recording operator self-fix" if self_fix else "Reporting stoppage",
            report,
            saved,
        )

    def remove_failure_station(self):
        station = self.modal["station"]

        def save():
            self.state["issue_zones"] = [
                zone for zone in self.selected_zones() if zone != station
            ]
            self.state.setdefault("failure_selections", {}).pop(station, None)
            self.state.setdefault("failure_notes", {}).pop(station, None)
            self.save_state()

        def saved(_result):
            self.modal = None
            self.notify(f"{station} deselected", "info")
            self.logger.log(
                "issue_station_removed", station=station, zones=self.selected_zones()
            )

        self.perform("Saving station selection", save, saved)

    def failure_summary(self, empty="None specified"):
        failures = self.state.get("failure_selections", {})
        notes = self.state.get("failure_notes", {})
        details = []
        for station in self.selected_zones():
            selected = failures.get(station, [])
            if selected:
                labels = list(selected)
                if "Others" in labels and notes.get(station):
                    labels[labels.index("Others")] = f"Others — {notes[station]}"
                details.append(f"{station}: {', '.join(labels)}")
        return "; ".join(details) if details else empty

    def select_issue_zone(self, zone):
        if zone != "all":
            try:
                station = self.config["zones"][int(zone)]
            except (ValueError, IndexError):
                return
            if self.group_station_touch(station):
                return
        if self.state["status"] != "RUNNING":
            self.notify(
                "Affected stations are fixed for this incident • complete it before changing scope",
                "info",
                6,
            )
            return
        if self.state.get("pending_planned_work"):
            self.notify(
                "Planned work is queued • synchronize or retry it before changing stations",
                "error",
                7,
            )
            return
        selected = self.selected_zones()
        if zone == "all":
            selected = [] if selected == ["ENTIRE LINE"] else ["ENTIRE LINE"]
        else:
            try:
                label = str(self.config.get("zones", [])[int(zone)])
            except (ValueError, IndexError):
                return
            if "ENTIRE LINE" in selected:
                selected = []
            if label not in selected:
                selected.append(label)

        def save():
            if zone == "all":
                self.state["failure_selections"] = {}
                self.state["failure_notes"] = {}
            self.state["issue_zones"] = selected
            self.save_state()

        def saved(_result):
            if zone != "all":
                self.open_failure_selection(label)
            else:
                summary = self.zone_summary("No station selected")
                self.notify(f"Selected: {summary}", "success" if selected else "info")
                if selected:
                    self.primary_action()
            self.logger.log("issue_zones_changed", zones=selected)

        self.perform("Saving station selection", save, saved)

    def request_settings_access(self):
        self.request_admin_access("settings")

    def request_admin_access(self, purpose):
        if self.modal:
            return
        if self.version_trial_active() and purpose not in {
            "software_rollback",
            "exit",
            "fullscreen",
            "windowed",
        }:
            self.notify(
                "Version health check • wait for confirmation before editing settings",
                "info",
                5,
            )
            return
        remaining = self.auth_throttle.remaining()
        labels = {
            "delivery_retry": (
                "REVIEW DELIVERY",
                "Verify the external system before retrying an uncertain write",
            ),
            "delivery_archive": (
                "ACKNOWLEDGE EXPIRED HELP",
                "This request will be recorded as expired, not sent",
            ),
            "delivery_link": (
                "LINK VERIFIED RECORD",
                "Only link the existing record for this exact line event",
            ),
            "delivery_asset_confirm": (
                "CONFIRM VERIFIED ASSET EVENT",
                "Verify the exact asset, state and event time externally; this does not resend the event",
            ),
            "settings": ("SETTINGS LOCKED", "Identify the administrator to continue"),
            "exit": (
                "EXIT PROTECTED",
                "Administrator authorization is required to stop tracking",
            ),
            "windowed": (
                "KIOSK PROTECTED",
                "Administrator authorization is required to reveal the desktop",
            ),
            "fullscreen": (
                "DISPLAY PROTECTED",
                "Administrator authorization is required to change display mode",
            ),
            "software_update": (
                "SOFTWARE UPDATE",
                "Administrator authorization is required to install a new version",
            ),
            "software_rollback": (
                "RESTORE PREVIOUS VERSION",
                "Administrator authorization is required to change the running version",
            ),
        }
        title, prompt = labels.get(purpose, labels["settings"])
        self.modal = {
            "kind": "password",
            "value": "",
            "shift": True,
            "stage": "identity",
            "purpose": purpose,
            "title": title,
            "prompt": prompt,
            "administrator": "",
        }
        if remaining:
            self.modal["error"] = f"Temporarily locked — wait {remaining} seconds"
        self.logger.log("administrator_authorization_requested", purpose=purpose)

    def submit_admin_dialog(self):
        if self.modal.get("stage") in {"new_password", "confirm_password"}:
            self.submit_password_change()
            return
        if self.modal.get("stage") == "identity":
            identity = " ".join(self.modal.get("value", "").strip().split())
            if not 2 <= len(identity) <= 64:
                self.modal["error"] = "Enter your administrator name or ID first"
                return
            self.modal.update(
                administrator=identity,
                stage="password",
                value="",
                error="",
                prompt="Enter the administrator password",
            )
            return
        self.verify_settings_password()

    def request_password_change(self, resume_settings):
        """Use the existing touch keyboard, preserving unsaved Settings edits."""
        self.request_admin_access("password_change")
        self.modal.update(
            stage="password",
            title="CHANGE SETTINGS PASSWORD",
            prompt="Step 1 of 3 • Enter the current password",
            administrator=self.authorized_admin_identity,
            resume_settings=resume_settings,
        )

    def submit_password_change(self):
        if time.monotonic() >= self.modal.get("authorization_expires", 0):
            self.modal.pop("new_password", None)
            self.modal.pop("authorized_hash", None)
            self.modal.update(
                value="",
                stage="password",
                error="Authorization expired; enter the current password again",
                prompt="Step 1 of 3 • Enter the current password",
            )
            return
        supplied = self.modal.get("value", "")
        if self.modal["stage"] == "new_password":
            try:
                validate_password(supplied)
            except SettingsAuthError as exc:
                self.modal.update(value="", error=str(exc))
                return
            self.modal.update(
                new_password=supplied,
                value="",
                error="",
                stage="confirm_password",
                prompt="Step 3 of 3 • Enter the new password again",
            )
            return
        if supplied != self.modal.pop("new_password", ""):
            self.modal.update(
                value="",
                stage="new_password",
                error="Passwords did not match; enter a new password",
                prompt="Step 2 of 3 • New password: 8–128 characters, no spaces",
            )
            return
        try:
            self.settings_credentials.replace(
                supplied, authorized_hash=self.modal["authorized_hash"]
            )
        except SettingsAuthError as exc:
            self.modal.update(
                value="",
                stage="new_password",
                error=str(exc),
                prompt="Step 2 of 3 • New password: 8–128 characters, no spaces",
            )
            return
        resume = self.modal.get("resume_settings")
        self.modal = None
        self.logger.log(
            "settings_password_changed", administrator=self.authorized_admin_identity
        )
        self.notify("Settings password changed for this installation", "success")
        if resume:
            resume(True)

    def verify_settings_password(self):
        remaining = self.auth_throttle.remaining()
        if remaining:
            self.modal["value"] = ""
            self.modal["error"] = f"Temporarily locked — wait {remaining} seconds"
            return
        supplied = self.modal.get("value", "")
        try:
            current_hash = self.settings_credentials.current_hash()
        except SettingsAuthError as exc:
            self.modal.update(value="", error=str(exc))
            self.logger.log("settings_credential_unavailable", "ERROR")
            return
        if verify_settings_password(supplied, current_hash):
            purpose = self.modal.get("purpose", "settings")
            administrator = self.modal.get(
                "administrator", "Unidentified administrator"
            )
            self.auth_throttle.clear()
            if purpose == "password_change":
                self.modal.update(
                    value="",
                    error="",
                    stage="new_password",
                    authorized_hash=current_hash,
                    authorization_expires=time.monotonic() + 300,
                    prompt="Step 2 of 3 • New password: 8–128 characters, no spaces",
                )
                return
            update_selection = self.modal.get("update_selection")
            delivery_id = self.modal.get("delivery_id")
            linked_record_id = self.modal.get("record_id")
            self.modal = None
            self.authorized_admin_identity = administrator
            self.logger.log(
                "administrator_authorized",
                purpose=purpose,
                administrator=administrator,
            )
            if purpose == "settings":
                self.load_settings_directory()
            elif purpose == "exit":
                self._shutdown(administrator)
            elif purpose in {"windowed", "fullscreen"}:
                fullscreen = purpose == "fullscreen"
                self.root.attributes("-fullscreen", fullscreen)
                self.logger.log(
                    "display_mode_changed",
                    administrator=administrator,
                    fullscreen=fullscreen,
                )
            elif purpose == "software_update":
                self.install_software_update(administrator, selection=update_selection)
            elif purpose == "software_rollback":
                self.restore_previous_version(administrator, selection=update_selection)
            elif purpose == "delivery_retry":
                self.delivery.retry_reviewed(delivery_id, administrator)
                self.modal = {"kind": "delivery", "item": 0}
            elif purpose == "delivery_archive":
                self.delivery.archive_expired_notice(delivery_id, administrator)
                self.modal = {"kind": "delivery", "item": 0}
            elif purpose == "delivery_link":
                self.delivery.link_reviewed_record(
                    delivery_id, linked_record_id, administrator
                )
                self.modal = {"kind": "delivery", "item": 0}
            elif purpose == "delivery_asset_confirm":
                self.delivery.confirm_reviewed_asset(
                    delivery_id, linked_record_id, administrator
                )
                self.modal = {"kind": "delivery", "item": 0}
        else:
            delay = self.auth_throttle.register_failure()
            self.modal["value"] = ""
            self.modal["error"] = (
                f"Incorrect password — wait {delay} seconds"
                if delay
                else "Incorrect password — try again"
            )
            self.logger.log(
                "settings_unlock_failed",
                "WARNING",
                attempts=self.auth_throttle.failed_attempts,
                retry_after_seconds=delay,
                administrator=self.modal.get("administrator", ""),
                purpose=self.modal.get("purpose", "settings"),
            )

    def load_settings_directory(self):
        if getattr(self.provider, "deferred_writes", False):
            cache = self.delivery.cached_roster()
            self.open_settings(
                {"teams": [cache["team_name"]] if cache else [], "conversations": []},
                deferred=True,
            )
            return
        if not self.provider.connected or not (
            self.provider.INFO.supports_team_directory
            or self.provider.INFO.supports_messaging
        ):
            self.open_settings({"teams": [], "conversations": []}, deferred=True)
            return

        def fetch():
            try:
                return self.provider.directory()
            except Exception as exc:  # noqa: BLE001 - an unreachable directory must still open Settings
                self.logger.log("directory_fetch_failed", "WARNING", error=str(exc))
                return {"teams": [], "conversations": []}

        self.perform(
            f"Fetching {self.provider.INFO.display_name} directory…",
            fetch,
            lambda directory: self.open_settings(directory, deferred=True),
        )
