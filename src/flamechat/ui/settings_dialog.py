"""Preferences dialog: General / Models / Sounds / Chats / About.

Opened via Cmd+, on macOS, Ctrl+, on Windows and Linux, or from the menu.
Changes to toggles apply immediately and are persisted on every flip
through the provided ``SettingsStore``. The language picker is an
exception: it only takes effect at the next app launch, and the dialog
spells that out so users know what to expect.

Accessibility:

* ``wx.Notebook`` is the right containment control on all three
  platforms — VoiceOver, NVDA and Orca all announce the active tab as
  the user switches with Ctrl+Tab / arrow keys.
* Every checkbox / dropdown has an explicit accessible name.
* The "test play" buttons let screen-reader users verify a sound
  without having to send a chat message.
"""

from __future__ import annotations

from typing import Callable

import wx

from .. import APP_NAME, __version__
from ..backend.hardware import HardwareProfile
from ..backend.ollama_client import OllamaClient
from ..backend.settings import Settings, SettingsStore
from ..i18n import LANGUAGE_NAMES, Language, t
from .models_panel import ModelsPanel
from .sounds import SoundBoard
from .theme import apply_theme


INITIAL_TAB_GENERAL = 0
INITIAL_TAB_MODELS = 1
INITIAL_TAB_SOUNDS = 2
INITIAL_TAB_CHATS = 3
INITIAL_TAB_ABOUT = 4


class SettingsDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        *,
        settings: Settings,
        store: SettingsStore,
        sounds: SoundBoard,
        client: OllamaClient,
        profile: HardwareProfile,
        on_models_changed: Callable[[], None],
        on_theme_changed: Callable[[], None] = lambda: None,
        initial_tab: int = INITIAL_TAB_GENERAL,
    ) -> None:
        super().__init__(
            parent,
            title=t("prefs.title"),
            size=(760, 620),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName(t("prefs.name_a11y"))
        self._settings = settings
        self._store = store
        self._sounds = sounds
        self._on_models_changed_ext = on_models_changed
        self._on_theme_changed_ext = on_theme_changed

        outer = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(self)
        self.notebook.SetName(t("prefs.notebook_name"))

        self.general_panel = _GeneralTab(
            self.notebook,
            settings=settings,
            store=store,
            on_theme_changed=self._handle_theme_changed,
        )
        self.notebook.AddPage(self.general_panel, t("prefs.tab_general"))

        self.models_panel = ModelsPanel(
            self.notebook,
            client=client,
            profile=profile,
            on_models_changed=self._handle_models_changed,
            sounds=sounds,
        )
        self.notebook.AddPage(self.models_panel, t("prefs.tab_models"))

        self.sounds_panel = _SoundsTab(
            self.notebook, settings=settings, store=store, sounds=sounds
        )
        self.notebook.AddPage(self.sounds_panel, t("prefs.tab_sounds"))

        self.chats_panel = _ChatsTab(self.notebook, settings=settings, store=store)
        self.notebook.AddPage(self.chats_panel, t("prefs.tab_chats"))

        self.about_panel = _AboutTab(self.notebook)
        self.notebook.AddPage(self.about_panel, t("prefs.tab_about"))

        self.notebook.SetSelection(
            max(0, min(initial_tab, self.notebook.GetPageCount() - 1))
        )
        outer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)

        close = wx.Button(self, wx.ID_CLOSE, t("prefs.close"))
        close.SetName(t("prefs.close_name"))
        outer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizer(outer)

        close.Bind(wx.EVT_BUTTON, lambda _e: self.EndModal(wx.ID_CLOSE))

        apply_theme(self, settings.theme)

    def _handle_models_changed(self) -> None:
        self._on_models_changed_ext()

    def _handle_theme_changed(self) -> None:
        # Re-paint our own window tree first so the picker's sibling
        # controls update immediately, then let the main frame reapply
        # to its own tree.
        apply_theme(self, self._settings.theme)
        self._on_theme_changed_ext()


class _GeneralTab(wx.Panel):
    WHISPER_SIZES = ("tiny", "base", "small", "medium", "large-v3")
    THEME_CODES: tuple[str, ...] = ("dark", "light")

    def __init__(
        self,
        parent: wx.Window,
        *,
        settings: Settings,
        store: SettingsStore,
        on_theme_changed: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._store = store
        self._on_theme_changed = on_theme_changed

        sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(self, label=t("prefs.general.heading"))
        f = heading.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(f)
        sizer.Add(heading, 0, wx.ALL, 12)

        # --- theme ---
        theme_row = wx.BoxSizer(wx.HORIZONTAL)
        theme_label = wx.StaticText(self, label=t("prefs.general.theme_label"))
        theme_choices = [t(f"prefs.general.theme_{c}") for c in self.THEME_CODES]
        self.theme_choice = wx.Choice(self, choices=theme_choices)
        self.theme_choice.SetName(t("prefs.general.theme_name"))
        current_theme = (
            settings.theme if settings.theme in self.THEME_CODES else "dark"
        )
        self.theme_choice.SetSelection(self.THEME_CODES.index(current_theme))
        theme_row.Add(theme_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        theme_row.Add(self.theme_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(theme_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self._add_note(sizer, t("prefs.general.theme_note"))

        # --- language ---
        lang_row = wx.BoxSizer(wx.HORIZONTAL)
        lang_label = wx.StaticText(self, label=t("prefs.general.language_label"))
        self._lang_codes: list[Language] = ["de", "en"]
        self.lang_choice = wx.Choice(
            self, choices=[LANGUAGE_NAMES[c] for c in self._lang_codes]
        )
        self.lang_choice.SetName(t("prefs.general.language_name"))
        current = settings.language if settings.language in self._lang_codes else "en"
        self.lang_choice.SetSelection(self._lang_codes.index(current))
        lang_row.Add(lang_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        lang_row.Add(self.lang_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(lang_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self._add_note(sizer, t("prefs.general.language_note"))

        # --- num_predict cap ---
        np_row = wx.BoxSizer(wx.HORIZONTAL)
        np_label = wx.StaticText(self, label=t("prefs.general.num_predict_label"))
        self.num_predict = wx.SpinCtrl(
            self, min=256, max=65536, initial=settings.max_predict_tokens
        )
        self.num_predict.SetName(t("prefs.general.num_predict_name"))
        np_row.Add(np_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        np_row.Add(self.num_predict, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(np_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self._add_note(sizer, t("prefs.general.num_predict_note"))

        # --- inline limit ---
        il_row = wx.BoxSizer(wx.HORIZONTAL)
        il_label = wx.StaticText(self, label=t("prefs.general.inline_limit_label"))
        self.inline_limit = wx.SpinCtrl(
            self, min=500, max=200000, initial=settings.inline_result_char_limit
        )
        self.inline_limit.SetName(t("prefs.general.inline_limit_name"))
        il_row.Add(il_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        il_row.Add(self.inline_limit, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(il_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self._add_note(sizer, t("prefs.general.inline_limit_note"))

        # --- whisper model picker ---
        wh_row = wx.BoxSizer(wx.HORIZONTAL)
        wh_label = wx.StaticText(self, label=t("prefs.general.whisper_label"))
        self.whisper_choice = wx.Choice(self, choices=list(self.WHISPER_SIZES))
        self.whisper_choice.SetName(t("prefs.general.whisper_name"))
        current_whisper = (
            settings.whisper_model
            if settings.whisper_model in self.WHISPER_SIZES
            else "small"
        )
        self.whisper_choice.SetSelection(self.WHISPER_SIZES.index(current_whisper))
        wh_row.Add(wh_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        wh_row.Add(self.whisper_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(wh_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self._add_note(sizer, t("prefs.general.whisper_note"))

        self.SetSizer(sizer)

        self.theme_choice.Bind(wx.EVT_CHOICE, self._on_theme_selected)
        self.lang_choice.Bind(wx.EVT_CHOICE, self._on_language_changed)
        self.num_predict.Bind(wx.EVT_SPINCTRL, self._on_num_predict_changed)
        self.inline_limit.Bind(wx.EVT_SPINCTRL, self._on_inline_limit_changed)
        self.whisper_choice.Bind(wx.EVT_CHOICE, self._on_whisper_changed)

    def _add_note(self, sizer: wx.BoxSizer, text: str) -> None:
        note = wx.StaticText(self, label=text)
        note.Wrap(680)
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

    def _on_theme_selected(self, _event) -> None:
        idx = self.theme_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        new_theme = self.THEME_CODES[idx]
        if new_theme == self._settings.theme:
            return
        self._settings.theme = new_theme
        self._store.save(self._settings)
        self._on_theme_changed()

    def _on_language_changed(self, _event) -> None:
        idx = self.lang_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._settings.language = self._lang_codes[idx]
        self._store.save(self._settings)

    def _on_num_predict_changed(self, _event) -> None:
        self._settings.max_predict_tokens = self.num_predict.GetValue()
        self._store.save(self._settings)

    def _on_inline_limit_changed(self, _event) -> None:
        self._settings.inline_result_char_limit = self.inline_limit.GetValue()
        self._store.save(self._settings)

    def _on_whisper_changed(self, _event) -> None:
        idx = self.whisper_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._settings.whisper_model = self.WHISPER_SIZES[idx]
        self._store.save(self._settings)


class _SoundsTab(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        *,
        settings: Settings,
        store: SettingsStore,
        sounds: SoundBoard,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._store = store
        self._sounds = sounds

        sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(self, label=t("prefs.sounds.heading"))
        f = heading.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(f)
        sizer.Add(heading, 0, wx.ALL, 12)

        self.sounds_on = wx.CheckBox(self, label=t("prefs.sounds.main_toggle"))
        self.sounds_on.SetName(t("prefs.sounds.main_toggle"))
        self.sounds_on.SetValue(settings.sounds_enabled)
        sizer.Add(self.sounds_on, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        self.typing_on = wx.CheckBox(self, label=t("prefs.sounds.typing_toggle"))
        self.typing_on.SetName(t("prefs.sounds.typing_toggle"))
        self.typing_on.SetValue(settings.typing_sounds_enabled)
        sizer.Add(self.typing_on, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        tests = wx.BoxSizer(wx.HORIZONTAL)
        self.test_send = wx.Button(self, label=t("prefs.sounds.test_send"))
        self.test_send.SetName(t("prefs.sounds.test_send"))
        self.test_receive = wx.Button(self, label=t("prefs.sounds.test_receive"))
        self.test_receive.SetName(t("prefs.sounds.test_receive"))
        self.test_typing = wx.Button(self, label=t("prefs.sounds.test_typing"))
        self.test_typing.SetName(t("prefs.sounds.test_typing"))
        tests.Add(self.test_send, 0, wx.RIGHT, 6)
        tests.Add(self.test_receive, 0, wx.RIGHT, 6)
        tests.Add(self.test_typing, 0)
        sizer.Add(tests, 0, wx.ALL, 12)

        note = wx.StaticText(self, label=t("prefs.sounds.note"))
        note.Wrap(680)
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.SetSizer(sizer)

        self.sounds_on.Bind(wx.EVT_CHECKBOX, self._on_toggle_sounds)
        self.typing_on.Bind(wx.EVT_CHECKBOX, self._on_toggle_typing)
        self.test_send.Bind(wx.EVT_BUTTON, lambda _e: self._sounds.play_send())
        self.test_receive.Bind(wx.EVT_BUTTON, lambda _e: self._sounds.play_receive())
        self.test_typing.Bind(
            wx.EVT_BUTTON, lambda _e: self._sounds.play_typing_sample()
        )

    def _on_toggle_sounds(self, _event) -> None:
        self._settings.sounds_enabled = self.sounds_on.GetValue()
        self._sounds.enabled = self._settings.sounds_enabled
        self._store.save(self._settings)

    def _on_toggle_typing(self, _event) -> None:
        self._settings.typing_sounds_enabled = self.typing_on.GetValue()
        self._sounds.typing_enabled = self._settings.typing_sounds_enabled
        self._store.save(self._settings)


class _ChatsTab(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        *,
        settings: Settings,
        store: SettingsStore,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._store = store

        sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(self, label=t("prefs.chats.heading"))
        f = heading.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(f)
        sizer.Add(heading, 0, wx.ALL, 12)

        self.auto_create = wx.CheckBox(self, label=t("prefs.chats.auto_create"))
        self.auto_create.SetName(t("prefs.chats.auto_create"))
        self.auto_create.SetValue(settings.auto_create_chat)
        sizer.Add(self.auto_create, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        note = wx.StaticText(self, label=t("prefs.chats.note"))
        note.Wrap(680)
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        self.SetSizer(sizer)

        self.auto_create.Bind(wx.EVT_CHECKBOX, self._on_toggle)

    def _on_toggle(self, _event) -> None:
        self._settings.auto_create_chat = self.auto_create.GetValue()
        self._store.save(self._settings)


class _AboutTab(wx.Panel):
    """Version, privacy and keyboard-shortcut cheatsheet — no controls."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        name = wx.StaticText(self, label=t("prefs.about.name"))
        font = name.GetFont()
        font.SetPointSize(font.GetPointSize() + 4)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        name.SetFont(font)
        sizer.Add(name, 0, wx.LEFT | wx.RIGHT | wx.TOP, 14)

        version = wx.StaticText(
            self, label=t("prefs.about.version", version=__version__)
        )
        sizer.Add(version, 0, wx.LEFT | wx.RIGHT, 14)

        tagline = wx.StaticText(self, label=t("prefs.about.tagline"))
        tagline.Wrap(680)
        sizer.Add(tagline, 0, wx.ALL, 14)

        self._add_section(
            sizer, t("prefs.about.privacy_heading"), t("prefs.about.privacy_body")
        )
        self._add_section(
            sizer, t("prefs.about.shortcuts_heading"), t("prefs.about.shortcuts_body")
        )

        self.SetSizer(sizer)

    def _add_section(self, sizer: wx.BoxSizer, heading_text: str, body_text: str) -> None:
        heading = wx.StaticText(self, label=heading_text)
        font = heading.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(font)
        sizer.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 14)

        body = wx.StaticText(self, label=body_text)
        body.Wrap(680)
        sizer.Add(body, 0, wx.ALL, 14)
