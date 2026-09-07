"""Safe, non-blocking playback of bundled operational sound cues."""

from __future__ import annotations

import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

try:
    import winsound  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows only
    winsound = None

CUES = frozenset({"alert", "error", "planned", "response", "restored", "support"})


class SoundManager:
    """Play only allowlisted local WAV assets without blocking Tk's event loop."""

    MAX_PLAY_SECONDS = 5

    def __init__(self, config, logger=None, asset_directory=None):
        self.logger = logger
        self.asset_directory = Path(
            asset_directory
            or Path(__file__).resolve().parent / "assets" / "sounds"
        ).resolve()
        self._lock = threading.Lock()
        self._last_played = {}
        self._processes = set()
        self.update(config)

    def update(self, config):
        self.enabled = bool(config.get("sound_enabled", True))
        self.volume = max(0, min(100, int(config.get("sound_volume", 70))))
        self.cooldown = max(0, int(config.get("sound_cooldown_ms", 750))) / 1000

    def play(self, cue, *, force=False, volume=None):
        """Schedule a known cue and return immediately; never execute input as code."""
        if cue not in CUES or (not self.enabled and not force):
            return False
        try:
            selected_volume = (
                self.volume if volume is None else max(0, min(100, int(volume)))
            )
        except (TypeError, ValueError):
            self._log("sound_preview_invalid_volume", "WARNING", cue=cue)
            return False
        if selected_volume == 0:
            return False
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_played.get(cue, 0) < self.cooldown:
                return False
            self._last_played[cue] = now
        path = (self.asset_directory / f"{cue}.wav").resolve()
        if path.parent != self.asset_directory or not path.is_file():
            self._log("sound_asset_missing", "WARNING", cue=cue)
            return False
        threading.Thread(
            target=self._play_worker,
            args=(cue, path, selected_volume),
            name=f"audio-{cue}",
            daemon=True,
        ).start()
        return True

    def preview(self, volume=None):
        return self.play("support", force=True, volume=volume)

    def _play_worker(self, cue, path, volume):
        try:
            system = platform.system()
            if system == "Windows":
                if winsound is None:
                    self._log("sound_backend_unavailable", "WARNING", cue=cue)
                    return
                winsound.PlaySound(
                    str(path), winsound.SND_FILENAME | winsound.SND_NODEFAULT
                )
                return
            command = self._command(system, path, volume)
            if not command:
                self._log("sound_backend_unavailable", "WARNING", cue=cue)
                return
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            with self._lock:
                self._processes.add(process)
            try:
                process.wait(timeout=self.MAX_PLAY_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
                self._log("sound_playback_timeout", "WARNING", cue=cue)
            finally:
                with self._lock:
                    self._processes.discard(process)
            if process.returncode:
                self._log(
                    "sound_playback_failed",
                    "WARNING",
                    cue=cue,
                    return_code=process.returncode,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            self._log("sound_playback_failed", "WARNING", cue=cue, error=str(exc))

    @staticmethod
    def _command(system, path, volume):
        if system == "Darwin" and shutil.which("afplay"):
            return ["afplay", "-v", f"{volume / 100:.2f}", str(path)]
        if system == "Linux" and shutil.which("paplay"):
            return ["paplay", f"--volume={round(65536 * volume / 100)}", str(path)]
        if system == "Linux" and shutil.which("aplay"):
            return ["aplay", "-q", str(path)]
        return None

    def close(self):
        with self._lock:
            processes = tuple(self._processes)
            self._processes.clear()
        for process in processes:
            try:
                process.terminate()
            except OSError:
                pass

    def _log(self, event, level="INFO", **fields):
        if self.logger:
            self.logger.log(event, level, **fields)
