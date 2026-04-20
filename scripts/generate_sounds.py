"""Generate the two UI sounds as 16-bit PCM WAV files.

Run once: ``python scripts/generate_sounds.py``.
Output goes to ``src/flamechat/assets/{send,receive}.wav``.

Why bundled: wx.adv.Sound plays WAVs natively on all three platforms with
no extra audio dependency. Shipping WAVs avoids runtime synthesis.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44_100
# -1.5 dB vs. the previous 0.35 level; user asked for a little quieter send.
SEND_AMPLITUDE = 0.29
RECEIVE_AMPLITUDE = 0.22   # sweeter pling, kept well below send
TYPING_AMPLITUDE = 0.12    # must be very subtle — plays many times per second


def _write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames)


def _envelope(i: int, total: int, attack: float, release: float) -> float:
    t = i / SAMPLE_RATE
    dur = total / SAMPLE_RATE
    if t < attack:
        return t / attack
    if t > dur - release:
        return max(0.0, (dur - t) / release)
    return 1.0


def send_sound() -> list[float]:
    """Short rising pop, WhatsApp-like send swoosh (~120 ms)."""
    duration = 0.12
    n = int(SAMPLE_RATE * duration)
    out: list[float] = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 620.0 + 520.0 * (t / duration)  # 620 Hz -> 1140 Hz sweep
        env = _envelope(i, n, attack=0.005, release=0.05)
        sample = math.sin(2 * math.pi * freq * t) * env * SEND_AMPLITUDE
        out.append(sample)
    return out


def receive_sound() -> list[float]:
    """Sweet single-note pling (~280 ms).

    One bright tone around C6 (1046 Hz) with a fifth above it an octave up
    for sparkle, exponential decay so it fades quickly to silence. The
    slight pitch bend at the very start gives it that iMessage-like
    "cute" character the user asked for.
    """
    duration = 0.28
    n = int(SAMPLE_RATE * duration)
    f0 = 1046.5   # C6
    f1 = 1568.0   # G6, a perfect fifth
    out: list[float] = []
    for i in range(n):
        t = i / SAMPLE_RATE
        # Small upward pitch bend in the first 10 ms for a "cute" onset.
        bend = 1.0 + 0.06 * max(0.0, 1.0 - t / 0.01)
        decay = math.exp(-5.5 * t)
        env = _envelope(i, n, attack=0.004, release=0.06) * decay
        fundamental = math.sin(2 * math.pi * f0 * bend * t)
        overtone = 0.45 * math.sin(2 * math.pi * f1 * bend * t)
        out.append((fundamental + overtone) * env * RECEIVE_AMPLITUDE)
    return out


def typing_sound() -> list[float]:
    """Short mechanical-keyboard tap (~22 ms).

    Noise burst with a high-frequency sine overlay for "click" character.
    Very short + very quiet because this sound plays continuously while
    the model is generating tokens.
    """
    duration = 0.022
    n = int(SAMPLE_RATE * duration)
    out: list[float] = []
    # Crude deterministic pseudo-random so the WAV is reproducible.
    seed = 0x9E3779B1
    for i in range(n):
        seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
        noise = ((seed >> 8) & 0xFFFF) / 0x7FFF - 1.0  # roughly [-1, 1]
        t = i / SAMPLE_RATE
        click = math.sin(2 * math.pi * 3200.0 * t)
        # Steep exponential envelope for a short "tap".
        env = math.exp(-t / 0.0045)
        out.append((0.35 * click + 0.65 * noise) * env * TYPING_AMPLITUDE)
    return out


def main() -> None:
    assets = Path(__file__).resolve().parent.parent / "src" / "flamechat" / "assets"
    _write_wav(assets / "send.wav", send_sound())
    _write_wav(assets / "receive.wav", receive_sound())
    _write_wav(assets / "typing.wav", typing_sound())
    print(f"Wrote send.wav, receive.wav and typing.wav to {assets}")


if __name__ == "__main__":
    main()
