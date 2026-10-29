"""Klippen algorithmisch setzen: das Gelaende bestimmt die Kachel.

Der Blockweg (`mapgen.klippe_aus_linie`) legt vorgefertigte Bloecke an die
Kante und bessert hinterher nach. Dieser Weg dreht das um -- er fragt nicht
"welche Kachel darf auf welche folgen", sondern "was verlangt das Gelaende an
dieser Stelle":

1. Das Gelaende wird viermal feiner beschrieben als das Kachelraster. Eine
   Kachel hat vier Abschnitte je Seite, also 4x4 Teilfelder je Kachel. Darin
   steht nur Fels oder Biom.

2. Fuer jede Kachel wird an ihren vier Raendern abgelesen, was das Gelaende
   dort verlangt -- 16 Abschnitte, jeder Fels oder Biom.

3. Gesetzt wird die Kachel, deren Handzuordnung genau das zeigt. EGAL passt
   auf beides, weil die Zuordnung es dort setzt, wo die Kachel selbst keine
   klare Auskunft gibt.

Damit ist ein harter Uebergang nicht mehr zu reparieren, sondern gar nicht
erst moeglich: eine Kachel, die Fels ins Biom zeigt, erfuellt die Abfrage
nicht und wird nicht gewaehlt. Dasselbe gilt fuer das Loch.

Gemessen an vier Gelaenden gegen die 51 Originalkarten:

    hart 0, Loch 0, keine unbediente Zelle
    Lauflaenge gleicher Kacheln 1,00 bis 1,04 (Originale 1,01)
    Wandhoehe 3,54 bis 3,63 (Originale 3,54)
    Fuellanteil 21 bis 33 % (Originale 16,4 %)
    regelwidrige Paare 0,9 bis 5,1 % (Originale 0,0 %)
    Naht 20,8 bis 22,0 (Originale 18,4)

Der Weg braucht die Handzuordnung der Kachelraender und laeuft darum vorerst
nur fuer `mud` -- `verfuegbar()` gibt Auskunft. Fuer die anderen Familien
bleibt der Blockweg zustaendig.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

import celltypes
from cliff_kanten import BIOM, EGAL, FELS, modell as kantenmodell
from cliff_pixels import modell as pixelmodell
from cliff_tiles import VERSATZ

SEITEN = ("N", "O", "S", "W")
FEIN = 4                       # Teilfelder je Kachel und Richtung
MINDEST_KACHELN = 40           # darunter traegt die Handzuordnung nicht

# Wieviel Naht die Abwechslung kosten darf. Die Originalkarten setzen zu 99 %
# keine zwei gleichen Kacheln nebeneinander; ohne diesen Spielraum steht auf
# einer geraden Wand acht mal dieselbe, und das ist die Treppe.
NAHT_SPIELRAUM = 3.0
NAHT_RUNDEN = 4

# Wandhoehe. Fest gewaehlt sah die Wand aus wie eine Treppe, weil Ober- und
# Unterkante im Gleichschritt sprangen.
#
# Die Dicke des FELSES, nicht der Zellen. Mit 2,5 bis 4,5 waren 43 % der
# gesetzten Kacheln Vollfels, in cm02 sind es 6,7 % -- die Originale sind ein
# duennes Felsband mit Uebergaengen drumherum, und das dicke Band zwang den
# Loeser, waagerechte Vollfelskacheln zu stapeln: die Treppe. Gemessen ueber
# 14 Waende (Zellen je Lauf, Vollfels, unbelegt, Faden = Querschnitt unter
# einer Kachel Fels):
#
#   2,5-4,5    4,45   43 %    5,0 %    0,9 %
#   1,5-2,5    3,00   21 %    3,5 %    1,5 %   <- gewaehlt
#   1,25-2,25  2,78   17 %   11,2 %    5,3 %
#   1,0-2,0    2,49   12 %   21,5 %   14,7 %   (waagerecht reisst zum Faden)
#
# cm02 hat in jeder Richtung rund 3 Zellen je Spalte.
HOEHE_MIN = 1.5
HOEHE_MAX = 2.5
UNRUHE = 0.35                  # wie stark die Oberkante wandert, in Kacheln

# Faellt die Wand nach NORDEN, sieht man keine Felswand, nur die Abbruchkante:
# in cm02 ist das eine Zelle (Zelltyp N; Spaltenmuster "N" 162x, "NN" 77x),
# gegen "HLL"/"HHLL" bei der Suedwand. Die N-Kacheln tragen innen eine einzige
# Felslinie, ein bis zwei Teilfelder dick. Dicke hier in Kacheln.
NORD_MIN = 0.25
NORD_MAX = 0.5

# Wandenden. In cm02 laeuft eine Wand ueber zwei bis drei Kacheln spitz bzw.
# rund zu; bisher war sie bis zum letzten Punkt voll dick und hoerte als
# Klumpen auf. `ENDE_LAENGE` ist die Strecke in Kacheln, auf der die Dicke
# von `ENDE_REST` (Anteil) auf voll waechst -- mit Wurzelverlauf, also rund
# statt keilfoermig. 2,5/0,15 liess die Enden sichtbar stumpf; 3,5/0 laeuft
# spitz aus. Alle 39 Pruefwaende (13 Zuege, 3 Saaten) bleiben bei jeder
# gemessenen Einstellung ohne unpassende Paare, Loch und harte Stelle.
# Die Nordkante wird nicht verjuengt -- sie ist schon eine Linie und zerfiel
# dabei.
ENDE_LAENGE = 3.5
ENDE_REST = 0.0

_zwischen: dict = {}


def _modelle():
    if "K" not in _zwischen:
        _zwischen["K"] = kantenmodell(auto=True)
        _zwischen["PX"] = pixelmodell()
    return _zwischen["K"], _zwischen["PX"]


def vorrat(tm, familie: str) -> dict:
    """Je Kachel der Familie ihre 16 Randabschnitte und ihr Fels-Anteil.

    Der Fels-Anteil stammt aus der Kantentabelle und nicht aus der Pixelflaeche
    -- gemessen macht das keinen Unterschied (Fuellanteil 25,1 gegen 26,9 %,
    alles andere gleich), spart aber die ganze Pixelrechnung zur Laufzeit.
    """
    schluessel = ("vorrat", familie)
    if schluessel in _zwischen:
        return _zwischen[schluessel]
    K, _px = _modelle()
    try:
        fi = tm.families.index(familie)
    except ValueError:
        _zwischen[schluessel] = {}
        return {}
    aus = {}
    for t in K.kanten:
        if int(tm.family_of[t]) != fi:
            continue
        s = {r: K.seite(t, r) for r in SEITEN}
        if any(v is None for v in s.values()):
            continue
        n = f = 0
        for r in SEITEN:
            for u in s[r]:
                n += 1
                if u == FELS:
                    f += 1
        aus[t] = (s, f / max(1, n))
    _zwischen[schluessel] = aus
    return aus


def verfuegbar(tm, familie: str) -> bool:
    """Traegt die Handzuordnung diese Familie schon?"""
    return len(vorrat(tm, familie)) >= MINDEST_KACHELN


# --------------------------------------------------------------- Gelaende


def _glatt(n: int, rng, staerke: float, laenge: int) -> np.ndarray:
    """Langsamer Zufallsverlauf: Rauschen, zweimal ueber `laenge` gemittelt.

    Ohne die Glaettung zackt die Kante von Teilfeld zu Teilfeld -- das waere
    keine Klippe mehr, sondern Rauschen.
    """
    laenge = max(1, laenge)
    r = rng.normal(0.0, 1.0, n + laenge * 2)
    k = np.ones(laenge) / laenge
    g = np.convolve(r, k, mode="same")
    g = np.convolve(g, k, mode="same")[laenge:laenge + n]
    s = float(g.std())
    return g / s * staerke if s > 1e-9 else g


def _wand_achse(x0, y0, x1, y1, hoch_seite: str):
    """In welche Richtung waechst die Wand von der Kante weg?

    Die Kante ist gezeichnet, das Hochland liegt auf der genannten Seite --
    die Wand faellt zur anderen.

    Die beiden Paare bedeuten NICHT dasselbe, und das ist die Falle: "oben"
    und "unten" sind bildschirmfest, "links" und "rechts" beziehen sich auf
    die ZEICHENRICHTUNG. Nach unten gezeichnet liegt links im Osten, nach oben
    gezeichnet im Westen. Wer das gleichsetzt, baut die Wand auf der falschen
    Seite -- gemessen gegen den Blockweg: der legt bei "links" und nach unten
    gezeichnet die Spalten 19 und 20 an eine Linie auf 20, also nach WESTEN.
    """
    dx, dy = x1 - x0, y1 - y0
    waagerecht = abs(dx) >= abs(dy)
    if hoch_seite in ("oben", "unten"):
        if waagerecht:
            return ("v", 1 if hoch_seite == "oben" else -1)
        # Ein senkrechtes Stueck mit "oben" sagt nichts ueber links/rechts;
        # dann bleibt nur eine Setzung.
        return ("h", 1)
    # Linke Normale in Bildschirmkoordinaten (y zeigt nach unten).
    lx, ly = dy, -dx
    if hoch_seite == "rechts":
        lx, ly = -lx, -ly
    if waagerecht:
        return ("v", -1 if ly > 0 else 1)
    return ("h", -1 if lx > 0 else 1)


# Flache Schraegen wie in den Originalen: waagerechte Laeufe, verbunden durch
# kurze 45-Grad-Abstiege. Gemessen an 20 abfallenden Suedwaenden aus allen 54
# Karten (cm03, cm04, eden03, mp4_03, mp4_06, mp4_12, ...): keine einzige
# laeuft gleichmaessig 2:1 -- jede ist eine Folge aus Plateau und 45-Grad-
# Stueck von zwei bis drei Zellen. Gleichmaessig gelegt wurde daraus bei den
# Kacheln eine Treppe aus Ein-Zellen-Versaetzen.
SCHRAEGE_ZERLEGEN = True
SCHRAEGE_STUECK = (2.0, 3.0)      # Laenge eines 45-Grad-Stuecks in Kacheln


def _schraege_profil(lx: float, ly: float, rng):
    """Flache Schraege -> (Stuetzstellen x, y) aus Plateaus und 45-Grad.

    `lx` ist die waagerechte Laenge, `ly` (<= lx) der Hoehenunterschied, beide
    in Kacheln und positiv. Die Gesamtneigung bleibt genau erhalten.
    """
    if ly < 0.75 or ly >= 0.9 * lx:
        return np.array([0.0, lx]), np.array([0.0, ly])
    k = max(1, int(round(ly / rng.uniform(*SCHRAEGE_STUECK))))
    stueck = ly / k
    flach = (lx - ly) * rng.dirichlet(np.full(k + 1, 2.0))
    xs, ys = [0.0], [0.0]
    for i in range(k + 1):
        xs.append(xs[-1] + flach[i])
        ys.append(ys[-1])
        if i < k:
            xs.append(xs[-1] + stueck)
            ys.append(ys[-1] + stueck)
    xs[-1] = lx
    return np.array(xs), np.array(ys)


def band_aus_linie(punkte, hoch_seite: str, breite: int, hoehe: int,
                   rng, hoehe_min: float = HOEHE_MIN,
                   hoehe_max: float = HOEHE_MAX, unruhe: float = UNRUHE,
                   enden: bool = True, nordenden: list | None = None):
    """Streckenzug -> (Teilfeldkarte, Achsenkarte je Zelle).

    Die Hoehe steht nicht fest: Oberkante und Dicke bekommen jede ihren
    eigenen langsamen Verlauf, damit sie nicht gemeinsam springen. Fest
    gewaehlt sah die Wand aus wie eine Treppe.
    """
    fein = np.zeros((hoehe * FEIN, breite * FEIN), dtype=bool)
    achse = np.zeros((hoehe, breite), dtype=np.uint8)     # 1 = v, 2 = h
    # Ein durchgehender Verlauf ueber den ganzen Zug, damit an einem Knick
    # kein Absatz entsteht.
    schritte = 0
    for i in range(len(punkte) - 1):
        x0, y0 = punkte[i]
        x1, y1 = punkte[i + 1]
        schritte += int(max(abs(x1 - x0), abs(y1 - y0)) * FEIN) + 1
    if schritte < 2:
        return fein, achse
    wandern = _glatt(schritte, rng, unruhe, 6 * FEIN)
    dicke_r = _glatt(schritte, rng, 1.0, 10 * FEIN)
    anteil = 0.5 + 0.5 * np.tanh(dicke_r)
    dicke = hoehe_min + (hoehe_max - hoehe_min) * anteil
    dicke_nord = NORD_MIN + (NORD_MAX - NORD_MIN) * anteil

    nordlinie = np.zeros_like(fein)
    s = 0
    for i in range(len(punkte) - 1):
        x0, y0 = punkte[i]
        x1, y1 = punkte[i + 1]
        art, ri = _wand_achse(x0, y0, x1, y1, hoch_seite)
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * FEIN) + 1
        profil = None
        if (SCHRAEGE_ZERLEGEN and art == "v" and ri > 0
                and abs(y1 - y0) > 0):
            profil = _schraege_profil(abs(x1 - x0), abs(y1 - y0), rng)
        for k in range(n):
            u = k / max(1, n - 1)
            px = (x0 + (x1 - x0) * u + 0.5) * FEIN
            if profil is None:
                py = (y0 + (y1 - y0) * u + 0.5) * FEIN
            else:
                hy = float(np.interp(abs(x1 - x0) * u, *profil))
                py = (y0 + np.sign(y1 - y0) * hy + 0.5) * FEIN
            w = wandern[min(s, schritte - 1)] * FEIN
            d = dicke[min(s, schritte - 1)] * FEIN
            # Abstand zum naechsten Ende des ganzen Zuges, in Kacheln.
            rand_ab = min(s, schritte - 1 - s) / FEIN
            ende = 1.0
            if enden and rand_ab < ENDE_LAENGE:
                ende = ENDE_REST + (1 - ENDE_REST) * (rand_ab / ENDE_LAENGE) ** 0.5
            d *= ende
            nord = art == "v" and ri < 0
            if nord:
                # Hochland im Sueden: die Wand faellt nach Norden.
                # Die Nordkante ist schon eine Linie; verjuengt zerfiel sie
                # (2:1 Nord bis Abweichung 8 unloesbar).
                d = dicke_nord[min(s, schritte - 1)] * FEIN
            s += 1
            if art == "v":
                fx = int(px)
                if not 0 <= fx < breite * FEIN:
                    continue
                a = py + w
                von, bis = (a, a + d * ri) if ri > 0 else (a + d * ri, a)
                v0 = max(0, int(round(von)))
                v1 = min(hoehe * FEIN, int(round(bis)))
                if v1 > v0:
                    fein[v0:v1, fx] = True
                    achse[v0 // FEIN:(v1 - 1) // FEIN + 1, fx // FEIN] = 1
                    if nord:
                        nordlinie[v0:v1, fx] = True
            else:
                fy = int(py)
                if not 0 <= fy < hoehe * FEIN:
                    continue
                a = px + w
                von, bis = (a, a + d * ri) if ri > 0 else (a + d * ri, a)
                v0 = max(0, int(round(von)))
                v1 = min(breite * FEIN, int(round(bis)))
                if v1 > v0:
                    fein[fy, v0:v1] = True
                    achse[fy // FEIN, v0 // FEIN:(v1 - 1) // FEIN + 1] = 2
    _nordlinie_durchziehen(fein, achse, nordlinie, nordenden)
    return fein, achse


# In welcher Teilfeldzeile die Nordkante liegt. In den 54 Karten sind die
# haeufigsten N-Kacheln 157, 158, 161, 160, 95, 162, 96, 159 (je 500 bis 700
# Vorkommen in der Mitte einer Kante): alle mit Fels im zweiten Abschnitt der
# Ostseite, also in der zweiten Zeile, und nur EIN Abschnitt dick. Eine
# Linie in Zeile 1 und 2 passte nur auf Kachel 211 -- die Kante bestand dann
# durchgehend aus derselben Kachel (Originale: 1,4 % gleiche Nachbarn).
NORD_ZEILE = 1


def _nordlinie_durchziehen(fein, achse, nordlinie, enden=None):
    """Die Nordkante: ein Teilfeld dick, in Zeile `NORD_ZEILE` jeder Zelle.

    Je Teilfeldspalte wird die Linie in die Zelle gelegt, in der ihre Mitte
    liegt, und dort auf Zeile `NORD_ZEILE`. Springt sie von Spalte zu Spalte
    in die Nachbarreihe, wird senkrecht verbunden -- das ist der schraege
    Uebergang.

    `enden` (Liste) bekommt je Ende eines Linienzugs (Zelle x, Zelle y,
    Seite). Dort laeuft die Linie bis an die Kachelkante: in den Karten hoert
    eine Nordkante an der Kante auf (Westende meist 94, 212, 160, 211, 157,
    159 -- mit Fels bis an die offene Seite), nicht mit einem Haken.
    """
    fh, fw = fein.shape
    spalten = {}
    for x in range(fw):
        ys = np.nonzero(nordlinie[:, x])[0]
        if not len(ys):
            continue
        fein[int(ys.min()):int(ys.max()) + 1, x] = False
        mitte = (int(ys.min()) + int(ys.max())) / 2.0
        zeile = int(mitte) // FEIN * FEIN + NORD_ZEILE
        spalten[x] = (min(fh - 1, zeile), min(fh - 1, zeile))
    vorher = None
    laeufe = []
    for x in sorted(spalten):
        y0, y1 = spalten[x]
        if vorher is not None and vorher[0] == x - 1:
            p0, p1 = vorher[1]
            if y0 > p1 + 1:
                y0 = p1 + 1
            elif y1 < p0 - 1:
                y1 = p0 - 1
            laeufe[-1].append(x)
        else:
            laeufe.append([x])
        fein[y0:y1 + 1, x] = True
        for yy in range(y0 // FEIN, y1 // FEIN + 1):
            achse[yy, x // FEIN] = 1
        vorher = (x, (y0, y1))
    for lauf in laeufe:
        for x, seite in ((lauf[0], "W"), (lauf[-1], "O")):
            zeile = spalten[x][0]
            zx = x // FEIN
            if seite == "W":
                fein[zeile, zx * FEIN:x + 1] = True
            else:
                fein[zeile, x:(zx + 1) * FEIN] = True
            if enden is not None:
                enden.append((zx, zeile // FEIN, seite, zeile))

def rand_dem_biom(fein: np.ndarray, runden: int = 3):
    """Stoesst Klippe an Biom, gehoert die Randlinie dem Biom.

    Faellt die Gelaendegrenze genau auf eine Kachelkante, ist die Randlinie
    Fels -- und die Kachel zeigt Fels an einer Naht, hinter der nur Biom
    liegt. Auf einer Schraege wandert die Grenze durch alle Zwischenlagen und
    trifft die Kachelkante regelmaessig. Die Regel rueckt die Grenze um ein
    Teilfeld nach innen; der Uebergang bekommt damit immer Platz innerhalb der
    Kachel.
    """
    fein = fein.copy()
    fh, fw = fein.shape
    h, w = fh // FEIN, fw // FEIN
    ber = Counter()
    for _r in range(runden):
        hat = _zellen(fein)
        geaendert = 0
        for y in range(h):
            for x in range(w):
                if not hat[y, x]:
                    continue
                for r in SEITEN:
                    dx, dy = VERSATZ[r]
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and hat[ny, nx]:
                        continue                  # dahinter Klippe: darf Fels
                    s = _randlinie(fein, x, y, r)
                    if s.any():
                        geaendert += int(s.sum())
                        s[:] = False
        ber["Randlinie geraeumt"] += geaendert
        if not geaendert:
            break
    return fein, ber


def naht_haelt(fein: np.ndarray):
    """Zwei benachbarte Klippenzellen muessen an ihrer Naht Fels teilen.

    Das Loch galt mir als unmoeglich -- zu Unrecht. Eine Naht hat zwei Seiten,
    und sie sind verschiedene Teilfelder: die letzte Spalte der linken Kachel
    und die erste der rechten. Beide koennen Biom sein, waehrend beide Zellen
    anderswo Fels tragen. Dann zeigen beide Kacheln an der Naht Boden, und die
    Wand ist dort durchtrennt. Gemessen: auf einer senkrechten Wand genau eine
    Stelle.

    Die Regel schliesst sie im Gelaende, nicht in der Kachelwahl -- an der
    breitesten Stelle des gemeinsamen Randes, damit die Wand dort zusammen-
    haengt, wo sie ohnehin am dicksten ist.
    """
    fein = fein.copy()
    fh, fw = fein.shape
    h, w = fh // FEIN, fw // FEIN
    hat = _zellen(fein)
    ber = Counter()
    for y in range(h):
        for x in range(w):
            if not hat[y, x]:
                continue
            for r, geg in (("O", "W"), ("S", "N")):
                dx, dy = VERSATZ[r]
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h) or not hat[ny, nx]:
                    continue
                a = _randlinie(fein, x, y, r)
                b = _randlinie(fein, nx, ny, geg)
                if a.any() or b.any():
                    continue
                # Wo ist die Wand beiderseits am dicksten? Dort schliessen.
                da = fein[y * FEIN:(y + 1) * FEIN,
                          x * FEIN:(x + 1) * FEIN].sum(axis=0 if r == "O"
                                                       else 1)
                db = fein[ny * FEIN:(ny + 1) * FEIN,
                          nx * FEIN:(nx + 1) * FEIN].sum(axis=0 if r == "O"
                                                         else 1)
                i = int(np.argmax(da + db))
                a[i] = True
                b[i] = True
                ber["Naht geschlossen"] += 1
    return fein, ber


def _randlinie(fein, x, y, r):
    """Die vier Teilfelder einer Kachelseite als beschreibbare Sicht."""
    if r == "N":
        return fein[y * FEIN, x * FEIN:(x + 1) * FEIN]
    if r == "S":
        return fein[(y + 1) * FEIN - 1, x * FEIN:(x + 1) * FEIN]
    if r == "W":
        return fein[y * FEIN:(y + 1) * FEIN, x * FEIN]
    return fein[y * FEIN:(y + 1) * FEIN, (x + 1) * FEIN - 1]


def _zellen(fein: np.ndarray) -> np.ndarray:
    """Welche Kacheln traegt das Gelaende ueberhaupt?"""
    fh, fw = fein.shape
    h, w = fh // FEIN, fw // FEIN
    return fein.reshape(h, FEIN, w, FEIN).any(axis=(1, 3))


def fuellregel(fein: np.ndarray, achse: np.ndarray, rng):
    """Bei Wandhoehe h sind h-2 bis h-1 Fuellkacheln erlaubt, hoechstens zwei.

    Ein massiver Wandkern gab 48 % Fuellkacheln gegen 16 % in den Originalen
    und Laeufe derselben Kachel ueber 51 Zellen. Ueberzaehlige Vollzellen
    bekommen darum eine Ecke Boden gekerbt -- und fragen damit nach den
    Kacheln, deren Schraege nur in einer Ecke sitzt. Von denen liegen 36 im
    Vorrat und blieben vorher fast ungenutzt.

    Der Deckel bei zwei ist gemessen: "h-2 bis h-1" weitergeschrieben erlaubte
    bei Hoehe 4 schon zwei bis drei und trieb den Fuellanteil auf 28,6 %.
    """
    fein = fein.copy()
    fh, fw = fein.shape
    h, w = fh // FEIN, fw // FEIN
    hat = _zellen(fein)
    ber = Counter()
    for quer, laengs, waagerecht in ((w, h, False), (h, w, True)):
        for a in range(quer):
            lauf = []
            for b in range(laengs + 1):
                x, y = (b, a) if waagerecht else (a, b)
                drin = (b < laengs and hat[y, x]
                        and achse[y, x] == (2 if waagerecht else 1))
                if drin:
                    lauf.append((x, y))
                    continue
                if lauf:
                    ber.update(_lauf_kerben(fein, lauf, rng))
                lauf = []
    return fein, ber


def _lauf_kerben(fein, lauf, rng):
    """Einen Wandquerschnitt auf die erlaubte Zahl Fuellkacheln bringen."""
    ber = Counter()
    n = len(lauf)
    voll = [(x, y) for x, y in lauf
            if fein[y * FEIN:(y + 1) * FEIN, x * FEIN:(x + 1) * FEIN].all()]
    unten = min(max(0, n - 2), 1)
    oben = min(max(0, n - 1), 2)
    ziel = int(rng.integers(unten, oben + 1))
    if len(voll) <= ziel:
        return ber
    for x, y in voll[:len(voll) - ziel]:
        links = bool(rng.integers(0, 2))
        gross = bool(rng.integers(0, 2))
        fx = x * FEIN + (0 if links else FEIN - 1)
        fy = y * FEIN
        fein[fy, fx] = False
        if gross:
            fein[fy + 1, fx] = False
            fein[fy, fx + (1 if links else -1)] = False
        ber["Ecke gekerbt"] += 1
    return ber


# --------------------------------------------------------------- Setzen


def verlangt(fein: np.ndarray, x: int, y: int) -> dict:
    """Was verlangt das Gelaende an den Raendern dieser Kachel?"""
    a = fein[y * FEIN:(y + 1) * FEIN, x * FEIN:(x + 1) * FEIN]
    return {"N": [FELS if v else BIOM for v in a[0, :]],
            "S": [FELS if v else BIOM for v in a[FEIN - 1, :]],
            "W": [FELS if v else BIOM for v in a[:, 0]],
            "O": [FELS if v else BIOM for v in a[:, FEIN - 1]]}


def erfuellt(seiten: dict, soll: dict) -> bool:
    for r in SEITEN:
        for a, b in zip(seiten[r], soll[r]):
            if a != EGAL and a != b:
                return False
    return True


def angleichen(fein: np.ndarray, vor: dict, runden: int = 6):
    """Das Gelaende an das anpassen, was der Kachelsatz aussprechen kann.

    Wo keine Kachel den verlangten Rand zeigt, wird nicht die Regel gelockert,
    sondern das Gelaende berichtigt: die Kachel mit den wenigsten Abweichungen
    wird genommen und ihr tatsaechlicher Rand zurueckgeschrieben. Der Nachbar
    liest danach denselben, berichtigten Rand.
    """
    fein = fein.copy()
    fh, fw = fein.shape
    h, w = fh // FEIN, fw // FEIN
    ber = Counter()
    for _r in range(runden):
        hat = _zellen(fein)
        geaendert = 0
        for y in range(h):
            for x in range(w):
                a = fein[y * FEIN:(y + 1) * FEIN, x * FEIN:(x + 1) * FEIN]
                if not a.any():
                    continue
                soll = verlangt(fein, x, y)
                if any(erfuellt(s, soll) for s, _fa in vor.values()):
                    continue
                # Welche Seiten stossen ans Biom? Dort darf die Berichtigung
                # keinen Fels hinschreiben -- sonst holt sie sich genau den
                # harten Uebergang zurueck, den die Randregel eben geraeumt
                # hat. Gemessen: auf einer 2:1-Schraege blieb sonst eine
                # Stelle stehen.
                offen = set()
                for r in SEITEN:
                    dx, dy = VERSATZ[r]
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h) or not hat[ny, nx]:
                        offen.add(r)
                anteil = float(a.mean())
                best = None
                for t, (s, fa) in vor.items():
                    hart = sum(1 for r in offen for u in s[r] if u == FELS)
                    fehl = sum(1 for r in SEITEN
                               for u, v in zip(s[r], soll[r])
                               if u != EGAL and u != v)
                    schl = (hart, fehl, abs(fa - anteil), t)
                    if best is None or schl < best[0]:
                        best = (schl, s)
                if best is None:
                    continue
                for r in SEITEN:
                    linie = _randlinie(fein, x, y, r)
                    for i, u in enumerate(best[1][r]):
                        if u == EGAL:
                            continue
                        linie[i] = (u == FELS) and r not in offen
                geaendert += 1
                ber["berichtigt"] += 1
        if not geaendert:
            break
    return fein, ber


def setzen(grid: np.ndarray, fein: np.ndarray, vor: dict,
           naht_runden: int = NAHT_RUNDEN,
           naht_spielraum: float = NAHT_SPIELRAUM):
    """Gelaende -> Kacheln im Gitter. Ein Nachschlagen je Kachel.

    Erst die harte Bedingung: nur Kacheln, die den verlangten Rand GENAU
    zeigen, kommen in Frage. Daran wird nicht geruettelt -- sie haelt hart und
    Loch bei null. Unter diesen entscheidet die Naht, und bei praktisch
    gleicher Naht die Abwechslung.
    """
    _K, PX = _modelle()
    h, w = grid.shape
    maske = np.zeros(grid.shape, dtype=bool)
    ber = Counter()
    auswahl = {}
    for y in range(h):
        for x in range(w):
            a = fein[y * FEIN:(y + 1) * FEIN, x * FEIN:(x + 1) * FEIN]
            if not a.any():
                continue
            soll = verlangt(fein, x, y)
            anteil = float(a.mean())
            passend = sorted((abs(fa - anteil), t)
                             for t, (s, fa) in vor.items()
                             if erfuellt(s, soll))
            if not passend:
                ber["kein Fall"] += 1
                continue
            grid[y, x] = passend[0][1]
            maske[y, x] = True
            auswahl[(x, y)] = [t for _d, t in passend]
            ber["gesetzt"] += 1

    def naht_hier(t, x, y):
        s = n = 0.0
        for r in SEITEN:
            dx, dy = VERSATZ[r]
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or not maske[ny, nx]:
                continue
            d = PX.naht(t, int(grid[ny, nx]), r)
            if d is not None:
                s += d
                n += 1
        return s / n if n else None

    for _r in range(naht_runden):
        geaendert = 0
        for (x, y), kand in sorted(auswahl.items()):
            bewertet = sorted((d, t) for d, t in
                              ((naht_hier(t, x, y), t) for t in kand)
                              if d is not None)
            if not bewertet:
                continue
            wahl = bewertet[0][1]
            nachbarn = set()
            for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and maske[ny, nx]:
                    nachbarn.add(int(grid[ny, nx]))
            grenze = bewertet[0][0] + naht_spielraum
            for d, t in bewertet:
                if d > grenze:
                    break
                if t not in nachbarn:
                    wahl = t
                    break
            if wahl != grid[y, x]:
                grid[y, x] = wahl
                geaendert += 1
        if not geaendert:
            break
    return maske, ber


# Ab dieser Helligkeit (Mittel der drei Kanaele) gilt ein Pixel als Boden.
# Gemessen gegen die Handzuordnung der Raender: 50 -> 72 %, 60 -> 83 %,
# 70 -> 90 %, 80 -> 93 % Uebereinstimmung.
FELS_HELLIGKEIT = 80


def innenbilder() -> dict:
    """Je Klippenkachel ihr Inneres als 4x4 Fels/Biom, aus den Pixeln.

    Die Handzuordnung beschreibt nur die RAENDER. Eine Kachel, deren Rand
    passt, kann innen ganz anders aussehen -- ein waagerechtes Felsband statt
    eines schraegen. Genau das gab auf Schraegen die Treppe: jede Kachel war
    am Rand richtig, innen aber flach.
    """
    if "innen" in _zwischen:
        return _zwischen["innen"]
    aus = {}
    try:
        from cliff_pixels import MODELL_PFAD as _pfad
    except ImportError:                                  # noqa: BLE001
        _pfad = None
    try:
        import os
        pfad = _pfad or os.path.join(os.path.dirname(__file__),
                                     "cliff_pixels_model.npz")
        d = np.load(pfad)
        k = 32 // FEIN
        for i, t in enumerate(d["kacheln"]):
            hell = d["bilder"][i].astype(float).mean(axis=2)
            aus[int(t)] = ((hell < FELS_HELLIGKEIT)
                           .reshape(FEIN, k, FEIN, k).mean(axis=(1, 3)) > 0.5)
    except Exception:                                    # noqa: BLE001
        aus = {}
    # Die Helligkeitsschwelle ist an mud gemessen. Bei san sind Sand und
    # Fels fast gleich hell (Mediane 76 gegen 54, beide unter 80) -- dort
    # waere jede Kachel "voll Fels". Fuer alles ausser mud trennen darum die
    # Farbzentren aus `cliff_kanten_auto`.
    try:
        import cliff_kanten_auto as _ka
        _b, fam = _ka._bilder()
        k = 32 // FEIN
        for t in list(aus):
            if fam.get(t, "mud") != "mud":
                aus[t] = (_ka.felsmaske(t).reshape(FEIN, k, FEIN, k)
                          .mean(axis=(1, 3)) > 0.5)
    except Exception:                                    # noqa: BLE001
        pass
    _zwischen["innen"] = aus
    return aus


# Ab so vielen Fels-Teilfeldern (von 4) am Rand gilt eine Seite laut Bild als
# Fels -- und darf dann nicht an offenen Boden grenzen.
OFFEN_FELS_MAX = 2


def _innenrand(ib: np.ndarray, r: str) -> np.ndarray:
    if r == "N":
        return ib[0, :]
    if r == "S":
        return ib[-1, :]
    if r == "W":
        return ib[:, 0]
    return ib[:, -1]


# Kachelseiten, die Boden zeigen, obwohl dahinter Klippe steht ("Randkachel
# mitten in der Wand", Pruefung aus dem Landschafts-Stand vom August).
# 0 = nicht beachten, 1 = zusammen mit Bild-Fels zum Boden als erste
# Vorliebe, 2 = direkt nach der Randabweichung. Gemessen ueber 39 Waende je
# Familie (Originale: mud 1,22 %, san 0,95 %):
#
#          mud innen  unbelegt    san innen  unbelegt
#   0      1,54 %     25,9 %      1,63 %     46,6 %
#   1      0,30 %     25,3 %      0,20 %     44,9 %   <- gewaehlt
#   2      0,48 %     25,1 %      0,90 %     45,1 %
#
# Unpassende Paare, Loch und hart bleiben in allen drei Faellen bei 0.
INNENKANTE = 1


# Der Loeser darf so lange suchen, dann faellt er auf `setzen` zurueck.
LOESER_ZEIT = 3.0


def loesen(grid: np.ndarray, fein: np.ndarray, vor: dict,
           zeit: float = LOESER_ZEIT, abweichung: int = 0,
           gelaende_zuerst: bool = True, loch_erlaubt: bool = False,
           nur_belegt: bool = False, innen_gewicht: bool = True,
           wdh_stufe: int = 1, offen_ok: dict | None = None):
    """Gelaende -> Kacheln, aber GESUCHT statt gesetzt.

    `setzen` waehlt je Zelle eine Kachel, die das Gelaende erfuellt, und
    schaut erst danach auf die Naht. Ob die beiden Nachbarn ueberhaupt
    zueinander passen, ist dort keine Bedingung -- jede Kachel liest ihren
    EIGENEN Rand des Gelaendes, und links und rechts einer Naht sind das
    verschiedene Teilfelder. Daher die 0,9 bis 5,1 % regelwidrigen Paare.

    Hier sind beide Auskuenfte hart:

        Gelaende    jede Zelle nur aus den Kacheln, die ihren Rand zeigen
                    (wie `setzen` -- hart und Loch bleiben ausgeschlossen)
        Paar        jedes gerade Nachbarpaar ist in den 54 Karten belegt
                    ODER nach der Kantenzuordnung erlaubt

    Gesucht wird mit Rueckverfolgung: immer die Zelle mit den wenigsten
    Moeglichkeiten zuerst, und nach jeder Wahl werden die Nachbarn
    nachgefiltert -- laeuft einer leer, wird sofort zurueckgenommen.

    Reihenfolge der Kandidaten, wie im Blockloeser gemessen: erst die an allen
    gesetzten Nachbarn BELEGTEN (belegt ist mehr wert als erlaubt), dann keine
    Wiederholung des Nachbarn, dann die Naht.

    -> (maske, Bericht) oder None, wenn innerhalb von `zeit` nichts gefunden
    wurde. Dann ist `grid` unveraendert.
    """
    import sys
    import time

    from cliff_tiles import modell as _tm

    ke, PX = _modelle()
    tt = _tm()
    h, w = grid.shape

    hat = _zellen(fein)
    zellen = []
    dom: dict = {}
    fehl_von: dict = {}
    innen_von: dict = {}
    ofs_von: dict = {}
    ik_von: dict = {}
    innen = innenbilder()
    for y in range(h):
        for x in range(w):
            a = fein[y * FEIN:(y + 1) * FEIN, x * FEIN:(x + 1) * FEIN]
            if not hat[y, x]:
                continue
            soll = verlangt(fein, x, y)
            anteil = float(a.mean())
            offen = set()
            for r in SEITEN:
                dx, dy = VERSATZ[r]
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h) or not hat[ny, nx]:
                    offen.add(r)
            if offen_ok and (x, y) in offen_ok:
                # Ende einer Nordkante: die Linie darf an die offene Seite.
                offen.discard(offen_ok[(x, y)])
            kand = []
            innenkante = {}
            blk = a
            for t, (s, fa) in vor.items():
                # Hart: kein Fels zum offenen Boden hin.
                if any(u == FELS for r in offen for u in s[r]):
                    continue
                # Auch nicht, wo die Handzuordnung `egal` sagt, das Bild aber
                # Fels zeigt: am Ende einer waagerechten Wand stand so eine
                # Kachel mit Fels unten rechts, und darunter war nichts --
                # im Bild fehlte dort sichtbar eine Kachel.
                #
                # Als Verbot gemessen zu streng: 17 von 39 Pruefwaenden wurden
                # unloesbar. Darum als erste Vorliebe: wo es geht, nie.
                ib = innen.get(t)
                ofs = 0 if ib is None else sum(
                    1 for r in offen
                    if int(_innenrand(ib, r).sum()) >= OFFEN_FELS_MAX)
                # Boden zu einer Nachbarzelle, die selbst Klippe ist: eine
                # Ober- oder Unterkante mitten in der Wand.
                # Nur Seiten ganz ohne Fels: eine Nordkante zeigt zur
                # Nachbarzelle drei Abschnitte Boden und einen Fels -- das ist
                # ihre Linie und kein Mangel. Mit ">= 3 Boden" blieb fuer sie
                # nur Kachel 211, die Kante bestand aus einer einzigen Kachel.
                bin_ = sum(1 for r in SEITEN if r not in offen
                           and sum(1 for u in s[r] if u == BIOM) >= 3
                           and not any(u == FELS for u in s[r]))
                fehl = sum(1 for r in SEITEN for u, v in zip(s[r], soll[r])
                           if u != EGAL and u != v)
                if fehl > abweichung:
                    continue
                ib = innen.get(t)
                inn = int((ib != blk).sum()) if ib is not None else FEIN * FEIN
                vorn = ofs + (bin_ if INNENKANTE == 1 else 0)
                kand.append((vorn, fehl, inn, abs(fa - anteil), t))
                innenkante[t] = bin_
            if not kand:
                return None
            kand.sort()
            zellen.append((x, y))
            dom[(x, y)] = [t for _o, _f, _i, _d, t in kand]
            fehl_von[(x, y)] = {t: f for _o, f, _i, _d, t in kand}
            innen_von[(x, y)] = {t: i for _o, _f, i, _d, t in kand}
            ofs_von[(x, y)] = {t: o for o, _f, _i, _d, t in kand}
            ik_von[(x, y)] = dict(innenkante)
    if not zellen:
        return None
    drin = set(zellen)

    nachbarn = {}
    for (x, y) in zellen:
        nb = []
        for r in SEITEN:
            dx, dy = VERSATZ[r]
            p = (x + dx, y + dy)
            if p in drin:
                nb.append((r, p))
        nachbarn[(x, y)] = nb

    _ok: dict = {}

    def ok(a, b, r):
        """Darf b in Richtung r neben a liegen? (belegt oder erlaubt)"""
        k = (a, b, r)
        v = _ok.get(k)
        if v is None:
            v = ((tt.passt(a, b, r) or (not nur_belegt and ke.passt(a, b, r)))
                 and (loch_erlaubt or not ke.loch(a, b, r)))
            _ok[k] = v
        return v

    belegt: dict = {}
    start = time.time()
    schritte = [0]

    def ordnen(kand, p):
        x, y = p
        gesetzt = [(r, belegt[q]) for r, q in nachbarn[p] if q in belegt]
        nb_kacheln = {t for _r, t in gesetzt}
        # Auch zwei und drei Zellen weiter: A-B-A-B und A-B-C-A-B-C sind
        # ebenso Wiederholung. Den Dreierrhythmus zeigte die Nordkante, nachdem
        # sie drei gleichwertige Kacheln hatte (158, 162, 159, 158, ...).
        weiter = set()
        for r in SEITEN:
            dx, dy = VERSATZ[r]
            for k in (2, 3):
                q = belegt.get((x + k * dx, y + k * dy))
                if q is not None:
                    weiter.add(q)

        fehl = fehl_von[p]

        def schluessel(i_t):
            i, t = i_t
            rang = 0 if all(tt.passt(t, b, r) for r, b in gesetzt) else 1
            gleich = (2 if t in nb_kacheln else 0) + (1 if t in weiter else 0)
            s = n = 0.0
            for r, b in gesetzt:
                d = PX.naht(t, b, r)
                if d is not None:
                    s += d
                    n += 1
            inn = innen_von[p][t] if innen_gewicht else 0
            if wdh_stufe == 2:
                stufen = (gleich, fehl[t], inn, rang)
            elif wdh_stufe == 1:
                stufen = (fehl[t], gleich, inn, rang)
            else:
                stufen = (fehl[t], inn, rang, gleich)
            if not gelaende_zuerst:
                stufen = (rang,) + stufen
            if INNENKANTE == 2:
                stufen = (stufen[0], ik_von[p][t]) + stufen[1:]
            stufen = (ofs_von[p][t],) + stufen
            # Der Rang im Gelaende (Felsanteil) bricht Gleichstand.
            return stufen + (s / n if n else 0.0, i)

        return [t for _i, t in sorted(enumerate(kand), key=schluessel)]

    def schritt():
        if time.time() - start > zeit:
            raise TimeoutError
        schritte[0] += 1
        beste = None
        for p in zellen:
            if p in belegt:
                continue
            k = dom[p]
            if beste is None or len(k) < len(dom[beste]):
                beste = p
                if len(k) <= 1:
                    break
        if beste is None:
            return True
        p = beste
        for t in ordnen(dom[p], p):
            belegt[p] = t
            # Vorausschau: die freien Nachbarn auf das einschraenken, was
            # neben t stehen darf. Laeuft einer leer, gleich weiter.
            alt = []
            tot = False
            for r, q in nachbarn[p]:
                if q in belegt:
                    continue
                neu = [u for u in dom[q] if ok(t, u, r)]
                alt.append((q, dom[q]))
                dom[q] = neu
                if not neu:
                    tot = True
                    break
            if not tot and schritt():
                return True
            for q, d in alt:
                dom[q] = d
            del belegt[p]
        return False

    alt_grenze = sys.getrecursionlimit()
    sys.setrecursionlimit(max(alt_grenze, len(zellen) + 500))
    try:
        gefunden = schritt()
    except TimeoutError:
        gefunden = False
    finally:
        sys.setrecursionlimit(alt_grenze)
    if not gefunden:
        return None
    maske = np.zeros(grid.shape, dtype=bool)
    for (x, y), t in belegt.items():
        grid[y, x] = t
        maske[y, x] = True
    ber = Counter(gesetzt=len(belegt), Suchschritte=schritte[0])
    return maske, ber


def naht_teilen(fein: np.ndarray) -> np.ndarray:
    """Beide Kacheln an einer Naht sollen dasselbe lesen.

    `verlangt` liest den Rand einer Kachel aus ihrem EIGENEN aeussersten
    Teilfeld. Links und rechts einer Naht sind das zwei verschiedene Spalten,
    und gemessen weichen sie an 23 bis 29 % der Naehte voneinander ab. Dann
    verlangt das Gelaende von zwei Nachbarn Raender, die nicht
    zusammenpassen -- und keine Wahl kann beides erfuellen. Der Loeser fand
    darum auf keinem der neun Testzuege eine Belegung.

    Hier wird an jeder Naht zwischen zwei Klippenzellen beidseits dasselbe
    eingetragen, und zwar Fels, wo eine der beiden Fels hat. Gemessen gegen
    "Boden, wo eine Boden hat": damit loeste der Loeser 0 von 9, mit Fels 6
    von 9 ohne jede weitere Hilfe. Die Wand haengt so eher zusammen, statt an
    der Naht zu reissen.
    """
    fein = fein.copy()
    fh, fw = fein.shape
    h, w = fh // FEIN, fw // FEIN
    hat = _zellen(fein)
    for y in range(h):
        for x in range(w):
            if not hat[y, x]:
                continue
            for r, geg in (("O", "W"), ("S", "N")):
                dx, dy = VERSATZ[r]
                nx, ny = x + dx, y + dy
                if not (nx < w and ny < h) or not hat[ny, nx]:
                    continue
                a = _randlinie(fein, x, y, r)
                b = _randlinie(fein, nx, ny, geg)
                v = a | b
                a[:] = v
                b[:] = v
    return fein


def gelaende_angleichen(fein: np.ndarray, vor: dict,
                        teilen: bool = False) -> np.ndarray:
    """Randregel, Naht und Berichtigung im Wechsel, bis nichts mehr aendert.

    Die Regeln muessen abwechselnd laufen. Die Berichtigung kann eine duenne
    Randzelle ganz leeren; danach steht die Nachbarzelle mit Fels an einer
    Naht, hinter der nun Biom liegt -- die Randregel hatte zu diesem Zeitpunkt
    noch Klippe gesehen. Ohne den Wechsel blieb auf einer 2:1-Schraege genau
    eine harte Stelle stehen.

    `teilen` nimmt `naht_teilen` dazu -- fuer den Loeser. Der gierige Setzer
    bekommt es nicht: dort brachte es harte Uebergaenge (Zickzack 2,
    senkrecht 3 bis 5), weil er an den Naehten nicht nachfragt.
    """
    for _r in range(8 if teilen else 4):
        vorher = fein
        fein, _b = rand_dem_biom(fein)
        fein, _b = naht_haelt(fein)
        if teilen:
            fein = naht_teilen(fein)
        fein, _b = angleichen(fein, vor)
        if np.array_equal(fein, vorher):
            break
    return fein


# Den Loeser benutzen; ohne Loesung faellt `klippe_aus_linie` auf `setzen`
# zurueck.
LOESER = True

# Die Stufen, in denen gesucht wird: (nur belegte Paare?, Abweichung vom
# Gelaende in Abschnitten, Zeit in Sekunden). Die erste, die eine Belegung
# findet, gilt. Gemessen auf 27 Waenden (neun Zuege, drei Saaten):
#
#   nur belegt, Abweichung 4        23 von 27, 0 % unbelegte Paare
#   belegt oder erlaubt, 0 bis 4    27 von 27, 15 % unbelegt
#   zum Vergleich `setzen`          38 % unbelegt, 0,9 bis 5,1 % regelwidrig
#
# Nur-belegt mit WENIGER Abweichung loest weniger (1: 12, 2: 16, 3: 20) und
# laeuft dabei oft in die Zeitgrenze; mit mehr (6) ebenfalls, weil die
# Domaenen zu gross werden. 4 ist der gemessene Sattel.
LOESER_STUFEN = (
    (True, 4, 1.5),
    (False, 0, 1.0),
    (False, 1, 1.0),
    (False, 2, 1.0),
    (False, 3, 1.0),
    (False, 4, 1.0),
    # Fuer die waagerechte Nordkante: dort greift erst 4 bis 5 (gemessen an
    # drei Saaten), sonst faellt sie auf `setzen` zurueck -- 54 % unpassende
    # Paare.
    (False, 5, 1.0),
    (False, 6, 1.0),
)


def loesen_stufenweise(grid: np.ndarray, fein: np.ndarray, vor: dict,
                       stufen=LOESER_STUFEN, offen_ok: dict | None = None):
    """`loesen` ueber die Stufen in `LOESER_STUFEN` -> (maske, Bericht) | None.

    Der Bericht nennt die Stufe, die gegriffen hat.
    """
    for i, (nur_belegt, abw, zeit) in enumerate(stufen):
        r = loesen(grid, fein, vor, zeit=zeit, abweichung=abw,
                   nur_belegt=nur_belegt, offen_ok=offen_ok)
        if r is not None:
            r[1]["Stufe"] = i
            return r
    return None


def klippe_aus_linie(grid: np.ndarray, punkte, hoch_seite: str, tm,
                     rng, familie: str = "mud",
                     hoehe_min: float = HOEHE_MIN,
                     hoehe_max: float = HOEHE_MAX):
    """Eine gezeichnete Kante algorithmisch belegen -> (Maske, Zelltypfeld).

    Gleiche Auskunft wie `mapgen.klippe_aus_linie`, damit der Editor beide
    Wege ohne Umbau aufrufen kann. Der Zelltyp wird nicht selbst gesetzt: -1
    heisst "aus der Kachel ableiten", und genau das tut der Aufrufer bereits.
    """
    h, w = grid.shape
    zellen = np.full(grid.shape, -1, dtype=np.int16)
    vor = vorrat(tm, familie)
    if len(punkte) < 2 or len(vor) < MINDEST_KACHELN:
        return np.zeros(grid.shape, dtype=bool), zellen
    nordenden: list = []
    fein, achse = band_aus_linie(punkte, hoch_seite, w, h, rng,
                                 hoehe_min, hoehe_max, nordenden=nordenden)
    if not fein.any():
        return np.zeros(grid.shape, dtype=bool), zellen
    fein, _b = fuellregel(fein, achse, rng)
    maske = None
    if LOESER:
        gel = gelaende_angleichen(fein, vor, True)
        # Die Enden der Nordkante wieder bis an die Kachelkante ziehen --
        # `rand_dem_biom` hat sie dort als Fels zum Boden entfernt.
        offen_ok = {}
        for zx, zy, seite, zeile in nordenden:
            blk = gel[zy * FEIN:(zy + 1) * FEIN, zx * FEIN:(zx + 1) * FEIN]
            if not blk.any():
                continue
            spalten = np.nonzero(gel[zeile, zx * FEIN:(zx + 1) * FEIN])[0]
            if not len(spalten):
                continue
            if seite == "W":
                gel[zeile, zx * FEIN:zx * FEIN + int(spalten.min()) + 1] = True
            else:
                gel[zeile, zx * FEIN + int(spalten.max()):(zx + 1) * FEIN] = True
            offen_ok[(zx, zy)] = seite
        r = loesen_stufenweise(grid, gel, vor, offen_ok=offen_ok)
        if r is not None:
            maske = r[0]
    if maske is None:
        maske, _ber = setzen(grid, gelaende_angleichen(fein, vor), vor)
    for y, x in zip(*np.nonzero(maske)):
        zt = celltypes.default_cell_type(int(grid[y, x]))
        if zt is not None:
            zellen[y, x] = zt
    return maske, zellen
