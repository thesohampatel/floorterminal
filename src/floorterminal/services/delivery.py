"""Local workflow writes and isolated, one-at-a-time external delivery.

The network worker receives a copy, never the live state or a Tk widget. Results
are applied only between local operations. Sending is journaled before dispatch;
uncertain non-idempotent writes are retained for review, not blindly repeated.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from copy import deepcopy

from ..integration.runtime import IntegrationError
from ..storage.delivery import LOCAL_PREFIX, binding, enqueue, replace_reference
from ..storage.state import StateSaveError
from .integration import ExternalIntegration
from .roster import RosterCoordinatorMixin

SEMANTICS = {
    "create_response_record": "create_response_record",
    "set_response_record_status": "update_response_record_status",
    "assign_participants": "update_response_record",
    "add_response_record_comment": "create_response_record_comment",
    "set_asset_status": "create_asset_status",
}
CAPABILITIES = {
    "create_response_record": "supports_response_records",
    "set_response_record_status": "supports_response_record_status",
    "assign_participants": "supports_response_record_assignments",
    "add_response_record_comment": "supports_response_record_comments",
    "set_asset_status": "supports_asset_status",
    "send_message": "supports_messaging",
}
LOCAL_REFERENCE = re.compile(
    r"local:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
)


class DeferredIntegration:
    """Network-free write facade. Reads are explicit and handled separately."""

    deferred_writes = True

    def __init__(self, app, remote):
        self.app, self.remote = app, remote

    def __getattr__(self, name):
        return getattr(self.remote, name)

    def _queue(
        self, method, args, kwargs=None, expires_at=None, context=None, incident=None
    ):
        if self.app.config.get("reporting_mode") == "local":
            import uuid

            key = (kwargs or {}).get("idempotency_key") or str(uuid.uuid4())
            return {"id": key, "reference": LOCAL_PREFIX + key}
        try:
            frozen_context = {
                **self.app.incident_context(incident),
                **(context or {}),
            }
            # Structured diagnoses are a creation field. Do not duplicate a
            # potentially large catalogue selection in every status/chat intent.
            if method != "create_response_record":
                frozen_context.pop("failure_details", None)
            item = enqueue(
                self.app.state,
                self.remote,
                method,
                args,
                kwargs or {},
                expires_at=expires_at,
                context_override=frozen_context,
                binding_override=(
                    (self.app.state if incident is None else incident).get(
                        "incident_scope"
                    )
                    or {}
                ).get("connector_binding"),
            )
        except (ValueError, TypeError) as exc:
            error = StateSaveError(f"External update could not be queued: {exc}")
            self.app.state_store.fail_transaction(error)
            raise error from exc
        self.app.save_state()
        return item

    def resolve_name(self, resource, name):
        if resource == "team":
            return "team-name:" + str(name) if name else None
        return self.remote.resolve_name(resource, name)

    def create_response_record(
        self,
        title,
        description,
        team_id,
        priority="HIGH",
        work_type=None,
        participant_ids=None,
        idempotency_key=None,
    ):
        item = self._queue(
            "create_response_record",
            (title, description, team_id, priority, work_type, participant_ids),
            {"idempotency_key": idempotency_key} if idempotency_key else {},
        )
        return {"id": item["reference"], "reference": item["reference"], "queued": True}

    def set_response_record_status(self, record_id, status):
        self._queue("set_response_record_status", (record_id, status))
        return {"queued": True}

    def assign_participants(self, record_id, team_id, user_ids):
        self._queue("assign_participants", (record_id, team_id, user_ids))
        return {"queued": True}

    def add_response_record_comment(self, record_id, content):
        from ..core.topology import scope_text

        scope = scope_text(self.app.state.get("incident_scope"))
        if scope and scope not in content:
            content += "\n" + scope
        self._queue("add_response_record_comment", (record_id, content))
        return {"queued": True}

    def set_asset_status(
        self,
        status,
        downtime_type=None,
        description=None,
        started_at=None,
        idempotency_key=None,
    ):
        import uuid

        routes = self.app.external_assets(status)
        if routes is None:
            routes = [
                {
                    "asset_id": self.remote.config.get("asset_id", ""),
                    "location_id": self.remote.config.get("location_id", ""),
                }
            ]
        for route in routes:
            # Distinct stable keys for each asset, including retry after restart.
            key = (
                str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        str(idempotency_key) + ":" + route["asset_id"],
                    )
                )
                if idempotency_key
                else str(uuid.uuid4())
            )
            self._queue(
                "set_asset_status",
                (status, downtime_type, description, started_at),
                {"idempotency_key": key},
                context={
                    "asset_id": route["asset_id"],
                    "location_id": route["location_id"],
                },
            )
        return {"queued": True}

    def send_message(self, target_name, content):
        from ..core.topology import scope_text

        scope = scope_text(self.app.state.get("incident_scope"))
        if scope and scope not in content:
            content += "\n" + scope
        self._queue("send_message", (target_name, content))
        return {"queued": True}

    def queue_message(self, entry, content):
        from ..core.topology import scope_text

        scope = scope_text(self.app.state.get("incident_scope"))
        if entry.get("kind") != "support" and scope and scope not in content:
            content += "\n" + scope
        # Help requests become stale; retain them visibly for review on expiry.
        self._queue(
            "send_message",
            (entry["chat"], content),
            {"idempotency_key": entry["id"]},
            entry.get("expires_at") if entry.get("kind") == "support" else None,
            # A new manual call uses the currently selected connection, not an
            # older incident's frozen routing. Lifecycle notifications retain it.
            incident={} if entry.get("kind") == "support" else None,
        )


def retry_safe(remote, method):
    try:
        names = (
            ("send_conversation_message", "send_user_message")
            if method == "send_message"
            else (SEMANTICS[method],)
        )
        operations = [
            remote.definition.operation(remote.operations[name])
            for name in names
            if name in remote.operations
        ]
        return bool(operations) and all(
            op.retry_safe
            or op.raw.get("idempotency", {}).get("remote_guarantee") is True
            for op in operations
        )
    except (KeyError, AttributeError, ValueError):
        return False


def send_one(remote, item):
    """Execute an immutable job; any provider-required lookups happen here too."""
    args = deepcopy(item["args"])
    method = item["method"]
    if method in {"create_response_record", "assign_participants"}:
        position = 2 if method == "create_response_record" else 1
        team = args[position]
        if isinstance(team, str) and team.startswith("team-name:"):
            args[position] = remote.resolve_name(
                "team", team.removeprefix("team-name:")
            )
    kwargs = (
        item["kwargs"]
        if method in {"create_response_record", "set_asset_status"}
        else {}
    )
    return getattr(remote, method)(*args, **kwargs)


class DeliveryCoordinator(RosterCoordinatorMixin):
    def __init__(self, app, provider_factory=ExternalIntegration):
        self.app = app
        self.provider_factory = provider_factory
        self.results = queue.Queue(maxsize=1)
        self.active = None
        self.closed = False
        self.deadlines = {}
        self.next_poll = 0.0
        self.ack_retry_at = 0.0
        self.init_roster()
        self.recover()

    def recover(self):
        changed = False
        for item in self.app.state.get("delivery_outbox", []):
            if item["phase"] == "sending":
                item["phase"] = "queued" if item["safe_retry"] else "attention"
                item["error"] = "Interrupted delivery; remote acceptance is uncertain"
                changed = True
        if changed:
            self.app.save_state()

    def close(self):
        # Never wait for a socket on the GUI shutdown path. Persisted 'sending'
        # is reconciled conservatively by recover() at the next launch.
        self.closed = True

    def explanation(self, item):
        remote = getattr(self.app.provider, "remote", None)
        if remote is None or not remote.connected:
            return "Waiting for an enabled, complete connector. Local line reporting remains available."
        if item["binding"] and item["binding"] != binding(remote):
            return "This update belongs to a different connection. Select its original connector; it will not be sent to another system."
        if not getattr(remote.INFO, CAPABILITIES[item["method"]], False):
            return "The selected connector does not offer this operation. Complete its mapping to resume; this update remains saved."
        return (
            item["error"]
            or "Waiting for the connection, request budget or an earlier dependent update."
        )

    def _due(self, item):
        epoch = item["next_at"]
        cached = self.deadlines.get(item["id"])
        if cached is None or cached[0] != epoch:
            cached = epoch, time.monotonic() + max(0, epoch - time.time())
            self.deadlines[item["id"]] = cached
        return time.monotonic() >= cached[1]

    def _apply(self, item_id, result, error, sent):
        state = self.app.state
        item = next(
            (
                item
                for item in state.get("delivery_outbox", [])
                if item["id"] == item_id
            ),
            None,
        )
        if item is None:
            return
        if error is None:
            if item["reference"]:
                identifier = result.get("id") if isinstance(result, dict) else None
                if (
                    isinstance(identifier, bool)
                    or not isinstance(identifier, (str, int))
                    or not str(identifier).strip()
                    or len(str(identifier)) > 200
                    or not str(identifier).isprintable()
                    or str(identifier).startswith(LOCAL_PREFIX)
                ):
                    error = IntegrationError(
                        "Creation returned no usable record identifier",
                        "INVALID_RESPONSE",
                    )
                else:
                    incident_id = item["context"].get("incident_id")
                    if incident_id:
                        state.setdefault("history_links", {})[incident_id] = identifier
                    state["delivery_outbox"].remove(item)
                    replaced = replace_reference(state, item["reference"], identifier)
                    state.clear()
                    state.update(replaced)
            else:
                state["delivery_outbox"].remove(item)
        if error is not None:
            code, status = getattr(error, "code", ""), getattr(error, "status", None)
            ambiguous = (
                sent
                and not item["safe_retry"]
                and (
                    status is None
                    or status == 408
                    or status >= 500
                    or code == "INVALID_RESPONSE"
                )
            )
            permanent = (
                (
                    status is not None
                    and 300 <= status < 500
                    and status not in {408, 425, 429}
                )
                or code
                in {
                    "AUTHENTICATION",
                    "PERMISSION",
                    "NOT_CONFIGURED",
                    "INVALID_RESPONSE",
                    "RESPONSE_TOO_LARGE",
                }
                or isinstance(error, (ValueError, TypeError))
                or not isinstance(error, (IntegrationError, OSError))
            )
            item["phase"] = "attention" if ambiguous or permanent else "queued"
            delay = max(
                1,
                float(
                    getattr(error, "retry_after", None)
                    or min(900, 5 * 2 ** min(item["attempts"], 8))
                ),
            )
            item["next_at"] = time.time() + delay
            item["error"] = (
                "Remote acceptance uncertain • " if ambiguous else ""
            ) + str(error)[:440]
            # A network outage or quota response pauses all jobs, rather than
            # burning another request for each entry in the queue.
            if not permanent:
                state["delivery_pause_until"] = max(
                    state.get("delivery_pause_until", 0), item["next_at"]
                )
        self.app.save_state()
        self.app.logger.log(
            "delivery_deferred" if error else "delivery_confirmed",
            "WARNING" if error else "INFO",
            delivery_id=item_id,
            operation=item["method"],
            phase=item["phase"] if error else "confirmed",
            error=item["error"] if error else "",
        )

    def poll(self):
        if self.closed or self.app.busy or time.monotonic() < self.ack_retry_at:
            return
        if self.active:
            try:
                result = self.results.get_nowait()
            except queue.Empty:
                return
            help_notice = next(
                (
                    item
                    for item in self.app.state.get("delivery_outbox", [])
                    if item["id"] == result[0]
                    and item["method"] == "send_message"
                    and item["expires_at"] is not None
                ),
                None,
            )

            def acknowledge():
                if result[0] == "roster":
                    self._acknowledge_roster(*result[1:])
                else:
                    self._apply(*result)

            def acknowledged(_result):
                self.active = None
                if result[0] == "roster":
                    self._roster_received(*result[1:])
                elif help_notice is not None:
                    if result[2] is None:
                        self.app.notify(
                            "Help message delivered to the service", "success", 5
                        )
                        self.app.play_sound("support")
                    elif help_notice["phase"] == "attention":
                        self.app.notify(
                            "Help delivery needs review • open Delivery", "info", 6
                        )

            def failed(_error):
                # Retry the local acknowledgement, never resend a successful
                # non-idempotent request just because disk persistence failed.
                self.results.put_nowait(result)
                self.ack_retry_at = time.monotonic() + 5

            if not self.app.perform(
                "Saving delivered updates",
                acknowledge,
                acknowledged,
                quiet=True,
                on_error=failed,
            ):
                failed(None)
            return
        if time.monotonic() < self.next_poll:
            return
        self.next_poll = time.monotonic() + 0.5
        entries = self.app.state.get("delivery_outbox", [])
        expired = next(
            (
                item
                for item in entries
                if item["phase"] == "queued"
                and item["expires_at"] is not None
                and time.time() >= item["expires_at"]
            ),
            None,
        )
        if expired is not None:
            # Stale calls must become reviewable even with no connector or while
            # the remote quota is paused. Expiration itself uses no network.
            def expire():
                expired["phase"], expired["error"] = (
                    "attention",
                    "Help request expired; use the site's escalation process",
                )
                self.app.save_state()

            self.app.perform("Saving expired help notice", expire, quiet=True)
            return
        keys = {item["id"] for item in entries}
        self.deadlines = {
            key: value
            for key, value in self.deadlines.items()
            if key in keys or key == "pause"
        }
        pause = {
            "id": "pause",
            "next_at": self.app.state.get("delivery_pause_until", 0),
        }
        if not self._due(pause):
            return
        remote = getattr(self.app.provider, "remote", None)
        if remote is None or not remote.connected:
            return
        blocked_streams = set()
        for item in entries:
            stream = (
                "asset:" + str(item["context"].get("asset_id", ""))
                if item["method"] == "set_asset_status"
                else item["method"] + ":" + str(item["args"][0])
                if item["method"]
                in {
                    "set_response_record_status",
                    "assign_participants",
                    "add_response_record_comment",
                    "send_message",
                }
                else item["reference"]
            )
            if stream in blocked_streams:
                continue
            if item["phase"] != "attention" or item["method"] in {
                "set_asset_status",
                "set_response_record_status",
                "assign_participants",
            }:
                blocked_streams.add(stream)
            if item["phase"] != "queued" or not self._due(item):
                continue
            if item["binding"] and item["binding"] != binding(remote):
                continue
            if not getattr(remote.INFO, CAPABILITIES[item["method"]], False):
                continue
            if LOCAL_REFERENCE.search(str(item["args"])):
                # Creation must be acknowledged before dependent writes.
                continue
            self._start(remote, item)
            return
        # Production writes have priority. Optional daily directory maintenance
        # uses the same single worker and never blocks the operator thread.
        self._poll_roster(remote)

    def _start(self, remote, item):
        """Persist dispatch off Tk; launch HTTP only AFTER that commit succeeds."""
        identifier = item["id"]
        self.active = identifier

        def prepare():
            worker_remote = self.provider_factory(
                {**deepcopy(remote.config), **item["context"]},
                self.app.logger,
                definition=remote.definition,
            )
            worker_remote.client.bind_request_window(self.app._api_request_window)
            worker_remote.client.max_attempts_override = 1
            worker_remote.client.default_idempotency_key = identifier
            worker_remote.name_cache = deepcopy(remote.name_cache)
            worker_remote.directory_progress = deepcopy(
                getattr(remote, "directory_progress", {})
            )
            item["safe_retry"] = retry_safe(worker_remote, item["method"])
            item["phase"] = "sending"
            item["attempts"] += 1
            self.app.save_state()
            return worker_remote, deepcopy(item)

        def failed(error):
            if isinstance(error, StateSaveError):
                self.active = None
                self.ack_retry_at = time.monotonic() + 5
            else:
                # No HTTP was attempted; normal error classification is safe.
                self.results.put_nowait((identifier, None, error, False))

        if not self.app.perform(
            "Preparing saved update",
            prepare,
            lambda prepared: self._dispatch(remote, *prepared),
            quiet=True,
            on_error=failed,
        ):
            self.active = None

    def _dispatch(self, remote, worker_remote, snapshot):
        # Frozen target config prevents a Settings edit from retargeting a queued
        # asset/location event. Credentials stay only in the transient worker.
        if self.closed:
            return
        attempted = {"write": False}
        worker_remote.client.before_send = lambda request: attempted.update(
            write=attempted["write"] or request.method not in {"GET", "HEAD"}
        )

        def worker():
            try:
                result = send_one(worker_remote, snapshot)
                outcome = (snapshot["id"], result, None, attempted["write"])
            except Exception as exc:  # noqa: BLE001 - isolated network boundary
                outcome = (
                    snapshot["id"],
                    None,
                    exc,
                    attempted["write"] and not getattr(exc, "no_request_sent", False),
                )
            finally:
                # Preserve successful reads even if a later request ran out of
                # budget. Otherwise a 1-request/minute budget can never progress.
                remote.name_cache = deepcopy(worker_remote.name_cache)
                remote.directory_progress = deepcopy(worker_remote.directory_progress)
                for name in ("limit", "remaining", "reset", "window_resets_at"):
                    setattr(remote.client, name, getattr(worker_remote.client, name))
            self.results.put(outcome)

        try:
            threading.Thread(
                target=worker, name="external-delivery", daemon=True
            ).start()
        except Exception as exc:  # noqa: BLE001 - dispatch never attempted HTTP
            self.results.put_nowait((snapshot["id"], None, exc, False))

    def retry_reviewed(self, item_id, administrator):
        if self.app.busy:
            raise RuntimeError("Wait for the local operation to finish")
        item = next(
            (
                entry
                for entry in self.app.state.get("delivery_outbox", [])
                if entry["id"] == item_id
            ),
            None,
        )
        if not item or item["phase"] != "attention":
            return
        if item["expires_at"] is not None and time.time() >= item["expires_at"]:
            raise RuntimeError(
                "This help request expired. Call support again with current conditions."
            )
        item.update(phase="queued", error="", next_at=0)
        if item["method"] == "send_message":
            from ..integration.directory import refresh_completed

            remote = getattr(self.app.provider, "remote", None)
            if remote is not None and hasattr(remote, "directory_progress"):
                refresh_completed(remote, {"conversations", "users"})
        self.app.save_state()
        self.app.logger.log(
            "delivery_retry_authorized",
            administrator=administrator,
            delivery_id=item_id,
        )

    def archive_expired_notice(self, item_id, administrator):
        """Acknowledge only stale help requests, never discard lifecycle records."""
        if self.app.busy:
            raise RuntimeError("Wait for the local operation to finish")
        entries = self.app.state.get("delivery_outbox", [])
        item = next((entry for entry in entries if entry["id"] == item_id), None)
        if (
            not item
            or item["phase"] != "attention"
            or item["method"] != "send_message"
            or item["expires_at"] is None
            or time.time() < item["expires_at"]
        ):
            raise RuntimeError("Only expired help requests can be acknowledged")
        self.app.logger.log(
            "expired_help_acknowledged",
            administrator=administrator,
            delivery_id=item_id,
            target=item["args"][0],
            created_at=item["created_at"],
        )
        entries.remove(item)
        self.app.save_state()

    def dismiss_reviewed_message(self, item_id, administrator):
        """Archive a reviewed chat notice; never discard records or asset writes.

        The protected UI requires external verification first. This records a
        dismissal, NOT proof of successful delivery; audit history is retained.
        """
        if self.app.busy:
            raise RuntimeError("Wait for the local operation to finish")
        entries = self.app.state.get("delivery_outbox", [])
        item = next((entry for entry in entries if entry["id"] == item_id), None)
        if not item or item["phase"] != "attention" or item["method"] != "send_message":
            raise RuntimeError("Only a held message can be dismissed after review")
        self.app.logger.log(
            "message_dismissed_after_review",
            administrator=administrator,
            delivery_id=item_id,
            target=item["args"][0],
            content=item["args"][1],
            created_at=item["created_at"],
            attempts=item["attempts"],
            last_error=item["error"],
            outcome="dismissed_not_confirmed",
        )
        entries.remove(item)
        self.app.save_state()

    def confirm_reviewed_asset(self, item_id, evidence, administrator):
        """Record a human-verified asset-history event without resending it."""
        if self.app.busy:
            raise RuntimeError("Wait for the local operation to finish")
        if (
            not isinstance(evidence, str)
            or not evidence.strip()
            or len(evidence) > 200
            or not evidence.isprintable()
        ):
            raise ValueError(
                "Enter the verified external asset-event ID or audit reference"
            )
        item = next(
            (
                entry
                for entry in self.app.state.get("delivery_outbox", [])
                if entry["id"] == item_id
            ),
            None,
        )
        if (
            not item
            or item["phase"] != "attention"
            or item["method"] != "set_asset_status"
        ):
            raise RuntimeError("Only a held asset event can be confirmed")
        remote = getattr(self.app.provider, "remote", None)
        if remote is None or not remote.connected or item["binding"] != binding(remote):
            raise RuntimeError(
                "Select the original connector before confirming its asset event"
            )
        self.app.logger.log(
            "delivery_asset_verified_by_administrator",
            delivery_id=item_id,
            asset_id=item["context"].get("asset_id", ""),
            evidence=evidence.strip(),
            administrator=administrator,
        )
        self._apply(item_id, {}, None, False)

    def link_reviewed_record(self, item_id, record_id, administrator):
        """Link a remotely verified creation instead of risking another POST."""
        if self.app.busy:
            raise RuntimeError("Wait for the local operation to finish")
        if (
            not isinstance(record_id, str)
            or not record_id.strip()
            or len(record_id) > 200
            or any(ord(c) < 32 for c in record_id)
            or record_id.startswith(LOCAL_PREFIX)
        ):
            raise ValueError("Enter the existing response record identifier")
        item = next(
            (
                entry
                for entry in self.app.state.get("delivery_outbox", [])
                if entry["id"] == item_id
            ),
            None,
        )
        if (
            not item
            or item["phase"] != "attention"
            or item["method"] != "create_response_record"
        ):
            raise RuntimeError("Only a held record creation can be linked")
        remote = getattr(self.app.provider, "remote", None)
        if (
            remote is None
            or not remote.connected
            or (item["binding"] and item["binding"] != binding(remote))
        ):
            raise RuntimeError(
                "Select the original connector before linking its record"
            )
        self.app.logger.log(
            "delivery_record_link_authorized",
            delivery_id=item_id,
            record_id=record_id,
            administrator=administrator,
        )
        self._apply(item_id, {"id": record_id.strip()}, None, False)
