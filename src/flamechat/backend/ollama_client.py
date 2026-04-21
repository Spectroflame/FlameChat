"""Thin Ollama HTTP client.

All traffic is localhost-only. The only non-local network activity in the
whole app happens inside Ollama itself when it pulls a model — that is a
user-initiated action, gated behind an explicit download button.

Localhost is enforced, not assumed. Before the client opens any socket we
resolve the configured host and reject anything that does not land on a
loopback address (127.0.0.0/8 or ::1). This guards against an attacker or
a mistake setting OLLAMA_HOST to a remote target.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlparse

import httpx

from ..i18n import t


DEFAULT_HOST = "http://127.0.0.1:11434"
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 600.0  # generation can be slow on CPU-only machines


class OllamaError(RuntimeError):
    pass


class OllamaNotRunning(OllamaError):
    pass


class NonLocalHostError(OllamaError):
    """Raised when the configured Ollama host is not a loopback address."""


def validate_loopback(raw: str) -> str:
    """Normalize ``raw`` to ``http://<host>:<port>`` and assert it is loopback.

    Raises :class:`NonLocalHostError` if the host resolves to any address
    outside 127.0.0.0/8 or ::1, or if the scheme is not plain http. TLS on
    loopback adds complexity without a threat model — Ollama does not
    serve https by default either.
    """
    raw = raw.strip()
    if "://" not in raw:
        raw = "http://" + raw  # Ollama's own convention: bare "127.0.0.1:11434"
    parsed = urlparse(raw)
    if parsed.scheme == "https":
        raise NonLocalHostError(t("ollama.loopback.https"))
    if parsed.scheme != "http":
        raise NonLocalHostError(
            t("ollama.loopback.unknown_scheme", scheme=parsed.scheme)
        )
    host = parsed.hostname
    if not host:
        raise NonLocalHostError(t("ollama.loopback.no_host"))
    try:
        infos = socket.getaddrinfo(host, parsed.port or 11434)
    except socket.gaierror as e:
        raise NonLocalHostError(
            t("ollama.loopback.resolve_failed", host=host, err=e)
        ) from e
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not ip.is_loopback:
            raise NonLocalHostError(
                t("ollama.loopback.not_loopback", host=host, ip=ip)
            )
    port = parsed.port or 11434
    # IPv6 literals must be wrapped in brackets in a URL authority.
    host_part = f"[{host}]" if ":" in host else host
    return f"http://{host_part}:{port}"


def resolve_host() -> str:
    """Return the Ollama URL to use, honouring ``OLLAMA_HOST`` if present."""
    return validate_loopback(os.environ.get("OLLAMA_HOST", DEFAULT_HOST))


@dataclass(frozen=True)
class InstalledModel:
    name: str          # e.g. "qwen2.5-coder:3b"
    size_bytes: int
    family: str        # e.g. "qwen2", "llama"
    parameter_size: str  # e.g. "3B"
    quantization: str  # e.g. "Q4_K_M"


@dataclass(frozen=True)
class LoadedModel:
    """A model currently resident in Ollama's RAM/VRAM (``/api/ps``)."""
    name: str
    size_bytes: int       # total resident size (RAM + VRAM)
    size_vram_bytes: int  # how much of it sits in GPU memory


@dataclass(frozen=True)
class PullProgress:
    status: str
    completed: int = 0
    total: int = 0

    @property
    def fraction(self) -> float:
        return self.completed / self.total if self.total else 0.0


# Allowed character set for an Ollama model reference (name + optional tag).
# Deliberately strict on punctuation to reject shell/path trickery, but
# case-insensitive on letters — Ollama accepts "Granite4:3b" and treats it
# the same as "granite4:3b", so the UI should too. Tag case is preserved
# downstream because quantization tags like "Q4_K_M" are conventionally
# uppercase on hf.co references.
_OLLAMA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(:[A-Za-z0-9._-]+)?$")
# Names entered by the user for a URL-downloaded model. Same shape as an
# Ollama ID but we also allow an optional namespace segment with a single
# slash ("user/model:tag") so custom locals can be grouped. Normalised to
# lowercase by ``normalise_ollama_ref`` before being sent to the API.
_CUSTOM_NAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?(:[A-Za-z0-9._-]+)?$"
)


def looks_like_url(text: str) -> bool:
    """True if ``text`` is an http(s) URL — the heuristic the UI uses to
    branch between an Ollama pull and a custom GGUF download."""
    t = text.strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def is_valid_ollama_id(text: str) -> bool:
    return bool(_OLLAMA_ID_RE.match(text.strip()))


def is_valid_custom_name(text: str) -> bool:
    return bool(_CUSTOM_NAME_RE.match(text.strip()))


def normalise_ollama_ref(text: str) -> str:
    """Normalise a user-typed reference to what Ollama expects on the wire.

    The name portion (before the colon) is lowercased because Ollama
    lowercases names server-side — typing ``Granite4:3b`` otherwise
    looks like a miss to first-time users. The tag portion after ``:``
    keeps its case, since quantization tags on hf.co references
    (``Q4_K_M``, ``IQ3_M``) are conventionally uppercase.
    """
    s = text.strip()
    if ":" in s:
        name, _, tag = s.partition(":")
        return f"{name.lower()}:{tag}"
    return s.lower()


def derive_name_from_url(url: str) -> str:
    """Pick a reasonable local model name from a GGUF URL.

    ``https://huggingface.co/TheBloke/Foo-GGUF/resolve/main/foo.Q4_K_M.gguf``
    → ``foo.q4_k_m`` (lowercased, `.gguf` stripped).
    """
    parsed = urlparse(url)
    stem = Path(parsed.path).name
    if stem.lower().endswith(".gguf"):
        stem = stem[:-5]
    stem = stem.lower()
    # Replace anything outside the allowed set with a dash so the name is
    # accepted by Ollama. Leading chars must be alnum.
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-._")
    return cleaned or "custom-model"


def download_gguf(
    url: str,
    dest: Path,
    *,
    chunk_size: int = 1 << 16,
    cancel_event: threading.Event | None = None,
) -> Iterator[PullProgress]:
    """Stream an external URL to ``dest``, yielding progress events.

    This is the one deliberate non-loopback destination in the normal
    lifecycle (the Ollama-binary download is a separate first-launch
    step). We only call it when the user explicitly typed a URL into
    the custom-model field, so the outbound request is user-initiated.

    Yields :class:`PullProgress` for UI reuse — ``status='downloading'``
    while bytes flow, then ``status='verifying'`` on the final event.
    Raises :class:`OllamaError` on HTTP failure or mid-download cancel.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(
            follow_redirects=True, timeout=httpx.Timeout(60.0, connect=10.0)
        ) as c:
            with c.stream("GET", url) as r:
                if r.status_code >= 400:
                    raise OllamaError(
                        f"HTTP {r.status_code} beim Download von {url}"
                    )
                total = int(r.headers.get("content-length", 0))
                done = 0
                yield PullProgress(status="downloading", completed=0, total=total)
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size):
                        if cancel_event is not None and cancel_event.is_set():
                            raise OllamaError("Download vom Nutzer abgebrochen.")
                        f.write(chunk)
                        done += len(chunk)
                        yield PullProgress(
                            status="downloading",
                            completed=done,
                            total=total or done,
                        )
        tmp.replace(dest)
        yield PullProgress(status="verifying", completed=done, total=total or done)
    except httpx.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise OllamaError(f"Netzwerkfehler beim Download: {e}") from e
    except OllamaError:
        tmp.unlink(missing_ok=True)
        raise


class OllamaClient:
    def __init__(self, host: str | None = None) -> None:
        """Build a client bound to a loopback Ollama instance.

        ``host`` defaults to ``OLLAMA_HOST`` or ``DEFAULT_HOST``. Either
        way it runs through :func:`validate_loopback`, so callers cannot
        bypass the check.
        """
        self.host = validate_loopback(host) if host else resolve_host()
        self._client = httpx.Client(
            base_url=self.host,
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        )

    def close(self) -> None:
        self._client.close()

    def ping(self) -> bool:
        try:
            r = self._client.get("/api/tags", timeout=CONNECT_TIMEOUT)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def list_installed(self) -> list[InstalledModel]:
        try:
            r = self._client.get("/api/tags")
        except httpx.HTTPError as e:
            raise OllamaNotRunning(t("ollama.unreachable", err=e)) from e
        r.raise_for_status()
        out: list[InstalledModel] = []
        for m in r.json().get("models", []):
            details = m.get("details") or {}
            out.append(
                InstalledModel(
                    name=m["name"],
                    size_bytes=int(m.get("size", 0)),
                    family=details.get("family", ""),
                    parameter_size=details.get("parameter_size", ""),
                    quantization=details.get("quantization_level", ""),
                )
            )
        return out

    def list_loaded(self) -> list[LoadedModel]:
        """Return which models are currently resident in Ollama's memory.

        Uses ``/api/ps`` — the same endpoint ``ollama ps`` on the
        command line queries. Empty list means nothing is loaded yet
        (fresh Ollama process, or the idle unload timer fired).
        Failures collapse to an empty list: the caller wants a memory
        readout, not a reason to surface an error dialog.
        """
        try:
            r = self._client.get("/api/ps", timeout=CONNECT_TIMEOUT)
            r.raise_for_status()
        except httpx.HTTPError:
            return []
        out: list[LoadedModel] = []
        for m in r.json().get("models", []):
            out.append(
                LoadedModel(
                    name=m.get("name", ""),
                    size_bytes=int(m.get("size", 0)),
                    size_vram_bytes=int(m.get("size_vram", 0)),
                )
            )
        return out

    def pull(self, model: str) -> Iterator[PullProgress]:
        """Stream pull progress. Yields PullProgress until done."""
        with self._client.stream(
            "POST",
            "/api/pull",
            json={"model": model, "stream": True},
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if err := payload.get("error"):
                    raise OllamaError(err)
                yield PullProgress(
                    status=payload.get("status", ""),
                    completed=int(payload.get("completed", 0)),
                    total=int(payload.get("total", 0)),
                )

    def upload_blob(
        self,
        path: Path,
        *,
        progress_cb: Callable[[str, int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Upload ``path`` to Ollama as a content-addressed blob.

        Returns the blob reference (``"sha256:<hex>"``) that ``/api/create``
        expects in its ``files`` map. Hashing and uploading both stream in
        1 MiB chunks and report progress via ``progress_cb(phase, done, total)``
        where ``phase`` is ``"hashing"`` or ``"uploading"``.

        If the blob already exists on the server (HEAD returns 200), the
        upload phase is skipped — Ollama deduplicates by digest, so a second
        run with the same file costs only a hash.
        """
        total = path.stat().st_size
        h = hashlib.sha256()
        done = 0
        with path.open("rb") as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise OllamaError(t("ollama.cancelled_by_user"))
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    progress_cb("hashing", done, total)
        ref = f"sha256:{h.hexdigest()}"

        head = self._client.head(f"/api/blobs/{ref}")
        if head.status_code == 200:
            if progress_cb is not None:
                progress_cb("uploading", total, total)
            return ref

        sent = {"n": 0}

        def chunked() -> Iterator[bytes]:
            with path.open("rb") as f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise OllamaError(t("ollama.cancelled_by_user"))
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    sent["n"] += len(chunk)
                    if progress_cb is not None:
                        progress_cb("uploading", sent["n"], total)
                    yield chunk

        r = self._client.post(f"/api/blobs/{ref}", content=chunked())
        r.raise_for_status()
        return ref

    def create_from_gguf_blob(
        self,
        name: str,
        blob_ref: str,
    ) -> Iterator[PullProgress]:
        """Create a new Ollama model from an already-uploaded GGUF blob.

        ``blob_ref`` is what :meth:`upload_blob` returned (``"sha256:..."``).
        Streams creation status lines — Ollama emits short ``status`` strings
        like ``"parsing GGUF"``, ``"writing manifest"``, ``"success"``.
        """
        body = {
            "model": name,
            "files": {"model.gguf": blob_ref},
            "stream": True,
        }
        with self._client.stream("POST", "/api/create", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if err := payload.get("error"):
                    raise OllamaError(err)
                yield PullProgress(
                    status=payload.get("status", ""),
                    completed=int(payload.get("completed", 0)),
                    total=int(payload.get("total", 0)),
                )

    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        *,
        options: dict | None = None,
        cancel_event=None,
    ) -> Iterator[str]:
        """Stream assistant text chunks. Raises OllamaNotRunning if unreachable.

        If ``cancel_event`` (a :class:`threading.Event`) is set from another
        thread, the iteration breaks out early and the httpx streaming
        context is closed — the server-side generation is abandoned.
        """
        body: dict = {"model": model, "messages": messages, "stream": True}
        if options:
            body["options"] = options
        try:
            with self._client.stream("POST", "/api/chat", json=body) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if err := payload.get("error"):
                        raise OllamaError(err)
                    message = payload.get("message") or {}
                    if chunk := message.get("content"):
                        yield chunk
                    if payload.get("done"):
                        break
        except httpx.ConnectError as e:
            raise OllamaNotRunning(t("ollama.connection_lost")) from e
