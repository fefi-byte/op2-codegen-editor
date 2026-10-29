"""Wo liegt Outpost 2? -- einmal fuer alle Werkzeuge in `mapview`.

Reihenfolge: Umgebungsvariable `OP2_GAME`, dann `game_path` aus der
`config.ini` des Editors (`codegen/appconfig.py`), dann die GOG-Standard-
installation. Frueher stand der GOG-Pfad fest in Tests und Lernskripten --
auf jedem anderen Rechner war die Suite dadurch dauerhaft rot.

Where Outpost 2 lives, for every tool in `mapview`: env var `OP2_GAME`, then
the editor's config.ini, then the GOG default.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

GOG = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
_WURZEL = Path(__file__).resolve().parent.parent


def spielordner() -> Path:
    kandidaten = []
    if os.environ.get("OP2_GAME"):
        kandidaten.append(Path(os.environ["OP2_GAME"]))
    try:
        sys.path.insert(0, str(_WURZEL / "codegen"))
        import appconfig
        p = str(appconfig.game_path())
        if p and p != ".":
            kandidaten.append(Path(p))
    except Exception as e:                       # config fehlt/kaputt
        print(f"spielpfad: config.ini nicht lesbar ({e})", file=sys.stderr)
    kandidaten.append(GOG)
    for k in kandidaten:
        if (k / "maps.vol").exists() or (k / "OPU").exists():
            return k
    return kandidaten[0]


def karte_lesen(name: str) -> bytes | None:
    """Eine Originalkarte als Bytes -- lose Datei oder aus `maps.vol`."""
    ordner = spielordner()
    lose = next(ordner.rglob(name), None) if ordner.exists() else None
    if lose is not None:
        return lose.read_bytes()
    vol = ordner / "maps.vol"
    if vol.exists():
        from vol import VolFile
        try:
            return VolFile(str(vol)).read_file(name)
        except Exception:
            return None
    return None
