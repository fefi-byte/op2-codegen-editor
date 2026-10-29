"""Malebenen: Absicht statt Kacheln.

Der alte Gelaende-Tab liess einzelne Kacheln stempeln. Das ist die falsche
Ebene: welche Kachel an einer Klippenkante richtig ist, haengt vom Umfeld ab,
und wer das von Hand setzt, kaempft gegen die Kachelgrammatik statt zu
gestalten.

Hier wird stattdessen die ABSICHT gemalt, in zwei Ebenen neben der Karte:

    hoehe     0 = Tiefland, 1 = Hochland  -> Klippen entstehen an der Grenze
    familie   Erde, Fels, Sand, Bewuchs, Schnee

Aus diesen beiden Ebenen rechnet `synth_region` die Kacheln aus -- Zelltyp aus
der Form, Kachel aus dem gelernten Umfeld, dazu die Nachbarschaftsbedingung.
Es sind dieselben zwei Felder, die der Generator benutzt: wuerfeln und dann
uebermalen, was nicht passt.

Paint layers: intent instead of tiles. The old terrain tab stamped individual
tiles, which is the wrong level -- which tile is right on a cliff edge depends
on the surroundings, and placing that by hand means fighting the tile grammar
instead of designing. Here the INTENT is painted in two layers beside the map,
and `synth_region` derives the tiles from them. They are the same two fields
the generator uses, so you can roll a map and then paint over what does not fit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_MAPVIEW = Path(__file__).resolve().parents[2] / "mapview"
if str(_MAPVIEW) not in sys.path:
    sys.path.insert(0, str(_MAPVIEW))

import celltypes    # noqa: E402
import mapgen       # noqa: E402
import shapegen     # noqa: E402

import klippe_algo  # noqa: E402

# Pinselarten. `tief` senkt ab, die naechsten setzen das Biom, der Rest sind
# Sonderflaechen.
#
# Einen Hochland-Pinsel gibt es nicht mehr. Hochland aus einer gemalten Flaeche
# abzuleiten war der alte Weg, an dem die Klippen gescheitert sind (siehe
# `docs/klippen-stand.md`, 1.): Flaeche -> Hoehenfeld -> Zelltypband -> Kachel,
# und nach drei Ableitungen war nicht mehr bekannt, wo die Wand gemeint war.
# Hochland entsteht jetzt dort, wo eine gezeichnete Klippe es setzt. `tief`
# bleibt als Radierer -- es ist der Weg, eine gesetzte Klippe wieder loszuwerden.
#
# Brush kinds: `tief` lowers, the next ones set the biome, the rest are special
# areas. There is no highland brush any more -- deriving highland from a painted
# area was the old path the cliffs failed on; highland now appears where a drawn
# cliff puts it. `tief` stays as the eraser for placed cliffs.
B_TIEF = "tief"
B_ERDE = "mud"
B_FELS = "roc"
B_SAND = "san"
B_BEWUCHS = "veg"
B_SCHNEE = "sno"
B_VULKAN = "vulkan"
B_KLIPPE = "klippe"
B_LAVA = "lava"
B_BAU = "bau"

FAMILIEN_PINSEL = (B_ERDE, B_FELS, B_SAND, B_BEWUCHS, B_SCHNEE)
BRUSHES = (B_TIEF, B_ERDE, B_FELS, B_SAND, B_BEWUCHS, B_SCHNEE,
           B_VULKAN, B_LAVA, B_BAU)

# Wie oft der Umriss geglaettet wird. 0 = gar nicht.
# Gemessen: drei Runden aendern das Bild kaum, kosten aber Zellen, die der
# Nutzer bewusst gemalt hat (589 statt 593 rein). Die sichtbare Verbesserung
# kam von der breiteren Mischzone aussen, nicht von der Glaettung.
# How often the outline is smoothed; 0 = not at all. Measured: three passes
# barely change the picture but cost cells the user deliberately painted (589
# instead of 593 pure). The visible improvement came from the wider blend zone
# outside, not from the smoothing.
GLAETT_RUNDEN = 1

# Wie weit ueber den Pinselrand hinaus neu gerechnet wird. Das Uebergangsband
# ist eine Zelle breit. Zwei ist das Minimum: der festgenagelte Aussenring
# des Bereichs muss AUSSERHALB des Strichs liegen, sonst nagelt er gemalte
# Zellen auf ihre alten Kacheln fest und der Pinsel wirkt gar nicht mehr.
# Vorher standen hier 6, damit auch ein Klippenband von drei Zellen komplett
# neu entsteht; sichtbar war das als Aenderung noch fuenf Kacheln neben dem
# Strich, obwohl dort gar nichts gemalt wurde.
# How far beyond the brush the tiles are recomputed. The transition band is one
# cell wide. Two is the minimum: the pinned outer ring of the region has to
# lie OUTSIDE the stroke, otherwise it pins painted cells to their old tiles
# and the brush stops having any effect. It
# used to be 6 so that a three-cell cliff band would be rebuilt completely;
# visibly that changed tiles five cells beside the stroke although nothing was
# painted there.
RAND = 3

# Wie weit um eine alte Uebergangskachel herum ebenfalls neu gerechnet wird.
# How far around an old transition tile the tiles are recomputed as well.
UEBERGANG_RAND = 2

CLIFF_CELLS = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
               celltypes.CLIFFS_LOW_SIDE)


class PaintLayers:
    """Hoehe und Biom fuer die geladene Karte."""

    def __init__(self, op2map, seed: int = 1):
        self.map = op2map
        self.tm = mapgen.model()
        self.rng = np.random.default_rng(seed)
        h, w = op2map.height, op2map.width
        self.hoehe = np.zeros((h, w), dtype=np.int8)
        self.familie = np.zeros((h, w), dtype=np.int16)
        self.lava = np.zeros((h, w), dtype=bool)
        self.bau = np.zeros((h, w), dtype=bool)
        self.vulkane: list[tuple[int, int]] = []
        # Zellen des letzten Strichs -- sie bleiben reiner Boden.
        # Cells of the last stroke -- they stay pure ground.
        self.gemalt = np.zeros((h, w), dtype=bool)
        # Offene Enden gesetzter Klippen -- daran kann weitergezeichnet werden.
        # Sie werden ausdruecklich gefuehrt statt aus der Karte gesucht: ein
        # ueberlappter Block ist teilweise ueberschrieben und per Mustersuche
        # nicht mehr auffindbar. Ein gemerkter Punkt bleibt auffindbar.
        # Open ends of placed cliffs, kept explicitly rather than searched for
        # in the map: an overlapped block is partly overwritten and no longer
        # matches, while a remembered point stays findable.
        self.klippen_enden: list[tuple[int, int]] = []
        self._aus_karte()

    # ------------------------------------------------------------------
    def _aus_karte(self) -> None:
        """Ebenen aus der geladenen Karte zurueckgewinnen.

        Damit laesst sich auch eine Originalkarte uebermalen, nicht nur eine
        selbst erzeugte: Hochland steht in den Zelltypen, das Biom in der
        Kachelfamilie.

        Recover the layers from the loaded map, so an original map can be
        painted over too, not just a generated one: the highland is in the cell
        types, the biome in the tile family.
        """
        h, w = self.hoehe.shape
        kacheln = np.array([[self.map.tile_mapping_index(x, y) for x in range(w)]
                            for y in range(h)], dtype=np.int32)
        zellen = np.array([[self.map.cell_type(x, y) for x in range(w)]
                           for y in range(h)], dtype=np.int32)
        self.hoehe = shapegen.height_field_from_cells(zellen)
        fam = self.tm.family_of[kacheln]
        # Unbekannte Kacheln der haeufigsten Familie zuschlagen, sonst haette
        # der Pinsel dort keinen definierten Untergrund.
        # Assign unknown tiles to the most common family, otherwise the brush
        # would have no defined ground there.
        bekannt = (fam >= 0) & (fam < len(self.tm.families))
        gueltig = fam[bekannt]
        vorgabe = int(np.bincount(gueltig).argmax()) if len(gueltig) else 0
        # Uebergangskacheln haben keine eigene Familie. Sie pauschal der
        # haeufigsten Familie der Karte zuzuschlagen war falsch: eine
        # Fels-Sand-Grenze besteht aus `santoroc`-Kacheln, und die wurden damit
        # allesamt zu Erde. Malte man daneben, tauchte genau dort ein
        # Erdstreifen auf, obwohl weit und breit keine Erde lag.
        #
        # Richtig ist die Mehrheit der Nachbarn: eine Uebergangskachel liegt
        # zwischen ihren beiden Boeden, also gehoert sie zu einem davon.
        #
        # Transition tiles have no family of their own. Assigning them wholesale
        # to the map's most common family was wrong: a rock-sand border consists
        # of `santoroc` tiles, and all of them thereby became dirt. Painting next
        # to it made a dirt strip appear exactly there although no dirt was
        # anywhere near.
        #
        # The majority of the neighbours is right: a transition tile lies between
        # its two grounds, so it belongs to one of them.
        fam = np.where(bekannt, fam, -1)
        for _ in range(4):
            offen = fam < 0
            if not offen.any():
                break
            zaehler = np.zeros((len(self.tm.families),) + fam.shape, dtype=np.int16)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                v = np.roll(np.roll(fam, dy, axis=0), dx, axis=1)
                for k in range(len(self.tm.families)):
                    zaehler[k] += (v == k)
            beste = np.argmax(zaehler, axis=0)
            hat_nachbar = zaehler.max(axis=0) > 0
            fam = np.where(offen & hat_nachbar, beste, fam)
        fam = np.where(fam < 0, vorgabe, fam)
        self.familie = fam.astype(np.int16)

    # ------------------------------------------------------------------
    def strich_beenden(self) -> tuple[int, int, int, int] | None:
        """Schutz aufheben und den Bereich des Strichs zurueckgeben.

        Waehrend des Strichs sind alle beruehrten Zellen geschuetzt, damit der
        Pinsel wirklich reinen Boden malt. Genau dieser Schutz verhindert aber
        auch eine Uebergangskachel auf der INNENSEITE der neuen Grenze --
        gemessen bekamen 76 von 76 geschuetzten Grenzzellen keinen Uebergang,
        waehrend aussen 56 % einen bekamen. Eine einseitig geblendete Grenze
        ist genau die harte Kante.

        Deshalb gibt der Strichabschluss seinen Bereich zurueck: der Aufrufer
        rechnet ihn ohne Schutz noch einmal, und dann darf der Rand nachgeben.
        Die Familie bleibt dabei unantastbar, es aendern sich nur die Kacheln.

        Release the protection and return the area of the stroke. While drawing,
        every touched cell is protected so the brush really paints pure ground.
        But that same protection also prevents a transition tile on the INSIDE
        of the new border -- measured, 76 of 76 protected border cells got no
        transition while 56 % of the outer ones did. A border blended on one
        side only is exactly the hard edge.

        So the stroke end returns its area: the caller recomputes it without
        protection, and then the rim may give way. The family stays inviolable
        there; only the tiles change.
        """
        if not self.gemalt.any():
            return None
        ys, xs = np.nonzero(self.gemalt)
        bereich = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        self.gemalt[:, :] = False
        return bereich

    def klippe_zeichnen(self, punkte, hoch_seite: str
                        ) -> list[tuple[int, int, int, int]]:
        """Eine gezeichnete Klippenlinie setzen -> [(x, y, Kachel, Zelltyp)].

        Anders als der Flaechenpinsel wird hier die KANTE angegeben, nicht das
        Hochland: eine Punktfolge und die Seite, auf der es hoch geht. Damit
        steht fest, was die Bloecke brauchen, und nichts muss aus einer
        gemalten Flaeche zurueckgerechnet werden -- daran war der Flaechenweg
        gescheitert.

        Die Hoehenebene wird anschliessend nachgezogen, damit Overlay und
        spaetere Striche wissen, wo jetzt Hochland liegt.

        Unlike the area brush this takes the EDGE, not the highland: a sequence
        of points and the side where the ground rises. The height layer is
        updated afterwards so the overlay and later strokes know where the
        highland now is.
        """
        if len(punkte) < 2:
            return []
        h, w = self.hoehe.shape
        gitter = np.array([[self.map.tile_mapping_index(x, y)
                            for x in range(w)] for y in range(h)],
                          dtype=np.int32)
        vorher = gitter.copy()
        # Die Familie am ersten Punkt bestimmt den Kachelsatz der Wand.
        # The family at the first point picks the wall's tile set.
        x0, y0 = punkte[0]
        fi = int(self.familie[max(0, min(h - 1, y0)), max(0, min(w - 1, x0))])
        familie = (self.tm.families[fi] if 0 <= fi < len(self.tm.families)
                   else "san")
        maske, zellen = self._klippe_belegen(gitter, list(punkte), hoch_seite,
                                             familie)
        if not maske.any():
            return []
        aenderungen = []
        for y, x in zip(*np.nonzero(gitter != vorher)):
            kachel = int(gitter[y, x])
            zt = int(zellen[y, x])
            aenderungen.append((int(x), int(y), kachel,
                                zt if zt >= 0
                                else celltypes.default_cell_type(kachel)))
        self._hoehe_aus_klippe(maske, zellen)
        # Enden merken; ein geschlossener Zug hat keine.
        # Remember the ends; a closed figure has none.
        if not (len(punkte) > 2 and tuple(punkte[0]) == tuple(punkte[-1])):
            for p in (punkte[0], punkte[-1]):
                if tuple(p) not in self.klippen_enden:
                    self.klippen_enden.append((int(p[0]), int(p[1])))
        return aenderungen

    def _klippe_belegen(self, gitter, punkte, hoch_seite, familie):
        """Die Kante mit dem Gelaende-Loeser (`klippe_algo`) belegen.

        Der Blockweg ist entfernt. Traegt die Familie keine Kantenzuordnung
        (sno: neun Klippenkacheln), bleibt die Maske leer -- der Aufrufer
        meldet dann "keine Klippe gesetzt", statt still etwas anderes zu tun.

        Cover the edge with the terrain solver. The block path is gone; a
        family without an edge assignment yields an empty mask.
        """
        if not klippe_algo.verfuegbar(self.tm, familie):
            return (np.zeros(gitter.shape, dtype=bool),
                    np.full(gitter.shape, -1, dtype=np.int16))
        return klippe_algo.klippe_aus_linie(gitter, punkte, hoch_seite,
                                            self.tm, self.rng, familie)

    def klippen_anker(self, x: int, y: int, umkreis: int = 5, ausser=()):
        """Naechstes offenes Klippenende im Umkreis -> (x, y) oder None.

        Die selbst gezeichneten Enden stehen kachelgenau, die aus der Karte
        abgeleiteten sitzen auf einem Dreierraster und verfehlen den
        tatsaechlichen Endpunkt um bis zu zwei Kacheln. Deshalb gewinnen die
        gemerkten, sobald ueberhaupt einer in Reichweite ist -- **nicht** der
        naechstliegende von beiden.

        Genau das stand hier zwar als Absicht im Kommentar, war aber nicht so
        gebaut: die Listenreihenfolge half nichts, weil `min` nach Abstand
        sortiert. Gemessen an einer Wand mit Ende bei (26,16) rastete ein Klick
        auf (29,16) auf den abgeleiteten Ring (28,16) ein -- zwei Kacheln hinter
        dem Ende, und die Fortsetzung setzte am falschen Block an.

        The self-drawn ends are tile-exact while the map-derived ones sit on a
        three-cell grid and miss the real end by up to two tiles, so a remembered
        one wins as soon as any is in range -- NOT whichever is nearest. That was
        the stated intent here but not what was built: list order did not help,
        because `min` sorts by distance. Measured on a wall ending at (26,16), a
        click at (29,16) snapped to the derived ring (28,16) -- two tiles past the
        end, and the continuation attached to the wrong block.
        """
        weg = {tuple(p) for p in ausser}

        def naechster(punkte):
            nah = [(abs(ax - x) + abs(ay - y), ax, ay) for ax, ay in punkte
                   if (ax, ay) not in weg
                   and abs(ax - x) <= umkreis and abs(ay - y) <= umkreis]
            if not nah:
                return None
            _d, ax, ay = min(nah)
            return ax, ay

        # ZUERST `offene_enden` -- der Aufruf wirft die gemerkten Enden weg, an
        # denen keine Klippe mehr steht. Ohne ihn liest die Zeile darunter die
        # rohe Liste, und ein wegradiertes Ende rastet weiter ein.
        # `offene_enden` FIRST: that call discards remembered ends with no cliff
        # left at them. Without it the line below reads the raw list and an
        # erased end keeps snapping.
        abgeleitet = self.offene_enden()
        return (naechster(self.klippen_enden)
                or naechster(p for p in abgeleitet
                             if p not in self.klippen_enden)
                or self.klippen_wand_punkt(x, y))

    def klippen_wand_punkt(self, x: int, y: int, umkreis: int = 3):
        """Naechste Klippenzelle im Umkreis -> (x, y) oder None.

        Damit laesst sich auch MITTEN auf eine Wand zielen, nicht nur auf ihre
        Enden. Ein eigener Ring je Wandstueck kam nicht in Frage: gemessen waeren
        das auf `cm04` 1017 statt 51 Ringe, auf `cm02` 804 statt 34 -- Faktor 16
        bis 24, und die Karte verschwindet darunter. Stattdessen zeigt der Editor
        EINEN Ring unter dem Zeiger, und der kommt von hier.

        Gefragt werden die Zelltypen in einem kleinen Fenster, nicht das
        Kachelgitter: das ist billig genug fuer jede Mausbewegung.

        Nearest cliff cell within the radius, so one can aim at the MIDDLE of a
        wall, not only at its ends. A ring per wall segment was no option --
        measured, `cm04` would show 1017 rings instead of 51, `cm02` 804 instead
        of 34, and the map disappears beneath them. The editor shows ONE ring
        under the cursor instead, fed from here. Cell types in a small window are
        asked rather than the tile grid: cheap enough for every mouse move.
        """
        h, w = self.hoehe.shape
        nah = []
        for py in range(max(0, y - umkreis), min(h, y + umkreis + 1)):
            for px in range(max(0, x - umkreis), min(w, x + umkreis + 1)):
                if self.map.cell_type(px, py) in CLIFF_CELLS:
                    nah.append((abs(px - x) + abs(py - y), px, py))
        if not nah:
            return None
        _d, px, py = min(nah)
        return px, py

    def offene_enden(self) -> list[tuple[int, int]]:
        """Enden aller Klippen der KARTE, nicht nur der selbst gezeichneten.

        Aus der Karte abgeleitet statt gemerkt, und das aus zwei Gruenden:
        Klippen einer geladenen oder erzeugten Karte bekommen so ebenfalls
        Ankerpunkte, und ein Rueckgaengig laesst die Ringe von selbst
        verschwinden -- eine gemerkte Liste wuesste davon nichts.

        Ein Ende ist eine Klippenzelle, deren Klippenumgebung in nur EINE
        Richtung weitergeht. Ein Stueck mittendrin hat zwei, eine Ecke auch.

        Ends of ALL the map's cliffs, derived from the map rather than
        remembered: cliffs of a loaded or generated map get anchors too, and an
        undo makes the rings disappear by itself. An end is a cliff cell whose
        cliff surroundings continue in only ONE direction.
        """
        # Fingerabdruck der Karte. Die Stichprobe allein reicht nicht: eine
        # frisch gezeichnete Klippe traf keine der abgetasteten Kacheln, und
        # der Zwischenspeicher gab die Liste von davor zurueck -- das Einrasten
        # fand das neue Ende dann nicht.
        #
        # Deshalb dicht abtasten. Bei Schrittweite 97 trifft ein oertlicher
        # Strich von rund 60 Kacheln die Stichprobe nur mit etwa jeder zweiten
        # Kachel gar nicht -- dann bleibt der Zwischenspeicher stehen und mit
        # ihm die toten Anker. Schrittweite 17 kostet ein paar hundert
        # Additionen und ist immer noch ein Vielfaches billiger als der
        # Zelltyp-Durchlauf darunter.
        #
        # Map fingerprint. The sample alone is not enough, and it has to be
        # dense: at stride 97 a local stroke of some 60 tiles misses the sample
        # about half the time, leaving the cache -- and the dead anchors with it
        # -- in place. Stride 17 costs a few hundred additions and is still far
        # cheaper than the cell-type sweep below.
        stand = (int(self.map.width), int(self.map.height),
                 len(self.klippen_enden),
                 sum(int(self.map.tiles[i])
                     for i in range(0, len(self.map.tiles), 17)))
        if getattr(self, "_enden_stand", None) == stand:
            return self._enden
        h, w = self.hoehe.shape
        zt = np.array([[self.map.cell_type(x, y) for x in range(w)]
                       for y in range(h)], dtype=np.int32)
        klippe = np.isin(zt, CLIFF_CELLS)
        enden: list[tuple[int, int]] = []
        if klippe.any():
            # Grob rastern: je 3x3-Feld eine Marke, sonst meldet jede
            # ausgefranste Kante ein Ende.
            # Coarse 3x3 grid, otherwise every frayed edge reports an end.
            gh, gw = (h + 2) // 3, (w + 2) // 3
            grob = np.zeros((gh, gw), dtype=bool)
            for gy in range(gh):
                for gx in range(gw):
                    grob[gy, gx] = klippe[gy * 3:gy * 3 + 3,
                                          gx * 3:gx * 3 + 3].any()
            for gy, gx in np.argwhere(grob):
                n = sum(1 for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0))
                        if 0 <= gy + dy < gh and 0 <= gx + dx < gw
                        and grob[gy + dy, gx + dx])
                if n == 1:
                    enden.append((int(gx) * 3 + 1, int(gy) * 3 + 1))
        # Ein gemerktes Ende, an dem keine Klippe mehr steht, wird WEGGEWORFEN --
        # nicht nur nicht angezeigt. Es blieb bisher in der Liste liegen und
        # rastete weiter ein, obwohl dort nichts mehr war: `offene_enden` prueft
        # auf eine Klippe im Umfeld, `klippen_anker` griff aber direkt auf die
        # rohe Liste zu. Gemessen: Klippe gezeichnet, mit Tiefland wegradiert --
        # null Klippenzellen, null Ringe, und ein Klick daneben rastete trotzdem
        # auf das alte Ende ein. Seit gemerkte Enden Vorrang haben (7.4) gewann
        # dieser tote Punkt sogar gegen jeden echten in der Naehe.
        #
        # A remembered end with no cliff left at it is DISCARDED, not merely
        # hidden. It used to stay in the list and keep snapping although nothing
        # was there: `offene_enden` checked for a nearby cliff, but
        # `klippen_anker` read the raw list. Measured: draw a cliff, erase it
        # with lowland -- zero cliff cells, zero rings, and a click nearby still
        # snapped to the old end. Since remembered ends take priority (7.4) that
        # dead point even beat every live one nearby.
        def lebt(ax, ay) -> bool:
            return bool(klippe[max(0, ay - 2):ay + 3, max(0, ax - 2):ax + 3].any())

        self.klippen_enden = [(ax, ay) for ax, ay in self.klippen_enden
                              if lebt(ax, ay)]
        for ax, ay in self.klippen_enden:
            if not any((ax, ay) == (bx, by) for bx, by in enden):
                enden.append((ax, ay))
        # Der Fingerabdruck traegt die Laenge der Liste -- nach dem Aufraeumen
        # also neu bilden, sonst rechnet der naechste Aufruf alles noch einmal.
        # The fingerprint carries the list length, so rebuild it after pruning.
        stand = (stand[0], stand[1], len(self.klippen_enden), stand[3])
        self._enden, self._enden_stand = enden, stand
        return enden

    def _hoehe_aus_klippe(self, maske, zellen) -> None:
        """Hochland aus dem Zelltypfeld der gesetzten Bloecke uebernehmen."""
        hoch = (zellen == celltypes.CLIFFS_HIGH_SIDE) & maske
        self.hoehe[hoch] = 1

    def male(self, brush: str, zellen) -> tuple[int, int, int, int] | None:
        """Pinselstrich in die Ebenen eintragen, Rechteck zurueckgeben."""
        if not zellen:
            return None
        h, w = self.hoehe.shape
        # Nur die Zellen melden, die sich WIRKLICH geaendert haben. Beim
        # Ziehen ueberlappen sich die Pinselabdruecke stark -- neu ist nur eine
        # schmale Sichel. Den ganzen Abdruck neu zu rechnen kostet ein
        # Vielfaches und ist der Unterschied zwischen live und ruckeln.
        # Report only the cells that ACTUALLY changed. While dragging the brush
        # footprints overlap heavily -- only a narrow crescent is new.
        # Recomputing the whole footprint costs a multiple and is the
        # difference between live and stuttering.
        xs: list[int] = []
        ys: list[int] = []

        def gemerkt(x, y):
            xs.append(x)
            ys.append(y)

        for x, y in zellen:
            if not (0 <= x < w and 0 <= y < h):
                continue
            # Geschuetzt ist jede BERUEHRTE Zelle, nicht nur die veraenderte.
            # Sonst bleibt eine Zelle ungeschuetzt, deren Ebene schon stimmte,
            # deren Kachel aber noch eine Mischkachel war -- und genau die
            # bekommt dann wieder den falschen Boden. Der neu zu rechnende
            # Bereich richtet sich weiterhin nur nach den Aenderungen, sonst
            # waere das Live-Malen wieder langsam.
            # Protected is every TOUCHED cell, not only the changed one.
            # Otherwise a cell whose layer was already right but whose tile was
            # still a blend tile stays unprotected -- and that is exactly the
            # one that gets the wrong ground again. The region to recompute
            # still follows the changes only, otherwise live painting would be
            # slow again.
            if brush in FAMILIEN_PINSEL or brush in (B_TIEF, B_BAU):
                self.gemalt[y, x] = True
            if brush == B_TIEF:
                if self.hoehe[y, x]:
                    self.hoehe[y, x] = 0
                    gemerkt(x, y)
            elif brush in FAMILIEN_PINSEL:
                if brush in self.tm.families:
                    neu_fam = self.tm.families.index(brush)
                    if self.familie[y, x] != neu_fam:
                        self.familie[y, x] = neu_fam
                        gemerkt(x, y)
            elif brush == B_LAVA:
                if not self.lava[y, x]:
                    self.lava[y, x] = True
                    gemerkt(x, y)
            elif brush == B_BAU:
                # Baugelaende: eben, ohne Klippen -- darauf soll gebaut werden.
                # Building ground: flat, no cliffs -- you build on it.
                if not self.bau[y, x] or self.hoehe[y, x]:
                    self.bau[y, x] = True
                    self.hoehe[y, x] = 0
                    gemerkt(x, y)
        if brush == B_VULKAN:
            mx, my = int(np.mean(xs)), int(np.mean(ys))
            self.vulkane.append((mx, my))
            fels = self.tm.families.index("roc") if "roc" in self.tm.families else 0
            ys_, xs_ = np.ogrid[:h, :w]
            umfeld = ((xs_ - mx) ** 2 + (ys_ - my) ** 2) <= 12 * 12
            self.familie[umfeld] = fels
            self.hoehe[umfeld] = 0
            return (max(0, mx - 14), max(0, my - 14),
                    min(w - 1, mx + 14), min(h - 1, my + 14))
        if not xs:
            return None
        rechteck = (max(0, min(xs)), max(0, min(ys)),
                    min(w - 1, max(xs)), min(h - 1, max(ys)))
        if brush in FAMILIEN_PINSEL or brush == B_TIEF:
            self._umriss_glaetten(brush, rechteck)
        return rechteck

    def _umriss_glaetten(self, brush: str, rechteck) -> None:
        """Zacken und Kerben aus dem gemalten Umriss nehmen.

        Der Pinsel rastert einen Kreis Zelle fuer Zelle; an der Kante bleiben
        einzelne Vorspruenge und Kerben stehen, die man deutlich sieht. Ein
        Mehrheitsentscheid ueber das 3x3-Umfeld raeumt beides weg.

        Ein Zacken IST eine gemalte Zelle -- die Glaettung muss sie also
        entfernen duerfen. Nur der Kern des Strichs bleibt unantastbar, damit
        ein kleiner Pinsel nicht ganz wegerodiert.

        Take spikes and notches out of the painted outline. The brush
        rasterises a circle cell by cell, leaving visible protrusions and
        notches along the edge; a majority vote over the 3x3 neighbourhood
        removes both. A spike IS a painted cell, so the smoothing has to be
        allowed to remove it -- only the core of the stroke stays untouchable
        so a small brush is not eroded away entirely.
        """
        if int(self.gemalt.sum()) < 9:
            return                      # zu klein zum Glaetten
        for _ in range(GLAETT_RUNDEN):
            self._eine_glaettung(brush, rechteck)

    def _eine_glaettung(self, brush: str, rechteck) -> None:
        h, w = self.hoehe.shape
        x0 = max(1, rechteck[0] - 2)
        y0 = max(1, rechteck[1] - 2)
        x1 = min(w - 2, rechteck[2] + 2)
        y1 = min(h - 2, rechteck[3] + 2)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        feld = self.hoehe if brush == B_TIEF else self.familie
        wert = 0 if brush == B_TIEF else self.tm.families.index(brush)

        aus = feld[y0 - 1:y1 + 2, x0 - 1:x1 + 2]
        innen = (aus == wert)
        nachbarn = np.zeros(innen.shape, dtype=np.int16)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nachbarn += np.roll(np.roll(innen, dy, axis=0), dx, axis=1)
        mehrheit = nachbarn[1:-1, 1:-1] >= 5

        # Kern des Strichs: Zellen, deren vier Nachbarn ebenfalls gemalt sind.
        # Core of the stroke: cells whose four neighbours are painted too.
        gem = self.gemalt[y0 - 1:y1 + 2, x0 - 1:x1 + 2]
        kern = gem[1:-1, 1:-1].copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            kern &= np.roll(np.roll(gem, dy, axis=0), dx, axis=1)[1:-1, 1:-1]

        ziel = feld[y0:y1 + 1, x0:x1 + 1]
        gemalt_hier = self.gemalt[y0:y1 + 1, x0:x1 + 1]
        # Zacken wegnehmen: gemalt, aber ohne Mehrheit und nicht im Kern.
        # Remove spikes: painted, but without a majority and not in the core.
        haeufigste = self._haeufigste_umgebung(feld, x0, y0, x1, y1, wert)
        weg = gemalt_hier & ~mehrheit & ~kern
        ziel[weg] = haeufigste[weg]
        gemalt_hier[weg] = False
        # Kerben fuellen: nicht gemalt, aber ringsum Mehrheit.
        # Fill notches: not painted, but a majority all around.
        dazu = ~gemalt_hier & mehrheit
        ziel[dazu] = wert
        gemalt_hier[dazu] = True

    @staticmethod
    def _haeufigste_umgebung(feld, x0, y0, x1, y1, ausser):
        """Haeufigster Nachbarwert je Zelle, ohne den eigenen."""
        aus = feld[y0 - 1:y1 + 2, x0 - 1:x1 + 2]
        werte = np.unique(aus)
        werte = werte[werte != ausser]
        if not len(werte):
            return np.full((y1 - y0 + 1, x1 - x0 + 1), ausser, dtype=feld.dtype)
        beste = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.int16)
        bestzahl = np.zeros(beste.shape, dtype=np.int16)
        for v in werte:
            ist = (aus == v)
            zahl = np.zeros(ist.shape, dtype=np.int16)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    zahl += np.roll(np.roll(ist, dy, axis=0), dx, axis=1)
            z = zahl[1:-1, 1:-1]
            besser = z > bestzahl
            beste[besser] = v
            bestzahl[besser] = z[besser]
        return beste.astype(feld.dtype)

    # ------------------------------------------------------------------
    def synth_region(self, rechteck) -> list[tuple[int, int, int, int]]:
        """Kacheln im bemalten Bereich neu ableiten -> [(x, y, kachel, zelltyp)].

        Benutzt dieselbe Kette wie der Generator: Uebergangsband an den
        Bodengrenzen gemeinsam aufloesen, dann den Boden drumherum sampeln,
        zuletzt die Klippen. Der aeussere Ring des Bereichs wird auf die
        vorhandenen Kacheln festgenagelt -- so faedelt sich das Neue in das
        Bestehende ein, statt an der Bereichsgrenze eine Naht zu hinterlassen.

        Uses the same chain as the generator: solve the transition band along
        the ground borders jointly, then sample the ground around it, cliffs
        last. The outer ring of the region is pinned to the existing tiles, so
        the new content threads into what is already there instead of leaving a
        seam at the region border.
        """
        h, w = self.hoehe.shape
        x0 = max(0, rechteck[0] - RAND)
        y0 = max(0, rechteck[1] - RAND)
        x1 = min(w - 1, rechteck[2] + RAND)
        y1 = min(h - 1, rechteck[3] + RAND)
        bh, bw = y1 - y0 + 1, x1 - x0 + 1
        if bh < 3 or bw < 3:
            return []

        # Erst glaetten, dann Kacheln waehlen -- genau die Reihenfolge, die der
        # Generator benutzt. Ohne das wird die Pinselform 1:1 uebernommen: ein
        # gemaltes Rechteck bleibt ein Rechteck mit rechten Winkeln, und seine
        # Kante hat nichts, woran ein Uebergangsband ansetzen koennte.
        #
        # Ein Mehrheitsfilter mit Radius 1 laesst grosse Flaechen stehen und
        # rundet nur Ecken und Einzelzacken ab -- die gemalte Absicht bleibt
        # also erhalten, sie bekommt nur einen natuerlichen Umriss.
        #
        # Smooth first, then choose tiles -- exactly the order the generator
        # uses. Without it the brush shape is taken over one to one: a painted
        # rectangle stays a rectangle with right angles, and its edge has nothing
        # for a transition band to attach to. A majority filter of radius 1
        # leaves large areas untouched and only rounds corners and single jags,
        # so the painted intent survives and merely gets a natural outline.
        if GLAETT_RUNDEN > 0:
            geglaettet = mapgen._smooth_families(
                self.familie[y0:y1 + 1, x0:x1 + 1].astype(np.int16),
                GLAETT_RUNDEN, radius=1)
            self.familie[y0:y1 + 1, x0:x1 + 1] = geglaettet
        fam = self.familie[y0:y1 + 1, x0:x1 + 1].astype(np.int16)
        H = self.hoehe[y0:y1 + 1, x0:x1 + 1].astype(np.int8)
        alt = np.array([[self.map.tile_mapping_index(x, y)
                         for x in range(x0, x1 + 1)]
                        for y in range(y0, y1 + 1)], dtype=np.int32)

        # Aussenring festnageln: er verbindet den neuen Bereich mit dem, was
        # schon auf der Karte liegt.
        # Pin the outer ring: it ties the new region to what is already there.
        fest = np.full((bh, bw), -1, dtype=np.int32)
        fest[0, :] = alt[0, :]
        fest[-1, :] = alt[-1, :]
        fest[:, 0] = alt[:, 0]
        fest[:, -1] = alt[:, -1]
        # Uebergangskacheln nie festnageln, auch nicht im Aussenring. Sie
        # gehoeren zu einer Grenze, die durch den Pinselstrich verschoben oder
        # verschwunden sein kann -- bleiben sie stehen, zeigt der Rand des neu
        # gerechneten Bereichs noch die alte Grenze. Zusaetzlich die zwei
        # Reihen dahinter freigeben, damit ein Band auch dann ganz neu entsteht,
        # wenn es breiter als eine Kachel ist.
        # Never pin transition tiles, not even in the outer ring. They belong to
        # a border that the brush stroke may have moved or removed -- if they
        # stay, the edge of the recomputed region still shows the old border.
        # Free the two rows behind it as well so a band is rebuilt completely
        # even when it is wider than one tile.
        ist_ueb = self.tm.ist_uebergang[alt]
        frei = ist_ueb.copy()
        for _ in range(UEBERGANG_RAND):
            gewachsen = frei.copy()
            gewachsen[1:, :] |= frei[:-1, :]
            gewachsen[:-1, :] |= frei[1:, :]
            gewachsen[:, 1:] |= frei[:, :-1]
            gewachsen[:, :-1] |= frei[:, 1:]
            frei = gewachsen
        fest[frei] = -1

        # Uebergangsband, gemeinsam geloest -- die frisch gemalten Zellen
        # bleiben ausgespart, damit der Pinsel wirklich das malt, was er soll.
        # Transition band, solved jointly -- the freshly painted cells are left
        # out so the brush really paints what it is supposed to.
        schutz = self.gemalt[y0:y1 + 1, x0:x1 + 1]
        # Band nach aussen breiter: die gemalten Zellen sind geschuetzt, also
        # bliebe sonst nur eine einzige Reihe uebrig -- und eine Kachel kann
        # keinen Verlauf zeigen, das wird ein Zickzack statt einer Zone.
        # Wider band towards the outside: the painted cells are protected, so
        # otherwise only a single row would remain -- and one tile cannot show
        # a ramp, which turns into a zigzag instead of a zone.
        # Bandbreite nach der Groesse der gemalten Flaeche. Fest auf 3 gesetzt
        # war das Band bei einem 4x4-Pinsel breiter als der Fleck selbst --
        # ringsum lagen Sandkacheln bis vier Felder weit weg und zerlegten die
        # Form. Ein kleiner Strich bekommt eine Kachel, ein grosser drei.
        # Band width follows the size of the painted area. Fixed at 3, the band
        # was wider than the patch itself for a 4x4 brush -- sand tiles sat up
        # to four fields away and broke up the shape. A small stroke gets one
        # tile, a large one three.
        flaeche = int(schutz.sum())
        breite = int(np.clip(round(np.sqrt(max(flaeche, 1)) / 6.0), 1, 3))
        # Waehrend des Strichs KEIN Band. Der Pinsel ist eine harte Grenze --
        # das ist gewollt, und das Band waere ohnehin verschwendet: die
        # gemalten Zellen sind geschuetzt, also legt `_mische_grenzen` sein Band
        # eine Zelle DANEBEN, und dort hat es vier gleiche Ecken. Gemessen warf
        # die Eckenkonstruktion davon 117 von 252 sofort wieder weg -- Arbeit
        # fuer nichts, und bei jedem Zwischenschritt eines Strichs erneut.
        #
        # Erst beim Loslassen faellt der Schutz, dann laeuft dieser Aufruf ohne
        # ihn und legt das Band beidseitig an: gemessen 76 Zellen auf der einen,
        # 80 auf der anderen Seite.
        #
        # NO band during the stroke. The brush is a hard boundary -- that is
        # intended, and the band would be wasted anyway: the painted cells are
        # protected, so `_mische_grenzen` puts its band one cell BESIDE them,
        # where all four corners are the same ground. Measured, the corner
        # construction threw away 117 of 252 of them right afterwards -- work for
        # nothing, and repeated at every intermediate step of a stroke.
        #
        # Only on release does the protection fall; then this call runs without
        # it and lays the band on both sides: measured 76 cells on one side and
        # 80 on the other.
        zt_alt = np.array([[self.map.cell_type(x, y)
                            for x in range(x0, x1 + 1)]
                           for y in range(y0, y1 + 1)])
        klippe_bleibt = (np.isin(zt_alt, (celltypes.NORTH_CLIFFS,
                                          celltypes.CLIFFS_HIGH_SIDE,
                                          celltypes.CLIFFS_LOW_SIDE))
                         & ~schutz)
        fest[klippe_bleibt] = alt[klippe_bleibt]
        if not schutz.any():
            mapgen._mische_grenzen(fest, fam, self.tm, self.rng, schutz=schutz,
                                   band_breite=breite)
        neu = mapgen._sample_tiles(fam, self.rng, self.tm, fest=fest,
                                   familie_zwingend=schutz)

        # Klippen werden nicht mehr aus dem Hoehenfeld abgeleitet (der
        # Blockweg ist entfernt): was schon als Klippe auf der Karte steht,
        # bleibt stehen -- ausser dort, wo dieser Strich selbst gemalt hat.
        # Cliffs are no longer derived from the height field: what already
        # stands as a cliff stays, except where this stroke painted.
        if klippe_bleibt.any():
            neu[klippe_bleibt] = alt[klippe_bleibt]
            mapgen._boden_an_klippen_nachziehen(neu, fam, klippe_bleibt,
                                                self.tm, self.rng)
        # Uebergaenge auch beim Malen aus den Ecken ableiten und danach
        # zurechtruecken -- dieselbe Kette wie beim Erzeugen.
        # Derive transitions from the corners when painting too and align them
        # afterwards -- the same chain as when generating.
        mapgen.nachbearbeite_uebergaenge(neu, fam, self.tm, self.rng)

        aenderungen = []
        for ly in range(bh):
            for lx in range(bw):
                kachel = int(neu[ly, lx])
                if kachel == int(alt[ly, lx]):
                    continue
                zt = celltypes.default_cell_type(kachel)
                aenderungen.append((x0 + lx, y0 + ly, kachel, int(zt)))
        return aenderungen

    def _nachbarn(self, x: int, y: int) -> tuple[int | None, int | None]:
        links = self.map.tile_mapping_index(x - 1, y) if x > 0 else None
        oben = self.map.tile_mapping_index(x, y - 1) if y > 0 else None
        return links, oben

    def _waehle(self, kacheln, gewichte, x: int, y: int) -> int | None:
        """Kachel ziehen, die zur linken und oberen Nachbarin passt."""
        if kacheln is None or not len(kacheln):
            return None
        kacheln = np.asarray(kacheln)
        gewichte = np.asarray(gewichte, dtype=float)
        passend = np.ones(len(kacheln), dtype=bool)
        for tabelle, nachbar in zip((self.tm.right, self.tm.down),
                                    self._nachbarn(x, y)):
            if nachbar is None:
                continue
            eintrag = tabelle.get(int(nachbar))
            if eintrag is not None:
                passend &= np.isin(kacheln, eintrag[0])
        auswahl = np.nonzero(passend)[0]
        if not len(auswahl):
            auswahl = np.arange(len(kacheln))
        gew = gewichte[auswahl]
        summe = gew.sum()
        if summe <= 0:
            return int(kacheln[auswahl[0]])
        return int(kacheln[auswahl[int(self.rng.choice(len(auswahl), p=gew / summe))]])

    def _klippen_kachel(self, x: int, y: int, rolle, ly: int, lx: int) -> int | None:
        if ly < 1 or lx < 1 or ly >= rolle.shape[0] - 1 or lx >= rolle.shape[1] - 1:
            return None
        fam = int(self.familie[y, x])
        if 2 <= ly < rolle.shape[0] - 2 and 2 <= lx < rolle.shape[1] - 2:
            fenster = rolle[ly - 2:ly + 3, lx - 2:lx + 3]
        else:
            fenster = rolle[ly - 1:ly + 2, lx - 1:lx + 2]
        kacheln, gewichte = self.tm.shapes.kacheln(fenster, fam)
        if kacheln is None or not len(kacheln):
            zt = celltypes.CLIFFS_HIGH_SIDE
            kacheln, gewichte = self.tm.shapes.grob(zt, fam)
        return self._waehle(kacheln, gewichte, x, y)

    def _boden_kachel(self, x: int, y: int) -> int | None:
        pool = self.tm.by_family.get(int(self.familie[y, x]))
        if pool is None:
            return None
        return self._waehle(pool[0], pool[1], x, y)
