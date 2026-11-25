"""Anbindung an OP2MappingLib (op2maplib).

OP2MappingLib ist die C++-Portierung des Gelaendepinsels und des
Klippenwerkzeugs dieses Editors (github.com/OutpostUniverse/OP2MappingLib).
Hier wird sie geladen und fuer `PaintLayers` aufbereitet: Profil einmal laden,
pro Rechnung eine frische Mischkarte (`BlendMap`) aus der aktuellen Karte.

Frisch statt mitgefuehrt, weil der Editor Kacheln auf vielen Wegen aendert
(Rueckgaengig, Kachelstempel, Vulkan, Generator, Klippenschnitte). Eine
mitgefuehrte Kopie muesste jeden davon melden; eine frische ist immer im
Stand der Karte und kostet auf 512x256 nur wenige Millisekunden.

Fehlt die Bibliothek oder ist sie in config.ini abgeschaltet ([terrain]
op2maplib = false), liefert `verfuegbar()` False und `PaintLayers` nimmt den
eingebauten Python-Weg.

Bridge to OP2MappingLib, the C++ port of this editor's terrain brush and cliff
tool. Loads the profile once and builds a fresh BlendMap from the current map
for every computation -- fresh rather than kept in sync, because the editor
changes tiles in many ways (undo, tile stamps, volcano, generator, cliff
cuts). If the library is missing or switched off, `verfuegbar()` is False and
`PaintLayers` uses the built-in Python path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

_CODEGEN = Path(__file__).resolve().parents[2] / "codegen"
if str(_CODEGEN) not in sys.path:
    sys.path.insert(0, str(_CODEGEN))

import appconfig  # noqa: E402

# Seiten der Klippenlinie im Editor -> om_cliff_side.
# Cliff line sides in the editor -> om_cliff_side.
SEITEN = {"links": 0, "rechts": 1, "oben": 2, "unten": 3}

_zustand: dict = {}


def _laden():
    """Bibliothek und Profil laden -> (modul, profil) oder None. Einmalig."""
    if "ergebnis" in _zustand:
        return _zustand["ergebnis"]
    ergebnis = None
    grund = ""
    try:
        if not appconfig.op2maplib_aktiv():
            grund = "abgeschaltet ([terrain] op2maplib = false)"
        else:
            d = appconfig.op2maplib_dir()
            if d is None:
                grund = "OP2MappingLib nicht gefunden (Submodul fehlt?)"
            else:
                # Welche DLL (EXE: aus den Quellen gebaut; selbst bauen; sonst
                # die des Submoduls) entscheidet appconfig.op2maplib_dll.
                # Which DLL is used is decided by appconfig.op2maplib_dll.
                dll = appconfig.op2maplib_dll()
                if dll is not None and not os.environ.get("OP2MAPLIB_PATH"):
                    os.environ["OP2MAPLIB_PATH"] = str(dll)
                binding = str(d / "bindings" / "python")
                if binding not in sys.path:
                    sys.path.insert(0, binding)
                import op2maplib
                profil = op2maplib.Profile.from_file(d / "profiles" / "op2.json")
                ergebnis = (op2maplib, profil)
    except Exception as e:          # fehlende DLL, falsche Architektur, ...
        grund = f"{type(e).__name__}: {e}"
        ergebnis = None
    if ergebnis is None:
        print("OP2MappingLib nicht aktiv, Python-Weg:", grund)
    else:
        print(f"OP2MappingLib {ergebnis[0].version()} aktiv")
    _zustand["ergebnis"] = ergebnis
    return ergebnis


def verfuegbar() -> bool:
    """Ist OP2MappingLib geladen und eingeschaltet?"""
    return _laden() is not None


def modul():
    """Das op2maplib-Modul (nur aufrufen, wenn `verfuegbar()`)."""
    return _laden()[0]


def profil():
    """Das geladene Outpost-2-Profil (nur aufrufen, wenn `verfuegbar()`)."""
    return _laden()[1]


def boden(familie: str) -> int:
    """Profil-Boden zu einer Editor-Familie ("mud", "san", ...) oder -1.

    -1 auch, wenn das Profil fuer den Boden keine Fuellkacheln hat -- dann
    kann die Bibliothek ihn nicht malen.
    Profile ground for an editor family, or -1 (also if it has no fill tiles).
    """
    p = profil()
    g = p.find_ground(familie)
    if g < 0 or p.ground_fill_count(g) <= 0:
        return -1
    return g


def mischkarte(op2map, gitter: np.ndarray):
    """Frische BlendMap aus der Karte. `gitter`: Kachelindizes (h, w)."""
    om = modul()
    quellen = op2map.tileset_sources
    zuordnung = []
    for m in op2map.tile_mappings:
        name = quellen[m.tileset_index].filename if m.tileset_index < len(quellen) else ""
        zuordnung.append((name, int(m.tile_graphic_index)))
    h, w = gitter.shape
    return om.BlendMap(profil(), w, h, zuordnung,
                       gitter.astype(np.int64).ravel().tolist())


# Merkmalsarten und Symmetrien des Editors -> OP2MappingLib.
# The editor's feature kinds and symmetries -> OP2MappingLib.
_MERKMALE = {"tal": 0, "berg": 1, "plateau": 2, "frei": 3, "enge": 4}
_MERKMAL_NAME = {v: k for k, v in _MERKMALE.items()}
_SYMMETRIEN = {"none": 0, "mirror_x": 1, "mirror_y": 2, "rot180": 3, "quad": 4}


def generieren(params):
    """Karte mit dem Generator von OP2MappingLib erzeugen -> mapgen.GeneratedMap.

    Nimmt dieselben `mapgen.MapGenParams` wie der Python-Generator und liefert
    dasselbe Ergebnis-Objekt, damit "Neue Karte" unveraendert bleibt. Ohne
    Bibliothek (oder ohne Generator in ihrer Version) None -- dann rechnet der
    Aufrufer mit `mapgen.generate`.

    Generate a map with OP2MappingLib's generator. Takes the same params as the
    Python generator and returns the same result object; None if the library
    (or its generator) is not available, so the caller falls back to Python.
    """
    if not verfuegbar():
        return None
    om = modul()
    if not hasattr(om, "MapGenerator"):
        return None
    import mapgen
    from dataclasses import replace
    # Klippen: die Bibliothek haelt den Kartenrand frei. Darum eine groessere
    # Welt erzeugen und die Karte ausschneiden -- ausser bei Vulkanen, Merkmalen
    # und dem Landschaftsmodus, die ihre Lage auf der Karte brauchen.
    # Cliffs: the library keeps the map border clear, so generate a larger world
    # and crop the map, except with volcanoes, features and landscape mode,
    # which need their position on the map.
    if (params.cliffs > 0 and not params.volcanoes and not params.features
            and not params.landschaft and not mapgen.berge_gewuenscht(params)
            and not getattr(params, "_welt", False)):
        return _aus_groesserer_welt(params)
    # Mit Bergen: erst die Karte ohne Streugut und Startpunkte, dann die Berge
    # hinein, dann beides.
    # With mountains: first the map without scatter and starting points, then
    # the mountains, then both.
    if mapgen.berge_gewuenscht(params):
        grund = generieren(replace(params, berge=0.0, hochebenen=0,
                                   details=0.0, spawns=0))
        tm = mapgen.model()
        return mapgen.berge_nachtragen(grund, params, tm, Zeichner())
    gen = om.MapGenerator("plains")
    werte = {
        "width": params.width, "height": params.height, "roughness": params.roughness,
        "symmetry": _SYMMETRIEN.get(params.symmetry, 0), "spawns": params.spawns,
        "spawn_clearance": params.spawn_clearance, "cliffs": params.cliffs, "ramps": params.ramps,
        "volcanoes": params.volcanoes, "lava_zone_tiles": params.lava_zone_tiles,
        "smooth": params.smooth, "vegetation_spacing": params.bewuchs_abstand,
        "min_biome": params.min_biome, "details": params.details,
        "landscape": 1 if params.landschaft else 0, "rivers": params.fluesse,
    }
    for k, v in werte.items():
        gen.set(k, v)
    gen.set("seed", int(params.seed) & 0xFFFFFFFFFFFFFFFF)
    gen.set_mix({k: float(v) for k, v in params.mix.items() if v > 0} or {"mud": 1.0})
    for f in params.features:
        if f.kind in _MERKMALE:
            gen.add_feature(_MERKMALE[f.kind], f.where or "", f.to or "", float(f.size), bool(f.lava))
    r = gen.generate(profil())
    p = profil()
    h, w = r.height, r.width
    anteile = {p.ground_id(g): s for g, s in enumerate(r.ground_shares) if s > 0}
    return mapgen.GeneratedMap(
        tiles=np.array(r.tiles, dtype=np.int32).reshape(h, w),
        cells=np.array(r.cell_types, dtype=np.uint8).reshape(h, w),
        spawns=[tuple(s) for s in r.spawns],
        passable_share=r.stats["passable"],
        family_share=anteile,
        connected=bool(r.stats["connected"]),
        volcanoes=[tuple(v) for v in r.volcanoes],
        lava_zones=[[tuple(c) for c in z] for z in r.lava_zones],
        plateau_share=r.stats["plateau"],
        detail_share=r.stats["details"],
        features={_MERKMAL_NAME[k]: n for k, n in enumerate(r.feature_report)},
        feature_spots=[(_MERKMAL_NAME.get(k, str(k)), x, y, s) for k, x, y, s in r.features],
        fluss_share=r.stats["rivers"],
    )


def _aus_groesserer_welt(params):
    """Groesser erzeugen und die Mitte nehmen; Startplaetze danach."""
    import mapgen
    from dataclasses import replace
    r = mapgen.WELT_RAND
    gross = replace(params, width=params.width + 2 * r, height=params.height + 2 * r,
                    spawns=0)
    gross._welt = True
    gen = generieren(gross)
    s = (slice(r, -r), slice(r, -r))
    gen.tiles, gen.cells = gen.tiles[s].copy(), gen.cells[s].copy()
    tm = mapgen.model()
    gen.spawns = mapgen._pick_spawns(
        gen.cells, params.spawns, params.spawn_clearance, params.symmetry,
        np.random.default_rng([int(params.seed) & 0xFFFFFFFF, 77]))
    gen.connected = mapgen._connected(gen.cells, gen.spawns)
    gen.passable_share = float(mapgen._passable_mask(gen.cells).mean())
    gen.plateau_share = float(np.isin(gen.cells, (8, 9, 10)).mean())
    anteile = {n: float((tm.family_of[gen.tiles] == i).mean())
               for i, n in enumerate(tm.families)}
    gen.family_share = {n: a for n, a in anteile.items() if a > 0}
    return gen


class Zeichner:
    """Klippenwaende der Berge mit OP2MappingLib (siehe mapgen_berge)."""
    versuche = 4
    laeufe = 4
    grob = False                     # letzte Wand nur im Notweg geloest

    def __init__(self):
        self._mappings = profil().standard_mapping()

    def _karte(self, grid: np.ndarray):
        h, w = grid.shape
        return modul().BlendMap(profil(), w, h, self._mappings,
                                grid.astype(np.int64).ravel().tolist())

    def boden_legen(self, grid, cells, maske, saat: int) -> None:
        """Erde unter die Berge malen, mit Uebergaengen zum Rest.
        Paint dirt under the mountains, blended into the rest."""
        bm = self._karte(grid)
        ys, xs = np.nonzero(maske)
        bm.paint(profil().find_ground("mud"), list(zip(xs.tolist(), ys.tolist())))
        for c in bm.resolve(saat):
            grid[c.y, c.x] = c.new_mapping
            if c.cell_type >= 0:
                cells[c.y, c.x] = c.cell_type

    def wand(self, grid, punkte, seite: str, saat: int, hoehe: float):
        maske = np.zeros(grid.shape, bool)
        zellen = np.full(grid.shape, -1, np.int16)
        bm = self._karte(grid)
        for c in bm.draw_cliff([(int(x), int(y)) for x, y in punkte],
                               SEITEN[seite], hoehe, saat):
            grid[c.y, c.x] = c.new_mapping
            if c.cell_type in (8, 9, 10):
                maske[c.y, c.x] = True
            zellen[c.y, c.x] = c.cell_type
        self.grob = bm.last_cliff_stage < 0
        return maske, zellen


def boden_feld(bm, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Boden der Bibliothek je Zelle im Rechteck (inklusive) -> (h, w), -1 = fest."""
    return np.array([[bm.ground_at(x, y) for x in range(x0, x1 + 1)]
                     for y in range(y0, y1 + 1)], dtype=np.int16)
