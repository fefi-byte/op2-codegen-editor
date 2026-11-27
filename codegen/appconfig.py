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
            netz_threads -> Threads des gelernten Kartengenerators, 0 = automatisch

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
            netz_threads -> threads of the learned map generator, 0 = automatic
"""
from __future__ import annotations

import configparser
import os
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


class BuildFehler(SystemExit):
    """Build-Fehler mit Schluessel fuer die Sprachdateien ([build_errors]).

    Der Editor zeigt ihn in der Oberflaechensprache (tr("build_errors.<key>",
    **werte)). Ohne Editor (Kommandozeile) ist str() der deutsche Text wie
    bisher -- er muss zu lang.de.ini passen.

    Build error carrying a key for the language files ([build_errors]). The
    editor shows it in the UI language; on the command line str() is the
    German text as before, which must match lang.de.ini.
    """

    def __init__(self, key: str, text_de: str, **werte):
        super().__init__(text_de.format(**werte))
        self.key = key
        self.werte = werte


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


def op2maplib_dir() -> Path | None:
    """Ordner von OP2MappingLib (github.com/OutpostUniverse/OP2MappingLib).

    Vorgabe: das Submodul OP2MappingLib/, im PyInstaller-Build die
    mitgelieferte Kopie unter _internal/. [paths] op2maplib_path in config.ini
    geht vor (z.B. ein eigener Checkout). None, wenn es keinen gibt.

    Folder of OP2MappingLib. Default: the OP2MappingLib/ submodule, in a
    PyInstaller build the bundled copy; [paths] op2maplib_path overrides it.
    None if there is none.
    """
    val = _load().get("paths", "op2maplib_path", fallback="").strip()
    if val:
        d = Path(val)
    elif getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        d = Path(sys._MEIPASS) / "OP2MappingLib"
    else:
        d = base_dir() / "OP2MappingLib"
    return d if (d / "profiles" / "op2.json").is_file() else None


def op2maplib_selbst_bauen() -> bool:
    """[build] op2maplib_selbst_bauen: op2maplib.dll aus den Quellen des
    Submoduls bauen (CMake + MSVC), statt die fertige DLL des Submoduls zu nehmen.

    [build] op2maplib_selbst_bauen: build op2maplib.dll from the submodule's
    sources (CMake + MSVC) instead of using the submodule's prebuilt DLL.
    """
    val = _load().get("build", "op2maplib_selbst_bauen", fallback="false").strip().lower()
    return val in ("1", "true", "ja", "yes")


def op2maplib_bauordner() -> Path:
    """Wohin `op2maplib_dll_bauen` baut (git-ignoriert). Build folder, git-ignored."""
    return base_dir() / "build-op2maplib"


def _cmake_suchen() -> str | None:
    """cmake: PATH, sonst die CMake jeder Visual-Studio-Installation (auch Build
    Tools, Insiders, Program Files (x86)), sonst eine eigene CMake-Installation.

    cmake on PATH, else the CMake of any Visual Studio install (including Build
    Tools, Insiders, Program Files (x86)), else a standalone CMake install.
    """
    import glob
    import shutil
    p = shutil.which("cmake")
    if p:
        return p
    for muster in (r"C:\Program Files*\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions"
                   r"\Microsoft\CMake\CMake\bin\cmake.exe",
                   r"C:\Program Files*\CMake\bin\cmake.exe"):
        treffer = sorted(glob.glob(muster), reverse=True)   # neuere VS-Versionen zuerst
        if treffer:
            return treffer[0]
    return None


def op2maplib_dll_bauen() -> Path:
    """op2maplib.dll mit CMake aus dem Submodul bauen -> Pfad der DLL.

    Gebaut wird nur, wenn die DLL fehlt oder eine Quelldatei neuer ist.
    Architektur wie das laufende Python (x64 / Win32). Wirft RuntimeError mit
    einer lesbaren Meldung, wenn CMake fehlt oder der Build scheitert.

    Build op2maplib.dll from the submodule with CMake. Rebuilds only when the DLL
    is missing or a source file is newer. Same architecture as the running
    Python. Raises RuntimeError with a readable message if CMake is missing or
    the build fails.
    """
    import struct
    import subprocess
    quelle = op2maplib_dir()
    if quelle is None or not (quelle / "CMakeLists.txt").is_file():
        raise RuntimeError("OP2MappingLib-Quellen fehlen (Submodul) / sources missing (submodule)")
    ziel = op2maplib_bauordner()
    dll = ziel / "bin" / "Release" / "op2maplib.dll"
    if dll.is_file():
        stand = dll.stat().st_mtime
        quellen = [quelle / "CMakeLists.txt", *(quelle / "src").rglob("*"), *(quelle / "include").rglob("*")]
        if all(q.stat().st_mtime <= stand for q in quellen if q.is_file()):
            return dll
    cmake = _cmake_suchen()
    if cmake is None:
        raise RuntimeError("cmake nicht gefunden / not found (Visual Studio mit C++ oder CMake installieren)")
    import shutil
    arch = "x64" if struct.calcsize("P") == 8 else "Win32"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    konfig = [cmake, "-S", str(quelle), "-B", str(ziel), "-A", arch, "-DOP2MAPLIB_BUILD_TESTS=OFF"]

    def lauf(cmd):
        return subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)

    r = lauf(konfig)
    if r.returncode != 0 and (ziel / "CMakeCache.txt").is_file():
        # Alter Cache, z.B. von einer anderen Visual-Studio-Version: einmal
        # frisch konfigurieren. Stale cache (e.g. another VS version): retry clean.
        shutil.rmtree(ziel, ignore_errors=True)
        r = lauf(konfig)
    if r.returncode == 0:
        r = lauf([cmake, "--build", str(ziel), "--config", "Release"])
    if r.returncode != 0:
        ende = "\n".join((r.stdout + r.stderr).strip().splitlines()[-20:])
        raise RuntimeError(f"op2maplib-Build gescheitert / build failed:\n{ende}")
    if not dll.is_file():
        raise RuntimeError(f"op2maplib.dll nach dem Build nicht gefunden / not found: {dll}")
    return dll


def op2maplib_dll() -> Path | None:
    """Die op2maplib.dll, die der Editor laedt, oder None.

    - EXE: die beim Release aus den Quellen gebaute DLL (_internal/OP2MappingLib/bin).
    - [build] op2maplib_selbst_bauen = true: aus den Quellen gebaut (`op2maplib_dll_bauen`).
    - sonst: die fertige DLL des Submoduls (bindings/dotnet/native/<arch>).

    The DLL the editor loads: in the EXE the one built from source for the
    release; with op2maplib_selbst_bauen built from source here; otherwise the
    submodule's prebuilt DLL. None if there is none.
    """
    import struct
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        dll = Path(sys._MEIPASS) / "OP2MappingLib" / "bin" / "op2maplib.dll"
        return dll if dll.is_file() else None
    if op2maplib_selbst_bauen():
        return op2maplib_dll_bauen()
    d = op2maplib_dir()
    if d is None:
        return None
    dll = d / "bindings" / "dotnet" / "native" / ("x64" if struct.calcsize("P") == 8 else "x86") / "op2maplib.dll"
    if not dll.is_file():
        return None
    # Die fertige DLL des Submoduls hinkt den Quellen hinterher, bis OP2MappingLib
    # eine neue Version veroeffentlicht. Fehlt ihr der Kartengenerator, aus den
    # Quellen bauen (CMake noetig); geht das nicht, bleibt sie fuer Pinsel und Klippen.
    # The submodule's prebuilt DLL lags behind its sources until a new release;
    # without the map generator, build from source (needs CMake); else keep it
    # for brush and cliffs. Nur unter Windows (die DLL ist eine Windows-DLL) und
    # nicht, wenn OP2MAPLIB_PATH ohnehin eine andere Bibliothek nennt.
    # Only on Windows, and not when OP2MAPLIB_PATH names another library anyway.
    if (sys.platform == "win32" and not os.environ.get("OP2MAPLIB_PATH")
            and b"om_mapgen_generate_learned" not in dll.read_bytes()):
        try:
            return op2maplib_dll_bauen()
        except RuntimeError as e:
            print("op2maplib.dll ohne Kartengenerator, Bauen gescheitert:", e)
    return dll


def op2maplib_aktiv() -> bool:
    """[terrain] op2maplib: Kartenfunktionen (Neue Karte, Gelaendepinsel,
    Klippen, Aufraeumen) ueber OP2MappingLib (Vorgabe). false schaltet sie ab --
    einen Python-Ersatz gibt es nicht mehr.

    [terrain] op2maplib: map functions via OP2MappingLib (default); false
    switches them off, there is no Python fallback any more.
    """
    val = _load().get("terrain", "op2maplib", fallback="true").strip().lower()
    return val not in ("0", "false", "nein", "no")


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


def op2ki_dll() -> Path:
    """op2ki.dll fuer die Mission: die fertige aus dem op2-ki-Release (fertig/op2ki.dll,
    gehoert zum ausgecheckten Tag) -- oder mit [build] op2ki_selbst_bauen = true aus den
    Quellen auf diesem PC gebaut (Rust noetig).

    op2ki.dll for the mission: the ready-built one from the op2-ki release
    (fertig/op2ki.dll) -- or, with [build] op2ki_selbst_bauen = true, built from
    the sources on this PC (needs Rust).
    """
    if _load().get("build", "op2ki_selbst_bauen", fallback="false").strip().lower() in ("1", "true", "ja", "yes"):
        return op2ki_dll_bauen()
    d = op2ki_dir()
    dll = d / "fertig" / "op2ki.dll" if d else None
    if dll is None or not dll.is_file():
        raise BuildFehler("op2ki_dll_missing", "op2ki.dll fehlt: {path}", path=dll)
    return dll


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
        raise BuildFehler("op2ki_missing",
                          "op2-ki fehlt (Submodul op2-ki/ oder [paths] op2ki_path).")
    cargo = _shutil.which("cargo")
    if cargo is None:
        raise BuildFehler("rust_missing",
                          "Rust fehlt: https://rustup.rs installieren, dann "
                          "'rustup target add i686-pc-windows-msvc'.")
    ziel = op2ki_bauordner()
    ziel.mkdir(parents=True, exist_ok=True)
    cmd = [cargo, "build", "--release", "-p", "op2ki-dll", "--target", "i686-pc-windows-msvc",
           "--manifest-path", str(d / "Cargo.toml"), "--target-dir", str(ziel)]
    log("op2-ki: " + " ".join(cmd))
    r = _subprocess.run(cmd, cwd=str(d), capture_output=True, text=True,
                        creationflags=getattr(_subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        ende = "\n".join((r.stderr or r.stdout or "").strip().splitlines()[-25:])
        if "i686-pc-windows-msvc" in ende and ("not installed" in ende or "can't find crate" in ende):
            raise BuildFehler("rust_build_failed_target",
                              "op2ki.dll: Rust-Build gescheitert:\n{details}\n\n"
                              "'rustup target add i686-pc-windows-msvc' ausfuehren.",
                              details=ende)
        raise BuildFehler("rust_build_failed",
                          "op2ki.dll: Rust-Build gescheitert:\n{details}", details=ende)
    dll = ziel / "i686-pc-windows-msvc" / "release" / "op2ki.dll"
    if not dll.is_file():
        raise BuildFehler("op2ki_dll_not_found", "op2ki.dll nicht gefunden: {path}",
                          path=dll)
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


def set_game_path(path: str) -> None:
    """Speichert den Outpost-2-Ordner in die config.ini.

    Saves the Outpost 2 folder into config.ini.
    """
    cp = _load()
    if not cp.has_section("paths"):
        cp.add_section("paths")
    cp.set("paths", "game_path", path)
    _save(cp)


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


def netz_threads() -> int:
    """Threads des gelernten Kartengenerators ([ui] netz_threads), 0 = automatisch.

    Threads of the learned map generator, 0 = automatic.
    """
    try:
        return max(0, _load().getint("ui", "netz_threads", fallback=0))
    except ValueError:
        return 0


def set_netz_threads(n: int) -> None:
    """Speichert die Threadzahl zurueck in die config.ini. / Saves the thread count."""
    cp = _load()
    if not cp.has_section("ui"):
        cp.add_section("ui")
    cp.set("ui", "netz_threads", str(int(n)))
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
