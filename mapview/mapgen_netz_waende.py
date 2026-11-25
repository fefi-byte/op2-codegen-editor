"""Wandskizze aufraeumen: verbinden, verlaengern, ausduennen, einfaerben.

Teil des gelernten Kartengenerators (`mapgen_netz`). Die Skizze hat ein Feld je
2x2 Kacheln; `wand` ist 0 (keine Wand) oder 1..8, die Richtung, in die sie
faellt: O, SO, S, SW, W, NW, N, NO. Boden: 0 Erde, 1 Fels, 2 Sand, 3 Bewuchs.

Clean up the wall sketch: join, extend, thin, colour. Part of the learned map
generator. The sketch has one cell per 2x2 tiles; `wand` is 0 or 1..8, the
direction the wall falls towards: E, SE, S, SW, W, NW, N, NE.
"""
from __future__ import annotations

import heapq

import numpy as np

RICHTUNGEN = np.array([(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1),
                       (0, -1), (1, -1)], float)
_RN = RICHTUNGEN / np.hypot(RICHTUNGEN[:, 0], RICHTUNGEN[:, 1])[:, None]
NORD = (6, 7, 8)                 # NW, N, NO: eine Zelle dick / one cell thick
ERDE, FELS, SAND, BEWUCHS = 0, 1, 2, 3

# Wie sich die Fallrichtung beim Spiegeln aendert.
# How the fall direction changes when mirroring.
SPIEGEL_X = np.array([0, 5, 4, 3, 2, 1, 8, 7, 6], np.int64)
SPIEGEL_Y = np.array([0, 1, 8, 7, 6, 5, 4, 3, 2], np.int64)
DREHEN = np.array([0, 5, 6, 7, 8, 1, 2, 3, 4], np.int64)


def tangente(r: int) -> np.ndarray:
    """Laufrichtung einer Wand, Hochseite links. / Walking direction, high side left."""
    return np.array([_RN[r][1], -_RN[r][0]])


def fallrichtung(t: np.ndarray) -> int:
    return int((_RN @ np.array([-t[1], t[0]])).argmax())


def label(maske: np.ndarray) -> tuple[np.ndarray, int]:
    """Zusammenhaengende Flaechen (8er) -> (Nummern ab 1, Anzahl).

    Laeufe je Zeile, vereinigt ueber Union-Find -- ohne SciPy.
    Connected areas (8-neighbourhood) via row runs and union-find, no SciPy."""
    h, w = maske.shape
    eltern: list[int] = []

    def wurzel(i):
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    zeilen = []
    vorige: list[tuple[int, int, int]] = []
    for y in range(h):
        d = np.flatnonzero(np.diff(np.concatenate(([0], maske[y].view(np.int8), [0]))))
        laeufe = []
        j = 0
        for a, b in zip(d[::2].tolist(), d[1::2].tolist()):
            nr = len(eltern)
            eltern.append(nr)
            while j < len(vorige) and vorige[j][1] < a:
                j += 1
            k = j
            while k < len(vorige) and vorige[k][0] <= b:
                p, q = wurzel(vorige[k][2]), wurzel(nr)
                eltern[max(p, q)] = min(p, q)
                k += 1
            laeufe.append((a, b, nr))
        zeilen.append(laeufe)
        vorige = laeufe
    aus = np.zeros((h, w), np.int32)
    nummern: dict[int, int] = {}
    for y, laeufe in enumerate(zeilen):
        for a, b, nr in laeufe:
            aus[y, a:b] = nummern.setdefault(wurzel(nr), len(nummern) + 1)
    return aus, len(nummern)


def ketten(w: np.ndarray) -> list[tuple[list, bool]]:
    """Wandfelder zu gerichteten Ketten verbinden -> [(Felder, geschlossen)]."""
    h, q = w.shape
    kand = []
    for y, x in np.argwhere(w > 0).tolist():
        r = int(w[y, x]) - 1
        d, t = _RN[r], tangente(r)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                p = (y + dy, x + dx)
                if not (dy or dx) or not (0 <= p[0] < h and 0 <= p[1] < q) or not w[p]:
                    continue
                v = np.array([dx, dy], float)
                lang = np.hypot(*v)
                s = v / lang
                r2 = int(w[p]) - 1
                a, b, c = s @ t, s @ tangente(r2), d @ _RN[r2]
                if a + b > .25 and a > -.2 and b > -.2 and c > -.4:
                    kand.append((a + b + .6 * c - .5 * lang, (y, x), p))
    nach: dict = {}
    vor: dict = {}
    for _n, p, z in sorted(kand, key=lambda k: -k[0]):
        if p in nach or z in vor:
            continue
        e, l = z, 0
        while e in nach and l < 5:
            e = nach[e]
            l += 1
        if e == p:
            continue
        nach[p] = z
        vor[z] = p
    alle = [tuple(p) for p in np.argwhere(w > 0).tolist()]
    aus = []
    gesehen = set()
    for p in [x for x in alle if x not in vor] + alle:
        if p in gesehen:
            continue
        kette = [p]
        gesehen.add(p)
        while kette[-1] in nach and nach[kette[-1]] not in gesehen:
            kette.append(nach[kette[-1]])
            gesehen.add(kette[-1])
        aus.append((kette, nach.get(kette[-1]) == p and len(kette) > 3))
    return aus


def _zwischen(a, b) -> list:
    n = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    return [(int(round(a[0] + (b[0] - a[0]) * i / n)),
             int(round(a[1] + (b[1] - a[1]) * i / n))) for i in range(1, n)]


def putzen(w: np.ndarray, zone: np.ndarray, rng: np.random.Generator,
           mindest: int = 7, weit: int = 7) -> np.ndarray:
    """Wandstuecke verbinden, in engen Zonen verlaengern, Schnipsel loeschen.

    Das Skizzenmodell liefert viele kurze Stuecke; in den Originalen sind Waende
    lang. Join wall pieces, extend them in tight zones, drop snippets."""
    h, q = w.shape
    alle = ketten(w)
    richtung = {p: int(w[p]) - 1 for kette, _z in alle for p in kette}
    stuecke = {i: list(k) for i, (k, zu) in enumerate(alle) if not zu}
    ringe = [list(k) for k, zu in alle if zu]

    def endrichtung(kette, hinten):
        s = kette[-4:] if hinten else kette[:4]
        t = tangente(richtung[s[-1] if hinten else s[0]])
        if len(s) > 1:
            v = np.array([s[-1][1] - s[0][1], s[-1][0] - s[0][0]], float)
            n = np.hypot(*v)
            if n > 0:
                return .6 * v / n + .4 * t
        return t

    # 1. Verbinden: kurze, gut fluchtende Luecken zuerst.
    # 1. Join: short, well-aligned gaps first.
    heap: list = []
    enden: dict = {}

    def merken(i):
        k = stuecke[i]
        enden[i] = (k[0], k[-1], endrichtung(k, False), endrichtung(k, True))

    def nah(i, j):
        a, b = enden[i][1], enden[j][0]
        return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= weit

    def paar(i, j):
        a1, ta = enden[i][1], enden[i][3]
        b0, tb = enden[j][0], enden[j][2]
        v = np.array([b0[1] - a1[1], b0[0] - a1[0]], float)
        lang = np.hypot(*v)
        if lang < 1 or lang > weit:
            return
        s = v / lang
        f = (s @ ta, s @ tb, _RN[richtung[a1]] @ _RN[richtung[b0]])
        if lang <= 2.9:
            gut = f[0] > -.1 and f[1] > -.1 and f[2] > -.3
        else:
            gut = f[0] > .45 and f[1] > .45 and f[2] > .1
        if gut:
            note = (sum(f) - .35 * lang
                    + .1 * min(4, (len(stuecke[i]) + len(stuecke[j])) / 8))
            heapq.heappush(heap, (-note, i, j))

    for i in stuecke:
        merken(i)
    for i in stuecke:
        for j in stuecke:
            if i != j and nah(i, j):
                paar(i, j)
    nr = len(alle)
    while heap:
        _n, i, j = heapq.heappop(heap)
        if i not in stuecke or j not in stuecke:
            continue
        a, b = stuecke[i], stuecke[j]
        li = _zwischen(a[-1], b[0])
        if any(p in richtung for p in li):
            continue
        pts = [a[-1]] + li + [b[0]]
        for k, p in enumerate(li):
            t = np.array([pts[k + 2][1] - pts[k][1], pts[k + 2][0] - pts[k][0]], float)
            richtung[p] = fallrichtung(t / max(1e-6, np.hypot(*t)))
        del stuecke[i], stuecke[j]
        stuecke[nr] = a + li + b
        merken(nr)
        for k in stuecke:
            if k != nr:
                if nah(nr, k):
                    paar(nr, k)
                if nah(k, nr):
                    paar(k, nr)
        nr += 1

    # 2. Schnipsel weg. / 2. Drop snippets.
    offen = []
    for kette in stuecke.values():
        if len(kette) >= mindest:
            offen.append(kette)
        else:
            for p in kette:
                richtung.pop(p, None)
    for kette in ringe:
        if len(kette) < 6:
            for p in kette:
                richtung.pop(p, None)

    # 3. In engen Zonen weiterziehen, bis kurz vor die naechste Wand.
    # 3. In tight zones extend up to just before the next wall.
    belegt = np.zeros((h, q), bool)
    for p in richtung:
        belegt[p] = True
    for kette in sorted(offen, key=len):
        for hinten in (True, False):
            t = endrichtung(kette, hinten) * (1 if hinten else -1)
            y, x = (float(v) for v in (kette[-1] if hinten else kette[0]))
            lang = int(rng.integers(4, 13))
            dreh = float(rng.normal(0, .06))
            eigen = set(kette)
            neu = []
            for _ in range(lang):
                a = np.arctan2(t[1], t[0]) + dreh
                t = np.array([np.cos(a), np.sin(a)])
                x += t[0]
                y += t[1]
                p = (int(round(y)), int(round(x)))
                if not (0 <= p[0] < h and 0 <= p[1] < q) or zone[p] != 1:
                    break
                if p in eigen:
                    continue
                if any(0 <= c < h and 0 <= d < q and belegt[c, d] and (c, d) not in eigen
                       for c in range(p[0] - 2, p[0] + 3)
                       for d in range(p[1] - 2, p[1] + 3)):
                    break
                neu.append(p)
                eigen.add(p)
            if len(neu) < 2:
                continue
            for p in neu:
                richtung[p] = fallrichtung(t if hinten else -t)
                belegt[p] = True
            if hinten:
                kette.extend(neu)
            else:
                kette[:0] = neu[::-1]
    aus = np.zeros_like(w)
    for p, r in richtung.items():
        aus[p] = r + 1
    return aus


def nordkanten_ausduennen(w: np.ndarray, abstand: int = 3) -> np.ndarray:
    """Parallele Nordkanten dicht uebereinander: die kuerzere weicht.

    Nordkanten sind duenn; zwei nebeneinander sehen nach Doppelstrich aus.
    Parallel north edges close together: the shorter one gives way."""
    aus = w.copy()
    h = w.shape[0]
    lang = {p: len(k) for k, _z in ketten(w) for p in k}
    felder = sorted((tuple(p) for p in np.argwhere(np.isin(w, NORD)).tolist()),
                    key=lambda p: lang.get(p, 0))
    for y, x in felder:
        if not aus[y, x]:
            continue
        for dy in [*range(-abstand, -1), *range(2, abstand + 1)]:
            c = y + dy
            if 0 <= c < h and aus[c, x] in NORD and lang.get((c, x), 0) >= lang.get((y, x), 0):
                aus[y, x] = 0
                break
    return aus


def ein_boden_je_wand(w: np.ndarray, boden: np.ndarray) -> np.ndarray:
    """Jede Wand samt Saum bekommt einen Boden (Erde oder Sand, nach Mehrheit).

    Danach verschwinden einzelne 4x4-Bloecke. Every wall and its rim get one
    ground by majority; after that single 4x4 blocks are dissolved."""
    h, q = w.shape
    breit = np.zeros((h, q), bool)
    k = w > 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            breit[max(0, dy):h + min(0, dy), max(0, dx):q + min(0, dx)] |= \
                k[max(0, -dy):h - max(0, dy), max(0, -dx):q - max(0, dx)]
    nummern, n = label(breit)
    nummern = np.where(k, nummern, 0)
    b = boden.copy()
    waende = []
    for i in range(1, n + 1):
        z = np.argwhere(nummern == i)
        if len(z):
            f = np.bincount(b[z[:, 0], z[:, 1]], minlength=5)
            waende.append((len(z), SAND if 2 * f[SAND] > f.sum() else ERDE, z))
    for _n, g, z in sorted(waende, key=lambda v: v[0]):     # grosse gewinnen / large win
        for y, x in z.tolist():
            b[max(0, y - 2):y + 3, max(0, x - 2):x + 3] = g
    grob = np.stack([(b.reshape(h // 2, 2, q // 2, 2) == i).sum((1, 3))
                     for i in range(5)]).argmax(0)
    for _ in range(2):
        p = np.pad(grob, 1, mode="edge")
        nachbarn = [p[1 + dy:1 + dy + grob.shape[0], 1 + dx:1 + dx + grob.shape[1]]
                    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0))]
        gleich = sum((v == grob).astype(int) for v in nachbarn)
        for y, x in np.argwhere(gleich == 0).tolist():
            grob[y, x] = np.bincount([v[y, x] for v in nachbarn], minlength=5).argmax()
    return np.kron(grob, np.ones((2, 2), np.int64))
