"""Mechanical animation must stay bounded, continuous and status-correct."""

import math
import unittest

from floorterminal.ui.conveyor import advance_motion, belt_point, station_slots
from floorterminal.ui.kiosk import KioskViewMixin
from floorterminal.ui.view import OperatorViewMixin


class ConveyorTests(unittest.TestCase):
    def test_animation_boundaries_never_change_canvas_item_structure(self):
        class Scene:
            def __init__(self):
                self.operations = []

            def __getattr__(self, name):
                return lambda *_args, **_kwargs: self.operations.append(name)

        class View:
            canvas = Scene()
            GREEN, RED, ORANGE, PURPLE = "green", "red", "orange", "purple"

            def rounded(self, *_args, **_kwargs):
                self.canvas.operations.append("rounded")

            def station_groups(self):
                return []

        view = View()
        signature = None
        for frame in range(1000):
            phase = frame / 30
            view.canvas.operations.clear()
            OperatorViewMixin.status_face(view, 30, 30, "RUNNING", phase)
            KioskViewMixin.kiosk_conveyor(
                view, (0, 70, 400, 96), phase, "RUNNING", "green"
            )
            current = tuple(view.canvas.operations)
            if signature is None:
                signature = current
            self.assertEqual(current, signature, f"Canvas churn at phase {phase}")

    def test_belt_joins_are_continuous_and_loop_closes(self):
        length, radius = 240, 11
        arc = math.pi * radius
        for join in (0, length, length + arc, 2 * length + arc, 2 * (length + arc)):
            before, after = (
                belt_point(join - 0.00001, length, radius),
                belt_point(join + 0.00001, length, radius),
            )
            self.assertLess(math.dist(before[:2], after[:2]), 0.0001)
            self.assertLess(math.dist(before[2:], after[2:]), 0.0001)

    def test_carry_and_return_have_opposite_directions(self):
        self.assertGreater(belt_point(20, 100, 10)[0], belt_point(10, 100, 10)[0])
        offset = 100 + math.pi * 10
        self.assertLess(
            belt_point(offset + 20, 100, 10)[0], belt_point(offset + 10, 100, 10)[0]
        )

    def test_motion_freezes_and_resumes_without_reset(self):
        state = advance_motion(None, 0, True, 100, 70, 10)
        state = advance_motion(state, 0.05, True, 100, 70, 10)
        self.assertGreater(state[1], 0)
        stopped = advance_motion(state, 1, False, 100, 70, 10)
        later = advance_motion(stopped, 99999999, False, 100, 70, 10)
        resumed = advance_motion(later, 99999999.5, True, 100, 70, 10)
        self.assertEqual(state[1:4], stopped[1:4])
        self.assertEqual(state[1:4], resumed[1:4])

    def test_long_pause_and_long_runtime_never_create_catchup_bursts(self):
        state = advance_motion(None, 0, True, 100, 70, 10)
        for now in range(1, 100000, 37):
            state = advance_motion(state, now, True, 100, 70, 10)
            self.assertTrue(0 <= state[1] < 100)
            self.assertTrue(0 <= state[2] < 70)
            self.assertTrue(0 <= state[3] < math.tau)
        self.assertEqual(
            advance_motion(None, 1000000000, True, 100, 70, 10)[1:4], (0, 35, 0)
        )

    def test_groups_have_larger_gaps_without_changing_station_order(self):
        groups = {"A": {"id": "one"}, "B": {"id": "one"}, "C": {"id": "two"}}
        slots = station_slots(["A", "B", "C"], groups, (0, 10, 500, 100), True)
        self.assertAlmostEqual(slots[1][0] - slots[0][2], 8)
        self.assertAlmostEqual(slots[2][0] - slots[1][2], 20)
        self.assertAlmostEqual(slots[-1][2], 500)
        self.assertTrue(all(c - a >= 48 for a, _b, c, _d in slots))
