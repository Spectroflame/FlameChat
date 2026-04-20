"""Offline audio transcription via faster-whisper.

We intentionally do not download models from Hugging Face in the main
thread — callers must ensure the model is cached first by calling
:func:`ensure_model` from a worker thread with a progress callback. On
first run that takes a minute over a fast connection; later runs hit
the on-disk cache and start almost instantly.

The whisper cache sits next to the Ollama binary in the app data
directory so cleaning up FlameChat is a single ``rm -rf``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .ollama_manager import app_data_dir


MODEL_CACHE_DIR = app_data_dir() / "whisper"


ProgressFn = Callable[[str, float], None]
"""``progress(phase_label, fraction 0..1)`` — fraction<0 means indeterminate."""


@dataclass
class TranscriptSegment:
    start: float  # seconds
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    duration: float
    segments: list[TranscriptSegment]

    @property
    def plain_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())


def ensure_model(
    size: str,
    on_progress: ProgressFn | None = None,
) -> None:
    """Download the whisper weights for ``size`` if not cached yet.

    This is idempotent; ``faster-whisper``'s ``WhisperModel`` constructor
    performs the download itself, we just set the cache directory and
    hand the progress back up.
    """
    from faster_whisper import WhisperModel  # local import — optional dep

    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if on_progress is not None:
        on_progress(f"Preparing whisper model '{size}' …", -1.0)
    # The constructor downloads the model on first use.
    WhisperModel(
        size,
        device="auto",
        compute_type="int8",
        download_root=str(MODEL_CACHE_DIR),
    )
    if on_progress is not None:
        on_progress("Whisper model ready.", 1.0)


def transcribe(
    audio_path: Path,
    *,
    size: str = "small",
    language: str | None = None,
    on_progress: ProgressFn | None = None,
    cancel_event: threading.Event | None = None,
) -> Transcript:
    """Transcribe the file at ``audio_path``. Blocks the calling thread.

    ``language=None`` triggers auto-detection. Pass ``"de"`` / ``"en"``
    to force a language (faster and more accurate when you know).
    """
    from faster_whisper import WhisperModel  # local import

    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(
        size,
        device="auto",
        compute_type="int8",
        download_root=str(MODEL_CACHE_DIR),
    )

    if on_progress is not None:
        on_progress("Transcribing …", 0.0)

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,  # skip silence
        beam_size=5,
    )

    segments: list[TranscriptSegment] = []
    duration = max(info.duration, 0.001)
    for seg in segments_iter:
        if cancel_event is not None and cancel_event.is_set():
            break
        segments.append(
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text)
        )
        if on_progress is not None:
            on_progress("Transcribing …", min(1.0, seg.end / duration))

    if on_progress is not None:
        on_progress("Transcription ready.", 1.0)

    return Transcript(
        language=info.language, duration=info.duration, segments=segments
    )
