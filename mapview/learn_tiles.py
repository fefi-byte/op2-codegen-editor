"""Lernt aus den mitgelieferten Karten, welche Kacheln nebeneinander liegen.

Ergebnis: `tiles_model.npz` neben diesem Skript --
  right   (N,3) int32  [Kachel a, Kachel b, Haeufigkeit]  b liegt rechts von a
  down    (N,3) int32  [Kachel a, Kachel b, Haeufigkeit]  b liegt unter a
  usage   (M,2) int32  [Kachel, Haeufigkeit]
  family  (M,2) int32  [Kachel, Familien-Index]
  families      <U8    Namen der Familien (mud/roc/san/sno/lav/…)

Damit erzeugt der Kartengenerator Gelaende, das wie handgebautes OP2-Gelaende
aussieht, statt Uebergaenge zu erfinden.

Aufruf:  python mapview/learn_tiles.py [<Outpost2-Ordner>]

Learns which tiles occur next to each other in the shipped maps and stores the
adjacency model as tiles_model.npz.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from op2map import Op2Map, CELL_TYPE_BITS, MAPPING_INDEX_MASK  # noqa: E402
import celltypes  # noqa: E402

DEFAULT_GAME_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
OUT_PATH = Path(__file__).with_name("tiles_model.npz")

# Nur die Kampagnenkarten anlernen: Mehrspielerkarten sind auf Spielbarkeit
# gebaut (kurze Wege, offene Flaechen) und nicht auf stimmige Landschaft.
# Learn from the campaign maps only: multiplayer maps are built for
# playability (short routes, open areas), not for coherent scenery.
CAMPAIGN_PATTERN = re.compile(r"^(cm\d|eden\d|ply\d|tutorial)", re.IGNORECASE)

# Kacheln aus diesen Gruppen sind BAUTEILE, keine Flaechen: Vulkane, Lava,
# Fumarolen, Brandspuren, planierter Boden, Klippen/Mesas. Sie werden im
# Original gezielt gesetzt -- wer sie zufaellig streut, bekommt Sprenkel.
# Tiles from these groups are BUILDING BLOCKS, not surfaces: volcanoes, lava,
# fumaroles, burn marks, bulldozed ground, cliffs/mesas. The originals place
# them deliberately -- scattering them randomly produces speckles.
STRUCTURE_MARKERS = ("volc", "lav", "vent", "burn", "brn", "doz", "mes")
LAVA_MARKERS = ("lav",)
VOLCANO_MARKER = "volc"
# Klippen-/Mesa-Stempel: Bauteile fuer Hochflaechen (Kanten + Ecken).
# Cliff/mesa stamps: building blocks for plateaus (edges + corners).
CLIFF_MARKER = "mes"
# Streugut: Steine, Risse, Krater. Das sind keine Bauteile, sondern Details
# INNERHALB einer Flaeche -- im Original decken sie rund 3 % der Karte ab.
# Scatter: stones, cracks, craters. Not building blocks but details WITHIN an
# area -- in the originals they cover about 3 % of the map.
# `wrk` sind Wrackteile -- Verzierung wie Brocken und Risse, kein Boden.
# Sie fehlten hier, und 13 `mudwrk*` plus 2 `sanwrk*` wurden deshalb als
# Grundkacheln frei gesetzt: 18 von 50 Erdkacheln waren gar keine Erde.
# `wrk` are wreck pieces -- decoration like boulders and cracks, not
# ground. They were missing here, so 13 `mudwrk*` plus 2 `sanwrk*` were
# placed freely as base tiles: 18 of 50 dirt tiles were not dirt at all.
DETAIL_MARKERS = ("rock", "rok", "crk", "crac", "crat", "wrk")

# Namenspraefixe der TileGroups -> Gelaendefamilie.
# Tile group name prefixes -> terrain family.
FAMILY_PREFIXES = {
    "mud": "mud", "roc": "roc", "san": "san", "sno": "sno", "snw": "sno",
    "lav": "lav",
}


def tile_grid(m: Op2Map) -> np.ndarray:
    h, w = m.height, m.width
    ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    idx = ((xs >> 5) * h + ys) * 32 + (xs & 0x1F)
    tiles = np.asarray(m.tiles, dtype=np.uint32)[idx]
    return ((tiles >> 5) & 0x7FF).astype(np.int32)


def classify_formation(tiles) -> str:
    """Bauart einer Formation bestimmen: Grat, Massiv oder Plateau.

    Massgeblich ist der eingeschlossene begehbare Innenraum. Ein Grat hat
    keinen, ein Massiv nur einen kleinen, ein Plateau ein richtiges Hochland,
    auf dem man bauen kann. Die Merkmale im Generator greifen darauf zu.

    Determine the build type of a formation: ridge, massif or plateau. What
    matters is the enclosed walkable interior -- a ridge has none, a massif
    only a small one, a plateau has real highland you can build on. The
    generator's terrain features pick from these classes.
    """
    import celltypes
    from collections import deque
    sperr = [k for k, v in celltypes.SPEED_CLASS.items()
             if v in ("cliff", "impassable")]
    ct = np.array([[celltypes.default_cell_type(int(t), fallback=0)
                    for t in reihe] for reihe in tiles], dtype=np.int32)
    h, w = ct.shape
    frei = ~np.isin(ct, sperr)
    aussen = np.zeros_like(frei)
    q = deque()
    rand = ([(x, y) for x in range(w) for y in (0, h - 1)]
            + [(x, y) for y in range(h) for x in (0, w - 1)])
    for x, y in rand:
        if frei[y, x] and not aussen[y, x]:
            aussen[y, x] = True
            q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (0 <= nx < w and 0 <= ny < h and frei[ny, nx]
                    and not aussen[ny, nx]):
                aussen[ny, nx] = True
                q.append((nx, ny))
    innen = int((frei & ~aussen).sum())
    if innen < 6:
        return "grat"
    return "plateau" if innen >= 20 else "massiv"


def formation_direction(tiles) -> str:
    """Gefaellerichtung: wohin faellt die Klippe ab?

    Aus dem Versatz zwischen Hoch- und Tiefseite. Fuer Taeler wichtig: die
    Wand gehoert auf die Seite, deren Gefaelle zum Korridor zeigt.

    Downhill direction from the offset between high and low side. Matters for
    valleys: a wall belongs on the side whose slope faces the corridor.
    """
    import celltypes
    ct = np.array([[celltypes.default_cell_type(int(t), fallback=0)
                    for t in reihe] for reihe in tiles], dtype=np.int32)
    hy, hx = np.where(ct == celltypes.CLIFFS_HIGH_SIDE)
    ty, tx = np.where(ct == celltypes.CLIFFS_LOW_SIDE)
    if not len(hy) or not len(ty):
        return ""
    dx = float(tx.mean() - hx.mean())
    dy = float(ty.mean() - hy.mean())
    if (dx * dx + dy * dy) ** 0.5 < 1.0:
        return ""
    if abs(dx) > abs(dy):
        return "o" if dx > 0 else "w"
    return "s" if dy > 0 else "n"


# Rollen im Hoehenfeld. Aus diesen fuenf Werten besteht der Kontext, aus dem
# die Kachel abgeleitet wird.
# Roles in the height field -- the context a tile is derived from.
ROLLE_TIEF, ROLLE_HOCH = 0, 1
ROLLE_NORD, ROLLE_HOCHSEITE, ROLLE_TIEFSEITE = 2, 3, 4

CLIFF_CELLS = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
               celltypes.CLIFFS_LOW_SIDE)


# Bodenarten, wie sie in Gruppennamen vorkommen, samt Schreibvarianten.
# Ground types as they appear in group names, with spelling variants.
BODEN_NAMEN = ("mud", "roc", "san", "sno", "lav")
BODEN_ALIAS = {"snow": "sno", "snw": "sno", "rock": "roc", "sand": "san",
               "dirt": "mud",
               # `roctola3` heisst "rock to lava", kuerzt Lava aber auf "la"
               # ab. Ohne diesen Eintrag galten seine 48 Kacheln als reiner
               # Fels und wurden mitten in Felsflaechen gestreut -- Lavaboden,
               # wo keine Lava ist.
               # `roctola3` means "rock to lava" but abbreviates lava as "la".
               # Without this entry its 48 tiles counted as pure rock and were
               # scattered in the middle of rock areas -- lava ground where
               # there is no lava.
               "tola": "lav"}


def familien_im_namen(low: str) -> list[str]:
    """Welche Bodenarten nennt ein Gruppenname?

    Nennt er zwei, ist es ein Uebergangssatz: `roctomud` ist Fels ZU Erde,
    `santoroc` Sand zu Fels. Die Entwickler haben ihre Uebergaenge selbst so
    benannt -- die verlaesslichste Quelle, die es dafuer gibt.

    Which ground types does a group name mention? If it names two, it is a
    transition set: `roctomud` is rock TO dirt. The developers named their
    transitions themselves, the most reliable source there is.
    """
    gefunden = []
    for f in BODEN_NAMEN:
        if f in low and f not in gefunden:
            gefunden.append(f)
    for alias, f in BODEN_ALIAS.items():
        if alias in low and f not in gefunden:
            gefunden.append(f)
    return gefunden


# Wie fein die Kante einer Kachel beschrieben wird: Mittelwerte ueber so
# viele Abschnitte je Seite. Gemessen deckt 8 noch 98,6 % der Nachbarschaften
# aus den Originalkarten ab und laesst 542 statt 21 Kacheln als Nachbarn zu --
# genau der Spielraum, der dem Loeser bisher fehlte. Feiner (32) waere
# strenger, wuerde aber 4 % der Kombinationen ausschliessen, die die
# Entwickler selbst benutzt haben.
# How finely a tile edge is described: means over this many segments per side.
# Measured, 8 still covers 98.6 % of the adjacencies in the original maps and
# admits 542 instead of 21 tiles as neighbours -- exactly the room the solver
# was missing. Finer (32) would be stricter but would rule out 4 % of the
# combinations the developers used themselves.
KANTEN_SEGMENTE = 8


def gruppe_je_kachel(m: Op2Map, n: int) -> np.ndarray:
    """Zu welcher TileGroup gehoert jede Kachel? (-1 = keiner)

    Die Gruppen sind die Pinsel des Originaleditors. Gemessen an cm03/cm04
    stammen 60-65 % aller benachbarten Klippenkacheln aus derselben Gruppe --
    die Entwickler haben Klippen als Zug gezogen, nicht Zelle fuer Zelle
    zusammengesucht.

    Which TileGroup does each tile belong to? (-1 = none). The groups are the
    original editor's brushes. Measured on cm03/cm04, 60-65 % of all adjacent
    cliff tiles come from the same group -- the developers drew cliffs as a run
    rather than assembling them cell by cell.
    """
    aus = np.full(n, -1, dtype=np.int16)
    for gi, g in enumerate(m.tile_groups):
        for t in np.asarray(g.mapping_indices).ravel():
            if 0 <= int(t) < n:
                aus[int(t)] = gi
    return aus


def kantensignatur(px: np.ndarray, segmente: int = KANTEN_SEGMENTE) -> np.ndarray:
    """Die vier Raender einer Kachel als Farbmittel je Abschnitt.

    Reihenfolge: Ost, West, Sued, Nord -- jeweils von oben bzw. links gelesen.

    The four borders of a tile as colour means per segment; order east, west,
    south, north, each read from top respectively left.
    """
    def teile(reihe):
        return reihe.reshape(segmente, -1, 3).mean(axis=1)
    return np.stack([teile(px[:, -1]), teile(px[:, 0]),
                     teile(px[-1, :]), teile(px[0, :])])


# Wie viele Pixelreihen tief eine Kante gelesen wird. Eine einzige Reihe ist
# zu wackelig: an einer gesprenkelten Grenze kippt ein Abschnitt schon durch
# ein paar Pixel. Gemessen an den 144 Uebergangskacheln sinken die unmoeglichen
# Muster (mehr als ein Wechsel je Kante) von 9 auf 3 von 576, wenn zwei Reihen
# gelesen werden. Tiefer wird es wieder schlechter, weil der Streifen dann ins
# Kachelinnere greift, wo der andere Boden schon anfaengt.
# How many pixel rows deep an edge is read. A single row is too shaky: on a
# dithered border a segment flips on a few pixels. Measured across the 144
# transition tiles, impossible patterns (more than one change per edge) drop
# from 9 to 3 of 576 when two rows are read. Deeper gets worse again because the
# strip then reaches into the tile interior where the other ground already
# begins.
KANTEN_TIEFE = 2

# In wie viele Abschnitte eine Seite zerlegt wird.
# Into how many segments a side is split.
MUSTER_ABSCHNITTE = 4


def _laeufe(n: int = MUSTER_ABSCHNITTE):
    """Alle Muster mit hoechstens EINEM Wechsel, als Wahrheitswerte."""
    aus = []
    for k in range(n + 1):
        aus.append([False] * k + [True] * (n - k))
        aus.append([True] * k + [False] * (n - k))
    return [tuple(x) for x in {tuple(a) for a in aus}]


def kantenmuster(px: np.ndarray, farbe_a: np.ndarray, farbe_b: np.ndarray,
                 tiefe: int = KANTEN_TIEFE,
                 abschnitte: int = MUSTER_ABSCHNITTE) -> np.ndarray:
    """Je Seite und Abschnitt: gehoert er zu Boden A oder B?

    Reihenfolge der Seiten wie bei `kantensignatur`: Ost, West, Sued, Nord.
    Jede Seite wird von links bzw. oben gelesen, damit zusammengehoerige Kanten
    dieselbe Reihenfolge haben.

    Zwei Schritte:
      1. Jeden Pixel des Randstreifens dem naeheren Boden zuordnen und je
         Abschnitt die Mehrheit nehmen. Den Streifen zu mitteln geht bei
         gesprenkelten Kacheln schief, weil der Mittelwert immer zwischen
         beiden Boeden landet.
      2. Auf ein Muster mit hoechstens EINEM Wechsel zurechtruecken. Eine
         Bodengrenze laeuft an einer Kante von einem Boden zum anderen, mehr
         nicht -- ein Muster wie MMSM kann es nicht geben und ist immer ein
         Messfehler.

    Per side and segment: does it belong to ground A or B? Side order as in
    `kantensignatur`: east, west, south, north, each read from the left resp.
    top so that matching edges share the same order.

    Two steps: (1) assign every pixel of the border strip to the nearer ground
    and take the majority per segment -- averaging the strip fails on dithered
    tiles because the mean always lands between the two grounds; (2) snap to a
    pattern with at most ONE change. A ground border runs from one ground to the
    other along an edge, no more -- a pattern like MMSM cannot exist and is
    always a measurement error.
    """
    seiten = (px[:, -tiefe:][:, ::-1], px[:, :tiefe],
              np.swapaxes(px[-tiefe:, :], 0, 1)[:, ::-1],
              np.swapaxes(px[:tiefe, :], 0, 1))
    gueltig = _laeufe(abschnitte)
    aus = np.zeros((4, abschnitte), dtype=bool)
    for i, feld in enumerate(seiten):
        anteil = np.array([
            float((np.linalg.norm(teil - farbe_b, axis=2)
                   < np.linalg.norm(teil - farbe_a, axis=2)).mean())
            for teil in np.array_split(feld, abschnitte, axis=0)])
        beste = min(gueltig, key=lambda lauf: float(np.abs(
            anteil - np.asarray(lauf, dtype=float)).sum()))
        aus[i] = beste
    return aus


def sammle_muster(m: Op2Map, vol, uebergang: dict, fam_of: dict,
                  n: int) -> np.ndarray:
    """Kantenmuster fuer alle Uebergangskacheln aus den Kachelbildern.

    Reine Kacheln bekommen durchgehend ihre eigene Familie: dort gibt es kein
    Muster zu erkennen, nur Verzierung. Gemessen wuerden sonst 41 von 145
    Sandkacheln erfundene Fels-Abschnitte bekommen, weil ein Kraterschatten
    farblich naeher an Fels liegt als an Sand.

    Edge patterns for all transition tiles, from the tile graphics. Pure tiles
    get their own family throughout: there is no pattern to detect there, only
    decoration. Measured, 41 of 145 sand tiles would otherwise get invented rock
    segments because a crater shadow is closer to rock than to sand in colour.
    """
    import tileset
    saetze = {}
    for src in m.tileset_sources:
        if not src.filename:
            continue
        try:
            saetze[src.filename] = tileset.load_tileset(
                vol.read_file(src.filename + ".bmp"))
        except Exception:
            pass

    def bild(t):
        mp = m.tile_mappings[t]
        if mp.tileset_index >= len(m.tileset_sources):
            return None
        satz = saetze.get(m.tileset_sources[mp.tileset_index].filename)
        if satz is None:
            return None
        px = tileset.get_tile_rgb(satz, mp.tile_graphic_index)
        return None if px is None else px.astype(np.float64)

    # Bodenfarbe je Familie aus GANZEN reinen Kacheln, nicht nur aus deren
    # Raendern -- Raender sind eine schiefe Stichprobe.
    # Ground colour per family from WHOLE pure tiles, not just their borders --
    # borders are a biased sample.
    farbe: dict[str, np.ndarray] = {}
    for fam in set(fam_of.values()):
        werte = []
        for t, f in fam_of.items():
            if f != fam or t in uebergang or not (0 <= t < n):
                continue
            px = bild(t)
            if px is not None:
                werte.append(px.reshape(-1, 3))
            if len(werte) >= 30:
                break
        if len(werte) >= 3:
            farbe[fam] = np.concatenate(werte).mean(axis=0)

    # Boeden ohne reine Kachel -- Lava kommt in den Karten nur als Uebergang
    # vor, es gibt keine reine Lavaflaeche. Die Farbe steckt aber in den
    # Uebergangskacheln selbst: was dort nicht der bekannte Boden ist, ist der
    # gesuchte. Ohne diesen Schritt blieben die 48 Kacheln von `roctola3` ganz
    # ohne Muster.
    # Grounds without a pure tile -- lava occurs in the maps only as a
    # transition, there is no pure lava area. Its colour is in the transition
    # tiles themselves: whatever is not the known ground there is the one we are
    # looking for. Without this step the 48 tiles of `roctola3` stayed without
    # any pattern.
    nach_paar: dict[tuple[str, str], list[int]] = {}
    for t, paar in uebergang.items():
        if 0 <= t < n:
            nach_paar.setdefault(paar, []).append(t)
    for (fa, fb), tiles in nach_paar.items():
        for bekannt, fehlt in ((fa, fb), (fb, fa)):
            if bekannt not in farbe or fehlt in farbe:
                continue
            werte = [bild(t).reshape(-1, 3) for t in tiles[:20]
                     if bild(t) is not None]
            if not werte:
                continue
            alle = np.concatenate(werte)
            d = np.linalg.norm(alle - farbe[bekannt], axis=1)
            # Das aeussere Drittel -- weit genug weg vom bekannten Boden, um
            # den anderen zu treffen, aber kein Einzelausreisser.
            # The outer third -- far enough from the known ground to hit the
            # other one, but not a single outlier.
            fern = alle[d >= np.quantile(d, 2 / 3)]
            if len(fern) >= 50:
                farbe[fehlt] = fern.mean(axis=0)

    aus = np.full((n, 4, MUSTER_ABSCHNITTE), -1, dtype=np.int16)
    familien = sorted(set(fam_of.values())
                      | {f for paar in uebergang.values() for f in paar})
    nummer = {f: i for i, f in enumerate(familien)}
    for t in range(n):
        paar = uebergang.get(t)
        if paar and paar[0] in farbe and paar[1] in farbe:
            px = bild(t)
            if px is None:
                continue
            maske = kantenmuster(px, farbe[paar[0]], farbe[paar[1]])
            aus[t] = np.where(maske, nummer[paar[1]], nummer[paar[0]])
        elif t in fam_of:
            aus[t] = nummer[fam_of[t]]
    return aus


def sammle_kanten(m: Op2Map, vol, segmente: int = KANTEN_SEGMENTE) -> np.ndarray:
    """Kantensignaturen aller Kacheln einer Karte."""
    import tileset
    saetze = {}
    for src in m.tileset_sources:
        if not src.filename:
            continue
        try:
            saetze[src.filename] = tileset.load_tileset(
                vol.read_file(src.filename + ".bmp"))
        except Exception:
            pass
    n = len(m.tile_mappings)
    aus = np.zeros((n, 4, segmente, 3), dtype=np.uint8)
    for t in range(n):
        mp = m.tile_mappings[t]
        if mp.tileset_index >= len(m.tileset_sources):
            continue
        satz = saetze.get(m.tileset_sources[mp.tileset_index].filename)
        if satz is None:
            continue
        px = tileset.get_tile_rgb(satz, mp.tile_graphic_index)
        if px is None or px.shape[0] % segmente:
            continue
        aus[t] = kantensignatur(px.astype(np.float64), segmente).round()
    return aus


def height_field(ct: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Hochland und Tiefland aus den Zelltypen rekonstruieren.

    Klippen trennen die Ebenen, und die Zelltypen sagen, welche Seite oben
    liegt: an einer Hochseite grenzt Hochland, an einer Tiefseite Tiefland.
    Damit laesst sich aus jeder Originalkarte ablesen, WELCHE FORM die
    Entwickler gebaut haben -- und getrennt davon, mit welchen Kacheln.

    Reconstruct highland and lowland from the cell types. Cliffs separate the
    levels and the cell types say which side is up: highland borders a high
    side, lowland a low side. This reads the SHAPE the developers built out of
    every original map, separately from the tiles they used for it.
    """
    from collections import deque, Counter
    h, w = ct.shape
    klippe = np.isin(ct, CLIFF_CELLS)
    H = np.zeros(ct.shape, dtype=np.int8)
    besucht = np.zeros(ct.shape, dtype=bool)
    for sy in range(h):
        for sx in range(w):
            if klippe[sy, sx] or besucht[sy, sx]:
                continue
            q = deque([(sx, sy)])
            besucht[sy, sx] = True
            zellen = []
            stimmen = Counter()
            while q:
                x, y = q.popleft()
                zellen.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if klippe[ny, nx]:
                        stimmen[int(ct[ny, nx])] += 1
                    elif not besucht[ny, nx]:
                        besucht[ny, nx] = True
                        q.append((nx, ny))
            if stimmen[celltypes.CLIFFS_HIGH_SIDE] > stimmen[celltypes.CLIFFS_LOW_SIDE]:
                for x, y in zellen:
                    H[y, x] = 1
    H[ct == celltypes.CLIFFS_HIGH_SIDE] = 1
    H[ct == celltypes.NORTH_CLIFFS] = 1
    return H, klippe


def role_field(ct: np.ndarray, H: np.ndarray, klippe: np.ndarray) -> np.ndarray:
    """Hoehenfeld plus Klippenrollen -- der Kontext fuer die Kachelwahl."""
    rolle = np.where(klippe, 0, H).astype(np.int8)
    rolle[ct == celltypes.NORTH_CLIFFS] = ROLLE_NORD
    rolle[ct == celltypes.CLIFFS_HIGH_SIDE] = ROLLE_HOCHSEITE
    rolle[ct == celltypes.CLIFFS_LOW_SIDE] = ROLLE_TIEFSEITE
    return rolle


def shape_key(fenster: np.ndarray) -> int:
    """5x5-Hoehenfenster als Zahl."""
    k = 0
    for v in fenster.ravel():
        k = (k << 1) | int(v)
    return k


def context_key(fenster: np.ndarray, familie: int) -> int:
    """3x3-Rollenfenster plus Familie als Zahl."""
    k = 0
    for v in fenster.ravel():
        k = k * 5 + int(v)
    return k * 8 + familie


def _cliff_mask(grid: np.ndarray) -> np.ndarray:
    """Alles, was den Weg versperrt: Klippen und unpassierbarer Grund."""
    import celltypes
    sperr = [k for k, v in celltypes.SPEED_CLASS.items()
             if v in ("cliff", "impassable")]
    ct = np.array([[celltypes.default_cell_type(int(t), fallback=0)
                    for t in reihe] for reihe in grid], dtype=np.int32)
    return np.isin(ct, sperr)


def _components(maske: np.ndarray, diagonal: bool = True):
    """Zusammenhaengende Gebiete einer Maske aufzaehlen."""
    from collections import deque
    h, w = maske.shape
    besucht = np.zeros_like(maske)
    nachbarn = ([(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
                if diagonal else [(1, 0), (-1, 0), (0, 1), (0, -1)])
    for sy in range(h):
        for sx in range(w):
            if not maske[sy, sx] or besucht[sy, sx]:
                continue
            q = deque([(sx, sy)])
            besucht[sy, sx] = True
            zellen = []
            while q:
                x, y = q.popleft()
                zellen.append((x, y))
                for dx, dy in nachbarn:
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < w and 0 <= ny < h and maske[ny, nx]
                            and not besucht[ny, nx]):
                        besucht[ny, nx] = True
                        q.append((nx, ny))
            yield zellen


def _dominant_family(grid, x0, y0, x1, y1, fam_of) -> str:
    from collections import Counter
    c = Counter(fam_of.get(int(t), "") for t in grid[y0:y1 + 1, x0:x1 + 1].ravel())
    c.pop("", None)
    return c.most_common(1)[0][0] if c else ""


def _familienrein(grid_teil: np.ndarray, fam: str, fam_of: dict,
                  grenze: float = 0.85, dicke: int = 4) -> bool:
    """Bringt der Ausschnitt fremde Biome mit?

    Beim Setzen wird der Koerper der Struktur kopiert -- Sperrzellen plus
    verdickter Saum. Steckt darin Fremdmaterial, landet es mit auf der Karte:
    ein Tal aus einer Eiskarte hinterliess einen weissen Schneebalken mitten
    in der Wueste. Deshalb hier aussortieren statt spaeter reparieren.

    Does the cutout drag foreign biomes along? Placement copies the body of the
    structure -- blocking cells plus a thickened seam. Foreign material inside
    ends up on the map: a valley from an ice map left a white snow bar in the
    middle of the desert. So sort it out here instead of repairing it later.
    """
    import celltypes
    from collections import Counter
    sperr = [k for k, v in celltypes.SPEED_CLASS.items()
             if v in ("cliff", "impassable")]
    ct = np.array([[celltypes.default_cell_type(int(t), fallback=0)
                    for t in reihe] for reihe in grid_teil], dtype=np.int32)
    maske = np.isin(ct, sperr)
    for _ in range(dicke):
        gewachsen = maske.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                gewachsen |= np.roll(np.roll(maske, dy, axis=0), dx, axis=1)
        maske = gewachsen
    c = Counter(fam_of.get(int(t), "") for t in grid_teil[maske].ravel())
    c.pop("", None)
    gesamt = sum(c.values())
    return bool(gesamt) and c.get(fam, 0) / gesamt >= grenze


def extract_massifs(m: Op2Map, grid: np.ndarray, fam_of: dict,
                    min_cells: int = 120, max_size: int = 56) -> list:
    """Grosse Klippenmassive am Stueck ausschneiden.

    Die 26-Kachel-Grenze der normalen Formationen ist fuer einen Berg zu eng
    -- ein Massiv soll als ein Gebilde lesbar sein, nicht als Haufen kleiner
    Huegel. Deshalb ein eigener Vorrat mit groesserem Rahmen.

    Cut out large cliff massifs in one piece. The 26-tile limit of the normal
    formations is too tight for a mountain -- a massif should read as one
    structure, not as a heap of small hills, hence a separate pool with a
    bigger frame.
    """
    h, w = grid.shape
    out = []
    for zellen in _components(_cliff_mask(grid)):
        if len(zellen) < min_cells:
            continue
        xs = [p[0] for p in zellen]
        ys = [p[1] for p in zellen]
        x0, x1 = max(0, min(xs) - 2), min(w - 1, max(xs) + 2)
        y0, y1 = max(0, min(ys) - 2), min(h - 1, max(ys) + 2)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if bw > max_size or bh > max_size or bw < 8 or bh < 8:
            continue
        teil = grid[y0:y1 + 1, x0:x1 + 1]
        fam = _dominant_family(grid, x0, y0, x1, y1, fam_of)
        if not _familienrein(teil, fam, fam_of):
            continue
        out.append((bw, bh, teil.astype(np.int32).ravel().tolist(), fam))
    return out


def extract_valleys(m: Op2Map, grid: np.ndarray, fam_of: dict,
                    min_cells: int = 40, max_size: int = 56) -> list:
    """Taeler samt beider Waende ausschneiden.

    Ein Tal ist in OP2 kein Bauteil, sondern der freie Korridor zwischen zwei
    Waenden. Aus Kantenstuecken laesst er sich nicht zusammensetzen (der
    erste Versuch ergab verstreute Klippen statt einer Schlucht) -- in den
    Originalkarten steckt er aber fertig drin, in 31 von 33.

    Cut out valleys including both walls. In OP2 a valley is not a building
    block but the free corridor between two walls. It cannot be assembled from
    edge pieces (the first attempt gave scattered cliffs instead of a canyon),
    but 31 of the 33 original maps contain finished ones.
    """
    sperr = _cliff_mask(grid)
    h, w = sperr.shape
    reichweite = 10
    oben = np.zeros_like(sperr); unten = np.zeros_like(sperr)
    links = np.zeros_like(sperr); rechts = np.zeros_like(sperr)
    for d in range(1, reichweite + 1):
        oben[d:, :] |= sperr[:-d, :]
        unten[:-d, :] |= sperr[d:, :]
        links[:, d:] |= sperr[:, :-d]
        rechts[:, :-d] |= sperr[:, d:]
    korridor = (~sperr) & ((oben & unten) | (links & rechts))
    out = []
    for zellen in _components(korridor, diagonal=False):
        if len(zellen) < min_cells:
            continue
        xs = [p[0] for p in zellen]
        ys = [p[1] for p in zellen]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if max(bw, bh) < 20 or max(bw, bh) / max(1, min(bw, bh)) < 1.5:
            continue
        # Rand mitnehmen, sonst fehlen die Waende, die das Tal ausmachen.
        # Include a margin, otherwise the walls that make the valley are missing.
        rand = reichweite + 2
        x0, x1 = max(0, min(xs) - rand), min(w - 1, max(xs) + rand)
        y0, y1 = max(0, min(ys) - rand), min(h - 1, max(ys) + rand)
        if x1 - x0 + 1 > max_size or y1 - y0 + 1 > max_size:
            continue
        teil = grid[y0:y1 + 1, x0:x1 + 1]
        fam = _dominant_family(grid, x0, y0, x1, y1, fam_of)
        if not _familienrein(teil, fam, fam_of):
            continue
        out.append((x1 - x0 + 1, y1 - y0 + 1,
                    teil.astype(np.int32).ravel().tolist(), fam,
                    "h" if bw >= bh else "v"))
    return out


def extract_formations(m: Op2Map, grid: np.ndarray, fam_of: dict,
                        min_cliff: int = 25, max_size: int = 26) -> list:
    """Zusammenhaengende Klippen-Gebilde als fertige Stempel ausschneiden.

    Die Kantenstuecke der TileGroups lassen sich nicht zu ueberzeugenden Mesas
    verketten -- die Originalkarten enthalten aber fertige Formationen. Die
    werden hier mitsamt Rand ausgeschnitten und spaeter am Stueck gesetzt,
    genau wie die Vulkanstempel.

    Cut out connected cliff formations as ready-made stamps. The TileGroup
    edge pieces cannot be chained into convincing mesas, but the original maps
    contain finished formations -- extracted here with their surroundings and
    later placed in one piece, just like the volcano stamps.
    """
    import celltypes
    h, w = grid.shape
    cliff = np.zeros(grid.shape, dtype=bool)
    for tile in np.unique(grid):
        if celltypes.default_cell_type(int(tile), fallback=-1) in (8, 9, 10):
            cliff |= grid == tile
    besucht = np.zeros_like(cliff)
    out = []
    for sy in range(h):
        for sx in range(w):
            if not cliff[sy, sx] or besucht[sy, sx]:
                continue
            stack = [(sx, sy)]
            besucht[sy, sx] = True
            zellen = []
            while stack:
                x, y = stack.pop()
                zellen.append((x, y))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if (0 <= nx < w and 0 <= ny < h and cliff[ny, nx]
                                and not besucht[ny, nx]):
                            besucht[ny, nx] = True
                            stack.append((nx, ny))
            if len(zellen) < min_cliff:
                continue
            xs = [p[0] for p in zellen]
            ys = [p[1] for p in zellen]
            # Rand mitnehmen: die Formation braucht ihren Fuss und ihr Plateau.
            # Include a margin: the formation needs its foot and its plateau.
            x0, x1 = max(0, min(xs) - 2), min(w - 1, max(xs) + 2)
            y0, y1 = max(0, min(ys) - 2), min(h - 1, max(ys) + 2)
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            if bw > max_size or bh > max_size or bw < 5 or bh < 5:
                continue
            block = grid[y0:y1 + 1, x0:x1 + 1].astype(np.int32)
            # Familie der Formation = haeufigste Familie ihrer Kacheln. Ohne
            # die landet eine Erd-Mesa mitten im Sand und schleppt ihren
            # fremden Untergrund mit.
            # Family of the formation = most common family of its tiles.
            # Without it a dirt mesa ends up in the middle of sand, dragging
            # its foreign ground along.
            zaehler = {}
            for t in block.ravel().tolist():
                fam = fam_of.get(int(t))
                if fam:
                    zaehler[fam] = zaehler.get(fam, 0) + 1
            fam = max(zaehler, key=zaehler.get) if zaehler else ""
            out.append((bw, bh, block.ravel().tolist(), fam))
    return out


def kachelfeld(m: Op2Map) -> np.ndarray:
    """Die Kachelindizes einer Karte als Feld (Hoehe x Breite).

    OP2 legt die Kacheln in senkrechten 32er-Streifen ab; ausgerollt ergibt
    das [Streifen, y, x-innerhalb] und damit nach einem Tausch das Feld.

    A map's tile indices as an array. OP2 stores tiles in vertical 32-column
    strips; unrolled that is [strip, y, x-within], one transpose from the field.
    """
    streifen = np.asarray(m.tiles).reshape(-1, m.height, 32)
    feld = streifen.transpose(1, 0, 2).reshape(m.height, -1)
    return ((feld[:, :m.width] >> CELL_TYPE_BITS)
            & MAPPING_INDEX_MASK).astype(np.int32)


def training_maps(game_dir: Path, campaign_only: bool = True) -> list[Path]:
    """Karten fuers Anlernen auswaehlen (ohne Altkopien, optional nur Kampagne)."""
    maps = [p for p in sorted(set(game_dir.rglob("*.map")))
            if "MonoBleedingEdge" not in str(p) and "backups" not in str(p).lower()]
    if campaign_only:
        maps = [p for p in maps if CAMPAIGN_PATTERN.match(p.stem)]
    return maps


def _packe_randkacheln(tab: dict) -> dict:
    """(Paar, Richtung) -> die richtungstypischen Kacheln, als flache Felder."""
    paare = sorted({paar for paar, _ in tab})
    # Eine Kachel bleibt in JEDER Richtung, in der sie vorkam. Zwei Versuche,
    # das zu schaerfen -- die untypischen aussortieren, dann sie nur schwaecher
    # gewichten -- haben die Fehlpaare von 3,88 auf 6,24 bzw. 5,98 % erhoeht.
    # Die Entwickler benutzen dieselbe Kachel tatsaechlich in mehreren
    # Richtungen; wer das wegfiltert, nimmt der Nachbarschaftsloesung die Luft.
    # A tile stays in EVERY direction it appeared in. Two attempts to sharpen
    # this -- dropping the untypical ones, then merely down-weighting them --
    # raised bad pairs from 3.88 to 6.24 and 5.98 % respectively. The
    # developers really do use the same tile in several directions; filtering
    # that away starves the adjacency solve.
    faelle = []
    for i, paar in enumerate(paare):
        for r in range(8):
            eintrag = tab.get((paar, r))
            if not eintrag:
                continue
            faelle.append((i * 8 + r,
                           eintrag.most_common(RAND_KACHELN_JE_FALL)))
    faelle.sort(key=lambda t: t[0])
    schluessel, tiles, counts, offsets = [], [], [], []
    for schl, eintraege in faelle:
        schluessel.append(schl)
        offsets.append(len(tiles))
        for kachel, n in eintraege:
            tiles.append(kachel)
            counts.append(n)
    offsets.append(len(tiles))
    return {
        "border_pairs": np.array([f"{a}|{b}" for a, b in paare] or [""], dtype="<U8"),
        "border_keys": np.array(schluessel or [0], dtype=np.int64),
        "border_offsets": np.array(offsets if schluessel else [0, 0], dtype=np.int32),
        "border_tiles": np.array(tiles or [0], dtype=np.int32),
        "border_counts": np.array(counts or [0], dtype=np.int32),
    }


def _mischgrad_quantile(uebergang: dict, summe: dict, usage) -> np.ndarray:
    """Verteilung der tatsaechlich benutzten Mischgrade, als 33 Quantile."""
    werte, gewichte = [], []
    for tile in sorted(uebergang):
        if tile not in summe or not summe[tile][1]:
            continue
        werte.append(summe[tile][0] / summe[tile][1])
        gewichte.append(int(usage.get(tile, 0)))
    if not werte or not sum(gewichte):
        return np.linspace(0.0, 1.0, 33).astype(np.float32)
    ordnung = np.argsort(werte)
    w = np.array(werte, dtype=np.float64)[ordnung]
    g = np.array(gewichte, dtype=np.float64)[ordnung]
    kumuliert = np.cumsum(g) / g.sum()
    ziel = np.linspace(0.0, 1.0, 33)
    return np.interp(ziel, kumuliert, w).astype(np.float32)


def lerne_mischgrad(grid: np.ndarray, uebergang: dict, fam_of: dict,
                    summe: dict) -> None:
    """Wie weit "drueben" liegt eine Uebergangskachel?

    Eine Uebergangstafel ist ein Verlauf: oben fast nur Bodenart A, unten fast
    nur B. Welche Kachel welchem Mischgrad entspricht, steht nirgends -- also
    wird es aus den Karten abgelesen: der Anteil von B in der Nachbarschaft,
    ueber alle Vorkommen gemittelt.

    How far "across" is a transition tile? A transition palette is a ramp --
    mostly ground A at the top, mostly B at the bottom. Which tile matches
    which blend level is written down nowhere, so it is read off the maps: the
    share of B in the neighbourhood, averaged over all occurrences.
    """
    h, w = grid.shape
    for y in range(2, h - 2):
        for x in range(2, w - 2):
            paar = uebergang.get(int(grid[y, x]))
            if paar is None:
                continue
            a = b = 0
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    f = fam_of.get(int(grid[y + dy, x + dx]))
                    if f == paar[0]:
                        a += 1
                    elif f == paar[1]:
                        b += 1
            if a + b:
                eintrag = summe.setdefault(int(grid[y, x]), [0.0, 0])
                eintrag[0] += b / (a + b)
                eintrag[1] += 1


# Wie viele Kacheln je Fall (Bodenpaar x Richtung) vorgehalten werden.
# Weniger Auswahl heisst gleichmaessigere Kante: bei 16 (87 % Abdeckung im
# Original) wirkte die Grenze noch unruhig, bei 6 greifen benachbarte Zellen
# oefter zur selben Kachel und die Kante liest sich als Linie.
# How many tiles are kept per case (ground pair x direction). Less choice
# means a more even edge: at 16 (87 % coverage in the originals) the border
# still looked restless; at 6 neighbouring cells reach for the same tile more
# often and the edge reads as a line.
RAND_KACHELN_JE_FALL = 40


def grenz_richtung(ist_a: np.ndarray, y: int, x: int) -> int | None:
    """In welche Richtung faellt der Anteil von Boden A ab?

    Der entscheidende Hinweis, welche Uebergangskachel hingehoert: eine
    Nordkante sieht anders aus als eine Ostkante. Ohne die Richtung bleiben
    je Bodenpaar hunderte Kacheln zur Auswahl und die Grenze wird zu Rauschen;
    mit ihr sind es 33, von denen 16 reichen.

    In which direction does the share of ground A fall off? The decisive hint
    for which transition tile belongs here: a north edge looks different from
    an east edge. Without the direction hundreds of tiles remain per ground
    pair and the border turns into noise; with it there are 33, of which 16
    suffice.
    """
    f = ist_a[y - 2:y + 3, x - 2:x + 3].astype(np.float64)
    if f.shape != (5, 5):
        return None
    gy = float(f[3:, :].sum() - f[:2, :].sum())
    gx = float(f[:, 3:].sum() - f[:, :2].sum())
    if gx == 0.0 and gy == 0.0:
        return None
    winkel = np.degrees(np.arctan2(gy, gx)) % 360.0
    return int((winkel + 22.5) // 45) % 8


def lerne_randkacheln(grid: np.ndarray, uebergang: dict, fam_of: dict,
                      tab: dict) -> None:
    """Welche Kachel benutzt das Original an einer Grenze dieser Richtung?"""
    h, w = grid.shape
    familien = {}
    for f in set(fam_of.values()):
        familien[f] = np.array([[fam_of.get(int(t), "") == f for t in reihe]
                                for reihe in grid], dtype=bool)
    for y in range(3, h - 3):
        for x in range(3, w - 3):
            paar = uebergang.get(int(grid[y, x]))
            if paar is None or paar[0] not in familien:
                continue
            r = grenz_richtung(familien[paar[0]], y, x)
            if r is None:
                continue
            tab.setdefault((paar, r), Counter())[int(grid[y, x])] += 1


def learn_shapes(grid: np.ndarray, fam_of: dict, zelltyp_tab: dict,
                 kachel_tab: dict, grob_tab: dict,
                 kachel_tab5: dict | None = None) -> None:
    """Aus einer Originalkarte lernen, wie Form zu Kacheln wird.

    Zwei Tabellen: welchen Zelltyp bekommt eine Stelle bei gegebener Form
    (5x5-Hoehenfenster), und welche Kachel passt zu einem Rollenumfeld
    (3x3) in einer Familie. Zusammen ersetzen sie das Kopieren von
    Ausschnitten -- die Form wird frei erzeugt, die Kacheln nachgeschlagen.

    Learn from an original map how shape turns into tiles. Two tables: which
    cell type a spot gets for a given shape (5x5 height window), and which tile
    fits a role neighbourhood (3x3) within a family. Together they replace
    copying cutouts -- the shape is generated freely, the tiles looked up.
    """
    from collections import Counter
    ct = np.array([[celltypes.default_cell_type(int(t), fallback=0)
                    for t in reihe] for reihe in grid], dtype=np.int32)
    H, klippe = height_field(ct)
    rolle = role_field(ct, H, klippe)
    familien = sorted({v for v in fam_of.values()})
    fam_idx = {name: i for i, name in enumerate(familien)}
    h, w = H.shape
    for y in range(2, h - 2):
        for x in range(2, w - 2):
            fenster = H[y - 2:y + 3, x - 2:x + 3]
            if klippe[y, x] or (fenster != H[y, x]).any():
                schl = shape_key(fenster)
                zelltyp_tab.setdefault(schl, Counter())[
                    int(ct[y, x]) if klippe[y, x] else -1] += 1
            if klippe[y, x]:
                fam = fam_idx.get(fam_of.get(int(grid[y, x]), ""), 7)
                schl = context_key(rolle[y - 1:y + 2, x - 1:x + 2], fam)
                kachel_tab.setdefault(schl, Counter())[int(grid[y, x])] += 1
                # Rueckfall: kennt die Tabelle das genaue Umfeld nicht, muss
                # wenigstens eine Kachel des richtigen Zelltyps her -- sonst
                # bleibt ein Loch in der Wand.
                # Fallback: if the table does not know the exact surroundings,
                # at least a tile of the right cell type is needed, otherwise a
                # hole remains in the wall.
                grob_tab.setdefault(int(ct[y, x]) * 8 + fam,
                                    Counter())[int(grid[y, x])] += 1
                # Zusaetzlich ein 5x5-Fenster. An vier zurueckgehaltenen
                # Karten gemessen trifft die Kette 5x5 -> 3x3 die
                # Originalkachel 7,6 Punkte haeufiger als 3x3 allein. 7x7
                # bringt nur noch 0,5 Punkte bei doppelt so vielen Mustern --
                # deshalb ist bei 5x5 Schluss.
                # Additionally a 5x5 window. Measured on four held-out maps,
                # the chain 5x5 -> 3x3 hits the original tile 7.6 points more
                # often than 3x3 alone; 7x7 adds only 0.5 points at twice the
                # pattern count, so 5x5 is where it stops.
                if kachel_tab5 is not None and 2 <= y < h - 2 and 2 <= x < w - 2:
                    schl5 = context_key(rolle[y - 2:y + 3, x - 2:x + 3], fam)
                    kachel_tab5.setdefault(schl5, Counter())[int(grid[y, x])] += 1


def learn(game_dir: Path, campaign_only: bool = True) -> dict:
    right: dict[int, Counter] = defaultdict(Counter)
    down: dict[int, Counter] = defaultdict(Counter)
    usage: Counter = Counter()
    fam_of: dict[int, str] = {}
    base_tiles: set[int] = set()
    structure_tiles: set[int] = set()
    deko_tiles: set[int] = set()
    lava_tiles: set[int] = set()
    volcanoes: dict[str, tuple[int, int, list[int]]] = {}
    formations: list = []
    massifs: list = []
    valleys: list = []
    form_zelltyp: dict = {}      # 5x5-Hoehenmuster -> Zelltyp
    form_kachel: dict = {}       # 3x3-Rollenmuster+Familie -> Kacheln
    form_kachel5: dict = {}      # dasselbe mit 5x5-Fenster
    uebergang: dict[int, tuple[str, str]] = {}   # Kachel -> Paar
    randkacheln: dict = {}       # (Paar, Richtung) -> Kacheln
    misch_summe: dict[int, list] = {}            # Kachel -> [Summe, Anzahl]
    grob_kachel: dict = {}       # Rueckfall: Zelltyp+Familie -> Kacheln
    cliffs: dict[str, tuple[int, int, list[int]]] = {}
    details: dict[str, tuple[int, int, list[int], str]] = {}

    maps = training_maps(game_dir, campaign_only)
    used = 0
    kanten = None
    gruppen = None
    muster = None
    for path in maps:
        try:
            m = Op2Map(path.read_bytes())
        except Exception:
            continue
        used += 1
        if gruppen is None:
            gruppen = gruppe_je_kachel(m, len(m.tile_mappings))
        if muster is None and uebergang and fam_of:
            # Nach dem Durchlauf der Gruppen: erst dann stehen Uebergaenge und
            # Familien dieser Karte fest.
            # After the group loop: only then are this map's transitions and
            # families known.
            try:
                from vol import VolFile
                muster = sammle_muster(
                    m, VolFile(str(next(game_dir.rglob("maps.vol")))),
                    uebergang, fam_of, len(m.tile_mappings))
            except Exception:
                muster = None
        if kanten is None:
            # Die Kantenfarben stehen im Kachelsatz, nicht in den Karten --
            # einmal von der ersten Karte lesen genuegt.
            # The edge colours live in the tileset, not in the maps -- reading
            # them once from the first map is enough.
            try:
                from vol import VolFile
                kanten = sammle_kanten(m, VolFile(str(next(
                    game_dir.rglob("maps.vol")))))
            except Exception:
                kanten = None
        for group in m.tile_groups:
            name = group.name
            if not name.isascii():
                continue
            low = name.lower()
            indices = [int(i) for i in group.mapping_indices]
            # Verbundgruppe: nennt zwei Boeden, ist aber kein Uebergang. Das
            # sind Mauern gegen Lava (`sanlavw`) und Felsbrocken auf Schnee
            # (`snowroc1..9`) -- Bauwerk, kein Gelaende. Die Entscheidung muss
            # VOR der Aufteilung fallen: `structure_only` zieht spaeter alles
            # ab, was auch in einer Flaechengruppe vorkam, und dort waeren sie
            # sonst gelandet.
            # Compound group: names two grounds but is not a transition. Those
            # are walls against lava (`sanlavw`) and boulders on snow
            # (`snowroc1..9`) -- structure, not terrain. The decision has to be
            # made BEFORE the split: `structure_only` later subtracts everything
            # that also appeared in a surface group, which is where they would
            # otherwise have gone.
            # Streugut ausgenommen: `mudrock2` nennt zwei Boeden und hat kein
            # "to", meint aber Felsbrocken AUF Erde -- die setzt das Streugut
            # absichtlich und sie sind laengst als solches erfasst.
            # Scatter excluded: `mudrock2` names two grounds and has no "to"
            # but means boulders ON dirt -- placed deliberately by the scatter
            # pass and long since recorded as such.
            # `rocroc1..4` nennt zweimal denselben Boden: Fels AUF Fels, also
            # Verzierung. `familien_im_namen` sieht dort nur eine Familie und
            # liess sie deshalb als Grundboden durchgehen -- der Sampler setzte
            # sie frei ins Gelaende, wo sie als Felsbrocken auffallen. Das
            # Gegenstueck `mudrock*` war ueber DETAIL_MARKERS laengst erfasst.
            # `rocroc1..4` names the same ground twice: rock ON rock, i.e.
            # decoration. `familien_im_namen` only sees one family there and so
            # let them pass as base ground -- the sampler placed them freely in
            # the terrain where they stand out as boulders. Their counterpart
            # `mudrock*` had long been covered via DETAIL_MARKERS.
            doppelt = (len(low) >= 6 and low[:3] in FAMILY_PREFIXES
                       and low[3:6] in FAMILY_PREFIXES
                       and FAMILY_PREFIXES[low[:3]] == FAMILY_PREFIXES[low[3:6]])
            # `doppelt` gehoert NICHT hierher: solche Gruppen kommen unten in
            # den Streugut-Vorrat, und Streugut wird ohnehin nicht frei
            # gesetzt. Zusaetzlich als Bauteil zu zaehlen waere doppelt und
            # laesst die Pruefung "ausser den Vulkanen keine Bauteile" anschlagen.
            # `doppelt` does NOT belong here: such groups go into the scatter
            # pool below, and scatter is never placed freely anyway. Counting
            # them as structure on top would be redundant and trips the check
            # "no building blocks apart from the volcanoes".
            ist_verbund = (len(familien_im_namen(low)) >= 2
                           and "to" not in low
                           and not any(k in low for k in DETAIL_MARKERS))
            if ist_verbund or any(marker in low for marker in STRUCTURE_MARKERS):
                structure_tiles.update(indices)
            else:
                base_tiles.update(indices)
            if any(marker in low for marker in LAVA_MARKERS):
                lava_tiles.update(indices)
            if VOLCANO_MARKER in low and name not in volcanoes:
                volcanoes[name] = (group.width, group.height, indices)
            if CLIFF_MARKER in low and name not in cliffs:
                cliffs[name] = (group.width, group.height, indices)
            if ((any(k in low for k in DETAIL_MARKERS) or doppelt)
                    and name not in details
                    and group.width * group.height <= 20):
                details[name] = (group.width, group.height, indices, low[:3])
            # Uebergangssaetze zuerst: `roctomud` faengt mit "roc" an, waere
            # nach Praefix also reiner Fels. Genau daran sind alle 342
            # Uebergangskacheln als normaler Boden in den Streupools gelandet
            # -- Felsflecken mitten im Sand, und an den echten Grenzen eine
            # harte Kante statt einer Mischzone.
            # Transition sets first: `roctomud` starts with "roc" and would be
            # classified as pure rock by prefix. That is exactly how all 342
            # transition tiles ended up in the scatter pools as ordinary
            # ground -- rock speckles in the middle of sand, and a hard edge
            # instead of a blend at the real borders.
            gefunden = familien_im_namen(low)
            # Streugut ausnehmen: `mudrock2` nennt zwar zwei Boeden, meint
            # aber Felsbrocken AUF Erde, nicht den Uebergang dorthin. Ohne
            # diese Ausnahme landeten 8 unpassierbare Brocken im mud|roc-Satz
            # und wurden entlang jeder Erde-Fels-Grenze gestreut.
            # Exclude scatter: `mudrock2` does name two grounds but means
            # boulders ON dirt, not the transition to it. Without this
            # exception 8 impassable boulders ended up in the mud|roc set and
            # were scattered along every dirt-rock border.
            ist_streugut = any(k in low for k in DETAIL_MARKERS) or doppelt
            if ist_streugut:
                # Alle Kacheln solcher Gruppen merken, nicht nur die, die es in
                # den Stempelvorrat schaffen. Fuenf Einzelkacheln aus
                # `mudcrk7/9/10` und `mudrock3/4` blieben sonst frei setzbar,
                # obwohl ihre Gruppe klar Verzierung ist -- sie kamen nie in den
                # Vorrat, weil dort je Name nur ein Stempel landet.
                # Remember all tiles of such groups, not only those that make it
                # into the stamp pool. Five single tiles from `mudcrk7/9/10` and
                # `mudrock3/4` stayed freely placeable although their group is
                # clearly decoration -- they never entered the pool because only
                # one stamp per name is kept there.
                deko_tiles.update(indices)
            # Zwei Boeden im Namen reichen NICHT. Die Entwickler schreiben
            # einen Uebergang aus: `santoroc` heisst woertlich sand-to-rock.
            # Ohne dieses Wort nennt ein Name zwar zwei Boeden, meint aber
            # etwas anderes -- `sanlavw` ist eine Mauer gegen Lava (16x1, ein
            # Mauerstreifen), `snowroc1..9` sind Felsbrocken auf Schnee.
            #
            # Ueber alle 33 Karten trennt das sauber: 4 Gruppen tragen `to`
            # (roctomud, santomud, santoroc, roctola3, alle 6x8) und sind die
            # echten Uebergaenge; 19 nennen zwei Boeden ohne `to` und sind
            # Mauern, Brocken oder Sonstiges. Ohne die Unterscheidung landeten
            # 214 dieser Kacheln in der Uebergangstabelle -- und die Vorlage
            # "ice" streute daraus 1228 unpassierbare Felsbrocken je Karte als
            # angebliche Schnee-Fels-Mischung.
            #
            # Two grounds in the name are NOT enough. The developers spell a
            # transition out: `santoroc` literally means sand-to-rock. Without
            # that word a name may mention two grounds but mean something else
            # -- `sanlavw` is a wall against lava (16x1, a wall strip),
            # `snowroc1..9` are boulders on snow.
            #
            # Across all 33 maps this separates cleanly: 4 groups carry `to`
            # (roctomud, santomud, santoroc, roctola3, all 6x8) and are the real
            # transitions; 19 name two grounds without `to` and are walls,
            # boulders or other things. Without the distinction 214 of those
            # tiles ended up in the transition table -- and the "ice" template
            # scattered 1228 impassable boulders per map from it as a supposed
            # snow-rock blend.
            ist_uebergang_name = "to" in low
            if (len(gefunden) >= 2 and group.width * group.height >= 6
                    and not ist_streugut and ist_uebergang_name):
                paar = tuple(sorted(gefunden[:2]))
                for i in indices:
                    uebergang[i] = paar
            else:
                fam = FAMILY_PREFIXES.get(low[:3])
                if fam:
                    for i in indices:
                        fam_of.setdefault(i, fam)
        g = tile_grid(m)
        for a, b in zip(g[:, :-1].ravel(), g[:, 1:].ravel()):
            right[int(a)][int(b)] += 1
        for a, b in zip(g[:-1, :].ravel(), g[1:, :].ravel()):
            down[int(a)][int(b)] += 1
        usage.update(g.ravel().tolist())
        lerne_mischgrad(g, uebergang, fam_of, misch_summe)
        lerne_randkacheln(g, uebergang, fam_of, randkacheln)
        formations.extend(extract_formations(m, g, fam_of))
        massifs.extend(extract_massifs(m, g, fam_of))
        valleys.extend(extract_valleys(m, g, fam_of))
        learn_shapes(g, fam_of, form_zelltyp, form_kachel, grob_kachel,
                     form_kachel5)

    # Uebergangskacheln gehoeren keiner reinen Familie an und duerfen nicht
    # frei gestreut werden -- sie kommen nur an Grenzen zum Einsatz.
    # Transition tiles belong to no pure family and must not be scattered
    # freely; they are only used along borders.
    for i in uebergang:
        fam_of.pop(i, None)
    structure_tiles.update(uebergang)

    # Auch Boeden aufnehmen, die nur in Uebergaengen vorkommen: Lava hat
    # keine reine Kachel, muss aber benennbar bleiben.
    # Include grounds that only occur in transitions: lava has no pure
    # tile but must stay nameable.
    families = sorted(set(fam_of.values())
                      | {f for paar in uebergang.values() for f in paar})
    fam_index = {name: i for i, name in enumerate(families)}

    def pairs(table) -> np.ndarray:
        rows = [(a, b, n) for a, counter in table.items() for b, n in counter.items()]
        return np.array(rows, dtype=np.int32)

    # Nur Kacheln, die AUSSCHLIESSLICH in Struktur-Gruppen vorkommen, gelten
    # als Bauteil -- alles, was auch in einer Flaechen-Gruppe auftaucht,
    # bleibt normales Gelaende.
    # Only tiles that appear EXCLUSIVELY in structure groups count as building
    # blocks -- anything also present in a surface group stays normal terrain.
    structure_only = sorted(structure_tiles - base_tiles)

    def pack(stamps: dict) -> tuple:
        names, sizes, flat, offsets = [], [], [], []
        for name, (w, h, indices) in sorted(stamps.items()):
            names.append(name)
            sizes.append((w, h))
            offsets.append(len(flat))
            flat.extend(indices)
        offsets.append(len(flat))
        return (np.array(names if names else [""]),
                np.array(sizes if sizes else [(0, 0)], dtype=np.int32),
                np.array(flat if flat else [0], dtype=np.int32),
                np.array(offsets, dtype=np.int32))

    def pack_list(items):
        sizes, flat, offsets, fams = [], [], [], []
        for w_, h_, tiles, fam in items:
            sizes.append((w_, h_))
            offsets.append(len(flat))
            flat.extend(tiles)
            fams.append(fam)
        offsets.append(len(flat))
        return (np.array(sizes if sizes else [(0, 0)], dtype=np.int32),
                np.array(flat if flat else [0], dtype=np.int32),
                np.array(offsets, dtype=np.int32),
                np.array(fams if fams else [""]))

    f_sizes, f_tiles, f_offsets, f_fams = pack_list(formations)
    f_class = np.array(
        [classify_formation(np.array(t).reshape(h_, w_))
         for w_, h_, t, _ in formations] or [""], dtype="<U8")
    f_dir = np.array(
        [formation_direction(np.array(t).reshape(h_, w_))
         for w_, h_, t, _ in formations] or [""], dtype="<U2")
    # Formtabellen packen
    schl_form = np.array(sorted(form_zelltyp), dtype=np.int64) if form_zelltyp else np.zeros(1, np.int64)
    wert_form = np.array([form_zelltyp[k].most_common(1)[0][0] for k in schl_form],
                         dtype=np.int16) if form_zelltyp else np.zeros(1, np.int16)
    schl_ctx = sorted(form_kachel)
    ctx_tiles, ctx_counts, ctx_off = [], [], []
    for k in schl_ctx:
        ctx_off.append(len(ctx_tiles))
        for kachel, n in form_kachel[k].most_common():
            ctx_tiles.append(kachel)
            ctx_counts.append(n)
    ctx_off.append(len(ctx_tiles))
    schl_ctx = np.array(schl_ctx, dtype=np.int64) if schl_ctx else np.zeros(1, np.int64)
    schl_ctx5 = sorted(form_kachel5)
    ctx5_tiles, ctx5_counts, ctx5_off = [], [], []
    for k in schl_ctx5:
        ctx5_off.append(len(ctx5_tiles))
        for kachel, n in form_kachel5[k].most_common():
            ctx5_tiles.append(kachel)
            ctx5_counts.append(n)
    ctx5_off.append(len(ctx5_tiles))
    schl_ctx5 = (np.array(schl_ctx5, dtype=np.int64) if schl_ctx5
                 else np.zeros(1, np.int64))

    schl_grob = sorted(grob_kachel)
    grob_tiles, grob_counts, grob_off = [], [], []
    for k in schl_grob:
        grob_off.append(len(grob_tiles))
        for kachel, n in grob_kachel[k].most_common():
            grob_tiles.append(kachel)
            grob_counts.append(n)
    grob_off.append(len(grob_tiles))
    schl_grob = np.array(schl_grob, dtype=np.int64) if schl_grob else np.zeros(1, np.int64)

    m_sizes, m_tiles, m_offsets, m_fams = pack_list(massifs)
    v2_sizes, v2_tiles, v2_offsets, v2_fams = pack_list(
        [(w_, h_, t, f) for w_, h_, t, f, _ in valleys])
    v2_axis = np.array([a for *_, a in valleys] or [""], dtype="<U1")
    d_sizes, d_tiles, d_offsets, d_fams = pack_list(
        [(w_, h_, t, fam) for w_, h_, t, fam in details.values()])
    v_names, v_sizes, v_tiles, v_offsets = pack(volcanoes)
    c_names, c_sizes, c_tiles, c_offsets = pack(cliffs)

    # Die Nachbarschaft der Klippengruppen steht bewusst NICHT hier, sondern in
    # `learn_cliffs.py` mit eigener Modelldatei. Sie braucht eine andere
    # Aufloesung -- Gruppe statt Kachel, mit Versatz -- und soll an dieser
    # durchgemessenen Kachelstatistik nicht ruetteln koennen.
    # The cliff group adjacency deliberately does NOT live here but in
    # `learn_cliffs.py` with its own model file: it needs a different
    # resolution -- group instead of tile, with offset -- and must not be able
    # to disturb this measured tile statistic.

    return {
        "right": pairs(right),
        "down": pairs(down),
        "usage": np.array(sorted(usage.items()), dtype=np.int32),
        "family": np.array(sorted((t, fam_index[f]) for t, f in fam_of.items()),
                           dtype=np.int32),
        "families": np.array(families),
        "structure": np.array(structure_only, dtype=np.int32),
        "deko": np.array(sorted(deko_tiles), dtype=np.int32),
        "lava": np.array(sorted(lava_tiles), dtype=np.int32),
        "volcano_names": v_names, "volcano_sizes": v_sizes,
        "volcano_tiles": v_tiles, "volcano_offsets": v_offsets,
        "detail_sizes": d_sizes, "detail_tiles": d_tiles,
        "detail_offsets": d_offsets, "detail_families": d_fams,
        "shape_keys": schl_form, "shape_cells": wert_form,
        "ctx_keys": schl_ctx,
        **_packe_randkacheln(randkacheln),
        "gruppen": (gruppen if gruppen is not None
                    else np.full(1, -1, dtype=np.int16)),
        "muster": (muster if muster is not None
                   else np.full((1, 4, MUSTER_ABSCHNITTE), -1, dtype=np.int16)),
        "kanten": (kanten if kanten is not None
                   else np.zeros((1, 4, KANTEN_SEGMENTE, 3), dtype=np.uint8)),
        "trans_tiles": (np.array(sorted(uebergang), dtype=np.int32)
                        if uebergang else np.zeros(1, np.int32)),
        "trans_a": np.array([uebergang[i][0] for i in sorted(uebergang)]
                            or [""], dtype="<U3"),
        "trans_b": np.array([uebergang[i][1] for i in sorted(uebergang)]
                            or [""], dtype="<U3"),
        # Wie oft welcher Mischgrad im Original vorkommt, als Quantile.
        # Ohne das greift der Generator systematisch zu den dichtesten
        # Kacheln -- an einer Grenze ist der gemessene Anteil ja rund 0,5 --
        # und die Uebergaenge wirken viel zu grob.
        # How often each blend level occurs in the originals, as quantiles.
        # Without this the generator systematically picks the densest tiles --
        # at a border the measured share is around 0.5 -- and the transitions
        # look far too coarse.
        "trans_quantile": _mischgrad_quantile(uebergang, misch_summe, usage),
        "trans_mix": np.array(
            [(misch_summe[i][0] / misch_summe[i][1]) if i in misch_summe else 0.5
             for i in sorted(uebergang)] or [0.5], dtype=np.float32),
        "ctx5_keys": schl_ctx5,
        "ctx5_offsets": np.array(ctx5_off, dtype=np.int32),
        "ctx5_tiles": np.array(ctx5_tiles or [0], dtype=np.int32),
        "ctx5_counts": np.array(ctx5_counts or [0], dtype=np.int32),
        "grob_keys": schl_grob,
        "grob_offsets": np.array(grob_off, dtype=np.int32),
        "grob_tiles": np.array(grob_tiles or [0], dtype=np.int32),
        "grob_counts": np.array(grob_counts or [0], dtype=np.int32),
        "ctx_offsets": np.array(ctx_off, dtype=np.int32),
        "ctx_tiles": np.array(ctx_tiles or [0], dtype=np.int32),
        "ctx_counts": np.array(ctx_counts or [0], dtype=np.int32),
        "massif_sizes": m_sizes, "massif_tiles": m_tiles,
        "massif_offsets": m_offsets, "massif_families": m_fams,
        "valley_sizes": v2_sizes, "valley_tiles": v2_tiles,
        "valley_offsets": v2_offsets, "valley_families": v2_fams,
        "valley_axis": v2_axis,
        "formation_class": f_class, "formation_dir": f_dir,
        "formation_sizes": f_sizes, "formation_tiles": f_tiles,
        "formation_offsets": f_offsets, "formation_families": f_fams,
        "cliff_names": c_names, "cliff_sizes": c_sizes,
        "cliff_tiles": c_tiles, "cliff_offsets": c_offsets,
        "maps": np.array([used], dtype=np.int32),
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    campaign_only = "--all" not in sys.argv[1:]
    game_dir = Path(args[0]) if args else DEFAULT_GAME_DIR
    if not game_dir.is_dir():
        print(f"Outpost-2-Ordner nicht gefunden: {game_dir}")
        return 1
    model = learn(game_dir, campaign_only)
    np.savez_compressed(OUT_PATH, **model)
    quelle = "nur Kampagnenkarten" if campaign_only else "alle Karten"
    print(f"{int(model['maps'][0])} Karten ausgewertet ({quelle})")
    print(f"Nachbarschaften rechts: {len(model['right'])}, unten: {len(model['down'])}")
    print(f"Kacheln: {len(model['usage'])}, davon mit Familie: {len(model['family'])}")
    print(f"Familien: {list(model['families'])}")
    print(f"Bauteil-Kacheln (nicht zufaellig streuen): {len(model['structure'])}")
    print(f"Lava-Kacheln: {len(model['lava'])}")
    print("Klippen-Nachbarschaft: eigenes Modell, siehe learn_cliffs.py")
    print(f"Vulkan-Stempel: {len(model['volcano_names'])}, "
          f"Klippen-Stempel: {len(model['cliff_names'])}, "
          f"Formationen: {len(model['formation_sizes'])}, "
          f"Detail-Stempel: {len(model['detail_sizes'])}")
    from collections import Counter as _C
    print("Formationen nach Bauart:", dict(_C(model["formation_class"].tolist())))
    print(f"Kantenmuster: {int((model['muster'] >= 0).all(axis=(1,2)).sum())} Kacheln")
    print(f"Kachelgruppen: {int((model['gruppen'] >= 0).sum())} zugeordnet")
    print(f"Kantensignaturen: {len(model['kanten'])} Kacheln")
    print(f"Formtabelle: {len(model['shape_keys'])} Hoehenmuster, "
          f"{len(model['ctx_keys'])} Muster 3x3, "
          f"{len(model['ctx5_keys'])} Muster 5x5")
    from collections import Counter as _C2
    print(f"Uebergangskacheln: {len(model['trans_tiles'])}, Paare: "
          f"{sorted(set(zip(model['trans_a'].tolist(), model['trans_b'].tolist())))}")
    print(f"Massive: {len(model['massif_sizes'])}, "
          f"Taeler: {len(model['valley_sizes'])} "
          f"{dict(_C(model['valley_axis'].tolist()))}")
    print(f"geschrieben: {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
