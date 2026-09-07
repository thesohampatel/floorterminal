"""Production workflow: reporting, response, restoration, and synchronization.

This is the local-first core. Every transition is persisted before a network
call is attempted, retries reuse one durable idempotency key, and an
unavailable connector degrades to a queued local record rather than a lost
event. Nothing here draws; it changes state and asks the view to repaint.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime


class WorkflowMixin:
    def selected_zones(self):
        return [str(zone) for zone in self.state.get("issue_zones", []) if str(zone)]

    def zone_summary(self, empty="Not specified"):
        zones = self.selected_zones()
        return ", ".join(zones) if zones else empty

    def has_zone_selection(self):
        return bool(self.selected_zones())

    def primary_action(self):
        if self.state.get("pending_planned_work"):
            if self.provider.connected and self.provider.INFO.supports_response_records:
                self.perform(
                    "Synchronizing planned work start…",
                    self.sync_pending_planned_work,
                )
            else:
                self.notify(
                    "Planned work is safely queued locally • connector unavailable",
                    "error",
                    8,
                )
            return
        status = self.state["status"]
        if status == "RUNNING":
            self.modal = {
                "kind": "confirm_downtime",
                "title": "CONFIRM LINE DOWNTIME",
                "message": "Report the selected station(s) as stopped and alert Engineering?",
            }
            self.logger.log("downtime_confirmation_requested")
        elif status == "DOWN":
            if self.state.get("pending_response_record") or not self.state.get(
                "response_record_id"
            ):
                if not self.provider.connected:
                    self.notify(
                        "Downtime is safely recorded locally • connector unavailable",
                        "error",
                        8,
                    )
                elif not self.provider.INFO.supports_response_records:
                    self.notify(
                        "Downtime is recorded locally • connector has no response-record capability",
                        "error",
                        8,
                    )
                else:
                    self.perform(
                        "Synchronizing recorded downtime…", self.sync_pending_downtime
                    )
                return
            if self.provider.INFO.supports_team_directory:
                self.load_engineers({"kind": "repair"})
            else:
                self.perform(
                    "Starting repair…",
                    lambda: self.change_status("IN_PROGRESS", "REPAIRING"),
                )
        else:
            self.confirm_done()

    def load_engineers(self, context):
        def fetch():
            team_id = self.provider.resolve_name(
                "team", self.config.get("engineering_team_name", "")
            )
            members = self.provider.team_members(team_id)
            normalized = []
            for member in members:
                name = (
                    str(member.get("displayName", "")).strip()
                    or
                    f"{member.get('firstName', '')} {member.get('lastName', '')}"
                ).strip() or f"User #{member['id']}"
                normalized.append(
                    {**member, "id": str(member["id"]), "displayName": name}
                )
            if context["kind"] == "edit":
                known = {str(member["id"]) for member in normalized}
                for user_id, name in zip(
                    self.state.get("engineer_ids", []),
                    self.state.get("engineer_names", []),
                ):
                    if str(user_id) not in known:
                        normalized.append(
                            {
                                "id": str(user_id),
                                "displayName": name,
                                "teamRole": "CURRENT",
                            }
                        )
            if not normalized:
                raise RuntimeError("The Engineering team has no selectable members")
            return {"members": normalized, "team_id": team_id, "context": context}

        self.perform("Loading Engineering team…", fetch, self.show_engineer_picker)

    def show_engineer_picker(self, result):
        selected = (
            {str(value) for value in self.state.get("engineer_ids", [])}
            if result["context"]["kind"] == "edit"
            else set()
        )
        usage = self.state.get("engineer_usage", {})
        members = sorted(
            result["members"],
            key=lambda member: (
                -int(usage.get(str(member["id"]), 0)),
                member["displayName"].casefold(),
            ),
        )
        self.modal = {
            "kind": "engineers",
            "members": members,
            "full_members": members,
            "team_id": result["team_id"],
            "context": result["context"],
            "selected": selected,
            "page": 0,
            "filter": "",
        }
        self.logger.log(
            "engineer_roster_displayed",
            member_count=len(result["members"]),
            context=result["context"]["kind"],
        )

    def confirm_engineers(self):
        selected = self.modal["selected"]
        if not selected:
            self.notify("Select at least one engineer", "error")
            return
        members = self.modal.get("full_members", self.modal["members"])
        chosen = [member for member in members if member["id"] in selected]
        context = self.modal["context"]
        team_id = self.modal["team_id"]
        usage = self.state.setdefault("engineer_usage", {})
        for member in chosen:
            key = str(member["id"])
            usage[key] = int(usage.get(key, 0)) + 1
        self.save_state()
        self.modal = None
        if context["kind"] == "repair":
            self.perform("Starting repair…", lambda: self.start_repair(team_id, chosen))
        elif context["kind"] == "edit":
            self.perform(
                "Updating Engineering crew…",
                lambda: self.update_active_crew(team_id, chosen),
            )
        else:
            self.perform(
                f"Starting {context['work_label'].lower()}",
                lambda: self.start_planned_work(
                    context["work_label"], context["work_type"], team_id, chosen
                ),
            )

    @staticmethod
    def participant_summary(members):
        return ", ".join(member["displayName"] for member in members)

    @staticmethod
    def initial_engineer_history(members, joined_at):
        return [
            {
                "id": str(member["id"]),
                "name": member["displayName"],
                "joined_at": joined_at,
                "left_at": None,
            }
            for member in members
        ]

    def _supports(self, name):
        info = getattr(self.provider, "INFO", None)
        # Small injected test/provider doubles created before capability flags
        # existed retain legacy behavior when they implement the operation.
        if info is None:
            operation = {
                "supports_response_record_status": "set_response_record_status",
                "supports_response_record_assignments": "assign_participants",
            }.get(name, "")
            return bool(operation and hasattr(self.provider, operation))
        return bool(getattr(info, name, False))

    def sync_response_status(self, response_record_id, status):
        """Persist an idempotent lifecycle update before attempting the connector."""
        if not response_record_id or not self._supports("supports_response_record_status"):
            return True
        pending = self.state.get("pending_response_status")
        if not isinstance(pending, dict) or (
            pending.get("record_id"), pending.get("status")
        ) != (response_record_id, status):
            pending = {
                "record_id": response_record_id,
                "status": status,
                "attempts": 0,
                "last_attempt_at": None,
            }
        self.state["pending_response_status"] = pending
        self.save_state()
        if not getattr(self.provider, "connected", True):
            return False
        pending["attempts"] = int(pending.get("attempts", 0)) + 1
        pending["last_attempt_at"] = time.time()
        self.save_state()
        try:
            self.provider.set_response_record_status(response_record_id, status)
        except Exception as exc:
            self.logger.log(
                "response_status_sync_failed",
                "WARNING",
                response_record_id=response_record_id,
                target_status=status,
                attempt=pending["attempts"],
                error=str(exc),
            )
            return False
        self.state["pending_response_status"] = None
        self.save_state()
        return True

    def sync_participant_assignment(self, response_record_id, team_id, user_ids):
        """Persist replacement-assignment intent and retry it without blocking work."""
        if not response_record_id or not self._supports(
            "supports_response_record_assignments"
        ):
            return True
        wanted = list(user_ids)
        pending = self.state.get("pending_participant_assignment")
        if not isinstance(pending, dict) or (
            pending.get("record_id"),
            pending.get("team_id"),
            pending.get("user_ids"),
        ) != (response_record_id, team_id, wanted):
            pending = {
                "record_id": response_record_id,
                "team_id": team_id,
                "user_ids": wanted,
                "attempts": 0,
                "last_attempt_at": None,
            }
        self.state["pending_participant_assignment"] = pending
        self.save_state()
        if not getattr(self.provider, "connected", True):
            return False
        pending["attempts"] = int(pending.get("attempts", 0)) + 1
        pending["last_attempt_at"] = time.time()
        self.save_state()
        try:
            self.provider.assign_participants(response_record_id, team_id, wanted)
        except Exception as exc:
            self.logger.log(
                "participant_assignment_sync_failed",
                "WARNING",
                response_record_id=response_record_id,
                attempt=pending["attempts"],
                error=str(exc),
            )
            return False
        self.state["pending_participant_assignment"] = None
        self.save_state()
        return True

    def try_asset_status(self, status, downtime_type=None, description=""):
        """Attempt asset synchronization while leaving its durable retry state intact."""
        try:
            self.sync_asset_status(status, downtime_type, description)
        except Exception:
            return False
        return not self.state.get("asset_status_sync_pending", False)

    def update_active_crew(self, team_id, members):
        response_record_id = self.state.get("response_record_id")
        if not response_record_id or self.state.get("status") not in (
            "REPAIRING",
            "ENGINEERING",
        ):
            raise RuntimeError("There is no active Engineering work to update")
        old_ids = [str(value) for value in self.state.get("engineer_ids", [])]
        old_names = dict(zip(old_ids, self.state.get("engineer_names", [])))
        new_ids = [str(member["id"]) for member in members]
        new_names = {str(member["id"]): member["displayName"] for member in members}
        added = [value for value in new_ids if value not in old_ids]
        removed = [value for value in old_ids if value not in new_ids]
        if not added and not removed:
            return "Engineering crew is unchanged"

        now = datetime.now().astimezone()
        timestamp = now.isoformat()
        history = list(self.state.get("engineer_history", []))
        if not history:
            joined = datetime.fromtimestamp(
                self.state.get("repair_at")
                or self.state.get("started_at")
                or now.timestamp(),
                tz=now.tzinfo,
            ).isoformat()
            history = [
                {
                    "id": user_id,
                    "name": old_names.get(user_id, f"User #{user_id}"),
                    "joined_at": joined,
                    "left_at": None,
                }
                for user_id in old_ids
            ]
        for user_id in removed:
            for record in reversed(history):
                if str(record.get("id", "")) == user_id and not record.get("left_at"):
                    record["left_at"] = timestamp
                    break
        for user_id in added:
            history.append(
                {
                    "id": user_id,
                    "name": new_names[user_id],
                    "joined_at": timestamp,
                    "left_at": None,
                }
            )
        self.state.update(
            engineer_ids=new_ids,
            engineer_names=[new_names[value] for value in new_ids],
            engineer_history=history,
        )
        self.log_event(f"Crew updated • {self.participant_summary(members)}", self.BLUE)
        self.save_state()
        assignment_ok = self.sync_participant_assignment(
            response_record_id, team_id, new_ids
        )

        added_names = ", ".join(new_names[value] for value in added) or "None"
        removed_names = (
            ", ".join(old_names.get(value, f"User #{value}") for value in removed)
            or "None"
        )
        active_names = self.participant_summary(members)
        message = (
            f"👥 ENGINEERING CREW UPDATED\nAdded: {added_names}\nLeft active work: {removed_names}"
            f"\nCurrently active: {active_names}\nStations: {self.zone_summary()}\nReported failures: {self.failure_summary()}"
            f"\nUpdated: {now:%Y-%m-%d %H:%M:%S %Z}"
        )
        try:
            self.provider.add_response_record_comment(response_record_id, message)
        except Exception as exc:
            self.logger.log(
                "crew_comment_failed",
                "WARNING",
                response_record_id=response_record_id,
                error=str(exc),
            )
        self.send_activity_chats(
            ["engineering_chat_name", "common_activity_chat_name"],
            f"👥 CREW UPDATED • {self.config['line_name']}\nResponse record: #{response_record_id}"
            f"\nAdded: {added_names}\nLeft: {removed_names}\nActive: {active_names}",
        )
        suffix = "" if assignment_ok else " • external assignment pending"
        return f"Active crew updated • {active_names}{suffix}"

    def start_repair(self, team_id, members):
        response_record_id = self.state.get("response_record_id")
        if not response_record_id:
            raise RuntimeError("No active maintenance response record")
        ids = [member["id"] for member in members]
        names = self.participant_summary(members) or "Not yet assigned"
        now = datetime.now().astimezone()
        zone = self.zone_summary()
        failures = self.failure_summary()
        joined_at = now.isoformat()
        self.state.update(
            status="REPAIRING",
            repair_at=time.time(),
            escalated_at=None,
            engineer_ids=ids,
            engineer_names=[m["displayName"] for m in members],
            engineer_history=self.initial_engineer_history(members, joined_at),
        )
        self.log_event(f"Repair started • {names}", self.ORANGE)
        self.save_state()
        assignment_ok = self.sync_participant_assignment(
            response_record_id, team_id, ids
        )
        status_ok = self.sync_response_status(response_record_id, "IN_PROGRESS")
        asset_ok = self.try_asset_status(
            "OFFLINE",
            "UNPLANNED",
            f"Repair active for response record #{response_record_id}; stations: {zone}",
        )
        try:
            self.provider.add_response_record_comment(
                response_record_id,
                f"🔧 WORK STARTED\nEngineers: {names}\nAffected stations: {zone}\nReported failures: {failures}\nStarted: {now:%Y-%m-%d %H:%M:%S %Z}\nSource: {self.project_profile.product_name}",
            )
        except Exception as exc:
            self.logger.log(
                "work_started_comment_failed",
                "WARNING",
                response_record_id=response_record_id,
                error=str(exc),
            )
        self.send_activity_chats(
            ["engineering_chat_name", "common_activity_chat_name"],
            f"🔧 REPAIR IN PROGRESS • {self.config['line_name']}\nResponse record: #{response_record_id}\nStations: {zone}\nReported failures: {failures}\nEngineers: {names}\nStarted: {now:%H:%M:%S %Z}",
        )
        self.play_sound("response")
        suffix = "" if assignment_ok and status_ok and asset_ok else " • external sync pending"
        return f"Repair started by {names}{suffix}"

    def report_downtime(self):
        if not self.has_zone_selection():
            raise RuntimeError("Select the affected station or Entire Line first")
        now = datetime.now().astimezone()
        line = self.config["line_name"]
        title = self.config["downtime_title_template"].format(
            line=line,
            zones=self.zone_summary(),
            time=now.strftime("%H:%M"),
            timestamp=now.isoformat(),
        )
        desc = self.config["downtime_description_template"].format(
            line=line,
            time=now.strftime("%H:%M"),
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
        failures = self.failure_summary()
        report_id = str(uuid.uuid4())
        desc += (
            f"\nStations selected on terminal: {self.zone_summary()}."
            f"\nReported failure types: {failures}."
            f"\nTerminal report ID: {report_id}. This is the remotely enforced idempotency key for synchronization."
        )
        self.state.update(
            status="DOWN",
            response_record_id=None,
            started_at=time.time(),
            repair_at=None,
            pending_response_record={
                "title": title,
                "description": desc,
                "priority": self.config.get("response_record_priority", "HIGH"),
                "created_at": time.time(),
                "report_id": report_id,
                "sync_attempts": 0,
                "last_attempt_at": None,
                "zones_summary": self.zone_summary(),
                "failures_summary": failures,
            },
            pending_sync_error="",
            asset_status_sync_pending=False,
            escalated_at=None,
        )
        self.log_event("Downtime recorded locally • synchronization pending", self.RED)
        self.save_state()
        self.logger.log(
            "downtime_recorded_locally",
            zones=self.selected_zones(),
            failures=failures,
            report_id=report_id,
        )
        self.play_sound("alert")
        if not self.provider.connected or not self.provider.INFO.supports_response_records:
            return "Downtime recorded locally • synchronization pending"
        try:
            return self.sync_pending_downtime()
        except Exception as exc:
            self.state["pending_sync_error"] = str(exc)
            self.save_state()
            self.logger.log("downtime_sync_deferred", "WARNING", error=str(exc))
            return "Downtime recorded locally • external synchronization pending"

    def sync_pending_downtime(self):
        pending = self.state.get("pending_response_record")
        if not pending:
            raise RuntimeError("No locally queued downtime report")
        if not self.provider.connected:
            raise RuntimeError("Connector is unavailable")
        if not self.provider.INFO.supports_response_records:
            raise RuntimeError("Connector does not provide response-record creation")
        team_id = (
            self.provider.resolve_name(
                "team", self.config.get("engineering_team_name", "")
            )
            if self.provider.INFO.supports_team_directory
            else None
        )
        pending["sync_attempts"] = int(pending.get("sync_attempts", 0)) + 1
        pending["last_attempt_at"] = time.time()
        self.save_state()
        self.logger.log(
            "downtime_sync_attempted",
            report_id=pending["report_id"],
            attempt=pending["sync_attempts"],
        )
        if pending["sync_attempts"] > 1:
            self.logger.log(
                "downtime_sync_retry_after_previous_attempt",
                "WARNING",
                report_id=pending["report_id"],
                attempt=pending["sync_attempts"],
            )
        result = self.provider.create_response_record(
            pending["title"],
            pending["description"],
            team_id,
            pending["priority"],
            idempotency_key=pending["report_id"],
        )
        if result.get("id") is None:
            raise RuntimeError(
                f"{self.provider.INFO.display_name} created no usable response-record ID"
            )
        self.state.update(
            response_record_id=result.get("id"),
            pending_response_record=None,
            pending_sync_error="",
            asset_status_sync_pending=bool(
                self.config.get("asset_status_tracking")
                and self.provider.INFO.supports_asset_status
            ),
        )
        self.save_state()
        line = self.config["line_name"]
        zones = pending.get("zones_summary") or self.zone_summary()
        failures = pending.get("failures_summary") or self.failure_summary()
        number = result.get("reference", result.get("id"))
        asset_ok = self.try_asset_status(
            "OFFLINE",
            "UNPLANNED",
            f"Unplanned downtime • RECORD #{number} • {line} • Stations: {zones}",
        )
        self.send_activity_chats(
            ["engineering_chat_name", "common_activity_chat_name"],
            f"🚨 UNPLANNED DOWNTIME CREATED • {line}\nResponse record: #{number}\nStations: {zones}\nReported failures: {failures}\nStatus: OPEN\nEngineering response requested.",
        )
        self.log_event(f"Downtime synchronized • RECORD #{number}", self.RED)
        self.save_state()
        self.logger.log(
            "downtime_sync_completed",
            response_record_id=result.get("id"),
            queued_at=pending.get("created_at"),
            report_id=pending.get("report_id"),
        )
        suffix = "" if asset_ok else " • asset sync pending"
        return f"Response record #{number} created • recorded downtime synchronized{suffix}"

    def sync_pending_tick(self):
        try:
            if self.provider.connected and not self.busy:
                if (
                    self.state.get("pending_response_record")
                    and self.provider.INFO.supports_response_records
                    and self.pending_retry_due(self.state["pending_response_record"])
                ):
                    self.perform(
                        "Synchronizing locally recorded downtime…",
                        self.sync_pending_downtime,
                    )
                elif (
                    self.state.get("pending_planned_work")
                    and self.provider.INFO.supports_response_records
                    and self.pending_retry_due(self.state["pending_planned_work"])
                ):
                    self.perform(
                        "Synchronizing planned work start…",
                        self.sync_pending_planned_work,
                    )
                elif self.state.get("pending_response_status"):
                    pending = self.state["pending_response_status"]
                    if self.pending_retry_due(pending):
                        self.perform(
                            "Synchronizing response status…",
                            lambda: (
                                "External response status synchronized"
                                if self.sync_response_status(
                                    pending["record_id"], pending["status"]
                                )
                                else "External response status remains pending"
                            ),
                        )
                elif self.state.get("pending_participant_assignment"):
                    pending = self.state["pending_participant_assignment"]
                    if self.pending_retry_due(pending):
                        self.perform(
                            "Synchronizing Engineering assignment…",
                            lambda: (
                                "Engineering assignment synchronized"
                                if self.sync_participant_assignment(
                                    pending["record_id"],
                                    pending.get("team_id"),
                                    pending["user_ids"],
                                )
                                else "Engineering assignment remains pending"
                            ),
                        )
                elif self.state.get("asset_status_sync_pending"):
                    context = self.state.get("asset_status_sync_context") or {}
                    if self.pending_retry_due(context):
                        self.perform(
                            "Synchronizing asset status…",
                            lambda: (
                                "Asset status synchronized"
                                if self.try_asset_status(
                                    context.get(
                                        "status",
                                        self.state.get("asset_status_sync_target"),
                                    ),
                                    context.get("downtime_type"),
                                    context.get("description", ""),
                                )
                                else "Asset status remains pending"
                            ),
                        )
        finally:
            self.root.after(60_000, self.sync_pending_tick)

    def deadline_due(self, key, occurred_at, interval_seconds):
        """Use persisted wall time once, then monotonic time within this process."""
        try:
            occurred_at = float(occurred_at)
            interval_seconds = max(0, int(interval_seconds))
        except (TypeError, ValueError):
            return True
        marker = (occurred_at, interval_seconds)
        cached = self.retry_deadlines.get(key)
        if not cached or cached[0] != marker:
            elapsed = min(interval_seconds, max(0.0, time.time() - occurred_at))
            cached = (marker, time.monotonic() + interval_seconds - elapsed)
            self.retry_deadlines[key] = cached
        return time.monotonic() >= cached[1]

    def pending_retry_due(self, pending, interval_seconds=60):
        """Rate-limit unattended retries across restarts and wall-clock changes."""
        last_attempt = pending.get("last_attempt_at")
        if last_attempt is None:
            return True
        key = f"retry:{pending.get('report_id', id(pending))}"
        return self.deadline_due(key, last_attempt, interval_seconds)

    def escalation_tick(self):
        try:
            threshold = int(self.config.get("escalation_minutes", 0)) * 60
            started = self.state.get("started_at")
            if (
                threshold
                and self.state.get("status") == "DOWN"
                and started
                and not self.state.get("escalated_at")
                and self.deadline_due("downtime-escalation", started, threshold)
                and not self.busy
            ):
                self.perform("Escalating unattended downtime…", self.escalate_downtime)
        finally:
            self.root.after(30_000, self.escalation_tick)

    def escalate_downtime(self):
        self.state["escalated_at"] = time.time()
        self.save_state()
        elapsed = self.format_duration(time.time() - self.state["started_at"])
        message = (
            f"⚠️ DOWNTIME ESCALATION • {self.config['line_name']}\n"
            f"Unattended for: {elapsed}\nStations: {self.zone_summary()}\n"
            f"Reported failures: {self.failure_summary()}\nImmediate response requested."
        )
        targets = (
            ["escalation_chat_name"]
            if str(self.config.get("escalation_chat_name", "")).strip()
            else ["engineering_chat_name", "common_activity_chat_name"]
        )
        self.send_activity_chats(targets, message)
        self.log_event("Downtime escalated • response overdue", self.RED)
        self.logger.log(
            "downtime_escalated",
            "WARNING",
            elapsed_seconds=int(time.time() - self.state["started_at"]),
            messaging_available=self.provider.INFO.supports_messaging,
        )
        self.play_sound("alert")
        return "Downtime escalated • supervisor response requested"

    def change_status(self, api_status, local_status):
        response_record_id = self.state.get("response_record_id")
        if not response_record_id:
            raise RuntimeError("No active maintenance response record")
        self.state["status"] = local_status
        if local_status == "REPAIRING":
            self.state["repair_at"] = time.time()
            self.state["escalated_at"] = None
            self.log_event("Engineer started repair", self.ORANGE)
        self.save_state()
        status_ok = self.sync_response_status(response_record_id, api_status)
        if local_status == "REPAIRING":
            self.play_sound("response")
        result = (
            "Repair timer started"
            if local_status == "REPAIRING"
            else "Response record completed"
        )
        return result + ("" if status_ok else " • external status pending")

    def confirm_done(self):
        planned = self.state.get("status") == "ENGINEERING"
        self.modal = {
            "kind": "done",
            "title": "Release line to Production?" if planned else "Resume production?",
            "message": (
                "Confirm Engineering work is complete, all changes are safe, guards are in place, and the line is ready for Production."
                if planned
                else "Confirm the repair is complete, guards are in place, and the line is safe to operate."
            ),
        }

    def open_planned_work(self):
        if self.state.get("pending_planned_work"):
            self.primary_action()
            return
        if self.state.get("status") != "RUNNING":
            self.notify("The line already has active work", "error")
            return
        if not self.has_zone_selection():
            self.notify("Select the work station or Entire Line first", "error")
            self.logger.log("planned_work_blocked_no_zone", "WARNING")
            return
        self.modal = {"kind": "planned"}
        self.logger.log("planned_work_menu_opened")

    def start_planned_work(self, work_label, work_type, team_id, members):
        if not self.has_zone_selection():
            raise RuntimeError("Select the planned-work station or Entire Line first")
        if self.state.get("pending_planned_work"):
            raise RuntimeError("Planned work is already queued for synchronization")
        names = self.participant_summary(members) or "Not yet assigned"
        now = datetime.now().astimezone()
        values = {
            "work_label": work_label,
            "line": self.config["line_name"],
            "zones": self.zone_summary(),
            "time": now.strftime("%H:%M"),
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        title = self.config["planned_work_title_template"].format(**values)
        description = self.config["planned_work_description_template"].format(**values)
        report_id = str(uuid.uuid4())
        description += (
            f"\nSelected line stations: {self.zone_summary()}."
            f"\nReported failure types: {self.failure_summary()}."
            f"\nEngineering participants: {names}."
            f"\nTerminal report ID: {report_id}. This is the remotely enforced idempotency key for synchronization."
        )
        # Persisted before the network call so an ambiguous timeout can be
        # retried with this exact idempotency key instead of minting a new
        # one, the same protection already applied to unplanned downtime.
        self.state["pending_planned_work"] = {
            "work_label": work_label,
            "work_type": work_type,
            "team_id": team_id,
            "participants": [
                {"id": member["id"], "displayName": member["displayName"]}
                for member in members
            ],
            "title": title,
            "description": description,
            "priority": self.config.get("planned_work_priority", "MEDIUM"),
            "report_id": report_id,
            "created_at": time.time(),
            "sync_attempts": 0,
            "last_attempt_at": None,
            "zones_summary": self.zone_summary(),
            "failures_summary": self.failure_summary(),
        }
        self.save_state()
        self.logger.log(
            "planned_work_recorded_locally", work_label=work_label, report_id=report_id
        )
        self.play_sound("planned")
        if not self.provider.connected or not self.provider.INFO.supports_response_records:
            return "Planned work recorded locally • synchronization pending"
        return self.sync_pending_planned_work()

    def sync_pending_planned_work(self):
        pending = self.state.get("pending_planned_work")
        if not pending:
            raise RuntimeError("No locally queued planned work to synchronize")
        if not self.provider.connected:
            raise RuntimeError("Connector is unavailable")
        if not self.provider.INFO.supports_response_records:
            raise RuntimeError("Connector does not provide response-record creation")
        pending["sync_attempts"] = int(pending.get("sync_attempts", 0)) + 1
        pending["last_attempt_at"] = time.time()
        self.save_state()
        self.logger.log(
            "planned_work_sync_attempted",
            report_id=pending["report_id"],
            attempt=pending["sync_attempts"],
        )
        if pending["sync_attempts"] > 1:
            self.logger.log(
                "planned_work_sync_retry_after_previous_attempt",
                "WARNING",
                report_id=pending["report_id"],
                attempt=pending["sync_attempts"],
            )
        members = pending["participants"]
        ids = [member["id"] for member in members]
        names = self.participant_summary(members) or "Not yet assigned"
        line = self.config["line_name"]
        zones = pending.get("zones_summary") or self.zone_summary()
        failures = pending.get("failures_summary") or self.failure_summary()
        result = self.provider.create_response_record(
            pending["title"],
            pending["description"],
            pending["team_id"],
            pending["priority"],
            pending["work_type"],
            ids,
            idempotency_key=pending["report_id"],
        )
        if result.get("id") is None:
            raise RuntimeError(
                f"{self.provider.INFO.display_name} created no usable response-record ID"
            )
        now = datetime.now().astimezone()
        self.state.update(
            status="ENGINEERING",
            response_record_id=result["id"],
            started_at=time.time(),
            repair_at=None,
            work_label=pending["work_label"],
            work_type=pending["work_type"],
            engineer_ids=ids,
            engineer_names=[m["displayName"] for m in members],
            engineer_history=self.initial_engineer_history(members, now.isoformat()),
            pending_planned_work=None,
            asset_status_sync_pending=bool(
                self.config.get("asset_status_tracking")
                and self.provider.INFO.supports_asset_status
            ),
        )
        self.save_state()
        status_ok = self.sync_response_status(result["id"], "IN_PROGRESS")
        asset_ok = self.try_asset_status(
            "OFFLINE",
            "PLANNED",
            f"Planned {pending['work_label']} • RECORD #{result.get('reference', result['id'])} • {line} • Stations: {zones}",
        )
        self.log_event(
            f"{pending['work_label']} RECORD #{result.get('reference', result['id'])}",
            self.PURPLE,
        )
        self.save_state()
        try:
            self.provider.add_response_record_comment(
                result["id"],
                f"🛠️ PLANNED WORK STARTED\nType: {pending['work_label']}\nEngineers: {names}\nStations: {zones}\nReported failures: {failures}\nStarted: {now:%Y-%m-%d %H:%M:%S %Z}\nSource: {self.project_profile.product_name}",
            )
        except Exception as exc:
            self.logger.log(
                "planned_work_comment_failed",
                "WARNING",
                response_record_id=result["id"],
                error=str(exc),
            )
        self.send_activity_chats(
            ["engineering_chat_name", "common_activity_chat_name"],
            f"🛠️ PLANNED • {pending['work_label'].upper()} STARTED • {line}\nResponse record: #{result.get('reference', result['id'])}\nStations: {zones}\nReported failures: {failures}\nEngineers: {names}",
        )
        suffix = "" if status_ok and asset_ok else " • external sync pending"
        return f"{pending['work_label']} started • RECORD #{result.get('reference', result['id'])}{suffix}"

    def retry_planned_work_sync(self):
        """Recover a planned-work start that was interrupted after response-record creation."""
        response_record_id = self.state.get("response_record_id")
        if not response_record_id or self.state.get("status") != "ENGINEERING":
            raise RuntimeError(
                "There is no planned Engineering workflow to synchronize"
            )
        status_ok = self.sync_response_status(response_record_id, "IN_PROGRESS")
        label = self.state.get("work_label") or "Engineering work"
        asset_ok = self.try_asset_status(
            "OFFLINE",
            "PLANNED",
            f"Planned {label} • RECORD #{response_record_id} • {self.config['line_name']} • Stations: {self.zone_summary()}",
        )
        now = datetime.now().astimezone()
        try:
            self.provider.add_response_record_comment(
                response_record_id,
                f"🔄 STATUS SYNCHRONIZED\nAsset set OFFLINE (PLANNED).\nStations: {self.zone_summary()}"
                f"\nRecovered: {now:%Y-%m-%d %H:%M:%S %Z}\nSource: {self.project_profile.product_name}",
            )
        except Exception as exc:
            self.logger.log(
                "planned_sync_comment_failed",
                "WARNING",
                response_record_id=response_record_id,
                error=str(exc),
            )
        self.send_activity_chats(
            ["engineering_chat_name", "common_activity_chat_name"],
            f"🔄 PLANNED WORK SYNCHRONIZED • {self.config['line_name']}\nResponse record: #{response_record_id}"
            f"\nAsset: OFFLINE (PLANNED)\nStations: {self.zone_summary()}",
        )
        self.log_event(f"Planned work synchronized • RECORD #{response_record_id}", self.PURPLE)
        self.save_state()
        return (
            "Planned work synchronized • Asset is OFFLINE"
            if status_ok and asset_ok
            else "Planned work active • external synchronization pending"
        )

    def finish_work(self):
        response_record_id = self.state.get("response_record_id")
        if not response_record_id:
            raise RuntimeError("No active maintenance response record")
        now = datetime.now().astimezone()
        history = list(self.state.get("engineer_history", []))
        all_names = []
        for name in [record.get("name", "") for record in history] + self.state.get(
            "engineer_names", []
        ):
            if name and name not in all_names:
                all_names.append(name)
        names = ", ".join(all_names) or "Not recorded"
        active_names = ", ".join(self.state.get("engineer_names", [])) or "Not recorded"
        timeline = []
        for record in history:
            joined = (
                str(record.get("joined_at", "")).replace("T", " ")[:19] or "Unknown"
            )
            left = (
                str(record.get("left_at", "")).replace("T", " ")[:19]
                if record.get("left_at")
                else "Completion"
            )
            timeline.append(f"- {record.get('name', 'Unknown')}: {joined} to {left}")
        timeline_text = (
            "\n".join(timeline) or f"- {active_names}: participation times not recorded"
        )
        base = self.state.get("started_at") or now.timestamp()
        total = max(0, int(now.timestamp() - base))
        threshold = int(self.config.get("micro_stop_threshold_minutes", 5)) * 60
        event_class = self.classify_downtime(total)
        repair_base = self.state.get("repair_at")
        repair = max(0, int(now.timestamp() - repair_base)) if repair_base else total
        zone = self.zone_summary()
        failures = self.failure_summary()
        selected_stations = self.selected_zones()
        # The physical release is authoritative. Persist it before any optional
        # network update so a connector outage cannot leave the kiosk showing a
        # stopped line after Production has safely resumed.
        self.state["status"] = "RUNNING"
        self.log_event(f"Production resumed • {event_class}", self.GREEN)
        self.logger.log(
            "downtime_classified",
            classification=event_class,
            total_seconds=total,
            threshold_seconds=threshold,
            stations=selected_stations,
        )
        self.state.update(
            response_record_id=None,
            started_at=None,
            repair_at=None,
            work_label=None,
            work_type=None,
            engineer_ids=[],
            engineer_names=[],
            engineer_history=[],
            issue_zones=[],
            failure_selections={},
            failure_notes={},
            escalated_at=None,
        )
        self.save_state()
        asset_ok = self.try_asset_status(
            "ONLINE",
            description=(
                f"Production resumed after RECORD #{response_record_id} • {self.config['line_name']} • "
                f"Stations: {zone} • Total line time: {self.format_duration(total)}"
            ),
        )
        try:
            self.provider.add_response_record_comment(
                response_record_id,
                f"✅ WORK COMPLETED • {event_class}\nAll engineers involved: {names}\nCrew active at completion: {active_names}"
                f"\nParticipation history:\n{timeline_text}\nLine stations: {zone}\nReported failures: {failures}"
                f"\nCompleted: {now:%Y-%m-%d %H:%M:%S %Z}\nTotal line time: {self.format_duration(total)}"
                f"\nActive work time: {self.format_duration(repair)}\nProduction release confirmed on {self.project_profile.product_name}.",
            )
        except Exception as exc:
            self.logger.log(
                "completion_comment_failed",
                "WARNING",
                response_record_id=response_record_id,
                error=str(exc),
            )
        status_ok = self.sync_response_status(response_record_id, "DONE")
        self.send_activity_chats(
            [
                "engineering_chat_name",
                "production_chat_name",
                "common_activity_chat_name",
            ],
            f"✅ LINE RELEASED TO PRODUCTION • {event_class} • {self.config['line_name']}\nResponse record: #{response_record_id}"
            f"\nStations: {zone}\nReported failures: {failures}\nEngineers involved: {names}\nCrew at completion: {active_names}"
            f"\nTotal line time: {self.format_duration(total)}\nResponse record: DONE • Asset: ONLINE",
        )
        self.save_state()
        self.play_sound("restored")
        suffix = "" if status_ok and asset_ok else " • external sync pending"
        return f"Work completed by {names} • Production resumed{suffix}"

    def sync_asset_status(self, status, downtime_type=None, description=""):
        """Synchronize provider asset state and persist enough data for safe retries."""
        if (
            not self.config.get("asset_status_tracking", False)
            or not self.provider.INFO.supports_asset_status
        ):
            return None
        target = str(status).upper()
        if self.state.get("asset_status") == target and not self.state.get(
            "asset_status_sync_pending"
        ):
            return self.state.get("asset_status_id")
        new_event = (
            not self.state.get("asset_status_sync_pending")
            or self.state.get("asset_status_sync_target") != target
        )
        if new_event:
            self.state["asset_status_sync_key"] = str(uuid.uuid4())
            self.state["asset_status_sync_attempts"] = 0
            timestamp = (
                datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            context = {
                "status": target,
                "downtime_type": downtime_type,
                "description": str(description or ""),
                "started_at": timestamp,
                "last_attempt_at": None,
            }
        else:
            context = self.state.get("asset_status_sync_context") or {
                "status": target,
                "downtime_type": downtime_type,
                "description": str(description or ""),
                "started_at": datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "last_attempt_at": None,
            }
        self.state["asset_status_sync_pending"] = True
        self.state["asset_status_sync_target"] = target
        context["last_attempt_at"] = time.time()
        self.state["asset_status_sync_context"] = context
        self.state["asset_status_sync_attempts"] = (
            int(self.state.get("asset_status_sync_attempts", 0)) + 1
        )
        self.save_state()
        try:
            result = self.provider.set_asset_status(
                context["status"],
                context.get("downtime_type"),
                context.get("description"),
                context.get("started_at"),
                idempotency_key=self.state["asset_status_sync_key"],
            )
        except Exception as exc:
            self.logger.log(
                "asset_status_sync_failed",
                "ERROR",
                asset_id=self.config.get("asset_id"),
                target_status=target,
                downtime_type=context.get("downtime_type"),
                error=str(exc),
            )
            self.save_state()
            raise RuntimeError(
                f"{self.provider.INFO.display_name} asset could not be set {target}; workflow is saved and can be retried: {exc}"
            ) from exc
        record = result.get("assetStatus", result) if isinstance(result, dict) else {}
        status_id = record.get("id") if isinstance(record, dict) else None
        self.state.update(
            asset_status=target,
            asset_status_id=status_id,
            asset_status_sync_pending=False,
            asset_status_sync_target=None,
            asset_status_sync_key=None,
            asset_status_sync_attempts=0,
            asset_status_sync_context=None,
        )
        if target == "OFFLINE":
            self.state["asset_offline_status_id"] = status_id
        self.save_state()
        self.logger.log(
            "asset_status_synchronized",
            asset_id=self.config.get("asset_id"),
            asset_status=target,
            downtime_type=context.get("downtime_type"),
            asset_status_id=status_id,
            response_record_id=self.state.get("response_record_id"),
        )
        return status_id

    @staticmethod
    def format_duration(seconds):
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def classify_downtime(self, seconds):
        threshold = int(self.config.get("micro_stop_threshold_minutes", 5)) * 60
        return "MICRO-STOP" if int(seconds) <= threshold else "DOWNTIME EVENT"

    def call_team(self, name):
        def action():
            if not self.provider.connected:
                raise RuntimeError("Configure and enable connector.json")
            if not self.provider.INFO.supports_messaging:
                raise RuntimeError("Messaging is not provided by connector.json")
            chat_name = self.config.get(name.lower() + "_chat_name", name).strip()
            now = datetime.now().astimezone()
            line = self.config["line_name"]
            status = self.state.get("status", "RUNNING")
            condition = {
                "RUNNING": "production is currently running",
                "DOWN": "the line is down",
                "REPAIRING": "a repair is in progress",
                "ENGINEERING": "Engineering has control for planned work",
            }.get(status, "assistance is required")
            message = self.config["help_message_template"].format(
                department=name,
                line=line,
                condition=condition,
                timestamp=now.strftime("%H:%M:%S %Z"),
                zones=self.zone_summary("No station specified"),
            )
            if self.failure_summary(""):
                message += f" Reported failures: {self.failure_summary('')}."
            self.provider.send_message(chat_name, message)
            self.log_event(
                f"{name} support called",
                {
                    "Engineering": self.BLUE,
                    "Quality": self.PURPLE,
                    "Production": self.ORANGE,
                }[name],
            )
            self.save_state()
            self.play_sound("support")
            return f"Message sent to {name} chat"

        self.perform(f"Calling {name}…", action)

    def send_activity_chats(self, config_keys, message):
        """Best-effort lifecycle broadcasts; response-record state remains authoritative."""
        if not self.provider.INFO.supports_messaging:
            return
        sent = set()
        for key in config_keys:
            chat_name = str(self.config.get(key, "")).strip()
            if not chat_name or chat_name.casefold() in sent:
                continue
            try:
                self.provider.send_message(chat_name, message)
                sent.add(chat_name.casefold())
                self.logger.log(
                    "lifecycle_chat_sent",
                    chat=chat_name,
                    message_type=message.split("\n", 1)[0],
                )
            except Exception as exc:
                self.logger.log(
                    "lifecycle_chat_failed", "WARNING", chat=chat_name, error=str(exc)
                )
