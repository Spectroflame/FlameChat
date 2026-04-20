"""Modal dialog that asks the user what to do with an attachment.

Shown from the Attach button. A modal ``wx.Dialog`` with four explicit
option buttons is used instead of a ``wx.Menu.PopupMenu`` because the
latter is unreliable with VoiceOver — focus does not always move into
the popup, so screen-reader users cannot navigate the items.

Returns one of the ``INTENT_*`` constants, or ``None`` if the user
cancels. Buttons are standard ``wx.Button`` controls so VoiceOver, NVDA,
JAWS and Orca all announce them without extra scaffolding.
"""

from __future__ import annotations

import wx

from ..i18n import t


INTENT_IMAGE = "image"
INTENT_ANALYSE = "analyse"
INTENT_TRANSCRIBE = "transcribe"
INTENT_TRANSCRIBE_SUMMARY = "transcribe_summary"
INTENT_TEXT = "text"


class AttachmentIntentDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            title=t("chat.intent_dialog_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.SetName(t("chat.intent_dialog_title"))
        self._choice: str | None = None

        outer = wx.BoxSizer(wx.VERTICAL)

        body = wx.StaticText(self, label=t("chat.intent_dialog_body"))
        body.Wrap(520)
        outer.Add(body, 0, wx.ALL, 14)

        btn_image = self._make_button(
            t("chat.attach_menu_image"), INTENT_IMAGE, default=True
        )
        btn_analyse = self._make_button(
            t("chat.attach_menu_analyse"), INTENT_ANALYSE
        )
        btn_transcribe = self._make_button(
            t("chat.attach_menu_transcribe"), INTENT_TRANSCRIBE
        )
        btn_transcribe_sum = self._make_button(
            t("chat.attach_menu_transcribe_summary"), INTENT_TRANSCRIBE_SUMMARY
        )
        btn_text = self._make_button(
            t("chat.attach_menu_text"), INTENT_TEXT
        )

        for b in (btn_image, btn_analyse, btn_transcribe, btn_transcribe_sum, btn_text):
            outer.Add(b, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        cancel = wx.Button(self, wx.ID_CANCEL, t("chat.intent_cancel"))
        cancel.SetName(t("chat.intent_cancel"))
        cancel.Bind(wx.EVT_BUTTON, self._on_cancel)
        outer.Add(cancel, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizerAndFit(outer)
        self.CenterOnParent()
        btn_image.SetFocus()

    def _make_button(self, label: str, intent: str, *, default: bool = False) -> wx.Button:
        btn = wx.Button(self, label=label)
        btn.SetName(label.replace("&", ""))
        btn.Bind(wx.EVT_BUTTON, lambda _e, i=intent: self._choose(i))
        if default:
            btn.SetDefault()
        return btn

    def _choose(self, intent: str) -> None:
        self._choice = intent
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _event) -> None:
        self._choice = None
        self.EndModal(wx.ID_CANCEL)

    @property
    def choice(self) -> str | None:
        return self._choice
