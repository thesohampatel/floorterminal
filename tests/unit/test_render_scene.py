"""Bounded-resource regression tests without a display server."""

import unittest
from unittest.mock import Mock

from floorterminal.ui.raster import RasterCache
from floorterminal.ui.scene import CanvasScene


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.create = Mock(side_effect=range(1, 100000))
        self.coords, self.configure, self.delete, self.raise_item = (
            Mock() for _ in range(4)
        )
        self.scene = CanvasScene(
            self.create, self.coords, self.configure, self.delete, self.raise_item
        )

    def frame(self, count=10):
        self.scene.begin()
        for i in range(count):
            self.scene.draw("text", (i, i), {"text": str(i)})
        self.scene.end()

    def test_ten_thousand_identical_frames_allocate_only_once(self):
        for _ in range(10000):
            self.frame()
        self.assertEqual(self.create.call_count, 10)
        self.assertEqual(len(self.scene.items), 10)
        self.coords.assert_not_called()
        self.configure.assert_not_called()
        self.delete.assert_not_called()
        self.assertEqual(self.raise_item.call_count, 10)

    def test_only_changed_coordinates_and_options_cross_the_tcl_boundary(self):
        self.frame(1)
        self.scene.begin()
        self.scene.draw("text", (2, 3), {"text": "changed"})
        self.scene.end()
        self.assertEqual(self.create.call_count, 1)
        self.coords.assert_called_once_with(1, 2, 3)
        self.configure.assert_called_once_with(1, text="changed")

    def test_shrinking_and_changing_kind_deletes_unused_items_and_restacks(self):
        self.frame()
        self.scene.begin()
        self.scene.draw("oval", (1, 2, 3, 4), {"fill": "red"})
        self.scene.end()
        self.assertEqual(len(self.scene.items), 1)
        self.assertEqual(self.delete.call_count, 10)
        self.raise_item.assert_called_with(11)

    def test_removed_options_do_not_leak_style_from_a_previous_screen(self):
        self.frame(1)
        self.scene.begin()
        self.scene.draw("text", (0, 0), {"text": "0", "anchor": "nw"})
        self.scene.end()
        self.assertEqual(self.create.call_count, 2)
        self.delete.assert_called_once_with(1)

    def test_visible_images_are_pinned_independently_of_cache_eviction(self):
        image = object()
        self.scene.begin()
        self.scene.draw("image", (0, 0), {"image": image}, "rounded")
        self.scene.end()
        self.scene.begin()
        self.assertIs(self.scene.current_raster("rounded"), image)
        self.assertIsNone(self.scene.current_raster("different"))
        self.scene.end()
        self.assertEqual(self.scene.items, [])

    def test_cache_obeys_decoded_byte_budget_and_clear_releases_references(self):
        cache = RasterCache(bytes, limit=200, byte_limit=100)
        for i in range(10000):
            cache.get(i, lambda: b"png", cost=40)
        self.assertEqual(cache.bytes_used, 80)
        self.assertEqual(len(cache.images), 2)
        cache.clear()
        self.assertEqual(cache.bytes_used, 0)
        self.assertEqual(cache.images, {})
        self.assertEqual(cache.costs, {})

    def test_oversized_image_is_drawable_but_not_cached(self):
        cache = RasterCache(bytes, byte_limit=10)
        self.assertEqual(cache.get("large", lambda: b"png", cost=100), b"png")
        self.assertFalse(cache.images)
        self.assertEqual(cache.bytes_used, 0)
