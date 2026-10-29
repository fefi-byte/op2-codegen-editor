"""Handgezeichnete Kolonie-Karte, 128x128, Platz fuer zwei Basen.

Nichts an dieser Karte ist gewuerfelt: Regionen, Hoehenzug, Paesse, Vulkane und
Basisflaechen stehen als Koordinaten im Entwurf weiter unten. Der Generator
liefert nur noch das Kachelwerk -- welche Kachel zu welcher Situation gehoert,
schlaegt er in den Originalkarten nach. Form von Hand, Kacheln gelernt.

Entwurf
-------
    N
    +--------------------------------------------------+
    |  BASIS WEST            .            Vulkan A      |
    |  (32,30) flach         .          (100,22)        |
    |  Bewuchs im Norden     .          Lava nach Sued   |
    |                        .                          |
    |      ~~~~ Hoehenzug quer ueber die Karte ~~~~     |
    |   Pass 1 (x=20)   Pass 2 (x=66)   Pass 3 (x=106)  |
    |          zentrale Mesa (64,62) mit Auffahrt        |
    |                        .                          |
    |  Vulkan B              .          BASIS OST       |
    |  (26,104)              .          (98,100) flach   |
    |  Wuestengebiet         .          Bewuchs im Sued   |
    +--------------------------------------------------+

Beide Basisflaechen liegen auf Erde, sind eben, klippenfrei und gross genug
fuer eine ausgebaute Kolonie. Der Hoehenzug trennt sie, laesst aber drei
Durchgaenge -- ohne die waere die Karte zwei getrennte Inseln.

Hand-drawn colony map, 128x128, room for two bases. Nothing here is rolled:
regions, ridge, passes, volcanoes and base areas are coordinates in the layout
below. The generator only supplies the tiles, looked up from the original maps.
Shape by hand, tiles learned.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import celltypes          # noqa: E402
import mapgen             # noqa: E402
import shapegen           # noqa: E402
from op2map import Op2Map  # noqa: E402

BREITE = HOEHE = 128
SEED = 1        # nur fuer Kachelauswahl und Streugut, nicht fuer das Layout

# --- Entwurf ---------------------------------------------------------------
BASIS_WEST = (32, 30)
BASIS_OST = (98, 100)
BASIS_RADIUS = 21            # freier Radius je Basis

VULKAN_A = (100, 22)
VULKAN_B = (26, 104)

MESA_ZENTRAL = (64, 62)

# Der Hoehenzug als Stuetzpunkte. Bewusst nicht gerade -- eine Linie quer
# ueber die Karte sieht nach Lineal aus.
# The ridge as control points, deliberately not straight.
HOEHENZUG = [(2, 74), (18, 70), (32, 62), (46, 58), (60, 60),
             (74, 66), (88, 62), (102, 54), (116, 48), (126, 44)]
ZUG_DICKE = 9

# Paesse: Durchgaenge im Hoehenzug, sonst waere die Karte geteilt.
# Passes through the ridge, otherwise the map would be split in two.
PAESSE = [(20, 69, 9), (66, 62, 11), (106, 52, 9)]      # x, y, Radius


def _kreis(shape, mitte, radius):
    h, w = shape
    ys, xs = np.ogrid[:h, :w]
    return ((xs - mitte[0]) ** 2 + (ys - mitte[1]) ** 2) <= radius * radius


def _pfad(punkte, dichte=2):
    """Stuetzpunkte zu einer durchgehenden Linie verfeinern."""
    fein = []
    for i in range(len(punkte) - 1):
        (ax, ay), (bx, by) = punkte[i], punkte[i + 1]
        schritte = max(2, int(max(abs(bx - ax), abs(by - ay))) // dichte)
        for k in range(schritte):
            t = k / schritte
            fein.append((int(round(ax + (bx - ax) * t)),
                         int(round(ay + (by - ay) * t))))
    fein.append(punkte[-1])
    return fein


def _fleck(shape, mitte, radius, rng, rauheit=0.4):
    """Unregelmaessige Flaeche. Ein exakter Kreis faellt als Scheibe auf."""
    return shapegen.blob(shape, mitte, radius, rng, rauheit=rauheit).astype(bool)


def familienfeld(tm) -> np.ndarray:
    """Welches Biom wo liegt -- von Hand gemalt.

    Erde dort, wo gebaut wird (die Basisflaechen und ihr Umland), Fels auf dem
    Hoehenzug und um die Vulkane, Sand im Suedwesten und am Ostrand, Bewuchs
    als Auflockerung an den Raendern der Basen.

    Which biome sits where -- painted by hand. Dirt where you build, rock on
    the ridge and around the volcanoes, sand in the south-west and along the
    eastern edge, vegetation as relief at the edges of the bases.
    """
    idx = {name: i for i, name in enumerate(tm.families)}
    feld = np.full((HOEHE, BREITE), idx["mud"], dtype=np.int16)
    rng = np.random.default_rng(11)

    # Wueste im Suedwesten. Aus ueberlappenden Kreisen statt als Diagonale --
    # eine gerade Trennlinie quer ueber die Karte faellt sofort auf.
    # Desert in the south-west, built from overlapping circles rather than a
    # diagonal: a straight dividing line across the map is immediately obvious.
    for mitte, radius in (((6, 112), 30), ((30, 122), 26), ((54, 124), 20),
                          ((12, 88), 18)):
        feld[_fleck((HOEHE, BREITE), mitte, radius, rng)] = idx["san"]
    feld[_fleck((HOEHE, BREITE), (126, 74), 22, rng)] = idx["san"]

    # Fels NUR um die Vulkane. Der erste Entwurf legte den ganzen Hoehenzug
    # auf Fels -- dort verschwinden die Klippen, weil Klippenkacheln auf
    # Felsboden kaum Kontrast haben. In den Originalen liegen Klippen fast
    # immer auf Erde, deshalb bleibt der Zug hier Erde.
    # Rock ONLY around the volcanoes. The first draft put the whole ridge on
    # rock, where the cliffs disappear for lack of contrast. In the originals
    # cliffs sit on dirt almost everywhere, so the ridge stays dirt here.
    for v in (VULKAN_A, VULKAN_B):
        feld[_fleck((HOEHE, BREITE), v, 15, rng, rauheit=0.55)] = idx["roc"]

    # Bewuchs: zwei Flecken je Basis, damit die Ebenen nicht kahl wirken.
    # Vegetation: two patches per base so the plains do not look bald.
    for mitte, radius in (((22, 12), 11), ((48, 16), 8),
                          ((108, 118), 11), ((84, 116), 8),
                          ((14, 46), 7), ((118, 92), 7)):
        feld[_fleck((HOEHE, BREITE), mitte, radius, rng, rauheit=0.6)] = idx["veg"]

    # Basisflaechen sind Erde -- dort wird gebaut, nicht geklettert.
    # Base areas are dirt -- you build there, you do not climb.
    for basis in (BASIS_WEST, BASIS_OST):
        feld[_kreis((HOEHE, BREITE), basis, BASIS_RADIUS)] = idx["mud"]
    # Einmal glaetten: nimmt den Flecken die letzte Rundheit und laesst die
    # Uebergaenge ineinanderlaufen.
    # Smooth once: takes the last roundness off the patches and lets the
    # transitions run into each other.
    return mapgen._smooth_families(feld, 1)


def hoehenfeld() -> np.ndarray:
    """Wo Hochland liegt -- der Hoehenzug, die zentrale Mesa, ein paar Kuppen.

    Where the highland is -- the ridge, the central mesa, a few knolls.
    """
    H = np.zeros((HOEHE, BREITE), dtype=np.int8)
    rng = np.random.default_rng(7)      # nur fuer die Unruhe der Kante

    for i, (px, py) in enumerate(_pfad(HOEHENZUG, dichte=1)):
        # Dicke leicht schwanken lassen, sonst wirkt der Zug wie ein Wall.
        # Vary the thickness slightly, otherwise the ridge looks like a wall.
        d = ZUG_DICKE + int(round(2.5 * np.sin(i * 0.23)))
        H |= _kreis((HOEHE, BREITE), (px, py), d)

    H |= shapegen.blob((HOEHE, BREITE), MESA_ZENTRAL, 17, rng, rauheit=0.35)

    # Kuppen als Deckung in den offenen Ebenen -- nicht in den Basisflaechen.
    # Knolls as cover in the open plains -- not inside the base areas.
    for mitte, radius in (((70, 22), 9), ((16, 60), 7), ((112, 84), 8),
                          ((52, 104), 9), ((92, 44), 7), ((36, 86), 8)):
        H |= shapegen.blob((HOEHE, BREITE), mitte, radius, rng, rauheit=0.45)

    # Der Zug muss bis an beide Kartenraender reichen, sonst laeuft man
    # aussen herum und die Paesse sind Deko. Genau das war der Fehler: der
    # freigeraeumte Randstreifen bildete einen Ring um die ganze Karte.
    # The ridge has to reach both map edges, otherwise you walk around it and
    # the passes are decoration. That was exactly the bug: the cleared border
    # strip formed a ring around the whole map.


    # Auffahrt auf die zentrale Mesa: eine Lucke reicht, damit sie erreichbar
    # bleibt und nicht nur Kulisse ist.
    # A ramp onto the central mesa: one gap keeps it reachable instead of
    # being mere scenery.
    H &= ~_kreis((HOEHE, BREITE), (MESA_ZENTRAL[0] + 12, MESA_ZENTRAL[1] + 13), 7)

    # Basisflaechen und Vulkane bleiben eben.
    # Base areas and volcanoes stay flat.
    for basis in (BASIS_WEST, BASIS_OST):
        H &= ~_kreis((HOEHE, BREITE), basis, BASIS_RADIUS + 3)
    for v in (VULKAN_A, VULKAN_B):
        H &= ~_kreis((HOEHE, BREITE), v, 12)

    # Kante auf Dreierraster rasten -- ruhige Zuege statt Pixelrauschen.
    # Snap the edge to a three-tile grid -- calm runs instead of pixel noise.
    H = shapegen.begradige(H.astype(np.int8), block=3)
    H = shapegen.entferne_kleinkram(H, mindest=30)
    # Nach dem Rastern kann der Zug an einer Stelle aufreissen. Pruefen und
    # schliessen -- eine unbeabsichtigte Luecke macht alle Paesse wertlos.
    # After snapping, the ridge can tear open somewhere. Check and close it --
    # one unintended gap makes all the passes worthless.
    for x in range(4, BREITE - 4):
        if H[:, x].any():
            continue
        links = next((xx for xx in range(x - 1, 3, -1) if H[:, xx].any()), None)
        rechts = next((xx for xx in range(x + 1, BREITE - 4) if H[:, xx].any()), None)
        if links is None or rechts is None:
            continue
        ly = int(np.nonzero(H[:, links])[0].mean())
        ry = int(np.nonzero(H[:, rechts])[0].mean())
        t = (x - links) / max(1, rechts - links)
        H |= _kreis((HOEHE, BREITE), (x, int(ly + (ry - ly) * t)), ZUG_DICKE)
    # Nur oben und unten freihalten -- links und rechts muss der Zug
    # durchlaufen, sonst trennt er nichts.
    # Only clear top and bottom -- left and right the ridge has to run through,
    # otherwise it separates nothing.
    H[:2, :] = 0
    H[-2:, :] = 0
    # Zug bis an den linken und rechten Kartenrand ziehen -- und zwar NACH dem
    # Rastern: 128 ist nicht durch 3 teilbar, der angebrochene Randblock wird
    # mit Nullen aufgefuellt und verliert die Mehrheit. Genau dort lief der
    # Weg vorbei, an dem alle drei Paesse zugemauert waren.
    # Pull the ridge to the left and right map edge -- AFTER snapping: 128 is
    # not divisible by 3, the partial edge block is padded with zeros and loses
    # the vote. That is exactly where the path ran when all three passes were
    # walled up.
    for spalte in range(5):
        H[:, spalte] |= H[:, 5]
        H[:, -1 - spalte] |= H[:, -6]

    # Paesse ZULETZT ausstanzen und breiter als das Wandband (drei Zellen je
    # Seite), sonst waechst die Klippe wieder in den Durchgang hinein.
    # Punch the passes LAST and wider than the wall band (three cells per
    # side), otherwise the cliff grows back into the passage.
    for px, py, r in PAESSE:
        H &= ~_kreis((HOEHE, BREITE), (px, py), r + 4)
    return H


def lavafelder(H: np.ndarray) -> list[list[tuple[int, int]]]:
    """Wo im Spiel Lava fliessen darf.

    Keine Lavakacheln -- die entstehen erst beim Ausbruch. Hier wird nur die
    Flaeche festgelegt, aus der der Codegen `GameMap::SetLavaPossible` macht.
    Beide Bahnen laufen vom Vulkan weg in Richtung Kartenmitte, nicht in die
    Basis: eine Kolonie soll bedroht werden, nicht beim ersten Ausbruch enden.

    Where lava may flow in-game. No lava tiles -- those appear on eruption.
    Both channels run from the volcano towards the middle, not into the base:
    a colony should be threatened, not ended by the first eruption.
    """
    zonen = []
    for start, ziel in ((VULKAN_A, (78, 52)), (VULKAN_B, (48, 84))):
        zellen = set()
        for px, py in _pfad([start, ziel], dichte=1):
            for dx in range(-6, 7):
                for dy in range(-6, 7):
                    x, y = px + dx, py + dy
                    if (0 <= x < BREITE and 0 <= y < HOEHE
                            and dx * dx + dy * dy <= 36 and not H[y, x]):
                        zellen.add((x, y))
        zonen.append(sorted(zellen))
    return zonen


def baue() -> tuple[mapgen.GeneratedMap, list]:
    tm = mapgen.model()
    rng = np.random.default_rng(SEED)
    fam = familienfeld(tm)
    H = hoehenfeld()

    grid = mapgen._sample_tiles(fam, rng, tm)
    vulkane = mapgen._stamp_volcanoes(grid, [VULKAN_A, VULKAN_B], tm, rng)
    # Klippen aus der Hoehenkontur, mit demselben Loeser wie der Generator.
    klippen, _zellen = mapgen._klippen_aus_linien(grid, fam, H, tm, rng)

    # Streugut ueberall ausser auf den Basisflaechen -- dort soll gebaut
    # werden, und ein Felsblock mitten im Bauplatz ist nur laestig.
    # Scatter everywhere except the base areas -- you build there, and a
    # boulder in the middle of the site is just a nuisance.
    gesperrt = klippen.copy()
    for basis in (BASIS_WEST, BASIS_OST):
        gesperrt |= _kreis((HOEHE, BREITE), basis, BASIS_RADIUS)
    for v in vulkane or (VULKAN_A, VULKAN_B):
        gesperrt |= _kreis((HOEHE, BREITE), v, 12)
    mapgen._scatter_details(grid, fam, tm, rng, int(0.03 * BREITE * HOEHE),
                            gesperrt)

    cells = mapgen._cell_types(grid)
    ergebnis = mapgen.GeneratedMap(
        tiles=grid, cells=cells,
        spawns=[BASIS_WEST, BASIS_OST],
        passable_share=float(mapgen._passable_mask(cells).mean()),
        family_share={}, connected=mapgen._connected(cells, [BASIS_WEST, BASIS_OST]),
        volcanoes=vulkane, lava_zones=lavafelder(H),
        plateau_share=float(np.isin(cells, [celltypes.NORTH_CLIFFS,
                                            celltypes.CLIFFS_HIGH_SIDE,
                                            celltypes.CLIFFS_LOW_SIDE]).mean()))
    return ergebnis, H


def main() -> int:
    from vol import VolFile
    import render

    spiel = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
    vorlage = next(spiel.rglob("cm01.map"))
    ziel_dir = Path(__file__).resolve().parent
    ergebnis, H = baue()

    karte = Op2Map(vorlage.read_bytes())
    mapgen.apply_to_map(karte, ergebnis)
    map_pfad = ziel_dir / "kolonie128.map"
    map_pfad.write_bytes(karte.to_bytes())

    # Was nicht in die .map gehoert, kommt als Beiblatt: Startpunkte und
    # lavaPossible sind Missionsdaten, keine Gelaendedaten.
    # What does not belong in the .map comes as a sidecar: spawns and
    # lavaPossible are mission data, not terrain data.
    beiblatt = {
        "spawns": [list(BASIS_WEST), list(BASIS_OST)],
        "volcanoes": [list(v) for v in ergebnis.volcanoes],
        "lava_fields": [[list(p) for p in zone] for zone in ergebnis.lava_zones],
    }
    (ziel_dir / "kolonie128.json").write_text(
        json.dumps(beiblatt, indent=1), encoding="utf-8")

    render.render(karte, VolFile(str(next(spiel.rglob("maps.vol")))),
                  str(ziel_dir / "kolonie128.png"), tile_px=8)
    print(f"Hochland {100*H.mean():.1f} %, Klippen {100*ergebnis.plateau_share:.1f} %, "
          f"befahrbar {100*ergebnis.passable_share:.1f} %, "
          f"verbunden {ergebnis.connected}, Vulkane {len(ergebnis.volcanoes)}, "
          f"Lavafelder {sum(len(z) for z in ergebnis.lava_zones)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
