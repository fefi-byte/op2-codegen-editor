"""Die Klippenkante entlanglaufen und die Kachelfolge lernen
-> `cliff_walk_model.npz`.

Aufruf:  python mapview/learn_cliff_walk.py

Nicht Bloecke stapeln, sondern der Kante folgen. In `cm04` bei (167,175) zeigt
die Klippe ein Gebirge, und entlang seiner Oberkante wiederholt sich eine
Kachelfolge:

    x=163  94    x=170  94    x=177  94
    x=164  95    x=171  95    x=178  95
    x=165  94    x=172  94    x=179  94
    x=166  95    x=173  95    x=180  95
    x=167 160    x=174 160    x=181 160
    x=168 161    x=175 161
    x=169 162    x=176 162

`94, 95` ist der Schritt, `160, 161, 162` das flache Stueck. Gelernt wird genau
das: welche Kachel folgt auf welche, gegeben den senkrechten Versatz zur
naechsten Spalte -- und dieser Versatz ist der oertliche Winkel der Wand.

--- Warum die Folge und nicht der Winkel -----------------------------------

Der Winkel allein sagt fast nichts. Gemessen ueber 712 Kantenlaeufe aus allen
54 Karten, "wie oft trifft die haeufigste Kachel":

    nichts (Grundrate)                       6,3 %
    nur der Sprung (also der Winkel)        10,9 %
    Trittlaenge + Stelle im Tritt + Sprung  25,9 %
    vorige Kachel                           58,4 %
    vorige Kachel + beide Spruenge          69,2 %
    ZWEI vorige Kacheln + Sprung            72,9 %

Die Geometrie ist schwach, die FOLGE ist stark. Und in 72 % der Faelle steht
die Kachel sogar fest -- dort kam ueber alle 54 Karten nie eine andere vor.

--- Ehrlich geprueft --------------------------------------------------------

Tabelle aus 40 Karten, geprueft auf den uebrigen 11 -- sonst misst man das
Auswendiglernen:

    Kante   Platz 1   erste zwei   Zusammenhang unbekannt
      N      62,1 %     72,8 %            8,3 %
      O      62,4 %     69,6 %            8,8 %
      S      60,1 %     72,5 %            6,7 %
      W      65,2 %     74,9 %            9,9 %

Alle vier Kanten tragen gleich gut. Gegen die Grundrate von 6,3 % ist das der
mit Abstand schaerfste Zusammenhang, der in diesem Projekt gemessen wurde --
und er haengt weder am Blockvorrat (18 Stueck je Familie) noch an der
Belegdichte der Paartabelle (3,17 % der moeglichen Paare).

Gespeichert werden Ordnung 2 UND Ordnung 1, damit der Setzer zurueckfallen
kann, wenn ein Zusammenhang fehlt.

--- Walking the cliff edge --------------------------------------------------

Rather than stacking blocks, follow the edge. Learned is which tile follows
which, given the vertical offset to the next column -- that offset is the local
angle. The angle alone predicts almost nothing (10,9 %); the sequence predicts
62 % on unseen maps against a 6,3 % base rate. Orders 2 and 1 are both stored so
a placer can back off.
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

GAME_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
OUT_PATH = HERE / "cliff_walk_model.npz"

KLIPPE = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
          celltypes.CLIFFS_LOW_SIDE)

# Teil des Dateiformats: 0 = N, 1 = O, 2 = S, 3 = W.
KANTEN = ("N", "O", "S", "W")

# Groesster Versatz, der einen Kantenlauf noch zusammenhaelt. Zwei ist die
# gemessene Obergrenze der Sprunghoehe in den Originalen (75,5 % einzeilig,
# 24,5 % zweizeilig, drei Zeilen nie).
SPRUNG_GRENZE = 2

# Kuerzester Lauf, der gezaehlt wird. Kuerzere sind Wandenden und Ecken, keine
# Kante mit Verlauf.
MIN_LAUF = 4


def kantenlaeufe(idx: np.ndarray, ist: np.ndarray, kante: str):
    """Ein Kantenzug -> [[(kachel, sprung_zur_naechsten), ...], ...].

    N und S laufen in x-Richtung und nehmen je Spalte die oberste bzw.
    unterste Klippenzelle; W und O laufen in y-Richtung. Der Sprung ist der
    Versatz der Kante zur naechsten Stelle -- er IST der oertliche Winkel.
    """
    if kante in ("W", "O"):
        idx, ist = idx.T, ist.T
    h, w = idx.shape
    erste = kante in ("N", "W")
    lage = {}
    for x in range(w):
        ys = np.nonzero(ist[:, x])[0]
        if len(ys):
            lage[x] = int(ys[0] if erste else ys[-1])
    aus = []
    x = 0
    while x < w:
        if x not in lage:
            x += 1
            continue
        lauf = [x]
        while x + 1 in lage and abs(lage[x + 1] - lage[x]) <= SPRUNG_GRENZE:
            x += 1
            lauf.append(x)
        x += 1
        if len(lauf) < MIN_LAUF:
            continue
        aus.append([(int(idx[lage[xx], xx]),
                     0 if i + 1 >= len(lauf)
                     else lage[lauf[i + 1]] - lage[xx])
                    for i, xx in enumerate(lauf)])
    return aus


def lerne(game_dir: Path = GAME_DIR) -> dict:
    vol = VolFile(str(game_dir / "maps.vol"))
    namen = [n for n in vol.names() if n.endswith(".map")]
    if not namen:
        raise SystemExit("keine Karten in maps.vol")

    zwei: Counter = Counter()      # (kante, a, b, sprung_b) -> naechste
    eins: Counter = Counter()      # (kante, b, sprung_b) -> naechste
    anfang: Counter = Counter()    # (kante, sprung) -> erste Kachel
    karten = laeufe = 0
    for name in namen:
        try:
            m = Op2Map(vol.read_file(name))
        except Exception:                            # noqa: BLE001
            continue
        h, w = m.height, m.width
        idx = np.array([[m.tile_mapping_index(x, y) for x in range(w)]
                        for y in range(h)], dtype=np.int32)
        ist = np.isin(np.array([[m.cell_type(x, y) for x in range(w)]
                                for y in range(h)]), KLIPPE)
        if not ist.any():
            continue
        for ki, kante in enumerate(KANTEN):
            for f in kantenlaeufe(idx, ist, kante):
                laeufe += 1
                anfang[(ki, f[0][1], f[0][0])] += 1
                for i in range(1, len(f)):
                    eins[(ki, f[i-1][0], f[i-1][1], f[i][0])] += 1
                    if i >= 2:
                        zwei[(ki, f[i-2][0], f[i-1][0], f[i-1][1],
                              f[i][0])] += 1
        karten += 1

    import mapgen
    tm = mapgen.model()

    def feld(z: Counter, spalten: int):
        if not z:
            return np.zeros((0, spalten), dtype=np.int32), \
                np.zeros(0, dtype=np.int64)
        schl = np.array(list(z.keys()), dtype=np.int32)
        return schl, np.array(list(z.values()), dtype=np.int64)

    z_schl, z_anz = feld(zwei, 5)
    e_schl, e_anz = feld(eins, 4)
    a_schl, a_anz = feld(anfang, 3)
    return {
        "zwei_schluessel": z_schl, "zwei_anzahl": z_anz,
        "eins_schluessel": e_schl, "eins_anzahl": e_anz,
        "anfang_schluessel": a_schl, "anfang_anzahl": a_anz,
        "kanten": np.array(KANTEN, dtype="U2"),
        "familie": np.array([int(tm.family_of[t]) if t < len(tm.family_of)
                             else -1 for t in range(2048)], dtype=np.int16),
        "familien_namen": np.array(tm.families, dtype="U8"),
        "karten": np.int32(karten),
        "laeufe": np.int32(laeufe),
        "sprung_grenze": np.int32(SPRUNG_GRENZE),
    }


def main() -> None:
    modell = lerne()
    np.savez_compressed(OUT_PATH, **modell)
    print(f"{int(modell['karten'])} Karten, {int(modell['laeufe'])} "
          f"Kantenlaeufe")
    print(f"Ordnung 2: {len(modell['zwei_anzahl'])} Zusammenhaenge aus "
          f"{int(modell['zwei_anzahl'].sum())} Vorkommen")
    print(f"Ordnung 1: {len(modell['eins_anzahl'])} Zusammenhaenge aus "
          f"{int(modell['eins_anzahl'].sum())} Vorkommen")
    print(f"Anfaenge : {len(modell['anfang_anzahl'])}")

    # Wie eindeutig ist Ordnung 2?
    nach: dict = defaultdict(list)
    for s, n in zip(modell["zwei_schluessel"], modell["zwei_anzahl"]):
        nach[tuple(int(v) for v in s[:4])].append(int(n))
    eindeutig = sum(1 for v in nach.values() if len(v) == 1)
    print(f"   davon eindeutig: {eindeutig} von {len(nach)} "
          f"({100*eindeutig/len(nach):.0f} %)")
    for ki, kante in enumerate(KANTEN):
        n = sum(int(v) for s, v in zip(modell["zwei_schluessel"],
                                       modell["zwei_anzahl"]) if s[0] == ki)
        print(f"   Kante {kante}: {n} Vorkommen")
    print(f"\n[ok] {OUT_PATH}")


if __name__ == "__main__":
    main()
