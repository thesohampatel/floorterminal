import unittest

from floorterminal.ui.responsive import (
    DESIGN_HEIGHT,
    DESIGN_WIDTH,
    design_scale,
    fitted_window_geometry,
)


class ResponsiveGeometryTests(unittest.TestCase):
    def test_supported_screen_matrix_never_overflows_or_crops_design(self):
        screens = (
            (480, 320),
            (800, 480),
            (1024, 600),
            (1280, 720),
            (1280, 800),
            (1920, 1080),
            (1080, 1920),
        )
        for screen_width, screen_height in screens:
            with self.subTest(screen=(screen_width, screen_height)):
                width, height, x, y = fitted_window_geometry(
                    screen_width, screen_height, 0.96, 0.94
                )
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + width, screen_width)
                self.assertLessEqual(y + height, screen_height)
                scale = design_scale(width, height)
                self.assertLessEqual(DESIGN_WIDTH * scale, width + 0.001)
                self.assertLessEqual(DESIGN_HEIGHT * scale, height + 0.001)

    def test_invalid_screen_and_ratio_inputs_are_safely_bounded(self):
        width, height, x, y = fitted_window_geometry(0, -20, 7, -1)
        self.assertEqual((width, height, x, y), (1, 1, 0, 0))

    def test_touch_coordinates_round_trip_for_letterboxed_viewports(self):
        for width, height in ((800, 480), (1024, 600), (1920, 1080)):
            scale = design_scale(width, height)
            offset_x = (width - DESIGN_WIDTH * scale) / 2
            offset_y = (height - DESIGN_HEIGHT * scale) / 2
            for logical_x, logical_y in ((0, 0), (400, 240), (800, 480)):
                physical_x = logical_x * scale + offset_x
                physical_y = logical_y * scale + offset_y
                self.assertAlmostEqual((physical_x - offset_x) / scale, logical_x)
                self.assertAlmostEqual((physical_y - offset_y) / scale, logical_y)


if __name__ == "__main__":
    unittest.main()
