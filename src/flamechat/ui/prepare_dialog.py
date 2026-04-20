"""First-run / cold-start dialog: prepares the Ollama subprocess.

Shown before the main window while we check for / download / start
Ollama. It is modal, self-contained, and screen-reader-friendly: the
phase label and the byte counter are StaticText controls that get updated
via wx.CallAfter from the worker thread.
"""

from __future__ import annotations

import threading
from typing import Callable

import wx

from ..backend.ollama_manager import OllamaManager, OllamaUnavailable
from ..i18n import t
from .sounds import SoundBoard


class PrepareDialog(wx.Dialog):
    """Runs ``manager.ensure_ready`` in a thread and reports progress.

    ``ShowModal`` returns ``wx.ID_OK`` on success or ``wx.ID_CANCEL`` on
    user abort / failure. On abort we ask the manager to stop anything it
    started so we leave no zombie subprocess behind.

    While the worker is active we play the typing-loop sound from
    SoundBoard so the user has constant non-visual feedback that
    something is still happening — this is especially important during
    the multi-minute first-run Ollama download.
    """

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        manager: OllamaManager,
        sounds: SoundBoard | None = None,
    ) -> None:
        super().__init__(
            parent,
            title=t("prepare.title"),
            size=(560, 340),
            style=wx.CAPTION | wx.RESIZE_BORDER,
        )
        self.SetName(t("prepare.title"))
        self._manager = manager
        self._sounds = sounds
        self._aborted = False
        self._worker: threading.Thread | None = None
        self._build()
        wx.CallAfter(self._start_worker)

    def _build(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        headline = wx.StaticText(self, label=t("prepare.headline"))
        headline.SetName(t("prepare.headline"))
        font = headline.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        headline.SetFont(font)
        sizer.Add(headline, 0, wx.ALL, 14)

        self.phase = wx.StaticText(self, label=t("prepare.phase_start"))
        self.phase.SetName(t("prepare.phase_start"))
        sizer.Add(self.phase, 0, wx.LEFT | wx.RIGHT, 14)

        self.detail = wx.StaticText(self, label="")
        self.detail.SetName("Details")
        sizer.Add(self.detail, 0, wx.LEFT | wx.RIGHT | wx.TOP, 14)

        self.gauge = wx.Gauge(self, range=1000, size=(-1, 18))
        self.gauge.SetName("Fortschritt")
        sizer.Add(self.gauge, 0, wx.EXPAND | wx.ALL, 14)

        note = wx.StaticText(self, label=t("prepare.note"))
        note.SetName(t("prepare.note"))
        note.Wrap(480)
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer()
        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, t("prepare.cancel"))
        self.cancel_btn.SetName(t("prepare.cancel_name"))
        buttons.Add(self.cancel_btn, 0, wx.ALL, 8)
        sizer.Add(buttons, 0, wx.EXPAND)

        self.SetSizer(sizer)
        self.Layout()

        self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)

    # --- worker thread glue -----------------------------------------------
    def _start_worker(self) -> None:
        # The click metronome starts ONLY if Ollama is not already
        # serving — the common-case "launch, Ollama is already up"
        # path is silent. When there is actual work (install or cold
        # start) the worker will tick.
        if self._sounds is not None and not self._manager.is_serving():
            self._sounds.start_click_metronome()
        self._worker = threading.Thread(target=self._worker_main, daemon=True)
        self._worker.start()

    def _stop_audio(self) -> None:
        if self._sounds is not None:
            self._sounds.stop_click_metronome()

    def _worker_main(self) -> None:
        try:
            self._manager.ensure_ready(self._on_progress)
        except OllamaUnavailable as e:
            wx.CallAfter(self._on_failure, str(e))
            return
        except Exception as e:  # noqa: BLE001 — surface anything
            wx.CallAfter(self._on_failure, str(e))
            return
        wx.CallAfter(self._on_success)

    def _on_progress(self, phase: str, done: int, total: int) -> None:
        if self._aborted:
            return
        wx.CallAfter(self._apply_progress, phase, done, total)

    # Manager emits these German phase strings; we translate them into
    # the active UI language here so the i18n layer stays in the UI tier.
    _PHASE_MAP = {
        "Ollama ist bereits aktiv": "prepare.ollama_running",
        "Ollama wird installiert …": "prepare.ollama_installing",
        "Lade Ollama-Installer herunter …": "prepare.ollama_downloading",
        "Entpacke Ollama-DMG …": "prepare.ollama_mounting",
        "Kopiere Ollama nach /Applications …": "prepare.ollama_copying",
        "Starte Ollama-Installer …": "prepare.ollama_win_installer",
        "Starte Ollama-Installations-Skript …": "prepare.ollama_linux_script",
        "Starte Ollama …": "prepare.ollama_starting",
        "Warte, bis Ollama bereit ist …": "prepare.ollama_waiting",
        "Bereit": "prepare.ollama_ready",
    }

    def _apply_progress(self, phase: str, done: int, total: int) -> None:
        key = self._PHASE_MAP.get(phase)
        self.phase.SetLabel(t(key) if key else phase)
        if total and total > 1:
            pct = done / total
            self.gauge.SetValue(int(pct * 1000))
            mb_done = done / (1024**2)
            mb_total = total / (1024**2)
            self.detail.SetLabel(f"{mb_done:.1f} / {mb_total:.1f} MB ({pct*100:.0f}%)")
        else:
            # Indeterminate phase (startup wait). Pulse the gauge so users
            # know we are still alive.
            self.gauge.Pulse()
            self.detail.SetLabel("")

    def _on_success(self) -> None:
        # Deliberately no pling here: opening the main window should be
        # silent so users who open FlameChat many times a day don't have
        # to hear a completion chime they never asked for. The click
        # metronome during an actual download still plays — that audio
        # feedback is useful when something is genuinely happening.
        self._stop_audio()
        self.gauge.SetValue(1000)
        self.phase.SetLabel(t("prepare.phase_ready"))
        self.EndModal(wx.ID_OK)

    def _on_failure(self, msg: str) -> None:
        self._stop_audio()
        wx.MessageBox(
            t("prepare.fail_body", err=msg),
            t("prepare.fail_title"),
            wx.OK | wx.ICON_ERROR,
            self,
        )
        self._manager.stop()
        self.EndModal(wx.ID_CANCEL)

    def _on_cancel(self, _event) -> None:
        self._aborted = True
        self._stop_audio()
        self.phase.SetLabel(t("prepare.phase_aborting"))
        self.cancel_btn.Disable()
        # Stop anything we started; then close.
        threading.Thread(
            target=self._cancel_worker, daemon=True
        ).start()

    def _cancel_worker(self) -> None:
        self._manager.stop()
        wx.CallAfter(self.EndModal, wx.ID_CANCEL)
