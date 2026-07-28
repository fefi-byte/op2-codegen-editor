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

# Pinselarten. Die ersten beiden aendern die Hoehe, die naechsten das Biom,
# der Rest sind Sonderflaechen.
# Brush kinds: the first two change the height, the next ones the biome, the
# rest are special areas.
B_HOCH = "hoch"
B_TIEF = "tief"
B_ERDE = "mud"
B_FELS = "roc"
B_SAND = "san"
B_BEWUCHS = "veg"
B_SCHNEE = "sno"
B_VULKAN = "vulkan"
B_LAVA = "lava"
B_BAU = "bau"

FAMILIEN_PINSEL = (B_ERDE, B_FELS, B_SAND, B_BEWUCHS, B_SCHNEE)
BRUSHES = (B_HOCH, B_TIEF, B_ERDE, B_FELS, B_SAND, B_BEWUCHS, B_SCHNEE,
           B_VULKAN, B_LAVA, B_BAU)

# Wie weit ueber den Pinselrand hinaus neu gerechnet wird. Das Klippenband ist
# drei Zellen dick und das Kachelumfeld reicht zwei weit -- ohne Zuschlag
# bliebe an der Strichkante eine alte Wand stehen.
# How far beyond the brush the tiles are recomputed. The cliff band is three
# cells thick and the tile context reaches two further -- without the margin an
# old wall would remain at the edge of the stroke.
RAND = 6

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
        gueltig = fam[(fam >= 0) & (fam < len(self.tm.families))]
        vorgabe = int(np.bincount(gueltig).argmax()) if len(gueltig) else 0
        fam = np.where((fam >= 0) & (fam < len(self.tm.families)), fam, vorgabe)
        self.familie = fam.astype(np.int16)

    # ------------------------------------------------------------------
    def male(self, brush: str, zellen) -> tuple[int, int, int, int] | None:
        """Pinselstrich in die Ebenen eintragen, Rechteck zurueckgeben."""
        if not zellen:
            return None
        h, w = self.hoehe.shape
        xs = [x for x, _ in zellen]
        ys = [y for _, y in zellen]
        for x, y in zellen:
            if not (0 <= x < w and 0 <= y < h):
                continue
            if brush == B_HOCH:
                self.hoehe[y, x] = 1
            elif brush == B_TIEF:
                self.hoehe[y, x] = 0
            elif brush in FAMILIEN_PINSEL:
                if brush in self.tm.families:
                    self.familie[y, x] = self.tm.families.index(brush)
            elif brush == B_LAVA:
                self.lava[y, x] = True
            elif brush == B_BAU:
                # Baugelaende: eben, ohne Klippen -- darauf soll gebaut werden.
                # Building ground: flat, no cliffs -- you build on it.
                self.bau[y, x] = True
                self.hoehe[y, x] = 0
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
        return (max(0, min(xs)), max(0, min(ys)),
                min(w - 1, max(xs)), min(h - 1, max(ys)))

    # ------------------------------------------------------------------
    def synth_region(self, rechteck) -> list[tuple[int, int, int, int]]:
        """Kacheln im Bereich neu ableiten -> [(x, y, kachel, zelltyp)].

        Nur was sich aendern muss, wird geaendert: sonst wuerde bei jedem
        Strich der ganze Untergrund neu gewuerfelt und die Karte flackert.

        Only what has to change is changed: otherwise every stroke would
        reroll the whole ground and the map would flicker.
        """
        h, w = self.hoehe.shape
        x0 = max(0, rechteck[0] - RAND)
        y0 = max(0, rechteck[1] - RAND)
        x1 = min(w - 1, rechteck[2] + RAND)
        y1 = min(h - 1, rechteck[3] + RAND)

        # Zelltypen fuer den Bereich aus der Form ableiten. Mit Zuschlag
        # rechnen, damit das 5x5-Fenster am Bereichsrand vollstaendig ist.
        # Derive cell types for the region from the shape, with a margin so the
        # 5x5 window is complete at the region border.
        ax0, ay0 = max(0, x0 - 4), max(0, y0 - 4)
        ax1, ay1 = min(w - 1, x1 + 4), min(h - 1, y1 + 4)
        H = self.hoehe[ay0:ay1 + 1, ax0:ax1 + 1]
        zelltypen = shapegen.zelltypen_aus_form(H, self.tm.shapes)
        rolle = shapegen.rollen_aus_zelltypen(H, zelltypen)

        aenderungen = []
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                ly, lx = y - ay0, x - ax0
                soll_zt = int(zelltypen[ly, lx])
                alt = self.map.tile_mapping_index(x, y)
                alt_zt = self.map.cell_type(x, y)
                if self.bau[y, x] and soll_zt in CLIFF_CELLS:
                    soll_zt = -1        # Baugelaende bleibt frei
                if soll_zt in CLIFF_CELLS:
                    kachel = self._klippen_kachel(x, y, rolle, ly, lx)
                    if kachel is None:
                        continue
                elif alt_zt in CLIFF_CELLS or self.tm.family_of[alt] != self.familie[y, x]:
                    kachel = self._boden_kachel(x, y)
                    if kachel is None:
                        continue
                else:
                    continue
                zt = celltypes.default_cell_type(kachel)
                if kachel != alt or zt != alt_zt:
                    aenderungen.append((x, y, int(kachel), int(zt)))
        return aenderungen

    # ------------------------------------------------------------------
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
        kacheln, gewichte = self.tm.shapes.kacheln(
            rolle[ly - 1:ly + 2, lx - 1:lx + 2], fam)
        if kacheln is None or not len(kacheln):
            zt = celltypes.CLIFFS_HIGH_SIDE
            kacheln, gewichte = self.tm.shapes.grob(zt, fam)
        return self._waehle(kacheln, gewichte, x, y)

    def _boden_kachel(self, x: int, y: int) -> int | None:
        pool = self.tm.by_family.get(int(self.familie[y, x]))
        if pool is None:
            return None
        return self._waehle(pool[0], pool[1], x, y)
