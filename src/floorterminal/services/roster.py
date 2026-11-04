"""One durable daily roster, sharing the existing delivery worker and API budget.

No network/storage work runs on Tk. Roster replacement is atomic and complete;
an unavailable directory never erases the last verified names.
"""

import json
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime

from ..core.roster import IDLE_SECONDS, daily_due, next_midnight
from ..integration.runtime import IntegrationError
from ..storage.delivery import binding
from ..storage.incidents import all_incidents
from ..storage.state import StateSaveError


class RosterCoordinatorMixin:
    def init_roster(self):
        self.roster_requested = False
        self.roster_retry_at = 0.0
        self._roster_deadline_stamp = None
        self._roster_attempt = None
        self._roster_started = time.monotonic()

    def _roster_matches(self, record):
        remote = getattr(self.app.provider, "remote", None)
        return bool(
            record
            and remote is not None
            and record.get("binding") == binding(remote)
            and record.get("team_name")
            == self.app.config.get("engineering_team_name", "")
        )

    def cached_roster(self):
        cached = self.app.state.get("roster_cache", {})
        return cached if self._roster_matches(cached) else {}

    def roster_sync(self):
        sync = self.app.state.get("roster_refresh", {})
        return sync if self._roster_matches(sync) else {}

    def request_roster(self):
        """Coalesce explicit requests; never bypass the shared API cooldown."""
        if self.app.version_trial_active() or getattr(
            self.app, "_version_change_pending", False
        ):
            return "Wait for software-version verification to finish before refreshing the team."
        remote = getattr(self.app.provider, "remote", None)
        team = self.app.config.get("engineering_team_name", "")
        if (
            self.closed
            or remote is None
            or not remote.connected
            or not remote.INFO.supports_team_directory
        ):
            return "The active connector has no available team directory. Saved names are retained."
        if (
            not isinstance(team, str)
            or not team.strip()
            or len(team) > 120
            or not team.isprintable()
        ):
            return "Save a valid Engineering assignment team in Settings first."
        if self.active == "roster" or self.roster_requested:
            return (
                "Team refresh is already queued or running; saved names remain usable."
            )
        sync = deepcopy(self.roster_sync())
        if not sync.get("pending"):
            sync = {
                "binding": binding(remote),
                "team_name": team,
                "attempted_at": 0,
                "retry_at": 0
                if sync.get("error") == "configuration"
                else sync.get("retry_at", 0),
                "failures": 0,
                "pending": True,
                "manual": True,
                "error": "",
            }
        else:
            sync["manual"] = True

        def save():
            self.app.state["roster_refresh"] = sync
            self.app.save_state()

        def saved(_result):
            self.roster_requested = True

        if not self.app.perform("Saving team refresh request", save, saved, quiet=True):
            return "Wait for the current operation, then request a team refresh."
        return "Team refresh queued in the background; saved names remain usable."

    def _roster_idle(self):
        return (
            not (
                any(all_incidents(self.app.state))
                or self.app.state.get("issue_zones")
                or self.app.state.get("delivery_outbox")
                or self.app.modal
                or getattr(self.app, "settings_visible", False)
                or getattr(self.app, "error_panel", None)
                or getattr(self.app, "render_blocked", False)
            )
            and time.monotonic()
            - getattr(self.app, "last_operator_activity", self._roster_started)
            >= IDLE_SECONDS
        )

    def _poll_roster(self, remote):
        team = self.app.config.get("engineering_team_name", "")
        if (
            not remote.INFO.supports_team_directory
            or not isinstance(team, str)
            or not team.strip()
            or len(team) > 120
            or not team.isprintable()
            or self.app.config.get("reporting_mode") == "local"
            or self.app.version_trial_active()
            or getattr(self.app, "_version_change_pending", False)
        ):
            return
        sync, cached = self.roster_sync(), self.cached_roster()
        # A manual retry accepted before a restart remains explicit. Automatic
        # retries, including first installation, still wait for an idle kiosk.
        explicit = self.roster_requested or bool(
            sync.get("pending") and sync.get("manual")
        )
        if not explicit:
            if not self._roster_idle():
                return
            if (
                cached
                and not daily_due(cached["saved_at"], time.time())
                and not sync.get("pending")
            ):
                return
        stamp = (sync.get("binding"), sync.get("team_name"), sync.get("retry_at"))
        if stamp != self._roster_deadline_stamp:
            self._roster_deadline_stamp = stamp
            self.roster_retry_at = time.monotonic() + max(
                0, sync.get("retry_at", 0) - time.time()
            )
        # The persisted retry deadline cannot be defeated by repeated touches.
        if time.monotonic() < self.roster_retry_at:
            return
        self._start_roster(remote, manual=explicit)

    def _start_roster(self, original, *, manual=False):
        prior = self.roster_sync()
        attempt = {
            "binding": binding(original),
            "team_name": self.app.config.get("engineering_team_name", ""),
            "attempted_at": time.time(),
            "retry_at": time.time() + 60,
            "failures": prior.get("failures", 0),
            "pending": True,
            "manual": manual,
            "error": "interrupted",
        }
        self.active = "roster"

        def prepare():
            remote = self.provider_factory(
                deepcopy(original.config),
                self.app.logger,
                definition=original.definition,
            )
            remote.name_cache = deepcopy(original.name_cache)
            remote.directory_progress = deepcopy(
                getattr(original, "directory_progress", {})
            )
            # A new refresh revalidates the team too. A quota-paused attempt
            # retains successful pages so a low-budget terminal can finish.
            if not prior.get("pending") or not prior.get("attempted_at"):
                remote.directory_progress = {
                    key: value
                    for key, value in remote.directory_progress.items()
                    if json.loads(key)[0] not in {"teams", "members"}
                }
                remote.name_cache["team"] = {}
            remote.client.bind_request_window(self.app._api_request_window)
            remote.client.max_attempts_override = 1
            self.app.state["roster_refresh"] = attempt
            self.app.save_state()
            return remote

        def failed(error):
            if error is None or isinstance(error, StateSaveError):
                self.active = None
                self.ack_retry_at = time.monotonic() + 5
            else:
                self._roster_attempt = deepcopy(attempt)
                self.results.put(("roster", None, error))

        def dispatch(remote):
            self.roster_requested = False
            self._roster_attempt = deepcopy(attempt)
            if self.closed:
                self.active = None
                return

            def worker():
                try:
                    team_id = remote.resolve_name("team", attempt["team_name"])
                    if not self._roster_identifier(team_id):
                        raise IntegrationError(
                            "Team identifier is invalid", "INVALID_RESPONSE"
                        )
                    members, seen = [], set()
                    for member in remote.team_members(team_id):
                        identifier = member.get("id")
                        if (
                            not self._roster_identifier(identifier)
                            or str(identifier) in seen
                        ):
                            raise IntegrationError(
                                "Team directory has invalid or duplicate IDs",
                                "INVALID_RESPONSE",
                            )
                        name = (
                            str(member.get("displayName") or "").strip()
                            or f"{member.get('firstName') or ''} {member.get('lastName') or ''}".strip()
                            or f"User #{identifier}"
                        )
                        members.append(
                            {"id": str(identifier), "displayName": name[:200]}
                        )
                        seen.add(str(identifier))
                    if (
                        len(members) > 1000
                        or len(json.dumps(members).encode()) > 120 * 1024
                    ):
                        raise IntegrationError(
                            "Team directory exceeds safe cache capacity; narrow its scope",
                            "INVALID_RESPONSE",
                        )
                    roster = {
                        "binding": attempt["binding"],
                        "team_name": attempt["team_name"],
                        "team_id": team_id,
                        "members": members,
                        "saved_at": time.time(),
                    }
                    outcome = ("roster", roster, None)
                except Exception as exc:  # noqa: BLE001 - optional read worker boundary
                    outcome = ("roster", None, exc)
                finally:
                    original.name_cache = deepcopy(remote.name_cache)
                    original.directory_progress = deepcopy(remote.directory_progress)
                self.results.put(outcome)

            try:
                threading.Thread(
                    target=worker, name="team-directory", daemon=True
                ).start()
            except Exception as exc:  # noqa: BLE001 - optional worker startup
                self.results.put(
                    (
                        "roster",
                        None,
                        IntegrationError(
                            f"Team refresh worker unavailable: {type(exc).__name__}",
                            "UNAVAILABLE",
                        ),
                    )
                )

        if not self.app.perform(
            "Preparing team refresh", prepare, dispatch, quiet=True, on_error=failed
        ):
            failed(None)

    @staticmethod
    def _roster_identifier(value):
        return (
            not isinstance(value, bool)
            and isinstance(value, (str, int))
            and bool(str(value).strip())
            and len(str(value)) <= 200
        )

    def _acknowledge_roster(self, roster, error):
        attempt = self._roster_attempt
        if not self._roster_matches(attempt):
            return  # A changed connector/team must never adopt an old result.
        sync = deepcopy(attempt)
        if not error:
            self.app.state["roster_cache"] = roster
            sync.update(pending=False, retry_at=0, failures=0, error="")
        else:
            temporary = isinstance(error, IntegrationError) and (
                error.status == 429
                or error.code in {"UNAVAILABLE", "RATE_LIMITED"}
                or error.status is not None
                and error.status >= 500
            )
            failures = min(32, sync["failures"] + 1)
            delay = max(30, min(3600, 30 * 2 ** min(failures - 1, 7)))
            if temporary:
                delay = max(delay, error.retry_after or 0)
            sync.update(
                pending=temporary,
                failures=failures,
                retry_at=time.time() + delay
                if temporary
                else next_midnight(time.time()),
                error=(
                    "rate_limited"
                    if error.code == "RATE_LIMITED" or error.status == 429
                    else "unavailable"
                )
                if temporary
                else "configuration",
            )
        self.app.state["roster_refresh"] = sync
        self.app.save_state()

    def _roster_received(self, roster, error):
        if not self._roster_matches(self._roster_attempt):
            return
        sync = self.roster_sync()
        self.roster_requested = bool(sync.get("pending") and sync.get("manual"))
        self._roster_deadline_stamp = None
        self.app.logger.log(
            "roster_refresh_deferred" if error else "roster_refreshed",
            "WARNING" if error else "INFO",
            reason=sync.get("error", ""),
            member_count=len(roster["members"]) if roster else None,
        )
        if self.app.modal and self.app.modal.get("kind") == "offline_crew":
            if not error and roster and roster["members"]:
                self.app.load_engineers(self.app.modal["context"])
            else:
                self.app.modal["message"] = self.roster_status()
        if hasattr(self.app, "root"):
            self.app.request_render()

    def roster_status(self):
        cached, sync = self.cached_roster(), self.roster_sync()
        prefix = "No verified team list saved for this connection."
        if cached:
            try:
                stamp = (
                    datetime.fromtimestamp(cached["saved_at"], UTC)
                    .astimezone()
                    .strftime("%d %b %Y %H:%M")
                )
            except (ValueError, OSError, OverflowError):
                stamp = "unknown time — check the system clock"
            count = len(cached["members"])
            prefix = (
                f"{count} saved member{'s' if count != 1 else ''} • refreshed {stamp}."
            )
            if daily_due(cached["saved_at"], time.time()):
                prefix += " Using the last verified list until refresh succeeds."
        remote = getattr(self.app.provider, "remote", None)
        if (
            remote is None
            or not remote.connected
            or not remote.INFO.supports_team_directory
        ):
            return (
                prefix
                + " Enable a connector with a team-directory capability to refresh names."
            )
        if self.active == "roster":
            return prefix + " Refreshing in the background…"
        if sync.get("error") == "configuration":
            return (
                prefix
                + " Refresh needs review: check connector, permissions, team name and directory capacity."
            )
        if self.roster_requested or sync.get("pending"):
            return (
                prefix
                + " Refresh queued; waiting for connection/API budget or an idle kiosk."
            )
        return (
            prefix
            + " Automatic refresh after midnight when idle; no reads on normal crew selection."
        )
