"""Mission-Ordner: jede Mission ist ein eigener self-contained Ordner (TitanAPI-Variante).

Inhalt:
  - mission.op2proj   (Editor-Projektdatei, JSON)
  - mission.cpp       (generiert -- TitanAPI / op2:: facade)
  - op2_mission.hpp   (1:1 aus Template, Mission-DLL-ABI)
  - op2_log.hpp       (1:1 aus Template, file logging)
  - op2_crash.hpp     (1:1 aus Template, SEH guards)
  - version.rc.in     (Windows version info, von CMake befuellt)
  - CMakeLists.txt    (CMake-Projekt, Pfade relativ zum TitanAPI-Submodul)
  - <name>.map        (Karte-Kopie)
  - MULTITEK.TXT      (optional, falls Mission custom tech tree nutzt)
  - build.bat, README.md

Ziel: jeder kann mit `git clone --recursive` + `build.bat` die Mission
kompilieren, ohne den Editor zu brauchen.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import appconfig

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _slugify(name: str) -> str:
    """Wandelt einen Mission-Namen in einen ordner-/dateisystemtauglichen Slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    slug = slug.strip("_-")
    return slug or "Mission"


def _project_guid_from_folder(folder: Path) -> str:
    """Stabiler GUID pro Mission-Ordnernamen (so dass Re-Saves den Wert behalten)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"op2-codegen-editor:{folder.name}")).upper()


def _apply_placeholders(text: str, repl: dict[str, str]) -> str:
    for key, val in repl.items():
        text = text.replace(key, val)
    return text


def _copy_template(name: str, dest: Path, repl: dict[str, str] | None = None) -> None:
    src = TEMPLATES_DIR / name
    text = src.read_text(encoding="utf-8")
    if repl:
        text = _apply_placeholders(text, repl)
    dest.write_text(text, encoding="utf-8")


def find_map_source(map_name: str, search_dirs: list[Path]) -> Path | None:
    """Sucht die Originalkarte (zum Kopieren in den Mission-Ordner)."""
    if not map_name:
        return None
    for d in search_dirs:
        if not d or not d.is_dir():
            continue
        cand = d / map_name
        if cand.is_file():
            return cand
        for sub in ("maps", "base/maps", "OPU/maps", "OPU/base/maps"):
            cand = d / sub / map_name
            if cand.is_file():
                return cand
    return None


def write_mission_folder(
    folder: Path,
    *,
    mission_name: str,
    map_name: str,
    project_data: dict[str, Any],
    level_main_cpp: str,
    map_source: Path | None,
    techtree_source: Path | None = None,
    dll_basename: str = "cMission",
) -> dict[str, Path]:
    """Schreibt eine vollstaendige TitanAPI-Mission in den Ordner.

    `level_main_cpp` wird als `mission.cpp` geschrieben. Solange der Editor-
    Codegen noch nicht auf TitanAPI portiert ist, faellt eine leere/legacy-
    Eingabe auf das `mission.cpp.template` zurueck.
    """
    folder.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    namespace = _slugify(mission_name)
    repl = {
        "__MISSION_NAMESPACE__": namespace,
        "__MISSION_NAME__": mission_name,
        "__DLL_BASENAME__": dll_basename,
        "__MAP_FILENAME__": map_name or "on1_01.map",
        # Absoluter Pfad statt fixem "../../TitanAPI/..." -- funktioniert im
        # Dev-Checkout genauso wie in einer aus dem Release-ZIP entpackten
        # Mission (siehe appconfig.titanapi_include_dir()).
        # Absolute path instead of a fixed "../../TitanAPI/..." -- works in
        # the dev checkout the same as in a mission extracted from the
        # release ZIP (see appconfig.titanapi_include_dir()).
        "__TITANAPI_INCLUDE_DIR__": appconfig.titanapi_include_dir().as_posix(),
    }

    # 1) Editor-Projektdatei
    proj_path = folder / "mission.op2proj"
    proj_path.write_text(json.dumps(project_data, indent=2), encoding="utf-8")
    written["project"] = proj_path

    # 2) mission.cpp -- wenn der Codegen schon TitanAPI-Code liefert, nehmen
    #    wir den; sonst die platzhalter-gefuellte Template-Datei.
    mcpp = folder / "mission.cpp"
    if level_main_cpp and level_main_cpp.lstrip().startswith("//") and "op2.hpp" in level_main_cpp:
        mcpp.write_text(level_main_cpp, encoding="utf-8")
    else:
        _copy_template("mission.cpp.template", mcpp, repl)
    written["mission_cpp"] = mcpp

    # 3) TitanAPI-Scaffolding (1:1 kopiert) + version.rc.in
    for name in ("op2_mission.hpp", "op2_log.hpp", "op2_crash.hpp", "version.rc.in"):
        target = folder / name
        _copy_template(name, target)
        written[name] = target

    # 4) Karte kopieren (sofern gefunden)
    if map_source and map_source.is_file():
        target = folder / map_name
        if not target.exists() or target.stat().st_mtime < map_source.stat().st_mtime:
            shutil.copy2(map_source, target)
        written["map"] = target

    # 5) Tech-Tree (optional)
    if techtree_source and techtree_source.is_file():
        target = folder / "MULTITEK.TXT"
        shutil.copy2(techtree_source, target)
        written["techtree"] = target

    # 6) CMakeLists.txt
    _copy_template("CMakeLists.txt.template", folder / "CMakeLists.txt", repl)
    written["cmake"] = folder / "CMakeLists.txt"

    # 7) build.bat (Windows) + build.sh (Linux) + README
    _copy_template("build.bat.template", folder / "build.bat", repl)
    build_sh = folder / "build.sh"
    _copy_template("build.sh.template", build_sh, repl)
    os.chmod(build_sh, 0o755)
    _copy_template("README.md.template", folder / "README.md", repl)
    written["build_bat"] = folder / "build.bat"
    written["build_sh"] = build_sh
    written["readme"] = folder / "README.md"

    return written


def is_mission_folder(path: Path) -> bool:
    return path.is_dir() and (path / "mission.op2proj").is_file()


def find_op2proj(path: Path) -> Path | None:
    """Gibt die op2proj-Datei zurueck, egal ob `path` der Ordner oder die Datei ist."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() in (".op2proj", ".json"):
        return p
    if p.is_dir() and (p / "mission.op2proj").is_file():
        return p / "mission.op2proj"
    return None


def default_dll_basename(dll_name: str) -> str:
    """`cEditorMission.dll` -> `cEditorMission`. Faellt auf `cMission` zurueck."""
    name = (dll_name or "").strip()
    if not name:
        return "cMission"
    if name.lower().endswith(".dll"):
        name = name[:-4]
    return name or "cMission"
