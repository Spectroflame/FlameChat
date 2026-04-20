"""Persistent chat storage — one JSON file per chat on the local disk.

Chats live in ``<app_data_dir>/chats/<uuid>.json`` where the app data
directory is the same per-user location used by the Ollama binary.
Writes are atomic (tempfile + rename) so a crash during save cannot
corrupt an existing chat.

The JSON schema is intentionally small and future-proof — a ``version``
field lets us add migrations later without breaking old files.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .ollama_manager import app_data_dir


SCHEMA_VERSION = 1
DEFAULT_TITLE = "Neuer Chat"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Chat:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = DEFAULT_TITLE
    model: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    messages: list[dict] = field(default_factory=list)
    version: int = SCHEMA_VERSION

    # Messages stored here are the chat-visible ones: {role: user|assistant,
    # content: str}. The system prompt is NOT stored per chat — it is
    # re-applied on load from the app's global default. Keeping the prompt
    # out of the file lets us evolve the prompt without retroactively
    # rewriting every saved conversation.

    @property
    def is_empty(self) -> bool:
        return not self.messages

    @property
    def updated_display(self) -> str:
        """Short local-time label for the chat list, e.g. '14:32' or '2026-04-18'."""
        try:
            dt = datetime.fromisoformat(self.updated_at)
        except ValueError:
            return self.updated_at
        dt = dt.astimezone()
        now = datetime.now(dt.tzinfo)
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        if (now.date() - dt.date()).days < 7:
            return dt.strftime("%a %H:%M")
        return dt.strftime("%Y-%m-%d")


class ChatStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.dir = (base_dir or app_data_dir()) / "chats"
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- collection ops ---------------------------------------------------
    def list_chats(self) -> list[Chat]:
        """All chats, newest first. Silently skips malformed files."""
        out: list[Chat] = []
        for path in self.dir.glob("*.json"):
            try:
                out.append(self._load_file(path))
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
        out.sort(key=lambda c: c.updated_at, reverse=True)
        return out

    def get(self, chat_id: str) -> Chat | None:
        path = self._path_for(chat_id)
        if not path.exists():
            return None
        try:
            return self._load_file(path)
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None

    # --- individual ops ---------------------------------------------------
    def create(self, model: str | None = None) -> Chat:
        chat = Chat(model=model)
        self.save(chat)
        return chat

    def save(self, chat: Chat) -> None:
        chat.updated_at = _now()
        chat.version = SCHEMA_VERSION
        path = self._path_for(chat.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace so a mid-write crash never produces a half-written
        # file that looks valid at a glance.
        fd, tmp = tempfile.mkstemp(
            prefix=".chat-", suffix=".json", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(chat), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    def delete(self, chat_id: str) -> None:
        path = self._path_for(chat_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def update_title_from_first_message(self, chat: Chat) -> None:
        """If still 'Neuer Chat', derive a title from the first user message."""
        if chat.title and chat.title != DEFAULT_TITLE:
            return
        for msg in chat.messages:
            if msg.get("role") == "user" and msg.get("content"):
                chat.title = _truncate_title(msg["content"])
                return

    # --- internals --------------------------------------------------------
    def _path_for(self, chat_id: str) -> Path:
        return self.dir / f"{chat_id}.json"

    @staticmethod
    def _load_file(path: Path) -> Chat:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return Chat(
            id=data["id"],
            title=data.get("title", DEFAULT_TITLE),
            model=data.get("model"),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
            messages=list(data.get("messages") or []),
            version=int(data.get("version", 1)),
        )


def _truncate_title(raw: str, *, limit: int = 48) -> str:
    """First non-empty line, collapsed whitespace, limited to ``limit`` chars."""
    first_line = next((line.strip() for line in raw.splitlines() if line.strip()), "")
    collapsed = " ".join(first_line.split())
    if len(collapsed) <= limit:
        return collapsed or DEFAULT_TITLE
    return collapsed[: limit - 1].rstrip() + "…"
