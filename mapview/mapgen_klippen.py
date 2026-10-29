"""Klippen im Generator und die Baurichtungen des Klippenpinsels.

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

Cliffs in the generator and the cliff brush's build directions. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # nur fuer Typangaben
    from mapgen_modell import TileModel  # noqa: F401


import numpy as np

from mapgen_felder import (  # noqa: E402
    _components,
)
from mapgen_relief import (  # noqa: E402
    _kontur_boegen,
    _kontur_hand,
    _kontur_vereinfachen,
    _rand_zyklus,
)


def _klippe_algo():
    """`klippe_algo` erst beim Aufruf laden -- es importiert seinerseits
    Module, die `mapgen` brauchen."""
    import klippe_algo
    return klippe_algo


def _klippen_aus_linien(grid: np.ndarray, fam_field: np.ndarray,
                        H: np.ndarray, tm: "TileModel",
                        rng: np.random.Generator, ramps: int = 2
                        ) -> tuple[np.ndarray, np.ndarray]:
    """Hochlandkonturen als Linienzuege mit dem Gelaende-Loeser belegen.

    -> (Klippenmaske, Zelltypfeld; -1 = nicht gesetzt).

    Je Komponente wird der Rand abgelaufen, zu Eckpunkten vereinfacht und in
    Boegen mit Rampenluecken zerlegt; jeder Bogen geht durch
    `klippe_algo.klippe_aus_linie`, denselben Loeser wie der Klippenpinsel.
    Der Blockweg und `_male_klippen` sind entfernt (Doku Abschnitt 24).

    Cover the highland contours as polylines with the block path. Per
    component the boundary is walked, simplified to corner points and split
    into arcs with ramp gaps; every arc goes through the terrain solver.
    """
    maske_gesamt = np.zeros(grid.shape, dtype=bool)
    zellen_gesamt = np.full(grid.shape, -1, dtype=np.int16)
    hoch = H > 0
    if not hoch.any():
        return maske_gesamt, zellen_gesamt
    komponenten = sorted(_components(hoch), key=lambda c: -int(c.sum()))
    for nr, comp in enumerate(komponenten):
        zyklus = _rand_zyklus(comp)
        if len(zyklus) < 12:
            continue
        # Die groesste Flaeche bekommt die eingestellten Rampen, jede weitere
        # eine -- sonst waere eine Mesa unerreichbar.
        # The largest area gets the configured ramps, every other one -- a
        # mesa would otherwise be unreachable.
        luecken = max(ramps, 1) if nr == 0 else 1
        for bogen in _kontur_boegen(zyklus, comp, luecken, rng):
            if len(bogen) > 2 and bogen[0] == bogen[-1]:
                # Geschlossene Figur: die Sehne der Vereinfachung haette
                # Laenge null und saehe jeden Punkt als abstandslos -- also
                # in zwei Haelften teilen und wieder zusammensetzen.
                # Closed figure: the simplification chord would have zero
                # length and see every point as distance-free -- split into
                # two halves and rejoin.
                mitte = len(bogen) // 2
                punkte = (_kontur_vereinfachen(bogen[:mitte + 1])[:-1]
                          + _kontur_vereinfachen(bogen[mitte:]))
            else:
                punkte = _kontur_vereinfachen(bogen)
            punkte = [p for i, p in enumerate(punkte)
                      if i == 0 or p != punkte[i - 1]]
            if len(punkte) < 3 and len(set(punkte)) < 2:
                continue
            seite = _kontur_hand(punkte, comp)
            x0, y0 = punkte[0]
            fi = int(fam_field[y0, x0])
            familie = tm.families[fi] if 0 <= fi < len(tm.families) else "mud"
            if familie not in ("mud", "san"):
                # Nur Erde und Sand haben Klippenbloecke.
                # Only dirt and sand have cliff blocks.
                familie = "mud"
            maske, zellen = _klippe_algo().klippe_aus_linie(
                grid, punkte, seite, tm, rng, familie)
            maske_gesamt |= maske
            zellen_gesamt[zellen >= 0] = zellen[zellen >= 0]
    return maske_gesamt, zellen_gesamt


# Duerfen sich Klippenbloecke ueberlappen? Die Originalkarten tun es --
# gemessen beginnen nur 29-42 % ihrer Klippenlaeufe auf einem Dreierraster.
# Zum Vergleichen laesst es sich hier abschalten.
# May cliff blocks overlap? The original maps do -- measured, only 29-42 % of
# their cliff runs start on a three-cell grid. It can be switched off here for
# comparison.
UEBERLAPPEN = False


# Die Neigungen, in denen sich eine Klippe bauen laesst -- als (dx, dy) je
# Achtelkreis, daraus werden alle vier Quadranten gespiegelt.
#
# Gemessen an cm03: der waagerechte Versatz der linken Klippenkante von Zeile
# zu Zeile (919 Messungen).
#
#     Versatz je Zeile   Anteil   entspricht
#      0 Spalten          55,2 %   senkrecht
#     ±1 Spalte           24,5 %   45 Grad
#     ±2 Spalten           8,0 %   26,6 Grad
#     ±3 Spalten           6,6 %   18,4 Grad
#     ±4 Spalten           3,6 %   14,0 Grad
#
# Ueber die Haelfte aller Schritte ist senkrecht; darueber hinaus kommen nur
# Versaetze bis vier Spalten vor. Eine schraege Wand entsteht in den Originalen
# also nicht aus einem festen Verhaeltnis, sondern aus einer Treppe -- die
# Schraege bei (82,39) in cm03 wechselt zwischen -1 und -2 und ergibt so 1,6:1.
# Genau diese Verhaeltnisse sind hier die erlaubten Richtungen.
#
# The slopes a cliff can be built in, as (dx, dy) per octant, mirrored into all
# four quadrants. Measured on cm03: the horizontal offset of the left cliff edge
# from row to row, 919 samples. More than half of all steps are vertical, and
# beyond that only offsets up to four columns occur.
KLIPPEN_NEIGUNGEN = ((1, 0), (4, 1), (3, 1), (2, 1), (1, 1),
                     (1, 2), (1, 3), (1, 4), (0, 1))


def klippen_richtungen() -> list[tuple[int, int]]:
    """Alle erlaubten Baurichtungen als gekuerzte (dx, dy)."""
    aus = set()
    for dx, dy in KLIPPEN_NEIGUNGEN:
        for sx in (1, -1):
            for sy in (1, -1):
                aus.add((dx * sx, dy * sy))
    return sorted(aus)


def klippe_winkel_rasten(ax: int, ay: int, bx: int, by: int) -> tuple[int, int]:
    """Den Zielpunkt auf die naechste erlaubte Baurichtung ziehen.

    Gewaehlt wird die Richtung mit dem kleinsten Winkelabstand, und darauf die
    Laenge, die der Zeigerlage am naechsten kommt. So bleibt die gezogene
    Strecke gleich lang und dreht sich nur auf die erlaubte Neigung.

    Pull the target point onto the nearest permitted build direction: the
    direction with the smallest angular distance, at the length closest to where
    the cursor sits, so the stroke keeps its length and only rotates.
    """
    vx, vy = bx - ax, by - ay
    if vx == 0 and vy == 0:
        return bx, by
    laenge = (vx * vx + vy * vy) ** 0.5
    beste = None
    for dx, dy in klippen_richtungen():
        n = (dx * dx + dy * dy) ** 0.5
        # Kosinus des Winkels zwischen Zeigerrichtung und Kandidat.
        kos = (vx * dx + vy * dy) / (laenge * n)
        if beste is None or kos > beste[0]:
            beste = (kos, dx, dy, n)
    _k, dx, dy, n = beste
    schritte = max(1, int(round(laenge / n)))
    return ax + dx * schritte, ay + dy * schritte
