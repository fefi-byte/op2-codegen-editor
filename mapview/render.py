"""Rendert eine OP2-Map als PNG: Tiles aufloesen -> Tilesets -> Bild zusammensetzen.

Aufruf:
  python render.py <maps.vol> <name.map> [out.png] [tile_px]
  python render.py <pfad/zur/datei.map> [out.png] [tile_px]

Renders an OP2 map as a PNG: resolve tiles -> tilesets -> assemble image.

Usage:
  python render.py <maps.vol> <name.map> [out.png] [tile_px]
  python render.py <path/to/file.map> [out.png] [tile_px]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from op2map import Op2Map
from tileset import TILE, Tileset, load_tileset
from vol import VolFile


def render_array(m: Op2Map, vol: VolFile) -> np.ndarray:
    """Rendert die Map in ein (H*32, W*32, 3) uint8 RGB-Array (volle Tile-Aufloesung).

    Renders the map into an (H*32, W*32, 3) uint8 RGB array (full tile resolution).
    """
    tilesets: dict[int, Tileset] = {}
    for i, ts in enumerate(m.tileset_sources):
        if ts.filename:
            tilesets[i] = load_tileset(vol.read_file(ts.filename + ".bmp"))

    W, H = m.width, m.height
    canvas = np.zeros((H * TILE, W * TILE, 3), dtype=np.uint8)

    for y in range(H):
        for x in range(W):
            ts_idx, gfx = m.tileset_and_graphic(x, y)
            ts = tilesets.get(ts_idx)
            if ts is None or gfx >= ts.num_tiles:
                continue
            block = ts.pixels[gfx * TILE:(gfx + 1) * TILE, :]
            canvas[y * TILE:(y + 1) * TILE, x * TILE:(x + 1) * TILE] = ts.palette[block]

    return canvas


def render(m: Op2Map, vol: VolFile, out: str, tile_px: int = 16) -> None:
    canvas = render_array(m, vol)
    W, H = m.width, m.height
    img = Image.fromarray(canvas, "RGB")
    if tile_px != TILE:
        img = img.resize((W * tile_px, H * tile_px), Image.NEAREST)
    img.save(out)
    print(f"[ok] {out}  ({img.width}x{img.height} px, {W}x{H} Tiles)")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0].lower().endswith(".vol"):
        vol = VolFile(args[0])
        map_name = args[1]
        data = vol.read_file(map_name)
        out = args[2] if len(args) > 2 else Path(map_name).stem + ".png"
        tile_px = int(args[3]) if len(args) > 3 else 16
    else:
        # Lose .map-Datei: zugehoeriges maps.vol im selben Ordner fuer Tilesets nutzen
        # Loose .map file: use the accompanying maps.vol in the same folder for tilesets
        map_path = Path(args[0])
        data = map_path.read_bytes()
        vol = VolFile(map_path.parent / "maps.vol")
        out = args[1] if len(args) > 1 else map_path.stem + ".png"
        tile_px = int(args[2]) if len(args) > 2 else 16

    m = Op2Map(data)
    print(f"Map {m.width}x{m.height}, {len([t for t in m.tileset_sources if t.filename])} Tilesets")
    render(m, vol, out, tile_px)


if __name__ == "__main__":
    main()
