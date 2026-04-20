"""Per-user app preferences: sounds on/off, auto-create chat, etc.

Persisted as a single JSON file next to the Ollama binary in the app
data directory. The file is rewritten on every change via atomic
replace, same as the chat store.

The Settings object is mutable — UI code flips fields directly, then
calls ``SettingsStore.save``. A missing or malformed settings file is
treated as "use defaults"; we never crash the app over a settings read.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .ollama_manager import app_data_dir


SETTINGS_VERSION = 1


@dataclass
class Settings:
    sounds_enabled: bool = True
    typing_sounds_enabled: bool = True
    # When True (default) FlameChat always has at least one chat — one is
    # created on first launch and a fresh one takes its place after the
    # user deletes the last existing chat. Power users can turn this off
    # to get an empty chat panel in those cases.
    auto_create_chat: bool = True
    # UI language: "de" or "en". Changes require an app restart.
    # English is the default; switch to German manually in Preferences.
    language: str = "en"
    # Upper bound passed to Ollama as num_predict. Gives the progress
    # percentage a meaningful denominator — the model stops earlier if
    # it is actually finished. Modern models can context much more than
    # this; 8 192 is a reasonable ceiling for a single chat turn.
    max_predict_tokens: int = 8192
    # Longest text that appears directly in the chat transcript. A
    # transcript or long tool result above this threshold is offered as
    # a file save instead of dumped inline.
    inline_result_char_limit: int = 4000
    # Transcription model size for faster-whisper: tiny/base/small/medium/
    # large-v3. "small" is a good default — decent accuracy, fast enough
    # on a laptop CPU.
    whisper_model: str = "small"
    # UI theme: "dark" (default) or "light". Dark is the default on
    # Windows, macOS and Linux — it matches the modern app baseline and
    # is the first thing most users expect. Users who prefer the system
    # light palette can switch in Preferences → General.
    theme: str = "dark"
    version: int = SETTINGS_VERSION


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "settings.json")

    def load(self) -> Settings:
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return Settings()
        defaults = Settings()
        lang = str(data.get("language", defaults.language))
        if lang not in ("de", "en"):
            lang = defaults.language
        whisper_model = str(data.get("whisper_model", defaults.whisper_model))
        if whisper_model not in ("tiny", "base", "small", "medium", "large-v3"):
            whisper_model = defaults.whisper_model
        theme = str(data.get("theme", defaults.theme))
        if theme not in ("dark", "light"):
            theme = defaults.theme
        return Settings(
            sounds_enabled=bool(data.get("sounds_enabled", defaults.sounds_enabled)),
            typing_sounds_enabled=bool(
                data.get("typing_sounds_enabled", defaults.typing_sounds_enabled)
            ),
            auto_create_chat=bool(
                data.get("auto_create_chat", defaults.auto_create_chat)
            ),
            language=lang,
            max_predict_tokens=max(
                256, int(data.get("max_predict_tokens", defaults.max_predict_tokens))
            ),
            inline_result_char_limit=max(
                500,
                int(data.get("inline_result_char_limit", defaults.inline_result_char_limit)),
            ),
            whisper_model=whisper_model,
            theme=theme,
            version=int(data.get("version", 1)),
        )

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        settings.version = SETTINGS_VERSION
        fd, tmp = tempfile.mkstemp(
            prefix=".settings-", suffix=".json", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise
