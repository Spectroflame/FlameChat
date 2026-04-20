"""Summarize a block of text through the running Ollama chat model.

Long inputs (multi-hour transcripts) get a Map-Reduce pass: chunks of
~10 000 characters are summarized individually, then the partial
summaries are combined into a final summary. For short inputs one pass
is enough. The function is blocking — call from a worker thread.
"""

from __future__ import annotations

import threading
from typing import Callable

from .ollama_client import OllamaClient


CHUNK_CHAR_SIZE = 10_000
OVERLAP_CHARS = 400


PROMPT_TEMPLATE_EN = (
    "You are an expert summariser. Summarise the following text in clear "
    "{language} as a tight set of bullet points. Focus on facts, names, "
    "numbers, decisions and action items. Leave out filler. Aim for at "
    "most {target_bullets} bullet points.\n\n"
    "TEXT:\n{body}\n\nSUMMARY:"
)


def summarize(
    client: OllamaClient,
    *,
    model: str,
    text: str,
    language: str = "English",
    target_bullets: int = 10,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[str, float], None] | None = None,
) -> str:
    """Return a plain-text bullet summary of ``text``."""
    text = text.strip()
    if not text:
        return ""

    # Fast path — text fits in a single request.
    if len(text) <= CHUNK_CHAR_SIZE:
        if on_progress is not None:
            on_progress("Summarising …", 0.0)
        result = _one_shot(
            client,
            model=model,
            body=text,
            language=language,
            target_bullets=target_bullets,
            cancel_event=cancel_event,
        )
        if on_progress is not None:
            on_progress("Summary ready.", 1.0)
        return result

    # Map-Reduce path.
    chunks = list(_chunk(text))
    partials: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        if cancel_event is not None and cancel_event.is_set():
            break
        if on_progress is not None:
            on_progress(
                f"Summarising part {i} of {len(chunks)} …",
                i / (len(chunks) + 1),
            )
        partials.append(
            _one_shot(
                client,
                model=model,
                body=chunk,
                language=language,
                target_bullets=max(5, target_bullets // 2),
                cancel_event=cancel_event,
            )
        )

    combined = "\n\n".join(partials)
    if on_progress is not None:
        on_progress("Combining partial summaries …", 0.95)
    final = _one_shot(
        client,
        model=model,
        body=combined,
        language=language,
        target_bullets=target_bullets,
        cancel_event=cancel_event,
    )
    if on_progress is not None:
        on_progress("Summary ready.", 1.0)
    return final


def _one_shot(
    client: OllamaClient,
    *,
    model: str,
    body: str,
    language: str,
    target_bullets: int,
    cancel_event: threading.Event | None,
) -> str:
    prompt = PROMPT_TEMPLATE_EN.format(
        language=language, target_bullets=target_bullets, body=body
    )
    messages = [{"role": "user", "content": prompt}]
    chunks: list[str] = []
    for piece in client.chat_stream(
        model, messages, cancel_event=cancel_event, options={"num_predict": 2048}
    ):
        chunks.append(piece)
    return "".join(chunks).strip()


def _chunk(text: str):
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + CHUNK_CHAR_SIZE)
        yield text[start:end]
        if end >= n:
            break
        start = end - OVERLAP_CHARS
