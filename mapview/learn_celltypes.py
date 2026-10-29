"""Lernt aus den mitgelieferten Karten, welcher Zelltyp zu welcher Kachel gehoert.

Ergebnis: `celltypes.json` neben diesem Skript --
  {"default": {tileMappingIndex: cellType}, "confidence": {...}, "meta": {...}}

Der Editor setzt damit beim Malen automatisch die Befahrbarkeit, die die
Original-Designer fuer diese Kachelgrafik verwendet haben.

Aufruf:  python mapview/learn_celltypes.py [<Outpost2-Ordner>]

Learns which cell type belongs to which tile graphic from the shipped maps and
writes celltypes.json next to this script.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from op2map import Op2Map  # noqa: E402

from spielpfad import spielordner  # noqa: E402
DEFAULT_GAME_DIR = spielordner()
OUT_PATH = Path(__file__).with_name("celltypes.json")


def learn(game_dir: Path) -> dict:
    per_tile: dict[int, Counter] = defaultdict(Counter)
    maps = [m for m in sorted(set(game_dir.rglob("*.map")))
            if "MonoBleedingEdge" not in str(m)]
    used = 0
    for path in maps:
        try:
            m = Op2Map(path.read_bytes())
        except Exception:
            continue
        used += 1
        for tile in m.tiles:
            per_tile[(tile >> 5) & 0x7FF][tile & 0x1F] += 1

    default: dict[str, int] = {}
    confidence: dict[str, float] = {}
    for idx, counter in per_tile.items():
        total = sum(counter.values())
        cell, n = counter.most_common(1)[0]
        default[str(idx)] = cell
        confidence[str(idx)] = round(n / total, 4)

    return {
        "default": default,
        "confidence": confidence,
        "meta": {
            "maps": used,
            "tiles": sum(sum(c.values()) for c in per_tile.values()),
            "distinct_mapping_indices": len(per_tile),
            "source": str(game_dir),
        },
    }


def main() -> int:
    game_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GAME_DIR
    if not game_dir.is_dir():
        print(f"Outpost-2-Ordner nicht gefunden: {game_dir}")
        return 1
    table = learn(game_dir)
    OUT_PATH.write_text(json.dumps(table, separators=(",", ":"), sort_keys=True),
                        encoding="utf-8")
    meta = table["meta"]
    sure = sum(1 for v in table["confidence"].values() if v >= 0.99)
    print(f"{meta['maps']} Karten, {meta['tiles']} Zellen ausgewertet")
    print(f"{meta['distinct_mapping_indices']} Kachelgrafiken -> {sure} davon "
          f"zu >=99 % eindeutig")
    print(f"geschrieben: {OUT_PATH} ({OUT_PATH.stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
