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

import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlparse

import httpx


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
        raise NonLocalHostError(
            "Die Umgebungsvariable OLLAMA_HOST benutzt das https-Schema. "
            "Für die Verbindung zu einem lokalen Ollama auf deinem "
            "eigenen Rechner ist TLS weder nötig noch von Ollama "
            "standardmäßig unterstützt.\n\n"
            "So behebst du das: setze OLLAMA_HOST auf "
            "http://127.0.0.1:11434 oder entferne die Variable ganz."
        )
    if parsed.scheme != "http":
        raise NonLocalHostError(
            f"Die Umgebungsvariable OLLAMA_HOST benutzt ein unbekanntes "
            f"Schema ({parsed.scheme!r}). FlameChat akzeptiert nur http "
            "auf einer Loopback-Adresse.\n\n"
            "So behebst du das: setze OLLAMA_HOST auf "
            "http://127.0.0.1:11434 oder entferne die Variable ganz."
        )
    host = parsed.hostname
    if not host:
        raise NonLocalHostError(
            "OLLAMA_HOST enthält keinen gültigen Hostnamen. Erwartet wird "
            "eine Adresse wie http://127.0.0.1:11434. Entferne die Variable "
            "oder setze sie auf genau diesen Wert."
        )
    try:
        infos = socket.getaddrinfo(host, parsed.port or 11434)
    except socket.gaierror as e:
        raise NonLocalHostError(
            f"Der Hostname „{host}“ in OLLAMA_HOST konnte nicht aufgelöst "
            f"werden ({e}).\n\n"
            "So behebst du das: setze OLLAMA_HOST auf http://127.0.0.1:11434 "
            "oder entferne die Variable."
        ) from e
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not ip.is_loopback:
            raise NonLocalHostError(
                f"OLLAMA_HOST verweist auf „{host}“, was zu {ip} aufgelöst "
                "wird. Das ist kein lokaler Rechner, sondern ein externer.\n\n"
                "FlameChat verbindet sich aus Datenschutz­gründen nur mit "
                "deinem eigenen Rechner (127.0.0.1 oder ::1). "
                "So behebst du das: setze OLLAMA_HOST auf "
                "http://127.0.0.1:11434 oder entferne die Variable ganz."
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
class PullProgress:
    status: str
    completed: int = 0
    total: int = 0

    @property
    def fraction(self) -> float:
        return self.completed / self.total if self.total else 0.0


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
            raise OllamaNotRunning(
                "FlameChat konnte Ollama nicht erreichen.\n\n"
                "Wahrscheinlich läuft der Ollama-Dienst gerade nicht. "
                "So bekommst du ihn wieder an:\n"
                " • Beende FlameChat und starte es neu — beim Start wird "
                "Ollama automatisch wieder hochgefahren.\n"
                " • Oder öffne Ollama.app aus dem Programme-Ordner von Hand.\n"
                f"Technische Details: {e}"
            ) from e
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
            raise OllamaNotRunning(
                "Die Verbindung zu Ollama ist unterbrochen.\n\n"
                "Mögliche Ursache: Ollama wurde zwischenzeitlich beendet "
                "(z. B. durch Schlaf­modus oder manuelles Schließen aus "
                "dem Menüleisten-Symbol).\n\n"
                "So geht's wieder: beende FlameChat und starte es neu — "
                "dabei wird Ollama automatisch hochgefahren."
            ) from e
