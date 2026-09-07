#!/usr/bin/env python3
"""Regenerate the project's original MIT-licensed PCM WAV cues."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 44_100
OUTPUT = Path(__file__).resolve().parents[1] / "src/floorterminal/assets/sounds"
CUES = {
    "alert": ((0.00, 0.22, 440), (0.27, 0.22, 440), (0.54, 0.30, 330)),
    "error": ((0.00, 0.20, 392), (0.22, 0.32, 247)),
    "planned": ((0.00, 0.18, 392), (0.19, 0.18, 494), (0.38, 0.28, 587)),
    "response": ((0.00, 0.16, 440), (0.17, 0.16, 554), (0.34, 0.30, 659)),
    "restored": ((0.00, 0.16, 523), (0.17, 0.16, 659), (0.34, 0.36, 784)),
    "support": ((0.00, 0.14, 587), (0.18, 0.14, 587)),
}


def envelope(position, duration):
    return min(1.0, position / 0.025) * min(
        1.0, max(0.0, duration - position) / 0.07
    )


def generate(name, notes):
    duration = max(start + length for start, length, _ in notes) + 0.04
    frames = []
    for index in range(math.ceil(duration * RATE)):
        moment = index / RATE
        sample = 0.0
        for start, length, frequency in notes:
            position = moment - start
            if 0 <= position <= length:
                tone = math.sin(2 * math.pi * frequency * position)
                tone += 0.18 * math.sin(4 * math.pi * frequency * position)
                sample += tone * envelope(position, length)
        frames.append(struct.pack("<h", round(max(-1, min(1, sample * 0.24)) * 32767)))
    with wave.open(str(OUTPUT / f"{name}.wav"), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(b"".join(frames))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, notes in CUES.items():
        generate(name, notes)


if __name__ == "__main__":
    main()
