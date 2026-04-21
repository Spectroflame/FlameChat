"""Cross-platform WAV playback for the FlameChat UI sounds.

We want three properties:

* A one-shot (send / receive / click) must start playing *instantly* —
  if the first 50 ms of a 120 ms send cue get swallowed by audio-device
  setup, users perceive the sound as truncated or missing.
* A looped typing cue must repeat *seamlessly* — any gap between
  iterations is audible and makes the sound feel broken.
* No extra work for the consumer on platforms where audio is flaky
  (missing PortAudio on a minimal Linux, no audio device on a CI box).

Strategy — pick the best available backend on construction:

1. **sounddevice + soundfile (preferred).** WAVs are loaded into numpy
   arrays once and fed straight to CoreAudio / WASAPI / PulseAudio by
   PortAudio. Both start-up latency and loop gaps vanish because
   there's no per-play process spawn.

2. **winsound (Windows fallback).** If sounddevice's import fails on
   Windows we keep the stdlib ``winsound`` path, which supports
   ``SND_LOOP`` natively.

3. **subprocess (last resort).** ``afplay`` on macOS, ``paplay`` /
   ``aplay`` / ``ffplay`` on Linux, driven by a restart-on-exit thread
   for looping. This is the historical fallback; it has the gap we're
   trying to avoid, but it keeps FlameChat audible on stripped-down
   systems where PortAudio won't load.

Every call is best-effort: if no backend works, the functions silently
do nothing rather than crash the app.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Protocol


class _Backend(Protocol):
    def play_oneshot(self, path: str) -> bool: ...
    def start_loop(self, path: str) -> bool: ...
    def stop_loop(self) -> None: ...


# --- sounddevice backend ---------------------------------------------------

class _SounddeviceBackend:
    """In-process WAV playback via PortAudio.

    Two *persistent* :class:`sd.OutputStream` instances are kept
    running from construction to shutdown:

    * **One-shot stream** — always open, fed by ``_oneshot_callback``
      which drains a thread-safe FIFO of queued samples and returns
      silence when the queue is empty. Keeping the stream open means
      CoreAudio / WASAPI never let the audio device suspend between
      plays, which is exactly the gap users heard at the Settings
      "test" buttons (a cold ``sd.play`` pays 200–300 ms for device
      wakeup on macOS).
    * **Loop stream** — spun up on ``start_loop``, torn down on
      ``stop_loop``. A dedicated stream lets the typing loop coexist
      with a one-shot (send + receive fire while the loop runs)
      without either side truncating the other.

    Both streams run at 44.1 kHz / stereo because all FlameChat WAVs
    are 44.1 kHz. Mono samples get duplicated into two channels
    before being queued so the one-shot callback never has to worry
    about shape mismatches.
    """

    _SAMPLE_RATE = 44100
    _CHANNELS = 2

    def __init__(self) -> None:
        import sounddevice as sd  # noqa: WPS433 — optional import
        import soundfile as sf    # noqa: WPS433
        import numpy as np        # noqa: WPS433

        self._sd = sd
        self._sf = sf
        self._np = np
        self._cache: dict[str, tuple[object, int]] = {}

        # One-shot queue: list of (frames, channels) float32 arrays,
        # consumed front-to-back by the always-on callback stream.
        self._oneshot_queue: list[object] = []
        self._oneshot_current = None
        self._oneshot_pos = 0
        self._oneshot_lock = threading.Lock()
        self._oneshot_stream = None
        try:
            self._oneshot_stream = sd.OutputStream(
                samplerate=self._SAMPLE_RATE,
                channels=self._CHANNELS,
                dtype="float32",
                callback=self._oneshot_callback,
            )
            self._oneshot_stream.start()
        except Exception:
            self._oneshot_stream = None

        # Typing loop stream — created on demand in ``start_loop``.
        self._loop_stream = None
        self._loop_lock = threading.Lock()
        self._loop_buffer = None  # numpy.ndarray (frames, channels)
        self._loop_position = 0

    # --- shared helpers --------------------------------------------------
    def _load(self, path: str) -> tuple[object, int]:
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        data, sr = self._sf.read(path, dtype="float32")
        self._cache[path] = (data, sr)
        return data, sr

    def _to_stream_shape(self, data) -> object:
        """Coerce a raw sample into ``(frames, _CHANNELS)`` float32."""
        np = self._np
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        if data.shape[1] == 1 and self._CHANNELS == 2:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] == 2 and self._CHANNELS == 1:
            data = data.mean(axis=1, keepdims=True).astype("float32")
        return data

    # --- one-shot --------------------------------------------------------
    def _oneshot_callback(self, outdata, frames: int, _time, _status) -> None:
        """Drain the one-shot queue into ``outdata``. Fill the tail with silence."""
        outdata.fill(0)
        written = 0
        with self._oneshot_lock:
            while written < frames:
                if self._oneshot_current is None:
                    if not self._oneshot_queue:
                        return
                    self._oneshot_current = self._oneshot_queue.pop(0)
                    self._oneshot_pos = 0
                buf = self._oneshot_current
                remaining = len(buf) - self._oneshot_pos
                take = min(remaining, frames - written)
                outdata[written:written + take] = buf[
                    self._oneshot_pos:self._oneshot_pos + take
                ]
                written += take
                self._oneshot_pos += take
                if self._oneshot_pos >= len(buf):
                    self._oneshot_current = None
                    self._oneshot_pos = 0

    def play_oneshot(self, path: str) -> bool:
        try:
            data, sr = self._load(path)
        except Exception:
            return False
        # If we couldn't keep a persistent stream (exotic audio
        # hardware, headless CI), fall back to the one-shot sd.play —
        # higher per-play latency but still audible.
        if self._oneshot_stream is None or sr != self._SAMPLE_RATE:
            try:
                self._sd.play(data, sr, blocking=False)
                return True
            except Exception:
                return False
        try:
            shaped = self._to_stream_shape(data)
        except Exception:
            return False
        with self._oneshot_lock:
            self._oneshot_queue.append(shaped)
        return True

    # --- loop ------------------------------------------------------------
    def _loop_callback(self, outdata, frames: int, _time, _status) -> None:
        with self._loop_lock:
            buf = self._loop_buffer
            pos = self._loop_position
            if buf is None:
                outdata.fill(0)
                return
            total = len(buf)
            written = 0
            while written < frames:
                chunk = min(total - pos, frames - written)
                outdata[written:written + chunk] = buf[pos:pos + chunk]
                written += chunk
                pos += chunk
                if pos >= total:
                    pos = 0
            self._loop_position = pos

    def start_loop(self, path: str) -> bool:
        try:
            data, sr = self._load(path)
        except Exception:
            return False
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        channels = data.shape[1]
        self.stop_loop()
        try:
            stream = self._sd.OutputStream(
                samplerate=sr,
                channels=channels,
                dtype="float32",
                callback=self._loop_callback,
            )
        except Exception:
            return False
        with self._loop_lock:
            self._loop_buffer = data
            self._loop_position = 0
        self._loop_stream = stream
        try:
            stream.start()
        except Exception:
            self._loop_stream = None
            return False
        return True

    def stop_loop(self) -> None:
        stream = self._loop_stream
        self._loop_stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        with self._loop_lock:
            self._loop_buffer = None
            self._loop_position = 0


# --- winsound backend (Windows-only fallback) ------------------------------

class _WinsoundBackend:
    def play_oneshot(self, path: str) -> bool:
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except (ImportError, RuntimeError, OSError):
            return False

    def start_loop(self, path: str) -> bool:
        try:
            import winsound
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
            return True
        except (ImportError, RuntimeError, OSError):
            return False

    def stop_loop(self) -> None:
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except (ImportError, RuntimeError, OSError):
            pass


# --- subprocess backend (last-resort cross-platform) -----------------------

def _resolve_oneshot_cmd(path: str) -> list[str] | None:
    if sys.platform == "darwin":
        return ["/usr/bin/afplay", path]
    for name in ("paplay", "aplay", "ffplay"):
        exe = shutil.which(name)
        if exe is None:
            continue
        if name == "ffplay":
            return [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
        return [exe, path]
    return None


def _spawn(cmd: list[str]) -> subprocess.Popen | None:
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except (OSError, ValueError):
        return None


class _LoopedSubprocess:
    """Restart-on-exit subprocess loop. Has an audible gap per iteration."""

    def __init__(self, cmd: list[str]) -> None:
        self._cmd = cmd
        self._stop = threading.Event()
        self._proc_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            proc = _spawn(self._cmd)
            if proc is None:
                return
            with self._proc_lock:
                self._proc = proc
            while True:
                if self._stop.is_set():
                    self._terminate_locked()
                    return
                try:
                    proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            with self._proc_lock:
                self._proc = None

    def _terminate_locked(self) -> None:
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
        except OSError:
            return
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._terminate_locked()
        self._thread.join(timeout=1.0)


class _SubprocessBackend:
    def __init__(self) -> None:
        self._loop: _LoopedSubprocess | None = None

    def play_oneshot(self, path: str) -> bool:
        cmd = _resolve_oneshot_cmd(path)
        if cmd is None:
            return False
        return _spawn(cmd) is not None

    def start_loop(self, path: str) -> bool:
        cmd = _resolve_oneshot_cmd(path)
        if cmd is None:
            return False
        self.stop_loop()
        loop = _LoopedSubprocess(cmd)
        self._loop = loop
        loop.start()
        return True

    def stop_loop(self) -> None:
        loop = self._loop
        self._loop = None
        if loop is not None:
            loop.stop()


# --- public facade ---------------------------------------------------------

def _create_backend() -> _Backend:
    """Pick the best available backend on this machine.

    sounddevice first (smoothest, but needs PortAudio), winsound second
    on Windows (stdlib, clean SND_LOOP), subprocess last (gappy but
    ships with every OS).
    """
    try:
        return _SounddeviceBackend()
    except Exception:
        pass
    if sys.platform.startswith("win"):
        return _WinsoundBackend()
    return _SubprocessBackend()


class AudioPlayer:
    """One-shot and looped WAV playback, abstracted per backend."""

    def __init__(self) -> None:
        self._backend: _Backend = _create_backend()

    def play_oneshot(self, path: str | os.PathLike[str]) -> bool:
        p = str(path)
        if not Path(p).exists():
            return False
        return self._backend.play_oneshot(p)

    def start_loop(self, path: str | os.PathLike[str]) -> bool:
        p = str(path)
        if not Path(p).exists():
            return False
        return self._backend.start_loop(p)

    def stop_loop(self) -> None:
        self._backend.stop_loop()
