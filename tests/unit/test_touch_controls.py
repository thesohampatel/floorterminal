"""Real Tk checks for staged panels and in-app selection controls."""

import gc
import subprocess
import sys
import time
import tkinter as tk
import unittest
from pathlib import Path

from floorterminal.ui.choices import TouchChoice
from floorterminal.ui.images import opaque_photo
from floorterminal.ui.panels import AppPanel
from floorterminal.ui.raster import _png
from floorterminal.ui.touch_button import TouchButton
from tests.unit.test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "No Tk display available")
class SettingsLifecycleTests(unittest.TestCase):
    def test_deferred_build_cancel_failure_resize_and_navigation(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("experience_ui_driver.py"))],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"failure_recovered": true', result.stdout)


@unittest.skipUnless(HAS_DISPLAY, "No Tk display available")
class TouchControlTests(unittest.TestCase):
    def test_static_logo_is_composited_without_losing_edge_coverage(self):
        source = tk.PhotoImage(
            master=self.root,
            data=_png(2, 1, [bytes((255, 0, 0, 128, 0, 0, 0, 0))]),
            format="png",
        )
        result = opaque_photo(source, "white", self.root)
        self.assertEqual(result.get(0, 0), (255, 127, 127))
        self.assertEqual(result.get(1, 0), (255, 255, 255))
        self.assertFalse(result.transparency_get(1, 0))
        self.assertTrue(source.transparency_get(1, 0))

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("No Tk display available")
        self.root.geometry("800x480+0+0")
        self.faults = []
        self.root.report_callback_exception = lambda _t, value, _tb: self.faults.append(
            str(value)
        )
        self.root.update()

    def tearDown(self):
        if hasattr(self, "root"):
            self.root.destroy()
        self.assertEqual(getattr(self, "faults", []), [])

    def pump(self):
        end = time.monotonic() + 0.25
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)

    def test_panel_keeps_build_covered_until_explicit_presentation(self):
        panel = AppPanel(self.root, background="white", border="gray")
        tk.Entry(panel.content).pack()
        self.root.update_idletasks()
        self.assertTrue(panel.cover.winfo_ismapped())
        panel.present()
        self.pump()
        self.assertFalse(panel.cover.winfo_ismapped())
        self.assertIsNone(panel._reveal_after)
        panel.destroy()

    def test_panel_raster_memory_is_independent_of_screen_area(self):
        panel = AppPanel(self.root, background="white", border="gray")
        for width, height in ((800, 480), (1920, 1200), (3840, 2160)):
            panel._resize(type("Size", (), {"width": width, "height": height})())
            self.assertLess(panel.backdrop.raster.bytes_used, 128 * 1024)
        panel.destroy()

    def test_dropdown_commits_once_and_restores_parent_grab(self):
        panel = AppPanel(self.root, background="white", border="gray")
        variable = tk.StringVar(value="One")
        choice = TouchChoice(
            panel.content,
            textvariable=variable,
            values=("One", "Two"),
            state="readonly",
        )
        choice.pack()
        panel.present()
        panel.grab_set()
        selected = []
        choice.bind("<<ComboboxSelected>>", lambda _e: selected.append(variable.get()))
        choice._open()
        self.pump()
        self.assertIs(self.root.grab_current(), choice.picker)
        pending = [choice.picker]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, TouchButton) and widget.cget("text") == "Two":
                widget.invoke()
                break
        self.root.update()
        self.assertEqual(selected, ["Two"])
        self.assertIs(self.root.grab_current(), panel)
        self.assertIsNone(choice.picker)

    def test_editable_choice_keeps_values_not_present_in_suggestions(self):
        choice = TouchChoice(self.root, values=("One", "Two"), state="normal")
        choice.set("A newly created destination")
        choice.pack()
        self.root.update()
        self.assertIsNone(choice._press(type("Event", (), {"x": 10, "y": 10})()))
        self.assertEqual(choice.get(), "A newly created destination")

    def test_faces_are_reused_and_lru_is_bounded(self):
        button = TouchButton(
            self.root,
            text="Test",
            command=lambda: None,
            font=("Helvetica", 10),
            bg="#EDF3FC",
            fg="#14213D",
        )
        button.refresh_surface(100, 48)
        original = button.faces
        button.refresh_surface(100, 48)
        self.assertIs(original, button.faces)
        for width in range(101, 170):
            button.refresh_surface(width, 48)
        self.assertLessEqual(len(self.root._touch_faces), 48)
        self.assertLessEqual(self.root._touch_face_bytes, 8 * 1024 * 1024)

    def test_nested_picker_destruction_cancels_pending_redraw(self):
        panel = AppPanel(self.root, background="white", border="gray")
        choice = TouchChoice(
            panel.content,
            values=tuple(f"Option {i}" for i in range(90)),
            state="readonly",
        )
        choice.pack()
        panel.present()
        choice._open()
        panel.destroy()
        self.pump()

    def test_repeated_picker_destruction_releases_traces_and_fonts(self):
        choice = TouchChoice(self.root, values=("One", "Two"), state="readonly")
        choice.pack()
        self.root.update()
        baseline = None
        for _ in range(21):
            choice._open()
            choice.picker.destroy()
            self.root.update()
            gc.collect()
            resources = (
                len(self.root.tk.call("info", "commands")),
                len(self.root.tk.call("font", "names")),
            )
            if baseline is None:
                baseline = resources
            self.assertEqual(resources, baseline)
            self.assertIsNone(choice.picker)
