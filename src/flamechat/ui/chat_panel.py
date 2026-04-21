"""The chat view: a scrollable message list on top, an input field below.

Layout and accessibility:

* Each message is its own focusable, read-only ``wx.TextCtrl`` inside a
  ``MessagePanel`` (role label + content). Native text navigation works
  inside a message; Cmd/Ctrl+Up and Cmd/Ctrl+Down jump between messages.
  This is much more reliable for VoiceOver / NVDA / Orca than a single
  giant TextCtrl — the screen reader always knows which message it is on.
* Role label and accessible name both include speaker and position, e.g.
  "Nachricht 3 von 5. Assistant:" — so VO reads something meaningful when
  focus lands on a message.
* Enter sends; Shift+Enter inserts a newline. This is the mainstream chat
  convention and what the user asked for.
* Each message has a right-click / Shift+F10 / context-menu-key menu with
  three actions: copy, regenerate (assistant messages only), save as TXT.
* We still do NOT stream characters into a message during generation —
  screen readers would re-read the growing buffer on every token. The
  assistant message appears once, fully, when generation finishes. A
  status line reports progress for sighted users.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

import wx

from ..backend.attachment import (
    Attachment,
    AttachmentError,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_ACTION,
    ingest as ingest_attachment,
)
from ..backend.chat_store import Chat
from ..i18n import t
from .announcer import Announcer
from .intent_dialog import (
    AttachmentIntentDialog,
    INTENT_ANALYSE,
    INTENT_IMAGE,
    INTENT_TEXT,
    INTENT_TRANSCRIBE,
    INTENT_TRANSCRIBE_SUMMARY,
)
from .sounds import SoundBoard
from .theme import apply_theme


# Upper bound we pass to Ollama via num_predict. Lets us show a real
# percentage during generation: "current_tokens / MAX_PREDICT". If the
# model stops earlier with `done:true` we snap to 100%.
MAX_PREDICT_TOKENS = 2048

# Seconds between two Alt+N presses that still count as a "double tap".
# 500 ms matches the OS-level double-click default on macOS, Windows
# and most Linux desktops — long enough to re-press deliberately, short
# enough not to conflate with a re-read after the screen reader has
# finished speaking.
DOUBLE_TAP_WINDOW_S = 0.5


Message = dict[str, str]  # {"role": "user"|"assistant"|"system", "content": "..."}


def _role_label(role: str) -> str:
    return t({"user": "msg.role_user",
              "assistant": "msg.role_assistant",
              "system": "msg.role_system"}.get(role, "msg.role_assistant"))

CONTEXT_MENU_COPY_ID = wx.NewIdRef()
CONTEXT_MENU_REGEN_ID = wx.NewIdRef()
CONTEXT_MENU_SAVE_ID = wx.NewIdRef()


def _is_copy_shortcut(event: wx.KeyEvent) -> bool:
    return event.GetKeyCode() in (ord("C"), ord("c")) and (
        event.CmdDown() or event.ControlDown()
    )


@dataclass
class _MessageRecord:
    role: str
    content: str
    panel: "MessagePanel | None" = field(default=None, repr=False)


class _MessageBody(wx.TextCtrl):
    """Read-only message body that stays out of the Tab ring.

    The transcript is navigated with Ctrl+Up/Down (see _handle_nav_key
    on ChatPanel), and the Alt+1..0/- shortcuts read recent messages
    aloud. Tab-stopping on every message would force screen-reader
    users to page through the whole history before reaching the input,
    which is the exact opposite of what they want. Overriding
    AcceptsFocusFromKeyboard drops us from Tab traversal while leaving
    programmatic SetFocus (the Ctrl+Up/Down target) untouched.
    """

    def AcceptsFocusFromKeyboard(self):  # noqa: N802 — wx API name
        return False


class MessagePanel(wx.Panel):
    """A single message row: role label + scrollable read-only text box."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        role: str,
        content: str,
        position_label: str,
        nav_handler: Callable[[wx.KeyEvent], bool],
        announcer: Announcer | None = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.role = role
        self._content = content
        self._nav_handler = nav_handler
        self._announcer = announcer

        sizer = wx.BoxSizer(wx.VERTICAL)

        role_text = _role_label(role)
        self.header = wx.StaticText(self, label=f"{role_text}:")
        header_font = self.header.GetFont()
        header_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.header.SetFont(header_font)
        self.header.SetName(f"{position_label} {role_text}")
        sizer.Add(self.header, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)

        self.body = _MessageBody(
            self,
            value=content,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_AUTO_URL
                  | wx.BORDER_NONE,
        )
        self.body.SetName(f"{position_label} {role_text}: {t('msg.a11y_body_suffix')}")
        # Assistant messages get a slight indent to make the speaker change
        # visually obvious without relying on colour alone.
        if role == "assistant":
            sizer.Add(self.body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        else:
            sizer.Add(self.body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.SetSizer(sizer)
        self._resize_body_to_fit()

        # Context menu: on macOS, wx.TextCtrl consumes right-click for its
        # own native Cut/Copy/Paste menu and EVT_CONTEXT_MENU never fires
        # for the body. Binding EVT_RIGHT_DOWN directly pre-empts that.
        # For keyboard users (Shift+F10, the context-menu key) we still
        # bind EVT_CONTEXT_MENU on the panel frame.
        self.body.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)
        self.header.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        # Cmd/Ctrl+Up/Down nav + Cmd/Ctrl+C copy shortcut. EVT_CHAR_HOOK
        # pre-empts wx.TextCtrl's own handling — on macOS, Cmd+Up/Down
        # are consumed by NSTextView as "jump to start/end of text", so
        # an EVT_KEY_DOWN binding never sees them.
        self.body.Bind(wx.EVT_CHAR_HOOK, self._on_body_key)

    # --- public API -------------------------------------------------------
    def get_content(self) -> str:
        return self._content

    def focus_body(self) -> None:
        self.body.SetFocus()
        self.body.SetInsertionPoint(0)

    def _on_body_key(self, event: wx.KeyEvent) -> None:
        # Cmd/Ctrl+C on a focused message: copy the whole message when
        # nothing is selected. If the user *has* selected text we let
        # wxPython's native copy run (event.Skip).
        if _is_copy_shortcut(event):
            sel_start, sel_end = self.body.GetSelection()
            if sel_start == sel_end:
                self._menu_copy(None)
                return
        if self._nav_handler(event):
            return
        event.Skip()

    def update_position_label(self, position_label: str) -> None:
        role_text = _role_label(self.role)
        self.header.SetName(f"{position_label} {role_text}")
        self.body.SetName(f"{position_label} {role_text}: {t('msg.a11y_body_suffix')}")

    # --- layout helpers ---------------------------------------------------
    def _resize_body_to_fit(self) -> None:
        # Pick a reasonable height: number of wrapped lines * line height.
        # The ScrolledWindow containing us handles scrolling between messages.
        lines = self._content.count("\n") + 1
        # Give a minimum of 1 line and cap at 20 so very long messages do
        # not push the input off the screen on small windows.
        visible_lines = max(1, min(lines, 20))
        line_px = self.body.GetCharHeight() + 2
        self.body.SetMinSize((-1, visible_lines * line_px + 8))

    # --- context menu -----------------------------------------------------
    def _on_right_down(self, event: wx.MouseEvent) -> None:
        # Do NOT skip: we consume the right-click so macOS's native
        # TextCtrl menu does not appear instead of ours.
        src = event.GetEventObject()
        client_pos = event.GetPosition()
        if src is self.body or src is self.header:
            client_pos = self.ScreenToClient(src.ClientToScreen(client_pos))
        self._show_menu(client_pos)

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        pos = event.GetPosition()
        if pos == wx.DefaultPosition:
            # Keyboard-triggered (Shift+F10 / context key): anchor on the
            # message body so the menu appears where focus is.
            pos = self.body.ClientToScreen((8, 8))
        self._show_menu(self.ScreenToClient(pos))

    def _show_menu(self, client_pos: wx.Point) -> None:
        menu = wx.Menu()
        menu.Append(CONTEXT_MENU_COPY_ID.GetId(), t("msg.menu_copy"))
        if self.role == "assistant":
            menu.Append(CONTEXT_MENU_REGEN_ID.GetId(), t("msg.menu_regen"))
        menu.Append(CONTEXT_MENU_SAVE_ID.GetId(), t("msg.menu_save"))

        self.Bind(wx.EVT_MENU, self._menu_copy, id=CONTEXT_MENU_COPY_ID.GetId())
        if self.role == "assistant":
            self.Bind(wx.EVT_MENU, self._menu_regen, id=CONTEXT_MENU_REGEN_ID.GetId())
        self.Bind(wx.EVT_MENU, self._menu_save, id=CONTEXT_MENU_SAVE_ID.GetId())

        self.PopupMenu(menu, client_pos)
        menu.Destroy()

    def _menu_copy(self, _event) -> None:
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(self._content))
            wx.TheClipboard.Close()
            if self._announcer is not None:
                self._announcer.announce(t("say.copied"))

    def _menu_regen(self, _event) -> None:
        # The ChatPanel is our grand-parent; it owns the history and the
        # send handler, so it performs the actual work.
        chat_panel = self.GetParent()
        while chat_panel is not None and not isinstance(chat_panel, ChatPanel):
            chat_panel = chat_panel.GetParent()
        if chat_panel is not None:
            chat_panel.regenerate_from(self)

    def _menu_save(self, _event) -> None:
        role_text = _role_label(self.role)
        default = t("msg.save_default_file", role=role_text.lower())
        with wx.FileDialog(
            self,
            t("msg.save_dialog_title"),
            wildcard=t("msg.save_wildcard"),
            defaultFile=default,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            try:
                with open(fd.GetPath(), "w", encoding="utf-8") as f:
                    f.write(f"{role_text}:\n{self._content}\n")
            except OSError as e:
                if self._announcer is not None:
                    self._announcer.announce(t("say.save_failed"), interrupt=True)
                wx.MessageBox(
                    t("msg.save_error_body", err=e),
                    t("msg.save_error_title"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return
            if self._announcer is not None:
                self._announcer.announce(t("say.saved"))


class ChatPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        *,
        sounds: SoundBoard,
        send_handler: Callable[[list[Message], str, threading.Event], Iterable[str]],
        get_active_model: Callable[[], str | None],
        on_changed: Callable[[Chat], None] = lambda _c: None,
        announcer: Announcer | None = None,
        describe_image: (
            Callable[[list[Attachment], threading.Event], Iterable[str]] | None
        ) = None,
        analyse_audio: (
            Callable[[Attachment, threading.Event, Callable[[str, float], None]], str]
            | None
        ) = None,
        transcribe_audio: (
            Callable[
                [Attachment, threading.Event, Callable[[str, float], None], bool],
                tuple[str, str],
            ]
            | None
        ) = None,
        inline_limit: int = 4000,
        theme: str = "dark",
    ) -> None:
        super().__init__(parent)
        self._sounds = sounds
        self._send_handler = send_handler
        self._get_active_model = get_active_model
        self._on_changed = on_changed
        self._announcer = announcer
        self._describe_image = describe_image
        self._analyse_audio = analyse_audio
        self._transcribe_audio = transcribe_audio
        self._inline_limit = inline_limit
        # Current theme is tracked here so every message panel we build
        # from now on gets painted on construction. Message panels are
        # created dynamically on chat load / send / regenerate, long
        # after the frame-level apply_theme has finished, so without
        # this we'd paint the frame dark and then add light children.
        self._theme = theme
        self._active_chat: Chat | None = None
        self._system_prompt: str | None = None
        self._history: list[Message] = []
        self._messages: list[_MessageRecord] = []
        self._busy = False
        self._cancel_event: threading.Event | None = None
        # Files the user has attached but not yet sent. Images and text
        # stage here; audio intents run immediately and bypass this.
        self._staged: list[Attachment] = []
        # Alt+N multi-tap tracking: the same shortcut, pressed
        # repeatedly inside DOUBLE_TAP_WINDOW, cycles through actions
        # on the same message — 1st tap speaks it, 2nd copies it, 3rd
        # speaks its size details (chars + rough token estimate).
        self._last_recent_offset: int | None = None
        self._last_recent_time: float = 0.0
        self._last_recent_count: int = 0
        # Running token count for the in-flight generation; drives the
        # Ctrl+Shift+S announcement during the "writing" phase.
        self._token_count: int = 0
        self._build()

    def _build(self) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        list_label = wx.StaticText(self, label=t("chat.transcript_label"))
        outer.Add(list_label, 0, wx.ALL, 4)

        self.message_list = wx.ScrolledWindow(
            self,
            style=wx.VSCROLL | wx.TAB_TRAVERSAL,
        )
        self.message_list.SetName(t("chat.transcript_label"))
        self.message_list.SetScrollRate(0, 20)
        self._list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.message_list.SetSizer(self._list_sizer)

        self._empty_label = wx.StaticText(
            self.message_list, label=t("chat.empty_state")
        )
        self._empty_label.Wrap(560)
        self._list_sizer.Add(self._empty_label, 0, wx.ALL, 10)

        outer.Add(self.message_list, 1, wx.EXPAND | wx.ALL, 4)

        input_label = wx.StaticText(self, label=t("chat.input_label"))
        self.input = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
            size=(-1, 90),
        )
        self.input.SetName(t("chat.input_name"))
        self.input.SetHint(t("chat.input_hint"))
        outer.Add(input_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        outer.Add(self.input, 0, wx.EXPAND | wx.ALL, 4)

        # Staging strip — populated by image / text intents. Hidden by
        # default; shown as soon as something is staged.
        self._staging_panel = wx.Panel(self)
        self._staging_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._staging_label = wx.StaticText(
            self._staging_panel, label=t("chat.staging_label")
        )
        self._staging_label.SetName(t("chat.staging_label"))
        font = self._staging_label.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._staging_label.SetFont(font)
        self._staging_sizer.Add(
            self._staging_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8
        )
        self._staging_panel.SetSizer(self._staging_sizer)
        self._staging_panel.Hide()
        outer.Add(self._staging_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.attach_button = wx.Button(self, label=t("chat.attach"))
        self.attach_button.SetName(t("chat.attach_name"))
        self.attach_button.SetToolTip(t("chat.attach_name"))
        self.send_button = wx.Button(self, label=t("chat.send"))
        self.send_button.SetName(t("chat.send_name"))
        self.send_button.SetToolTip("Enter")
        self.abort_button = wx.Button(self, label=t("chat.abort"))
        self.abort_button.SetName(t("chat.abort_name"))
        self.abort_button.SetToolTip("Esc")
        self.abort_button.Hide()

        self.progress = wx.Gauge(self, range=1000, size=(150, 14))
        self.progress.SetName(t("chat.progress_name"))
        self.progress.Hide()

        self.status = wx.StaticText(self, label=t("chat.status_ready"))
        self.status.SetName("Status")
        bottom.Add(self.attach_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        bottom.Add(self.send_button, 0, wx.ALIGN_CENTER_VERTICAL)
        bottom.Add(self.abort_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        bottom.AddSpacer(12)
        bottom.Add(self.progress, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        bottom.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(bottom, 0, wx.EXPAND | wx.ALL, 6)

        self.SetSizer(outer)

        self.send_button.Bind(wx.EVT_BUTTON, self._on_send)
        self.abort_button.Bind(wx.EVT_BUTTON, lambda _e: self._request_cancel())
        self.attach_button.Bind(wx.EVT_BUTTON, lambda _e: self._on_attach())
        self.input.Bind(wx.EVT_KEY_DOWN, self._on_input_key)
        # Keep the send button in sync with "there's something to send":
        # empty input and no staged attachments → disabled, so screen
        # reader users get a clear "dimmed" cue and accidental clicks
        # just do nothing.
        self.input.Bind(wx.EVT_TEXT, lambda _e: self._refresh_send_button())
        self._refresh_send_button()

        self.input.SetFocus()

    # --- public API used by MainFrame --------------------------------------
    def load_chat(self, chat: Chat) -> None:
        """Replace the visible conversation with the contents of ``chat``."""
        self._clear_ui()
        self._active_chat = chat
        self._history = list(chat.messages)
        # Re-apply the system prompt in front (it is not persisted per chat).
        if self._system_prompt:
            self._history.insert(0, {"role": "system", "content": self._system_prompt})
        for msg in chat.messages:
            self._append_message(msg["role"], msg["content"])
        self.message_list.Layout()
        self.message_list.FitInside()
        self._scroll_to_bottom()
        self._set_status(
            t("chat.status_ready") if chat.messages else t("chat.status_ready_new")
        )
        self.input.SetFocus()

    def active_chat(self) -> Chat | None:
        return self._active_chat

    def activate_recent_message(self, offset_from_end: int) -> None:
        """Handle Alt+N: cycle speak → copy → details on rapid re-taps.

        The Alt+1..0/ß shortcuts address the last 11 messages. A
        single press speaks the message. Pressing the *same* shortcut
        again inside :data:`DOUBLE_TAP_WINDOW_S` copies it to the
        clipboard. A third press in the same window announces size
        details (character count + rough token estimate) — the
        "advanced" information we stopped surfacing in the status
        bar. Any press on a different slot, or a press after the
        window expires, resets the cycle.
        """
        now = time.monotonic()
        in_window = (
            self._last_recent_offset == offset_from_end
            and (now - self._last_recent_time) <= DOUBLE_TAP_WINDOW_S
        )
        next_count = self._last_recent_count + 1 if in_window else 1
        self._last_recent_offset = offset_from_end
        self._last_recent_time = now
        self._last_recent_count = next_count

        if next_count == 1:
            self.announce_recent_message(offset_from_end)
        elif next_count == 2:
            self._copy_recent_message(offset_from_end)
        else:
            # Third (or later) press: announce details. Keep the
            # counter pinned so a very fast fourth press doesn't
            # wrap back to "speak" — the user's intent is clearly
            # "drill into this message", not "start over".
            self._announce_message_details(offset_from_end)

    def announce_recent_message(self, offset_from_end: int) -> None:
        """Speak the message at ``offset_from_end`` via the screen reader.

        ``offset_from_end == 1`` means the most recent message, ``2`` the
        one before it, and so on. If the chat has no messages or the
        offset is beyond what exists, we say so in the active language
        — a silent beep is useless to blind users.
        """
        if self._announcer is None:
            return
        if offset_from_end < 1:
            return
        total = len(self._messages)
        if total == 0:
            self._announcer.announce(t("say.no_messages_in_chat"), interrupt=True)
            return
        idx = total - offset_from_end
        if idx < 0 or idx >= total:
            self._announcer.announce(
                t("say.only_n_messages", count=total), interrupt=True
            )
            return
        rec = self._messages[idx]
        role_text = _role_label(rec.role)
        self._announcer.announce(
            f"{role_text}: {rec.content}", interrupt=True
        )

    def _copy_recent_message(self, offset_from_end: int) -> None:
        """Second Alt+N tap: copy the targeted message's body to clipboard."""
        total = len(self._messages)
        idx = total - offset_from_end
        if idx < 0 or idx >= total:
            if self._announcer is not None:
                self._announcer.announce(
                    t("say.only_n_messages", count=total), interrupt=True
                )
            return
        content = self._messages[idx].content
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(content))
            wx.TheClipboard.Close()
        if self._announcer is not None:
            self._announcer.announce(t("say.copied"), interrupt=True)

    def _announce_message_details(self, offset_from_end: int) -> None:
        """Third Alt+N tap: speak size details for the targeted message.

        Token count is estimated at 4 characters per token — the
        rough heuristic for Latin-script text. It isn't the exact
        number Ollama would bill for, but it's in the right
        ballpark and saves us from shipping a real tokenizer just
        to answer "is this a big message?".
        """
        total = len(self._messages)
        idx = total - offset_from_end
        if idx < 0 or idx >= total or self._announcer is None:
            return
        rec = self._messages[idx]
        chars = len(rec.content)
        tokens = max(1, chars // 4)
        self._announcer.announce(
            t(
                "msg.details",
                role=_role_label(rec.role),
                i=idx + 1,
                n=total,
                chars=chars,
                tokens=tokens,
            ),
            interrupt=True,
        )

    def announce_status(self) -> None:
        """Ctrl+Shift+S — speak what FlameChat is doing right now.

        Busy (generation in flight): phase + percentage, so users who
        stepped away know roughly how long is left without having to
        watch the progress bar. Otherwise: chat state, picked model,
        and the resident memory Ollama is using for it — the three
        bits of context that matter when deciding whether to send
        another message or switch to a smaller model.
        """
        if self._announcer is None:
            return
        if self._busy:
            pct = int((self.progress.GetValue() / 1000) * 100)
            if self._token_count == 0:
                self._announcer.announce(t("status.busy_thinking"), interrupt=True)
            else:
                self._announcer.announce(
                    t("status.busy_writing", pct=pct), interrupt=True
                )
            return

        # Idle — build the message out of chat state + model + RAM.
        if self._active_chat is None:
            self._announcer.announce(t("status.no_chat_open"), interrupt=True)
            return
        n = len(self._messages)
        model = self._get_active_model()
        model_clause = (
            t("status.model_clause", model=model) if model else t("status.no_model")
        )
        ram_clause = self._describe_active_model_ram(model)
        key = "status.idle_empty" if n == 0 else "status.idle_messages"
        self._announcer.announce(
            t(key, n=n, model_clause=model_clause, ram_clause=ram_clause),
            interrupt=True,
        )

    def _describe_active_model_ram(self, model: str | None) -> str:
        """Ask Ollama how much memory the active model is holding.

        Returns a translated "X.Y GB" clause when the model is
        currently loaded, a "not loaded yet" note when Ollama has it
        on disk but not in memory, or an empty string when we can't
        reach Ollama / no model is picked (the broader status line
        is already covering those cases).
        """
        if not model:
            return ""
        try:
            frame = self.GetTopLevelParent()
            client = getattr(frame, "client", None)
            if client is None:
                return ""
            loaded = client.list_loaded()
        except Exception:
            return ""
        for lm in loaded:
            if lm.name == model:
                return t("status.ram_clause", gb=lm.size_bytes / (1024 ** 3))
        return t("status.ram_unknown")

    def set_system_prompt(self, prompt: str | None) -> None:
        """System prompt is app-global; stored outside the persisted chat."""
        self._system_prompt = prompt
        # Rebuild the in-memory history with the new prompt in front.
        non_system = [m for m in self._history if m["role"] != "system"]
        self._history = non_system
        if prompt:
            self._history.insert(0, {"role": "system", "content": prompt})

    def _clear_ui(self) -> None:
        # Detach every item from the sizer before destroying the panels —
        # otherwise the sizer holds a stale reference briefly and the
        # layout pass that follows can still include the old widgets.
        self._list_sizer.Clear(delete_windows=False)
        for rec in self._messages:
            if rec.panel is not None:
                rec.panel.Destroy()
        self._messages.clear()
        self._history.clear()
        # Staged attachments belong to the previous chat; discard them
        # so a chat switch does not leak files into a different context.
        self._clear_staging()
        # Put the empty-state label back in the sizer; it was detached
        # above but not destroyed (we held the reference on self).
        self._list_sizer.Add(self._empty_label, 0, wx.ALL, 10)
        self._empty_label.Show()
        self.message_list.SetVirtualSize((-1, -1))
        self.message_list.Scroll(0, 0)
        self.message_list.Layout()
        self.message_list.FitInside()
        # Force an immediate repaint so users never see a stale frame
        # between a chat switch and the new chat's first render.
        self.message_list.Refresh()
        self.message_list.Update()

    def regenerate_from(self, panel: MessagePanel) -> None:
        """Drop this assistant message (and everything after it), re-send."""
        if self._busy:
            wx.Bell()
            return
        idx = next(
            (i for i, rec in enumerate(self._messages) if rec.panel is panel),
            None,
        )
        if idx is None or self._messages[idx].role != "assistant":
            return
        # Find the user message that prompted this assistant turn.
        prompt_idx = idx - 1
        while prompt_idx >= 0 and self._messages[prompt_idx].role != "user":
            prompt_idx -= 1
        if prompt_idx < 0:
            return
        prompt_text = self._messages[prompt_idx].content

        # Drop from `prompt_idx` onward — UI + history.
        self._drop_messages_from(prompt_idx)
        self._history = [m for m in self._history if m["role"] == "system"]
        if self._active_chat is not None:
            self._active_chat.messages = self._active_chat.messages[:prompt_idx]
            self._on_changed(self._active_chat)

        # Re-send by the usual path. ``_submit`` no longer chimes on
        # its own, so do it here to match the Enter-press behaviour.
        self._sounds.play_send()
        self._submit(prompt_text)

    # --- event handlers ----------------------------------------------------
    def _on_input_key(self, event: wx.KeyEvent) -> None:
        if self._handle_nav_key(event):
            return
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE and self._busy:
            self._request_cancel()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if event.ShiftDown():
                # Insert a real newline at the caret. wxPython's default
                # handling of Enter in a TE_MULTILINE + TE_PROCESS_ENTER
                # field is platform-specific, so we do it explicitly.
                self.input.WriteText("\n")
                return
            # Plain Enter → send.
            self._on_send(None)
            return
        event.Skip()

    def _handle_nav_key(self, event: wx.KeyEvent) -> bool:
        """Message-navigation shortcut. Return True if the event was consumed.

        On macOS we require *exactly* Cmd + the real Control key; on
        Windows and Linux we require exactly Ctrl + Alt. We compare the
        raw modifier bitmask against the required combination so that a
        plain Cmd+Up (caret to start of text) or Cmd+Shift+Up (select
        to start) never reaches this handler.
        """
        key = event.GetKeyCode()
        if key not in (wx.WXK_UP, wx.WXK_DOWN):
            return False
        mods = event.GetModifiers()
        # Strip Shift from the comparison so the user can hold Shift too
        # without breaking the combo, but any other extra key cancels.
        mods &= ~wx.MOD_SHIFT
        if sys.platform == "darwin":
            required = wx.MOD_CONTROL | wx.MOD_RAW_CONTROL  # Cmd + ⌃
        else:
            required = wx.MOD_CONTROL | wx.MOD_ALT
        if mods != required:
            return False
        if key == wx.WXK_UP:
            self._focus_prev_message()
            return True
        if key == wx.WXK_DOWN:
            self._focus_next_message()
            return True
        return False

    # --- attachments ------------------------------------------------------
    def _on_attach(self) -> None:
        """Ask the user what to do with the file via a modal dialog.

        A modal ``wx.Dialog`` with four buttons is used rather than a
        ``wx.Menu.PopupMenu`` because the latter is unreliable with
        VoiceOver on macOS — focus does not always move into the popup,
        so screen-reader users could not navigate its items. A dialog is
        native, focusable and announced by every major screen reader.
        """
        if self._busy:
            wx.Bell()
            return
        if self._active_chat is None:
            return

        dlg = AttachmentIntentDialog(self)
        result = dlg.ShowModal()
        choice = dlg.choice
        dlg.Destroy()
        if result != wx.ID_OK or choice is None:
            return

        if choice == INTENT_IMAGE:
            self._pick_image()
        elif choice == INTENT_ANALYSE:
            self._pick_audio(mode="analyse")
        elif choice == INTENT_TRANSCRIBE:
            self._pick_audio(mode="transcribe")
        elif choice == INTENT_TRANSCRIBE_SUMMARY:
            self._pick_audio(mode="transcribe_summarise")
        elif choice == INTENT_TEXT:
            self._pick_text()

    def _pick_image(self) -> None:
        attachments = self._pick_and_ingest(
            title=t("chat.attach_dialog_image"),
            wildcard=t("chat.attach_wildcard_image"),
            expected_kind="image",
            wrong_type_key="chat.attach_wrong_type_image",
        )
        if attachments:
            self._handle_image_attachment(attachments)

    def _pick_audio(self, *, mode: str) -> None:
        attachments = self._pick_and_ingest(
            title=t("chat.attach_dialog_audio"),
            wildcard=t("chat.attach_wildcard_audio"),
            expected_kind="audio",
            wrong_type_key="chat.attach_wrong_type_audio",
        )
        if not attachments:
            return
        if mode == "analyse":
            self._handle_audio_analyse(attachments)
        elif mode == "transcribe":
            self._handle_audio_transcribe(attachments, summarise=False)
        elif mode == "transcribe_summarise":
            self._handle_audio_transcribe(attachments, summarise=True)

    def _pick_text(self) -> None:
        attachments = self._pick_and_ingest(
            title=t("chat.attach_dialog_text"),
            wildcard=t("chat.attach_wildcard_text"),
            expected_kind="text",
            wrong_type_key="chat.attach_wrong_type_text",
        )
        if attachments:
            self._handle_text_attachment(attachments)

    def _pick_and_ingest(
        self,
        *,
        title: str,
        wildcard: str,
        expected_kind: str,
        wrong_type_key: str,
    ) -> list[Attachment]:
        """Multi-select picker + ingest, shared across all intents.

        Returns an empty list on any validation failure. On failure the
        user has already seen a dialog explaining what went wrong.
        """
        paths = self._pick_files(title=title, wildcard=wildcard)
        if not paths:
            return []
        if len(paths) > MAX_FILES_PER_ACTION:
            wx.MessageBox(
                t(
                    "chat.attach_too_many",
                    count=len(paths),
                    limit=MAX_FILES_PER_ACTION,
                ),
                t("chat.attach_error_title"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return []
        attachments: list[Attachment] = []
        for path in paths:
            att = self._ingest_or_warn(path)
            if att is None:
                return []  # abort the whole batch on any ingest error
            if att.kind != expected_kind:
                wx.MessageBox(
                    t(wrong_type_key),
                    t("chat.attach_error_title"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return []
            attachments.append(att)
        return attachments

    def _pick_files(self, *, title: str, wildcard: str) -> list[Path]:
        with wx.FileDialog(
            self,
            title,
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return []
            return [Path(p) for p in fd.GetPaths()]

    def _ingest_or_warn(self, raw_path: Path) -> Attachment | None:
        assert self._active_chat is not None
        try:
            return ingest_attachment(raw_path, self._active_chat.id)
        except AttachmentError as e:
            wx.MessageBox(
                str(e),
                t("chat.attach_error_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return None

    # Image + text attachments stage into self._staged and ride with
    # the next Send. This is what lets the user type "what's in this
    # picture?" and hit Send alongside the image, rather than firing a
    # canned "describe this" request the moment they click Attach.
    def _handle_image_attachment(self, attachments: list[Attachment]) -> None:
        # Gate: at least one installed model must be vision-capable —
        # otherwise the user would stage images that can never be sent.
        if self._pick_installed_vision_model() is None:
            wx.MessageBox(
                t("chat.no_vision_model_body"),
                t("chat.no_vision_model_title"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return
        self._stage(attachments)

    # Batch audio actions: one file at a time, combined result. This is
    # serial and can take a while for a three-file batch with the
    # medium whisper model — users see per-file progress in the status.
    def _handle_audio_analyse(self, attachments: list[Attachment]) -> None:
        if self._analyse_audio is None or not attachments:
            return
        files_label = ", ".join(a.original_name for a in attachments)
        note = t("chat.attached_analyse_note", file=files_label)
        self._append_user_note(note)
        self._cancel_event = threading.Event()
        self._set_busy(True)
        self._set_status(note)
        self.progress.SetValue(0)

        cancel_event = self._cancel_event
        threading.Thread(
            target=self._run_audio_analyse_batch,
            args=(attachments, cancel_event),
            daemon=True,
        ).start()

    def _run_audio_analyse_batch(
        self, attachments: list[Attachment], cancel_event: threading.Event
    ) -> None:
        reports: list[str] = []
        progress_hook = self._pipeline_progress_hook()
        try:
            assert self._analyse_audio is not None
            for i, attachment in enumerate(attachments, start=1):
                if cancel_event.is_set():
                    break
                progress_hook(
                    t(
                        "audio.status.analysing_item",
                        name=attachment.original_name,
                        i=i,
                        n=len(attachments),
                    ),
                    -1.0,
                )
                report = self._analyse_audio(
                    attachment, cancel_event, progress_hook
                )
                reports.append(report)
        except Exception as e:  # noqa: BLE001
            wx.CallAfter(self._on_generation_error, e)
            return
        combined = "\n\n".join(reports)
        wx.CallAfter(
            self._finish_attachment, combined, "", cancel_event.is_set()
        )

    def _handle_audio_transcribe(
        self, attachments: list[Attachment], *, summarise: bool
    ) -> None:
        if self._transcribe_audio is None or not attachments:
            return
        files_label = ", ".join(a.original_name for a in attachments)
        key = (
            "chat.attached_transcribe_summary_note"
            if summarise
            else "chat.attached_transcribe_note"
        )
        note = t(key, file=files_label)
        self._append_user_note(note)
        self._cancel_event = threading.Event()
        self._set_busy(True)
        self._set_status(note)
        self.progress.SetValue(0)

        cancel_event = self._cancel_event
        threading.Thread(
            target=self._run_audio_transcribe_batch,
            args=(attachments, cancel_event, summarise),
            daemon=True,
        ).start()

    def _run_audio_transcribe_batch(
        self,
        attachments: list[Attachment],
        cancel_event: threading.Event,
        summarise: bool,
    ) -> None:
        per_file: list[tuple[Attachment, str, str]] = []
        progress_hook = self._pipeline_progress_hook()
        try:
            assert self._transcribe_audio is not None
            for i, attachment in enumerate(attachments, start=1):
                if cancel_event.is_set():
                    break
                progress_hook(
                    t(
                        "audio.status.transcribing_item",
                        name=attachment.original_name,
                        i=i,
                        n=len(attachments),
                    ),
                    -1.0,
                )
                transcript, summary = self._transcribe_audio(
                    attachment, cancel_event, progress_hook, summarise
                )
                per_file.append((attachment, transcript, summary))
        except Exception as e:  # noqa: BLE001
            wx.CallAfter(self._on_generation_error, e)
            return

        wx.CallAfter(self._finalize_transcribe_batch, per_file, cancel_event.is_set())

    def _finalize_transcribe_batch(
        self,
        per_file: list[tuple[Attachment, str, str]],
        aborted: bool,
    ) -> None:
        """Compose inline output for a batch of transcribed files.

        Summaries go inline. Transcripts go inline if they fit under the
        inline limit, otherwise the user is offered a save dialog per
        file and the inline body just references the saved path.
        """
        what_summary = t("chat.what_summary").capitalize()
        what_transcript = t("chat.what_transcript").capitalize()
        blocks: list[str] = []
        for attachment, transcript, summary in per_file:
            file_block: list[str] = [f"=== {attachment.original_name} ==="]
            if summary:
                file_block.append(f"{what_summary}:\n{summary}")
            if transcript:
                if len(transcript) <= self._inline_limit:
                    file_block.append(f"{what_transcript}:\n{transcript}")
                else:
                    saved = self._offer_save_long_text(
                        attachment, transcript, what_key="chat.what_transcript"
                    )
                    if saved is not None:
                        file_block.append(
                            t(
                                "audio.transcript.saved",
                                what=what_transcript,
                                path=saved,
                            )
                        )
                    else:
                        file_block.append(
                            t(
                                "audio.transcript.not_saved",
                                what=what_transcript,
                                chars=len(transcript),
                            )
                        )
            blocks.append("\n\n".join(file_block))
        combined = "\n\n".join(blocks).strip()
        self._finish_attachment(combined, "", aborted)

    # --- text attachments ------------------------------------------------
    def _handle_text_attachment(self, attachments: list[Attachment]) -> None:
        """Stage text files; they ride with the next Send as file blocks."""
        if not attachments:
            return
        self._stage(attachments)

    # --- shared staging UI -----------------------------------------------
    def _stage(self, new_attachments: list[Attachment]) -> None:
        """Append ``new_attachments`` to the staging strip, refresh UI."""
        remaining = max(0, MAX_FILES_PER_ACTION - len(self._staged))
        if len(new_attachments) > remaining:
            wx.MessageBox(
                t(
                    "chat.attach_too_many",
                    count=len(self._staged) + len(new_attachments),
                    limit=MAX_FILES_PER_ACTION,
                ),
                t("chat.attach_error_title"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return
        self._staged.extend(new_attachments)
        self._refresh_staging_ui()
        self.input.SetFocus()

    def _unstage(self, attachment: Attachment) -> None:
        self._staged = [a for a in self._staged if a is not attachment]
        self._refresh_staging_ui()

    def _clear_staging(self) -> None:
        self._staged.clear()
        self._refresh_staging_ui()

    def _refresh_staging_ui(self) -> None:
        """Rebuild the chip row so it matches ``self._staged`` exactly."""
        # Staging state feeds into the send button's enabled state —
        # an attached file counts as "something to send" even with an
        # empty text input.
        self._refresh_send_button()
        # Remove every child except the leading label.
        for child in list(self._staging_sizer.GetChildren()):
            win = child.GetWindow()
            if win is not None and win is not self._staging_label:
                win.Destroy()
        self._staging_sizer.Clear(delete_windows=False)
        self._staging_sizer.Add(
            self._staging_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8
        )
        for att in self._staged:
            self._staging_sizer.Add(
                self._make_staging_chip(att),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                6,
            )
        self._staging_panel.Show(bool(self._staged))
        self._staging_panel.Layout()
        self.Layout()

    def _make_staging_chip(self, attachment: Attachment) -> wx.Window:
        chip = wx.Panel(self._staging_panel, style=wx.BORDER_SIMPLE)
        inner = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(
            chip,
            label=f"{attachment.original_name} ({attachment.size_display})",
        )
        label.SetName(f"{attachment.kind}: {attachment.original_name}")
        remove = wx.Button(chip, label="×", size=(26, -1))
        remove.SetName(
            t("chat.staging_remove", name=attachment.original_name)
        )
        remove.SetToolTip(t("chat.staging_remove_short"))
        remove.Bind(wx.EVT_BUTTON, lambda _e, a=attachment: self._unstage(a))
        inner.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        inner.Add(remove, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        chip.SetSizer(inner)
        chip.Fit()
        return chip

    def _pipeline_progress_hook(self) -> Callable[[str, float], None]:
        def on_progress(label: str, fraction: float) -> None:
            def _apply() -> None:
                self._set_status(label)
                if fraction >= 0:
                    self.progress.SetValue(int(max(0.0, min(1.0, fraction)) * 1000))
                else:
                    self.progress.Pulse()
            wx.CallAfter(_apply)
        return on_progress

    def _finish_attachment(
        self, inline_text: str, _extra: str, aborted: bool
    ) -> None:
        self._set_busy(False)
        self._cancel_event = None
        if aborted:
            self._append_assistant_result(t("chat.aborted_answer"))
            self._set_status(t("chat.aborted"))
            if self._announcer is not None:
                self._announcer.announce(t("say.cancelled"))
            return
        self._append_assistant_result(inline_text or t("chat.empty_answer"))
        self._sounds.play_receive()
        self._set_status(t("chat.received"))
        # No SetFocus here for the same reason as _on_generation_done:
        # moving focus fires a VoiceOver focus cue that would cut off
        # whatever we announce next, and the user either is still in
        # the input anyway or has intentionally navigated elsewhere.
        if self._announcer is not None:
            self._announcer.announce(t("say.msg_received"))

    # --- helpers used by attachments -------------------------------------
    def _append_user_note(self, text: str) -> None:
        self._append_message("user", text)
        self._history.append({"role": "user", "content": text})
        if self._active_chat is not None:
            self._active_chat.messages.append({"role": "user", "content": text})
            self._on_changed(self._active_chat)

    def _append_assistant_result(self, text: str) -> None:
        self._history.append({"role": "assistant", "content": text})
        self._append_message("assistant", text)
        if self._active_chat is not None:
            self._active_chat.messages.append({"role": "assistant", "content": text})
            self._on_changed(self._active_chat)

    def _offer_save_long_text(
        self,
        attachment: Attachment,
        body: str,
        *,
        what_key: str,
    ) -> Path | None:
        """Prompt the user for a file to save ``body`` to. Returns the path written, or None."""
        default_name = t(
            "chat.attachment_saved_default",
            stem=Path(attachment.original_name).stem,
            what=t(what_key),
        )
        wx.MessageBox(
            t("chat.attachment_saved_prompt", chars=len(body)),
            t("chat.attachment_saved_title"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )
        with wx.FileDialog(
            self,
            t("chat.attachment_saved_title"),
            wildcard=t("msg.save_wildcard"),
            defaultFile=default_name,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return None
            path = Path(fd.GetPath())
        try:
            path.write_text(body, encoding="utf-8")
        except OSError as e:
            wx.MessageBox(
                t("msg.save_error_body", err=e),
                t("msg.save_error_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return None
        if self._announcer is not None:
            self._announcer.announce(t("say.saved"))
        return path

    def _on_send(self, _event) -> None:
        if self._busy:
            wx.Bell()
            return
        typed = self.input.GetValue().strip()
        if not typed and not self._staged:
            self._set_status(t("chat.empty_submit"))
            return
        # Play the send chime *before* clearing the input, rendering a
        # new message widget and persisting the chat. Those steps can
        # take 50–150 ms on slower machines, and users expect instant
        # auditory feedback on Enter / Send click — moving the sound
        # to the top makes the app feel responsive.
        self._sounds.play_send()
        self.input.SetValue("")
        staged = list(self._staged)
        self._clear_staging()
        self._submit(typed, staged=staged)

    def _refresh_send_button(self) -> None:
        """Enable send iff there is content to send (text or attachments)."""
        has_text = bool(self.input.GetValue().strip())
        has_staged = bool(self._staged)
        self.send_button.Enable(has_text or has_staged)

    def _submit(
        self,
        text: str,
        *,
        staged: list[Attachment] | None = None,
    ) -> None:
        """Build one user-turn out of ``text`` + any staged attachments."""
        staged = staged or []
        images = [a for a in staged if a.kind == "image"]
        text_files = [a for a in staged if a.kind == "text"]

        # Pick a model. If images ride along, the chat's current model
        # must be vision-capable — otherwise we swap in any installed
        # vision model for this single turn (silently, because the
        # earlier "attach image" path already warned if there was none).
        model = self._get_active_model()
        if images:
            from ..backend.vision import VISION_HINTS
            if model is None or not any(h in model.lower() for h in VISION_HINTS):
                model = self._pick_installed_vision_model() or model
        if not model:
            wx.MessageBox(
                t("chat.no_model_body"),
                t("chat.no_model_title"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return

        # Compose the visible body and any inline text-file sections.
        visible_parts: list[str] = []
        if text:
            visible_parts.append(text)
        for att in text_files:
            try:
                content = att.stored_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                wx.MessageBox(
                    t("chat.read_error", name=att.original_name),
                    t("chat.attach_error_title"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return
            visible_parts.append(
                t(
                    "chat.staged_text_section",
                    name=att.original_name,
                    size=att.size_display,
                    content=content,
                )
            )
        if images:
            visible_parts.append(
                t(
                    "chat.staged_image_marker",
                    files=", ".join(a.original_name for a in images),
                )
            )
        if not visible_parts:
            visible_parts.append(t("chat.empty_body_default"))
        visible = "\n\n".join(visible_parts).strip()

        # Store in UI + persisted history (as plain text — images go
        # into the wire message only, they aren't persisted).
        self._append_message("user", visible)
        self._history.append({"role": "user", "content": visible})
        if self._active_chat is not None:
            self._active_chat.messages.append({"role": "user", "content": visible})
            self._on_changed(self._active_chat)

        # Build the wire message. Ollama's chat API expects ``images``
        # as base64-encoded bytes on the user turn; we add them only on
        # the tail message of the conversation we send.
        wire_messages = [dict(m) for m in self._history]
        if images:
            import base64
            wire_messages[-1]["images"] = [
                base64.b64encode(img.stored_path.read_bytes()).decode("ascii")
                for img in images
            ]

        # The send chime is fired by the caller (``_on_send`` /
        # ``regenerate_from``) right after the user's action — that
        # way the "ding" plays while this method spends time rendering
        # the message widget and persisting the chat to disk.
        self._cancel_event = threading.Event()
        self._token_count = 0  # reset — fresh turn, no chunks yet
        self._set_busy(True)
        self._set_status(t("chat.thinking"))
        self.progress.SetValue(0)
        if self._announcer is not None:
            self._announcer.announce(t("say.msg_sent"))
        self._sounds.play_typing_loop()

        threading.Thread(
            target=self._run_generation,
            args=(wire_messages, model, self._cancel_event),
            daemon=True,
        ).start()

    def _pick_installed_vision_model(self) -> str | None:
        """Find a vision-capable model among the globally installed list."""
        try:
            main_frame = self.GetTopLevelParent()
            installed = getattr(main_frame, "_installed_models", []) or []
        except Exception:
            installed = []
        from ..backend.vision import pick_vision_model
        return pick_vision_model(installed)

    def _run_generation(
        self,
        messages: list[Message],
        model: str,
        cancel_event: threading.Event,
    ) -> None:
        chunks: list[str] = []
        try:
            for chunk in self._send_handler(messages, model, cancel_event):
                if cancel_event.is_set():
                    break
                chunks.append(chunk)
                wx.CallAfter(self._on_generation_chunk, len(chunks))
        except Exception as e:  # noqa: BLE001  — surface any backend failure
            # Stop the typing loop immediately on failure too — no point
            # letting the soundtrack keep going while the error dialog
            # loads.
            wx.CallAfter(self._sounds.stop_typing)
            wx.CallAfter(self._on_generation_error, e)
            return
        # Silence the typing loop the instant the stream ends — before
        # any of the rendering / history / persistence work in
        # _on_generation_done runs. Users should hear the model stop
        # typing the moment it actually stops.
        wx.CallAfter(self._sounds.stop_typing)
        full = "".join(chunks).strip()
        aborted = cancel_event.is_set()
        wx.CallAfter(self._on_generation_done, full, aborted)

    def _on_generation_chunk(self, token_count: int) -> None:
        """Called on the UI thread for each streamed chunk."""
        # Approximate percentage: chunks ≈ tokens, capped at MAX_PREDICT.
        # We deliberately stopped surfacing the raw token count in the
        # status bar — most users can't act on "430 tokens of 2048",
        # it was just noise. Power users who want the raw number can
        # still get it via Ctrl+Shift+S or the Alt+N triple-tap.
        pct = min(1.0, token_count / MAX_PREDICT_TOKENS)
        self.progress.SetValue(int(pct * 1000))
        self._token_count = token_count
        self._set_status(t("chat.writing", pct=int(pct * 100)))

    def _request_cancel(self) -> None:
        if self._cancel_event is not None and not self._cancel_event.is_set():
            self._cancel_event.set()
            self._set_status(t("chat.aborting"))
            self.abort_button.Disable()
            if self._announcer is not None:
                self._announcer.announce(t("say.cancelling"), interrupt=True)

    def _on_generation_done(self, text: str, aborted: bool = False) -> None:
        # stop_typing was already fired from the worker thread the
        # instant the stream ended; calling it again is harmless.
        self._sounds.stop_typing()
        if not text:
            text = t("chat.aborted_answer") if aborted else t("chat.empty_answer")
        elif aborted:
            text = text + "\n\n" + t("chat.aborted_suffix")
        self._history.append({"role": "assistant", "content": text})
        self._append_message("assistant", text)
        if self._active_chat is not None:
            self._active_chat.messages.append({"role": "assistant", "content": text})
            self._on_changed(self._active_chat)
        if not aborted:
            self._sounds.play_receive()
        self._set_busy(False)
        self._cancel_event = None
        self._set_status(t("chat.aborted") if aborted else t("chat.received"))
        # Deliberately no ``self.input.SetFocus()`` here: the user
        # either was already in the input (typed + Enter, focus never
        # moved) or navigated to an older message with Ctrl+Up/Down to
        # re-read it. In the first case SetFocus is a no-op on screen
        # but still fires a VoiceOver focus cue ("Nachrichteneingabe")
        # that barges in and truncates our own ``announce(text)``. In
        # the second case SetFocus yanks the user off a message they
        # wanted to read. Leaving focus where it is covers both.
        if self._announcer is not None:
            if aborted:
                self._announcer.announce(t("say.cancelled"), interrupt=True)
            else:
                # Speak the reply directly with interrupt=True so any
                # lingering "Assistant denkt nach" speech gets cut off.
                # The receive chime + status line already act as the
                # "message received" cue — two back-to-back announce
                # calls (cue + body) were dropping the body on macOS
                # VoiceOver, which coalesces rapid output() calls.
                self._announcer.announce(text, interrupt=True)

    def _on_generation_error(self, err: Exception) -> None:
        self._sounds.stop_typing()
        self._set_busy(False)
        self._cancel_event = None
        self._set_status(t("chat.error", err=err))
        if self._announcer is not None:
            self._announcer.announce(t("say.request_error"), interrupt=True)
        wx.MessageBox(
            t("chat.error_box_body", err=err),
            t("chat.error_box_title"),
            wx.OK | wx.ICON_ERROR,
            self,
        )

    def set_theme(self, theme: str) -> None:
        """Update the stored theme and repaint every existing message."""
        self._theme = theme
        apply_theme(self.message_list, theme)

    # --- message list helpers ---------------------------------------------
    def _append_message(self, role: str, content: str) -> None:
        if self._empty_label.IsShown():
            self._empty_label.Hide()
            self._list_sizer.Clear()
        position = len(self._messages) + 1
        record = _MessageRecord(role=role, content=content)
        panel = MessagePanel(
            self.message_list,
            role=role,
            content=content,
            position_label=t("msg.a11y_position", i=position, n=position),
            nav_handler=self._handle_nav_key,
            announcer=self._announcer,
        )
        # Paint the fresh panel before it's added to the sizer so the
        # first frame the user sees is already dark; otherwise Windows
        # renders one light frame before the Refresh kicks in.
        apply_theme(panel, self._theme)
        record.panel = panel
        self._messages.append(record)
        self._list_sizer.Add(panel, 0, wx.EXPAND | wx.ALL, 4)
        self._relabel_positions()
        self.message_list.Layout()
        self.message_list.FitInside()
        self._scroll_to_bottom()

    def _drop_messages_from(self, start_idx: int) -> None:
        for rec in self._messages[start_idx:]:
            if rec.panel is not None:
                rec.panel.Destroy()
        self._messages = self._messages[:start_idx]
        self._relabel_positions()
        if not self._messages:
            self._list_sizer.Clear()
            self._list_sizer.Add(self._empty_label, 0, wx.ALL, 10)
            self._empty_label.Show()
        self.message_list.Layout()
        self.message_list.FitInside()

    def _relabel_positions(self) -> None:
        total = len(self._messages)
        for i, rec in enumerate(self._messages):
            if rec.panel is not None:
                rec.panel.update_position_label(
                    t("msg.a11y_position", i=i + 1, n=total)
                )

    def _scroll_to_bottom(self) -> None:
        _, sy = self.message_list.GetVirtualSize()
        _, ch = self.message_list.GetClientSize()
        self.message_list.Scroll(0, max(0, sy - ch) // 20)

    # --- navigation -------------------------------------------------------
    def _focus_prev_message(self) -> None:
        if not self._messages:
            return
        current = self._focused_message_index()
        target = (
            len(self._messages) - 1
            if current is None
            else max(0, current - 1)
        )
        self._focus_message(target)

    def _focus_next_message(self) -> None:
        if not self._messages:
            return
        current = self._focused_message_index()
        if current is None or current >= len(self._messages) - 1:
            # Past the last message → jump back to input.
            self.input.SetFocus()
            return
        self._focus_message(current + 1)

    def _focused_message_index(self) -> int | None:
        focused = wx.Window.FindFocus()
        if focused is None:
            return None
        for i, rec in enumerate(self._messages):
            if rec.panel is None:
                continue
            if focused is rec.panel or focused is rec.panel.body or focused is rec.panel.header:
                return i
        return None

    def _focus_message(self, idx: int) -> None:
        rec = self._messages[idx]
        if rec.panel is None:
            return
        rec.panel.focus_body()
        # Make sure the focused message is on-screen.
        self.message_list.ScrollChildIntoView(rec.panel)

    # --- misc helpers -----------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_button.Show(not busy)
        self.abort_button.Show(busy)
        self.abort_button.Enable(busy)
        self.progress.Show(busy)
        if not busy:
            self.progress.SetValue(0)
        self.Layout()

    def _set_status(self, text: str) -> None:
        self.status.SetLabel(text)
