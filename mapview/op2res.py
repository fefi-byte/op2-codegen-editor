"""Liest Outpost-2-Ressourcen aus dem entpackten OPU-Ordner (1.4.1) statt aus .vol.

OPU 1.4.1 legt alles als lose Dateien ab, daher braucht der Editor keine
.vol-Archive mehr:
  <content>/base/tilesets/well####.bmp   Tilesets
  <content>/base/maps/<Mission>/*.map    Karten (Kampagne/Stock)
  <content>/maps/<Mission>/*.map         weitere Karten
  <content>/*.map                         lose Karten
  <content>/base/techs/*.txt             Techbaeume

`<content>` ist `<game>/OPU`, falls vorhanden, sonst `<game>` selbst.

FolderResources bietet dieselbe Schnittstelle wie VolFile (names()/read_file()),
ist also ein direkter Ersatz fuer Editor und Renderer.

Reads Outpost-2 resources from the unpacked OPU folder (1.4.1) instead of from .vol.

OPU 1.4.1 stores everything as loose files, so the editor no longer needs
.vol archives:
  <content>/base/tilesets/well####.bmp   tilesets
  <content>/base/maps/<Mission>/*.map    maps (campaign/stock)
  <content>/maps/<Mission>/*.map         additional maps
  <content>/*.map                         loose maps
  <content>/base/techs/*.txt             tech trees

`<content>` is `<game>/OPU` if present, otherwise `<game>` itself.

FolderResources offers the same interface as VolFile (names()/read_file()),
so it is a drop-in replacement for the editor and renderer.
"""
from __future__ import annotations

from pathlib import Path


def content_root(game_path) -> Path:
    """Wurzel der entpackten Inhalte: <game>/OPU falls vorhanden, sonst <game>.

    Root of the unpacked content: <game>/OPU if present, otherwise <game>.
    """
    game_path = Path(game_path)
    opu = game_path / "OPU"
    return opu if opu.is_dir() else game_path


class FolderResources:
    """Indiziert .map- und Tileset-.bmp-Dateien im OPU-Ordnerbaum.

    Indexes .map and tileset .bmp files in the OPU folder tree.
    """

    def __init__(self, game_path):
        self.game_path = Path(game_path)
        self.root = content_root(self.game_path)
        self.tilesets_dir = self.root / "base" / "tilesets"
        self.techs_dir = self.root / "base" / "techs"
        self._index: dict[str, Path] = {}   # kleingeschriebener Dateiname -> Pfad
                                            # lowercased filename -> path
        self._maps: list[str] = []          # .map-Dateinamen (Originalschreibweise)
                                            # .map filenames (original spelling)
        self._build_index()

    def _add(self, path: Path) -> None:
        key = path.name.lower()
        if key in self._index:              # erste Fundstelle gewinnt
                                            # first occurrence wins
            return
        self._index[key] = path
        if key.endswith(".map"):
            self._maps.append(path.name)

    def _build_index(self) -> None:
        if self.tilesets_dir.is_dir():
            for p in self.tilesets_dir.glob("*.bmp"):
                self._add(p)
        for root in (self.root / "base" / "maps", self.root / "maps"):
            if root.is_dir():
                for p in root.rglob("*.map"):
                    if not any(part.lower() == "backups" for part in p.parts):
                        self._add(p)
        for p in self.root.glob("*.map"):
            self._add(p)

    # --- VolFile-kompatible Schnittstelle ---
    # --- VolFile-compatible interface ---
    def names(self) -> list[str]:
        """Alle gefundenen .map-Dateinamen (alphabetisch).

        All found .map filenames (alphabetical).
        """
        return sorted(self._maps, key=str.lower)

    def read_file(self, name: str) -> bytes:
        """Dateibytes per Basisnamen (z.B. 'cm02.map' oder 'well0001.bmp').

        File bytes by base name (e.g. 'cm02.map' or 'well0001.bmp').
        """
        path = self._index.get(name.lower())
        if path is None:
            raise KeyError(name)
        return path.read_bytes()


if __name__ == "__main__":
    import sys
    res = FolderResources(sys.argv[1] if len(sys.argv) > 1 else r"D:\Outpost 2")
    print(f"Wurzel: {res.root}")
    print(f"{len(res.names())} Karten, Tilesets in {res.tilesets_dir}")
    for n in res.names()[:10]:
        print(f"  {n}")
