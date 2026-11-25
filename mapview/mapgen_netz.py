"""Gelernter Kartengenerator: Karten im Stil der Originalkarten.

Zwei kleine neuronale Netze, gelernt an 61 Karten (Originale und OPU):

1. **Skizze** (`netz_skizze.onnx`, 0,7 Mio. Gewichte): legt Waende und Boeden
   auf einem groben Raster an. Vorgabe sind Zonen: 1 = Berg oder Schlucht (eng,
   kein Bauplatz), 2 = Hochebene, Tal, Bauland, 0 = egal.
2. **Kacheln** (`netz_kacheln.onnx`, 1,3 Mio. Gewichte): malt die Karte Kachel
   fuer Kachel nach dieser Skizze. Gesetzt werden nur Kachelpaare, die in den
   Lernkarten vorkommen (`netz_tabellen.npz`).

Gerechnet wird mit ONNX Runtime auf der CPU; ohne das Paket `onnxruntime` gibt
es diese Vorlage nicht (`verfuegbar()`). Wie gelernt und gemessen wurde, steht
in `docs/kartenmodell.md`.

Learned map generator: maps in the style of the original maps. Two small neural
networks trained on 61 maps: the sketch lays out walls and grounds from zones,
the tile network paints the map from the sketch, using only tile pairs that
occur in the training maps. Runs on ONNX Runtime (CPU); without the package
`onnxruntime` the template is not available.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import celltypes
import mapgen
import mapgen_netz_waende as waende
import shapegen
from mapgen_basis import (
    FEAT_BERG,
    FEAT_ENGE,
    FEAT_FREI,
    FEAT_PLATEAU,
    FEAT_TAL,
    SYM_MIRROR_X,
    SYM_MIRROR_Y,
    SYM_NONE,
    SYM_QUAD,
    SYM_ROT180,
    GeneratedMap,
    MapGenParams,
)
from mapgen_berge import (
    WELT_RAND,
    BergPlan,
    _fluten,
    bauplatz_maske,
    welt_plan,
    zonen_bericht,
)
from mapgen_felder import _components, _naht_passt, _scatter_details
from mapgen_relief import _feature_layout, _feature_maske
from mapgen_wege import _connected, _groesstes_gebiet, _passable_mask, _pick_spawns

HIER = Path(__file__).resolve().parent

# Boeden der Skizze -> Kachelfamilien; 4 = sonstiges, gilt als Erde.
# Sketch grounds -> tile families.
BOEDEN = ("mud", "roc", "san", "veg")
# Anteile in den Lernkarten; daran haengt der Mischungsregler.
# Shares in the training maps; the mix sliders are relative to these.
BODEN_ANTEIL = np.array([.59, .19, .20, .02, .004])
BERG_AUF_SAND = .06              # Originale: 94 % Erde, 6 % Sand
WAND_VERSTAERKUNG = 30.0         # Skizze sagt Wand -> Wandkacheln bevorzugen
NORD_VERSTAERKUNG = 2.0          # Nordkanten sind nur eine Zelle dick

# Runden beim Malen je Guetestufe. / Painting rounds per quality level.
STUFEN = {"schnell": 6, "gut": 24}


class Abgebrochen(Exception):
    """Der Nutzer hat neu gewuerfelt oder abgebrochen. / Cancelled."""


# --------------------------------------------------------------------------
# Laden / loading

_geladen: dict = {}


def _modell():
    """Netze und Tabellen einmal laden -> Namensraum oder Ausnahme."""
    if "m" in _geladen:
        return _geladen["m"]
    import onnxruntime as ort
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = max(1, min(8, (os.cpu_count() or 4) // 2))
    opt.log_severity_level = 3

    def netz(name):
        return ort.InferenceSession(str(HIER / name), opt,
                                    providers=["CPUExecutionProvider"])
    d = np.load(HIER / "netz_tabellen.npz")
    m = type("Modell", (), {})()
    m.skizze, m.kacheln = netz("netz_skizze.onnx"), netz("netz_kacheln.onnx")
    m.vok = d["vok"].astype(np.int32)
    m.n = len(m.vok)
    m.maske = m.n + 1
    m.rechts = np.unpackbits(d["rechts"], axis=1)[:, :m.n].astype(bool)
    m.unten = np.unpackbits(d["unten"], axis=1)[:, :m.n].astype(bool)
    m.links, m.oben = m.rechts.T.copy(), m.unten.T.copy()
    zt = np.array([celltypes.default_cell_type(int(t)) for t in m.vok], np.uint8)
    m.wand = np.isin(zt, _KLIPPEN)
    m.wand_idx = np.flatnonzero(m.wand)
    m.frei = _passable_mask(zt)
    _geladen["m"] = m
    return m


_KLIPPEN = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
            celltypes.CLIFFS_LOW_SIDE)


def verfuegbar() -> bool:
    """Sind onnxruntime und die Modelldateien da? (ohne sie zu laden)"""
    import importlib.util
    return (importlib.util.find_spec("onnxruntime") is not None
            and all((HIER / n).is_file() for n in (
                "netz_skizze.onnx", "netz_kacheln.onnx", "netz_tabellen.npz")))


# --------------------------------------------------------------------------
# Hilfen / helpers

def _dehne(m: np.ndarray, n: int) -> np.ndarray:
    for _ in range(n):
        q = m.copy()
        q[1:] |= m[:-1]
        q[:-1] |= m[1:]
        q[:, 1:] |= m[:, :-1]
        q[:, :-1] |= m[:, 1:]
        m = q
    return m


def _rand_ebenen(h: int, w: int, weite: int) -> np.ndarray:
    """Naehe zu den vier Kartenraendern, als Eingabe der Netze."""
    y, x = np.mgrid[:h, :w].astype(np.float32)
    return np.stack([np.clip(1 - y / weite, 0, 1), np.clip(1 - (h - 1 - y) / weite, 0, 1),
                     np.clip(1 - x / weite, 0, 1), np.clip(1 - (w - 1 - x) / weite, 0, 1)])


def _softmax(a: np.ndarray, achse: int = -1) -> np.ndarray:
    a = a - a.max(achse, keepdims=True)
    np.exp(a, out=a)
    a /= a.sum(achse, keepdims=True)
    return a


def _spiegel(a: np.ndarray, sym: str, wand: bool = False) -> np.ndarray:
    """Grundhaelfte auf die andere uebertragen; bei Waenden dreht sich die
    Fallrichtung mit. Copy the base half; wall directions are mirrored too."""
    out = a.copy()
    h, w = a.shape

    def tausch(teil, tabelle):
        return tabelle[teil] if wand else teil
    if sym in (SYM_MIRROR_X, SYM_QUAD):
        out[:, w // 2:] = tausch(out[:, :w // 2][:, ::-1], waende.SPIEGEL_X)
    if sym in (SYM_MIRROR_Y, SYM_QUAD):
        out[h // 2:] = tausch(out[:h // 2][::-1], waende.SPIEGEL_Y)
    if sym == SYM_ROT180:
        out[h // 2:] = tausch(out[:h // 2][::-1, ::-1], waende.DREHEN)
    return out


# --------------------------------------------------------------------------
# 1. Skizze / sketch

@dataclass
class Skizze:
    """Waende und Boeden auf halber Aufloesung, dazu die Zonen der Karte."""
    wand: np.ndarray                 # (h/2, w/2), 0..8
    boden: np.ndarray                # (h/2, w/2), 0..4
    zonen: np.ndarray                # (h, w): 1 Berg 2 Hochebene 3 Tal 4 Schlucht
    plan: BergPlan


def _zonen(params: MapGenParams) -> tuple[np.ndarray, BergPlan]:
    """Zonen aus den Reglern (Berge, Schluchten, ...) und den Merkmalen, auf der
    groesseren Welt; der Plan ist schon der Ausschnitt der Karte.
    Zones on the larger world; the plan is already the map's cutout."""
    plan = welt_plan(params)
    z = np.zeros((params.height + 2 * WELT_RAND, params.width + 2 * WELT_RAND), np.int8)
    for e in plan.taeler:
        z[e.sohle] = 3
    for e in plan.schluchten:
        z[e.sohle] = 4
    for m in plan.hochebenen:
        z[m] = 2
    if plan.stufen:
        z[plan.stufen[0]] = 1
    rng = np.random.default_rng([int(params.seed) & 0xFFFFFFFF, 61])
    for eintrag in _feature_layout(params, rng):
        art = eintrag["feat"].kind
        eintrag["x"] += WELT_RAND
        eintrag["y"] += WELT_RAND
        if "pfad" in eintrag:
            eintrag["pfad"] = [(x + WELT_RAND, y + WELT_RAND) for x, y in eintrag["pfad"]]
        maske = _feature_maske(eintrag, z.shape)
        if art == FEAT_BERG:
            z[maske] = 1
        elif art in (FEAT_PLATEAU, FEAT_FREI):
            z[maske] = 2
        elif art == FEAT_TAL:
            z[_feature_maske(eintrag, z.shape, rand=5)] = 1
            z[maske] = 3
        elif art == FEAT_ENGE:
            z[maske] = 4
            z[shapegen.riegel(z.shape, eintrag["pfad"], len(eintrag["pfad"]) // 2,
                              max(2, eintrag["breite"] // 2), rng) > 0] = 1
    if params.symmetry != SYM_NONE:
        z = _spiegel(z, params.symmetry)
    return z, plan.ausschneiden()


def _zonenraster(z: np.ndarray, params: MapGenParams, rng) -> np.ndarray:
    """Zonen -> Vorgabe je Skizzenfeld: 1 eng, 2 Bauland, 0 egal.

    Was keine Zone ist, wird je nach Klippenregler in grossen Flaechen zu
    Bauland erklaert -- sonst fuellt das Netz alles mit Waenden. Um Berge bleibt
    ein Saum frei. What is no zone becomes building ground in large areas,
    depending on the cliff slider; otherwise the network fills it with walls."""
    h, w = z.shape
    v = z.reshape(h // 4, 4, w // 4, 4)
    eng = ((v == 1) | (v == 4)).mean((1, 3))
    bau = ((v == 2) | (v == 3)).mean((1, 3))
    o = np.where(eng >= .5, 1, np.where(bau >= .5, 2, 0))
    f = rng.normal(size=((h // 8 + 1), (w // 8 + 1)))
    for _ in range(6):
        p = np.pad(f, 1, mode="edge")
        f = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + p[1:-1, 1:-1]) / 5
    f = np.kron(f, np.ones((2, 2)))[:h // 4, :w // 4]
    rest = (o == 0) & ~_dehne(o == 1, 2)
    anteil = float(np.clip(1 - params.cliffs / .40, 0, 1))
    if rest.any() and anteil > 0:
        o[rest & (f <= np.quantile(f[rest], anteil))] = 2
    return np.kron(o, np.ones((2, 2), np.int64)).astype(np.int64)


def _bergboden(zone: np.ndarray, rng) -> np.ndarray:
    """Je Berg ein Boden samt Saum: Erde, selten Sand. 5 = nicht vorgegeben."""
    eng = zone[::2, ::2] == 1
    o = np.full(eng.shape, 5, np.int64)
    nummern, n = waende.label(eng)
    for i in range(1, n + 1):
        boden = waende.SAND if rng.random() < BERG_AUF_SAND else waende.ERDE
        m = nummern == i
        o[_dehne(m, 2) & (o == 5)] = boden
        o[m] = boden
    return np.kron(o, np.ones((2, 2), np.int64))


def _skizze_ziehen(m, zone, boden0, soll, rng, runden: int, pruefe,
                   temperatur: float = .94, zonenkraft: float = .7) -> tuple:
    """Eine Skizze aus dem Netz ziehen, in zufaelliger Reihenfolge.

    Nicht die sichersten Felder zuerst: am sichersten ist fast ueberall "keine
    Wand", und die Karte bliebe leer. `zonenkraft` verstaerkt die Zonenvorgabe.
    Random order, not most-certain-first: "no wall" is the safest almost
    everywhere and the map would stay empty."""
    h, w = zone.shape
    wand = np.full((h, w), 9, np.int64)
    boden = boden0.copy()
    leer = np.zeros_like(zone)
    pos = _rand_ebenen(h, w, 8)[None]

    def mischung():
        """Zuschlag je Boden: erst nach den Lernkarten, dann nachgeregelt nach
        dem, was schon liegt. Per-ground bias, corrected by what is laid so far."""
        if soll is None:
            return np.zeros(5, np.float32)
        liegt = np.bincount(boden[boden < 5], minlength=5)
        ist = liegt / max(1, liegt.sum()) if liegt.sum() > .04 * boden.size \
            else BODEN_ANTEIL
        return (1.2 * np.log((soll + .004) / (ist + .004))).clip(-4, 4).astype(np.float32)

    def wahrscheinlich():
        e = dict(wand=wand[None], boden=boden[None], zone=zone[None], pos=pos)
        lw, lb = m.skizze.run(None, e)
        ohne = m.skizze.run(None, {**e, "zone": leer[None]})
        lw = lw + zonenkraft * (lw - ohne[0])
        lb = lb + mischung()[None, :, None, None]
        return (_softmax(lw[0].transpose(1, 2, 0) / temperatur),
                _softmax(lb[0].transpose(1, 2, 0)))

    def setze(felder, bloecke):
        pw, pb = wahrscheinlich()
        if len(felder):
            y, x = felder.T
            wand[y, x] = (pw[y, x].cumsum(-1) > rng.random((len(felder), 1))).argmax(-1)
        if len(bloecke):
            y, x = bloecke.T
            mittel = pb.reshape(h // 2, 2, w // 2, 2, 5).mean((1, 3))[y, x]
            c = (mittel.cumsum(-1) > rng.random((len(bloecke), 1))).argmax(-1)
            for dy in (0, 1):
                for dx in (0, 1):
                    boden[2 * y + dy, 2 * x + dx] = c

    offen_w = rng.permutation(np.argwhere(wand == 9))
    offen_b = rng.permutation(np.argwhere(boden[::2, ::2] == 5))
    plan = 1 - np.cos(np.pi / 2 * np.linspace(0, 1, runden + 1))
    a = b = 0
    for r in range(runden):
        pruefe()
        a2 = int(round(len(offen_w) * plan[r + 1]))
        b2 = int(round(len(offen_b) * min(1, plan[r + 1] * 2)))
        setze(offen_w[a:a2], offen_b[b:b2])
        a, b = a2, b2
    # Ein Nachzug: ein Achtel der Felder noch einmal, jetzt mit allen Nachbarn.
    # One more pass over an eighth of the cells, now with all neighbours known.
    nochmal = rng.random((h, w)) < .12
    wand[nochmal] = 9
    setze(np.argwhere(nochmal), np.zeros((0, 2), int))
    return wand, boden


def _mischung(params: MapGenParams) -> np.ndarray | None:
    """Mischungsregler -> gewuenschter Anteil je Boden (Schnee gibt es nicht)."""
    soll = np.array([params.mix.get(b, 0.0) for b in BOEDEN] + [0.0])
    return soll / soll.sum() if soll.sum() > 0 else None


def skizze(params: MapGenParams, abbruch=None) -> Skizze:
    """Die Skizze einer Karte (etwa eine Sekunde): gezogen auf der groesseren
    Welt und dann ausgeschnitten.

    `abbruch()` -> True bricht mit `Abgebrochen` ab."""
    m = _modell()

    def pruefe():
        if abbruch is not None and abbruch():
            raise Abgebrochen
    rng = np.random.default_rng([int(params.seed) & 0xFFFFFFFF, 60])
    z, plan = _zonen(params)
    raster = _zonenraster(z, params, rng)
    boden0 = _bergboden(raster, rng)
    soll = _mischung(params)
    klein = params.width * params.height <= 128 * 128
    r = WELT_RAND // 2
    karte = (slice(r, -r), slice(r, -r))
    ziel = .035 + .20 * params.cliffs + .3 * float((raster[karte] == 1).mean())
    bester = None
    for _ in range(2 if klein else 1):
        wand, boden = _skizze_ziehen(m, raster, boden0, soll, rng, 16, pruefe)
        wand = waende.nordkanten_ausduennen(waende.putzen(wand, raster, rng))
        note = abs(float((wand[karte] > 0).mean()) - ziel)
        if bester is None or note < bester[0]:
            bester = (note, wand, boden)
    _n, wand, boden = bester
    boden = np.where(boden > 4, 0, boden)
    if params.symmetry != SYM_NONE:
        wand = _spiegel(wand, params.symmetry, wand=True)
        boden = _spiegel(boden, params.symmetry)
    boden = waende.ein_boden_je_wand(wand, boden)
    # Erst jetzt ausschneiden: Waende laufen ueber den Rand hinaus.
    # Crop only now: walls run off the map.
    voll = (slice(WELT_RAND, -WELT_RAND), slice(WELT_RAND, -WELT_RAND))
    return Skizze(wand[karte], boden[karte], z[voll], plan)


_FARBEN = np.array([(118, 110, 92), (74, 80, 84), (196, 110, 20), (96, 104, 74),
                    (118, 110, 92)], np.uint8)


def skizzenbild(sk: Skizze) -> np.ndarray:
    """Vorschaubild der Skizze (h/2, w/2, 3), fuer die Sofortvorschau."""
    bild = _FARBEN[sk.boden].copy()
    bild[sk.wand > 0] = (34, 28, 20)
    bild[np.isin(sk.wand, waende.NORD)] = (66, 58, 46)
    return bild


# --------------------------------------------------------------------------
# 2. Kacheln / tiles

class _Maler:
    """Malt Kacheln nach der Skizze. Gitter: Nummern im Vokabular."""

    def __init__(self, sk: Skizze, pruefe):
        self.m = _modell()
        self.sw = np.kron(sk.wand, np.ones((2, 2), np.int64))
        self.sb = np.kron(sk.boden, np.ones((2, 2), np.int64))
        self.h, self.w = self.sw.shape
        self.pos = _rand_ebenen(self.h, self.w, 12)
        self.pruefe = pruefe
        self._masken()

    def _masken(self):
        self.nah = _dehne(self.sw > 0, 3)
        self.nord = np.isin(self.sw, waende.NORD)
        self.muss = (self.sw > 0) & ~self.nord

    def wahrscheinlich(self, g, offen, temperatur, rand=20):
        """Wahrscheinlichkeiten der offenen Felder, gerechnet nur im Ausschnitt
        um sie. Probabilities of the open cells, computed only around them."""
        y0, x0 = np.maximum(offen.min(0) - rand, 0) // 4 * 4
        y1, x1 = -(-(offen.max(0) + 1 + rand) // 4) * 4
        y1, x1 = min(self.h, int(y1)), min(self.w, int(x1))
        s = (slice(int(y0), y1), slice(int(x0), x1))
        breite = x1 - int(x0)
        idx = (offen[:, 0] - y0) * breite + (offen[:, 1] - x0)
        a = self.m.kacheln.run(None, dict(
            x=g[s][None], pos=self.pos[:, s[0], s[1]][None], wand=self.sw[s][None],
            boden=self.sb[s][None], idx=idx.astype(np.int64)))[0]
        p = _softmax(a / temperatur)
        y, x = offen.T
        f = np.where(self.nah[y, x], 1.0, .01)
        f = f * np.where(self.muss[y, x], WAND_VERSTAERKUNG, 1.0)
        f = f * np.where(self.nord[y, x], NORD_VERSTAERKUNG, 1.0)
        p[:, self.m.wand_idx] *= f.astype(np.float32)[:, None]
        p /= p.sum(-1, keepdims=True)
        return p

    def erlaubt(self, g, y, x):
        """Kacheln, die zu allen schon gesetzten Nachbarn passen."""
        m, n = self.m, self.m.n
        e = np.ones(n, bool)
        if x > 0 and g[y, x - 1] < n:
            e &= m.rechts[g[y, x - 1]]
        if x < self.w - 1 and g[y, x + 1] < n:
            e &= m.links[g[y, x + 1]]
        if y > 0 and g[y - 1, x] < n:
            e &= m.unten[g[y - 1, x]]
        if y < self.h - 1 and g[y + 1, x] < n:
            e &= m.oben[g[y + 1, x]]
        return e

    def fuelle(self, g, rng, runden, temperatur, fest, rand=20, melde=None):
        """Offene Felder setzen, sichere zuerst; Sackgassen wieder oeffnen.
        Fill the open cells, certain ones first; reopen dead ends."""
        m = self.m
        n0 = int((g == m.maske).sum())
        for r in range(1, runden * 2 + 1):
            offen = np.argwhere(g == m.maske)
            if not len(offen):
                return g
            self.pruefe()
            t = min(1.0, r / runden)
            anzahl = len(offen) if t >= 1 else max(
                1, len(offen) - int(n0 * np.cos(np.pi / 2 * t)))
            p = self.wahrscheinlich(g, offen, temperatur, rand)
            sicher = np.log(p.max(-1) + 1e-9) + rng.gumbel(size=len(offen)) * 1.2 * (1 - t)
            for i in np.argsort(-sicher)[:anzahl].tolist():
                y, x = offen[i]
                c = (p[i] * self.erlaubt(g, y, x)).cumsum()
                if c[-1] < 1e-12:
                    s = (slice(max(0, y - 1), y + 2), slice(max(0, x - 1), x + 2))
                    g[s][~fest[s]] = m.maske
                    continue
                g[y, x] = min(int(np.searchsorted(c, rng.random() * c[-1], side="right")),
                              m.n - 1)
            if melde is not None:
                melde(t)
        rest = np.argwhere(g == m.maske)
        if len(rest):
            p = self.wahrscheinlich(g, rest, temperatur, rand)
            for i, (y, x) in enumerate(rest.tolist()):
                e = self.erlaubt(g, y, x)
                g[y, x] = int(np.where(e, p[i], -1.0).argmax() if e.any() else p[i].argmax())
        return g

    def falsch(self, g) -> np.ndarray:
        """Zellen mit einem Nachbarpaar, das keine Lernkarte kennt."""
        b = np.zeros(g.shape, bool)
        r = ~self.m.rechts[g[:, :-1], g[:, 1:]]
        u = ~self.m.unten[g[:-1], g[1:]]
        b[:, :-1] |= r
        b[:, 1:] |= r
        b[:-1] |= u
        b[1:] |= u
        return b

    def flicke(self, g, rng, mal=6):
        """Unbekannte Kachelpaare neu malen, Stelle fuer Stelle.
        Repaint unknown tile pairs, spot by spot."""
        for k in range(mal):
            b = self.falsch(g)
            if not b.any():
                break
            breit = _dehne(_dehne(b, 1), 1)
            nummern, n = waende.label(breit)
            nummern = np.where(b, nummern, 0)
            for i in range(1, n + 1):
                z = np.argwhere(nummern == i)
                if not len(z):
                    continue
                y0, x0 = np.maximum(z.min(0) - 8, 0)
                y1, x1 = z.max(0) + 9
                s = (slice(int(y0), int(y1)), slice(int(x0), int(x1)))
                m = np.zeros_like(b)
                m[z[:, 0], z[:, 1]] = True
                m = _dehne(m, 1 + k // 2)
                neu = g.copy()
                neu[m] = self.m.maske
                neu = self.fuelle(neu, rng, 4, 1.0, ~m, rand=10)
                if self.falsch(neu[s]).sum() <= self.falsch(g[s]).sum():
                    g = neu
        return g

    def reste_weg(self, g, rng, mindest=10):
        """Winzige Wandinseln mit Boden uebermalen. / Paint over tiny wall bits."""
        for r in range(4):
            wand = self.m.wand[g]
            nummern, n = waende.label(wand)
            groesse = np.bincount(nummern.ravel(), minlength=n + 1)
            # Am Kartenrand setzt sich eine Wand gedacht fort.
            # At the map border a wall continues off the map.
            rand = np.unique(np.concatenate((nummern[0], nummern[-1],
                                             nummern[:, 0], nummern[:, -1])))
            grenze = np.full(n + 1, mindest)
            grenze[rand] = 4
            klein = wand & (groesse < grenze)[nummern]
            if not klein.any():
                break
            m = _dehne(klein, 1 + r // 2) & ~(wand & ~klein)
            self.sw = np.where(m, 0, self.sw)
            nah = self.nah
            self._masken()
            self.nah = nah & ~m & self.nah
            neu = g.copy()
            neu[m] = self.m.maske
            g = self.fuelle(neu, rng, 5, .8, ~m)
        self._masken()
        return g

    def bauplatz(self, g):
        """Zellen mit freiem 7x7-Quadrat, und die Eckpunkte dieser Quadrate."""
        f = self.m.frei[g]
        n = mapgen.BAUPLATZ
        s = np.zeros((self.h + 1, self.w + 1), np.int64)
        s[1:, 1:] = f.cumsum(0).cumsum(1)
        voll = (s[n:, n:] - s[:-n, n:] - s[n:, :-n] + s[:-n, :-n]) == n * n
        aus = np.zeros((self.h, self.w), bool)
        for dy in range(n):
            for dx in range(n):
                aus[dy:dy + voll.shape[0], dx:dx + voll.shape[1]] |= voll
        return aus, voll

    def bergstufen(self, g, berg, dichte, rng):
        """Bauplatz im Berg auf der fertigen Karte suchen, eine Wandstufe
        einzeichnen und nur diese Stelle neu malen. Auf Sand nie.
        Find building ground inside a mountain, draw a terrace there and repaint
        only that spot. Never on sand."""
        runden, ziel = int(round(14 * dichte * dichte)), .16 - .12 * dichte
        kurz = 5 if dichte < .8 else 3
        abstand = 3
        hh, hw = self.h // 2, self.w // 2
        for _ in range(runden):
            self.pruefe()
            bau, voll = self.bauplatz(g)
            if not berg.any() or (bau & berg).sum() <= ziel * berg.sum():
                break
            mitte = mapgen.BAUPLATZ // 2
            in_berg = voll & berg[mitte:mitte + voll.shape[0], mitte:mitte + voll.shape[1]]
            wand = self.m.wand[g]
            nahe = _dehne(wand, abstand)
            orte = np.argwhere(wand)
            gemalt = np.zeros_like(wand)
            sw = self.sw.copy()
            for y, x in (rng.permutation(np.argwhere(in_berg)) + mitte).tolist():
                if self.sb[y, x] == waende.SAND or \
                        gemalt[max(0, y - 7):y + 8, max(0, x - 7):x + 8].any():
                    continue
                r = int(rng.integers(5))
                if len(orte):
                    c = orte[np.abs(orte - (y, x)).sum(1).argmin()]
                    v = int(self.sw[c[0], c[1]])
                    if v and v not in waende.NORD:
                        r = v - 1
                linie = {}
                for sinn in (-1, 1):
                    t = waende.tangente(r) * sinn
                    fy, fx = y / 2, x / 2
                    dreh = float(rng.normal(0, .10))
                    for _k in range(int(rng.integers(3, 9))):
                        p = (int(fy), int(fx))
                        if not (0 <= p[0] < hh and 0 <= p[1] < hw) \
                                or not berg[2 * p[0], 2 * p[1]] \
                                or nahe[2 * p[0]:2 * p[0] + 2, 2 * p[1]:2 * p[1] + 2].any():
                            break
                        linie[p] = waende.fallrichtung(t * sinn) + 1
                        a = np.arctan2(t[1], t[0]) + dreh
                        t = np.array([np.cos(a), np.sin(a)])
                        fx += t[0]
                        fy += t[1]
                if len(linie) < kurz:
                    continue
                for (a, b), v in linie.items():
                    sw[2 * a:2 * a + 2, 2 * b:2 * b + 2] = v
                    gemalt[2 * a:2 * a + 2, 2 * b:2 * b + 2] = True
            if not gemalt.any():
                abstand -= 1
                if dichte < .8 or abstand < 0:
                    break
                continue
            self.sw = sw
            self._masken()
            m = _dehne(gemalt, 4) & ~(wand & ~gemalt)
            neu = g.copy()
            neu[m] = self.m.maske
            g = self.fuelle(neu, rng, 10, .9, ~m)
        return g


# --------------------------------------------------------------------------
# 3. Nacharbeit / finishing

class _Nacharbeit:
    """Objekte, Bodensprenkel und Notfelsen auf der fertigen Kachelkarte."""

    def __init__(self, tm, rng):
        self.tm, self.rng = tm, rng
        n = 2048
        self.zt = np.array([celltypes.default_cell_type(t) for t in range(n)], np.uint8)
        self.wand = np.isin(self.zt, _KLIPPEN)
        ueb = np.zeros(n, bool)
        ueb[:len(tm.ist_uebergang)] = tm.ist_uebergang[:n]
        fuell = (tm.family_of >= 0) & tm.placeable
        det = np.zeros(n, bool)
        for block, _f in tm.details:
            det[np.unique(block)] = True
        self.objekt = (det & ~fuell | np.isin(self.zt, (celltypes.IMPASSIBLE_1,
                                                        celltypes.IMPASSIBLE_2))) \
            & ~self.wand & ~ueb
        self.ueb = ueb
        self.rein = np.where((tm.family_of >= 0) & ~ueb & ~self.wand, tm.family_of, -1)
        self.fuell = {f: np.flatnonzero(fuell & (tm.family_of == f) & ~self.wand & ~ueb
                                        & ~self.objekt)
                      for f in range(len(tm.families))}

    def _passt(self, t, y, x, k) -> bool:
        tm = self.tm
        h, w = t.shape
        for a, b, r in (([(t[y, x - 1], k, "rechts")] if x else [])
                        + ([(k, t[y, x + 1], "rechts")] if x < w - 1 else [])
                        + ([(t[y - 1, x], k, "unten")] if y else [])
                        + ([(k, t[y + 1, x], "unten")] if y < h - 1 else [])):
            bekannt, _g = tm.nachbarn(int(a), r)
            if bekannt is not None and int(b) not in bekannt:
                return False
        return True

    def _boden(self, t, y, x, familie):
        liste = self.fuell.get(int(familie))
        if liste is None or not len(liste):
            return
        probe = self.rng.permutation(liste)[:40]
        t[y, x] = next((k for k in probe.tolist() if self._passt(t, y, x, k)), probe[0])

    def _familie(self, t):
        """Bodenfamilie je Zelle; Waende und Objekte erben vom Nachbarn."""
        f = np.where(self.objekt[t], -1, self.rein[t])
        for _ in range(24):
            leer = f < 0
            if not leer.any():
                break
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                v = np.full_like(f, -1)
                h, w = f.shape
                v[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] = \
                    f[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
                f = np.where((f < 0) & (v >= 0), v, f)
        return f

    def objekte(self, t, behalten: float):
        """Ganze Objekte entfernen, nur der Anteil `behalten` bleibt."""
        nummern, n = waende.label(self.objekt[t])
        weg = np.concatenate(([False], self.rng.random(n) >= behalten))[nummern]
        familie = self._familie(t)
        for _ in range(2):
            for y, x in np.argwhere(weg & self.objekt[t]).tolist():
                self._boden(t, y, x, familie[y, x])

    def sprenkel(self, t, gross: int = 30):
        """Winzige Flecken fremden Bodens im Umgebungsboden aufloesen."""
        fam = {b: self.tm.families.index(b) for b in ("mud", "roc", "san")
               if b in self.tm.families}
        for _ in range(2):
            for f in fam.values():
                fremd = (self.rein[t] != f) & ~self.wand[t]
                nummern, n = waende.label(fremd)
                groesse = np.bincount(nummern.ravel(), minlength=n + 1)
                groesse[0] = gross
                groesse[np.unique(np.concatenate((nummern[0], nummern[-1],
                                                  nummern[:, 0], nummern[:, -1])))] += 12
                klein = np.flatnonzero(groesse < gross)
                if not len(klein):
                    continue
                zellen = np.argwhere(np.isin(nummern, klein))
                je = {}
                for y, x in zellen.tolist():
                    je.setdefault(int(nummern[y, x]), []).append((y, x))
                for z in je.values():
                    ks = np.array([t[p] for p in z])
                    andere = [v for v in fam.values() if v != f]
                    if not (np.isin(self.rein[ks], andere) | self.ueb[ks]).any():
                        continue                 # nur Objekte / objects only
                    a = np.array(z)
                    y0, x0 = np.maximum(a.min(0) - 1, 0)
                    y1, x1 = a.max(0) + 2
                    um = self.rein[t[y0:y1, x0:x1]]
                    if (um == f).sum() < .6 * max(1, um.size - len(z)):
                        continue
                    for y, x in z:
                        self._boden(t, y, x, f)

    def felsen(self, t, eng, ziel: float = .04):
        """Notbehelf: unpassierbare Felsen und Krater dorthin, wo in Berg oder
        Schlucht noch gebaut werden koennte. Nie auf Sand.
        Last resort: impassable rocks where one could still build inside a
        mountain or gorge. Never on sand."""
        blocked = (celltypes.IMPASSIBLE_1, celltypes.IMPASSIBLE_2)
        stempel = [b for b, _f in self.tm.details
                   if max(b.shape) <= 4 and np.isin(self.zt[b], blocked).any()]
        san = self.tm.families.index("san") if "san" in self.tm.families else -2
        eng = eng & (self._familie(t) != san)
        n = mapgen.BAUPLATZ
        h, w = t.shape
        fehl = 0
        while stempel and eng.any() and fehl < 60:
            f = _passable_mask(self.zt[t])
            s = np.zeros((h + 1, w + 1), np.int64)
            s[1:, 1:] = f.cumsum(0).cumsum(1)
            voll = (s[n:, n:] - s[:-n, n:] - s[n:, :-n] + s[:-n, :-n]) == n * n
            mitte = n // 2
            orte = np.argwhere(voll & eng[mitte:mitte + voll.shape[0],
                                          mitte:mitte + voll.shape[1]]) + mitte
            if len(orte) <= ziel * eng.sum() / 4:
                break
            # Mehrere je Durchgang, mit Abstand -- sonst dauert es ewig.
            # Several per pass, spaced out.
            gesetzt = []
            for y, x in self.rng.permutation(orte)[:40].tolist():
                if any(abs(y - a) < 8 and abs(x - b) < 8 for a, b in gesetzt):
                    continue
                b = stempel[int(self.rng.integers(len(stempel)))]
                y0, x0 = y - b.shape[0] // 2, x - b.shape[1] // 2
                feld = (slice(y0, y0 + b.shape[0]), slice(x0, x0 + b.shape[1]))
                if y0 < 0 or x0 < 0 or t[feld].shape != b.shape \
                        or self.wand[t[feld]].any() \
                        or not _naht_passt(t, self.tm, b, x0, y0):
                    continue
                t[feld] = b
                gesetzt.append((y, x))
            fehl = 0 if gesetzt else fehl + 1


def karte(params: MapGenParams, sk: Skizze, stufe: str = "schnell",
          fortschritt=None, abbruch=None) -> GeneratedMap:
    """Aus der Skizze die fertige Karte malen -> GeneratedMap.

    `fortschritt(anteil)` wird mit 0..1 gerufen; `abbruch()` -> True bricht ab.
    Paint the finished map from the sketch."""
    def melde(anteil):
        if fortschritt is not None:
            fortschritt(float(anteil))

    def pruefe():
        if abbruch is not None and abbruch():
            raise Abgebrochen
    rng = np.random.default_rng([int(params.seed) & 0xFFFFFFFF, 62])
    maler = _Maler(sk, pruefe)
    m = maler.m
    g = np.full((maler.h, maler.w), m.maske, np.int64)
    g = maler.fuelle(g, rng, STUFEN.get(stufe, 6), .95, np.zeros(g.shape, bool),
                     melde=lambda t: melde(.6 * t))
    melde(.6)
    g = maler.flicke(g, rng)
    melde(.75)
    g = maler.reste_weg(g, rng)
    dichte = float(np.clip(params.berg_dichte, 0, 1))
    g = maler.bergstufen(g, sk.zonen == 1, dichte, rng)
    melde(.88)
    g = maler.reste_weg(g, rng)
    g = maler.flicke(g, rng, 8)
    melde(.95)
    pruefe()

    tm = mapgen.model()
    t = m.vok[g]
    nach = _Nacharbeit(tm, rng)
    nach.sprenkel(t)
    ziel = params.details * .06
    anteil = float(nach.objekt[t].mean())
    nach.objekte(t, min(1.0, ziel / anteil) if anteil > 0 else 0.0)
    if params.berg_felsen:
        nach.felsen(t, (sk.zonen == 1) | (sk.zonen == 4))
    mehr = int(round((ziel - float(nach.objekt[t].mean())) * t.size))
    if mehr > 0 and ziel > anteil:
        _scatter_details(t, tm.family_of[t], tm, rng, mehr,
                         _dehne(nach.wand[t], 1) | np.isin(sk.zonen, (3, 4)))
    cells = nach.zt[t]
    bericht = _bericht(cells, sk)
    spawns = _startplaetze(cells, params, rng)
    anteile = {n: float((tm.family_of[t] == i).mean()) for i, n in enumerate(tm.families)}
    melde(1.0)
    return GeneratedMap(
        tiles=t.astype(np.int32), cells=cells, spawns=spawns,
        passable_share=float(_passable_mask(cells).mean()),
        family_share={n: s for n, s in anteile.items() if s > 0},
        connected=_connected(cells, spawns),
        plateau_share=float(np.isin(cells, _KLIPPEN).mean()),
        detail_share=float(nach.objekt[t].mean()), zonen=bericht)


def _bericht(cells, sk: Skizze) -> dict:
    """Wie bei den Bergen des Generators: Zahl und Guete der Zonen."""
    b = zonen_bericht(cells, sk.plan)
    frei = _passable_mask(cells)
    gebiet = np.asarray(_groesstes_gebiet(frei)).astype(bool)
    # Die Waende liegen nicht genau auf dem Plan: etwas Platz daneben zaehlt mit.
    # Walls are not exactly on the plan; some room beside it counts.
    b["durchfahrbar"] = sum(
        bool((_fluten(frei & _dehne(e.flaeche, 5), _dehne(e.ende_a, 5), False)
              & _dehne(e.ende_b, 5)).any()) for e in sk.plan.schluchten)
    berge = list(_components(sk.zonen == 1))
    ebenen = list(_components(sk.zonen == 2))
    b.update(berge=len(berge), hochebenen=len(ebenen), undicht=0,
             unerreichbar=int(sum((gebiet & e).sum() < .3 * e.sum() for e in ebenen)),
             bauplatz=float(bauplatz_maske(cells).mean()))
    return b


def _startplaetze(cells, params: MapGenParams, rng):
    """Startplaetze; bei Symmetrie nur dort, wo auch das Spiegelbild frei ist
    (die Kacheln sind es nur ungefaehr). With symmetry only where the mirror
    image is free too, since the tiles are only roughly symmetric."""
    c = cells.copy()
    if params.symmetry != SYM_NONE:
        frei = _passable_mask(c)
        bilder = {SYM_MIRROR_X: (lambda f: f[:, ::-1],), SYM_MIRROR_Y: (lambda f: f[::-1],),
                  SYM_ROT180: (lambda f: f[::-1, ::-1],),
                  SYM_QUAD: (lambda f: f[:, ::-1], lambda f: f[::-1],
                             lambda f: f[::-1, ::-1])}[params.symmetry]
        alle = frei.copy()
        for b in bilder:
            alle &= b(frei)
        c[~alle] = celltypes.IMPASSIBLE_1
    return _pick_spawns(c, params.spawns, params.spawn_clearance, params.symmetry, rng)
