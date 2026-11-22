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


def op2sdk_dir() -> Path:
    """Wurzelordner des OP2MissionSDK (Outpost2DLL + OP2Helper + HFL), fuer
    generierte CMakeLists.txt.

    Im PyInstaller-Build liegt es gebuendelt unter sys._MEIPASS (_internal/);
    im Dev-Checkout als Submodul OP2MissionSDK/ neben codegen/. Ein fixer
    relativer Pfad ist falsch, sobald eine Mission ausserhalb des
    Repo-Layouts liegt (z.B. im entpackten Release-ZIP).

    Root folder of the OP2MissionSDK (Outpost2DLL + OP2Helper + HFL), for the
    generated CMakeLists.txt. In a PyInstaller build it is bundled under
    sys._MEIPASS (_internal/); in a dev checkout it is the OP2MissionSDK/
    submodule next to codegen/. A fixed relative path breaks as soon as a
    mission folder lives outside the repo layout (e.g. an extracted release
    ZIP).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "OP2MissionSDK"
    return base_dir() / "OP2MissionSDK"


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


def op2ki_dir() -> Path | None:
    """Ordner des op2-ki-Projekts (eigenes Projekt, github.com/fefi-byte/op2-ki).

    Vorgabe: das Submodul op2-ki/ (im Release auf dem neuesten op2-ki-Release),
    im PyInstaller-Build die mitgelieferte Kopie unter _internal/. [paths]
    op2ki_path in config.ini geht vor (z.B. ein eigener Checkout). None, wenn
    es keinen gibt.

    Folder of the op2-ki project. Default: the op2-ki/ submodule (in a release
    on the latest op2-ki release), in a PyInstaller build the bundled copy;
    [paths] op2ki_path overrides it. None if there is none.
    """
    val = _load().get("paths", "op2ki_path", fallback="").strip()
    if val:
        return Path(val)
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        d = Path(sys._MEIPASS) / "op2-ki"
    else:
        d = base_dir() / "op2-ki"
    return d if (d / "Cargo.toml").is_file() else None


def op2ki_dateien() -> dict[str, Path] | None:
    """Die Header der op2-ki-Schnittstelle ("op2ki.hpp", "op2ki_bruecke.hpp")
    oder None, wenn das op2-ki-Projekt fehlt.

    The headers of the op2-ki interface, or None if the project is missing.
    """
    d = op2ki_dir()
    if d is None:
        return None
    g = d / "missionen" / "gemeinsam"
    dateien = {name: g / name for name in ("op2ki.hpp", "op2ki_bruecke.hpp")}
    return dateien if all(p.is_file() for p in dateien.values()) else None


def op2ki_bauordner() -> Path:
    """Schreibbarer Ordner fuer den Rust-Build der op2ki.dll (cargo target).

    Writable folder for the Rust build of op2ki.dll (cargo target dir).
    """
    return base_dir() / "build" / "op2ki"


def op2ki_dll_bauen(log=print) -> Path:
    """op2ki.dll aus dem op2-ki-Projekt auf diesem PC bauen (Rust, 32 Bit).

    cargo baut nur neu, was sich geaendert hat -- ein zweiter Aufruf ist schnell.
    Wirft SystemExit mit einer verstaendlichen Meldung, wenn Rust oder das Ziel
    i686-pc-windows-msvc fehlt oder der Build scheitert.

    Build op2ki.dll from the op2-ki project on this PC (Rust, 32 bit). cargo
    only rebuilds what changed. Raises SystemExit with a readable message if
    Rust or the i686-pc-windows-msvc target is missing or the build fails.
    """
    import shutil as _shutil
    import subprocess as _subprocess
    d = op2ki_dir()
    if d is None:
        raise SystemExit("op2-ki fehlt (Submodul op2-ki/ oder [paths] op2ki_path). "
                         "op2-ki is missing (op2-ki/ submodule or [paths] op2ki_path).")
    cargo = _shutil.which("cargo")
    if cargo is None:
        raise SystemExit("Rust fehlt: https://rustup.rs installieren, dann "
                         "'rustup target add i686-pc-windows-msvc'. "
                         "Rust is missing: install it from https://rustup.rs, then add the target above.")
    ziel = op2ki_bauordner()
    ziel.mkdir(parents=True, exist_ok=True)
    cmd = [cargo, "build", "--release", "-p", "op2ki-dll", "--target", "i686-pc-windows-msvc",
           "--manifest-path", str(d / "Cargo.toml"), "--target-dir", str(ziel)]
    log("op2-ki: " + " ".join(cmd))
    r = _subprocess.run(cmd, cwd=str(d), capture_output=True, text=True,
                        creationflags=getattr(_subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        ende = "\n".join((r.stderr or r.stdout or "").strip().splitlines()[-25:])
        hinweis = ""
        if "i686-pc-windows-msvc" in ende and ("not installed" in ende or "can't find crate" in ende):
            hinweis = "\n\n'rustup target add i686-pc-windows-msvc' ausfuehren / run it."
        raise SystemExit(f"op2ki.dll: Rust-Build gescheitert / Rust build failed:\n{ende}{hinweis}")
    dll = ziel / "i686-pc-windows-msvc" / "release" / "op2ki.dll"
    if not dll.is_file():
        raise SystemExit(f"op2ki.dll nicht gefunden / not found: {dll}")
    return dll


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
