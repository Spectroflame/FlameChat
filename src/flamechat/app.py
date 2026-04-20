"""wx.App + MainFrame wiring the UI to the Ollama backend.

Two non-local network destinations are touched — both user-gated, both
clearly telegraphed to the user:

1. The Ollama release channel on GitHub, ONCE on first launch, to fetch
   the Ollama binary into our app data directory. Managed by
   ``OllamaManager``. The PrepareDialog makes this visible and interruptible.
2. Ollama's own model registry when the user clicks the download button
   in the model dialog.

Everything else — chat messages, hardware detection, UI — stays on the
loopback interface. See ``backend/ollama_client.py`` for the loopback
enforcement.
"""

from __future__ import annotations

import atexit

import wx

from . import APP_NAME, __version__
from .i18n import set_language, t
from .backend import hardware
from .backend.chat_store import Chat, ChatStore
from .backend.ollama_client import (
    NonLocalHostError,
    OllamaClient,
    OllamaError,
    OllamaNotRunning,
)
from .backend import audio_analysis, summarization, transcription, vision
from .backend.attachment import Attachment
from .backend.ollama_manager import OllamaManager
from .backend.settings import SettingsStore
from .ui.announcer import Announcer
from .ui.chat_list import ChatListPanel
from .ui.chat_panel import ChatPanel
from .ui.prepare_dialog import PrepareDialog
from .ui.settings_dialog import (
    INITIAL_TAB_ABOUT,
    INITIAL_TAB_CHATS,
    INITIAL_TAB_MODELS,
    INITIAL_TAB_SOUNDS,
    SettingsDialog,
)
from .ui.sounds import SoundBoard
from .ui.theme import apply_theme, prime_native_theme


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant for conversations and coding tasks. "
    "Be concise but complete. When writing code, use fenced code blocks "
    "with the language tag. If the user writes in German, reply in German."
)


class MainFrame(wx.Frame):
    def __init__(
        self,
        *,
        manager: OllamaManager,
        sounds: SoundBoard,
        settings_store: SettingsStore,
        settings,
    ) -> None:
        super().__init__(
            None, title=t("app.title", version=__version__), size=(1100, 760)
        )
        self.SetName(APP_NAME)
        self.SetMinSize((800, 500))

        self.manager = manager
        self.sounds = sounds
        self.announcer = Announcer()
        # Validator already ran in FlameChatApp.OnInit; this cannot raise.
        self.client = OllamaClient()
        self.profile = hardware.detect()
        self.store = ChatStore()
        self.settings_store = settings_store
        self.settings = settings
        self._installed_models: list[str] = []

        self._build_menu()
        self._build_toolbar()
        self._build_split()
        self._build_accelerators()

        self.CreateStatusBar()
        self.SetStatusText(t("status.shortcuts"))
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self.apply_theme()

        wx.CallAfter(self._initial_boot)

    def apply_theme(self) -> None:
        """Paint the frame and every descendant per ``settings.theme``.

        Called once after construction and again whenever the user
        flips the theme picker in Preferences. Dialogs apply their own
        theme on open, so we only need to cover the main window here.
        ``chat.set_theme`` also repaints existing message panels, which
        wouldn't otherwise be reached because they were built after the
        last apply_theme cycle.
        """
        apply_theme(self, self.settings.theme)
        if hasattr(self, "chat"):
            self.chat.set_theme(self.settings.theme)

    def _build_accelerators(self) -> None:
        """Global keyboard shortcuts for focus management and read-back.

        ``Cmd+1 / Ctrl+1`` jumps to the chat list; ``Cmd+2 / Ctrl+2`` to
        the chat input; ``Cmd+3 / Ctrl+3`` to the model chooser in the
        toolbar. Explicit shortcuts make the app usable with keyboard
        and screen readers even on systems where Tab traversal into the
        sidebar or toolbar is unreliable — the splitter traps Tab inside
        itself on Windows, so NVDA users had no way to reach the model
        dropdown without a dedicated accelerator.

        ``Alt/Option + 1..0 + -`` speak the last 11 messages through the
        screen reader. ``Alt+1`` reads the most recent message, ``Alt+2``
        the one before it, and so on; ``Alt+-`` (the key right of 0, i.e.
        ß on German layouts) reads the 11th-most-recent.
        """
        self._focus_list_id = wx.NewIdRef().GetId()
        self._focus_input_id = wx.NewIdRef().GetId()
        self._focus_model_id = wx.NewIdRef().GetId()

        entries: list[tuple[int, int, int]] = [
            (wx.ACCEL_CTRL, ord("1"), self._focus_list_id),
            (wx.ACCEL_CTRL, ord("2"), self._focus_input_id),
            (wx.ACCEL_CTRL, ord("3"), self._focus_model_id),
        ]

        # Alt/Option + digit/minus: announce last 11 messages. Keys in
        # physical-key order: 1..9, 0, then the key right of 0 which
        # carries ß on German and - on US layouts. wxPython's ord maps
        # to the primary (unshifted) character code.
        self._announce_ids: dict[int, int] = {}
        key_codes = [ord(c) for c in "1234567890"] + [ord("-")]
        for offset_from_end, key in enumerate(key_codes, start=1):
            new_id = wx.NewIdRef().GetId()
            self._announce_ids[new_id] = offset_from_end
            entries.append((wx.ACCEL_ALT, key, new_id))
            self.Bind(
                wx.EVT_MENU,
                lambda _e, off=offset_from_end: self.chat.announce_recent_message(off),
                id=new_id,
            )

        table = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(table)
        self.Bind(
            wx.EVT_MENU, lambda _e: self.chat_list.focus_list(), id=self._focus_list_id
        )
        self.Bind(
            wx.EVT_MENU, lambda _e: self.chat.input.SetFocus(), id=self._focus_input_id
        )
        self.Bind(
            wx.EVT_MENU, lambda _e: self._focus_model_choice(), id=self._focus_model_id
        )

        # App-wide Tab routing that bridges the toolbar into the natural
        # Tab ring. Without this, NVDA users (and sighted keyboard users)
        # hit two problems: Tab from the model dropdown is trapped inside
        # the toolbar panel — wx.SplitterWindow doesn't forward focus
        # cleanly on Windows — and Shift+Tab from the chat panes never
        # climbs out of the splitter to reach the toolbar. We patch both
        # directions here so Ctrl+3 is a shortcut, not the only way in.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_global_tab)

    def _focus_model_choice(self) -> None:
        """Move focus to the model dropdown and announce it.

        NVDA reads the Choice's accessible name + current selection when
        focus lands on it; the announcer line is a belt-and-braces hint
        for users who missed the native focus-change event.
        """
        if not hasattr(self, "model_choice"):
            return
        self.model_choice.SetFocus()
        if self.announcer is not None:
            self.announcer.announce(t("say.focus_model_chooser"))

    def _on_global_tab(self, event: wx.KeyEvent) -> None:
        """Frame-level Tab handler: enforce one explicit Tab ring.

        wxPython's default Tab traversal can't cleanly cross the toolbar
        / splitter boundary on Windows, so forward Tab and Shift+Tab end
        up touring different sets of controls. We replace that with one
        explicit cycle — input → attach → send → list → new → delete →
        model picker → input — and drive it here via EVT_CHAR_HOOK so
        both directions always hit the same stops.

        Only acts when the focused widget lives in this frame; modal
        dialogs have their own TopLevelParent, so their Tab navigation
        is left alone.
        """
        if event.GetKeyCode() != wx.WXK_TAB:
            event.Skip()
            return
        if not hasattr(self, "model_choice"):
            event.Skip()
            return
        focused = wx.Window.FindFocus()
        if focused is None or focused.GetTopLevelParent() is not self:
            event.Skip()
            return

        ring = self._tab_ring()
        if not ring:
            event.Skip()
            return

        if focused in ring:
            idx = ring.index(focused)
            offset = -1 if event.ShiftDown() else 1
            target = ring[(idx + offset) % len(ring)]
        else:
            # Focus escaped the ring — most likely on a message body
            # via Ctrl+Up/Down. Tab returns to the input; Shift+Tab
            # steps back into the model chooser.
            target = self.model_choice if event.ShiftDown() else self.chat.input
        target.SetFocus()

    def _tab_ring(self) -> list[wx.Window]:
        """Ordered list of controls that participate in the Tab cycle.

        Dynamic: buttons that are hidden (send vs. abort swap during a
        generation) or disabled (delete with no chat selected) are
        filtered out so Tab never lands on a dead control.
        """
        candidates: list[wx.Window] = [
            self.chat.input,
            self.chat.attach_button,
            self.chat.send_button,
            self.chat.abort_button,
            self.chat_list.list,
            self.chat_list.new_btn,
            self.chat_list.delete_btn,
            self.model_choice,
        ]
        return [w for w in candidates if w.IsShown() and w.IsEnabled()]

    # --- layout -----------------------------------------------------------
    def _build_menu(self) -> None:
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        new_chat = file_menu.Append(wx.ID_NEW, t("menu.file.new_chat"))
        file_menu.AppendSeparator()
        # wx.ID_PREFERENCES wires up the platform-native menu slot — on
        # macOS that is automatically moved to Application > Preferences
        # and given the Cmd+, accelerator. On Windows/Linux we keep it in
        # the File menu with Ctrl+, as the visible shortcut.
        prefs = file_menu.Append(wx.ID_PREFERENCES, t("menu.file.prefs"))
        file_menu.AppendSeparator()
        quit_item = file_menu.Append(wx.ID_EXIT, t("menu.file.quit"))
        menu_bar.Append(file_menu, t("menu.file"))

        models_menu = wx.Menu()
        open_models = models_menu.Append(wx.ID_ANY, t("menu.models.manage"))
        menu_bar.Append(models_menu, t("menu.models"))

        help_menu = wx.Menu()
        about = help_menu.Append(wx.ID_ABOUT, t("menu.help.about"))
        menu_bar.Append(help_menu, t("menu.help"))

        self.SetMenuBar(menu_bar)

        self.Bind(wx.EVT_MENU, lambda _e: self._new_chat(), new_chat)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), quit_item)
        self.Bind(
            wx.EVT_MENU,
            lambda _e: self._open_settings(INITIAL_TAB_MODELS),
            open_models,
        )
        self.Bind(wx.EVT_MENU, lambda _e: self._open_settings(), prefs)
        self.Bind(wx.EVT_MENU, self._on_about, about)

    def _build_toolbar(self) -> None:
        # TAB_TRAVERSAL keeps the wx.Choice reachable via Tab once focus
        # is inside this panel. Cross-panel tab from the splitter is
        # still unreliable on Windows, which is why Ctrl+3 exists.
        self.toolbar_panel = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.model_label = wx.StaticText(
            self.toolbar_panel, label=t("toolbar.model_for_chat")
        )
        self.model_choice = wx.Choice(self.toolbar_panel, choices=[])
        self.model_choice.SetName(t("toolbar.model_name_a11y"))
        # Tooltip announces the shortcut so users who hover (or whose
        # screen reader reads tooltips) learn Ctrl+3 reaches this control.
        self.model_choice.SetToolTip(t("toolbar.model_tooltip"))

        # Host / loopback info lives in Preferences → About, not the
        # main toolbar — it confused users without adding actionable info.
        sizer.Add(self.model_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.model_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        self.toolbar_panel.SetSizer(sizer)

        self.model_choice.Bind(wx.EVT_CHOICE, self._on_model_selected)

    def _build_split(self) -> None:
        self.splitter = wx.SplitterWindow(
            self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH
        )
        self.splitter.SetMinimumPaneSize(220)

        self.chat_list = ChatListPanel(
            self.splitter,
            store=self.store,
            on_open=self._open_chat,
            on_empty=self._show_empty_state,
            auto_create_empty=lambda: self.settings.auto_create_chat,
            announcer=self.announcer,
        )
        self.chat = ChatPanel(
            self.splitter,
            sounds=self.sounds,
            send_handler=self._stream_chat,
            get_active_model=lambda: self._current_model(),
            on_changed=self._on_chat_changed,
            announcer=self.announcer,
            describe_image=self._describe_image,
            analyse_audio=self._analyse_audio,
            transcribe_audio=self._transcribe_audio,
            inline_limit=self.settings.inline_result_char_limit,
            theme=self.settings.theme,
        )
        self.chat.set_system_prompt(DEFAULT_SYSTEM_PROMPT)

        self.splitter.SplitVertically(self.chat_list, self.chat, 280)

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(self.toolbar_panel, 0, wx.EXPAND)
        frame_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

    # --- actions -----------------------------------------------------------
    def _new_chat(self) -> None:
        default_model = self._current_model() or (
            self._installed_models[0] if self._installed_models else None
        )
        self.chat_list.create_new_chat(default_model=default_model)

    def _on_about(self, _event) -> None:
        # The Help → About menu item opens the About tab inside the
        # Preferences dialog, so there is one canonical place for app
        # info (version, privacy, shortcuts).
        self._open_settings(INITIAL_TAB_ABOUT)

    def _open_settings(self, initial_tab: int = INITIAL_TAB_MODELS) -> None:
        dlg = SettingsDialog(
            self,
            settings=self.settings,
            store=self.settings_store,
            sounds=self.sounds,
            client=self.client,
            profile=self.profile,
            on_models_changed=self._reload_installed,
            on_theme_changed=self.apply_theme,
            initial_tab=initial_tab,
        )
        dlg.ShowModal()
        dlg.Destroy()
        self._reload_installed()

    def _on_model_selected(self, _event) -> None:
        chat = self.chat.active_chat()
        idx = self.model_choice.GetSelection()
        new_model = None if idx == wx.NOT_FOUND else self.model_choice.GetString(idx)
        if chat is not None:
            chat.model = new_model
            self.store.save(chat)
            self.chat_list.reload(select_id=chat.id)
        self.SetStatusText(
            t("status.active_model", model=new_model or t("list.no_model_cell"))
        )

    def _open_chat(self, chat: Chat) -> None:
        self.chat.load_chat(chat)
        self._sync_model_dropdown(chat)
        self.SetStatusText(t("status.chat_opened", title=chat.title))
        self.announcer.announce(t("say.chat_opened", title=chat.title))

    def _on_chat_changed(self, chat: Chat) -> None:
        """Called by ChatPanel after every history mutation. Persists + re-titles."""
        self.store.update_title_from_first_message(chat)
        self.store.save(chat)
        self.chat_list.reload(select_id=chat.id)

    def _sync_model_dropdown(self, chat: Chat) -> None:
        if chat.model and chat.model in self._installed_models:
            self.model_choice.SetSelection(self._installed_models.index(chat.model))
        elif self._installed_models:
            # Chat has no model or its model was uninstalled — default to first.
            self.model_choice.SetSelection(0)
            chat.model = self._installed_models[0]
            self.store.save(chat)
        else:
            self.model_choice.SetSelection(wx.NOT_FOUND)

    def _current_model(self) -> str | None:
        idx = self.model_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        return self.model_choice.GetString(idx)

    # --- startup ----------------------------------------------------------
    def _initial_boot(self) -> None:
        """Ollama is already reachable (PrepareDialog saw to that). Load state."""
        self._reload_installed()
        if not self._installed_models:
            self._open_settings(INITIAL_TAB_MODELS)
            self._reload_installed()
        chats = self.store.list_chats()
        if not chats:
            if self.settings.auto_create_chat:
                self.chat_list.create_new_chat(
                    default_model=self._installed_models[0] if self._installed_models else None
                )
            else:
                self._show_empty_state()
        else:
            self._open_chat(chats[0])
            self.chat_list.reload(select_id=chats[0].id)

    def _show_empty_state(self) -> None:
        """Reset the right pane when there are no chats and auto-create is off."""
        self.chat._clear_ui()  # noqa: SLF001
        self.chat._active_chat = None  # noqa: SLF001
        self.chat._set_status(  # noqa: SLF001
            "Keine Chats — lege links einen neuen Chat an, um zu beginnen."
        )

    def _reload_installed(self) -> None:
        try:
            installed = self.client.list_installed()
        except OllamaError as e:
            self.SetStatusText(t("status.ollama_error", err=e))
            return
        names = [m.name for m in installed]
        self._installed_models = names
        self.model_choice.Clear()
        for n in names:
            self.model_choice.Append(n)
        chat = self.chat.active_chat() if hasattr(self, "chat") else None
        if chat is not None:
            self._sync_model_dropdown(chat)

    # --- backend glue ------------------------------------------------------
    def _stream_chat(self, messages, model, cancel_event):
        if not model:
            raise OllamaNotRunning("Kein Modell ausgewählt.")
        # Cap generation length so the progress percentage has a meaningful
        # ceiling. The model may still stop earlier with done:true.
        yield from self.client.chat_stream(
            model,
            messages,
            options={"num_predict": self.settings.max_predict_tokens},
            cancel_event=cancel_event,
        )

    # --- attachment dispatchers ------------------------------------------
    def _describe_image(self, attachments: list[Attachment], cancel_event):
        """Stream a description of one or more images through a vision model."""
        vision_model = vision.pick_vision_model(self._installed_models)
        if vision_model is None:
            # Signal the ChatPanel to show the "no vision model" dialog by
            # raising; ChatPanel surfaces backend errors.
            raise RuntimeError("no_vision_model")
        yield from vision.describe_images(
            self.client,
            model=vision_model,
            image_paths=[a.stored_path for a in attachments],
            cancel_event=cancel_event,
        )

    def _analyse_audio(self, attachment: Attachment, cancel_event, on_progress) -> str:
        """Run the technical audio analysis only. No transcription."""
        on_progress("Analysing audio …", -1.0)
        return audio_analysis.analyze(attachment.stored_path).as_text()

    def _transcribe_audio(
        self, attachment: Attachment, cancel_event, on_progress, summarise: bool
    ) -> tuple[str, str]:
        """Transcribe and (optionally) summarise. Returns (transcript, summary)."""
        on_progress("Preparing transcription model …", -1.0)
        try:
            transcription.ensure_model(self.settings.whisper_model, on_progress)
        except Exception as e:  # noqa: BLE001
            return f"[Transcription model preparation failed: {e}]", ""
        if cancel_event.is_set():
            return "", ""

        on_progress("Transcribing …", 0.0)
        try:
            transcript = transcription.transcribe(
                attachment.stored_path,
                size=self.settings.whisper_model,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )
        except Exception as e:  # noqa: BLE001
            return f"[Transcription failed: {e}]", ""

        transcript_text = transcript.plain_text
        if not summarise or cancel_event.is_set() or not transcript_text:
            return transcript_text, ""

        model = self._current_model()
        if not model:
            # No chat model loaded — skip summary, return transcript only.
            return transcript_text, ""

        on_progress("Summarising transcript …", -1.0)
        try:
            summary_text = summarization.summarize(
                self.client,
                model=model,
                text=transcript_text,
                language=("German" if self.settings.language == "de" else "English"),
                cancel_event=cancel_event,
                on_progress=on_progress,
            )
        except Exception as e:  # noqa: BLE001
            summary_text = f"[Summary failed: {e}]"
        return transcript_text, summary_text

    def _on_close(self, event) -> None:
        self.client.close()
        # Stop the managed subprocess. If Ollama was already running when
        # we started (system install), manager.stop() is a no-op.
        self.manager.stop()
        event.Skip()


class FlameChatApp(wx.App):
    def OnInit(self) -> bool:  # noqa: N802 — wx naming convention
        self.SetAppName(APP_NAME)

        # 0. Load persisted prefs and apply the UI language *before* any
        #    widget exists — otherwise the PrepareDialog would render in
        #    the default language regardless of the user's setting.
        settings_store = SettingsStore()
        settings = settings_store.load()
        try:
            set_language(settings.language)  # type: ignore[arg-type]
        except Exception:
            pass

        # Opt this process into the Windows dark common-controls theme
        # BEFORE the first wx.Dialog or wx.Frame is constructed. The
        # undocumented SetPreferredAppMode call has to run early to take
        # effect on controls that cache their theme handle at creation.
        prime_native_theme(settings.theme)

        # 0b. Create one SoundBoard up-front and apply persisted sound
        #     preferences. PrepareDialog, ModelsPanel (inside Settings)
        #     and MainFrame all share this instance so audio feedback is
        #     consistent everywhere.
        sounds = SoundBoard()
        sounds.enabled = settings.sounds_enabled
        sounds.typing_enabled = settings.typing_sounds_enabled

        # 1. Validate the Ollama host *before* anything else, so a stray
        #    OLLAMA_HOST env var pointing to a remote server stops us
        #    before we open any socket or write any file.
        try:
            OllamaClient().close()
        except NonLocalHostError as e:
            wx.MessageBox(
                (
                    "FlameChat wurde mit einer nicht-lokalen Ollama-Adresse "
                    "gestartet und verbindet sich aus Sicherheitsgründen nur "
                    "mit deinem eigenen Rechner (127.0.0.1).\n\n"
                    f"Fehler: {e}\n\n"
                    "Zum Beheben: lösche die Umgebungsvariable OLLAMA_HOST oder "
                    "setze sie auf http://127.0.0.1:11434 und starte FlameChat "
                    "erneut."
                ),
                "Ollama-Adresse nicht lokal",
                wx.OK | wx.ICON_ERROR,
            )
            return False

        # 2. Prepare Ollama. If a system Ollama is already serving on
        #    localhost the manager detects that and does nothing; if not
        #    installed, it downloads the official installer and installs
        #    Ollama.app to /Applications (or the Windows/Linux equivalent).
        manager = OllamaManager()
        atexit.register(manager.stop)
        prepare = PrepareDialog(None, manager=manager, sounds=sounds)
        apply_theme(prepare, settings.theme)
        result = prepare.ShowModal()
        prepare.Destroy()
        if result != wx.ID_OK:
            manager.stop()
            return False

        # 3. Hand the pre-built pieces to MainFrame so it doesn't create
        #    its own copies.
        frame = MainFrame(
            manager=manager,
            sounds=sounds,
            settings_store=settings_store,
            settings=settings,
        )
        frame.Show()
        # Re-apply after Show: SetBackgroundStyle(BG_STYLE_COLOUR) only
        # sticks once the widget has a native handle, which on wxMSW
        # happens during Show. Applying once before and once after
        # covers both the "constructed but hidden" widgets and the
        # ones that only finish theming on first paint.
        frame.apply_theme()
        return True


def run() -> None:
    import wx.adv  # noqa: F401  — ensure adv is importable early
    app = FlameChatApp()
    app.MainLoop()
