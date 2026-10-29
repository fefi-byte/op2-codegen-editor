"""Kantenzuordnung automatisch -- fuer die Familien ohne Handzuordnung.

Die Handzuordnung (`cliff_kanten.json`) gibt es nur fuer mud. Fuer san und
sno leitet dieses Modul dieselbe Aussage -- je Kachelseite vier Abschnitte,
FELS, BIOM oder EGAL -- aus zwei Quellen ab, die beide schon im Repo liegen:

    1. die Kachelbilder (`cliff_pixels_model.npz`): Fels oder Boden je Pixel
    2. die Paartabelle (`cliff_tiles_model.npz`): wer in den 54 Karten an
       wem lag

Der Ablauf, an mud gegen die Handzuordnung gemessen:

    Pixel       Fels/Boden je Pixel, dann je Abschnitt die Mehrheit der
                aeussersten zwei Pixelreihen
    Mehrheit    ein Abschnitt uebernimmt den Wert, den seine Partner in den
                Karten zu mindestens 80 % verlangen
    zerrissen   verlangen die Partner beides (je mindestens 10 Vorkommen),
                ist `EGAL` die einzige zutreffende Aussage (Doku Abschnitt 12)

    mud, Helligkeitsmaske:  96,8 % der Abschnitte wie von Hand,
                            0,0 % Widersprueche gegen die Karten

Fels und Boden werden je Familie getrennt: zwei Farbzentren per k-means auf
geglaetteten Pixeln, Boden ist das hellere. Bei mud traegt auch die
Helligkeit allein; bei san nicht -- dort sind orangefarbener Sand und
rotbrauner Fels fast gleich hell (Mediane 76 gegen 54, beide unter der
mud-Schwelle 80).

sno ist NICHT dabei: 9 Kacheln, 63 Vorkommen in allen 54 Karten -- die
Zuordnung widersprach den Karten zu 63,8 %, und fuer eine Wand reicht der
Vorrat ohnehin nicht (`klippe_algo.MINDEST_KACHELN` = 40).

Die Datei `cliff_kanten_auto.json` wird mit

    python mapview/cliff_kanten_auto.py

neu erzeugt. `cliff_kanten.CliffEdgeModel` liest sie fuer jede Kachel, die
NICHT von Hand bearbeitet ist -- die Handzuordnung hat immer Vorrang.

Automatic edge assignment for the families without a hand assignment, derived
from the tile images and the stock-map adjacency table.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HIER = Path(__file__).resolve().parent
PIXEL_PFAD = HIER / "cliff_pixels_model.npz"
AUSGABE = HIER / "cliff_kanten_auto.json"

SEITEN = ("N", "O", "S", "W")
GEGEN = {"N": "S", "O": "W", "S": "N", "W": "O"}
BIOM, FELS, EGAL = 0, 1, 2

TIEFE = 2            # Pixelreihen am Rand, die ein Abschnitt liest
ANTEIL = 0.5         # ab diesem Felsanteil ist ein Abschnitt FELS
MEHRHEIT = 0.8       # so einig muessen die Partner sein, um zu ueberstimmen
ZERRISSEN = 10       # je Seite so viele Vorkommen, dann EGAL

_zwischen: dict = {}


def _bilder() -> tuple[dict, dict]:
    if "bilder" not in _zwischen:
        import mapgen
        tm = mapgen.model()
        d = np.load(PIXEL_PFAD)
        bilder = {int(t): d["bilder"][i].astype(float)
                  for i, t in enumerate(d["kacheln"])}
        fam = {t: tm.families[int(tm.family_of[t])] for t in bilder}
        _zwischen["bilder"] = (bilder, fam)
    return _zwischen["bilder"]


def _glatt(img: np.ndarray, k: int = 5) -> np.ndarray:
    h = k // 2
    p = np.pad(img, ((h, h), (h, h), (0, 0)), mode="edge")
    n = img.shape[0]
    return sum(p[i:i + n, j:j + n] for i in range(k) for j in range(k)) / (k * k)


def zentren(familie: str) -> np.ndarray:
    """Zwei Farbzentren der Familie -> [Boden, Fels]."""
    schl = ("zentren", familie)
    if schl in _zwischen:
        return _zwischen[schl]
    bilder, fam = _bilder()
    ts = [t for t in bilder if fam[t] == familie]
    px = np.concatenate([_glatt(bilder[t]).reshape(-1, 3) for t in ts])
    hell = px.mean(1)
    c = np.array([px[hell > np.percentile(hell, 80)].mean(0),
                  px[hell < np.percentile(hell, 20)].mean(0)])
    for _ in range(20):
        z = ((px[:, None, :] - c[None]) ** 2).sum(2).argmin(1)
        c = np.array([px[z == i].mean(0) if (z == i).any() else c[i]
                      for i in range(2)])
    if c[0].mean() < c[1].mean():
        c = c[::-1]
    _zwischen[schl] = c
    return c


def felsmaske(kachel: int) -> np.ndarray:
    """32x32 Fels (True) / Boden (False) aus dem Kachelbild."""
    bilder, fam = _bilder()
    c = zentren(fam[kachel])
    g = _glatt(bilder[kachel])
    return ((g - c[1]) ** 2).sum(2) < ((g - c[0]) ** 2).sum(2)


def _rand(f: np.ndarray, r: str) -> np.ndarray:
    if r == "N":
        b = f[:TIEFE, :].mean(0)
    elif r == "S":
        b = f[-TIEFE:, :].mean(0)
    elif r == "W":
        b = f[:, :TIEFE].mean(1)
    else:
        b = f[:, -TIEFE:].mean(1)
    return b.reshape(4, -1).mean(1)


def _paare(familie: str) -> list:
    from cliff_tiles import modell as _tm
    tt = _tm()
    bilder, fam = _bilder()
    ts = {t for t in bilder if fam[t] == familie}
    out = []
    for r in SEITEN:
        for a in ts:
            for b, n in tt.nachbarn(a, r).items():
                if b in ts:
                    out.append((a, b, r, n))
    return out


def _stimmen(kanten: dict, pp: list) -> dict:
    st: dict = defaultdict(Counter)
    for a, b, r, n in pp:
        sa, sb = kanten[a][r], kanten[b][GEGEN[r]]
        for i in range(4):
            if sb[i] != EGAL:
                st[(a, r, i)][sb[i]] += n
            if sa[i] != EGAL:
                st[(b, GEGEN[r], i)][sa[i]] += n
    return st


def zuordnen(familie: str) -> dict:
    """-> {kachel: {seite: (4 Abschnitte)}} fuer eine Familie."""
    bilder, fam = _bilder()
    ts = [t for t in bilder if fam[t] == familie]
    kanten = {}
    for t in ts:
        f = felsmaske(t)
        kanten[t] = {r: tuple(FELS if v >= ANTEIL else BIOM
                              for v in _rand(f, r)) for r in SEITEN}
    pp = _paare(familie)
    for _ in range(3):
        neu = 0
        for (t, r, i), c in _stimmen(kanten, pp).items():
            w, m = c.most_common(1)[0]
            if m / sum(c.values()) >= MEHRHEIT and kanten[t][r][i] != w:
                seite = list(kanten[t][r])
                seite[i] = w
                kanten[t][r] = tuple(seite)
                neu += 1
        if not neu:
            break
    for (t, r, i), c in _stimmen(kanten, pp).items():
        if c[BIOM] >= ZERRISSEN and c[FELS] >= ZERRISSEN:
            seite = list(kanten[t][r])
            seite[i] = EGAL
            kanten[t][r] = tuple(seite)
    return kanten


def widersprueche(kanten: dict, familie: str) -> float:
    """Anteil der Vorkommen in den Karten, die die Zuordnung verbietet."""
    pp = _paare(familie)
    z = ges = 0
    for a, b, r, n in pp:
        ges += n
        sa, sb = kanten[a][r], kanten[b][GEGEN[r]]
        if not all(x == y or EGAL in (x, y) for x, y in zip(sa, sb)):
            z += n
    return z / max(1, ges)


def schreiben(familien=("san",), pfad: Path = AUSGABE) -> dict:
    aus = {}
    bericht = {}
    for f in familien:
        k = zuordnen(f)
        bericht[f] = (len(k), widersprueche(k, f))
        for t, e in k.items():
            aus[str(t)] = {r: list(v) for r, v in e.items()}
    pfad.write_text(json.dumps({
        "hinweis": "automatisch erzeugt von cliff_kanten_auto.py -- nicht "
                   "von Hand bearbeiten; Handzuordnung hat Vorrang",
        "kanten": aus}, indent=0), encoding="utf-8")
    return bericht


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HIER))
    for f, (n, w) in schreiben().items():
        print(f"{f}: {n} Kacheln, Widersprueche gegen die Karten {100 * w:.1f} %")
