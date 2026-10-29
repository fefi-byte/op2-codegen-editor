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
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import celltypes
import shapegen  # noqa: E402
from op2map import Op2Map  # noqa: E402

# Der Generator ist auf Module verteilt (mapgen_basis, _modell, _felder,
# _kacheln, _wege, _relief, _klippen, _uebergaenge). Dieses Modul reicht ALLE
# Namen weiter -- auch die mit Unterstrich, die Editor und Tests benutzen --,
# damit `mapgen.X` ueberall gleich bleibt. Hier stehen nur noch `generate`
# und `apply_to_map`.
# The generator is split across modules; this one re-exports every name so
# `mapgen.X` keeps working, and holds only `generate` and `apply_to_map`.

from mapgen_basis import (  # noqa: E402,F401
    MODEL_PATH,
    SYM_NONE,
    SYM_MIRROR_X,
    SYM_MIRROR_Y,
    SYM_ROT180,
    SYM_QUAD,
    SYMMETRIES,
    FAMILY_VEGETATION,
    TEMPLATES,
    PASSABLE_CLASSES,
    MapGenParams,
    GeneratedMap,
    _cell_types,
    FEAT_TAL,
    FEAT_BERG,
    FEAT_PLATEAU,
    FEAT_FREI,
    FEAT_ENGE,
    FEATURE_KINDS,
    SEKTOREN,
    GEGENUEBER,
    Feature,
    _sperr_maske,
    _korridor_von_stempel,
    _LEER,
)
from mapgen_modell import (  # noqa: E402,F401
    TileModel,
    _model,
    model,
)
from mapgen_felder import (  # noqa: E402,F401
    _value_noise,
    _family_field,
    _smooth_families,
    _components,
    _mirror_region,
    _naht_passt,
    _scatter_details,
    _volcano_sites,
    _lava_zone,
    _stamp_volcanoes,
    _dissolve_small_biomes,
    _apply_symmetry,
)
from mapgen_kacheln import (  # noqa: E402,F401
    _sample_tiles,
)
from mapgen_wege import (  # noqa: E402,F401
    _passable_mask,
    _clearance,
    _groesstes_gebiet,
    _pick_spawns,
    _connected,
)
from mapgen_relief import (  # noqa: E402,F401
    _hoehenfeld,
    _MOORE,
    _fluss_pfad,
    _pfad_band,
    _dehne,
    _landschaft_hoehenfeld,
    _landschaft_familien,
    _rand_zyklus,
    _kontur_vereinfachen,
    _kontur_hand,
    _kontur_boegen,
    _sektor_punkt,
    _feature_layout,
    _merkmal_pfad,
    _steer_feature_families,
    _feature_maske,
    _apply_features,
)
from mapgen_klippen import (  # noqa: E402,F401
    _klippe_algo,
    _klippen_aus_linien,
    UEBERLAPPEN,
    KLIPPEN_NEIGUNGEN,
    klippen_richtungen,
    klippe_winkel_rasten,
)
from mapgen_uebergaenge import (  # noqa: E402,F401
    _bewuchs_abstand,
    RAND_LIMIT,
    _mische_grenzen,
    _schieb,
    _rand_kandidaten,
    _loese_band,
    _rand_kachel,
    _passt_seite,
    _kanten_wuerfel,
    NAHT_STRAFE,
    nachbearbeite_uebergaenge,
    _harte_kanten,
    _schliesse_harte_kanten,
    _uebergaenge_aus_ecken,
    _richte_uebergaenge,
    _repariere_kontakte,
    _grenz_richtung,
    _passt_zu_nachbarn,
    _schlimmste_naht,
    _auffaellige_naehte,
    _macht_harte_kante,
    _boden_an_klippen_nachziehen,
)


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
