"""Konstanten, Parameter und Ergebnis des Kartengenerators.

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

Constants, parameters and result type of the map generator. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import celltypes  # noqa: E402


MODEL_PATH = Path(__file__).with_name("tiles_model.npz")


# Symmetriearten / symmetry modes
SYM_NONE = "none"


SYM_MIRROR_X = "mirror_x"      # linke Haelfte gespiegelt (2 Spieler)


SYM_MIRROR_Y = "mirror_y"      # obere Haelfte gespiegelt (2 Spieler)


SYM_ROT180 = "rot180"          # punktsymmetrisch (2 Spieler)


SYM_QUAD = "quad"              # vierfach gespiegelt (4 Spieler)


SYMMETRIES = [SYM_NONE, SYM_MIRROR_X, SYM_MIRROR_Y, SYM_ROT180, SYM_QUAD]


# "Bewuchs" -- bewachsener Fels; in OP2 kein eigenes Gelaende, aber als
# Flaeche steuerbar (siehe TileModel).
# "Vegetation" -- overgrown rock; not its own terrain in OP2 but steerable as
# an area (see TileModel).
FAMILY_VEGETATION = "veg"


# Vorlagen: Voreinstellungen fuer Mischung und Zerkluefung.
# Templates: presets for terrain mix and roughness.
TEMPLATES: dict[str, dict] = {
    "plains":  {"mix": {"mud": 0.45, "roc": 0.25, "san": 0.15, "veg": 0.15},
                "roughness": 0.0},
    "canyon":  {"mix": {"roc": 0.55, "mud": 0.25, "san": 0.10, "veg": 0.10},
                "roughness": 0.75},
    "desert":  {"mix": {"san": 0.60, "mud": 0.30, "roc": 0.08, "veg": 0.02},
                "roughness": 0.35},
    "islands": {"mix": {"mud": 0.35, "roc": 0.35, "san": 0.20, "veg": 0.10},
                "roughness": 0.85},
    "ice":     {"mix": {"sno": 0.45, "roc": 0.35, "mud": 0.20}, "roughness": 0.45},
    # Landschaftsmodus: nicht Flecken wuerfeln, sondern ein Relief bauen --
    # Hochlandmassiv, Mesas, ausgetrocknete Flussbetten, Klippen als gezeichnete
    # Linien (Gelaende-Loeser). Trocken, karg, leicht vulkanisch -- New Terra.
    # Landscape mode: build a relief instead of rolling patches -- highland
    # massif, mesas, dry riverbeds, cliffs as drawn lines (terrain solver).
    # Sandanteil bewusst klein: bei 0,28 wuchs auf 128er-Karten regelmaessig
    # ein Sandkontinent, in dem die Flussbetten untergingen.
    # Sand share deliberately small: at 0.28 a sand continent regularly grew
    # on 128 maps and swallowed the riverbeds.
    "newterra": {"mix": {"mud": 0.68, "san": 0.20, "roc": 0.12},
                 "roughness": 0.0, "landschaft": True, "volcanoes": 1},
}


# Zelltypen, ueber die Fahrzeuge kommen (fuer Startpunkte und Statistik).
# Cell types vehicles can cross (for spawn points and statistics).
PASSABLE_CLASSES = {celltypes.FAST, celltypes.MEDIUM, celltypes.SLOW}


@dataclass
class MapGenParams:
    width: int = 128
    height: int = 128
    seed: int = 1
    mix: dict[str, float] = field(default_factory=lambda: dict(TEMPLATES["plains"]["mix"]))
    # 0 = weiche grosse Flaechen, 1 = zerklueftet.
    #
    # Gemessen ist das der staerkste Hebel auf die Kachelqualitaet, staerker als
    # jede Kachelregel: von 0 auf 0,5 verdoppeln sich die Musterbrueche (4,95 ->
    # 9,20 %) und die sichtbaren Brueche steigen von 0,80 auf 1,45 %. Bei 0
    # liegen beide im Bereich der Originalkarten (3,7-5,7 % bzw. 1,0-1,8 %), die
    # sichtbaren Brueche sogar darunter. Der Grund: eine zerklueftete Biomgrenze
    # braucht in fast jeder Zelle eine Mischkachel, und die gibt es nur fuer
    # wenige Kantenmuster.
    #
    # 0 = soft large areas, 1 = rugged. Measured, this is the strongest lever on
    # tile quality, stronger than any tile rule: from 0 to 0.5 pattern breaks
    # double (4.95 -> 9.20 %) and visible breaks rise from 0.80 to 1.45 %. At 0
    # both are within the range of the original maps (3.7-5.7 % resp. 1.0-1.8 %),
    # visible breaks even below it. The reason: a rugged biome border needs a
    # blend tile in almost every cell, and those exist for only a few edge
    # patterns.
    roughness: float = 0.0
    symmetry: str = SYM_NONE
    spawns: int = 0                  # feste Startpunkte (0 = keine)
    spawn_clearance: int = 6         # freier Radius je Startpunkt in Kacheln
    cliffs: float = 0.0              # Flaechenanteil Hochflaechen (0 = keine)
    ramps: int = 2                   # Auffahrten je Karte (Luecken im Kantenring)
    volcanoes: int = 0               # Vulkane (jeder mit lavaPossible-Zone)
    lava_zone_tiles: int = 300       # Groesse der lavaPossible-Zone je Vulkan
    smooth: int = 2                  # Glaettungsdurchgaenge gegen Kleinstflecken
    # Wie weit Bewuchs von Fels, Sand und Schnee wegbleibt. Gemessen ueber
    # acht Seeds ist 1 der beste Wert: kein Seed faellt unter die
    # Klippenschwelle (kleinster Anteil 1,71 % gegen 0,85 % bei 2), und der
    # Bewuchsanteil bleibt mit 13,8 % naeher am Regler als bei 2 (12,9 %).
    # How far vegetation stays away from rock, sand and snow. Measured across
    # eight seeds, 1 is the best value: no seed drops below the cliff threshold
    # (smallest share 1.71 % against 0.85 % at 2), and the vegetation share
    # stays closer to the slider at 13.8 % than at 2 (12.9 %).
    bewuchs_abstand: int = 1
    # Mindestgroesse einer zusammenhaengenden Biomflaeche, als Anteil der
    # Karte. Kleinere Flecken gehen im umgebenden Biom auf, statt als
    # Sprenkel stehen zu bleiben.
    # Minimum size of a contiguous biome area as a share of the map. Smaller
    # patches dissolve into the surrounding biome instead of staying as
    # speckles.
    min_biome: float = 0.006
    # Streugut (Steine, Risse, Krater): 0.5 entspricht ungefaehr der Dichte
    # der Originalkarten (rund 3 % der Flaeche).
    # Scatter (stones, cracks, craters): 0.5 is about the density of the
    # original maps (roughly 3 % of the area).
    details: float = 0.5
    # Bodengrenzen: "zone" streut ueber 2-3 Kacheln wie im Original, "linie"
    # setzt eine einzellige, durchgehende Kante. Die Linie steckt NICHT im
    # Originalmaterial -- dort ist der Uebergang gesprenkelt -- sie ist eine
    # bewusste Abweichung fuer eine ruhigere Optik.
    # Ground borders: "zone" scatters over 2-3 tiles like the originals,
    # "linie" sets a single-cell continuous edge. The line is NOT in the
    # original material -- there the transition is dithered -- it is a
    # deliberate deviation for a calmer look.
    border_style: str = "zone"
    # Gewuenschte Gelaendemerkmale (Tal, Berg, Plateau, Freiflaeche,
    # Engstelle). Sie werden vor dem Zufall gesetzt und nehmen ihm den Platz.
    # Requested terrain features -- placed before the randomness, taking the
    # space away from it.
    features: list = field(default_factory=list)
    # Landschaftsmodus: Hochland als EIN Relief (Massiv + Mesas) statt
    # gestreuter Blobs, Klippen ueber klippe_aus_linie (Gelaende-Loeser),
    # ausgetrocknete Flussbetten. Aus, solange keine Vorlage ihn anfordert --
    # die bestehenden Wege bleiben unangetastet.
    # Landscape mode: highland as ONE relief (massif + mesas) instead of
    # scattered blobs, cliffs via klippe_aus_linie (block path with groups),
    # dry riverbeds. Off unless a template requests it.
    landschaft: bool = False
    # Ausgetrocknete Flussbetten im Landschaftsmodus. -1 = nach Kartengroesse
    # (eine je 128er-Kantenlaenge), 0 = keine.
    # Dry riverbeds in landscape mode. -1 = by map size, 0 = none.
    fluesse: int = -1

    @classmethod
    def from_template(cls, name: str, **kwargs) -> "MapGenParams":
        tpl = TEMPLATES.get(name, TEMPLATES["plains"])
        params = cls(mix=dict(tpl["mix"]), roughness=tpl["roughness"],
                     landschaft=bool(tpl.get("landschaft", False)),
                     volcanoes=int(tpl.get("volcanoes", 0)))
        for key, value in kwargs.items():
            setattr(params, key, value)
        return params


@dataclass
class GeneratedMap:
    tiles: np.ndarray                # (h, w) tileMappingIndex
    cells: np.ndarray                # (h, w) cellType
    spawns: list[tuple[int, int]]
    passable_share: float
    family_share: dict[str, float]
    connected: bool
    volcanoes: list[tuple[int, int]] = field(default_factory=list)
    # Je Vulkan die Kacheln, auf denen Lava fliessen darf (lavaPossible).
    # Per volcano the tiles on which lava may flow (lavaPossible).
    lava_zones: list[list[tuple[int, int]]] = field(default_factory=list)
    plateau_share: float = 0.0
    ramps: list[tuple[int, int]] = field(default_factory=list)
    mesas: list[tuple[int, int]] = field(default_factory=list)
    detail_share: float = 0.0
    features: dict = field(default_factory=dict)
    # Je Merkmal, wo es wirklich liegt -- die Lage wird um den
    # Sektor herum verwackelt, sonst saehe jede Karte gleich aus.
    # Where each feature actually ended up -- the position is
    # jittered around the sector, otherwise every map would look
    # the same.
    feature_spots: list = field(default_factory=list)
    # Anteil der Karte, der im Landschaftsmodus Flussbett ist.
    # Share of the map that is riverbed in landscape mode.
    fluss_share: float = 0.0


def _cell_types(grid: np.ndarray) -> np.ndarray:
    """Befahrbarkeit je Kachel aus der gelernten Tabelle."""
    lut = np.full(2048, celltypes.MEDIUM_PASSIBLE_1, dtype=np.uint8)
    for tile in np.unique(grid):
        lut[int(tile)] = celltypes.default_cell_type(int(tile))
    return lut[grid]


# --------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Gelaendemerkmale / terrain features
#
# Bis hierher war alles Zufall aus dem Seed. Merkmale sind der Gegenpol: eine
# grobe Beschreibung dessen, was auf der Karte vorkommen soll -- ein Tal, ein
# Berg, eine Freiflaeche -- die vor dem Zufall gesetzt wird und ihm den Platz
# wegnimmt. Der Rest wuerfelt sich wie gehabt drumherum.
#
# Up to here everything came from the seed. Features are the counterweight: a
# rough description of what the map should contain -- a valley, a mountain, a
# clearing -- placed before the randomness and taking the space away from it.
# The rest is rolled around them as before.
# ---------------------------------------------------------------------------

FEAT_TAL = "tal"


FEAT_BERG = "berg"


FEAT_PLATEAU = "plateau"


FEAT_FREI = "frei"


FEAT_ENGE = "enge"


FEATURE_KINDS = (FEAT_TAL, FEAT_BERG, FEAT_PLATEAU, FEAT_FREI, FEAT_ENGE)


# 3x3-Raster fuer die grobe Lage. Leerer Schluessel = egal, dann wuerfelt der Seed.
# 3x3 grid for the rough position. Empty key = don't care, the seed decides.
SEKTOREN: dict[str, tuple[float, float]] = {
    "nw": (0.22, 0.22), "n": (0.50, 0.20), "no": (0.78, 0.22),
    "w":  (0.20, 0.50), "c": (0.50, 0.50), "o":  (0.80, 0.50),
    "sw": (0.22, 0.78), "s": (0.50, 0.80), "so": (0.78, 0.78),
}


# Gegenueberliegender Sektor -- Vorgabe fuer das Ziel eines Tals.
# Opposite sector -- default target for a valley.
GEGENUEBER = {"nw": "so", "n": "s", "no": "sw", "w": "o", "c": "so",
              "o": "w", "sw": "no", "s": "n", "so": "nw"}


@dataclass
class Feature:
    """Ein gewuenschtes Gelaendemerkmal.

    `where` und `to` sind Sektoren aus SEKTOREN (leer = egal), `size` geht von
    0 bis 1. `lava` gilt nur fuer das Tal und setzt lavaPossible auf die Sohle
    plus einen Vulkan ans obere Ende -- Lavakacheln werden nie gemalt, die
    entstehen im Spiel aus dem Ausbruch.

    A requested terrain feature. `where` and `to` are sectors (empty = any),
    `size` runs 0..1. `lava` applies to valleys only and sets lavaPossible on
    the valley floor plus a volcano at its head -- lava tiles are never
    painted, they come from the eruption in-game.
    """
    kind: str
    where: str = ""
    to: str = ""
    size: float = 0.5
    lava: bool = False


def _sperr_maske(tiles: np.ndarray) -> np.ndarray:
    """Zellen, die den Weg versperren (Klippen und unpassierbarer Grund)."""
    sperr = [k for k, v in celltypes.SPEED_CLASS.items()
             if v in ("cliff", "impassable")]
    ct = np.array([[celltypes.default_cell_type(int(t), fallback=0)
                    for t in reihe] for reihe in tiles], dtype=np.int32)
    return np.isin(ct, sperr)


def _korridor_von_stempel(tiles: np.ndarray, reichweite: int = 10) -> np.ndarray:
    """Die Talsohle eines Talstempels: frei, aber beidseitig von Wand gesaeumt.

    Beim Aneinanderreihen mehrerer Stempel muessen die Sohlen aufeinander
    treffen, sonst endet das Tal in einer Wand. Deshalb wird die Sohle hier
    einmal bestimmt und der Stempel spaeter danach ausgerichtet.

    The valley floor of a valley stamp: free ground flanked by wall on both
    sides. When chaining several stamps the floors have to meet, otherwise the
    valley ends in a wall -- so the floor is determined once here and the stamp
    aligned by it later.
    """
    sperr = _sperr_maske(tiles)
    oben = np.zeros_like(sperr); unten = np.zeros_like(sperr)
    links = np.zeros_like(sperr); rechts = np.zeros_like(sperr)
    for d in range(1, reichweite + 1):
        oben[d:, :] |= sperr[:-d, :]
        unten[:-d, :] |= sperr[d:, :]
        links[:, d:] |= sperr[:, :-d]
        rechts[:, :-d] |= sperr[:, d:]
    return (~sperr) & ((oben & unten) | (links & rechts))


_LEER = np.zeros(0, dtype=np.int32)
