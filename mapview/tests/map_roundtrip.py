"""Roundtrip-Test des .map-Lesers/Schreibers ueber alle vorhandenen Karten.

Jede Karte wird gelesen und wieder serialisiert; das Ergebnis muss byte-
identisch zum Original sein. Zusaetzlich werden die Zell-Zugriffe geprueft
(cellType/tileMappingIndex setzen veraendert genau die gemeinten Bits).

Aufruf:  python mapview/tests/map_roundtrip.py [<Outpost2-Ordner>]
Exit 0 = alles gruen.

Roundtrip test of the .map reader/writer across every map found: read, write,
compare byte for byte, plus cell-accessor checks.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAPVIEW = HERE.parent
sys.path.insert(0, str(MAPVIEW))

# Kartennamen sind nicht durchgaengig ASCII -- Ausgabe robust machen.
# Map names are not consistently ASCII -- make the output robust.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from op2map import Op2Map  # noqa: E402
import celltypes  # noqa: E402

DEFAULT_GAME_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")

_failures: list[str] = []


def check(name: str, ok, info: str = "") -> bool:
    ok = bool(ok)
    print(("OK  " if ok else "FAIL") + f"  {name}" + (f"  {info}" if info else ""))
    if not ok:
        _failures.append(name)
    return ok


def roundtrip_all(game_dir: Path) -> list[Op2Map]:
    maps = [m for m in sorted(set(game_dir.rglob("*.map")))
            if "MonoBleedingEdge" not in str(m)]
    parsed, identical, broken = 0, 0, []
    samples = []
    for path in maps:
        raw = path.read_bytes()
        try:
            m = Op2Map(raw)
        except Exception as e:
            broken.append(f"{path.name}: {type(e).__name__} {e}")
            continue
        parsed += 1
        if m.to_bytes() == raw:
            identical += 1
        else:
            broken.append(f"{path.name}: Roundtrip weicht ab "
                          f"({len(m.to_bytes())} statt {len(raw)} Bytes)")
        if len(samples) < 3:
            samples.append(m)
    check(f"alle {len(maps)} Karten gelesen", parsed == len(maps), f"({parsed})")
    check(f"alle {len(maps)} Karten byte-identisch geschrieben",
          identical == len(maps), f"({identical})")
    for b in broken[:8]:
        print("      ", b)
    return samples


def check_accessors(m: Op2Map) -> None:
    x, y = 10, 10
    original = m.tiles[m.tile_index(x, y)]
    mapping = m.tile_mapping_index(x, y)
    cell = m.cell_type(x, y)

    m.set_cell_type(x, y, celltypes.IMPASSIBLE_1)
    check("set_cell_type aendert nur den Zelltyp",
          m.cell_type(x, y) == celltypes.IMPASSIBLE_1
          and m.tile_mapping_index(x, y) == mapping)

    m.set_tile_mapping_index(x, y, 1234)
    check("set_tile_mapping_index aendert nur die Grafik",
          m.tile_mapping_index(x, y) == 1234
          and m.cell_type(x, y) == celltypes.IMPASSIBLE_1)

    m.set_tile(x, y, mapping, cell)
    check("set_tile stellt den Ausgangszustand her",
          m.tiles[m.tile_index(x, y)] == original,
          f"(0x{m.tiles[m.tile_index(x, y)]:08X} vs 0x{original:08X})")

    # Kachel-Indizierung: jede Zelle muss genau einmal adressiert werden.
    seen = {m.tile_index(px, py) for py in range(m.height) for px in range(m.width)}
    check("tile_index adressiert jede Zelle genau einmal",
          len(seen) == m.width * m.height, f"({len(seen)}/{m.width*m.height})")


def check_groups(m: Op2Map) -> None:
    groups = m.tile_groups
    check("TileGroups gelesen", len(groups) > 0, f"({len(groups)})")
    if not groups:
        return
    bad = [g for g in groups if len(g.mapping_indices) != g.width * g.height]
    check("Gruppengroessen stimmen mit der Indexanzahl ueberein", not bad,
          str([g.name for g in bad[:3]]))
    cliffs = [g for g in groups if g.name.endswith(tuple("0123456789"))
              and "mes" in g.name]
    check("Klippen-Stempel vorhanden (mud/roc/san…mes*)", bool(cliffs),
          f"z.B. {[g.name for g in cliffs[:3]]}")
    check("terrainTypes durchgereicht", len(m.terrain_types) > 0,
          f"({len(m.terrain_types)} x 264 B)")


def check_celltype_table(m: Op2Map) -> None:
    if not (MAPVIEW / "celltypes.json").exists():
        check("celltypes.json vorhanden", False,
              "-> zuerst 'python mapview/learn_celltypes.py' ausfuehren")
        return
    check("celltypes.json vorhanden", True)
    hits = total = 0
    for y in range(0, m.height, 4):
        for x in range(0, m.width, 4):
            total += 1
            if celltypes.default_cell_type(m.tile_mapping_index(x, y)) == m.cell_type(x, y):
                hits += 1
    share = hits / total if total else 0
    check("gelernte Vorgabe trifft die Originalkarte zu >=90 %", share >= 0.90,
          f"({100*share:.1f} % auf {total} Stichproben)")
    speeds = {celltypes.speed_class(c) for c in celltypes.EDITABLE_CELL_TYPES}
    check("jede Zelltyp-Klasse hat eine Geschwindigkeitsklasse",
          "fast" in speeds and "impassable" in speeds, str(sorted(speeds)))


def main() -> int:
    game_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GAME_DIR
    if not game_dir.is_dir():
        print(f"Outpost-2-Ordner nicht gefunden: {game_dir}")
        return 1
    samples = roundtrip_all(game_dir)
    if samples:
        check_accessors(samples[0])
        check_groups(samples[0])
        check_celltype_table(samples[0])
    print("\n" + ("Alle Pruefungen gruen." if not _failures
                  else f"{len(_failures)} Pruefung(en) rot: {_failures}"))
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
