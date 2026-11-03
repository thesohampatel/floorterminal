"""Software-update controls presented on the touchscreen.

The subsystem itself lives in ``floorterminal.update``. This layer is
only the operator-facing half: opening the panel, routing its controls,
collecting administrator authorization, and handing control to the newly
active version. Every method is defensive, because an update fault must never
reach the production workflow.
"""

from __future__ import annotations

import os

from ..update import RESTART_EXEC, RESTART_UNSUPPORTED


class SoftwareUpdateMixin:
    def version_trial_active(self):
        service = getattr(self, "update_service", None)
        return bool(service and service.status().state == "probation")

    def version_change_blocker(self):
        """Keep the saved snapshot stable until the new process takes ownership."""
        if self.busy or getattr(self, "_version_change_pending", False):
            return "Wait for the current operation to finish"
        if any(
            getattr(getattr(self, name, None), "active", False)
            for name in ("delivery", "history")
        ):
            return "Wait for the background synchronization to finish, then retry"
        state = self.state
        if state.get("status") != "RUNNING" or state.get("parked_incidents"):
            return "Finish all active responses and resume production before changing versions"
        if any(
            state.get(key)
            for key in (
                "delivery_outbox",
                "pending_response_record",
                "pending_planned_work",
                "pending_response_status",
                "pending_participant_assignment",
                "pending_record_updates",
                "pending_messages",
                "asset_status_sync_pending",
                "history_pending",
                "history_links",
            )
        ):
            return "Finish synchronization and resolve saved updates before changing versions"
        return ""

    def stop_update_service(self):
        service = getattr(self, "update_service", None)
        if service is not None:
            service.stop()

    def open_update_panel(self, page="status", automatic=False):
        """Open the Software Update panel and request a fresh removable-media scan."""
        self.modal = {"kind": "update", "page": page}
        service = getattr(self, "update_service", None)
        if service is not None:
            service.request_scan()
        status = self.update_status()
        self.logger.log(
            "software_update_panel_opened",
            automatic=automatic,
            level=status.level,
            installed_version=status.installed_version,
            staged_version=status.staged.version if status.staged else "",
            latest_version=status.latest_version,
        )

    def handle_update_control(self, action):
        """Route one touch inside the Software Update panel."""
        if action.startswith("tab_"):
            page = action.removeprefix("tab_")
            self.modal["page"] = page
            return
        service = getattr(self, "update_service", None)
        if service is None:
            self.notify(
                "The update subsystem is unavailable on this terminal", "error", 6
            )
            return
        if action == "check":
            self.logger.log("software_update_check_requested")
            self.perform(
                "Checking for a newer version…",
                lambda: self.describe_update_check(service.check_channel(force=True)),
            )
        elif action == "scan":
            self.logger.log("software_update_scan_requested")
            self.perform(
                "Looking for an update drive…",
                lambda: self.describe_update_scan(service),
            )
        elif action in {"install", "rollback"}:
            self.request_update_authorization(action)

    def describe_update_check(self, status):
        if status.update_available:
            return f"Version {status.latest_version} is available"
        if status.level == "unknown":
            return "Update availability could not be checked"
        if status.level == "ok":
            return f"Version {status.installed_version} is up to date"
        return status.headline

    def describe_update_scan(self, service):
        """Scan every removable mount, including drives whose label was lost."""
        service.scan_media(labelled_only=False)
        status = service.refresh()
        if status.staged:
            return f"Version {status.staged.version} is verified and ready to install"
        if status.media_error:
            return f"Update drive rejected • {status.media_error}"
        return "No update drive with a verified package was found"

    def request_update_authorization(self, action):
        """Collect administrator identity and password before changing versions."""
        status = self.update_status()
        if action == "install" and not status.can_install:
            self.notify("No verified update is ready to install", "error", 6)
            return
        if action == "rollback" and not status.can_rollback:
            self.notify("No previous version is available on this terminal", "error", 6)
            return
        blocker = self.version_change_blocker()
        if blocker:
            self.notify(blocker, "error", 8)
            return
        page = self.modal.get("page", "status") if self.modal else "status"
        self.modal = None
        self.request_admin_access(
            "software_update" if action == "install" else "software_rollback"
        )
        if not self.modal:
            return
        self.modal["return_modal"] = {"kind": "update", "page": page}
        self.modal["update_selection"] = {
            "version": status.staged.version
            if action == "install"
            else status.rollback_version,
            "sha256": status.staged.artifact_sha256 if action == "install" else "",
        }
        selected_version = self.modal["update_selection"]["version"]
        self.modal["title"] = f"{action.upper()} VERSION {selected_version}"
        self.modal["prompt"] = (
            "Identify the administrator to authorize this version change."
        )
        machine_status = self.state.get("status", "RUNNING")
        self.logger.log(
            "software_update_authorization_requested",
            update_action=action,
            machine_status=machine_status,
            staged_version=status.staged.version if status.staged else "",
            rollback_version=status.rollback_version,
        )

    def install_software_update(self, administrator, selection=None):
        """Activate the verified staged version after successful authorization."""
        service = getattr(self, "update_service", None)
        status = self.update_status()
        if service is None or not status.can_install or not selection:
            self.notify("No verified update is ready to install", "error", 8)
            return

        def change():
            return service.install_staged(
                authorized_by=administrator,
                expected_version=selection["version"],
                expected_sha256=selection["sha256"],
            )

        self.run_version_change(change, administrator)

    def restore_previous_version(self, administrator, selection=None):
        """Switch back to a previously installed version after authorization."""
        service = getattr(self, "update_service", None)
        status = self.update_status()
        if service is None or not status.can_rollback or not selection:
            self.notify("No previous version is available on this terminal", "error", 8)
            return

        def change():
            return service.rollback(
                authorized_by=administrator, target=selection["version"]
            )

        self.run_version_change(change, administrator)

    def run_version_change(self, change, administrator):
        blocker = self.version_change_blocker()
        if blocker:
            self.notify(blocker, "error", 8)
            return
        self._version_change_pending = True

        def work():
            # A failed save must never occur AFTER the executable is selected.
            self.save_state()
            return change()

        def failed(_error):
            self._version_change_pending = False

        def done(result):
            self.logger.log(
                "software_version_changed",
                from_version=result.from_version,
                to_version=result.to_version,
                administrator=administrator,
            )
            self.finish_version_change(result, f"Version {result.to_version} selected")

        if not self.perform(
            "Checking saved data and preparing the version change…",
            work,
            done,
            on_error=failed,
            transactional=False,
        ):
            self._version_change_pending = False

    def finish_version_change(self, result, summary):
        """Persist state and hand control to the newly active version."""
        self.modal = None
        mechanism = self.update_service.restart_mechanism()
        if mechanism == RESTART_UNSUPPORTED:
            self._version_change_pending = False
            self.notify(
                f"{summary} • restart this terminal to run it",
                "success",
                25,
            )
            self.logger.log(
                "software_update_restart_deferred",
                to_version=result.to_version,
                reason="no supervisor and not a frozen application",
            )
            return
        # No report, Settings save or background acknowledgement may race the
        # version change during the short visible restart countdown.
        self.busy = True
        self.busy_message = "Restarting into the selected version…"
        self.notify(f"{summary} • restarting now", "success", 8)
        self.logger.log(
            "software_update_restart_scheduled",
            to_version=result.to_version,
            mechanism=mechanism,
        )
        self.root.after(1500, lambda: self.restart_into_active_version(mechanism))

    def restart_into_active_version(self, mechanism):
        """Leave this process so the supervisor or exec starts the active version."""
        self.logger.log(
            "application_restarting_for_update",
            mechanism=mechanism,
            state=self.state.get("status"),
        )
        self.stop_update_service()
        self.sound.close()
        target = str(self.update_service.layout.active_link)
        self.root.destroy()
        if mechanism == RESTART_EXEC:
            os.execv(target, [target])

    def update_watch_tick(self):
        """Announce a newly verified update drive without interrupting the workflow."""
        try:
            status = self.update_status()
            trial = status.state == "probation"
            if trial and not getattr(self, "_trial_announced", False):
                self._trial_announced = True
                self.open_update_panel("status", automatic=True)
                self.notify(
                    "Version health check • reporting resumes after confirmation",
                    "info",
                    10,
                )
            elif not trial and getattr(self, "_trial_announced", False):
                self._trial_announced = False
                self.notify("Version confirmed • reporting is ready", "success", 8)
            staged = status.staged.version if status.staged else ""
            if staged and staged != self.announced_update:
                self.announced_update = staged
                self.logger.log(
                    "software_update_ready",
                    version=staged,
                    signing_key_id=status.staged.signing_key_id,
                    source=status.staged.source_mount,
                )
                self.notify(
                    f"Software update {staged} verified • open the update button to install",
                    "success",
                    20,
                )
                if (
                    not self.modal
                    and not self.busy
                    and not getattr(self, "settings_visible", False)
                ):
                    self.open_update_panel("changes", automatic=True)
            elif not staged and self.announced_update:
                self.announced_update = ""
        except Exception as exc:
            self.logger.log("software_update_watch_failed", "WARNING", error=str(exc))
        finally:
            self.root.after(3000, self.update_watch_tick)
