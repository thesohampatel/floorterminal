"""One bounded background archive writer; no filesystem work in animation."""

import queue
import threading
import time
from copy import deepcopy

from ..storage.history import IncidentArchive


class HistoryCoordinator:
    def __init__(self, app):
        self.app = app
        self.archive = IncidentArchive(app.state_store.path.parent / "records")
        self.results = queue.Queue(maxsize=1)
        self.active = False
        self.next_at = 0
        self.next_cleanup = 0
        self.health = {}
        self.closed = False
        self.worker = None
        self.ack_retry_at = 0

    def close(self, timeout=0.25):
        self.closed = True
        if self.worker:
            self.worker.join(timeout)

    def poll(self):
        if self.closed or self.app.busy or getattr(self.app, "_closing", False):
            return
        if time.monotonic() < self.ack_retry_at:
            return
        if self.active:
            try:
                records, links, report, error = self.results.get_nowait()
            except queue.Empty:
                return
            if not error:

                def acknowledged(success):
                    if success:
                        self.health = report or self.health
                        self.health.pop("error", None)
                        self.active = False
                        self.next_at = time.monotonic() + 5

                # A maintenance-only pass has no delivery intent to acknowledge.
                # Taking the operator lock and rewriting state here needlessly
                # blocks a touch at startup (and after each hourly cleanup).
                # Newly staged records/links remain untouched for the next pass.
                if not records and not links:
                    acknowledged(True)
                    return

                def acknowledge():
                    with self.app.state_store.transaction():
                        self.app.state["history_pending"] = [
                            r
                            for r in self.app.state.get("history_pending", [])
                            if r not in records
                        ]
                        self.app.state["history_links"] = {
                            key: value
                            for key, value in self.app.state.get(
                                "history_links", {}
                            ).items()
                            if links.get(key) != value
                        }
                    return True

                def failed(_error):
                    self.results.put_nowait((records, links, report, None))
                    self.ack_retry_at = time.monotonic() + 5

                # Durable acknowledgement can fsync on a slow SD card. It uses
                # the existing local-operation worker, never the Tk event loop.
                if not self.app.perform(
                    "Saving local history",
                    acknowledge,
                    acknowledged,
                    quiet=True,
                    on_error=failed,
                ):
                    failed(None)
                return
            else:
                self.health["error"] = str(error)
                self.next_cleanup = 0
                self.app.logger.log(
                    "local_history_unavailable", "WARNING", error=str(error)
                )
                self.app.notify(
                    "Local history storage needs attention • records remain in recovery state",
                    "error",
                    8,
                )
            self.active = False
            self.next_at = time.monotonic() + (30 if error else 5)
        if time.monotonic() < self.next_at:
            return
        # Staged records are replaced, not mutated. Capture a bounded batch of
        # references and detach their contents inside the writer thread.
        records = list(self.app.state.get("history_pending", [])[:32])
        links = deepcopy(self.app.state.get("history_links", {}))
        protected = {
            item["context"].get("incident_id")
            for item in self.app.state.get("delivery_outbox", [])
        }
        cleanup = time.monotonic() >= self.next_cleanup
        if not records and not links and not cleanup:
            return
        self.active = True
        if cleanup:
            self.next_cleanup = time.monotonic() + 3600

        def work():
            try:
                # Reclaim eligible old data before adding a batch. Failed writes
                # request maintenance again on the next backoff-limited attempt.
                if cleanup:
                    self.archive.store([])
                report = self.archive.maintain(protected=protected) if cleanup else {}
                self.archive.store(deepcopy(records), links)
                self.results.put((records, links, report, None))
            except Exception as exc:  # noqa: BLE001 - isolated background storage
                self.results.put((records, links, {}, exc))

        self.worker = threading.Thread(
            target=work, daemon=True, name="incident-history"
        )
        try:
            self.worker.start()
        except Exception as exc:  # noqa: BLE001 - retry if worker creation fails
            self.worker = None
            self.results.put((records, links, {}, exc))
