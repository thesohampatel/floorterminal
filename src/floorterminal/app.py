"""Touchscreen application controller and production workflow UI."""

from __future__ import annotations

import platform
import queue
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from importlib.resources import as_file, files

from .audio import SoundManager
from .controller.dialogs import DialogMixin
from .controller.updates import SoftwareUpdateMixin
from .controller.workflow import WorkflowMixin
from .core.auth_throttle import PersistentAuthThrottle
from .core.clock import check_clock
from .core.config import (
    CONFIG_FILE,
    ConfigurationError,
    load_config,
)
from .core.project_profile import (
    ProjectProfileError,
    load_project_profile,
)
from .core.settings_auth import SettingsCredentials
from .i18n import load_translator
from .integration import discover_connectors
from .services import ExternalIntegration, NoIntegrationProvider
from .storage.audit import ActivityLogger
from .storage.state import StateIntegrityError, StateStore
from .ui.responsive import (
    DESIGN_HEIGHT,
    DESIGN_WIDTH,
    ResponsiveCanvas,
    fitted_window_geometry,
)
from .ui.settings import SettingsWindow
from .ui.view import RESPONDER_PAGE_SIZE, OperatorViewMixin
from .update import UpdateService


class FloorTerminalApp(WorkflowMixin, DialogMixin, SoftwareUpdateMixin, OperatorViewMixin):
    """Custom-drawn line reporting console optimized for touch and glanceability."""

    BG, CARD, TEXT, MUTED = "#F3F5F9", "#FFFFFF", "#14213D", "#718096"
    RED, GREEN, BLUE, ORANGE, PURPLE = (
        "#E84855",
        "#16A36A",
        "#246BFD",
        "#F09A3E",
        "#7956D8",
    )
    BORDER, PALE_BLUE = "#E3E8F1", "#EDF3FF"

    def __init__(self, root, project_profile=None):
        self.root = root
        self.project_profile = project_profile or load_project_profile()
        self.settings_credentials = SettingsCredentials(self.project_profile.settings_password_hash)
        self.config = load_config()
        self.t = load_translator(self.config.get("ui_language", "en"))
        colors = self.config["ui_colors"]
        self.BG, self.CARD, self.TEXT, self.MUTED = (
            colors["background"],
            colors["card"],
            colors["text"],
            colors["muted"],
        )
        self.RED, self.GREEN, self.BLUE = colors["red"], colors["green"], colors["blue"]
        self.ORANGE, self.PURPLE, self.BORDER = (
            colors["orange"],
            colors["purple"],
            colors["border"],
        )
        self.logger = ActivityLogger(self.config)
        self.sound = SoundManager(self.config, self.logger)
        self.brand_images = self._load_brand_images()
        # The update subsystem is additive: construction, reconciliation, and every
        # later operation are isolated so a damaged update directory can never stop
        # the console from reporting downtime.
        # Audit records, downtime durations, and update entries all carry the
        # system clock. A Raspberry Pi without a battery-backed clock can boot
        # with the wrong time, so the condition is made visible rather than left
        # to be discovered during an investigation. Workflow timers are monotonic
        # and unaffected, so nothing is blocked.
        self.clock_check = check_clock()
        if not self.clock_check.trusted:
            self.logger.log(
                "system_clock_suspect",
                "WARNING",
                reason=self.clock_check.reason,
                system_time_utc=self.clock_check.system_time_utc,
                reference_utc=self.clock_check.reference_utc,
            )
        self.update_service = UpdateService(self.config, self.logger)
        self.announced_update = ""
        try:
            self.update_service.prepare()
        except Exception as exc:
            self.logger.log("update_subsystem_unavailable", "WARNING", error=str(exc))
        try:
            self.state_store = StateStore()
        except StateIntegrityError as exc:
            self.logger.log("state_integrity_failed", "CRITICAL", error=str(exc))
            raise
        self.state = self.state_store.data
        self.events = queue.Queue()
        self.busy = False
        self.modal = None
        self.toast_text, self.toast_kind, self.toast_until = "", "info", 0
        self.animation_start = time.monotonic()
        self.pressed = None
        self.station_page = 0
        self.api_limit_warning_active = False
        self.storage_warning_active = False
        self.auth_throttle = PersistentAuthThrottle()
        self.retry_deadlines = {}
        self.escalation_deadline = None
        self.authorized_admin_identity = ""
        self.reload_connector()
        self.logger.log(
            "application_started",
            platform=platform.platform(),
            architecture=platform.machine(),
            python=platform.python_version(),
            tk_version=tk.TkVersion,
            windowing_system=str(root.tk.call("tk", "windowingsystem")),
            screen=f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}",
            state=self.state.get("status"),
            integration=self.provider.INFO.display_name,
            integration_ready=self.provider.connected,
        )

        root.title(f"{self.project_profile.product_name} • {self.provider.INFO.display_name}")
        root.configure(bg=self.BG)
        root.report_callback_exception = self.callback_error
        screen_width, screen_height = (
            root.winfo_screenwidth(),
            root.winfo_screenheight(),
        )
        ratio = 1.0 if platform.system() == "Linux" else 0.94
        width, height, x, y = fitted_window_geometry(
            screen_width, screen_height, ratio, ratio
        )
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.resizable(True, True)
        root.bind("<Escape>", self.request_windowed_access)
        root.bind("<F11>", self.request_fullscreen_toggle)
        root.bind("<Key>", self.on_keypress)
        root.protocol("WM_DELETE_WINDOW", self.close_application)
        self.canvas = ResponsiveCanvas(
            root,
            logical_width=DESIGN_WIDTH,
            logical_height=DESIGN_HEIGHT,
            width=width,
            height=height,
            bg=self.BG,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.set_viewport(width, height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.hitboxes = {}
        # Render before fullscreen, then repaint after the native window is mapped.
        # This avoids a blank first frame with Raspberry Pi display compositors.
        self.render()
        root.after_idle(self.finish_startup)
        self.poll_events()
        root.after(1200, self.check_storage_capacity)
        root.after(60_000, self.sync_pending_tick)
        root.after(30_000, self.escalation_tick)
        if self.provider.connected:
            threading.Thread(target=self.fetch_api_identity, daemon=True).start()

    def _load_brand_images(self):
        """Load fixed-size identity assets without depending on the launch directory."""
        images = {}
        try:
            package = files("floorterminal.assets.branding")
            for size in (32, 64, 128, 256):
                resource = package.joinpath(f"floorterminal-mark-{size}.png")
                with as_file(resource) as path:
                    images[size] = tk.PhotoImage(file=str(path))
        except (FileNotFoundError, ModuleNotFoundError, OSError, tk.TclError) as exc:
            self.logger.log("brand_asset_unavailable", "WARNING", error=str(exc))
        return images

    def reload_connector(self, logger=None):
        """Rescan deployment files and activate the safely selected connector."""
        self.connector_inventory = discover_connectors()
        active = self.connector_inventory.active
        active_logger = logger or getattr(self, "logger", None)
        # Inventory keeps disabled drafts visible in Settings, but their declared
        # capabilities must not advertise operational actions on the kiosk.
        if active and active.ready:
            self.provider = ExternalIntegration(
                self.config,
                active_logger,
                definition=active.definition,
            )
        else:
            self.provider = NoIntegrationProvider(self.config, active_logger)
        if hasattr(self, "root"):
            self.root.title(
                f"{self.project_profile.product_name} • {self.provider.INFO.display_name}"
            )
        return self.provider

    def on_canvas_resize(self, event):
        self.canvas.set_viewport(event.width, event.height)
        self.render()

    def fetch_api_identity(self):
        try:
            name = self.provider.load_identity()
            self.logger.log("api_identity_loaded", user_name=name or "Unavailable")
            self.events.put((True, name, self.identity_loaded))
        except Exception as exc:
            self.logger.log("api_identity_failed", "WARNING", error=str(exc))

    def identity_loaded(self, _name):
        self.render()

    def check_api_limit_warning(self):
        if not self.provider.limit or self.provider.remaining is None:
            return
        used = max(0, self.provider.limit - self.provider.remaining)
        ratio = used / self.provider.limit
        if ratio >= 0.90 and not self.api_limit_warning_active:
            self.api_limit_warning_active = True
            self.notify(
                f"{self.provider.INFO.display_name} API warning • {used}/{self.provider.limit} shared requests used",
                "error",
                10,
            )
            self.logger.log(
                "integration_limit_warning",
                "WARNING",
                used=used,
                limit=self.provider.limit,
                remaining=self.provider.remaining,
            )
        elif ratio < 0.90:
            self.api_limit_warning_active = False

    def check_storage_capacity(self):
        try:
            self.logger.prune()
            report = self.logger.storage_capacity()
            level = "INFO" if report["enough"] else "WARNING"
            self.logger.log("log_storage_capacity_checked", level, **report)
            if not report["enough"]:
                self.storage_warning_active = True
                self.notify(
                    f"LOW STORAGE • {report['free_mb']} MB free; {report['required_mb']} MB recommended",
                    "error",
                    15,
                )
            else:
                self.storage_warning_active = False
        except OSError as exc:
            self.logger.log(
                "log_storage_capacity_check_failed", "WARNING", error=str(exc)
            )
        finally:
            # Recheck during continuous multi-month operation without generating API traffic.
            self.root.after(6 * 60 * 60 * 1000, self.check_storage_capacity)

    def close_application(self):
        self.request_admin_access("exit")

    def _shutdown(self, administrator):
        self.logger.log(
            "application_stopped",
            state=self.state.get("status"),
            response_record_id=self.state.get("response_record_id"),
            authorized_by=administrator,
        )
        self.stop_update_service()
        self.sound.close()
        self.root.destroy()

    def request_windowed_access(self, _event=None):
        if bool(self.root.attributes("-fullscreen")):
            self.request_admin_access("windowed")
        return "break"

    def request_fullscreen_toggle(self, _event=None):
        purpose = (
            "windowed" if bool(self.root.attributes("-fullscreen")) else "fullscreen"
        )
        self.request_admin_access(purpose)
        return "break"

    def finish_startup(self):
        self.root.deiconify()
        self.root.lift()
        self.render()
        self.root.update_idletasks()
        if platform.system() == "Linux" and self.config.get(
            "fullscreen_on_linux", True
        ):
            self.root.after(150, lambda: self.root.attributes("-fullscreen", True))
        self.root.after(int(self.config.get("animation_interval_ms", 80)), self.animate)
        try:
            self.update_service.start()
        except Exception as exc:
            self.logger.log("update_subsystem_unavailable", "WARNING", error=str(exc))
        self.root.after(4000, self.update_watch_tick)
        if not getattr(self, "clock_check", None) or not self.clock_check.trusted:
            self.notify(
                "SYSTEM CLOCK • recorded times may be wrong until time "
                "synchronization succeeds",
                "error",
                20,
            )

    def callback_error(self, exc_type, exc_value, exc_traceback):
        """Never leave an unexplained white screen if a Tk callback fails."""
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        self.logger.log(
            "ui_callback_failed",
            "CRITICAL",
            error=str(exc_value),
            traceback="".join(
                traceback.format_exception(exc_type, exc_value, exc_traceback)
            ),
        )
        try:
            self.canvas.delete("all")
            self.canvas.configure(bg="#FDECEC")
            self.canvas.create_text(
                400,
                170,
                text="Application could not render",
                font=self.font(22, "bold"),
                fill=self.RED,
                anchor="center",
            )
            self.canvas.create_text(
                400,
                220,
                text=str(exc_value),
                font=self.font(11),
                fill=self.TEXT,
                width=650,
                anchor="center",
            )
            self.canvas.create_text(
                400,
                275,
                text="Copy the Terminal error and send it for support.",
                font=self.font(10),
                fill=self.MUTED,
                anchor="center",
            )
        except Exception:
            traceback.print_exc()

    def elapsed_seconds(self):
        status = self.state["status"]
        started = (
            self.state.get("repair_at")
            if status == "REPAIRING"
            else self.state.get("started_at")
        )
        return max(0, int(time.time() - (started or time.time())))

    def on_press(self, event):
        x, y = self.canvas.to_logical(event.x, event.y)
        for key, box in reversed(list(self.hitboxes.items())):
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                self.pressed = key
                break

    def on_keypress(self, event):
        if not self.modal or self.modal.get("kind") not in {"password", "text_input"}:
            return
        if event.keysym in ("Return", "KP_Enter"):
            (
                self.submit_admin_dialog()
                if self.modal["kind"] == "password"
                else self.submit_text_input()
            )
        elif event.keysym == "BackSpace":
            self.modal["value"] = self.modal["value"][:-1]
        elif (
            event.char
            and event.char.isprintable()
            and len(self.modal["value"]) < self.modal.get("max_length", 128)
        ):
            self.modal["value"] += event.char

    def on_release(self, event):
        x, y = self.canvas.to_logical(event.x, event.y)
        key = self.pressed
        self.pressed = None
        if not key or key not in self.hitboxes:
            return
        box = self.hitboxes[key]
        if not (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
            return
        if self.modal:
            if key == "cancel":
                modal_kind = self.modal.get("kind")
                return_modal = self.modal.get("return_modal")
                resume_settings = self.modal.get("resume_settings")
                self.modal = None
                if return_modal:
                    self.modal = return_modal
                if resume_settings:
                    resume_settings(False)
                self.logger.log(
                    "about_closed" if modal_kind == "about" else "dialog_cancelled",
                    dialog=modal_kind,
                )
            elif key.startswith("pwd_"):
                action = key.removeprefix("pwd_")
                if action.isdigit() and len(self.modal["value"]) < self.modal.get(
                    "max_length", 128
                ):
                    self.modal["value"] += chr(int(action))
                elif action == "shift":
                    self.modal["shift"] = not self.modal.get("shift", True)
                elif action == "back":
                    self.modal["value"] = self.modal["value"][:-1]
                elif action == "space" and len(self.modal["value"]) < self.modal.get(
                    "max_length", 128
                ):
                    self.modal["value"] += " "
                elif action == "enter":
                    (
                        self.submit_admin_dialog()
                        if self.modal["kind"] == "password"
                        else self.submit_text_input()
                    )
            elif key.startswith("update_"):
                self.handle_update_control(key.removeprefix("update_"))
            elif key.startswith("member_"):
                index = int(key.split("_")[1])
                page = self.modal.get("page", 0)
                member = self.modal["members"][page * RESPONDER_PAGE_SIZE + index]
                selected = self.modal["selected"]
                if member["id"] in selected:
                    selected.remove(member["id"])
                else:
                    selected.add(member["id"])
            elif key == "members_prev":
                self.modal["page"] = max(0, self.modal.get("page", 0) - 1)
            elif key == "members_next":
                pages = max(
                    1,
                    -(-len(self.modal["members"]) // RESPONDER_PAGE_SIZE),
                )
                self.modal["page"] = min(pages - 1, self.modal.get("page", 0) + 1)
            elif key == "members_search":
                previous = self.modal
                self.open_text_input(
                    "engineer_search",
                    "FILTER ENGINEERING TEAM",
                    "Enter all or part of a name",
                    previous.get("filter", ""),
                    return_modal=previous,
                    max_length=64,
                )
            elif key == "start_engineers":
                self.confirm_engineers()
            elif key == "planned_preventive":
                self.modal = None
                context = {
                    "kind": "planned",
                    "work_label": "Preventive Maintenance",
                    "work_type": "PREVENTIVE",
                }
                if (
                    self.provider.connected
                    and self.provider.INFO.supports_team_directory
                ):
                    self.load_engineers(context)
                else:
                    self.perform(
                        "Starting planned work…",
                        lambda: self.start_planned_work(
                            context["work_label"], context["work_type"], None, []
                        ),
                    )
            elif key == "planned_change":
                self.modal = None
                context = {
                    "kind": "planned",
                    "work_label": "Modification / Change",
                    "work_type": "OTHER",
                }
                if (
                    self.provider.connected
                    and self.provider.INFO.supports_team_directory
                ):
                    self.load_engineers(context)
                else:
                    self.perform(
                        "Starting planned work…",
                        lambda: self.start_planned_work(
                            context["work_label"], context["work_type"], None, []
                        ),
                    )
            elif key == "confirm":
                kind = self.modal.get("kind")
                self.modal = None
                if kind == "confirm_downtime":
                    self.logger.log("downtime_confirmation_accepted")
                    self.perform("Recording downtime…", self.report_downtime)
                else:
                    self.logger.log("completion_confirmation_accepted")
                    self.perform("Completing repair", self.finish_work)
            elif key.startswith("failure_"):
                action = key.removeprefix("failure_")
                selected = self.modal["selected"]
                if action.isdigit():
                    option = self.modal["options"][int(action)]
                    selected.remove(option) if option in selected else selected.add(
                        option
                    )
                elif action == "all":
                    selected.update(self.modal["options"])
                elif action == "clear":
                    selected.clear()
                elif action == "done":
                    self.save_failure_selection()
                elif action == "remove":
                    self.remove_failure_station()
            return
        if self.busy:
            return
        self.logger.log(
            "touch_action", control=key, machine_status=self.state.get("status")
        )
        if key == "about":
            self.modal = {"kind": "about"}
            self.logger.log("about_opened")
        elif key == "software_update":
            self.open_update_panel()
        elif key == "settings":
            self.request_settings_access()
        elif key == "primary":
            self.primary_action()
        elif key == "sync_pending":
            if self.state.get("pending_planned_work"):
                self.perform(
                    "Synchronizing planned work start…",
                    self.sync_pending_planned_work,
                )
            else:
                self.primary_action()
        elif key == "planned_work":
            self.open_planned_work()
        elif key == "crew":
            self.load_engineers({"kind": "edit"})
        elif key == "stations_prev":
            self.station_page = max(0, self.station_page - 1)
        elif key == "stations_next":
            self.station_page += 1
        elif key.startswith("zone_"):
            self.select_issue_zone(key.removeprefix("zone_"))
        elif key in ("engineering", "quality", "production"):
            self.call_team(key.title())

    def notify(self, text, kind="info", duration=4):
        self.toast_text, self.toast_kind, self.toast_until = (
            text,
            kind,
            time.monotonic() + duration,
        )
        if kind == "error":
            self.play_sound("error")

    def play_sound(self, cue):
        """Keep workflow methods testable when instantiated without the full GUI."""
        sound = getattr(self, "sound", None)
        return bool(sound and sound.play(cue))

    def log_event(self, text, color=None):
        self.state.setdefault("events", []).append(
            {
                "text": text,
                "time": datetime.now().astimezone().strftime("%H:%M"),
                "color": color or self.BLUE,
            }
        )
        self.state["events"] = self.state["events"][-8:]
        self.logger.log(
            "line_activity",
            activity=text,
            machine_status=self.state.get("status"),
        )

    def perform(self, working, function, on_success=None):
        if self.busy:
            return
        self.busy = True
        self.notify(working, "info", 15)
        self.logger.log("operation_started", operation=working)

        def worker():
            try:
                result = function()
                self.logger.log("operation_completed", operation=working, result=result)
                self.events.put((True, result, on_success))
            except Exception as exc:
                self.logger.log(
                    "operation_failed", "ERROR", operation=working, error=str(exc)
                )
                self.events.put((False, str(exc), None))

        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self):
        try:
            ok, result, callback = self.events.get_nowait()
            self.busy = False
            if ok and callback:
                callback(result)
            else:
                self.notify(str(result), "success" if ok else "error", 5)
        except queue.Empty:
            pass
        self.check_api_limit_warning()
        self.root.after(100, self.poll_events)

    def save_state(self):
        self.state_store.save()
        self.logger.log(
            "state_saved",
            machine_status=self.state.get("status"),
            response_record_id=self.state.get("response_record_id"),
        )

    @property
    def provider_name(self):
        return self.provider.INFO.display_name

    # ------------------------------------------------------------------
    # Software updates
    #
    # Every method here is defensive on purpose. The update subsystem is an
    # addition to a production terminal that already works, so a missing update
    # directory, an unreadable journal, a removed drive, or a blocked network can
    # only change what the panel reports.
    # ------------------------------------------------------------------

    def open_settings(self, directory=None):
        return SettingsWindow(
            self, directory or {"teams": [], "conversations": []}
        )


def main():
    root = tk.Tk()
    project_profile = None
    try:
        project_profile = load_project_profile()
        FloorTerminalApp(root, project_profile)
    except (ProjectProfileError, ConfigurationError, StateIntegrityError) as exc:
        print(f"Configuration error: {exc}")
        root.title(
            f"{project_profile.product_short_name if project_profile else 'Application'} • Configuration Required"
        )
        root.configure(bg="#F3F5F9")
        screen_width, screen_height = (
            root.winfo_screenwidth(),
            root.winfo_screenheight(),
        )
        width, height, x, y = fitted_window_geometry(
            screen_width, screen_height, 0.94, 0.94
        )
        root.geometry(f"{width}x{height}+{x}+{y}")
        panel = tk.Frame(
            root, bg="white", highlightthickness=1, highlightbackground="#E3E8F1"
        )
        panel.pack(fill="both", expand=True, padx=28, pady=28)
        project_profile_failure = isinstance(exc, ProjectProfileError)
        state_failure = isinstance(exc, StateIntegrityError)
        tk.Label(
            panel,
            text=(
                "BUILD PROFILE REQUIRED"
                if project_profile_failure
                else (
                    "STATE RECOVERY REQUIRED"
                    if state_failure
                    else "CONFIGURATION REQUIRED"
                )
            ),
            font=("Helvetica", 10, "bold"),
            fg="#E84855",
            bg="white",
        ).pack(pady=(38, 8))
        tk.Label(
            panel,
            text=(
                "Product build identity is invalid"
                if project_profile_failure
                else (
                    "Operational state cannot be trusted"
                    if state_failure
                    else "Production configuration is invalid"
                )
            ),
            font=("Helvetica", 20, "bold"),
            fg="#14213D",
            bg="white",
        ).pack()
        tk.Label(
            panel,
            text=str(exc),
            font=("Helvetica", 10),
            fg="#14213D",
            bg="#FFF0F1",
            justify="left",
            wraplength=max(120, int(width * 0.78)),
            padx=18,
            pady=16,
        ).pack(fill="x", padx=48, pady=24)
        guidance = (
            "Correct project_profile.json and rebuild the application; build identity is not editable at runtime."
            if project_profile_failure
            else (
                "Preserve response_state.json for investigation. An authorized administrator must repair or archive it before restart; the terminal will not silently assume the line is running."
                if state_failure
                else f"Correct {CONFIG_FILE} and restart the application. Use the exact validation message above."
            )
        )
        tk.Label(
            panel,
            text=guidance,
            font=("Helvetica", 10),
            fg="#718096",
            bg="white",
            justify="center",
        ).pack()
    root.mainloop()


if __name__ == "__main__":
    main()
