import time
import unittest

from floorterminal.core.clock import (
    BACKWARD_TOLERANCE_SECONDS,
    FORWARD_LIMIT_SECONDS,
    check_clock,
)

REFERENCE = "2026-08-31T00:00:00Z"
RELEASED = 1788134400.0  # 2026-08-31T00:00:00Z


class SystemClockTests(unittest.TestCase):
    """Recorded times are only meaningful if the clock is plausible."""

    def test_a_clock_at_or_after_the_release_date_is_trusted(self):
        for offset in (0, 3600, 365 * 24 * 3600):
            with self.subTest(offset=offset):
                self.assertTrue(check_clock(REFERENCE, RELEASED + offset).trusted)

    def test_a_clock_before_the_release_date_is_reported(self):
        result = check_clock(REFERENCE, RELEASED - BACKWARD_TOLERANCE_SECONDS - 60)
        self.assertFalse(result.trusted)
        self.assertIn("earlier than the date this version was released", result.reason)
        self.assertIn("not plausible", result.summary)

    def test_a_pi_booting_without_network_time_is_caught(self):
        """A Raspberry Pi with no real-time clock can come up at the epoch."""
        self.assertFalse(check_clock(REFERENCE, 0).trusted)

    def test_small_backward_drift_is_tolerated(self):
        self.assertTrue(check_clock(REFERENCE, RELEASED - 3600).trusted)

    def test_an_implausibly_future_clock_is_reported(self):
        result = check_clock(REFERENCE, RELEASED + FORWARD_LIMIT_SECONDS + 86400)
        self.assertFalse(result.trusted)
        self.assertIn("far ahead", result.reason)

    def test_an_unusable_reference_never_blocks_startup(self):
        for reference in (None, "", "not a timestamp", "2026-13-45T99:99:99Z"):
            with self.subTest(reference=reference):
                self.assertTrue(check_clock(reference, RELEASED).trusted)

    def test_the_default_reference_is_the_running_release(self):
        result = check_clock()
        self.assertTrue(result.system_time_utc.endswith("Z"))
        self.assertIsInstance(result.trusted, bool)

    def test_timestamps_are_reported_in_utc(self):
        result = check_clock(REFERENCE, RELEASED)
        self.assertEqual(result.reference_utc, REFERENCE)
        self.assertTrue(result.system_time_utc.startswith("2026-08-31T"))

    def test_the_check_is_cheap_enough_for_startup(self):
        start = time.perf_counter()
        for _ in range(200):
            check_clock(REFERENCE, RELEASED)
        self.assertLess(time.perf_counter() - start, 1.0)


if __name__ == "__main__":
    unittest.main()
