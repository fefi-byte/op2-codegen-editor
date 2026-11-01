"""Benannte Kachelgruppen der Originalkarten (mudrock1, sandoz2, rocburn ...).

Der Generator kennt sonst nur Kachelnummern. Fuer die Chronik braucht er
bestimmte Bauteile beim Namen: planierte Flaechen, Schutt, Brandspuren,
Wrackteile, Krater. Die Gruppen stehen in jeder Originalkarte gleich; hier
liegen sie als `kachelgruppen.json` -- nur Namen, Groesse und Kachelnummern.

    python kachelgruppen.py <Spielordner>      # Tabelle neu erzeugen

Named tile groups of the stock maps. The chronicle needs certain building
blocks by name; the table holds names, size and tile numbers only.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

PFAD = Path(__file__).with_name("kachelgruppen.json")
_CACHE: dict | None = None


def alle() -> dict[str, np.ndarray]:
    """Name -> Kachelblock (h, w)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        try:
            for name, e in json.loads(PFAD.read_text("utf-8")).items():
                _CACHE[name] = np.asarray(e["kacheln"], dtype=np.int32).reshape(
                    e["hoehe"], e["breite"])
        except (OSError, ValueError, KeyError):
            pass
    return _CACHE


def gruppe(name: str) -> np.ndarray | None:
    return alle().get(name)


def mit_praefix(praefix: str) -> list[tuple[str, np.ndarray]]:
    return [(n, t) for n, t in sorted(alle().items()) if n.lower().startswith(praefix)]


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from op2map import Op2Map
    from op2res import FolderResources
    res = FolderResources(sys.argv[1])
    karte = Op2Map(res.read_file("cm02.map"))
    daten = {g.name: {"breite": g.width, "hoehe": g.height,
                      "kacheln": [int(k) for k in g.mapping_indices]}
             for g in karte.tile_groups if g.width * g.height > 0}
    PFAD.write_text(json.dumps(daten), "utf-8")
    print(f"{len(daten)} Gruppen -> {PFAD.name}")
