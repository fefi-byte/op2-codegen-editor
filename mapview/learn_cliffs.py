"""Klippenmodell anlernen -- getrennt vom Kachelmodell.

Die Klippengruppen (`*mes*`) sind die Pinsel, mit denen die Entwickler ihre
Waende gemalt haben. Ihre Kachelmuster stehen deshalb woertlich in den Karten,
und damit laesst sich abzaehlen statt raten, welche Gruppe an welche grenzt.

Warum ein eigenes Modell: das Kachelmodell (`tiles_model.npz`) traegt die
Statistik fuer den Bodensampler und ist durchgemessen. Klippen brauchen eine
andere Aufloesung -- Gruppe statt Kachel, mit Versatz -- und sollen daran nicht
ruetteln koennen.

Was gegenueber einer bloss buendigen Zaehlung dazukommt: der VERSATZ. Die
Originalkarten setzen ihre Bloecke nicht auf ein Dreierraster, sondern
verschoben; gemessen beginnen nur 29-42 % der Klippenlaeufe rasterbuendig. Eine
Zaehlung, die gleiche Zeilen bzw. Spalten verlangt, verliert deshalb den
Grossteil der echten Nachbarschaften.

Cliff model training -- separate from the tile model. The cliff groups are the
brushes the developers painted their walls with, so their tile patterns appear
verbatim in the maps and the adjacency can be counted instead of guessed. It
gets its own model because the tile model carries the ground sampler's measured
statistics and must not be disturbed. Beyond a flush-only count this records the
OFFSET: the originals place their blocks shifted, not on a three-cell grid.

Aufruf / usage:
    python mapview/learn_cliffs.py [Spielordner]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from op2map import Op2Map  # noqa: E402
import celltypes  # noqa: E402
from learn_tiles import (CLIFF_MARKER, training_maps, kachelfeld,  # noqa: E402
                         DEFAULT_GAME_DIR)

OUT_PATH = Path(__file__).resolve().parent / "cliffs_model.npz"

# Richtungen wie in den Kantensignaturen: 0 = Ost, 1 = West, 2 = Sued, 3 = Nord,
# gelesen als "b liegt dort von a".
RICHTUNG_NAME = {0: "Ost", 1: "West", 2: "Sued", 3: "Nord"}


def sammle_gruppen(maps: list[Path]) -> dict[str, np.ndarray]:
    """Alle Klippengruppen ueber alle Karten -- Name -> Kachelfeld."""
    gruppen: dict[str, np.ndarray] = {}
    for path in maps:
        try:
            m = Op2Map(path.read_bytes())
        except Exception:
            continue
        for g in m.tile_groups:
            name = (g.name or "").strip().lower()
            if CLIFF_MARKER in name and name not in gruppen:
                gruppen[name] = np.asarray(
                    g.mapping_indices, dtype=np.int32).reshape(g.height, g.width)
    return gruppen


def finde_bloecke(feld: np.ndarray, gruppen: dict[str, np.ndarray]) -> list:
    """Wo steht welche Gruppe woertlich in dieser Karte?

    Rueckgabe: [(Name, x, y, Breite, Hoehe)], ohne Treffer, die vollstaendig in
    einem groesseren stecken -- die obere Reihe eines 3x3-Blocks passt sonst
    ein zweites Mal als 1x3-Streifen.
    """
    funde = []
    for name, b in gruppen.items():
        bh, bw = b.shape
        if bh > feld.shape[0] or bw > feld.shape[1]:
            continue
        ecken = np.argwhere(
            feld[:feld.shape[0] - bh + 1, :feld.shape[1] - bw + 1] == b[0, 0])
        for y, x in ecken:
            if np.array_equal(feld[y:y + bh, x:x + bw], b):
                funde.append((name, int(x), int(y), bw, bh))
    flaeche = {n: b.size for n, b in gruppen.items()}
    return [e for e in funde
            if not any(o != e and flaeche[o[0]] > flaeche[e[0]]
                       and o[1] <= e[1] and o[2] <= e[2]
                       and e[1] + e[3] <= o[1] + o[3]
                       and e[2] + e[4] <= o[2] + o[4]
                       for o in funde)]


def zaehle_nachbarn(funde: list, zaehler: Counter, buendig: Counter) -> None:
    """Beruehrende Blockpaare zaehlen -- mit Versatz.

    Zwei Bloecke sind Nachbarn, wenn eine Kante des einen an der Gegenkante des
    anderen liegt und sich ihre Ausdehnung quer dazu ueberlappt. Der Versatz
    ist die Verschiebung entlang der gemeinsamen Kante.

    Frueher habe ich zusaetzlich gleiche Zeilen bzw. Spalten verlangt. Das ist
    genau der Fehler: die Karten setzen versetzt, und alles Versetzte fiel
    heraus -- deshalb fehlten Paare, die im Spiel klar zu sehen sind.
    """
    for name, x, y, bw, bh in funde:
        for n2, x2, y2, bw2, bh2 in funde:
            if (n2, x2, y2) == (name, x, y):
                continue
            quer_v = y < y2 + bh2 and y2 < y + bh      # Zeilen ueberlappen
            quer_h = x < x2 + bw2 and x2 < x + bw      # Spalten ueberlappen
            if quer_v and x2 == x + bw:
                r, versatz, fluchtend = 0, y2 - y, bh == bh2 and y2 == y
            elif quer_v and x2 + bw2 == x:
                r, versatz, fluchtend = 1, y2 - y, bh == bh2 and y2 == y
            elif quer_h and y2 == y + bh:
                r, versatz, fluchtend = 2, x2 - x, bw == bw2 and x2 == x
            elif quer_h and y2 + bh2 == y:
                r, versatz, fluchtend = 3, x2 - x, bw == bw2 and x2 == x
            else:
                continue
            zaehler[(name, n2, r, int(versatz))] += 1
            if fluchtend:
                buendig[(name, n2, r)] += 1


def lerne(game_dir: Path) -> dict:
    """Das Klippenmodell aus allen Karten des Spielordners bauen."""
    maps = training_maps(game_dir, campaign_only=False)
    gruppen = sammle_gruppen(maps)
    namen = sorted(gruppen)
    pos = {n: i for i, n in enumerate(namen)}
    zaehler: Counter = Counter()
    buendig: Counter = Counter()
    vorkommen: Counter = Counter()
    karten = 0
    for path in maps:
        try:
            feld = kachelfeld(Op2Map(path.read_bytes()))
        except Exception:
            continue
        karten += 1
        funde = finde_bloecke(feld, gruppen)
        for name, *_ in funde:
            vorkommen[name] += 1
        zaehle_nachbarn(funde, zaehler, buendig)

    eintraege = sorted((pos[a], pos[b], r, v, n)
                       for (a, b, r, v), n in zaehler.items())
    spalten = ([np.array([e[i] for e in eintraege], dtype=np.int32)
                for i in range(5)] if eintraege
               else [np.zeros(0, np.int32)] * 5)

    groessen, flach, versatz_off = [], [], []
    for n in namen:
        b = gruppen[n]
        groessen.append((b.shape[1], b.shape[0]))
        versatz_off.append(len(flach))
        flach.extend(b.ravel().tolist())
    versatz_off.append(len(flach))

    # Zelltypen je Gruppe mitgeben: daraus liest sich die Wandlage ab, ohne
    # die Kacheltabelle zu bemuehen.
    return {
        "namen": np.array(namen or [""]),
        "groessen": np.array(groessen or [(0, 0)], dtype=np.int32),
        "kacheln": np.array(flach or [0], dtype=np.int32),
        "offsets": np.array(versatz_off, dtype=np.int32),
        "nb_a": spalten[0], "nb_b": spalten[1], "nb_richtung": spalten[2],
        "nb_versatz": spalten[3], "nb_anzahl": spalten[4],
        "buendig": np.array(
            [[pos[a], pos[b], r, n] for (a, b, r), n in sorted(buendig.items())]
            or [[0, 0, 0, 0]], dtype=np.int32),
        "vorkommen": np.array([vorkommen[n] for n in namen] or [0],
                              dtype=np.int32),
        "karten": np.array([karten], dtype=np.int32),
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    game_dir = Path(args[0]) if args else DEFAULT_GAME_DIR
    if not game_dir.is_dir():
        print(f"Outpost-2-Ordner nicht gefunden: {game_dir}")
        return 1
    modell = lerne(game_dir)
    np.savez_compressed(OUT_PATH, **modell)
    namen = [str(n) for n in modell["namen"]]
    ges = int(modell["nb_anzahl"].sum())
    buendig = int(modell["buendig"][:, 3].sum())
    print(f"{int(modell['karten'][0])} Karten, {len(namen)} Klippengruppen, "
          f"{int(modell['vorkommen'].sum())} Vorkommen")
    print(f"Nachbarschaften: {ges} beruehrende Paare, davon {buendig} buendig "
          f"({100 * buendig / max(1, ges):.0f} %)")
    print(f"verschiedene (a,b,Richtung,Versatz): {len(modell['nb_a'])}")
    for fam in sorted({n[:3] for n in namen}):
        eigen = [i for i, n in enumerate(namen) if n.startswith(fam)]
        n_paare = int(sum(modell["nb_anzahl"][i] for i in range(len(modell["nb_a"]))
                          if int(modell["nb_a"][i]) in eigen))
        print(f"   {fam}: {len(eigen)} Gruppen, {n_paare} Nachbarschaften")
    print(f"geschrieben: {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
