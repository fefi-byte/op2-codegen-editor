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


def boden_feld(bm, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Boden der Bibliothek je Zelle im Rechteck (inklusive) -> (h, w), -1 = fest."""
    return np.array([[bm.ground_at(x, y) for x in range(x0, x1 + 1)]
                     for y in range(y0, y1 + 1)], dtype=np.int16)
