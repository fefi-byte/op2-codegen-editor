"""Schlanke INI-basierte Mehrsprachigkeit fuer den Editor.

Sprachdateien `lang.<code>.ini` liegen neben der EXE bzw. im Projekt-Root
(dieselbe base_dir wie config.ini). Aufbau:

    [section]
    key = Text mit optionalen {platzhaltern}

Zugriff im Code:  tr("section.key", platzhalter=wert)

Die aktive Sprache kommt aus config.ini ([ui] language); fehlt ein Schluessel,
wird auf Deutsch (de) und zuletzt auf den Schluessel selbst zurueckgegriffen.
Fehlende Schluessel werden gesammelt (missing_keys()), damit Tests Luecken
finden.
"""
from __future__ import annotations

import configparser

import appconfig

FALLBACK_LANG = "de"

_langs: dict[str, dict[str, str]] = {}
_active: str = FALLBACK_LANG
_missing: set[str] = set()


def _load_lang(code: str) -> dict[str, str]:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # Schluessel case-sensitiv lassen
    cp.read(appconfig.base_dir() / f"lang.{code}.ini", encoding="utf-8")
    flat: dict[str, str] = {}
    for section in cp.sections():
        for key, value in cp.items(section):
            # Literales \n in der INI -> echter Zeilenumbruch (robuster als
            # mehrzeilige INI-Werte).
            flat[f"{section}.{key}"] = value.replace("\\n", "\n")
    return flat


def detect_system_language() -> str | None:
    """Zwei-Buchstaben-Sprachcode der Systemsprache (z.B. 'de', 'en') oder None."""
    # Windows: konfigurierte Anzeige-Sprache der Oberflaeche.
    try:
        import ctypes
        import locale
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        name = locale.windows_locale.get(langid)
        if name:
            return name.split("_")[0].lower()
    except Exception:
        pass
    # POSIX: uebliche Locale-Umgebungsvariablen (de_DE.UTF-8 -> de).
    import os
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var)
        if val:
            code = val.replace("-", "_").split(".")[0].split("_")[0].strip().lower()
            if code.isalpha():
                return code
    return None


def resolve_language(language: str | None) -> str:
    """Loest 'auto'/leer in einen tatsaechlich vorhandenen Sprachcode auf."""
    code = (language or "").strip().lower()
    if code in ("", "auto"):
        code = detect_system_language() or FALLBACK_LANG
    avail = set(available())
    if avail and code not in avail:
        code = FALLBACK_LANG if FALLBACK_LANG in avail else sorted(avail)[0]
    return code or FALLBACK_LANG


def init(language: str | None = None) -> None:
    """Laedt Fallback- und aktive Sprache. Mehrfachaufruf ist unschaedlich.

    `language` = None -> aus config.ini; 'auto'/leer -> Systemsprache erkennen.
    """
    global _active
    _active = resolve_language(language if language is not None else appconfig.language())
    for code in {FALLBACK_LANG, _active}:
        _langs[code] = _load_lang(code)


def active() -> str:
    return _active


def available() -> list[str]:
    """Sprachkuerzel, fuer die eine lang.<code>.ini existiert."""
    base = appconfig.base_dir()
    return sorted(p.stem.split(".", 1)[1] for p in base.glob("lang.*.ini"))


def tr(key: str, /, **fmt) -> str:
    """Uebersetzten Text fuer `key` liefern (mit optionaler {platzhalter}-Ersetzung)."""
    if not _langs:
        init()
    text = _langs.get(_active, {}).get(key)
    if text is None:
        text = _langs.get(FALLBACK_LANG, {}).get(key)
    if text is None:
        _missing.add(key)
        return key
    return text.format(**fmt) if fmt else text


def missing_keys() -> set[str]:
    return set(_missing)
