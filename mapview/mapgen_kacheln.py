"""Kacheln innerhalb der Regionen aus der gelernten Nachbarschaft ziehen.

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

Draw tiles inside the regions from the learned adjacency. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from mapgen_basis import (  # noqa: E402
    _LEER,
)
from mapgen_modell import (  # noqa: E402
    TileModel,
)


# --------------------------------------------------------------------------
# Kacheln / tiles

def _sample_tiles(fam_field: np.ndarray, rng: np.random.Generator,
                  tm: TileModel, fest: np.ndarray | None = None,
                  familie_zwingend: np.ndarray | None = None) -> np.ndarray:
    """Kacheln zeilenweise aus der gelernten Nachbarschaft ziehen.

    `fest` belegt Zellen vor, die nicht gewuerfelt werden sollen -- die
    Uebergangskacheln an Bodengrenzen. Sie muessen VOR dem Boden feststehen,
    sonst waehlt der Sampler seine Kacheln ohne Wissen um den Uebergang und
    die beiden passen hinterher nicht zusammen. Genau daher stammten 67 % aller
    nie beobachteten Nachbarpaare.

    `fest` pre-fills cells that must not be rolled -- the transition tiles at
    ground borders. They have to be fixed BEFORE the ground, otherwise the
    sampler picks its tiles without knowing about the transition and the two do
    not fit afterwards. That was the source of 67 % of all never-observed tile
    pairs.
    """
    h, w = fam_field.shape
    grid = np.zeros((h, w), dtype=np.int32)

    def family_pick(fi: int) -> int:
        pool = tm.by_family.get(int(fi))
        if pool is None:
            pool = tm.by_family[next(iter(tm.by_family))]
        tiles, probs = pool
        return int(rng.choice(tiles, p=probs))

    # Wie oft welche Stufe gebraucht wurde -- fuer die Messung.
    # How often each level was needed -- for measurement.
    stufen = Counter()
    # Alle frei setzbaren Kacheln -- Grundlage, wenn nur noch die Vorschau
    # eingehalten werden kann.
    # All freely placeable tiles -- the basis when only the look-ahead can
    # still be honoured.
    _frei = np.array([t for t in range(2048) if tm.placeable[t]], dtype=np.int32)
    # Echte Haeufigkeit als Gewicht. Der fruehere Boden von 1.0 hob jede
    # Rarität auf das Niveau der haeufigsten Kachel.
    # Real frequency as the weight. The former floor of 1.0 lifted every rarity
    # to the level of the most common tile.
    alle_kacheln = (_frei, np.array([max(0.01, float(tm.usage.get(int(t), 0)))
                                     for t in _frei]))

    def schnitt(a, b):
        """Zwei gewichtete Kachelmengen schneiden."""
        if a is None:
            return b
        if b is None:
            return a
        keys_a, w_a = a
        keys_b, w_b = b
        gemeinsam, ia, ib = np.intersect1d(keys_a, keys_b, return_indices=True)
        if not len(gemeinsam):
            return None
        return gemeinsam, w_a[ia] * w_b[ib]

    def nur_familie(paar, ziel):
        if paar is None:
            return None
        keys, gew = paar
        maske = tm.family_of[keys] == ziel
        return (keys[maske], gew[maske]) if maske.any() else None

    def nur_platzierbar(paar):
        if paar is None:
            return None
        keys, gew = paar
        maske = tm.placeable[keys]
        return (keys[maske], gew[maske]) if maske.any() else None

    for y in range(h):
        for x in range(w):
            if fest is not None and fest[y, x] >= 0:
                grid[y, x] = int(fest[y, x])
                continue
            target = int(fam_field[y, x])
            links = tm.nachbarn(int(grid[y, x - 1]), "rechts") if x > 0 else None
            oben = tm.nachbarn(int(grid[y - 1, x]), "unten") if y > 0 else None
            if links is not None and links[0] is None:
                links = None
            if oben is not None and oben[0] is None:
                oben = None
            links = nur_platzierbar(links)
            oben = nur_platzierbar(oben)

            # Vorausschauen auf schon festgelegte Zellen rechts und unten.
            # Die Uebergangskacheln stehen fest, BEVOR der Boden gesampelt
            # wird -- ohne diesen Blick nach vorn waehlt der Boden ueber und
            # links von ihnen seine Kachel, ohne sie zu kennen, und genau dort
            # entstehen die Paare, die es im Original nie gab.
            # Look ahead at cells already fixed to the right and below. The
            # transition tiles are set BEFORE the ground is sampled -- without
            # this look-ahead the ground above and left of them picks its tile
            # without knowing them, and that is exactly where the pairs appear
            # that never existed in the originals.
            vorlaeufer = []
            if fest is not None:
                # Auch hier die Kantenregel statt der gelernten Tabelle:
                # die kannte je Kachel 21 Vorgaenger und war damit die
                # strengste verbliebene Bedingung -- sie allein trieb die
                # Rueckfallstufen.
                # The edge rule here too: the learned table knew 21 predecessors
                # per tile and was thus the strictest remaining constraint --
                # it alone drove the fallback levels.
                if x + 1 < w and fest[y, x + 1] >= 0:
                    k, _ = tm.nachbarn_rev(int(fest[y, x + 1]), "rechts")
                    vorlaeufer.append(k if k is not None else _LEER)
                if y + 1 < h and fest[y + 1, x] >= 0:
                    k, _ = tm.nachbarn_rev(int(fest[y + 1, x]), "unten")
                    vorlaeufer.append(k if k is not None else _LEER)

            def passt_voraus(paar):
                """Kandidaten aussortieren, die zur festen Nachbarin nicht passen."""
                if paar is None or not vorlaeufer:
                    return paar
                keys, gew = paar
                maske = np.ones(len(keys), dtype=bool)
                for erlaubte in vorlaeufer:
                    maske &= np.isin(keys, erlaubte)
                    if not maske.any():
                        return None
                return keys[maske], gew[maske]

            # Stufenleiter: immer nur die schwaechste Bedingung fallen lassen.
            # Der alte Notnagel warf bei leerer Auswahl ALLE Bedingungen weg
            # und zog irgendeine Kachel der Zielfamilie -- daher stammten die
            # nie beobachteten Nachbarpaare. Jede Stufe hier haelt noch
            # mindestens eine gelernte Nachbarschaft ein.
            # Ladder: only ever drop the weakest constraint. The old fallback
            # threw away ALL constraints when the choice was empty and drew any
            # tile of the target family -- that was the source of the
            # never-observed tile pairs. Every level here still honours at
            # least one learned adjacency.
            _zwischen = {}

            def beide():
                if "b" not in _zwischen:
                    _zwischen["b"] = schnitt(links, oben)
                return _zwischen["b"]

            def beide_fam():
                if "bf" not in _zwischen:
                    _zwischen["bf"] = nur_familie(beide(), target)
                return _zwischen["bf"]

            def mit_zukunft(paar):
                """Kandidaten, hinter denen es rechts und unten weitergeht."""
                if paar is None or not len(paar[0]):
                    return paar
                keys, gew = paar
                maske = np.ones(len(keys), dtype=bool)
                if x + 1 < w and (fest is None or fest[y, x + 1] < 0):
                    maske &= tm.hat_nachfolger(keys, "rechts",
                                               int(fam_field[y, x + 1]))
                if y + 1 < h and (fest is None or fest[y + 1, x] < 0):
                    maske &= tm.hat_nachfolger(keys, "unten",
                                               int(fam_field[y + 1, x]))
                return (keys[maske], gew[maske]) if maske.any() else None
            # Die Vorschau steht in JEDER Stufe vor allem anderen. Vorher
            # fiel sie in den Rueckfallstufen weg -- in rund 4 % der Zellen,
            # und genau dort entstanden 37 % aller Fehlpaare (Boden gegen
            # Uebergang). Eine feste Nachbarin laesst sich nicht mehr aendern,
            # die Familie schon.
            # The look-ahead comes before everything else in EVERY level.
            # Before it was dropped in the fallback levels -- in about 4 % of
            # cells, and exactly there 37 % of all bad pairs arose (ground
            # against transition). A fixed neighbour cannot be changed any
            # more, the family can.
            # Stufen erst berechnen, wenn sie gebraucht werden. Als Tupel
            # notiert wurden vorher ALLE vierzehn ausgewertet, obwohl die
            # erste in 84 % der Faelle trifft -- das kostete beim Malen ein
            # Vielfaches der noetigen Zeit.
            # Compute a level only when it is needed. Written as a tuple, all
            # fourteen were evaluated before, although the first one hits in
            # 84 % of cases -- while painting that cost a multiple of the time
            # actually required.
            # (Name, Berechnung, haelt die Familie ein). Das dritte Feld
            # ausdruecklich mitfuehren statt aus dem Namen zu raten -- die
            # Stufe "nur Vorschau, jede Familie" enthaelt das Wort Familie und
            # rutschte bei einer Namenspruefung faelschlich durch, obwohl sie
            # gerade die Familie fallen laesst.
            # (name, computation, honours the family). Carry the third field
            # explicitly instead of guessing from the name -- the level
            # "look-ahead only, any family" contains the word family and
            # slipped through a name check although it is the one dropping it.
            def gelockert(schwelle, mit_muster=True):
                """Beide Nachbarn bei groesserer Schwelle."""
                schluessel = f"g{schwelle}{mit_muster}"
                if schluessel not in _zwischen:
                    paar = None
                    nachbarn_da = False
                    for zelle, richtung in (((y, x - 1), "rechts"),
                                            ((y - 1, x), "unten")):
                        if zelle[0] < 0 or zelle[1] < 0:
                            continue
                        nachbarn_da = True
                        t = nur_platzierbar(tm.nachbarn_schwelle(
                            int(grid[zelle]), richtung, schwelle,
                            mit_muster=mit_muster))
                        paar = t if paar is None else schnitt(paar, t)
                    # Wenn es Nachbarn gibt, aber keine Kachel dazu passt, muss
                    # diese Stufe DURCHFALLEN. Vorher stand hier ein Rueckfall
                    # auf alle platzierbaren Kacheln -- also gar keine Bedingung
                    # mehr. Gemessen stammten dadurch 0 von 200 sichtbaren
                    # Bruechen aus der erlaubten Menge: sie entstanden alle in
                    # genau diesem Rueckfall. Nur ohne jede Nachbarin (linke
                    # obere Ecke) ist die freie Wahl richtig.
                    # If there are neighbours but no tile fits them, this level
                    # must FAIL. A fallback to all placeable tiles used to live
                    # here -- that is, no constraint at all. Measured, 0 of 200
                    # visible breaks came from the allowed set: they all arose in
                    # exactly this fallback. Only with no neighbour at all
                    # (top-left corner) is the free choice correct.
                    _zwischen[schluessel] = (
                        paar if nachbarn_da else alle_kacheln)
                return _zwischen[schluessel]

            # Die Leiter lockert jetzt die Schwelle, statt eine Nachbarin ganz
            # fallen zu lassen. Vorher hiess die unterste Stufe "nimm irgendeine
            # Kachel der Familie" -- an dieser Naht durfte damit alles stehen,
            # und genau dort blieben die sichtbaren Brueche uebrig. Mit der
            # Kantenregel gibt es 542 statt 21 Nachbarn, also braucht es das
            # Aufgeben nicht mehr: es reicht, die Naht etwas sichtbarer zu
            # erlauben.
            # The ladder now relaxes the threshold instead of dropping a
            # neighbour entirely. The bottom level used to mean "take any tile
            # of the family" -- anything was allowed at that seam, and that is
            # where the visible breaks remained. With the edge rule there are
            # 542 instead of 21 neighbours, so giving up is no longer necessary:
            # allowing the seam to be slightly more visible suffices.
            # Die Vorausschau zuerst -- sie kostet nur eine Tabellenabfrage und
            # erspart die Sackgasse, in der gar nichts mehr passt.
            # Look-ahead first -- it costs only a table lookup and avoids the
            # dead end in which nothing fits at all.
            # Die Familie ist unantastbar. Vorher liessen vier Stufen sie
            # fallen, sobald keine Kachel der Zielfamilie zu beiden Nachbarn
            # passte -- gemessen bekamen dadurch 505 Zellen je Karte den
            # falschen Boden: Erde mitten im Sand, und bei Bewuchs (nur 21
            # Kacheln, im Schnitt 16 gleichfarbige Nachbarn) wurden 205 Zellen
            # je Karte kurzerhand zu Sand. Wer Sand malt, will Sand.
            #
            # Notwendig wird das Aufgeben dadurch nicht: die letzte Stufe
            # waehlt ohnehin innerhalb der Zielfamilie die Kachel mit der
            # unauffaelligsten Naht.
            #
            # The family is inviolable. Four levels used to drop it as soon as
            # no tile of the target family fitted both neighbours -- measured,
            # 505 cells per map got the wrong ground that way: dirt in the
            # middle of sand, and vegetation (only 21 tiles, 16 same-family
            # neighbours on average) simply turned into sand for 205 cells per
            # map. Whoever paints sand wants sand.
            #
            # Giving up is not necessary for it: the last level picks the tile
            # with the least noticeable seam within the target family anyway.
            leiter = (
                ("streng+Familie+Zukunft",
                 lambda: mit_zukunft(passt_voraus(beide_fam())), True),
                ("streng+Familie", lambda: passt_voraus(beide_fam()), True),
                ("gelockert+Familie",
                 lambda: passt_voraus(nur_familie(gelockert(45.0), target)),
                 True),
                ("weit+Familie",
                 lambda: nur_familie(gelockert(60.0), target), True),
            )
            for name, stufe, _haelt_familie in leiter:
                wahl = stufe()
                if wahl is not None and len(wahl[0]):
                    keys, weights = wahl
                    stufen[name] += 1
                    break
            else:
                # Auch hier nicht raten: von den Kacheln der Zielfamilie die
                # nehmen, deren schlechteste Naht am wenigsten auffaellt.
                # No guessing here either: of the target family's tiles take
                # the one whose worst seam is least noticeable.
                stufen["beste Naeherung"] += 1
                kand = _frei[tm.family_of[_frei] == target]
                if not len(kand):
                    kand = _frei
                schlimmste = np.zeros(len(kand))
                if x > 0:
                    schlimmste = np.maximum(schlimmste, tm.kanten_abstand(
                        int(grid[y, x - 1]), "rechts")[kand])
                if y > 0:
                    schlimmste = np.maximum(schlimmste, tm.kanten_abstand(
                        int(grid[y - 1, x]), "unten")[kand])
                grid[y, x] = int(kand[int(np.argmin(schlimmste))])
                continue
            probs = weights / weights.sum()
            grid[y, x] = int(rng.choice(keys, p=probs))
    _sample_tiles.stufen = stufen
    return grid
