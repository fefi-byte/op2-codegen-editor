"""Reader fuer Outpost-2 .vol-Archive (unkomprimiert, wie im GOG/OPU-Release).

Format (aus OP2Utility/src/Archive/VolFile.cpp nachgebaut):
  SectionHeader = 4-Byte-Tag + uint32  (length = wert & 0x7FFFFFFF, padding-bit = wert>>31)
  Layout: "VOL " | "volh"(len 0) | "vols"+Stringtabelle | "voli"+Indextabelle | Datenbloecke("VBLK")
  IndexEntry (14 Byte): filenameOffset u32, dataBlockOffset u32, fileSize i32, compressionType u16

Reader for Outpost-2 .vol archives (uncompressed, as in the GOG/OPU release).

Format (reconstructed from OP2Utility/src/Archive/VolFile.cpp):
  SectionHeader = 4-byte tag + uint32  (length = value & 0x7FFFFFFF, padding bit = value>>31)
  Layout: "VOL " | "volh"(len 0) | "vols"+string table | "voli"+index table | data blocks ("VBLK")
  IndexEntry (14 bytes): filenameOffset u32, dataBlockOffset u32, fileSize i32, compressionType u16
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

UNCOMPRESSED = 0x100
LZH = 0x103


@dataclass
class VolEntry:
    name: str
    data_block_offset: int
    file_size: int
    compression: int


class VolFile:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._buf = self.path.read_bytes()
        self._pos = 0
        self.entries: list[VolEntry] = []
        self._read_header()

    # --- Low-level Helfer ---
    # --- Low-level helpers ---
    def _read(self, n: int) -> bytes:
        b = self._buf[self._pos:self._pos + n]
        self._pos += n
        return b

    def _u32(self) -> int:
        return struct.unpack_from("<I", self._read(4))[0]

    def _read_tag(self, expected: bytes) -> int:
        tag = self._read(4)
        raw = self._u32()
        length = raw & 0x7FFFFFFF
        four_byte_padding = (raw >> 31) & 1
        if tag != expected:
            raise ValueError(f"Erwartetes Tag {expected!r}, gefunden {tag!r} @ offset {self._pos-8}")
        if not four_byte_padding:
            raise ValueError(f"Tag {expected!r}: 2-Byte-Padding nicht unterstuetzt")
        return length

    # --- Header ---
    # --- Header ---
    def _read_header(self) -> None:
        self._read_tag(b"VOL ")
        if self._read_tag(b"volh") != 0:
            raise ValueError("volh-Laenge ist nicht 0")

        string_table_length = self._read_tag(b"vols")
        actual = self._u32()
        char_buffer = self._read(actual)
        names = char_buffer.split(b"\x00")
        if names and names[-1] == b"":
            names = names[:-1]
        names = [n.decode("ascii", "replace") for n in names]
        # Padding am Ende der Stringtabelle ueberspringen
        # Skip padding at the end of the string table
        self._pos += string_table_length - actual - 4

        index_table_length = self._read_tag(b"voli")
        count = index_table_length // 14
        raw_entries = []
        for _ in range(count):
            fn_off, blk_off, size, comp = struct.unpack_from("<IIiH", self._read(14))
            raw_entries.append((fn_off, blk_off, size, comp))

        # Gueltige Eintraege: bis filenameOffset == 0xFFFFFFFF
        # Valid entries: until filenameOffset == 0xFFFFFFFF
        for i, (fn_off, blk_off, size, comp) in enumerate(raw_entries):
            if fn_off == 0xFFFFFFFF:
                break
            name = names[i] if i < len(names) else f"<unnamed {i}>"
            self.entries.append(VolEntry(name, blk_off, size, comp))

    # --- Zugriff ---
    # --- Access ---
    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def read_file(self, name: str) -> bytes:
        for e in self.entries:
            if e.name.lower() == name.lower():
                return self._read_entry(e)
        raise KeyError(name)

    def _read_entry(self, e: VolEntry) -> bytes:
        tag = self._buf[e.data_block_offset:e.data_block_offset + 4]
        if tag != b"VBLK":
            raise ValueError(f"VBLK-Tag fehlt fuer {e.name}")
        if e.compression != UNCOMPRESSED:
            raise NotImplementedError(
                f"{e.name}: Kompression 0x{e.compression:X} (nur unkomprimiert unterstuetzt)"
            )
        start = e.data_block_offset + 8  # nach SectionHeader
        # start = e.data_block_offset + 8  # after the SectionHeader
        return self._buf[start:start + e.file_size]


if __name__ == "__main__":
    import sys
    vol = VolFile(sys.argv[1])
    print(f"{len(vol.entries)} Dateien in {vol.path.name}")
    for e in vol.entries:
        print(f"  {e.name:<16} {e.file_size:>9} B  comp=0x{e.compression:X}")
