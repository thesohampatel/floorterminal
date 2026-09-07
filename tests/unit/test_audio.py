import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest import mock

from floorterminal.audio import CUES, SoundManager


class SoundManagerTests(unittest.TestCase):
    def manager(self, directory, **config):
        values = {
            "sound_enabled": True,
            "sound_volume": 70,
            "sound_cooldown_ms": 750,
            **config,
        }
        return SoundManager(values, asset_directory=directory)

    def test_all_assets_are_bounded_pcm_wave_files(self):
        directory = (
            Path(__file__).resolve().parents[2]
            / "src/floorterminal/assets/sounds"
        )
        self.assertEqual({path.stem for path in directory.glob("*.wav")}, set(CUES))
        for path in directory.glob("*.wav"):
            with wave.open(str(path), "rb") as stream:
                self.assertEqual(stream.getnchannels(), 1)
                self.assertEqual(stream.getsampwidth(), 2)
                self.assertEqual(stream.getframerate(), 44_100)
                self.assertLess(stream.getnframes(), 44_100 * 2)

    def test_disabled_unknown_zero_volume_and_missing_cues_do_not_play(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.manager(directory, sound_enabled=False).play("alert"))
            self.assertFalse(self.manager(directory).play("not-allowlisted"))
            self.assertFalse(self.manager(directory, sound_volume=0).play("alert"))
            self.assertFalse(self.manager(directory).play("alert"))

    def test_invalid_preview_volume_is_rejected_without_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.manager(directory).preview("not-a-number"))

    def test_cooldown_suppresses_repeat_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "support.wav"
            path.write_bytes(b"RIFF-local-test")
            manager = self.manager(directory, sound_cooldown_ms=5000)
            with mock.patch.object(threading.Thread, "start", return_value=None):
                self.assertTrue(manager.play("support"))
                self.assertFalse(manager.play("support"))
                self.assertTrue(manager.play("support", force=True))

    def test_commands_are_argument_lists_with_no_shell(self):
        path = Path("/safe/local cue.wav")
        with mock.patch("floorterminal.audio.shutil.which", return_value="/bin/tool"):
            self.assertEqual(
                SoundManager._command("Darwin", path, 50),
                ["afplay", "-v", "0.50", str(path)],
            )
            self.assertEqual(
                SoundManager._command("Linux", path, 50),
                ["paplay", "--volume=32768", str(path)],
            )


if __name__ == "__main__":
    unittest.main()
