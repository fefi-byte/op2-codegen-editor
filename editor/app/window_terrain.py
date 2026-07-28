"""Gelaende bearbeiten: Kachel-Stempel setzen, Befahrbarkeit mitfuehren.

Die Kachelgrafik und der Zelltyp (Befahrbarkeit) stehen in derselben 32-Bit-
Zelle der Karte. Beim Stempeln wird die Grafik aus der TileGroup uebernommen
und der Zelltyp aus der gelernten Tabelle (mapview/celltypes.json) -- also
genau der Wert, den die Original-Designer fuer diese Kachel benutzt haben.
Ueber die Auswahl im Panel laesst sich der Zelltyp uebersteuern.

Terrain editing: stamp tile groups and carry the passability along. Graphic
and cell type live in the same 32-bit cell; stamping takes the graphic from
the tile group and the cell type from the learned table, unless the panel
overrides it.
"""
from __future__ import annotations

import numpy as np

from .common import *
from celltypes import (
    CLIFF, EDITABLE_CELL_TYPES, FAST, IMPASSABLE, MEDIUM, SLOW, SPECIAL,
    default_cell_type, speed_class,
)
from tileset import TILE, load_tileset
import mapgen
from .paint_layers import PaintLayers, B_HOCH, B_ERDE, B_VULKAN
from .panels.terrain_panel import PUNKT_PINSEL

# Farben des Befahrbarkeits-Overlays je Geschwindigkeitsklasse.
# Colors of the passability overlay per speed class.
SPEED_COLORS: dict[str, tuple[int, int, int]] = {
    FAST:       (120, 220, 120),
    MEDIUM:     (240, 220, 110),
    SLOW:       (240, 160,  80),
    IMPASSABLE: (230,  90,  90),
    CLIFF:      (170, 130, 240),
    SPECIAL:    (120, 220, 230),
}
OVERLAY_ALPHA = 110

# Groesse der Nachzeichen-Bloecke (in Kacheln bzw. Pixeln) und Obergrenze,
# ab der sie in die Karte eingebacken werden.
# Size of the repaint chunks (in tiles resp. pixels) and the limit at which
# they get baked into the map.
CHUNK_TILES = 8
CHUNK_PX = CHUNK_TILES * TILE
MAX_PATCH_CHUNKS = 96


class TerrainEdit:
    """Eine Stempel-Aktion fuer die Rueckgaengig-Liste.

    One stamp action for the undo stack: which cells changed, and how."""

    display = "Gelände"          # fuer die Statusmeldungen der Undo-Logik

    def __init__(self, changes: list[tuple[int, int, int]]):
        # (tile_index, alter Wert, neuer Wert)
        self.changes = changes


class _TerrainMixin:
    # ------------------------------------------------------------------
    # Zustand / state

    def _reset_terrain_state(self):
        """Nach dem Laden einer Karte: Zwischenspeicher und Overlay verwerfen."""
        self._tile_pixmaps: dict[int, QPixmap] = {}
        self._tilesets_cache = None
        self._terrain_overlay_item = None
        self._terrain_preview_item = None
        self._tile_index_grid = None      # Kartengroesse kann sich aendern
        self._cell_cache = None
        self._patch_chunks: dict[tuple[int, int], list] = {}
        self.map_edited = False
        # Die Stempel stehen in der Karte -- nach jedem Kartenwechsel neu
        # einlesen (beim ersten Aufruf gibt es das Panel noch nicht).
        # The stamps live in the map -- reload them after every map change
        # (on the first call the panel does not exist yet).
        if hasattr(self, "terrain_panel"):
            # load() statt refresh(): die Vorschaubilder gehoeren zur alten
            # Karte und muessen mit den Tilesets verworfen werden.
            # load() instead of refresh(): the thumbnails belong to the old
            # map and must be dropped together with its tilesets.
            self.terrain_panel.load()
        if getattr(self, "_terrain_active", False):
            self._refresh_terrain_overlay()

    def _init_terrain(self):
        self._terrain_active = False
        self._terrain_brush = 1
        self._overlay_enabled = True
        self._overlay_mode = "speed"
        self._reset_terrain_state()

    def _set_overlay_options(self, enabled: bool, mode: str):
        """Schalter und Modus des Befahrbarkeits-Overlays uebernehmen.

        Apply the passability overlay's toggle and mode."""
        self._overlay_enabled = bool(enabled)
        self._overlay_mode = mode or "speed"
        if getattr(self, "_terrain_active", False):
            if self._overlay_enabled:
                self._refresh_terrain_overlay()
            else:
                self._clear_terrain_overlay()

    # ------------------------------------------------------------------
    # Aktivierung durch den Tab / activation from the tab

    def _set_terrain_mode(self, on: bool):
        """Gelaendemodus an/aus -- das Overlay haengt am Tab, nicht an einem
        eigenen Schalter.

        Terrain mode on/off -- the overlay follows the tab, not a separate
        toggle."""
        on = bool(on)
        if on == getattr(self, "_terrain_active", False):
            return
        self._terrain_active = on
        self.view.terrain_paint_enabled = on
        if on:
            # Platzier- und Auswahlzustand merken und beim Verlassen
            # wiederherstellen -- sonst ist nach einem Besuch im Gelaende-Tab
            # das Platzieren dauerhaft aus.
            # Remember the placement/selection state and restore it on the way
            # out -- otherwise placing stays off for good after one visit to
            # the terrain tab.
            self._placement_was_active = self._placement_active
            self._prev_rect_select = self.view.rect_select_enabled
            self._placement_active = False
            self._clear_placement_preview()
            self.view.rect_select_enabled = True
            self.view.setCursor(Qt.CrossCursor)
            self._refresh_terrain_overlay()
            self.statusBar().showMessage(tr("terrain.status_active"))
        else:
            self.view.rect_select_enabled = getattr(self, "_prev_rect_select", False)
            self.view.setCursor(Qt.ArrowCursor)
            self._clear_terrain_overlay()
            self._clear_terrain_preview()
            if getattr(self, "_placement_was_active", False):
                self._activate_placement()

    # ------------------------------------------------------------------
    # Kachelgrafiken / tile graphics

    def _tilesets(self):
        if self._tilesets_cache is None:
            self._tilesets_cache = {}
            for i, ts in enumerate(self.map.tileset_sources):
                if ts.filename:
                    try:
                        self._tilesets_cache[i] = load_tileset(
                            self.res.read_file(ts.filename + ".bmp"))
                    except Exception:
                        pass
        return self._tilesets_cache

    def _tile_pixmap(self, mapping_index: int) -> QPixmap | None:
        """32x32-Grafik zu einem TileMapping-Index (gepuffert).

        32x32 graphic for a tile mapping index (cached)."""
        cached = self._tile_pixmaps.get(mapping_index)
        if cached is not None:
            return cached
        try:
            m = self.map.tile_mappings[mapping_index]
        except IndexError:
            return None
        ts = self._tilesets().get(m.tileset_index)
        if ts is None or m.tile_graphic_index >= ts.num_tiles:
            return None
        block = ts.pixels[m.tile_graphic_index * TILE:(m.tile_graphic_index + 1) * TILE, :]
        rgb = np.ascontiguousarray(ts.palette[block][:, :, :3].astype(np.uint8))
        img = QImage(rgb.data, TILE, TILE, TILE * 3, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(img)
        self._tile_pixmaps[mapping_index] = pix
        return pix

    # ------------------------------------------------------------------
    # Stempeln / stamping

    def _paint_layers(self):
        """Malebenen der geladenen Karte, bei Bedarf aufgebaut."""
        if self.map is None:
            return None
        ebenen = getattr(self, "_layers", None)
        if ebenen is None or ebenen.map is not self.map:
            ebenen = PaintLayers(self.map)
            self._layers = ebenen
        return ebenen

    def _terrain_cells(self, tx: int, ty: int) -> list[tuple[int, int]]:
        """Zellen unter dem Pinsel -> [(x, y)].

        Runder Pinsel statt Quadrat: ein quadratischer Abdruck zeichnet sich
        als Stufe in die Klippenkante, ein runder nicht.

        Cells under the brush. A round brush rather than a square one: a square
        footprint prints itself as a step into the cliff edge, a round one
        does not.
        """
        if self.map is None or not hasattr(self, "terrain_panel"):
            return []
        if self.terrain_panel.selected_brush() in PUNKT_PINSEL:
            return [(tx, ty)]
        r = self.terrain_panel.brush_radius()
        halb = r // 2
        zellen = []
        for dy in range(-halb, halb + 1):
            for dx in range(-halb, halb + 1):
                if dx * dx + dy * dy > (halb + 0.5) ** 2:
                    continue
                x, y = tx + dx, ty + dy
                if 0 <= x < self.map.width and 0 <= y < self.map.height:
                    zellen.append((x, y))
        return zellen or [(tx, ty)]

    def _terrain_stamp(self, tx: int, ty: int):
        """Pinselstrich: Absicht in die Ebenen malen, Kacheln neu ableiten.

        Gemalt wird nicht die Kachel, sondern was dort sein soll. Die Kacheln
        rechnet `synth_region` daraus aus -- inklusive Klippenband an der neuen
        Hoehenkante, mit Zelltyp und passenden Nachbarn.

        A brush stroke paints intent into the layers, not tiles. `synth_region`
        derives the tiles from it, including the cliff band along the new
        height edge with its cell type and matching neighbours.
        """
        ebenen = self._paint_layers()
        if ebenen is None:
            return
        zellen = self._terrain_cells(tx, ty)
        if not zellen:
            return
        brush = self.terrain_panel.selected_brush()
        rechteck = ebenen.male(brush, zellen)
        if rechteck is None:
            return
        if brush == B_VULKAN:
            self._stempel_vulkan(rechteck, ebenen)
        aenderungen = ebenen.synth_region(rechteck)
        if not aenderungen:
            self._refresh_terrain_overlay()
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
        if not rueck:
            return
        self._mark_map_edited()
        self._push_undo("terrain", TerrainEdit(rueck))
        self._refresh_terrain_overlay()
        self.statusBar().showMessage(
            tr("terrain.status_painted", brush=tr(f"terrain.brush_{brush}"),
               n=len(rueck)))

    def _stempel_vulkan(self, rechteck, ebenen):
        """Vulkanstempel setzen -- der ist ein festes Bauteil, keine Flaeche."""
        import numpy as np
        mx = (rechteck[0] + rechteck[2]) // 2
        my = (rechteck[1] + rechteck[3]) // 2
        gitter = np.array([[self.map.tile_mapping_index(x, y)
                            for x in range(self.map.width)]
                           for y in range(self.map.height)], dtype=np.int32)
        mapgen._stamp_volcanoes(gitter, [(mx, my)], ebenen.tm, ebenen.rng)
        for y in range(max(0, my - 14), min(self.map.height, my + 15)):
            for x in range(max(0, mx - 14), min(self.map.width, mx + 15)):
                self.map.set_tile(x, y, int(gitter[y, x]),
                                  default_cell_type(int(gitter[y, x])))

    def _terrain_pick(self, tx: int, ty: int):
        """Rechtsklick: Pinsel auf das umschalten, was dort schon liegt.

        Right-click: switch the brush to whatever is already there."""
        ebenen = self._paint_layers()
        if ebenen is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
            return
        if ebenen.hoehe[ty, tx]:
            brush = B_HOCH
        else:
            fam = int(ebenen.familie[ty, tx])
            namen = ebenen.tm.families
            brush = namen[fam] if 0 <= fam < len(namen) else B_ERDE
        self.terrain_panel.set_brush(brush)
        self.statusBar().showMessage(
            tr("terrain.status_picked_brush", brush=tr(f"terrain.brush_{brush}")))

    def _chunk_entry(self, cx: int, cy: int):
        """Flicken-Kachelblock (cx,cy) holen oder aus der Karte herausschneiden.

        Get or cut out patch chunk (cx,cy) from the map."""
        from PySide6.QtCore import QRect
        key = (cx, cy)
        entry = self._patch_chunks.get(key)
        if entry is None:
            rect = QRect(cx * CHUNK_PX, cy * CHUNK_PX, CHUNK_PX, CHUNK_PX)
            pix = self._map_pixmap.copy(rect)
            item = self.scene.addPixmap(pix)
            item.setPos(cx * CHUNK_PX, cy * CHUNK_PX)
            item.setZValue(10)          # ueber der Karte, unter allem anderen
            entry = [pix, item]
            self._patch_chunks[key] = entry
        return entry

    def _repaint_tiles(self, coords):
        """Geaenderte Kacheln nachzeichnen.

        NICHT in das grosse Karten-Pixmap malen: ein QPainter darauf loest bei
        8192x8192 eine 268-MB-Kopie aus (~35 ms je Stempel). Stattdessen
        bekommen nur die betroffenen 256x256-Bloecke ein eigenes Bild-Element
        ueber der Karte.

        Repaint changed tiles. Do NOT paint into the large map pixmap: opening
        a QPainter on it forces a 268 MB copy at 8192x8192 (~35 ms per stamp).
        Only the affected 256x256 chunks get their own item above the map."""
        if getattr(self, "_map_pixmap", None) is None:
            return
        by_chunk: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for x, y in coords:
            by_chunk.setdefault((x // CHUNK_TILES, y // CHUNK_TILES), []).append((x, y))
        for (cx, cy), cells in by_chunk.items():
            pix, item = self._chunk_entry(cx, cy)
            painter = QPainter(pix)
            for x, y in cells:
                tile = self._tile_pixmap(self.map.tile_mapping_index(x, y))
                if tile is not None:
                    painter.drawPixmap(x * TILE - cx * CHUNK_PX,
                                       y * TILE - cy * CHUNK_PX, tile)
            painter.end()
            item.setPixmap(pix)
        # Zu viele Bloecke: einmalig in die Karte einbacken (ein teurer
        # Kopiervorgang statt unbegrenzt wachsendem Speicher).
        # Too many chunks: bake them into the map once (one expensive copy
        # instead of unbounded memory growth).
        if len(self._patch_chunks) > MAX_PATCH_CHUNKS:
            self._flush_patch_chunks()

    def _flush_patch_chunks(self):
        """Alle Flicken in das Karten-Pixmap uebernehmen und Elemente loeschen."""
        if not self._patch_chunks:
            return
        painter = QPainter(self._map_pixmap)
        for (cx, cy), (pix, item) in self._patch_chunks.items():
            painter.drawPixmap(cx * CHUNK_PX, cy * CHUNK_PX, pix)
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
        painter.end()
        self._patch_chunks.clear()
        if getattr(self, "_map_item", None) is not None:
            self._map_item.setPixmap(self._map_pixmap)

    def _repaint_tile(self, x: int, y: int):
        self._repaint_tiles([(x, y)])

    def _mark_map_edited(self):
        if not self.map_edited:
            self.map_edited = True
            self.statusBar().showMessage(tr("terrain.status_first_edit"))

    # ------------------------------------------------------------------
    # Overlay / passability overlay

    def _cell_grid(self) -> np.ndarray:
        """Zelltypen als (Hoehe, Breite)-Array.

        Die Kacheln liegen in vertikalen 32er-Streifen; die Umrechnung nach
        (y, x) wird einmal je Karte vorberechnet.

        Cell types as a (height, width) array. Tiles are stored in vertical
        32-column strips; the (y, x) mapping is computed once per map."""
        w, h = self.map.width, self.map.height
        cache = getattr(self, "_cell_cache", None)
        if cache is not None and cache.shape == (h, w):
            return cache
        grid = getattr(self, "_tile_index_grid", None)
        if grid is None or grid.shape != (h, w):
            ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
            grid = ((xs >> 5) * h + ys) * 32 + (xs & 0x1F)
            self._tile_index_grid = grid
        tiles = np.asarray(self.map.tiles, dtype=np.uint32)
        cache = (tiles[grid] & 0x1F).astype(np.uint8)
        self._cell_cache = cache
        return cache

    def _patch_cells(self, coords):
        """Geaenderte Zellen im Puffer nachziehen.

        Das komplette Array aus der Kachelliste neu aufzubauen kostet je
        Stempel ~35 ms; punktuelles Nachziehen ist praktisch gratis.

        Update changed cells in the cache. Rebuilding the whole array from the
        tile list costs ~35 ms per stamp; patching is practically free."""
        cache = getattr(self, "_cell_cache", None)
        if cache is None:
            return
        for x, y in coords:
            if 0 <= x < cache.shape[1] and 0 <= y < cache.shape[0]:
                cache[y, x] = self.map.cell_type(x, y)

    def _overlay_lut(self) -> np.ndarray:
        """Farbtabelle Zelltyp -> RGBA (32 Eintraege).

        Colour lookup table cell type -> RGBA (32 entries)."""
        blocked_only = getattr(self, "_overlay_mode", "speed") == "blocked"
        lut = np.zeros((32, 4), dtype=np.uint8)
        for cell in range(32):
            cls = speed_class(cell)
            # Hindernis-Modus: nur Sperren und Klippen einfaerben, alles
            # Befahrbare bleibt durchsichtig.
            # Obstacle mode: tint only blockers and cliffs, everything
            # passable stays clear.
            if blocked_only and cls not in (IMPASSABLE, CLIFF):
                continue
            r, g, b = SPEED_COLORS.get(cls, SPEED_COLORS[SPECIAL])
            lut[cell] = (r, g, b, 160 if blocked_only else OVERLAY_ALPHA)
        return lut

    def _terrain_overlay_pixmap(self) -> QPixmap:
        """Ein Pixel je Kachel -- die Skalierung uebernimmt die Szene.

        Ein Pixmap in voller Kachelaufloesung waere auf einer 256x256-Karte
        8192x8192 Pixel gross; das Item wird stattdessen um TILE skaliert.

        One pixel per tile -- the scene does the scaling. A pixmap at full
        tile resolution would be 8192x8192 on a 256x256 map; the item is
        scaled by TILE instead."""
        w, h = self.map.width, self.map.height
        if getattr(self, "_overlay_mode", "speed") == "height":
            # Hoehenansicht: beim Malen muss man sehen, wo Hochland liegt --
            # die Klippe ist nur die Kante davon, nicht die Flaeche.
            # Height view: while painting you have to see where the highland
            # is -- the cliff is only its edge, not the area.
            ebenen = self._paint_layers()
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            if ebenen is not None:
                hoch = ebenen.hoehe.astype(bool)
                rgba[hoch] = (200, 170, 90, 90)
                rgba[~hoch] = (60, 90, 120, 45)
            rgba = np.ascontiguousarray(rgba)
        else:
            rgba = np.ascontiguousarray(self._overlay_lut()[self._cell_grid()])
        img = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        return QPixmap.fromImage(img)

    def _refresh_terrain_overlay(self):
        if not getattr(self, "_terrain_active", False) or self.map is None:
            return
        if not getattr(self, "_overlay_enabled", True):
            self._clear_terrain_overlay()
            return
        pix = self._terrain_overlay_pixmap()
        item = getattr(self, "_terrain_overlay_item", None)
        if item is None:
            item = self.scene.addPixmap(pix)
            item.setZValue(900)
            item.setScale(TILE)
            self._terrain_overlay_item = item
        else:
            item.setPixmap(pix)

    def _clear_terrain_overlay(self):
        item = getattr(self, "_terrain_overlay_item", None)
        if item is not None:
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
            self._terrain_overlay_item = None

    # ------------------------------------------------------------------
    # Vorschau unter dem Mauszeiger / cursor preview

    def _update_terrain_preview(self, tx: int, ty: int):
        self._clear_terrain_preview()
        cells = self._terrain_cells(tx, ty)
        if not cells:
            return
        xs = [c[0] for c in cells]
        ys = [c[1] for c in cells]
        rect = QGraphicsRectItem(min(xs) * SCENE_TILE, min(ys) * SCENE_TILE,
                                 (max(xs) - min(xs) + 1) * SCENE_TILE,
                                 (max(ys) - min(ys) + 1) * SCENE_TILE)
        rect.setPen(QPen(QColor(255, 255, 255), 2, Qt.DashLine))
        rect.setZValue(1000)
        self.scene.addItem(rect)
        self._terrain_preview_item = rect

    def _clear_terrain_preview(self):
        item = getattr(self, "_terrain_preview_item", None)
        if item is not None:
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
            self._terrain_preview_item = None

    # ------------------------------------------------------------------
    # Rueckgaengig / undo

    def _apply_terrain_changes(self, edit: "TerrainEdit", forward: bool):
        for i, old, new in edit.changes:
            self.map.tiles[i] = new if forward else old
        self._redraw_terrain_cells(edit)
        self._mark_map_edited()
        self._refresh_terrain_overlay()

    def _redraw_terrain_cells(self, edit: "TerrainEdit"):
        """Betroffene Kacheln neu zeichnen (Index -> x/y zurueckrechnen)."""
        height = self.map.height
        coords = []
        for i, _old, _new in edit.changes:
            lower_x = i % 32
            rest = i // 32
            y = rest % height
            upper_x = rest // height
            coords.append((upper_x * 32 + lower_x, y))
        self._repaint_tiles(coords)
        self._patch_cells(coords)

    def _terrain_brush_step(self, delta: int):
        self._terrain_brush = max(1, min(15, self._terrain_brush + delta))
        if hasattr(self, "terrain_panel"):
            self.terrain_panel.set_brush_size(self._terrain_brush)
        self.statusBar().showMessage(tr("terrain.status_brush", n=self._terrain_brush))

    # ------------------------------------------------------------------
    # Speichern / saving

    # ------------------------------------------------------------------
    # Neue Karte erzeugen / generate a new map

    def _tile_average_colors(self, indices) -> np.ndarray:
        """Durchschnittsfarbe je Kachelgrafik -- fuer die schnelle Vorschau.

        Average colour per tile graphic -- for the fast preview."""
        tsets = self._tilesets()
        out = np.zeros((len(indices), 3), dtype=np.uint8)
        for row, idx in enumerate(indices):
            try:
                mapping = self.map.tile_mappings[int(idx)]
            except IndexError:
                continue
            ts = tsets.get(mapping.tileset_index)
            if ts is None or mapping.tile_graphic_index >= ts.num_tiles:
                continue
            block = ts.pixels[mapping.tile_graphic_index * TILE:
                              (mapping.tile_graphic_index + 1) * TILE, :]
            out[row] = ts.palette[block][:, :, :3].reshape(-1, 3).mean(axis=0)
        return out

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

    # ------------------------------------------------------------------
    # Lavafelder / lava fields

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
