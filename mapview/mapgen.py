"""Kartengenerator: aus einem Seed eine spielbare Outpost-2-Karte erzeugen.

Zwei Ebenen:

1. **Regionen** -- ein Rauschfeld legt fest, welche Gegend welche
   Gelaendefamilie wird (Erde/Fels/Sand/Eis). Daran haengen die Regler
   (Mischung, Zerkluefung) und die Symmetrie.
2. **Kacheln** -- innerhalb der Regionen werden die konkreten Kacheln aus der
   gelernten Nachbarschaft der Originalkarten gezogen (tiles_model.npz).
   Dadurch entstehen Uebergaenge, die es im Spiel wirklich gibt, statt
   erfundener.

Die Befahrbarkeit kommt aus derselben gelernten Tabelle wie beim Malen
(celltypes.json), Startpunkte werden auf freier, zusammenhaengender Flaeche
gesucht.

Map generator: turn a seed into a playable Outpost 2 map. A noise layer
decides the terrain family per region (that is what the sliders and the
symmetry act on); the concrete tiles are then drawn from the adjacency learned
from the original maps, so transitions are real ones rather than invented.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import celltypes
import shapegen  # noqa: E402
from op2map import Op2Map  # noqa: E402

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
                "roughness": 0.25},
    "canyon":  {"mix": {"roc": 0.55, "mud": 0.25, "san": 0.10, "veg": 0.10},
                "roughness": 0.75},
    "desert":  {"mix": {"san": 0.60, "mud": 0.30, "roc": 0.08, "veg": 0.02},
                "roughness": 0.35},
    "islands": {"mix": {"mud": 0.35, "roc": 0.35, "san": 0.20, "veg": 0.10},
                "roughness": 0.85},
    "ice":     {"mix": {"sno": 0.45, "roc": 0.35, "mud": 0.20}, "roughness": 0.45},
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
    roughness: float = 0.35          # 0 = weiche grosse Flaechen, 1 = zerklueftet
    symmetry: str = SYM_NONE
    spawns: int = 0                  # feste Startpunkte (0 = keine)
    spawn_clearance: int = 6         # freier Radius je Startpunkt in Kacheln
    cliffs: float = 0.0              # Flaechenanteil Hochflaechen (0 = keine)
    ramps: int = 2                   # Auffahrten je Karte (Luecken im Kantenring)
    volcanoes: int = 0               # Vulkane (jeder mit lavaPossible-Zone)
    lava_zone_tiles: int = 300       # Groesse der lavaPossible-Zone je Vulkan
    smooth: int = 2                  # Glaettungsdurchgaenge gegen Kleinstflecken
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
    # Gewuenschte Gelaendemerkmale (Tal, Berg, Plateau, Freiflaeche,
    # Engstelle). Sie werden vor dem Zufall gesetzt und nehmen ihm den Platz.
    # Requested terrain features -- placed before the randomness, taking the
    # space away from it.
    features: list = field(default_factory=list)

    @classmethod
    def from_template(cls, name: str, **kwargs) -> "MapGenParams":
        tpl = TEMPLATES.get(name, TEMPLATES["plains"])
        params = cls(mix=dict(tpl["mix"]), roughness=tpl["roughness"])
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


class TileModel:
    """Gelernte Nachbarschaft + Familienzuordnung der Kacheln."""

    def __init__(self, path: Path | None = None):
        data = np.load(path or MODEL_PATH, allow_pickle=False)
        self.families = [str(f) for f in data["families"]]
        # Formtabellen: Klippen entstehen daraus, statt kopiert zu werden.
        # Shape tables: cliffs are generated from these instead of copied.
        self.shapes = shapegen.ShapeTables(data)
        self.right = self._index(data["right"])
        self.down = self._index(data["down"])
        usage = data["usage"]
        self.usage = dict(zip(usage[:, 0].tolist(), usage[:, 1].tolist()))
        fam = data["family"]
        self.family_of = np.full(2048, -1, dtype=np.int16)
        self.family_of[fam[:, 0]] = fam[:, 1].astype(np.int16)
        # Bewuchs ist in OP2 keine eigene Gelaendesorte, sondern bewachsener
        # Fels (Zelltyp cellFastPassible1). Die 27 Kacheln liegen in den
        # Gruppen von Erde und Fels, bilden aber Flaechen (zu 80 % folgt
        # rechts wieder Bewuchs) -- deshalb hier als eigene Familie fuehren,
        # damit sie steuerbar wird.
        # Vegetation is not its own terrain type in OP2 but overgrown rock
        # (cell type cellFastPassible1). Those 27 tiles sit in the dirt and
        # rock groups yet form patches (80 % continue to the right), so they
        # are treated as their own family here to make them steerable.
        self.veg_family = len(self.families)
        self.families.append(FAMILY_VEGETATION)
        for tile in range(2048):
            if celltypes.default_cell_type(tile, fallback=-1) == celltypes.FAST_PASSIBLE_1:
                self.family_of[tile] = self.veg_family

        # Bauteile (Vulkan, Lava, Klippen, Brandspuren, planiert): duerfen NIE
        # zufaellig gestreut werden -- im Original werden sie gesetzt.
        # Building blocks (volcano, lava, cliffs, burn marks, bulldozed): must
        # never be scattered randomly -- the originals place them.
        self.structure = np.zeros(2048, dtype=bool)
        self.structure[data["structure"]] = True
        # Lavakacheln werden NIE gesetzt: fliessende Lava entsteht im Spiel
        # durch den Vulkanausbruch. Die Karte liefert nur den Vulkan und das
        # Gebiet, in dem Lava fliessen darf (lavaPossible, zur Laufzeit).
        # Lava tiles are NEVER placed: flowing lava is created in-game by the
        # eruption. The map only provides the volcano and the area where lava
        # may flow (lavaPossible, set at runtime).
        self.lava = np.zeros(2048, dtype=bool)
        self.lava[data["lava"]] = True
        self.placeable = ~self.structure

        self.cliff_pool = self._load_cliffs(data)
        # Fertige Klippenformationen aus den Originalkarten -- am Stueck
        # gesetzt sehen sie aus wie handgebaut, weil sie es sind.
        # Ready-made cliff formations from the original maps -- placed in one
        # piece they look hand-built, because they are.
        self.details: list = []             # (tiles, familie)
        if "detail_sizes" in data:
            d_sizes = data["detail_sizes"]
            d_tiles = data["detail_tiles"]
            d_off = data["detail_offsets"]
            d_fams = [str(f) for f in data["detail_families"]]
            for i in range(len(d_sizes)):
                dw, dh = int(d_sizes[i][0]), int(d_sizes[i][1])
                block = d_tiles[d_off[i]:d_off[i + 1]]
                # 1x1-Stempel weglassen: eine einzelne Kachel im Nichts sieht
                # nach Rauschen aus, nicht nach einem Steinfeld.
                # Skip 1x1 stamps: a single tile in the middle of nowhere looks
                # like noise, not like a rock field.
                if dw * dh > 1 and len(block) == dw * dh:
                    self.details.append((block.reshape(dh, dw),
                                         d_fams[i] if i < len(d_fams) else ""))

        # Grosse Massive und fertige Taeler -- fuer die Gelaendemerkmale.
        # Large massifs and finished valleys -- for the terrain features.
        self.massifs: list = []             # (tiles, familie)
        self.valleys: list = []             # (tiles, familie, achse, korridor)
        for name, ziel in (("massif", self.massifs), ("valley", self.valleys)):
            if f"{name}_sizes" not in data:
                continue
            sizes = data[f"{name}_sizes"]
            flat = data[f"{name}_tiles"]
            off = data[f"{name}_offsets"]
            fams = [str(f) for f in data[f"{name}_families"]]
            achsen = ([str(a) for a in data["valley_axis"]]
                      if name == "valley" else [""] * len(sizes))
            for i in range(len(sizes)):
                bw, bh = int(sizes[i][0]), int(sizes[i][1])
                block = flat[off[i]:off[i + 1]]
                if bw * bh <= 1 or len(block) != bw * bh:
                    continue
                tiles = block.reshape(bh, bw)
                fam = fams[i] if i < len(fams) else ""
                # Fremdes Biom aussortieren. Der Filter beim Anlernen greift zu
                # frueh: dort waechst die Familienzuordnung noch Karte fuer
                # Karte, hier ist sie vollstaendig. Ohne das stand ein weisser
                # Schneebalken mitten in der Wueste.
                # Sort out foreign biomes. The filter during training runs too
                # early -- there the family assignment still grows map by map,
                # here it is complete. Without this a white snow bar stood in
                # the middle of the desert.
                if not self._familienrein(tiles, fam):
                    continue
                if name == "valley":
                    ziel.append((tiles, fam, achsen[i] if i < len(achsen) else "h",
                                 _korridor_von_stempel(tiles)))
                else:
                    ziel.append((tiles, fam))

        self._saeubere_formtabellen()
        self.formation_class: list[str] = []   # grat / massiv / plateau
        self.formation_dir: list[str] = []     # Gefaellerichtung n/o/s/w
        if "formation_class" in data:
            self.formation_class = [str(v) for v in data["formation_class"]]
        if "formation_dir" in data:
            self.formation_dir = [str(v) for v in data["formation_dir"]]

        self.formations: list = []          # (tiles, familie)
        f_sizes = data["formation_sizes"]
        f_tiles = data["formation_tiles"]
        f_off = data["formation_offsets"]
        f_fams = ([str(f) for f in data["formation_families"]]
                  if "formation_families" in data else [""] * len(f_sizes))
        for i in range(len(f_sizes)):
            fw, fh = int(f_sizes[i][0]), int(f_sizes[i][1])
            block = f_tiles[f_off[i]:f_off[i + 1]]
            if fw * fh and len(block) == fw * fh:
                self.formations.append((block.reshape(fh, fw),
                                        f_fams[i] if i < len(f_fams) else ""))
        self.volcanoes: list[tuple[str, int, int, np.ndarray]] = []
        names = [str(n) for n in data["volcano_names"]]
        sizes = data["volcano_sizes"]
        flat = data["volcano_tiles"]
        offsets = data["volcano_offsets"]
        for i, name in enumerate(names):
            if not name:
                continue
            w, h = int(sizes[i][0]), int(sizes[i][1])
            block = flat[offsets[i]:offsets[i + 1]]
            if w * h and len(block) == w * h:
                self.volcanoes.append((name, w, h, block.reshape(h, w)))
        self._build_family_pools()

    def _load_cliffs(self, data) -> dict:
        """Klippen-Stempel nach (Familie, Ausrichtung) ablegen -- als GANZE
        Stempel, nicht als Kacheltopf.

        Die Kacheln eines Stempels ergeben nur in ihrer Reihenfolge eine Wand;
        einzeln gezogen entsteht ein Flickenteppich. Die Ausrichtung steckt
        nicht im Namen, sondern im Zelltyp-Muster: wo die Hochseite relativ
        zur Tiefseite liegt, zeigt, wohin es hinuntergeht.

        Store cliff stamps by (family, orientation) as WHOLE stamps, not as a
        tile pool: the tiles of a stamp only form a wall in their given order.
        """
        stamps: dict = {}
        names = [str(n) for n in data["cliff_names"]]
        sizes, flat = data["cliff_sizes"], data["cliff_tiles"]
        offsets = data["cliff_offsets"]
        for i, name in enumerate(names):
            if not name:
                continue
            w, h = int(sizes[i][0]), int(sizes[i][1])
            block = flat[offsets[i]:offsets[i + 1]]
            if not (w * h) or len(block) != w * h:
                continue
            tiles = block.reshape(h, w)
            cells = np.array([[celltypes.default_cell_type(int(t), fallback=-1)
                               for t in row] for row in tiles])
            fam = name[:3].lower()
            high = np.argwhere(cells == celltypes.CLIFFS_HIGH_SIDE)
            low = np.argwhere(cells == celltypes.CLIFFS_LOW_SIDE)
            if not len(high) or not len(low):
                if (cells == celltypes.NORTH_CLIFFS).any():
                    stamps.setdefault((fam, "N"), []).append(tiles)
                continue
            dy = low[:, 0].mean() - high[:, 0].mean()
            dx = low[:, 1].mean() - high[:, 1].mean()
            if abs(dy) >= abs(dx):
                direction = "S" if dy > 0 else "N"
            else:
                direction = "O" if dx > 0 else "W"
            # Faellt der Abfall in BEIDE Richtungen etwa gleich stark aus, ist
            # es ein Eckstueck -- genau das braucht eine Kontur, die abbiegt.
            # If the drop is about equally strong in BOTH directions it is a
            # corner piece -- exactly what a turning contour needs.
            # Nur DURCHGEHENDE Stempel taugen als Wandstueck: viele Motive
            # bestehen nur zu 60-80 % aus Klippenzellen, der Rest ist normales
            # Gelaende -- aneinandergereiht stanzt das Loecher in die Wand.
            # Only SOLID stamps work as a wall piece: many motifs are just
            # 60-80 % cliff cells, the rest is plain terrain -- chained
            # together that punches holes into the wall.
            anteil = float(np.isin(cells, [celltypes.NORTH_CLIFFS,
                                           celltypes.CLIFFS_HIGH_SIDE,
                                           celltypes.CLIFFS_LOW_SIDE]).mean())
            if anteil < 0.9:
                # Kein Wandstueck, aber ein fertiges kleines Mesa-Motiv --
                # genau so setzen die Originalkarten sie: einzeln in die
                # Flaeche, nicht aneinandergereiht.
                # Not a wall piece but a finished little mesa motif -- exactly
                # how the original maps use them: placed singly in the open,
                # not chained.
                stamps.setdefault((fam, "Motiv"), []).append(tiles)
                continue
            if abs(abs(dy) - abs(dx)) < 0.35 and abs(dy) > 0.2:
                stamps.setdefault((fam, "Ecke"), []).append(tiles)
            else:
                stamps.setdefault((fam, direction), []).append(tiles)
        return stamps

    def _build_family_pools(self):
        """Kacheln je Familie, nach Haeufigkeit -- Startpunkt des Samplings.

        Bauteile bleiben draussen; nur das Lavagebiet zieht aus Lavakacheln.

        Tiles per family, by frequency. Building blocks stay out; only the
        lava area draws from lava tiles."""
        self.by_family: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        for fi in range(len(self.families)):
            tiles = np.array([t for t, n in self.usage.items()
                              if self.family_of[t] == fi and self.placeable[t]],
                             dtype=np.int32)
            if len(tiles):
                weights = np.array([self.usage[int(t)] for t in tiles], dtype=float)
                self.by_family[fi] = (tiles, weights / weights.sum())

    @staticmethod
    def _index(pairs: np.ndarray) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        order = np.argsort(pairs[:, 0], kind="stable")
        pairs = pairs[order]
        starts = np.searchsorted(pairs[:, 0], np.arange(pairs[:, 0].max() + 2))
        table = {}
        for a in range(len(starts) - 1):
            lo, hi = starts[a], starts[a + 1]
            if hi > lo:
                table[a] = (pairs[lo:hi, 1].copy(), pairs[lo:hi, 2].astype(float))
        return table

    def _saeubere_formtabellen(self) -> None:
        """Lava, Fumarolen und Geroell aus den Klippen-Tabellen werfen.

        Die Tabellen lernen alles, was im Original in dieser Situation stand --
        rund um vulkanische Klippen also auch Lavakacheln und Schlote. Beim
        Nachschlagen landeten die dann mitten in der Wueste. Der Boden-Sampler
        filtert Bauteile laengst heraus, die Klippen-Tabelle muss es auch.
        Klippenkacheln selbst bleiben natuerlich drin.

        Throw lava, fumaroles and rubble out of the cliff tables. The tables
        learn everything that stood in that situation in the original, so around
        volcanic cliffs that includes lava tiles and vents, which then ended up
        in the middle of the desert on lookup. The ground sampler has always
        filtered structure tiles; the cliff table has to as well. Cliff tiles
        themselves of course stay.
        """
        verboten = {celltypes.VENTS_AND_FUMAROLES}
        erlaubt = np.ones(2048, dtype=bool)
        for tile in range(2048):
            zt = celltypes.default_cell_type(tile, fallback=-1)
            if zt in (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
                      celltypes.CLIFFS_LOW_SIDE):
                continue                      # Klippen sind das Ziel
            if zt in verboten or celltypes.speed_class(zt) in ("slow", "impassable"):
                erlaubt[tile] = False
        erlaubt[np.nonzero(self.lava)[0]] = False

        for keys, offs, tiles, counts in (
                ("ctx_keys", "ctx_offsets", "ctx_tiles", "ctx_counts"),
                ("grob_keys", "grob_offsets", "grob_tiles", "grob_counts")):
            k = getattr(self.shapes, keys)
            o = getattr(self.shapes, offs)
            t = getattr(self.shapes, tiles)
            c = getattr(self.shapes, counts)
            neu_k, neu_o, neu_t, neu_c = [], [0], [], []
            for i in range(len(k)):
                lo, hi = int(o[i]), int(o[i + 1])
                behalten = [(int(t[j]), int(c[j])) for j in range(lo, hi)
                            if erlaubt[int(t[j])]]
                if not behalten:
                    continue
                neu_k.append(int(k[i]))
                for kachel, n in behalten:
                    neu_t.append(kachel)
                    neu_c.append(n)
                neu_o.append(len(neu_t))
            setattr(self.shapes, keys, np.array(neu_k or [0], dtype=np.int64))
            setattr(self.shapes, offs, np.array(neu_o, dtype=np.int32))
            setattr(self.shapes, tiles, np.array(neu_t or [0], dtype=np.int32))
            setattr(self.shapes, counts, np.array(neu_c or [0], dtype=np.int32))

    def _familienrein(self, tiles, fam: str, grenze: float = 0.85) -> bool:
        """Bringt der Stempel ueberwiegend den eigenen Untergrund mit?"""
        if fam not in self.families:
            return True
        koerper = _sperr_maske(tiles)
        for _ in range(4):
            gewachsen = koerper.copy()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    gewachsen |= np.roll(np.roll(koerper, dy, 0), dx, 1)
            koerper = gewachsen
        fams = self.family_of[tiles[koerper]]
        klass = fams[(fams >= 0) & (fams < len(self.families))]
        if not len(klass):
            return False
        return float((klass == self.families.index(fam)).mean()) >= grenze


_model: TileModel | None = None


def model() -> TileModel:
    global _model
    if _model is None:
        _model = TileModel()
    return _model


# --------------------------------------------------------------------------
# Regionen / regions

def _value_noise(rng: np.random.Generator, h: int, w: int, freq: int) -> np.ndarray:
    """Weiches Rauschfeld in [0,1) per bilinearer Interpolation."""
    freq = max(2, int(freq))
    base = rng.random((freq + 1, freq + 1))
    ys = np.linspace(0, freq, h, endpoint=False)
    xs = np.linspace(0, freq, w, endpoint=False)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    fy = fy * fy * (3 - 2 * fy)      # smoothstep
    fx = fx * fx * (3 - 2 * fx)
    v00 = base[np.ix_(y0, x0)]
    v01 = base[np.ix_(y0, x0 + 1)]
    v10 = base[np.ix_(y0 + 1, x0)]
    v11 = base[np.ix_(y0 + 1, x0 + 1)]
    top = v00 * (1 - fx) + v01 * fx
    bottom = v10 * (1 - fx) + v11 * fx
    return top * (1 - fy) + bottom * fy


def _family_field(params: MapGenParams, rng: np.random.Generator,
                  fam_names: list[str]) -> np.ndarray:
    """Welche Familie bekommt welche Zelle? -> (h, w) Familienindex."""
    h, w = params.height, params.width
    # Zerkluefung steuert die Frequenz: wenige grosse Flaechen vs. viele kleine.
    # Roughness controls the frequency: few large areas vs. many small ones.
    base_freq = 3 + params.roughness * 14
    scores = []
    order = []
    targets = []
    total = sum(v for v in params.mix.values() if v > 0) or 1.0
    for name, weight in params.mix.items():
        if weight <= 0 or name not in fam_names:
            continue
        noise = (_value_noise(rng, h, w, base_freq)
                 + 0.5 * _value_noise(rng, h, w, base_freq * 2))
        scores.append(noise / 1.5)
        order.append(fam_names.index(name))
        targets.append(weight / total)
    if not scores:
        return np.zeros((h, w), dtype=np.int16)

    stack = np.stack(scores)
    target = np.array(targets)
    # Je Familie einen Versatz einregeln, bis die Flaechenanteile den
    # gewuenschten entsprechen. Ein fester Bonus je Gewicht trifft die
    # Vorgabe nicht -- die Rauschfelder ueberlagern sich zu unterschiedlich.
    # Tune a per-family offset until the area shares match the request. A
    # fixed bonus per weight misses the target -- the noise fields overlap
    # too differently.
    offsets = np.zeros(len(scores))
    picked = np.argmax(stack, axis=0)
    for _ in range(40):
        picked = np.argmax(stack + offsets[:, None, None], axis=0)
        shares = np.array([(picked == i).mean() for i in range(len(scores))])
        error = target - shares
        if np.abs(error).max() < 0.015:
            break
        offsets += 0.4 * error
    lookup = np.array(order, dtype=np.int16)
    return lookup[picked]


def _smooth_families(field_: np.ndarray, passes: int = 2, radius: int = 2) -> np.ndarray:
    """Kleinstflecken aufloesen: jede Zelle bekommt die Mehrheitsfamilie ihrer
    Umgebung.

    Ohne das entstehen ueberall Ein-Kachel-Inseln -- genau die Sprenkel, die
    eine erzeugte Karte unruhig aussehen lassen.

    Dissolve tiny patches: every cell takes the majority family of its
    surroundings. Without this the map is littered with one-tile islands.
    """
    out = field_
    kinds = int(out.max()) + 1
    for _ in range(max(0, passes)):
        counts = np.zeros((kinds,) + out.shape, dtype=np.int16)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                shifted = np.roll(np.roll(out, dy, axis=0), dx, axis=1)
                for k in range(kinds):
                    counts[k] += (shifted == k)
        out = np.argmax(counts, axis=0).astype(np.int16)
    return out


def _shrink_grow(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Erst schrumpfen, dann wieder wachsen -- loest Fransen und Splitter auf.

    Erode then dilate -- removes fringes and splinters (morphological
    opening), so plateaus become compact areas instead of ragged blobs."""
    def shift_all(m, op):
        out = m.copy()
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                shifted = np.roll(np.roll(m, dy, axis=0), dx, axis=1)
                out = op(out, shifted)
        return out
    eroded = shift_all(mask, np.logical_and)
    return shift_all(eroded, np.logical_or)


def _per_component(mask: np.ndarray, fn) -> np.ndarray:
    """`fn` auf jede zusammenhaengende Flaeche einzeln anwenden.

    Apply `fn` to each connected area separately."""
    h, w = mask.shape
    besucht = np.zeros_like(mask)
    out = np.zeros_like(mask)
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or besucht[sy, sx]:
                continue
            stack = [(sx, sy)]
            besucht[sy, sx] = True
            zellen = []
            while stack:
                x, y = stack.pop()
                zellen.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not besucht[ny, nx]:
                        besucht[ny, nx] = True
                        stack.append((nx, ny))
            teil = np.zeros_like(mask)
            for x, y in zellen:
                teil[y, x] = True
            out |= fn(teil)
    return out


def _staircase(mask: np.ndarray, min_run: int = 5) -> np.ndarray:
    """Kontur zu einer Treppe mit Mindestlauflaenge glaetten.

    Die Klippenstempel der Originalkarten sind fuer GERADE Abschnitte gebaut
    (plus Eckstuecke). Eine frei gekruemmte Kante liefert pro Zeile nur ein
    bis zwei Randzellen -- dort passt kein Stempel hin und die Wand zerfaellt.
    Diese Glaettung behaelt die gewachsene Gesamtform, laesst die Raender aber
    nur alle `min_run` Zeilen bzw. Spalten springen.

    Smooth the contour into a staircase with a minimum run length. The
    original cliff stamps are built for STRAIGHT sections (plus corners); a
    freely curved border yields only one or two border cells per row, where no
    stamp fits and the wall falls apart. This keeps the overall organic shape
    but lets the edges step only every `min_run` rows resp. columns.
    """
    h, w = mask.shape
    out = np.zeros_like(mask)
    for y in range(h):
        xs = np.nonzero(mask[y])[0]
        if not len(xs):
            continue
        # Zeilenweise linke/rechte Grenze in Stufen von min_run festhalten.
        # Hold the left/right border per row in steps of min_run.
        links, rechts = int(xs[0]), int(xs[-1])
        block = (y // min_run) * min_run
        ende = min(h, block + min_run)
        alle = [np.nonzero(mask[yy])[0] for yy in range(block, ende)]
        alle = [a for a in alle if len(a)]
        if not alle:
            continue
        links = int(round(np.median([a[0] for a in alle])))
        rechts = int(round(np.median([a[-1] for a in alle])))
        links = (links // min_run) * min_run
        rechts = ((rechts + min_run) // min_run) * min_run - 1
        if rechts - links + 1 >= min_run:
            out[y, max(0, links):min(w, rechts + 1)] = True
    return out


def _drop_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    """Zu kleine Inseln verwerfen -- ein 3x3-Plateau ergibt keine Mesa.

    Drop islands that are too small -- a 3x3 plateau is not a mesa."""
    h, w = mask.shape
    besucht = np.zeros_like(mask)
    out = np.zeros_like(mask)
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or besucht[sy, sx]:
                continue
            stack = [(sx, sy)]
            besucht[sy, sx] = True
            zellen = []
            while stack:
                x, y = stack.pop()
                zellen.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not besucht[ny, nx]:
                        besucht[ny, nx] = True
                        stack.append((nx, ny))
            if len(zellen) >= min_area:
                for x, y in zellen:
                    out[y, x] = True
    return out


def _plateau_field(fam_field: np.ndarray, params: "MapGenParams",
                   rng: np.random.Generator, tm: "TileModel") -> np.ndarray:
    """Hochflaechen bestimmen -- bevorzugt dort, wo es Klippen-Stempel gibt.

    Klippenkanten existieren nur fuer Erde und Sand; in Fels- und Eisgebieten
    gaebe es keine passenden Kanten, deshalb werden Plateaus dorthin gelenkt.

    Determine plateaus -- preferably where cliff stamps exist. Cliff edges
    only exist for dirt and sand, so plateaus are steered towards those.
    """
    if params.cliffs <= 0:
        return np.zeros(fam_field.shape, dtype=bool)
    h, w = fam_field.shape
    noise = (_value_noise(rng, h, w, 4 + params.roughness * 8)
             + 0.5 * _value_noise(rng, h, w, 10 + params.roughness * 10)) / 1.5
    passend = np.zeros(fam_field.shape, dtype=bool)
    for name in ("mud", "san"):
        if name in tm.families:
            passend |= fam_field == tm.families.index(name)
    noise = noise + 0.25 * passend            # Bonus fuer Erde/Sand
    ziel = float(np.clip(params.cliffs, 0.0, 0.6))
    schwelle = float(np.quantile(noise, 1.0 - ziel))
    # Organische Form, aber ohne Fransen: kraeftig oeffnen und schliessen.
    # Gerade Kanten entstehen NICHT durch Rastern (das gaebe rechteckige
    # Gehege), sondern dadurch, dass die Kanten spaeter in Laeufen abgefahren
    # werden.
    # Organic shape without fringes: open and close firmly. Straight edges are
    # NOT produced by quantising (that gives rectangular pens) but by walking
    # the border in runs later on.
    mask = _shrink_grow(noise >= schwelle, radius=2)
    mask = ~_shrink_grow(~mask, radius=2)          # Loecher schliessen
    mask = _drop_small(mask, min_area=140)
    # Getrennte Plateaus einzeln in eine Treppenkontur bringen, damit die
    # Stempel Platz finden -- sonst zerfaellt die Wand in Einzelstuecke.
    # Turn each plateau into a staircase contour so the stamps have room --
    # otherwise the wall falls apart into single pieces.
    mask = _per_component(mask, lambda m: _staircase(m, min_run=3))
    mask = _drop_small(mask, min_area=140)
    # Rand freilassen: eine Kante am Kartenrand liesse sich nicht sauber
    # abschliessen. / Keep the border clear: an edge at the map border could
    # not be closed properly.
    mask[:3, :] = mask[-3:, :] = False
    mask[:, :3] = mask[:, -3:] = False
    return mask


def _components(mask: np.ndarray):
    """Zusammenhaengende Flaechen einzeln liefern.

    Yield connected areas one by one."""
    h, w = mask.shape
    besucht = np.zeros_like(mask)
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or besucht[sy, sx]:
                continue
            stack = [(sx, sy)]
            besucht[sy, sx] = True
            teil = np.zeros_like(mask)
            while stack:
                x, y = stack.pop()
                teil[y, x] = True
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not besucht[ny, nx]:
                        besucht[ny, nx] = True
                        stack.append((nx, ny))
            yield teil


def _paint_cliffs(grid, plateau, fam_field, tm, rng, ramps):
    """Klippenwaende ENTLANG DES UMRISSES zeichnen, Stempel an Stempel.

    Die *mes*-Stempel sind fuer gerade Abschnitte gezeichnet. Statt sie an
    eine beliebige Kontur anzupassen (das gibt Fransen), wird hier der Umriss
    in Laeufe zerlegt und Stempel wie Perlen auf eine Schnur gefaedelt: jeder
    Stempel setzt dort an, wo der vorige endet. Ueberlappen ist erlaubt --
    eine Luecke nicht.

    Draw the cliff walls ALONG THE OUTLINE, stamp after stamp. The *mes*
    stamps are drawn for straight sections; instead of fitting them to an
    arbitrary contour (which frays), the outline is split into runs and stamps
    are threaded like beads on a string: each one starts where the previous
    ended. Overlap is allowed -- a gap is not.
    """
    if not plateau.any() or not tm.cliff_pool:
        return []
    h, w = plateau.shape

    verfuegbar = sorted({fam for fam, _ in tm.cliff_pool})
    zaehler = {}
    for fam in verfuegbar:
        if fam in tm.families:
            zaehler[fam] = int((fam_field[plateau] == tm.families.index(fam)).sum())
    haupt = max(zaehler, key=zaehler.get) if zaehler else verfuegbar[0]

    def pool(direction):
        p = tm.cliff_pool.get((haupt, direction)) or []
        if not p:
            for fam in verfuegbar:
                p = tm.cliff_pool.get((fam, direction)) or []
                if p:
                    break
        return p

    # Rampen: Streifen, in denen keine Wand gezeichnet wird.
    # Ramps: stretches where no wall is drawn.
    rand = plateau & ~(np.roll(plateau, -1, axis=0) & np.roll(plateau, 1, axis=0) &
                       np.roll(plateau, -1, axis=1) & np.roll(plateau, 1, axis=1))
    ys, xs = np.nonzero(rand)
    ramp_positions = []
    if len(xs) and ramps > 0:
        gewaehlt = [int(rng.integers(len(xs)))]
        while len(gewaehlt) < min(ramps, len(xs)):
            px, py = xs[gewaehlt], ys[gewaehlt]
            dist = np.min((xs[:, None] - px) ** 2 + (ys[:, None] - py) ** 2, axis=1)
            gewaehlt.append(int(np.argmax(dist)))
        ramp_positions = [(int(xs[i]), int(ys[i])) for i in gewaehlt]
    frei = np.zeros_like(rand)
    for rx, ry in ramp_positions:
        frei[max(0, ry - 3):ry + 4, max(0, rx - 3):rx + 4] = True

    def setze(tiles, x0, y0):
        sh, sw = tiles.shape
        x0 = int(np.clip(x0, 0, w - sw))
        y0 = int(np.clip(y0, 0, h - sh))
        if frei[y0:y0 + sh, x0:x0 + sw].any():
            return False
        grid[y0:y0 + sh, x0:x0 + sw] = tiles
        return True

    def faedeln(direction, x, y, laenge, waagerecht):
        """Stempel entlang eines Laufs aneinanderreihen (ohne Luecke)."""
        p = pool(direction)
        if not p or laenge <= 0:
            return
        pos = 0
        schutz = 0
        while pos < laenge and schutz < 200:
            schutz += 1
            tiles = p[int(rng.integers(len(p)))]
            sh, sw = tiles.shape
            if waagerecht:
                px = x + pos
                py = y if direction == "S" else y - sh + 1
            else:
                px = x if direction == "O" else x - sw + 1
                py = y + pos
            setze(tiles, px, py)
            pos += (sw if waagerecht else sh)

    # Zeilenspannen des Plateaus -- die Treppenkontur macht sie zeilenkonvex.
    # Row spans of the plateau -- the staircase contour makes it row-convex.
    for teil in _components(plateau):
        rows = {}
        for y in range(h):
            xs_ = np.nonzero(teil[y])[0]
            if len(xs_):
                rows[y] = (int(xs_[0]), int(xs_[-1]))
        if not rows:
            continue
        ys_sorted = sorted(rows)
        y_oben, y_unten = ys_sorted[0], ys_sorted[-1]

        # Senkrechte Waende: Laeufe konstanter linker bzw. rechter Grenze.
        # Vertical walls: runs of constant left resp. right border.
        for seite, direction in (("links", "W"), ("rechts", "O")):
            start = ys_sorted[0]
            aktuell = rows[start][0 if seite == "links" else 1]
            for i, y in enumerate(ys_sorted + [None]):
                wert = None if y is None else rows[y][0 if seite == "links" else 1]
                if wert != aktuell or y is None:
                    ende = ys_sorted[i - 1] if y is not None else ys_sorted[-1]
                    faedeln(direction, aktuell, start, ende - start + 1, waagerecht=False)
                    if y is not None:
                        start, aktuell = y, wert
        # Waagerechte Waende oben und unten.
        # Horizontal walls at the top and bottom.
        l, r = rows[y_oben]
        faedeln("N", l, y_oben, r - l + 1, waagerecht=True)
        l, r = rows[y_unten]
        faedeln("S", l, y_unten, r - l + 1, waagerecht=True)

        # Ecken an den Stufen -- dort biegt die Wand ab.
        # Corners at the steps -- that is where the wall turns.
        ecken = pool("Ecke")
        if ecken:
            for i in range(1, len(ys_sorted)):
                y_prev, y = ys_sorted[i - 1], ys_sorted[i]
                for seite in (0, 1):
                    if rows[y][seite] != rows[y_prev][seite]:
                        tiles = ecken[int(rng.integers(len(ecken)))]
                        sh, sw = tiles.shape
                        x = rows[y][seite]
                        setze(tiles, x if seite == 0 else x - sw + 1, y - sh // 2)
    return ramp_positions


def _mirror_region(grid: np.ndarray, mode: str) -> None:
    """Gesetzte Formationen auf die gespiegelte Haelfte uebertragen.

    Die Regionen sind schon symmetrisch; die Formationen werden zufaellig
    gesetzt und muessen daher nachgezogen werden, sonst ist die Karte fuer
    Mehrspieler unfair.

    Copy placed formations to the mirrored half: the regions are already
    symmetric, but the formations are placed randomly and must follow, or the
    map is unfair for multiplayer."""
    h, w = grid.shape
    if mode == SYM_MIRROR_X:
        grid[:, w // 2:] = grid[:, :w // 2][:, ::-1]
    elif mode == SYM_MIRROR_Y:
        grid[h // 2:, :] = grid[:h // 2, :][::-1, :]
    elif mode == SYM_ROT180:
        grid[h // 2:, :] = grid[:h // 2, :][::-1, ::-1]
    elif mode == SYM_QUAD:
        grid[:, w // 2:] = grid[:, :w // 2][:, ::-1]
        grid[h // 2:, :] = grid[:h // 2, :][::-1, :]


def _scatter_details(grid, fam_field, tm, rng, ziel_zellen, gesperrt):
    """Steine, Risse und Krater ins passende Biom streuen.

    Immer als ganzer Stempel und nur dort, wo der Untergrund zur Familie
    passt -- eine Sandduene mitten im Fels sieht falsch aus. Die Dichte
    orientiert sich an den Originalkarten (rund 3 % der Flaeche).

    Scatter stones, cracks and craters into the matching biome: always as a
    whole stamp and only where the ground matches the family -- a sand dune in
    the middle of rock looks wrong. Density follows the original maps.
    """
    if ziel_zellen <= 0 or not tm.details:
        return 0
    h, w = grid.shape
    gesetzt = 0
    versuche = 0
    while gesetzt < ziel_zellen and versuche < ziel_zellen * 6 + 200:
        versuche += 1
        tiles, fam = tm.details[int(rng.integers(len(tm.details)))]
        dh, dw = tiles.shape
        if dw + 2 >= w or dh + 2 >= h:
            continue
        x = int(rng.integers(1, w - dw - 1))
        y = int(rng.integers(1, h - dh - 1))
        if gesperrt[y:y + dh, x:x + dw].any():
            continue
        if fam and fam in tm.families:
            unter = fam_field[y:y + dh, x:x + dw]
            if float((unter == tm.families.index(fam)).mean()) < 0.75:
                continue
        grid[y:y + dh, x:x + dw] = tiles
        gesperrt[y:y + dh, x:x + dw] = True
        gesetzt += dw * dh
    return gesetzt


def _place_formations(grid, fam_field, tm, rng, anzahl, gesperrt):
    """Fertige Klippenformationen aus den Originalkarten setzen.

    Ihre Zelltypen (Klippen, Hoch-/Tiefseite) kommen mit den Kacheln mit, die
    Form ist handgebaut -- deshalb sehen sie aus wie im Original.

    Place ready-made cliff formations from the original maps. Their cell types
    come with the tiles and the shape is hand-built, which is exactly why they
    look like the originals.
    """
    if anzahl <= 0 or not tm.formations:
        return []
    h, w = grid.shape
    gesetzt = []
    versuche = 0
    while len(gesetzt) < anzahl and versuche < 400:
        versuche += 1
        tiles, fam = tm.formations[int(rng.integers(len(tm.formations)))]
        fh, fw = tiles.shape
        if fw + 6 >= w or fh + 6 >= h:
            continue
        x = int(rng.integers(3, w - fw - 3))
        y = int(rng.integers(3, h - fh - 3))
        # Nur dort setzen, wo der Untergrund zur Formation passt -- sonst
        # steht eine Erd-Mesa im Sand und bringt ihren Untergrund mit.
        # Only place where the ground matches the formation, otherwise a dirt
        # mesa stands in the sand and drags its ground along.
        if fam and fam in tm.families:
            unter = fam_field[y:y + fh, x:x + fw]
            anteil = float((unter == tm.families.index(fam)).mean())
            if anteil < 0.5:
                continue
        bereich = (slice(max(0, y - 2), y + fh + 2), slice(max(0, x - 2), x + fw + 2))
        if gesperrt[bereich].any():
            continue
        # NUR die Klippenzellen samt schmalem Saum uebernehmen -- der
        # Ausschnitt bringt sonst den Untergrund der Originalkarte mit und
        # klebt als rechteckiger Fleck im Gelaende.
        # Copy ONLY the cliff cells plus a narrow seam -- otherwise the cutout
        # drags along the original map's ground and sits in the terrain as a
        # rectangular patch.
        maske = np.zeros(tiles.shape, dtype=bool)
        for t in np.unique(tiles):
            if celltypes.default_cell_type(int(t), fallback=-1) in (
                    celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
                    celltypes.CLIFFS_LOW_SIDE):
                maske |= tiles == t
        saum = maske.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                saum |= np.roll(np.roll(maske, dy, axis=0), dx, axis=1)
        ziel = grid[y:y + fh, x:x + fw]
        grid[y:y + fh, x:x + fw] = np.where(saum, tiles, ziel)
        gesperrt[bereich] = True
        gesetzt.append((x + fw // 2, y + fh // 2))
    return gesetzt


def _place_mesas(grid, plateau, fam_field, tm, rng, anzahl, gesperrt):
    """Einzelne Mesa-Motive in die freie Flaeche setzen.

    Die Teilmotive (60-80 % Klippe) sind fertige kleine Felsformationen mit
    eigenem Umriss -- als Wandstueck untauglich, einzeln gesetzt aber genau
    das, was die Originalkarten zeigen.

    Place single mesa motifs in the open. The partial motifs (60-80 % cliff)
    are finished little rock formations with their own outline -- useless as a
    wall piece, but placed singly they are exactly what the originals show.
    """
    if anzahl <= 0:
        return []
    h, w = grid.shape
    gesetzt = []
    versuche = 0
    while len(gesetzt) < anzahl and versuche < 200:
        versuche += 1
        fam_idx = int(fam_field[int(rng.integers(h)), int(rng.integers(w))])
        fam = tm.families[fam_idx] if 0 <= fam_idx < len(tm.families) else "mud"
        pool = tm.cliff_pool.get((fam, "Motiv"))
        if not pool:
            pool = next((v for k, v in tm.cliff_pool.items() if k[1] == "Motiv"), None)
        if not pool:
            return gesetzt
        tiles = pool[int(rng.integers(len(pool)))]
        sh, sw = tiles.shape
        x = int(rng.integers(2, max(3, w - sw - 2)))
        y = int(rng.integers(2, max(3, h - sh - 2)))
        bereich = (slice(max(0, y - 2), y + sh + 2), slice(max(0, x - 2), x + sw + 2))
        if plateau[bereich].any() or gesperrt[bereich].any():
            continue
        grid[y:y + sh, x:x + sw] = tiles
        gesperrt[bereich] = True
        gesetzt.append((x + sw // 2, y + sh // 2))
    return gesetzt


def _volcano_sites(fam_field: np.ndarray, params: "MapGenParams",
                   rng: np.random.Generator, rock_family: int) -> list[tuple[int, int]]:
    """Standorte fuer Vulkane suchen und die Umgebung auf Fels stellen.

    Der Vulkan selbst ist ein Kachel-Stempel, die Lava kommt spaeter im Spiel
    aus dem Ausbruch -- hier wird nur der Untergrund vorbereitet.

    Find volcano sites and turn their surroundings into rock. The volcano
    itself is a tile stamp; the lava comes from the eruption in-game -- this
    only prepares the ground.
    """
    if params.volcanoes <= 0:
        return []
    h, w = fam_field.shape
    radius = max(6, int(round((params.lava_zone_tiles / np.pi) ** 0.5)))
    margin = radius + 4
    if w <= 2 * margin or h <= 2 * margin:
        return []

    def mirrored(cx: int, cy: int) -> list[tuple[int, int]]:
        if params.symmetry == SYM_MIRROR_X:
            return [(w - 1 - cx, cy)]
        if params.symmetry == SYM_MIRROR_Y:
            return [(cx, h - 1 - cy)]
        if params.symmetry == SYM_ROT180:
            return [(w - 1 - cx, h - 1 - cy)]
        if params.symmetry == SYM_QUAD:
            return [(w - 1 - cx, cy), (cx, h - 1 - cy), (w - 1 - cx, h - 1 - cy)]
        return []

    ys, xs = np.mgrid[0:h, 0:w]
    centres: list[tuple[int, int]] = []
    wanted = params.volcanoes
    guard = 0
    while len(centres) < wanted and guard < 40:
        guard += 1
        cx = int(rng.integers(margin, w - margin))
        cy = int(rng.integers(margin, h - margin))
        if any((cx - ox) ** 2 + (cy - oy) ** 2 < (3 * radius) ** 2 for ox, oy in centres):
            continue
        for gx, gy in [(cx, cy)] + mirrored(cx, cy):
            if len(centres) >= wanted:
                break
            # Vulkane stehen im Fels -- die Umgebung entsprechend setzen,
            # mit unregelmaessigem Rand statt Kreis.
            # Volcanoes sit in rock -- set the surroundings accordingly, with
            # an irregular rim instead of a circle.
            wobble = 0.75 + 0.5 * _value_noise(rng, h, w, 8)
            dist = np.sqrt((xs - gx) ** 2 + (ys - gy) ** 2)
            fam_field[dist < radius * wobble] = rock_family
            centres.append((gx, gy))
    return centres


def _lava_zone(centre: tuple[int, int], shape: tuple[int, int],
               tiles: int, rng: np.random.Generator) -> list[tuple[int, int]]:
    """Flaeche, in der beim Ausbruch Lava fliessen darf (lavaPossible).

    Kein Gelaende, sondern eine Angabe fuer die Mission: der Codegen setzt
    daraus `GameMap::SetLavaPossible(...)`.

    The area in which lava may flow during an eruption. Not terrain but a
    mission fact: codegen turns it into `GameMap::SetLavaPossible(...)`.
    """
    h, w = shape
    cx, cy = centre
    radius = max(4, int(round((tiles / np.pi) ** 0.5)))
    wobble = 0.7 + 0.6 * _value_noise(rng, h, w, 10)
    ys, xs = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    mask = dist < radius * wobble
    ys_i, xs_i = np.nonzero(mask)
    return [(int(x), int(y)) for x, y in zip(xs_i, ys_i)]


def _stamp_volcanoes(grid: np.ndarray, centres: list[tuple[int, int]],
                     tm: "TileModel", rng: np.random.Generator) -> list[tuple[int, int]]:
    """In jedes Lavagebiet einen Vulkan setzen (echter Stempel aus der Karte)."""
    placed = []
    if not tm.volcanoes:
        return placed
    h, w = grid.shape
    for cx, cy in centres:
        name, vw, vh, block = max(tm.volcanoes, key=lambda v: v[1] * v[2])
        if vw > w or vh > h:
            name, vw, vh, block = min(tm.volcanoes, key=lambda v: v[1] * v[2])
        x0 = int(np.clip(cx - vw // 2, 0, w - vw))
        y0 = int(np.clip(cy - vh // 2, 0, h - vh))
        grid[y0:y0 + vh, x0:x0 + vw] = block
        placed.append((x0 + vw // 2, y0 + vh // 2))
    return placed


def _dissolve_small_biomes(field_: np.ndarray, min_cells: int) -> np.ndarray:
    """Zu kleine Biomflecken im umgebenden Biom aufloesen.

    Ein paar Kacheln Sand mitten in der Erde sehen nach Rauschen aus, nicht
    nach Landschaft. Jede zusammenhaengende Flaeche unter `min_cells` bekommt
    die Familie ihrer haeufigsten Nachbarn.

    Dissolve biome patches that are too small. A few tiles of sand in the
    middle of dirt look like noise, not landscape: every connected area below
    `min_cells` takes the family of its most common neighbours.
    """
    if min_cells <= 1:
        return field_
    h, w = field_.shape
    out = field_.copy()
    besucht = np.zeros(field_.shape, dtype=bool)
    for sy in range(h):
        for sx in range(w):
            if besucht[sy, sx]:
                continue
            fam = int(field_[sy, sx])
            stack = [(sx, sy)]
            besucht[sy, sx] = True
            zellen = []
            rand = []
            while stack:
                x, y = stack.pop()
                zellen.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if int(field_[ny, nx]) == fam:
                        if not besucht[ny, nx]:
                            besucht[ny, nx] = True
                            stack.append((nx, ny))
                    else:
                        rand.append(int(field_[ny, nx]))
            if len(zellen) >= min_cells or not rand:
                continue
            werte, anzahl = np.unique(np.array(rand), return_counts=True)
            ersatz = int(werte[int(np.argmax(anzahl))])
            for x, y in zellen:
                out[y, x] = ersatz
    return out


def _apply_symmetry(field_: np.ndarray, mode: str) -> np.ndarray:
    """Regionen spiegeln -- gespiegelt wird die LAGE, nicht die Kachelgrafik.

    Mirror the regions -- the layout is mirrored, not the tile graphics
    (a mirrored tile index would not be a mirrored picture)."""
    out = field_.copy()
    h, w = out.shape
    if mode == SYM_MIRROR_X:
        out[:, w // 2:] = out[:, :w // 2][:, ::-1]
    elif mode == SYM_MIRROR_Y:
        out[h // 2:, :] = out[:h // 2, :][::-1, :]
    elif mode == SYM_ROT180:
        out[h // 2:, :] = out[:h // 2, :][::-1, ::-1]
    elif mode == SYM_QUAD:
        out[:, w // 2:] = out[:, :w // 2][:, ::-1]
        out[h // 2:, :] = out[:h // 2, :][::-1, :]
    return out


# --------------------------------------------------------------------------
# Kacheln / tiles

def _sample_tiles(fam_field: np.ndarray, rng: np.random.Generator,
                  tm: TileModel) -> np.ndarray:
    """Kacheln zeilenweise aus der gelernten Nachbarschaft ziehen."""
    h, w = fam_field.shape
    grid = np.zeros((h, w), dtype=np.int32)

    def family_pick(fi: int) -> int:
        pool = tm.by_family.get(int(fi))
        if pool is None:
            pool = tm.by_family[next(iter(tm.by_family))]
        tiles, probs = pool
        return int(rng.choice(tiles, p=probs))

    for y in range(h):
        for x in range(w):
            target = int(fam_field[y, x])
            keys = None
            weights = None
            if x > 0:
                keys, weights = tm.right.get(int(grid[y, x - 1]), (None, None))
            if y > 0:
                dkeys, dweights = tm.down.get(int(grid[y - 1, x]), (None, None))
                if keys is None:
                    keys, weights = dkeys, dweights
                elif dkeys is not None:
                    common, ia, ib = np.intersect1d(keys, dkeys, return_indices=True)
                    if len(common):
                        keys, weights = common, weights[ia] * dweights[ib]
                    else:
                        keys, weights = None, None
            if keys is not None and len(keys):
                # Bauteile aussortieren; im Lavagebiet nur Lavakacheln.
                # Filter out building blocks; inside lava only lava tiles.
                allowed = tm.placeable[keys]
                keys, weights = keys[allowed], weights[allowed]
            if keys is None or not len(keys):
                grid[y, x] = family_pick(target)
                continue
            # Auf die Zielfamilie einschraenken. Gibt es keinen gelernten
            # Uebergang dorthin, wird neu angesetzt statt in der falschen
            # Familie weiterzulaufen -- sonst "faerbt" die Startecke die
            # halbe Karte ein und die eingestellte Mischung stimmt nicht.
            # Restrict to the target family. Without a learned transition,
            # reseed instead of carrying on in the wrong family -- otherwise
            # the starting corner tints half the map and the requested mix is
            # not met.
            fams = tm.family_of[keys]
            mask = fams == target
            if mask.any():
                keys, weights = keys[mask], weights[mask]
            elif tm.family_of[grid[y, x - 1] if x > 0 else grid[y - 1, x]] != target:
                grid[y, x] = family_pick(target)
                continue
            probs = weights / weights.sum()
            grid[y, x] = int(rng.choice(keys, p=probs))
    return grid


def _cell_types(grid: np.ndarray) -> np.ndarray:
    """Befahrbarkeit je Kachel aus der gelernten Tabelle."""
    lut = np.full(2048, celltypes.MEDIUM_PASSIBLE_1, dtype=np.uint8)
    for tile in np.unique(grid):
        lut[int(tile)] = celltypes.default_cell_type(int(tile))
    return lut[grid]


# --------------------------------------------------------------------------
# Startpunkte / spawn points

def _passable_mask(cells: np.ndarray) -> np.ndarray:
    passable = np.zeros(32, dtype=bool)
    for cell in range(32):
        passable[cell] = celltypes.speed_class(cell) in PASSABLE_CLASSES
    return passable[cells]


def _clearance(mask: np.ndarray, radius: int) -> np.ndarray:
    """Anteil befahrbarer Kacheln im Quadrat um jede Zelle (Summentabelle)."""
    h, w = mask.shape
    size = 2 * radius + 1
    padded = np.pad(mask.astype(np.int32), radius, mode="constant")
    # Fuehrende Null-Zeile/-Spalte, damit die vier Ecken der Summentabelle
    # ohne Sonderfaelle passen.
    # Leading zero row/column so the four corners of the summed-area table
    # work without special cases.
    integral = np.zeros((padded.shape[0] + 1, padded.shape[1] + 1), dtype=np.int32)
    integral[1:, 1:] = padded.cumsum(0).cumsum(1)
    total = (integral[size:size + h, size:size + w]
             - integral[:h, size:size + w]
             - integral[size:size + h, :w]
             + integral[:h, :w])
    return total / float(size * size)


def _pick_spawns(cells: np.ndarray, count: int, clearance: int,
                 symmetry: str, rng: np.random.Generator) -> list[tuple[int, int]]:
    """Freie, weit auseinander liegende Startplaetze suchen."""
    if count <= 0:
        return []
    mask = _passable_mask(cells)
    free = _clearance(mask, clearance) >= 0.995
    h, w = mask.shape
    margin = clearance + 2
    free[:margin, :] = free[-margin:, :] = False
    free[:, :margin] = free[:, -margin:] = False
    ys, xs = np.nonzero(free)
    if len(xs) == 0:
        return []

    def mirror(p: tuple[int, int]) -> list[tuple[int, int]]:
        x, y = p
        if symmetry == SYM_MIRROR_X:
            return [(w - 1 - x, y)]
        if symmetry == SYM_MIRROR_Y:
            return [(x, h - 1 - y)]
        if symmetry == SYM_ROT180:
            return [(w - 1 - x, h - 1 - y)]
        if symmetry == SYM_QUAD:
            return [(w - 1 - x, y), (x, h - 1 - y), (w - 1 - x, h - 1 - y)]
        return []

    # Bei Symmetrie nur in der Grundhaelfte/-viertel suchen und spiegeln --
    # so sind die Startplaetze fair.
    # With symmetry only search the base half/quadrant and mirror -- that keeps
    # the starting positions fair.
    if symmetry in (SYM_MIRROR_X, SYM_ROT180, SYM_QUAD):
        keep = xs < w // 2
        ys, xs = ys[keep], xs[keep]
    if symmetry in (SYM_MIRROR_Y, SYM_QUAD):
        keep = ys < h // 2
        ys, xs = ys[keep], xs[keep]
    if len(xs) == 0:
        return []

    picked: list[tuple[int, int]] = []
    first = int(rng.integers(len(xs)))
    picked.append((int(xs[first]), int(ys[first])))
    per_mirror = 1 + len(mirror(picked[0]))
    needed = max(1, -(-count // per_mirror))     # aufrunden
    while len(picked) < needed:
        px = np.array([p[0] for p in picked])
        py = np.array([p[1] for p in picked])
        dist = np.min((xs[:, None] - px) ** 2 + (ys[:, None] - py) ** 2, axis=1)
        best = int(np.argmax(dist))
        if dist[best] == 0:
            break
        picked.append((int(xs[best]), int(ys[best])))

    spawns: list[tuple[int, int]] = []
    for p in picked:
        spawns.append(p)
        spawns.extend(mirror(p))
    return spawns[:count] if count <= len(spawns) else spawns


def _connected(cells: np.ndarray, spawns: list[tuple[int, int]]) -> bool:
    """Sind alle Startpunkte ueber befahrbares Gelaende verbunden?"""
    if len(spawns) < 2:
        return True
    mask = _passable_mask(cells)
    h, w = mask.shape
    seen = np.zeros_like(mask)
    stack = [spawns[0]]
    seen[spawns[0][1], spawns[0][0]] = True
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                stack.append((nx, ny))
    return all(seen[y, x] for x, y in spawns)


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


def _hoehenfeld(params: "MapGenParams", rng: np.random.Generator,
                layout: list) -> np.ndarray:
    """Wo soll Hochland sein? Die Form der Klippen, noch ohne eine Kachel.

    Merkmale liefern gezielte Formen (Berg, Tal, Engstelle), der
    Klippen-Regler streut zusaetzliche Blobs. Alles frei erzeugt -- es wird
    nichts mehr aus den Originalkarten kopiert, deshalb gibt es auch keine
    geraden Schnittkanten mehr.

    Where should highland be? The shape of the cliffs, still without a single
    tile. Features contribute deliberate shapes, the cliff slider scatters
    additional blobs. All generated freely -- nothing is copied from the
    original maps any more, which is why there are no straight cut edges left.
    """
    h, w = params.height, params.width
    H = np.zeros((h, w), dtype=np.int8)
    for eintrag in layout:
        kind = eintrag["feat"].kind
        if kind == FEAT_BERG:
            H |= shapegen.blob((h, w), (eintrag["x"], eintrag["y"]),
                               eintrag["radius"], rng, rauheit=0.5)
        elif kind == FEAT_PLATEAU:
            # Plateaus sind flacher und runder als Berge -- man soll oben
            # bauen koennen.
            # Plateaus are flatter and rounder than mountains -- you should be
            # able to build on top.
            H |= shapegen.blob((h, w), (eintrag["x"], eintrag["y"]),
                               int(eintrag["radius"] * 1.3), rng, rauheit=0.25)
        elif kind == FEAT_TAL:
            H |= shapegen.korridor((h, w), eintrag["pfad"], eintrag["breite"], rng)
        elif kind == FEAT_ENGE:
            pfad = eintrag["pfad"]
            mitte = len(pfad) // 2 + int(rng.integers(-len(pfad) // 6,
                                                      len(pfad) // 6 + 1))
            H |= shapegen.riegel((h, w), pfad, mitte,
                                 max(2, eintrag["breite"] // 2), rng)
    anzahl = int(round(params.cliffs * w * h / 900))
    for _ in range(anzahl):
        cx = int(rng.integers(6, max(7, w - 6)))
        cy = int(rng.integers(6, max(7, h - 6)))
        r = int(rng.integers(6, 16))
        H |= shapegen.blob((h, w), (cx, cy), r, rng, rauheit=0.55)
    # Freiflaechen ausstanzen -- dort soll gebaut werden koennen.
    # Punch out clearings -- they are meant to be buildable.
    for eintrag in layout:
        if eintrag["feat"].kind == FEAT_FREI:
            # Mit Zuschlag ausstanzen: das Wandband ist drei Zellen dick und
            # sein Fuss laege sonst noch in der Freiflaeche.
            # Punch with margin: the wall band is three cells thick and its
            # foot would otherwise still lie inside the clearing.
            H = (H & ~_feature_maske(eintrag, (h, w), rand=4)).astype(np.int8)
    if H.any():
        # Kante rasten, sonst franst die Klippe zellenweise aus.
        # Snap the edge, otherwise the cliff frays cell by cell.
        H = shapegen.begradige(H, block=3)
        H = shapegen.entferne_kleinkram(H, mindest=24)
        H[:3, :] = 0
        H[-3:, :] = 0
        H[:, :3] = 0
        H[:, -3:] = 0
    return H


def _male_klippen(grid: np.ndarray, fam_field: np.ndarray, H: np.ndarray,
                  tm: "TileModel", rng: np.random.Generator) -> np.ndarray:
    """Kacheln fuer die Klippenkanten nachschlagen und setzen.

    Fuer jede Randzelle steht durch die Form fest, welchen Zelltyp sie
    braucht. Welche Kachel dazu gehoert, haben die Originalkarten in genau
    dieser Situation schon beantwortet -- und zusaetzlich muss die Kachel zu
    ihrer linken und oberen Nachbarin passen, sonst entsteht wieder eine Naht.

    Look up and place the tiles for the cliff edges. The shape determines which
    cell type each border cell needs; which tile belongs there was already
    answered by the original maps in exactly this situation -- and the tile
    additionally has to fit its left and top neighbour, otherwise a seam
    appears again.
    """
    leer = np.zeros(H.shape, dtype=bool)
    if not tm.shapes.ok or not H.any():
        return leer
    zelltypen = shapegen.zelltypen_aus_form(H, tm.shapes)
    rolle = shapegen.rollen_aus_zelltypen(H, zelltypen)
    h, w = grid.shape
    gesetzt = leer
    ys, xs = np.nonzero(zelltypen >= 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if y < 1 or x < 1 or y >= h - 1 or x >= w - 1:
            continue
        fam = int(fam_field[y, x])
        kacheln, gewichte = tm.shapes.kacheln(rolle[y - 1:y + 2, x - 1:x + 2], fam)
        if kacheln is None or not len(kacheln):
            kacheln, gewichte = tm.shapes.grob(int(zelltypen[y, x]), fam)
        if kacheln is None or not len(kacheln):
            continue
        # Nachbarschaft beruecksichtigen: bevorzugt Kacheln, die im Original
        # rechts von der linken bzw. unter der oberen Nachbarin standen.
        # Respect adjacency: prefer tiles that in the originals stood right of
        # the left neighbour and below the top one.
        passend = np.ones(len(kacheln), dtype=bool)
        for tabelle, nachbar in ((tm.right, int(grid[y, x - 1])),
                                 (tm.down, int(grid[y - 1, x]))):
            eintrag = tabelle.get(nachbar)
            if eintrag is not None:
                passend &= np.isin(kacheln, eintrag[0])
        auswahl = np.nonzero(passend)[0]
        if not len(auswahl):
            auswahl = np.arange(len(kacheln))
        gew = gewichte[auswahl].astype(float)
        gew = gew / gew.sum()
        grid[y, x] = int(kacheln[auswahl[int(rng.choice(len(auswahl), p=gew))]])
        gesetzt[y, x] = True
    return gesetzt


def _sektor_punkt(where: str, w: int, h: int, rng: np.random.Generator,
                  symmetry: str = SYM_NONE) -> tuple[int, int]:
    """Punkt im gewuenschten Sektor, leicht verwackelt."""
    fx, fy = SEKTOREN.get(where, (float(rng.random()), float(rng.random())))
    if where not in SEKTOREN:
        fx = 0.15 + 0.70 * fx
        fy = 0.15 + 0.70 * fy
    x = int(np.clip(fx * w + rng.normal(0, 0.04 * w), 4, w - 5))
    y = int(np.clip(fy * h + rng.normal(0, 0.04 * h), 4, h - 5))
    # Bei Symmetrie in die Grundhaelfte falten -- die Spiegelung zieht das
    # Merkmal danach auf die andere Seite, sonst wird es ueberschrieben.
    # With symmetry fold into the base half -- mirroring copies the feature to
    # the other side afterwards, otherwise it would be overwritten.
    if symmetry in (SYM_MIRROR_X, SYM_ROT180, SYM_QUAD) and x >= w // 2:
        x = w - 1 - x
    if symmetry in (SYM_MIRROR_Y, SYM_QUAD) and y >= h // 2:
        y = h - 1 - y
    return x, y


def _feature_layout(params: "MapGenParams",
                    rng: np.random.Generator) -> list[dict]:
    """Konkrete Geometrie je Merkmal festlegen (vor allem anderen).

    Muss vor der Vulkansuche laufen, damit Freiflaechen dort schon als
    verboten gelten.

    Fix the concrete geometry per feature, before everything else. Must run
    before the volcano search so clearings are already off limits there.
    """
    w, h = params.width, params.height
    klein = min(w, h)
    layout = []
    for feat in params.features:
        if feat.kind not in FEATURE_KINDS:
            continue
        groesse = float(np.clip(feat.size, 0.0, 1.0))
        x, y = _sektor_punkt(feat.where, w, h, rng, params.symmetry)
        eintrag = {"feat": feat, "x": x, "y": y}
        if feat.kind in (FEAT_TAL, FEAT_ENGE):
            ziel = feat.to or GEGENUEBER.get(feat.where or "c", "")
            zx, zy = _sektor_punkt(ziel, w, h, rng, params.symmetry)
            eintrag["pfad"] = _merkmal_pfad((x, y), (zx, zy), rng)
            eintrag["breite"] = (3 + int(round(5 * groesse)) if feat.kind == FEAT_TAL
                                 else 2 + int(round(9 * groesse)))
        else:
            eintrag["radius"] = int(round((0.06 + 0.10 * groesse) * klein))
        layout.append(eintrag)
    return layout


def _merkmal_pfad(start: tuple[int, int], ende: tuple[int, int],
                  rng: np.random.Generator) -> list[tuple[int, int]]:
    """Verwackelte Linie von A nach B.

    Eine gerade Schneise sieht nach Lineal aus; die Stuetzpunkte werden quer
    zur Achse versetzt und dann geglaettet.

    A jittered line from A to B: a straight cut looks like it was drawn with a
    ruler, so the control points are offset across the axis and smoothed.
    """
    x0, y0 = start
    x1, y1 = ende
    laenge = max(abs(x1 - x0), abs(y1 - y0), 1)
    schritte = max(4, laenge // 8)
    dx, dy = (x1 - x0) / laenge, (y1 - y0) / laenge
    quer = (-dy, dx)
    punkte = []
    for i in range(schritte + 1):
        t = i / schritte
        versatz = 0.0 if i in (0, schritte) else float(rng.normal(0, 0.06 * laenge))
        punkte.append((x0 + (x1 - x0) * t + quer[0] * versatz,
                       y0 + (y1 - y0) * t + quer[1] * versatz))
    fein = []
    for i in range(len(punkte) - 1):
        ax, ay = punkte[i]
        bx, by = punkte[i + 1]
        n = max(2, int(max(abs(bx - ax), abs(by - ay))))
        for k in range(n):
            t = k / n
            fein.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    fein.append(punkte[-1])
    return [(int(round(px)), int(round(py))) for px, py in fein]


def _steer_feature_families(fam_field: np.ndarray, layout: list[dict],
                            tm: "TileModel") -> None:
    """Untergrund unter den Merkmalen auf eine Familie mit Formationen stellen.

    271 der 327 Formationen sind Erde, 38 Sand, 18 Fels -- auf Gras oder
    Schnee gaebe es nichts zu setzen. Deshalb bekommt der Bereich vorher den
    passenden Untergrund, sonst faellt das Merkmal mangels Material aus.

    Set the ground under a feature to a family that actually has formations:
    271 of 327 are dirt, 38 sand, 18 rock -- on grass or snow there would be
    nothing to place, so the area gets suitable ground beforehand.
    """
    if not layout:
        return
    h, w = fam_field.shape
    erde = tm.families.index("mud") if "mud" in tm.families else 0
    sand = tm.families.index("san") if "san" in tm.families else erde
    beruehrt = False
    for eintrag in layout:
        if eintrag["feat"].kind == FEAT_FREI:
            continue
        maske = _feature_maske(eintrag, (h, w), rand=3)
        if not maske.any():
            continue
        # Sand behalten, wenn der Bereich ohnehin ueberwiegend Sand ist --
        # sonst klebt ein Erdfleck mitten in der Wueste.
        # Keep sand if the area is mostly sand anyway, otherwise a dirt patch
        # sits in the middle of the desert.
        sand_anteil = float((fam_field[maske] == sand).mean())
        fam_field[maske] = sand if sand_anteil > 0.5 else erde
        beruehrt = True
    if beruehrt:
        # Kante weichzeichnen -- sonst bleibt der Umriss der Steuerflaeche als
        # Naht im Gelaende stehen.
        # Blur the edge, otherwise the outline of the steered area remains
        # visible as a seam in the terrain.
        fam_field[:, :] = _smooth_families(fam_field, 1)


def _feature_maske(eintrag: dict, shape: tuple[int, int], rand: int = 0) -> np.ndarray:
    """Flaeche, die ein Merkmal beansprucht."""
    h, w = shape
    maske = np.zeros((h, w), dtype=bool)
    kind = eintrag["feat"].kind
    if kind in (FEAT_TAL, FEAT_ENGE):
        # Scheiben statt Quadrate: aneinandergereihte Quadrate ergeben ein
        # achsenparalleles Band, und die Familiensteuerung malt dieses Band
        # als hartkantiges Rechteck in die Biomkarte -- genau der Fehler, der
        # als Schnee- und Sandbloecke auf der Karte auftauchte.
        # Discs instead of squares: chained squares form an axis-aligned band,
        # and the family steering paints that band into the biome map as a
        # hard-edged rectangle -- exactly the defect that showed up as snow and
        # sand blocks on the map.
        r = eintrag["breite"] + rand + (4 if kind == FEAT_TAL else 0)
        ys, xs = np.ogrid[:h, :w]
        for px, py in eintrag["pfad"][::2]:
            maske |= ((xs - px) ** 2 + (ys - py) ** 2) <= r * r
    else:
        r = eintrag["radius"] + rand
        cx, cy = eintrag["x"], eintrag["y"]
        ys, xs = np.ogrid[:h, :w]
        maske = ((xs - cx) ** 2 + (ys - cy) ** 2) <= r * r
    return maske


def _formationen_der_art(tm: "TileModel", art: str) -> list[int]:
    """Indizes aller Formationen einer Bauart."""
    return [i for i, k in enumerate(tm.formation_class) if k == art]


def _setze_formation(grid: np.ndarray, tm: "TileModel", idx: int,
                     x: int, y: int, gesperrt: np.ndarray,
                     saum_rand: int = 2) -> bool:
    """Eine bestimmte Formation an eine bestimmte Stelle setzen.

    Wie bei den Zufallsformationen werden nur die Klippenzellen samt schmalem
    Saum kopiert, damit der Ausschnitt nicht als Rechteck im Gelaende klebt.

    Like the random formations, only cliff cells plus a narrow seam are
    copied so the cutout does not sit in the terrain as a rectangle.
    """
    tiles, _ = tm.formations[idx]
    fh, fw = tiles.shape
    h, w = grid.shape
    if x < 1 or y < 1 or x + fw >= w - 1 or y + fh >= h - 1:
        return False
    bereich = (slice(max(0, y - saum_rand), y + fh + saum_rand),
               slice(max(0, x - saum_rand), x + fw + saum_rand))
    if gesperrt[bereich].any():
        return False
    maske = np.zeros(tiles.shape, dtype=bool)
    for t in np.unique(tiles):
        if celltypes.default_cell_type(int(t), fallback=-1) in (
                celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
                celltypes.CLIFFS_LOW_SIDE):
            maske |= tiles == t
    saum = maske.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            saum |= np.roll(np.roll(maske, dy, axis=0), dx, axis=1)
    ziel = grid[y:y + fh, x:x + fw]
    grid[y:y + fh, x:x + fw] = np.where(saum, tiles, ziel)
    gesperrt[bereich] = True
    return True


def _apply_features(grid, fam_field, tm, rng, layout, gesperrt,
                    volcanoes, lava_zones, params, H, klippen) -> dict:
    """Zaehlen, was von den Merkmalen tatsaechlich auf der Karte gelandet ist.

    Gebaut wird nichts mehr hier -- die Form steckt im Hoehenfeld, die Kacheln
    hat die Nachschlagetabelle gesetzt. Diese Funktion meldet nur noch, wie
    viele Klippenzellen je Merkmal entstanden sind, und traegt das Lavafeld
    eines Tals nach.

    Count what actually ended up on the map. Nothing is built here any more --
    the shape lives in the height field and the tiles were placed by the lookup
    table. This only reports how many cliff cells each feature produced and
    adds the lava field of a valley.
    """
    bericht = {k: 0 for k in FEATURE_KINDS}
    h, w = grid.shape
    for eintrag in layout:
        kind = eintrag["feat"].kind
        maske = _feature_maske(eintrag, (h, w), rand=4)
        if kind == FEAT_FREI:
            gesperrt |= maske
            bericht[kind] += 1
            continue
        bericht[kind] += int((klippen & maske).sum())
        # Merkmalsflaechen fuer Streugut und Vulkane sperren, damit die
        # gewuenschte Form nicht zugestellt wird.
        # Block feature areas against scatter and volcanoes so the requested
        # shape does not get cluttered.
        gesperrt |= maske
        if kind == FEAT_TAL and eintrag["feat"].lava:
            # Keine Lavakacheln -- nur das Feld, auf dem im Spiel Lava
            # fliessen darf. Die Sohle ist der Weg zwischen den Waenden.
            # No lava tiles -- only the field on which lava may flow in-game.
            # The floor is the path between the walls.
            sohle = []
            for px, py in eintrag["pfad"]:
                for dx in range(-eintrag["breite"], eintrag["breite"] + 1):
                    for dy in range(-eintrag["breite"], eintrag["breite"] + 1):
                        x, y = px + dx, py + dy
                        if 0 <= x < w and 0 <= y < h and not H[y, x]:
                            sohle.append((x, y))
            if sohle:
                lava_zones.append(sorted(set(sohle)))
    return bericht


def generate(params: MapGenParams) -> GeneratedMap:
    """Karte aus den Parametern erzeugen (gleicher Seed = gleiche Karte)."""
    tm = model()
    rng = np.random.default_rng(params.seed)
    fam_field = _family_field(params, rng, tm.families)
    fam_field = _apply_symmetry(fam_field, params.symmetry)
    # Erst glaetten, dann Lava setzen -- sonst frisst die Glaettung das
    # Lavagebiet wieder weg.
    # Smooth first, place lava after -- otherwise smoothing eats the lava area.
    fam_field = _smooth_families(fam_field, params.smooth)
    fam_field = _dissolve_small_biomes(
        fam_field, int(round(params.min_biome * params.width * params.height)))
    # Symmetrie danach erneut anwenden -- das Aufloesen arbeitet ortsbezogen
    # und koennte die Spiegelung sonst brechen.
    # Re-apply symmetry afterwards -- dissolving works locally and could
    # otherwise break the mirroring.
    fam_field = _apply_symmetry(fam_field, params.symmetry)
    rock_family = tm.families.index("roc") if "roc" in tm.families else 0
    # Merkmale zuerst verorten: die Vulkansuche muss Freiflaechen kennen und
    # der Untergrund unter einem Merkmal braucht passende Formationen.
    # Locate features first: the volcano search must know about clearings and
    # the ground under a feature needs matching formations.
    layout = _feature_layout(params, rng)
    sites = _volcano_sites(fam_field, params, rng, rock_family)
    frei = np.zeros(fam_field.shape, dtype=bool)
    for eintrag in layout:
        if eintrag["feat"].kind == FEAT_FREI:
            frei |= _feature_maske(eintrag, fam_field.shape)
    if frei.any():
        sites = [(vx, vy) for vx, vy in sites if not frei[vy, vx]]
    _steer_feature_families(fam_field, layout, tm)
    grid = _sample_tiles(fam_field, rng, tm)
    volcanoes = _stamp_volcanoes(grid, sites, tm, rng)
    lava_zones = [_lava_zone(v, grid.shape, params.lava_zone_tiles, rng)
                  for v in volcanoes]

    # Klippen: erst die Form, dann die Kacheln. Das Kopieren fertiger
    # Ausschnitte aus den Originalkarten ist raus -- es sah aufgeklebt aus,
    # weil ein Ausschnitt seinen eigenen Boden mitbringt und an der Naht
    # Kacheln aufeinandertreffen, die im Original nie nebeneinander lagen.
    # Cliffs: shape first, tiles second. Copying finished cutouts from the
    # original maps is gone -- it looked glued on, because a cutout brings its
    # own ground along and at the seam tiles meet that never sat next to each
    # other in the original.
    gesperrt = np.zeros(grid.shape, dtype=bool)
    for vx, vy in sites:
        gesperrt[max(0, vy - 10):vy + 11, max(0, vx - 10):vx + 11] = True
    flaeche = params.width * params.height
    H = _hoehenfeld(params, rng, layout)
    if params.symmetry != SYM_NONE:
        H = _apply_symmetry(H, params.symmetry).astype(np.int8)
    # Vulkane freihalten: eine Klippe mitten im Krater ergibt keinen Sinn.
    # Keep volcanoes clear: a cliff in the middle of the crater makes no sense.
    H[gesperrt] = 0
    klippen = _male_klippen(grid, fam_field, H, tm, rng)
    gesperrt |= klippen
    feature_bericht = _apply_features(grid, fam_field, tm, rng, layout,
                                      gesperrt, volcanoes, lava_zones, params,
                                      H, klippen)
    mesas = []
    # Streugut zum Schluss -- es soll sich um die Klippen herum verteilen,
    # nicht unter ihnen liegen.
    # Scatter last -- it should spread around the cliffs, not underneath.
    detail_zellen = _scatter_details(
        grid, fam_field, tm, rng,
        int(round(params.details * 0.06 * flaeche)), gesperrt)
    if params.symmetry != SYM_NONE:
        _mirror_region(grid, params.symmetry)
    cells = _cell_types(grid)
    spawns = _pick_spawns(cells, params.spawns, params.spawn_clearance,
                          params.symmetry, rng)
    shares = {}
    for i, name in enumerate(tm.families):
        share = float((tm.family_of[grid] == i).mean())
        if share > 0:
            shares[name] = share
    return GeneratedMap(
        tiles=grid,
        cells=cells,
        spawns=spawns,
        passable_share=float(_passable_mask(cells).mean()),
        family_share=shares,
        connected=_connected(cells, spawns),
        plateau_share=float(np.isin(cells, [celltypes.NORTH_CLIFFS,
                                            celltypes.CLIFFS_HIGH_SIDE,
                                            celltypes.CLIFFS_LOW_SIDE]).mean()),
        mesas=mesas,
        detail_share=detail_zellen / float(params.width * params.height),
        features=feature_bericht,
        feature_spots=[(e["feat"].kind, e["x"], e["y"],
                        e.get("radius", e.get("breite", 0)))
                       for e in layout],
        volcanoes=volcanoes,
        lava_zones=lava_zones,
    )


def apply_to_map(base: Op2Map, generated: GeneratedMap) -> Op2Map:
    """Erzeugtes Gelaende in eine Stock-Karte uebertragen.

    Tilesets, TileMappings, terrainTypes und TileGroups bleiben die der
    Vorlage -- nur Groesse und Kacheln werden ersetzt.

    Transfer generated terrain into a stock map; tilesets, mappings, terrain
    types and tile groups stay those of the template."""
    h, w = generated.tiles.shape
    base.lg_width = int(np.log2(w))
    base.width, base.height = w, h
    base.tiles = [0] * (w * h)
    base.clip_rect = (32, 0, 31 + w, h - 2)
    for y in range(h):
        for x in range(w):
            base.set_tile(x, y, int(generated.tiles[y, x]), int(generated.cells[y, x]))
    return base
