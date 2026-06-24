"""Decoder fuer OP2-Tilesets (well####.bmp) in beiden Varianten:

* OP2-"PBMP" (in den .vol-Archiven), nachgebaut aus
  OP2Utility/src/Sprite/TilesetLoader.cpp + TilesetHeaders.h:
    SectionHeader "PBMP" (8B)
    TilesetHeader: "head"(8B) + tagCount,pixelWidth,pixelHeight,bitDepth,flags (5*u32=20B)
    PpalHeader:    "PPAL"(8B) + "head"(8B) + tagCount(u32=4B)
    paletteHeader: "data"(8B) + 256*4B Palette  (R/B getauscht ggue. Standard-BMP)
    pixelHeader:   "data"(8B) + width*height B   (8bpp Indizes, top-down)
* Standard-Windows-BMP (entpacktes OPU 1.4.1, base/tilesets/well####.bmp):
  gleiches Layout (32px breiter Streifen aus 32x32-Tiles, 8bpp-Palette), aber
  als gewoehnliche .bmp-Datei -> per PIL gelesen.

`load_tileset()` waehlt anhand der Magic-Bytes automatisch den passenden Decoder.
Tiles sind 32x32 und vertikal gestapelt (Tile t = Zeilen t*32 .. t*32+31).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

TILE = 32


@dataclass
class Tileset:
    num_tiles: int
    palette: np.ndarray   # (256, 3) uint8, RGB
    pixels: np.ndarray    # (height, 32) uint8 Palettenindizes


def decode_tileset(data: bytes) -> Tileset:
    pos = 0

    def section() -> tuple[bytes, int]:
        nonlocal pos
        tag = data[pos:pos + 4]
        length = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
        return tag, length

    tag, _ = section()
    assert tag == b"PBMP", f"kein PBMP: {tag!r}"

    tag, head_len = section()
    assert tag == b"head"
    tag_count, pw, ph, bit_depth, flags = struct.unpack_from("<5I", data, pos)
    pos += head_len
    assert pw == TILE and bit_depth == 8, f"unerwartet: w={pw} bpp={bit_depth}"

    # PPAL-Container
    tag, _ = section()
    assert tag == b"PPAL"
    tag, _ = section()
    assert tag == b"head"
    pos += 4  # tagCount im PPAL/head

    # Palette
    tag, pal_len = section()
    assert tag == b"data"
    pal_raw = np.frombuffer(data, dtype=np.uint8, count=pal_len, offset=pos).reshape(-1, 4)
    pos += pal_len
    # Datei speichert R,G,B,A; wir nehmen die ersten 3 Kanaele als RGB.
    palette = pal_raw[:, :3].copy()

    # Pixel
    tag, px_len = section()
    assert tag == b"data"
    pixels = np.frombuffer(data, dtype=np.uint8, count=px_len, offset=pos).reshape(ph, pw)

    return Tileset(num_tiles=ph // TILE, palette=palette, pixels=pixels)


def decode_bmp_tileset(data: bytes) -> Tileset:
    """Decodes a standard Windows BMP tileset (OPU 1.4.1 well####.bmp).

    Gleiches Tile-Layout wie PBMP (32px breiter, vertikaler Streifen aus
    32x32-Tiles, 8bpp-Palettenbild); per PIL gelesen (Lazy-Import, damit die
    reine PBMP-/.vol-Nutzung ohne Pillow auskommt).
    """
    import io
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    if im.mode != "P":
        im = im.convert("P")
    pixels = np.asarray(im, dtype=np.uint8)            # (H, 32) Indizes (top-down)
    raw = bytes(im.getpalette() or b"")
    palette = np.zeros((256, 3), dtype=np.uint8)
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)[:256]
    palette[: len(rgb)] = rgb
    return Tileset(num_tiles=pixels.shape[0] // TILE, palette=palette, pixels=pixels)


def load_tileset(data: bytes) -> Tileset:
    """Laedt ein Tileset unabhaengig vom Format (OP2-PBMP oder Standard-BMP)."""
    if data[:4] == b"PBMP":
        return decode_tileset(data)
    if data[:2] == b"BM":
        return decode_bmp_tileset(data)
    raise ValueError(f"Unbekanntes Tileset-Format: {data[:8]!r}")


def get_tile_rgb(ts: Tileset, graphic_index: int) -> np.ndarray:
    """32x32x3 RGB-Bild fuer einen Tile-Index."""
    block = ts.pixels[graphic_index * TILE:(graphic_index + 1) * TILE, :]  # (32,32)
    return ts.palette[block]  # (32,32,3)


if __name__ == "__main__":
    import sys
    from vol import VolFile
    vol = VolFile(sys.argv[1])
    ts = decode_tileset(vol.read_file(sys.argv[2]))
    print(f"{sys.argv[2]}: {ts.num_tiles} Tiles, Palette {ts.palette.shape}, Pixel {ts.pixels.shape}")
