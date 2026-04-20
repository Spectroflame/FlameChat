"""Image description via Ollama's multimodal chat API.

Ollama's ``/api/chat`` accepts a ``messages[].images`` list of base64-
encoded image bytes. Any installed model with visual perception can be
passed directly; we just need to identify which installed model to use.
"""

from __future__ import annotations

import base64
import threading
from pathlib import Path
from typing import Iterator

from .ollama_client import OllamaClient


# Substrings that appear in the name of vision-capable models on Ollama.
# Kept conservative: we only reach for a model we are reasonably sure
# can read images, to avoid sending an image to a plain chat model that
# would silently ignore it.
VISION_HINTS = (
    "llava",
    "vision",
    "bakllava",
    "moondream",
    "-vl",
    "qwen2.5vl",
    # Gemma 3 (4B+) and Gemma 4 (all variants) are natively multimodal.
    # Tiny text-only variants like ``gemma3:1b`` are an edge case and
    # will simply error out via Ollama if picked — the user can install
    # a different vision model in that case.
    "gemma3:4b",
    "gemma3:12b",
    "gemma3:27b",
    "gemma4",
)


DEFAULT_PROMPT = (
    "Describe the attached image in clear, concrete language. "
    "Cover the subject, surroundings, colours, text that is visible, "
    "and any notable context. Do not invent details."
)


def pick_vision_model(installed: list[str]) -> str | None:
    """Return the first vision-capable installed model, or None."""
    for name in installed:
        lower = name.lower()
        if any(hint in lower for hint in VISION_HINTS):
            return name
    return None


def describe_images(
    client: OllamaClient,
    *,
    model: str,
    image_paths: list[Path],
    prompt: str | None = None,
    cancel_event: threading.Event | None = None,
) -> Iterator[str]:
    """Stream a description for one or more images at once.

    Ollama's ``/api/chat`` accepts a list of images per message, so all
    N images are described together and the response can cross-reference
    them (e.g. "the first picture shows …, the second …").
    """
    if not image_paths:
        return
    if prompt is None:
        if len(image_paths) == 1:
            prompt = DEFAULT_PROMPT
        else:
            prompt = (
                "Describe each of the attached images in clear, concrete "
                "language. Number them in the order attached. Cover the "
                "subject, surroundings, colours, any visible text, and "
                "relationships between images if relevant. Do not invent "
                "details."
            )
    encoded = [
        base64.b64encode(p.read_bytes()).decode("ascii") for p in image_paths
    ]
    messages = [
        {
            "role": "user",
            "content": prompt,
            "images": encoded,
        }
    ]
    yield from client.chat_stream(model, messages, cancel_event=cancel_event)
