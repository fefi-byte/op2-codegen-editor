"""Boeden und Kacheln aus dem Profil von OP2MappingLib.

Der Editor muss fuer einige Dinge wissen, zu welchem Boden eine Kachel
gehoert: die Malebene einer geladenen Karte zurueckgewinnen, die Kachelpalette
nach Boeden ordnen, ein Detailpaket einem Boden zuschlagen, einen Vulkan
stempeln. Frueher kam das aus dem Python-Kachelmodell (TileModel).
Jetzt kommt es aus dem Profil, mit dem auch die Bibliothek malt
(`profiles/op2.json`) -- so sehen Editor und Bibliothek dieselben Boeden.

Kacheln, die das Profil nicht nennt (Lava-Animationen, seltene Klippenstuecke),
bekommen den Grundboden ihres Tilesets, wie in den Originalkarten.

Grounds and tiles from OP2MappingLib's profile. The editor needs a tile's
ground in a few places (recovering the paint layer of a loaded map, sorting
the tile palette, packages, the volcano stamp). It used to come from the
Python tile model; now it comes from the same profile the library paints with,
so editor and library agree. Tiles the profile does not list get their
tileset's base ground, as in the original maps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from . import maplib

# Grundboden je Standard-Tileset der Originale (well0001..well0012). well0010
# traegt nur Sonderkacheln und bekommt keinen.
# Base ground per standard tileset of the originals; well0010 has none.
TILESET_BODEN = {1: "mud", 2: "mud", 3: "mud", 4: "roc", 5: "roc", 6: "roc", 7: "roc",
                 8: "san", 9: "san", 11: "sno", 12: "sno"}

ANZAHL = 2048           # Kachelindizes einer Karte / mapping indices of a map


@dataclass
class Vulkan:
    name: str
    breite: int
    hoehe: int
    kacheln: np.ndarray     # (hoehe, breite) Kachelindizes
    zelltypen: np.ndarray   # (hoehe, breite)


class Boeden:
    """Boeden des Profils und die Zuordnung Kachel -> Boden."""

    def __init__(self, profil_json: dict, profil):
        self.families: list[str] = [profil.ground_id(g) for g in range(profil.ground_count)]
        self._fuell = [profil.ground_fill_count(g) for g in range(profil.ground_count)]
        index = {tuple(v): i for i, v in enumerate(profil_json["standardMapping"])}
        n = max(ANZAHL, len(index))
        self.family_of = np.full(n, -1, dtype=np.int16)
        self.ist_uebergang = np.zeros(n, dtype=bool)
        self.lava = np.zeros(n, dtype=bool)
        self.usage: dict[int, int] = {}
        self.trans: dict[tuple[str, str], list[int]] = {}
        fam = {f: i for i, f in enumerate(self.families)}

        for i, (ts, _img) in enumerate(profil_json["standardMapping"]):
            b = TILESET_BODEN.get(int(ts))
            if b in fam:
                self.family_of[i] = fam[b]

        def setze(ts, img, boden):
            i = index.get((int(ts), int(img)))
            if i is not None and boden in fam:
                self.family_of[i] = fam[boden]
            return i

        for t in profil_json.get("cliffs", {}).get("tiles", []):
            setze(t["ts"], t["img"], t.get("family"))
        gen = profil_json.get("generator", {})
        for art in ("details", "decorations"):
            for s in gen.get(art, []):
                for ts, img, _zt in s["tiles"]:
                    setze(ts, img, s.get("ground"))
        for t in profil_json["tiles"]:
            i = index.get((int(t["ts"]), int(t["img"])))
            if i is None:
                continue
            if t.get("w"):
                self.usage[i] = int(t["w"])
            if t["role"] == "transition":
                self.ist_uebergang[i] = True
                self.family_of[i] = -1
                self.trans.setdefault((t["a"], t["b"]), []).append(i)
            else:
                setze(t["ts"], t["img"], t.get("ground"))
                if t.get("ground") == "lav":
                    self.lava[i] = True

        self.volcanoes: list[Vulkan] = []
        for v in gen.get("volcanoes", []):
            w, h = int(v["w"]), int(v["h"])
            k = np.array([index.get((ts, img), 0) for ts, img, _zt in v["tiles"]], dtype=np.int32)
            z = np.array([zt for _ts, _img, zt in v["tiles"]], dtype=np.int32)
            self.lava[k] = True
            self.volcanoes.append(Vulkan(v["name"], w, h, k.reshape(h, w), z.reshape(h, w)))

    def familie_nutzbar(self, f: int) -> bool:
        """Kann der Pinsel diesen Boden malen (hat er Fuellkacheln)?"""
        return 0 <= f < len(self._fuell) and self._fuell[f] > 0

    def familie(self, kachel: int) -> str:
        """Bodenname einer Kachel oder "" (Uebergang, unbekannt)."""
        f = int(self.family_of[kachel]) if 0 <= kachel < len(self.family_of) else -1
        return self.families[f] if 0 <= f < len(self.families) else ""


_zwischen: dict = {}


def boeden() -> Boeden:
    """Die Boeden des geladenen Profils. RuntimeError ohne OP2MappingLib."""
    if "b" not in _zwischen:
        if not maplib.verfuegbar():
            raise RuntimeError(maplib.fehlt_text())
        pfad = maplib.profil_pfad()
        _zwischen["b"] = Boeden(json.loads(pfad.read_text(encoding="utf-8")), maplib.profil())
    return _zwischen["b"]
