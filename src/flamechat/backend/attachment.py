"""File-attachment policy: size cap, type detection, copy-to-app-data.

Attachments are copied into ``<app_data_dir>/attachments/<chat_id>/`` on
ingest so the chat's transcript can reference them by stable path even
if the user deletes the original. The 500 MB cap is deliberately lower
than what the OS allows — anything larger would either refuse to fit in
a local model's context window or drive the Mac into swap.

Single file per user action — this is a chat app, not a batch tool.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .ollama_manager import app_data_dir


# 500 * 1024 * 1024 bytes. We can lift it later if users complain, but
# a 1 GB image or 2 h audio tends to crater laptop-class hardware.
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024
# Text files go straight into the model's context window — generous but
# much smaller than audio/image. 1 MB of text is roughly 250 000 tokens
# worst case, already past most models' context budget.
MAX_TEXT_SIZE_BYTES = 1 * 1024 * 1024

# Upper bound on how many files the user can attach per action. Keeps
# the UI predictable and prevents accidentally dragging half a folder in.
MAX_FILES_PER_ACTION = 3


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".tiff"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff"}
TEXT_SUFFIXES = {
    # Plain text + markup
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv",
    # Config
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    # Web
    ".html", ".htm", ".xml", ".css", ".svg",
    # Programming languages
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".rs", ".go", ".java",
    ".swift", ".kt", ".rb", ".pl", ".sh", ".bash", ".zsh", ".fish",
    ".sql", ".r", ".lua", ".tex", ".bat", ".ps1", ".dockerfile",
}

AttachmentKind = Literal["image", "audio", "text", "unsupported"]


class AttachmentError(RuntimeError):
    """User-visible problem with the attachment (too big, wrong type, missing)."""


@dataclass(frozen=True)
class Attachment:
    kind: AttachmentKind
    original_name: str
    stored_path: Path
    size_bytes: int
    mime_type: str | None

    @property
    def size_display(self) -> str:
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        if self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        if self.size_bytes < 1024 * 1024 * 1024:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"
        return f"{self.size_bytes / (1024 * 1024 * 1024):.2f} GB"


def classify(path: Path) -> AttachmentKind:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in TEXT_SUFFIXES:
        return "text"
    # Fall back to MIME sniffing for files with uncommon extensions.
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("image/"):
        return "image"
    if mime and mime.startswith("audio/"):
        return "audio"
    if mime and (
        mime.startswith("text/")
        or mime in ("application/json", "application/xml")
    ):
        return "text"
    return "unsupported"


def ingest(src: Path, chat_id: str) -> Attachment:
    """Validate size + type, copy into app data dir, return an Attachment."""
    src = src.expanduser().resolve()
    if not src.exists():
        raise AttachmentError(
            f"Die Datei „{src.name}“ scheint nicht mehr zu existieren.\n"
            "Möglicherweise wurde sie inzwischen verschoben oder gelöscht. "
            "Bitte wähle die Datei neu aus."
        )
    if not src.is_file():
        raise AttachmentError(
            f"„{src.name}“ ist keine Datei, sondern ein Verzeichnis oder "
            "Symlink. Bitte wähle eine einzelne Datei aus."
        )
    size = src.stat().st_size
    if size == 0:
        raise AttachmentError(
            f"Die Datei „{src.name}“ ist leer (0 Byte). Es gibt nichts zu "
            "analysieren oder zu beschreiben. Prüfe den Export deines "
            "Programms und wähle die Datei neu aus."
        )
    if size > MAX_FILE_SIZE_BYTES:
        mb = size / (1024 ** 2)
        cap_mb = MAX_FILE_SIZE_BYTES / (1024 ** 2)
        raise AttachmentError(
            f"Die Datei „{src.name}“ ist {mb:.1f} MB groß und liegt damit "
            f"über dem Limit von {cap_mb:.0f} MB.\n\n"
            "Dieses Limit besteht, damit das Modell und dein Rechner die "
            "Datei noch sinnvoll verarbeiten können. Vorschläge:\n"
            " • Kürze das Audio auf den relevanten Abschnitt.\n"
            " • Exportiere Bilder mit geringerer Auflösung.\n"
            " • Konvertiere Audio in ein verlustbehaftetes Format wie MP3 oder Opus."
        )
    kind = classify(src)
    # Text files are additionally capped at a stricter per-file limit
    # because they go straight into the model's context window.
    if kind == "text" and size > MAX_TEXT_SIZE_BYTES:
        kb = size / 1024
        cap_kb = MAX_TEXT_SIZE_BYTES / 1024
        raise AttachmentError(
            f"Die Textdatei „{src.name}“ ist {kb:.0f} KB groß — mehr als "
            f"das Kontextfenster eines lokalen Modells sinnvoll aufnehmen "
            f"kann (Limit: {cap_kb:.0f} KB).\n\n"
            "Teile die Datei in kleinere Abschnitte und hänge den für dich "
            "relevanten Teil an, oder fasse den Inhalt mit einem anderen "
            "Werkzeug vorher zusammen."
        )
    if kind == "unsupported":
        img = ", ".join(sorted(s.lstrip('.') for s in IMAGE_SUFFIXES))
        aud = ", ".join(sorted(s.lstrip('.') for s in AUDIO_SUFFIXES))
        raise AttachmentError(
            f"„{src.name}“ hat einen Dateityp, den FlameChat nicht lesen "
            f"kann.\n\n"
            f"Unterstützt werden:\n"
            f" • Bilder: {img}\n"
            f" • Audio: {aud}\n"
            f" • Text / Code: .txt, .md, .json, .yaml, .xml, .html, .csv sowie "
            "die meisten Programmier-Quelldateien (.py, .js, .ts, .c/.cpp, "
            ".rs, .go, .java, .rb, .sh …)\n\n"
            "Konvertiere die Datei in eines dieser Formate (zum Beispiel "
            "mit Vorschau / Quicktime / Audacity) und versuche es erneut."
        )

    target_dir = app_data_dir() / "attachments" / chat_id
    target_dir.mkdir(parents=True, exist_ok=True)
    # Hash-prefix the filename so repeated drops of the same file do not
    # collide while still keeping the original name visible in the
    # stored path (helps debugging and makes the "Save as" suggested
    # filename sensible).
    digest = hashlib.sha1(src.read_bytes()[: 1024 * 1024]).hexdigest()[:8]
    target = target_dir / f"{digest}-{src.name}"
    if not target.exists():
        shutil.copy2(src, target)

    mime, _ = mimetypes.guess_type(str(target))
    return Attachment(
        kind=kind,
        original_name=src.name,
        stored_path=target,
        size_bytes=size,
        mime_type=mime,
    )
