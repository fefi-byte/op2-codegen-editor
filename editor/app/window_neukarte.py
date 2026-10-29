"""Erzeugte Karten uebernehmen: neue Karte, Lavafelder, Startpunkte, Vulkane.

Aus `window_terrain.py` herausgeloest.

Generated maps: new map, lava fields, spawn points, volcanoes.
"""
from __future__ import annotations
from .common import *
from PySide6.QtWidgets import QGraphicsEllipseItem


class _NeueKarteMixin:
    """Erzeugte Karten uebernehmen: neue Karte, Lavafelder, Startpunkte, Vulkane."""

    def new_generated_map(self):
        """Panel "Neue Karte" in der Seitenleiste oeffnen.

        Kein Dialog: die erzeugte Karte landet direkt in der grossen Ansicht,
        damit man sie in voller Groesse beurteilen kann. Das Panel gibt es nur
        so lange, wie man es braucht.

        Open the "new map" panel in the sidebar. No dialog: the generated map
        goes straight into the main view so it can be judged at full size.
        """
        if self.map is None:
            return
        if getattr(self, "newmap_panel", None) is not None:
            self._sidebar_tabs.setCurrentIndex(
                self._sidebar_tabs.indexOf(self.newmap_panel))
            return
        from .panels.newmap_panel import NewMapPanel
        panel = NewMapPanel(self)
        self.newmap_panel = panel
        index = self._sidebar_tabs.addTab(panel, tr("window.tab_newmap"))
        self._sidebar_tabs.setCurrentIndex(index)
        panel.start()

    def close_newmap_panel(self, keep: bool):
        """Panel schliessen -- Karte behalten oder alten Zustand zuruecksetzen."""
        panel = getattr(self, "newmap_panel", None)
        if panel is None:
            return
        if not keep:
            panel.restore_backup()
            self.statusBar().showMessage(tr("newmap.status_discarded"))
        index = self._sidebar_tabs.indexOf(panel)
        self.newmap_panel = None
        if index >= 0:
            self._sidebar_tabs.removeTab(index)
        self._refresh_overview()

    def apply_generated_map(self, generated, params):
        """Erzeugtes Gelaende als aktuelle Karte setzen.

        Take the generated terrain as the current map."""
        import mapgen
        mapgen.apply_to_map(self.map, generated)
        self.map_name = self._custom_map_name()
        self.mapgen_params = {
            "seed": params.seed, "width": params.width, "height": params.height,
            "mix": params.mix, "roughness": params.roughness,
            "symmetry": params.symmetry, "spawns": params.spawns,
        }
        self.spawn_points = [list(p) for p in generated.spawns]
        self.volcano_points = [list(p) for p in generated.volcanoes]
        self._collect_lava_fields(generated)
        self._rebuild_scene_from_map()
        self.map_edited = True
        self._refresh_overview()
        self.statusBar().showMessage(tr(
            "newmap.status_created", seed=params.seed,
            w=params.width, h=params.height, n=len(generated.spawns)))

    def _collect_lava_fields(self, generated):
        """Lavafelder aus den erzeugten Zonen uebernehmen.

        Bewusst OHNE Trigger: die Karte legt nur fest, WO Lava fliessen kann
        (SetLavaPossible im InitProc). WANN ein Vulkan ausbricht, entscheidet
        die Mission mit eigenen Triggern.

        Take the lava fields from the generated zones -- deliberately WITHOUT
        a trigger: the map only defines WHERE lava can flow; WHEN a volcano
        erupts is up to the mission's own triggers.
        """
        tiles: set[tuple[int, int]] = set()
        for zone in generated.lava_zones:
            tiles.update((int(x), int(y)) for x, y in zone)
        self.lava_fields = [list(t) for t in sorted(tiles)]

    def _rebuild_scene_from_map(self):
        """Szene nach einem Kartenwechsel neu aufbauen (Objekte bleiben)."""
        import numpy as np
        from render import render_array
        arr = np.ascontiguousarray(render_array(self.map, self.res))
        qimg = QImage(arr.data, arr.shape[1], arr.shape[0], arr.shape[1] * 3,
                      QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())
        self.scene.clear()
        self._map_pixmap = pix
        self._map_item = self.scene.addPixmap(pix)
        self.scene.setSceneRect(QRectF(pix.rect()))
        self._tile_pixmaps = {}
        self._tilesets_cache = None
        self._terrain_overlay_item = None
        self._terrain_preview_item = None
        self._tile_index_grid = None
        self._cell_cache = None
        self._patch_chunks = {}
        self._placement_preview_items = []
        self._planned_items = []
        self._lava_paint_items = []
        for obj in self.objects:
            self._draw(obj)
        self._draw_spawn_points()
        self._draw_volcano_points()
        self._draw_lava_fields()
        if hasattr(self, "terrain_panel"):
            self.terrain_panel.load()
        if getattr(self, "_terrain_active", False):
            self._refresh_terrain_overlay()
        self.view.zoom_fit()

    def _draw_spawn_points(self):
        """Startpunkte als Ringe auf der Karte markieren."""
        self._spawn_items = []
        for i, (x, y) in enumerate(getattr(self, "spawn_points", []), start=1):
            r = 3 * SCENE_TILE
            ring = QGraphicsEllipseItem(x * SCENE_TILE - r, y * SCENE_TILE - r, 2 * r, 2 * r)
            ring.setPen(QPen(QColor(255, 255, 255), 3))
            ring.setZValue(1150)
            self.scene.addItem(ring)
            label = QGraphicsSimpleTextItem(f"S{i}")
            label.setBrush(QBrush(QColor(255, 255, 255)))
            label.setPos(x * SCENE_TILE + 4, y * SCENE_TILE - r)
            label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            label.setZValue(1151)
            self.scene.addItem(label)
            self._spawn_items += [ring, label]

    def edit_lava_fields(self):
        """Malmodus fuer die Lavafelder der Karte starten.

        Die Felder gehoeren zur Karte, nicht zu einem Trigger: sie legen fest,
        WO Lava ueberhaupt fliessen kann (SetLavaPossible im InitProc).

        Start the paint mode for the map's lava fields. They belong to the
        map, not to a trigger: they define WHERE lava can flow at all."""
        if self.map is None:
            return
        self._clear_lava_field_items()
        self._begin_lava_paint({"kind": "lava_paint", "target": "mission"})

    def _draw_lava_fields(self):
        """Lavafelder auf der Karte zeigen (ausserhalb des Malmodus)."""
        self._clear_lava_field_items()
        items = []
        for x, y in getattr(self, "lava_fields", []):
            rect = QGraphicsRectItem(x * SCENE_TILE, y * SCENE_TILE,
                                     SCENE_TILE, SCENE_TILE)
            rect.setPen(QPen(Qt.NoPen))
            rect.setBrush(QBrush(QColor(255, 90, 30, 90)))
            rect.setZValue(880)
            self.scene.addItem(rect)
            items.append(rect)
        self._lava_field_items = items

    def _clear_lava_field_items(self):
        for item in getattr(self, "_lava_field_items", []):
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
        self._lava_field_items = []

    def _draw_volcano_points(self):
        """Vulkane markieren -- der Krater selbst steckt schon im Gelaende."""
        self._volcano_items = []
        for i, (x, y) in enumerate(getattr(self, "volcano_points", []), start=1):
            r = 4 * SCENE_TILE
            ring = QGraphicsEllipseItem(x * SCENE_TILE - r, y * SCENE_TILE - r, 2 * r, 2 * r)
            ring.setPen(QPen(QColor(255, 140, 40), 3))
            ring.setZValue(1150)
            self.scene.addItem(ring)
            label = QGraphicsSimpleTextItem(f"V{i}")
            label.setBrush(QBrush(QColor(255, 170, 80)))
            label.setPos(x * SCENE_TILE + 4, y * SCENE_TILE - r)
            label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            label.setZValue(1151)
            self.scene.addItem(label)
            self._volcano_items += [ring, label]

    def terrain_map_bytes(self) -> bytes | None:
        """Bearbeitete Karte als Bytes (None, wenn unveraendert).

        The edited map as bytes (None when unchanged)."""
        if not getattr(self, "map_edited", False) or self.map is None:
            return None
        return self.map.to_bytes()
