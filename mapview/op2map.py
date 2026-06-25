"""Reader fuer Outpost-2 .map-Dateien (aus OP2Utility/src/Map nachgebaut).

Layout:
  MapHeader (20 B): versionTag u32, bSavedGame i32, lgWidth u32, height u32, tilesetCount u32
  tiles:        TileCount * u32  (Bitfeld; tileMappingIndex = (tile>>5) & 0x7FF)
  clipRect:     4 * i32
  tilesetSources: pro Tileset: len u32, name[len], (falls len>0) numTiles u32
  "TILE SET\x1a" (10 B)
  tileMappings: count u32, dann count * 8 B (tilesetIndex u16, tileGraphicIndex u16, animCount u16, animDelay u16)
  ... (terrainTypes, versionTags, tileGroups -- fuer Rendering nicht noetig)

Reader for Outpost-2 .map files (reimplemented from OP2Utility/src/Map).

Layout:
  MapHeader (20 B): versionTag u32, bSavedGame i32, lgWidth u32, height u32, tilesetCount u32
  tiles:        TileCount * u32  (bitfield; tileMappingIndex = (tile>>5) & 0x7FF)
  clipRect:     4 * i32
  tilesetSources: per tileset: len u32, name[len], (if len>0) numTiles u32
  "TILE SET\x1a" (10 B)
  tileMappings: count u32, then count * 8 B (tilesetIndex u16, tileGraphicIndex u16, animCount u16, animDelay u16)
  ... (terrainTypes, versionTags, tileGroups -- not needed for rendering)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class TilesetSource:
    filename: str   # z.B. "well0001"
    # e.g. "well0001"
    num_tiles: int


@dataclass
class TileMapping:
    tileset_index: int
    tile_graphic_index: int
    animation_count: int
    animation_delay: int


class Op2Map:
    def __init__(self, data: bytes):
        self._buf = data
        self._pos = 0
        self._read()

    def _read(self) -> None:
        (self.version_tag, b_saved, lg_width, self.height,
         self.tileset_count) = struct.unpack_from("<IiIII", self._buf, 0)
        self._pos = 20
        self.is_saved_game = bool(b_saved)
        self.width = 1 << lg_width
        tile_count = self.height * self.width

        # Tiles
        # Tiles
        self.tiles = list(struct.unpack_from(f"<{tile_count}I", self._buf, self._pos))
        self._pos += tile_count * 4

        # clipRect (4 * i32)
        # clipRect (4 * i32)
        self.clip_rect = struct.unpack_from("<4i", self._buf, self._pos)
        self._pos += 16

        # Tileset-Quellen
        # Tileset sources
        self.tileset_sources: list[TilesetSource] = []
        for _ in range(self.tileset_count):
            ln = struct.unpack_from("<I", self._buf, self._pos)[0]
            self._pos += 4
            name = self._buf[self._pos:self._pos + ln].decode("ascii", "replace")
            self._pos += ln
            num = 0
            if ln > 0:
                num = struct.unpack_from("<I", self._buf, self._pos)[0]
                self._pos += 4
            self.tileset_sources.append(TilesetSource(name, num))

        # "TILE SET\x1a"
        # "TILE SET\x1a"
        header = self._buf[self._pos:self._pos + 10]
        self._pos += 10
        if header != b"TILE SET\x1a\x00":
            raise ValueError(f"'TILE SET'-Marker nicht gefunden, stattdessen {header!r}")

        # TileMappings
        # TileMappings
        count = struct.unpack_from("<I", self._buf, self._pos)[0]
        self._pos += 4
        self.tile_mappings: list[TileMapping] = []
        for _ in range(count):
            ts, gfx, ac, ad = struct.unpack_from("<4H", self._buf, self._pos)
            self._pos += 8
            self.tile_mappings.append(TileMapping(ts, gfx, ac, ad))

    # --- Render-Hilfen ---
    # --- Render helpers ---
    def tile_index(self, x: int, y: int) -> int:
        # OP2 speichert Tiles in vertikalen 32-Spalten-Streifen (siehe Map::GetTileIndex):
        # OP2 stores tiles in vertical 32-column strips (see Map::GetTileIndex):
        #   index = (upperX * height + y) * 32 + lowerX
        #   index = (upperX * height + y) * 32 + lowerX
        # lowerX = die unteren 5 Bits von x (Position innerhalb des 32er-Streifens),
        #          upperX = x >> 5 (welcher Streifen).
        # lowerX = the low 5 bits of x (position within the 32-column strip),
        #          upperX = x >> 5 (which strip).
        lower_x = x & 0x1F
        upper_x = x >> 5
        return (upper_x * self.height + y) * 32 + lower_x

    def tile_mapping_index(self, x: int, y: int) -> int:
        # Das Tile-Wort ist ein Bitfeld; die Bits [5:16] = (tile>>5)&0x7FF
        # enthalten den 11-Bit-Tile-Mapping-Index.
        # The tile word is a bitfield; bits [5:16] = (tile>>5)&0x7FF
        # hold the 11-bit tile-mapping index.
        tile = self.tiles[self.tile_index(x, y)]
        return (tile >> 5) & 0x7FF

    def tileset_and_graphic(self, x: int, y: int) -> tuple[int, int]:
        """Gibt (tileset_index, tile_graphic_index) fuer eine Zelle zurueck.

        Returns (tileset_index, tile_graphic_index) for a cell. Der ueber
        tile_mapping_index() gewonnene 11-Bit-Index waehlt ein TileMapping,
        das wiederum den Tileset-Index und den Grafik-Index liefert.

        The 11-bit index obtained via tile_mapping_index() selects a
        TileMapping, which in turn yields the tileset index plus graphic index.
        """
        m = self.tile_mappings[self.tile_mapping_index(x, y)]
        return m.tileset_index, m.tile_graphic_index


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
    print(f"Beispiel Zelle (10,10): tileset/gfx = {m.tileset_and_graphic(10, 10)}")
