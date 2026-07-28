"""Reader UND Writer fuer Outpost-2 .map-Dateien.

Das Layout wurde empirisch an allen 135 mitgelieferten Karten verifiziert
(133 parsen byte-exakt bis zum Dateiende; zwei Altkarten aus OPU/backups
haben ueberzaehlige TileGroups hinter dem Zaehler -- die werden als
`trailing` mitgefuehrt, damit auch sie unveraendert zurueckgeschrieben
werden koennen).

Layout:
  MapHeader (20 B): versionTag u32, bSavedGame i32, lgWidth u32, height u32,
                    tilesetCount u32          (Breite = 1 << lgWidth)
  tiles:            width*height * u32 (Bitfeld, siehe unten)
  clipRect:         4 * i32
  tilesetSources:   pro Tileset: len u32, name[len], (falls len>0) numTiles u32
  "TILE SET\x1a\0"  10 B
  tileMappings:     count u32, dann count * 8 B
                    (tilesetIndex u16, tileGraphicIndex u16, animCount u16, animDelay u16)
  terrainTypes:     count u32, dann count * 264 B (Innenaufbau unbekannt,
                    wird als Rohblock durchgereicht)
  versionTags:      2 * u32 (beide == Header-versionTag)
  tileGroups:       count u32, ein zweiter u32 (mal count-1, mal 0), dann je Gruppe:
                    w u32, h u32, mappingIndices[w*h] u32, nameLen u32, name[nameLen]

Kachel-Bitfeld (siehe HFL `MapTile`):
  Bits  0-4   cellType        (Befahrbarkeit -- siehe celltypes.py)
  Bits  5-15  tileMappingIndex (welche Grafik)
  Bits 16-26  unitIndex        (Laufzeit, in Dateien immer 0)
  Bits 27-31  lava/lavaPossible/expand/microbe/wallOrBuilding
                               (Laufzeit, in Dateien immer 0)

Reader AND writer for Outpost 2 .map files; the layout was verified against
all 135 shipped maps. Only bits 0-15 of a tile are used on disk -- the upper
bits are runtime state and are always zero in files.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# Groesse eines terrainTypes-Eintrags (empirisch: Luecke / Anzahl, ueber alle
# Karten konstant). Der Inhalt wird nicht interpretiert.
# Size of one terrainTypes record (empirical, constant across all maps). Its
# content is not interpreted.
TERRAIN_TYPE_SIZE = 264

TILE_SET_MARKER = b"TILE SET\x1a\x00"

CELL_TYPE_BITS = 5
CELL_TYPE_MASK = 0x1F
MAPPING_INDEX_MASK = 0x7FF


def _decode(raw: bytes) -> str:
    return raw.decode("ascii", "replace")


def _encode(text: str, raw: bytes | None) -> bytes:
    """Rohbytes bevorzugen -- manche Karten enthalten Namen, die kein sauberes
    ASCII sind; nur so bleibt das Zurueckschreiben byte-identisch.

    Prefer the raw bytes -- some maps contain names that are not clean ASCII;
    only this keeps writing byte-identical."""
    if raw is not None and _decode(raw) == text:
        return raw
    return text.encode("ascii", "replace")


@dataclass
class TilesetSource:
    filename: str   # z.B. "well0001" / e.g. "well0001"
    num_tiles: int
    filename_raw: bytes | None = None


@dataclass
class TileMapping:
    tileset_index: int
    tile_graphic_index: int
    animation_count: int
    animation_delay: int


@dataclass
class TileGroup:
    """Benannter Kachel-Stempel aus der Karte (die Pinsel des Originaleditors).

    Named tile stamp stored in the map (the original editor's brushes)."""
    name: str
    width: int
    height: int
    mapping_indices: list[int] = field(default_factory=list)
    name_raw: bytes | None = None

    def index_at(self, x: int, y: int) -> int:
        return self.mapping_indices[y * self.width + x]


class Op2Map:
    def __init__(self, data: bytes):
        self._buf = data
        self._pos = 0
        self._read()

    # ------------------------------------------------------------------
    # Lesen / reading

    def _u32(self) -> int:
        v = struct.unpack_from("<I", self._buf, self._pos)[0]
        self._pos += 4
        return v

    def _read(self) -> None:
        (self.version_tag, b_saved, self.lg_width, self.height,
         self.tileset_count) = struct.unpack_from("<IiIII", self._buf, 0)
        self._pos = 20
        self.is_saved_game = bool(b_saved)
        self._b_saved_game = b_saved
        self.width = 1 << self.lg_width
        tile_count = self.height * self.width

        self.tiles = list(struct.unpack_from(f"<{tile_count}I", self._buf, self._pos))
        self._pos += tile_count * 4

        self.clip_rect = struct.unpack_from("<4i", self._buf, self._pos)
        self._pos += 16

        self.tileset_sources: list[TilesetSource] = []
        for _ in range(self.tileset_count):
            ln = self._u32()
            raw = self._buf[self._pos:self._pos + ln]
            self._pos += ln
            # Leere Eintraege (len == 0) haben KEIN numTiles-Feld.
            # Empty entries (len == 0) carry NO numTiles field.
            num = self._u32() if ln > 0 else 0
            self.tileset_sources.append(TilesetSource(_decode(raw), num, raw))

        marker = self._buf[self._pos:self._pos + 10]
        self._pos += 10
        if marker != TILE_SET_MARKER:
            raise ValueError(f"'TILE SET'-Marker nicht gefunden, stattdessen {marker!r}")

        count = self._u32()
        self.tile_mappings: list[TileMapping] = []
        for _ in range(count):
            ts, gfx, ac, ad = struct.unpack_from("<4H", self._buf, self._pos)
            self._pos += 8
            self.tile_mappings.append(TileMapping(ts, gfx, ac, ad))

        # terrainTypes: undurchsichtige Bloecke, 1:1 durchgereicht.
        # terrainTypes: opaque blocks, passed through verbatim.
        count = self._u32()
        self.terrain_types: list[bytes] = []
        for _ in range(count):
            self.terrain_types.append(self._buf[self._pos:self._pos + TERRAIN_TYPE_SIZE])
            self._pos += TERRAIN_TYPE_SIZE

        self.version_tags = struct.unpack_from("<2I", self._buf, self._pos)
        self._pos += 8

        group_count = self._u32()
        # Zweites Feld: in manchen Karten count-1, in anderen 0 -- beides wird
        # vom Spiel akzeptiert, also unveraendert uebernehmen.
        # Second field: count-1 in some maps, 0 in others -- the game accepts
        # both, so keep whatever was there.
        self.tile_group_second = self._u32()
        self.tile_groups: list[TileGroup] = []
        for _ in range(group_count):
            gw, gh = struct.unpack_from("<II", self._buf, self._pos)
            self._pos += 8
            n = gw * gh
            idx = list(struct.unpack_from(f"<{n}I", self._buf, self._pos))
            self._pos += n * 4
            ln = self._u32()
            raw = self._buf[self._pos:self._pos + ln]
            self._pos += ln
            self.tile_groups.append(TileGroup(_decode(raw), gw, gh, idx, raw))

        # Zwei Altkarten haben ueberzaehlige Saetze hinter dem Zaehler.
        # Two legacy maps carry surplus records behind the counter.
        self.trailing = self._buf[self._pos:]

    # ------------------------------------------------------------------
    # Schreiben / writing

    def to_bytes(self) -> bytes:
        """Serialisiert die Karte wieder in das .map-Format.

        Unveraendert eingelesene Karten kommen byte-identisch heraus
        (siehe mapview/tests/map_roundtrip.py).

        Serialises the map back into the .map format; an unmodified map comes
        out byte-identical."""
        out = bytearray()
        out += struct.pack("<IiIII", self.version_tag, self._b_saved_game,
                           self.lg_width, self.height, len(self.tileset_sources))
        out += struct.pack(f"<{len(self.tiles)}I", *self.tiles)
        out += struct.pack("<4i", *self.clip_rect)
        for src in self.tileset_sources:
            raw = _encode(src.filename, src.filename_raw)
            out += struct.pack("<I", len(raw))
            out += raw
            if raw:
                out += struct.pack("<I", src.num_tiles)
        out += TILE_SET_MARKER
        out += struct.pack("<I", len(self.tile_mappings))
        for m in self.tile_mappings:
            out += struct.pack("<4H", m.tileset_index, m.tile_graphic_index,
                               m.animation_count, m.animation_delay)
        out += struct.pack("<I", len(self.terrain_types))
        for block in self.terrain_types:
            out += block
        out += struct.pack("<2I", *self.version_tags)
        out += struct.pack("<2I", len(self.tile_groups), self.tile_group_second)
        for g in self.tile_groups:
            out += struct.pack("<II", g.width, g.height)
            out += struct.pack(f"<{len(g.mapping_indices)}I", *g.mapping_indices)
            raw = _encode(g.name, g.name_raw)
            out += struct.pack("<I", len(raw))
            out += raw
        out += self.trailing
        return bytes(out)

    def save(self, path) -> None:
        from pathlib import Path
        Path(path).write_bytes(self.to_bytes())

    # ------------------------------------------------------------------
    # Zellzugriff / cell access

    def tile_index(self, x: int, y: int) -> int:
        # OP2 speichert Tiles in vertikalen 32-Spalten-Streifen (Map::GetTileIndex):
        # OP2 stores tiles in vertical 32-column strips (Map::GetTileIndex):
        #   index = (upperX * height + y) * 32 + lowerX
        lower_x = x & 0x1F
        upper_x = x >> 5
        return (upper_x * self.height + y) * 32 + lower_x

    def tile_mapping_index(self, x: int, y: int) -> int:
        return (self.tiles[self.tile_index(x, y)] >> CELL_TYPE_BITS) & MAPPING_INDEX_MASK

    def cell_type(self, x: int, y: int) -> int:
        """Befahrbarkeit der Zelle (CellTypes-Enum, siehe celltypes.py).

        Passability of the cell (CellTypes enum, see celltypes.py)."""
        return self.tiles[self.tile_index(x, y)] & CELL_TYPE_MASK

    def set_cell_type(self, x: int, y: int, cell_type: int) -> None:
        i = self.tile_index(x, y)
        self.tiles[i] = (self.tiles[i] & ~CELL_TYPE_MASK) | (cell_type & CELL_TYPE_MASK)

    def set_tile_mapping_index(self, x: int, y: int, mapping_index: int) -> None:
        i = self.tile_index(x, y)
        keep = self.tiles[i] & ~(MAPPING_INDEX_MASK << CELL_TYPE_BITS)
        self.tiles[i] = keep | ((mapping_index & MAPPING_INDEX_MASK) << CELL_TYPE_BITS)

    def set_tile(self, x: int, y: int, mapping_index: int, cell_type: int) -> None:
        """Grafik und Befahrbarkeit in einem Rutsch setzen (alles andere bleibt).

        Set graphic and passability in one go (everything else is preserved)."""
        i = self.tile_index(x, y)
        upper = self.tiles[i] & ~0xFFFF          # unitIndex/lava/... unangetastet
        self.tiles[i] = (upper
                         | ((mapping_index & MAPPING_INDEX_MASK) << CELL_TYPE_BITS)
                         | (cell_type & CELL_TYPE_MASK))

    def tileset_and_graphic(self, x: int, y: int) -> tuple[int, int]:
        """Gibt (tileset_index, tile_graphic_index) fuer eine Zelle zurueck.

        Returns (tileset index, graphic index) for a cell."""
        m = self.tile_mappings[self.tile_mapping_index(x, y)]
        return m.tileset_index, m.tile_graphic_index

    def group_by_name(self, name: str) -> TileGroup | None:
        for g in self.tile_groups:
            if g.name == name:
                return g
        return None


if __name__ == "__main__":
    import sys
    from vol import VolFile

    src = sys.argv[1]
    if src.lower().endswith(".vol"):
        data = VolFile(src).read_file(sys.argv[2])
    else:
        data = open(src, "rb").read()

    m = Op2Map(data)
    print(f"Version: 0x{m.version_tag:X}  SavedGame={m.is_saved_game}")
    print(f"Groesse: {m.width} x {m.height} Tiles  ({len(m.tiles)} Zellen)")
    print(f"Tilesets ({m.tileset_count}):")
    for i, ts in enumerate(m.tileset_sources):
        if ts.filename:
            print(f"  [{i}] {ts.filename}  ({ts.num_tiles} Tiles)")
    print(f"TileMappings: {len(m.tile_mappings)}")
    print(f"terrainTypes: {len(m.terrain_types)} x {TERRAIN_TYPE_SIZE} B")
    print(f"TileGroups:   {len(m.tile_groups)}  z.B. "
          f"{[g.name for g in m.tile_groups[:6]]}")
    print(f"Beispiel Zelle (10,10): tileset/gfx = {m.tileset_and_graphic(10, 10)}, "
          f"cellType = {m.cell_type(10, 10)}")
    print(f"Roundtrip byte-identisch: {m.to_bytes() == data}")
