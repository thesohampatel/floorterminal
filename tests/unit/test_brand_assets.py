import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "branding" / "floorterminal"
RUNTIME = ROOT / "src" / "floorterminal" / "assets" / "branding"


def png_dimensions(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a valid PNG header: {path}")
    return struct.unpack(">II", data[16:24])


class BrandAssetTests(unittest.TestCase):
    def test_vector_master_is_original_flat_artwork(self):
        svg = (MASTER / "floorterminal-mark.svg").read_text(encoding="utf-8")
        self.assertIn('viewBox="0 0 1024 1024"', svg)
        self.assertNotIn("<image", svg)
        self.assertNotIn("linearGradient", svg)
        self.assertNotIn("href=", svg)

    def test_master_rasters_have_their_declared_dimensions(self):
        for size in (32, 64, 128, 256, 512, 1024):
            with self.subTest(size=size):
                path = MASTER / f"floorterminal-mark-{size}.png"
                self.assertEqual(png_dimensions(path), (size, size))

    def test_runtime_and_linux_icons_are_packaged(self):
        for size in (32, 64, 128, 256):
            with self.subTest(size=size):
                runtime = RUNTIME / f"floorterminal-mark-{size}.png"
                self.assertEqual(png_dimensions(runtime), (size, size))
        self.assertEqual(
            (ROOT / "packaging" / "linux" / "floorterminal-icon.png").read_bytes(),
            (MASTER / "floorterminal-mark-256.png").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
