"""Ensure a system-wide Ollama is installed and reachable on localhost.

FlameChat does NOT ship its own Ollama binary. Instead we rely on the
official Ollama.app / Ollama installer being present on the machine —
the same binary users get if they download Ollama directly. This keeps
the app bundle small, avoids two copies on disk, and lets users pull
models via the terminal (``ollama pull`` etc.) with the same install the
app talks to.

On first launch we look for a system install in a handful of standard
locations. If nothing is found, FlameChat offers to fetch the official
installer (DMG on macOS, installer EXE on Windows, ``install.sh`` on
Linux) and place the app system-wide. After install we launch it once
and wait for ``127.0.0.1:11434`` to answer.

Once Ollama is serving, we never touch its process again — shutdown of
FlameChat leaves Ollama running, exactly like any other app that talks
to a system service.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx


APP_NAME = "FlameChat"
OLLAMA_PORT = 11434
OLLAMA_HOST = "127.0.0.1"
READY_TIMEOUT_S = 60.0


# Release-channel URLs. Ollama publishes the DMG / EXE / install script
# under stable names so we can link to them without pinning a version.
DMG_URL = "https://github.com/ollama/ollama/releases/latest/download/Ollama.dmg"
WINDOWS_INSTALLER_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"
)
LINUX_INSTALL_SCRIPT_URL = "https://ollama.com/install.sh"


ProgressFn = Callable[[str, int, int], None]
"""Signature: on_progress(phase_label, completed, total). total=1 marks indeterminate steps."""


def app_data_dir() -> Path:
    """Per-user directory for chat history, settings, cached whisper weights."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        root = os.environ.get("APPDATA")
        if root:
            return Path(root) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


class OllamaUnavailable(RuntimeError):
    """Could not find, install, or start a system Ollama."""


@dataclass(frozen=True)
class SystemOllama:
    """Path to the ``ollama`` CLI + the directory to launch the GUI / service."""
    cli_path: Path
    launcher: Path | None  # .app bundle on macOS, None elsewhere


class OllamaManager:
    def __init__(self) -> None:
        pass  # no per-instance state; we never own a subprocess any more

    # --- health checks ----------------------------------------------------
    @staticmethod
    def is_serving() -> bool:
        try:
            r = httpx.get(
                f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags", timeout=2.0
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # --- public entry points ---------------------------------------------
    def ensure_ready(self, on_progress: ProgressFn) -> None:
        """Make sure Ollama is reachable. Install if missing, start if idle.

        Blocks the calling thread; call from a worker and marshal the
        progress callbacks back to the UI.
        """
        if self.is_serving():
            on_progress("Ollama ist bereits aktiv", 1, 1)
            return

        system = self.detect_system_install()
        if system is None:
            on_progress("Ollama wird installiert …", 0, 1)
            try:
                system = self._install_system(on_progress)
            except Exception as e:  # noqa: BLE001 — surface any install failure
                raise OllamaUnavailable(
                    "FlameChat konnte Ollama nicht automatisch installieren.\n\n"
                    f"Technische Details: {e}\n\n"
                    "So kommst du trotzdem weiter:\n"
                    " • Prüfe deine Internetverbindung und versuche es erneut.\n"
                    " • Oder installiere Ollama von Hand: "
                    "https://ollama.com/download — danach startet FlameChat "
                    "beim nächsten Öffnen automatisch."
                ) from e
            if system is None:
                raise OllamaUnavailable(
                    "Die Ollama-Installation wurde durchgeführt, aber FlameChat "
                    "konnte sie anschließend nicht finden.\n\n"
                    "Das sollte normalerweise nicht passieren. Versuche, "
                    "FlameChat neu zu starten. Bleibt das Problem bestehen, "
                    "installiere Ollama von Hand über https://ollama.com/download."
                )

        on_progress("Starte Ollama …", 0, 1)
        try:
            self._launch_system(system)
        except Exception as e:  # noqa: BLE001
            raise OllamaUnavailable(
                "Ollama ist zwar installiert, konnte aber nicht gestartet werden.\n\n"
                f"Technische Details: {e}\n\n"
                "Versuche Ollama.app manuell aus dem Programme-Ordner zu "
                "starten (auf dem Mac) bzw. Ollama aus dem Startmenü (Windows) "
                "und öffne dann FlameChat erneut."
            ) from e
        self._wait_ready(on_progress)

    def stop(self) -> None:
        """No-op: we never own an Ollama process. System Ollama stays up."""
        return

    # --- detection --------------------------------------------------------
    @staticmethod
    def detect_system_install() -> SystemOllama | None:
        """Return the system Ollama paths if one is installed, else None.

        We check the standard per-platform locations AND whatever ``which
        ollama`` returns, so a Homebrew install or a custom path is also
        picked up.
        """
        if sys.platform == "darwin":
            candidates = [
                Path("/Applications/Ollama.app"),
                Path.home() / "Applications" / "Ollama.app",
            ]
            for app in candidates:
                cli = app / "Contents" / "Resources" / "ollama"
                if cli.is_file():
                    return SystemOllama(cli_path=cli, launcher=app)
            # Homebrew CLI fallback (no .app wrapper).
            cli = shutil.which("ollama")
            if cli:
                return SystemOllama(cli_path=Path(cli), launcher=None)
            return None

        if sys.platform == "win32":
            candidates = [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
            ]
            for cli in candidates:
                if cli.is_file():
                    return SystemOllama(cli_path=cli, launcher=cli)
            cli = shutil.which("ollama")
            if cli:
                return SystemOllama(cli_path=Path(cli), launcher=Path(cli))
            return None

        # Linux: ``ollama`` must be on PATH after the official install script.
        cli = shutil.which("ollama")
        if cli:
            return SystemOllama(cli_path=Path(cli), launcher=None)
        return None

    # --- installation -----------------------------------------------------
    def _install_system(self, on_progress: ProgressFn) -> SystemOllama | None:
        """Download and install the official Ollama release system-wide.

        Returns the detected install on success, None if the install
        finished but detection still fails (which shouldn't happen, but
        we want the caller to surface a clean error in that case).
        """
        if sys.platform == "darwin":
            self._install_macos(on_progress)
        elif sys.platform == "win32":
            self._install_windows(on_progress)
        else:
            self._install_linux(on_progress)
        return self.detect_system_install()

    def _install_macos(self, on_progress: ProgressFn) -> None:
        with tempfile.TemporaryDirectory(prefix="flamechat-ollama-") as tmp:
            dmg_path = Path(tmp) / "Ollama.dmg"
            self._download(DMG_URL, dmg_path, on_progress)
            on_progress("Entpacke Ollama-DMG …", 0, 1)
            mount = subprocess.check_output(
                ["hdiutil", "attach", "-nobrowse", "-readonly", str(dmg_path)],
                text=True,
            )
            mount_point = self._parse_hdiutil_mountpoint(mount)
            try:
                src = mount_point / "Ollama.app"
                target = Path("/Applications/Ollama.app")
                if target.exists():
                    shutil.rmtree(target)
                on_progress("Kopiere Ollama nach /Applications …", 0, 1)
                shutil.copytree(src, target, symlinks=True)
            finally:
                subprocess.run(
                    ["hdiutil", "detach", str(mount_point), "-quiet"], check=False
                )

    def _install_windows(self, on_progress: ProgressFn) -> None:
        with tempfile.TemporaryDirectory(prefix="flamechat-ollama-") as tmp:
            exe_path = Path(tmp) / "OllamaSetup.exe"
            self._download(WINDOWS_INSTALLER_URL, exe_path, on_progress)
            on_progress("Starte Ollama-Installer …", 0, 1)
            # `/SILENT` suppresses the UI; `/NORESTART` keeps us in control.
            subprocess.check_call([str(exe_path), "/SILENT", "/NORESTART"])

    def _install_linux(self, on_progress: ProgressFn) -> None:
        with tempfile.TemporaryDirectory(prefix="flamechat-ollama-") as tmp:
            script_path = Path(tmp) / "install.sh"
            self._download(LINUX_INSTALL_SCRIPT_URL, script_path, on_progress)
            script_path.chmod(0o755)
            on_progress("Starte Ollama-Installations-Skript …", 0, 1)
            # The Ollama install script uses sudo internally; we run it
            # interactively so the password prompt reaches the user.
            subprocess.check_call(["sh", str(script_path)])

    @staticmethod
    def _parse_hdiutil_mountpoint(output: str) -> Path:
        for line in output.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[-1].startswith("/Volumes/"):
                return Path(parts[-1].strip())
        raise OllamaUnavailable("hdiutil attach produced no mount point.")

    # --- launch -----------------------------------------------------------
    def _launch_system(self, system: SystemOllama) -> None:
        """Bring the system Ollama into the foreground so the server starts.

        On macOS we ``open`` the .app — it sets up the menu bar icon and
        starts the background service. On Linux we run ``ollama serve``
        as a detached process. On Windows we launch the installed exe.
        """
        if sys.platform == "darwin" and system.launcher is not None:
            subprocess.Popen(
                ["/usr/bin/open", "-a", str(system.launcher)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        if sys.platform == "win32" and system.launcher is not None:
            subprocess.Popen(
                [str(system.launcher), "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            return
        # Linux / Homebrew CLI fallback: start a detached `ollama serve`.
        subprocess.Popen(
            [str(system.cli_path), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _wait_ready(self, on_progress: ProgressFn) -> None:
        deadline = time.time() + READY_TIMEOUT_S
        while time.time() < deadline:
            if self.is_serving():
                on_progress("Bereit", 1, 1)
                return
            on_progress("Warte, bis Ollama bereit ist …", 0, 1)
            time.sleep(0.4)
        raise OllamaUnavailable(
            f"Ollama wurde gestartet, antwortet aber nach {int(READY_TIMEOUT_S)} "
            "Sekunden immer noch nicht.\n\n"
            "Möglicherweise ist ein anderes Programm auf Port 11434 aktiv, "
            "oder Ollama hängt beim ersten Start.\n\n"
            "Versuche Folgendes:\n"
            " • Beende FlameChat und andere Ollama-Instanzen, dann neu starten.\n"
            " • Prüfe im Terminal mit `lsof -iTCP:11434 -sTCP:LISTEN`, "
            "welcher Prozess den Port belegt.\n"
            " • Starte Ollama.app manuell aus dem Programme-Ordner und "
            "öffne FlameChat erneut."
        )

    # --- download primitive ----------------------------------------------
    @staticmethod
    def _download(url: str, target: Path, on_progress: ProgressFn) -> None:
        with httpx.Client(
            follow_redirects=True, timeout=httpx.Timeout(60.0, connect=10.0)
        ) as client:
            with client.stream("GET", url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with target.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        done += len(chunk)
                        on_progress("Lade Ollama-Installer herunter …", done, total or done)
