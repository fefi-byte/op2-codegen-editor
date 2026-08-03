"""Klippen als senkrechte Saeulen lernen -> `cliff_columns_model.npz`.

Aufruf:  python mapview/learn_cliff_columns.py

Eine Klippenwand ist im Querschnitt ein senkrechtes Band aus wenigen Kacheln.
Statt einzelner Kacheln oder ganzer Bloecke ist hier dieses **Band** die
Einheit. Gezaehlt wird, welches Band rechts neben welchem steht und mit welchem
senkrechten Versatz -- und dieser Versatz IST die Neigung der Wand.

--- Warum das Band und nicht die Kachel -------------------------------------

Der Versuch mit einzelnen Kacheln ist gescheitert, und zwar an zwei Dingen, die
sich nicht beheben liessen: es gibt praktisch keine Fuellkachel (mud hat EINE
mit vier reinen Felskanten, san keine -- jede Klippenkachel ist Randkachel), und
die ROLLE einer Kachel steht nicht in ihren Kanten. Beides ist im Band
enthalten: es traegt Ober-, Wand- und Unterkante in einem.

--- Warum die Hoehe 3 bis 4 und nicht fest 3 --------------------------------

Ein senkrechter Schnitt durch eine SCHRAEGE Wand ist laenger als durch eine
waagerechte. Nimmt man nur Baender der Hoehe genau 3, misst man deshalb nicht
"Klippen", sondern "waagerechte Klippen" -- und findet folgerichtig zu 94,9 %
Versatz null. Trifft ein Dreierband auf ein Viererband, ist der Versatz dagegen
zu 70,1 % ungleich null: dort sitzen die Stufen.

Nach oben ist bei 4 Schluss, weil hohe Baender gar keine Querschnitte mehr sind:
eine Spalte, die 11 Klippenkacheln durchlaeuft, folgt einer Nord-Sued-Wand der
LAENGE nach. Gemessen ueber alle 54 Stockkarten:

    Bandhoehe   Baender  je Band  einmalig  Versatz != 0  Wachstum 20->54
        3           788    11,77    46,3 %        5,1 %          x2,10
        3..4       1297    10,07    49,6 %       23,6 %          x2,16
        3..5       1756     9,21    51,2 %       30,3 %          x2,19
        3..8       2951     6,78    56,0 %       37,4 %          x2,36

Ab 5 steigt der Anteil der Baender, die in 54 Karten genau einmal vorkommen,
und die Belege je Band fallen -- das waere Auswendiglernen statt einer Regel.
Bei 3..4 sind die Versaetze fast nur ±1:

    -2  0,9 %     -1  14,2 %     0  76,4 %     +1  7,7 %     +2  0,4 %

also eine Treppe aus einzelnen Stufen.

--- Was sonst noch gemessen wurde -------------------------------------------

**Der Vorrat saettigt sich.** Von 20 auf 54 Karten verdoppelt sich die Zahl der
verschiedenen Baender, waehrend sich die Vorkommen fast vervierfachen. Es sind
Regeln, keine Einzelfaelle.

**Das Band weiss, wohin die Wand laeuft.** Ueber echte Dreierfolgen a -> b -> c
gemessen: die Ungewissheit ueber den naechsten Versatz betraegt frei 2,047 Bit.
Kennt man nur den vorigen Versatz, bleiben 1,949 Bit (4,8 % weg) -- eine Wand
ist also nicht einfach autokorreliert. Kennt man das Band, bleiben 0,727 Bit
(64,5 % weg). Ein Setzer braucht deshalb kein Gedaechtnis fuer die Neigung; er
muss nur das Band kennen.

--- Learning cliffs as vertical bands ---------------------------------------

A cliff wall in cross-section is a short vertical band of tiles, and that band
is the unit here -- not the tile, not the whole block. Counted is which band
stands to the right of which and at what vertical offset; that offset IS the
slope. The per-tile attempt failed on two things: there is practically no fill
tile (every cliff tile is a rim tile) and a tile's ROLE is not in its edges.

Height is 3 to 4, not a fixed 3: a vertical cut through a DIAGONAL wall is
longer than through a horizontal one, so sampling only 3-tall bands samples only
horizontal walls (94,9 % zero offset). Above 4 a band stops being a cross-
section at all -- an 11-tall band is a column following a N-S wall lengthwise --
and the vocabulary starts memorising instead of generalising.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import celltypes                                   # noqa: E402
from op2map import Op2Map                          # noqa: E402
from vol import VolFile                            # noqa: E402

GAME_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
OUT_PATH = HERE / "cliff_columns_model.npz"

KLIPPE = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
          celltypes.CLIFFS_LOW_SIDE)

# Hoehe eines Bandes, das noch als Querschnitt einer Ost-West-Wand gilt.
# Begruendung mit Messwerten oben im Modulkopf.
# Band heights that still count as a cross-section; see the header for numbers.
MINDESTHOEHE = 3
HOECHSTHOEHE = 4

# Groesster senkrechter Versatz, der noch als Nachbarschaft zaehlt. Zwei Baender
# gehoeren nur dann zur selben Wand, wenn sie sich senkrecht UEBERLAPPEN -- das
# wird unten Band fuer Band geprueft, diese Grenze kappt nur den Rest.
#
# Frueher stand hier 4, und die Messung zaehlte 216 Uebergaenge mit Versatz ±4.
# Das waren keine Stufen, sondern die jeweils ANDERE Wand einer Karte, in der
# zwei Baender parallel laufen; beim Setzen zerfiel die Kette dort in
# unverbundene Stuecke.
# Two bands belong to the same wall only if they overlap vertically.
VERSATZ_GRENZE = HOECHSTHOEHE - 1


def _baender_einer_karte(m: Op2Map):
    """Klippenbaender einer Karte -> je Spalte [(y, Kacheln, Zelltypen)].

    Ein Band ist ein zusammenhaengender senkrechter Lauf von Klippenzellen in
    einer Spalte. Genommen werden nur die Hoehen MINDESTHOEHE..HOECHSTHOEHE.
    """
    h, w = m.height, m.width
    kl = np.array([[m.cell_type(x, y) in KLIPPE for x in range(w)]
                   for y in range(h)])
    idx = np.array([[m.tile_mapping_index(x, y) for x in range(w)]
                    for y in range(h)])
    zt = np.array([[m.cell_type(x, y) for x in range(w)] for y in range(h)])
    baender: list[list] = [[] for _ in range(w)]
    for x in range(w):
        y = 0
        while y < h:
            if not kl[y, x]:
                y += 1
                continue
            ende = y
            while ende + 1 < h and kl[ende + 1, x]:
                ende += 1
            if MINDESTHOEHE <= ende - y + 1 <= HOECHSTHOEHE:
                baender[x].append((
                    y,
                    tuple(int(v) for v in idx[y:ende + 1, x]),
                    tuple(int(v) for v in zt[y:ende + 1, x]),
                ))
            y = ende + 1
    return baender


def lerne(game_dir: Path = GAME_DIR) -> dict:
    vol = VolFile(str(game_dir / "maps.vol"))
    namen = [n for n in vol.names() if n.endswith(".map")]
    if not namen:
        raise SystemExit("keine Karten in maps.vol")

    haeufig: Counter = Counter()
    zelltyp: dict[tuple, tuple] = {}
    uebergang: Counter = Counter()
    karten = 0
    for name in namen:
        try:
            m = Op2Map(vol.read_file(name))
        except Exception:                            # noqa: BLE001
            continue
        spalten = _baender_einer_karte(m)
        for spalte in spalten:
            for _y, b, zt in spalte:
                haeufig[b] += 1
                zelltyp.setdefault(b, zt)
        for x in range(len(spalten) - 1):
            for y, a, _z in spalten[x]:
                for y2, b, _z2 in spalten[x + 1]:
                    # kein senkrechter Ueberlapp heisst: andere Wand
                    if y2 >= y + len(a) or y >= y2 + len(b):
                        continue
                    if abs(y2 - y) > VERSATZ_GRENZE:
                        continue
                    uebergang[(a, b, y2 - y)] += 1
        karten += 1

    baender = sorted(haeufig, key=lambda b: -haeufig[b])
    platz = {b: i for i, b in enumerate(baender)}

    import mapgen
    tm = mapgen.model()

    def familie_der(b):
        f = [int(tm.family_of[t]) for t in b
             if 0 <= t < len(tm.family_of) and int(tm.family_of[t]) >= 0]
        return Counter(f).most_common(1)[0][0] if f else -1

    def gefuellt(folgen, fuell=-1):
        """Baender verschiedener Hoehe in ein rechteckiges Feld, -1 als Rand."""
        aus = np.full((len(folgen), HOECHSTHOEHE), fuell, dtype=np.int32)
        for i, f in enumerate(folgen):
            aus[i, :len(f)] = f
        return aus

    return {
        "saeulen": gefuellt(baender),
        "hoehe": np.array([len(b) for b in baender], dtype=np.int8),
        "haeufigkeit": np.array([haeufig[b] for b in baender], dtype=np.int64),
        "zelltypen": gefuellt([zelltyp[b] for b in baender]),
        "familie": np.array([familie_der(b) for b in baender], dtype=np.int16),
        "familien_namen": np.array(tm.families, dtype="U8"),
        "nb_a": np.array([platz[a] for a, _b, _d in uebergang], dtype=np.int32),
        "nb_b": np.array([platz[b] for _a, b, _d in uebergang], dtype=np.int32),
        "nb_versatz": np.array([d for _a, _b, d in uebergang], dtype=np.int8),
        "nb_anzahl": np.array(list(uebergang.values()), dtype=np.int32),
        "mindesthoehe": np.int32(MINDESTHOEHE),
        "hoechsthoehe": np.int32(HOECHSTHOEHE),
        "karten": np.int32(karten),
    }


def main() -> None:
    modell = lerne()
    np.savez_compressed(OUT_PATH, **modell)
    h = modell["haeufigkeit"]
    ges = int(h.sum())
    print(f"{int(modell['karten'])} Karten, {len(h)} verschiedene Baender "
          f"aus {ges} Vorkommen ({ges/len(h):.2f} je Band, einmalig "
          f"{100*int((h == 1).sum())/len(h):.1f} %)")
    print(f"Uebergaenge: {len(modell['nb_a'])} verschiedene, "
          f"{int(modell['nb_anzahl'].sum())} Vorkommen")
    for anteil in (0.5, 0.8, 0.9):
        n = int(np.searchsorted(np.cumsum(h), anteil * ges) + 1)
        print(f"   {100*anteil:.0f} % der Vorkommen entfallen auf {n} Baender")
    hoehen = Counter(int(v) for v in modell["hoehe"])
    print(f"Bandhoehen: { dict(sorted(hoehen.items())) }")
    versatz: Counter = Counter()
    for d, n in zip(modell["nb_versatz"], modell["nb_anzahl"]):
        versatz[int(d)] += int(n)
    gv = sum(versatz.values())
    print("Versatz nach Vorkommen: " + "  ".join(
        f"{d:+d}: {100*versatz[d]/gv:.1f} %" for d in sorted(versatz)))
    print(f"\n[ok] {OUT_PATH}")


if __name__ == "__main__":
    main()
