"""Embeddable panel for browsing installed models + pulling recommended ones.

Factored out of the previous ``ModelDialog`` (which is gone now) so it can
live inside the Settings dialog as one notebook tab. Logic and
accessibility are the same; only the containment changed.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import wx

from ..backend.hardware import HardwareProfile
from ..backend.ollama_client import (
    InstalledModel,
    OllamaClient,
    OllamaError,
    PullProgress,
    derive_name_from_url,
    download_gguf,
    is_valid_custom_name,
    is_valid_ollama_id,
    looks_like_url,
    normalise_ollama_ref,
)
from ..backend.ollama_manager import app_data_dir
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
        self._current_pull_name: str = ""
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

        # --- custom model (ID or direct GGUF URL) ---
        custom_heading = wx.StaticText(self, label=t("models.custom_heading"))
        f = custom_heading.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        custom_heading.SetFont(f)
        sizer.Add(custom_heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        custom_note = wx.StaticText(self, label=t("models.custom_note"))
        custom_note.Wrap(700)
        sizer.Add(custom_note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        id_row = wx.BoxSizer(wx.HORIZONTAL)
        id_label = wx.StaticText(self, label=t("models.custom_input_label"))
        # TE_PROCESS_ENTER so Enter inside the field triggers the custom
        # download action instead of silently escaping to the dialog or
        # (worse) falling through to the recommended-model pull button.
        self.custom_input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.custom_input.SetHint(t("models.custom_input_hint"))
        self.custom_input.SetName(t("models.custom_input_name"))
        id_row.Add(id_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        id_row.Add(self.custom_input, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(id_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        name_row = wx.BoxSizer(wx.HORIZONTAL)
        name_label = wx.StaticText(self, label=t("models.custom_name_label"))
        self.custom_name = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.custom_name.SetHint(t("models.custom_name_hint"))
        self.custom_name.SetName(t("models.custom_name_a11y"))
        name_row.Add(name_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        name_row.Add(self.custom_name, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(name_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        self.custom_button = wx.Button(self, label=t("models.custom_button"))
        self.custom_button.SetName(t("models.custom_button"))
        sizer.Add(self.custom_button, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 10)

        self.SetSizer(sizer)

        self.pull_button.Bind(wx.EVT_BUTTON, self._on_pull)
        self.custom_button.Bind(wx.EVT_BUTTON, self._on_custom)
        self.custom_input.Bind(wx.EVT_TEXT_ENTER, self._on_custom)
        self.custom_name.Bind(wx.EVT_TEXT_ENTER, self._on_custom)

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
            # Silent return used to be the norm here, but that made the
            # adjacent custom-model field confusing — users typed into
            # the custom input, hit this button (or Enter), and saw
            # nothing happen. Point them at the right control instead.
            wx.MessageBox(
                t("models.pull_no_selection_body"),
                t("models.pull_no_selection_title"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        suggestion = self._suggestions[idx]
        self._current_pull_name = suggestion.display_name
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
        # Ollama's raw status strings include digests like
        # "pulling ac3d1ba8aa77" that are meaningless to users and very
        # noisy for screen readers (every digit change is announced).
        # Replace them with a stable, model-named label and two friendly
        # phase fallbacks for the short non-byte-carrying transitions
        # (manifest fetch, verify, cleanup).
        name = self._current_pull_name or ""
        if p.total:
            self.progress.SetValue(int(p.fraction * 1000))
            self.progress_label.SetLabel(
                t(
                    "models.pull_progress",
                    model=name,
                    done=_fmt_size(p.completed),
                    total=_fmt_size(p.total),
                    pct=f"{p.fraction * 100:.0f}",
                )
            )
        else:
            key = _pull_phase_key(p.status)
            self.progress_label.SetLabel(t(key, model=name))

    def _on_pull_done(self, model: str) -> None:
        if self._sounds is not None:
            self._sounds.stop_click_metronome()
            self._sounds.play_receive()
        self.progress.SetValue(1000)
        self.progress_label.SetLabel(t("models.pull_done", model=model))
        self.pull_button.Enable()
        self.custom_button.Enable()
        self.custom_input.SetValue("")
        self.custom_name.SetValue("")
        self.refresh_installed()
        self._on_models_changed()

    def _on_pull_error(self, err: Exception) -> None:
        if self._sounds is not None:
            self._sounds.stop_click_metronome()
        self.pull_button.Enable()
        self.custom_button.Enable()
        self.progress_label.SetLabel(t("chat.error", err=err))
        # Typo-in-the-name is by far the most common failure in the
        # custom-model flow (e.g. "Lama3.1:8b" vs. "llama3.1:8b").
        # Ollama returns "pull model manifest: file does not exist" in
        # that case. The generic pull-error dialog talks about network
        # and disk space, which misleads the user into the wrong fix —
        # so catch the manifest case and show a targeted dialog instead.
        msg = str(err).lower()
        if "manifest" in msg and "exist" in msg:
            wx.MessageBox(
                t("models.pull_not_found_body", err=err),
                t("models.pull_not_found_title"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return
        wx.MessageBox(
            t("models.pull_error_body", err=err),
            t("models.pull_error_title"),
            wx.OK | wx.ICON_ERROR,
            self,
        )

    # --- custom download flow ---------------------------------------------
    def _on_custom(self, _event) -> None:
        raw = self.custom_input.GetValue().strip()
        name_raw = self.custom_name.GetValue().strip()
        if not raw:
            wx.MessageBox(
                t("models.custom_empty_body"),
                t("models.custom_invalid_title"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.custom_input.SetFocus()
            return

        if looks_like_url(raw):
            if not raw.lower().endswith(".gguf"):
                wx.MessageBox(
                    t("models.custom_not_gguf_body"),
                    t("models.custom_invalid_title"),
                    wx.OK | wx.ICON_WARNING,
                    self,
                )
                self.custom_input.SetFocus()
                return
            name = name_raw or derive_name_from_url(raw)
            if not is_valid_custom_name(name):
                wx.MessageBox(
                    t("models.custom_bad_name_body"),
                    t("models.custom_invalid_title"),
                    wx.OK | wx.ICON_WARNING,
                    self,
                )
                self.custom_name.SetFocus()
                return
            self._start_custom_url(raw, name)
            return

        # ID path (Ollama name or hf.co reference)
        if not is_valid_ollama_id(raw) and "/" not in raw:
            wx.MessageBox(
                t("models.custom_bad_id_body"),
                t("models.custom_invalid_title"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            self.custom_input.SetFocus()
            return
        self._start_custom_id(normalise_ollama_ref(raw))

    def _start_custom_id(self, model_id: str) -> None:
        self._current_pull_name = model_id
        self.pull_button.Disable()
        self.custom_button.Disable()
        self.progress.SetValue(0)
        self.progress_label.SetLabel(
            t("models.pull_starting", model=model_id)
        )
        if self._sounds is not None:
            self._sounds.start_click_metronome()
        threading.Thread(
            target=self._run_pull, args=(model_id,), daemon=True
        ).start()

    def _start_custom_url(self, url: str, name: str) -> None:
        self.pull_button.Disable()
        self.custom_button.Disable()
        self.progress.SetValue(0)
        self.progress_label.SetLabel(t("models.custom_start", name=name))
        if self._sounds is not None:
            self._sounds.start_click_metronome()
        threading.Thread(
            target=self._run_custom_url, args=(url, name), daemon=True
        ).start()

    def _run_custom_url(self, url: str, name: str) -> None:
        cache_dir = app_data_dir() / "custom_models"
        dest = cache_dir / f"{name.replace('/', '_').replace(':', '_')}.gguf"
        try:
            # Phase 1: download to local disk
            for p in download_gguf(url, dest):
                wx.CallAfter(self._on_custom_download_progress, p, name)

            # Phase 2: hand the file to Ollama as a blob
            def on_blob(phase: str, done: int, total: int) -> None:
                wx.CallAfter(self._on_custom_blob_progress, phase, done, total, name)

            blob_ref = self._client.upload_blob(dest, progress_cb=on_blob)

            # Phase 3: create the model entry from the blob
            wx.CallAfter(self._on_custom_create_start, name)
            for p in self._client.create_from_gguf_blob(name, blob_ref):
                wx.CallAfter(self._on_custom_create_progress, p, name)
        except OllamaError as e:
            wx.CallAfter(self._on_pull_error, e)
            return
        wx.CallAfter(self._on_pull_done, name)

    def _on_custom_download_progress(
        self, p: PullProgress, name: str
    ) -> None:
        if p.total:
            self.progress.SetValue(int(p.fraction * 1000))
            self.progress_label.SetLabel(
                t(
                    "models.custom_downloading",
                    name=name,
                    done=_fmt_size(p.completed),
                    total=_fmt_size(p.total),
                    pct=f"{p.fraction * 100:.0f}",
                )
            )
        else:
            self.progress_label.SetLabel(
                t("models.custom_downloading_indeterminate", name=name)
            )

    def _on_custom_blob_progress(
        self, phase: str, done: int, total: int, name: str
    ) -> None:
        frac = done / total if total else 0.0
        self.progress.SetValue(int(frac * 1000))
        key = (
            "models.custom_hashing"
            if phase == "hashing"
            else "models.custom_uploading"
        )
        self.progress_label.SetLabel(
            t(
                key,
                name=name,
                done=_fmt_size(done),
                total=_fmt_size(total),
                pct=f"{frac * 100:.0f}",
            )
        )

    def _on_custom_create_start(self, name: str) -> None:
        self.progress.Pulse()
        self.progress_label.SetLabel(t("models.custom_creating", name=name))

    def _on_custom_create_progress(self, p: PullProgress, name: str) -> None:
        # Ollama emits short status strings here ("parsing GGUF",
        # "writing manifest", etc). Keep them visible for advanced users
        # but lead with the friendly phrase.
        status = (p.status or "").strip()
        if status and status.lower() != "success":
            self.progress_label.SetLabel(
                t("models.custom_creating_step", name=name, step=status)
            )


def _fmt_size(num_bytes: int) -> str:
    """Human-readable size string. Uses MB below 1 GB, GB above."""
    if num_bytes <= 0:
        return "0 MB"
    mb = num_bytes / (1024 ** 2)
    if mb < 1000:
        return f"{mb:.0f} MB"
    gb = num_bytes / (1024 ** 3)
    return f"{gb:.1f} GB"


_FINALIZING_TOKENS = ("verif", "writing", "removing", "success")


def _pull_phase_key(raw_status: str) -> str:
    """Map Ollama's no-total status strings to a friendly i18n key.

    Ollama emits phases like ``pulling manifest``, ``verifying sha256
    digest``, ``writing manifest``, ``removing any unused layers`` —
    and digest-only strings like ``pulling ac3d1ba8aa77`` when it
    flips to a new layer before bytes start flowing. Anything that
    looks like a post-download step gets the finalizing label; the
    rest (manifest, digest handoff) falls back to preparing.
    """
    status = (raw_status or "").lower()
    if any(token in status for token in _FINALIZING_TOKENS):
        return "models.pull_phase_finalizing"
    return "models.pull_phase_preparing"


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
