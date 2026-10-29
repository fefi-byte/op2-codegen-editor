"""Befahrbarkeit, Startpunkte und Zusammenhang.

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

Passability, spawn points and connectivity. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations


import numpy as np

import celltypes  # noqa: E402
from mapgen_basis import (  # noqa: E402
    PASSABLE_CLASSES,
    SYM_MIRROR_X,
    SYM_MIRROR_Y,
    SYM_QUAD,
    SYM_ROT180,
)


# --------------------------------------------------------------------------
# Startpunkte / spawn points

def _passable_mask(cells: np.ndarray) -> np.ndarray:
    passable = np.zeros(32, dtype=bool)
    for cell in range(32):
        passable[cell] = celltypes.speed_class(cell) in PASSABLE_CLASSES
    return passable[cells]


def _clearance(mask: np.ndarray, radius: int) -> np.ndarray:
    """Anteil befahrbarer Kacheln im Quadrat um jede Zelle (Summentabelle)."""
    h, w = mask.shape
    size = 2 * radius + 1
    padded = np.pad(mask.astype(np.int32), radius, mode="constant")
    # Fuehrende Null-Zeile/-Spalte, damit die vier Ecken der Summentabelle
    # ohne Sonderfaelle passen.
    # Leading zero row/column so the four corners of the summed-area table
    # work without special cases.
    integral = np.zeros((padded.shape[0] + 1, padded.shape[1] + 1), dtype=np.int32)
    integral[1:, 1:] = padded.cumsum(0).cumsum(1)
    total = (integral[size:size + h, size:size + w]
             - integral[:h, size:size + w]
             - integral[size:size + h, :w]
             + integral[:h, :w])
    return total / float(size * size)


def _groesstes_gebiet(mask: np.ndarray) -> np.ndarray:
    """Groesste zusammenhaengende Flaeche einer Maske (4er-Nachbarschaft)."""
    if not mask.any():
        return mask
    h, w = mask.shape
    marke = np.zeros((h, w), dtype=np.int32)
    groessen = [0]
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or marke[sy, sx]:
                continue
            nummer = len(groessen)
            stapel = [(sy, sx)]
            marke[sy, sx] = nummer
            anzahl = 0
            while stapel:
                y, x = stapel.pop()
                anzahl += 1
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if (0 <= ny < h and 0 <= nx < w and mask[ny, nx]
                            and not marke[ny, nx]):
                        marke[ny, nx] = nummer
                        stapel.append((ny, nx))
            groessen.append(anzahl)
    beste = int(np.argmax(groessen))
    return marke == beste


def _pick_spawns(cells: np.ndarray, count: int, clearance: int,
                 symmetry: str, rng: np.random.Generator) -> list[tuple[int, int]]:
    """Freie, weit auseinander liegende Startplaetze suchen."""
    if count <= 0:
        return []
    mask = _passable_mask(cells)
    # Nur im groessten zusammenhaengenden befahrbaren Gebiet suchen. Vorher
    # wurde irgendwo Freiflaeche genommen und hinterher nur GEMELDET, ob die
    # Startplaetze einander erreichen -- bei einem Berg quer ueber der Karte
    # lagen sie dann je nach Zufall auf verschiedenen Seiten. Ein Startplatz,
    # den der Gegner nie erreicht, macht die Karte unbrauchbar.
    # Search only within the largest connected passable area. Previously any
    # free spot was taken and afterwards it was merely REPORTED whether the
    # starts could reach each other -- with a mountain across the map they then
    # landed on opposite sides depending on chance. A start the opponent can
    # never reach makes the map useless.
    mask = _groesstes_gebiet(mask)
    free = _clearance(mask, clearance) >= 0.995
    h, w = mask.shape
    margin = clearance + 2
    free[:margin, :] = free[-margin:, :] = False
    free[:, :margin] = free[:, -margin:] = False
    ys, xs = np.nonzero(free)
    if len(xs) == 0:
        return []

    def mirror(p: tuple[int, int]) -> list[tuple[int, int]]:
        x, y = p
        if symmetry == SYM_MIRROR_X:
            return [(w - 1 - x, y)]
        if symmetry == SYM_MIRROR_Y:
            return [(x, h - 1 - y)]
        if symmetry == SYM_ROT180:
            return [(w - 1 - x, h - 1 - y)]
        if symmetry == SYM_QUAD:
            return [(w - 1 - x, y), (x, h - 1 - y), (w - 1 - x, h - 1 - y)]
        return []

    # Bei Symmetrie nur in der Grundhaelfte/-viertel suchen und spiegeln --
    # so sind die Startplaetze fair.
    # With symmetry only search the base half/quadrant and mirror -- that keeps
    # the starting positions fair.
    if symmetry in (SYM_MIRROR_X, SYM_ROT180, SYM_QUAD):
        keep = xs < w // 2
        ys, xs = ys[keep], xs[keep]
    if symmetry in (SYM_MIRROR_Y, SYM_QUAD):
        keep = ys < h // 2
        ys, xs = ys[keep], xs[keep]
    if len(xs) == 0:
        return []

    picked: list[tuple[int, int]] = []
    first = int(rng.integers(len(xs)))
    picked.append((int(xs[first]), int(ys[first])))
    per_mirror = 1 + len(mirror(picked[0]))
    needed = max(1, -(-count // per_mirror))     # aufrunden
    while len(picked) < needed:
        px = np.array([p[0] for p in picked])
        py = np.array([p[1] for p in picked])
        dist = np.min((xs[:, None] - px) ** 2 + (ys[:, None] - py) ** 2, axis=1)
        best = int(np.argmax(dist))
        if dist[best] == 0:
            break
        picked.append((int(xs[best]), int(ys[best])))

    spawns: list[tuple[int, int]] = []
    for p in picked:
        spawns.append(p)
        spawns.extend(mirror(p))
    return spawns[:count] if count <= len(spawns) else spawns


def _connected(cells: np.ndarray, spawns: list[tuple[int, int]]) -> bool:
    """Sind alle Startpunkte ueber befahrbares Gelaende verbunden?"""
    if len(spawns) < 2:
        return True
    mask = _passable_mask(cells)
    h, w = mask.shape
    seen = np.zeros_like(mask)
    stack = [spawns[0]]
    seen[spawns[0][1], spawns[0][0]] = True
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                stack.append((nx, ny))
    return all(seen[y, x] for x, y in spawns)
