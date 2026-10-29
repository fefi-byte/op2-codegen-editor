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
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsEllipseItem
from celltypes import (
    CLIFF, EDITABLE_CELL_TYPES, FAST, IMPASSABLE, MEDIUM, SLOW, SPECIAL,
    default_cell_type, speed_class,
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
OVERLAY_ALPHA = 110

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
        if getattr(self, "_terrain_active", False):
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
        ebenen = getattr(self, "_layers", None)
        if (ebenen is None or ebenen.map is not self.map
                or getattr(self, "_layers_marke", None) != marke):
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
        # Nur der erste Aufruf eines Strichs zaehlt als Klick. Der
        # Klippenpinsel setzt sonst bei jeder Mausbewegung einen Punkt.
        # Only a stroke's first call counts as a click, otherwise the cliff
        # brush would add a point on every mouse move.
        self._klick_neu = True

    def _terrain_strich_abschliessen(self):
        """Ende des Strichs: einmal rechnen und alles auf einmal setzen."""
        rechteck = getattr(self, "_strich_rechteck", None)
        gesammelt = getattr(self, "_strich_rueck", [])
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
            self._rand_nachziehen(ebenen, [])

    def _rand_nachziehen(self, ebenen, gesammelt):
        """Nach dem Strich einmal ohne Schutz rechnen -- fuer die Innenkante."""
        bereich = ebenen.strich_beenden()
        if bereich is None:
            return gesammelt
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
            self._strich_rueck = getattr(self, "_strich_rueck", []) + rueck
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
        if getattr(self, "_strich_offen", False):
            # Kleiner Pinsel rechnet live mit, grosser sammelt. Gemessen
            # braucht ein Strich beim Ziehen 51 ms bei Pinsel 11 und 114 ms
            # bei 21 -- darueber ruckelt es sichtbar, also wird dann erst beim
            # Loslassen gerechnet.
            # A small brush computes live, a large one collects. Measured, a
            # drag step takes 51 ms at brush 11 and 114 ms at 21 -- above that
            # it stutters visibly, so it is computed on release instead.
            if self.terrain_panel.brush_radius() > LIVE_GRENZE:
                vorher = getattr(self, "_strich_rechteck", None)
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

    # ------------------------------------------------------------------
    # Live-Vorschau der Klippe / live cliff preview

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
