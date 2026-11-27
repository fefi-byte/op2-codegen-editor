"""Anbindung an OP2MappingLib (op2maplib).

OP2MappingLib ist die C++-Portierung des Gelaendepinsels, des
Klippenwerkzeugs und des Kartengenerators dieses Editors
(github.com/OutpostUniverse/OP2MappingLib). Karten erzeugt nur noch sie.
Hier wird sie geladen und fuer `PaintLayers` aufbereitet: Profil einmal laden,
pro Rechnung eine frische Mischkarte (`BlendMap`) aus der aktuellen Karte.

Frisch statt mitgefuehrt, weil der Editor Kacheln auf vielen Wegen aendert
(Rueckgaengig, Kachelstempel, Vulkan, Generator). Eine
mitgefuehrte Kopie muesste jeden davon melden; eine frische ist immer im
Stand der Karte und kostet auf 512x256 nur wenige Millisekunden.

Fehlt die Bibliothek oder ist sie in config.ini abgeschaltet ([terrain]
op2maplib = false), liefert `verfuegbar()` False. Einen Python-Ersatz gibt es
nicht mehr: Generator und Malwerkzeuge melden dann, dass sie nicht verfuegbar
sind (`fehlt_text()`).

Bridge to OP2MappingLib, the C++ port of this editor's terrain brush, cliff
tool and map generator; maps are generated and painted only there. Loads the
profile once and builds a fresh BlendMap from the current map for every
computation -- fresh rather than kept in sync, because the editor changes
tiles in many ways (undo, tile stamps, volcano, generator). If the library is
missing or switched off, `verfuegbar()` is False; there is no Python fallback
any more, the generator and paint tools report themselves unavailable.
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
                pfad = d / "profiles" / "op2.json"
                profil = op2maplib.Profile.from_file(pfad)
                ergebnis = (op2maplib, profil, pfad)
    except Exception as e:          # fehlende DLL, falsche Architektur, ...
        grund = f"{type(e).__name__}: {e}"
        ergebnis = None
    if ergebnis is None:
        print("OP2MappingLib nicht aktiv, Kartenfunktionen aus:", grund)
        _zustand["grund"] = grund
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


def profil_pfad() -> Path:
    """Pfad der Profildatei (nur aufrufen, wenn `verfuegbar()`)."""
    return _laden()[2]


def fehlt_text() -> str:
    """Meldung, wenn die Kartenfunktionen ohne OP2MappingLib nicht gehen."""
    _laden()
    grund = _zustand.get("grund", "")
    return ("OP2MappingLib nicht verfuegbar, Kartenfunktionen (Neue Karte, Gelaende "
            "malen, Klippen) sind aus / OP2MappingLib unavailable, map functions are off"
            + (f" ({grund})" if grund else ""))


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
    """Karte mit dem klassischen Generator von OP2MappingLib -> mapgen.GeneratedMap.

    Wirft RuntimeError, wenn die Bibliothek fehlt.
    Generate a map with OP2MappingLib's classic generator; RuntimeError without it.
    """
    if not verfuegbar():
        raise RuntimeError(fehlt_text())
    gen = _einstellungen(params, gelernt=False)
    return _ergebnis(gen.generate(profil()), params)


# Verlaeufe des Editors -> om_mapgen_set "gradient" (1..10 in dieser Reihenfolge).
# The editor's gradients -> "gradient" 1..10 in this order.
_VERLAEUFE = ("n-s", "s-n", "w-o", "o-w", "nw-so", "so-nw", "no-sw", "sw-no", "mitte-rand", "rand-mitte")
_VERLAUF_BODEN = {"": -1, "mud": 0, "roc": 1, "san": 2}


def _einstellungen(params, gelernt: bool):
    """MapGenParams -> op2maplib.MapGenerator."""
    om = modul()
    gen = om.MapGenerator("learned" if gelernt else "plains")
    werte = {
        "width": params.width, "height": params.height, "roughness": params.roughness,
        "symmetry": _SYMMETRIEN.get(params.symmetry, 0), "spawns": params.spawns,
        "spawn_clearance": params.spawn_clearance, "cliffs": params.cliffs, "ramps": params.ramps,
        "volcanoes": 0 if gelernt else params.volcanoes, "lava_zone_tiles": params.lava_zone_tiles,
        "smooth": params.smooth, "vegetation_spacing": params.bewuchs_abstand,
        "min_biome": params.min_biome, "details": params.details,
        "landscape": 1 if params.landschaft else 0, "rivers": params.fluesse,
        "mountains": params.berge, "mountain_density": params.berg_dichte,
        "gorges": params.schluchten, "valleys": params.taeler, "plateaus": params.hochebenen,
        # Klippen laufen wie im Original ueber den Rand (die Bibliothek nimmt das
        # nur, wo es geht: ohne Vulkane, Merkmale, Landschaftsmodus).
        # Cliffs run off the map as in the originals where the library allows it.
        "world_cutout": 1 if params.cliffs > 0 else 0,
        "learned_rocks": 1 if params.berg_felsen else 0,
    }
    if gelernt:
        werte.update({
            "coherence": params.grossform, "calm_terrain": params.gelaende_ruhe,
            "biome_calm": params.biom_ruhe, "lava_rock": params.lavafels,
            "volcanoes_small": params.vulkane[0], "volcanoes_medium": params.vulkane[1],
            "volcanoes_large": params.vulkane[2],
            "craters": params.krater, "cracks": params.risse, "debris": params.truemmer,
            "gradient": _VERLAEUFE.index(params.verlauf) + 1 if params.verlauf in _VERLAEUFE else 0,
            "gradient_ground_start": _VERLAUF_BODEN.get(params.verlauf_boden[0], -1),
            "gradient_ground_end": _VERLAUF_BODEN.get(params.verlauf_boden[1], -1),
            "gradient_terrain_start": params.verlauf_gelaende[0],
            "gradient_terrain_end": params.verlauf_gelaende[1],
        })
    for k, v in werte.items():
        gen.set(k, v)
    gen.set("seed", int(params.seed) & 0xFFFFFFFFFFFFFFFF)
    gen.set_mix({k: float(v) for k, v in params.mix.items() if v > 0} or {"mud": 1.0})
    if not gelernt:
        for f in params.features:
            if f.kind in _MERKMALE:
                gen.add_feature(_MERKMALE[f.kind], f.where or "", f.to or "", float(f.size), bool(f.lava))
    return gen


def _ergebnis(r, params):
    """Ergebnis der Bibliothek -> mapgen.GeneratedMap. Library result -> GeneratedMap."""
    import mapgen
    p = profil()
    h, w = r.height, r.width
    st = r.stats
    anteile = {p.ground_id(g): s for g, s in enumerate(r.ground_shares) if s > 0}
    zonen = {}
    if st["mountains"] or st["plateaus"]:
        zonen = {"berge": int(st["mountains"]), "hochebenen": int(st["plateaus"]),
                 "schluchten": int(st["gorges"]), "durchfahrbar": int(st["gorges_passable"]),
                 "undicht": int(st["mountains_leaky"]), "unerreichbar": int(st["plateaus_unreachable"]),
                 "bauplatz": float(st["build"])}
    return mapgen.GeneratedMap(
        tiles=np.array(r.tiles, dtype=np.int32).reshape(h, w),
        cells=np.array(r.cell_types, dtype=np.uint8).reshape(h, w),
        spawns=[tuple(s) for s in r.spawns],
        passable_share=st["passable"],
        family_share=anteile,
        connected=bool(st["connected"]),
        volcanoes=[tuple(v) for v in r.volcanoes],
        lava_zones=[[tuple(c) for c in z] for z in r.lava_zones],
        plateau_share=st["plateau"],
        detail_share=st["details"],
        features={_MERKMAL_NAME[k]: n for k, n in enumerate(r.feature_report)},
        feature_spots=[(_MERKMAL_NAME.get(k, str(k)), x, y, s) for k, x, y, s in r.features],
        fluss_share=st["rivers"],
        zonen=zonen,
    )


# ---------------------------------------------------------------------------
# Gelernter Generator / learned generator

def modell():
    """Die Netze des gelernten Generators (profiles/op2-net.bin) oder None. Einmalig geladen."""
    if "modell" not in _zustand:
        m = None
        try:
            if verfuegbar() and hasattr(modul(), "LearnedModel"):
                datei = appconfig.op2maplib_dir() / "profiles" / "op2-net.bin"
                m = modul().LearnedModel.from_file(datei)
        except Exception as e:
            print("Gelernter Generator nicht verfuegbar:", f"{type(e).__name__}: {e}")
            m = None
        _zustand["modell"] = m
    return _zustand["modell"]


def gelernt_verfuegbar() -> bool:
    """Kann der gelernte Generator laufen (Bibliothek mit Generator und Netzdatei)?"""
    return modell() is not None


def threads_vorgabe() -> int:
    """Rechenthreads ohne eigene Einstellung: die Haelfte der Kerne, hoechstens 8."""
    return max(1, min(8, (os.cpu_count() or 4) // 2))


class Abgebrochen(Exception):
    """Die Rechnung wurde abgebrochen. The computation was cancelled."""


class Skizze:
    """Die Skizze einer gelernten Karte auf halber Aufloesung: Waende (0 keine,
    1..8 Fallrichtung O..NO) und Boeden (0 Erde, 1 Fels, 2 Sand, 3 Bewuchs, 4 sonst).
    The sketch of a learned map at half resolution."""
    def __init__(self, wand: np.ndarray, boden: np.ndarray):
        self.wand, self.boden = wand, boden


def _gelernt(params, qualitaet: int, threads: int, fortschritt, abbruch):
    m = modell()
    if m is None:
        raise RuntimeError(fehlt_text())
    om = modul()

    def melde(anteil):
        if abbruch is not None and abbruch():
            return False
        if fortschritt is not None:
            fortschritt(float(anteil))
        return True
    try:
        return _einstellungen(params, gelernt=True).generate_learned(
            profil(), m, qualitaet, int(threads), melde)
    except om.Op2MapLibError as e:
        if abbruch is not None and abbruch():
            raise Abgebrochen from e
        raise


def skizze(params, threads: int = 0, abbruch=None) -> Skizze:
    """Nur die Skizze (etwa eine Sekunde), fuer die Sofortvorschau."""
    r = _gelernt(params, modul().LearnedQuality.SKETCH, threads, None, abbruch)
    form = (r.sketch_height, r.sketch_width)
    return Skizze(np.array(r.sketch_walls, np.uint8).reshape(form),
                  np.array(r.sketch_grounds, np.uint8).reshape(form))


def generieren_gelernt(params, stufe: str = "schnell", threads: int = 0,
                       fortschritt=None, abbruch=None):
    """Karte mit dem gelernten Generator -> mapgen.GeneratedMap.
    `stufe`: "schnell" oder "gut"; `fortschritt(anteil)`, `abbruch()` -> True bricht ab."""
    q = modul().LearnedQuality
    r = _gelernt(params, q.GOOD if stufe == "gut" else q.FAST, threads, fortschritt, abbruch)
    return _ergebnis(r, params)


_FARBEN = np.array([(118, 110, 92), (74, 80, 84), (196, 110, 20), (96, 104, 74),
                    (118, 110, 92)], np.uint8)


def skizzenbild(sk: Skizze) -> np.ndarray:
    """Vorschaubild der Skizze (h/2, w/2, 3). Preview image of the sketch."""
    bild = _FARBEN[np.minimum(sk.boden, 4)].copy()
    bild[sk.wand > 0] = (34, 28, 20)
    bild[np.isin(sk.wand, (6, 7, 8))] = (66, 58, 46)
    return bild


def boden_feld(bm, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Boden der Bibliothek je Zelle im Rechteck (inklusive) -> (h, w), -1 = fest."""
    return np.array([[bm.ground_at(x, y) for x in range(x0, x1 + 1)]
                     for y in range(y0, y1 + 1)], dtype=np.int16)
