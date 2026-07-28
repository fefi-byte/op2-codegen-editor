"""Zelltypen (Befahrbarkeit) einer Outpost-2-Karte -- Engine-Konvention.

Die Werte stammen aus `Outpost2DLL/game/NonExportedEnums.h` (enum CellTypes);
die Geschwindigkeitsklassen sind die des Spiels, NICHT frei gewaehlt: Fels ist
schnell, Erde mittel, Lavafels langsam bis mittel.

`DEFAULT_CELL_TYPES` bildet einen tileMappingIndex auf den Zelltyp ab, den die
Original-Designer dort ueblicherweise gesetzt haben (aus allen mitgelieferten
Karten gelernt, siehe learn_celltypes.py). Damit kann ein Editor beim Malen
die Befahrbarkeit passend mitsetzen, ohne dass der Nutzer sie kennen muss.

Cell types (passability) of an Outpost 2 map -- engine convention, taken from
the SDK's CellTypes enum. DEFAULT_CELL_TYPES maps a tile mapping index to the
cell type the original designers usually paired it with (learned from the
shipped maps).
"""
from __future__ import annotations

import json
from pathlib import Path

# --- Enum aus dem SDK / enum from the SDK ---------------------------------
FAST_PASSIBLE_1 = 0      # Fels mit Bewuchs / rock vegetation
IMPASSIBLE_2 = 1         # Krater, Spalten / meteor craters, crevasses
SLOW_PASSIBLE_1 = 2      # Lavafels dunkel / lava rock (dark)
SLOW_PASSIBLE_2 = 3      # Riffel-Erde, Lavabuckel / rippled dirt, lava bumps
MEDIUM_PASSIBLE_1 = 4    # Erde / dirt
MEDIUM_PASSIBLE_2 = 5    # Lavafels / lava rock
IMPASSIBLE_1 = 6         # Huegel, Eis, Vulkan / mounds, ice, volcano
FAST_PASSIBLE_2 = 7      # Fels / rock
NORTH_CLIFFS = 8
CLIFFS_HIGH_SIDE = 9
CLIFFS_LOW_SIDE = 10
VENTS_AND_FUMAROLES = 11  # nur GeoCons / GeoCons only
DOZED_AREA = 21
RUBBLE = 22
NORMAL_WALL = 23
MICROBE_WALL = 24
LAVA_WALL = 25
TUBE_0 = 26

# Geschwindigkeitsklasse je Zelltyp / speed class per cell type
FAST, MEDIUM, SLOW, IMPASSABLE, CLIFF, SPECIAL = (
    "fast", "medium", "slow", "impassable", "cliff", "special")

SPEED_CLASS: dict[int, str] = {
    FAST_PASSIBLE_1: FAST,
    FAST_PASSIBLE_2: FAST,
    MEDIUM_PASSIBLE_1: MEDIUM,
    MEDIUM_PASSIBLE_2: MEDIUM,
    SLOW_PASSIBLE_1: SLOW,
    SLOW_PASSIBLE_2: SLOW,
    IMPASSIBLE_1: IMPASSABLE,
    IMPASSIBLE_2: IMPASSABLE,
    NORTH_CLIFFS: CLIFF,
    CLIFFS_HIGH_SIDE: CLIFF,
    CLIFFS_LOW_SIDE: CLIFF,
    VENTS_AND_FUMAROLES: SPECIAL,
    DOZED_AREA: FAST,
    RUBBLE: SLOW,
    NORMAL_WALL: IMPASSABLE,
    MICROBE_WALL: IMPASSABLE,
    LAVA_WALL: IMPASSABLE,
    TUBE_0: FAST,
}

# Kurzbezeichnungen fuer die Oberflaeche / short labels for the UI
CELL_TYPE_NAMES: dict[int, str] = {
    FAST_PASSIBLE_1: "Fels bewachsen (schnell)",
    IMPASSIBLE_2: "Krater/Spalte (unpassierbar)",
    SLOW_PASSIBLE_1: "Lavafels dunkel (langsam)",
    SLOW_PASSIBLE_2: "Riffel/Lavabuckel (langsam)",
    MEDIUM_PASSIBLE_1: "Erde (mittel)",
    MEDIUM_PASSIBLE_2: "Lavafels (mittel)",
    IMPASSIBLE_1: "Huegel/Eis/Vulkan (unpassierbar)",
    FAST_PASSIBLE_2: "Fels (schnell)",
    NORTH_CLIFFS: "Klippe Nordkante",
    CLIFFS_HIGH_SIDE: "Klippe Oberseite",
    CLIFFS_LOW_SIDE: "Klippe Unterseite",
    VENTS_AND_FUMAROLES: "Fumarole (nur GeoCon)",
    DOZED_AREA: "planiert",
    RUBBLE: "Schutt",
    NORMAL_WALL: "Mauer",
    MICROBE_WALL: "Mikroben-Mauer",
    LAVA_WALL: "Lava-Mauer",
    TUBE_0: "Tube/Gebaeudegrund",
}

# Zelltypen, die in Kartendateien vorkommen (der Rest ist Laufzeitzustand).
# Cell types that occur in map files (the rest is runtime state).
EDITABLE_CELL_TYPES = [
    FAST_PASSIBLE_2, FAST_PASSIBLE_1, MEDIUM_PASSIBLE_1, MEDIUM_PASSIBLE_2,
    SLOW_PASSIBLE_1, SLOW_PASSIBLE_2, IMPASSIBLE_1, IMPASSIBLE_2,
    NORTH_CLIFFS, CLIFFS_HIGH_SIDE, CLIFFS_LOW_SIDE, VENTS_AND_FUMAROLES,
]

_TABLE_PATH = Path(__file__).with_name("celltypes.json")
_table: dict | None = None


def _load() -> dict:
    global _table
    if _table is None:
        try:
            _table = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _table = {"default": {}, "meta": {}}
    return _table


def default_cell_type(mapping_index: int, fallback: int = MEDIUM_PASSIBLE_1) -> int | None:
    """Ueblicher Zelltyp fuer eine Kachelgrafik (gelernt aus den Originalkarten).

    Usual cell type for a tile graphic (learned from the original maps)."""
    return _load()["default"].get(str(mapping_index), fallback)


def default_confidence(mapping_index: int) -> float:
    """Anteil der Originalzellen, die diesen Zelltyp benutzen (0..1).

    Share of original cells using that cell type (0..1)."""
    return _load().get("confidence", {}).get(str(mapping_index), 0.0)


def speed_class(cell_type: int) -> str:
    return SPEED_CLASS.get(cell_type, SPECIAL)


def cell_type_name(cell_type: int) -> str:
    return CELL_TYPE_NAMES.get(cell_type, f"Zelltyp {cell_type}")
