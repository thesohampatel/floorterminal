import time
import unittest

from floorterminal.app import FloorTerminalApp
from floorterminal.i18n import load_translator
from floorterminal.storage.state import INITIAL_STATE
from floorterminal.ui import update_view
from floorterminal.ui.update_view import TAB_KEYS, UpdateViewMixin
from floorterminal.update import remote, trust
from floorterminal.update.service import (
    LEVEL_ATTENTION,
    LEVEL_OK,
    LEVEL_UNKNOWN,
    StagedUpdate,
    UpdateStatus,
)


class RecordingCanvas:
    """Capture drawing calls without needing a display server."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **values):
            self.calls.append((name, args, values))

        return record


class ViewHarness(UpdateViewMixin):
    """The update drawing code with the console's primitives stubbed out."""

    BG, CARD, TEXT, MUTED = "#F3F5F9", "#FFFFFF", "#14213D", "#718096"
    RED, GREEN, BLUE, ORANGE, PURPLE = (
        "#E84855",
        "#16A36A",
        "#246BFD",
        "#F09A3E",
        "#7956D8",
    )
    BORDER, PALE_BLUE = "#E3E8F1", "#EDF3FF"

    def __init__(self, status, page="status"):
        # A real translator, so a label the catalogue is missing shows up as its
        # own key and the assertions below catch it.
        self.t = load_translator("en")
        self.canvas = RecordingCanvas()
        self.hitboxes = {}
        self.pressed = None
        self.modal = {"kind": "update", "page": page}
        self.texts = []
        self.buttons = []
        self._status = status

    def update_status(self):
        return self._status

    def rounded(self, *args, **values):
        self.canvas.calls.append(("rounded", args, values))

    def text(self, x, y, value, *args, **values):
        self.texts.append(str(value))

    def button(self, key, box, label, *args, **values):
        self.buttons.append((key, label))
        self.hitboxes[key] = box


def status(**values):
    return UpdateStatus(**values)


def staged(version="1.1.0"):
    return StagedUpdate(
        version=version,
        release_title="Reliability improvements",
        release_summary="Improves startup and synchronization.",
        released_utc="2026-11-14T09:00:00Z",
        artifact_sha256="a" * 64,
        signing_key_id="1234abcd",
        source_mount="/media/kiosk/FLOORTERM",
        highlights=(("NEW", "Signed offline updates"), ("FIX", "Steadier sync badge")),
    )


def channel(version="1.1.0"):
    return remote.ChannelResult(
        outcome=remote.OUTCOME_OK,
        checked_at_epoch=time.time(),
        checked_at_utc="2026-11-14T09:00:00Z",
        version=version,
        released_utc="2026-11-14T09:00:00Z",
        release_title="Published release",
        release_summary="Summary of the published release.",
        minimum_upgradable_version="1.0.0",
        features=("Something new",),
    )


class PanelDrawingTests(unittest.TestCase):
    def test_every_page_draws_and_registers_its_controls(self):
        cases = {
            "up to date": status(
                level=LEVEL_OK,
                headline="Version 1.0.0 is up to date",
                channel=channel("1.0.0"),
                managed=True,
            ),
            "update staged": status(
                level=LEVEL_ATTENTION,
                headline="Ready to install",
                staged=staged(),
                managed=True,
                rollback_version="0.9.0",
            ),
            "unreachable": status(level=LEVEL_UNKNOWN, headline="Could not be checked"),
            "published": status(
                level=LEVEL_ATTENTION,
                headline="Version 1.1.0 is available",
                channel=channel(),
                update_available=True,
                latest_version="1.1.0",
                managed=True,
            ),
        }
        for label, snapshot in cases.items():
            for page in TAB_KEYS:
                with self.subTest(case=label, page=page):
                    harness = ViewHarness(snapshot, page)
                    harness.draw_update_panel()
                    for key in TAB_KEYS:
                        self.assertIn(f"update_tab_{key}", harness.hitboxes)
                    self.assertIn("cancel", harness.hitboxes)
                    self.assertIn("update_check", harness.hitboxes)
                    self.assertIn("update_scan", harness.hitboxes)

    def test_install_and_rollback_controls_appear_only_when_they_are_usable(self):
        harness = ViewHarness(status(level=LEVEL_OK, managed=True))
        harness.draw_update_panel()
        self.assertNotIn("update_install", harness.hitboxes)
        self.assertNotIn("update_rollback", harness.hitboxes)
        self.assertIn("NO UPDATE ACTION AVAILABLE", harness.texts)

        harness = ViewHarness(
            status(level=LEVEL_ATTENTION, staged=staged(), managed=True)
        )
        harness.draw_update_panel()
        self.assertIn("update_install", harness.hitboxes)
        self.assertNotIn("update_rollback", harness.hitboxes)

        harness = ViewHarness(
            status(
                level=LEVEL_ATTENTION,
                staged=staged(),
                managed=True,
                rollback_version="1.0.0",
            )
        )
        harness.draw_update_panel()
        self.assertIn("update_install", harness.hitboxes)
        self.assertIn("update_rollback", harness.hitboxes)

    def test_an_unmanaged_installation_never_offers_a_version_change(self):
        harness = ViewHarness(
            status(
                level=LEVEL_ATTENTION,
                staged=staged(),
                managed=False,
                rollback_version="1.0.0",
            )
        )
        harness.draw_update_panel()
        self.assertNotIn("update_install", harness.hitboxes)
        self.assertNotIn("update_rollback", harness.hitboxes)

    def test_every_panel_label_resolves_through_the_locale_catalogue(self):
        """A missing catalogue key renders as the key itself; none may leak."""
        for page in TAB_KEYS:
            harness = ViewHarness(
                status(
                    level=LEVEL_ATTENTION,
                    staged=staged(),
                    managed=True,
                    rollback_version="1.0.0",
                    channel=channel(),
                    history=(
                        {
                            "at_utc": "2026-11-14T09:05:00Z",
                            "action": "activated",
                            "from_version": "1.0.0",
                            "to_version": "1.1.0",
                            "outcome": "ok",
                            "authorized_by": "A. Supervisor",
                        },
                    ),
                ),
                page,
            )
            harness.draw_update_panel()
            drawn = [*harness.texts, *(label for _, label in harness.buttons)]
            leaked = [value for value in drawn if value.startswith("update_")]
            with self.subTest(page=page):
                self.assertEqual(leaked, [], f"unresolved catalogue keys: {leaked}")
                self.assertTrue(drawn)

    def test_the_status_page_always_states_how_to_update_and_whom_to_contact(self):
        harness = ViewHarness(status(level=LEVEL_UNKNOWN))
        harness.draw_update_panel()
        joined = " ".join(harness.texts)
        self.assertIn(trust.RELEASES_URL, joined)
        self.assertIn(trust.UPDATE_VOLUME_LABELS[0], joined)
        self.assertIn(trust.UPDATE_PACKAGE_DIRNAME, joined)
        self.assertIn(trust.MAINTAINER_EMAIL, joined)
        self.assertIn(trust.MAINTAINER_NAME, joined)

    def test_the_indicator_uses_a_second_cue_besides_colour(self):
        for level, expect_badge in (
            (LEVEL_OK, False),
            (LEVEL_ATTENTION, True),
            (LEVEL_UNKNOWN, True),
        ):
            with self.subTest(level=level):
                harness = ViewHarness(status(level=level))
                harness.hitboxes = {}
                harness.draw_update_indicator((656, 13, 694, 51))
                self.assertIn("software_update", harness.hitboxes)
                ovals = [
                    call for call in harness.canvas.calls if call[0] == "create_oval"
                ]
                self.assertEqual(len(ovals) > 1, expect_badge)

    def test_each_level_has_a_distinct_accent_and_glyph(self):
        harness = ViewHarness(status())
        styles = {
            level: harness.update_level_style(level)
            for level in (LEVEL_OK, LEVEL_ATTENTION, LEVEL_UNKNOWN)
        }
        self.assertEqual(len({style[0] for style in styles.values()}), 3)
        self.assertEqual(len({style[2] for style in styles.values()}), 3)

    def test_activity_timestamps_are_rendered_for_operators(self):
        self.assertEqual(
            update_view._stamp("2026-11-14T09:05:00Z"), "2026-11-14  09:05 UTC"
        )
        self.assertEqual(update_view._stamp(""), "")
        self.assertEqual(update_view._stamp("not a timestamp"), "not a timestamp")


class ApplicationWiringTests(unittest.TestCase):
    def app(self, **attributes):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.state = dict(INITIAL_STATE)
        app.busy = False
        app.modal = None
        app.toast_text, app.toast_kind, app.toast_until = "", "info", 0
        app.announced_update = ""
        app.logger = self.Logger()
        for name, value in attributes.items():
            setattr(app, name, value)
        return app

    class Logger:
        def __init__(self):
            self.events = []

        def log(self, event, level="INFO", **details):
            self.events.append((event, level, details))

        @property
        def names(self):
            return [event for event, _, _ in self.events]

    class Service:
        def __init__(self, snapshot):
            self.snapshot = snapshot
            self.scans = 0

        def status(self):
            return self.snapshot

        def request_scan(self):
            self.scans += 1

    def test_status_falls_back_to_a_safe_snapshot_without_a_service(self):
        app = self.app()
        self.assertIs(app.update_status(), update_view.UNAVAILABLE_STATUS)
        self.assertEqual(app.update_status().level, LEVEL_UNKNOWN)

    def test_opening_the_panel_requests_a_scan_and_is_audited(self):
        service = self.Service(status(level=LEVEL_OK, installed_version="1.0.0"))
        app = self.app(update_service=service)
        app.open_update_panel()
        self.assertEqual(app.modal, {"kind": "update", "page": "status"})
        self.assertEqual(service.scans, 1)
        self.assertIn("software_update_panel_opened", app.logger.names)

    def test_tab_controls_only_change_the_visible_page(self):
        service = self.Service(status(level=LEVEL_OK))
        app = self.app(update_service=service)
        app.open_update_panel()
        for page in TAB_KEYS:
            app.handle_update_control(f"tab_{page}")
            self.assertEqual(app.modal["page"], page)
        self.assertEqual(app.modal["kind"], "update")

    def test_installation_requires_administrator_authorization(self):
        service = self.Service(
            status(level=LEVEL_ATTENTION, staged=staged(), managed=True)
        )
        app = self.app(update_service=service, auth_throttle=self.Throttle())
        app.open_update_panel("changes")
        app.handle_update_control("install")
        self.assertEqual(app.modal["kind"], "password")
        self.assertEqual(app.modal["purpose"], "software_update")
        self.assertEqual(
            app.modal["update_selection"]["version"], service.snapshot.staged.version
        )
        self.assertEqual(
            app.modal["update_selection"]["sha256"],
            service.snapshot.staged.artifact_sha256,
        )
        self.assertEqual(
            app.modal["return_modal"], {"kind": "update", "page": "changes"}
        )
        self.assertIn("software_update_authorization_requested", app.logger.names)

    def test_authorization_warns_when_the_line_is_not_running(self):
        service = self.Service(
            status(level=LEVEL_ATTENTION, staged=staged(), managed=True)
        )
        app = self.app(update_service=service, auth_throttle=self.Throttle())
        app.state["status"] = "REPAIRING"
        app.open_update_panel()
        app.handle_update_control("install")
        self.assertIn("REPAIRING", app.modal["prompt"])
        self.assertIn("restarts and resumes", app.modal["prompt"])

    def test_actions_are_refused_when_nothing_is_available(self):
        service = self.Service(status(level=LEVEL_OK, managed=True))
        app = self.app(update_service=service)
        app.open_update_panel()
        app.handle_update_control("install")
        self.assertEqual(app.modal["kind"], "update")
        self.assertIn("No verified update", app.toast_text)
        app.handle_update_control("rollback")
        self.assertIn("No previous version", app.toast_text)

    def test_actions_are_refused_while_another_operation_is_running(self):
        service = self.Service(
            status(level=LEVEL_ATTENTION, staged=staged(), managed=True)
        )
        app = self.app(update_service=service, busy=True)
        app.open_update_panel()
        app.handle_update_control("install")
        self.assertEqual(app.modal["kind"], "update")
        self.assertIn("Wait for the current operation", app.toast_text)

    def test_a_missing_update_service_never_raises_from_a_touch(self):
        app = self.app()
        app.modal = {"kind": "update", "page": "status"}
        app.handle_update_control("check")
        self.assertIn("unavailable", app.toast_text)

    def test_check_and_scan_results_are_described_for_the_operator(self):
        app = self.app()
        self.assertIn(
            "up to date",
            app.describe_update_check(
                status(level=LEVEL_OK, installed_version="1.0.0")
            ),
        )
        self.assertIn(
            "1.1.0 is available",
            app.describe_update_check(
                status(
                    level=LEVEL_ATTENTION, update_available=True, latest_version="1.1.0"
                )
            ),
        )
        self.assertIn(
            "could not be checked",
            app.describe_update_check(status(level=LEVEL_UNKNOWN)),
        )

    def test_a_newly_verified_package_is_announced_once(self):
        service = self.Service(
            status(level=LEVEL_ATTENTION, staged=staged(), managed=True)
        )
        app = self.app(update_service=service, root=self.Root())
        app.update_watch_tick()
        self.assertIn("Software update 1.1.0 verified", app.toast_text)
        self.assertIn("software_update_ready", app.logger.names)
        self.assertEqual(app.modal["kind"], "update")
        app.logger.events.clear()
        app.update_watch_tick()
        self.assertNotIn("software_update_ready", app.logger.names)

    def test_the_restart_hand_over_stops_everything_it_owns(self):
        events = []

        class Service:
            layout = type("Layout", (), {"active_link": "/opt/x/floorterminal"})()

            def status(self):
                return status(level=LEVEL_OK)

            def stop(self):
                events.append("service stopped")

        class Sound:
            def close(self):
                events.append("sound closed")

        class Root:
            def destroy(self):
                events.append("window destroyed")

        app = self.app(update_service=Service(), sound=Sound(), root=Root())
        app.restart_into_active_version("supervisor")
        self.assertEqual(
            events, ["service stopped", "sound closed", "window destroyed"]
        )
        self.assertIn("application_restarting_for_update", app.logger.names)

    def test_an_unsupported_restart_asks_the_operator_to_restart_the_terminal(self):
        class Service:
            def status(self):
                return status(level=LEVEL_ATTENTION)

            def restart_mechanism(self):
                return "unsupported"

        class Result:
            action, from_version, to_version = "activated", "1.0.0", "1.1.0"

        app = self.app(update_service=Service(), state_store=self.StateStore())
        app.save_state = lambda: None
        app.finish_version_change(Result(), "Version 1.1.0 installed")
        self.assertIn("restart this terminal", app.toast_text)
        self.assertIn("software_update_restart_deferred", app.logger.names)

    class StateStore:
        def save(self):
            return None

    class Throttle:
        def remaining(self):
            return 0

    class Root:
        def after(self, _delay, _callback):
            return "scheduled"


if __name__ == "__main__":
    unittest.main()
