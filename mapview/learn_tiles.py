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

from op2map import Op2Map  # noqa: E402
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
DETAIL_MARKERS = ("rock", "rok", "crk", "crac", "crat")

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


def training_maps(game_dir: Path, campaign_only: bool = True) -> list[Path]:
    """Karten fuers Anlernen auswaehlen (ohne Altkopien, optional nur Kampagne)."""
    maps = [p for p in sorted(set(game_dir.rglob("*.map")))
            if "MonoBleedingEdge" not in str(p) and "backups" not in str(p).lower()]
    if campaign_only:
        maps = [p for p in maps if CAMPAIGN_PATTERN.match(p.stem)]
    return maps


def learn_shapes(grid: np.ndarray, fam_of: dict, zelltyp_tab: dict,
                 kachel_tab: dict, grob_tab: dict) -> None:
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


def learn(game_dir: Path, campaign_only: bool = True) -> dict:
    right: dict[int, Counter] = defaultdict(Counter)
    down: dict[int, Counter] = defaultdict(Counter)
    usage: Counter = Counter()
    fam_of: dict[int, str] = {}
    base_tiles: set[int] = set()
    structure_tiles: set[int] = set()
    lava_tiles: set[int] = set()
    volcanoes: dict[str, tuple[int, int, list[int]]] = {}
    formations: list = []
    massifs: list = []
    valleys: list = []
    form_zelltyp: dict = {}      # 5x5-Hoehenmuster -> Zelltyp
    form_kachel: dict = {}       # 3x3-Rollenmuster+Familie -> Kacheln
    grob_kachel: dict = {}       # Rueckfall: Zelltyp+Familie -> Kacheln
    cliffs: dict[str, tuple[int, int, list[int]]] = {}
    details: dict[str, tuple[int, int, list[int], str]] = {}

    maps = training_maps(game_dir, campaign_only)
    used = 0
    for path in maps:
        try:
            m = Op2Map(path.read_bytes())
        except Exception:
            continue
        used += 1
        for group in m.tile_groups:
            name = group.name
            if not name.isascii():
                continue
            low = name.lower()
            indices = [int(i) for i in group.mapping_indices]
            if any(marker in low for marker in STRUCTURE_MARKERS):
                structure_tiles.update(indices)
            else:
                base_tiles.update(indices)
            if any(marker in low for marker in LAVA_MARKERS):
                lava_tiles.update(indices)
            if VOLCANO_MARKER in low and name not in volcanoes:
                volcanoes[name] = (group.width, group.height, indices)
            if CLIFF_MARKER in low and name not in cliffs:
                cliffs[name] = (group.width, group.height, indices)
            if (any(k in low for k in DETAIL_MARKERS) and name not in details
                    and group.width * group.height <= 20):
                details[name] = (group.width, group.height, indices, low[:3])
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
        formations.extend(extract_formations(m, g, fam_of))
        massifs.extend(extract_massifs(m, g, fam_of))
        valleys.extend(extract_valleys(m, g, fam_of))
        learn_shapes(g, fam_of, form_zelltyp, form_kachel, grob_kachel)

    families = sorted(set(fam_of.values()))
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

    return {
        "right": pairs(right),
        "down": pairs(down),
        "usage": np.array(sorted(usage.items()), dtype=np.int32),
        "family": np.array(sorted((t, fam_index[f]) for t, f in fam_of.items()),
                           dtype=np.int32),
        "families": np.array(families),
        "structure": np.array(structure_only, dtype=np.int32),
        "lava": np.array(sorted(lava_tiles), dtype=np.int32),
        "volcano_names": v_names, "volcano_sizes": v_sizes,
        "volcano_tiles": v_tiles, "volcano_offsets": v_offsets,
        "detail_sizes": d_sizes, "detail_tiles": d_tiles,
        "detail_offsets": d_offsets, "detail_families": d_fams,
        "shape_keys": schl_form, "shape_cells": wert_form,
        "ctx_keys": schl_ctx,
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
    print(f"Vulkan-Stempel: {len(model['volcano_names'])}, "
          f"Klippen-Stempel: {len(model['cliff_names'])}, "
          f"Formationen: {len(model['formation_sizes'])}, "
          f"Detail-Stempel: {len(model['detail_sizes'])}")
    from collections import Counter as _C
    print("Formationen nach Bauart:", dict(_C(model["formation_class"].tolist())))
    print(f"Formtabelle: {len(model['shape_keys'])} Hoehenmuster, "
          f"{len(model['ctx_keys'])} Kachelmuster")
    print(f"Massive: {len(model['massif_sizes'])}, "
          f"Taeler: {len(model['valley_sizes'])} "
          f"{dict(_C(model['valley_axis'].tolist()))}")
    print(f"geschrieben: {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
