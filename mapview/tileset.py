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

Decoder for OP2 tilesets (well####.bmp) in both variants:

* OP2 "PBMP" (inside the .vol archives), reimplemented from
  OP2Utility/src/Sprite/TilesetLoader.cpp + TilesetHeaders.h:
    SectionHeader "PBMP" (8B)
    TilesetHeader: "head"(8B) + tagCount,pixelWidth,pixelHeight,bitDepth,flags (5*u32=20B)
    PpalHeader:    "PPAL"(8B) + "head"(8B) + tagCount(u32=4B)
    paletteHeader: "data"(8B) + 256*4B palette  (R/B swapped vs. standard BMP)
    pixelHeader:   "data"(8B) + width*height B   (8bpp indices, top-down)
* Standard Windows BMP (extracted OPU 1.4.1, base/tilesets/well####.bmp):
  same layout (32px-wide strip of 32x32 tiles, 8bpp palette), but
  as an ordinary .bmp file -> read via PIL.

`load_tileset()` picks the matching decoder automatically based on the magic bytes.
Tiles are 32x32 and vertically stacked (tile t = rows t*32 .. t*32+31).
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
    # (256, 3) uint8, RGB
    pixels: np.ndarray    # (height, 32) uint8 Palettenindizes
    # (height, 32) uint8 palette indices


def decode_tileset(data: bytes) -> Tileset:
    # bit_depth muss 8 sein: das Format ist ein 8bpp-Palettenbild, jedes Pixel
    # ist ein 1-Byte-Index in die 256-Eintraege-Palette. Andere Tiefen werden
    # nicht unterstuetzt (siehe assert weiter unten).
    # bit_depth must be 8: the format is an 8bpp paletted image, each pixel is
    # a 1-byte index into the 256-entry palette. Other depths are unsupported
    # (see the assert below).
    pos = 0

    def section() -> tuple[bytes, int]:
        nonlocal pos
        tag = data[pos:pos + 4]
        length = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
        return tag, length

    tag, _ = section()
    # "kein PBMP" = "not PBMP"
    assert tag == b"PBMP", f"kein PBMP: {tag!r}"

    tag, head_len = section()
    assert tag == b"head"
    tag_count, pw, ph, bit_depth, flags = struct.unpack_from("<5I", data, pos)
    pos += head_len
    # Breite muss 32 (TILE) sein und die Tiefe 8bpp; "unerwartet" = "unexpected".
    # Width must be 32 (TILE) and the depth 8bpp.
    assert pw == TILE and bit_depth == 8, f"unerwartet: w={pw} bpp={bit_depth}"

    # PPAL-Container
    # PPAL container
    tag, _ = section()
    assert tag == b"PPAL"
    tag, _ = section()
    assert tag == b"head"
    pos += 4  # tagCount im PPAL/head
    # tagCount in PPAL/head

    # Palette
    # Palette
    tag, pal_len = section()
    assert tag == b"data"
    pal_raw = np.frombuffer(data, dtype=np.uint8, count=pal_len, offset=pos).reshape(-1, 4)
    pos += pal_len
    # Datei speichert R,G,B,A; wir nehmen die ersten 3 Kanaele als RGB.
    # File stores R,G,B,A; we take the first 3 channels as RGB.
    # Das 4. Byte (Alpha) wird verworfen (RGBA -> RGB, Alpha ignoriert).
    # The 4th byte (alpha) is dropped (RGBA -> RGB, alpha ignored).
    palette = pal_raw[:, :3].copy()

    # Pixel
    # Pixel
    tag, px_len = section()
    assert tag == b"data"
    # Die flachen Pixel-Bytes werden zu (ph, pw) umgeformt: Hoehe x Breite
    # (Breite = 32), jedes Byte ein Palettenindex.
    # The flat pixel bytes are reshaped to (ph, pw): height x width
    # (width = 32), each byte one palette index.
    pixels = np.frombuffer(data, dtype=np.uint8, count=px_len, offset=pos).reshape(ph, pw)

    return Tileset(num_tiles=ph // TILE, palette=palette, pixels=pixels)


def decode_bmp_tileset(data: bytes) -> Tileset:
    """Decodes a standard Windows BMP tileset (OPU 1.4.1 well####.bmp).

    Dekodiert ein Standard-Windows-BMP-Tileset (OPU 1.4.1 well####.bmp).

    Gleiches Tile-Layout wie PBMP (32px breiter, vertikaler Streifen aus
    32x32-Tiles, 8bpp-Palettenbild); per PIL gelesen (Lazy-Import, damit die
    reine PBMP-/.vol-Nutzung ohne Pillow auskommt).

    Same tile layout as PBMP (32px-wide, vertical strip of 32x32 tiles,
    8bpp paletted image); read via PIL (lazy import, so that pure PBMP/.vol
    usage works without Pillow).
    """
    import io
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    if im.mode != "P":
        im = im.convert("P")
    pixels = np.asarray(im, dtype=np.uint8)            # (H, 32) Indizes (top-down)
    # (H, 32) indices (top-down)
    raw = bytes(im.getpalette() or b"")
    # Die Palette wird auf genau 256 Eintraege aufgefuellt/zugeschnitten (8bpp).
    # The palette is padded/sliced to exactly 256 entries (8bpp).
    palette = np.zeros((256, 3), dtype=np.uint8)
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)[:256]
    palette[: len(rgb)] = rgb
    return Tileset(num_tiles=pixels.shape[0] // TILE, palette=palette, pixels=pixels)


def load_tileset(data: bytes) -> Tileset:
    """Laedt ein Tileset unabhaengig vom Format (OP2-PBMP oder Standard-BMP).

    Loads a tileset regardless of format (OP2-PBMP or standard BMP).
    """
    # Verzweigt anhand der Magic-Bytes: "PBMP" = OP2-Container (in .vol),
    # "BM" = Standard-Windows-BMP (OPU-1.4.1-Lose-Dateien).
    # Dispatches by magic bytes: "PBMP" = OP2 container (in .vol),
    # "BM" = standard Windows BMP (OPU 1.4.1 loose files).
    if data[:4] == b"PBMP":
        return decode_tileset(data)
    if data[:2] == b"BM":
        return decode_bmp_tileset(data)
    # "Unbekanntes Tileset-Format" = "Unknown tileset format"
    raise ValueError(f"Unbekanntes Tileset-Format: {data[:8]!r}")


def get_tile_rgb(ts: Tileset, graphic_index: int) -> np.ndarray:
    """32x32x3 RGB-Bild fuer einen Tile-Index.

    32x32x3 RGB image for a tile index.
    """
    block = ts.pixels[graphic_index * TILE:(graphic_index + 1) * TILE, :]  # (32,32)
    return ts.palette[block]  # (32,32,3)


if __name__ == "__main__":
    import sys
    from vol import VolFile
    vol = VolFile(sys.argv[1])
    ts = decode_tileset(vol.read_file(sys.argv[2]))
    print(f"{sys.argv[2]}: {ts.num_tiles} Tiles, Palette {ts.palette.shape}, Pixel {ts.pixels.shape}")
