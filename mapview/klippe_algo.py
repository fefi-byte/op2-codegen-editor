"""Klippen algorithmisch setzen: das Gelaende bestimmt die Kachel.

Der fruehere Blockweg legte vorgefertigte Bloecke an die Kante und besserte
hinterher nach; er ist entfernt (docs/klippen-stand.md, Abschnitt 24). Dieser
Weg dreht das um -- er fragt nicht
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

Der Weg braucht eine Kantenzuordnung der Kachelraender: fuer mud von Hand,
fuer san automatisch (`cliff_kanten_auto`). sno hat zu wenige Klippenkacheln
-- `verfuegbar()` gibt Auskunft, und ohne Zuordnung wird keine Klippe gesetzt.

Er ist der einzige Klippenweg: Editorpinsel, Live-Vorschau und Kartengenerator
rufen alle `klippe_aus_linie`.
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
    ber = Counter()
    for _r in range(runden):
        hat = _zellen(fein)
        offen = _offen(hat) & hat[..., None]
        blk = _bloecke(fein)                      # Sicht -- schreibt durch
        vorher = int(fein.sum())
        blk[offen[..., 0], 0, :] = False
        blk[offen[..., 1], :, -1] = False
        blk[offen[..., 2], -1, :] = False
        blk[offen[..., 3], :, 0] = False
        geaendert = vorher - int(fein.sum())
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
    hat = _zellen(fein)
    blk = _bloecke(fein)
    ber = Counter()
    for r, geg, dy, dx in (("O", "W", 0, 1), ("S", "N", 1, 0)):
        if r == "O":
            a_leer = ~blk[:, :-1, :, -1].any(axis=-1)
            b_leer = ~blk[:, 1:, :, 0].any(axis=-1)
            paar = hat[:, :-1] & hat[:, 1:] & a_leer & b_leer
        else:
            a_leer = ~blk[:-1, :, -1, :].any(axis=-1)
            b_leer = ~blk[1:, :, 0, :].any(axis=-1)
            paar = hat[:-1, :] & hat[1:, :] & a_leer & b_leer
        for y, x in zip(*np.nonzero(paar)):
            ny, nx = y + dy, x + dx
            a_l = _randlinie(fein, x, y, r)
            b_l = _randlinie(fein, nx, ny, geg)
            da = fein[y * FEIN:(y + 1) * FEIN,
                      x * FEIN:(x + 1) * FEIN].sum(axis=0 if r == "O" else 1)
            db = fein[ny * FEIN:(ny + 1) * FEIN,
                      nx * FEIN:(nx + 1) * FEIN].sum(axis=0 if r == "O"
                                                     else 1)
            i = int(np.argmax(da + db))
            a_l[i] = True
            b_l[i] = True
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
    ber = Counter()
    tab = _tabelle(vor)
    for _r in range(runden):
        hat = _zellen(fein)
        ys, xs = np.nonzero(hat)
        if not len(ys):
            break
        blk = _bloecke(fein)
        soll = _soll(blk[ys, xs])                          # (m, 4, FEIN)
        fehl = _fehl(tab, soll)                            # (m, n)
        schlecht = np.nonzero(~(fehl == 0).any(axis=1))[0]
        if not len(schlecht):
            break
        offen = _offen(hat)[ys, xs]                        # (m, 4)
        for k in schlecht:
            y, x = int(ys[k]), int(xs[k])
            # Welche Seiten stossen ans Biom? Dort darf die Berichtigung
            # keinen Fels hinschreiben -- sonst holt sie sich genau den
            # harten Uebergang zurueck, den die Randregel eben geraeumt
            # hat. Gemessen: auf einer 2:1-Schraege blieb sonst eine
            # Stelle stehen.
            hart = (tab.fels & offen[k][None, :, None]).sum(axis=(1, 2))
            anteil = float(blk[y, x].mean())
            reihe = np.lexsort((tab.kacheln, np.abs(tab.fa - anteil),
                                fehl[k], hart))
            seiten = tab.E[reihe[0]]
            for ri, r in enumerate(SEITEN):
                linie = _randlinie(fein, x, y, r)
                for i in range(FEIN):
                    u = seiten[ri, i]
                    if u == EGAL:
                        continue
                    linie[i] = (u == FELS) and not offen[k][ri]
            ber["berichtigt"] += 1
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



# --------------------------------------------------------------- schnell
#
# Alles, was je Zelle und je Kachel gefragt wird, steht hier einmal als
# numpy-Tabelle. Vorher liefen Kandidatenwahl, Angleichen und Paarpruefung
# in Python-Schleifen ueber Kacheln und Abschnitte: 0,35 s je Wand im Mittel,
# bis 2,9 s -- zu langsam fuer eine Vorschau unter der Maus.

SEITEN_I = {r: i for i, r in enumerate(SEITEN)}
GEGEN_R = {"N": "S", "O": "W", "S": "N", "W": "O"}


class _Tabelle:
    """Der Vorrat einer Familie als Felder (Kacheln in fester Reihenfolge)."""

    def __init__(self, vor: dict):
        from cliff_tiles import modell as _tm
        ke, px = _modelle()
        tt = _tm()
        innen = innenbilder()
        self.kacheln = np.array(sorted(vor), dtype=np.int64)
        self.platz = {int(t): i for i, t in enumerate(self.kacheln)}
        n = len(self.kacheln)
        self.n = n
        self.E = np.zeros((n, 4, FEIN), dtype=np.int8)          # N O S W
        self.fa = np.zeros(n)
        self.I = np.zeros((n, FEIN, FEIN), dtype=bool)
        self.hat_innen = np.zeros(n, dtype=bool)
        for i, t in enumerate(self.kacheln):
            seiten, fa = vor[int(t)]
            for r in SEITEN:
                self.E[i, SEITEN_I[r]] = seiten[r]
            self.fa[i] = fa
            ib = innen.get(int(t))
            if ib is not None:
                self.I[i] = ib
                self.hat_innen[i] = True
        self.fels = (self.E == FELS)
        self.felsseite = self.fels.any(axis=2)                   # (n, 4)
        rand = np.stack([self.I[:, 0, :], self.I[:, :, -1],
                         self.I[:, -1, :], self.I[:, :, 0]], axis=1)
        self.pixfels = (rand.sum(axis=2) >= OFFEN_FELS_MAX) & \
            self.hat_innen[:, None]
        biom = (self.E == BIOM).sum(axis=2)
        self.binseite = (biom >= 3) & ~self.felsseite
        # Paare je Richtung: belegt (Karten), Kanten erlaubt, Loch.
        self.belegt = {}
        self.kante = {}
        self.loch = {}
        self.naht = {}
        for r in SEITEN:
            g = GEGEN_R[r]
            a = self.E[:, SEITEN_I[r]][:, None, :]
            b = self.E[None, :, SEITEN_I[g]]
            self.kante[r] = ((a == b) | (a == EGAL) | (b == EGAL)).all(axis=2)
            self.loch[r] = ((a == BIOM) & (b == BIOM)).sum(axis=2) >= 3
            bel = np.zeros((n, n), dtype=bool)
            for i, t in enumerate(self.kacheln):
                for u in tt.nachbarn(int(t), r):
                    j = self.platz.get(int(u))
                    if j is not None:
                        bel[i, j] = True
            self.belegt[r] = bel
            nt = np.full((n, n), np.nan)
            pp = [px._platz.get(int(t)) for t in self.kacheln]
            if all(v is not None for v in pp):
                taf = px._tafel(r)
                nt = taf[np.ix_(pp, pp)].astype(float)
            self.naht[r] = nt
        self._erlaubt: dict = {}

    def erlaubt(self, nur_belegt: bool, loch_erlaubt: bool) -> dict:
        """-> {r: [Menge erlaubter j je i]} -- einmal je Einstellung."""
        k = (nur_belegt, loch_erlaubt)
        if k not in self._erlaubt:
            aus = {}
            for r in SEITEN:
                m = self.belegt[r] if nur_belegt else \
                    (self.belegt[r] | self.kante[r])
                if not loch_erlaubt:
                    m = m & ~self.loch[r]
                aus[r] = [set(np.nonzero(m[i])[0].tolist())
                          for i in range(self.n)]
            self._erlaubt[k] = aus
        return self._erlaubt[k]


def _tabelle(vor: dict) -> _Tabelle:
    k = ("tabelle", id(vor))
    if k not in _zwischen:
        _zwischen[k] = _Tabelle(vor)
    return _zwischen[k]


def _bloecke(fein: np.ndarray) -> np.ndarray:
    """(h*FEIN, w*FEIN) -> (h, w, FEIN, FEIN)."""
    fh, fw = fein.shape
    return fein.reshape(fh // FEIN, FEIN, fw // FEIN, FEIN).transpose(0, 2, 1, 3)


def _soll(blk: np.ndarray) -> np.ndarray:
    """(..., FEIN, FEIN) -> (..., 4, FEIN): Rand N O S W als FELS/BIOM."""
    return np.stack([blk[..., 0, :], blk[..., :, -1],
                     blk[..., -1, :], blk[..., :, 0]], axis=-2).astype(np.int8)


def _offen(hat: np.ndarray) -> np.ndarray:
    """(h, w) -> (h, w, 4): ist die Nachbarzelle N O S W keine Klippe?"""
    p = np.pad(hat, 1, constant_values=False)
    return ~np.stack([p[:-2, 1:-1], p[1:-1, 2:], p[2:, 1:-1], p[1:-1, :-2]],
                     axis=-1)


def _fehl(tab: _Tabelle, soll: np.ndarray) -> np.ndarray:
    """(m, 4, FEIN) Soll -> (m, n) Abweichungen je Kachel."""
    E = tab.E[None]
    return ((E != EGAL) & (E != soll[:, None])).sum(axis=(2, 3))


def loesen(grid: np.ndarray, fein: np.ndarray, vor: dict,
           zeit: float = LOESER_ZEIT, abweichung: int = 0,
           gelaende_zuerst: bool = True, loch_erlaubt: bool = False,
           nur_belegt: bool = False, innen_gewicht: bool = True,
           wdh_stufe: int = 1, offen_ok: dict | None = None,
           vorbereitet: dict | None = None):
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

    tab = _tabelle(vor)
    vb = vorbereitet if vorbereitet is not None else \
        _vorbereiten(tab, fein, offen_ok)
    if vb is None:
        return None
    zellen, nachbarn = vb["zellen"], vb["nachbarn"]
    FE, IN, OF, BI, AN = vb["fehl"], vb["inn"], vb["ofs"], vb["bin"], vb["anteil"]
    erlaubt = tab.erlaubt(nur_belegt, loch_erlaubt)
    belegt_m = tab.belegt
    naht = tab.naht

    dom: dict = {}
    for k, p in enumerate(zellen):
        moegl = np.nonzero(FE[k] <= abweichung)[0]
        if not len(moegl):
            return None
        vorn = OF[k, moegl] + (BI[k, moegl] if INNENKANTE == 1 else 0)
        reihe = np.lexsort((tab.kacheln[moegl], AN[k, moegl], IN[k, moegl],
                            FE[k, moegl], vorn))
        dom[p] = moegl[reihe].tolist()
    platz = {p: k for k, p in enumerate(zellen)}

    belegt: dict = {}
    start = time.time()
    schritte = [0]

    def ordnen(kand, p):
        x, y = p
        k = platz[p]
        gesetzt = [(r, belegt[q]) for r, q in nachbarn[p] if q in belegt]
        nb_kacheln = {t for _r, t in gesetzt}
        # Auch zwei und drei Zellen weiter: A-B-A-B und A-B-C-A-B-C sind
        # ebenso Wiederholung. Den Dreierrhythmus zeigte die Nordkante, nachdem
        # sie drei gleichwertige Kacheln hatte (158, 162, 159, 158, ...).
        weiter = set()
        for r in SEITEN:
            dx, dy = VERSATZ[r]
            for kk in (2, 3):
                q = belegt.get((x + kk * dx, y + kk * dy))
                if q is not None:
                    weiter.add(q)
        fe, inn_k, of = FE[k], IN[k], OF[k]
        bi = BI[k]

        def schluessel(i_t):
            i, t = i_t
            rang = 0 if all(belegt_m[r][t, b] for r, b in gesetzt) else 1
            gleich = (2 if t in nb_kacheln else 0) + (1 if t in weiter else 0)
            s = n = 0.0
            for r, b in gesetzt:
                d = naht[r][t, b]
                if d == d:                                   # nicht NaN
                    s += d
                    n += 1
            inn = int(inn_k[t]) if innen_gewicht else 0
            f = int(fe[t])
            if wdh_stufe == 2:
                stufen = (gleich, f, inn, rang)
            elif wdh_stufe == 1:
                stufen = (f, gleich, inn, rang)
            else:
                stufen = (f, inn, rang, gleich)
            if not gelaende_zuerst:
                stufen = (rang,) + stufen
            if INNENKANTE == 2:
                stufen = (stufen[0], int(bi[t])) + stufen[1:]
            # Erste Vorliebe wie bei der Kandidatenliste: Bild-Fels zum
            # offenen Boden, plus (INNENKANTE 1) Seiten ohne Fels zu einer
            # Klippennachbarin.
            vorn = int(of[t]) + (int(bi[t]) if INNENKANTE == 1 else 0)
            stufen = (vorn,) + stufen
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
            kk = dom[p]
            if beste is None or len(kk) < len(dom[beste]):
                beste = p
                if len(kk) <= 1:
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
                darf = erlaubt[r][t]
                neu = [u for u in dom[q] if u in darf]
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
    for (x, y), i in belegt.items():
        grid[y, x] = int(tab.kacheln[i])
        maske[y, x] = True
    ber = Counter(gesetzt=len(belegt), Suchschritte=schritte[0])
    return maske, ber


def _vorbereiten(tab: _Tabelle, fein: np.ndarray, offen_ok: dict | None):
    """Alles je Zelle und Kachel, was nicht von der Stufe abhaengt -- einmal.

    -> dict mit Zellen (x, y), Nachbarn und den Feldern (Zellen x Kacheln):
    fehl (Randabweichung), inn (Innenabweichung), ofs (Bild-Fels zum
    offenen Boden), bin (Seite ohne Fels zu einer Klippennachbarin), anteil
    (Abstand im Felsanteil). Kacheln mit FELS zu einer offenen Seite sind
    ausgeschlossen (fehl = 99).
    """
    hat = _zellen(fein)
    ys, xs = np.nonzero(hat)
    if not len(ys):
        return None
    blk = _bloecke(fein)[ys, xs]                          # (m, F, F)
    soll = _soll(blk)
    offen = _offen(hat)[ys, xs].copy()                    # (m, 4)
    if offen_ok:
        for k, (y, x) in enumerate(zip(ys, xs)):
            r = offen_ok.get((int(x), int(y)))
            if r is not None:
                # Ende einer Nordkante: die Linie darf an die offene Seite.
                offen[k, SEITEN_I[r]] = False
    fehl = _fehl(tab, soll)
    # Hart: kein Fels zum offenen Boden hin.
    hart = (tab.felsseite[None] & offen[:, None, :]).any(axis=2)
    fehl = np.where(hart, 99, fehl)
    # Bild-Fels zum offenen Boden -- als Verbot gemessen zu streng (17 von 39
    # Pruefwaenden unloesbar), darum als erste Vorliebe.
    ofs = (tab.pixfels[None] & offen[:, None, :]).sum(axis=2)
    # Seite ganz ohne Fels zu einer Nachbarzelle, die selbst Klippe ist.
    bin_ = (tab.binseite[None] & ~offen[:, None, :]).sum(axis=2)
    inn = (tab.I[None] != blk[:, None]).sum(axis=(2, 3))
    inn = np.where(tab.hat_innen[None], inn, FEIN * FEIN)
    anteil = np.abs(tab.fa[None] - blk.mean(axis=(1, 2))[:, None])
    zellen = [(int(x), int(y)) for y, x in zip(ys, xs)]
    drin = set(zellen)
    nachbarn = {}
    for (x, y) in zellen:
        nb = []
        for r in SEITEN:
            dx, dy = VERSATZ[r]
            q = (x + dx, y + dy)
            if q in drin:
                nb.append((r, q))
        nachbarn[(x, y)] = nb
    return {"zellen": zellen, "nachbarn": nachbarn, "fehl": fehl,
            "inn": inn, "ofs": ofs, "bin": bin_, "anteil": anteil}

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
    hat = _zellen(fein)
    blk = _bloecke(fein)
    # waagerecht: Zelle (y, x) und (y, x+1)
    paar = hat[:, :-1] & hat[:, 1:]
    l = blk[:, :-1, :, -1]
    r = blk[:, 1:, :, 0]
    v = l | r
    l[paar] = v[paar]
    r[paar] = v[paar]
    # senkrecht: Zelle (y, x) und (y+1, x)
    paar = hat[:-1, :] & hat[1:, :]
    o = blk[:-1, :, -1, :]
    u = blk[1:, :, 0, :]
    v = o | u
    o[paar] = v[paar]
    u[paar] = v[paar]
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
# Zeit je Stufe. Erfolgreiche Stufen sind nach hoechstens 0,05 s fertig
# (gemessen ueber 78 Pruefwaende); was laenger sucht, findet nichts mehr und
# lief vorher bis zur Grenze von 1 bis 1,5 s -- das waren alle Ausreisser.
STUFEN_ZEIT = 0.15

LOESER_STUFEN = (
    (True, 4, STUFEN_ZEIT),
    (False, 0, STUFEN_ZEIT),
    (False, 1, STUFEN_ZEIT),
    (False, 2, STUFEN_ZEIT),
    (False, 3, STUFEN_ZEIT),
    (False, 4, STUFEN_ZEIT),
    # Fuer die waagerechte Nordkante: dort greift erst 4 bis 5 (gemessen an
    # drei Saaten), sonst faellt sie auf `setzen` zurueck -- 54 % unpassende
    # Paare.
    (False, 5, STUFEN_ZEIT),
    (False, 6, STUFEN_ZEIT),
)


def loesen_stufenweise(grid: np.ndarray, fein: np.ndarray, vor: dict,
                       stufen=LOESER_STUFEN, offen_ok: dict | None = None):
    """`loesen` ueber die Stufen in `LOESER_STUFEN` -> (maske, Bericht) | None.

    Der Bericht nennt die Stufe, die gegriffen hat.
    """
    vb = _vorbereiten(_tabelle(vor), fein, offen_ok)
    if vb is None:
        return None
    for i, (nur_belegt, abw, zeit) in enumerate(stufen):
        r = loesen(grid, fein, vor, zeit=zeit, abweichung=abw,
                   nur_belegt=nur_belegt, offen_ok=offen_ok, vorbereitet=vb)
        if r is not None:
            r[1]["Stufe"] = i
            return r
    return None


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


def klippe_aus_linie(grid: np.ndarray, punkte, hoch_seite: str, tm,
                     rng, familie: str = "mud",
                     hoehe_min: float = HOEHE_MIN,
                     hoehe_max: float = HOEHE_MAX):
    """Eine gezeichnete Kante algorithmisch belegen -> (Maske, Zelltypfeld).

    Gleiche Auskunft wie `mapgen.klippe_aus_linie`, damit der Editor beide
    Wege ohne Umbau aufrufen kann. Der Zelltyp wird nicht selbst gesetzt: -1
    heisst "aus der Kachel ableiten", und genau das tut der Aufrufer bereits.
    """
    # Nur auf dem Ausschnitt um die Linie arbeiten. Mehrere Schritte laufen
    # ueber jede Zelle ihres Gitters; auf einer 256x256-Karte war das der
    # groesste Teil der Zeit, obwohl die Wand nur ein paar hundert Zellen hat.
    h, w = grid.shape
    zellen = np.full(grid.shape, -1, dtype=np.int16)
    if len(punkte) < 2:
        return np.zeros(grid.shape, dtype=bool), zellen
    rand = int(np.ceil(max(hoehe_max, NORD_MAX) + 3 * UNRUHE)) + 3
    xs = [p[0] for p in punkte]
    ys = [p[1] for p in punkte]
    x0, x1 = max(0, int(min(xs)) - rand), min(w, int(max(xs)) + rand + 1)
    y0, y1 = max(0, int(min(ys)) - rand), min(h, int(max(ys)) + rand + 1)
    if x1 - x0 < w or y1 - y0 < h:
        teil = grid[y0:y1, x0:x1]
        m, z = klippe_aus_linie(teil, [(px - x0, py - y0) for px, py in punkte],
                                hoch_seite, tm, rng, familie,
                                hoehe_min, hoehe_max)
        maske = np.zeros(grid.shape, dtype=bool)
        maske[y0:y1, x0:x1] = m
        zellen[y0:y1, x0:x1] = z
        return maske, zellen
    vor = vorrat(tm, familie)
    if len(punkte) < 2 or len(vor) < MINDEST_KACHELN:
        return np.zeros(grid.shape, dtype=bool), zellen
    nordenden: list = []
    # Ein geschlossener Zug (Mesa, Ring) hat keine Enden -- dort darf die Wand
    # nicht spitz auslaufen.
    geschlossen = len(punkte) > 2 and tuple(punkte[0]) == tuple(punkte[-1])
    fein, achse = band_aus_linie(punkte, hoch_seite, w, h, rng,
                                 hoehe_min, hoehe_max, nordenden=nordenden,
                                 enden=not geschlossen)
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
