"""Themen der Streugut-Stempel: Risse, Felsen, Krater, Wrackteile.

Das Kachelmodell kennt die Streugut-Stempel nur als Kachelblock mit Boden --
nicht, WAS sie darstellen. Fuer zusammengehoerige Streufelder (ein Kraterfeld,
eine Geroellhalde am Wandfuss, eine Bruchlinie) muss der Generator das aber
wissen. Die Zuordnung kommt aus den Gruppennamen der Originalkarten
(`mudcrk1` = Riss, `sanrok03` = Felsen, ...) und liegt in
`detail_themen.json` -- nur Kachelnummern und Namen, keine Grafik.

    python detail_themen.py <Spielordner>      # Tabelle neu erzeugen

Themes of the scatter stamps. The tile model knows the scatter stamps only as
tile blocks with a ground, not WHAT they show. For coherent scatter fields the
generator needs that; the assignment comes from the stock maps' group names and
lives in `detail_themen.json` (tile numbers and names only).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PFAD = Path(__file__).with_name("detail_themen.json")

RISSE, FELSEN, KRATER, WRACK = "risse", "felsen", "krater", "wrack"
THEMEN = (RISSE, FELSEN, KRATER, WRACK)

_MUSTER = ((r"wrk", WRACK), (r"cra?c|crk", RISSE), (r"crat", KRATER),
           (r"ro[ck]|rok", FELSEN))


def thema_aus_name(name: str) -> str:
    """Thema aus einem Gruppennamen wie `sancratx3` ablesen."""
    rest = name.lower()[3:]
    for muster, thema in _MUSTER:
        if re.search(muster, rest):
            return thema
    return FELSEN


_CACHE: dict | None = None


def tabelle() -> dict[tuple[int, ...], tuple[str, str]]:
    """Kachelblock (zeilenweise) -> (Name, Thema)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        try:
            for e in json.loads(PFAD.read_text("utf-8")):
                _CACHE[tuple(int(k) for k in e["kacheln"])] = (e["name"], e["thema"])
        except (OSError, ValueError, KeyError):
            pass
    return _CACHE


def thema(kacheln) -> str:
    """Thema eines Streugut-Stempels; unbekannte gelten als Felsen."""
    import numpy as np
    schl = tuple(int(k) for k in np.asarray(kacheln).ravel())
    return tabelle().get(schl, ("", FELSEN))[1]


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mapgen
    from op2map import Op2Map
    from op2res import FolderResources
    res = FolderResources(sys.argv[1])
    karte = Op2Map(res.read_file("cm02.map"))
    namen = {tuple(g.mapping_indices): g.name for g in karte.tile_groups}
    eintraege = []
    for kacheln, fam in mapgen.model().details:
        schl = tuple(int(k) for k in kacheln.ravel())
        name = namen.get(schl, "")
        eintraege.append({"name": name, "familie": fam,
                          "thema": thema_aus_name(name) if name else FELSEN,
                          "kacheln": list(schl)})
    PFAD.write_text(json.dumps(eintraege, indent=1), "utf-8")
    print(f"{len(eintraege)} Stempel -> {PFAD.name}")
