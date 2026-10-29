"""Klippenpinsel im Editor: Punkte setzen, Anker, Live-Vorschau, Setzen.

Aus `window_terrain.py` herausgeloest.

Cliff brush: points, anchors, live preview, set.
"""
from __future__ import annotations
import numpy as np
from .common import *
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsEllipseItem
from tileset import TILE
import mapgen
from .paint_layers import B_KLIPPE
from .window_terrain import (  # noqa: F401
    KLIPPEN_LIVE_DECKKRAFT,
    KLIPPEN_LIVE_VERZOEGERUNG,
    TerrainEdit,
)


class _KlippenMixin:
    """Klippenpinsel im Editor: Punkte setzen, Anker, Live-Vorschau, Setzen."""

    def _klippe_punkt(self, tx: int, ty: int):
        """Einen Stuetzpunkt der Klippenlinie setzen.

        Beim Klippenpinsel wird nicht gemalt, sondern die Kante gezeichnet:
        jeder Klick setzt einen Punkt, der Knopf "Setzen" legt die Bloecke.
        Waehrend des Ziehens darf nur der erste Aufruf zaehlen -- sonst
        entstuenden bei jeder Mausbewegung neue Punkte.

        A cliff brush click sets a point of the edge instead of painting. Only
        the first call of a drag counts, otherwise every mouse move would add
        another point.
        """
        if not getattr(self, "_klick_neu", False):
            return
        self._klick_neu = False
        if not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
            return
        punkte = getattr(self, "_klippen_punkte", None)
        if punkte is None:
            punkte = self._klippen_punkte = []
        # Auf ein offenes Klippenende einrasten. Damit muss man beim
        # Weiterzeichnen nicht kachelgenau treffen -- und die Fortsetzung
        # setzt garantiert am richtigen Block an.
        #
        # Fuer JEDEN Punkt, nicht nur den ersten: eine Linie kann genauso gut auf
        # eine vorhandene Klippe zulaufen wie von einer wegfuehren, und dann muss
        # ihr Ende einrasten. Schon gesetzte Punkte sind ausgenommen, sonst
        # zoege es einen kurzen zweiten Klick auf den ersten zurueck.
        # For EVERY point, not only the first: a line can run into an existing
        # cliff as well as away from one, and then its end has to snap. Points
        # already placed are excluded, otherwise a short second click would be
        # pulled back onto the first.
        ebenen = self._paint_layers()
        if ebenen is not None:
            anker = ebenen.klippen_anker(tx, ty, ausser=punkte)
            if anker is not None:
                tx, ty = anker
                self.statusBar().showMessage(tr("terrain.klippe_eingerastet"))
        # Ab dem zweiten Punkt auf eine erlaubte Baurichtung rasten. Gemessen
        # kommen in den Originalkarten nur Neigungen bis vier Spalten je Zeile
        # vor, ueber die Haelfte der Kantenschritte ist senkrecht -- eine frei
        # gezogene Schraege gibt es dort nicht (siehe `KLIPPEN_NEIGUNGEN`).
        # From the second point on, snap to a permitted build direction: the
        # originals only use slopes up to four columns per row.
        if punkte:
            ax, ay = punkte[-1]
            if (tx, ty) != (ax, ay):
                tx, ty = mapgen.klippe_winkel_rasten(ax, ay, tx, ty)
                tx = max(0, min(self.map.width - 1, tx))
                ty = max(0, min(self.map.height - 1, ty))
        # Auf denselben Punkt noch einmal zu klicken schliesst die Figur.
        # Clicking the same point again closes the figure.
        punkte.append((int(tx), int(ty)))
        self._klippen_vorschau()
        self.terrain_panel.klippen_punkte_geaendert(len(punkte))

    def klippen_anker_auffrischen(self):
        """Die Ankerringe neu zeichnen -- nach jeder Kartenaenderung.

        Sie kommen aus den Zelltypen der Karte, also stimmen sie nach einem
        Rueckgaengig von selbst wieder; sie muessen nur neu gezeichnet werden.
        Redraw the anchor rings after any map change: they come from the map's
        cell types, so an undo fixes them by itself -- they only need redrawing.
        """
        if getattr(self, "_terrain_active", False) and hasattr(self, "terrain_panel"):
            self._klippen_vorschau()

    def _klippen_verwerfen(self):
        """Gesetzte Stuetzpunkte wegwerfen, ohne etwas zu zeichnen."""
        self._klippen_punkte = []
        self._klippen_vorschau()
        self.terrain_panel.klippen_punkte_geaendert(0)
        self.statusBar().showMessage(tr("terrain.klippe_verworfen"))

    def _klippe_setzen(self):
        """Aus den Stuetzpunkten eine Klippe machen."""
        ebenen = self._paint_layers()
        punkte = getattr(self, "_klippen_punkte", []) or []
        if ebenen is None or len(punkte) < 2:
            self.statusBar().showMessage(tr("terrain.klippe_zu_kurz"))
            return
        seite = self.terrain_panel.klippen_seite()
        aenderungen = ebenen.klippe_zeichnen(
            punkte, seite, self.terrain_panel.klippen_hoehe())
        self._klippen_punkte = []
        self.terrain_panel.klippen_punkte_geaendert(0)
        if not aenderungen:
            self._klippen_vorschau()
            self.statusBar().showMessage(tr("terrain.klippe_leer"))
            return
        rueck: list[tuple[int, int, int]] = []
        for x, y, kachel, zelltyp in aenderungen:
            i = self.map.tile_index(x, y)
            alt = self.map.tiles[i]
            self.map.set_tile(x, y, kachel, zelltyp)
            if self.map.tiles[i] != alt:
                rueck.append((i, alt, self.map.tiles[i]))
        coords = [(x, y) for x, y, _, _ in aenderungen]
        self._repaint_tiles(coords)
        self._patch_cells(coords)
        # Die Vorschau ERST jetzt neu zeichnen, mit der fertig geschriebenen
        # Karte. Sie fragt `offene_enden`, und das wirft gemerkte Enden weg, an
        # denen keine Klippe steht -- lief sie vor dem Schreiben, verwarf sie
        # genau die Enden, die dieser Zug eben erst gemerkt hatte.
        # Redraw the preview only now, with the map fully written: it asks
        # `offene_enden`, which discards remembered ends with no cliff at them --
        # run before the write it discarded exactly the ends this stroke had just
        # remembered.
        self._klippen_vorschau()
        if not rueck:
            return
        self._mark_map_edited()
        self._push_undo("terrain", TerrainEdit(rueck))
        self._refresh_terrain_overlay()
        self.statusBar().showMessage(tr("terrain.klippe_gesetzt", n=len(rueck)))

    def _klippen_vorschau(self):
        """Die gesetzten Stuetzpunkte als Linie in der Szene zeigen."""
        for item in getattr(self, "_klippen_items", []):
            if item.scene() is self.scene:
                self.scene.removeItem(item)
        self._klippen_items = []
        # Offene Enden als Anker zeigen, auch wenn gerade nichts gezeichnet
        # wird -- man muss sehen, wo man ansetzen kann.
        # Show open ends as anchors even when nothing is being drawn.
        ebenen = self._paint_layers()
        if ebenen is not None and self.terrain_panel.selected_brush() == B_KLIPPE:
            for ax, ay in ebenen.offene_enden():
                ring = QGraphicsEllipseItem((ax - 0.6) * SCENE_TILE,
                                            (ay - 0.6) * SCENE_TILE,
                                            2.2 * SCENE_TILE, 2.2 * SCENE_TILE)
                ring.setPen(QPen(QColor(120, 220, 255), 2))
                ring.setZValue(1000)
                self.scene.addItem(ring)
                self._klippen_items.append(ring)
        punkte = getattr(self, "_klippen_punkte", []) or []
        if not punkte or self.terrain_panel.selected_brush() != B_KLIPPE:
            self._klippen_live_weg()
            return
        if len(punkte) >= 2 and self._klippen_live_ziel is None:
            self._klippen_live_planen(None)
        farbe = QColor(255, 210, 90)
        for i, (x, y) in enumerate(punkte):
            marke = QGraphicsRectItem((x - 0.5) * SCENE_TILE,
                                      (y - 0.5) * SCENE_TILE,
                                      2 * SCENE_TILE, 2 * SCENE_TILE)
            marke.setPen(QPen(farbe, 3))
            marke.setZValue(1002)
            self.scene.addItem(marke)
            self._klippen_items.append(marke)
            if i:
                x0, y0 = punkte[i - 1]
                strich = QGraphicsLineItem(
                    (x0 + 0.5) * SCENE_TILE, (y0 + 0.5) * SCENE_TILE,
                    (x + 0.5) * SCENE_TILE, (y + 0.5) * SCENE_TILE)
                strich.setPen(QPen(farbe, 4))
                strich.setZValue(1001)
                self.scene.addItem(strich)
                self._klippen_items.append(strich)

    def _klippen_live_planen(self, ziel, neu: bool = False):
        """Die Wand fuer die Punkte plus `ziel` (den Zeiger) bald zeigen.

        `ziel` None heisst: nur die gesetzten Punkte. Gerechnet wird erst,
        wenn die Maus kurz stillsteht (`KLIPPEN_LIVE_VERZOEGERUNG`).
        Schedule the preview of the placed points plus `ziel` (the cursor).
        """
        # Derselbe Zielpunkt wie eben: nicht neu aufziehen. Sonst haelt ein
        # Strom von Hover-Ereignissen auf derselben Kachel den Zeitgeber
        # endlos zurueck, und die Vorschau kommt nie.
        # Same target as before: don't restart, or a stream of hover events on
        # one tile keeps the timer from ever firing.
        if (not neu and ziel == self._klippen_live_ziel
                and (self._klippen_live_timer.isActive()
                     or self._klippen_live_schluessel is not None)):
            return
        self._klippen_live_ziel = ziel
        self._klippen_live_timer.start()

    def _klippen_live_rechnen(self):
        """Die Wand ausrechnen und als Bild ueber die Karte legen.

        Geschrieben wird nichts: `klippe_berechnen` arbeitet auf einer Kopie
        des Kachelgitters. Die Kacheln kommen als ein einziges Pixmap ueber
        die Karte, unter die Punktmarken.
        Compute the wall on a copy and lay it over the map as one pixmap.
        """
        ebenen = self._paint_layers()
        punkte = list(getattr(self, "_klippen_punkte", []) or [])
        if (ebenen is None or self.map is None
                or not getattr(self, "_terrain_active", False)
                or self.terrain_panel.selected_brush() != B_KLIPPE):
            self._klippen_live_weg()
            return
        ziel = self._klippen_live_ziel
        if ziel is not None and (not punkte or tuple(ziel) != tuple(punkte[-1])):
            punkte.append((int(ziel[0]), int(ziel[1])))
        seite = self.terrain_panel.klippen_seite()
        hoehe = self.terrain_panel.klippen_hoehe()
        schluessel = (tuple(punkte), seite, hoehe)
        if schluessel == self._klippen_live_schluessel:
            return
        self._klippen_live_bild_weg()
        self._klippen_live_schluessel = schluessel
        if len(punkte) < 2:
            return
        try:
            aenderungen, _, _ = ebenen.klippe_berechnen(punkte, seite, hoehe)
        except Exception as e:          # Vorschau darf den Editor nie stoeren
            print("Klippenvorschau:", e)
            return
        if hoehe is None:
            self.terrain_panel.klippen_hoehe_gemessen(
                getattr(ebenen, "letzte_wandhoehe", None))
        if not aenderungen:
            return
        xs = [a[0] for a in aenderungen]
        ys = [a[1] for a in aenderungen]
        x0, y0 = min(xs), min(ys)
        bild = QPixmap((max(xs) - x0 + 1) * TILE, (max(ys) - y0 + 1) * TILE)
        bild.fill(Qt.transparent)
        maler = QPainter(bild)
        for x, y, kachel, _zt in aenderungen:
            kp = self._tile_pixmap(kachel)
            if kp is not None:
                maler.drawPixmap((x - x0) * TILE, (y - y0) * TILE, kp)
        maler.end()
        item = self.scene.addPixmap(bild)
        item.setPos(x0 * SCENE_TILE, y0 * SCENE_TILE)
        if SCENE_TILE != TILE:
            item.setScale(SCENE_TILE / TILE)
        item.setOpacity(KLIPPEN_LIVE_DECKKRAFT)
        item.setZValue(999)             # ueber der Karte, unter den Marken
        self._klippen_live_items.append(item)

    def _klippen_live_weg(self):
        """Die Live-Vorschau entfernen und vergessen."""
        timer = getattr(self, "_klippen_live_timer", None)
        if timer is not None:
            timer.stop()
        self._klippen_live_bild_weg()
        self._klippen_live_schluessel = None
        self._klippen_live_ziel = None

    def _klippen_live_bild_weg(self):
        for item in getattr(self, "_klippen_live_items", []):
            if item.scene() is self.scene:
                self.scene.removeItem(item)
        self._klippen_live_items = []

    def _klippen_vorwaermen(self):
        """Die Klippenmodelle im Hintergrund laden.

        Die erste Klippe braucht sonst rund zwei Sekunden, bis Kantentabelle,
        Paartabelle und Kachelbilder geladen sind -- bei der Live-Vorschau
        hiesse das: die erste Mausbewegung friert ein. Ein Probelauf auf einem
        kleinen Feld fuellt alle Zwischenspeicher, waehrend man noch den
        ersten Punkt setzt.
        Warm the cliff models up in a background thread so the first live
        preview does not freeze for two seconds.
        """
        if getattr(self, "_klippen_warm", False):
            return
        ebenen = self._paint_layers()
        if ebenen is None:
            return
        self._klippen_warm = True
        import threading

        def probe():
            try:
                import klippe_algo
                for fam in ("mud", "san"):
                    if not klippe_algo.verfuegbar(ebenen.tm, fam):
                        continue
                    g = np.zeros((24, 32), dtype=np.int32)
                    klippe_algo.klippe_aus_linie(
                        g, [(4, 12), (27, 12)], "oben", ebenen.tm,
                        np.random.default_rng(0), fam)
            except Exception as e:      # nur Vorwaermen -- darf scheitern
                print("Klippen vorwaermen:", e)

        threading.Thread(target=probe, daemon=True).start()

    def _klippen_zielring(self, tx: int, ty: int):
        """Ein Ring unter dem Zeiger: dorthin wuerde der Klick einrasten.

        Die offenen Enden tragen ihren eigenen, dauerhaften Ring. Fuer die
        Wandmitte geht das nicht -- ein Ring je Wandstueck waeren auf `cm04`
        1017 statt 51 und auf `cm02` 804 statt 34, Faktor 16 bis 24. Also einer,
        der mitgeht, und nur dort, wo wirklich eingerastet wird.

        One ring under the cursor showing where the click would snap. Open ends
        carry their own permanent ring; for the middle of a wall that does not
        scale -- one ring per wall segment would be 1017 instead of 51 on `cm04`.
        So one that follows along, and only where snapping really happens.
        """
        ebenen = self._paint_layers()
        if ebenen is None or self.map is None:
            return
        if not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
            return
        punkte = getattr(self, "_klippen_punkte", None) or []
        # Steht schon ein Punkt, zeigt eine Linie, wohin gebaut wuerde. Sie
        # rastet auf dieselbe Richtung wie der Klick -- so sieht man die
        # Baurichtung, bevor man sie setzt.
        # With a point already placed, a line shows where building would go; it
        # snaps to the same direction as the click would.
        if punkte:
            ax, ay = punkte[-1]
            if (tx, ty) != (ax, ay):
                bx, by = mapgen.klippe_winkel_rasten(ax, ay, tx, ty)
                bx = max(0, min(self.map.width - 1, bx))
                by = max(0, min(self.map.height - 1, by))
                anker = ebenen.klippen_anker(bx, by, ausser=punkte)
                self._klippen_live_planen(anker if anker is not None
                                          else (bx, by))
                linie = QGraphicsLineItem((ax + 0.5) * SCENE_TILE,
                                          (ay + 0.5) * SCENE_TILE,
                                          (bx + 0.5) * SCENE_TILE,
                                          (by + 0.5) * SCENE_TILE)
                linie.setPen(QPen(QColor(120, 220, 255), 3, Qt.DashLine))
                linie.setZValue(1000)
                self.scene.addItem(linie)
                self._terrain_preview_item = linie
                return
        ziel = ebenen.klippen_anker(tx, ty, ausser=punkte)
        if ziel is None or ziel in ebenen.offene_enden():
            return          # dort steht schon ein dauerhafter Ring
        ring = QGraphicsEllipseItem((ziel[0] - 0.6) * SCENE_TILE,
                                    (ziel[1] - 0.6) * SCENE_TILE,
                                    2.2 * SCENE_TILE, 2.2 * SCENE_TILE)
        ring.setPen(QPen(QColor(120, 220, 255), 2, Qt.DashLine))
        ring.setZValue(1000)
        self.scene.addItem(ring)
        self._terrain_preview_item = ring
