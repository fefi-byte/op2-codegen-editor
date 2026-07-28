from __future__ import annotations
from .common import *


class MapView(QGraphicsView):
    """
    Eine ``QGraphicsView`` ueber die Karte mit drei Eingabemodi:
    Linksklick platziert / Rechtsklick entfernt, Mittel-Ziehen schwenkt
    (Pan) und Links-Ziehen waehlt ein Rechteck aus, wenn
    ``rect_select_enabled`` aktiv ist.

    A ``QGraphicsView`` over the map with three input modes: left-click
    place / right-click remove, middle-drag pan, and left-drag
    rectangle-select when ``rect_select_enabled`` is active.
    """
    # Signale / Signals:
    # tileClicked(x, y): Linksklick auf eine Kachel (Platzieren).
    #   Emitted on a left-click on a tile (place).
    # tileRemoved(x, y): Rechtsklick auf eine Kachel (Entfernen).
    #   Emitted on a right-click on a tile (remove).
    # tileHover(x, y): Mausbewegung ueber eine Kachel (kein Drag).
    #   Emitted on mouse move over a tile (when not dragging).
    # rectDragStarted(x, y): Beginn der Rechteckauswahl (Links-Druecken).
    #   Emitted when a rectangle selection starts (left button pressed).
    # rectDragMoved(x, y): Aktualisierung waehrend der Rechteckauswahl.
    #   Emitted while the rectangle selection is being dragged.
    # rectDragFinished(x, y): Abschluss der Rechteckauswahl (Links-Loslassen).
    #   Emitted when the rectangle selection finishes (left button released).
    # rectDragCanceled(): Abbruch der Rechteckauswahl (Rechtsklick).
    #   Emitted when the rectangle selection is canceled (right-click).
    tileClicked = Signal(int, int)
    tileRemoved = Signal(int, int)
    tileHover = Signal(int, int)
    rectDragStarted = Signal(int, int)
    rectDragMoved = Signal(int, int)
    rectDragFinished = Signal(int, int)
    rectDragCanceled = Signal()
    # brushSizeStep(delta): Strg+Mausrad im Lava-Malmodus (+1/-1).
    # brushSizeStep(delta): Ctrl+wheel in lava paint mode (+1/-1).
    brushSizeStep = Signal(int)
    # zoomChanged(scale): neuer Massstab (1.0 = 1:1, 32px je Kachel).
    # zoomChanged(scale): new scale factor (1.0 = 1:1, 32px per tile).
    zoomChanged = Signal(float)

    # Unterhalb dieser Kachelgroesse (in Bildschirmpixeln) wird das Gitter zu
    # einem Rauschmuster und Beschriftungen ueberlappen sich -- beides wird
    # dann ausgeblendet.
    # Below this tile size (in screen pixels) the grid turns into a noise
    # pattern and labels overlap -- both are hidden from then on.
    GRID_MIN_TILE_PX = 8
    LABEL_MIN_TILE_PX = 14

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self._panning = False
        self._pan_start = None
        self.rect_select_enabled = False
        self.lava_paint_enabled = False
        # Gelaendemodus: Linksziehen stempelt, Rechtsklick ist die Pipette.
        # Terrain mode: left-drag stamps, right-click is the eyedropper.
        self.terrain_paint_enabled = False
        self._rect_dragging = False
        self._erase_dragging = False
        # Kachelgitter standardmaessig aus (via set_grid umschaltbar).
        # Tile grid off by default (toggled via set_grid).
        self.show_grid = False

    def set_grid(self, on):
        """
        Blendet das Kachelgitter ein/aus und zeichnet die Ansicht neu.

        Shows/hides the tile grid and repaints the view.
        """
        self.show_grid = bool(on)
        self.viewport().update()

    def drawForeground(self, painter, rect):
        """
        Zeichnet bei aktivem Gitter Linien im SCENE_TILE-Raster ueber die
        Karte (nur ueber dem Kartenbereich, in der aktuellen Ansicht).

        When the grid is on, draws lines on the SCENE_TILE raster over the
        map (only across the map area, within the current view).
        """
        super().drawForeground(painter, rect)
        if not self.show_grid:
            return
        # Herausgezoomt liegen die Linien nur wenige Bildschirmpixel
        # auseinander und ueberdecken das Terrain als Moire-Muster.
        # When zoomed out the lines are only a few screen pixels apart and
        # cover the terrain with a moire pattern.
        if self.tile_screen_px() < self.GRID_MIN_TILE_PX:
            return
        # Nur ueber der Karte zeichnen (sceneRect == Kartenflaeche).
        # Only draw over the map (sceneRect == map area).
        area = rect.intersected(self.sceneRect())
        if area.isEmpty():
            return
        # Breite 0 = kosmetischer 1px-Stift, unabhaengig vom Zoom.
        # Width 0 = cosmetic 1px pen, independent of zoom.
        painter.setPen(QPen(QColor(255, 255, 255, 70), 0))
        lines = []
        x = (int(area.left()) // SCENE_TILE) * SCENE_TILE
        while x <= area.right():
            lines.append(QLineF(x, area.top(), x, area.bottom()))
            x += SCENE_TILE
        y = (int(area.top()) // SCENE_TILE) * SCENE_TILE
        while y <= area.bottom():
            lines.append(QLineF(area.left(), y, area.right(), y))
            y += SCENE_TILE
        painter.drawLines(lines)

    def scale_factor(self) -> float:
        """Aktueller Massstab (1.0 = 1:1). / Current scale (1.0 = 1:1)."""
        return float(self.transform().m11())

    def tile_screen_px(self) -> float:
        """Kantenlaenge einer Kachel in Bildschirmpixeln.

        Edge length of one tile in screen pixels."""
        return self.scale_factor() * SCENE_TILE

    def _emit_zoom(self):
        self.viewport().update()
        self.zoomChanged.emit(self.scale_factor())

    def _tile(self, pos):
        """
        Wandelt einen Widget-Punkt ueber die Szenenkoordinaten in
        Kachel-Koordinaten (x, y) um.

        Converts a widget point, via scene coordinates, into tile
        coordinates (x, y).
        """
        sp = self.mapToScene(pos.toPoint())
        return int(sp.x() // SCENE_TILE), int(sp.y() // SCENE_TILE)

    def zoom_default(self):
        """
        Setzt die Ansicht auf 1:1 (32px je Kachel = OP2-Spielansicht) und
        behaelt den aktuellen Bildmittelpunkt.

        Sets the view to 1:1 (32px per tile = OP2 in-game view), keeping the
        current center point.
        """
        center = self.mapToScene(self.viewport().rect().center())
        self.resetTransform()
        self.centerOn(center)
        self._emit_zoom()

    def zoom_fit(self):
        """
        Zoomt heraus, bis die gesamte Karte ins Fenster passt
        (Seitenverhaeltnis bleibt erhalten).

        Zooms out until the whole map fits in the window (aspect ratio
        preserved).
        """
        self.resetTransform()
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self._emit_zoom()

    def wheelEvent(self, event):
        # Strg+Rad im Lava-/Gelaende-Malmodus: Pinselgroesse statt Zoom.
        # Ctrl+wheel in lava/terrain paint mode: brush size instead of zoom.
        if ((self.lava_paint_enabled or self.terrain_paint_enabled)
                and event.modifiers() & Qt.ControlModifier):
            self.brushSizeStep.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        # Mausrad zoomt frei (zusaetzlich zu den Standard-Zoomstufen).
        # The mouse wheel free-zooms (in addition to the preset zoom levels).
        f = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(f, f)
        self._emit_zoom()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
        elif event.button() == Qt.LeftButton and self.rect_select_enabled:
            self._rect_dragging = True
            self.rectDragStarted.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton and self.terrain_paint_enabled:
            # Pipette statt "Abbrechen": im Gelaendemodus gibt es nichts zu
            # entfernen, jede Zelle traegt immer eine Kachel.
            # Eyedropper instead of "cancel": in terrain mode there is nothing
            # to remove, every cell always carries a tile.
            self.tileRemoved.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton and self.rect_select_enabled:
            if self.lava_paint_enabled:
                # Radieren: auch beim Ziehen weiterfeuern (siehe mouseMove).
                # Erasing: keeps firing while dragging (see mouseMove).
                self._erase_dragging = True
                self.tileRemoved.emit(*self._tile(event.position()))
            else:
                self._rect_dragging = False
                self.rectDragCanceled.emit()
        elif event.button() == Qt.LeftButton:
            self.tileClicked.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton:
            self.tileRemoved.emit(*self._tile(event.position()))
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Zweiter Klick eines Doppelklicks = ganz normaler Klick.

        Qt liefert ihn als eigenen Ereignistyp; ohne diese Weiterleitung
        verschluckt die Ansicht jeden zweiten schnellen Klick -- beim
        Platzieren mehrerer Einheiten dicht nebeneinander faellt damit jede
        zweite aus.

        The second click of a double-click is just another click. Qt delivers
        it as its own event type; without forwarding it the view swallows
        every second quick click -- placing several units close together then
        drops every other one."""
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            d = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        if self._rect_dragging:
            self.rectDragMoved.emit(*self._tile(event.position()))
            return
        if self._erase_dragging:
            self.tileRemoved.emit(*self._tile(event.position()))
            return
        self.tileHover.emit(*self._tile(event.position()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
        elif event.button() == Qt.LeftButton and self._rect_dragging:
            self._rect_dragging = False
            self.rectDragFinished.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton and self._erase_dragging:
            self._erase_dragging = False
        else:
            super().mouseReleaseEvent(event)


