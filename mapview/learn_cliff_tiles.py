"""Nachbarschaft je Kachel und Richtung auszaehlen -> `cliff_tiles_model.npz`.

Aufruf:  python mapview/learn_cliff_tiles.py

Keine Gruppen, keine Baender, keine Statistik ueber Formen: die rohe Liste.
Fuer jede Klippenkachel und jede der vier Richtungen wird ausgezaehlt, welche
Kachel dort in den Originalkarten tatsaechlich steht -- und ob dort ueberhaupt
Boden stehen darf.

    an Kachel 88 darf nach Osten die 89 (94 %), die 122 (1 %), ... und NIE Boden
    an Kachel 89 darf nach Westen die 88 (77 %), die 234 (13 %), ... und nie Boden
    an Kachel 89 darf nach Norden fast alles, denn dort liegt offenes Gelaende

Richtungen sind N = y-1, O = x+1, S = y+1, W = x-1.

--- Warum das ueberhaupt geht -----------------------------------------------

**Es sind nur 307 Kacheln.** Ueber alle 54 Stockkarten kommen genau 307
verschiedene Kacheln als Klippe vor, bei 121603 Vorkommen. Das ist ein Vorrat,
den man vollstaendig auszaehlen kann.

**Die Liste ist satt.** 11934 verschiedene (Richtung, a, b) mit b als Klippe.
Von 20 auf 54 Karten waechst sie nur um den Faktor 1,60, und die letzten VIER
Karten brachten noch 68 neue Paare -- 0,6 %. Es kommt nichts Wesentliches mehr.

**Und sie ist scharf, wo es darauf ankommt:**

    Richtung   erlaubte Klippennachbarn      davon fuer 95 % der Faelle
       N           Median  7                       Median 4
       O           Median  9                       Median 5
       S           Median  8                       Median 4
       W           Median  9                       Median 5

Zaehlt man Boden mit, sieht dieselbe Tabelle unscharf aus (Median 11 bis 16).
Das ist kein Widerspruch, sondern der Punkt: wo eine Klippenkachel an offenes
Gelaende grenzt, darf dort jede Bodenkachel stehen. Deshalb werden die beiden
Faelle getrennt gefuehrt -- Klippennachbar und "Boden erlaubt" sind zwei
verschiedene Aussagen.

**Verbote gibt es wirklich.** Nach Norden haben 27 Kacheln nie eine Klippe
daneben, nach Sueden 37. Und 186 Kacheln haben nach Norden nie Boden.

--- Gezaehlt, nicht geschaetzt ----------------------------------------------

Gespeichert werden Anzahlen, keine Ja/Nein-Marken. Die harte Bedingung ist
"Anzahl > 0", alles Weitere ist Gewicht -- eine Vorliebe gehoert nicht in einen
Filter, sonst sortiert sie irgendwann das Richtige aus.

--- Counting tile adjacency -------------------------------------------------

For every cliff tile and each of the four directions, count which tile actually
stands there across the 54 stock maps, and whether ground may stand there at
all. Only 307 tiles occur as cliff, and the pair list is saturated: the last
four maps added 68 of 11934 pairs. Cliff neighbours and "ground allowed" are
kept apart, because where a cliff meets open terrain any ground tile may sit
there and the list would otherwise look unconstrained.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import celltypes                                   # noqa: E402
from op2map import Op2Map                          # noqa: E402
from vol import VolFile                            # noqa: E402

from spielpfad import spielordner  # noqa: E402
GAME_DIR = spielordner()
OUT_PATH = HERE / "cliff_tiles_model.npz"

KLIPPE = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
          celltypes.CLIFFS_LOW_SIDE)

# Reihenfolge ist Teil des Dateiformats:
#   0..3  N, O, S, W   -- die geraden Nachbarn, harte Bedingung
#   4..7  NO, SO, SW, NW -- die Diagonalen, nur Gewicht
#
# Warum die Diagonalen nicht auch hart gelten, ist gemessen. Tabelle aus 40
# Karten, geprueft auf den 14 ungesehenen:
#
#                            richtige Kachel   Widerspruch,
#                            auf Platz 1       gar nichts passt
#   nur die vier geraden        87,0 %            0,70 %
#   acht, alle hart             90,6 %            2,37 %
#   vier hart + vier Gewicht    88,8 %            0,70 %
#
# Hart gerechnet schaerfen die Diagonalen zwar, aber der Setzer verbaut sich
# dreimal so oft selbst -- und vor einer Zelle zu stehen, in die nichts passt,
# kostet mehr als ein zweitbester Treffer.
# Diagonals as weight, not constraint: taken as hard rules they sharpen the
# guess but triple the dead ends.
RICHTUNGEN = (("N", 0, -1), ("O", 1, 0), ("S", 0, 1), ("W", -1, 0),
              ("NO", 1, -1), ("SO", 1, 1), ("SW", -1, 1), ("NW", -1, -1))
GERADE = 4                      # die ersten vier sind die harte Bedingung


def lerne(game_dir: Path = GAME_DIR) -> dict:
    vol = VolFile(str(game_dir / "maps.vol"))
    namen = [n for n in vol.names() if n.endswith(".map")]
    if not namen:
        raise SystemExit("keine Karten in maps.vol")

    vorkommen: Counter = Counter()
    zelltyp: Counter = Counter()          # (kachel, zelltyp) -> Vorkommen
    # (richtung, a, b) -> Anzahl, b immer Klippe
    paar: Counter = Counter()
    boden: Counter = Counter()            # (richtung, a) -> Anzahl
    rand: Counter = Counter()             # (richtung, a) -> Kartenrand
    karten = 0
    for name in namen:
        try:
            m = Op2Map(vol.read_file(name))
        except Exception:                            # noqa: BLE001
            continue
        h, w = m.height, m.width
        idx = np.array([[m.tile_mapping_index(x, y) for x in range(w)]
                        for y in range(h)])
        zt = np.array([[m.cell_type(x, y) for x in range(w)]
                       for y in range(h)])
        ist = np.isin(zt, KLIPPE)
        for y in range(h):
            for x in range(w):
                if not ist[y, x]:
                    continue
                a = int(idx[y, x])
                vorkommen[a] += 1
                zelltyp[(a, int(zt[y, x]))] += 1
                for r, (_nm, dx, dy) in enumerate(RICHTUNGEN):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        rand[(r, a)] += 1
                        continue
                    if ist[ny, nx]:
                        paar[(r, a, int(idx[ny, nx]))] += 1
                    else:
                        boden[(r, a)] += 1
        karten += 1

    kacheln = sorted(vorkommen, key=lambda t: -vorkommen[t])
    platz = {t: i for i, t in enumerate(kacheln)}

    import mapgen
    tm = mapgen.model()

    # Haeufigster Zelltyp je Kachel -- eine Kachel wird fast immer mit
    # demselben Typ gesetzt, aber "fast" ist nicht "immer".
    haupttyp = {}
    streit = 0
    for t in kacheln:
        z = Counter({ct: n for (tt, ct), n in zelltyp.items() if tt == t})
        haupttyp[t] = z.most_common(1)[0][0]
        if len(z) > 1 and z.most_common(2)[1][1] > 0.05 * sum(z.values()):
            streit += 1

    n = len(kacheln)
    boden_feld = np.zeros((n, len(RICHTUNGEN)), dtype=np.int64)
    rand_feld = np.zeros((n, len(RICHTUNGEN)), dtype=np.int64)
    for (r, a), v in boden.items():
        boden_feld[platz[a], r] = v
    for (r, a), v in rand.items():
        rand_feld[platz[a], r] = v

    return {
        "kacheln": np.array(kacheln, dtype=np.int32),
        "vorkommen": np.array([vorkommen[t] for t in kacheln], dtype=np.int64),
        "zelltyp": np.array([haupttyp[t] for t in kacheln], dtype=np.int32),
        "familie": np.array([int(tm.family_of[t]) if t < len(tm.family_of)
                             else -1 for t in kacheln], dtype=np.int16),
        "familien_namen": np.array(tm.families, dtype="U8"),
        "nb_richtung": np.array([r for r, _a, _b in paar], dtype=np.int8),
        "nb_a": np.array([platz[a] for _r, a, _b in paar], dtype=np.int32),
        "nb_b": np.array([platz[b] for _r, _a, b in paar], dtype=np.int32),
        "nb_anzahl": np.array(list(paar.values()), dtype=np.int64),
        "boden": boden_feld,
        "kartenrand": rand_feld,
        "karten": np.int32(karten),
        "typstreit": np.int32(streit),
        "gerade": np.int32(GERADE),
    }


def main() -> None:
    modell = lerne()
    np.savez_compressed(OUT_PATH, **modell)
    n = len(modell["kacheln"])
    print(f"{int(modell['karten'])} Karten, {n} Klippenkacheln aus "
          f"{int(modell['vorkommen'].sum())} Vorkommen")
    print(f"{len(modell['nb_a'])} Paare (Richtung, a, b), "
          f"{int(modell['nb_anzahl'].sum())} Vorkommen")
    if int(modell["typstreit"]):
        print(f"   {int(modell['typstreit'])} Kacheln kommen mit mehr als "
              f"einem Zelltyp vor")

    nr = len(RICHTUNGEN)
    je = {r: defaultdict(int) for r in range(nr)}
    fuer95 = {r: [] for r in range(nr)}
    weite = {r: defaultdict(Counter) for r in range(nr)}
    for r, a, _b, c in zip(modell["nb_richtung"], modell["nb_a"],
                           modell["nb_b"], modell["nb_anzahl"]):
        je[int(r)][int(a)] += 1
        weite[int(r)][int(a)][int(_b)] = int(c)
    for r in range(nr):
        for a, z in weite[r].items():
            ges = sum(z.values())
            s = k = 0
            for v in sorted(z.values(), reverse=True):
                s += v
                k += 1
                if s >= 0.95 * ges:
                    break
            fuer95[r].append(k)

    print(f"\n{'Ri':>3s} {'Kacheln':>8s} {'Nachbarn Median':>16s}"
          f" {'fuer 95 %':>10s} {'nie Klippe':>11s} {'nie Boden':>10s}")
    for r, (nm, _dx, _dy) in enumerate(RICHTUNGEN):
        werte = np.array(list(je[r].values()))
        nie_klippe = n - len(je[r])
        nie_boden = int((modell["boden"][:, r] == 0).sum())
        marke = "" if r < GERADE else "   (nur Gewicht)"
        print(f"{nm:>3s} {len(je[r]):8d} {np.median(werte):16.0f}"
              f" {np.median(fuer95[r]):10.0f} {nie_klippe:11d}"
              f" {nie_boden:10d}{marke}")
    print(f"\n[ok] {OUT_PATH}")


if __name__ == "__main__":
    main()
