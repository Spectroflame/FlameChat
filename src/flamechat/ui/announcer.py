"""Send spoken status to the user's screen reader.

``accessible_output2`` handles the platform differences for us:

* Windows → NVDA / JAWS / SAPI / System Access / Window-Eyes / PCTalker /
  Dolphin / ZDSR (it picks whichever is running at import time).
* macOS → VoiceOver via the system AppleScript hook.
* Linux → Speech Dispatcher (``speechd``), which is what Orca and every
  major Linux screen reader reads from.

If the library is missing (e.g. in a stripped-down dev environment) or
no screen reader is running, ``announce`` silently does nothing — we
never let a missing accessibility backend break the app.
"""

from __future__ import annotations

import threading


class Announcer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._out = None
        self._enabled = True
        try:
            from accessible_output2.outputs.auto import Auto

            self._out = Auto()
        except Exception:
            # Either the package is missing or no screen reader is running
            # at init time. Either way: fall silent — never crash.
            self._out = None

    @property
    def available(self) -> bool:
        return self._out is not None

    def enable(self, on: bool) -> None:
        self._enabled = on

    def announce(self, text: str, *, interrupt: bool = False) -> None:
        """Say ``text`` through the active screen reader.

        ``interrupt=True`` cuts off any previously queued speech — use
        this for status changes the user must hear right away (error,
        abort). For steady-stream events like "copied to clipboard",
        keep the default so the announcement doesn't clobber whatever
        the reader was already saying.
        """
        if not self._enabled or self._out is None or not text:
            return
        with self._lock:
            try:
                self._out.speak(text, interrupt=interrupt)
            except Exception:
                # Screen-reader IPC can fail transiently (user switched
                # VO off, NVDA restarting, speechd socket blip, etc.).
                # We swallow so UI actions always complete.
                pass
