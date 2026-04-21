"""Load and play the FlameChat UI sounds.

Historically this used ``wx.adv.Sound``, but recent macOS builds
(wxPython 4.2.x on Apple Silicon) silently refuse to play anything —
``Play()`` returns False and the user hears nothing. We now decode the
embedded WAVs to temp files and hand playback to a platform-specific
:class:`AudioPlayer` (see ``audio_player.py``). That keeps the
obfuscated-on-disk property (no ``.wav`` files visible inside the app
bundle) while giving us audio that actually plays.

Sounds can be disabled at runtime (e.g. via the Settings dialog) by
flipping ``SoundBoard.enabled`` to False. The typing-loop has its own
``typing_enabled`` flag so users can silence the long running loop
without losing the short send / receive cues.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import random
import re
import tempfile
import threading
from importlib.resources import files
from pathlib import Path

from .audio_player import AudioPlayer


_TYPING_VARIANT_RE = re.compile(r"^_typing_(\d+)_data$")

# Metronome tick interval for long-running operations (downloads,
# installs). Chosen to feel rhythmic rather than urgent. Same feel as
# NonvisualAudio / FlameTranscribe.
CLICK_INTERVAL_S = 1.2


class SoundBoard:
    def __init__(self) -> None:
        self.enabled = True
        self.typing_enabled = True
        self._tmp_paths: list[Path] = []
        self._click_timer: threading.Timer | None = None
        self._click_lock = threading.Lock()
        self._click_running = False
        self._player = AudioPlayer()
        self._typing_player = AudioPlayer()

        # Send / receive: single-slot obfuscated WAV, fallback to asset.
        self._send = self._load_obfuscated("send") or self._load_asset("send.wav")
        self._receive = (
            self._load_obfuscated("receive") or self._load_asset("receive.wav")
        )
        # Click: the "byte-bloop" progress tick shared across FlameChat,
        # FlameTranscribe and NonvisualAudio. Used during long-running
        # operations like downloads and installs via the metronome below.
        self._click = self._load_obfuscated("click")
        # Typing: 0..N obfuscated variants. On each generation we pick one
        # at random and loop it until stop_typing() is called. Old-style
        # single "typing" slot is still accepted as a fallback.
        self._typing_variants: list[Path] = self._load_typing_variants()
        if not self._typing_variants:
            path = self._load_obfuscated("typing") or self._load_asset("typing.wav")
            if path is not None:
                self._typing_variants = [path]

    # --- discovery helpers ------------------------------------------------
    def _load_typing_variants(self) -> list[Path]:
        """Find every ``_typing_<N>_data`` module and extract its WAV."""
        try:
            package = importlib.import_module("flamechat.ui")
        except ImportError:
            return []
        variants: list[tuple[int, Path]] = []
        for info in pkgutil.iter_modules(package.__path__):
            match = _TYPING_VARIANT_RE.match(info.name)
            if not match:
                continue
            path = self._load_obfuscated(f"typing_{match.group(1)}")
            if path is not None:
                variants.append((int(match.group(1)), path))
        variants.sort(key=lambda pair: pair[0])
        return [p for _, p in variants]

    @staticmethod
    def _load_asset(name: str) -> Path | None:
        try:
            ref = files("flamechat.assets").joinpath(name)
            path = Path(str(ref))
            return path if path.exists() else None
        except (FileNotFoundError, ModuleNotFoundError):
            return None

    def _load_obfuscated(self, slot: str) -> Path | None:
        """Decode ``_<slot>_data.WAV_BYTES`` into a temp WAV file.

        Returns the filesystem path to the decoded WAV, or ``None`` if
        the data module is missing or can't be written. Temp files are
        tracked for :meth:`cleanup` so they vanish when the app quits.
        """
        try:
            module = importlib.import_module(f"flamechat.ui._{slot}_data")
        except ImportError:
            return None
        wav_bytes: bytes = getattr(module, "WAV_BYTES", b"")
        if not wav_bytes:
            return None
        try:
            fd, name = tempfile.mkstemp(prefix=f"flamechat-{slot}-", suffix=".wav")
            os.write(fd, wav_bytes)
            os.close(fd)
        except OSError:
            return None
        path = Path(name)
        self._tmp_paths.append(path)
        return path

    def cleanup(self) -> None:
        self._typing_player.stop_loop()
        self._player.stop_loop()
        for p in self._tmp_paths:
            try:
                p.unlink()
            except OSError:
                pass
        self._tmp_paths.clear()

    def play_send(self) -> None:
        if self.enabled and self._send is not None:
            self._player.play_oneshot(self._send)

    def play_receive(self) -> None:
        if self.enabled and self._receive is not None:
            self._player.play_oneshot(self._receive)

    def play_typing_loop(self) -> None:
        """Pick a random typing variant and loop it until ``stop_typing``.

        The random pick avoids the repetitive feeling of always hearing
        the same clip. We always stop the previous loop first, so a
        second call during generation restarts cleanly with a new pick.
        """
        if not (self.enabled and self.typing_enabled):
            return
        if not self._typing_variants:
            return
        variant = random.choice(self._typing_variants)
        self._typing_player.start_loop(variant)

    def stop_typing(self) -> None:
        """Stop any looping typing sound. Safe to call when nothing is playing."""
        self._typing_player.stop_loop()

    def play_typing_sample(self) -> None:
        """Play one random typing variant once (no loop). Used by test buttons."""
        if not self._typing_variants:
            return
        self._typing_player.stop_loop()
        self._player.play_oneshot(random.choice(self._typing_variants))

    # --- click / byte-bloop + metronome ----------------------------------
    def play_click(self) -> None:
        """Play one byte-bloop click. Used as a progress tick sound."""
        if not self.enabled or self._click is None:
            return
        self._player.play_oneshot(self._click)

    def start_click_metronome(self, interval_s: float = CLICK_INTERVAL_S) -> None:
        """Play a click tick every ``interval_s`` until :meth:`stop_click_metronome`.

        Same idea as NonvisualAudio's Metronome and FlameTranscribe's
        ClickPlayer: gentle rhythmic feedback that the app is still
        working on a long-running task. The first tick fires right away
        so the user hears the click as soon as the operation begins.
        """
        if not self.enabled or self._click is None:
            return
        with self._click_lock:
            if self._click_running:
                return
            self._click_running = True
        self.play_click()
        self._schedule_click_tick(interval_s)

    def stop_click_metronome(self) -> None:
        """Stop the ticking metronome. Safe to call when nothing is ticking."""
        with self._click_lock:
            self._click_running = False
            timer = self._click_timer
            self._click_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_click_tick(self, interval_s: float) -> None:
        with self._click_lock:
            if not self._click_running:
                return

            def _tick() -> None:
                with self._click_lock:
                    still = self._click_running
                if not still:
                    return
                self.play_click()
                self._schedule_click_tick(interval_s)

            t = threading.Timer(interval_s, _tick)
            t.daemon = True
            self._click_timer = t
            t.start()
