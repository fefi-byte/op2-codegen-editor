"""Eigene Klippengruppen aus den Originalkarten schuerfen -> `cliff_patches_model.npz`.

Aufruf:  python mapview/learn_cliff_patches.py

Die 35 mitgelieferten `*mes*`-TileGroups kennen den diagonalen Lauf nicht -- ein
schraeg durchlaufendes Wandstueck mit seinen Uebergaengen gibt es dort als
Ganzes nicht. In den Karten gibt es es sehr wohl: als 6x4-Block kommt so ein
Lauf bis zu 272 mal vor. Also holt man sich die Gruppen aus den Karten statt
aus dem Kachelsatz.

Jedes NxM-Fenster ueber einer Klippe ist ein Kandidat. Der Boden wird dabei zur
WILDCARD -- sonst zaehlt jede Bodenvariante als eigene Gruppe und der Vorrat
zerfaellt in Einzelfaelle. Eine Gruppe beschreibt die Klippe, nicht das Gelaende
daneben.

--- Warum mehrere Groessen --------------------------------------------------

Streng gemessen -- ueberlappungsfrei gekachelt, nur Gruppen ab 10 Vorkommen --
deckt eine Groesse allein nie genug:

    Groesse   Gruppen ab 10x   deckt streng   davon gebraucht
      2x2          2187           71,0 %           1164
      3x3          3542           49,5 %           1343
      4x3          4015           43,0 %           1411
      6x4          4348           27,8 %           1098
      6x6          4210           20,4 %            947

Grosse Gruppen tragen den Lauf, decken aber wenig; kleine decken viel, tragen
aber keine Richtung. Darum werden mehrere Groessen geschuerft und der Setzer
nimmt die groesste, die passt.

--- Was eine Gruppe passend macht -------------------------------------------

Die FORM ist die harte Bedingung: eine Gruppe darf nur dort liegen, wo genau die
Zellen Klippe sind, die in ihr Klippe sind. Wo die Form stimmt, kommen die
Kacheln mit. Das ist der ganze Zweck -- die Nachbarschaftstabelle
(`cliff_tiles.py`) sieht immer nur eine Kachel weit und verliert an langen
Laeufen die Richtung; eine Gruppe traegt den Lauf als Ganzes.

--- Mining our own cliff groups ---------------------------------------------

The stock TileGroups have no diagonal run; the maps do. Every NxM window over a
cliff is a candidate, with ground as a WILDCARD so that ground variation does
not shatter the vocabulary. Several sizes are mined because no single size
covers enough: large ones carry the run but cover little, small ones cover much
but carry no direction. A group may be placed only where exactly those cells are
cliff that are cliff in it -- the shape is the constraint, the tiles come along.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import celltypes                                   # noqa: E402
from op2map import Op2Map                          # noqa: E402
from vol import VolFile                            # noqa: E402

GAME_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
OUT_PATH = HERE / "cliff_patches_model.npz"

KLIPPE = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
          celltypes.CLIFFS_LOW_SIDE)

# (Breite, Hoehe), von gross nach klein -- der Setzer probiert in dieser Folge.
# Hoch und breit sind beide dabei: eine Nord-Sued-Wand braucht ein hohes
# Fenster, eine Ost-West-Wand ein breites.
GROESSEN = ((6, 4), (4, 6), (4, 3), (3, 4), (3, 3), (2, 2))

# Weniger Vorkommen als das ist kein Muster, sondern eine Stelle in einer Karte.
# Bei 10 bleiben je Groesse zwischen 2000 und 4400 Gruppen uebrig.
MINDEST = 10

WILDCARD = -1        # dort liegt Gelaende
RAND = -2            # Auffuellung, weil die Groessen verschieden sind


def _karte_lesen(m: Op2Map):
    """-> (Kachelnummern, Zelltypen), Gelaende jeweils als WILDCARD.

    Der Zelltyp muss mitgeschuerft werden, weil er NICHT in der Kachel steht:
    171 der 307 Klippenkacheln kommen sowohl als CLIFFS_HIGH_SIDE als auch als
    CLIFFS_LOW_SIDE vor, und das sind 73,9 % aller Vorkommen. Nur 20,2 % der
    Zellen haben eine Kachel, die ihren Typ eindeutig festlegt. Eine Gruppe
    dagegen ist aus einer echten Karte geschnitten und bringt ihn mit.
    Cell types must be mined too: a tile does not know whether it faces the
    high or the low side, but a group cut from a real map does.
    """
    h, w = m.height, m.width
    idx = np.array([[m.tile_mapping_index(x, y) for x in range(w)]
                    for y in range(h)], dtype=np.int32)
    zt = np.array([[m.cell_type(x, y) for x in range(w)]
                   for y in range(h)], dtype=np.int32)
    ist = np.isin(zt, KLIPPE)
    return (np.where(ist, idx, WILDCARD).astype(np.int32),
            np.where(ist, zt, WILDCARD).astype(np.int32))


def lerne(game_dir: Path = GAME_DIR) -> dict:
    vol = VolFile(str(game_dir / "maps.vol"))
    namen = [n for n in vol.names() if n.endswith(".map")]
    if not namen:
        raise SystemExit("keine Karten in maps.vol")

    felder = []
    for name in namen:
        try:
            felder.append(_karte_lesen(Op2Map(vol.read_file(name))))
        except Exception:                            # noqa: BLE001
            continue
    if not felder:
        raise SystemExit("keine Karte lesbar")

    import mapgen
    tm = mapgen.model()

    def familie_der(bloc: np.ndarray) -> int:
        f = {int(tm.family_of[t]) for t in bloc.flat
             if 0 <= t < len(tm.family_of) and tm.family_of[t] >= 0}
        return f.pop() if len(f) == 1 else -1        # gemischt: -1

    gruppen, typen, anzahlen, groessen, familien = [], [], [], [], []
    for bw, bh in GROESSEN:
        zaehl: dict = {}
        typ_zaehl: dict = {}          # Gruppe -> {Zelltypmuster: Vorkommen}
        for feld, ztfeld in felder:
            h, w = feld.shape
            if h < bh or w < bw:
                continue
            f = np.lib.stride_tricks.sliding_window_view(
                feld, (bh, bw)).reshape(-1, bh * bw)
            z = np.lib.stride_tricks.sliding_window_view(
                ztfeld, (bh, bw)).reshape(-1, bh * bw)
            hat = (f >= 0).any(axis=1)
            f, z = f[hat], z[hat]
            if not len(f):
                continue
            for zeile, ztz in zip(f, z):
                s = zeile.tobytes()
                zaehl[s] = zaehl.get(s, 0) + 1
                tz = typ_zaehl.setdefault(s, {})
                st = ztz.tobytes()
                tz[st] = tz.get(st, 0) + 1
        for s, n in zaehl.items():
            if n < MINDEST:
                continue
            bloc = np.frombuffer(s, dtype=np.int32).reshape(bh, bw)
            # Dieselben Kacheln koennen verschiedene Zelltypen tragen -- der
            # haeufigste Fall gewinnt, wie ueberall sonst auch.
            st = max(typ_zaehl[s].items(), key=lambda t: t[1])[0]
            gruppen.append(bloc)
            typen.append(np.frombuffer(st, dtype=np.int32).reshape(bh, bw))
            anzahlen.append(n)
            groessen.append((bw, bh))
            familien.append(familie_der(bloc))

    zellen = max(bw * bh for bw, bh in GROESSEN)

    def flach(bloecke):
        aus = np.full((len(bloecke), zellen), RAND, dtype=np.int32)
        for i, b in enumerate(bloecke):
            aus[i, :b.size] = b.reshape(-1)
        return aus

    feld = flach(gruppen)

    return {
        "kacheln": feld,
        "zelltypen": flach(typen),
        "groesse": np.array(groessen, dtype=np.int8),
        "anzahl": np.array(anzahlen, dtype=np.int64),
        "familie": np.array(familien, dtype=np.int16),
        "familien_namen": np.array(tm.families, dtype="U8"),
        "karten": np.int32(len(felder)),
        "mindest": np.int32(MINDEST),
        "wildcard": np.int32(WILDCARD),
        "rand": np.int32(RAND),
    }


def main() -> None:
    modell = lerne()
    np.savez_compressed(OUT_PATH, **modell)
    gr, an, fa = modell["groesse"], modell["anzahl"], modell["familie"]
    print(f"{int(modell['karten'])} Karten, {len(an)} Gruppen ab "
          f"{int(modell['mindest'])} Vorkommen\n")
    print(f"{'Groesse':>8s} {'Gruppen':>8s} {'Vorkommen':>10s} "
          f"{'haeufigste':>11s} {'gemischt':>9s}")
    for bw, bh in GROESSEN:
        w = (gr[:, 0] == bw) & (gr[:, 1] == bh)
        if not w.any():
            continue
        print(f"{bw}x{bh:<6d} {int(w.sum()):8d} {int(an[w].sum()):10d} "
              f"{int(an[w].max()):11d} {int((fa[w] == -1).sum()):9d}")
    for i, nm in enumerate(modell["familien_namen"]):
        n = int((fa == i).sum())
        if n:
            print(f"   {nm}: {n} Gruppen")
    print(f"\n[ok] {OUT_PATH}")


if __name__ == "__main__":
    main()
