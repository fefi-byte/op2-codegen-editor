from __future__ import annotations
from .common import *


class PlacedObject:
    """
    Ein auf der Karte platziertes Objekt: ``kind`` bestimmt den Typ
    (structure/vehicle/beacon/wall), ``tile_x``/``tile_y`` sind die Kachel-
    Koordinaten, ``footprint`` die Grundflaeche (Breite, Hoehe in Kacheln),
    ``player`` der Besitzer, ``params`` ein Dictionary mit zusaetzlichen
    Eigenschaften, ``uid`` ein eindeutiger Bezeichner und ``unit_name`` ein
    optionaler Anzeigename der Einheit.

    An object placed on the map: ``kind`` selects the type
    (structure/vehicle/beacon/wall), ``tile_x``/``tile_y`` are the tile
    coordinates, ``footprint`` is the footprint (width, height in tiles),
    ``player`` is the owner, ``params`` a dict of extra properties, ``uid`` a
    unique identifier and ``unit_name`` an optional unit display name.
    """
    def __init__(self, kind, tx, ty, map_id, footprint, display, player, params, uid="", unit_name=""):
        self.kind = kind
        self.tile_x = tx
        self.tile_y = ty
        self.map_id = map_id
        self.footprint = footprint
        self.display = display
        self.player = player
        self.params = params
        self.uid = uid
        self.unit_name = unit_name
        self.items = []

    def covers(self, tx, ty):
        """
        Trefferpruefung anhand der Grundflaeche: liefert ``True``, wenn die
        Kachel (``tx``, ``ty``) innerhalb des um ``tile_x``/``tile_y``
        zentrierten Footprints liegt.

        Footprint-based hit-test: returns ``True`` if tile (``tx``, ``ty``)
        lies within the footprint centered on ``tile_x``/``tile_y``.
        """
        fw, fh = self.footprint
        x0, y0 = self.tile_x - fw // 2, self.tile_y - fh // 2
        return x0 <= tx < x0 + fw and y0 <= ty < y0 + fh

    def to_dict(self):
        """
        Serialisiert das Objekt fuer das Speichern in der .op2proj-Datei (JSON).

        Serializes the object for JSON storage in the .op2proj save file.
        """
        return {"kind": self.kind, "tile_x": self.tile_x, "tile_y": self.tile_y,
                "map_id": self.map_id, "footprint": list(self.footprint),
                "display": self.display, "player": self.player, "params": self.params,
                "uid": self.uid, "unit_name": self.unit_name}

    @classmethod
    def from_dict(cls, d):
        """
        Rekonstruiert ein ``PlacedObject`` aus einem JSON-Dictionary, wie es
        aus der .op2proj-Datei geladen wird (Gegenstueck zu ``to_dict``).

        Reconstructs a ``PlacedObject`` from a JSON dict loaded from the
        .op2proj file (inverse of ``to_dict``).
        """
        return cls(d["kind"], d["tile_x"], d["tile_y"], d["map_id"],
                   tuple(d["footprint"]), d["display"], d["player"], d.get("params", {}),
                   d.get("uid", ""), d.get("unit_name", ""))


