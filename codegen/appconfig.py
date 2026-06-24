"""Zentrale INI-Konfiguration des Editors (maschinenspezifische Pfade).

Liegt als `config.ini` neben der EXE (PyInstaller-Build) bzw. im Projekt-Root
(Start via `python -m app`). Damit stehen weder Spiel- noch Visual-Studio-Pfad
im Code.

Abschnitte:
  [paths]   game_path  -> Outpost-2-Installation (enthaelt maps.vol)
            msvs_path  -> Visual-Studio-Installation
                          (enthaelt Common7\\Tools\\VsDevCmd.bat)
  [output]  output_dir -> Zielordner der Mission-DLL (leer = game_path)
            dll_name   -> Dateiname der Mission-DLL
  [ui]      language   -> Sprache der Oberflaeche: auto (Systemsprache), de, en, ...
"""
from __future__ import annotations

import configparser
import sys
from pathlib import Path

DEFAULT_GAME_PATH = r"D:\Outpost 2"
DEFAULT_MSVS_PATH = r"C:\Program Files\Microsoft Visual Studio\18\Community"
DEFAULT_DLL_NAME = "cEditorMission.dll"
DEFAULT_LANGUAGE = "auto"  # "auto" = Systemsprache erkennen (sonst de/en/...)


def base_dir() -> Path:
    """Ordner, in dem config.ini erwartet wird: neben der EXE bzw. Projekt-Root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # codegen/appconfig.py -> Projekt-Root
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = base_dir() / "config.ini"


def _load() -> configparser.ConfigParser:
    # interpolation=None: Pfade mit '%' werden nicht als Platzhalter missdeutet.
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONFIG_PATH, encoding="utf-8")
    return cp


def _save(cp: configparser.ConfigParser) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cp.write(f)


def game_path() -> Path:
    return Path(_load().get("paths", "game_path", fallback=DEFAULT_GAME_PATH).strip()
                or DEFAULT_GAME_PATH)


def msvs_path() -> Path:
    return Path(_load().get("paths", "msvs_path", fallback=DEFAULT_MSVS_PATH).strip()
                or DEFAULT_MSVS_PATH)


def vsdevcmd() -> Path:
    """Pfad zu VsDevCmd.bat innerhalb der Visual-Studio-Installation."""
    return msvs_path() / "Common7" / "Tools" / "VsDevCmd.bat"


def platform_toolset() -> str:
    """msbuild PlatformToolset-Override (leer = Projekt-Vorgabe v142/VS2019).

    Auf neueren Visual-Studio-Versionen ohne v142 hier z.B. v143 (VS2022)
    oder v145 (VS2026) setzen.
    """
    return _load().get("build", "platform_toolset", fallback="").strip()


def windows_sdk() -> str:
    """msbuild WindowsTargetPlatformVersion-Override (leer = Projekt-Vorgabe)."""
    return _load().get("build", "windows_sdk", fallback="").strip()


def output_dir() -> str:
    val = _load().get("output", "output_dir", fallback="").strip()
    return val or str(game_path())


def dll_name() -> str:
    return _load().get("output", "dll_name", fallback=DEFAULT_DLL_NAME).strip() or DEFAULT_DLL_NAME


def language() -> str:
    """UI-Sprachkuerzel aus [ui] language (Vorgabe: de)."""
    return _load().get("ui", "language", fallback=DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    """Speichert das UI-Sprachkuerzel zurueck in die config.ini."""
    cp = _load()
    if not cp.has_section("ui"):
        cp.add_section("ui")
    cp.set("ui", "language", code)
    _save(cp)


def set_output(out_dir: str, name: str) -> None:
    """Speichert Ausgabeordner + DLL-Name zurueck in die config.ini."""
    cp = _load()
    if not cp.has_section("output"):
        cp.add_section("output")
    cp.set("output", "output_dir", out_dir)
    cp.set("output", "dll_name", name)
    _save(cp)


def ensure_default_file() -> None:
    """Legt eine config.ini mit Standardwerten an, falls noch keine existiert."""
    if CONFIG_PATH.exists():
        return
    cp = configparser.ConfigParser(interpolation=None)
    cp["paths"] = {"game_path": DEFAULT_GAME_PATH, "msvs_path": DEFAULT_MSVS_PATH}
    cp["build"] = {"platform_toolset": "", "windows_sdk": ""}
    cp["output"] = {"output_dir": "", "dll_name": DEFAULT_DLL_NAME}
    cp["ui"] = {"language": DEFAULT_LANGUAGE}
    try:
        _save(cp)
    except OSError:
        pass  # schreibgeschuetzter Ordner: Defaults greifen trotzdem via fallback
