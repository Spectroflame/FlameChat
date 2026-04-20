"""Load and play the send / receive sounds.

Uses wx.adv.Sound which is built into wxPython and works on all three
platforms with bundled WAV files. No extra audio dependency.

Sounds can be disabled at runtime (e.g. a user setting in the menu) by
flipping ``SoundBoard.enabled`` to False.
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

import wx
import wx.adv


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
        self._typing_variants: list[wx.adv.Sound] = self._load_typing_variants()
        if not self._typing_variants:
            snd = self._load_obfuscated("typing") or self._load_asset("typing.wav")
            if snd is not None:
                self._typing_variants = [snd]

    # --- discovery helpers ------------------------------------------------
    def _load_typing_variants(self) -> list[wx.adv.Sound]:
        """Find every ``_typing_<N>_data`` module and load its WAV."""
        try:
            package = importlib.import_module("flamechat.ui")
        except ImportError:
            return []
        variants: list[tuple[int, wx.adv.Sound]] = []
        for info in pkgutil.iter_modules(package.__path__):
            match = _TYPING_VARIANT_RE.match(info.name)
            if not match:
                continue
            snd = self._load_obfuscated(f"typing_{match.group(1)}")
            if snd is not None:
                variants.append((int(match.group(1)), snd))
        variants.sort(key=lambda pair: pair[0])
        return [snd for _, snd in variants]

    @staticmethod
    def _load_asset(name: str) -> wx.adv.Sound | None:
        try:
            ref = files("flamechat.assets").joinpath(name)
            path = Path(str(ref))
            if not path.exists():
                return None
            snd = wx.adv.Sound(str(path))
            return snd if snd.IsOk() else None
        except (FileNotFoundError, ModuleNotFoundError):
            return None

    def _load_obfuscated(self, slot: str) -> wx.adv.Sound | None:
        """Load WAV from ``_<slot>_data.WAV_BYTES`` if that module exists.

        Prefers ``wx.adv.Sound.CreateFromData`` (no disk touch at all); if
        that refuses the bytes — the API is known to be finicky — we drop
        them to a temp file we clean up on quit. An installed app bundle
        therefore never has a plain-text .wav on disk.
        """
        try:
            module = importlib.import_module(f"flamechat.ui._{slot}_data")
        except ImportError:
            return None
        wav_bytes: bytes = getattr(module, "WAV_BYTES", b"")
        if not wav_bytes:
            return None
        try:
            snd = wx.adv.Sound()
            if snd.CreateFromData(wav_bytes) and snd.IsOk():
                return snd
        except Exception:
            pass
        try:
            fd, name = tempfile.mkstemp(prefix=f"flamechat-{slot}-", suffix=".wav")
            os.write(fd, wav_bytes)
            os.close(fd)
            path = Path(name)
            self._tmp_paths.append(path)
            snd = wx.adv.Sound(str(path))
            return snd if snd.IsOk() else None
        except OSError:
            return None

    def cleanup(self) -> None:
        for p in self._tmp_paths:
            try:
                p.unlink()
            except OSError:
                pass
        self._tmp_paths.clear()

    def play_send(self) -> None:
        if self.enabled and self._send is not None:
            self._send.Play(wx.adv.SOUND_ASYNC)

    def play_receive(self) -> None:
        if self.enabled and self._receive is not None:
            self._receive.Play(wx.adv.SOUND_ASYNC)

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
        wx.adv.Sound.Stop()
        variant = random.choice(self._typing_variants)
        variant.Play(wx.adv.SOUND_ASYNC | wx.adv.SOUND_LOOP)

    def stop_typing(self) -> None:
        """Stop any looping typing sound. Safe to call when nothing is playing."""
        wx.adv.Sound.Stop()

    def play_typing_sample(self) -> None:
        """Play one random typing variant once (no loop). Used by test buttons."""
        if not self._typing_variants:
            return
        wx.adv.Sound.Stop()
        random.choice(self._typing_variants).Play(wx.adv.SOUND_ASYNC)

    # --- click / byte-bloop + metronome ----------------------------------
    def play_click(self) -> None:
        """Play one byte-bloop click. Used as a progress tick sound."""
        if not self.enabled or self._click is None:
            return
        self._click.Play(wx.adv.SOUND_ASYNC)

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
