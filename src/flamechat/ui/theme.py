"""Manual theming for wxPython 4.2.

wxPython 4.2.5 does not expose ``wx.App.MSWEnableDarkMode`` (that
landed in 4.2.2 only for specific builds) and the GTK / Cocoa backends
track system appearance but don't offer a cross-platform app-level
toggle. So we paint the widget tree ourselves: each top-level window
walks its children and calls ``SetBackgroundColour`` / ``SetForegroundColour``
with palette values, plus a couple of native shortcuts (DWM dark title
bar on Windows 10+ and the undocumented ``SetPreferredAppMode`` call
in uxtheme.dll, which is what lets scroll bars, context menus and the
menu bar go dark on Windows).

This module deliberately does not ship a "system" mode. The product
brief is: dark is the default everywhere, light is an opt-in. Adding
"follow the OS" would be a second cognitive step for users and a third
branch to test — not worth it for this release.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import wx


# SetPreferredAppMode values from Windows' undocumented uxtheme.dll
# ordinal 135. The Windows enum is stable across 1903 → 11.
_APP_MODE_DEFAULT = 0
_APP_MODE_ALLOW_DARK = 1
_APP_MODE_FORCE_DARK = 2
_APP_MODE_FORCE_LIGHT = 3

_preferred_app_mode_set: bool = False


@dataclass(frozen=True)
class Palette:
    name: str
    background: wx.Colour
    foreground: wx.Colour
    # Text inputs / lists: slightly brighter than the frame so they
    # read as "elevated" surfaces on dark backgrounds.
    control_bg: wx.Colour
    control_fg: wx.Colour
    # Accent colour for selection highlights, the status bar and the
    # focus ring. Not heavily used by wxPython itself but some controls
    # pick it up when explicitly set.
    accent: wx.Colour


DARK_PALETTE = Palette(
    name="dark",
    background=wx.Colour(30, 30, 30),
    foreground=wx.Colour(224, 224, 224),
    control_bg=wx.Colour(43, 43, 43),
    control_fg=wx.Colour(240, 240, 240),
    accent=wx.Colour(79, 195, 247),
)

LIGHT_PALETTE = Palette(
    name="light",
    background=wx.NullColour,
    foreground=wx.NullColour,
    control_bg=wx.NullColour,
    control_fg=wx.NullColour,
    accent=wx.NullColour,
)


def palette_for(theme: str) -> Palette:
    if theme == "light":
        return LIGHT_PALETTE
    return DARK_PALETTE


# Text-entry classes whose inner surface should use the slightly brighter
# control_bg, not the frame background. Declared by import name to avoid
# picking up subclasses we might not want to retint.
_CONTROL_SURFACE_TYPES: tuple[type, ...] = (
    wx.TextCtrl,
    wx.SpinCtrl,
    wx.Choice,
    wx.ComboBox,
    wx.ListBox,
    wx.CheckListBox,
)


_CUSTOM_PAINT_TYPES: tuple[type, ...] = (
    wx.ScrolledWindow,
    wx.Notebook,
)


def _is_plain_container(window: wx.Window) -> bool:
    """True for generic Panel/Frame/Dialog surfaces; False for custom-painted widgets.

    We only flip BG_STYLE_COLOUR on these — anything else (scrolled
    windows, dataview, notebook pages) does its own double-buffered
    painting and would assert out. MessagePanel is a wx.Panel subclass
    and needs the flip just like a plain Panel, so we accept subclasses
    of the safe types and explicitly reject the known paint-based ones.
    """
    if isinstance(window, _CUSTOM_PAINT_TYPES):
        return False
    return isinstance(window, (wx.Panel, wx.Frame, wx.Dialog))


def prime_native_theme(theme: str) -> None:
    """Run the Windows dark-mode hint before any window exists.

    wxPython's common-controls backed widgets cache their theme handle
    on creation, so flipping SetPreferredAppMode *after* a widget is
    built leaves that widget on the old palette until it's reopened.
    Calling this from FlameChatApp.OnInit, before the first Dialog /
    Frame, catches the startup controls (the Prepare dialog, the menu
    bar, scrollbars) in the right mode from the first paint.
    """
    _set_msw_app_mode(palette_for(theme))


def apply_theme(window: wx.Window, theme: str) -> None:
    """Paint ``window`` and every descendant with the palette for ``theme``.

    The light palette maps to ``wx.NullColour`` which resets every
    control back to the system default — so toggling dark → light is a
    clean reversal without having to remember the original colours.
    """
    palette = palette_for(theme)
    # Apply process-wide Windows dark-mode hint first so any control
    # subsequently repainted picks up the system dark palette (scroll
    # bars, context menus, menu bar). Idempotent and safe to call
    # multiple times per process.
    _set_msw_app_mode(palette)
    _paint(window, palette)
    _apply_native_chrome(window, palette)
    window.Refresh()
    window.Update()


def _paint(window: wx.Window, palette: Palette) -> None:
    # Rich text / read-only bodies inside the chat transcript use a
    # custom subclass but still inherit from wx.TextCtrl, so the type
    # check catches them too.
    if isinstance(window, _CONTROL_SURFACE_TYPES):
        window.SetBackgroundColour(palette.control_bg)
        window.SetForegroundColour(palette.control_fg)
    else:
        window.SetBackgroundColour(palette.background)
        window.SetForegroundColour(palette.foreground)
    # Force solid-colour painting on the containers that default to
    # BG_STYLE_SYSTEM on Windows (the system brush paints the explorer
    # gradient over whatever we set). Controls that do their own
    # double-buffered drawing — wx.ScrolledWindow, wx.dataview,
    # anything using wxAutoBufferedPaintDC — must stay on BG_STYLE_PAINT,
    # so we restrict this switch to plain containers.
    if palette.name != "light" and _is_plain_container(window):
        try:
            window.SetBackgroundStyle(wx.BG_STYLE_COLOUR)
        except Exception:
            pass
    # Forcing Refresh per-widget is slower than one top-level refresh,
    # but without it Windows leaves older cached surfaces on controls
    # that were drawn under the system theme. The wasted cycles only
    # hit on theme switch, not on every repaint.
    window.Refresh()
    for child in window.GetChildren():
        _paint(child, palette)


def _set_msw_app_mode(palette: Palette) -> None:
    """Call SetPreferredAppMode so native chrome tracks our theme.

    This is an undocumented uxtheme.dll export (ordinal 135) that
    Windows File Explorer and Settings use to opt their own processes
    into dark mode. Without it, scroll bars, the menu bar and common
    context menus render in the system light theme regardless of what
    we paint on top. The export exists on Windows 10 1903 and newer;
    on older builds GetProcAddress returns NULL and we silently skip.
    """
    global _preferred_app_mode_set
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LoadLibraryW.restype = wintypes.HMODULE
        kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetProcAddress.restype = ctypes.c_void_p
        kernel32.GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]
        hmod = kernel32.LoadLibraryW("uxtheme.dll")
        if not hmod:
            return
        proc_set = kernel32.GetProcAddress(hmod, ctypes.cast(135, wintypes.LPCSTR))
        if not proc_set:
            return
        mode = (
            _APP_MODE_FORCE_DARK
            if palette.name == "dark"
            else _APP_MODE_FORCE_LIGHT
        )
        set_preferred_app_mode = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int)(
            proc_set
        )
        set_preferred_app_mode(mode)
        # Flush the menu theme cache so the main menu bar repaints in
        # the new palette without needing to re-show it.
        proc_flush = kernel32.GetProcAddress(hmod, ctypes.cast(136, wintypes.LPCSTR))
        if proc_flush:
            ctypes.WINFUNCTYPE(None)(proc_flush)()
        _preferred_app_mode_set = True
    except OSError:
        return


def _apply_native_chrome(window: wx.Window, palette: Palette) -> None:
    """Flip the title bar / window frame to match the palette on Windows.

    Uses DwmSetWindowAttribute with DWMWA_USE_IMMERSIVE_DARK_MODE, which
    is available on Windows 10 1809+ and silently no-ops on older
    builds. Skipped entirely on macOS (the window server follows the
    system appearance) and Linux (no portable way to retint the WM
    decorations from the client).
    """
    if sys.platform != "win32":
        return
    top = window.GetTopLevelParent() if window is not None else None
    if top is None or not top.IsShown() and not hasattr(top, "GetHandle"):
        # Defer to after-show: DWM refuses to touch a window before it
        # has been presented at least once. We'll be called again from
        # apply_theme on the next Refresh cycle.
        return
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return

    hwnd = top.GetHandle()
    if not hwnd:
        return
    # 20 is the public attribute id on Windows 20H1 and later. 19 was
    # the undocumented id used in 1903 / 1909 — we try the new one
    # first and fall back silently.
    use_dark = palette.name == "dark"
    value = ctypes.c_int(1 if use_dark else 0)
    for attr in (20, 19):
        try:
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_uint(attr),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                break
        except OSError:
            continue
