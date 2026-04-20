"""Sidebar listing saved chats.

Accessibility notes:

* Uses ``wx.dataview.DataViewListCtrl`` rather than ``wx.ListCtrl``. On
  macOS that maps to ``NSOutlineView`` which VoiceOver navigates
  reliably (``wx.ListCtrl`` in report mode is known to be iffy with VO
  — it often fails to emit row events). On Windows the control is UIA-
  backed which NVDA and JAWS read natively. On Linux it uses GTK
  ``GtkTreeView`` which Orca picks up via AT-SPI.
* The row label is the chat title — the most important field — so
  screen readers announce it first. Model and timestamp are columns
  after.
* Up / Down arrow keys move the selection (native control behaviour).
  Enter or Space activates (opens the chat). Delete or Backspace
  removes the row after a confirmation. There is also a Cmd+1 / Ctrl+1
  shortcut at the MainFrame level that jumps focus here from anywhere.
"""

from __future__ import annotations

from typing import Callable

import wx
import wx.dataview as dv

from ..backend.chat_store import Chat, ChatStore
from ..i18n import t
from .announcer import Announcer


class ChatListPanel(wx.Panel):
    COL_TITLE = 0
    COL_MODEL = 1
    COL_UPDATED = 2

    def __init__(
        self,
        parent: wx.Window,
        *,
        store: ChatStore,
        on_open: Callable[[Chat], None],
        on_empty: Callable[[], None] = lambda: None,
        auto_create_empty: Callable[[], bool] = lambda: True,
        announcer: Announcer | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._on_open = on_open
        self._on_empty = on_empty
        self._auto_create_empty = auto_create_empty
        self._announcer = announcer
        self._chats: list[Chat] = []
        self._build()
        self.reload()

    def _build(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        header = wx.StaticText(self, label=t("list.header"))
        font = header.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        header.SetFont(font)
        header.SetName(t("list.header"))
        sizer.Add(header, 0, wx.ALL, 6)

        self.list = dv.DataViewListCtrl(
            self,
            style=dv.DV_ROW_LINES | dv.DV_SINGLE,
        )
        self.list.SetName(t("list.name_a11y"))
        self.list.AppendTextColumn(t("list.col_title"), width=200)
        self.list.AppendTextColumn(t("list.col_model"), width=130)
        self.list.AppendTextColumn(t("list.col_updated"), width=90)
        sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.new_btn = wx.Button(self, label=t("list.new_chat"))
        self.new_btn.SetName(t("list.new_chat_name"))
        self.delete_btn = wx.Button(self, label=t("list.delete"))
        self.delete_btn.SetName(t("list.delete_name"))
        self.delete_btn.Disable()
        buttons.Add(self.new_btn, 1, wx.RIGHT, 4)
        buttons.Add(self.delete_btn, 1)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 6)

        self.SetSizer(sizer)

        self.list.Bind(dv.EVT_DATAVIEW_SELECTION_CHANGED, self._on_selected)
        self.list.Bind(dv.EVT_DATAVIEW_ITEM_ACTIVATED, self._on_activated)
        self.list.Bind(dv.EVT_DATAVIEW_ITEM_CONTEXT_MENU, self._on_context_menu)
        self.list.Bind(wx.EVT_CHAR_HOOK, self._on_list_key)
        self.new_btn.Bind(wx.EVT_BUTTON, lambda _e: self.create_new_chat())
        self.delete_btn.Bind(wx.EVT_BUTTON, lambda _e: self.delete_selected())

    # --- public API -------------------------------------------------------
    def reload(self, *, select_id: str | None = None) -> None:
        """Repopulate the list from disk, preserving selection if possible."""
        self._chats = self._store.list_chats()
        preferred = select_id or self._selected_chat_id()
        self.list.DeleteAllItems()
        for chat in self._chats:
            self.list.AppendItem(
                [
                    chat.title or t("list.default_title"),
                    chat.model or t("list.no_model_cell"),
                    chat.updated_display,
                ]
            )
        if self._chats:
            target_row = 0
            if preferred:
                for i, chat in enumerate(self._chats):
                    if chat.id == preferred:
                        target_row = i
                        break
            self.list.SelectRow(target_row)
            self.delete_btn.Enable()
        else:
            self.delete_btn.Disable()

    def selected_chat(self) -> Chat | None:
        row = self.list.GetSelectedRow()
        if row == -1 or row >= len(self._chats):
            return None
        return self._chats[row]

    def focus_list(self) -> None:
        """Put keyboard focus on the list and select the first row if possible."""
        self.list.SetFocus()
        if self._chats and self.list.GetSelectedRow() == -1:
            self.list.SelectRow(0)
        if self._announcer is not None and self._chats:
            chat = self.selected_chat()
            if chat:
                self._announcer.announce(t("say.chat_list_focus", title=chat.title))

    def create_new_chat(self, *, default_model: str | None = None) -> Chat:
        chat = self._store.create(model=default_model)
        self.reload(select_id=chat.id)
        self._on_open(chat)
        if self._announcer is not None:
            self._announcer.announce(t("say.chat_created"))
        return chat

    def delete_selected(self) -> None:
        chat = self.selected_chat()
        if chat is None:
            return
        confirm = wx.MessageBox(
            t("list.confirm_delete_body", title=chat.title),
            t("list.confirm_delete_title"),
            wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT,
            self,
        )
        if confirm != wx.YES:
            return
        self._store.delete(chat.id)
        if self._announcer is not None:
            self._announcer.announce(t("say.chat_deleted"))
        remaining = [c for c in self._chats if c.id != chat.id]
        if remaining:
            next_chat = remaining[0]
            self.reload(select_id=next_chat.id)
            self._on_open(next_chat)
        elif self._auto_create_empty():
            new_chat = self._store.create()
            self.reload(select_id=new_chat.id)
            self._on_open(new_chat)
        else:
            self.reload()
            self._on_empty()

    # --- event handlers ---------------------------------------------------
    def _on_selected(self, _event) -> None:
        chat = self.selected_chat()
        self.delete_btn.Enable(chat is not None)

    def _on_activated(self, _event) -> None:
        chat = self.selected_chat()
        if chat is not None:
            self._on_open(chat)

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_DELETE, wx.WXK_BACK):
            self.delete_selected()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            chat = self.selected_chat()
            if chat is not None:
                self._on_open(chat)
            return
        event.Skip()

    def _on_context_menu(self, event: dv.DataViewEvent) -> None:
        chat = self.selected_chat()
        if chat is None:
            return
        menu = wx.Menu()
        open_id = wx.NewIdRef().GetId()
        del_id = wx.NewIdRef().GetId()
        menu.Append(open_id, t("list.menu_open"))
        menu.Append(del_id, t("list.menu_delete"))
        self.Bind(wx.EVT_MENU, lambda _e: self._on_open(chat), id=open_id)
        self.Bind(wx.EVT_MENU, lambda _e: self.delete_selected(), id=del_id)
        self.PopupMenu(menu)
        menu.Destroy()

    def _selected_chat_id(self) -> str | None:
        chat = self.selected_chat()
        return chat.id if chat else None
