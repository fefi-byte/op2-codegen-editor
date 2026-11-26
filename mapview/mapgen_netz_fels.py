"""Felsgebiete des gelernten Generators: Lavakerne, ruhige Kachelmuster, Vulkane.

Das Skizzennetz kennt nur "Fels". In den Originalkarten sind das zwei Boeden:
normaler Fels (`rocbas1/2`) und dunkler Lavafels (`rocbas3-5`), dazwischen die
48 Uebergangskacheln `roctola`. Gemessen an 54 Originalen mit Fels: 62 % der
groesseren Felsgebiete haben einen Lavakern, im Mittel mit 31 % der Flaeche; er
ist geschlossen (3 Flecken je 128x128) und stoesst so gut wie nie ohne
Uebergang an Fels. Hier wird deshalb erst geplant, wo Lava liegt, und das
Kachelnetz malt nach diesem Plan.

Rock areas of the learned generator: lava cores, calm tile patterns, volcanoes.
The sketch network only knows "rock", but the original maps have two grounds:
normal rock (`rocbas1/2`) and dark lava rock (`rocbas3-5`) with the transition
tiles `roctola` in between. Where lava lies is planned first; the tile network
then paints to that plan.
"""
from __future__ import annotations

import numpy as np

import mapgen_netz_waende as waende

# Art einer Kachel bzw. Vorgabe einer Zelle. / Kind of a tile, plan of a cell.
SONST, FELS, LAVA, SAUM = 0, 1, 2, 3

# (erste, letzte Kachel, Breite des Musters) / (first, last tile, pattern width)
MUSTER = {"rocbas1": (439, 454, 4), "rocbas2": (455, 470, 4), "rocbas3": (471, 486, 4),
          "rocbas4": (487, 495, 3), "rocbas5": (496, 504, 3)}
ROCTOLA = (559, 606)

# Originale: wie oft ein Felsgebiet einen Lavakern hat, nach Groesse in Kacheln.
# Originals: how often a rock area has a lava core, by size in tiles.
KERN_CHANCE = ((300, 0.0), (1000, .45), (3000, .62), (1 << 30, .78))
# Kernanteil des Gebiets: Quantile 10/50/90 % der Originale.
KERN_ANTEIL = (.08, .31, .60)
# Anteil der Nebenmuster. / Share of the secondary patterns.
ANTEIL_ROCBAS2, ANTEIL_LAVA4, ANTEIL_LAVA5 = .11, .29, .24


def kachelart() -> np.ndarray:
    """Je Kachelnummer: Fels, Lavafels, Uebergang oder etwas anderes."""
    art = np.zeros(2048, np.int8)
    for name, (a, b, _w) in MUSTER.items():
        art[a:b + 1] = FELS if name in ("rocbas1", "rocbas2") else LAVA
    art[ROCTOLA[0]:ROCTOLA[1] + 1] = SAUM
    return art


def rauschen(form, rng, radien) -> np.ndarray:
    """Weiches Rauschen, Summe mehrerer Groessen, Streuung 1."""
    from mapgen_netz import _weich
    summe = np.zeros(form)
    for r, staerke in radien:
        f = _weich(rng.normal(size=form), r)
        summe += staerke * f / (f.std() + 1e-9)
    return summe / (summe.std() + 1e-9)


def _tiefe(m: np.ndarray, hoechstens: int) -> np.ndarray:
    """Abstand jeder Zelle zum Rand der Maske; der Kartenrand zaehlt nicht."""
    from mapgen_netz import _dehne
    d = np.zeros(m.shape)
    kern = m.copy()
    for _ in range(hoechstens):
        if not kern.any():
            break
        d += kern
        kern = kern & ~_dehne(~kern, 1)
    return d


def lavaplan(boden: np.ndarray, wand: np.ndarray, regler: float, rng) -> np.ndarray:
    """Wo im Fels Lavakerne liegen -> Maske auf dem Skizzenraster.

    Je Felsgebiet: Chance und Anteil nach den Originalen, dann die Felder mit der
    groessten Tiefe plus Rauschen -- der Kern folgt der Form des Gebiets.
    Per rock area: chance and share as in the originals, then the cells with the
    greatest depth plus noise, so the core follows the shape of the area."""
    from mapgen_netz import _dehne, _kleine_flecken_weg
    fels = (boden == waende.FELS) & ~_dehne(wand > 0, 2)
    lava = np.zeros(boden.shape, bool)
    if regler <= 0:
        return lava
    note = np.minimum(_tiefe(fels, 9), 9) / 9 \
        + .5 * rauschen(boden.shape, rng, ((5, 1.0), (2, .6)))
    nummern, n = waende.label(boden == waende.FELS)
    for i in range(1, n + 1):
        gebiet = nummern == i
        kacheln = 4 * int(gebiet.sum())
        chance = next(c for grenze, c in KERN_CHANCE if kacheln < grenze)
        zufall = rng.random(2)
        if zufall[0] >= min(1.0, 2 * regler * chance):
            continue
        anteil = float(np.interp(zufall[1], (0, .1, .5, .9, 1), (.04, *KERN_ANTEIL, .7)))
        anteil = min(.85, anteil * min(1.6, .5 + regler))
        moeglich = gebiet & (_tiefe(fels, 2) >= 2)     # Felsguertel bleibt / rock belt
        if moeglich.sum() < 30:
            continue
        wunsch = min(int(anteil * gebiet.sum()), int(.9 * moeglich.sum()))
        werte = np.where(moeglich, note, -np.inf).ravel()
        lava.ravel()[np.argpartition(-werte, wunsch)[:wunsch]] = True
        lava &= moeglich | ~gebiet
    # Loecher und Krumen weg, Rand weich. / Fill holes, drop crumbs, smooth rim.
    f = lava.astype(np.int64)
    for _ in range(3):
        p = np.pad(f, 1, mode="edge")
        s = sum(p[1 + dy:1 + dy + f.shape[0], 1 + dx:1 + dx + f.shape[1]]
                for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        f = np.where(s >= 5, 1, 0)
    f = _kleine_flecken_weg(f, np.zeros_like(f), 14)
    return (f == 1) & fels


def zellplan(lava: np.ndarray, boden: np.ndarray) -> np.ndarray:
    """Vorgabe je Kachel: Fels, Lava oder Saum (beides moeglich) im Felsgebiet."""
    from mapgen_netz import _dehne
    kl = np.kron(lava, np.ones((2, 2), bool))
    kb = np.kron(boden == waende.FELS, np.ones((2, 2), bool))
    plan = np.where(kb, np.where(kl, LAVA, FELS), SONST).astype(np.int8)
    rand = _dehne(kl, 1) & _dehne(~kl, 1)
    plan[rand & (kb | kl)] = SAUM
    return plan


def flaechen(form, rng) -> dict[str, np.ndarray]:
    """Wo welches Grundmuster liegt: zusammenhaengende Flaechen statt Wuerfeln."""
    r = rauschen(form, rng, ((9, 1.0), (4, .35)))
    q = rauschen(form, rng, ((6, 1.0), (3, .35)))
    f2 = r > np.quantile(r, 1 - ANTEIL_ROCBAS2)
    l4 = q < np.quantile(q, ANTEIL_LAVA4)
    l5 = q > np.quantile(q, 1 - ANTEIL_LAVA5)
    return {"rocbas1": ~f2, "rocbas2": f2, "rocbas3": ~l4 & ~l5, "rocbas4": l4,
            "rocbas5": l5}


class Felsmaler:
    """Gewichte fuers Kachelnetz und das Nachlegen der Grundmuster."""

    def __init__(self, vok: np.ndarray, plan: np.ndarray, rng):
        art = kachelart()[vok]
        self.vok, self.plan = vok, plan
        self.nummer = {int(t): i for i, t in enumerate(vok)}
        self.art = art
        self.idx = {k: np.flatnonzero(art == k) for k in (FELS, LAVA, SAUM)}
        self.wo = flaechen(plan.shape, rng)
        self.teil = {n: np.flatnonzero((vok >= a) & (vok <= b))
                     for n, (a, b, _w) in MUSTER.items()}

    def gewichte(self, p: np.ndarray, y: np.ndarray, x: np.ndarray) -> None:
        """Wahrscheinlichkeiten (n, Vokabular) an den Plan anpassen."""
        v = self.plan[y, x]
        faktor = {FELS: np.where(v == LAVA, 2e-3, 1.0),
                  LAVA: np.where((v == LAVA) | (v == SAUM), 1.0, 2e-3),
                  SAUM: np.where(v == SAUM, 6.0, 2e-3)}
        for art, f in faktor.items():
            p[:, self.idx[art]] *= f.astype(np.float32)[:, None]
        for name, maske in self.wo.items():
            p[:, self.teil[name]] *= np.where(maske[y, x], 1.0, .03).astype(np.float32)[:, None]

    def grundmuster(self, g: np.ndarray, rechts, unten, rng, behalten: float = .25):
        """Reine Fels- und Lavakacheln im 4x4- bzw. 3x3-Muster nachlegen, wie mit
        dem Pinsel der Originaleditoren; nur, wo alle vier Nachbarn passen.
        Lay pure rock and lava tiles in their brush pattern where all fit."""
        h, w = g.shape
        yy, xx = np.mgrid[0:h, 0:w]
        ziel = np.full(g.shape, -1)
        art = self.art[g]
        zufall = rng.random(g.shape) < behalten
        for name, (a, _b, breite) in MUSTER.items():
            passt = (art == (FELS if name in ("rocbas1", "rocbas2") else LAVA)) \
                & self.wo[name] & ~zufall
            nr = a + (yy % breite) * breite + xx % breite
            liste = np.array([self.nummer.get(int(t), -1) for t in range(a, a + breite ** 2)])
            ziel = np.where(passt, liste[nr - a], ziel)
        # Abwechselnd wie ein Schachbrett, damit Nachbarn nicht gleichzeitig wechseln.
        # Checkerboard order so that neighbours never change at once.
        for runde in range(4):
            m = (ziel >= 0) & (ziel != g) & ((yy + xx) % 2 == runde % 2)
            z = np.where(ziel >= 0, ziel, g)
            ok = np.ones(g.shape, bool)
            ok[:, 1:] &= rechts[g[:, :-1], z[:, 1:]]
            ok[:, :-1] &= rechts[z[:, :-1], g[:, 1:]]
            ok[1:] &= unten[g[:-1], z[1:]]
            ok[:-1] &= unten[z[:-1], g[1:]]
            g = np.where(m & ok, z, g)
        return g


def ohne_kante(rechts: np.ndarray, art: np.ndarray) -> np.ndarray:
    """Kachelpaare ohne direkten Wechsel Fels|Lava (Originale: 1 % der Paare)."""
    f, l = art == FELS, art == LAVA
    r = rechts.copy()
    r[np.ix_(f, l)] = False
    r[np.ix_(l, f)] = False
    return r


# Vulkane je Groesse: Stempel (Kachelgruppe) und Platz auf dem Skizzenraster.
# Volcanoes per size: stamp (tile group) and room on the sketch raster.
VULKANE = {"klein": (("rocvolc2",), FELS, 3),
           "mittel": (("rocvolc3", "rocvolc1"), LAVA, 4),
           "gross": (("rocvolc4",), LAVA, 6)}


def vulkanplaetze(boden, wand, anzahl, karte, rng, erlaubt=None) -> list:
    """Plaetze fuer die Vulkane auf dem Skizzenraster waehlen und den Boden dort
    auf Fels stellen -> [(y, x, Groesse, Lava?, Radius)]. Felsgebiete zuerst,
    fern von Waenden und voneinander.
    Choose volcano sites on the sketch raster and turn the ground there to rock:
    rock areas first, away from walls and from each other."""
    from mapgen_netz import _dehne
    h, w = boden.shape
    orte = []
    ys, xs = np.mgrid[0:h, 0:w]
    tiefe = _tiefe(boden == waende.FELS, 8)
    for groesse, zahl in zip(("gross", "mittel", "klein"), anzahl[::-1]):
        _namen, art, r = VULKANE[groesse]
        for _ in range(int(zahl)):
            lava = art == LAVA
            frei = ~_dehne(wand > 0, r + 3)
            if erlaubt is not None:
                frei &= erlaubt
            frei[:karte[0].start + r + 2] = frei[karte[0].stop - r - 2:] = False
            frei[:, :karte[1].start + r + 2] = frei[:, karte[1].stop - r - 2:] = False
            for y, x, _g, _l, rr in orte:
                frei &= (ys - y) ** 2 + (xs - x) ** 2 > (r + rr + 10) ** 2
            if not frei.any():
                break
            note = np.where(frei, tiefe + rng.random((h, w)) * 3, -1)
            y, x = np.unravel_index(int(note.argmax()), note.shape)
            boden[(ys - y) ** 2 + (xs - x) ** 2 <= (r + 2) ** 2] = waende.FELS
            orte.append((int(y), int(x), groesse, lava, r))
    return orte


def vulkane(t: np.ndarray, anzahl: int, tm, rng, gesperrt: np.ndarray,
            plaetze=()) -> list:
    """Vulkane in die Lavakerne stempeln -> Mittelpunkte. Der grosse steht auf
    Lavafels; passt er nirgends, einer der kleineren auf Fels.
    Stamp volcanoes into the lava cores; smaller ones on rock if none fits."""
    art = kachelart()[t]
    orte = []
    gruppen = {v[0]: v for v in tm.volcanoes}
    for y, x, groesse, lava, _r in plaetze:
        namen = [n for n in VULKANE[groesse][0] if n in gruppen]
        if groesse == "mittel" and not lava:
            namen = namen[::-1]
        for name in namen:
            _n, bw, bh, block = gruppen[name]
            boden = LAVA if int(block.min()) >= 653 else FELS
            # Am Platz suchen, notfalls ein Stueck daneben. Near the site.
            # Am Platz suchen, notfalls ein Stueck daneben; einzelne fremde
            # Kacheln im Rahmen werden durch die haeufigste Grundkachel ersetzt.
            # Search near the site; single foreign tiles in the frame are
            # replaced by the most common base tile.
            beste = None
            for dy in range(-6, 7):
                for dx in range(-6, 7):
                    y0, x0 = 2 * y + 1 - bh // 2 + dy, 2 * x + 1 - bw // 2 + dx
                    if y0 < 2 or x0 < 2 or y0 + bh + 2 > t.shape[0] or x0 + bw + 2 > t.shape[1]:
                        continue
                    feld = (slice(y0 - 1, y0 + bh + 1), slice(x0 - 1, x0 + bw + 1))
                    passt = float((art[feld] == boden).mean())
                    if passt >= .85 and not gesperrt[feld].any():
                        note = (round(passt, 2), -(abs(dy) + abs(dx)))
                        if beste is None or note > beste[0]:
                            beste = (note, y0, x0)
            if beste is None:
                continue
            _a, y0, x0 = beste
            feld = (slice(y0 - 1, y0 + bh + 1), slice(x0 - 1, x0 + bw + 1))
            gleich = t[art == boden]
            if len(gleich):
                grund = int(np.bincount(gleich).argmax())
                fremd = art[feld] != boden
                t[feld][fremd] = grund
                art[feld][fremd] = boden
            t[y0:y0 + bh, x0:x0 + bw] = block
            orte.append((x0 + bw // 2, y0 + bh // 2))
            art[y0:y0 + bh, x0:x0 + bw] = SONST
            break
    bloecke = sorted(tm.volcanoes, key=lambda v: -v[1] * v[2])
    for _ in range(anzahl):
        for _name, bw, bh, block in bloecke:
            boden = LAVA if block[0, 0] >= 0 and int(block.min()) >= 653 else FELS
            frei = (art == boden) & ~gesperrt
            s = np.pad(frei.astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
            hh, ww = bh + 2, bw + 2
            if t.shape[0] <= hh or t.shape[1] <= ww:
                continue
            voll = (s[hh:, ww:] - s[:-hh, ww:] - s[hh:, :-ww] + s[:-hh, :-ww]) == hh * ww
            stellen = [(y + 1, x + 1) for y, x in np.argwhere(voll).tolist()
                       if all(abs(y - a) + abs(x - b) > 40 for b, a in orte)]
            if not stellen:
                continue
            y, x = stellen[int(rng.integers(len(stellen)))]
            t[y:y + bh, x:x + bw] = block
            orte.append((x + bw // 2, y + bh // 2))
            art[y:y + bh, x:x + bw] = SONST
            break
    return orte
