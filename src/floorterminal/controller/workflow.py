"""Production workflow: reporting, response, restoration, and synchronization.

This is the local-first core. Every transition is persisted before a network
call is attempted, retries reuse one durable idempotency key, and an
unavailable connector degrades to a queued local record rather than a lost
event. Nothing here draws; it changes state and asks the view to repaint.

External side effects that follow a committed transition — response-record
comments and lifecycle status, and chat notifications — are written to durable
queues in the same save as the transition, then attempted immediately. A
failed, rate-limited, or interrupted attempt therefore stays queued and is
retried automatically, including after a restart.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from ..storage.state import (
    MAX_QUEUED_MESSAGES,
    MAX_QUEUED_RECORD_UPDATES,
    MAX_QUEUED_TEXT_LENGTH,
    StateSaveError,
)

#: Automatic synchronization cadence. Individual items keep their own retry
#: intervals, so a short tick only shortens the wait after a rate-limit window.
SYNC_TICK_MS = 30_000
RETRY_BASE_SECONDS = 60
RETRY_MAX_SECONDS = 15 * 60
#: A lifecycle notification older than this is no longer operational news.
LIFECYCLE_MESSAGE_TTL_SECONDS = 12 * 60 * 60
#: A request for help that could not be sent promptly must not arrive much later.
SUPPORT_MESSAGE_TTL_SECONDS = 15 * 60
RECORD_UPDATE_TTL_SECONDS = 72 * 60 * 60
#: Requests rejected as invalid, unauthorized, or not found are retried a few
#: times, which covers a Settings correction, and then abandoned with an audit entry.
PERMANENT_FAILURE_ATTEMPTS = 3
PERMANENT_HTTP_STATUSES = {400, 401, 403, 404, 410, 422}


def _bounded_text(value, limit=MAX_QUEUED_TEXT_LENGTH):
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _short_error(exc, limit=240):
    text = " ".join(str(exc).split()) or exc.__class__.__name__
    return text if len(text) <= limit else text[: limit - 1] + "…"


def failure_kind(exc):
    """Classify a connector failure as ``rate_limited``, ``transient`` or ``permanent``."""
    code = str(getattr(exc, "code", "") or "")
    status = getattr(exc, "status", None)
    if code == "RATE_LIMITED" or status == 429:
        return "rate_limited"
    if isinstance(status, int) and status in PERMANENT_HTTP_STATUSES:
        return "permanent"
    if code in {"UNAVAILABLE", "SERVER", "INVALID_RESPONSE", "UNKNOWN"} or (
        isinstance(status, int) and status >= 500
    ):
        return "transient"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "transient"
    if code:
        return "permanent" if code in {"AUTHENTICATION", "PERMISSION"} else "transient"
    # A missing chat, an unresolvable name, or an invalid mapping is a local
    # configuration problem: retrying immediately cannot succeed.
    return "permanent"


class WorkflowMixin:
    def selected_zones(self):
        return [str(zone) for zone in self.state.get("issue_zones", []) if str(zone)]

    def zone_summary(self, empty="Not specified"):
        zones = self.selected_zones()
        return ", ".join(zones) if zones else empty

    def has_zone_selection(self):
        return bool(self.selected_zones())

    def failure_reasons(self, empty="Not specified at the terminal"):
        """Selected failure types per station, without free-text notes."""
        failures = self.state.get("failure_selections", {}) or {}
        details = [
            f"{station}: {', '.join(failures[station])}"
            for station in self.selected_zones()
            if failures.get(station)
        ]
        return "; ".join(details) if details else empty

    def operator_notes(self):
        """The operator's optional Others descriptions, per station."""
        failures = self.state.get("failure_selections", {}) or {}
        notes = self.state.get("failure_notes", {}) or {}
        return "; ".join(
            f"{station}: {notes[station]}"
            for station in self.selected_zones()
            if notes.get(station) and "Others" in failures.get(station, [])
        )

    @staticmethod
    def asset_status_note(heading, zones, reasons, notes="", record=None, extra=()):
        """Plain-language note stored with an asset status change.

        It says where and why — affected stations, the reported failure types,
        and the operator's own words — so the note is useful without opening the
        response record. Times are omitted: the status carries its own start time.
        """
        lines = [heading, f"Affected stations: {zones or 'Not specified'}"]
        lines.append(f"Reason: {reasons or 'Not specified at the terminal'}")
        if notes:
            lines.append(f"Operator note: {notes}")
        lines.extend(line for line in extra if line)
        if record is not None:
            lines.append(f"Response record: #{record}")
        return _bounded_text("\n".join(lines), 1000)

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
                "supports_response_record_comments": "add_response_record_comment",
                "supports_messaging": "send_message",
                "supports_asset_status": "set_asset_status",
            }.get(name, "")
            return bool(operation and hasattr(self.provider, operation))
        return bool(getattr(info, name, False))

    def asset_tracking_enabled(self):
        return bool(self.config.get("asset_status_tracking", False)) and self._supports(
            "supports_asset_status"
        )

    # ------------------------------------------------------------------
    # Durable queues for work that follows a committed transition
    # ------------------------------------------------------------------

    def _new_queue_entry(self, ttl_seconds):
        now = time.time()
        return {
            "id": str(uuid.uuid4()),
            "created_at": now,
            "expires_at": now + ttl_seconds,
            "attempts": 0,
            "last_attempt_at": None,
            "retry_after_seconds": None,
            "last_error": "",
        }

    def _queue_entry_due(self, entry):
        last_attempt = entry.get("last_attempt_at")
        if last_attempt is None:
            return True
        interval = entry.get("retry_after_seconds") or RETRY_BASE_SECONDS
        return self.deadline_due(f"outbox:{entry.get('id')}", last_attempt, interval)

    @staticmethod
    def _queue_entry_expired(entry):
        expires_at = entry.get("expires_at")
        return expires_at is not None and time.time() > float(expires_at)

    def _schedule_retry(self, entry, exc):
        """Record a failed attempt; returns the failure kind and whether to give up."""
        kind = failure_kind(exc)
        attempts = int(entry.get("attempts", 1))
        if kind == "rate_limited":
            delay = max(5, int(getattr(exc, "retry_after", None) or RETRY_BASE_SECONDS) + 1)
        else:
            delay = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2 ** max(0, attempts - 1))
        entry["retry_after_seconds"] = delay
        entry["last_error"] = _short_error(exc)
        give_up = kind == "permanent" and attempts >= PERMANENT_FAILURE_ATTEMPTS
        return kind, give_up, delay

    def _trim_queue(self, queue, limit, event):
        while len(queue) > limit:
            # Comments and notifications are dropped before lifecycle status,
            # which is what closes the response record.
            victim = next(
                (item for item in queue if item.get("action") != "status"), queue[0]
            )
            self._mark_completion_outcome(victim, "failed")
            queue.remove(victim)
            self.logger.log(
                event,
                "ERROR",
                queued_at=victim.get("created_at"),
                record_id=victim.get("record_id"),
                chat=victim.get("chat"),
                reason=f"queue limit of {limit} reached",
            )

    def queued_sync_count(self):
        state = self.state
        return sum(
            (
                bool(state.get("pending_response_record")),
                bool(state.get("pending_planned_work")),
                bool(state.get("pending_response_status")),
                bool(state.get("pending_participant_assignment")),
                bool(state.get("asset_status_sync_pending")),
                len(state.get("pending_record_updates") or []),
                len(state.get("pending_messages") or []),
            )
        )

    def has_queued_sync(self):
        return self.queued_sync_count() > 0

    def queue_record_update(self, record_id, action, *, status=None, content=None):
        """Queue one response-record comment or status change without network use."""
        capability = (
            "supports_response_record_status"
            if action == "status"
            else "supports_response_record_comments"
        )
        if not record_id or not self._supports(capability):
            return None
        queue = self.state.setdefault("pending_record_updates", [])
        if action == "status":
            # The newest lifecycle status for a record supersedes an older one.
            queue[:] = [
                item
                for item in queue
                if not (item.get("action") == "status" and item.get("record_id") == record_id)
            ]
        entry = {
            **self._new_queue_entry(RECORD_UPDATE_TTL_SECONDS),
            "record_id": record_id,
            "action": action,
        }
        if action == "status":
            entry["status"] = status
        else:
            entry["content"] = _bounded_text(content)
        queue.append(entry)
        self._trim_queue(queue, MAX_QUEUED_RECORD_UPDATES, "record_update_dropped")
        return entry

    def _mark_completion_outcome(self, update, outcome):
        """Keep delivery evidence with queued completion messages, across restarts."""
        if update.get("action") != "status" or update.get("status") != "DONE":
            return
        for message in self.state.get("pending_messages") or []:
            if message.get("status_record_id") == update.get("record_id"):
                message["record_status_outcome"] = outcome

    def flush_record_updates(self, force=False):
        """Deliver queued record updates in order; True when none remain.

        The first rate-limited or transient failure ends the pass, because later
        requests would fail the same way and each attempt spends connector budget.
        """
        queue = self.state.get("pending_record_updates") or []
        if not queue:
            return True
        if not getattr(self.provider, "connected", True):
            return False
        for entry in list(queue):
            if self._queue_entry_expired(entry):
                self._mark_completion_outcome(entry, "failed")
                queue.remove(entry)
                self.logger.log(
                    "record_update_expired",
                    "CRITICAL",
                    record_id=entry.get("record_id"),
                    action=entry.get("action"),
                    target_status=entry.get("status"),
                    attempts=entry.get("attempts"),
                    last_error=entry.get("last_error", ""),
                )
                self.save_state()
                continue
            if not force and not self._queue_entry_due(entry):
                continue
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            entry["last_attempt_at"] = time.time()
            self.save_state()
            try:
                if entry["action"] == "status":
                    self.provider.set_response_record_status(
                        entry["record_id"], entry["status"]
                    )
                else:
                    self.provider.add_response_record_comment(
                        entry["record_id"], entry["content"]
                    )
            except Exception as exc:
                kind, give_up, delay = self._schedule_retry(entry, exc)
                self.logger.log(
                    "record_update_failed",
                    "WARNING",
                    record_id=entry["record_id"],
                    action=entry["action"],
                    target_status=entry.get("status"),
                    attempt=entry["attempts"],
                    failure=kind,
                    retry_in_seconds=None if give_up else delay,
                    error=entry["last_error"],
                )
                if give_up:
                    self._mark_completion_outcome(entry, "failed")
                    queue.remove(entry)
                    self.logger.log(
                        "record_update_abandoned",
                        "ERROR",
                        record_id=entry["record_id"],
                        action=entry["action"],
                        target_status=entry.get("status"),
                        attempts=entry["attempts"],
                        error=entry["last_error"],
                    )
                self.save_state()
                if kind != "permanent":
                    break
                continue
            self._mark_completion_outcome(entry, "confirmed")
            queue.remove(entry)
            self.logger.log(
                "record_update_synchronized",
                record_id=entry["record_id"],
                action=entry["action"],
                target_status=entry.get("status"),
                attempt=entry["attempts"],
                queued_seconds=max(0, int(time.time() - entry["created_at"])),
            )
            self.save_state()
        return not self.state.get("pending_record_updates")

    def post_record_comment(self, record_id, content):
        """Queue a response-record comment durably and try to deliver it now."""
        if not self.queue_record_update(record_id, "comment", content=content):
            return True
        try:
            self.save_state()
        except StateSaveError as exc:
            self.logger.log(
                "record_comment_queue_unsaved",
                "ERROR",
                response_record_id=record_id,
                error=str(exc),
            )
            try:
                self.provider.add_response_record_comment(record_id, content)
            except Exception as send_exc:
                self.logger.log(
                    "record_comment_failed",
                    "WARNING",
                    response_record_id=record_id,
                    error=str(send_exc),
                )
                return False
            return True
        return self.flush_record_updates()

    def queue_message(
        self,
        chat_name,
        content,
        *,
        kind="lifecycle",
        status_record_id=None,
        ttl_seconds=LIFECYCLE_MESSAGE_TTL_SECONDS,
    ):
        """Queue one chat message without network use; returns the entry."""
        chat = str(chat_name or "").strip()
        if not chat:
            return None
        entry = {
            **self._new_queue_entry(ttl_seconds),
            "chat": chat,
            "content": _bounded_text(content),
            "kind": kind,
        }
        if status_record_id is not None:
            entry["status_record_id"] = status_record_id
            entry["record_status_outcome"] = "pending"
        queue = self.state.setdefault("pending_messages", [])
        queue.append(entry)
        self._trim_queue(queue, MAX_QUEUED_MESSAGES, "lifecycle_chat_dropped")
        return entry

    def queue_activity_chats(self, config_keys, message, *, status_record_id=None):
        if not self._supports("supports_messaging"):
            return []
        entries, seen = [], set()
        for key in config_keys:
            chat_name = str(self.config.get(key, "")).strip()
            if not chat_name or chat_name.casefold() in seen:
                continue
            seen.add(chat_name.casefold())
            entry = self.queue_message(
                chat_name, message, status_record_id=status_record_id
            )
            if entry:
                entries.append(entry)
        return entries

    def completion_status_line(self, record_id, outcome=None):
        """Describe external completion state as it is when the message is sent."""
        parts = []
        if self._supports("supports_response_record_status"):
            queued = any(
                item.get("record_id") == record_id and item.get("action") == "status"
                for item in self.state.get("pending_record_updates") or []
            )
            slot = self.state.get("pending_response_status")
            if isinstance(slot, dict) and slot.get("record_id") == record_id:
                queued = True
            if queued:
                parts.append("Response record: DONE update queued")
            elif outcome == "confirmed":
                parts.append("Response record: DONE")
            else:
                # Absence from the queue can mean expiry, rejection or eviction;
                # it is not evidence that the external system accepted DONE.
                parts.append("Response record: DONE not confirmed — check external system")
        if self.asset_tracking_enabled():
            if self.state.get("asset_status_sync_pending"):
                parts.append(
                    "Asset: ONLINE update queued"
                    if self.state.get("asset_status_sync_target") == "ONLINE"
                    else "Asset: superseded by a newer line event"
                )
            elif self.state.get("asset_status") == "ONLINE":
                parts.append("Asset: ONLINE")
            else:
                parts.append("Asset: changed by a newer line event")
        return " • ".join(parts)

    def render_queued_message(self, entry):
        content = entry["content"]
        record_id = entry.get("status_record_id")
        if record_id is None:
            return content
        status_line = self.completion_status_line(
            record_id, entry.get("record_status_outcome")
        )
        return f"{content}\n{status_line}" if status_line else content

    def flush_messages(self, force=False):
        """Deliver queued chat messages; returns ``{entry id: outcome}``.

        Requests for help go first. Outcomes are ``sent``, ``queued``,
        ``abandoned`` or ``expired``; entries not attempted are not reported.
        """
        outcomes = {}
        queue = self.state.get("pending_messages") or []
        if not queue:
            return outcomes
        if not self._supports("supports_messaging") or not getattr(
            self.provider, "connected", True
        ):
            return outcomes
        ordered = sorted(
            queue, key=lambda item: (item.get("kind") != "support", item["created_at"])
        )
        for entry in ordered:
            if self._queue_entry_expired(entry):
                queue.remove(entry)
                outcomes[entry["id"]] = "expired"
                self.logger.log(
                    "lifecycle_chat_expired",
                    "WARNING",
                    chat=entry["chat"],
                    message_type=entry["content"].split("\n", 1)[0],
                    attempts=entry.get("attempts"),
                    last_error=entry.get("last_error", ""),
                )
                self.save_state()
                continue
            if not force and not self._queue_entry_due(entry):
                continue
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            entry["last_attempt_at"] = time.time()
            self.save_state()
            try:
                self.provider.send_message(entry["chat"], self.render_queued_message(entry))
            except Exception as exc:
                kind, give_up, delay = self._schedule_retry(entry, exc)
                if entry.get("kind") == "support" and kind == "permanent":
                    give_up = True
                self.logger.log(
                    "lifecycle_chat_failed",
                    "WARNING",
                    chat=entry["chat"],
                    message_type=entry["content"].split("\n", 1)[0],
                    attempt=entry["attempts"],
                    failure=kind,
                    retry_in_seconds=None if give_up else delay,
                    error=entry["last_error"],
                )
                if give_up:
                    queue.remove(entry)
                    outcomes[entry["id"]] = "abandoned"
                    self.logger.log(
                        "lifecycle_chat_abandoned",
                        "ERROR",
                        chat=entry["chat"],
                        message_type=entry["content"].split("\n", 1)[0],
                        attempts=entry["attempts"],
                        error=entry["last_error"],
                    )
                else:
                    outcomes[entry["id"]] = "queued"
                self.save_state()
                if kind != "permanent":
                    break
                continue
            queue.remove(entry)
            outcomes[entry["id"]] = "sent"
            self.logger.log(
                "lifecycle_chat_sent",
                chat=entry["chat"],
                message_type=entry["content"].split("\n", 1)[0],
                attempt=entry["attempts"],
                queued_seconds=max(0, int(time.time() - entry["created_at"])),
            )
            self.save_state()
        return outcomes

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
        self._mark_completion_outcome(
            {"action": "status", "status": status, "record_id": response_record_id},
            "confirmed",
        )
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
        except StateSaveError:
            raise
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
        self.post_record_comment(response_record_id, message)
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
            completion_confirmed_at=None,
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
            self.asset_status_note(
                f"Unplanned downtime • repair in progress • {self.config['line_name']}",
                zone,
                self.failure_reasons(),
                self.operator_notes(),
                response_record_id,
            ),
        )
        self.post_record_comment(
            response_record_id,
            f"🔧 WORK STARTED\nEngineers: {names}\nAffected stations: {zone}\nReported failures: {failures}\nStarted: {now:%Y-%m-%d %H:%M:%S %Z}\nSource: {self._source_name()}",
        )
        self.send_activity_chats(
            ["engineering_chat_name", "common_activity_chat_name"],
            f"🔧 REPAIR IN PROGRESS • {self.config['line_name']}\nResponse record: #{response_record_id}\nStations: {zone}\nReported failures: {failures}\nEngineers: {names}\nStarted: {now:%H:%M:%S %Z}",
        )
        self.play_sound("response")
        suffix = "" if assignment_ok and status_ok and asset_ok else " • external sync pending"
        return f"Repair started by {names}{suffix}"

    def format_template(self, key, **values):
        """Fill a configured message template.

        Settings accepts every documented placeholder in every template, so each
        one always has a value here; a valid template can never fail to format.
        """
        now = datetime.now().astimezone()
        defaults = {
            "line": self.config.get("line_name", ""),
            "zones": self.zone_summary(),
            "time": now.strftime("%H:%M"),
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "department": "Engineering",
            "condition": "assistance is required",
            "work_label": self.state.get("work_label") or "Engineering work",
        }
        return str(self.config[key]).format(**{**defaults, **values})

    def report_downtime(self):
        if not self.has_zone_selection():
            raise RuntimeError("Select the affected station or Entire Line first")
        now = datetime.now().astimezone()
        line = self.config["line_name"]
        title = self.format_template(
            "downtime_title_template",
            line=line,
            zones=self.zone_summary(),
            time=now.strftime("%H:%M"),
            timestamp=now.isoformat(),
        )
        desc = self.format_template(
            "downtime_description_template",
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
            work_label=None,
            work_type=None,
            completion_confirmed_at=None,
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
                "reasons_summary": self.failure_reasons(),
                "notes_summary": self.operator_notes(),
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
            self.asset_status_note(
                f"Unplanned downtime • {line}",
                zones,
                pending.get("reasons_summary") or failures,
                pending.get("notes_summary", ""),
                number,
            ),
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

    def _record_creation_supported(self):
        info = getattr(self.provider, "INFO", None)
        return bool(getattr(info, "supports_response_records", False))

    def _queued_creation(self):
        """The one queued record creation, if any, as ``(kind, pending)``."""
        if not self._record_creation_supported():
            return None, None
        for kind in ("pending_response_record", "pending_planned_work"):
            pending = self.state.get(kind)
            if pending:
                return kind, pending
        return None, None

    def sync_work_due(self):
        """Whether any queued external work is due for an automatic attempt."""
        state = self.state
        _kind, creation = self._queued_creation()
        if creation and self.pending_retry_due(creation):
            return True
        for key in ("pending_response_status", "pending_participant_assignment"):
            pending = state.get(key)
            if isinstance(pending, dict) and self.pending_retry_due(pending):
                return True
        if state.get("asset_status_sync_pending") and self.pending_retry_due(
            state.get("asset_status_sync_context") or {}
        ):
            return True
        return any(
            self._queue_entry_expired(entry) or self._queue_entry_due(entry)
            for key in ("pending_record_updates", "pending_messages")
            for entry in state.get(key) or []
        )

    def synchronize_due_work(self, force=False):
        """Attempt every due queued item once, in dependency order.

        Record creation comes first because every later update refers to the
        created record. ``force`` ignores retry intervals for a manual retry.
        """
        state = self.state
        kind, creation = self._queued_creation()
        if creation and (force or self.pending_retry_due(creation)):
            try:
                if kind == "pending_response_record":
                    self.sync_pending_downtime()
                else:
                    self.sync_pending_planned_work()
            except StateSaveError:
                raise
            except Exception as exc:
                if kind == "pending_response_record":
                    self.state["pending_sync_error"] = str(exc)
                    self.save_state()
                self.logger.log(
                    "downtime_sync_deferred"
                    if kind == "pending_response_record"
                    else "planned_work_sync_deferred",
                    "WARNING",
                    error=str(exc),
                )
                subject = (
                    "Downtime is recorded locally"
                    if kind == "pending_response_record"
                    else "Planned work is queued locally"
                )
                return f"{subject} • sync pending: {_short_error(exc, 90)}"
        pending = state.get("pending_response_status")
        if isinstance(pending, dict) and (force or self.pending_retry_due(pending)):
            self.sync_response_status(pending["record_id"], pending["status"])
        pending = state.get("pending_participant_assignment")
        if isinstance(pending, dict) and (force or self.pending_retry_due(pending)):
            self.sync_participant_assignment(
                pending["record_id"], pending.get("team_id"), pending["user_ids"]
            )
        context = state.get("asset_status_sync_context") or {}
        if state.get("asset_status_sync_pending") and (
            force or self.pending_retry_due(context)
        ):
            self.attempt_asset_status()
        self.flush_record_updates(force=force)
        self.flush_messages(force=force)
        remaining = self.queued_sync_count()
        if not remaining:
            return "No external updates remain queued • check activity for delivery details"
        return (
            f"{remaining} external update{'s' if remaining != 1 else ''} still queued"
            " • retrying automatically"
        )

    def sync_pending_tick(self):
        try:
            if (
                getattr(self.provider, "connected", False)
                and not self.busy
                and self.sync_work_due()
            ):
                self.perform(
                    "Synchronizing queued updates…",
                    self.synchronize_due_work,
                    quiet=True,
                )
        finally:
            self.root.after(SYNC_TICK_MS, self.sync_pending_tick)

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
                self.perform(
                    "Escalating unattended downtime…", self.escalate_downtime, quiet=True
                )
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
        earlier = self.state.get("completion_confirmed_at")
        if isinstance(earlier, (int, float)) and not isinstance(earlier, bool):
            stamp = datetime.fromtimestamp(earlier).astimezone().strftime("%H:%M:%S")
            self.modal["note"] = (
                f"An earlier release at {stamp} was not saved • "
                f"confirming records Production restored at {stamp}"
            )

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
        title = self.format_template("planned_work_title_template", **values)
        description = self.format_template(
            "planned_work_description_template", **values
        )
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
            "reasons_summary": self.failure_reasons(""),
            "notes_summary": self.operator_notes(),
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
            completion_confirmed_at=None,
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
            self.asset_status_note(
                f"Planned {pending['work_label']} • {line}",
                zones,
                pending["work_label"]
                + (
                    f" • reported failures: {pending['reasons_summary']}"
                    if pending.get("reasons_summary")
                    else ""
                ),
                pending.get("notes_summary", ""),
                result.get("reference", result["id"]),
                (f"Engineering crew: {names}",),
            ),
        )
        self.log_event(
            f"{pending['work_label']} RECORD #{result.get('reference', result['id'])}",
            self.PURPLE,
        )
        self.save_state()
        self.post_record_comment(
            result["id"],
            f"🛠️ PLANNED WORK STARTED\nType: {pending['work_label']}\nEngineers: {names}\nStations: {zones}\nReported failures: {failures}\nStarted: {now:%Y-%m-%d %H:%M:%S %Z}\nSource: {self._source_name()}",
        )
        self.send_activity_chats(
            ["engineering_chat_name", "common_activity_chat_name"],
            f"🛠️ PLANNED • {pending['work_label'].upper()} STARTED • {line}\nResponse record: #{result.get('reference', result['id'])}\nStations: {zones}\nReported failures: {failures}\nEngineers: {names}",
        )
        suffix = "" if status_ok and asset_ok else " • external sync pending"
        return f"{pending['work_label']} started • RECORD #{result.get('reference', result['id'])}{suffix}"

    def _source_name(self):
        profile = getattr(self, "project_profile", None)
        return getattr(profile, "product_name", "") or "FloorTerminal"

    def finish_work(self, confirmed_at=None):
        """Release the line to Production as one atomic, durable transition.

        The release, the queued response-record completion, the asset state, and
        the notifications are committed in a single save. Network attempts happen
        only afterwards, so an interruption at any point leaves every external
        update queued for automatic retry rather than silently lost.
        """
        response_record_id = self.state.get("response_record_id")
        if not response_record_id:
            raise RuntimeError("No active maintenance response record")
        released_at = float(confirmed_at or time.time())
        earlier = self.state.get("completion_confirmed_at")
        if (
            isinstance(earlier, (int, float))
            and not isinstance(earlier, bool)
            and 0 < earlier <= released_at
        ):
            # A previous release was confirmed but could not be saved. The line
            # was released then, so the recorded durations must not grow.
            released_at = float(earlier)
            self.logger.log(
                "completion_uses_first_confirmation",
                "WARNING",
                response_record_id=response_record_id,
                confirmed_at=released_at,
            )
        else:
            self.state["completion_confirmed_at"] = released_at
            self.save_state()
        now = datetime.fromtimestamp(released_at).astimezone()
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
        base = self.state.get("started_at") or released_at
        total = max(0, int(released_at - base))
        threshold = int(self.config.get("micro_stop_threshold_minutes", 5)) * 60
        event_class = self.classify_downtime(total)
        repair_base = self.state.get("repair_at")
        repair = max(0, int(released_at - repair_base)) if repair_base else total
        zone = self.zone_summary()
        failures = self.failure_summary()
        reasons = self.failure_reasons()
        operator_notes = self.operator_notes()
        selected_stations = self.selected_zones()
        line = self.config["line_name"]
        planned_label = (
            self.state.get("work_label")
            if self.state.get("status") == "ENGINEERING"
            else None
        )
        completion_comment = (
            f"✅ WORK COMPLETED • {event_class}\nAll engineers involved: {names}\nCrew active at completion: {active_names}"
            f"\nParticipation history:\n{timeline_text}\nLine stations: {zone}\nReported failures: {failures}"
            f"\nCompleted: {now:%Y-%m-%d %H:%M:%S %Z}\nTotal line time: {self.format_duration(total)}"
            f"\nActive work time: {self.format_duration(repair)}\nProduction release confirmed on {self._source_name()}."
        )
        completion_message = (
            f"✅ LINE RELEASED TO PRODUCTION • {event_class} • {line}\nResponse record: #{response_record_id}"
            + (f"\nWork: {planned_label}" if planned_label else "")
            + f"\nStations: {zone}\nReported failures: {failures}\nEngineers involved: {names}\nCrew at completion: {active_names}"
            f"\nTotal line time: {self.format_duration(total)}"
        )

        # --- one atomic transition -----------------------------------------
        # The physical release is authoritative. It is persisted together with
        # every follow-up so neither can exist on disk without the other.
        self.state["status"] = "RUNNING"
        self.log_event(f"Production resumed • {event_class}", self.GREEN)
        self.state.update(
            response_record_id=None,
            started_at=None,
            repair_at=None,
            work_label=None,
            work_type=None,
            completion_confirmed_at=None,
            engineer_ids=[],
            engineer_names=[],
            engineer_history=[],
            issue_zones=[],
            failure_selections={},
            failure_notes={},
            escalated_at=None,
        )
        slot = self.state.get("pending_response_status")
        if isinstance(slot, dict) and slot.get("record_id") == response_record_id:
            # Completion supersedes an unsent In Progress update for this record.
            self.state["pending_response_status"] = None
        self.queue_record_update(response_record_id, "comment", content=completion_comment)
        status_queued = self.queue_record_update(response_record_id, "status", status="DONE")
        asset_queued = self.queue_asset_status(
            "ONLINE",
            description=self.asset_status_note(
                f"Production resumed • {event_class} • {line}",
                zone,
                planned_label or reasons,
                operator_notes,
                response_record_id,
                (f"Total line time: {self.format_duration(total)}",),
            ),
        )
        self.queue_activity_chats(
            ["engineering_chat_name", "production_chat_name", "common_activity_chat_name"],
            completion_message,
            status_record_id=response_record_id if (status_queued or asset_queued) else None,
        )
        self.save_state()
        self.logger.log(
            "downtime_classified",
            classification=event_class,
            total_seconds=total,
            threshold_seconds=threshold,
            stations=selected_stations,
        )
        self.logger.log(
            "production_release_recorded",
            response_record_id=response_record_id,
            classification=event_class,
            total_seconds=total,
            active_work_seconds=repair,
            queued_external_updates=self.queued_sync_count(),
        )
        self.play_sound("restored")

        # --- external synchronization; each step stays queued on failure ------
        asset_ok = self.attempt_asset_status() if asset_queued else True
        updates_ok = self.flush_record_updates()
        self.flush_messages()
        suffix = "" if asset_ok and updates_ok else " • external sync queued"
        return f"Work completed by {names} • Production resumed{suffix}"

    def queue_asset_status(self, status, downtime_type=None, description=""):
        """Record the desired asset state durably without network use.

        Returns False when asset tracking is off or the asset is already in the
        requested state. An unchanged pending target keeps its idempotency key and
        original context so a retry after an ambiguous timeout cannot duplicate it.
        """
        if not self.asset_tracking_enabled():
            return False
        target = str(status).upper()
        if self.state.get("asset_status") == target and not self.state.get(
            "asset_status_sync_pending"
        ):
            return False
        new_event = (
            not self.state.get("asset_status_sync_pending")
            or self.state.get("asset_status_sync_target") != target
        )
        context = None if new_event else self.state.get("asset_status_sync_context")
        if new_event:
            self.state["asset_status_sync_key"] = str(uuid.uuid4())
            self.state["asset_status_sync_attempts"] = 0
        if context is None:
            context = {
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
        self.state["asset_status_sync_context"] = context
        return True

    def attempt_asset_status(self):
        """Make one attempt for the queued asset state; never raises connector errors."""
        if not self.state.get("asset_status_sync_pending"):
            return True
        try:
            self._send_asset_status()
        except StateSaveError:
            raise
        except Exception:
            return False
        return not self.state.get("asset_status_sync_pending")

    def _send_asset_status(self):
        context = self.state["asset_status_sync_context"]
        target = self.state.get("asset_status_sync_target") or context["status"]
        if not self.state.get("asset_status_sync_key"):
            self.state["asset_status_sync_key"] = str(uuid.uuid4())
        context["last_attempt_at"] = time.time()
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
            display_name = getattr(
                getattr(self.provider, "INFO", None), "display_name", "Connector"
            )
            raise RuntimeError(
                f"{display_name} asset could not be set {target}; workflow is saved and can be retried: {exc}"
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

    def sync_asset_status(self, status, downtime_type=None, description=""):
        """Synchronize provider asset state and persist enough data for safe retries."""
        if not self.asset_tracking_enabled():
            return None
        target = str(status).upper()
        if self.state.get("asset_status") == target and not self.state.get(
            "asset_status_sync_pending"
        ):
            return self.state.get("asset_status_id")
        self.queue_asset_status(status, downtime_type, description)
        return self._send_asset_status()

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
            if not self._supports("supports_messaging"):
                raise RuntimeError("Messaging is not provided by connector.json")
            chat_name = str(self.config.get(name.lower() + "_chat_name", "")).strip()
            if not chat_name:
                raise RuntimeError(
                    f"No {name} chat is configured • set it in Settings → Connector"
                )
            now = datetime.now().astimezone()
            line = self.config["line_name"]
            status = self.state.get("status", "RUNNING")
            condition = {
                "RUNNING": "production is currently running",
                "DOWN": "the line is down",
                "REPAIRING": "a repair is in progress",
                "ENGINEERING": "Engineering has control for planned work",
            }.get(status, "assistance is required")
            message = self.format_template(
                "help_message_template",
                department=name,
                line=line,
                condition=condition,
                timestamp=now.strftime("%H:%M:%S %Z"),
                zones=self.zone_summary("No station specified"),
                time=now.strftime("%H:%M"),
                work_label=self.state.get("work_label") or "",
            )
            if self.failure_summary(""):
                message += f" Reported failures: {self.failure_summary('')}."
            entry = self.queue_message(
                chat_name,
                message,
                kind="support",
                ttl_seconds=SUPPORT_MESSAGE_TTL_SECONDS,
            )
            self.log_event(
                f"{name} support called",
                {
                    "Engineering": self.BLUE,
                    "Quality": self.PURPLE,
                    "Production": self.ORANGE,
                }[name],
            )
            self.save_state()
            outcome = self.flush_messages().get(entry["id"], "queued")
            if outcome == "sent":
                self.play_sound("support")
                return f"Message sent to {name} chat"
            if outcome == "abandoned":
                raise RuntimeError(
                    f"{name} was not notified: {entry.get('last_error') or 'the message was rejected'}"
                )
            wait = entry.get("retry_after_seconds")
            self.logger.log(
                "support_call_queued",
                "WARNING",
                department=name,
                chat=chat_name,
                retry_in_seconds=wait,
                error=entry.get("last_error", ""),
            )
            return (
                f"{name} call queued • sending automatically"
                + (f" in {wait} s" if wait else "")
            )

        self.perform(f"Calling {name}…", action)

    def send_activity_chats(self, config_keys, message, *, status_record_id=None):
        """Queue lifecycle broadcasts durably, then attempt delivery now.

        Response-record state remains authoritative; a notification that cannot be
        delivered — for example because the connector's request budget is spent —
        stays queued and is retried automatically instead of being dropped.
        """
        entries = self.queue_activity_chats(
            config_keys, message, status_record_id=status_record_id
        )
        if not entries:
            return
        try:
            self.save_state()
        except StateSaveError as exc:
            # The queue could not be persisted and was rolled back; fall back to
            # one direct attempt so an operational message is still delivered.
            self.logger.log("lifecycle_chat_queue_unsaved", "ERROR", error=str(exc))
            for entry in entries:
                try:
                    self.provider.send_message(entry["chat"], entry["content"])
                    self.logger.log(
                        "lifecycle_chat_sent",
                        chat=entry["chat"],
                        message_type=entry["content"].split("\n", 1)[0],
                    )
                except Exception as send_exc:
                    self.logger.log(
                        "lifecycle_chat_failed",
                        "WARNING",
                        chat=entry["chat"],
                        error=str(send_exc),
                    )
            return
        try:
            self.flush_messages()
        except StateSaveError as exc:
            self.logger.log("lifecycle_chat_state_unsaved", "ERROR", error=str(exc))
