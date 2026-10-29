"""Uebergaenge zwischen Gelaendefamilien: Mischen, Reparieren, Nachziehen.

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

Transitions between terrain families: blending, repair, follow-up. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # nur fuer Typangaben
    from mapgen_modell import TileModel  # noqa: F401


import numpy as np

import celltypes  # noqa: E402
from mapgen_basis import (  # noqa: E402
    _cell_types,
)
from mapgen_modell import (  # noqa: E402
    model,
)


def _bewuchs_abstand(fam_field: np.ndarray, tm: "TileModel",
                     abstand: int = 2) -> int:
    """Bewuchs von fremden Boeden wegruecken.

    Bewuchs ist in OP2 kein eigenes Biom, sondern die bemooste Variante von
    Erde (`mudpln01..12`, 21 Kacheln). Entsprechend gibt es keinen einzigen
    Uebergangssatz zu Fels oder Sand -- stoesst Bewuchs dort direkt an, bleibt
    nur eine harte Kante, und weil so wenige Kacheln zur Verfuegung stehen,
    wiederholt sich dabei dieselbe Kachel ueber viele Felder.

    Hier bekommt jede Bewuchszelle, die einem fremden Boden zu nahe kommt,
    Erde untergeschoben. Erde ist der richtige Puffer, weil Bewuchs ohnehin
    Erde ist und es zu Fels und Sand echte Uebergangssaetze gibt.

    Move vegetation away from foreign grounds. Vegetation is not a biome of its
    own in OP2 but the mossy variant of dirt (`mudpln01..12`, 21 tiles).
    Accordingly there is not a single transition set to rock or sand -- where
    vegetation abuts them directly only a hard edge remains, and with so few
    tiles available the same tile repeats across many cells.

    Here every vegetation cell that comes too close to a foreign ground is
    turned into dirt. Dirt is the right buffer because vegetation is dirt
    anyway, and real transition sets exist from dirt to rock and sand.
    """
    if "veg" not in tm.families or "mud" not in tm.families or abstand <= 0:
        return 0
    veg = tm.families.index("veg")
    mud = tm.families.index("mud")
    ist_veg = fam_field == veg
    if not ist_veg.any():
        return 0
    # Fremd ist alles ausser Bewuchs und Erde.
    # Foreign is everything except vegetation and dirt.
    fremd = ~(ist_veg | (fam_field == mud))
    nah = fremd.copy()
    for _ in range(abstand):
        gewachsen = nah.copy()
        gewachsen[1:, :] |= nah[:-1, :]
        gewachsen[:-1, :] |= nah[1:, :]
        gewachsen[:, 1:] |= nah[:, :-1]
        gewachsen[:, :-1] |= nah[:, 1:]
        nah = gewachsen
    treffer = ist_veg & nah
    fam_field[treffer] = mud
    return int(treffer.sum())


# Wie viele Kachelkandidaten je (Bodenpaar, Richtung) benutzt werden.
# How many tile candidates per (ground pair, direction) are used.
RAND_LIMIT = 0        # 0 = alle


def _mische_grenzen(grid: np.ndarray, fam_field: np.ndarray,
                    tm: "TileModel", rng: np.random.Generator,
                    bereich=None, params_style=None,
                    schutz: np.ndarray | None = None,
                    band_breite: int = 1) -> int:
    """Zwischen zwei Boeden eine Mischzone legen statt einer harten Kante.

    In den Originalkarten stossen zwei reine Boeden nie direkt aneinander:
    dafuer gibt es eigene Kachelsaetze (`roctomud`, `santoroc`, ...), die eine
    Flaeche in die andere einstreuen, im Mittel 2,3 Kacheln breit.

    JEDE Zelle wird genau einmal behandelt. Der erste Entwurf lief die
    Bodenpaare nacheinander durch und legte je ein Band -- wo drei Boeden
    zusammentreffen, ueberschrieb das dritte Band die beiden ersten, und die
    Kachel, die uebrig blieb, gehoerte nur zu einem Paar und stiess gegen die
    dritte Familie ungefiltert an. Gemessen blieben so 104 Kontakte uebrig,
    die es in keiner der 33 Originalkarten gibt -- ausnahmslos zwischen
    verschiedenen Familien.

    EVERY cell is handled exactly once. The first draft walked the ground pairs
    one after another, laying one band each; where three grounds meet, the
    third band overwrote the first two, and the tile left over belonged to only
    one pair and met the third family unfiltered. That left 104 contacts which
    do not occur in any of the 33 original maps -- without exception between
    different families.
    """
    if not tm.trans and not tm.rand:
        return 0
    hart = (getattr(params_style, "border_style", "zone") == "linie"
            if params_style is not None else False)
    h, w = fam_field.shape
    y0, y1, x0, x1 = (0, h, 0, w) if bereich is None else bereich

    # Je Familie: wo sie liegt und wo sie direkt angrenzt.
    # Per family: where it is and where it directly borders.
    vorhanden = sorted({int(v) for v in np.unique(fam_field)
                        if 0 <= int(v) < len(tm.families)})
    ist = {f: fam_field == f for f in vorhanden}
    eng = {}
    for f in vorhanden:
        m = ist[f].copy()
        for _ in range(max(1, band_breite)):
            gewachsen = m.copy()
            # Nur orthogonal wachsen. Ueber die Ecke mitzuwachsen laege nahe --
            # dort stossen zwei reine Kacheln diagonal aneinander, und die
            # Uebergangskachel dazwischen muesste an einer Seite durchgehend
            # Fels und an der anderen durchgehend Erde zeigen, was keine Kachel
            # des Satzes kann. Gemessen wird es davon aber SCHLECHTER: das Band
            # wird breiter, es entstehen mehr Uebergang-an-Uebergang-Kontakte,
            # und die Musterbrueche einer erzeugten Karte stiegen von 0,90 auf
            # 1,14 %.
            # Grow orthogonally only. Growing across the corner would seem
            # obvious -- two pure tiles meet diagonally there and the transition
            # between them would have to show solid rock on one side and solid
            # dirt on the other, which no tile of the set can do. Measured, it
            # gets WORSE that way: the band widens, more transition-to-
            # transition contacts arise, and a generated map's pattern breaks
            # rose from 0.90 to 1.14 %.
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                gewachsen |= _schieb(m, dy, dx)
            m = gewachsen
        eng[f] = m

    # Grenzzellen: mindestens zwei Familien im direkten Umfeld.
    # Border cells: at least two families in the immediate neighbourhood.
    zahl = np.zeros(fam_field.shape, dtype=np.int16)
    for f in vorhanden:
        zahl += eng[f].astype(np.int16)
    grenze = zahl >= 2
    if schutz is not None:
        # Frisch gemalte Zellen bleiben reiner Boden. Wer Sand malt, will
        # Sand -- und nicht, dass ein kleiner Fleck komplett zur Mischzone
        # wird, nur weil jede seiner Zellen am Nachbarbiom liegt. Der
        # Uebergang bildet sich dann aussen herum.
        # Freshly painted cells stay pure ground. Whoever paints sand wants
        # sand -- not a small patch turning entirely into blend zone just
        # because every one of its cells touches the neighbouring biome. The
        # transition then forms around it instead.
        grenze &= ~schutz
    # Ausgespart wird, was schon festgenagelt ist -- nicht der Rand als solcher.
    # Vorher fielen pauschal die aeusseren ZWEI Reihen weg, weil das Umfeld mit
    # `np.roll` gerechnet wurde und dort umlief. Beim Erzeugen ist das der
    # unspielbare Kartenrand und faellt nicht auf; beim Malen liegt dieser Rand
    # mitten in der Karte. Das Band wurde genau dort abgeschnitten, und zurueck
    # blieb eine schnurgerade Kante, an der zwei Boeden ohne Uebergang
    # aneinanderstiessen -- gemessen sechs neue harte Kontakte je Strich, alle
    # am Bereichsrand.
    # What is already pinned is left out -- not the border as such. Previously
    # the outer TWO rows fell away wholesale because the neighbourhood was
    # computed with `np.roll`, which wrapped there. When generating, that is the
    # unplayable map border and does not show; when painting, that border sits
    # in the middle of the map. The band was cut off exactly there and left a
    # dead straight edge where two grounds met without a transition -- measured,
    # six new hard contacts per stroke, all at the region border.
    grenze &= grid < 0
    if bereich is not None:
        maske = np.zeros(fam_field.shape, dtype=bool)
        maske[y0:y1, x0:x1] = True
        grenze &= maske

    # Wie stark jede Familie im 5x5-Umfeld vertreten ist -- daraus wird die
    # Gegenfamilie bestimmt.
    # How strongly each family is present in a 5x5 window -- the counterpart
    # family is derived from that.
    dichte = {}
    for f in vorhanden:
        d = np.zeros(fam_field.shape, dtype=np.int16)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                d += _schieb(ist[f], dy, dx).astype(np.int16)
        dichte[f] = d

    offen: dict[tuple[int, int], tuple] = {}
    ys, xs = np.nonzero(grenze)
    for y, x in zip(ys.tolist(), xs.tolist()):
        eigen = int(fam_field[y, x])
        if eigen not in ist:
            continue
        # Staerkste fremde Familie im Umfeld
        # Strongest foreign family in the neighbourhood
        fremde = [(int(dichte[f][y, x]), f) for f in vorhanden
                  if f != eigen and eng[f][y, x]]
        if not fremde:
            continue
        gegen = max(fremde)[1]
        paar = tuple(sorted((tm.families[eigen], tm.families[gegen])))
        if hart and tm.families[eigen] != paar[0]:
            continue            # harte Linie liegt nur auf einer Seite
        kandidaten = _rand_kandidaten(tm, paar, ist, fam_field, x, y, hart)
        if kandidaten is not None:
            offen[(x, y)] = kandidaten

    gesetzt = _loese_band(grid, tm, rng, offen)
    return gesetzt


def _schieb(m: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Verschieben wie `np.roll`, aber ohne Umlauf: der Rand wiederholt sich.

    Beim Erzeugen faellt der Unterschied kaum auf -- oben und unten liegt der
    unspielbare Kartenrand. Beim Malen ist das Feld ein AUSSCHNITT mitten aus
    der Karte, und dann behauptet der Umlauf, die obere Reihe grenze an die
    untere. Die Randwiederholung nimmt stattdessen an, der Boden gehe nach
    aussen weiter -- was er in aller Regel auch tut.

    Shift like `np.roll` but without wrap-around: the edge repeats. When
    generating, the difference hardly matters -- top and bottom are the
    unplayable map border. When painting, the field is a CROP from the middle of
    the map, and there the wrap claims the top row borders the bottom one. Edge
    repetition assumes instead that the ground continues outwards -- which it
    usually does.
    """
    erg = m
    if dy:
        vorher = erg
        erg = np.roll(vorher, dy, axis=0)
        if dy > 0:
            erg[:dy, :] = vorher[:1, :]
        else:
            erg[dy:, :] = vorher[-1:, :]
    if dx:
        vorher = erg
        erg = np.roll(vorher, dx, axis=1)
        if dx > 0:
            erg[:, :dx] = vorher[:, :1]
        else:
            erg[:, dx:] = vorher[:, -1:]
    return erg


def _rand_kandidaten(tm, paar, ist, fam_field, x, y, hart=False):
    """Welche Kacheln kommen fuer diese Grenzzelle in Frage?

    Nur Richtung und Seite entscheiden hier -- die Vertraeglichkeit mit den
    Nachbarn loest `_loese_band` fuer das ganze Band gemeinsam.

    Only direction and side decide here; compatibility with the neighbours is
    resolved by `_loese_band` for the whole band at once.
    """
    nach_richtung = tm.rand.get(paar)
    if not nach_richtung:
        return None
    erste = tm.families.index(paar[0]) if paar[0] in tm.families else None
    if erste is None or erste not in ist:
        return None
    r = _grenz_richtung(ist[erste], y, x)
    eintrag = nach_richtung.get(r) if r is not None else None
    if eintrag is None:
        for versatz in (1, -1, 2, -2, 3, -3, 4):
            eintrag = nach_richtung.get(((r or 0) + versatz) % 8)
            if eintrag is not None:
                break
    if eintrag is None:
        return None
    kacheln = np.asarray(eintrag[0])
    gewichte = np.asarray(eintrag[1], dtype=float).copy()

    # Vorlieben als GEWICHT, nicht als Filter. Vorher schnitten Rangliste und
    # Seite hart -- am Ende blieben 3,0 Kandidaten je Zelle, und bei 24,9 %
    # der benachbarten Bandzellen passte dann ueberhaupt keine Kombination
    # mehr zueinander. Die Bedingung war unerfuellbar, bevor der Loeser
    # ueberhaupt anfing. Jetzt bleiben alle Kacheln zulaessig, die
    # bevorzugten bekommen nur mehr Gewicht.
    # Preferences as WEIGHT, not as a filter. Before, ranking and side cut
    # hard -- 3.0 candidates per cell remained, and for 24.9 % of neighbouring
    # band cells no combination fitted at all. The constraint was unsatisfiable
    # before the solver even started. Now every tile stays admissible, the
    # preferred ones merely weigh more.
    if RAND_LIMIT and len(kacheln) > RAND_LIMIT:
        daempfung = np.ones(len(kacheln))
        daempfung[RAND_LIMIT:] = 0.08
        gewichte = gewichte * daempfung
    if hart and len(kacheln) > 2:
        daempfung = np.ones(len(kacheln))
        daempfung[2:] = 0.04
        gewichte = gewichte * daempfung
    eigen = int(fam_field[y, x])
    if tm.mix_of and 0 <= eigen < len(tm.families):
        zur_seite = tm.families[eigen] == paar[0]
        passend_seite = np.array([
            (tm.mix_of.get(int(k), 0.5) < 0.5) == zur_seite for k in kacheln])
        gewichte = gewichte * np.where(passend_seite, 1.0, 0.05)
    return kacheln, np.maximum(gewichte, 1e-6)


def _loese_band(grid, tm, rng, offen) -> int:
    """Das ganze Uebergangsband gemeinsam aufloesen.

    Eine Zelle nach der anderen zu waehlen kann hier nicht funktionieren: der
    Nachbarschaftsgraph der Uebergangskacheln ist duenn (im Schnitt 5,4
    zulaessige Nachfolger), also macht jede Festlegung links eine gueltige
    Wahl rechts unmoeglich, und zurueck kann man nicht. Gemessen waren 51,5 %
    aller verbliebenen Fehlpaare Uebergang gegen Uebergang.

    Deshalb hier Propagation: immer die Zelle mit den wenigsten
    Moeglichkeiten festlegen, danach die Nachbarn einschraenken. Wird eine
    Zelle leer, wird die Einschraenkung dort aufgehoben statt abzubrechen --
    ein schlechter Nachbar ist besser als ein Abbruch.

    Solve the whole transition band at once. Choosing cell by cell cannot work
    here: the adjacency graph of the transition tiles is sparse (5.4 admissible
    successors on average), so every decision on the left makes a valid choice
    on the right impossible, and there is no going back. Measured, 51.5 % of
    all remaining bad pairs were transition against transition. Hence
    propagation: always fix the cell with the fewest options, then restrict its
    neighbours. If a cell runs empty, the restriction there is lifted rather
    than aborting -- one bad neighbour beats a failed solve.
    """
    if not offen:
        return 0
    moeglich = {p: (k.copy(), g.copy()) for p, (k, g) in offen.items()}
    gesetzt = 0
    while moeglich:
        # Zelle mit der geringsten Auswahl zuerst -- so bleibt am meisten Luft.
        # Fewest options first -- that leaves the most room.
        stelle = min(moeglich, key=lambda p: len(moeglich[p][0]))
        kacheln, gewichte = moeglich.pop(stelle)
        x, y = stelle
        if not len(kacheln):
            continue
        w = gewichte / gewichte.sum() if gewichte.sum() > 0 else None
        kachel = int(rng.choice(kacheln, p=w))
        grid[y, x] = kachel
        gesetzt += 1
        # Nachbarn einschraenken
        for dx, dy, tabelle, vorwaerts in ((1, 0, tm.right, True),
                                           (-1, 0, tm.right, False),
                                           (0, 1, tm.down, True),
                                           (0, -1, tm.down, False)):
            nachbar = (x + dx, y + dy)
            if nachbar not in moeglich:
                continue
            nk, ng = moeglich[nachbar]
            richtung = "rechts" if tabelle is tm.right else "unten"
            if vorwaerts:
                k, _ = tm.nachbarn(kachel, richtung)
                erlaubt = (np.isin(nk, k) if k is not None
                           else np.ones(len(nk), dtype=bool))
            else:
                erlaubt = np.array([
                    (lambda e: e is None or kachel in e)(
                        tm.nachbarn(int(k), richtung)[0]) for k in nk])
            if erlaubt.any():
                moeglich[nachbar] = (nk[erlaubt], ng[erlaubt])
    return gesetzt


def _rand_kachel(grid, fam_field, tm, rng, paar, ist, x, y, hart=False):
    """Uebergangskachel fuer eine Grenzzelle waehlen -- nach Richtung."""
    nach_richtung = tm.rand.get(paar)
    if not nach_richtung:
        return None
    erste = tm.families.index(paar[0]) if paar[0] in tm.families else None
    if erste is None or erste not in ist:
        return None
    r = _grenz_richtung(ist[erste], y, x)
    eintrag = nach_richtung.get(r) if r is not None else None
    if eintrag is None:
        for versatz in (1, -1, 2, -2, 3, -3, 4):
            eintrag = nach_richtung.get(((r or 0) + versatz) % 8)
            if eintrag is not None:
                break
    if eintrag is None:
        return None
    kacheln, gewichte = eintrag
    if RAND_LIMIT:
        kacheln, gewichte = kacheln[:RAND_LIMIT], gewichte[:RAND_LIMIT]
    if hart:
        kacheln, gewichte = kacheln[:2], gewichte[:2]

    # Stufenleiter statt Alles-oder-nichts. Vorher wurde geprueft, ob eine
    # Kachel zu allen gesetzten Nachbarn passt -- und wenn keine passte, eine
    # beliebige gesetzt. Gemessen passten so nur 13 % der Zellen; der Notnagel
    # war der Normalfall. Jede Stufe haelt jetzt noch mindestens eine gelernte
    # Nachbarschaft ein.
    # Ladder instead of all-or-nothing. Before, a tile was checked against all
    # placed neighbours -- and if none fitted, an arbitrary one was placed.
    # Measured, only 13 % of cells fitted; the fallback was the normal case.
    # Every level now honours at least one learned adjacency.
    # Seite ZUERST: das Band ist zwei Zellen dick, eine in Boden A und eine in
    # B. Wer die Seite erst nach der Nachbarschaftsleiter beruecksichtigt, hat
    # keine Auswahl mehr -- gemessen bekamen dann beide Zellen denselben
    # Mischgrad, also lag auf der Erdseite eine felsige Kachel und daneben auf
    # der Felsseite dieselbe. Das ergibt zwei parallele Linien statt einer Zone.
    # Side FIRST: the band is two cells thick, one in ground A and one in B.
    # Taking the side into account only after the adjacency ladder leaves no
    # choice -- measured, both cells then got the same blend level, so a rocky
    # tile sat on the dirt side and the same one beside it on the rock side.
    # That gives two parallel lines instead of one zone.
    eigen = int(fam_field[y, x])
    if tm.mix_of and 0 <= eigen < len(tm.families):
        zur_seite = tm.families[eigen] == paar[0]
        gewuenscht = [i for i in range(len(kacheln))
                      if (tm.mix_of.get(int(kacheln[i]), 0.5) < 0.5) == zur_seite]
        if gewuenscht:
            kacheln = kacheln[gewuenscht]
            gewichte = np.asarray(gewichte, dtype=float)[gewuenscht]

    def waehlbar(bedingung):
        return [i for i in range(len(kacheln))
                if bedingung(int(kacheln[i]))]

    stufen = (
        lambda k: _passt_zu_nachbarn(grid, tm, x, y, k),                 # alle vier
        lambda k: _passt_zu_nachbarn(grid, tm, x, y, k, nur_gesetzte=True),
        lambda k: _passt_seite(grid, tm, x, y, k, "links"),
        lambda k: _passt_seite(grid, tm, x, y, k, "oben"),
    )
    passend = []
    for bedingung in stufen:
        passend = waehlbar(bedingung)
        if passend:
            break
    if not passend:
        passend = list(range(len(kacheln)))

    # Seite beruecksichtigen. Das Band ist zwei Zellen dick -- eine in Boden A,
    # eine in B. Bisher entschied nur die Richtung, also konnte im Fels eine
    # "fast schon Erde"-Kachel landen und daneben in der Erde eine "fast noch
    # Fels"-Kachel: das liest sich als zwei parallele Linien statt als eine
    # Zone. Der gelernte Mischgrad je Kachel loest das.
    # Take the side into account. The band is two cells thick -- one in ground
    # A, one in B. Previously only the direction decided, so a nearly-dirt tile
    # could sit in the rock and a nearly-rock tile beside it in the dirt: that
    # reads as two parallel lines instead of one zone. The learned blend level
    # per tile resolves it.
    g = np.asarray(gewichte, dtype=float)[passend]
    if g.sum() <= 0:
        return int(kacheln[passend[0]])
    return int(kacheln[passend[int(rng.choice(len(passend), p=g / g.sum()))]])


def _passt_seite(grid, tm, x, y, kachel, seite) -> bool:
    """Passt die Kachel wenigstens zu einer Seite?"""
    if seite == "links":
        if x <= 0:
            return True
        erlaubt, _ = tm.nachbarn(int(grid[y, x - 1]), "rechts")
    else:
        if y <= 0:
            return True
        erlaubt, _ = tm.nachbarn(int(grid[y - 1, x]), "unten")
    return erlaubt is None or kachel in erlaubt


def _kanten_wuerfel(art: str, x: int, y: int) -> int:
    """Feste Zufallszahl je Kante -- in jedem Lauf dieselbe.

    Hier stand `hash((art, x, y))`. Pythons `hash` ist fuer Zeichenketten pro
    Prozess gesalzen (PYTHONHASHSEED), also lieferte derselbe Seed in jedem
    neuen Lauf eine andere Karte. Gemessen: zwei Aufrufe hintereinander,
    Seed 42, zwei verschiedene Karten. Der Determinismus-Test hat das nie
    gesehen, weil er beide Karten im SELBEN Prozess erzeugt.

    Fixed random number per edge -- the same in every run. This used to be
    `hash((art, x, y))`. Python's `hash` is salted per process for strings
    (PYTHONHASHSEED), so the same seed produced a different map in every new
    run. Measured: two consecutive calls, seed 42, two different maps. The
    determinism check never saw it because it generates both maps in the SAME
    process.
    """
    n = (x * 73856093) ^ (y * 19349663) ^ (0 if art == "h" else 83492791)
    n &= 0xFFFFFFFF
    n ^= n >> 16
    n = (n * 0x7FEB352D) & 0xFFFFFFFF
    n ^= n >> 15
    return n


# Was eine sichtbar springende Nahtstelle im Vergleich zu einer Muster-
# abweichung wiegt. Ein Musterfehler ist ein Abschnitt von sechzehn (vier
# Seiten zu vier Abschnitten); eine springende Naht verdirbt eine ganze Seite,
# also vier davon.
# What a visibly jumping seam weighs compared to a pattern deviation. A pattern
# error is one segment out of sixteen (four sides of four segments); a jumping
# seam spoils a whole side, hence four of them.
NAHT_STRAFE = 4


def nachbearbeite_uebergaenge(grid: np.ndarray, fam_field: np.ndarray,
                              tm: "TileModel | None" = None,
                              rng: np.random.Generator | None = None) -> int:
    """Alle Uebergangskacheln einer fertigen Karte nachbearbeiten.

    Fasst die beiden Durchgaenge zusammen, die der Generator ohnehin benutzt:

      1. Jede Uebergangskachel aus den vier Ecken des Familienfeldes ableiten.
         Zwei benachbarte Zellen teilen sich die Ecken ihrer gemeinsamen Kante,
         also passen ihre Muster bauartbedingt zusammen. Sitzt eine
         Uebergangskachel dort, wo alle vier Ecken derselbe Boden sind, wird sie
         durch reinen Boden ersetzt -- dort ist keine Grenze.
      2. Was danach noch nicht passt, gegen eine besser passende Kachel
         desselben Satzes tauschen.

    Laesst sich auf jede Karte anwenden, auch auf eine geladene oder von Hand
    bearbeitete. Gibt die Zahl der geaenderten Zellen zurueck.

    Post-process all transition tiles of a finished map. Combines the two passes
    the generator uses anyway: derive each transition tile from the four corners
    of the family field (adjacent cells share the corners of their common edge,
    so their patterns match by construction; a transition tile where all four
    corners are the same ground is replaced by pure ground), then swap whatever
    still does not fit for a better tile from the same set. Applicable to any
    map, including a loaded or hand-edited one. Returns the number of changed
    cells.
    """
    if tm is None:
        tm = model()
    if rng is None:
        rng = np.random.default_rng(0)
    n = _uebergaenge_aus_ecken(grid, fam_field, tm, rng)
    n += _richte_uebergaenge(grid, tm)
    return n + _schliesse_harte_kanten(grid, fam_field, tm, rng)


def _harte_kanten(grid: np.ndarray, tm: "TileModel") -> tuple[np.ndarray, int]:
    """Zellen, die ohne Uebergangskachel an einen fremden Boden stossen.

    Gezaehlt werden nur Bodenpaare mit eigenem Kachelsatz. Erde neben Bewuchs
    ist normal -- dafuer gibt es keine Uebergangskacheln, der Bewuchs sitzt
    einfach auf der Erde.

    Cells butting against a foreign ground without a transition tile. Only
    ground pairs with their own tile set count; dirt beside vegetation is
    normal, there are no transition tiles for it.
    """
    fam, ueb = tm.family_of[grid], tm.ist_uebergang[grid]
    # Klippen zaehlen nicht als Bodengrenze und werden auch nicht angetastet.
    # Eine Felsklippe auf Erde gehoert einer anderen Familie an als der Boden
    # daneben -- das ist kein fehlender Uebergang, sondern eine Wand. Ohne
    # diese Ausnahme ersetzte der Durchgang Klippenkacheln durch
    # Uebergangskacheln und der Klippenanteil fiel von 1,2 auf 0,9 %.
    # Cliffs do not count as a ground border and are not touched. A rock cliff
    # on dirt belongs to a different family than the ground beside it -- that is
    # not a missing transition but a wall. Without this exception the pass
    # replaced cliff tiles with transition tiles and the cliff share fell from
    # 1.2 to 0.9 %.
    klippe = np.isin(_cell_types(grid), [celltypes.NORTH_CLIFFS,
                                         celltypes.CLIFFS_HIGH_SIDE,
                                         celltypes.CLIFFS_LOW_SIDE])
    ueb = ueb | klippe
    maske = np.zeros(grid.shape, dtype=bool)
    n = 0
    for a, b, ua, ub, dy, dx in (
            (fam[:, :-1], fam[:, 1:], ueb[:, :-1], ueb[:, 1:], 0, 1),
            (fam[:-1, :], fam[1:, :], ueb[:-1, :], ueb[1:, :], 1, 0)):
        roh = (~ua) & (~ub) & (a >= 0) & (b >= 0) & (a != b)
        ys, xs = np.nonzero(roh)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if tm.paar_hat_satz[int(a[y, x]), int(b[y, x])]:
                maske[y, x] = maske[y + dy, x + dx] = True
                n += 1
    return maske, n


def _schliesse_harte_kanten(grid: np.ndarray, fam_field: np.ndarray,
                            tm: "TileModel",
                            rng: np.random.Generator | None = None) -> int:
    """Fehlende Uebergangskacheln nachtragen, wo zwei Boeden hart anstossen.

    Die beiden anderen Durchgaenge laufen nur ueber Zellen, auf denen SCHON
    eine Uebergangskachel liegt -- sie koennen eine harte Kante verbessern,
    aber keine schliessen. Auf einer von Hand bearbeiteten Karte blieben so
    136 Stellen stehen, an denen Erde und Fels ohne `mudtoroc` aneinander-
    stossen, und der Knopf aenderte daran nichts.

    Hier werden genau die betroffenen Zellen freigegeben und alles andere
    festgenagelt, dann legt `_mische_grenzen` sein Band nur noch dort. Drei
    Runden, weil eine frisch gesetzte Uebergangskachel ihrerseits an einen
    dritten Boden stossen kann.

    Add the missing transition tiles where two grounds meet hard. The other two
    passes only walk cells that ALREADY hold a transition tile -- they can
    improve a hard edge but not close one. On a hand-edited map that left 136
    places where dirt and rock meet without `mudtoroc`, and the button did
    nothing about them. Here exactly the affected cells are freed and everything
    else is pinned, so `_mische_grenzen` lays its band only there. Three rounds,
    because a freshly placed transition tile can itself butt against a third
    ground.
    """
    if not tm.trans and not tm.rand:
        return 0
    if rng is None:
        rng = np.random.default_rng(0)
    gesetzt = 0
    for _ in range(3):
        maske, n = _harte_kanten(grid, tm)
        if not n:
            break
        fest = grid.copy()
        fest[maske] = -1
        _mische_grenzen(fest, fam_field, tm, rng)
        neu = maske & (fest >= 0) & (fest != grid)
        if not neu.any():
            break
        grid[neu] = fest[neu]
        gesetzt += int(neu.sum())
    return gesetzt


def _uebergaenge_aus_ecken(grid: np.ndarray, fam_field: np.ndarray,
                           tm: "TileModel",
                           rng: np.random.Generator | None = None) -> int:
    """Jede Uebergangskachel aus dem Familienfeld ableiten statt aus den
    Nachbarkacheln.

    Bisher wurde jede Bandzelle einzeln gewaehlt und hinterher gegen ihre
    Nachbarinnen zurechtgerueckt. Das bleibt eine Nachbesserung: wer zuerst
    gesetzt wird, gibt den Ton an, und wer spaeter kommt, muss sich fuegen.

    Hier steht das Ergebnis vorher fest. Jede Zelle hat vier Ecken, und eine
    Ecke gehoert zum fremden Boden, sobald eine der vier dort zusammen-
    stossenden Zellen ihm gehoert. Aus den zwei Ecken einer Seite folgt deren
    Muster: die erste Haelfte richtet sich nach der einen Ecke, die zweite nach
    der anderen.

    Der Gewinn steckt in der Geometrie: zwei benachbarte Zellen teilen sich
    genau die zwei Ecken ihrer gemeinsamen Kante. Ihre Muster dort sind damit
    zwangslaeufig gleich -- das passende Gegenstueck entsteht, ohne dass jemand
    es abgleichen muesste.

    Derive every transition tile from the family field instead of from the
    neighbouring tiles. Until now each band cell was chosen individually and
    afterwards aligned to its neighbours. That stays a correction: whoever is
    placed first sets the tone and whoever comes later has to comply.

    Here the result is fixed beforehand. Every cell has four corners, and a
    corner belongs to the foreign ground as soon as one of the four cells
    meeting there does. The two corners of a side give its pattern: the first
    half follows one corner, the second half the other.

    The gain lies in the geometry: two adjacent cells share exactly the two
    corners of their common edge. Their patterns there are therefore
    necessarily equal -- the matching counterpart arises without anyone having
    to reconcile it.
    """
    if tm.muster is None or not tm.trans:
        return 0
    if rng is None:
        rng = np.random.default_rng(0)
    satz: dict[int, np.ndarray] = {}
    fremd_von: dict[int, tuple[int, int]] = {}
    for (na, nb), liste in tm.trans.items():
        if na not in tm.families or nb not in tm.families:
            continue
        a, b = tm.families.index(na), tm.families.index(nb)
        kacheln = np.array([int(t) for t, _ in liste], dtype=np.int32)
        for t, _ in liste:
            satz[int(t)] = kacheln
            fremd_von[int(t)] = (a, b)
    h, w = grid.shape
    abschnitte = tm.muster.shape[2]
    halb = abschnitte // 2
    _frei = np.array([t for t in range(2048) if tm.placeable[t]], dtype=np.int32)
    gesetzt = 0
    ys, xs = np.nonzero(tm.ist_uebergang[grid])
    for y, x in zip(ys.tolist(), xs.tolist()):
        kand = satz.get(int(grid[y, x]))
        if kand is None or len(kand) < 2:
            continue
        a, b = fremd_von[int(grid[y, x])]

        def ecke(ey, ex):
            """Gehoert diese Ecke zum Boden b?"""
            for cy in (ey - 1, ey):
                for cx in (ex - 1, ex):
                    if 0 <= cy < h and 0 <= cx < w and int(fam_field[cy, cx]) == b:
                        return True
            return False

        no, nw = ecke(y, x + 1), ecke(y, x)
        so, sw = ecke(y + 1, x + 1), ecke(y + 1, x)
        # Gehoeren alle vier Ecken demselben Boden, ist hier keine Grenze --
        # und dann gehoert hier auch keine Uebergangskachel hin. Die Mischzone
        # setzt sie trotzdem: gemessen lagen zwoelf identische `santomud`
        # mitten im reinen Sand nebeneinander, alle vier Ecken Sand. Sichtbar
        # wurde das als Kette derselben Kachel, weil zu einer einheitlichen
        # Vorgabe genau eine Kachel passt.
        # If all four corners belong to the same ground there is no border here
        # -- and then no transition tile belongs here either. The blend zone
        # places one regardless: measured, twelve identical `santomud` lay side
        # by side in the middle of pure sand, all four corners sand. That showed
        # up as a chain of the same tile, because exactly one tile matches a
        # uniform specification.
        if no == nw == so == sw:
            ziel = int(fam_field[y, x])
            kand = _frei[tm.family_of[_frei] == ziel]
            if not len(kand):
                continue
            # Hier kann der Musterwert nicht entscheiden: gegen eine
            # einheitliche Vorgabe schneidet reiner Boden IMMER besser ab als
            # eine Uebergangskachel, die auf beiden Boeden steht. Auf einer
            # erzeugten Karte stimmt das auch -- das Familienfeld ist dort der
            # Entwurf. Auf einer fremden Karte ist es aus den Kacheln
            # zurueckgerechnet, und dann heisst "alle vier Ecken gleich"
            # oft nur, dass die Mehrheitsregel eine einzelne Uebergangskachel
            # ihrem Umfeld zugeschlagen hat. Gemessen richtete genau dieser
            # Zweig den Schaden an: auf cm03 allein 2923 Zellen, Musterbrueche
            # 4,10 -> 2,93 %, sichtbare Brueche aber 1,00 -> 1,40 %.
            # Entschieden wird deshalb an der Naht: getauscht wird nur, was
            # optisch nicht schlechter anschliesst als das, was schon da liegt.
            # The pattern value cannot decide here: against a uniform
            # specification pure ground ALWAYS scores better than a transition
            # tile standing on both grounds. On a generated map that is true --
            # there the family field is the design. On a foreign map it is
            # computed back from the tiles, and then "all four corners equal"
            # often only means the majority rule assigned a lone transition tile
            # to its surroundings. Measured, exactly this branch did the damage:
            # 2923 cells on cm03 alone, pattern breaks 4.10 -> 2.93 %, but
            # visible breaks 1.00 -> 1.40 %. So the seam decides: only swap for
            # something that joins no worse than what is already there.
            jetzt_naht = int(_auffaellige_naehte(
                grid, tm, x, y, [int(grid[y, x])])[0])
            kand = kand[_auffaellige_naehte(grid, tm, x, y, kand) <= jetzt_naht]
            # Und kein Kandidat, der zwei Boeden direkt aneinanderstossen
            # laesst. Die Nahtbedingung oben faengt das nicht: Erde neben Fels
            # ist farblich unauffaellig und trotzdem falsch -- dort gehoert
            # `mudtoroc` hin. Gemessen liess dieser Zweig auf einer erzeugten
            # Karte die harten Kanten von 24 auf 74 steigen; die Originale
            # haben davon keine einzige.
            # And no candidate that lets two grounds butt straight against each
            # other. The seam condition above does not catch this: dirt beside
            # rock is inconspicuous in colour and still wrong -- `mudtoroc`
            # belongs there. Measured, this branch raised the hard edges on a
            # generated map from 24 to 74; the originals have not a single one.
            if len(kand):
                kand = kand[~_macht_harte_kante(grid, tm, x, y, kand)]
            if not len(kand):
                continue
            gut = np.array([k for k in kand
                            if _passt_zu_nachbarn(grid, tm, x, y, int(k))],
                           dtype=np.int32)
            if len(gut):
                gew = np.array([max(1.0, float(tm.usage.get(int(t), 1)))
                                for t in gut])
                grid[y, x] = int(rng.choice(gut, p=gew / gew.sum()))
            else:
                schlimm = _schlimmste_naht(grid, tm, x, y, kand)
                grid[y, x] = int(kand[int(np.argmin(schlimm))])
            gesetzt += 1
            continue
        # Reihenfolge wie in `muster`: Ost, West, Sued, Nord -- jede Seite von
        # oben bzw. links gelesen.
        # Order as in `muster`: east, west, south, north, each read from the top
        # respectively the left.
        # (Eckenpaar, Kennung der gemeinsamen Kante). Wechselt der Boden
        # entlang einer Seite, gibt es drei moegliche Teilungen (1/3, 2/2, 3/1).
        # Welche genommen wird, muss an der KANTE haengen, nicht an der Zelle --
        # sonst waehlen die beiden Anrainer verschieden und die Muster passen
        # trotz gleicher Ecken nicht zusammen.
        # (corner pair, identity of the shared edge). Where the ground changes
        # along a side there are three possible splits (1/3, 2/2, 3/1). Which one
        # is taken must depend on the EDGE, not on the cell -- otherwise the two
        # neighbours choose differently and the patterns fail to match despite
        # equal corners.
        seiten = ((no, so, ("v", x + 1, y)), (nw, sw, ("v", x, y)),
                  (sw, so, ("h", x, y + 1)), (nw, no, ("h", x, y)))
        soll = np.empty((4, abschnitte), dtype=np.int16)
        for i, (anfang, ende, kante) in enumerate(seiten):
            if anfang == ende:
                soll[i, :] = b if anfang else a
                continue
            art, kx, ky = kante
            teil = 1 + (_kanten_wuerfel(art, kx, ky) % (abschnitte - 1))
            soll[i, :teil] = b if anfang else a
            soll[i, teil:] = b if ende else a
        # Wo die Nachbarin KEIN Uebergang ist, zaehlt ihr tatsaechliches Muster,
        # nicht die Ecke. Die Ecken sagen nur, wo die Grenze verlaeuft -- sie
        # setzen voraus, dass jede Zelle mit gemischten Ecken auch eine
        # Uebergangskachel traegt. Beim Malen stimmt das nicht: die frisch
        # gemalten Zellen bleiben absichtlich reiner Boden, damit der Pinsel
        # wirklich malt, was er soll. Deren Muster ist durchgehend einfarbig,
        # die Ecke daneben aber gemischt -- und dann fordert die Konstruktion
        # eine Kante, die keine Kachel des Satzes liefern kann. Gemessen waren
        # 36 von 50 uebrigen Musterbruechen im gemalten Bereich genau solche
        # Boden-Uebergang-Paare.
        # Where the neighbour is NOT a transition, its actual pattern counts,
        # not the corner. The corners only say where the border runs -- they
        # assume every cell with mixed corners also carries a transition tile.
        # When painting that does not hold: the freshly painted cells stay pure
        # ground on purpose so the brush really paints what it should. Their
        # pattern is uniform while the corner beside them is mixed -- and then
        # the construction demands an edge no tile of the set can supply.
        # Measured, 36 of 50 remaining pattern breaks in the painted region were
        # exactly such ground-transition pairs.
        for i, (ny, nx, gegen) in enumerate(((y, x + 1, 1), (y, x - 1, 0),
                                             (y + 1, x, 3), (y - 1, x, 2))):
            if 0 <= ny < h and 0 <= nx < w:
                nachbar = int(grid[ny, nx])
                if not tm.ist_uebergang[nachbar]:
                    soll[i, :] = tm.muster[nachbar, gegen]
        fehler = (tm.muster[kand] != soll[None]).sum(axis=(1, 2))
        # Musterabweichung UND Farbsprung in einem Wert. Nur die Abweichungen
        # zu zaehlen genuegte nicht: die Kachel, die schon da liegt, wurde mit
        # demselben Mass verglichen, und gemessen waren die Tausche echte
        # Verbesserungen -- nur eben optisch schlechtere. Auf cm03 sanken die
        # Musterbrueche von 4,10 auf 2,10 %, waehrend die SICHTBAREN Brueche
        # von 1,00 auf 1,31 % stiegen. Der Schaden zeigt sich am Farbsprung an
        # der Naht, also muss der Farbsprung mit in den Wert.
        # Pattern deviation AND colour jump in one value. Counting the
        # deviations alone was not enough: the tile already in place was
        # compared by the same measure, and measured, the swaps were genuine
        # improvements -- only visually worse ones. On cm03 pattern breaks fell
        # from 4.10 to 2.10 % while VISIBLE breaks rose from 1.00 to 1.31 %. The
        # damage shows up as the colour jump at the seam, so the colour jump has
        # to be part of the value.
        gesamt = fehler + NAHT_STRAFE * _auffaellige_naehte(grid, tm, x, y, kand)
        # Fehlerwert der Kachel, die schon da liegt. Ohne diesen Vergleich
        # ueberschreibt die Konstruktion auch eine Kachel, die bereits gut
        # sitzt.
        # Error value of the tile already in place. Without this comparison the
        # construction also overwrites a tile that already sits well.
        _ist = np.nonzero(kand == int(grid[y, x]))[0]
        jetzt = int(gesamt[_ist[0]]) if len(_ist) else 10 ** 6
        jetzt_muster = int(fehler[_ist[0]]) if len(_ist) else 10 ** 6
        # Unter den gleich guten wuerfeln. `argmin` nimmt immer dieselbe, und
        # weil die Ecken entlang einer geraden Grenze in jeder Zelle gleich
        # sind, stand danach vier-, fuenfmal dieselbe Kachel nebeneinander --
        # ein sichtbares Muster im Uebergang. Gewichtet nach Haeufigkeit, damit
        # seltene Kacheln selten bleiben.
        # Roll the dice among the equally good ones. `argmin` always takes the
        # same one, and since the corners are identical in every cell along a
        # straight border, the same tile then stood side by side four or five
        # times -- a visible pattern in the transition. Weighted by frequency so
        # rare tiles stay rare.
        # Eine Abweichung von einem Abschnitt zulassen. Ein vollstaendig
        # vorgegebenes 4-Seiten-Muster ist fast eindeutig -- bei 742 von 1009
        # Zellen passt genau EINE Kachel. An einer geraden Grenze wiederholt
        # sich die Vorgabe, also stand dieselbe Kachel bis zu sechzehnmal
        # nebeneinander; die Originale wiederholen hoechstens zwei.
        # Allow a deviation of one segment. A fully specified four-side pattern
        # is almost unique -- for 742 of 1009 cells exactly ONE tile fits. Along
        # a straight border the specification repeats, so the same tile stood
        # side by side up to sixteen times; the originals repeat at most two.
        # Passt keine Kachel des Satzes halbwegs, gehoert hier gar kein
        # Uebergang hin: dann lieber reiner Boden als eine Kachel, deren
        # Struktur an der Kante abgeschnitten wird.
        # If no tile of the set fits reasonably, no transition belongs here:
        # then pure ground rather than a tile whose structure gets cut off at
        # the edge.
        # Diese Frage bleibt am Muster haengen: ob ueberhaupt ein Uebergang
        # hierher gehoert, entscheidet die Form der Grenze, nicht die Farbe.
        # This question stays with the pattern: whether a transition belongs
        # here at all is decided by the shape of the border, not by the colour.
        if int(fehler.min()) > 3 and jetzt_muster > 3:
            ziel = int(fam_field[y, x])
            rein = _frei[tm.family_of[_frei] == ziel]
            # Auch hier die Naht als Bedingung. Bleibt nichts uebrig, faellt
            # die Zelle in die normale Wahl zurueck, statt reinen Boden mit
            # sichtbarem Sprung hinzustellen.
            # The seam is a condition here too. If nothing survives, the cell
            # falls back to the normal choice instead of placing pure ground
            # with a visible jump.
            if len(rein):
                jetzt_naht = int(_auffaellige_naehte(
                    grid, tm, x, y, [int(grid[y, x])])[0])
                rein = rein[_auffaellige_naehte(grid, tm, x, y, rein)
                            <= jetzt_naht]
            if len(rein):
                rein = rein[~_macht_harte_kante(grid, tm, x, y, rein)]
            if len(rein):
                gut = np.array([k for k in rein
                                if _passt_zu_nachbarn(grid, tm, x, y, int(k))],
                               dtype=np.int32)
                if len(gut):
                    gew = np.array([max(1.0, float(tm.usage.get(int(t), 1)))
                                    for t in gut])
                    grid[y, x] = int(rng.choice(gut, p=gew / gew.sum()))
                else:
                    grid[y, x] = int(rein[int(np.argmin(
                        _schlimmste_naht(grid, tm, x, y, rein)))])
                gesetzt += 1
                continue
        gleich = kand[gesamt <= gesamt.min() + 1]
        if len(gleich) > 1:
            gew = np.array([max(1.0, float(tm.usage.get(int(t), 1)))
                            for t in gleich])
            wahl = int(rng.choice(gleich, p=gew / gew.sum()))
        else:
            wahl = int(gleich[0])
        # Nur tauschen, wenn es wirklich besser wird.
        # Only swap when it actually gets better.
        neu_fehler = int(gesamt[np.nonzero(kand == wahl)[0][0]])
        if wahl != int(grid[y, x]) and neu_fehler < jetzt:
            grid[y, x] = wahl
            gesetzt += 1
    return gesetzt


def _richte_uebergaenge(grid: np.ndarray, tm: "TileModel",
                        runden: int = 3) -> int:
    """Uebergangskacheln gegen passende aus demselben Satz tauschen.

    Eine Uebergangskachel wird beim Sampeln einzeln gewaehlt und kennt dabei
    nur ihre linke und obere Nachbarin. Was rechts und unten spaeter dazukommt,
    kann nicht mehr beruecksichtigt werden -- und weil das Mischband zwei bis
    drei Kacheln dick ist, stehen dort Uebergaenge neben Uebergaengen, deren
    Ausrichtung nichts koppelt.

    Hier bekommt jede Uebergangskachel alle vier Nachbarn zu sehen und wird
    gegen die Kachel ihres eigenen Satzes getauscht, die am besten dazu passt.
    Der Satz bleibt, es aendert sich nur, welches Stueck daraus genommen wird
    -- Boden und Bandverlauf bleiben also unveraendert.

    Gemessen ueber drei Seeds fallen die sichtbaren Brueche dadurch um 40-43 %
    (0,79 auf 0,45 %), bei rund 500 getauschten Kacheln je Karte. Der Gewinn
    sitzt am Kontakt zum reinen Boden (2,24 auf 1,27 %); innerhalb des Bandes
    steigt es leicht (0,19 auf 0,63 %), was der Tausch bewusst in Kauf nimmt.

    Swap transition tiles for fitting ones from the same set. A transition tile
    is chosen individually while sampling and only knows its left and top
    neighbour; whatever arrives to the right and below later cannot be taken
    into account -- and since the blend band is two to three tiles thick,
    transitions stand next to transitions with nothing coupling their
    orientation.

    Here every transition tile gets to see all four neighbours and is swapped
    for the tile of its own set that fits them best. The set stays the same,
    only which piece is taken from it changes, so ground and band layout remain
    untouched.

    Measured across three seeds, visible breaks drop by 40-43 % (0.79 to
    0.45 %) at around 500 swapped tiles per map. The gain sits at the contact
    with pure ground (2.24 to 1.27 %); inside the band it rises slightly (0.19
    to 0.63 %), which the swap accepts deliberately.
    """
    if tm.muster is None or not tm.trans:
        return 0
    satz: dict[int, np.ndarray] = {}
    for liste in tm.trans.values():
        kacheln = np.array([int(t) for t, _ in liste], dtype=np.int32)
        for t, _ in liste:
            satz[int(t)] = kacheln
    h, w = grid.shape
    getauscht = 0
    for _ in range(max(1, runden)):
        ys, xs = np.nonzero(tm.ist_uebergang[grid])
        aenderung = 0
        for y, x in zip(ys.tolist(), xs.tolist()):
            kand = satz.get(int(grid[y, x]))
            if kand is None or len(kand) < 2:
                continue
            # (eigene Seite, Muster der Nachbarin an der gemeinsamen Kante)
            # (own side, the neighbour's pattern along the shared edge)
            soll = []
            for (ny, nx), (q, z) in (((y, x - 1), (1, 0)), ((y - 1, x), (3, 2)),
                                     ((y, x + 1), (0, 1)), ((y + 1, x), (2, 3))):
                if 0 <= ny < h and 0 <= nx < w:
                    soll.append((q, tm.muster[int(grid[ny, nx]), z]))
            if not soll:
                continue
            fehler = np.zeros(len(kand), dtype=np.int32)
            for q, muster in soll:
                fehler += (tm.muster[kand, q] != muster).sum(axis=1)
            jetzt = int(fehler[kand == int(grid[y, x])][0])
            i = int(np.argmin(fehler))
            if int(fehler[i]) < jetzt:
                grid[y, x] = int(kand[i])
                aenderung += 1
        getauscht += aenderung
        if not aenderung:
            break
    return getauscht


def _repariere_kontakte(grid, fam_field, tm, rng, ist, bereich) -> int:
    """Uebrig gebliebene Direktkontakte zweier Boeden nachtraeglich schliessen.

    Geprueft wird an den KACHELN, nicht am Familienfeld. Der erste Anlauf sah
    aufs Familienfeld -- also auf die Absicht -- und uebersah damit genau die
    Faelle, in denen der Sampler auf seinen Notnagel zurueckgefallen ist und
    eine Kachel der falschen Familie gesetzt hat. Sichtbar ist aber, was auf
    der Karte liegt.

    Checked on the TILES, not on the family field. The first attempt looked at
    the family field -- the intent -- and thereby missed exactly those cases
    where the sampler fell back and placed a tile of the wrong family. What is
    visible is what lies on the map.
    """
    y0, y1, x0, x1 = bereich
    h, w = grid.shape
    geheilt = 0
    for durchgang in range(2):
        fam = tm.family_of[grid]
        gefunden = False
        for y in range(max(1, y0), min(h - 1, y1)):
            for x in range(max(1, x0), min(w - 1, x1)):
                a = int(fam[y, x])
                if a < 0 or a >= len(tm.families):
                    continue
                for dy, dx in ((0, 1), (1, 0)):
                    ny, nx = y + dy, x + dx
                    if ny >= h - 1 or nx >= w - 1:
                        continue
                    b = int(fam[ny, nx])
                    if b < 0 or b >= len(tm.families) or a == b:
                        continue
                    paar = tuple(sorted((tm.families[a], tm.families[b])))
                    if paar not in tm.rand:
                        continue
                    kachel = _rand_kachel(grid, fam_field, tm, rng, paar,
                                          ist, nx, ny)
                    if kachel is not None:
                        grid[ny, nx] = kachel
                        fam[ny, nx] = tm.family_of[kachel]
                        geheilt += 1
                        gefunden = True
        if not gefunden:
            break
    return geheilt


def _grenz_richtung(ist_a: np.ndarray, y: int, x: int) -> int | None:
    """In welche Richtung faellt der Anteil von Boden A ab? (0-7, 45-Grad-Schritte)"""
    # 7x7 statt 5x5: mit dem engen Fenster sprang die geschaetzte Richtung
    # entlang derselben Kante von Zelle zu Zelle, und benachbarte Zellen
    # griffen dadurch in voellig verschiedene Kacheltoepfe.
    # 7x7 instead of 5x5: with the narrow window the estimated direction jumped
    # from cell to cell along the same edge, so neighbouring cells drew from
    # completely different tile pools.
    if y < 3 or x < 3 or y >= ist_a.shape[0] - 3 or x >= ist_a.shape[1] - 3:
        return None
    f = ist_a[y - 3:y + 4, x - 3:x + 4].astype(np.float64)
    gy = float(f[4:, :].sum() - f[:3, :].sum())
    gx = float(f[:, 4:].sum() - f[:, :3].sum())
    if gx == 0.0 and gy == 0.0:
        return None
    return int((np.degrees(np.arctan2(gy, gx)) % 360.0 + 22.5) // 45) % 8


def _passt_zu_nachbarn(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                       kachel: int, nur_gesetzte: bool = False, schwelle: float | None = None) -> bool:
    """Passt die Kachel zu ALLEN vier Nachbarn?

    Beim zeilenweisen Erzeugen reichen links und oben -- rechts und unten ist
    noch nichts gesetzt. Uebergangskacheln kommen aber NACHTRAEGLICH auf
    fertigen Boden, da liegen alle vier Nachbarn schon. Nur zwei zu pruefen
    liess entsprechend die Haelfte der Fehlpaarungen durch: gemessen stammten
    67 % aller nie beobachteten Nachbarpaare von Uebergangskacheln, obwohl die
    nur 20 % der Flaeche ausmachen.

    Does the tile fit ALL four neighbours? Row-by-row generation only needs
    left and top -- nothing is placed right or below yet. But transition tiles
    go onto finished ground AFTERWARDS, where all four neighbours already
    exist. Checking only two let half the mismatches through: 67 % of all
    never-observed tile pairs came from transition tiles, which cover only
    20 % of the area.
    """
    h, w = grid.shape
    # Kantenregel statt gelernter Paartabelle: die Tabelle kannte nur, was in
    # 33 Karten zufaellig vorkam, und liess deshalb fast alles durchfallen.
    # Edge rule instead of the learned pair table: the table only knew what
    # happened to occur in 33 maps and therefore rejected almost everything.
    pruefungen = (
        ("rechts", int(grid[y, x - 1]) if x > 0 else None, True),
        ("unten", int(grid[y - 1, x]) if y > 0 else None, True),
        ("rechts", int(grid[y, x + 1]) if x + 1 < w else None, False),
        ("unten", int(grid[y + 1, x]) if y + 1 < h else None, False),
    )
    for richtung, nachbar, nachbar_ist_quelle in pruefungen:
        if nachbar is None or (nur_gesetzte and nachbar < 0):
            continue
        quelle, ziel = ((nachbar, kachel) if nachbar_ist_quelle
                        else (kachel, nachbar))
        if schwelle is None:
            erlaubt, _ = tm.nachbarn(quelle, richtung)
        else:
            erlaubt, _ = tm.nachbarn_schwelle(quelle, richtung, schwelle)
        if erlaubt is not None and ziel not in erlaubt:
            return False
    return True


def _schlimmste_naht(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                     kacheln) -> np.ndarray:
    """Groesster Farbsprung je Kandidat an allen vier Nahtstellen.

    Damit laesst sich auch dort noch waehlen, wo keine Kachel die Schwelle
    haelt: nicht irgendeine, sondern die am wenigsten auffaellige.

    Largest colour jump per candidate across all four seams. This still allows
    a choice where no tile keeps the threshold: not an arbitrary one, but the
    least noticeable.
    """
    h, w = grid.shape
    kand = np.asarray(kacheln, dtype=int)
    schlimm = np.zeros(len(kand))
    nachbarn = (
        ("rechts", grid[y, x - 1] if x > 0 else -1, False),
        ("unten", grid[y - 1, x] if y > 0 else -1, False),
        ("rechts", grid[y, x + 1] if x + 1 < w else -1, True),
        ("unten", grid[y + 1, x] if y + 1 < h else -1, True),
    )
    for richtung, nachbar, rueck in nachbarn:
        if nachbar < 0:
            continue
        d = tm.kanten_abstand(int(nachbar), richtung, rueck)
        schlimm = np.maximum(schlimm, d[kand])
    return schlimm


def _auffaellige_naehte(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                        kacheln) -> np.ndarray:
    """Wie viele der vier Nahtstellen je Kandidat sichtbar springen (0..4).

    Gegenstueck zu `_schlimmste_naht`: dort interessiert der groesste Sprung,
    hier ihre Zahl. Das ist genau das, was auf der fertigen Karte als
    sichtbarer Bruch gezaehlt wird, und laesst sich deshalb mit Musterfehlern
    verrechnen. Ohne Musterstrafe, sonst zaehlt die Musterabweichung zweimal.

    How many of the four seams jump visibly per candidate (0..4). Counterpart to
    `_schlimmste_naht`: there the largest jump matters, here their number --
    exactly what is counted as a visible break on the finished map, and
    therefore commensurable with pattern errors. Without the pattern penalty,
    otherwise the pattern deviation would count twice.
    """
    h, w = grid.shape
    kand = np.asarray(kacheln, dtype=int)
    zahl = np.zeros(len(kand), dtype=np.int32)
    nachbarn = (
        ("rechts", grid[y, x - 1] if x > 0 else -1, False),
        ("unten", grid[y - 1, x] if y > 0 else -1, False),
        ("rechts", grid[y, x + 1] if x + 1 < w else -1, True),
        ("unten", grid[y + 1, x] if y + 1 < h else -1, True),
    )
    for richtung, nachbar, rueck in nachbarn:
        if nachbar < 0:
            continue
        d = tm.kanten_abstand(int(nachbar), richtung, rueck, mit_muster=False)
        zahl += d[kand] > tm.KANTEN_SCHWELLE
    return zahl


def _macht_harte_kante(grid: np.ndarray, tm: "TileModel", x: int, y: int,
                       kacheln) -> np.ndarray:
    """Welche Kandidaten stossen ohne Uebergang direkt an einen fremden Boden?

    Gemessen ueber die Originalkarten: zwischen zwei Boeden, fuer die es einen
    Uebergangssatz gibt, liegt dort IMMER eine Uebergangskachel -- cm03, cm04,
    newworld, eden01 und on2_01 haben zusammen null solche Nahtstellen. Harte
    Kanten gibt es nur zwischen Erde und Bewuchs sowie Fels und Schnee, und
    genau fuer diese Paare fehlt der Satz.

    Which candidates butt straight against a foreign ground without a
    transition? Measured across the original maps: between two grounds that have
    a transition set there is ALWAYS a transition tile -- cm03, cm04, newworld,
    eden01 and on2_01 together have zero such seams. Hard edges exist only
    between dirt and vegetation and between rock and snow, and those are exactly
    the pairs without a set.
    """
    h, w = grid.shape
    kand = np.asarray(kacheln, dtype=int)
    eigen = tm.family_of[kand]
    schlecht = np.zeros(len(kand), dtype=bool)
    gueltig = eigen >= 0
    for ny, nx in ((y, x - 1), (y - 1, x), (y, x + 1), (y + 1, x)):
        if not (0 <= ny < h and 0 <= nx < w):
            continue
        nachbar = int(grid[ny, nx])
        if tm.ist_uebergang[nachbar]:
            continue
        gegen = int(tm.family_of[nachbar])
        if gegen < 0:
            continue
        schlecht |= gueltig & (eigen != gegen) & tm.paar_hat_satz[
            np.where(gueltig, eigen, 0), gegen]
    return schlecht


def _boden_an_klippen_nachziehen(grid: np.ndarray, fam_field: np.ndarray,
                                 klippen: np.ndarray, tm: "TileModel",
                                 rng: np.random.Generator) -> int:
    """Bodenkacheln neben fertigen Klippen noch einmal waehlen.

    Die Klippen entstehen zuletzt und ueberschreiben, was der Sampler dort
    gesetzt hatte. Der Boden daneben wurde also fuer eine Nachbarin gewaehlt,
    die es nicht mehr gibt -- gemessen war die Naht Klippe|Boden mit 10,0 %
    die schlechteste der ganzen Karte, gegen 0,2-0,3 % in den Originalen.
    Hier bekommt dieser Boden seine Wahl zurueck, jetzt mit der echten Klippe
    als Nachbarin. Die Familie bleibt, es geht nur um die Kachel.

    Choose the ground tiles next to finished cliffs again. Cliffs are drawn last
    and overwrite what the sampler had put there, so the ground beside them was
    chosen for a neighbour that no longer exists -- measured, the cliff|ground
    seam was the worst on the map at 10.0 %, against 0.2-0.3 % in the originals.
    Here that ground gets its choice back, now with the real cliff as its
    neighbour. The family stays; only the tile changes.
    """
    if not klippen.any():
        return 0
    h, w = grid.shape
    rand = np.zeros_like(klippen)
    rand[1:, :] |= klippen[:-1, :]
    rand[:-1, :] |= klippen[1:, :]
    rand[:, 1:] |= klippen[:, :-1]
    rand[:, :-1] |= klippen[:, 1:]
    rand &= ~klippen
    frei = np.array([t for t in range(2048) if tm.placeable[t]], dtype=np.int32)
    geaendert = 0
    ys, xs = np.nonzero(rand)
    for y, x in zip(ys.tolist(), xs.tolist()):
        fam = int(fam_field[y, x])
        kand = frei[tm.family_of[frei] == fam]
        if not len(kand):
            continue
        # Nur eingreifen, wenn die jetzige Kachel wirklich nicht mehr passt.
        # Only step in when the current tile really no longer fits.
        if _passt_zu_nachbarn(grid, tm, x, y, int(grid[y, x])):
            continue
        gut = np.array([i for i, k in enumerate(kand)
                        if _passt_zu_nachbarn(grid, tm, x, y, int(k))],
                       dtype=int)
        if len(gut):
            gew = np.array([max(0.01, float(tm.usage.get(int(kand[i]), 0)))
                            for i in gut])
            wahl = int(kand[gut[int(rng.choice(len(gut), p=gew / gew.sum()))]])
        else:
            schlimm = _schlimmste_naht(grid, tm, x, y, kand)
            wahl = int(kand[int(np.argmin(schlimm))])
        if wahl != int(grid[y, x]):
            grid[y, x] = wahl
            geaendert += 1
    return geaendert
