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
HOEHE_MIN = 2.5
HOEHE_MAX = 4.5
UNRUHE = 0.35                  # wie stark die Oberkante wandert, in Kacheln

_zwischen: dict = {}


def _modelle():
    if "K" not in _zwischen:
        _zwischen["K"] = kantenmodell()
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


def band_aus_linie(punkte, hoch_seite: str, breite: int, hoehe: int,
                   rng, hoehe_min: float = HOEHE_MIN,
                   hoehe_max: float = HOEHE_MAX, unruhe: float = UNRUHE):
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
    dicke = hoehe_min + (hoehe_max - hoehe_min) * (0.5 + 0.5 * np.tanh(dicke_r))

    s = 0
    for i in range(len(punkte) - 1):
        x0, y0 = punkte[i]
        x1, y1 = punkte[i + 1]
        art, ri = _wand_achse(x0, y0, x1, y1, hoch_seite)
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * FEIN) + 1
        for k in range(n):
            u = k / max(1, n - 1)
            px = (x0 + (x1 - x0) * u + 0.5) * FEIN
            py = (y0 + (y1 - y0) * u + 0.5) * FEIN
            w = wandern[min(s, schritte - 1)] * FEIN
            d = dicke[min(s, schritte - 1)] * FEIN
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
    return fein, achse


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
    fein, achse = band_aus_linie(punkte, hoch_seite, w, h, rng,
                                 hoehe_min, hoehe_max)
    if not fein.any():
        return np.zeros(grid.shape, dtype=bool), zellen
    fein, _b = fuellregel(fein, achse, rng)
    # Die beiden Regeln muessen abwechselnd laufen. Die Berichtigung kann eine
    # duenne Randzelle ganz leeren; danach steht die Nachbarzelle mit Fels an
    # einer Naht, hinter der nun Biom liegt -- die Randregel hatte zu diesem
    # Zeitpunkt noch Klippe gesehen. Ohne den Wechsel blieb auf einer
    # 2:1-Schraege genau eine harte Stelle stehen.
    for _r in range(4):
        vorher = fein
        fein, _b = rand_dem_biom(fein)
        fein, _b = naht_haelt(fein)
        fein, _b = angleichen(fein, vor)
        if np.array_equal(fein, vorher):
            break
    maske, _ber = setzen(grid, fein, vor)
    for y, x in zip(*np.nonzero(maske)):
        zt = celltypes.default_cell_type(int(grid[y, x]))
        if zt is not None:
            zellen[y, x] = zt
    return maske, zellen
