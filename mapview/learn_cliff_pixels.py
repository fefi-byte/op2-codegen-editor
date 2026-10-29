"""Die Kantenpixel der Klippenkacheln sammeln -> `cliff_pixels_model.npz`.

Aufruf:  python mapview/learn_cliff_pixels.py

Alle anderen Masse in diesem Projekt fragen die 54 Originalkarten: gilt ein
Kachelpaar als gut, weil es dort vorkam? Ueber die 97 % der moeglichen Paare,
die nie vorkamen, sagen sie nichts -- und genau die braucht ein Setzer, der mehr
bauen soll als das Gezaehlte.

Dieses Mass liest statt dessen die Kachel selbst: passen die beruehrenden
Pixelreihen zweier Kacheln zusammen? Gespeichert werden je Kachel die vier
Randreihen (oben, rechts, unten, links), 32 Pixel mal drei Farbkanaele.

--- Was es taugt ------------------------------------------------------------

Gemessen an den 195 Klippenkacheln, deren Bild aus `cm01` zu holen ist:

    Richtung   belegte Paare   unbelegte   Trennschaerfe
       O        Median 24,2    Median 40,1     81,4 %
       S        Median 25,1    Median 40,8     85,1 %

Ein Paar, das die Entwickler gebaut haben, hat an der Naht typisch 24 Einheiten
Farbunterschied, ein nie gebautes 40. Die Trennschaerfe ist der Anteil der
Faelle, in denen ein zufaellig gezogenes belegtes Paar naeher ist als ein
zufaellig gezogenes unbelegtes; 50 % waere gar keine Trennung.

Als alleiniges Kriterium taugt das nicht -- in etwa jedem sechsten Fall irrt es.
Als zweites neben der gezaehlten Tabelle sehr wohl: die Tabelle sagt, was
erlaubt ist, die Pixel sagen, was davon passt.

--- Collecting the tiles' edge pixels ---------------------------------------

Every other measure in this project asks the 54 stock maps whether a pair
occurred. This one reads the tile itself: do the touching pixel rows of two
tiles match? Measured, attested pairs differ by 24 units at the seam and
unattested ones by 40, separating them 81 to 85 % of the time -- useful as a
second criterion beside the counted table, not as the only one.
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
from tileset import TILE, load_tileset             # noqa: E402
from vol import VolFile                            # noqa: E402

from spielpfad import spielordner  # noqa: E402
GAME_DIR = spielordner()
OUT_PATH = HERE / "cliff_pixels_model.npz"

KLIPPE = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
          celltypes.CLIFFS_LOW_SIDE)
# Reihenfolge ist Teil des Dateiformats: 0 = N, 1 = O, 2 = S, 3 = W.
KANTEN = ("N", "O", "S", "W")

# In wieviele Abschnitte eine Kantenreihe zerfaellt. Vier mal acht Pixel.
ABSCHNITTE = 4

# Ab welchem Farbabstand zur Grundkachel ein Abschnitt als FELS gilt.
#
# Gemessen an den Seiten, ueber die die Originalkarten Eindeutiges sagen:
# wo nie Gelaende lag, haben die Abschnitte im Median Abstand 15,6; wo immer
# Gelaende lag, Abstand 0,0 -- sie SIND Boden. Die Trennschaerfe betraegt
# 90,1 %, die beste Schwelle liegt bei 2,0 und trifft 84,6 %.
#
# Measured against the sides the stock maps are unambiguous about: rock
# sections sit at distance 15,6 from the plain ground tile, biome sections at
# 0,0. Separation 90,1 %, best threshold 2,0 at 84,6 % correct.
FELS_SCHWELLE = 2.0


def _randreihen(bild: np.ndarray) -> np.ndarray:
    """Die vier Randreihen einer Kachel -> (4, TILE, 3)."""
    return np.stack([bild[0, :, :], bild[:, -1, :],
                     bild[-1, :, :], bild[:, 0, :]])


def lerne(game_dir: Path = GAME_DIR) -> dict:
    vol = VolFile(str(game_dir / "maps.vol"))
    namen = [n for n in vol.names() if n.endswith(".map")]
    if not namen:
        raise SystemExit("keine Karten in maps.vol")

    kanten: dict[int, np.ndarray] = {}
    bilder: dict[int, np.ndarray] = {}
    karten = 0
    for name in namen:
        try:
            m = Op2Map(vol.read_file(name))
        except Exception:                            # noqa: BLE001
            continue
        sets = {}
        for i, ts in enumerate(m.tileset_sources):
            if not ts.filename:
                continue
            try:
                sets[i] = load_tileset(vol.read_file(ts.filename + ".bmp"))
            except Exception:                        # noqa: BLE001
                pass
        if not sets:
            continue
        h, w = m.height, m.width
        for y in range(h):
            for x in range(w):
                if m.cell_type(x, y) not in KLIPPE:
                    continue
                t = int(m.tile_mapping_index(x, y))
                if t in kanten:
                    continue
                si, gfx = m.tileset_and_graphic(x, y)
                ts = sets.get(si)
                if ts is None or gfx >= ts.num_tiles:
                    continue
                block = ts.pixels[gfx * TILE:(gfx + 1) * TILE, :]
                voll = ts.palette[block]
                kanten[t] = _randreihen(voll).astype(np.uint8)
                # Das ganze Bild kommt mit -- 307 mal 32x32x3 ist nichts, und
                # ein Werkzeug, das die Kacheln zeigen soll, muss dafuer nicht
                # 54 Karten durchlaufen.
                bilder[t] = voll.astype(np.uint8)
        karten += 1

    kacheln = sorted(kanten)

    # Vorbelegung: je Kante vier Abschnitte, Fels oder Biom. Gemessen am
    # Abstand zur Grundkachel der eigenen Familie -- eine Klippenkachel kann
    # nur das Biom tragen, in dem sie steht.
    import mapgen
    tmod = mapgen.model()
    grund = {}
    for fi, fam in enumerate(tmod.families):
        for t in range(2048):
            if (tmod.family_of[t] == fi and tmod.placeable[t]
                    and t in bilder):
                grund[fi] = bilder[t].reshape(-1, 3).astype(np.int16)
                break
    vor = np.zeros((len(kacheln), len(KANTEN), ABSCHNITTE), dtype=bool)
    for i, t in enumerate(kacheln):
        fi = int(tmod.family_of[t]) if t < len(tmod.family_of) else -1
        g = grund.get(fi)
        for k, _s in enumerate(KANTEN):
            reihe = kanten[t][k].astype(np.int16)
            breit = reihe.shape[0] // ABSCHNITTE
            for a in range(ABSCHNITTE):
                teil = reihe[a * breit:(a + 1) * breit]
                if g is None:
                    vor[i, k, a] = True
                    continue
                d = np.abs(teil[:, None, :] - g[None, :, :]).sum(axis=2)
                vor[i, k, a] = float(d.min(axis=1).mean()) >= FELS_SCHWELLE

    return {
        "kacheln": np.array(kacheln, dtype=np.int32),
        "raender": np.stack([kanten[t] for t in kacheln]),
        "bilder": np.stack([bilder[t] for t in kacheln]),
        "kanten": np.array(KANTEN, dtype="U2"),
        "vorbelegung": vor,
        "abschnitte": np.int32(ABSCHNITTE),
        "karten": np.int32(karten),
    }


def main() -> None:
    modell = lerne()
    np.savez_compressed(OUT_PATH, **modell)
    print(f"{int(modell['karten'])} Karten, "
          f"{len(modell['kacheln'])} Klippenkacheln mit Randpixeln")
    print(f"Form: {modell['raender'].shape}  "
          f"(Kacheln, 4 Kanten, {modell['raender'].shape[2]} Pixel, 3 Kanaele)")
    print(f"\n[ok] {OUT_PATH}")


if __name__ == "__main__":
    main()
