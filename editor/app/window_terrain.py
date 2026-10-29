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

import sys

import numpy as np

from .common import *
from celltypes import (
    CLIFF, FAST, IMPASSABLE, MEDIUM, SLOW, SPECIAL, default_cell_type,
    speed_class,
)
from tileset import TILE, load_tileset
import mapgen
from .paint_layers import PaintLayers, B_ERDE, B_VULKAN, B_KLIPPE
from .panels.terrain_panel import PUNKT_PINSEL

# Live-Vorschau der Klippe: so lange muss die Maus stillstehen, bevor
# gerechnet wird. Der Loeser braucht im Median gut 20 ms; ohne Pause wuerde
# jede Mausbewegung eine Rechnung anstossen, die beim naechsten Pixel schon
# veraltet ist.
# Live cliff preview: the mouse has to rest this long before computing.
KLIPPEN_LIVE_VERZOEGERUNG = 60      # ms
KLIPPEN_LIVE_DECKKRAFT = 0.85

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
OVERLAY_ALPHA = 75             # war 110: zu bunt, die Kacheln verschwanden

# Groesse der Nachzeichen-Bloecke (in Kacheln bzw. Pixeln) und Obergrenze,
# ab der sie in die Karte eingebacken werden.
# Size of the repaint chunks (in tiles resp. pixels) and the limit at which
# they get baked into the map.
# Bis zu dieser Pinselgroesse wird waehrend des Ziehens live gerechnet.
# Up to this brush size the tiles are computed live while dragging.
LIVE_GRENZE = 21

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
        if self._terrain_active:
            self._refresh_terrain_overlay()

    def _init_terrain(self):
        self._terrain_active = False
        self._strich_rechteck = None
        self._strich_offen = False
        self._klippen_punkte = []
        self._klippen_items = []
        self._klippen_live_items = []
        self._klippen_live_ziel = None
        self._klippen_live_schluessel = None
        self._klippen_live_timer = QTimer(self)
        self._klippen_live_timer.setSingleShot(True)
        self._klippen_live_timer.setInterval(KLIPPEN_LIVE_VERZOEGERUNG)
        self._klippen_live_timer.timeout.connect(self._klippen_live_rechnen)
        self._klick_neu = False
        self._terrain_brush = 1
        self._overlay_enabled = True
        self._overlay_mode = "speed"
        self._reset_terrain_state()

    def _set_overlay_options(self, enabled: bool, mode: str):
        """Schalter und Modus des Befahrbarkeits-Overlays uebernehmen.

        Apply the passability overlay's toggle and mode."""
        self._overlay_enabled = bool(enabled)
        self._overlay_mode = mode or "speed"
        if self._terrain_active:
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
        if on == self._terrain_active:
            return
        self._terrain_active = on
        self.view.terrain_paint_enabled = on
        if not on:
            self._klippen_live_weg()
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
            self.view.rect_select_enabled = self._prev_rect_select
            self.view.setCursor(Qt.ArrowCursor)
            self._clear_terrain_overlay()
            self._clear_terrain_preview()
            if self._placement_was_active:
                self._activate_placement()
        self._gelaende_banner_aktualisieren()

    def _gelaende_banner_aktualisieren(self):
        """Ein Schild oben links auf der Karte, solange Gelaende gemalt wird.

        Ob man gerade Gelaende veraendert oder Objekte setzt, war nur an der
        Statuszeile zu erkennen. Das Schild nennt auch den Pinsel.
        A badge in the map's top-left corner while terrain is being painted,
        naming the brush.
        """
        banner = getattr(self.view, "_gelaende_banner", None)
        if not self._terrain_active:
            if banner is not None:
                banner.hide()
            return
        if banner is None:
            banner = QLabel(self.view)
            banner.setObjectName("gelaende_banner")
            banner.setStyleSheet(
                "QLabel#gelaende_banner { background: rgba(250, 179, 135, 215);"
                " color: #1e1e2e; font-weight: bold; padding: 4px 10px;"
                " border-radius: 4px; }")
            banner.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            banner.move(12, 12)
            self.view._gelaende_banner = banner
        pinsel = self.terrain_panel.selected_brush()
        banner.setText(tr("window.terrain_banner",
                          brush=tr(f"terrain.brush_{pinsel}")))
        banner.adjustSize()
        banner.show()
        banner.raise_()

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
                    except Exception as e:  # Kacheln dieses Satzes bleiben leer
                        print(f"Tileset {ts.filename}.bmp nicht ladbar: {e}",
                              file=sys.stderr)
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
        # Nicht nur auf ein anderes Kartenobjekt pruefen, sondern auf einen
        # anderen INHALT. "Neue Karte" schreibt in dasselbe Op2Map-Objekt --
        # die Pruefung auf Objektgleichheit ging deshalb gut, und der Pinsel
        # arbeitete anschliessend mit den Hoehen- und Biomebenen der ALTEN
        # Karte. Beim Malen kam dadurch voelliger Unsinn heraus.
        # Do not only check for a different map object but for different
        # CONTENT. "New map" writes into the same Op2Map object, so the identity
        # check passed and the brush then worked with the height and biome
        # layers of the OLD map, producing complete nonsense while painting.
        marke = (id(self.map), len(self.map.tiles),
                 int(sum(self.map.tiles[::97])))
        ebenen = self._layers
        if (ebenen is None or ebenen.map is not self.map
                or self._layers_marke != marke):
            ebenen = PaintLayers(self.map)
            self._layers = ebenen
            self._layers_marke = marke
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

    def _terrain_strich_beginnen(self):
        """Anfang eines Pinselstrichs."""
        self._strich_rechteck = None
        self._strich_rueck = []
        self._strich_offen = True
        ebenen = self._paint_layers()
        if ebenen is not None:
            ebenen.strich_beginnen()
        # Nur der erste Aufruf eines Strichs zaehlt als Klick. Der
        # Klippenpinsel setzt sonst bei jeder Mausbewegung einen Punkt.
        # Only a stroke's first call counts as a click, otherwise the cliff
        # brush would add a point on every mouse move.
        self._klick_neu = True

    def _terrain_strich_abschliessen(self):
        """Ende des Strichs: einmal rechnen und alles auf einmal setzen."""
        rechteck = self._strich_rechteck
        gesammelt = self._strich_rueck
        self._strich_rechteck = None
        self._strich_rueck = []
        self._strich_offen = False
        ebenen = self._paint_layers()
        if rechteck is None:
            # Live gerechnet -- nur noch den gesammelten Strich in die
            # Rueckgaengig-Kette legen.
            # Computed live -- only the collected stroke still goes into the
            # undo chain.
            if ebenen is not None:
                gesammelt = self._rand_nachziehen(ebenen, gesammelt)
            if gesammelt:
                self._push_undo("terrain", TerrainEdit(gesammelt))
            return
        if ebenen is None:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            aenderungen = ebenen.synth_region(rechteck)
            self._terrain_uebernehmen(aenderungen, tr("terrain.brush_"
                                                      + self.terrain_panel.selected_brush()))
        finally:
            QApplication.restoreOverrideCursor()
            # Schutz nur fuer die Dauer des Strichs -- sonst blieben alle je
            # gemalten Zellen fuer immer von der Mischzone ausgenommen. Danach
            # den Bereich einmal ohne Schutz nachrechnen, damit die Grenze auch
            # auf der Innenseite eine Uebergangskachel bekommt.
            # Protection only for the duration of the stroke, otherwise every
            # cell ever painted would stay excluded from the blend zone.
            # Afterwards recompute the area once without protection so the
            # border gets a transition tile on its inner side as well.
            rest = self._rand_nachziehen(ebenen, [])
            if rest:
                # Rand und geschlossene Klippenenden ebenfalls rueckgaengig
                # machbar -- bisher fielen sie aus der Kette.
                self._push_undo("terrain", TerrainEdit(rest))

    def _rand_nachziehen(self, ebenen, gesammelt):
        """Nach dem Strich einmal ohne Schutz rechnen -- fuer die Innenkante."""
        bereich = ebenen.strich_beenden()
        if bereich is None:
            return gesammelt
        # Hat der Strich eine Klippe durchschnitten, die Enden schliessen,
        # BEVOR der Rand nachgerechnet wird -- der richtet dann den Boden an den
        # neuen Enden mit aus.
        # If the stroke cut through a cliff, close the ends BEFORE recomputing
        # the rim, which then also fixes the ground at the new ends.
        schnitt, schnitt_bereich = ebenen.klippen_schnitte_schliessen()
        if schnitt:
            gesammelt = self._aenderungen_schreiben(schnitt, gesammelt)
            bx0, by0, bx1, by1 = bereich
            sx0, sy0, sx1, sy1 = schnitt_bereich
            bereich = (min(bx0, sx0), min(by0, sy0), max(bx1, sx1), max(by1, sy1))
        aenderungen = ebenen.synth_region(bereich)
        if not aenderungen:
            return gesammelt
        for x, y, kachel, zelltyp in aenderungen:
            i = self.map.tile_index(x, y)
            alt = self.map.tiles[i]
            self.map.set_tile(x, y, kachel, zelltyp)
            if self.map.tiles[i] != alt:
                gesammelt = list(gesammelt) + [(i, alt, self.map.tiles[i])]
        coords = [(x, y) for x, y, _, _ in aenderungen]
        self._repaint_tiles(coords)
        self._patch_cells(coords)
        self._refresh_terrain_overlay()
        return gesammelt

    def _aenderungen_schreiben(self, aenderungen, gesammelt):
        """Kacheln in die Karte schreiben, zeichnen, Rueckgaengig-Daten sammeln."""
        for x, y, kachel, zelltyp in aenderungen:
            i = self.map.tile_index(x, y)
            alt = self.map.tiles[i]
            self.map.set_tile(x, y, kachel, zelltyp)
            if self.map.tiles[i] != alt:
                gesammelt = list(gesammelt) + [(i, alt, self.map.tiles[i])]
        coords = [(x, y) for x, y, _, _ in aenderungen]
        self._repaint_tiles(coords)
        self._patch_cells(coords)
        return gesammelt

    def _uebergaenge_aufraeumen(self):
        """Alle Uebergangskacheln der Karte neu bestimmen.

        Nuetzlich nach dem Laden einer fremden Karte oder nach vielen
        Einzelstrichen: der Aufruf leitet jede Uebergangskachel aus dem
        Familienfeld ab und ersetzt die, an deren Stelle gar keine Grenze
        liegt, durch reinen Boden.

        Recompute every transition tile of the map. Useful after loading a
        foreign map or after many individual strokes: derives each transition
        tile from the family field and replaces those sitting where there is no
        border at all with pure ground.
        """
        import celltypes as _ct
        ebenen = self._paint_layers()
        if ebenen is None:
            return
        h, w = self.map.height, self.map.width
        gitter = np.array([[self.map.tile_mapping_index(x, y) for x in range(w)]
                           for y in range(h)], dtype=np.int32)
        vorher = gitter.copy()
        anzahl = mapgen.nachbearbeite_uebergaenge(
            gitter, ebenen.familie, ebenen.tm, ebenen.rng)
        ys, xs = np.nonzero(gitter != vorher)
        aenderungen = [(int(x), int(y), int(gitter[y, x]),
                        int(_ct.default_cell_type(int(gitter[y, x]))))
                       for y, x in zip(ys.tolist(), xs.tolist())]
        self._terrain_uebernehmen(aenderungen, tr("terrain.btn_aufraeumen"))
        self.statusBar().showMessage(
            tr("terrain.aufgeraeumt", n=len(aenderungen)), 4000)

    def _terrain_uebernehmen(self, aenderungen, was: str, sammeln: bool = False):
        """Berechnete Kacheln setzen, zeichnen und in die Rueckgaengig-Kette."""
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
        if sammeln:
            # Waehrend eines Strichs sammeln -- sonst entstuende je
            # Mausschritt ein eigener Rueckgaengig-Eintrag.
            # Collect during a stroke, otherwise every mouse step would produce
            # its own undo entry.
            self._strich_rueck = self._strich_rueck + rueck
        else:
            self._push_undo("terrain", TerrainEdit(rueck))
        self._refresh_terrain_overlay()
        self.statusBar().showMessage(
            tr("terrain.status_painted", brush=was, n=len(rueck)))

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
        if brush == B_KLIPPE:
            self._klippe_punkt(tx, ty)
            return
        rechteck = ebenen.male(brush, zellen)
        if rechteck is None:
            return
        if brush == B_VULKAN:
            self._stempel_vulkan(rechteck, ebenen)

        # Waehrend des Ziehens nur die Ebenen malen und den Bereich merken.
        # Das Ableiten der Kacheln dauert bei grossem Pinsel ueber eine
        # Sekunde -- bei jeder Mausbewegung waere das unbenutzbar. Gerechnet
        # wird einmal beim Loslassen.
        # While dragging, only paint the layers and remember the region.
        # Deriving the tiles takes over a second with a large brush -- doing
        # that on every mouse move would be unusable. It is computed once on
        # release.
        if self._strich_offen:
            # Kleiner Pinsel rechnet live mit, grosser sammelt. Gemessen
            # braucht ein Strich beim Ziehen 51 ms bei Pinsel 11 und 114 ms
            # bei 21 -- darueber ruckelt es sichtbar, also wird dann erst beim
            # Loslassen gerechnet.
            # A small brush computes live, a large one collects. Measured, a
            # drag step takes 51 ms at brush 11 and 114 ms at 21 -- above that
            # it stutters visibly, so it is computed on release instead.
            if self.terrain_panel.brush_radius() > LIVE_GRENZE:
                vorher = self._strich_rechteck
                if vorher is None:
                    self._strich_rechteck = tuple(rechteck)
                else:
                    a, b, c, d = vorher
                    self._strich_rechteck = (min(a, rechteck[0]), min(b, rechteck[1]),
                                             max(c, rechteck[2]), max(d, rechteck[3]))
                self._update_terrain_preview(tx, ty)
                return
            self._terrain_uebernehmen(ebenen.synth_region(rechteck),
                                      tr(f"terrain.brush_{brush}"), sammeln=True)
            self._update_terrain_preview(tx, ty)
            return
        aenderungen = ebenen.synth_region(rechteck)
        ebenen.strich_beenden()
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

    # ------------------------------------------------------------------
    # Klippenlinie / cliff line

    # ------------------------------------------------------------------
    # Live-Vorschau der Klippe / live cliff preview

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
        # Auch auf Hochland wird der BODEN aufgenommen. Frueher schaltete es
        # dort auf den Hochland-Pinsel um -- den gibt es nicht mehr, und die
        # Hoehe ist ohnehin nichts, was man aufnehmen und weitermalen koennte.
        # On highland the GROUND is picked too: it used to switch to the
        # highland brush, which no longer exists.
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
        if self._map_pixmap is None:
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
        if self._map_item is not None:
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
        cache = self._cell_cache
        if cache is not None and cache.shape == (h, w):
            return cache
        grid = self._tile_index_grid
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
        cache = self._cell_cache
        if cache is None:
            return
        for x, y in coords:
            if 0 <= x < cache.shape[1] and 0 <= y < cache.shape[0]:
                cache[y, x] = self.map.cell_type(x, y)

    def _overlay_lut(self) -> np.ndarray:
        """Farbtabelle Zelltyp -> RGBA (32 Eintraege).

        Colour lookup table cell type -> RGBA (32 entries)."""
        blocked_only = self._overlay_mode == "blocked"
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
        if self._overlay_mode == "height":
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
        if not self._terrain_active or self.map is None:
            return
        if not self._overlay_enabled:
            self._clear_terrain_overlay()
            return
        pix = self._terrain_overlay_pixmap()
        item = self._terrain_overlay_item
        if item is None:
            item = self.scene.addPixmap(pix)
            item.setZValue(900)
            item.setScale(TILE)
            self._terrain_overlay_item = item
        else:
            item.setPixmap(pix)

    def _clear_terrain_overlay(self):
        item = self._terrain_overlay_item
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
        if self.terrain_panel.selected_brush() == B_KLIPPE:
            self._klippen_zielring(tx, ty)
            return
        self._klippen_live_weg()
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
        item = self._terrain_preview_item
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

    # ------------------------------------------------------------------
    # Lavafelder / lava fields
