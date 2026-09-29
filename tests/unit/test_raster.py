"""Pre-rendered anti-aliased shapes: exact size, binary transparency, soft edges."""

import struct
import unittest
import zlib

from floorterminal.ui.raster import RasterCache, rounded_rectangle_png

BACKDROP = (243, 245, 249)


def decode(png):
    """Minimal decoder for the unfiltered RGBA PNGs the renderer writes."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    offset, data = 8, b""
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset : offset + 4])
        kind = png[offset + 4 : offset + 8]
        body = png[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", png[offset + 8 + length : offset + 12 + length])
        assert zlib.crc32(kind + body) & 0xFFFFFFFF == crc
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            data += body
        offset += 12 + length
    raw = zlib.decompress(data)
    stride = 1 + 4 * width
    rows = [raw[row * stride + 1 : (row + 1) * stride] for row in range(height)]
    assert all(raw[row * stride] == 0 for row in range(height))
    pixels = [
        [tuple(row[column * 4 : column * 4 + 4]) for column in range(width)]
        for row in rows
    ]
    return width, height, pixels


class RoundedRectangleTests(unittest.TestCase):
    def test_every_size_encodes_exactly_including_odd_dimensions(self):
        for width, height, radius in ((1, 1, 0.5), (9, 9, 4.5), (10, 7, 3), (33, 20, 16), (240, 60, 12)):
            with self.subTest(size=(width, height)):
                png = rounded_rectangle_png(
                    width, height, radius, (22, 163, 106), (200, 20, 40), 2, BACKDROP
                )
                self.assertEqual(decode(png)[:2], (width, height))

    def test_transparency_is_binary_so_tk_keeps_its_fast_drawing_path(self):
        _w, _h, pixels = decode(
            rounded_rectangle_png(40, 40, 20, (36, 107, 253), None, 0, BACKDROP)
        )
        alphas = {pixel[3] for row in pixels for pixel in row}
        self.assertEqual(alphas, {0, 255})

    def test_corner_pixels_are_blended_toward_the_backdrop(self):
        fill = (22, 163, 106)
        _w, _h, pixels = decode(rounded_rectangle_png(60, 60, 30, fill, None, 0, BACKDROP))
        self.assertEqual(pixels[0][0][3], 0)
        self.assertEqual(pixels[30][30][:3], fill)
        edge = [
            pixel[:3]
            for pixel in pixels[30][:10]
            if pixel[3] == 255 and pixel[:3] not in (fill, BACKDROP)
        ]
        self.assertTrue(edge, "no intermediate edge colour was produced")

    def test_an_outline_only_ring_leaves_its_interior_transparent(self):
        _w, _h, pixels = decode(
            rounded_rectangle_png(50, 30, 8, None, (36, 107, 253), 2, BACKDROP)
        )
        self.assertEqual(pixels[15][25][3], 0)
        self.assertEqual(pixels[15][0], (36, 107, 253, 255))

    def test_nothing_to_draw_returns_none(self):
        self.assertIsNone(rounded_rectangle_png(10, 10, 3, None, None, 0, BACKDROP))


class RasterCacheTests(unittest.TestCase):
    def test_cache_renders_once_per_key_and_is_bounded(self):
        rendered = []
        cache = RasterCache(lambda data: ("image", data), limit=2)
        for key in ("a", "a", "b", "c", "a"):
            cache.get(key, lambda key=key: rendered.append(key) or key.encode())
        self.assertEqual(rendered, ["a", "b", "c", "a"])
        self.assertEqual(len(cache.images), 2)


if __name__ == "__main__":
    unittest.main()
