"""Grossform der Karte: Hochflaechen und Kessel, deren Raender Klippen werden.

Teil des gelernten Kartengenerators (`mapgen_netz`). Das Skizzennetz sieht nur
seine Umgebung; hier entsteht vorher ein Hoehenplan der ganzen Karte. Seine
Hoehenlinien gehen als feste Klippen ins Netz und halten die Boeden auseinander.

The large shape of the map: uplands and basins whose rims become cliffs. The
sketch network only sees its surroundings, so a height plan of the whole map is
made first. Its contours are given to the network as cliffs and separate grounds.
"""
from __future__ import annotations

import numpy as np

import mapgen_netz_waende as waende
from mapgen_netz_fels import rauschen

GROESSEN = ((11, 1.0), (5, .45))     # Rauschradien in Feldern zu 2x2 Kacheln
MINDEST = 60                         # kleinste Hochflaeche in Feldern
TREPPE = 3                           # gerade Stuecke in Feldern, wie im Original
GESCHLOSSEN = 180                    # bis hier ohne Auffahrt / closed up to here
KUPPEN = 3                           # je 128x128 bei voller Staerke
KURZ = 9                             # kuerzeste Klippe / shortest cliff
LUECKE = (5, 1.0), (2, .5)


def _glatt(m: np.ndarray, mal: int = 2) -> np.ndarray:
    """Mehrheit der 3x3-Nachbarn: keine Zacken. / 3x3 majority: no jags."""
    for _ in range(mal):
        p = np.pad(m.astype(int), 1, mode="edge")
        h, w = m.shape
        m = sum(p[1 + a:1 + a + h, 1 + b:1 + b + w]
                for a in (-1, 0, 1) for b in (-1, 0, 1)) >= 5
    return m


def _flaechen(m: np.ndarray, mindest: int) -> np.ndarray:
    nummern, n = waende.label(m)
    gross = np.bincount(nummern.ravel(), minlength=n + 1) >= mindest
    gross[0] = False
    return gross[nummern]


def ohne_schnipsel(wand: np.ndarray, kurz: int, leer: int = 9) -> np.ndarray:
    """Zusammenhaengende Wandstuecke unter `kurz` Feldern loeschen.
    Drop connected wall pieces below `kurz` cells."""
    k = (wand > 0) & (wand < 9)
    return np.where(k & ~_flaechen(k, kurz), leer, wand)


def _rand(wand, hoch, wo) -> None:
    """Rand der hohen Seite als Klippe eintragen; sie faellt vom Hohen weg.
    Enter the rim of the high side as a cliff falling away from it."""
    from mapgen_netz import _weich
    p = np.pad(hoch, 1, mode="edge")
    rand = hoch & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])
    gy, gx = np.gradient(_weich(hoch.astype(float), 1))
    for y, x in np.argwhere(rand & wo).tolist():
        v = np.array([-gx[y, x], -gy[y, x]])
        if np.hypot(*v) > 1e-6:
            wand[y, x] = int((waende._RN @ v).argmax()) + 1


def _treppe(m: np.ndarray, n: int) -> np.ndarray:
    """Grob gerastert: die Klippen laufen in geraden Stufen wie im Original.
    Coarse raster: cliffs run in straight steps as in the originals."""
    h, w = m.shape
    a, b = h // n * n, w // n * n
    aus = m.copy()
    grob = m[:a, :b].reshape(a // n, n, b // n, n).mean((1, 3)) >= .5
    aus[:a, :b] = np.kron(grob, np.ones((n, n))) > 0
    return aus


def _bergterrassen(wand, eng, dichte: float, rng, ruhe: float = 0.0) -> None:
    """Im Berg ineinanderliegende Hoehenlinien statt einzelner Stuecke.
    Nested contours inside a mountain instead of single pieces."""
    from mapgen_netz import _weich
    if not eng.any():
        return
    hoehe = 2.2 * _weich(eng.astype(float), 3) + .5 * rauschen(eng.shape, rng, ((3, 1.0), (2, .4)))
    luecke = rauschen(eng.shape, rng, ((3, 1.0),))
    stufen = 1 + int(3 * dichte * (1 - ruhe) + .5)
    for q in np.linspace(.15, .80, stufen):
        m = _flaechen(_treppe(_glatt(hoehe > np.quantile(hoehe[eng], q), 2 + int(4 * ruhe)),
                                    2 + int(ruhe > .4)),
                      12 + int(30 * ruhe))
        frei = wand == 9
        n = np.pad(wand < 9, 1)
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                frei &= ~n[1 + a:n.shape[0] - 1 + a, 1 + b:n.shape[1] - 1 + b]
        _rand(wand, m, eng & frei & (luecke > np.quantile(luecke, .12)))


def _kuppen(wand, raster, zahl: int, rng) -> None:
    """Kleine ringsum geschlossene Kuppen, wie sie die Originale oft haben.
    Small hills closed all around, common in the originals."""
    from mapgen_netz import _dehne
    h, w = wand.shape
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(20 * zahl):
        if zahl <= 0:
            break
        y, x = int(rng.integers(6, h - 6)), int(rng.integers(6, w - 6))
        a, b = rng.uniform(1.6, 3.6, 2)
        m = ((yy - y) / a) ** 2 + ((xx - x) / b) ** 2 <= 1
        if rng.random() < .5:                    # L-Form / L shape
            c, d = rng.uniform(1.4, 2.4, 2)
            dy, dx = rng.choice((-1, 1), 2)
            m |= (abs(yy - y - dy * a * .8) <= c) & (abs(xx - x - dx * b * .8) <= d)
        if (wand[_dehne(m, 2)] < 9).any() or raster[y, x] == 2 and rng.random() < .6:
            continue
        m = _treppe(m, 2)
        _rand(wand, m, m)
        zahl -= 1


def grossform(raster: np.ndarray, staerke: float, rng, dichte: float = .5,
              ruhe: float = 0.0, rau=None) -> np.ndarray:
    """-> Wandvorgabe je Feld: 9 = offen, sonst die Fallrichtung.
    Wall preset per cell: 9 = open, else the fall direction."""
    from mapgen_netz import _dehne
    h, w = raster.shape
    wand = np.full((h, w), 9, np.int64)
    if staerke <= 0:
        return wand
    hoehe = rauschen((h, w), rng, tuple((int(r * (1 + .5 * ruhe)), a) for r, a in GROESSEN))
    tabu = _dehne(raster == 1, 2)
    luecke = rauschen((h, w), rng, LUECKE)
    offen = np.quantile(luecke, .25 * (1 - .5 * staerke))
    anteil = .08 + .135 * staerke
    # Verlauf: Hochflaechen und Kessel auf die bergige Seite.
    # Gradient: uplands and basins towards the rugged side.
    neigung = 0 if rau is None else 1.6 * (rau - .5)
    oben, unten = hoehe + neigung, hoehe - neigung
    for nr, m in enumerate((oben > np.quantile(oben, 1 - anteil),
                            unten < np.quantile(unten, .8 * anteil))):
        m = _flaechen(_glatt(m, 2 + int(5 * ruhe)), int(MINDEST * (1 + 1.5 * ruhe)))
        # Kleine Hochflaechen bleiben ganz zu, grosse bekommen Auffahrten.
        # Small uplands stay closed, large ones get ramps.
        gross = _dehne(_flaechen(m, GESCHLOSSEN), 2)
        m = _treppe(m, TREPPE)
        _rand(wand, m if nr == 0 else ~m, ~tabu & ((luecke > offen) | ~gross))
    wand = ohne_schnipsel(wand, int(KURZ * (1 + ruhe)))
    _bergterrassen(wand, raster == 1, dichte, rng, ruhe)
    _kuppen(wand, raster, int(round(KUPPEN * (1 - .6 * ruhe) * staerke * h * w / 4096)), rng)
    return wand
