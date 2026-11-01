"""Chronik: die Karte erzaehlt ihre Entstehung.

Statt Gelaende zu wuerfeln, wird die Geschichte eines Ortes in Kapiteln
nachgespielt. Jedes Kapitel veraendert die Karte, spaetere ueberlagern
fruehere -- und genau dieses Ueberlagern macht sie lesbar: ein Lavastrom, der
an einem Kraterwall endet; Duenen, die ihn halb begraben; die Reste einer
Kolonie, ueber die die Lava hinweggegangen ist.

Kapitel (Reihenfolge frei, jedes mit Ort, Staerke und ggf. Richtung):

    urland     Hochland und Becken -- das unsichtbare Relief, worauf alles fliesst
    spalte     Spaltenausbruch: Lava quillt aus einer Spalte und fliesst bergab
    einschlag  Meteoriteneinschlag: Krater mit Wall, Strahlen, Nebenkratern
    sandsturm  Wind treibt Sand aus den Becken und begraebt, was dort liegt
    kolonie    Verlassene Kolonie: planierte Bauplaetze, Schutt, Brandspuren
    absturz    Absturz: Schleifspur mit Wrackteilen bis zum Einschlag
    flechten   Letzte Vegetation in einer geschuetzten Senke

Jedes Kapitel wuerfelt mit seinem eigenen Zufall (Seed + Kapitelnummer).
Aendert man ein Kapitel, bleiben die anderen, wie sie waren.

Chronicle: the map tells how it came to be. Chapters are played in order,
later ones overlaying earlier ones; each has its own random stream so editing
one chapter leaves the others unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi

import celltypes as ct
import detail_themen as dt
import kachelgruppen as kg
from mapgen_basis import GeneratedMap, MapGenParams, SYM_NONE, _cell_types
from mapgen_felder import _dissolve_small_biomes, _naht_passt
from mapgen_kacheln import _sample_tiles
from mapgen_modell import model
from mapgen_uebergaenge import (_bewuchs_abstand, _mische_grenzen,
                                _repariere_kontakte, nachbearbeite_uebergaenge)
from mapgen_wege import _connected, _passable_mask, _pick_spawns

ARTEN = ("urland", "spalte", "einschlag", "sandsturm", "kolonie", "absturz", "flechten")
ORTE = ("zufall", "nord", "nordost", "ost", "suedost", "sued", "suedwest", "west",
        "nordwest", "mitte")
RICHTUNGEN = ("zufall", "n", "no", "o", "so", "s", "sw", "w", "nw")

_ORT_XY = {"nord": (0.5, 0.2), "nordost": (0.78, 0.22), "ost": (0.8, 0.5),
           "suedost": (0.78, 0.78), "sued": (0.5, 0.8), "suedwest": (0.22, 0.78),
           "west": (0.2, 0.5), "nordwest": (0.22, 0.22), "mitte": (0.5, 0.5)}
# Bildschirmrichtung: x nach rechts (Osten), y nach unten (Sueden)
_RICHTUNG_XY = {"n": (0, -1), "no": (0.707, -0.707), "o": (1, 0), "so": (0.707, 0.707),
                "s": (0, 1), "sw": (-0.707, 0.707), "w": (-1, 0), "nw": (-0.707, -0.707)}


@dataclass
class Kapitel:
    art: str
    wo: str = "zufall"
    staerke: float = 0.5
    richtung: str = "zufall"

    def als_dict(self) -> dict:
        return {"art": self.art, "wo": self.wo, "staerke": self.staerke,
                "richtung": self.richtung}

    @classmethod
    def aus_dict(cls, d: dict) -> "Kapitel":
        return cls(str(d.get("art", "urland")), str(d.get("wo", "zufall")),
                   float(d.get("staerke", 0.5)), str(d.get("richtung", "zufall")))


@dataclass
class Chronik:
    kapitel: list = field(default_factory=list)
    width: int = 128
    height: int = 128
    seed: int = 1
    spawns: int = 2


# Fertige Geschichten / ready-made stories
VORLAGEN: dict[str, list[Kapitel]] = {
    "gefallene_kolonie": [
        Kapitel("urland", "nord", 0.5),
        Kapitel("kolonie", "mitte", 0.6),
        Kapitel("spalte", "nord", 0.6),
        Kapitel("sandsturm", "zufall", 0.4, "o"),
        Kapitel("absturz", "suedost", 0.5, "sw"),
    ],
    "narbenland": [
        Kapitel("urland", "zufall", 0.35),
        Kapitel("spalte", "nordwest", 0.5),
        Kapitel("einschlag", "mitte", 0.85),
        Kapitel("einschlag", "suedost", 0.35),
        Kapitel("sandsturm", "zufall", 0.35, "w"),
    ],
    "erbe_des_feuers": [
        Kapitel("urland", "nord", 0.4),
        Kapitel("spalte", "nordost", 0.8),
        Kapitel("spalte", "nordwest", 0.5),
        Kapitel("sandsturm", "zufall", 0.3, "s"),
        Kapitel("flechten", "sued", 0.4),
    ],
    "beispiel": [
        Kapitel("urland", "nord", 0.5),
        Kapitel("spalte", "nord", 0.6),
        Kapitel("einschlag", "mitte", 0.6),
        Kapitel("sandsturm", "zufall", 0.5, "o"),
        Kapitel("kolonie", "west", 0.5),
        Kapitel("absturz", "zufall", 0.5),
    ],
}


# ---------------------------------------------------------------------------
# Hilfen / helpers

class _Rauschen:
    """Wertrauschen, an beliebigen Stellen abfragbar."""

    def __init__(self, rng, freq):
        self.freq = float(freq)
        n = int(np.ceil(freq)) * 3 + 4
        self.b = rng.random((n, n))
        self.m = n / 2.0

    def __call__(self, u, v):
        n = self.b.shape[0]
        x = np.clip(u * self.freq + self.m, 0, n - 1.001)
        y = np.clip(v * self.freq + self.m, 0, n - 1.001)
        x0, y0 = x.astype(int), y.astype(int)
        fx, fy = x - x0, y - y0
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        b = self.b
        o = b[y0, x0] * (1 - fx) + b[y0, x0 + 1] * fx
        un = b[y0 + 1, x0] * (1 - fx) + b[y0 + 1, x0 + 1] * fx
        return o * (1 - fy) + un * fy


def _rund(r: int) -> np.ndarray:
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= r * r


def _scheiben(shape, punkte, radien) -> np.ndarray:
    h, w = shape
    m = np.zeros(shape, dtype=bool)
    yy, xx = np.ogrid[:h, :w]
    for (px, py), r in zip(punkte, radien):
        x0, x1 = int(max(0, px - r - 1)), int(min(w, px + r + 2))
        y0, y1 = int(max(0, py - r - 1)), int(min(h, py + r + 2))
        if x0 >= x1 or y0 >= y1:
            continue
        m[y0:y1, x0:x1] |= ((xx[:, x0:x1] - px) ** 2 + (yy[y0:y1] - py) ** 2) <= r * r
    return m


def _schieben(m: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Verschieben ohne Umlauf (was hinausfaellt, ist weg)."""
    h, w = m.shape
    out = np.zeros_like(m)
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    out[ys0:ys1, xs0:xs1] = m[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def _richtung(name: str, rng) -> np.ndarray:
    if name in _RICHTUNG_XY:
        return np.array(_RICHTUNG_XY[name], dtype=float)
    a = rng.uniform(0, 2 * np.pi)
    return np.array([np.cos(a), np.sin(a)])


class Welt:
    """Zwischenstand der Karte waehrend der Kapitel."""

    def __init__(self, chronik: Chronik):
        self.tm = model()
        self.c = chronik
        self.h, self.w = chronik.height, chronik.width
        self.F = {n: i for i, n in enumerate(self.tm.families)}
        self.H = np.zeros((self.h, self.w))           # unsichtbares Relief
        self.fam = np.full((self.h, self.w), self.F["mud"], dtype=np.int16)
        self.zeit = np.full((self.h, self.w), -1, dtype=np.int16)
        self.senke = np.zeros((self.h, self.w), dtype=bool)
        self.riffel = np.zeros((self.h, self.w), dtype=bool)
        self.schutz = np.zeros((self.h, self.w), dtype=bool)
        self.stempel: list[dict] = []
        self.orte: list[dict] = []
        self.lava_zonen: list[list[tuple[int, int]]] = []
        self.kapitel_index = 0
        self.rng = np.random.default_rng(chronik.seed)

    def setze(self, maske: np.ndarray, familie: str) -> None:
        self.fam[maske] = self.F[familie]
        self.zeit[maske] = self.kapitel_index

    def ort(self, wo: str, rng, eignung: np.ndarray | None = None,
            rand: int = 10) -> tuple[int, int]:
        """Punkt im gewuenschten Kartenteil, bevorzugt wo `eignung` gilt."""
        h, w = self.h, self.w
        if wo in _ORT_XY:
            fx, fy = _ORT_XY[wo]
            fx += rng.normal(0, 0.05)
            fy += rng.normal(0, 0.05)
        else:
            fx, fy = rng.uniform(0.25, 0.75), rng.uniform(0.25, 0.75)
        zx, zy = fx * w, fy * h
        if eignung is None or not eignung.any():
            return (int(np.clip(zx, rand, w - rand - 1)), int(np.clip(zy, rand, h - rand - 1)))
        ok = eignung.copy()
        ok[:rand, :] = ok[-rand:, :] = False
        ok[:, :rand] = ok[:, -rand:] = False
        if not ok.any():
            ok = eignung
        ys, xs = np.nonzero(ok)
        d = (xs - zx) ** 2 + (ys - zy) ** 2
        naechste = np.argsort(d)[:max(1, len(d) // 40 + 1)]
        k = int(naechste[int(rng.integers(len(naechste)))])
        return int(xs[k]), int(ys[k])

    def stempel_dazu(self, kacheln, x: int, y: int, pruefen: bool = True,
                     familie: str | None = None) -> None:
        if not isinstance(kacheln, tuple):
            kacheln = np.asarray(kacheln)
        self.stempel.append({"kacheln": kacheln, "x": int(x), "y": int(y),
                             "kapitel": self.kapitel_index, "pruefen": pruefen,
                             "familie": familie})

    def familie_bei(self, x: int, y: int) -> str:
        f = int(self.fam[int(np.clip(y, 0, self.h - 1)), int(np.clip(x, 0, self.w - 1))])
        return self.tm.families[f]

    def u_v(self):
        seite = float(max(self.h, self.w))
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(float)
        return (xx - self.w / 2) / seite, (yy - self.h / 2) / seite


# ---------------------------------------------------------------------------
# Kapitel / chapters

def _urland(welt: Welt, k: Kapitel, rng) -> None:
    """Hochland und Becken. `wo` = wo das Hochland liegt; Staerke = Beckenanteil."""
    u, v = welt.u_v()
    wa, wb = _Rauschen(rng, 2.0), _Rauschen(rng, 2.0)
    u2 = u + 0.25 * (wa(u, v) - 0.5)
    v2 = v + 0.25 * (wb(u, v) - 0.5)
    grob, mittel = _Rauschen(rng, 2.5), _Rauschen(rng, 6.0)
    H = 0.7 * grob(u2, v2) + 0.3 * mittel(u2, v2)
    if k.wo in _ORT_XY:
        fx, fy = _ORT_XY[k.wo]
        neig = np.array([fx - 0.5, fy - 0.5])
        if np.linalg.norm(neig) < 1e-6:
            neig = rng.normal(0, 1, 2)
        neig /= np.linalg.norm(neig)
    else:
        a = rng.uniform(0, 2 * np.pi)
        neig = np.array([np.cos(a), np.sin(a)])
    H = 0.6 * H + 0.6 * (neig[0] * u + neig[1] * v + 0.5)
    H = ndi.gaussian_filter(H, 3)
    welt.H = (H - H.min()) / (np.ptp(H) + 1e-9)
    anteil = 0.10 + 0.25 * float(np.clip(k.staerke, 0, 1))
    becken = welt.H < np.quantile(welt.H, anteil)
    becken = ndi.binary_opening(becken, _rund(2))
    welt.fam[:] = welt.F["mud"]
    welt.setze(becken, "san")
    welt.senke = becken.copy()


def _fliessen(H, ziel, start, richtung, rng, laenge):
    """Lava laeuft bergab zum naechsten Becken, mit Traegheit und Maeandern."""
    h, w = H.shape
    D = ndi.distance_transform_edt(~ziel) if ziel.any() else np.zeros_like(H)
    D = D / (D.max() + 1e-9)
    G = ndi.gaussian_filter(D + 0.18 * H, 3)
    gy, gx = np.gradient(G)
    p = np.array(start, dtype=float)
    d = np.array(richtung, dtype=float)
    d /= np.linalg.norm(d) + 1e-9
    pfad = [p.copy()]
    phase, frequenz, ampl = rng.uniform(0, 6.3), rng.uniform(0.05, 0.11), rng.uniform(0.04, 0.09)
    im_ziel = 0
    stillstand = 0
    for schritt in range(laenge):
        ix, iy = int(np.clip(p[0], 0, w - 1)), int(np.clip(p[1], 0, h - 1))
        g = -np.array([gx[iy, ix], gy[iy, ix]])
        gn = np.linalg.norm(g)
        if gn > 1e-9:
            g /= gn
        d = 0.9 * d + 0.1 * g
        dreh = ampl * np.sin(phase + frequenz * schritt)
        c, s = np.cos(dreh), np.sin(dreh)
        d = np.array([c * d[0] - s * d[1], s * d[0] + c * d[1]])
        d /= np.linalg.norm(d) + 1e-9
        alt = G[iy, ix]
        p = p + d
        if not (4 <= p[0] < w - 4 and 4 <= p[1] < h - 4):
            break
        pfad.append(p.copy())
        neu = G[int(p[1]), int(p[0])]
        stillstand = stillstand + 1 if neu >= alt else 0
        if stillstand > 30 and schritt > 0.35 * max(h, w):
            break
        if ziel[int(p[1]), int(p[0])]:
            im_ziel += 1
            if im_ziel > 10:
                break
    pfad = np.array(pfad)
    if len(pfad) > 9:
        kern = np.ones(9) / 9
        for a in (0, 1):
            innen = np.convolve(pfad[:, a], kern, mode="same")
            innen[:4], innen[-4:] = pfad[:4, a], pfad[-4:, a]
            pfad[:, a] = innen
    return pfad


def _spalte(welt: Welt, k: Kapitel, rng) -> None:
    """Spaltenausbruch: Lava quillt aus einer Spalte im Hochland und fliesst in
    zwei, drei Stroemen bergab, bis in ein Becken oder einen Krater."""
    h, w = welt.h, welt.w
    ziel = welt.senke if welt.senke.any() else welt.H < np.quantile(welt.H, 0.2)
    D = ndi.distance_transform_edt(~ziel)
    eignung = (D > np.quantile(D, 0.6)) & (welt.H > np.quantile(welt.H, 0.5))
    cx, cy = welt.ort(k.wo, rng, eignung, rand=14)
    # Bergab zum naechsten Becken / downhill towards the nearest basin
    G = ndi.gaussian_filter(D / (D.max() + 1e-9) + 0.18 * welt.H, 6)
    gy, gx = np.gradient(G)
    abw = -np.array([gx[cy, cx], gy[cy, cx]])
    abw = abw / np.linalg.norm(abw) if np.linalg.norm(abw) > 1e-12 else _richtung("zufall", rng)
    quer = np.array([-abw[1], abw[0]])
    staerke = float(np.clip(k.staerke, 0, 1))
    spalt_laenge = 12 + 16 * staerke
    n = 2 if staerke < 0.65 else 3
    maske = np.zeros((h, w), dtype=bool)
    for i in range(n):
        t = (i / max(1, n - 1) - 0.5) * spalt_laenge
        start = np.array([cx, cy], dtype=float) + quer * t
        spreiz = (i / max(1, n - 1) - 0.5) * rng.uniform(0.6, 1.1)
        pfad = _fliessen(welt.H, ziel, start, abw + quer * spreiz, rng, int(1.4 * max(h, w)))
        L = len(pfad)
        if L < 10:
            continue
        s = np.linspace(0, 1, L)
        r = (4.3 + 1.6 * s) * (0.9 + 0.25 * staerke)
        r *= np.interp(s, np.linspace(0, 1, 7), rng.uniform(0.85, 1.15, 7))
        maske |= _scheiben((h, w), pfad, r)
        ende, rend = pfad[-1], float(r[-1])
        d_end = pfad[-1] - pfad[max(0, L - 8)]
        d_end /= np.linalg.norm(d_end) + 1e-9
        for _z in range(int(rng.integers(2, 5))):
            wink = rng.uniform(-0.9, 0.9)
            c, s_ = np.cos(wink), np.sin(wink)
            dz = np.array([c * d_end[0] - s_ * d_end[1], s_ * d_end[0] + c * d_end[1]])
            lz = int(rng.uniform(6, 16))
            pz = np.array([ende + dz * j for j in range(lz)])
            maske |= _scheiben((h, w), pz, np.linspace(rend * 0.9, rend * rng.uniform(0.6, 0.85), lz))
    # Die Spalte selbst: ein laenglicher Lavasee quer zum Gefaelle.
    sp = np.array([np.array([cx, cy]) + quer * t
                   for t in np.linspace(-spalt_laenge / 2, spalt_laenge / 2, 12)])
    maske |= _scheiben((h, w), sp, np.full(len(sp), 3.4))
    rand = maske & ~ndi.binary_erosion(maske)
    ys, xs = np.nonzero(rand)
    if len(xs):
        wahl = rng.choice(len(xs), size=max(1, len(xs) // 22), replace=False)
        maske |= _scheiben((h, w), np.stack([xs[wahl], ys[wahl]], 1).astype(float),
                           rng.uniform(2.0, 3.2, len(wahl)))
    maske = ndi.binary_opening(ndi.binary_closing(maske, _rund(2)), _rund(2))
    loecher = ndi.binary_fill_holes(maske) & ~maske
    lab, n_l = ndi.label(loecher)
    for i_l in range(1, n_l + 1):
        if (lab == i_l).sum() < 120:
            maske |= lab == i_l
    welt.setze(maske, "roc")
    kern = ndi.distance_transform_edt(maske) >= 4.0
    welt.setze(kern, "lav")
    # Risse setzen die Spalte ueber die Lava hinaus fort.
    for seite in (-1, 1):
        for j in range(2):
            p = np.array([cx, cy]) + quer * seite * (spalt_laenge / 2 + 7 + 7 * j)
            welt.stempel_dazu(("thema", dt.RISSE), int(p[0]), int(p[1]))
    welt.lava_zonen.append([(int(x), int(y)) for y, x in zip(*np.nonzero(maske))])
    welt.orte.append({"art": "spalte", "x": int(cx), "y": int(cy)})


def _einschlag(welt: Welt, k: Kapitel, rng) -> None:
    """Meteoriteneinschlag: Wall aus Fels, Kraterboden, Strahlen, Nebenkrater.
    Was vorher dort lag -- auch ein Lavastrom -- endet am Wall."""
    h, w = welt.h, welt.w
    staerke = float(np.clip(k.staerke, 0, 1))
    R = 6.0 + 11.0 * staerke
    cx, cy = welt.ort(k.wo, rng, None, rand=int(R * 1.6) + 4)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(xx - cx, yy - cy)
    wink = np.arctan2(yy - cy, xx - cx)
    wackel = 1.0 + 0.08 * np.sin(wink * rng.integers(3, 6) + rng.uniform(0, 6))
    innen = dist < 0.72 * R * wackel
    wall = (dist < 1.08 * R * wackel) & ~innen
    # Strahlen aus Auswurf / ejecta rays
    strahlen = np.zeros((h, w), dtype=bool)
    for _ in range(int(rng.integers(5, 9))):
        a = rng.uniform(-np.pi, np.pi)
        laenge = R * rng.uniform(1.5, 2.3)
        pz = np.array([[cx + np.cos(a) * t, cy + np.sin(a) * t]
                       for t in np.linspace(R, laenge, int(laenge - R) + 2)])
        strahlen |= _scheiben((h, w), pz, np.linspace(3.2, 2.2, len(pz)))
    strahlen = ndi.binary_opening(strahlen | wall, _rund(1)) & ~innen
    # Im Krater sammelt sich Sand -- die orange Scheibe im Felswall macht ihn
    # auch aus der Ferne als Krater lesbar.
    boden = "san"
    welt.setze(strahlen, "roc")
    welt.setze(innen, boden)
    welt.H[innen] = np.minimum(welt.H[innen], 0.0)
    welt.senke |= innen
    # Grosser Krater in der Mitte, kleine Nebenkrater drumherum.
    welt.stempel_dazu(("gross", dt.KRATER), cx, cy, familie=boden)
    for _ in range(int(3 + 6 * staerke)):
        a = rng.uniform(-np.pi, np.pi)
        r = R * rng.uniform(1.3, 2.4)
        welt.stempel_dazu(("thema", dt.KRATER), int(cx + np.cos(a) * r), int(cy + np.sin(a) * r))
    for _ in range(int(1 + 2 * staerke)):
        a = rng.uniform(-np.pi, np.pi)
        r = R * rng.uniform(0.15, 0.45)
        welt.stempel_dazu(("thema", dt.KRATER), int(cx + np.cos(a) * r), int(cy + np.sin(a) * r),
                          familie=boden)
    welt.orte.append({"art": "einschlag", "x": int(cx), "y": int(cy)})


def _sandsturm(welt: Welt, k: Kapitel, rng) -> None:
    """Wind treibt Sand aus Becken und Kratern; Duenen begraben, was dort liegt."""
    h, w = welt.h, welt.w
    staerke = float(np.clip(k.staerke, 0, 1))
    wind = _richtung(k.richtung, rng)
    u, v = welt.u_v()
    laengs = wind[0] * u + wind[1] * v
    quer = -wind[1] * u + wind[0] * v
    duene = _Rauschen(rng, 7.0)(laengs / 2.5, quer)
    sand = welt.fam == welt.F["san"]
    if not sand.any():
        sand = welt.senke.copy()
    # Sand wandert in Windrichtung: verschieben und dort halten, wo Duenen liegen.
    weite = int(6 + 30 * staerke)
    feld = sand.copy()
    dx, dy = wind
    for schritt in range(1, weite + 1):
        sx, sy = int(round(dx * schritt)), int(round(dy * schritt))
        verschoben = _schieben(sand, sy, sx)
        schwelle = 0.38 + 0.5 * schritt / weite
        feld |= verschoben & (duene > schwelle)
    feld = ndi.binary_opening(ndi.binary_closing(feld, _rund(2)), _rund(2))
    neu = feld & ~sand
    welt.setze(neu, "san")
    # Riffelsand: Duenenkaemme quer zum Wind, im Inneren der Sandflaechen.
    kamm = _Rauschen(rng, 9.0)(laengs / 3.0, quer)
    welt.riffel |= feld & (kamm > 0.55)
    if neu.any():
        ys, xs = np.nonzero(neu)
        welt.orte.append({"art": "sandsturm", "x": int(np.median(xs)), "y": int(np.median(ys))})


def _kolonie(welt: Welt, k: Kapitel, rng) -> None:
    """Verlassene Kolonie: planierte Bauplaetze in Reihen, Wege, Schutt und
    Brandspuren auf den zerstoerten Plaetzen."""
    h, w = welt.h, welt.w
    staerke = float(np.clip(k.staerke, 0, 1))
    eben = (welt.fam == welt.F["mud"])
    eben = ndi.binary_erosion(eben, _rund(4))
    cx, cy = welt.ort(k.wo, rng, eben, rand=14)
    fam = welt.familie_bei(cx, cy)
    praefix = {"mud": "mud", "san": "san"}.get(fam, "roc")
    doz = kg.gruppe(f"{praefix}doz2")
    if doz is None:
        return
    doz = doz.ravel()
    plaetze = []
    n = int(4 + 8 * staerke)
    groessen = [(2, 2), (3, 2), (3, 3), (4, 3), (2, 3), (5, 4), (3, 4)]
    versuche = 0
    belegt = np.zeros((h, w), dtype=bool)
    while len(plaetze) < n and versuche < 200:
        versuche += 1
        bw, bh = groessen[int(rng.integers(len(groessen)))]
        x = int(cx + rng.integers(-9, 10) // 3 * 3 - bw // 2)
        y = int(cy + rng.integers(-8, 9) // 3 * 3 - bh // 2)
        if x < 4 or y < 4 or x + bw + 4 > w or y + bh + 4 > h:
            continue
        if belegt[y - 1:y + bh + 1, x - 1:x + bw + 1].any():
            continue
        if (welt.fam[y:y + bh, x:x + bw] != welt.fam[cy, cx]).any():
            continue
        belegt[y:y + bh, x:x + bw] = True
        plaetze.append((x, y, bw, bh))
    if not plaetze:
        return
    zerstoert = 0.4 + 0.5 * staerke
    for x, y, bw, bh in plaetze:
        block = doz[rng.integers(len(doz), size=(bh, bw))]
        welt.stempel_dazu(block, x, y, pruefen=False, familie=fam)
        welt.schutz[y - 1:y + bh + 1, x - 1:x + bw + 1] = True
        if rng.random() < zerstoert:
            # Schutt auf dem Platz: das Gebaeude liegt in Truemmern.
            # Rubble on the plot: the building lies in ruins.
            for _ in range(max(1, (bw * bh) // 4)):
                rub = kg.gruppe(f"{praefix}rub0{int(rng.integers(1, 3))}")
                if rub is not None and bw >= 2 and bh >= 2:
                    welt.stempel_dazu(rub, x + int(rng.integers(0, bw - 1)),
                                      y + int(rng.integers(0, bh - 1)), pruefen=False, familie=fam)
    # Wege zwischen den Plaetzen: planierte Streifen zum Mittelpunkt
    for x, y, bw, bh in plaetze:
        px, py = x + bw // 2, y + bh // 2
        for t in np.linspace(0, 1, int(abs(px - cx) + abs(py - cy)) + 1):
            qx, qy = int(round(px + (cx - px) * t)), int(round(py))
            if 0 <= qx < w and not belegt[qy, qx]:
                welt.stempel_dazu(doz[int(rng.integers(len(doz)))].reshape(1, 1), qx, qy,
                                  pruefen=False, familie=fam)
                belegt[qy, qx] = True
        for t in np.linspace(0, 1, abs(py - cy) + 1):
            qy = int(round(py + (cy - py) * t))
            if 0 <= qy < h and not belegt[qy, cx]:
                welt.stempel_dazu(doz[int(rng.integers(len(doz)))].reshape(1, 1), cx, qy,
                                  pruefen=False, familie=fam)
                belegt[qy, cx] = True
    # Brandspuren verstreut ueber das Gelaende der Kolonie
    brand = kg.gruppe(f"{praefix}burn")
    if brand is not None:
        flecken = brand.ravel()
        for _ in range(int(8 + 16 * staerke * zerstoert)):
            bx = int(cx + rng.normal(0, 6))
            by = int(cy + rng.normal(0, 5))
            if 0 <= bx < w and 0 <= by < h and not belegt[by, bx]:
                welt.stempel_dazu(flecken[int(rng.integers(len(flecken)))].reshape(1, 1),
                                  bx, by, pruefen=False, familie=fam)
                belegt[by, bx] = True
    welt.orte.append({"art": "kolonie", "x": int(cx), "y": int(cy)})


def _absturz(welt: Welt, k: Kapitel, rng) -> None:
    """Absturz: Schleifspur aus planiertem Boden, Brandflecken und Wrackteilen,
    am Ende ein Einschlag mit dem groessten Wrackstueck."""
    h, w = welt.h, welt.w
    staerke = float(np.clip(k.staerke, 0, 1))
    flug = _richtung(k.richtung, rng)
    laenge = 14 + 22 * staerke
    eignung = (welt.fam == welt.F["mud"]) | (welt.fam == welt.F["san"])
    ex, ey = welt.ort(k.wo, rng, ndi.binary_erosion(eignung, _rund(3)), rand=8)
    sx, sy = ex - flug[0] * laenge, ey - flug[1] * laenge
    punkte = [(sx + (ex - sx) * t, sy + (ey - sy) * t)
              for t in np.linspace(0, 1, int(laenge) + 1)]
    for i, (px, py) in enumerate(punkte):
        px, py = int(round(px)), int(round(py))
        if not (2 <= px < w - 2 and 2 <= py < h - 2):
            continue
        fam = welt.familie_bei(px, py)
        praefix = {"mud": "mud", "san": "san"}.get(fam, "roc")
        doz = kg.gruppe(f"{praefix}doz2")
        if doz is not None:
            # Schleifspur zwei Kacheln breit / skid trail two tiles wide
            for ox, oy in ((0, 0), (int(round(-flug[1])), int(round(flug[0])))):
                welt.stempel_dazu(doz.ravel()[int(rng.integers(8))].reshape(1, 1),
                                  px + ox, py + oy, pruefen=False, familie=fam)
        if i % 3 == 1:
            brand = kg.gruppe(f"{praefix}burn")
            if brand is not None:
                welt.stempel_dazu(brand.ravel()[int(rng.integers(brand.size))].reshape(1, 1),
                                  px + int(round(flug[1] * 2)), py - int(round(flug[0] * 2)),
                                  pruefen=False, familie=fam)
        if i % 6 == 4 and i < len(punkte) - 4:
            welt.stempel_dazu(("thema", dt.WRACK), px - int(round(flug[1] * 2)),
                              py + int(round(flug[0] * 2)), pruefen=False, familie=fam)
        if i % 9 == 7:
            rub = kg.gruppe(f"{praefix}rub0{1 + i % 2}")
            if rub is not None:
                welt.stempel_dazu(rub, px + int(round(flug[1] * 2)), py - int(round(flug[0] * 2)),
                                  pruefen=False, familie=fam)
    # Am Ende: Einschlagmulde, darin das groesste Wrackstueck, Truemmer drumherum.
    fam = welt.familie_bei(ex, ey)
    welt.stempel_dazu(("gross", dt.WRACK), ex, ey, pruefen=False, familie=fam)
    for _ in range(3):
        welt.stempel_dazu(("thema", dt.WRACK), int(ex + rng.normal(0, 3)),
                          int(ey + rng.normal(0, 3)), pruefen=False, familie=fam)
    welt.orte.append({"art": "absturz", "x": int(ex), "y": int(ey)})


def _flechten(welt: Welt, k: Kapitel, rng) -> None:
    """Letzte Vegetation: wenige Flecken in einer geschuetzten Senke auf Erde."""
    h, w = welt.h, welt.w
    staerke = float(np.clip(k.staerke, 0, 1))
    erde = welt.fam == welt.F["mud"]
    innen = ndi.distance_transform_edt(erde) >= 3
    tief = welt.H < np.quantile(welt.H[erde], 0.4) if erde.any() else innen
    cx, cy = welt.ort(k.wo, rng, innen & tief, rand=10)
    maske = np.zeros((h, w), dtype=bool)
    for _ in range(int(2 + 4 * staerke)):
        px = cx + rng.normal(0, 5 + 5 * staerke)
        py = cy + rng.normal(0, 4 + 4 * staerke)
        maske |= _scheiben((h, w), [(px, py)], [rng.uniform(2.5, 4.5 + 2 * staerke)])
    maske = ndi.binary_opening(maske, _rund(1)) & innen
    welt.setze(maske, "veg")
    welt.orte.append({"art": "flechten", "x": int(cx), "y": int(cy)})


_KAPITEL = {"urland": _urland, "spalte": _spalte, "einschlag": _einschlag,
            "sandsturm": _sandsturm, "kolonie": _kolonie, "absturz": _absturz,
            "flechten": _flechten}


# ---------------------------------------------------------------------------
# Fertigstellen / finishing

def _ordnen(welt: Welt) -> None:
    """Regeln der Kachelgrammatik durchsetzen: dunkler Lavafels nur mit
    hellem Rand, keine Splitter, Bewuchs nur auf Erde."""
    F = welt.F
    for _ in range(2):
        nicht_lava = (welt.fam != F["lav"]) & (welt.fam != F["roc"])
        nah = ndi.distance_transform_edt(~nicht_lava) < 3.0
        welt.fam[(welt.fam == F["lav"]) & nah] = F["roc"]
        lav = welt.fam == F["lav"]
        lab, n = ndi.label(lav)
        for i in range(1, n + 1):
            teil = lab == i
            if teil.sum() < 14:
                welt.fam[teil] = F["roc"]
        welt.fam = _dissolve_small_biomes(welt.fam, int(0.0025 * welt.h * welt.w))


def _stempel_kacheln(welt: Welt, eintrag: dict, rng):
    """Aus einem Stempeleintrag den Kachelblock machen (Thema -> Auswahl)."""
    kacheln = eintrag["kacheln"]
    if isinstance(kacheln, tuple):
        modus, thema = kacheln
        fam = eintrag.get("familie") or welt.familie_bei(eintrag["x"], eintrag["y"])
        fam = "roc" if fam == "lav" else fam
        liste = [t for t, f in welt.tm.details if f == fam and dt.thema(t) == thema]
        if not liste and thema == dt.KRATER:
            liste = [t for t, f in welt.tm.details if f == fam and dt.thema(t) == dt.RISSE]
        if not liste:
            return None
        if modus == "gross":
            return max(liste, key=lambda t: t.size)
        return liste[int(rng.integers(len(liste)))]
    return kacheln


def _stempel_setzen(welt: Welt, grid: np.ndarray, rng) -> int:
    tm, F = welt.tm, welt.F
    h, w = grid.shape
    gesetzt = 0
    belegt = np.zeros((h, w), dtype=bool)
    versucht: dict[int, int] = {}
    begraben: dict[int, int] = {}
    for e in welt.stempel:
        versucht[e["kapitel"]] = versucht.get(e["kapitel"], 0) + 1
        if _stempel_einer(welt, grid, rng, e, belegt):
            gesetzt += 1
        elif e.get("begraben"):
            begraben[e["kapitel"]] = begraben.get(e["kapitel"], 0) + 1
    # Wurde ein Ort grossteils von spaeteren Kapiteln ueberdeckt, merkt er es
    # sich -- die Geschichte erzaehlt dann davon.
    for o in welt.orte:
        k = o.get("kapitel")
        if o["art"] in ("kolonie", "absturz") and versucht.get(k):
            o["verschuettet"] = begraben.get(k, 0) / versucht[k] > 0.3
    return gesetzt


def _stempel_einer(welt: Welt, grid: np.ndarray, rng, e: dict, belegt) -> bool:
    tm, F = welt.tm, welt.F
    h, w = grid.shape
    if True:
        kacheln = _stempel_kacheln(welt, e, rng)
        if kacheln is None:
            return False
        kacheln = np.atleast_2d(kacheln)
        dh, dw = kacheln.shape
        x = e["x"] - (dw // 2 if isinstance(e["kacheln"], tuple) else 0)
        y = e["y"] - (dh // 2 if isinstance(e["kacheln"], tuple) else 0)
        if x < 1 or y < 1 or x + dw >= w - 1 or y + dh >= h - 1:
            return False
        # Spaeter ueberdeckt (Lava, Sand)? Dann ist das Teil verschuettet.
        if (welt.zeit[y:y + dh, x:x + dw] > e["kapitel"]).any():
            e["begraben"] = True
            return False
        if e["pruefen"] and belegt[y:y + dh, x:x + dw].any():
            return False
        fam_soll = e.get("familie")
        unter = welt.fam[y:y + dh, x:x + dw]
        if fam_soll and (unter != F.get(fam_soll, -1)).any():
            return False
        if not fam_soll and len(np.unique(unter)) > 1:
            return False
        # Nur auf reinen Boden, nie auf Uebergaenge oder Klippen.
        if tm.ist_uebergang[grid[y:y + dh, x:x + dw]].any():
            return False
        if e["pruefen"] and not _naht_passt(grid, tm, kacheln, x, y):
            return False
        grid[y:y + dh, x:x + dw] = kacheln
        belegt[y:y + dh, x:x + dw] = True
        return True
    return False


def _umfaerben(tm, grid, maske, rng) -> None:
    """Sandzellen der Maske auf Riffelsand ziehen, Nachbarschaft eingehalten."""
    san = tm.families.index("san")
    pool = np.array([t for t in range(min(2017, len(tm.family_of)))
                     if tm.family_of[t] == san and tm.placeable[t]
                     and not tm.ist_uebergang[t]
                     and ct.default_cell_type(t, fallback=-1) == ct.SLOW_PASSIBLE_2])
    if not len(pool):
        return
    gew = np.array([max(0.01, tm.usage.get(int(t), 0)) for t in pool])
    rechts = {int(t): tm.nachbarn(int(t), "rechts")[0] for t in pool}
    unten = {int(t): tm.nachbarn(int(t), "unten")[0] for t in pool}
    h, w = grid.shape
    for y, x in zip(*np.nonzero(maske)):
        if tm.ist_uebergang[grid[y, x]]:
            continue
        ok = np.ones(len(pool), dtype=bool)
        if x > 0:
            k, _ = tm.nachbarn(int(grid[y, x - 1]), "rechts")
            if k is not None:
                ok &= np.isin(pool, k)
        if y > 0:
            k, _ = tm.nachbarn(int(grid[y - 1, x]), "unten")
            if k is not None:
                ok &= np.isin(pool, k)
        if x + 1 < w and not maske[y, x + 1]:
            ok &= np.array([rechts[int(t)] is None or grid[y, x + 1] in rechts[int(t)] for t in pool])
        if y + 1 < h:
            ok &= np.array([unten[int(t)] is None or grid[y + 1, x] in unten[int(t)] for t in pool])
        if ok.any():
            p = gew * ok
            grid[y, x] = int(rng.choice(pool, p=p / p.sum()))


def erzaehle(chronik: Chronik) -> GeneratedMap:
    """Die Chronik nachspielen und die Karte daraus bauen."""
    welt = Welt(chronik)
    kapitel = list(chronik.kapitel)
    if not kapitel or kapitel[0].art != "urland":
        kapitel.insert(0, Kapitel("urland"))
    for i, k in enumerate(kapitel):
        fn = _KAPITEL.get(k.art)
        if fn is None:
            continue
        welt.kapitel_index = i
        # Eigener Zufall je Kapitel: ein Kapitel aendern laesst die anderen stehen.
        rng = np.random.default_rng([chronik.seed, i, ARTEN.index(k.art) if k.art in ARTEN else 99])
        fn(welt, k, rng)
        for o in welt.orte:
            o.setdefault("kapitel", i)

    _ordnen(welt)
    tm = welt.tm
    rng = np.random.default_rng([chronik.seed, 1000])
    fam = welt.fam
    _bewuchs_abstand(fam, tm, 1)
    h, w = fam.shape
    params = MapGenParams(width=w, height=h, seed=chronik.seed)
    vor = np.full((h, w), -1, dtype=np.int32)
    _mische_grenzen(vor, fam, tm, rng, params_style=params)
    grid = _sample_tiles(fam, rng, tm, fest=vor)
    ist = {f: fam == f for f in range(len(tm.families))}
    _repariere_kontakte(grid, fam, tm, rng, ist, (0, h, 0, w))
    nachbearbeite_uebergaenge(grid, fam, tm, rng)
    sand = fam == welt.F["san"]
    riffel = welt.riffel & (ndi.distance_transform_edt(sand) >= 4.0) & ~welt.schutz
    riffel = ndi.binary_opening(ndi.binary_closing(riffel, _rund(2)), _rund(2)) \
        & (ndi.distance_transform_edt(sand) >= 4.0)
    _umfaerben(tm, grid, riffel, rng)
    _stempel_setzen(welt, grid, rng)
    cells = _cell_types(grid)
    spawns = _pick_spawns(cells, chronik.spawns, 6, SYM_NONE, rng)
    shares = {name: float((tm.family_of[grid] == i).mean())
              for i, name in enumerate(tm.families) if (tm.family_of[grid] == i).any()}
    gen = GeneratedMap(
        tiles=grid, cells=cells, spawns=spawns,
        passable_share=float(_passable_mask(cells).mean()),
        family_share=shares, connected=_connected(cells, spawns),
        lava_zones=[z for z in welt.lava_zonen if z],
    )
    gen.story_orte = welt.orte
    gen.kapitel = kapitel
    return gen
