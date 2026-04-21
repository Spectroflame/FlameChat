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

If no reader is running at construction time we remember that and retry
the probe on the next ``announce`` call, so users who enable VoiceOver
after FlameChat started still get spoken feedback without restarting.

Library maintenance note (re-verified April 2026): ``accessible_output2``
0.17 is still the latest release (upstream has not published since July
2022) but it continues to work on all three platforms — VoiceOver,
NVDA/JAWS and Speech Dispatcher are wrapped stably and the dependency
surface (``appscript``, ``libloader``, ``platform-utils``) remains
healthy. The modern contender is SRAL (``m1maker/SRAL``, January 2025),
which is cross-platform and MIT-licensed but still 0.3 and ships as a
C library + Python binding; we'd take on native-build complexity for
no new user-visible capability. Keeping the ``Announcer`` as the only
place that touches the backend means swapping to SRAL later is a
single-file change if that trade-off ever flips.
"""

from __future__ import annotations

import threading


class Announcer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._out = None
        self._probe_failed = False
        self._enabled = True
        self._probe()

    def _probe(self) -> None:
        """Instantiate the accessible_output2 Auto facade, once per try.

        ``Auto()`` builds a list of every output backend whose probe
        succeeds right now. That list is frozen for the lifetime of
        the Auto object, so re-probing (by re-instantiating) lets us
        pick up a screen reader the user launched after FlameChat did.
        """
        try:
            from accessible_output2.outputs.auto import Auto

            self._out = Auto()
            self._probe_failed = False
        except Exception:
            self._out = None
            self._probe_failed = True

    @property
    def available(self) -> bool:
        return self._out is not None

    def enable(self, on: bool) -> None:
        self._enabled = on

    def announce(
        self, text: str, *, interrupt: bool = False, braille: bool = True
    ) -> None:
        """Say ``text`` through the active screen reader.

        ``interrupt=True`` cuts off any previously queued speech — use
        this for status changes the user must hear right away (error,
        abort, new assistant reply). For steady-stream events like
        "copied to clipboard", keep the default so the announcement
        doesn't clobber whatever the reader was already saying.

        ``braille=True`` (the default) also sends the text to the
        active Braille display. Pass ``braille=False`` for ephemeral
        status cues you do not want to latch onto a physical cell
        line that the user is currently reading.
        """
        if not self._enabled or not text:
            return
        with self._lock:
            if self._out is None:
                # Screen reader might have started after us — retry the
                # probe once per call rather than staying silent forever.
                self._probe()
            if self._out is None:
                return
            try:
                self._out.speak(text, interrupt=interrupt)
            except Exception:
                # Screen-reader IPC can fail transiently (user switched
                # VO off, NVDA restarting, speechd socket blip, etc.).
                # Drop the stored Auto so the next call re-probes, and
                # swallow so UI actions always complete.
                self._out = None
                return
            if braille:
                try:
                    self._out.braille(text)
                except Exception:
                    # Braille backends can be just as flaky as speech
                    # ones (a hot-unplugged USB display, a stalled
                    # BrlTTY socket). Swallow but keep the speech
                    # output alive — speech users still got their cue.
                    pass

    def braille(self, text: str) -> None:
        """Push ``text`` to the active Braille display if one is wired up.

        Calling the accessible_output2 ``braille`` hook costs nothing
        when no Braille device is attached — the backend silently
        no-ops. Useful when you want a Braille-only cue without
        speaking anything (``announce`` already braille-s by default).
        """
        if not self._enabled or not text:
            return
        with self._lock:
            if self._out is None:
                self._probe()
            if self._out is None:
                return
            try:
                self._out.braille(text)
            except Exception:
                self._out = None
