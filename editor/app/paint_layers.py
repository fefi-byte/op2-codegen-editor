"""Malebenen: Absicht statt Kacheln.

Der alte Gelaende-Tab liess einzelne Kacheln stempeln. Das ist die falsche
Ebene: welche Kachel an einer Klippenkante richtig ist, haengt vom Umfeld ab,
und wer das von Hand setzt, kaempft gegen die Kachelgrammatik statt zu
gestalten.

Hier wird stattdessen die ABSICHT gemalt, in zwei Ebenen neben der Karte:

    hoehe     0 = Tiefland, 1 = Hochland  -> Klippen entstehen an der Grenze
    familie   Erde, Fels, Sand, Bewuchs, Schnee

Aus diesen beiden Ebenen rechnet `synth_region` die Kacheln aus. Die Kacheln
waehlt OP2MappingLib (`BlendMap.paint`/`resolve`, Klippen mit `draw_cliff`);
hier stehen nur noch die Ebenen selbst und was der Editor um die Bibliothek
herum braucht (Glaettung des Umrisses, Anker der Klippenenden, Wandhoehe "wie
Karte"). Ohne Bibliothek gibt es keine Malebenen: `PaintLayers` wirft dann
RuntimeError mit `maplib.fehlt_text()`.

Paint layers: intent instead of tiles. The old terrain tab stamped individual
tiles, which is the wrong level -- which tile is right on a cliff edge depends
on the surroundings, and placing that by hand means fighting the tile grammar
instead of designing. Here the INTENT is painted in two layers beside the map,
and `synth_region` derives the tiles from them through OP2MappingLib (paint and
resolve, cliffs via draw_cliff). Only the layers and the editor glue around the
library live here. Without the library there are no paint layers: PaintLayers
raises RuntimeError with `maplib.fehlt_text()`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import zlib
from collections import Counter, deque

import numpy as np

_MAPVIEW = Path(__file__).resolve().parents[2] / "mapview"
if str(_MAPVIEW) not in sys.path:
    sys.path.insert(0, str(_MAPVIEW))

import celltypes    # noqa: E402
from op2map import (CELL_TYPE_BITS, CELL_TYPE_MASK,  # noqa: E402
                    MAPPING_INDEX_MASK)

from . import maplib  # noqa: E402
from .boeden import boeden  # noqa: E402

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

KLIPPEN_ERSATZ = "mud"     # Klippenfamilie fuer Boeden ohne eigene Klippen
CLIFF_CELLS = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
               celltypes.CLIFFS_LOW_SIDE)

# Wandhoehe "wie Karte": gemessen an den Klippen um die Linie, sonst auf der
# ganzen Karte, sonst WAND_ZELLEN. Die Bibliothek nimmt 3 bis 6 Zellen.
# Wall height "like the map": measured around the line, else on the whole map,
# else WAND_ZELLEN. The library takes 3 to 6 cells.
WAND_ZELLEN = 3.0
WAND_ZELLEN_MIN = 3.0
WAND_ZELLEN_MAX = 6.0
WAND_MESS_MIN = 12             # so viele Laeufe, bevor eine Messung zaehlt
WAND_UMKREIS = 24              # Zellen um die Linie fuer die Messung vor Ort


def wandhoehe_messen(zelltypen: np.ndarray) -> tuple[float, int]:
    """Mittlere Wandhoehe in Zellen -> (Mittel, Anzahl Laeufe).

    Gezaehlt werden senkrechte Laeufe von Hochseiten-Zellen (Zelltyp 9, 10),
    deren Nachbarspalten ebenfalls Klippe sind.
    Mean wall height in cells: vertical runs of high-side cells whose
    neighbouring columns are cliff as well.
    """
    zt = np.asarray(zelltypen)
    hl = (zt == celltypes.CLIFFS_HIGH_SIDE) | (zt == celltypes.CLIFFS_LOW_SIDE)
    kl = hl | (zt == celltypes.NORTH_CLIFFS)
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

    Erst um die Linie herum -- wer an eine Klippe ansetzt, will deren Hoehe --,
    dann die ganze Karte, sonst `WAND_ZELLEN`.
    The wall height a new line follows: around the line, then the whole map.
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


def hoehe_aus_zelltypen(ct: np.ndarray) -> np.ndarray:
    """Hochland/Tiefland aus den Zelltypen einer fertigen Karte zurueckgewinnen.

    Klippen trennen die Ebenen, ihre Zelltypen sagen, welche Seite oben liegt:
    jede klippenfreie Flaeche stimmt mit den Klippenzellen an ihrem Rand ab.
    Eine geladene Karte -- auch eine Originalkarte -- braucht ihre Hoehenebene,
    sonst weiss der Pinsel nicht, worauf er malt.

    Recover highland/lowland from the cell types of a finished map: every
    cliff-free area votes with the cliff cells on its rim.
    """
    h, w = ct.shape
    klippe = np.isin(ct, CLIFF_CELLS)
    H = np.zeros(ct.shape, dtype=np.int8)
    besucht = np.zeros(ct.shape, dtype=bool)
    for sy in range(h):
        for sx in range(w):
            if klippe[sy, sx] or besucht[sy, sx]:
                continue
            q = deque([(sx, sy)])
            besucht[sy, sx] = True
            zellen = []
            stimmen = Counter()
            while q:
                x, y = q.popleft()
                zellen.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if klippe[ny, nx]:
                        stimmen[int(ct[ny, nx])] += 1
                    elif not besucht[ny, nx]:
                        besucht[ny, nx] = True
                        q.append((nx, ny))
            if stimmen[celltypes.CLIFFS_HIGH_SIDE] > stimmen[celltypes.CLIFFS_LOW_SIDE]:
                for x, y in zellen:
                    H[y, x] = 1
    H[ct == celltypes.CLIFFS_HIGH_SIDE] = 1
    H[ct == celltypes.NORTH_CLIFFS] = 1
    return H


def mehrheit_glaetten(feld: np.ndarray, runden: int = 1, radius: int = 1) -> np.ndarray:
    """Jede Zelle bekommt den haeufigsten Wert ihrer Umgebung (Mehrheitsfilter).

    Every cell takes the most common value of its surroundings.
    """
    out = feld
    arten = int(out.max()) + 1
    for _ in range(max(0, runden)):
        zahl = np.zeros((arten,) + out.shape, dtype=np.int16)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                v = np.roll(np.roll(out, dy, axis=0), dx, axis=1)
                for k in range(arten):
                    zahl[k] += (v == k)
        out = np.argmax(zahl, axis=0).astype(np.int16)
    return out


class PaintLayers:
    """Hoehe und Biom fuer die geladene Karte."""

    def __init__(self, op2map, seed: int = 1):
        # Ohne OP2MappingLib keine Malebenen -- der Aufrufer zeigt die Meldung.
        # Without OP2MappingLib there are no paint layers; the caller shows why.
        if not maplib.verfuegbar():
            raise RuntimeError(maplib.fehlt_text())
        self.map = op2map
        # Die Familien SIND die Boeden des Profils (gleiche Reihenfolge).
        # The families ARE the profile's grounds (same order).
        self.tm = boeden()
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
        self.letzter_strich = None      # Maske des zuletzt beendeten Strichs
        self.letzte_klippe_ersatz = None  # Familie, fuer die mud einsprang
        # Offene Enden gesetzter Klippen -- daran kann weitergezeichnet werden.
        # Sie werden ausdruecklich gefuehrt statt aus der Karte gesucht: ein
        # ueberlappter Block ist teilweise ueberschrieben und per Mustersuche
        # nicht mehr auffindbar. Ein gemerkter Punkt bleibt auffindbar.
        # Open ends of placed cliffs, kept explicitly rather than searched for
        # in the map: an overlapped block is partly overwritten and no longer
        # matches, while a remembered point stays findable.
        self.klippen_enden: list[tuple[int, int]] = []
        # Familie -> malbarer Profil-Boden (-1 = keine Fuellkacheln, etwa Lava).
        # Family -> paintable profile ground (-1 = no fill tiles, e.g. lava).
        self._lib_boden = np.array([maplib.boden(f) for f in self.tm.families],
                                   dtype=np.int16)
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
        self.hoehe = hoehe_aus_zelltypen(zellen)
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
        # Den Boden der Bibliothek je Zelle uebernehmen, wo sie einen kennt.
        # Sonst rechnen Ebene und Bibliothek mit verschiedenen Boeden, und der
        # naechste Strich malt Zellen neu, die er gar nicht beruehrt.
        # Take the library's ground per cell where it knows one, otherwise
        # layer and library disagree and the next stroke repaints cells it
        # never touched. Ground index == family index.
        bm = maplib.mischkarte(self.map, kacheln)
        lib = maplib.boden_feld(bm, 0, 0, w - 1, h - 1)
        fam = np.where(lib >= 0, lib, fam)
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
        self.letzter_strich = self.gemalt.copy()
        self.gemalt[:, :] = False
        return bereich

    def klippe_zeichnen(self, punkte, hoch_seite: str, wandhoehe=None
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
        aenderungen, maske, zellen = self.klippe_berechnen(punkte, hoch_seite,
                                                           wandhoehe)
        if not aenderungen:
            return []
        self._hoehe_aus_klippe(maske, zellen)
        if not (len(punkte) > 2 and tuple(punkte[0]) == tuple(punkte[-1])):
            for p in (punkte[0], punkte[-1]):
                if tuple(p) not in self.klippen_enden:
                    self.klippen_enden.append((int(p[0]), int(p[1])))
        return aenderungen

    def klippe_berechnen(self, punkte, hoch_seite: str, wandhoehe=None):
        """Die Klippe ausrechnen, OHNE etwas zu veraendern.

        -> (aenderungen, maske, zellen). Fuer die Live-Vorschau: sie ruft das
        bei jeder Mausbewegung, also darf hier weder Hoehe noch Enden noch der
        Zufallsstand weiterlaufen. Der Zufall kommt deshalb aus den Punkten
        selbst -- dieselbe Linie gibt dieselbe Wand, und was die Vorschau
        zeigt, ist genau das, was "Setzen" schreibt.

        `wandhoehe` in Zellen; None heisst "wie die Karte": gemessen an den
        Klippen um die Linie, sonst auf der ganzen Karte, sonst 3
        (`wandhoehe_vor_ort`). Was genommen wurde, steht danach in
        `letzte_wandhoehe`. Die Kacheln setzt OP2MappingLib (`draw_cliff`).

        Compute the cliff WITHOUT changing anything. The random state is seeded
        from the points, so the preview shows exactly what "Set" will write.
        `wandhoehe` None means: measured from the cliffs on the map.
        """
        leer = ([], None, None)
        self.letzte_klippe_ersatz = None
        if len(punkte) < 2:
            return leer
        h, w = self.hoehe.shape
        roh = self._rohgitter()
        gitter = ((roh >> CELL_TYPE_BITS) & MAPPING_INDEX_MASK).astype(np.int32)
        if wandhoehe is None:
            wandhoehe = wandhoehe_vor_ort(roh & CELL_TYPE_MASK, punkte)
        self.letzte_wandhoehe = float(wandhoehe)
        x0, y0 = punkte[0]
        fi = int(self.familie[max(0, min(h - 1, y0)), max(0, min(w - 1, x0))])
        saat = zlib.crc32(repr(([tuple(map(int, p)) for p in punkte],
                                hoch_seite)).encode())
        return self._klippe_lib(gitter, punkte, hoch_seite, wandhoehe, saat, fi)

    def _klippe_lib(self, gitter, punkte, hoch_seite, wandhoehe, saat, fi):
        """Die Klippe mit OP2MappingLib rechnen -> wie `klippe_berechnen`.

        Kann die Bibliothek es nicht (unbekannte Seite, keine Klippenkacheln
        im Profil), bleibt das Ergebnis leer und der Aufrufer meldet "keine
        Klippe gesetzt". Die Bibliothek nimmt die Klippenfamilie selbst vom
        Boden am ersten Punkt und springt auf Boeden ohne eigene Klippen mit
        mud ein; den Erdrand darum legt der Editor (`letzte_klippe_ersatz`).

        Compute the cliff with OP2MappingLib. If it cannot (unknown side, no
        cliff tiles), the result is empty. The library picks the cliff family
        from the ground at the first point and falls back to mud; the editor
        lays the mud rim around it.
        """
        leer = ([], None, None)
        seite = maplib.SEITEN.get(hoch_seite)
        if seite is None:
            return leer
        p = maplib.profil()
        g = int(self._lib_boden[fi]) if 0 <= fi < len(self._lib_boden) else -1
        eigene = p.cliff_ground(g if g >= 0 else p.find_ground(KLIPPEN_ERSATZ))
        if eigene < 0:
            return leer
        self.letzte_klippe_ersatz = (self.tm.families[fi]
                                     if eigene == 0 and g >= 0 else None)
        bm = maplib.mischkarte(self.map, gitter)
        try:
            changes = bm.draw_cliff([(int(x), int(y)) for x, y in punkte], seite,
                                    float(wandhoehe), saat)
        except maplib.modul().Op2MapLibError:
            changes = []                  # z.B. Punkte ausserhalb der Karte
        if not changes:
            return [], None, None
        maske = np.zeros(gitter.shape, dtype=bool)
        zellen = np.full(gitter.shape, -1, dtype=np.int16)
        aenderungen = []
        for c in changes:
            maske[c.y, c.x] = True
            zt = c.cell_type if c.cell_type >= 0 else self._zelltyp(c.new_mapping, c.x, c.y)
            zellen[c.y, c.x] = zt
            aenderungen.append((c.x, c.y, c.new_mapping, int(zt)))
        return aenderungen, maske, zellen

    def _zelltyp(self, kachel: int, x: int, y: int) -> int:
        """Ueblicher Zelltyp der Kachel, sonst der bisherige der Zelle."""
        zt = celltypes.default_cell_type(kachel)
        return int(zt) if zt is not None else int(self.map.cell_type(x, y))

    def _synth_lib(self, x0: int, y0: int, x1: int, y1: int):
        """Den Bereich mit OP2MappingLib rechnen -> Aenderungen oder None.

        Gemalt werden die Zellen dieses Strichs (`gemalt`) und alle, deren
        Familie nicht mehr zum Boden der Bibliothek passt (Glaettung, Vulkan,
        Erdrand). Danach waehlt die Bibliothek die Kacheln im Bereich samt
        Uebergaengen. Klippen und andere feste Kacheln bleiben, ausser der
        Strich selbst hat sie uebermalt.

        Zellen, deren Boden die Bibliothek nicht malen kann (keine
        Fuellkacheln, etwa Lava), bleiben, wie sie sind.

        Compute the region with OP2MappingLib. Paints the stroke's cells and all
        cells whose family no longer matches the library's ground, then lets
        the library pick the tiles and transitions. Cliffs stay unless the
        stroke itself painted over them. Cells whose ground the library cannot
        paint (no fill tiles, e.g. lava) stay as they are.
        """
        gitter = self._kachelgitter()
        bm = maplib.mischkarte(self.map, gitter)
        lib = maplib.boden_feld(bm, x0, y0, x1, y1)
        soll = self._lib_boden[self.familie[y0:y1 + 1, x0:x1 + 1]]
        malen = self.gemalt[y0:y1 + 1, x0:x1 + 1] | ((lib >= 0) & (lib != soll))
        malen &= soll >= 0
        if not malen.any():
            return []
        for g in np.unique(soll[malen]):
            ys, xs = np.nonzero(malen & (soll == g))
            bm.paint(int(g), [(int(x) + x0, int(y) + y0) for y, x in zip(ys, xs)])
        saat = int(self.rng.integers(0, 2 ** 63))
        changes = bm.resolve(saat, region=(x0, y0, x1 - x0 + 1, y1 - y0 + 1))
        return [(c.x, c.y, c.new_mapping,
                 c.cell_type if c.cell_type >= 0 else self._zelltyp(c.new_mapping, c.x, c.y))
                for c in changes]

    def uebergaenge_aufraeumen(self) -> list[tuple[int, int, int, int]]:
        """Alle Uebergangskacheln der Karte neu bestimmen -> Aenderungen.

        OP2MappingLibs Aufraeum-Durchgang (`resolve_all`).
        Recompute every transition tile: OP2MappingLib's clean-up pass.
        """
        bm = maplib.mischkarte(self.map, self._kachelgitter())
        changes = bm.resolve_all(int(self.rng.integers(0, 2 ** 63)))
        return [(c.x, c.y, c.new_mapping,
                 c.cell_type if c.cell_type >= 0 else self._zelltyp(c.new_mapping, c.x, c.y))
                for c in changes]

    def _kachelgitter(self):
        """Die Kachelindizes der Karte als Feld (eine frische Kopie)."""
        return ((self._rohgitter() >> CELL_TYPE_BITS)
                & MAPPING_INDEX_MASK).astype(np.int32)

    def _rohgitter(self):
        """Die rohen Kachelwerte (Zelltyp + Kachel) als Feld (h, w).

        Ueber eine gemerkte Indextabelle statt Zelle fuer Zelle: die
        Live-Vorschau braucht das bei jeder Mausbewegung (11 ms -> unter 1 ms
        auf 128x128).
        """
        h, w = self.hoehe.shape
        schl = (w, h)
        if getattr(self, "_roh_index", (None,))[0] != schl:
            ys, xs = np.mgrid[0:h, 0:w]
            idx = ((xs >> 5) * h + ys) * 32 + (xs & 0x1F)
            self._roh_index = (schl, idx)
        return np.asarray(self.map.tiles, dtype=np.int64)[self._roh_index[1]]

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
        # Gemerkte Enden sind genau (der gezeichnete Punkt), die gerasterten
        # nur auf drei Zellen genau. Liegt ein gerastertes daneben, ist es
        # dasselbe Ende -- sonst standen an jedem Ende zwei Ringe.
        # A remembered end is exact; a grid end next to it is the same end.
        for ax, ay in self.klippen_enden:
            enden = [(bx, by) for bx, by in enden
                     if max(abs(bx - ax), abs(by - ay)) > 3]
        enden.extend(self.klippen_enden)
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

        Erst wird der Umriss der Familienebene geglaettet, dann malt
        OP2MappingLib die Boeden und waehlt Kacheln und Uebergaenge
        (`_synth_lib`). Was ausserhalb des Bereichs liegt, bleibt; die
        Bibliothek faedelt das Neue an den Nachbarn ein.

        The family layer's outline is smoothed first, then OP2MappingLib paints
        the grounds and picks tiles and transitions (`_synth_lib`). Everything
        outside the region stays; the library threads the new tiles into their
        neighbours.
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
            geglaettet = mehrheit_glaetten(
                self.familie[y0:y1 + 1, x0:x1 + 1].astype(np.int16),
                GLAETT_RUNDEN, radius=1)
            self.familie[y0:y1 + 1, x0:x1 + 1] = geglaettet
        return self._synth_lib(x0, y0, x1, y1)
