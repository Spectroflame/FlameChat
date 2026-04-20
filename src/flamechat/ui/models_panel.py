"""Embeddable panel for browsing installed models + pulling recommended ones.

Factored out of the previous ``ModelDialog`` (which is gone now) so it can
live inside the Settings dialog as one notebook tab. Logic and
accessibility are the same; only the containment changed.
"""

from __future__ import annotations

import threading
from typing import Callable

import wx

from ..backend.hardware import HardwareProfile
from ..backend.ollama_client import (
    InstalledModel,
    OllamaClient,
    OllamaError,
    PullProgress,
)
from ..backend.recommendations import ModelSuggestion, recommend
from ..i18n import t
from .sounds import SoundBoard


class ModelsPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        *,
        client: OllamaClient,
        profile: HardwareProfile,
        on_models_changed: Callable[[], None],
        sounds: SoundBoard | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._profile = profile
        self._on_models_changed = on_models_changed
        self._sounds = sounds
        self._installed: list[InstalledModel] = []
        self._build()
        self.refresh_installed()

    def _build(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        summary = _hardware_summary(self._profile)
        summary_ctrl = wx.StaticText(self, label=summary)
        summary_ctrl.SetName(t("models.hardware_name"))
        sizer.Add(summary_ctrl, 0, wx.ALL, 10)

        sizer.Add(
            wx.StaticText(self, label=t("models.installed_label")),
            0,
            wx.LEFT | wx.RIGHT,
            10,
        )
        self.installed_list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.installed_list.SetName(t("models.installed_name"))
        sizer.Add(self.installed_list, 1, wx.EXPAND | wx.ALL, 10)

        sizer.Add(
            wx.StaticText(self, label=t("models.suggestions_label")),
            0,
            wx.LEFT | wx.RIGHT,
            10,
        )
        self.suggestions_list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.suggestions_list.SetName(t("models.suggestions_name"))
        self._suggestions: list[ModelSuggestion] = recommend(self._profile, limit=6)
        for s in self._suggestions:
            self.suggestions_list.Append(
                t(
                    "models.suggestion_row",
                    name=s.display_name,
                    size=s.size_gb,
                    ram=s.ram_required_gb,
                    desc=s.description,
                )
            )
        if self._suggestions:
            self.suggestions_list.SetSelection(0)
        sizer.Add(self.suggestions_list, 1, wx.EXPAND | wx.ALL, 10)

        progress_row = wx.BoxSizer(wx.HORIZONTAL)
        self.pull_button = wx.Button(self, label=t("models.pull_button"))
        self.pull_button.SetName(t("models.pull_name"))
        self.progress = wx.Gauge(self, range=1000)
        self.progress.SetName(t("models.progress_name"))
        self.progress_label = wx.StaticText(self, label="")
        self.progress_label.SetName(t("models.progress_status_name"))
        progress_row.Add(self.pull_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        progress_row.Add(self.progress, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        progress_row.Add(self.progress_label, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(progress_row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(sizer)

        self.pull_button.Bind(wx.EVT_BUTTON, self._on_pull)

    # --- public API -------------------------------------------------------
    def refresh_installed(self) -> None:
        try:
            self._installed = self._client.list_installed()
        except OllamaError as e:
            wx.MessageBox(
                t("models.ollama_unreachable_body", err=e),
                t("models.ollama_unreachable_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._installed = []
        self.installed_list.Clear()
        for m in self._installed:
            size_gb = m.size_bytes / (1024**3)
            self.installed_list.Append(
                t(
                    "models.installed_row",
                    name=m.name,
                    size=size_gb,
                    params=m.parameter_size,
                    quant=m.quantization,
                )
            )

    # --- pull flow --------------------------------------------------------
    def _on_pull(self, _event) -> None:
        idx = self.suggestions_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        suggestion = self._suggestions[idx]
        self.pull_button.Disable()
        self.progress.SetValue(0)
        self.progress_label.SetLabel(
            t("models.pull_starting", model=suggestion.display_name)
        )
        if self._sounds is not None:
            # Byte-bloop progress ticks — the same "something is
            # happening" cue NonvisualAudio and FlameTranscribe use.
            self._sounds.start_click_metronome()
        threading.Thread(
            target=self._run_pull, args=(suggestion.ollama_name,), daemon=True
        ).start()

    def _run_pull(self, model: str) -> None:
        try:
            for p in self._client.pull(model):
                wx.CallAfter(self._on_pull_progress, p)
        except OllamaError as e:
            wx.CallAfter(self._on_pull_error, e)
            return
        wx.CallAfter(self._on_pull_done, model)

    def _on_pull_progress(self, p: PullProgress) -> None:
        if p.total:
            self.progress.SetValue(int(p.fraction * 1000))
            mb_done = p.completed / (1024**2)
            mb_total = p.total / (1024**2)
            self.progress_label.SetLabel(
                t(
                    "models.pull_progress",
                    status=p.status,
                    done=f"{mb_done:.0f}",
                    total=f"{mb_total:.0f}",
                    pct=f"{p.fraction*100:.0f}",
                )
            )
        else:
            self.progress_label.SetLabel(p.status)

    def _on_pull_done(self, model: str) -> None:
        if self._sounds is not None:
            self._sounds.stop_click_metronome()
            self._sounds.play_receive()
        self.progress.SetValue(1000)
        self.progress_label.SetLabel(t("models.pull_done", model=model))
        self.pull_button.Enable()
        self.refresh_installed()
        self._on_models_changed()

    def _on_pull_error(self, err: Exception) -> None:
        if self._sounds is not None:
            self._sounds.stop_click_metronome()
        self.pull_button.Enable()
        self.progress_label.SetLabel(t("chat.error", err=err))
        wx.MessageBox(
            t("models.pull_error_body", err=err),
            t("models.pull_error_title"),
            wx.OK | wx.ICON_ERROR,
            self,
        )


def _hardware_summary(p: HardwareProfile) -> str:
    lines = [
        t("models.hw_os", os=p.os_name),
        t("models.hw_cpu", phys=p.cpu_cores_physical, log=p.cpu_cores_logical),
        t("models.hw_ram", ram=p.total_ram_gb),
    ]
    if p.gpu_vendor == "apple":
        lines.append(
            t("models.hw_apple_gpu", name=p.gpu_name, vram=p.effective_vram_gb)
        )
    elif p.gpu_vendor in ("nvidia", "amd"):
        lines.append(t("models.hw_discrete_gpu", name=p.gpu_name, vram=p.gpu_vram_gb))
    else:
        lines.append(t("models.hw_no_gpu"))
    return "\n".join(lines)
