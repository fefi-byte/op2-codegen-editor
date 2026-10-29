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

import math
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from collections import Counter

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


class TileModel:
    """Gelernte Nachbarschaft + Familienzuordnung der Kacheln."""

    def __init__(self, path: Path | None = None):
        data = np.load(path or MODEL_PATH, allow_pickle=False)
        self.families = [str(f) for f in data["families"]]
        # Formtabellen: Klippen entstehen daraus, statt kopiert zu werden.
        # Shape tables: cliffs are generated from these instead of copied.
        self.shapes = shapegen.ShapeTables(data)
        # Uebergangskacheln: je Bodenpaar die Kacheln samt gelerntem
        # Mischgrad (0 = fast nur A, 1 = fast nur B).
        # Transition tiles: per ground pair the tiles with their learned blend
        # level (0 = almost only A, 1 = almost only B).
        self.mix_quantile = (np.asarray(data["trans_quantile"], dtype=np.float32)
                             if "trans_quantile" in data else None)
        # Randkacheln je (Bodenpaar, Richtung) -- das ist die eigentliche
        # Auswahl. Nach Mischgrad allein blieben hunderte Kacheln je Paar und
        # die Grenze wurde zu Rauschen; mit der Richtung sind es 16.
        # Border tiles per (ground pair, direction) -- this is the actual
        # choice. By blend level alone hundreds of tiles remained per pair and
        # the border turned into noise; with the direction there are 16.
        self.rand: dict[tuple[str, str], dict[int, tuple]] = {}
        if "border_keys" in data and len(data["border_keys"]) > 1:
            paare = [tuple(str(p).split("|")) for p in data["border_pairs"]]
            keys = data["border_keys"]
            offs = data["border_offsets"]
            for i, schl in enumerate(keys.tolist()):
                paar, richtung = paare[schl // 8], schl % 8
                lo, hi = int(offs[i]), int(offs[i + 1])
                if hi > lo and len(paar) == 2:
                    self.rand.setdefault(paar, {})[richtung] = (
                        data["border_tiles"][lo:hi],
                        data["border_counts"][lo:hi].astype(float))

        self.trans: dict[tuple[str, str], list[tuple[int, float]]] = {}
        if "trans_tiles" in data and len(data["trans_tiles"]) > 1:
            for tile, a, b, mix in zip(data["trans_tiles"], data["trans_a"],
                                       data["trans_b"], data["trans_mix"]):
                self.trans.setdefault((str(a), str(b)), []).append(
                    (int(tile), float(mix)))
            for eintraege in self.trans.values():
                eintraege.sort(key=lambda t: t[1])
        # Mischgrad je Kachel: 0 = fast nur Boden A, 1 = fast nur B.
        # Blend level per tile: 0 = almost only ground A, 1 = almost only B.
        self.mix_of = {t: m for e in self.trans.values() for t, m in e}
        self.right = self._index(data["right"])
        self.down = self._index(data["down"])
        # Umkehrtabellen: zu einer Kachel alle, die links bzw. darueber
        # stehen duerfen. Die Vorausschau auf feste Nachbarn fragt genau das
        # und war ohne diese Tabellen mit 66 % der Rechenzeit der Flaschenhals
        # beim Malen.
        # Reverse tables: for a tile, everything allowed to its left or above.
        # The look-ahead at fixed neighbours asks exactly that and, without
        # these tables, was the bottleneck while painting at 66 % of the time.
        self.right_rev = self._umkehren(self.right)
        self.down_rev = self._umkehren(self.down)
        self._nachbar_cache: dict = {}
        self._abstand_cache: dict = {}
        self._daten = data
        self.gruppe = (np.asarray(data["gruppen"], dtype=np.int32)
                       if "gruppen" in data else None)
        usage = data["usage"]
        self.usage = dict(zip(usage[:, 0].tolist(), usage[:, 1].tolist()))
        self._usage_summe = float(sum(self.usage.values())) or 1.0
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
        # Nur was die Originalkarten oft genug benutzen, darf frei gesetzt
        # werden. Mauern, Tubes, Wracks und Schutt stehen dort als fertige
        # Bauteile in Missionen, nicht als Landschaft -- `sanwrk17` etwa kommt
        # in 33 Karten neunmal vor.
        #
        # Frueher hat die gelernte Paartabelle sie nebenbei ausgesperrt: sie
        # standen nie neben normalem Boden, also kam die Kombination nie vor.
        # Die Kantenregel prueft aber nur den Rand, und der Rand eines
        # Wrackteils auf Sand sieht aus wie Sand. Schlimmer noch: die rechte
        # Kante eines Wrackteils passt fast nur zum naechsten Wrackteil, also
        # blieb der Sampler nach einer einzigen Fehlplatzierung mit 93,9 % in
        # derselben Gruppe -- eine Kachel zog einen ganzen Zug nach sich. So
        # kamen 384 statt 34 solcher Kacheln auf eine Karte.
        #
        # Gemessen ueber drei Seeds: ab 20 fallen sie von 384 auf 1, waehrend
        # noch 386 Kacheln frei bleiben. Hoehere Grenzen bringen nichts mehr
        # und nehmen nur Vielfalt weg.
        #
        # Only what the original maps use often enough may be placed freely.
        # Walls, tubes, wrecks and rubble appear there as finished building
        # blocks in missions, not as landscape -- `sanwrk17` for instance
        # occurs nine times across 33 maps.
        #
        # The learned pair table used to lock them out as a side effect: they
        # never stood next to ordinary ground, so the combination never
        # occurred. The edge rule however only checks the border, and the
        # border of a wreck piece on sand looks like sand. Worse, a wreck
        # piece's right edge fits almost only the next wreck piece, so after a
        # single misplacement the sampler stayed in the same group with 93.9 %
        # -- one tile dragged in a whole run. That produced 384 instead of 34
        # such tiles per map.
        #
        # Measured over three seeds: from 20 upwards they drop from 384 to 1
        # while 386 tiles remain free. Higher limits gain nothing and only
        # remove variety.
        for _t in range(len(self.placeable)):
            if int(self.usage.get(int(_t), 0)) < self.MINDEST_NUTZUNG:
                self.placeable[_t] = False

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

        # Uebergangskacheln gehoeren ausschliesslich ins Band. Ueber die
        # Nachbarschaftstabellen konnte der Bodensampler sie trotzdem waehlen
        # (342 von 486 galten als frei setzbar) -- dann malt man Sand und
        # bekommt Mischkacheln mitten hinein.
        # Transition tiles belong to the band only. Through the adjacency
        # tables the ground sampler could still pick them (342 of 486 counted
        # as freely placeable) -- then you paint sand and get blend tiles right
        # in the middle of it.
        for _paar in self.trans.values():
            for _t, _ in _paar:
                self.placeable[int(_t)] = False

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
        # Deko gehoert ins Streugut, nicht in die freie Auswahl. Krater,
        # Felsbrocken und Risse haben einen eigenen Durchgang, der sie in
        # Gruppen und passend zum Untergrund verteilt. Konnte der Sampler sie
        # zusaetzlich einzeln setzen, standen je Karte 71-96 solcher Kacheln
        # zusammenhanglos im Gelaende -- ein Krater mitten im Sand, der zu
        # nichts gehoert.
        # Decoration belongs to the scatter pass, not to the free choice.
        # Craters, boulders and cracks have their own pass that distributes them
        # in groups and to matching ground. When the sampler could place them
        # individually on top, 71-96 such tiles per map stood in the terrain
        # without context -- a crater in the middle of the sand belonging to
        # nothing.
        for _kacheln, _fam in self.details:
            for _t in np.asarray(_kacheln).ravel():
                if 0 <= int(_t) < len(self.placeable):
                    self.placeable[int(_t)] = False
        # Dazu jede Kachel aus einer Verzierungsgruppe, auch wenn sie es nicht
        # in den Stempelvorrat geschafft hat.
        # Plus every tile from a decoration group, even one that did not make it
        # into the stamp pool.
        for _t in data.get("deko", np.array([], dtype=np.int32)):
            if 0 <= int(_t) < len(self.placeable):
                self.placeable[int(_t)] = False
        self._build_family_pools()
        # Zuletzt: die Kantenregel braucht Familien, Uebergaenge und
        # Haeufigkeiten, die weiter oben erst entstehen.
        # Last: the edge rule needs families, transitions and usage
        # counts, which only come into existence further up.
        self._lade_kanten(data)


    # Ab welchem ANTEIL der Nachbarschaften eines Blocks eine seiner Seiten als
    # "hier darf eine Klippe anschliessen" gilt.
    #
    # Bewusst ein Anteil und keine feste Zahl: eine feste haengt daran, wie
    # viele Karten zufaellig im Training liegen. Gemessen an 13 unabhaengig
    # belegten Regeln -- `sanmes00/01/02` ohne Nord/Sued, `07` und `14` ohne
    # Ost/West, `07` stapelbar, `05` ueber `07` -- haelt eine feste 3 bei 33
    # Karten alle 13, bei 107 nur noch 8: drei von 25 Faellen sind ein Signal,
    # drei von 629 sind Rauschen. Mit 10 % bleiben es in beiden Faellen 13.
    #
    # From what SHARE of a block's adjacencies one of its sides counts as "a
    # cliff may adjoin here". Deliberately a share and not a fixed count: a
    # fixed one depends on how many maps happen to be in the training set.
    # Measured against 13 independently established rules, a fixed 3 holds all
    # 13 at 33 maps but only 8 at 107 -- three out of 25 cases is a signal,
    # three out of 629 is noise. At 10 % it stays 13 either way.
    KLIPPEN_ANTEIL = 0.10

    # Grundgewicht fuer eine nie beobachtete Paarung auf einer erlaubten Seite.
    # Die Messung sagt, was die Entwickler taten, nicht was moeglich ist -- Sand
    # bringt nur 7 bis 20 Vorkommen je Block mit. Ein Filter daraus wuerde die
    # Auswahl auf die paar gesehenen Faelle einkochen; als Gewicht bleibt das
    # Seltene selten statt unmoeglich.
    # Base weight for a never-observed pairing on a permitted side. The
    # measurement says what the developers did, not what is possible -- sand
    # brings only 7 to 20 occurrences per block. Turning that into a filter
    # would boil the choice down to the handful of seen cases; as a weight the
    # rare stays rare instead of impossible.
    KLIPPEN_GRUNDRATE = 0.5


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

    # Ab welchem Farbunterschied zwei Kacheln an ihrer gemeinsamen Kante als
    # unvereinbar gelten. Gemessen an den Originalkarten: bei 30 sind 98,6 %
    # aller dort tatsaechlich benachbarten Paare erlaubt, und je Kachel
    # kommen 542 statt 21 Nachbarn in Frage.
    # From what colour difference two tiles count as incompatible along their
    # shared edge. Measured against the original maps: at 30, 98.6 % of all
    # pairs actually adjacent there are allowed, and 542 instead of 21 tiles
    # qualify as neighbours per tile.
    KANTEN_SCHWELLE = 30.0

    # Zusaetzlich der groesste Unterschied EINES Abschnitts. Der Mittelwert
    # allein verduennt eine einzelne verrutschte Ecke: passen sieben von acht
    # Abschnitten, faellt der achte nicht mehr auf, und im Bild endet dann eine
    # dunkle Struktur mitten an der Kachelkante. Gemessen an den Originalen
    # liegt dieser Groesstwert bei echten Nachbarn im Mittel bei 26; mit 55
    # bleiben 95 % der echten Paare erlaubt und noch 472 statt 542 Nachbarn je
    # Kachel -- es fallen also nur die Faelle mit einer stark abweichenden
    # Ecke weg.
    # Additionally the largest difference of a SINGLE segment. The mean alone
    # dilutes one misaligned corner: if seven of eight segments match, the
    # eighth no longer registers, and in the picture a dark structure then ends
    # in the middle of a tile border. Measured against the originals this
    # maximum averages 26 for real neighbours; at 55, 95 % of real pairs stay
    # allowed and 472 instead of 542 neighbours per tile remain -- so only the
    # cases with one strongly deviating corner drop out.
    KANTEN_SPITZE = 55.0

    # In wie viele Abschnitte eine Seite fuer den Musterabgleich zerlegt wird.
    # Jeder Abschnitt bekommt eine Bodenfamilie, und zwei Kacheln duerfen nur
    # aneinander, wenn die gemeinsame Seite dieselbe Folge hat -- Abschnitt fuer
    # Abschnitt, in derselben Leserichtung. Deckt eine Suedseite links bis zur
    # Mitte ab, muss die Nordseite darunter genau dort ebenfalls abdecken.
    #
    # Das ist keine Frage von "nah genug", sondern eine Ja/Nein-Regel, und
    # gemessen halten sich die Originalkarten daran: bei 4 Abschnitten stimmen
    # 95,3 % (waagerecht) und 95,9 % (senkrecht) aller echten Nachbarschaften
    # exakt, und es bleiben 429 erlaubte Nachbarn je Kachel. Feiner (8) faellt
    # auf 93 %, groeber (2) laesst mit 479 Nachbarn zu viel durch.
    #
    # Into how many segments a side is split for the pattern match. Each segment
    # gets a ground family, and two tiles may only join when the shared side has
    # the same sequence -- segment by segment, in the same reading direction. If
    # a south side is covered from the left to the middle, the north side below
    # must be covered exactly there too.
    #
    # This is not a question of "close enough" but a yes/no rule, and measured,
    # the original maps obey it: at 4 segments, 95.3 % (horizontal) and 95.9 %
    # (vertical) of all real adjacencies match exactly, leaving 429 allowed
    # neighbours per tile. Finer (8) drops to 93 %, coarser (2) lets too much
    # through at 479 neighbours.
    MUSTER_ABSCHNITTE = 4

    # Aufschlag auf den Kantenabstand, wenn das Muster nicht passt. Nur fuer die
    # Notwahl gedacht, wo keine Kachel die Bedingung haelt -- dann soll immer
    # noch die mit passendem Muster vorgehen.
    # Surcharge on the edge distance when the pattern does not match. Only for
    # the last-resort choice where no tile satisfies the constraint -- there the
    # one with a matching pattern should still win.
    MUSTER_STRAFE = 100.0

    # Gewicht fuer ein Paar, das die Kantenregel erlaubt, das aber in keiner
    # Originalkarte vorkam. Klein genug, dass Beobachtetes vorgeht, gross
    # genug, dass der Loeser nicht in Sackgassen laeuft.
    # Weight for a pair the edge rule allows but which occurs in no original
    # map: small enough that observed combinations win, large enough that the
    # solver does not run into dead ends.
    # Wie stark die Grundhaeufigkeit einer Kachel gegen die beobachteten
    # Paare zaehlt. Beide auf EINE Skala zu bringen ist der Kern: ein Paar, das
    # in 33 Karten neunmal vorkam, darf nicht so schwer wiegen wie die
    # haeufigste Bodenkachel ueberhaupt, nur weil deren Kombination zufaellig
    # nie beobachtet wurde. Vorher standen hier zwei getrennte Werte, und genau
    # dazwischen entstand die Kettenreaktion: lag erst eine seltene Kachel,
    # zog sie die naechste nach, und die Karte fuellte sich mit Mauern, Tubes
    # und Schrott.
    # How strongly a tile's base frequency counts against the observed pairs.
    # Putting both on ONE scale is the crux: a pair seen nine times across 33
    # maps must not weigh as much as the single most common ground tile merely
    # because that combination happened never to be observed. Two separate
    # values used to live here, and the chain reaction arose exactly in
    # between: once one rare tile was placed it pulled in the next, and the map
    # filled up with walls, tubes and debris.
    GRUNDRATE = 2000.0

    # Wie oft eine Kachel in den 33 Originalkarten vorkommen muss, damit der
    # Generator sie frei setzen darf.
    # How often a tile must occur across the 33 original maps for the generator
    # to place it freely.
    MINDEST_NUTZUNG = 20

    # Obergrenze fuer den Zwischenspeicher der Kantenabstaende. Ein Eintrag ist
    # ein Wert je Kachel, also rund 16 KB; ohne Grenze standen nach vier Karten
    # 3276 Eintraege und 54 MB darin. Bei Ueberlauf ganz leeren statt einzeln zu
    # verdraengen -- eine Karte braucht ihr Arbeitsgebiet ohnehin am Stueck.
    # Upper bound for the edge-distance cache. One entry is one value per tile,
    # about 16 KB; without a limit four maps left 3276 entries and 54 MB in it.
    # On overflow clear it wholesale instead of evicting one by one -- a map
    # needs its working set in one piece anyway.
    ABSTAND_CACHE_MAX = 2048


    def _lade_kanten(self, data) -> None:
        """Kantensignaturen laden und daraus die erlaubten Nachbarn bilden.

        Das ersetzt die gelernte Paartabelle als BEDINGUNG. Sie kannte nur,
        was in 33 Karten zufaellig vorkam -- im Schnitt 21 von 2012 moeglichen
        Nachbarn. Daher die Sackgassen: was links gesetzt wurde, machte rechts
        jede gueltige Wahl unmoeglich. Die Kantenregel ist dagegen berechenbar
        und gilt fuer alle Kacheln.

        This replaces the learned pair table as the CONSTRAINT. That table only
        knew what happened to occur in 33 maps -- 21 of 2012 possible
        neighbours on average, which is where the dead ends came from: what was
        placed on the left made every valid choice on the right impossible. The
        edge rule, by contrast, is computable and holds for every tile.
        """
        self.kanten = np.asarray(data["kanten"], dtype=np.float32) \
            if "kanten" in data else None
        self.kante_rechts: dict[int, np.ndarray] = {}
        self.kante_unten: dict[int, np.ndarray] = {}
        if self.kanten is None or len(self.kanten) < 2:
            return
        n = len(self.kanten)
        gueltig = self.kanten.reshape(n, -1).any(axis=1)
        self._baue_muster(gueltig)
        ost = self.kanten[:, 0]
        west = self.kanten[:, 1]
        sued = self.kanten[:, 2]
        nord = self.kanten[:, 3]
        idx = np.nonzero(gueltig)[0].astype(np.int32)
        # In Bloecken rechnen -- die volle Matrix waere sonst hunderte MB.
        # Compute in blocks; the full matrix would otherwise be hundreds of MB.
        for quelle, ziel, ablage, muster_q, muster_z in (
                (ost, west, self.kante_rechts, 0, 1),
                (sued, nord, self.kante_unten, 2, 3)):
            b = ziel[idx]
            for anfang in range(0, len(idx), 128):
                teil = idx[anfang:anfang + 128]
                d = np.abs(quelle[teil][:, None, :, :]
                           - b[None, :, :, :]).mean(axis=3)
                erlaubt = ((d.mean(axis=2) <= self.KANTEN_SCHWELLE)
                           & (d.max(axis=2) <= self.KANTEN_SPITZE))
                if self.muster is not None:
                    ma = self.muster[teil, muster_q][:, None, :]
                    mb = self.muster[idx, muster_z][None, :, :]
                    gleich = (ma == mb).all(axis=2)
                    betrifft = (self.ist_uebergang[teil][:, None]
                                | self.ist_uebergang[idx][None, :])
                    erlaubt &= gleich | ~betrifft
                for i, t in enumerate(teil):
                    ablage[int(t)] = idx[erlaubt[i]]
        self._baue_nachfolger()

    def _baue_muster(self, gueltig: np.ndarray) -> None:
        """Je Seite eine Folge von Bodenfamilien, ein Eintrag je Abschnitt.

        Reine Kacheln bekommen durchgehend ihre eigene Familie. Bei
        Uebergangskacheln wird je Abschnitt nur zwischen deren BEIDEN Boeden
        entschieden -- eine Zuordnung zur naechsten von allen Familien war zu
        wackelig, weil Fels und Erde farblich nah liegen und reine Kacheln dann
        zufaellig kippten (die Trefferquote fiel damit von 95 auf 60 %).

        One sequence of ground families per side, one entry per segment. Pure
        tiles get their own family throughout. For transition tiles each segment
        is decided between their TWO grounds only -- assigning to the nearest of
        all families was too shaky, because rock and dirt are close in colour
        and pure tiles then flipped at random (the match rate fell from 95 % to
        60 % that way).
        """
        n = len(self.kanten)
        abschnitte = self.MUSTER_ABSCHNITTE
        # Beim Lernen aus den echten Kachelpixeln bestimmt -- zwei Pixelreihen
        # tief, jeder Pixel einzeln eingeordnet und auf hoechstens einen
        # Wechsel je Kante zurechtgerueckt. Aus den gespeicherten Kantenmitteln
        # abzuleiten war ungenauer: eine einzige Pixelreihe kippt an
        # gesprenkelten Grenzen, und ein Mittelwert landet immer zwischen
        # beiden Boeden.
        # Determined during training from the real tile pixels -- two pixel rows
        # deep, every pixel classified individually and snapped to at most one
        # change per edge. Deriving it from the stored edge means was less
        # accurate: a single pixel row flips on dithered borders, and a mean
        # always lands between the two grounds.
        gelernt = self._daten.get("muster") if hasattr(self, "_daten") else None
        if gelernt is not None and len(gelernt) >= n:
            self.muster = np.asarray(gelernt[:n], dtype=np.int16)
            self.ist_uebergang = np.zeros(n, dtype=bool)
            for (na, nb), liste in self.trans.items():
                if na in self.families and nb in self.families:
                    for t, _ in liste:
                        if 0 <= int(t) < n:
                            self.ist_uebergang[int(t)] = True
            return
        segmente = self.kanten.shape[2]
        if segmente % abschnitte:
            self.muster = None
            return
        grob = self.kanten.reshape(n, 4, abschnitte,
                                   segmente // abschnitte, 3).mean(axis=3)

        # Kachel -> Bodenpaar aus der Uebergangstabelle
        paar_von: dict[int, tuple[int, int]] = {}
        for (na, nb), liste in self.trans.items():
            if na in self.families and nb in self.families:
                a = self.families.index(na)
                b = self.families.index(nb)
                for t, _ in liste:
                    paar_von[int(t)] = (a, b)

        farbe: dict[int, np.ndarray] = {}
        for fi in range(len(self.families)):
            rein = [t for t in range(n)
                    if gueltig[t] and self.family_of[t] == fi
                    and self.usage.get(int(t), 0) >= 100 and t not in paar_von]
            if len(rein) >= 3:
                farbe[fi] = grob[rein].reshape(-1, 3).mean(axis=0)

        # Nur Uebergangskacheln tragen ueberhaupt ein Muster, das etwas
        # aussagt. Bei einer reinen Kachel sind alle Abschnitte dieselbe
        # Familie -- verlangt man dann Gleichheit, duerfen zwei reine Kacheln
        # verschiedener Familien NIE aneinander, und die Biomgrenze kann nur
        # noch durch Uebergangskacheln laufen. Wo die fehlen, rastet sie auf
        # ganze Kacheln: im Bild wurde aus einem organischen Bewuchsrand eine
        # gerade Rastertreppe.
        # Only transition tiles carry a pattern that says anything. On a pure
        # tile all segments are the same family -- demanding equality then means
        # two pure tiles of different families may NEVER touch, and the biome
        # border can only run through transition tiles. Where those are missing
        # it snaps to whole tiles: in the picture an organic vegetation border
        # turned into a straight staircase.
        self.ist_uebergang = np.zeros(n, dtype=bool)
        for t in paar_von:
            if 0 <= t < n:
                self.ist_uebergang[t] = True
        muster = np.full((n, 4, abschnitte), -1, dtype=np.int16)
        schluessel = np.array(sorted(farbe)) if farbe else np.array([], int)
        farben = (np.stack([farbe[k] for k in schluessel]) if len(schluessel)
                  else None)
        for t in range(n):
            if not gueltig[t]:
                continue
            paar = paar_von.get(t)
            if paar and paar[0] in farbe and paar[1] in farbe:
                a, b = paar
                da = np.linalg.norm(grob[t] - farbe[a], axis=2)
                db = np.linalg.norm(grob[t] - farbe[b], axis=2)
                muster[t] = np.where(da <= db, a, b)
                continue
            f = int(self.family_of[t])
            if f >= 0:
                muster[t] = f
            elif farben is not None:
                d = np.linalg.norm(grob[t][:, :, None, :] - farben[None, None],
                                   axis=3)
                muster[t] = schluessel[d.argmin(axis=2)]
        self.muster = muster

    def muster_passt(self, a: int, b: int, richtung: str) -> bool:
        """Haben die beiden an ihrer gemeinsamen Seite dasselbe Muster?"""
        if self.muster is None:
            return True
        if not (self.ist_uebergang[int(a)] or self.ist_uebergang[int(b)]):
            return True
        q, z = (0, 1) if richtung == "rechts" else (2, 3)
        return bool((self.muster[int(a), q] == self.muster[int(b), z]).all())

    def _kanten_teile(self, kachel: int, richtung: str,
                      rueck: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Mittelwert und groesster Einzelabschnitt, getrennt."""
        q, z = (0, 1) if richtung == "rechts" else (2, 3)
        if rueck:
            q, z = z, q
        je_abschnitt = np.abs(self.kanten[:, z]
                              - self.kanten[int(kachel), q]).mean(axis=2)
        return je_abschnitt.mean(axis=1), je_abschnitt.max(axis=1)

    def kanten_abstand(self, kachel: int, richtung: str,
                       rueck: bool = False,
                       mit_muster: bool = True) -> np.ndarray:
        """Wie schlecht diese Kachel an jede andere anschliesst.

        Beide Kriterien auf eine Skala gebracht: der Wert ist so normiert, dass
        `<= KANTEN_SCHWELLE` genau dann gilt, wenn Mittelwert UND groesster
        Einzelabschnitt innerhalb ihrer Grenzen liegen.

        `mit_muster=False` laesst die Musterstrafe weg und liefert den reinen
        Farbsprung. Das braucht, wer Muster und Farbe getrennt verrechnet --
        sonst zaehlt die Musterabweichung zweimal.

        How badly this tile joins every other one. Both criteria on one scale:
        the value is normalised so that `<= KANTEN_SCHWELLE` holds exactly when
        the mean AND the largest single segment are within their limits.
        `mit_muster=False` drops the pattern penalty and yields the pure colour
        jump -- needed by callers that score pattern and colour separately,
        otherwise the pattern deviation would count twice.

        Das Ergebnis liegt im Zwischenspeicher -- nicht veraendern.
        The result is cached -- do not modify it.
        """
        schluessel = (int(kachel), richtung, bool(rueck), bool(mit_muster))
        treffer = self._abstand_cache.get(schluessel)
        if treffer is not None:
            return treffer
        q, z = (0, 1) if richtung == "rechts" else (2, 3)
        if rueck:
            q, z = z, q
        eigen = self.kanten[int(kachel), q]                 # (segmente, 3)
        andere = self.kanten[:, z]                          # (n, segmente, 3)
        je_abschnitt = np.abs(andere - eigen).mean(axis=2)   # (n, segmente)
        mittel = je_abschnitt.mean(axis=1)
        spitze = je_abschnitt.max(axis=1)
        wert = np.maximum(mittel,
                          spitze * self.KANTEN_SCHWELLE / self.KANTEN_SPITZE)
        if self.muster is not None and mit_muster:
            mq, mz = (0, 1) if richtung == "rechts" else (2, 3)
            if rueck:
                mq, mz = mz, mq
            passt = (self.muster[:, mz] == self.muster[int(kachel), mq]).all(axis=1)
            betrifft = self.ist_uebergang | self.ist_uebergang[int(kachel)]
            wert = wert + np.where(passt | ~betrifft, 0.0, self.MUSTER_STRAFE)
        if len(self._abstand_cache) >= self.ABSTAND_CACHE_MAX:
            self._abstand_cache.clear()
        self._abstand_cache[schluessel] = wert
        return wert

    def nachbarn_schwelle(self, kachel: int, richtung: str, schwelle: float,
                          rueck: bool = False, mit_muster: bool = True):
        """Erlaubte Nachbarn bei gelockerter Schwelle.

        Fuer die Rueckfallstufen: eine Nachbarin ganz zu ignorieren hiesse, an
        dieser Naht alles zuzulassen. Eine groessere Schwelle laesst die Naht
        sichtbarer werden, aber nicht beliebig.

        Allowed neighbours at a relaxed threshold. For the fallback levels:
        ignoring a neighbour entirely would allow anything at that seam; a
        larger threshold lets the seam become more visible, but not arbitrary.
        """
        schluessel = (int(kachel), richtung, float(schwelle), bool(rueck),
                      bool(mit_muster))
        treffer = self._nachbar_cache.get(schluessel)
        if treffer is not None:
            return treffer
        if self.kanten is None or len(self.kanten) < 2:
            return None, None
        # Nur der Mittelwert wird gelockert. Spitze und Muster bleiben hart:
        # ein normiertes Gesamtmass hat beim Lockern auch die Spitze mitgezogen
        # (bei Schwelle 60 waere ein Einzelabschnitt bis 110 durchgegangen), und
        # gemessen stiegen die sichtbaren Brueche dadurch von 0,24 auf 1,78 % --
        # die Stufen feuerten in 7,1 % der Zellen statt in 0,2 %.
        # Only the mean is relaxed. Peak and pattern stay hard: a single
        # normalised measure dragged the peak along when relaxing (at threshold
        # 60 a single segment up to 110 would have passed), and measured, visible
        # breaks rose from 0.24 to 1.78 % because the levels fired in 7.1 % of
        # cells instead of 0.2 %.
        mittel, spitze = self._kanten_teile(kachel, richtung, rueck)
        gueltig = self.kanten.reshape(len(self.kanten), -1).any(axis=1)
        erlaubt = (mittel <= schwelle) & (spitze <= self.KANTEN_SPITZE) & gueltig
        if self.muster is not None and mit_muster:
            mq, mz = (0, 1) if richtung == "rechts" else (2, 3)
            if rueck:
                mq, mz = mz, mq
            gleich = (self.muster[:, mz]
                      == self.muster[int(kachel), mq]).all(axis=1)
            betrifft = self.ist_uebergang | self.ist_uebergang[int(kachel)]
            erlaubt &= gleich | ~betrifft
        keys = np.nonzero(erlaubt)[0].astype(np.int32)
        treffer = (keys, self._gewichte(kachel, richtung, keys, rueck))
        self._nachbar_cache[schluessel] = treffer
        return treffer

    def _gewichte(self, kachel: int, richtung: str, keys: np.ndarray,
                  rueck: bool = False) -> np.ndarray:
        """Beobachtete Paare plus Grundrate der Kachel.

        Entspricht der ueblichen Glaettung: P(b|a) ~ Zaehler(a,b) + a * P(b).
        Ein nie beobachtetes Paar erbt damit die Haeufigkeit, die die Kachel
        ueberhaupt hat -- haeufiger Boden bleibt haeufig, Seltenes selten.

        Observed pairs plus the tile's base rate, i.e. the usual smoothing
        P(b|a) ~ count(a,b) + a * P(b). A never-observed pair thus inherits the
        frequency the tile has at all: common ground stays common, rare stays
        rare.
        """
        grund = self.GRUNDRATE * np.array(
            [self.usage.get(int(k), 0) for k in keys], dtype=float)
        grund /= max(1.0, self._usage_summe)
        # KEINE Untergrenze: eine feste Untergrenze macht alle unbeobachteten
        # Kandidaten gleich wahrscheinlich, und seltene Kacheln gibt es viel
        # mehr als haeufige -- gemessen setzte der Sampler dann 471 Kacheln
        # einer Gruppe, die in 33 Originalkarten neunmal vorkommt.
        # NO floor: a fixed floor makes all unobserved candidates equally
        # likely, and rare tiles far outnumber common ones -- measured, the
        # sampler then placed 471 tiles of a group occurring nine times across
        # 33 original maps.
        gew = np.maximum(grund, 1e-9)
        if rueck:
            tabelle = self.right_rev if richtung == "rechts" else self.down_rev
            erlaubt = tabelle.get(int(kachel))
            if erlaubt is not None:
                gew = gew + np.isin(keys, erlaubt).astype(float)
            return gew
        tabelle = self.right if richtung == "rechts" else self.down
        gelernt = tabelle.get(int(kachel))
        if gelernt is not None:
            zuordnung = {int(k): float(v) for k, v in zip(*gelernt)}
            for i, k in enumerate(keys):
                gew[i] += zuordnung.get(int(k), 0.0)
        return gew

    def nachbarn_rev(self, kachel: int, richtung: str):
        """Welche Kacheln duerfen LINKS bzw. UEBER dieser stehen."""
        schluessel = (int(kachel), richtung, "rev")
        treffer = self._nachbar_cache.get(schluessel)
        if treffer is None:
            treffer = self.nachbarn_schwelle(kachel, richtung,
                                             self.KANTEN_SCHWELLE, rueck=True)
            self._nachbar_cache[schluessel] = treffer
        return treffer

    def _baue_nachfolger(self) -> None:
        """Gibt es hinter Kachel t ueberhaupt eine Kachel der Familie f?

        Mit der Musterregel wird die Bedingung so streng, dass linke und obere
        Nachbarin gemeinsam eine Kachel fordern koennen, die es nicht gibt --
        gemessen in 3,87 % der Zellen, und genau dort entstanden die sichtbaren
        Brueche. Diese Tabelle erlaubt es, solche Sackgassen VOR dem Setzen zu
        meiden, statt sie hinterher zu bemerken.

        Is there any tile of family f behind tile t at all? With the pattern rule
        the constraint becomes strict enough that the left and top neighbour can
        jointly demand a tile that does not exist -- measured in 3.87 % of cells,
        and that is exactly where the visible breaks arose. This table allows
        avoiding such dead ends BEFORE placing instead of noticing them after.
        """
        anzahl = len(self.families)
        self.nachfolger_rechts = np.zeros((2048, anzahl + 1), dtype=bool)
        self.nachfolger_unten = np.zeros((2048, anzahl + 1), dtype=bool)
        for ablage, tabelle in ((self.nachfolger_rechts, self.kante_rechts),
                                (self.nachfolger_unten, self.kante_unten)):
            for t, erlaubt in tabelle.items():
                if not len(erlaubt):
                    continue
                frei = erlaubt[self.placeable[erlaubt]]
                if not len(frei):
                    continue
                fams = self.family_of[frei]
                ablage[int(t), anzahl] = True          # irgendeine Familie
                for f in np.unique(fams):
                    if 0 <= int(f) < anzahl:
                        ablage[int(t), int(f)] = True

    def hat_nachfolger(self, kacheln: np.ndarray, richtung: str,
                       familie: int) -> np.ndarray:
        """Maske: welche dieser Kacheln lassen die Familie noch zu?"""
        ablage = (self.nachfolger_rechts if richtung == "rechts"
                  else self.nachfolger_unten)
        spalte = familie if 0 <= familie < len(self.families) else len(self.families)
        return ablage[kacheln, spalte]

    def familie_nutzbar(self, familie: int) -> bool:
        """Hat dieser Boden ueberhaupt setzbare Kacheln?

        Schnee zum Beispiel hat keine: von 222 Kacheln sind 210 unpassierbar
        und keine erreicht die Mindesthaeufigkeit. Was der Generator nicht als
        Boden setzen kann, soll auch nicht ueber die Formtabelle hereinkommen.

        Does this ground have any placeable tiles at all? Snow for instance has
        none: of 222 tiles 210 are impassable and none reaches the minimum
        frequency. What the generator cannot place as ground should not enter
        through the shape table either.
        """
        if not hasattr(self, "_nutzbar"):
            self._nutzbar = {
                f: bool((self.placeable & (self.family_of == f)).any())
                for f in range(len(self.families))}
        return self._nutzbar.get(int(familie), True)

    def nachbarn(self, kachel: int, richtung: str):
        schluessel = (int(kachel), richtung)
        treffer = self._nachbar_cache.get(schluessel)
        if treffer is None:
            treffer = self._nachbarn_bauen(kachel, richtung)
            self._nachbar_cache[schluessel] = treffer
        return treffer

    def _nachbarn_bauen(self, kachel: int, richtung: str):
        """Erlaubte Nachbarn samt Gewicht -- Kantenregel plus Vorliebe.

        Allowed neighbours with weights: the edge rule decides what is
        possible, the learned frequency what is preferred.
        """
        tabelle = self.right if richtung == "rechts" else self.down
        kante = self.kante_rechts if richtung == "rechts" else self.kante_unten
        erlaubt = kante.get(int(kachel))
        gelernt = tabelle.get(int(kachel))
        if erlaubt is None or not len(erlaubt):
            return gelernt if gelernt is not None else (None, None)
        # Dieselbe Gewichtung wie bei gelockerter Schwelle -- vorher stand
        # hier eine zweite, flache Fassung, und weil der Sampler ueber genau
        # diesen Weg laeuft, blieb jede Verbesserung an `_gewichte` wirkungslos.
        # The same weighting as for a relaxed threshold -- a second, flat
        # version used to live here, and since the sampler runs through exactly
        # this path, every improvement to `_gewichte` had no effect.
        return erlaubt, self._gewichte(kachel, richtung, erlaubt)

    @staticmethod
    def _umkehren(tabelle: dict) -> dict:
        """a -> [b...] wird zu b -> [a...] (als sortierte Felder)."""
        sammler: dict[int, list[int]] = {}
        for a, (keys, _) in tabelle.items():
            for b in keys.tolist():
                sammler.setdefault(int(b), []).append(int(a))
        return {b: np.array(sorted(v), dtype=np.int32) for b, v in sammler.items()}

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
                ("ctx5_keys", "ctx5_offsets", "ctx5_tiles", "ctx5_counts"),
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

    @property
    def paar_hat_satz(self) -> np.ndarray:
        """Matrix: gibt es fuer diese beiden Boeden einen Uebergangssatz?

        Erde neben Bewuchs ist normal -- dafuer gibt es keine Uebergangskacheln,
        der Bewuchs sitzt einfach auf der Erde. Erde neben Fels dagegen kommt in
        den 33 Originalkarten KEIN einziges Mal ohne `mudtoroc` dazwischen vor.
        Die Matrix trennt beide Faelle.

        Matrix: is there a transition set for these two grounds? Dirt beside
        vegetation is normal -- there are no transition tiles for it, the growth
        simply sits on the dirt. Dirt beside rock on the other hand does not
        occur even once without `mudtoroc` in between across the 33 original
        maps. The matrix separates the two cases.
        """
        if getattr(self, "_paar_satz", None) is None:
            n = len(self.families)
            m = np.zeros((n, n), dtype=bool)
            for na, nb in self.trans:
                if na in self.families and nb in self.families:
                    a, b = self.families.index(na), self.families.index(nb)
                    m[a, b] = m[b, a] = True
            self._paar_satz = m
        return self._paar_satz


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
                 + 0.5 * _value_noise(rng, h, w, base_freq * 2)) / 1.5
        scores.append(noise)
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


def _naht_passt(grid: np.ndarray, tm: "TileModel", tiles: np.ndarray,
                x: int, y: int) -> bool:
    """Passt der Rand eines Stempels zu dem, was schon daneben liegt?"""
    h, w = grid.shape
    dh, dw = tiles.shape
    def erlaubt(quelle, ziel, richtung):
        k, _ = tm.nachbarn(int(quelle), richtung)
        return k is None or int(ziel) in k

    for i in range(dw):
        if y > 0 and not erlaubt(grid[y - 1, x + i], tiles[0, i], "unten"):
            return False
        if y + dh < h and not erlaubt(tiles[dh - 1, i], grid[y + dh, x + i], "unten"):
            return False
    for j in range(dh):
        if x > 0 and not erlaubt(grid[y + j, x - 1], tiles[j, 0], "rechts"):
            return False
        if x + dw < w and not erlaubt(tiles[j, dw - 1], grid[y + j, x + dw], "rechts"):
            return False
    return True


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
        # Naht pruefen: der Stempel wird als Ganzes ueber fertigen Boden
        # gelegt. Ohne Pruefung entstehen an seinem Rand Kachelpaare, die es
        # im Original nie gab -- gemessen 1.047 Stueck je drei Karten.
        # Check the seam: the stamp is laid over finished ground as a whole.
        # Without checking, its border creates tile pairs that never existed in
        # the originals -- measured 1,047 across three maps.
        if not _naht_passt(grid, tm, tiles, x, y):
            continue
        if fam and fam in tm.families:
            unter = fam_field[y:y + dh, x:x + dw]
            if float((unter == tm.families.index(fam)).mean()) < 0.75:
                continue
        grid[y:y + dh, x:x + dw] = tiles
        gesperrt[y:y + dh, x:x + dw] = True
        gesetzt += dw * dh
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
                  tm: TileModel, fest: np.ndarray | None = None,
                  familie_zwingend: np.ndarray | None = None) -> np.ndarray:
    """Kacheln zeilenweise aus der gelernten Nachbarschaft ziehen.

    `fest` belegt Zellen vor, die nicht gewuerfelt werden sollen -- die
    Uebergangskacheln an Bodengrenzen. Sie muessen VOR dem Boden feststehen,
    sonst waehlt der Sampler seine Kacheln ohne Wissen um den Uebergang und
    die beiden passen hinterher nicht zusammen. Genau daher stammten 67 % aller
    nie beobachteten Nachbarpaare.

    `fest` pre-fills cells that must not be rolled -- the transition tiles at
    ground borders. They have to be fixed BEFORE the ground, otherwise the
    sampler picks its tiles without knowing about the transition and the two do
    not fit afterwards. That was the source of 67 % of all never-observed tile
    pairs.
    """
    h, w = fam_field.shape
    grid = np.zeros((h, w), dtype=np.int32)

    def family_pick(fi: int) -> int:
        pool = tm.by_family.get(int(fi))
        if pool is None:
            pool = tm.by_family[next(iter(tm.by_family))]
        tiles, probs = pool
        return int(rng.choice(tiles, p=probs))

    # Wie oft welche Stufe gebraucht wurde -- fuer die Messung.
    # How often each level was needed -- for measurement.
    stufen = Counter()
    # Alle frei setzbaren Kacheln -- Grundlage, wenn nur noch die Vorschau
    # eingehalten werden kann.
    # All freely placeable tiles -- the basis when only the look-ahead can
    # still be honoured.
    _frei = np.array([t for t in range(2048) if tm.placeable[t]], dtype=np.int32)
    # Echte Haeufigkeit als Gewicht. Der fruehere Boden von 1.0 hob jede
    # Rarität auf das Niveau der haeufigsten Kachel.
    # Real frequency as the weight. The former floor of 1.0 lifted every rarity
    # to the level of the most common tile.
    alle_kacheln = (_frei, np.array([max(0.01, float(tm.usage.get(int(t), 0)))
                                     for t in _frei]))

    def schnitt(a, b):
        """Zwei gewichtete Kachelmengen schneiden."""
        if a is None:
            return b
        if b is None:
            return a
        keys_a, w_a = a
        keys_b, w_b = b
        gemeinsam, ia, ib = np.intersect1d(keys_a, keys_b, return_indices=True)
        if not len(gemeinsam):
            return None
        return gemeinsam, w_a[ia] * w_b[ib]

    def nur_familie(paar, ziel):
        if paar is None:
            return None
        keys, gew = paar
        maske = tm.family_of[keys] == ziel
        return (keys[maske], gew[maske]) if maske.any() else None

    def nur_platzierbar(paar):
        if paar is None:
            return None
        keys, gew = paar
        maske = tm.placeable[keys]
        return (keys[maske], gew[maske]) if maske.any() else None

    for y in range(h):
        for x in range(w):
            if fest is not None and fest[y, x] >= 0:
                grid[y, x] = int(fest[y, x])
                continue
            target = int(fam_field[y, x])
            links = tm.nachbarn(int(grid[y, x - 1]), "rechts") if x > 0 else None
            oben = tm.nachbarn(int(grid[y - 1, x]), "unten") if y > 0 else None
            if links is not None and links[0] is None:
                links = None
            if oben is not None and oben[0] is None:
                oben = None
            links = nur_platzierbar(links)
            oben = nur_platzierbar(oben)

            # Vorausschauen auf schon festgelegte Zellen rechts und unten.
            # Die Uebergangskacheln stehen fest, BEVOR der Boden gesampelt
            # wird -- ohne diesen Blick nach vorn waehlt der Boden ueber und
            # links von ihnen seine Kachel, ohne sie zu kennen, und genau dort
            # entstehen die Paare, die es im Original nie gab.
            # Look ahead at cells already fixed to the right and below. The
            # transition tiles are set BEFORE the ground is sampled -- without
            # this look-ahead the ground above and left of them picks its tile
            # without knowing them, and that is exactly where the pairs appear
            # that never existed in the originals.
            vorlaeufer = []
            if fest is not None:
                # Auch hier die Kantenregel statt der gelernten Tabelle:
                # die kannte je Kachel 21 Vorgaenger und war damit die
                # strengste verbliebene Bedingung -- sie allein trieb die
                # Rueckfallstufen.
                # The edge rule here too: the learned table knew 21 predecessors
                # per tile and was thus the strictest remaining constraint --
                # it alone drove the fallback levels.
                if x + 1 < w and fest[y, x + 1] >= 0:
                    k, _ = tm.nachbarn_rev(int(fest[y, x + 1]), "rechts")
                    vorlaeufer.append(k if k is not None else _LEER)
                if y + 1 < h and fest[y + 1, x] >= 0:
                    k, _ = tm.nachbarn_rev(int(fest[y + 1, x]), "unten")
                    vorlaeufer.append(k if k is not None else _LEER)

            def passt_voraus(paar):
                """Kandidaten aussortieren, die zur festen Nachbarin nicht passen."""
                if paar is None or not vorlaeufer:
                    return paar
                keys, gew = paar
                maske = np.ones(len(keys), dtype=bool)
                for erlaubte in vorlaeufer:
                    maske &= np.isin(keys, erlaubte)
                    if not maske.any():
                        return None
                return keys[maske], gew[maske]

            # Stufenleiter: immer nur die schwaechste Bedingung fallen lassen.
            # Der alte Notnagel warf bei leerer Auswahl ALLE Bedingungen weg
            # und zog irgendeine Kachel der Zielfamilie -- daher stammten die
            # nie beobachteten Nachbarpaare. Jede Stufe hier haelt noch
            # mindestens eine gelernte Nachbarschaft ein.
            # Ladder: only ever drop the weakest constraint. The old fallback
            # threw away ALL constraints when the choice was empty and drew any
            # tile of the target family -- that was the source of the
            # never-observed tile pairs. Every level here still honours at
            # least one learned adjacency.
            _zwischen = {}

            def beide():
                if "b" not in _zwischen:
                    _zwischen["b"] = schnitt(links, oben)
                return _zwischen["b"]

            def beide_fam():
                if "bf" not in _zwischen:
                    _zwischen["bf"] = nur_familie(beide(), target)
                return _zwischen["bf"]

            def mit_zukunft(paar):
                """Kandidaten, hinter denen es rechts und unten weitergeht."""
                if paar is None or not len(paar[0]):
                    return paar
                keys, gew = paar
                maske = np.ones(len(keys), dtype=bool)
                if x + 1 < w and (fest is None or fest[y, x + 1] < 0):
                    maske &= tm.hat_nachfolger(keys, "rechts",
                                               int(fam_field[y, x + 1]))
                if y + 1 < h and (fest is None or fest[y + 1, x] < 0):
                    maske &= tm.hat_nachfolger(keys, "unten",
                                               int(fam_field[y + 1, x]))
                return (keys[maske], gew[maske]) if maske.any() else None
            # Die Vorschau steht in JEDER Stufe vor allem anderen. Vorher
            # fiel sie in den Rueckfallstufen weg -- in rund 4 % der Zellen,
            # und genau dort entstanden 37 % aller Fehlpaare (Boden gegen
            # Uebergang). Eine feste Nachbarin laesst sich nicht mehr aendern,
            # die Familie schon.
            # The look-ahead comes before everything else in EVERY level.
            # Before it was dropped in the fallback levels -- in about 4 % of
            # cells, and exactly there 37 % of all bad pairs arose (ground
            # against transition). A fixed neighbour cannot be changed any
            # more, the family can.
            # Stufen erst berechnen, wenn sie gebraucht werden. Als Tupel
            # notiert wurden vorher ALLE vierzehn ausgewertet, obwohl die
            # erste in 84 % der Faelle trifft -- das kostete beim Malen ein
            # Vielfaches der noetigen Zeit.
            # Compute a level only when it is needed. Written as a tuple, all
            # fourteen were evaluated before, although the first one hits in
            # 84 % of cases -- while painting that cost a multiple of the time
            # actually required.
            # (Name, Berechnung, haelt die Familie ein). Das dritte Feld
            # ausdruecklich mitfuehren statt aus dem Namen zu raten -- die
            # Stufe "nur Vorschau, jede Familie" enthaelt das Wort Familie und
            # rutschte bei einer Namenspruefung faelschlich durch, obwohl sie
            # gerade die Familie fallen laesst.
            # (name, computation, honours the family). Carry the third field
            # explicitly instead of guessing from the name -- the level
            # "look-ahead only, any family" contains the word family and
            # slipped through a name check although it is the one dropping it.
            def gelockert(schwelle, mit_muster=True):
                """Beide Nachbarn bei groesserer Schwelle."""
                schluessel = f"g{schwelle}{mit_muster}"
                if schluessel not in _zwischen:
                    paar = None
                    nachbarn_da = False
                    for zelle, richtung in (((y, x - 1), "rechts"),
                                            ((y - 1, x), "unten")):
                        if zelle[0] < 0 or zelle[1] < 0:
                            continue
                        nachbarn_da = True
                        t = nur_platzierbar(tm.nachbarn_schwelle(
                            int(grid[zelle]), richtung, schwelle,
                            mit_muster=mit_muster))
                        paar = t if paar is None else schnitt(paar, t)
                    # Wenn es Nachbarn gibt, aber keine Kachel dazu passt, muss
                    # diese Stufe DURCHFALLEN. Vorher stand hier ein Rueckfall
                    # auf alle platzierbaren Kacheln -- also gar keine Bedingung
                    # mehr. Gemessen stammten dadurch 0 von 200 sichtbaren
                    # Bruechen aus der erlaubten Menge: sie entstanden alle in
                    # genau diesem Rueckfall. Nur ohne jede Nachbarin (linke
                    # obere Ecke) ist die freie Wahl richtig.
                    # If there are neighbours but no tile fits them, this level
                    # must FAIL. A fallback to all placeable tiles used to live
                    # here -- that is, no constraint at all. Measured, 0 of 200
                    # visible breaks came from the allowed set: they all arose in
                    # exactly this fallback. Only with no neighbour at all
                    # (top-left corner) is the free choice correct.
                    _zwischen[schluessel] = (
                        paar if nachbarn_da else alle_kacheln)
                return _zwischen[schluessel]

            # Die Leiter lockert jetzt die Schwelle, statt eine Nachbarin ganz
            # fallen zu lassen. Vorher hiess die unterste Stufe "nimm irgendeine
            # Kachel der Familie" -- an dieser Naht durfte damit alles stehen,
            # und genau dort blieben die sichtbaren Brueche uebrig. Mit der
            # Kantenregel gibt es 542 statt 21 Nachbarn, also braucht es das
            # Aufgeben nicht mehr: es reicht, die Naht etwas sichtbarer zu
            # erlauben.
            # The ladder now relaxes the threshold instead of dropping a
            # neighbour entirely. The bottom level used to mean "take any tile
            # of the family" -- anything was allowed at that seam, and that is
            # where the visible breaks remained. With the edge rule there are
            # 542 instead of 21 neighbours, so giving up is no longer necessary:
            # allowing the seam to be slightly more visible suffices.
            # Die Vorausschau zuerst -- sie kostet nur eine Tabellenabfrage und
            # erspart die Sackgasse, in der gar nichts mehr passt.
            # Look-ahead first -- it costs only a table lookup and avoids the
            # dead end in which nothing fits at all.
            # Die Familie ist unantastbar. Vorher liessen vier Stufen sie
            # fallen, sobald keine Kachel der Zielfamilie zu beiden Nachbarn
            # passte -- gemessen bekamen dadurch 505 Zellen je Karte den
            # falschen Boden: Erde mitten im Sand, und bei Bewuchs (nur 21
            # Kacheln, im Schnitt 16 gleichfarbige Nachbarn) wurden 205 Zellen
            # je Karte kurzerhand zu Sand. Wer Sand malt, will Sand.
            #
            # Notwendig wird das Aufgeben dadurch nicht: die letzte Stufe
            # waehlt ohnehin innerhalb der Zielfamilie die Kachel mit der
            # unauffaelligsten Naht.
            #
            # The family is inviolable. Four levels used to drop it as soon as
            # no tile of the target family fitted both neighbours -- measured,
            # 505 cells per map got the wrong ground that way: dirt in the
            # middle of sand, and vegetation (only 21 tiles, 16 same-family
            # neighbours on average) simply turned into sand for 205 cells per
            # map. Whoever paints sand wants sand.
            #
            # Giving up is not necessary for it: the last level picks the tile
            # with the least noticeable seam within the target family anyway.
            leiter = (
                ("streng+Familie+Zukunft",
                 lambda: mit_zukunft(passt_voraus(beide_fam())), True),
                ("streng+Familie", lambda: passt_voraus(beide_fam()), True),
                ("gelockert+Familie",
                 lambda: passt_voraus(nur_familie(gelockert(45.0), target)),
                 True),
                ("weit+Familie",
                 lambda: nur_familie(gelockert(60.0), target), True),
            )
            for name, stufe, _haelt_familie in leiter:
                wahl = stufe()
                if wahl is not None and len(wahl[0]):
                    keys, weights = wahl
                    stufen[name] += 1
                    break
            else:
                # Auch hier nicht raten: von den Kacheln der Zielfamilie die
                # nehmen, deren schlechteste Naht am wenigsten auffaellt.
                # No guessing here either: of the target family's tiles take
                # the one whose worst seam is least noticeable.
                stufen["beste Naeherung"] += 1
                kand = _frei[tm.family_of[_frei] == target]
                if not len(kand):
                    kand = _frei
                schlimmste = np.zeros(len(kand))
                if x > 0:
                    schlimmste = np.maximum(schlimmste, tm.kanten_abstand(
                        int(grid[y, x - 1]), "rechts")[kand])
                if y > 0:
                    schlimmste = np.maximum(schlimmste, tm.kanten_abstand(
                        int(grid[y - 1, x]), "unten")[kand])
                grid[y, x] = int(kand[int(np.argmin(schlimmste))])
                continue
            probs = weights / weights.sum()
            grid[y, x] = int(rng.choice(keys, p=probs))
    _sample_tiles.stufen = stufen
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


def _groesstes_gebiet(mask: np.ndarray) -> np.ndarray:
    """Groesste zusammenhaengende Flaeche einer Maske (4er-Nachbarschaft)."""
    if not mask.any():
        return mask
    h, w = mask.shape
    marke = np.zeros((h, w), dtype=np.int32)
    groessen = [0]
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or marke[sy, sx]:
                continue
            nummer = len(groessen)
            stapel = [(sy, sx)]
            marke[sy, sx] = nummer
            anzahl = 0
            while stapel:
                y, x = stapel.pop()
                anzahl += 1
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if (0 <= ny < h and 0 <= nx < w and mask[ny, nx]
                            and not marke[ny, nx]):
                        marke[ny, nx] = nummer
                        stapel.append((ny, nx))
            groessen.append(anzahl)
    beste = int(np.argmax(groessen))
    return marke == beste


def _pick_spawns(cells: np.ndarray, count: int, clearance: int,
                 symmetry: str, rng: np.random.Generator) -> list[tuple[int, int]]:
    """Freie, weit auseinander liegende Startplaetze suchen."""
    if count <= 0:
        return []
    mask = _passable_mask(cells)
    # Nur im groessten zusammenhaengenden befahrbaren Gebiet suchen. Vorher
    # wurde irgendwo Freiflaeche genommen und hinterher nur GEMELDET, ob die
    # Startplaetze einander erreichen -- bei einem Berg quer ueber der Karte
    # lagen sie dann je nach Zufall auf verschiedenen Seiten. Ein Startplatz,
    # den der Gegner nie erreicht, macht die Karte unbrauchbar.
    # Search only within the largest connected passable area. Previously any
    # free spot was taken and afterwards it was merely REPORTED whether the
    # starts could reach each other -- with a mountain across the map they then
    # landed on opposite sides depending on chance. A start the opponent can
    # never reach makes the map useless.
    mask = _groesstes_gebiet(mask)
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


# --------------------------------------------------------------------------
# Landschaftsmodus: ein Relief statt gestreuter Flecken. Das Hochland ist ein
# Massiv an einer Kartenseite plus freistehende Mesas; ausgetrocknete
# Flussbetten schneiden Schluchten hindurch. Die Klippen entstehen NICHT mehr
# ueber das Zelltypband (_male_klippen), sondern indem die Hochlandkontur als
# Linienzug abgelaufen und mit `klippe_algo.klippe_aus_linie` gesetzt wird --
# derselbe Gelaende-Loeser wie beim Klippenpinsel im Editor.
#
# Landscape mode: one relief instead of scattered patches. The highland is a
# massif anchored at one map side plus free-standing mesas; dry riverbeds cut
# gorges through it. Cliffs are no longer derived from the cell-type band
# (_male_klippen) but by walking the highland contour as a polyline and
# covering it with `klippe_algo.klippe_aus_linie` -- the same terrain solver
# as the editor's cliff brush.

# Moore-Nachbarschaft im Uhrzeigersinn, beginnend im Westen.
# Moore neighbourhood clockwise, starting west.
_MOORE = [(-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1)]


def _fluss_pfad(start, ziel, shape, rng: np.random.Generator
                ) -> list[tuple[int, int]]:
    """Maeandernder Pfad von `start` Richtung `ziel` -> [(x, y)].

    Ein ausgetrocknetes Flussbett ist kein Zufallslauf: es haelt grob die
    Richtung und pendelt seitlich aus. Kurs zum Ziel plus eine langsam
    laufende Seitwaertswelle ergibt genau das; Zufall steckt nur in Phase,
    Wellenlaenge und Auslenkung.

    A meandering path: heading towards the target plus a slowly running
    sideways wave; randomness only in phase, wavelength and amplitude.
    """
    h, w = shape
    x, y = float(start[0]), float(start[1])
    tx, ty = float(ziel[0]), float(ziel[1])
    punkte = [(int(round(x)), int(round(y)))]
    phase = float(rng.uniform(0, 2 * np.pi))
    takt = float(rng.uniform(0.05, 0.09))
    auslenkung = float(rng.uniform(0.5, 0.85))
    for schritt in range(4 * (w + h)):
        dx, dy = tx - x, ty - y
        if float(np.hypot(dx, dy)) < 2.0:
            break
        winkel = float(np.arctan2(dy, dx))
        winkel += auslenkung * float(np.sin(phase + schritt * takt))
        x = min(max(x + float(np.cos(winkel)), 1.0), w - 2.0)
        y = min(max(y + float(np.sin(winkel)), 1.0), h - 2.0)
        p = (int(round(x)), int(round(y)))
        if p != punkte[-1]:
            punkte.append(p)
        if p[0] <= 1 or p[0] >= w - 2 or p[1] <= 1 or p[1] >= h - 2:
            break
    return punkte


def _pfad_band(shape, punkte, radius: float) -> np.ndarray:
    """Zellen im Abstand <= radius um den Pfad -- das Bett bzw. die Schlucht."""
    h, w = shape
    band = np.zeros((h, w), dtype=bool)
    r = int(np.ceil(radius))
    for px, py in punkte:
        y0, y1 = max(0, py - r), min(h, py + r + 1)
        x0, x1 = max(0, px - r), min(w, px + r + 1)
        ys, xs = np.ogrid[y0:y1, x0:x1]
        band[y0:y1, x0:x1] |= ((xs - px) ** 2 + (ys - py) ** 2) <= radius ** 2
    return band


def _dehne(mask: np.ndarray, schritte: int) -> np.ndarray:
    """4er-Dehnung um `schritte` Zellen (randfest, ohne np.roll-Umlauf)."""
    out = mask.copy()
    for _ in range(max(0, schritte)):
        gewachsen = out.copy()
        gewachsen[1:, :] |= out[:-1, :]
        gewachsen[:-1, :] |= out[1:, :]
        gewachsen[:, 1:] |= out[:, :-1]
        gewachsen[:, :-1] |= out[:, 1:]
        out = gewachsen
    return out


def _landschaft_hoehenfeld(params: "MapGenParams", rng: np.random.Generator
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Relief des Landschaftsmodus -> (H, Flussbetten).

    Ein Massiv, an einer zufaelligen Kartenseite verankert, ein bis drei
    freistehende Mesas, und die Flussbetten schneiden Schluchten durch das
    Massiv. Die Kanten werden auf ein Viererraster gerastet: Laeufe unter vier
    Zellen kann der Blockweg nicht sauber belegen (mud-Bloecke sind 3 bis 5
    lang), und ein groeberes Raster erzeugt genau die "mehrere Kacheln
    geradeaus, dann sauber abbiegen"-Kanten der Originalkarten.

    The relief of landscape mode -> (H, riverbeds). A massif anchored at a
    random map side, one to three mesas, riverbeds cutting gorges through the
    massif. Edges are snapped to a four-cell grid: the block path cannot
    cleanly cover runs shorter than four cells.
    """
    h, w = params.height, params.width
    flaeche = w * h
    H = np.zeros((h, w), dtype=np.int8)
    # 0 = West, 1 = Ost, 2 = Nord, 3 = Sued.
    seite = int(rng.integers(4))
    # Zielanteil des Massivs an der Karte; der Klippenregler stockt auf.
    # Target share of the massif; the cliff slider adds to it.
    ziel = 0.16 + 0.45 * params.cliffs
    grundradius = int(round(np.sqrt(flaeche) / 5.5))
    for _ in range(10):
        if float((H > 0).mean()) >= ziel:
            break
        r = int(rng.integers(max(4, grundradius - 4), grundradius + 5))
        laengs = float(rng.uniform(0.08, 0.92))
        tiefe = float(rng.uniform(0.0, 0.55)) * r
        if seite == 0:
            cx, cy = int(tiefe), int(laengs * h)
        elif seite == 1:
            cx, cy = w - 1 - int(tiefe), int(laengs * h)
        elif seite == 2:
            cx, cy = int(laengs * w), int(tiefe)
        else:
            cx, cy = int(laengs * w), h - 1 - int(tiefe)
        H |= shapegen.blob((h, w), (cx, cy), r, rng, rauheit=0.35)
    massiv = H.astype(bool)

    # Mesas: freistehende Tafelberge im Tiefland, mit Abstand vom Massiv.
    # Mesas: free-standing table mountains in the lowland, clear of the massif.
    anzahl_mesas = max(1, int(round(flaeche / 12000)))
    sperr = _dehne(massiv, 8)
    for _ in range(anzahl_mesas * 6):
        if anzahl_mesas <= 0:
            break
        r = int(rng.integers(5, 9))
        cx = int(rng.integers(r + 4, w - r - 4))
        cy = int(rng.integers(r + 4, h - r - 4))
        if sperr[cy, cx]:
            continue
        mesa = shapegen.blob((h, w), (cx, cy), r, rng, rauheit=0.3)
        H |= mesa
        sperr |= _dehne(mesa.astype(bool), 8)
        anzahl_mesas -= 1

    # Flussbetten: Quelle im Massiv, Muendung am gegenueberliegenden Rand.
    # Durch das Massiv wird eine Schlucht geschnitten -- breit genug fuer
    # zwei Wandbaender (je 3) und einen begehbaren Boden dazwischen.
    # Riverbeds: source inside the massif, mouth at the opposite border. The
    # gorge is wide enough for two wall bands (3 each) plus a walkable floor.
    anzahl = params.fluesse
    if anzahl < 0:
        anzahl = max(1, int(round(np.sqrt(flaeche) / 128.0)))
    betten = np.zeros((h, w), dtype=bool)
    innen = massiv & ~_dehne(~massiv, 6)
    ys, xs = np.nonzero(innen if innen.any() else massiv)
    for _ in range(anzahl):
        if not len(ys):
            break
        i = int(rng.integers(len(ys)))
        start = (int(xs[i]), int(ys[i]))
        if seite == 0:
            muendung = (w - 2, int(rng.integers(h // 6, h - h // 6)))
        elif seite == 1:
            muendung = (1, int(rng.integers(h // 6, h - h // 6)))
        elif seite == 2:
            muendung = (int(rng.integers(w // 6, w - w // 6)), h - 2)
        else:
            muendung = (int(rng.integers(w // 6, w - w // 6)), 1)
        pfad = _fluss_pfad(start, muendung, (h, w), rng)
        schlucht = _pfad_band((h, w), pfad, 5.0)
        H[schlucht] = 0
        betten |= _pfad_band((h, w), pfad, 2.1)
        # Gelegentliche Aufweitungen: ein trockener Fluss hat Kolke.
        # Occasional widenings: a dry river has scour pools.
        for px, py in pfad[:: max(1, len(pfad) // 4)][1:]:
            if rng.random() < 0.5:
                betten |= _pfad_band((h, w), [(px, py)],
                                     float(rng.uniform(3.0, 4.0)))

    if H.any():
        # Erst glaetten, dann auf ein FUENFERraster rasten. Fuenf, weil der
        # senkrechte mud-Laufblock genau 5 Zellen hoch ist: jeder Lauf der
        # Kontur laesst sich dann mit ganzen Bloecken belegen. Feinere Raster
        # ergaben Zickzackkanten aus 3er/4er-Stuecken, und die zerlegte der
        # Blockweg sichtbar in Haken; frei gelassene Schraegen zerfielen als
        # duenne Nordkanten-Treppen in Stummel. Rechtwinklige Zuege mit langen
        # Laeufen sind gemessen die fehlerfreie Gangart des Blockwegs (0 bis
        # 3,4 % unbelegte Paare, docs/klippen-stand.md, 10) -- und genau so
        # sehen die Waelle der Originalkarten aus.
        # Smooth first, then snap to a FIVE-cell grid. Five because the
        # vertical mud run block is exactly 5 cells tall: every contour run
        # can then be covered with whole blocks. Finer grids gave zigzag edges
        # the block path took apart into hooks; free diagonals crumbled into
        # stubs of thin north-edge stairs. Rectilinear strokes with long runs
        # are the block path's measured error-free gait.
        H = shapegen.glaette(H, 2)
        H = shapegen.begradige(H, block=5)
        H = shapegen.entferne_kleinkram(
            H, mindest=max(24, int(round(0.0015 * flaeche))))
        # Nur die Ankerseite darf bis an den Rand: dort laeuft das Hochland
        # aus dem Bild, und die Kontur wird am Rand bewusst NICHT gezeichnet.
        # Die uebrigen Raender bleiben frei wie ueberall im Generator.
        # Only the anchored side may reach the border -- the highland runs off
        # the map there and the contour is deliberately not drawn along it.
        if seite != 0:
            H[:, :3] = 0
        if seite != 1:
            H[:, -3:] = 0
        if seite != 2:
            H[:3, :] = 0
        if seite != 3:
            H[-3:, :] = 0
    # Eine Zelle Abstand zur Wand: der Wandfuss gehoert der Wandfamilie,
    # direkt daneben darf das Bett beginnen.
    # One cell clear of the wall: the footing belongs to the wall family, the
    # bed may start right beside it.
    betten &= ~_dehne(H > 0, 1)
    return H, betten


def _landschaft_familien(fam_field: np.ndarray, H: np.ndarray,
                         betten: np.ndarray | None, tm: "TileModel") -> None:
    """Ein Biom je Wand: jede Hochflaeche samt Saum wird einfarbig.

    Ein Wandzug behaelt die Familie seines ersten Punkts; laeuft er ueber eine
    Biomgrenze, stehen seine Kacheln dort gegen fremden Boden (gemessen 118
    harte Bodenkanten an einem einzigen Zug, docs/klippen-stand.md, 12).
    Deshalb bekommt jede Hochflaeche einen einfarbigen Saum, BEVOR die
    Uebergaenge festgelegt werden.

    Die Farbe je Komponente ist die Mehrheitsfamilie ihres Umfelds: eine Mesa
    mitten im Sand bekommt Sandklippen statt eines Erdrings, der dort wie ein
    Hof aussaehe. Nur Erde und Sand haben Klippenbloecke; alles andere wird
    Erde -- dort laufen ausserdem alle Reparaturen (Kantenzuordnung nur mud).

    One biome per wall: each highland component plus rim becomes one colour --
    the majority family of its surroundings. A mesa amid sand gets sand
    cliffs instead of a dirt ring. Only dirt and sand have cliff blocks;
    everything else becomes dirt, where all repairs are active too.
    """
    if "mud" not in tm.families:
        return
    mud = tm.families.index("mud")
    san = tm.families.index("san") if "san" in tm.families else -1
    for comp in _components(H > 0):
        saum = _dehne(comp, 4)
        # Saum 4: Wandband 3 plus eine Zelle Fuss.
        # Rim 4: wall band of 3 plus one cell of footing.
        werte, anzahl = np.unique(fam_field[saum], return_counts=True)
        mehrheit = int(werte[int(np.argmax(anzahl))])
        fam_field[saum] = mehrheit if mehrheit in (mud, san) else mud
    if betten is not None and betten.any() and san >= 0:
        fam_field[betten] = san


def _rand_zyklus(comp: np.ndarray) -> list[tuple[int, int]]:
    """Geordneter Randzyklus einer Komponente (Moore-Randverfolgung).

    Ordered boundary cycle of one component (Moore boundary tracing)."""
    h, w = comp.shape
    ys, xs = np.nonzero(comp)
    if not len(ys):
        return []
    sy = int(ys.min())
    sx = int(xs[ys == sy].min())

    def drin(x, y):
        return 0 <= x < w and 0 <= y < h and comp[y, x]

    zyklus = [(sx, sy)]
    bx, by = sx - 1, sy
    cx, cy = sx, sy
    for _ in range(int(comp.sum()) * 8 + 8):
        start_i = _MOORE.index((bx - cx, by - cy))
        naechster = None
        for k in range(1, 9):
            dx, dy = _MOORE[(start_i + k) % 8]
            nx, ny = cx + dx, cy + dy
            if drin(nx, ny):
                naechster = (nx, ny)
                pdx, pdy = _MOORE[(start_i + k - 1) % 8]
                bx, by = cx + pdx, cy + pdy
                break
        if naechster is None:
            return zyklus                      # Einzelzelle / single cell
        cx, cy = naechster
        if (cx, cy) == (sx, sy):
            return zyklus
        zyklus.append((cx, cy))
    return zyklus


def _kontur_vereinfachen(punkte: list[tuple[int, int]], eps: float = 1.0
                         ) -> list[tuple[int, int]]:
    """Randzellenfolge zu Eckpunkten eindampfen (Ramer-Douglas-Peucker).

    eps = 1.0 behaelt jede echte Ecke: auf dem Fuenferraster des Hoehenfelds
    werden die Waende reine waagerecht/senkrecht-Zuege mit Eckbloecken --
    die gemessen fehlerfreie Gangart des Blockwegs. Ein groesseres eps (2,9)
    ist probiert und verworfen: es fasste Rasterstufen zu freien Schraegen
    zusammen, und deren Treppen zerfielen als haarfeine Nordkanten sichtbar
    in Stummel (Seed 7, Schlucht und Massiv-Suedkante).

    Boil the boundary run down to corner points (RDP). eps = 1.0 keeps every
    true corner: on the five-cell grid the walls become pure horizontal/
    vertical runs with corner blocks -- the block path's measured error-free
    gait. A larger eps (2.9) was tried and dropped: it merged grid steps into
    free diagonals whose stairs crumbled into visible stubs.
    """
    if len(punkte) < 3:
        return list(punkte)
    p = np.asarray(punkte, dtype=float)
    a, b = p[0], p[-1]
    ab = b - a
    laenge = float(np.hypot(*ab)) or 1.0
    quer = np.abs(ab[0] * (p[:, 1] - a[1]) - ab[1] * (p[:, 0] - a[0])) / laenge
    i = int(np.argmax(quer))
    if quer[i] <= eps:
        return [(int(a[0]), int(a[1])), (int(b[0]), int(b[1]))]
    links = _kontur_vereinfachen(punkte[:i + 1], eps)
    rechts = _kontur_vereinfachen(punkte[i:], eps)
    return links[:-1] + rechts


def _kontur_hand(punkte, comp: np.ndarray) -> str:
    """Liegt das Hochland links oder rechts der Laufrichtung? -> hoch_seite.

    Nicht aus der Umlaufrichtung hergeleitet, sondern nachgesehen: neben
    mehreren Segmentmitten wird gezaehlt, auf welcher Seite die Komponente
    liegt. Links von (dx, dy) ist (dy, -dx) -- y waechst nach unten.

    Does the highland lie left or right of the walking direction? Not derived
    from the winding order but looked up beside several segment midpoints.
    """
    h, w = comp.shape
    links = rechts = 0
    for (x1, y1), (x2, y2) in zip(punkte, punkte[1:]):
        dx = int(np.sign(x2 - x1))
        dy = int(np.sign(y2 - y1))
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        for k in (1, 2, 3):
            lx, ly = mx + dy * k, my - dx * k
            rx, ry = mx - dy * k, my + dx * k
            if 0 <= lx < w and 0 <= ly < h and comp[ly, lx]:
                links += 1
            if 0 <= rx < w and 0 <= ry < h and comp[ry, rx]:
                rechts += 1
    return "links" if links >= rechts else "rechts"


def _kontur_boegen(zyklus: list, comp: np.ndarray, luecken: int,
                   rng: np.random.Generator, luecke_laenge: int = 9
                   ) -> list[list]:
    """Zyklus in offene Boegen teilen: Kartenrand raus, Rampenluecken rein.

    Am Kartenrand wird keine Wand gezeichnet -- das Hochland laeuft dort aus
    dem Bild, wie auf den Originalkarten. Die Rampenluecken sitzen bevorzugt
    auf waagerechten Laeufen, weil es nur dort Abschlussstuecke gibt
    (senkrechte Wandenden bleiben im Kachelsatz ohne Abschluss).

    Split the cycle into open arcs: drop border-hugging stretches, cut ramp
    gaps. Gaps prefer horizontal runs because only those have end caps.
    """
    h, w = comp.shape
    n = len(zyklus)
    am_rand = [x <= 1 or y <= 1 or x >= w - 2 or y >= h - 2
               for x, y in zyklus]
    weg = list(am_rand)
    if luecken > 0 and n >= 40:
        # Waagerechte Laufmitte als Kandidaten fuer eine Luecke.
        # Middle of a horizontal run as gap candidates.
        kandidaten = [i for i in range(n)
                      if not weg[i]
                      and zyklus[i][1] == zyklus[(i + 1) % n][1]
                      and zyklus[i][1] == zyklus[i - 1][1]]
        if not kandidaten:
            kandidaten = [i for i in range(n) if not weg[i]]
        for k in range(luecken):
            if not kandidaten:
                break
            ziel = int(round((k + 0.5) * n / luecken))
            i = min(kandidaten,
                    key=lambda j: min(abs(j - ziel), n - abs(j - ziel)))
            for d in range(-(luecke_laenge // 2), luecke_laenge // 2 + 1):
                weg[(i + d) % n] = True
    if not any(weg):
        return [zyklus + [zyklus[0]]]          # geschlossen / closed figure
    # Offene Boegen einsammeln: beim ersten entfernten Punkt beginnen, dann
    # laufen die Boegen nicht ueber den Zyklusanfang.
    # Collect the open arcs: start at the first removed point, then no arc
    # wraps around the cycle start.
    versatz = weg.index(True)
    boegen: list[list] = []
    lauf: list = []
    for i in range(n + 1):
        j = (versatz + i) % n
        if i == n or weg[j]:
            if len(lauf) >= 6:
                boegen.append(lauf)
            lauf = []
        else:
            lauf.append(zyklus[j])
    return boegen


def _klippe_algo():
    """`klippe_algo` erst beim Aufruf laden -- es importiert seinerseits
    Module, die `mapgen` brauchen."""
    import klippe_algo
    return klippe_algo

def _klippen_aus_linien(grid: np.ndarray, fam_field: np.ndarray,
                        H: np.ndarray, tm: "TileModel",
                        rng: np.random.Generator, ramps: int = 2
                        ) -> tuple[np.ndarray, np.ndarray]:
    """Hochlandkonturen als Linienzuege mit dem Gelaende-Loeser belegen.

    -> (Klippenmaske, Zelltypfeld; -1 = nicht gesetzt).

    Je Komponente wird der Rand abgelaufen, zu Eckpunkten vereinfacht und in
    Boegen mit Rampenluecken zerlegt; jeder Bogen geht durch
    `klippe_algo.klippe_aus_linie`, denselben Loeser wie der Klippenpinsel.
    Der Blockweg und `_male_klippen` sind entfernt (Doku Abschnitt 24).

    Cover the highland contours as polylines with the block path. Per
    component the boundary is walked, simplified to corner points and split
    into arcs with ramp gaps; every arc goes through the terrain solver.
    """
    maske_gesamt = np.zeros(grid.shape, dtype=bool)
    zellen_gesamt = np.full(grid.shape, -1, dtype=np.int16)
    hoch = H > 0
    if not hoch.any():
        return maske_gesamt, zellen_gesamt
    komponenten = sorted(_components(hoch), key=lambda c: -int(c.sum()))
    for nr, comp in enumerate(komponenten):
        zyklus = _rand_zyklus(comp)
        if len(zyklus) < 12:
            continue
        # Die groesste Flaeche bekommt die eingestellten Rampen, jede weitere
        # eine -- sonst waere eine Mesa unerreichbar.
        # The largest area gets the configured ramps, every other one -- a
        # mesa would otherwise be unreachable.
        luecken = max(ramps, 1) if nr == 0 else 1
        for bogen in _kontur_boegen(zyklus, comp, luecken, rng):
            if len(bogen) > 2 and bogen[0] == bogen[-1]:
                # Geschlossene Figur: die Sehne der Vereinfachung haette
                # Laenge null und saehe jeden Punkt als abstandslos -- also
                # in zwei Haelften teilen und wieder zusammensetzen.
                # Closed figure: the simplification chord would have zero
                # length and see every point as distance-free -- split into
                # two halves and rejoin.
                mitte = len(bogen) // 2
                punkte = (_kontur_vereinfachen(bogen[:mitte + 1])[:-1]
                          + _kontur_vereinfachen(bogen[mitte:]))
            else:
                punkte = _kontur_vereinfachen(bogen)
            punkte = [p for i, p in enumerate(punkte)
                      if i == 0 or p != punkte[i - 1]]
            if len(punkte) < 3 and len(set(punkte)) < 2:
                continue
            seite = _kontur_hand(punkte, comp)
            x0, y0 = punkte[0]
            fi = int(fam_field[y0, x0])
            familie = tm.families[fi] if 0 <= fi < len(tm.families) else "mud"
            if familie not in ("mud", "san"):
                # Nur Erde und Sand haben Klippenbloecke.
                # Only dirt and sand have cliff blocks.
                familie = "mud"
            maske, zellen = _klippe_algo().klippe_aus_linie(
                grid, punkte, seite, tm, rng, familie)
            maske_gesamt |= maske
            zellen_gesamt[zellen >= 0] = zellen[zellen >= 0]
    return maske_gesamt, zellen_gesamt


def _bewuchs_abstand(fam_field: np.ndarray, tm: "TileModel",
                     abstand: int = 2) -> int:
    """Bewuchs von fremden Boeden wegruecken.

    Bewuchs ist in OP2 kein eigenes Biom, sondern die bemooste Variante von
    Erde (`mudpln01..12`, 21 Kacheln). Entsprechend gibt es keinen einzigen
    Uebergangssatz zu Fels oder Sand -- stoesst Bewuchs dort direkt an, bleibt
    nur eine harte Kante, und weil so wenige Kacheln zur Verfuegung stehen,
    wiederholt sich dabei dieselbe Kachel ueber viele Felder.

    Hier bekommt jede Bewuchszelle, die einem fremden Boden zu nahe kommt,
    Erde untergeschoben. Erde ist der richtige Puffer, weil Bewuchs ohnehin
    Erde ist und es zu Fels und Sand echte Uebergangssaetze gibt.

    Move vegetation away from foreign grounds. Vegetation is not a biome of its
    own in OP2 but the mossy variant of dirt (`mudpln01..12`, 21 tiles).
    Accordingly there is not a single transition set to rock or sand -- where
    vegetation abuts them directly only a hard edge remains, and with so few
    tiles available the same tile repeats across many cells.

    Here every vegetation cell that comes too close to a foreign ground is
    turned into dirt. Dirt is the right buffer because vegetation is dirt
    anyway, and real transition sets exist from dirt to rock and sand.
    """
    if "veg" not in tm.families or "mud" not in tm.families or abstand <= 0:
        return 0
    veg = tm.families.index("veg")
    mud = tm.families.index("mud")
    ist_veg = fam_field == veg
    if not ist_veg.any():
        return 0
    # Fremd ist alles ausser Bewuchs und Erde.
    # Foreign is everything except vegetation and dirt.
    fremd = ~(ist_veg | (fam_field == mud))
    nah = fremd.copy()
    for _ in range(abstand):
        gewachsen = nah.copy()
        gewachsen[1:, :] |= nah[:-1, :]
        gewachsen[:-1, :] |= nah[1:, :]
        gewachsen[:, 1:] |= nah[:, :-1]
        gewachsen[:, :-1] |= nah[:, 1:]
        nah = gewachsen
    treffer = ist_veg & nah
    fam_field[treffer] = mud
    return int(treffer.sum())


# Wie viele Kachelkandidaten je (Bodenpaar, Richtung) benutzt werden.
# How many tile candidates per (ground pair, direction) are used.
RAND_LIMIT = 0        # 0 = alle
_LEER = np.zeros(0, dtype=np.int32)


def _mische_grenzen(grid: np.ndarray, fam_field: np.ndarray,
                    tm: "TileModel", rng: np.random.Generator,
                    bereich=None, params_style=None,
                    schutz: np.ndarray | None = None,
                    band_breite: int = 1) -> int:
    """Zwischen zwei Boeden eine Mischzone legen statt einer harten Kante.

    In den Originalkarten stossen zwei reine Boeden nie direkt aneinander:
    dafuer gibt es eigene Kachelsaetze (`roctomud`, `santoroc`, ...), die eine
    Flaeche in die andere einstreuen, im Mittel 2,3 Kacheln breit.

    JEDE Zelle wird genau einmal behandelt. Der erste Entwurf lief die
    Bodenpaare nacheinander durch und legte je ein Band -- wo drei Boeden
    zusammentreffen, ueberschrieb das dritte Band die beiden ersten, und die
    Kachel, die uebrig blieb, gehoerte nur zu einem Paar und stiess gegen die
    dritte Familie ungefiltert an. Gemessen blieben so 104 Kontakte uebrig,
    die es in keiner der 33 Originalkarten gibt -- ausnahmslos zwischen
    verschiedenen Familien.

    EVERY cell is handled exactly once. The first draft walked the ground pairs
    one after another, laying one band each; where three grounds meet, the
    third band overwrote the first two, and the tile left over belonged to only
    one pair and met the third family unfiltered. That left 104 contacts which
    do not occur in any of the 33 original maps -- without exception between
    different families.
    """
    if not tm.trans and not tm.rand:
        return 0
    hart = (getattr(params_style, "border_style", "zone") == "linie"
            if params_style is not None else False)
    h, w = fam_field.shape
    y0, y1, x0, x1 = (0, h, 0, w) if bereich is None else bereich

    # Je Familie: wo sie liegt und wo sie direkt angrenzt.
    # Per family: where it is and where it directly borders.
    vorhanden = sorted({int(v) for v in np.unique(fam_field)
                        if 0 <= int(v) < len(tm.families)})
    ist = {f: fam_field == f for f in vorhanden}
    eng = {}
    for f in vorhanden:
        m = ist[f].copy()
        for _ in range(max(1, band_breite)):
            gewachsen = m.copy()
            # Nur orthogonal wachsen. Ueber die Ecke mitzuwachsen laege nahe --
            # dort stossen zwei reine Kacheln diagonal aneinander, und die
            # Uebergangskachel dazwischen muesste an einer Seite durchgehend
            # Fels und an der anderen durchgehend Erde zeigen, was keine Kachel
            # des Satzes kann. Gemessen wird es davon aber SCHLECHTER: das Band
            # wird breiter, es entstehen mehr Uebergang-an-Uebergang-Kontakte,
            # und die Musterbrueche einer erzeugten Karte stiegen von 0,90 auf
            # 1,14 %.
            # Grow orthogonally only. Growing across the corner would seem
            # obvious -- two pure tiles meet diagonally there and the transition
            # between them would have to show solid rock on one side and solid
            # dirt on the other, which no tile of the set can do. Measured, it
            # gets WORSE that way: the band widens, more transition-to-
            # transition contacts arise, and a generated map's pattern breaks
            # rose from 0.90 to 1.14 %.
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                gewachsen |= _schieb(m, dy, dx)
            m = gewachsen
        eng[f] = m

    # Grenzzellen: mindestens zwei Familien im direkten Umfeld.
    # Border cells: at least two families in the immediate neighbourhood.
    zahl = np.zeros(fam_field.shape, dtype=np.int16)
    for f in vorhanden:
        zahl += eng[f].astype(np.int16)
    grenze = zahl >= 2
    if schutz is not None:
        # Frisch gemalte Zellen bleiben reiner Boden. Wer Sand malt, will
        # Sand -- und nicht, dass ein kleiner Fleck komplett zur Mischzone
        # wird, nur weil jede seiner Zellen am Nachbarbiom liegt. Der
        # Uebergang bildet sich dann aussen herum.
        # Freshly painted cells stay pure ground. Whoever paints sand wants
        # sand -- not a small patch turning entirely into blend zone just
        # because every one of its cells touches the neighbouring biome. The
        # transition then forms around it instead.
        grenze &= ~schutz
    # Ausgespart wird, was schon festgenagelt ist -- nicht der Rand als solcher.
    # Vorher fielen pauschal die aeusseren ZWEI Reihen weg, weil das Umfeld mit
    # `np.roll` gerechnet wurde und dort umlief. Beim Erzeugen ist das der
    # unspielbare Kartenrand und faellt nicht auf; beim Malen liegt dieser Rand
    # mitten in der Karte. Das Band wurde genau dort abgeschnitten, und zurueck
    # blieb eine schnurgerade Kante, an der zwei Boeden ohne Uebergang
    # aneinanderstiessen -- gemessen sechs neue harte Kontakte je Strich, alle
    # am Bereichsrand.
    # What is already pinned is left out -- not the border as such. Previously
    # the outer TWO rows fell away wholesale because the neighbourhood was
    # computed with `np.roll`, which wrapped there. When generating, that is the
    # unplayable map border and does not show; when painting, that border sits
    # in the middle of the map. The band was cut off exactly there and left a
    # dead straight edge where two grounds met without a transition -- measured,
    # six new hard contacts per stroke, all at the region border.
    grenze &= grid < 0
    if bereich is not None:
        maske = np.zeros(fam_field.shape, dtype=bool)
        maske[y0:y1, x0:x1] = True
        grenze &= maske

    # Wie stark jede Familie im 5x5-Umfeld vertreten ist -- daraus wird die
    # Gegenfamilie bestimmt.
    # How strongly each family is present in a 5x5 window -- the counterpart
    # family is derived from that.
    dichte = {}
    for f in vorhanden:
        d = np.zeros(fam_field.shape, dtype=np.int16)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                d += _schieb(ist[f], dy, dx).astype(np.int16)
        dichte[f] = d

    offen: dict[tuple[int, int], tuple] = {}
    ys, xs = np.nonzero(grenze)
    for y, x in zip(ys.tolist(), xs.tolist()):
        eigen = int(fam_field[y, x])
        if eigen not in ist:
            continue
        # Staerkste fremde Familie im Umfeld
        # Strongest foreign family in the neighbourhood
        fremde = [(int(dichte[f][y, x]), f) for f in vorhanden
                  if f != eigen and eng[f][y, x]]
        if not fremde:
            continue
        gegen = max(fremde)[1]
        paar = tuple(sorted((tm.families[eigen], tm.families[gegen])))
        if hart and tm.families[eigen] != paar[0]:
            continue            # harte Linie liegt nur auf einer Seite
        kandidaten = _rand_kandidaten(tm, paar, ist, fam_field, x, y, hart)
        if kandidaten is not None:
            offen[(x, y)] = kandidaten

    gesetzt = _loese_band(grid, tm, rng, offen)
    return gesetzt


def _schieb(m: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Verschieben wie `np.roll`, aber ohne Umlauf: der Rand wiederholt sich.

    Beim Erzeugen faellt der Unterschied kaum auf -- oben und unten liegt der
    unspielbare Kartenrand. Beim Malen ist das Feld ein AUSSCHNITT mitten aus
    der Karte, und dann behauptet der Umlauf, die obere Reihe grenze an die
    untere. Die Randwiederholung nimmt stattdessen an, der Boden gehe nach
    aussen weiter -- was er in aller Regel auch tut.

    Shift like `np.roll` but without wrap-around: the edge repeats. When
    generating, the difference hardly matters -- top and bottom are the
    unplayable map border. When painting, the field is a CROP from the middle of
    the map, and there the wrap claims the top row borders the bottom one. Edge
    repetition assumes instead that the ground continues outwards -- which it
    usually does.
    """
    erg = m
    if dy:
        vorher = erg
        erg = np.roll(vorher, dy, axis=0)
        if dy > 0:
            erg[:dy, :] = vorher[:1, :]
        else:
            erg[dy:, :] = vorher[-1:, :]
    if dx:
        vorher = erg
        erg = np.roll(vorher, dx, axis=1)
        if dx > 0:
            erg[:, :dx] = vorher[:, :1]
        else:
            erg[:, dx:] = vorher[:, -1:]
    return erg


def _rand_kandidaten(tm, paar, ist, fam_field, x, y, hart=False):
    """Welche Kacheln kommen fuer diese Grenzzelle in Frage?

    Nur Richtung und Seite entscheiden hier -- die Vertraeglichkeit mit den
    Nachbarn loest `_loese_band` fuer das ganze Band gemeinsam.

    Only direction and side decide here; compatibility with the neighbours is
    resolved by `_loese_band` for the whole band at once.
    """
    nach_richtung = tm.rand.get(paar)
    if not nach_richtung:
        return None
    erste = tm.families.index(paar[0]) if paar[0] in tm.families else None
    if erste is None or erste not in ist:
        return None
    r = _grenz_richtung(ist[erste], y, x)
    eintrag = nach_richtung.get(r) if r is not None else None
    if eintrag is None:
        for versatz in (1, -1, 2, -2, 3, -3, 4):
            eintrag = nach_richtung.get(((r or 0) + versatz) % 8)
            if eintrag is not None:
                break
    if eintrag is None:
        return None
    kacheln = np.asarray(eintrag[0])
    gewichte = np.asarray(eintrag[1], dtype=float).copy()

    # Vorlieben als GEWICHT, nicht als Filter. Vorher schnitten Rangliste und
    # Seite hart -- am Ende blieben 3,0 Kandidaten je Zelle, und bei 24,9 %
    # der benachbarten Bandzellen passte dann ueberhaupt keine Kombination
    # mehr zueinander. Die Bedingung war unerfuellbar, bevor der Loeser
    # ueberhaupt anfing. Jetzt bleiben alle Kacheln zulaessig, die
    # bevorzugten bekommen nur mehr Gewicht.
    # Preferences as WEIGHT, not as a filter. Before, ranking and side cut
    # hard -- 3.0 candidates per cell remained, and for 24.9 % of neighbouring
    # band cells no combination fitted at all. The constraint was unsatisfiable
    # before the solver even started. Now every tile stays admissible, the
    # preferred ones merely weigh more.
    if RAND_LIMIT and len(kacheln) > RAND_LIMIT:
        daempfung = np.ones(len(kacheln))
        daempfung[RAND_LIMIT:] = 0.08
        gewichte = gewichte * daempfung
    if hart and len(kacheln) > 2:
        daempfung = np.ones(len(kacheln))
        daempfung[2:] = 0.04
        gewichte = gewichte * daempfung
    eigen = int(fam_field[y, x])
    if tm.mix_of and 0 <= eigen < len(tm.families):
        zur_seite = tm.families[eigen] == paar[0]
        passend_seite = np.array([
            (tm.mix_of.get(int(k), 0.5) < 0.5) == zur_seite for k in kacheln])
        gewichte = gewichte * np.where(passend_seite, 1.0, 0.05)
    return kacheln, np.maximum(gewichte, 1e-6)


def _loese_band(grid, tm, rng, offen) -> int:
    """Das ganze Uebergangsband gemeinsam aufloesen.

    Eine Zelle nach der anderen zu waehlen kann hier nicht funktionieren: der
    Nachbarschaftsgraph der Uebergangskacheln ist duenn (im Schnitt 5,4
    zulaessige Nachfolger), also macht jede Festlegung links eine gueltige
    Wahl rechts unmoeglich, und zurueck kann man nicht. Gemessen waren 51,5 %
    aller verbliebenen Fehlpaare Uebergang gegen Uebergang.

    Deshalb hier Propagation: immer die Zelle mit den wenigsten
    Moeglichkeiten festlegen, danach die Nachbarn einschraenken. Wird eine
    Zelle leer, wird die Einschraenkung dort aufgehoben statt abzubrechen --
    ein schlechter Nachbar ist besser als ein Abbruch.

    Solve the whole transition band at once. Choosing cell by cell cannot work
    here: the adjacency graph of the transition tiles is sparse (5.4 admissible
    successors on average), so every decision on the left makes a valid choice
    on the right impossible, and there is no going back. Measured, 51.5 % of
    all remaining bad pairs were transition against transition. Hence
    propagation: always fix the cell with the fewest options, then restrict its
    neighbours. If a cell runs empty, the restriction there is lifted rather
    than aborting -- one bad neighbour beats a failed solve.
    """
    if not offen:
        return 0
    moeglich = {p: (k.copy(), g.copy()) for p, (k, g) in offen.items()}
    gesetzt = 0
    while moeglich:
        # Zelle mit der geringsten Auswahl zuerst -- so bleibt am meisten Luft.
        # Fewest options first -- that leaves the most room.
        stelle = min(moeglich, key=lambda p: len(moeglich[p][0]))
        kacheln, gewichte = moeglich.pop(stelle)
        x, y = stelle
        if not len(kacheln):
            continue
        w = gewichte / gewichte.sum() if gewichte.sum() > 0 else None
        kachel = int(rng.choice(kacheln, p=w))
        grid[y, x] = kachel
        gesetzt += 1
        # Nachbarn einschraenken
        for dx, dy, tabelle, vorwaerts in ((1, 0, tm.right, True),
                                           (-1, 0, tm.right, False),
                                           (0, 1, tm.down, True),
                                           (0, -1, tm.down, False)):
            nachbar = (x + dx, y + dy)
            if nachbar not in moeglich:
                continue
            nk, ng = moeglich[nachbar]
            richtung = "rechts" if tabelle is tm.right else "unten"
            if vorwaerts:
                k, _ = tm.nachbarn(kachel, richtung)
                erlaubt = (np.isin(nk, k) if k is not None
                           else np.ones(len(nk), dtype=bool))
            else:
                erlaubt = np.array([
                    (lambda e: e is None or kachel in e)(
                        tm.nachbarn(int(k), richtung)[0]) for k in nk])
            if erlaubt.any():
                moeglich[nachbar] = (nk[erlaubt], ng[erlaubt])
    return gesetzt


def _rand_kachel(grid, fam_field, tm, rng, paar, ist, x, y, hart=False):
    """Uebergangskachel fuer eine Grenzzelle waehlen -- nach Richtung."""
    nach_richtung = tm.rand.get(paar)
    if not nach_richtung:
        return None
    erste = tm.families.index(paar[0]) if paar[0] in tm.families else None
    if erste is None or erste not in ist:
        return None
    r = _grenz_richtung(ist[erste], y, x)
    eintrag = nach_richtung.get(r) if r is not None else None
    if eintrag is None:
        for versatz in (1, -1, 2, -2, 3, -3, 4):
            eintrag = nach_richtung.get(((r or 0) + versatz) % 8)
            if eintrag is not None:
                break
    if eintrag is None:
        return None
    kacheln, gewichte = eintrag
    if RAND_LIMIT:
        kacheln, gewichte = kacheln[:RAND_LIMIT], gewichte[:RAND_LIMIT]
    if hart:
        kacheln, gewichte = kacheln[:2], gewichte[:2]

    # Stufenleiter statt Alles-oder-nichts. Vorher wurde geprueft, ob eine
    # Kachel zu allen gesetzten Nachbarn passt -- und wenn keine passte, eine
    # beliebige gesetzt. Gemessen passten so nur 13 % der Zellen; der Notnagel
    # war der Normalfall. Jede Stufe haelt jetzt noch mindestens eine gelernte
    # Nachbarschaft ein.
    # Ladder instead of all-or-nothing. Before, a tile was checked against all
    # placed neighbours -- and if none fitted, an arbitrary one was placed.
    # Measured, only 13 % of cells fitted; the fallback was the normal case.
    # Every level now honours at least one learned adjacency.
    # Seite ZUERST: das Band ist zwei Zellen dick, eine in Boden A und eine in
    # B. Wer die Seite erst nach der Nachbarschaftsleiter beruecksichtigt, hat
    # keine Auswahl mehr -- gemessen bekamen dann beide Zellen denselben
    # Mischgrad, also lag auf der Erdseite eine felsige Kachel und daneben auf
    # der Felsseite dieselbe. Das ergibt zwei parallele Linien statt einer Zone.
    # Side FIRST: the band is two cells thick, one in ground A and one in B.
    # Taking the side into account only after the adjacency ladder leaves no
    # choice -- measured, both cells then got the same blend level, so a rocky
    # tile sat on the dirt side and the same one beside it on the rock side.
    # That gives two parallel lines instead of one zone.
    eigen = int(fam_field[y, x])
    if tm.mix_of and 0 <= eigen < len(tm.families):
        zur_seite = tm.families[eigen] == paar[0]
        gewuenscht = [i for i in range(len(kacheln))
                      if (tm.mix_of.get(int(kacheln[i]), 0.5) < 0.5) == zur_seite]
        if gewuenscht:
            kacheln = kacheln[gewuenscht]
            gewichte = np.asarray(gewichte, dtype=float)[gewuenscht]

    def waehlbar(bedingung):
        return [i for i in range(len(kacheln))
                if bedingung(int(kacheln[i]))]

    stufen = (
        lambda k: _passt_zu_nachbarn(grid, tm, x, y, k),                 # alle vier
        lambda k: _passt_zu_nachbarn(grid, tm, x, y, k, nur_gesetzte=True),
        lambda k: _passt_seite(grid, tm, x, y, k, "links"),
        lambda k: _passt_seite(grid, tm, x, y, k, "oben"),
    )
    passend = []
    for bedingung in stufen:
        passend = waehlbar(bedingung)
        if passend:
            break
    if not passend:
        passend = list(range(len(kacheln)))

    # Seite beruecksichtigen. Das Band ist zwei Zellen dick -- eine in Boden A,
    # eine in B. Bisher entschied nur die Richtung, also konnte im Fels eine
    # "fast schon Erde"-Kachel landen und daneben in der Erde eine "fast noch
    # Fels"-Kachel: das liest sich als zwei parallele Linien statt als eine
    # Zone. Der gelernte Mischgrad je Kachel loest das.
    # Take the side into account. The band is two cells thick -- one in ground
    # A, one in B. Previously only the direction decided, so a nearly-dirt tile
    # could sit in the rock and a nearly-rock tile beside it in the dirt: that
    # reads as two parallel lines instead of one zone. The learned blend level
    # per tile resolves it.
    g = np.asarray(gewichte, dtype=float)[passend]
    if g.sum() <= 0:
        return int(kacheln[passend[0]])
    return int(kacheln[passend[int(rng.choice(len(passend), p=g / g.sum()))]])


def _passt_seite(grid, tm, x, y, kachel, seite) -> bool:
    """Passt die Kachel wenigstens zu einer Seite?"""
    if seite == "links":
        if x <= 0:
            return True
        erlaubt, _ = tm.nachbarn(int(grid[y, x - 1]), "rechts")
    else:
        if y <= 0:
            return True
        erlaubt, _ = tm.nachbarn(int(grid[y - 1, x]), "unten")
    return erlaubt is None or kachel in erlaubt


def _kanten_wuerfel(art: str, x: int, y: int) -> int:
    """Feste Zufallszahl je Kante -- in jedem Lauf dieselbe.

    Hier stand `hash((art, x, y))`. Pythons `hash` ist fuer Zeichenketten pro
    Prozess gesalzen (PYTHONHASHSEED), also lieferte derselbe Seed in jedem
    neuen Lauf eine andere Karte. Gemessen: zwei Aufrufe hintereinander,
    Seed 42, zwei verschiedene Karten. Der Determinismus-Test hat das nie
    gesehen, weil er beide Karten im SELBEN Prozess erzeugt.

    Fixed random number per edge -- the same in every run. This used to be
    `hash((art, x, y))`. Python's `hash` is salted per process for strings
    (PYTHONHASHSEED), so the same seed produced a different map in every new
    run. Measured: two consecutive calls, seed 42, two different maps. The
    determinism check never saw it because it generates both maps in the SAME
    process.
    """
    n = (x * 73856093) ^ (y * 19349663) ^ (0 if art == "h" else 83492791)
    n &= 0xFFFFFFFF
    n ^= n >> 16
    n = (n * 0x7FEB352D) & 0xFFFFFFFF
    n ^= n >> 15
    return n


# Was eine sichtbar springende Nahtstelle im Vergleich zu einer Muster-
# abweichung wiegt. Ein Musterfehler ist ein Abschnitt von sechzehn (vier
# Seiten zu vier Abschnitten); eine springende Naht verdirbt eine ganze Seite,
# also vier davon.
# What a visibly jumping seam weighs compared to a pattern deviation. A pattern
# error is one segment out of sixteen (four sides of four segments); a jumping
# seam spoils a whole side, hence four of them.
NAHT_STRAFE = 4


def nachbearbeite_uebergaenge(grid: np.ndarray, fam_field: np.ndarray,
                              tm: "TileModel | None" = None,
                              rng: np.random.Generator | None = None) -> int:
    """Alle Uebergangskacheln einer fertigen Karte nachbearbeiten.

    Fasst die beiden Durchgaenge zusammen, die der Generator ohnehin benutzt:

      1. Jede Uebergangskachel aus den vier Ecken des Familienfeldes ableiten.
         Zwei benachbarte Zellen teilen sich die Ecken ihrer gemeinsamen Kante,
         also passen ihre Muster bauartbedingt zusammen. Sitzt eine
         Uebergangskachel dort, wo alle vier Ecken derselbe Boden sind, wird sie
         durch reinen Boden ersetzt -- dort ist keine Grenze.
      2. Was danach noch nicht passt, gegen eine besser passende Kachel
         desselben Satzes tauschen.

    Laesst sich auf jede Karte anwenden, auch auf eine geladene oder von Hand
    bearbeitete. Gibt die Zahl der geaenderten Zellen zurueck.

    Post-process all transition tiles of a finished map. Combines the two passes
    the generator uses anyway: derive each transition tile from the four corners
    of the family field (adjacent cells share the corners of their common edge,
    so their patterns match by construction; a transition tile where all four
    corners are the same ground is replaced by pure ground), then swap whatever
    still does not fit for a better tile from the same set. Applicable to any
    map, including a loaded or hand-edited one. Returns the number of changed
    cells.
    """
    if tm is None:
        tm = model()
    if rng is None:
        rng = np.random.default_rng(0)
    n = _uebergaenge_aus_ecken(grid, fam_field, tm, rng)
    n += _richte_uebergaenge(grid, tm)
    return n + _schliesse_harte_kanten(grid, fam_field, tm, rng)


def _harte_kanten(grid: np.ndarray, tm: "TileModel") -> tuple[np.ndarray, int]:
    """Zellen, die ohne Uebergangskachel an einen fremden Boden stossen.

    Gezaehlt werden nur Bodenpaare mit eigenem Kachelsatz. Erde neben Bewuchs
    ist normal -- dafuer gibt es keine Uebergangskacheln, der Bewuchs sitzt
    einfach auf der Erde.

    Cells butting against a foreign ground without a transition tile. Only
    ground pairs with their own tile set count; dirt beside vegetation is
    normal, there are no transition tiles for it.
    """
    fam, ueb = tm.family_of[grid], tm.ist_uebergang[grid]
    # Klippen zaehlen nicht als Bodengrenze und werden auch nicht angetastet.
    # Eine Felsklippe auf Erde gehoert einer anderen Familie an als der Boden
    # daneben -- das ist kein fehlender Uebergang, sondern eine Wand. Ohne
    # diese Ausnahme ersetzte der Durchgang Klippenkacheln durch
    # Uebergangskacheln und der Klippenanteil fiel von 1,2 auf 0,9 %.
    # Cliffs do not count as a ground border and are not touched. A rock cliff
    # on dirt belongs to a different family than the ground beside it -- that is
    # not a missing transition but a wall. Without this exception the pass
    # replaced cliff tiles with transition tiles and the cliff share fell from
    # 1.2 to 0.9 %.
    klippe = np.isin(_cell_types(grid), [celltypes.NORTH_CLIFFS,
                                         celltypes.CLIFFS_HIGH_SIDE,
                                         celltypes.CLIFFS_LOW_SIDE])
    ueb = ueb | klippe
    maske = np.zeros(grid.shape, dtype=bool)
    n = 0
    for a, b, ua, ub, dy, dx in (
            (fam[:, :-1], fam[:, 1:], ueb[:, :-1], ueb[:, 1:], 0, 1),
            (fam[:-1, :], fam[1:, :], ueb[:-1, :], ueb[1:, :], 1, 0)):
        roh = (~ua) & (~ub) & (a >= 0) & (b >= 0) & (a != b)
        ys, xs = np.nonzero(roh)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if tm.paar_hat_satz[int(a[y, x]), int(b[y, x])]:
                maske[y, x] = maske[y + dy, x + dx] = True
                n += 1
    return maske, n


def _schliesse_harte_kanten(grid: np.ndarray, fam_field: np.ndarray,
                            tm: "TileModel",
                            rng: np.random.Generator | None = None) -> int:
    """Fehlende Uebergangskacheln nachtragen, wo zwei Boeden hart anstossen.

    Die beiden anderen Durchgaenge laufen nur ueber Zellen, auf denen SCHON
    eine Uebergangskachel liegt -- sie koennen eine harte Kante verbessern,
    aber keine schliessen. Auf einer von Hand bearbeiteten Karte blieben so
    136 Stellen stehen, an denen Erde und Fels ohne `mudtoroc` aneinander-
    stossen, und der Knopf aenderte daran nichts.

    Hier werden genau die betroffenen Zellen freigegeben und alles andere
    festgenagelt, dann legt `_mische_grenzen` sein Band nur noch dort. Drei
    Runden, weil eine frisch gesetzte Uebergangskachel ihrerseits an einen
    dritten Boden stossen kann.

    Add the missing transition tiles where two grounds meet hard. The other two
    passes only walk cells that ALREADY hold a transition tile -- they can
    improve a hard edge but not close one. On a hand-edited map that left 136
    places where dirt and rock meet without `mudtoroc`, and the button did
    nothing about them. Here exactly the affected cells are freed and everything
    else is pinned, so `_mische_grenzen` lays its band only there. Three rounds,
    because a freshly placed transition tile can itself butt against a third
    ground.
    """
    if not tm.trans and not tm.rand:
        return 0
    if rng is None:
        rng = np.random.default_rng(0)
    gesetzt = 0
    for _ in range(3):
        maske, n = _harte_kanten(grid, tm)
        if not n:
            break
        fest = grid.copy()
        fest[maske] = -1
        _mische_grenzen(fest, fam_field, tm, rng)
        neu = maske & (fest >= 0) & (fest != grid)
        if not neu.any():
            break
        grid[neu] = fest[neu]
        gesetzt += int(neu.sum())
    return gesetzt


def _uebergaenge_aus_ecken(grid: np.ndarray, fam_field: np.ndarray,
                           tm: "TileModel",
                           rng: np.random.Generator | None = None) -> int:
    """Jede Uebergangskachel aus dem Familienfeld ableiten statt aus den
    Nachbarkacheln.

    Bisher wurde jede Bandzelle einzeln gewaehlt und hinterher gegen ihre
    Nachbarinnen zurechtgerueckt. Das bleibt eine Nachbesserung: wer zuerst
    gesetzt wird, gibt den Ton an, und wer spaeter kommt, muss sich fuegen.

    Hier steht das Ergebnis vorher fest. Jede Zelle hat vier Ecken, und eine
    Ecke gehoert zum fremden Boden, sobald eine der vier dort zusammen-
    stossenden Zellen ihm gehoert. Aus den zwei Ecken einer Seite folgt deren
    Muster: die erste Haelfte richtet sich nach der einen Ecke, die zweite nach
    der anderen.

    Der Gewinn steckt in der Geometrie: zwei benachbarte Zellen teilen sich
    genau die zwei Ecken ihrer gemeinsamen Kante. Ihre Muster dort sind damit
    zwangslaeufig gleich -- das passende Gegenstueck entsteht, ohne dass jemand
    es abgleichen muesste.

    Derive every transition tile from the family field instead of from the
    neighbouring tiles. Until now each band cell was chosen individually and
    afterwards aligned to its neighbours. That stays a correction: whoever is
    placed first sets the tone and whoever comes later has to comply.

    Here the result is fixed beforehand. Every cell has four corners, and a
    corner belongs to the foreign ground as soon as one of the four cells
    meeting there does. The two corners of a side give its pattern: the first
    half follows one corner, the second half the other.

    The gain lies in the geometry: two adjacent cells share exactly the two
    corners of their common edge. Their patterns there are therefore
    necessarily equal -- the matching counterpart arises without anyone having
    to reconcile it.
    """
    if tm.muster is None or not tm.trans:
        return 0
    if rng is None:
        rng = np.random.default_rng(0)
    satz: dict[int, np.ndarray] = {}
    fremd_von: dict[int, tuple[int, int]] = {}
    for (na, nb), liste in tm.trans.items():
        if na not in tm.families or nb not in tm.families:
            continue
        a, b = tm.families.index(na), tm.families.index(nb)
        kacheln = np.array([int(t) for t, _ in liste], dtype=np.int32)
        for t, _ in liste:
            satz[int(t)] = kacheln
            fremd_von[int(t)] = (a, b)
    h, w = grid.shape
    abschnitte = tm.muster.shape[2]
    halb = abschnitte // 2
    _frei = np.array([t for t in range(2048) if tm.placeable[t]], dtype=np.int32)
    gesetzt = 0
    ys, xs = np.nonzero(tm.ist_uebergang[grid])
    for y, x in zip(ys.tolist(), xs.tolist()):
        kand = satz.get(int(grid[y, x]))
        if kand is None or len(kand) < 2:
            continue
        a, b = fremd_von[int(grid[y, x])]

        def ecke(ey, ex):
            """Gehoert diese Ecke zum Boden b?"""
            for cy in (ey - 1, ey):
                for cx in (ex - 1, ex):
                    if 0 <= cy < h and 0 <= cx < w and int(fam_field[cy, cx]) == b:
                        return True
            return False

        no, nw = ecke(y, x + 1), ecke(y, x)
        so, sw = ecke(y + 1, x + 1), ecke(y + 1, x)
        # Gehoeren alle vier Ecken demselben Boden, ist hier keine Grenze --
        # und dann gehoert hier auch keine Uebergangskachel hin. Die Mischzone
        # setzt sie trotzdem: gemessen lagen zwoelf identische `santomud`
        # mitten im reinen Sand nebeneinander, alle vier Ecken Sand. Sichtbar
        # wurde das als Kette derselben Kachel, weil zu einer einheitlichen
        # Vorgabe genau eine Kachel passt.
        # If all four corners belong to the same ground there is no border here
        # -- and then no transition tile belongs here either. The blend zone
        # places one regardless: measured, twelve identical `santomud` lay side
        # by side in the middle of pure sand, all four corners sand. That showed
        # up as a chain of the same tile, because exactly one tile matches a
        # uniform specification.
        if no == nw == so == sw:
            ziel = int(fam_field[y, x])
            kand = _frei[tm.family_of[_frei] == ziel]
            if not len(kand):
                continue
            # Hier kann der Musterwert nicht entscheiden: gegen eine
            # einheitliche Vorgabe schneidet reiner Boden IMMER besser ab als
            # eine Uebergangskachel, die auf beiden Boeden steht. Auf einer
            # erzeugten Karte stimmt das auch -- das Familienfeld ist dort der
            # Entwurf. Auf einer fremden Karte ist es aus den Kacheln
            # zurueckgerechnet, und dann heisst "alle vier Ecken gleich"
            # oft nur, dass die Mehrheitsregel eine einzelne Uebergangskachel
            # ihrem Umfeld zugeschlagen hat. Gemessen richtete genau dieser
            # Zweig den Schaden an: auf cm03 allein 2923 Zellen, Musterbrueche
            # 4,10 -> 2,93 %, sichtbare Brueche aber 1,00 -> 1,40 %.
            # Entschieden wird deshalb an der Naht: getauscht wird nur, was
            # optisch nicht schlechter anschliesst als das, was schon da liegt.
            # The pattern value cannot decide here: against a uniform
            # specification pure ground ALWAYS scores better than a transition
            # tile standing on both grounds. On a generated map that is true --
            # there the family field is the design. On a foreign map it is
            # computed back from the tiles, and then "all four corners equal"
            # often only means the majority rule assigned a lone transition tile
            # to its surroundings. Measured, exactly this branch did the damage:
            # 2923 cells on cm03 alone, pattern breaks 4.10 -> 2.93 %, but
            # visible breaks 1.00 -> 1.40 %. So the seam decides: only swap for
            # something that joins no worse than what is already there.
            jetzt_naht = int(_auffaellige_naehte(
                grid, tm, x, y, [int(grid[y, x])])[0])
            kand = kand[_auffaellige_naehte(grid, tm, x, y, kand) <= jetzt_naht]
            # Und kein Kandidat, der zwei Boeden direkt aneinanderstossen
            # laesst. Die Nahtbedingung oben faengt das nicht: Erde neben Fels
            # ist farblich unauffaellig und trotzdem falsch -- dort gehoert
            # `mudtoroc` hin. Gemessen liess dieser Zweig auf einer erzeugten
            # Karte die harten Kanten von 24 auf 74 steigen; die Originale
            # haben davon keine einzige.
            # And no candidate that lets two grounds butt straight against each
            # other. The seam condition above does not catch this: dirt beside
            # rock is inconspicuous in colour and still wrong -- `mudtoroc`
            # belongs there. Measured, this branch raised the hard edges on a
            # generated map from 24 to 74; the originals have not a single one.
            if len(kand):
                kand = kand[~_macht_harte_kante(grid, tm, x, y, kand)]
            if not len(kand):
                continue
            gut = np.array([k for k in kand
                            if _passt_zu_nachbarn(grid, tm, x, y, int(k))],
                           dtype=np.int32)
            if len(gut):
                gew = np.array([max(1.0, float(tm.usage.get(int(t), 1)))
                                for t in gut])
                grid[y, x] = int(rng.choice(gut, p=gew / gew.sum()))
            else:
                schlimm = _schlimmste_naht(grid, tm, x, y, kand)
                grid[y, x] = int(kand[int(np.argmin(schlimm))])
            gesetzt += 1
            continue
        # Reihenfolge wie in `muster`: Ost, West, Sued, Nord -- jede Seite von
        # oben bzw. links gelesen.
        # Order as in `muster`: east, west, south, north, each read from the top
        # respectively the left.
        # (Eckenpaar, Kennung der gemeinsamen Kante). Wechselt der Boden
        # entlang einer Seite, gibt es drei moegliche Teilungen (1/3, 2/2, 3/1).
        # Welche genommen wird, muss an der KANTE haengen, nicht an der Zelle --
        # sonst waehlen die beiden Anrainer verschieden und die Muster passen
        # trotz gleicher Ecken nicht zusammen.
        # (corner pair, identity of the shared edge). Where the ground changes
        # along a side there are three possible splits (1/3, 2/2, 3/1). Which one
        # is taken must depend on the EDGE, not on the cell -- otherwise the two
        # neighbours choose differently and the patterns fail to match despite
        # equal corners.
        seiten = ((no, so, ("v", x + 1, y)), (nw, sw, ("v", x, y)),
                  (sw, so, ("h", x, y + 1)), (nw, no, ("h", x, y)))
        soll = np.empty((4, abschnitte), dtype=np.int16)
        for i, (anfang, ende, kante) in enumerate(seiten):
            if anfang == ende:
                soll[i, :] = b if anfang else a
                continue
            art, kx, ky = kante
            teil = 1 + (_kanten_wuerfel(art, kx, ky) % (abschnitte - 1))
            soll[i, :teil] = b if anfang else a
            soll[i, teil:] = b if ende else a
        # Wo die Nachbarin KEIN Uebergang ist, zaehlt ihr tatsaechliches Muster,
        # nicht die Ecke. Die Ecken sagen nur, wo die Grenze verlaeuft -- sie
        # setzen voraus, dass jede Zelle mit gemischten Ecken auch eine
        # Uebergangskachel traegt. Beim Malen stimmt das nicht: die frisch
        # gemalten Zellen bleiben absichtlich reiner Boden, damit der Pinsel
        # wirklich malt, was er soll. Deren Muster ist durchgehend einfarbig,
        # die Ecke daneben aber gemischt -- und dann fordert die Konstruktion
        # eine Kante, die keine Kachel des Satzes liefern kann. Gemessen waren
        # 36 von 50 uebrigen Musterbruechen im gemalten Bereich genau solche
        # Boden-Uebergang-Paare.
        # Where the neighbour is NOT a transition, its actual pattern counts,
        # not the corner. The corners only say where the border runs -- they
        # assume every cell with mixed corners also carries a transition tile.
        # When painting that does not hold: the freshly painted cells stay pure
        # ground on purpose so the brush really paints what it should. Their
        # pattern is uniform while the corner beside them is mixed -- and then
        # the construction demands an edge no tile of the set can supply.
        # Measured, 36 of 50 remaining pattern breaks in the painted region were
        # exactly such ground-transition pairs.
        for i, (ny, nx, gegen) in enumerate(((y, x + 1, 1), (y, x - 1, 0),
                                             (y + 1, x, 3), (y - 1, x, 2))):
            if 0 <= ny < h and 0 <= nx < w:
                nachbar = int(grid[ny, nx])
                if not tm.ist_uebergang[nachbar]:
                    soll[i, :] = tm.muster[nachbar, gegen]
        fehler = (tm.muster[kand] != soll[None]).sum(axis=(1, 2))
        # Musterabweichung UND Farbsprung in einem Wert. Nur die Abweichungen
        # zu zaehlen genuegte nicht: die Kachel, die schon da liegt, wurde mit
        # demselben Mass verglichen, und gemessen waren die Tausche echte
        # Verbesserungen -- nur eben optisch schlechtere. Auf cm03 sanken die
        # Musterbrueche von 4,10 auf 2,10 %, waehrend die SICHTBAREN Brueche
        # von 1,00 auf 1,31 % stiegen. Der Schaden zeigt sich am Farbsprung an
        # der Naht, also muss der Farbsprung mit in den Wert.
        # Pattern deviation AND colour jump in one value. Counting the
        # deviations alone was not enough: the tile already in place was
        # compared by the same measure, and measured, the swaps were genuine
        # improvements -- only visually worse ones. On cm03 pattern breaks fell
        # from 4.10 to 2.10 % while VISIBLE breaks rose from 1.00 to 1.31 %. The
        # damage shows up as the colour jump at the seam, so the colour jump has
        # to be part of the value.
        gesamt = fehler + NAHT_STRAFE * _auffaellige_naehte(grid, tm, x, y, kand)
        # Fehlerwert der Kachel, die schon da liegt. Ohne diesen Vergleich
        # ueberschreibt die Konstruktion auch eine Kachel, die bereits gut
        # sitzt.
        # Error value of the tile already in place. Without this comparison the
        # construction also overwrites a tile that already sits well.
        _ist = np.nonzero(kand == int(grid[y, x]))[0]
        jetzt = int(gesamt[_ist[0]]) if len(_ist) else 10 ** 6
        jetzt_muster = int(fehler[_ist[0]]) if len(_ist) else 10 ** 6
        # Unter den gleich guten wuerfeln. `argmin` nimmt immer dieselbe, und
        # weil die Ecken entlang einer geraden Grenze in jeder Zelle gleich
        # sind, stand danach vier-, fuenfmal dieselbe Kachel nebeneinander --
        # ein sichtbares Muster im Uebergang. Gewichtet nach Haeufigkeit, damit
        # seltene Kacheln selten bleiben.
        # Roll the dice among the equally good ones. `argmin` always takes the
        # same one, and since the corners are identical in every cell along a
        # straight border, the same tile then stood side by side four or five
        # times -- a visible pattern in the transition. Weighted by frequency so
        # rare tiles stay rare.
        # Eine Abweichung von einem Abschnitt zulassen. Ein vollstaendig
        # vorgegebenes 4-Seiten-Muster ist fast eindeutig -- bei 742 von 1009
        # Zellen passt genau EINE Kachel. An einer geraden Grenze wiederholt
        # sich die Vorgabe, also stand dieselbe Kachel bis zu sechzehnmal
        # nebeneinander; die Originale wiederholen hoechstens zwei.
        # Allow a deviation of one segment. A fully specified four-side pattern
        # is almost unique -- for 742 of 1009 cells exactly ONE tile fits. Along
        # a straight border the specification repeats, so the same tile stood
        # side by side up to sixteen times; the originals repeat at most two.
        # Passt keine Kachel des Satzes halbwegs, gehoert hier gar kein
        # Uebergang hin: dann lieber reiner Boden als eine Kachel, deren
        # Struktur an der Kante abgeschnitten wird.
        # If no tile of the set fits reasonably, no transition belongs here:
        # then pure ground rather than a tile whose structure gets cut off at
        # the edge.
        # Diese Frage bleibt am Muster haengen: ob ueberhaupt ein Uebergang
        # hierher gehoert, entscheidet die Form der Grenze, nicht die Farbe.
        # This question stays with the pattern: whether a transition belongs
        # here at all is decided by the shape of the border, not by the colour.
        if int(fehler.min()) > 3 and jetzt_muster > 3:
            ziel = int(fam_field[y, x])
            rein = _frei[tm.family_of[_frei] == ziel]
            # Auch hier die Naht als Bedingung. Bleibt nichts uebrig, faellt
            # die Zelle in die normale Wahl zurueck, statt reinen Boden mit
            # sichtbarem Sprung hinzustellen.
            # The seam is a condition here too. If nothing survives, the cell
            # falls back to the normal choice instead of placing pure ground
            # with a visible jump.
            if len(rein):
                jetzt_naht = int(_auffaellige_naehte(
                    grid, tm, x, y, [int(grid[y, x])])[0])
                rein = rein[_auffaellige_naehte(grid, tm, x, y, rein)
                            <= jetzt_naht]
            if len(rein):
                rein = rein[~_macht_harte_kante(grid, tm, x, y, rein)]
            if len(rein):
                gut = np.array([k for k in rein
                                if _passt_zu_nachbarn(grid, tm, x, y, int(k))],
                               dtype=np.int32)
                if len(gut):
                    gew = np.array([max(1.0, float(tm.usage.get(int(t), 1)))
                                    for t in gut])
                    grid[y, x] = int(rng.choice(gut, p=gew / gew.sum()))
                else:
                    grid[y, x] = int(rein[int(np.argmin(
                        _schlimmste_naht(grid, tm, x, y, rein)))])
                gesetzt += 1
                continue
        gleich = kand[gesamt <= gesamt.min() + 1]
        if len(gleich) > 1:
            gew = np.array([max(1.0, float(tm.usage.get(int(t), 1)))
                            for t in gleich])
            wahl = int(rng.choice(gleich, p=gew / gew.sum()))
        else:
            wahl = int(gleich[0])
        # Nur tauschen, wenn es wirklich besser wird.
        # Only swap when it actually gets better.
        neu_fehler = int(gesamt[np.nonzero(kand == wahl)[0][0]])
        if wahl != int(grid[y, x]) and neu_fehler < jetzt:
            grid[y, x] = wahl
            gesetzt += 1
    return gesetzt


def _richte_uebergaenge(grid: np.ndarray, tm: "TileModel",
                        runden: int = 3) -> int:
    """Uebergangskacheln gegen passende aus demselben Satz tauschen.

    Eine Uebergangskachel wird beim Sampeln einzeln gewaehlt und kennt dabei
    nur ihre linke und obere Nachbarin. Was rechts und unten spaeter dazukommt,
    kann nicht mehr beruecksichtigt werden -- und weil das Mischband zwei bis
    drei Kacheln dick ist, stehen dort Uebergaenge neben Uebergaengen, deren
    Ausrichtung nichts koppelt.

    Hier bekommt jede Uebergangskachel alle vier Nachbarn zu sehen und wird
    gegen die Kachel ihres eigenen Satzes getauscht, die am besten dazu passt.
    Der Satz bleibt, es aendert sich nur, welches Stueck daraus genommen wird
    -- Boden und Bandverlauf bleiben also unveraendert.

    Gemessen ueber drei Seeds fallen die sichtbaren Brueche dadurch um 40-43 %
    (0,79 auf 0,45 %), bei rund 500 getauschten Kacheln je Karte. Der Gewinn
    sitzt am Kontakt zum reinen Boden (2,24 auf 1,27 %); innerhalb des Bandes
    steigt es leicht (0,19 auf 0,63 %), was der Tausch bewusst in Kauf nimmt.

    Swap transition tiles for fitting ones from the same set. A transition tile
    is chosen individually while sampling and only knows its left and top
    neighbour; whatever arrives to the right and below later cannot be taken
    into account -- and since the blend band is two to three tiles thick,
    transitions stand next to transitions with nothing coupling their
    orientation.

    Here every transition tile gets to see all four neighbours and is swapped
    for the tile of its own set that fits them best. The set stays the same,
    only which piece is taken from it changes, so ground and band layout remain
    untouched.

    Measured across three seeds, visible breaks drop by 40-43 % (0.79 to
    0.45 %) at around 500 swapped tiles per map. The gain sits at the contact
    with pure ground (2.24 to 1.27 %); inside the band it rises slightly (0.19
    to 0.63 %), which the swap accepts deliberately.
    """
    if tm.muster is None or not tm.trans:
        return 0
    satz: dict[int, np.ndarray] = {}
    for liste in tm.trans.values():
        kacheln = np.array([int(t) for t, _ in liste], dtype=np.int32)
        for t, _ in liste:
            satz[int(t)] = kacheln
    h, w = grid.shape
    getauscht = 0
    for _ in range(max(1, runden)):
        ys, xs = np.nonzero(tm.ist_uebergang[grid])
        aenderung = 0
        for y, x in zip(ys.tolist(), xs.tolist()):
            kand = satz.get(int(grid[y, x]))
            if kand is None or len(kand) < 2:
                continue
            # (eigene Seite, Muster der Nachbarin an der gemeinsamen Kante)
            # (own side, the neighbour's pattern along the shared edge)
            soll = []
            for (ny, nx), (q, z) in (((y, x - 1), (1, 0)), ((y - 1, x), (3, 2)),
                                     ((y, x + 1), (0, 1)), ((y + 1, x), (2, 3))):
                if 0 <= ny < h and 0 <= nx < w:
                    soll.append((q, tm.muster[int(grid[ny, nx]), z]))
            if not soll:
                continue
            fehler = np.zeros(len(kand), dtype=np.int32)
            for q, muster in soll:
                fehler += (tm.muster[kand, q] != muster).sum(axis=1)
            jetzt = int(fehler[kand == int(grid[y, x])][0])
            i = int(np.argmin(fehler))
            if int(fehler[i]) < jetzt:
                grid[y, x] = int(kand[i])
                aenderung += 1
        getauscht += aenderung
        if not aenderung:
            break
    return getauscht


def _repariere_kontakte(grid, fam_field, tm, rng, ist, bereich) -> int:
    """Uebrig gebliebene Direktkontakte zweier Boeden nachtraeglich schliessen.

    Geprueft wird an den KACHELN, nicht am Familienfeld. Der erste Anlauf sah
    aufs Familienfeld -- also auf die Absicht -- und uebersah damit genau die
    Faelle, in denen der Sampler auf seinen Notnagel zurueckgefallen ist und
    eine Kachel der falschen Familie gesetzt hat. Sichtbar ist aber, was auf
    der Karte liegt.

    Checked on the TILES, not on the family field. The first attempt looked at
    the family field -- the intent -- and thereby missed exactly those cases
    where the sampler fell back and placed a tile of the wrong family. What is
    visible is what lies on the map.
    """
    y0, y1, x0, x1 = bereich
    h, w = grid.shape
    geheilt = 0
    for durchgang in range(2):
        fam = tm.family_of[grid]
        gefunden = False
        for y in range(max(1, y0), min(h - 1, y1)):
            for x in range(max(1, x0), min(w - 1, x1)):
                a = int(fam[y, x])
                if a < 0 or a >= len(tm.families):
                    continue
                for dy, dx in ((0, 1), (1, 0)):
                    ny, nx = y + dy, x + dx
                    if ny >= h - 1 or nx >= w - 1:
                        continue
                    b = int(fam[ny, nx])
                    if b < 0 or b >= len(tm.families) or a == b:
                        continue
                    paar = tuple(sorted((tm.families[a], tm.families[b])))
                    if paar not in tm.rand:
                        continue
                    kachel = _rand_kachel(grid, fam_field, tm, rng, paar,
                                          ist, nx, ny)
                    if kachel is not None:
                        grid[ny, nx] = kachel
                        fam[ny, nx] = tm.family_of[kachel]
                        geheilt += 1
                        gefunden = True
        if not gefunden:
            break
    return geheilt


def _grenz_richtung(ist_a: np.ndarray, y: int, x: int) -> int | None:
    """In welche Richtung faellt der Anteil von Boden A ab? (0-7, 45-Grad-Schritte)"""
    # 7x7 statt 5x5: mit dem engen Fenster sprang die geschaetzte Richtung
    # entlang derselben Kante von Zelle zu Zelle, und benachbarte Zellen
    # griffen dadurch in voellig verschiedene Kacheltoepfe.
    # 7x7 instead of 5x5: with the narrow window the estimated direction jumped
    # from cell to cell along the same edge, so neighbouring cells drew from
    # completely different tile pools.
    if y < 3 or x < 3 or y >= ist_a.shape[0] - 3 or x >= ist_a.shape[1] - 3:
        return None
    f = ist_a[y - 3:y + 4, x - 3:x + 4].astype(np.float64)
    gy = float(f[4:, :].sum() - f[:3, :].sum())
    gx = float(f[:, 4:].sum() - f[:, :3].sum())
    if gx == 0.0 and gy == 0.0:
        return None
    return int((np.degrees(np.arctan2(gy, gx)) % 360.0 + 22.5) // 45) % 8


def _passt_zu_nachbarn(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                       kachel: int, nur_gesetzte: bool = False, schwelle: float | None = None) -> bool:
    """Passt die Kachel zu ALLEN vier Nachbarn?

    Beim zeilenweisen Erzeugen reichen links und oben -- rechts und unten ist
    noch nichts gesetzt. Uebergangskacheln kommen aber NACHTRAEGLICH auf
    fertigen Boden, da liegen alle vier Nachbarn schon. Nur zwei zu pruefen
    liess entsprechend die Haelfte der Fehlpaarungen durch: gemessen stammten
    67 % aller nie beobachteten Nachbarpaare von Uebergangskacheln, obwohl die
    nur 20 % der Flaeche ausmachen.

    Does the tile fit ALL four neighbours? Row-by-row generation only needs
    left and top -- nothing is placed right or below yet. But transition tiles
    go onto finished ground AFTERWARDS, where all four neighbours already
    exist. Checking only two let half the mismatches through: 67 % of all
    never-observed tile pairs came from transition tiles, which cover only
    20 % of the area.
    """
    h, w = grid.shape
    # Kantenregel statt gelernter Paartabelle: die Tabelle kannte nur, was in
    # 33 Karten zufaellig vorkam, und liess deshalb fast alles durchfallen.
    # Edge rule instead of the learned pair table: the table only knew what
    # happened to occur in 33 maps and therefore rejected almost everything.
    pruefungen = (
        ("rechts", int(grid[y, x - 1]) if x > 0 else None, True),
        ("unten", int(grid[y - 1, x]) if y > 0 else None, True),
        ("rechts", int(grid[y, x + 1]) if x + 1 < w else None, False),
        ("unten", int(grid[y + 1, x]) if y + 1 < h else None, False),
    )
    for richtung, nachbar, nachbar_ist_quelle in pruefungen:
        if nachbar is None or (nur_gesetzte and nachbar < 0):
            continue
        quelle, ziel = ((nachbar, kachel) if nachbar_ist_quelle
                        else (kachel, nachbar))
        if schwelle is None:
            erlaubt, _ = tm.nachbarn(quelle, richtung)
        else:
            erlaubt, _ = tm.nachbarn_schwelle(quelle, richtung, schwelle)
        if erlaubt is not None and ziel not in erlaubt:
            return False
    return True


def _schlimmste_naht(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                     kacheln) -> np.ndarray:
    """Groesster Farbsprung je Kandidat an allen vier Nahtstellen.

    Damit laesst sich auch dort noch waehlen, wo keine Kachel die Schwelle
    haelt: nicht irgendeine, sondern die am wenigsten auffaellige.

    Largest colour jump per candidate across all four seams. This still allows
    a choice where no tile keeps the threshold: not an arbitrary one, but the
    least noticeable.
    """
    h, w = grid.shape
    kand = np.asarray(kacheln, dtype=int)
    schlimm = np.zeros(len(kand))
    nachbarn = (
        ("rechts", grid[y, x - 1] if x > 0 else -1, False),
        ("unten", grid[y - 1, x] if y > 0 else -1, False),
        ("rechts", grid[y, x + 1] if x + 1 < w else -1, True),
        ("unten", grid[y + 1, x] if y + 1 < h else -1, True),
    )
    for richtung, nachbar, rueck in nachbarn:
        if nachbar < 0:
            continue
        d = tm.kanten_abstand(int(nachbar), richtung, rueck)
        schlimm = np.maximum(schlimm, d[kand])
    return schlimm


def _auffaellige_naehte(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                        kacheln) -> np.ndarray:
    """Wie viele der vier Nahtstellen je Kandidat sichtbar springen (0..4).

    Gegenstueck zu `_schlimmste_naht`: dort interessiert der groesste Sprung,
    hier ihre Zahl. Das ist genau das, was auf der fertigen Karte als
    sichtbarer Bruch gezaehlt wird, und laesst sich deshalb mit Musterfehlern
    verrechnen. Ohne Musterstrafe, sonst zaehlt die Musterabweichung zweimal.

    How many of the four seams jump visibly per candidate (0..4). Counterpart to
    `_schlimmste_naht`: there the largest jump matters, here their number --
    exactly what is counted as a visible break on the finished map, and
    therefore commensurable with pattern errors. Without the pattern penalty,
    otherwise the pattern deviation would count twice.
    """
    h, w = grid.shape
    kand = np.asarray(kacheln, dtype=int)
    zahl = np.zeros(len(kand), dtype=np.int32)
    nachbarn = (
        ("rechts", grid[y, x - 1] if x > 0 else -1, False),
        ("unten", grid[y - 1, x] if y > 0 else -1, False),
        ("rechts", grid[y, x + 1] if x + 1 < w else -1, True),
        ("unten", grid[y + 1, x] if y + 1 < h else -1, True),
    )
    for richtung, nachbar, rueck in nachbarn:
        if nachbar < 0:
            continue
        d = tm.kanten_abstand(int(nachbar), richtung, rueck, mit_muster=False)
        zahl += d[kand] > tm.KANTEN_SCHWELLE
    return zahl


def _macht_harte_kante(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                       kacheln) -> np.ndarray:
    """Welche Kandidaten stossen ohne Uebergang direkt an einen fremden Boden?

    Gemessen ueber die Originalkarten: zwischen zwei Boeden, fuer die es einen
    Uebergangssatz gibt, liegt dort IMMER eine Uebergangskachel -- cm03, cm04,
    newworld, eden01 und on2_01 haben zusammen null solche Nahtstellen. Harte
    Kanten gibt es nur zwischen Erde und Bewuchs sowie Fels und Schnee, und
    genau fuer diese Paare fehlt der Satz.

    Which candidates butt straight against a foreign ground without a
    transition? Measured across the original maps: between two grounds that have
    a transition set there is ALWAYS a transition tile -- cm03, cm04, newworld,
    eden01 and on2_01 together have zero such seams. Hard edges exist only
    between dirt and vegetation and between rock and snow, and those are exactly
    the pairs without a set.
    """
    h, w = grid.shape
    kand = np.asarray(kacheln, dtype=int)
    eigen = tm.family_of[kand]
    schlecht = np.zeros(len(kand), dtype=bool)
    gueltig = eigen >= 0
    for ny, nx in ((y, x - 1), (y - 1, x), (y, x + 1), (y + 1, x)):
        if not (0 <= ny < h and 0 <= nx < w):
            continue
        nachbar = int(grid[ny, nx])
        if tm.ist_uebergang[nachbar]:
            continue
        gegen = int(tm.family_of[nachbar])
        if gegen < 0:
            continue
        schlecht |= gueltig & (eigen != gegen) & tm.paar_hat_satz[
            np.where(gueltig, eigen, 0), gegen]
    return schlecht


def _boden_an_klippen_nachziehen(grid: np.ndarray, fam_field: np.ndarray,
                                 klippen: np.ndarray, tm: "TileModel",
                                 rng: np.random.Generator) -> int:
    """Bodenkacheln neben fertigen Klippen noch einmal waehlen.

    Die Klippen entstehen zuletzt und ueberschreiben, was der Sampler dort
    gesetzt hatte. Der Boden daneben wurde also fuer eine Nachbarin gewaehlt,
    die es nicht mehr gibt -- gemessen war die Naht Klippe|Boden mit 10,0 %
    die schlechteste der ganzen Karte, gegen 0,2-0,3 % in den Originalen.
    Hier bekommt dieser Boden seine Wahl zurueck, jetzt mit der echten Klippe
    als Nachbarin. Die Familie bleibt, es geht nur um die Kachel.

    Choose the ground tiles next to finished cliffs again. Cliffs are drawn last
    and overwrite what the sampler had put there, so the ground beside them was
    chosen for a neighbour that no longer exists -- measured, the cliff|ground
    seam was the worst on the map at 10.0 %, against 0.2-0.3 % in the originals.
    Here that ground gets its choice back, now with the real cliff as its
    neighbour. The family stays; only the tile changes.
    """
    if not klippen.any():
        return 0
    h, w = grid.shape
    rand = np.zeros_like(klippen)
    rand[1:, :] |= klippen[:-1, :]
    rand[:-1, :] |= klippen[1:, :]
    rand[:, 1:] |= klippen[:, :-1]
    rand[:, :-1] |= klippen[:, 1:]
    rand &= ~klippen
    frei = np.array([t for t in range(2048) if tm.placeable[t]], dtype=np.int32)
    geaendert = 0
    ys, xs = np.nonzero(rand)
    for y, x in zip(ys.tolist(), xs.tolist()):
        fam = int(fam_field[y, x])
        kand = frei[tm.family_of[frei] == fam]
        if not len(kand):
            continue
        # Nur eingreifen, wenn die jetzige Kachel wirklich nicht mehr passt.
        # Only step in when the current tile really no longer fits.
        if _passt_zu_nachbarn(grid, tm, x, y, int(grid[y, x])):
            continue
        gut = np.array([i for i, k in enumerate(kand)
                        if _passt_zu_nachbarn(grid, tm, x, y, int(k))],
                       dtype=int)
        if len(gut):
            gew = np.array([max(0.01, float(tm.usage.get(int(kand[i]), 0)))
                            for i in gut])
            wahl = int(kand[gut[int(rng.choice(len(gut), p=gew / gew.sum()))]])
        else:
            schlimm = _schlimmste_naht(grid, tm, x, y, kand)
            wahl = int(kand[int(np.argmin(schlimm))])
        if wahl != int(grid[y, x]):
            grid[y, x] = wahl
            geaendert += 1
    return geaendert


# Duerfen sich Klippenbloecke ueberlappen? Die Originalkarten tun es --
# gemessen beginnen nur 29-42 % ihrer Klippenlaeufe auf einem Dreierraster.
# Zum Vergleichen laesst es sich hier abschalten.
# May cliff blocks overlap? The original maps do -- measured, only 29-42 % of
# their cliff runs start on a three-cell grid. It can be switched off here for
# comparison.
UEBERLAPPEN = False


# Die Neigungen, in denen sich eine Klippe bauen laesst -- als (dx, dy) je
# Achtelkreis, daraus werden alle vier Quadranten gespiegelt.
#
# Gemessen an cm03: der waagerechte Versatz der linken Klippenkante von Zeile
# zu Zeile (919 Messungen).
#
#     Versatz je Zeile   Anteil   entspricht
#      0 Spalten          55,2 %   senkrecht
#     ±1 Spalte           24,5 %   45 Grad
#     ±2 Spalten           8,0 %   26,6 Grad
#     ±3 Spalten           6,6 %   18,4 Grad
#     ±4 Spalten           3,6 %   14,0 Grad
#
# Ueber die Haelfte aller Schritte ist senkrecht; darueber hinaus kommen nur
# Versaetze bis vier Spalten vor. Eine schraege Wand entsteht in den Originalen
# also nicht aus einem festen Verhaeltnis, sondern aus einer Treppe -- die
# Schraege bei (82,39) in cm03 wechselt zwischen -1 und -2 und ergibt so 1,6:1.
# Genau diese Verhaeltnisse sind hier die erlaubten Richtungen.
#
# The slopes a cliff can be built in, as (dx, dy) per octant, mirrored into all
# four quadrants. Measured on cm03: the horizontal offset of the left cliff edge
# from row to row, 919 samples. More than half of all steps are vertical, and
# beyond that only offsets up to four columns occur.
KLIPPEN_NEIGUNGEN = ((1, 0), (4, 1), (3, 1), (2, 1), (1, 1),
                     (1, 2), (1, 3), (1, 4), (0, 1))


def klippen_richtungen() -> list[tuple[int, int]]:
    """Alle erlaubten Baurichtungen als gekuerzte (dx, dy)."""
    aus = set()
    for dx, dy in KLIPPEN_NEIGUNGEN:
        for sx in (1, -1):
            for sy in (1, -1):
                aus.add((dx * sx, dy * sy))
    return sorted(aus)


def klippe_winkel_rasten(ax: int, ay: int, bx: int, by: int) -> tuple[int, int]:
    """Den Zielpunkt auf die naechste erlaubte Baurichtung ziehen.

    Gewaehlt wird die Richtung mit dem kleinsten Winkelabstand, und darauf die
    Laenge, die der Zeigerlage am naechsten kommt. So bleibt die gezogene
    Strecke gleich lang und dreht sich nur auf die erlaubte Neigung.

    Pull the target point onto the nearest permitted build direction: the
    direction with the smallest angular distance, at the length closest to where
    the cursor sits, so the stroke keeps its length and only rotates.
    """
    vx, vy = bx - ax, by - ay
    if vx == 0 and vy == 0:
        return bx, by
    laenge = (vx * vx + vy * vy) ** 0.5
    beste = None
    for dx, dy in klippen_richtungen():
        n = (dx * dx + dy * dy) ** 0.5
        # Kosinus des Winkels zwischen Zeigerrichtung und Kandidat.
        kos = (vx * dx + vy * dy) / (laenge * n)
        if beste is None or kos > beste[0]:
            beste = (kos, dx, dy, n)
    _k, dx, dy, n = beste
    schritte = max(1, int(round(laenge / n)))
    return ax + dx * schritte, ay + dy * schritte


# Wie stark der Versatz innerhalb einer Schraegen schwankt. Gemessen an 41
# schraegen Kantenstuecken aus 6 Originalkarten: KEINES benutzt lauter gleiche
# Versaetze, 39 % benutzen vier verschiedene Werte, die Streuung innerhalb
# einer Folge liegt im Median bei 1,31.
#
#     0  0  0 -1  0 -1 -2 -2 -1  0 -1 -2 -4 -3 -2 -4 -2  0  0
#     0  0 -1 -2  0  0 -1 -3 -1 -3 -2 -3 -4 -1  0 -1  0  0 -1 +1
#
# Darin steckt dreierlei: Nullen mittendrin (die Wand laeuft ein Stueck
# senkrecht weiter), grosse Spruenge neben kleinen, und gelegentlich eine
# Gegenbewegung. Eine gleichmaessige Treppe -2, -2, -2 kommt nirgends vor --
# und genau deshalb sieht man bei ihr jede Stufe einzeln.
#
# How much the offset varies inside a slope. Measured on 41 diagonal edge runs
# from 6 original maps: not one uses uniform offsets, 39 % use four different
# values, and the spread within a run has a median of 1.31.
#
# Diese Streuung war lange die einzige Vorgabe, und daran ist der Erzeuger
# gescheitert: Mittelwert und Streuung legen eine Verteilung nicht fest. Die
# Verteilung selbst ist unten gemessen und wird direkt benutzt.
# Mean and spread do not pin down a distribution; the distribution itself is
# measured below and used directly.

# Die Treppe einer Schraegen -- Trittlaenge und Sprunghoehe, direkt gemessen.
#
# Gezaehlt an 206 Schraegen aus den 54 Stockkarten (974 Tritte): die Oberkante
# eines Klippenbandes Spalte fuer Spalte verfolgt und gezaehlt, wie viele
# Spalten sie gleich bleibt, bevor sie springt.
#
#   Trittlaenge   1  41,1 %   2  23,4 %   3  12,1 %   4  7,8 %   5  6,1 %
#                 Median 2, Mittel 2,62, laenger kommt vor, aber selten
#   Sprunghoehe   1  75,5 %   2  24,5 %   -- drei Zeilen NIE
#
# Die Trittlaengen sind fast genau geometrisch: mit q = 1 - 1/2,62 sagt die
# Verteilung 38,2 / 23,6 / 14,6 / 9,0 / 5,6 % gegen gemessene
# 41,1 / 23,4 / 12,1 / 7,8 / 6,1 %. Erzeugt wird deshalb geometrisch mit dem
# Mittel, das die verlangte Neigung fordert -- die FORM der Verteilung ist
# gemessen, ihr Mittelwert kommt aus der gezeichneten Linie.
#
# Vorher wurde die Folge aus Mittelwert und Streuung gebaut. Das lieferte 17 %
# Schritte <= 0 -- ein Tritt der Laenge 0 ist kein Tritt, sondern zwei Absaetze
# uebereinander, und die Wand faellt in EINER Spalte um zwei Zeilen. An genau
# diesen Stellen sassen 79 % der Kachelpaare, die in keiner Originalkarte
# vorkommen. Mit einer Untergrenze allein wurde es nicht besser, sondern
# anders schlecht: die geforderte Streuung war dann nur noch ueber Extreme zu
# erreichen (lauter Einsen und Vieren), und ueber Eck stand 20 % lang dieselbe
# Kachel statt der gemessenen 1,31 %.
#
# Measured on 206 slopes from the 54 stock maps: tread lengths are all but
# exactly geometric, and a riser is one row (75,5 %) or two (24,5 %), never
# three. The distribution's SHAPE is measured; its mean comes from the drawn
# line.
# Die Naht an der Stufe laesst sich NICHT ueber die Blockwahl verbessern -- der
# Blockweg hat dafuer keinen Spielraum. Gemessen:
#
#   Bloecke je Familie insgesamt            mud 18, san 17
#   Bloecke je Laufrichtung                 1 bis 3
#   Blockpaare mit mehr als einem
#     gezaehlten Versatz                    38 von 482 (8 %)
#
# Ein Gewicht auf der Naht wurde gebaut und gemessen: Faktoren von 0 bis 200
# aendern kein einziges Ergebnis, weil `waehle` meist genau einen Kandidaten
# hat. Die Wand, die der Blockweg baut, ist praktisch festgelegt.
#
# The seam cannot be improved through the block choice: with 18 blocks per
# family, 1 to 3 per direction and a single counted offset for 92 % of pairs,
# there is nothing to weight. Seam weights from 0 to 200 changed no result.


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
    _bewuchs_abstand(fam_field, tm, params.bewuchs_abstand)
    # Landschaftsmodus: das Relief steht VOR den Uebergaengen fest, denn der
    # einfarbige Saum unter den kommenden Waenden und die Sandbetten aendern
    # die Biomgrenzen -- und die werden gleich darunter eingemischt.
    # Landscape mode: the relief is fixed BEFORE the transitions, because the
    # single-colour rim under the future walls and the sand beds change the
    # biome borders -- which get blended right below.
    land_H = None
    land_betten = None
    if params.landschaft:
        land_H, land_betten = _landschaft_hoehenfeld(params, rng)
        if params.symmetry != SYM_NONE:
            land_H = _apply_symmetry(land_H, params.symmetry).astype(np.int8)
            land_betten = _apply_symmetry(
                land_betten.astype(np.int8), params.symmetry).astype(bool)
        _landschaft_familien(fam_field, land_H, land_betten, tm)
    # Der Erdpuffer zwischen Fels und Sand ist ein Notbehelf aus der Zeit, als
    # es fuer dieses Paar keinen Uebergangssatz gab. `santoroc` mit 48 Kacheln
    # gibt es aber -- gemessen ueber vier Seeds ist es OHNE Puffer besser:
    # Musterbrueche 1,02 statt 1,32 %, sichtbare Brueche 0,51 statt 0,61 %, bei
    # praktisch gleichem Erdanteil (44,0 statt 44,5 %). Sichtbar war er als
    # heller Erdkeil mitten in einer Sand-Fels-Grenze.
    # The dirt buffer between rock and sand is a stopgap from a time when this
    # pair had no transition set. But `santoroc` with 48 tiles does exist -- and
    # measured across four seeds it is better WITHOUT the buffer: pattern breaks
    # 1.02 instead of 1.32 %, visible breaks 0.51 instead of 0.61 %, at
    # practically the same dirt share (44.0 instead of 44.5 %). It showed up as a
    # pale dirt wedge in the middle of a sand-rock border.
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
    # Erst die Uebergaenge festlegen, dann den Boden drumherum sampeln.
    # Umgekehrt kann der Uebergang nicht mehr zum schon gesetzten Boden passen.
    # Fix the transitions first, then sample the ground around them. The other
    # way round the transition cannot fit the ground that is already there.
    vorbelegt = np.full(fam_field.shape, -1, dtype=np.int32)
    _mische_grenzen(vorbelegt, fam_field, tm, rng, params_style=params)

    # Die Klippen genauso: Form steht schon fest, also die Kacheln vor dem
    # Boden setzen statt hinterher darueber zu malen. Gemessen kosteten die
    # nachtraeglich gemalten Klippen 1,55 Prozentpunkte an Fehlpaaren -- der
    # Boden neben ihnen war laengst gewaehlt, als sie kamen.
    # The cliffs likewise: their shape is already determined, so place their
    # tiles before the ground instead of painting over it afterwards. Measured,
    # cliffs painted afterwards cost 1.55 percentage points of bad pairs -- the
    # ground beside them had long been chosen when they arrived.
    gesperrt_vulkan = np.zeros(fam_field.shape, dtype=bool)
    for vx, vy in sites:
        gesperrt_vulkan[max(0, vy - 10):vy + 11, max(0, vx - 10):vx + 11] = True
    if params.landschaft:
        # Der Klippenregler ist im Relief schon verrechnet; _hoehenfeld traegt
        # hier nur noch die gezielten Merkmale (Berg, Tal, Engstelle) bei.
        # The cliff slider is already part of the relief; _hoehenfeld only
        # contributes the requested features here.
        H = (_hoehenfeld(replace(params, cliffs=0.0), rng, layout)
             | land_H).astype(np.int8)
    else:
        H = _hoehenfeld(params, rng, layout)
    if params.symmetry != SYM_NONE:
        H = _apply_symmetry(H, params.symmetry).astype(np.int8)
    H[gesperrt_vulkan] = 0
    if params.landschaft and H.any():
        # Der Vulkanausschnitt kann das Massiv zerteilen; Splitter unter der
        # Mindestgroesse waeren spaeter unbelegbare Konturen.
        # The volcano punch can split the massif; slivers below the minimum
        # size would later be contours no block can cover.
        H = shapegen.entferne_kleinkram(
            H, mindest=max(24, int(round(0.0015 * params.width
                                         * params.height))))

    grid = _sample_tiles(fam_field, rng, tm, fest=vorbelegt)
    # Klippen NACH dem Sampeln: sie brauchen echte Bodennachbarn, um passende
    # Kacheln zu finden. Vorbelegt gewaehlt sahen sie nur leere Zellen und
    # entschieden unbeschraenkt -- das kostete 0,55 Punkte.
    # Cliffs AFTER sampling: they need real ground neighbours to find fitting
    # tiles. Chosen as a pre-fill they saw only empty cells and decided without
    # constraints, which cost 0.55 points.
    # Reparatur ERST hier: vorher existiert der Boden noch nicht. Sie schliesst
    # die Direktkontakte, die an Dreipunkten und beim Notnagel des Samplers
    # uebrig bleiben.
    # Repair only here: before this the ground does not exist yet. It closes
    # the direct contacts left over at three-way junctions and by the sampler's
    # fallback.
    _ist = {f: fam_field == f for f in range(len(tm.families))}
    _repariere_kontakte(grid, fam_field, tm, rng, _ist,
                        (0, params.height, 0, params.width))
    volcanoes = _stamp_volcanoes(grid, sites, tm, rng)
    lava_zones = [_lava_zone(v, grid.shape, params.lava_zone_tiles, rng)
                  for v in volcanoes]

    # Klippen ganz zum Schluss: sie brauchen echte Bodennachbarn, und die
    # Reparatur wuerde sie sonst nachtraeglich wieder zerlegen.
    # Cliffs last of all: they need real ground neighbours, and the repair pass
    # would otherwise take them apart again afterwards.
    # Beide Modi: die Hochlandkontur als Linienzug, belegt vom
    # Gelaende-Loeser. Der Blockweg und das Zelltypband (_male_klippen) sind
    # entfernt.
    # Both modes: the highland contour as a polyline, covered by the terrain
    # solver. The block path and the cell-type band are gone.
    klippen, land_zellen = _klippen_aus_linien(grid, fam_field, H, tm,
                                               rng, params.ramps)
    _boden_an_klippen_nachziehen(grid, fam_field, klippen, tm, rng)
    nachbearbeite_uebergaenge(grid, fam_field, tm, rng)

    # Klippen: erst die Form, dann die Kacheln. Das Kopieren fertiger
    # Ausschnitte aus den Originalkarten ist raus -- es sah aufgeklebt aus,
    # weil ein Ausschnitt seinen eigenen Boden mitbringt und an der Naht
    # Kacheln aufeinandertreffen, die im Original nie nebeneinander lagen.
    # Cliffs: shape first, tiles second. Copying finished cutouts from the
    # original maps is gone -- it looked glued on, because a cutout brings its
    # own ground along and at the seam tiles meet that never sat next to each
    # other in the original.
    gesperrt = gesperrt_vulkan.copy()
    flaeche = params.width * params.height
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
    # Die gezeichneten Klippen kennen ihre Hochseite; die Zelltypen aus dem
    # Zug sind der Tabelle je Kachel ueberlegen (98,6 gegen 94,1 % richtig,
    # docs/klippen-stand.md, 10). Bei Symmetrie kommt die zweite Haelfte aus
    # der Spiegelung des Kachelgitters -- dort passt das Zugfeld nicht mehr,
    # also bleibt es bei der Tabelle.
    # The drawn cliffs know their high side; the stroke's cell types beat the
    # per-tile table. Under symmetry the second half comes from mirroring the
    # tile grid, where the stroke field no longer matches -- table it is.
    if land_zellen is not None and params.symmetry == SYM_NONE:
        treffer = land_zellen >= 0
        cells[treffer] = land_zellen[treffer].astype(cells.dtype)
    # Klippenzellen aus den Lavafeldern nehmen. Die Felder entstehen aus dem
    # Hoehenfeld und enthielten dadurch den Wandfuss -- eine Klippe hinauf
    # fliesst keine Lava. Nur Klippen, nicht alles Unpassierbare: der
    # Vulkankrater selbst ist unpassierbar und ist genau die Quelle.
    # Remove cliff cells from the lava fields. The fields are built from the
    # height field and therefore included the foot of the wall -- lava does not
    # flow up a cliff. Cliffs only, not everything impassable: the volcano
    # crater itself is impassable and is precisely the source.
    keine_klippe = ~np.isin(cells, [celltypes.NORTH_CLIFFS,
                                    celltypes.CLIFFS_HIGH_SIDE,
                                    celltypes.CLIFFS_LOW_SIDE])
    lava_zones = [[(x, y) for x, y in zone if keine_klippe[y, x]]
                  for zone in lava_zones]
    lava_zones = [zone for zone in lava_zones if zone]

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
        fluss_share=(float(land_betten.mean()) if land_betten is not None
                     else 0.0),
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
