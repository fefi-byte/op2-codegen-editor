"""Dunkler Lavafels als eigene Bodenart "lav".

In den Originalkarten bildet der dunkle Lavafels eigene Flaechen und grenzt
fast nur an die lav-roc-Uebergangskacheln (16.749 Mal, an hellen Fels direkt
nur 1.379 Mal, an Erde 312 Mal). Das Kachelmodell fuehrte ihn als Teil von
"roc" -- der Generator setzte ihn deshalb nie, und umgefaerbt zeigte er harte
Kachelkanten. Als eigene Familie bekommt er genau den Rand, den die
Entwickler benutzt haben: dunkler Kern, lav-roc-Uebergang, heller Fels.

Die Randkacheln je Richtung (wie bei den anderen Bodenpaaren) kommen aus den
Originalkarten und liegen in `lavafels_rand.json`.

    python lavafels.py <Spielordner>      # Randtabelle neu lernen

Dark lava rock as its own ground "lav", bordered by the lav-roc transition
tiles exactly as in the stock maps.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

PFAD = Path(__file__).with_name("lavafels_rand.json")


def dunkle_kacheln(tm) -> list[int]:
    import celltypes as ct
    if "roc" not in tm.families:
        return []
    roc = tm.families.index("roc")
    return [i for i in range(min(2017, len(tm.family_of)))
            if tm.family_of[i] == roc
            and ct.default_cell_type(i, fallback=-1) == ct.SLOW_PASSIBLE_1]


def einrichten(tm) -> None:
    """Modell umstellen: dunkle Kacheln -> Familie lav, Randtabelle lav|roc."""
    if "lav" not in tm.families or ("lav", "roc") not in tm.trans:
        return
    try:
        rand = json.loads(PFAD.read_text("utf-8"))
    except (OSError, ValueError):
        return
    lav = tm.families.index("lav")
    for t in dunkle_kacheln(tm):
        tm.family_of[t] = lav
        if getattr(tm, "muster", None) is not None:
            tm.muster[t][:] = lav
    tm.rand[("lav", "roc")] = {
        int(r): (np.array([k for k, _ in e], dtype=np.int32),
                 np.array([n for _, n in e], dtype=float))
        for r, e in rand.items()}
    tm._build_family_pools()
    tm._nachbar_cache.clear()
    tm._abstand_cache.clear()
    for attr in ("_nutzbar", "_paar_satz"):
        if hasattr(tm, attr):
            delattr(tm, attr)
    if hasattr(tm, "_baue_nachfolger"):
        tm._baue_nachfolger()


if __name__ == "__main__":
    import sys
    from collections import Counter, defaultdict
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mapgen_modell
    from learn_tiles import grenz_richtung
    from op2map import Op2Map
    tm = mapgen_modell.TileModel(lavafels=False)   # ohne Umstellung lernen
    dunkel = set(dunkle_kacheln(tm))
    lavaseite = list(dunkel | {i for i in range(2017) if tm.lava[i]})
    uebergang = list({t for t, _ in tm.trans[("lav", "roc")]})
    tab: dict = defaultdict(Counter)
    for p in sorted(Path(sys.argv[1]).rglob("*.map")):
        if "backups" in str(p).lower():
            continue
        m = Op2Map(p.read_bytes())
        g = np.array([[m.tile_mapping_index(x, y) for x in range(m.width)]
                      for y in range(m.height)])
        ist = np.isin(g, lavaseite)
        ys, xs = np.nonzero(np.isin(g, uebergang))
        for y, x in zip(ys.tolist(), xs.tolist()):
            if 3 <= y < g.shape[0] - 3 and 3 <= x < g.shape[1] - 3:
                r = grenz_richtung(ist, y, x)
                if r is not None:
                    tab[r][int(g[y, x])] += 1
    PFAD.write_text(json.dumps({str(r): c.most_common(16) for r, c in tab.items()}), "utf-8")
    print({r: sum(c.values()) for r, c in sorted(tab.items())})
