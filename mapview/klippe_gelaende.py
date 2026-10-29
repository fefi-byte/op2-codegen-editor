"""Das Gelaende einer gezeichneten Klippenlinie: Felsband im Viertelraster, Schraegen, Nordkanten, Wandhoehe.

Aus `klippe_algo.py` herausgeloest; `klippe_algo` reicht alle Namen weiter.
"""
from __future__ import annotations
from collections import Counter
import numpy as np
import celltypes
from cliff_kanten import BIOM, EGAL, FELS, modell as kantenmodell
from cliff_pixels import modell as pixelmodell
from cliff_tiles import VERSATZ
FEIN = 4                       # Teilfelder je Kachel und Richtung


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


# Gerade gezeichnete Abschnitte (waagerecht oder senkrecht) sollen auch gerade
# aussehen. Mit voller Unruhe und voller Dickenstreuung sprang die Unterkante
# einer waagerechten Wand von Zelle zu Zelle um eine Reihe -- im Editor sah
# die Linie zwischen zwei Punkten auf derselben Hoehe wellig aus. Auf geraden
# Stuecken wird die Unruhe deshalb mit `GERADE_UNRUHE` und die Streuung der
# Dicke um ihre Mitte mit `GERADE_DICKE` gestaucht; an Knicks zu einem
# schraegen Stueck wird ueber `GERADE_UEBERGANG` Kacheln uebergeblendet, damit
# dort kein Absatz entsteht.
#
# Gemessen ueber 10 Saaten (Randkacheln mitten in der Wand, Mittel/Max):
#   Unruhe/Dicke  1,0/1,0 (vorher)  san senkrecht 2,4 / 4,3 %   mud 0,8 / 5,2 %
#                 0/0,3             san senkrecht 1,2 / 3,9 %   mud 0,2 / 0,7 %
#                 0/0,15            san senkrecht 0,6 / 0,7 %   mud 0,0 / 0,0 %
# Unpassend, Loch, hart bleiben 0; gleiche Nachbarn mud 1,5 -> 1,3 %.
GERADE_UNRUHE = 0.0


GERADE_DICKE = 0.15


GERADE_UEBERGANG = 2.0


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


# Auf einem kurzen Zug fraessen zwei Enden von je 3,5 Kacheln fast die ganze
# Wand auf (9 Zeilen steil: 7 davon verjuengt). Jedes Ende hoechstens dieser
# Anteil der Zuglaenge.
ENDE_ANTEIL_MAX = 0.25


# Seitenwaende (Hochland im Osten oder Westen, `art == "h"`). In den
# Originalen ein durchgehendes dunkles Band mit gleichmaessig verteilten
# Ein-Zellen-Versaetzen (cm02 212,20; 228,160). Mit der vollen Unruhe der
# Suedwand wurde daraus ein fleckiger Streifen; die Unruhe ist daher
# gedaempft. Schmaler machen (0,7) wurde probiert und verworfen: unter etwa
# einer Kachel Fels zerfiel das Band in einzelne Flecken und Vollfelsbloecke.
SEITE_DICKE = 1.0


SEITE_UNRUHE = 0.4


ENDE_REST = 0.0


def _glatt(n: int, rng, staerke: float, laenge: int) -> np.ndarray:
    """Langsamer Zufallsverlauf: Rauschen, zweimal ueber `laenge` gemittelt.

    Ohne die Glaettung zackt die Kante von Teilfeld zu Teilfeld -- das waere
    keine Klippe mehr, sondern Rauschen.
    """
    laenge = max(1, laenge)
    # Mindestens acht Glaettungslaengen rechnen und auf DIESE Streuung
    # normieren. Auf einer kurzen Wand (n kleiner als `laenge`) ist der
    # Verlauf fast konstant; normiert man ihn auf seine eigene Streuung, wird
    # aus dem kleinen Rest ein grosser fester Versatz -- die Wand lag dann
    # bis zu vier Teilfelder neben der gezeichneten Linie.
    # Normalise over at least eight smoothing lengths: on a short wall the
    # curve is nearly constant, and normalising it by its own spread turned it
    # into a large constant offset away from the drawn line.
    m = max(n, 8 * laenge)
    r = rng.normal(0.0, 1.0, m + laenge * 2)
    k = np.ones(laenge) / laenge
    g = np.convolve(r, k, mode="same")
    g = np.convolve(g, k, mode="same")[laenge:laenge + m]
    s = float(g.std())
    g = g[:n]
    return g / s * staerke if s > 1e-9 else g


def _wand_achse(x0, y0, x1, y1, hoch_seite: str):
    """In welche Richtung waechst die Wand von der Kante weg?

    Die Kante ist gezeichnet, das Hochland liegt auf der genannten Seite --
    die Wand faellt zur anderen.

    Die beiden Paare bedeuten NICHT dasselbe, und das ist die Falle: "oben"
    und "unten" sind bildschirmfest, "links" und "rechts" beziehen sich auf
    die ZEICHENRICHTUNG. Nach unten gezeichnet liegt links im Osten, nach oben
    gezeichnet im Westen. Wer das gleichsetzt, baut die Wand auf der falschen
    Seite -- gemessen gegen den frueheren Blockweg: der legte bei "links" und nach unten
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


# Steile Seitenwaende genauso, nur gekippt: senkrechte Laeufe, dazwischen
# Versaetze. In den Originalen sind es fast immer EIN, selten zwei Zellen
# (cm02 212,20: 0 0 0 1 0 0 1 0 0 1 ...). Gleichmaessig schraeg gelegt riss
# das Band an der Stelle, wo es eine Zellgrenze kreuzte, quer durch.
STEIL_STUECK = (1.0, 1.0)


STEIL_GLEICHMASS = 4.0            # Dirichlet: gross = gleich lange Laeufe


def _schraege_profil(lx: float, ly: float, rng, stueck=None,
                     gleichmass: float = 2.0):
    """Flache Schraege -> (Stuetzstellen x, y) aus Plateaus und 45-Grad.

    `lx` ist die waagerechte Laenge, `ly` (<= lx) der Hoehenunterschied, beide
    in Kacheln und positiv. Die Gesamtneigung bleibt genau erhalten.
    """
    if ly < 0.75 or ly >= 0.9 * lx:
        return np.array([0.0, lx]), np.array([0.0, ly])
    k = max(1, int(round(ly / rng.uniform(*(stueck or SCHRAEGE_STUECK)))))
    stueck = ly / k
    flach = (lx - ly) * rng.dirichlet(np.full(k + 1, gleichmass))
    xs, ys = [0.0], [0.0]
    for i in range(k + 1):
        xs.append(xs[-1] + flach[i])
        ys.append(ys[-1])
        if i < k:
            xs.append(xs[-1] + stueck)
            ys.append(ys[-1] + stueck)
    xs[-1] = lx
    return np.array(xs), np.array(ys)


# Steile Nordkanten (Hochland im Sueden, Neigung ab `NORD_TREPPE_AB`). Als
# duenne Schraeglinie zerfielen sie in Striche: fuer eine duenne Linie quer
# durch die Kachel hat mud kaum Kacheln. Die Originale (84 Fundstellen mit
# Neigung 0,6-1,4) bauen eine Treppe: waagerechte Laeufe, und jeder Absatz
# ist ein Stueck echte Seitenwand (Kacheln 88, 89, 94, 95, 97, 98, 210 --
# die wir vorher kaum setzten). Also: Laeufe mit senkrechten Absaetzen von 1
# bis 2 Zellen, und an jedem Absatz eine kleine Wand von
# `NORD_ABSATZ_DICKE` Kacheln auf der Seite des tieferen Laufs. Bei 45 Grad
# wachsen die Absaetze zu einer durchgehenden rauen Wand zusammen.
# Sechs steile Nordzuege x 3 Saaten, mud: unpassend 6,0 -> 0 %, unbelegt
# 62 -> 32 %, 0 hart, 0 Loch.
NORD_TREPPE = True


NORD_STUFE = (1.0, 2.0)        # Hoehe eines Absatzes in Zellen


NORD_GLEICHMASS = 20.0


NORD_HAKEN = 0.0               # Breite eines Absatzes in Kacheln


NORD_ABSATZ_DICKE = 1.5        # Felsdicke der kleinen Seitenwand am Absatz


NORD_TREPPE_AB = 0.6           # erst ab dieser Neigung (Zeilen je Spalte)


def _nord_treppe(lx: float, ly: float, rng):
    """Schraege Nordkante -> (x, y) Stuetzstellen: Laeufe und Haken."""
    stufen = max(1, int(round(ly)))
    hoehen = []
    rest = stufen
    while rest > 0:
        h = max(1, int(min(rest, round(rng.uniform(*NORD_STUFE)))))
        hoehen.append(h)
        rest -= h
    k = len(hoehen)
    haken = [min(NORD_HAKEN * h, 0.9 * lx / k) for h in hoehen]
    laeufe = max(0.0, lx - sum(haken)) * rng.dirichlet(
        np.full(k + 1, NORD_GLEICHMASS))
    xs, ys = [0.0], [0.0]
    y = 0.0
    for i in range(k + 1):
        xs.append(xs[-1] + laeufe[i])
        ys.append(y)
        if i < k:
            y += hoehen[i] * ly / stufen
            xs.append(xs[-1] + max(1e-6, haken[i]))
            ys.append(y)
    xs[-1] = max(xs[-1], lx)
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
    # Je Schritt: liegt er auf einem geraden Abschnitt? 1 = schraeg, 0 = gerade,
    # dazwischen weich uebergeblendet.
    schraeg = np.ones(schritte)
    s = 0
    for i in range(len(punkte) - 1):
        x0, y0 = punkte[i]
        x1, y1 = punkte[i + 1]
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * FEIN) + 1
        if x0 == x1 or y0 == y1:
            schraeg[s:s + n] = 0.0
        s += n
    if not schraeg.all() and schraeg.any():
        b = max(1, int(GERADE_UEBERGANG * FEIN))
        schraeg = np.convolve(np.pad(schraeg, b, mode="edge"),
                              np.ones(2 * b + 1) / (2 * b + 1),
                              mode="same")[b:b + schritte]
    wandern = wandern * (GERADE_UNRUHE + (1 - GERADE_UNRUHE) * schraeg)
    anteil = 0.5 + (anteil - 0.5) * (GERADE_DICKE
                                     + (1 - GERADE_DICKE) * schraeg)
    dicke = hoehe_min + (hoehe_max - hoehe_min) * anteil
    dicke_nord = NORD_MIN + (NORD_MAX - NORD_MIN) * anteil

    nordlinie = np.zeros_like(fein)
    absaetze = []           # (x, y_a, y_b, Richtung zum tieferen Lauf)
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
        elif (NORD_TREPPE and art == "v" and ri < 0
                and abs(y1 - y0) >= NORD_TREPPE_AB * abs(x1 - x0)):
            profil = _nord_treppe(abs(x1 - x0), abs(y1 - y0), rng)
            sx = 1 if x1 > x0 else -1
            sy = 1 if y1 > y0 else -1
            pxs, pys = profil
            for j in range(len(pxs) - 1):
                if pys[j + 1] != pys[j]:
                    ya = y0 + sy * pys[j]
                    yb = y0 + sy * pys[j + 1]
                    absaetze.append((x0 + sx * pxs[j], ya, yb,
                                     sx if yb > ya else -sx))
        steil = None
        if SCHRAEGE_ZERLEGEN and art == "h" and abs(x1 - x0) > 0:
            steil = _schraege_profil(abs(y1 - y0), abs(x1 - x0), rng,
                                     STEIL_STUECK, STEIL_GLEICHMASS)
        for k in range(n):
            u = k / max(1, n - 1)
            if steil is None:
                px = (x0 + (x1 - x0) * u + 0.5) * FEIN
            else:
                hx = float(np.interp(abs(y1 - y0) * u, *steil))
                px = (x0 + np.sign(x1 - x0) * hx + 0.5) * FEIN
            if profil is None:
                py = (y0 + (y1 - y0) * u + 0.5) * FEIN
            else:
                hy = float(np.interp(abs(x1 - x0) * u, *profil))
                py = (y0 + np.sign(y1 - y0) * hy + 0.5) * FEIN
            w = wandern[min(s, schritte - 1)] * FEIN
            d = dicke[min(s, schritte - 1)] * FEIN
            # Abstand zum naechsten Ende des ganzen Zuges, in Kacheln.
            rand_ab = min(s, schritte - 1 - s) / FEIN
            ende_l = min(ENDE_LAENGE, ENDE_ANTEIL_MAX * schritte / FEIN)
            ende = 1.0
            if enden and rand_ab < ende_l:
                ende = ENDE_REST + (1 - ENDE_REST) * (rand_ab / ende_l) ** 0.5
            d *= ende
            if art == "h":
                d *= SEITE_DICKE
                w *= SEITE_UNRUHE
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
    # Absaetze der Nordtreppe als kleine Seitenwand: in den Originalen ist der
    # Absatz keine duenne Linie, sondern ein Stueck echte Wand (Kacheln 88,
    # 89, 94, 95, 97, 98, 210) -- der Fels liegt auf der Seite des tieferen
    # Laufs. Eine duenne senkrechte Linie zerfiel in Striche.
    for xs_, ya, yb, ri_ in absaetze:
        r0 = int(min(ya, yb)) * FEIN + NORD_ZEILE
        r1 = int(max(ya, yb)) * FEIN + NORD_ZEILE + 1
        fx = (xs_ + 0.5) * FEIN
        d = NORD_ABSATZ_DICKE * FEIN
        c0, c1 = (fx, fx + d) if ri_ > 0 else (fx - d, fx)
        c0 = max(0, int(round(c0)))
        c1 = min(breite * FEIN, int(round(c1)))
        r0, r1 = max(0, r0), min(hoehe * FEIN, r1)
        if c1 > c0 and r1 > r0:
            fein[r0:r1, c0:c1] = True
            achse[r0 // FEIN:(r1 - 1) // FEIN + 1,
                  c0 // FEIN:(c1 - 1) // FEIN + 1] = 2
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


# Wandhoehe aus der Karte. Gemessen wird wie in den Originalkarten: je Spalte
# die Laeufe von H/L-Zellen (Zelltyp 9/10), und nur dort, wo links und rechts
# ebenfalls Klippe steht -- also quer durch eine waagerecht laufende Wand, nicht
# entlang einer senkrechten. In den 54 Karten liegt der Median ueberall bei 3,
# das Mittel je Karte zwischen 2,5 und 3,8 (mp2_05: 5,1).
#
# Umrechnung Zellen -> Felsdicke, gemessen am Loeser (mud und san, waagerecht,
# senkrecht und schraeg, je 3 Saaten): Dicke d +- 0,5 ergibt d + 1 Zellen
# (2,0 -> 2,96; 3,0 -> 3,96; 4,0 -> 4,99; 5,0 -> 6,00), bei 0 hart und 0 Loch
# auf jeder Hoehe. Also Dicke = Zellen - 1.
WAND_ZELLEN = 3.0              # ohne Messung: wie die Originale


# Untergrenze 3, nicht 2: vor Ort gemessen kommt oft 2,0 bis 2,6 heraus (cm02
# an einzelnen Stellen 2,0, cm03 bis 2,1). Das ergab Fels unter 1,5 Kacheln,
# und so duenn zerfaellt das Band in einzelne Flecken (im Editor gesehen,
# siehe auch die Tabelle bei `HOEHE_MIN`: 1,0-2,0 reisst zum Faden). Die
# Messung darf die Wand also hoeher machen, nie duenner als bisher.
WAND_ZELLEN_MIN = 3.0


WAND_ZELLEN_MAX = 6.0


WAND_MESS_MIN = 12             # so viele Laeufe, bevor eine Messung zaehlt


WAND_UMKREIS = 24              # Zellen um die Linie fuer die Messung vor Ort


def wandhoehe_messen(zelltypen: np.ndarray) -> tuple[float, int]:
    """Mittlere Wandhoehe in Zellen -> (Mittel, Anzahl Laeufe).

    `zelltypen` ist das Zelltypfeld (h, w) der Karte oder eines Ausschnitts.
    """
    zt = np.asarray(zelltypen)
    hl = (zt == 9) | (zt == 10)
    kl = hl | (zt == 8)
    h, w = zt.shape
    if h < 2 or w < 3:
        return 0.0, 0
    summe = n = 0
    for x in range(1, w - 1):
        spalte = hl[:, x]
        if not spalte.any():
            continue
        d = np.diff(np.concatenate(([0], spalte.astype(np.int8), [0])))
        for y0, y1 in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            if (kl[y0:y1, x - 1].mean() > 0.8
                    and kl[y0:y1, x + 1].mean() > 0.8):
                summe += y1 - y0
                n += 1
    return (summe / n if n else 0.0), n


def wandhoehe_vor_ort(zelltypen: np.ndarray, punkte) -> float:
    """Die Wandhoehe, an der sich eine neue Linie orientiert, in Zellen.

    Erst um die Linie herum (`WAND_UMKREIS`) -- wer an eine Klippe ansetzt,
    will deren Hoehe. Reicht das nicht (`WAND_MESS_MIN` Laeufe), die ganze
    Karte; steht auf der Karte noch keine Klippe, `WAND_ZELLEN`.
    """
    zt = np.asarray(zelltypen)
    h, w = zt.shape
    xs = [int(p[0]) for p in punkte]
    ys = [int(p[1]) for p in punkte]
    r = WAND_UMKREIS
    nah = zt[max(0, min(ys) - r):min(h, max(ys) + r + 1),
             max(0, min(xs) - r):min(w, max(xs) + r + 1)]
    for feld in (nah, zt):
        mittel, n = wandhoehe_messen(feld)
        if n >= WAND_MESS_MIN:
            return float(np.clip(mittel, WAND_ZELLEN_MIN, WAND_ZELLEN_MAX))
    return WAND_ZELLEN


def dicke_aus_hoehe(zellen: float) -> tuple[float, float]:
    """Wandhoehe in Zellen -> (hoehe_min, hoehe_max) der Felsdicke."""
    z = float(np.clip(zellen, WAND_ZELLEN_MIN, WAND_ZELLEN_MAX))
    return z - 1.5, z - 0.5
