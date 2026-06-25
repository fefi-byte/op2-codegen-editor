"""Mission-Ordner: jede Mission ist ein eigener self-contained Ordner.

Inhalt:
  - mission.op2proj   (Editor-Projektdatei, JSON)
  - LevelMain.cpp     (generiert)
  - DllMain.cpp       (1:1 aus Template)
  - <name>.map        (Karte-Kopie)
  - MULTITEK.TXT      (optional, falls Mission custom tech tree nutzt)
  - OP2Script.vcxproj, OP2Script.sln  (VS-Projekt, Pfade relativ zum LevelTemplate-Submodul)
  - build.bat, README.md

Ziel: jeder kann mit `git clone --recursive` + `build.bat` die Mission
kompilieren, ohne den Editor zu brauchen.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

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
    dll_basename: str = "ctest",
) -> dict[str, Path]:
    """Schreibt eine vollstaendige Mission in den Ordner.

    Gibt ein Dict mit den geschriebenen Pfaden zurueck (fuer Status-Anzeigen).
    """
    folder.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    # 1) Editor-Projektdatei
    proj_path = folder / "mission.op2proj"
    proj_path.write_text(json.dumps(project_data, indent=2), encoding="utf-8")
    written["project"] = proj_path

    # 2) LevelMain.cpp (generiert)
    lm = folder / "LevelMain.cpp"
    lm.write_text(level_main_cpp, encoding="utf-8")
    written["levelmain"] = lm

    # 3) DllMain.cpp (aus Template, 1:1)
    dll = folder / "DllMain.cpp"
    _copy_template("DllMain.cpp", dll)
    written["dllmain"] = dll

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

    # 6) Visual-Studio-Projekt + Solution
    namespace = _slugify(mission_name)
    guid = _project_guid_from_folder(folder)
    repl = {
        "__PROJECT_GUID__": guid,
        "__MISSION_NAMESPACE__": namespace,
        "__MISSION_NAME__": mission_name,
        "__DLL_BASENAME__": dll_basename,
        "__MAP_FILENAME__": map_name or "(none)",
    }
    _copy_template("OP2Script.vcxproj.template", folder / "OP2Script.vcxproj", repl)
    _copy_template("OP2Script.sln.template", folder / "OP2Script.sln", repl)
    written["vcxproj"] = folder / "OP2Script.vcxproj"
    written["sln"] = folder / "OP2Script.sln"

    # 7) build.bat + README
    _copy_template("build.bat.template", folder / "build.bat", repl)
    _copy_template("README.md.template", folder / "README.md", repl)
    written["build_bat"] = folder / "build.bat"
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
    """`cEditorMission.dll` -> `cEditorMission`. Faellt auf `ctest` zurueck."""
    name = (dll_name or "").strip()
    if not name:
        return "ctest"
    if name.lower().endswith(".dll"):
        name = name[:-4]
    return name or "ctest"
