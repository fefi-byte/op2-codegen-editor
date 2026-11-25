"""Berge, Schluchten, Hochebenen und Taeler: Formen und Waende.

Teil des Kartengenerators; `mapgen` reicht alles weiter.

Vier Zonen, unterschieden danach, ob man dort bauen kann:

    Berg        kein Bauplatz   enge Stufen, Aussenwand geschlossen
    Schlucht    kein Bauplatz   schmaler Einschnitt durch den Berg, Durchfahrt
    Hochebene   Bauplatz        eine Stufe, grosse Flaeche, zwei Auffahrten
    Tal         Bauplatz        breiter Einschnitt durch die Bergkette

`berg_plan` legt nur die Formen fest (Masken), `berge_zeichnen` belegt sie mit
Waenden. Wer zeichnet, ist austauschbar: OP2MappingLib (`editor/app/maplib.py`)
oder der Python-Loeser (`PythonZeichner`).

Mountains, gorges, plateaus and valleys: shapes and walls. Four zones, told
apart by whether you can build there. `berg_plan` fixes the shapes only (masks),
`berge_zeichnen` covers them with walls. The drawer is interchangeable:
OP2MappingLib or the Python solver.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import celltypes
import shapegen
from mapgen_basis import (
    SYM_MIRROR_X,
    SYM_MIRROR_Y,
    SYM_NONE,
    SYM_QUAD,
    SYM_ROT180,
    MapGenParams,
    _cell_types,
)
from mapgen_felder import _apply_symmetry, _components
from mapgen_relief import _dehne, _kontur_hand, _kontur_vereinfachen, _rand_zyklus
from mapgen_wege import _groesstes_gebiet, _passable_mask

# Kantenlaenge des freien Quadrats, ab dem eine Flaeche als Bauplatz gilt. Das
# groesste Gebaeude (Raumhafen) belegt 5x4, dazu ringsum eine Zelle.
# Side of the free square from which an area counts as building ground: the
# largest structure covers 5x4, plus one cell all round.
BAUPLATZ = 7

# Abstand zweier Stufen in Zellen: (Seite und Sued, Nord). Nordwaende sind eine
# Zelle dick, die anderen drei -- unter 4 Zellen schneiden sich die Waende
# gegenseitig ab. Gemessen ist der ECHTE Abstand: in Treppenschritten gezaehlt
# bleiben an Schraegen statt 4 nur 2,8 Zellen.
# Distance between two terraces: (sides and south, north). North walls are one
# cell thick, the others three; below 4 cells the walls cut into each other.
# This is the true distance: counted in steps, slopes only get 2.8 instead of 4.
ABSTAND_ENG = (4.0, 3.0)
ABSTAND_WEIT = (7.0, 5.0)

# Halbe Mindestbreite von Bergteilen und Buchten: zwei Waende je drei Zellen
# plus etwas dazwischen.
# Half the minimum width of mountain parts and bays: two walls plus some room.
HALS_HALB = 4.5

# Wie breit Schlucht und Tal von der Mitte bis zur Wandlinie sind.
# Half width of gorge and valley up to the wall line.
SCHLUCHT_HALB = 4.6
TAL_HALB = 13.0

KLIPPEN_ZELLEN = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
                  celltypes.CLIFFS_LOW_SIDE)


@dataclass
class Einschnitt:
    """Schlucht oder Tal: Sohle und ihre beiden Enden."""
    sohle: np.ndarray                # Mittelstreifen / centre strip
    flaeche: np.ndarray              # zwischen den Waenden / between the walls
    ende_a: np.ndarray
    ende_b: np.ndarray


@dataclass
class BergPlan:
    """Formen der Zonen, noch ohne eine Kachel. / Zone shapes, no tiles yet."""
    stufen: list[np.ndarray] = field(default_factory=list)   # aussen -> innen
    hochebenen: list[np.ndarray] = field(default_factory=list)
    schluchten: list[Einschnitt] = field(default_factory=list)
    taeler: list[Einschnitt] = field(default_factory=list)

    def alles(self) -> np.ndarray | None:
        masken = self.stufen[:1] + self.hochebenen
        return np.logical_or.reduce(masken) if masken else None

    def saum(self) -> np.ndarray | None:
        """Flaeche, die einfarbig sein muss, damit die Waende passen.
        Area that has to be one ground so the walls fit."""
        # Berge ganz, Hochebenen nur am Rand -- oben bleibt ihr eigener Boden.
        # Mountains entirely, plateaus along the edge only; their top keeps its
        # own ground.
        teile = [_weite(m, 5) for m in self.stufen[:1]]
        teile += [_weite(p, 5) & ~_schrumpf(p, 6, 6) for p in self.hochebenen]
        return np.logical_or.reduce(teile) if teile else None


def berge_gewuenscht(params: MapGenParams) -> bool:
    return params.berge > 0 or params.hochebenen > 0


# --------------------------------------------------------------------------
# Formen / shapes

def _rauschen(h: int, w: int, rng: np.random.Generator, zelle: int) -> np.ndarray:
    """Weiches Rauschen mit fester Zellgroesse statt fester Zellzahl -- die
    Formen sollen auf jeder Kartengroesse gleich gross sein.
    Smooth noise with a fixed cell SIZE, so shapes are equally large on every
    map size."""
    g = rng.random((h // zelle + 3, w // zelle + 3))
    ys, xs = np.arange(h) / zelle, np.arange(w) / zelle
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = ys - y0, xs - x0
    fy = (fy * fy * (3 - 2 * fy))[:, None]
    fx = (fx * fx * (3 - 2 * fx))[None, :]
    a, b = g[np.ix_(y0, x0)], g[np.ix_(y0, x0 + 1)]
    c, d = g[np.ix_(y0 + 1, x0)], g[np.ix_(y0 + 1, x0 + 1)]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _schrumpf(m: np.ndarray, seite: float, nord: float) -> np.ndarray:
    """Maske um den echten Abstand schrumpfen; im Norden um `nord`.
    Shrink a mask by the true distance; by `nord` on its north side."""
    h, w = m.shape
    out = m.copy()
    r = int(np.ceil(max(seite, nord)))
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            ry = nord if dy < 0 else seite
            if (dx or dy) and (dx / seite) ** 2 + (dy / ry) ** 2 <= 1:
                v = np.zeros_like(m)
                v[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)] = \
                    m[max(0, dy):h - max(0, -dy), max(0, dx):w - max(0, -dx)]
                out &= v
    return out


def _weite(m: np.ndarray, r: float) -> np.ndarray:
    """Runde Dehnung; ausserhalb der Karte gilt als frei.
    Round dilation; outside the map counts as empty."""
    n = int(np.ceil(r))
    return ~_schrumpf(np.pad(~m, n, constant_values=True), r, r)[n:-n, n:-n]


def _erodiere(m: np.ndarray, n: int) -> np.ndarray:
    return m & ~_dehne(~m, n)


def _saeubern(m: np.ndarray, mindest: int, rand: int = 5) -> np.ndarray:
    f = shapegen.entferne_kleinkram(
        shapegen.glaette(m.astype(np.int8), 3), mindest=mindest)
    f[:rand] = 0
    f[-rand:] = 0
    f[:, :rand] = 0
    f[:, -rand:] = 0
    return f > 0


def _spiegeln(m: np.ndarray, sym: str) -> np.ndarray:
    if sym == SYM_NONE:
        return m
    return _apply_symmetry(m.astype(np.int8), sym) > 0


def _ketten(h: int, w: int, rng: np.random.Generator, sym: str) -> list[dict]:
    """Mittelpunkte, Richtungen und Groessen der Bergketten -- eine je 128er-
    Kartenflaeche. / One mountain chain per 128x128 of map area."""
    anzahl = max(1, int(round(w * h / (128 * 128))))
    lang = 0.45 * min(min(w, h), 128)
    kurz = 0.38 * lang
    ketten: list[dict] = []
    for _ in range(anzahl):
        bester = None
        for _v in range(12):
            if anzahl == 1:
                cx = w / 2 + float(rng.uniform(-.06, .06)) * w
                cy = h / 2 + float(rng.uniform(-.06, .06)) * h
            else:
                cx = float(rng.uniform(.18, .82)) * w
                cy = float(rng.uniform(.22, .78)) * h
            # Bei Symmetrie zaehlt nur die Grundhaelfte, der Rest wird gespiegelt.
            # With symmetry only the base half counts, the rest is mirrored.
            if sym in (SYM_MIRROR_X, SYM_QUAD) and cx >= w / 2:
                cx = w - 1 - cx
            if sym in (SYM_MIRROR_Y, SYM_ROT180, SYM_QUAD) and cy >= h / 2:
                cy = h - 1 - cy
            ab = min([np.hypot(cx - k["cx"], cy - k["cy"]) for k in ketten] or [1e9])
            if bester is None or ab > bester[0]:
                bester = (ab, cx, cy)
        # Nicht laenger als die schmale Kartenseite hergibt: quer auf einer
        # 128x64-Karte laege die Kette sonst von Rand zu Rand.
        # No longer than the narrow side allows.
        winkel = float(rng.uniform(-.6, .6))
        if h >= w and rng.random() < .5 or h > w:
            winkel += np.pi / 2
        ketten.append({"cx": bester[1], "cy": bester[2], "winkel": winkel,
                       "lang": lang if min(w, h) >= 128 else lang * 1.6,
                       "kurz": kurz, "kipp": float(rng.uniform(0, 2 * np.pi))})
    return ketten


def berg_plan(params: MapGenParams, sperr: np.ndarray | None = None) -> BergPlan:
    """Die Formen aller Zonen festlegen. `sperr`: Zellen, die frei bleiben.

    Das Hoehenfeld ist eine verzerrte Ellipse je Kette plus Grate: die
    Verzerrung der Koordinaten gibt Sporne und Buchten, die Grate Einschnuerungen.
    Jede weitere Stufe bekommt je Gipfelblock ihre eigene Schwelle auf einem
    gekippten Feld -- so entstehen steile und flache Seiten statt
    Zwiebelschalen.

    Fix the shapes of all zones. The height field is a warped ellipse per chain
    plus ridges; each further terrace gets its own threshold per summit on a
    tilted field, which gives steep and gentle sides instead of onion rings.
    """
    plan = BergPlan()
    if not berge_gewuenscht(params):
        return plan
    h, w = params.height, params.width
    # Eigener Zufall: ohne Berge bleibt jede bisherige Karte bitgleich.
    # Own randomness: without mountains every existing map stays bit-identical.
    rng = np.random.default_rng([int(params.seed) & 0xFFFFFFFF, 4242])
    frei = np.zeros((h, w), bool) if sperr is None else _spiegeln(sperr, params.symmetry)
    ys, xs = np.mgrid[:h, :w].astype(float)
    if params.berge > 0:
        _plane_berge(plan, params, rng, frei, xs, ys)
    _plane_hochebenen(plan, params, rng, frei)
    return plan


def _plane_berge(plan, params, rng, frei, xs, ys) -> None:
    h, w = frei.shape
    sym = params.symmetry
    X = xs + (_rauschen(h, w, rng, 16) - .5) * 22 + (_rauschen(h, w, rng, 8) - .5) * 9
    Y = ys + (_rauschen(h, w, rng, 16) - .5) * 22 + (_rauschen(h, w, rng, 8) - .5) * 9
    ketten = _ketten(h, w, rng, sym)
    felder = []
    for k in ketten:
        c, s = np.cos(k["winkel"]), np.sin(k["winkel"])
        u = (X - k["cx"]) * c + (Y - k["cy"]) * s
        v = -(X - k["cx"]) * s + (Y - k["cy"]) * c
        felder.append(1 - np.sqrt((u / k["lang"]) ** 2 + (v / k["kurz"]) ** 2))
    naechste = np.argmax(felder, axis=0)
    grat = 1 - np.abs(2 * _rauschen(h, w, rng, 14) - 1)
    f = (np.max(felder, axis=0) + .42 * (_rauschen(h, w, rng, 18) - .5)
         + .32 * (grat - .6) + .18 * (_rauschen(h, w, rng, 7) - .5))
    # Zum Kartenrand weich abfallen: eine Wand, die am Rand entlanglaeuft, ist
    # ein gerader Strich.
    # Fall off softly towards the map border; a wall along it is a straight line.
    rand = np.minimum(np.minimum(xs, w - 1 - xs), np.minimum(ys, h - 1 - ys))
    f = f - np.clip((15 - rand) / 10, 0, 1) * 1.2
    kipp = np.zeros((h, w))
    for nr in range(len(ketten)):
        k = ketten[nr]
        kipp = np.where(naechste == nr, (np.cos(k["kipp"]) * (xs - k["cx"])
                                         + np.sin(k["kipp"]) * (ys - k["cy"])) / 60., kipp)
    if sym != SYM_NONE:
        f, kipp = _apply_symmetry(f, sym), _apply_symmetry(kipp, sym)
    dichte = float(np.clip(params.berg_dichte, 0, 1))
    seite = ABSTAND_WEIT[0] + dichte * (ABSTAND_ENG[0] - ABSTAND_WEIT[0])
    nord = ABSTAND_WEIT[1] + dichte * (ABSTAND_ENG[1] - ABSTAND_WEIT[1])
    offen = ~_dehne(frei, 6)
    if not offen.any():
        return
    # Schwelle so, dass der gewuenschte Anteil der Karte herauskommt.
    # Threshold chosen so the requested share of the map results.
    ziel = min(.9, params.berge * h * w / float(offen.sum()))
    roh = (f > np.quantile(f[offen], 1 - ziel)) & offen
    bleibt = offen.copy()

    # Taeler und Schluchten dorthin legen, wo am meisten Berg durchschnitten
    # wird -- sonst geht der Schnitt am Berg vorbei.
    # Put valleys and gorges where they cut through the most mountain.
    schnitte = []
    for i, art in enumerate(["tal"] * params.taeler + ["schlucht"] * params.schluchten):
        halb = TAL_HALB if art == "tal" else SCHLUCHT_HALB
        beste = None
        for k in ketten:
            c, sn = np.cos(k["winkel"]), np.sin(k["winkel"])
            uu = (xs - k["cx"]) * c + (ys - k["cy"]) * sn
            vv = -(xs - k["cx"]) * sn + (ys - k["cy"]) * c
            ph = float(rng.uniform(0, 2 * np.pi))
            for ort in np.linspace(-.85, .85, 18) * k["lang"]:
                d = uu - ort - 4 * np.sin(vv / 9 + ph) - 2 * np.sin(vv / 5 - ph)
                d = np.where(np.abs(vv) < k["kurz"] * 2.4, d, 1e9)
                weit = min([np.abs(d[s["sohle"]]).min() for s in schnitte
                            if s["sohle"].any()] or [1e9])
                if weit < halb + 12:
                    continue
                # Auf beiden Seiten muss Berg bleiben.
                # Mountain has to remain on both sides.
                li = int((roh & (d < -halb) & (d > -halb - 10)).sum())
                re = int((roh & (d > halb) & (d < halb + 10)).sum())
                note = min(li, re) * float(rng.uniform(.8, 1.0))
                if beste is None or note > beste["note"]:
                    beste = {"art": art, "note": note, "d": d, "vv": vv, "halb": halb,
                             "sohle": np.abs(d) < 1.5}
        if beste is None or beste["note"] < 40:
            continue
        bleibt &= np.abs(beste["d"]) > beste["halb"]
        schnitte.append(beste)
        # Was der Schnitt wegnimmt, kommt anderswo dazu -- der Anteil bleibt.
        # What the cut removes is added elsewhere, the share stays.
        roh = (f > np.quantile(f[bleibt], 1 - min(.9, ziel * offen.sum() / bleibt.sum()))) & bleibt
    m = _saeubern(_spiegeln(roh, sym), mindest=90)
    # Enge Buchten schliessen, duenne Haelse und Sporne abnehmen: dort
    # ueberlappen sich die Waende beider Seiten, und der Berg wird undicht.
    # Close narrow bays, take off thin necks and spurs: the walls of both sides
    # overlap there and the mountain leaks.
    m = ~_weite(~_weite(m, HALS_HALB), HALS_HALB) & _spiegeln(bleibt, sym)
    m = _weite(_schrumpf(m, HALS_HALB, HALS_HALB), HALS_HALB) & m
    m = _spiegeln(_saeubern(m, mindest=90), sym)
    if not m.any():
        return
    plan.stufen.append(m)
    g = f + .5 * kipp
    for _ in range(7):
        vorige = plan.stufen[-1]
        # Nord- und Suedabstand sind verschieden: bei Symmetrie muss die Stufe
        # beide einhalten, sonst sind die Haelften ungleich.
        # North and south distance differ; with symmetry the terrace has to keep
        # both, or the halves are unequal.
        innen_alle = _schrumpf(vorige, seite, nord)
        if sym in (SYM_MIRROR_Y, SYM_QUAD):
            innen_alle = innen_alle & innen_alle[::-1]
        elif sym == SYM_ROT180:
            innen_alle = innen_alle & innen_alle[::-1, ::-1]
        n = np.zeros_like(m)
        for c in _components(vorige):
            innen = innen_alle & c
            if int(innen.sum()) < 14:
                continue
            n |= innen & (g > np.quantile(g[c], float(rng.uniform(.02, .30))))
        n = (shapegen.glaette(n.astype(np.int8), 1) > 0) & innen_alle
        n = shapegen.entferne_kleinkram(n.astype(np.int8), mindest=12) > 0
        n = _spiegeln(n, sym) & innen_alle
        if not n.any():
            break
        plan.stufen.append(n)

    grundhaelfte = np.ones((h, w), bool)
    if sym in (SYM_MIRROR_X, SYM_QUAD):
        grundhaelfte[:, w // 2:] = False
    if sym in (SYM_MIRROR_Y, SYM_ROT180, SYM_QUAD):
        grundhaelfte[h // 2:] = False
    for s in schnitte:
        d, vv, halb = s["d"], s["vv"], s["halb"]
        # Schlucht ist nur, was auf BEIDEN Seiten Berg hat.
        # Only what has mountain on BOTH sides counts.
        weite = int(halb) + 4
        zwischen = (_dehne(m & (d < 0) & (d > -halb - 8), weite)
                    & _dehne(m & (d > 0) & (d < halb + 8), weite))
        # Bei Symmetrie zaehlt der Schnitt in der Grundhaelfte; die Flaeche
        # wird gespiegelt, weil er ueber die Achse weiterlaufen kann.
        # With symmetry the cut counts in the base half; its area is mirrored
        # because it may continue across the axis.
        sohle = (np.abs(d) < (9 if s["art"] == "tal" else 3)) & zwischen & grundhaelfte
        if int(sohle.sum()) < 20:
            continue
        vmin, vmax = float(vv[sohle].min()), float(vv[sohle].max())
        flaeche = np.abs(d) <= halb + 2
        if sym != SYM_NONE:
            flaeche = _spiegeln(flaeche, sym)
        e = Einschnitt(sohle=sohle, flaeche=flaeche,
                       ende_a=flaeche & grundhaelfte & (np.abs(vv - vmin) < 1.5),
                       ende_b=flaeche & grundhaelfte & (np.abs(vv - vmax) < 1.5))
        (plan.taeler if s["art"] == "tal" else plan.schluchten).append(e)


def _plane_hochebenen(plan, params, rng, frei) -> None:
    """Hochebenen mit Abstand zu Bergen, Taelern und gesperrten Zellen."""
    h, w = frei.shape
    sperr = _dehne(frei, 7)
    if plan.stufen:
        sperr |= _dehne(plan.stufen[0], 9)
    for e in plan.taeler + plan.schluchten:
        sperr |= e.flaeche & _dehne(e.sohle, 4)
    klein = min(w, h)
    for _ in range(400):
        if len(plan.hochebenen) >= params.hochebenen:
            break
        r = int(rng.integers(13, 18)) if klein >= 128 else int(rng.integers(9, 12))
        if w <= 2 * r + 13 or h <= 2 * r + 13:
            break
        x = int(rng.integers(r + 6, w - r - 6))
        y = int(rng.integers(r + 6, h - r - 6))
        p = shapegen.blob((h, w), (x, y), r, rng, rauheit=.7) > 0
        p = _saeubern(_spiegeln(p, params.symmetry), mindest=60)
        # Gespiegelte Flaechen duerfen sich nicht ueber die Achse beruehren.
        # Mirrored areas must not touch across the axis.
        if not p.any() or (p & sperr).any():
            continue
        plan.hochebenen.append(p)
        sperr |= _dehne(p, 9)


# --------------------------------------------------------------------------
# Konturen / contours

def _boegen(zyklus: list, shape, anzahl: int, lang: tuple[int, int],
            rng: np.random.Generator) -> list[list]:
    """Randzyklus in Boegen mit zufaellig verteilten Luecken zerlegen.
    Split the boundary cycle into arcs with randomly placed gaps."""
    h, w = shape
    n = len(zyklus)
    weg = np.array([x <= 1 or y <= 1 or x >= w - 2 or y >= h - 2 for x, y in zyklus])
    start = int(rng.integers(n))
    for i in range(anzahl):
        p = start + int((i + float(rng.uniform(-.25, .25))) * n / anzahl)
        for q in range(p, p + int(rng.integers(lang[0], lang[1] + 1))):
            weg[q % n] = True
    if not weg.any():
        return [zyklus + [zyklus[0]]]
    s = int(np.argmax(weg))
    aus: list[list] = []
    lauf: list = []
    for i in range(n + 1):
        j = (s + i) % n
        if i == n or weg[j]:
            if len(lauf) >= 8:
                aus.append(lauf)
            lauf = []
        else:
            lauf.append(zyklus[j])
    return aus


def _wellig(b: list, rng: np.random.Generator, shape, hub: float = 1.3) -> list:
    """Kontur seitlich auslenken -- sonst laeuft sie zwischen den Ecken gerade.
    Deflect the contour sideways, otherwise it runs straight between corners."""
    h, w = shape
    zu = b[0] == b[-1]
    p = np.array(b[:-1] if zu else b, float)
    n = len(p)
    if n < 14:
        return b
    k = max(3, n // 5)
    st = rng.uniform(-1, 1, k)
    if not zu:
        st[0] = st[-1] = 0
    x = np.arange(n) / n * k if zu else np.arange(n) / (n - 1) * (k - 1)
    i = x.astype(int)
    f = x - i
    f = f * f * (3 - 2 * f)
    off = (st[i % k] * (1 - f) + st[(i + 1) % k] * f) * hub
    tg = np.roll(p, -3, 0) - np.roll(p, 3, 0) if zu else np.gradient(p, axis=0)
    ln = np.maximum(np.hypot(tg[:, 0], tg[:, 1]), 1e-6)
    q = p + np.stack([-tg[:, 1] / ln, tg[:, 0] / ln], 1) * off[:, None]
    aus = [(int(round(min(max(a, 3), w - 4))), int(round(min(max(c, 3), h - 4))))
           for a, c in q]
    return aus + [aus[0]] if zu else aus


def _weich(b: list, r: int) -> list:
    zu = b[0] == b[-1]
    p = np.array(b[:-1] if zu else b, float)
    n = len(p)
    idx = np.arange(n)[:, None] + np.arange(-r, r + 1)
    idx = idx % n if zu else np.clip(idx, 0, n - 1)
    aus = [(int(round(x)), int(round(y))) for x, y in p[idx].mean(1)]
    return aus + [aus[0]] if zu else aus


def _linie(b: list, eps: float) -> list:
    if b[0] == b[-1]:
        m = len(b) // 2
        pt = _kontur_vereinfachen(b[:m + 1], eps)[:-1] + _kontur_vereinfachen(b[m:], eps)
    else:
        pt = _kontur_vereinfachen(b, eps)
    return [q for i, q in enumerate(pt) if i == 0 or q != pt[i - 1]]


# --------------------------------------------------------------------------
# Waende / walls

class PythonZeichner:
    """Waende mit `klippe_algo` -- der Weg ohne OP2MappingLib."""
    versuche = 3
    laeufe = 1

    def __init__(self, tm):
        self.tm = tm

    def wand(self, grid, punkte, seite: str, saat: int, hoehe: float):
        """Wand ins Gitter setzen -> (Maske, Zelltypen; -1 = nicht gesetzt)."""
        import klippe_algo
        hmin, hmax = klippe_algo.dicke_aus_hoehe(hoehe)
        return klippe_algo.klippe_aus_linie(
            grid, punkte, seite, self.tm, np.random.default_rng(saat), "mud",
            hmin, hmax)


def _fluten(frei: np.ndarray, start: np.ndarray, diagonal: bool = True) -> np.ndarray:
    r = start & frei
    while True:
        e = r.copy()
        e[1:] |= r[:-1]
        e[:-1] |= r[1:]
        e[:, 1:] |= r[:, :-1]
        e[:, :-1] |= r[:, 1:]
        if diagonal:
            e[1:, 1:] |= r[:-1, :-1]
            e[:-1, :-1] |= r[1:, 1:]
            e[1:, :-1] |= r[:-1, 1:]
            e[:-1, 1:] |= r[1:, :-1]
        e &= frei
        if (e == r).all():
            return r
        r = e


def _kern_erreichbar(grid, zellen, comp) -> bool:
    """Kommt man von aussen ins Innere der Flaeche? Auch diagonal geprueft.
    Can the inside be reached from outside? Diagonal steps count."""
    ct = _cell_types(grid)
    ct[zellen >= 0] = zellen[zellen >= 0]
    frei = _passable_mask(ct) & _dehne(comp, 6)
    aussen = _dehne(comp, 6) & ~_dehne(comp, 4)
    return bool((_fluten(frei, aussen) & _erodiere(comp, 3)).any())


def _fremde_paare(tm, grid, maske) -> int:
    """Kachelpaare an der Wand, die keine Originalkarte kennt."""
    # Direkt gegen die gezaehlten Paare: `tm.nachbarn` gibt die Kantenregel
    # zurueck, und die laesst mehr zu, als in den Karten vorkommt.
    # Against the counted pairs directly; `tm.nachbarn` returns the edge rule,
    # which permits more than the maps contain.
    s = 0
    for a, b, k, tab in ((grid[:, :-1], grid[:, 1:], maske[:, :-1] | maske[:, 1:], tm.right),
                         (grid[:-1], grid[1:], maske[:-1] | maske[1:], tm.down)):
        for x, y in zip(a[k].tolist(), b[k].tolist()):
            s += x not in tab or y not in tab[x][0]
    return s


def _ziehe(maske: np.ndarray, punkte) -> None:
    """Linienzug in die Maske eintragen. / Rasterise a polyline into the mask."""
    for (x0, y0), (x1, y1) in zip(punkte, punkte[1:]):
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        t = np.arange(n + 1) / n
        maske[np.rint(y0 + (y1 - y0) * t).astype(int),
              np.rint(x0 + (x1 - x0) * t).astype(int)] = True


def _ausschnitt(comp: np.ndarray, rand: int = 10):
    ys, xs = np.nonzero(comp)
    h, w = comp.shape
    return (slice(max(0, int(ys.min()) - rand), min(h, int(ys.max()) + rand + 1)),
            slice(max(0, int(xs.min()) - rand), min(w, int(xs.max()) + rand + 1)))


def _setze(grid, zellen, maske, comp, zeichner, tm, rng, luecken, lang, ziel) -> bool:
    """Eine Flaeche mit Wand umgeben; der beste von mehreren Versuchen gewinnt.

    `ziel`: "zu" (nicht hineinzukommen), "offen" (hineinzukommen) oder "".
    Enclose one area with a wall; the best of several attempts wins.
    -> Ziel erreicht / goal met
    """
    sl = _ausschnitt(comp)
    c = comp[sl]
    zyklus = _rand_zyklus(c)
    if len(zyklus) < 9:
        return True
    bester = None
    runden = zeichner.versuche * (3 if ziel else 1)
    for v in range(runden):
        # Erst wenn es mit den gewuenschten Luecken nicht geht, eine mehr.
        # One more gap only if the requested number does not work.
        mehr = v // zeichner.versuche if ziel == "offen" else 0
        boegen = _boegen(zyklus, c.shape, luecken + mehr, lang, rng)
        g, z, m = grid[sl].copy(), zellen[sl].copy(), maske[sl].copy()
        ueber = grob = 0
        soll = np.zeros(c.shape, bool)
        for b in boegen:
            if v % 3:
                b = _wellig(b, rng, c.shape)
            pt = _linie(_weich(b, 1 + v % 2), 1.0 + .25 * (v % 4))
            if len(pt) < 2:
                continue
            # Spaete Versuche mit dickerer Wand: die schliesst Luecken.
            # Late attempts with a thicker wall, which closes gaps.
            hoehe = 4.0 if ziel == "zu" and v >= 2 * zeichner.versuche else 3.0
            ma, ze = zeichner.wand(g, pt, _kontur_hand(pt, c),
                                   int(rng.integers(1 << 31)), hoehe)
            grob += getattr(zeichner, "grob", False)
            _ziehe(soll, pt)
            ueber += int((ma & _dehne(m, 1)).sum())
            m |= ma
            z[ze >= 0] = ze[ze >= 0]
        if ziel:
            erreichbar = _kern_erreichbar(g, z, c)
            gut = erreichbar if ziel == "offen" else not erreichbar
        else:
            gut = True
        # Je Wandzelle bewertet -- in Summe gewaenne die kuerzeste Wand. Und wo
        # der Loeser nichts gezeichnet hat, fehlt Wand.
        # Rated per wall cell; as a sum the shortest wall would win. And where
        # the solver drew nothing, wall is missing.
        band = _dehne(c, 5) & ~_erodiere(c, 5) & m
        fehlt = int((soll & ~_dehne(m, 1)).sum()) / max(1, int(soll.sum()))
        note = (not gut, (3 * ueber + _fremde_paare(tm, g, band))
                / max(1, int(band.sum())) + 4 * fehlt + .5 * grob)
        if bester is None or note < bester[0]:
            bester = (note, g, z, m)
        if not bester[0][0] and v >= zeichner.versuche - 1:
            break
    (schlecht, _n), g, z, m = bester
    grid[sl], zellen[sl], maske[sl] = g, z, m
    return not schlecht


def berge_zeichnen(grid: np.ndarray, plan: BergPlan, zeichner, tm,
                   params: MapGenParams) -> tuple[np.ndarray, np.ndarray, dict]:
    """Alle Waende des Plans ins Kachelgitter setzen.

    -> (Klippenmaske, Zelltypfeld mit -1 = nicht gesetzt, Bericht).

    Berg fuer Berg, und jeder so oft, bis er dicht ist (hoechstens
    `zeichner.laeufe`). Der Bericht wird am Ende gezaehlt, wenn alle Waende
    stehen: die Wand des Nachbarn koennte eine schon gepruefte anschneiden.
    Mountain by mountain, each repeated until it is closed (at most
    `zeichner.laeufe` times). The report is counted at the end, once all walls
    stand: a neighbour's wall could cut one that was already checked.
    """
    maske = np.zeros(grid.shape, bool)
    zellen = np.full(grid.shape, -1, np.int16)
    rng = np.random.default_rng([int(params.seed) & 0xFFFFFFFF, 777])
    locker = 1 - float(np.clip(params.berg_dichte, 0, 1))
    berge = [c for m in plan.stufen[:1] for c in _components(m)]
    for berg in berge:
        sl = _ausschnitt(berg)
        stand = [x[sl].copy() for x in (grid, zellen, maske)]
        bester = None
        for _lauf in range(zeichner.laeufe):
            for x, alt in zip((grid, zellen, maske), stand):
                x[sl] = alt
            dicht = _ein_berg(grid, zellen, maske, berg, plan, zeichner, tm, rng, locker)
            if bester is None or dicht:
                bester = [x[sl].copy() for x in (grid, zellen, maske)]
            if dicht:
                break
        for x, neu in zip((grid, zellen, maske), bester):
            x[sl] = neu
    ebenen = [c for m in plan.hochebenen for c in _components(m)]
    for comp in ebenen:
        _setze(grid, zellen, maske, comp, zeichner, tm, rng, 2, (8, 11), "offen")

    def drin(comp):
        sl = _ausschnitt(comp)
        return _kern_erreichbar(grid[sl], zellen[sl], comp[sl])

    bericht = {"berge": len(berge), "undicht": sum(drin(c) for c in berge),
               "hochebenen": len(ebenen), "unerreichbar": sum(not drin(c) for c in ebenen)}
    return maske, zellen, bericht


def _ein_berg(grid, zellen, maske, berg, plan, zeichner, tm, rng, locker) -> bool:
    """Einen Berg von innen nach aussen belegen -> dicht?

    Die Aussenwand kommt zuletzt und wird von keiner eigenen mehr
    angeschnitten. From the inside out: the outer wall comes last.
    """
    for k in range(len(plan.stufen) - 1, 0, -1):
        for comp in _components(plan.stufen[k] & berg):
            n = len(_rand_zyklus(comp))
            luecken = 1 if n < 60 else int(round(n / (60 - 25 * locker)))
            _setze(grid, zellen, maske, comp, zeichner, tm, rng, luecken,
                   (4, 8 + int(6 * locker)), "")
    # Was keinen Kern hat, kann nicht undicht sein.
    # Without a core there is nothing to leak into.
    kern = bool(_erodiere(berg, 3).any())
    return _setze(grid, zellen, maske, berg, zeichner, tm, rng, 0, (0, 0),
                  "zu" if kern else "")


# --------------------------------------------------------------------------
# Auswertung / evaluation

def bauplatz_maske(cells: np.ndarray) -> np.ndarray:
    """Zellen, auf denen ein freies, erreichbares Quadrat liegt.
    Cells covered by a free, reachable square."""
    gebiet = np.asarray(_groesstes_gebiet(_passable_mask(cells))).astype(bool)
    h, w = gebiet.shape
    n = BAUPLATZ
    s = np.zeros((h + 1, w + 1), np.int64)
    s[1:, 1:] = gebiet.cumsum(0).cumsum(1)
    voll = (s[n:, n:] - s[:-n, n:] - s[n:, :-n] + s[:-n, :-n]) == n * n
    aus = np.zeros((h, w), bool)
    for dy in range(n):
        for dx in range(n):
            aus[dy:dy + voll.shape[0], dx:dx + voll.shape[1]] |= voll
    return aus


def zonen_bericht(cells: np.ndarray, plan: BergPlan) -> dict:
    """Wieviel Bauplatz liegt in welcher Zone, sind die Schluchten durchfahrbar?
    How much building ground is in which zone, can the gorges be driven through?"""
    bau = bauplatz_maske(cells)
    frei = _passable_mask(cells)

    def anteil(masken) -> float:
        if not masken:
            return -1.0
        m = np.logical_or.reduce(masken)
        return float((bau & m).sum()) / max(1, int(m.sum()))

    # Durchfahrt wird ohne Diagonalen geprueft, also streng.
    # Passage is tested without diagonals, i.e. strictly.
    durch = sum(bool((_fluten(frei & e.flaeche, e.ende_a, False) & e.ende_b).any())
                for e in plan.schluchten)
    return {"bauplatz": float(bau.mean()),
            "berg": anteil(plan.stufen[:1]),
            "hochebene": anteil(plan.hochebenen),
            "tal": anteil([e.sohle for e in plan.taeler]),
            "schlucht": anteil([e.sohle for e in plan.schluchten]),
            "schluchten": len(plan.schluchten), "durchfahrbar": int(durch)}
