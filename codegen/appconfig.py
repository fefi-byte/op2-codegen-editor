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
            show_grid  -> Kachelgitter ueber der Karte (true/false)

Central INI configuration of the editor (machine-specific paths).

Lives as `config.ini` next to the EXE (PyInstaller build) or in the project
root (start via `python -m app`). This keeps neither the game nor the Visual
Studio path in the code.

Sections:
  [paths]   game_path  -> Outpost 2 installation (contains maps.vol)
            msvs_path  -> Visual Studio installation
                          (contains Common7\\Tools\\VsDevCmd.bat)
  [output]  output_dir -> target folder of the mission DLL (empty = game_path)
            dll_name   -> file name of the mission DLL
  [ui]      language   -> language of the UI: auto (system language), de, en, ...
            show_grid  -> tile grid over the map (true/false)
"""
from __future__ import annotations

import configparser
import sys
from pathlib import Path

import platform as _platform

# On Windows keep sensible install defaults; on Linux there is no universal path
# (game typically runs under Wine), so leave blank and let the user fill it in.
if _platform.system() == "Windows":
    DEFAULT_GAME_PATH = r"D:\Outpost 2"
    DEFAULT_MSVS_PATH = r"C:\Program Files\Microsoft Visual Studio\18\Community"
else:
    DEFAULT_GAME_PATH = ""
    DEFAULT_MSVS_PATH = ""

DEFAULT_DLL_NAME = "cEditorMission.dll"
DEFAULT_LANGUAGE = "auto"  # "auto" = Systemsprache erkennen (sonst de/en/...)
                           # "auto" = detect system language (otherwise de/en/...)


def base_dir() -> Path:
    """Ordner, in dem config.ini erwartet wird: neben der EXE bzw. Projekt-Root.

    Folder in which config.ini is expected: next to the EXE or project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # codegen/appconfig.py -> Projekt-Root
    # codegen/appconfig.py -> project root
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = base_dir() / "config.ini"


def titanapi_include_dir() -> Path:
    """Ordner mit den TitanAPI-Headern (op2.hpp usw.), fuer generierte CMakeLists.txt.

    Im PyInstaller-Build liegen sie gebuendelt unter sys._MEIPASS (_internal/);
    im Dev-Checkout unter TitanAPI/TitanAPI/include neben codegen/. Ein fixer
    relativer Pfad (z.B. "../../TitanAPI/...") ist falsch, sobald eine Mission
    ausserhalb des Repo-Layouts liegt (z.B. im entpackten Release-ZIP).

    Folder containing the TitanAPI headers (op2.hpp etc.), for the generated
    CMakeLists.txt. In a PyInstaller build they are bundled under sys._MEIPASS
    (_internal/); in a dev checkout under TitanAPI/TitanAPI/include next to
    codegen/. A fixed relative path (e.g. "../../TitanAPI/...") breaks as soon
    as a mission folder lives outside the repo layout (e.g. an extracted
    release ZIP).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "TitanAPI" / "TitanAPI" / "include"
    return base_dir() / "TitanAPI" / "TitanAPI" / "include"


def _load() -> configparser.ConfigParser:
    # interpolation=None: Pfade mit '%' werden nicht als Platzhalter missdeutet.
    # interpolation=None: paths containing '%' are not misread as placeholders.
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONFIG_PATH, encoding="utf-8")
    return cp


def _save(cp: configparser.ConfigParser) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cp.write(f)


def game_path() -> Path:
    val = _load().get("paths", "game_path", fallback=DEFAULT_GAME_PATH).strip()
    return Path(val or DEFAULT_GAME_PATH or ".")


def msvs_path() -> Path:
    return Path(_load().get("paths", "msvs_path", fallback=DEFAULT_MSVS_PATH).strip()
                or DEFAULT_MSVS_PATH)


def vsdevcmd() -> Path:
    """Pfad zu VsDevCmd.bat innerhalb der Visual-Studio-Installation.

    Path to VsDevCmd.bat inside the Visual Studio installation.
    """
    return msvs_path() / "Common7" / "Tools" / "VsDevCmd.bat"


def platform_toolset() -> str:
    """msbuild PlatformToolset-Override (leer = Projekt-Vorgabe v142/VS2019).

    Auf neueren Visual-Studio-Versionen ohne v142 hier z.B. v143 (VS2022)
    oder v145 (VS2026) setzen.

    msbuild PlatformToolset override (empty = project default v142/VS2019).

    On newer Visual Studio versions without v142, set e.g. v143 (VS2022)
    or v145 (VS2026) here.
    """
    return _load().get("build", "platform_toolset", fallback="").strip()


def windows_sdk() -> str:
    """msbuild WindowsTargetPlatformVersion-Override (leer = Projekt-Vorgabe).

    msbuild WindowsTargetPlatformVersion override (empty = project default).
    """
    return _load().get("build", "windows_sdk", fallback="").strip()


def output_dir() -> str:
    val = _load().get("output", "output_dir", fallback="").strip()
    if val:
        return val
    # Vorgabe: der OPU-Ordner -- dort sucht die OPU-Version von OP2 nach
    # Missionen (und dort liegt op2launcher.exe), nie der Spiel-Wurzelordner.
    # Default: the OPU folder -- where the OPU version of OP2 looks for missions
    # (and where op2launcher.exe lives), never the game root folder.
    opu = game_path() / "OPU"
    return str(opu if opu.is_dir() else game_path())


def dll_name() -> str:
    return _load().get("output", "dll_name", fallback=DEFAULT_DLL_NAME).strip() or DEFAULT_DLL_NAME


def language() -> str:
    """UI-Sprachkuerzel aus [ui] language (Vorgabe: de).

    UI language code from [ui] language (default: de).
    """
    return _load().get("ui", "language", fallback=DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    """Speichert das UI-Sprachkuerzel zurueck in die config.ini.

    Saves the UI language code back into config.ini.
    """
    cp = _load()
    if not cp.has_section("ui"):
        cp.add_section("ui")
    cp.set("ui", "language", code)
    _save(cp)


def show_grid() -> bool:
    """Ob das Kachelgitter ueber der Karte angezeigt wird ([ui] show_grid).

    Whether the tile grid over the map is shown ([ui] show_grid). Default: off.
    """
    return _load().getboolean("ui", "show_grid", fallback=False)


def set_show_grid(on: bool) -> None:
    """Speichert die Gitter-Sichtbarkeit zurueck in die config.ini.

    Saves the grid visibility back into config.ini.
    """
    cp = _load()
    if not cp.has_section("ui"):
        cp.add_section("ui")
    cp.set("ui", "show_grid", "true" if on else "false")
    _save(cp)


def last_mission() -> str:
    """Pfad zur zuletzt geoeffneten/gespeicherten Mission (Ordner). Leer = keiner."""
    return _load().get("ui", "last_mission", fallback="").strip()


def set_last_mission(path: str) -> None:
    """Merkt sich den Mission-Ordner fuer den Reopen-Dialog beim naechsten Start."""
    cp = _load()
    if not cp.has_section("ui"):
        cp.add_section("ui")
    cp.set("ui", "last_mission", path or "")
    _save(cp)


def set_output(out_dir: str, name: str) -> None:
    """Speichert Ausgabeordner + DLL-Name zurueck in die config.ini.

    Saves output folder + DLL name back into config.ini.
    """
    cp = _load()
    if not cp.has_section("output"):
        cp.add_section("output")
    cp.set("output", "output_dir", out_dir)
    cp.set("output", "dll_name", name)
    _save(cp)


def ensure_default_file() -> None:
    """Legt eine config.ini mit Standardwerten an, falls noch keine existiert.

    Creates a config.ini with default values if none exists yet.
    """
    if CONFIG_PATH.exists():
        return
    cp = configparser.ConfigParser(interpolation=None)
    paths: dict[str, str] = {"game_path": DEFAULT_GAME_PATH}
    if _platform.system() == "Windows":
        paths["msvs_path"] = DEFAULT_MSVS_PATH
    cp["paths"] = paths
    cp["build"] = {"platform_toolset": "", "windows_sdk": ""}
    cp["output"] = {"output_dir": "", "dll_name": DEFAULT_DLL_NAME}
    cp["ui"] = {"language": DEFAULT_LANGUAGE, "show_grid": "false"}
    try:
        _save(cp)
    except OSError:
        pass  # schreibgeschuetzter Ordner: Defaults greifen trotzdem via fallback
              # read-only folder: defaults still apply via fallback
