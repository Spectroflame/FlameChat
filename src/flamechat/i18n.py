"""Runtime translation layer, driven by per-language JSON files.

Every user-visible string lives under a stable key in
``src/flamechat/locale/<lang>.json``. Adding a language is a matter of
dropping a new JSON file next to the existing ones — no code changes.

The active language is chosen in this order:

1. ``Settings.language`` — if it is one of the shipped languages (``"de"``
   or ``"en"``), we honour it verbatim.
2. ``"auto"`` — detect the OS UI language at startup via the stdlib
   ``locale`` module and map it to the closest shipped language. This
   keeps first-launch experience native for German users and defaults
   to English everywhere else.
3. Fallback: English.

A language change requires an app restart (we don't rebuild widgets on
the fly), and the Settings dialog tells the user so.

Usage::

    from .i18n import t
    label = t("chat.send_button")

``t`` falls back to English when a key is missing in the active
language, and to the raw key when English is missing too — so a typo
never crashes the UI, it just renders as the key itself (easy to spot
in testing).
"""

from __future__ import annotations

import json
import locale as _stdlib_locale
from importlib.resources import files
from typing import Iterable, Literal


Language = Literal["de", "en"]


SUPPORTED_LANGUAGES: tuple[Language, ...] = ("de", "en")
DEFAULT_LANGUAGE: Language = "en"


LANGUAGE_NAMES: dict[Language, str] = {
    "de": "Deutsch",
    "en": "English",
}


_current: Language = DEFAULT_LANGUAGE
_translations: dict[Language, dict[str, str]] = {}


def _load_translations() -> None:
    """Pull each shipped locale file into ``_translations``.

    Missing or malformed files fall back to an empty dict for that
    language so a broken locale file cannot take the whole UI down —
    the ``t()`` fallback chain renders the raw key instead, which is
    easy to spot in testing.
    """
    _translations.clear()
    for lang in SUPPORTED_LANGUAGES:
        try:
            ref = files("flamechat.locale").joinpath(f"{lang}.json")
            with ref.open("r", encoding="utf-8") as f:
                _translations[lang] = json.load(f)
        except (FileNotFoundError, ModuleNotFoundError, OSError, json.JSONDecodeError):
            _translations[lang] = {}


_load_translations()


def _detect_system_language() -> Language:
    """Guess a shipped language from the OS UI locale.

    ``locale.getlocale()`` is the stdlib's portable entry point —
    ``getdefaultlocale`` was deprecated in 3.11. On macOS and Linux it
    reads the LANG / LC_MESSAGES env vars; on Windows it queries
    ``GetUserDefaultUILanguage``. We only care about the language
    portion (``de_AT.UTF-8`` → ``de``) and map anything unknown to
    English so a Hungarian user without a ``hu.json`` still gets
    usable UI.
    """
    candidates: list[str | None] = []
    try:
        lang_code, _encoding = _stdlib_locale.getlocale()
        candidates.append(lang_code)
    except (ValueError, TypeError):
        pass
    try:
        candidates.append(_stdlib_locale.getdefaultlocale()[0])  # type: ignore[attr-defined]
    except (AttributeError, ValueError, TypeError):
        pass
    for raw in candidates:
        if not raw:
            continue
        primary = raw.split("_", 1)[0].split("-", 1)[0].lower()
        if primary in SUPPORTED_LANGUAGES:
            return primary  # type: ignore[return-value]
    return DEFAULT_LANGUAGE


def resolve_language(preference: str | None) -> Language:
    """Turn a stored preference (``"de"``, ``"en"``, ``"auto"``, …) into a shipped language.

    Called once at startup and any time the settings dialog writes a
    new value. Unknown values collapse to the default so a stray
    ``Settings.language = "xx"`` can never leave the UI untranslated.
    """
    if preference in SUPPORTED_LANGUAGES:
        return preference  # type: ignore[return-value]
    if preference == "auto" or preference is None:
        return _detect_system_language()
    return DEFAULT_LANGUAGE


def set_language(lang_or_preference: str) -> Language:
    """Activate a language and return the language that was actually applied.

    Accepts either a concrete supported language (``"de"`` / ``"en"``)
    or the ``"auto"`` sentinel. Returns the resolved language so the
    settings layer can display what auto-detect picked.
    """
    global _current
    _current = resolve_language(lang_or_preference)
    return _current


def current_language() -> Language:
    return _current


def available_languages() -> Iterable[Language]:
    return SUPPORTED_LANGUAGES


def t(key: str, **kwargs: object) -> str:
    """Translate ``key`` using the current language.

    ``kwargs`` are substituted via ``str.format`` if the translation
    uses placeholders. Unknown keys render as the key itself so
    developers spot the typo at a glance.
    """
    text = (
        _translations.get(_current, {}).get(key)
        or _translations.get(DEFAULT_LANGUAGE, {}).get(key)
        or key
    )
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
