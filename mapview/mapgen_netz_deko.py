"""Krater, Risse und Truemmer fuer den gelernten Kartengenerator.

Die Stempel sind die Kachelgruppen des Spiels (`kachelgruppen.json`). Jeder liegt
nur auf seinem Boden und nur dort, wo seine Naht zu den Nachbarn passt.
Truemmer kommen in Gruppen, wie an einer Absturzstelle.

Craters, cracks and debris for the learned map generator. The stamps are the
game's tile groups; each lies only on its own ground and only where its seam
fits. Debris comes in groups, like at a crash site.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

import mapgen_netz_fels as felsen

HIER = Path(__file__).resolve().parent

# Art -> Muster der Gruppennamen. Kind -> pattern of the group names.
ARTEN = {"krater": r"(mudcrk|sancrat|sancratx)\d+$",
         "risse": r"roccrac\d+$",
         "truemmer": r"(mud|roc|san)(wrk|rub|burn)\d*$"}
# Stueck je 128x128 bei Regler 1 (Truemmer: Gruppen). Pieces per 128x128 at 1.
DICHTE = {"krater": 36, "risse": 16, "truemmer": 7}
BODEN = {"mud": felsen.SONST, "san": felsen.SONST, "roc": felsen.FELS}

_stempel: dict = {}


def stempel() -> dict:
    """Art -> [(Name, Familie, Kacheln)]."""
    if not _stempel:
        gruppen = json.loads((HIER / "kachelgruppen.json").read_text(encoding="utf-8"))
        for art, muster in ARTEN.items():
            _stempel[art] = [
                (n, n[:3], np.array(e["kacheln"], np.int64).reshape(e["hoehe"], e["breite"]))
                for n, e in gruppen.items() if re.match(muster, n)]
    return _stempel


def _setze(t, tm, block, fam, x, y, gesperrt, kachelart) -> bool:
    from mapgen_felder import _naht_passt
    bh, bw = block.shape
    if y < 1 or x < 1 or y + bh + 1 > t.shape[0] or x + bw + 1 > t.shape[1]:
        return False
    rahmen = (slice(y - 1, y + bh + 1), slice(x - 1, x + bw + 1))
    if gesperrt[rahmen].any():
        return False
    if fam == "roc":
        if not (kachelart[t[rahmen]] == felsen.FELS).all():
            return False
    elif not (tm.family_of[t[rahmen]] == tm.families.index(fam)).all():
        return False
    if not _naht_passt(t, tm, block, x, y):
        return False
    t[y:y + bh, x:x + bw] = block
    gesperrt[y:y + bh, x:x + bw] = True
    return True


def verzieren(t, tm, staerke: dict, gesperrt, rng) -> dict:
    """Stempel setzen -> Zahl je Art. `staerke`: Art -> 0..1.
    Place the stamps; returns the count per kind."""
    alle = stempel()
    art = felsen.kachelart()
    flaeche = t.size / (128 * 128)
    h, w = t.shape
    gezaehlt = {}
    for name, liste in alle.items():
        ziel = int(round(DICHTE[name] * float(staerke.get(name, 0)) * flaeche))
        n = 0
        for _ in range(ziel * 40):
            if n >= ziel or not liste:
                break
            if name == "truemmer":
                # Eine Absturzstelle: ein Mittelpunkt, Teile drumherum.
                # A crash site: a centre with pieces around it.
                cy, cx = int(rng.integers(8, h - 8)), int(rng.integers(8, w - 8))
                fam = tm.families[int(tm.family_of[t[cy, cx]])] \
                    if tm.family_of[t[cy, cx]] >= 0 else ""
                teile = [s for s in liste if s[1] == fam]
                if not teile:
                    continue
                gesetzt = 0
                for _k in range(int(rng.integers(4, 9)) * 6):
                    _nm, f, block = teile[int(rng.integers(len(teile)))]
                    y = cy + int(rng.normal(0, 3.5)) - block.shape[0] // 2
                    x = cx + int(rng.normal(0, 3.5)) - block.shape[1] // 2
                    gesetzt += _setze(t, tm, block, f, x, y, gesperrt, art)
                    if gesperrt[cy - 6:cy + 7, cx - 6:cx + 7].mean() > .35:
                        break
                n += gesetzt >= 2
            else:
                _nm, f, block = liste[int(rng.integers(len(liste)))]
                y = int(rng.integers(1, h - block.shape[0] - 1))
                x = int(rng.integers(1, w - block.shape[1] - 1))
                n += _setze(t, tm, block, f, x, y, gesperrt, art)
        gezaehlt[name] = n
    return gezaehlt
