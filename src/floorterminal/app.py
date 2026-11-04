"""Touchscreen application controller and production workflow UI."""

from __future__ import annotations

import platform
import queue
import threading
import time
import tkinter as tk
import traceback
from contextlib import nullcontext
from datetime import datetime
from importlib.resources import as_file, files

from .audio import SoundManager
from .controller.dialogs import DialogMixin
from .controller.groups import GroupWorkflowMixin
from .controller.operator import OperatorResponseMixin
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
from .core.rate_policy import RequestWindow, request_budget
from .core.settings_auth import SettingsCredentials
from .i18n import load_translator
from .integration import discover_connectors
from .services import ExternalIntegration, NoIntegrationProvider
from .services.delivery import DeferredIntegration, DeliveryCoordinator
from .services.history import HistoryCoordinator
from .storage.audit import ActivityLogger
from .storage.state import StateIntegrityError, StateSaveError, StateStore
from .ui.panels import AppPanel
from .ui.responsive import (
    ResponsiveCanvas,
    fitted_window_geometry,
)
from .ui.settings import SettingsWindow
from .ui.view import OperatorViewMixin
from .update import UpdateService

#: Tk sizes fonts in points and converts them with the X server's reported DPI.
#: Logical layout units and point-based font metrics share a 96 DPI baseline; X11 displays are
#: pinned to it; otherwise a panel reporting its physical size (for example a
#: 7-inch DSI display at ~130 DPI) enlarges every label relative to its shape.
DESIGN_POINTS_PER_PIXEL = 96 / 72

#: Human-readable names for touch controls, used when an action fails so the
#: operator and the audit log identify the operation instead of a generic error.
CONTROL_DESCRIPTIONS = {
    "primary": "Main workflow action",
    "operator_self_fix": "Choosing operator self-fix",
    "operator_name": "Recording the operator name",
    "operator_start": "Starting operator self-fix",
    "operator_options": "Opening operator response options",
    "operator_help": "Requesting Engineering for this incident",
    "operator_arrived": "Handing this incident to Engineering",
    "operator_done": "Completing operator self-fix",
    "confirm": "Confirmation",
    "cancel": "Closing a dialog",
    "start_engineers": "Confirming the Engineering crew",
    "crew": "Updating the Engineering crew",
    "planned_work": "Opening planned Engineering work",
    "planned_preventive": "Starting preventive maintenance",
    "planned_change": "Starting a modification or change",
    "sync_pending": "Synchronizing queued updates",
    "settings": "Opening Settings",
    "about": "Opening Software Information",
    "software_update": "Opening Software Update",
    "engineering": "Calling Engineering",
    "quality": "Calling Quality",
    "production": "Calling Production",
    "zone_all": "Selecting the entire line",
    "failure_done": "Saving failure details",
    "failure_remove": "Deselecting a station",
    "failure_all": "Selecting all failure types",
    "failure_clear": "Clearing failure types",
    "failure_report": "Reporting the selected station faults",
    "failure_self_fix": "Starting operator self-fix for the selected faults",
    "members_mode": "Choosing single or multiple crew selection",
    "members_search": "Filtering the Engineering team",
    "operator_details": "Adding optional operator details",
    "operator_request": "Requesting Engineering for the active incident",
    "operator_join": "Recording Engineering arrival",
    "stations_prev": "Paging stations",
    "stations_next": "Paging stations",
    "pwd_enter": "Submitting the keyboard entry",
    "error_dismiss": "Closing the error message",
}
CONTROL_PREFIXES = (
    ("zone_", "Selecting a station"),
    ("failure_", "Choosing a failure type"),
    ("member_", "Selecting an engineer"),
    ("pwd_", "Typing on the touch keyboard"),
    ("update_", "Using the Software Update panel"),
)


def describe_control(key):
    if key in CONTROL_DESCRIPTIONS:
        return CONTROL_DESCRIPTIONS[key]
    for prefix, description in CONTROL_PREFIXES:
        if str(key).startswith(prefix):
            return description
    return f"Touch control {key!r}" if key else "Screen update"


class FloorTerminalApp(
    GroupWorkflowMixin,
    OperatorResponseMixin,
    WorkflowMixin,
    DialogMixin,
    SoftwareUpdateMixin,
    OperatorViewMixin,
):
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
        self.settings_credentials = SettingsCredentials(
            self.project_profile.settings_password_hash
        )
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
        self.logger = ActivityLogger(self.config, background=True)
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
        self.error_panel = None
        self.render_blocked = False
        self.ui_context = ""
        self.toast_text, self.toast_kind, self.toast_until = "", "info", 0
        self.animation_start = time.monotonic()
        self.last_operator_activity = time.monotonic()
        self.pressed = None
        self.station_page = 0
        self.api_limit_warning_active = False
        self.storage_warning_active = False
        self.auth_throttle = PersistentAuthThrottle()
        self.retry_deadlines = {}
        self.escalation_deadline = None
        self.authorized_admin_identity = ""
        self.reload_connector()
        self.delivery = DeliveryCoordinator(self)
        self.migrate_active_scope()
        self.validate_active_topology()
        self.history = HistoryCoordinator(self)
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

        root.title(
            f"{self.project_profile.product_name} • {self.provider.INFO.display_name}"
        )
        root.configure(bg=self.BG)
        self.font_scaling = self.pin_font_scaling(root)
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
        root.bind("<ButtonPress-1>", self.note_operator_activity, add="+")
        root.protocol("WM_DELETE_WINDOW", self.close_application)
        self.canvas = ResponsiveCanvas(
            root,
            width=width,
            height=height,
            bg=self.BG,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.aa_backdrop = self.BG
        self.canvas.adaptive = True
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

    def pin_font_scaling(self, root):
        """Make text size independent of the display's reported DPI on X11."""
        try:
            original = float(root.tk.call("tk", "scaling"))
            if str(root.tk.call("tk", "windowingsystem")) != "x11":
                return original
            if abs(original - DESIGN_POINTS_PER_PIXEL) > 0.01:
                root.tk.call("tk", "scaling", DESIGN_POINTS_PER_PIXEL)
                self.logger.log(
                    "display_font_scaling_pinned",
                    reported_pixels_per_point=round(original, 4),
                    applied_pixels_per_point=round(DESIGN_POINTS_PER_PIXEL, 4),
                )
            return DESIGN_POINTS_PER_PIXEL
        except (tk.TclError, ValueError) as exc:
            self.logger.log(
                "display_font_scaling_unavailable", "WARNING", error=str(exc)
            )
            return None

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
        if not hasattr(self, "_api_request_window"):
            self._api_request_window = RequestWindow()
        self.connector_inventory = discover_connectors()
        active = self.connector_inventory.active
        connection = (
            active.definition.data["connection"] if active and active.definition else {}
        )
        self._api_request_window.set_budget(request_budget(self.config, connection))
        active_logger = logger or getattr(self, "logger", None)
        # Inventory keeps disabled drafts visible in Settings, but their declared
        # capabilities must not advertise operational actions on the kiosk.
        if (
            active
            and active.ready
            and self.config.get("reporting_mode", "connected") != "local"
        ):
            self.provider = ExternalIntegration(
                self.config,
                active_logger,
                definition=active.definition,
            )
        else:
            self.provider = NoIntegrationProvider(self.config, active_logger)
        # A Settings save or connector switch must not reset this terminal's
        # rolling request window. Old in-flight clients keep the same lock/deque.
        client = getattr(self.provider, "client", None)
        if client is not None:
            client.bind_request_window(self._api_request_window)
        if hasattr(self, "state_store"):
            self.provider = DeferredIntegration(self, self.provider)
        if hasattr(self, "root"):
            self.root.title(
                f"{self.project_profile.product_name} • {self.provider.INFO.display_name}"
            )
        return self.provider

    def on_canvas_resize(self, event):
        # A touch spanning a resize must not activate a newly repositioned item.
        self.pressed = None
        self.touch_feedback = None
        self.canvas.set_viewport(event.width, event.height)
        self.request_render()

    def request_render(self):
        """Coalesce main-thread input/resize events into one immediate repaint."""
        if getattr(self, "_closing", False):
            return
        if getattr(self, "_render_after", None) is not None:
            return

        def repaint():
            self._render_after = None
            self.safe_render()
            # A static sheet's one-second fallback must not strand a newly
            # accepted touch ring or busy indicator. Wake the existing timer,
            # never create a second animation chain.
            scheduled = getattr(self, "_animation_after", None)
            if scheduled is not None and (
                getattr(self, "touch_feedback", None)
                or self.busy
                or time.monotonic() < getattr(self, "_page_transition_until", 0)
            ):
                self.root.after_cancel(scheduled)
                self._animation_after = self.root.after(
                    int(self.config.get("animation_interval_ms", 33)), self.animate
                )

        if hasattr(getattr(self, "root", None), "after_idle"):
            self._render_after = self.root.after_idle(repaint)

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
        if getattr(self, "_closing", False):
            return
        # One background job owns maintenance; it never owns the UI busy flag.
        if getattr(self, "_storage_check_running", False):
            self.root.after(60_000, self.check_storage_capacity)
            return
        self._storage_check_running = True
        logger = self.logger

        def worker():
            report = None
            try:
                logger.prune()
                report = logger.storage_capacity()
                from .services.health import system_observations

                report["system"] = system_observations()
                logger.log(
                    "log_storage_capacity_checked",
                    "INFO" if report["enough"] else "WARNING",
                    **report,
                )
            except Exception as exc:
                logger.log(
                    "log_storage_capacity_check_failed", "WARNING", error=str(exc)
                )
                report = {
                    "check_error": "Automatic storage checks are unavailable; check device storage and permissions"
                }
            finally:
                self.events.put((True, report, self._storage_capacity_checked))

        try:
            threading.Thread(target=worker, name="device-care", daemon=True).start()
        except (OSError, RuntimeError):
            self._storage_check_running = False
            self._storage_capacity_checked(
                {
                    "check_error": "Automatic storage checks could not start; retrying in one minute"
                }
            )
        finally:
            self.root.after(60_000, self.check_storage_capacity)

    def _storage_capacity_checked(self, report):
        self._storage_check_running = False
        if report is None:
            return
        previous = getattr(self, "health_snapshot", {})
        self.health_snapshot = report
        if report.get("check_error"):
            if previous.get("check_error") != report["check_error"]:
                self.notify(f"DEVICE CARE • {report['check_error']}", "error", 10)
            return
        was_low = getattr(self, "storage_warning_active", False)
        self.storage_warning_active = not report["enough"]
        if not report["enough"] and not was_low:
            self.notify(
                f"LOW STORAGE • {report['free_mb']} MB free; {report['required_mb']} MB recommended",
                "error",
                15,
            )
        warnings = report.get("system", {}).get("warnings", [])
        warning = report.get("audit_error") or (warnings[0] if warnings else "")
        previous_warnings = previous.get("system", {}).get("warnings", [])
        previous_warning = previous.get("audit_error") or (
            previous_warnings[0] if previous_warnings else ""
        )
        if warning and warning != previous_warning and report["enough"]:
            self.notify(f"DEVICE CARE • {warning}", "error", 10)

    def close_application(self):
        if self._close_settings_panel():
            return
        self.request_admin_access("exit")
        self.request_render()

    def _close_settings_panel(self):
        """Close only the top app-owned page; never reveal the desktop."""
        if not getattr(self, "settings_visible", False):
            return False
        current = self.root.grab_current()
        if isinstance(current, AppPanel):
            current.destroy()
        else:
            self.settings_window.win.destroy()
        return True

    def _shutdown(self, administrator):
        if getattr(self, "history", None):
            self.history.close()
        if getattr(self, "delivery", None):
            self.delivery.close()
        self._closing = True
        for name in ("_animation_after", "_render_after"):
            callback = getattr(self, name, None)
            if callback is not None:
                self.root.after_cancel(callback)
                setattr(self, name, None)
        self.logger.log(
            "application_stopped",
            state=self.state.get("status"),
            response_record_id=self.state.get("response_record_id"),
            authorized_by=administrator,
        )
        self.stop_update_service()
        self.sound.close()
        self.logger.close()
        self.root.destroy()

    def request_windowed_access(self, _event=None):
        if self._close_settings_panel():
            return "break"
        if bool(self.root.attributes("-fullscreen")):
            self.request_admin_access("windowed")
            self.request_render()
        return "break"

    def request_fullscreen_toggle(self, _event=None):
        if getattr(self, "settings_visible", False):
            return "break"
        purpose = (
            "windowed" if bool(self.root.attributes("-fullscreen")) else "fullscreen"
        )
        self.request_admin_access(purpose)
        self.request_render()
        return "break"

    def finish_startup(self):
        if self.version_trial_active():
            self.modal = {"kind": "update", "page": "status"}
            self._trial_announced = True
        self.root.deiconify()
        self.root.lift()
        self.render()
        self.root.update_idletasks()
        if platform.system() == "Linux" and self.config.get(
            "fullscreen_on_linux", True
        ):
            self.root.after(150, lambda: self.root.attributes("-fullscreen", True))
        self._animation_after = self.root.after(
            int(self.config.get("animation_interval_ms", 33)), self.animate
        )
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
        """Report an unexpected Tk callback failure without losing the screen.

        The explanation is part of the rendered frame, so the animation loop
        cannot paint over it; it stays until the operator dismisses it.
        """
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        context = getattr(self, "ui_context", "") or "Screen update"
        self.logger.log(
            "ui_callback_failed",
            "CRITICAL",
            context=context,
            error=f"{exc_type.__name__}: {exc_value}",
            traceback="".join(
                traceback.format_exception(exc_type, exc_value, exc_traceback)
            ),
        )
        self.show_error_panel(
            context,
            exc_value
            if isinstance(exc_value, Exception)
            else RuntimeError(str(exc_value)),
            unexpected=True,
        )
        self.safe_render()

    def show_error_panel(self, operation, error, *, unexpected=False):
        """Show a persistent, specific explanation of a failed operation."""
        operation = str(operation or "Operation").strip().rstrip("….").strip()
        message = " ".join(str(error).split()) or error.__class__.__name__
        if isinstance(error, StateSaveError):
            title = "Line state could not be saved"
        elif unexpected:
            title = "Unexpected interface error"
        else:
            title = f"{operation} did not finish"
        self.error_panel = {
            "title": title,
            "operation": operation,
            "message": message if len(message) <= 320 else message[:319] + "…",
            "state_failure": isinstance(error, StateSaveError),
            "time": datetime.now().astimezone().strftime("%H:%M:%S"),
        }
        self.play_sound("error")

    def dismiss_error_panel(self):
        panel = self.error_panel
        self.error_panel = None
        self.render_blocked = False
        if panel:
            self.logger.log(
                "error_message_acknowledged",
                operation=panel.get("operation"),
                title=panel.get("title"),
            )

    def safe_render(self):
        """Render, or fall back to a static explanation if drawing itself fails."""
        try:
            self.render()
            self.render_blocked = False
        except Exception as exc:
            self.render_blocked = True
            self.logger.log(
                "ui_render_failed",
                "CRITICAL",
                error=f"{exc.__class__.__name__}: {exc}",
                traceback=traceback.format_exc(),
            )
            self.draw_static_error(exc)

    def draw_static_error(self, exc):
        """Minimal drawing used only when the normal frame cannot be drawn."""
        panel = self.error_panel or {}
        try:
            self.canvas.delete("all")
            self.hitboxes = {}
            width = self.canvas.logical_width
            height = self.canvas.logical_height
            self.canvas.create_rectangle(
                0, 0, width, height, fill="#FDECEC", outline=""
            )
            self.canvas.create_text(
                width / 2,
                height * 0.2,
                text=panel.get("title", "The screen could not be drawn"),
                font=self.font(14, "bold"),
                fill="#B42331",
                width=max(1, width - 32),
                anchor="center",
            )
            self.canvas.create_text(
                width / 2,
                height * 0.35,
                text=f"During: {panel.get('operation', 'Screen update')}",
                font=self.font(10, "bold"),
                fill="#14213D",
                width=max(1, width - 32),
                anchor="center",
            )
            self.canvas.create_text(
                width / 2,
                height * 0.52,
                text=(panel.get("message") or f"{exc.__class__.__name__}: {exc}")[:180],
                font=self.font(9),
                fill="#14213D",
                width=max(1, width - 32),
                anchor="center",
            )
            self.canvas.create_text(
                width / 2,
                height * 0.8,
                text="The saved line state is unchanged. Touch anywhere to try again; "
                "if this screen returns, note the time and contact support.",
                font=self.font(9),
                fill="#4A5568",
                width=max(1, width - 32),
                anchor="center",
            )
        except Exception:
            traceback.print_exc()

    def elapsed_seconds(self):
        status = self.state["status"]
        started = (
            self.state.get("repair_at")
            if status == "REPAIRING" and not self.state.get("operator_response")
            else self.state.get("started_at")
        )
        return max(0, int(time.time() - (started or time.time())))

    def note_operator_activity(self, _event=None):
        self.last_operator_activity = time.monotonic()

    def on_press(self, event):
        self.note_operator_activity()
        if self.render_blocked:
            return
        x, y = self.canvas.to_logical(event.x, event.y)
        self.touch_feedback = (x, y, time.monotonic())
        self.pressed = None
        for key, box in reversed(list(self.hitboxes.items())):
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                self.pressed = key
                break
        self.request_render()

    def on_keypress(self, event):
        self.note_operator_activity()
        if self.error_panel or self.render_blocked:
            if event.keysym in ("Return", "KP_Enter"):
                self.dismiss_error_panel()
                self.safe_render()
            return
        try:
            self._handle_keypress(event)
        except Exception as exc:
            self.report_ui_error("Typing on the keyboard", exc)
        finally:
            self.request_render()

    def _handle_keypress(self, event):
        if self.busy:
            return
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
        if self.render_blocked:
            # The static fallback has no controls: any touch acknowledges it.
            self.pressed = None
            self.dismiss_error_panel()
            self.safe_render()
            return
        key = self.pressed
        self.ui_context = describe_control(key)
        try:
            self._handle_release(event)
        except Exception as exc:
            self.report_ui_error(describe_control(key), exc)
        finally:
            self.ui_context = ""
            self.request_render()

    def report_ui_error(self, operation, exc):
        """Log a failed touch action with its control and explain it on screen."""
        self.logger.log(
            "ui_action_failed",
            "ERROR",
            operation=operation,
            error=f"{exc.__class__.__name__}: {exc}",
            traceback=traceback.format_exc(),
            machine_status=self.state.get("status"),
        )
        self.show_error_panel(operation, exc)

    def _handle_release(self, event):
        x, y = self.canvas.to_logical(event.x, event.y)
        key = self.pressed
        self.pressed = None
        if not key or key not in self.hitboxes:
            return
        box = self.hitboxes[key]
        if not (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
            return
        self._released_control = (key, time.monotonic())
        if self.busy and key not in {
            "error_dismiss",
            "ui_feedback",
            "ui_page_prev",
            "ui_page_next",
        }:
            self.notify("Saving local changes • please wait", "info", 4)
            return
        if self.version_trial_active() and not (
            key in {"software_update", "about", "cancel", "error_dismiss"}
            or key.startswith(("update_", "pwd_", "ui_page_"))
        ):
            self.notify(
                "Version health check • wait for confirmation before reporting",
                "info",
                5,
            )
            return
        if key.startswith("operator_"):
            if not self.busy and not self.error_panel:
                self.handle_layout_control(key)
            return
        if key.startswith("ui_"):
            self.handle_layout_control(key)
            return
        if self.error_panel:
            if key == "error_dismiss":
                self.dismiss_error_panel()
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
                elif action == "symbols":
                    self.modal["symbols"] = not self.modal.get("symbols", False)
                    self.modal["keys_page"] = 0
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
                self.choose_engineer(int(key.split("_")[1]))
            elif key == "members_mode":
                self.modal["batch"] = not self.modal.get("batch", False)
                if not self.modal["batch"]:
                    self.modal["selected"] = (
                        set(map(str, self.state.get("engineer_ids", [])))
                        if self.modal["context"]["kind"] == "edit"
                        else set()
                    )
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
                # Timestamp the affirmative touch, not when the dialog opened.
                requested_at = time.time()
                self.modal = None
                if kind == "confirm_downtime":
                    self.logger.log("downtime_confirmation_accepted")
                    self.perform("Recording downtime…", self.report_downtime)
                else:
                    self.logger.log("completion_confirmation_accepted")
                    self.perform(
                        "Releasing the line to Production"
                        if self.state.get("status") == "ENGINEERING"
                        else "Completing repair",
                        lambda: self.finish_work(requested_at),
                        before_transaction=lambda: self.capture_release_confirmation(
                            requested_at
                        ),
                    )
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
                elif action in {"previous", "next"}:
                    self.modal["page"] = max(
                        0, self.modal.get("page", 0) + (1 if action == "next" else -1)
                    )
                elif action == "search":
                    previous = self.modal
                    self.open_text_input(
                        "failure_search",
                        "FIND A FAILURE REASON",
                        "Search this station's reasons • blank shows all • selections stay saved",
                        previous.get("filter", ""),
                        return_modal=previous,
                    )
                elif action == "done":
                    self.save_failure_selection()
                elif action == "remove":
                    self.remove_failure_station()
                elif action in {"report", "self_fix"}:
                    self.report_from_failure_picker(self_fix=action == "self_fix")
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
            if not self.provider.connected:
                self.notify(
                    "Updates are safely queued locally • connector unavailable",
                    "error",
                    8,
                )
            else:
                self.perform(
                    "Synchronizing queued updates…",
                    lambda: self.synchronize_due_work(force=True),
                )
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

    def perform(
        self,
        working,
        function,
        on_success=None,
        *,
        quiet=False,
        before_transaction=None,
        on_error=None,
        transactional=True,
    ):
        """Run one operation off the UI thread.

        ``quiet`` marks automatic background work: it shows no progress message
        and reports a failure as a short notice instead of a dialog, because no
        operator is waiting on it.
        """
        if self.busy or (transactional and self.version_trial_active()):
            return False
        self.busy = True
        self.busy_message = working or "Saving local updates"
        self.busy_started = time.monotonic()
        if hasattr(getattr(self, "canvas", None), "configure"):
            self.canvas.configure(cursor="watch")
        self.request_render()
        if not quiet:
            self.notify(working, "info", 15)
        self.logger.log("operation_started", operation=working)

        def worker():
            try:
                if before_transaction:
                    before_transaction()
                queued_before = len(self.state.get("delivery_outbox", []))
                transaction = (
                    self.state_store.transaction()
                    if transactional
                    and getattr(self.provider, "deferred_writes", False)
                    else nullcontext()
                )
                with transaction:
                    result = function()
                if (
                    not quiet
                    and on_success is None
                    and len(self.state.get("delivery_outbox", [])) > queued_before
                ):
                    result = "Action saved on this terminal • external updates queued"
                self.logger.log("operation_completed", operation=working, result=result)
                self.events.put((True, result, on_success, working, quiet))
            except Exception as exc:
                self.logger.log(
                    "operation_failed",
                    "ERROR",
                    operation=working,
                    error=str(exc),
                    error_type=exc.__class__.__name__,
                )
                # Recovery coordinators must see failures of the OUTERMOST
                # commit too, not only exceptions raised inside function().
                self.events.put((False, exc, on_error, working, quiet))

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:  # restore UI ownership on thread exhaustion
            self.events.put((False, exc, on_error, working, quiet))
        return True

    def poll_events(self):
        try:
            item = self.events.get_nowait()
        except queue.Empty:
            item = None
        if item is not None:
            ok, result, callback = item[:3]
            working, quiet = (item[3], item[4]) if len(item) >= 5 else ("", False)
            if len(item) >= 5:
                self.busy = False
                self.busy_message = ""
                if hasattr(getattr(self, "canvas", None), "configure"):
                    self.canvas.configure(cursor="")
            try:
                if ok and callback:
                    self.ui_context = working or "Screen update"
                    callback(result)
                elif ok:
                    if result or not quiet:
                        self.notify(str(result), "success", 5)
                else:
                    if callback:
                        callback(result)
                    if quiet:
                        self.notify(str(result), "error", 8)
                    else:
                        self.show_error_panel(working or "Operation", result)
            except Exception as exc:
                self.report_ui_error(working or "Screen update", exc)
            finally:
                self.ui_context = ""
                self.request_render()
        try:
            service = getattr(self, "update_service", None)
            if service and not self.render_blocked and not self.error_panel:
                service.note_ui_heartbeat()
            self.check_api_limit_warning()
            if getattr(self, "history", None):
                self.history.poll()
            if getattr(self, "delivery", None) and not getattr(self, "_closing", False):
                try:
                    self.delivery.poll()
                except StateSaveError as exc:
                    # A held acknowledgement is retried after storage recovers.
                    self.notify(str(exc), "error", 8)
        finally:
            self.root.after(100, self.poll_events)

    def save_state(self):
        try:
            if self.state_store.save() is False:
                # The enclosing transaction will commit once, after every intent
                # is present. Do not log intermediate states as durable saves.
                return
        except StateSaveError as exc:
            self.logger.log(
                "state_save_failed",
                "CRITICAL",
                error=str(exc),
                machine_status=self.state.get("status"),
                response_record_id=self.state.get("response_record_id"),
            )
            raise
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

    def open_settings(self, directory=None, *, deferred=False):
        current = getattr(self, "settings_window", None)
        if current is not None and current.win.winfo_exists():
            current.win.deiconify()
            current.win.lift()
            return current
        self.settings_window = SettingsWindow(
            self, directory or {"teams": [], "conversations": []}, deferred=deferred
        )
        return self.settings_window


def main():
    import sys

    from .core.paths import RUNTIME_ROOT
    from .update.compatibility import (
        CHECK_ARGUMENT,
        CompatibilityError,
        cli,
        probation_startup_check,
    )

    if sys.argv[1:] == [CHECK_ARGUMENT]:
        raise SystemExit(cli(RUNTIME_ROOT))
    try:
        probation = probation_startup_check(RUNTIME_ROOT)
    except (CompatibilityError, OSError):
        print(
            "New version could not safely read runtime data; supervised recovery requested"
        )
        raise SystemExit(78) from None
    root = tk.Tk()
    project_profile = None
    try:
        project_profile = load_project_profile()
        FloorTerminalApp(root, project_profile)
    except (ProjectProfileError, ConfigurationError, StateIntegrityError) as exc:
        if probation:
            root.destroy()
            print("New version could not initialize; supervised recovery requested")
            raise SystemExit(78) from None
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
