"""Klippengruppen nach FORM aus den Originalkarten -> `cliff_gruppen_model.npz`.

Aufruf:  python mapview/learn_cliff_gruppen.py

Der Unterschied zum aelteren `learn_cliff_patches`: dort war die Fuellung der
Schluessel, hier ist es die FORM. Gefragt wird beim Setzen ja nicht "kenne ich
diese Kachelfolge", sondern "hier steht diese Stufe -- welche Kacheln gehoeren
da hin?". Nach Fuellung indiziert muss man dafuer suchen; nach Form indiziert
schlaegt man nach.

--- Was die Karten hergeben ------------------------------------------------

Anteil der 121603 Klippenzellen, die in einer Gruppe ab N Vorkommen liegen:

    Groesse   ab 3     ab 10    ab 30    ab 100
      2x2    99,3 %   97,4 %   92,8 %   81,8 %
      3x3    98,2 %   93,6 %   85,2 %   70,6 %
      4x3    97,1 %   90,3 %   78,6 %   62,0 %
      6x4    92,4 %   80,2 %   66,3 %   47,9 %

Die aeltere Notiz sagte fuer 6x4 "deckt streng 27,8 %". Das war eine andere
Frage -- dort ueberlappungsfrei gekachelt, hier "liegt in mindestens einer
haeufigen Gruppe". Der Wortschatz ist also da, er laesst sich nur nicht
lueckenlos parkettieren. Genau deshalb mehrere Groessen: die grosse traegt die
Richtung, die kleine stopft die Reste.

--- Warum die Form der Schluessel ist --------------------------------------

Nach Art getrennt, 4x3 (Bestimmtheit = Vorkommen je Fuellung):

    Art      Formen   Vorkommen   Fuellungen   Bestimmtheit
    gerade      354      204860        34133        6,0
    Stufe       749       64003        18911        3,4

Im Mittel sagt das wenig, im Einzelnen sehr viel. Die haeufigsten GERADEN
Formen haben 700 bis 3000 Fuellungen -- die sagen nur "hier ist Wand". Einzelne
STUFENformen dagegen:

    6x4  ......|....##|...##.|...##.    175 Vorkommen,  4 Fuellungen
    6x4  ......|....##|..###.|..##..     87 Vorkommen,  2 Fuellungen
    4x3  ...#|..##|...#                 330 Vorkommen, 13 Fuellungen

Das sind Vorlagen. Und es sind die Stufen -- also gerade das, was die Bloecke
aus dem Kachelsatz nicht kennen: die kennen den geraden Lauf, den diagonalen
gibt es nur in den Karten.

Cliff groups keyed by SHAPE, not by filling: when placing, the question is
"this step is here, which tiles belong in it?".
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HIER = Path(__file__).resolve().parent
if str(HIER) not in sys.path:
    sys.path.insert(0, str(HIER))

import celltypes                                          # noqa: E402
from op2map import Op2Map                                 # noqa: E402
from vol import VolFile                                   # noqa: E402

GAME_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
ZIEL = HIER / "cliff_gruppen_model.npz"

KLIPPE = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
          celltypes.CLIFFS_LOW_SIDE)

# Von gross nach klein. Die grosse Gruppe traegt die Richtung eines Laufs, die
# kleine deckt, was uebrig bleibt -- keine Groesse allein reicht.
GROESSEN = ((6, 4), (4, 6), (4, 3), (3, 4), (3, 3), (2, 2))

# Groesstes Fenster, auf das alles aufgefuellt wird. 6*4 = 24.
PLATZ = max(bw * bh for bw, bh in GROESSEN)

# Weniger Vorkommen als das ist kein Muster, sondern eine Stelle in einer
# Karte. Bei 10 bleiben je Groesse ein paar tausend Fuellungen uebrig, und die
# Deckung liegt zwischen 80 und 97 Prozent.
MINDEST = 10

BODEN = -1          # dort liegt Gelaende, die Gruppe sagt darueber nichts
RAND = -2           # Auffuellung, weil die Groessen verschieden sind


def _karte_lesen(m: Op2Map):
    """-> (Kachelnummern, Klippenmaske) oder None, wenn die Karte keine hat."""
    h, w = m.height, m.width
    idx = np.array([[m.tile_mapping_index(x, y) for x in range(w)]
                    for y in range(h)], dtype=np.int32)
    ist = np.array([[m.cell_type(x, y) in KLIPPE for x in range(w)]
                    for y in range(h)])
    return (idx, ist) if ist.any() else None


def lerne(game_dir: Path = GAME_DIR) -> dict:
    import mapgen
    tm = mapgen.model()

    vol = VolFile(str(game_dir / "maps.vol"))
    felder = []
    for name in sorted(n for n in vol.names() if n.endswith(".map")):
        try:
            m = Op2Map(vol.read_file(name))
        except Exception:                                # noqa: BLE001
            continue
        gelesen = _karte_lesen(m)
        if gelesen:
            felder.append(gelesen)
    if not felder:
        raise SystemExit("keine Karten mit Klippen gefunden")
    zellen = sum(int(i.sum()) for _x, i in felder)
    print(f"{len(felder)} Karten, {zellen} Klippenzellen")

    zeilen = []
    for bw, bh in GROESSEN:
        # Fuellung -> (Form, Familie, Anzahl)
        zaehl: Counter = Counter()
        merk: dict = {}
        for idx, ist in felder:
            h, w = idx.shape
            for y in range(h - bh + 1):
                for x in range(w - bw + 1):
                    maske = ist[y:y + bh, x:x + bw]
                    if not maske.any():
                        continue
                    fenster = idx[y:y + bh, x:x + bw]
                    fuell = np.where(maske, fenster, BODEN).astype(np.int32)
                    schluessel = fuell.tobytes()
                    zaehl[schluessel] += 1
                    if schluessel not in merk:
                        # Die Familie aus den Klippenkacheln selbst; sie
                        # mischen sich nie.
                        fams = {int(tm.family_of[int(t)])
                                for t in fenster[maske]
                                if 0 <= int(t) < len(tm.family_of)}
                        fams.discard(-1)
                        merk[schluessel] = (maske.copy(),
                                            fams.pop() if len(fams) == 1
                                            else -1)
        behalten = 0
        for schluessel, n in zaehl.items():
            if n < MINDEST:
                continue
            maske, fam = merk[schluessel]
            fuell = np.frombuffer(schluessel, dtype=np.int32).reshape(bh, bw)
            form = np.full(PLATZ, RAND, dtype=np.int8)
            kach = np.full(PLATZ, RAND, dtype=np.int32)
            form[:bw * bh] = maske.reshape(-1).astype(np.int8)
            kach[:bw * bh] = fuell.reshape(-1)
            zeilen.append((bw, bh, form, kach, n, fam))
            behalten += 1
        print(f"   {bw}x{bh}: {len(zaehl)} Fuellungen, {behalten} ab "
              f"{MINDEST} Vorkommen")

    if not zeilen:
        raise SystemExit("nichts gefunden")
    return {
        "groesse": np.array([[z[0], z[1]] for z in zeilen], dtype=np.int8),
        "form": np.stack([z[2] for z in zeilen]),
        "kacheln": np.stack([z[3] for z in zeilen]),
        "anzahl": np.array([z[4] for z in zeilen], dtype=np.int64),
        "familie": np.array([z[5] for z in zeilen], dtype=np.int16),
        "familien_namen": np.array(mapgen.model().families, dtype="U8"),
        "karten": np.int32(len(felder)),
        "mindest": np.int32(MINDEST),
        "boden": np.int32(BODEN),
        "rand": np.int32(RAND),
    }


def main() -> int:
    daten = lerne()
    np.savez_compressed(ZIEL, **daten)
    print(f"\n[ok] {ZIEL.name}: {len(daten['anzahl'])} Gruppen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
