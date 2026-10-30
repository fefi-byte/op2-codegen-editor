from __future__ import annotations

import sys

from .common import *
from .placed_object import PlacedObject
from .mapview import MapView
from .window_menu import _MenuMixin
from .window_sidebar import _SidebarMixin
from .window_overview import _OverviewMixin
from .window_placement import _PlacementMixin
from .window_map_pick import _MapPickMixin
from .window_project import _ProjectMixin
from .window_build import _BuildMixin
from .window_overlays import _OverlaysMixin
from .window_terrain import _TerrainMixin
from .window_klippen import _KlippenMixin
from .window_neukarte import _NeueKarteMixin
from .verlauf import _VerlaufMixin
from .window_mission import _MissionMixin


class EditorWindow(
    _MenuMixin, _SidebarMixin, _OverviewMixin,
    _PlacementMixin, _MapPickMixin, _ProjectMixin,
    _BuildMixin, _OverlaysMixin, _TerrainMixin, _KlippenMixin,
    _NeueKarteMixin, _VerlaufMixin, _MissionMixin, QMainWindow,
):
    def _zustand_anlegen(self):
        """Jeden Zustand des Fensters VOR allem anderen anlegen.

        Frueher fragten die Mixins verstreut `getattr(self, "_x", Standard)`,
        weil nicht sicher war, ob ein Wert schon existiert. Das verschleierte
        Fehler in der Startreihenfolge (die Klippenvorschau kam so nie an).
        Jetzt existiert alles ab der ersten Zeile; die `_init_*`-Methoden
        setzen danach ihre eigentlichen Werte.

        Create every piece of window state before anything else, instead of
        scattered `getattr(self, "_x", default)` calls in the mixins.
        """
        self._action_pick = None
        self._cell_cache = None
        self._did_initial_fit = False
        self._klick_neu = False
        self._klippen_items = []
        self._klippen_live_items = []
        self._klippen_live_timer = None
        self._klippen_punkte = []
        self._klippen_warm = False
        self._lava_brush_cursor_item = None
        self._lava_field_items = []
        self._layers = None
        self._layers_marke = None
        self._map_item = None
        self._map_pixmap = None
        self._map_search_folder = None
        self._object_dialog_open = False
        self._overlay_enabled = True
        self._overlay_mode = "speed"
        self._placement_active = False
        self._placement_was_active = False
        self._prev_rect_select = False
        self._rect_pick_group = None
        self._redo_stack = None
        self._strich_offen = False
        self._strich_rechteck = None
        self._strich_rueck = []
        self._terrain_active = False
        self._terrain_overlay_item = None
        self._terrain_preview_item = None
        self._tile_index_grid = None
        self._undo_stack = None
        self._view_menu = None
        self.verlauf_liste = None
        # Neues Layout / new layout (window_mission.py)
        self.outline = None
        self._titel = None
        self._bearbeitung = None
        self._modus = "mission"
        self._auswahl = None
        self._auswahl_items = []
        self._zug = None
        self._letzter_klick = (None, 0.0)
        self._objekte_sichtbar = True
        self._overlay_typ = None
        self.zeitleiste = None

    def __init__(self):
        super().__init__()
        self._zustand_anlegen()
        self.setWindowTitle(tr("window.app_title"))
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1250, 870)

        try:
            self.res = FolderResources(OP2_DIR)
            if not self.res.names():
                raise FileNotFoundError(f"keine .map-Dateien unter {self.res.root}")
        except Exception as e:
            QMessageBox.critical(
                self, tr("window.op2_not_found_title"),
                tr("window.op2_not_found_text", e=e, path=appconfig.CONFIG_PATH))
            raise SystemExit(1)
        self.map = None
        self.map_name = "cm02.map"
        self.mission_name = "Editor Mission"
        self.mission_type: MissionType = MissionType.Colony
        self.tech_tree: str = "MULTITEK.TXT"
        self.briefing: str = ""
        self.custom_code: str = ""
        self.custom_actions: list = []
        self.campaign: str = ""            # "" | "eden" | "plymouth"
        self.campaign_mission: int = 1
        self.max_tech_level: int = 12
        self.diff_setup: DifficultySetup = DifficultySetup()
        self.variables: list[VariableDef] = []
        self.players: list[PlayerSpec] = [PlayerSpec()]
        self.objects: list[PlacedObject] = []
        self.victories: list[Condition] = []
        self.defeats: list[Condition] = []
        self.triggers: list[TriggerDef] = []
        self.building_groups: list[BuildingGroupSpec] = []
        self.reinforce_groups: list[ReinforceGroupSpec] = []
        self.fight_groups: list[FightGroupSpec] = []
        self.mining_groups: list[MiningGroupSpec] = []
        self.node_positions: dict = {}
        self.mapgen_params: dict | None = None
        self.spawn_points: list = []
        self.volcano_points: list = []
        self.lava_fields: list = []
        self.newmap_panel = None
        self.mission_folder: Path | None = None
        self._next_object_id = 1
        self._pending_trigger_index = 0
        self._pending_action_index = -1

        self.output_dir = DEFAULT_OUTPUT_DIR
        self.dll_name = DEFAULT_DLL_NAME
        self._placement_active = False
        self._placement_preview_items = []
        self._init_overlays()
        self._init_undo()
        self._init_terrain()

        self.scene = QGraphicsScene(self)
        self.view = MapView(self.scene)
        self.view.tileClicked.connect(self.on_place)
        self.view.tileRemoved.connect(self.on_remove)
        self.view.brushSizeStep.connect(self._lava_brush_step)
        self.view.tileHover.connect(self._on_tile_hover)
        self.view.rectDragStarted.connect(self._rect_drag_start)
        self.view.rectDragMoved.connect(self._rect_drag_move)
        self.view.rectDragFinished.connect(self._rect_drag_finish)
        self.view.rectDragCanceled.connect(self._rect_drag_cancel)
        self.view.zoomChanged.connect(self._on_zoom_changed)
        self.view.tileDragged.connect(self._karte_ziehen)
        self.view.tileReleased.connect(self._karte_loslassen)
        self.setCentralWidget(self.view)
        self._rect_pick_group = None
        self._rect_pick_start = None
        self._rect_pick_item = None
        self._action_pick = None
        self._action_pick_start = None
        self._action_preview_items = []
        self._planned_items = []

        self._build_menu()
        self._build_sidebar()
        self.terrain_panel.load()
        self.trigger_panel.load()
        self.groups_panel.load()
        self.conditions_panel.load()
        self._build_overview()
        self._build_verlauf()
        self._refresh_player_range()
        # Rechte Docks sind im neuen Layout aus; ueber "Ansicht" erreichbar.
        # The right docks are off in the new layout; reachable via "View".
        for d in (self.overview_dock, self.verlauf_dock, self.validation_dock):
            d.hide()
        self._baue_ebenenleiste()

        # Klick auf den Zaehler blendet die Validierung ein oder aus.
        # Clicking the counter shows or hides the validation dock.
        self.validation_label = QPushButton("")
        self.validation_label.setFlat(True)
        self.validation_label.setCursor(Qt.PointingHandCursor)
        self.validation_label.setToolTip(tr("window.validation_toggle_hint"))
        self.validation_label.clicked.connect(
            lambda: self.validation_dock.setVisible(not self.validation_dock.isVisible()))
        self.statusBar().addPermanentWidget(self.validation_label)
        self.zoom_label = QLabel("")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.coord_label = QLabel("Tile: –")
        self.statusBar().addPermanentWidget(self.coord_label)
        self.statusBar().showMessage(tr("window.status_ready"))
        self.load_map(self.map_name)
        self._refresh_overview()
        self._layout_wiederherstellen()
        QTimer.singleShot(0, self._maybe_reopen_last_mission)

    # Fenstergroesse und Docks (sichtbar, Breite, Position) ueberdauern den
    # Neustart. Window size and docks survive a restart.
    _LAYOUT_VERSION = 2

    def _einstellungen(self):
        from PySide6.QtCore import QSettings
        return QSettings("OP2MissionEditor", "Editor")

    @staticmethod
    def _layout_merken() -> bool:
        # Nicht in Tests/ohne Bildschirm: sonst haengt ein Testlauf vom
        # Fensterlayout des vorigen ab. Not in headless test runs.
        return QApplication.platformName() != "offscreen"

    def _layout_wiederherstellen(self):
        if not self._layout_merken():
            return
        s = self._einstellungen()
        geo = s.value("fenster/geometrie")
        zustand = s.value("fenster/docks")
        try:
            if geo is not None:
                self.restoreGeometry(geo)
            if zustand is not None:
                self.restoreState(zustand, self._LAYOUT_VERSION)
        except Exception as e:                       # kaputter Eintrag: Standard
            print(f"Fensterlayout nicht wiederhergestellt: {e}", file=sys.stderr)

    def closeEvent(self, event):
        if self._layout_merken():
            s = self._einstellungen()
            s.setValue("fenster/geometrie", self.saveGeometry())
            s.setValue("fenster/docks", self.saveState(self._LAYOUT_VERSION))
        super().closeEvent(event)

    def showEvent(self, event):
        """Karte erst einpassen, wenn das Fenster seine endgueltige Groesse hat.

        Fit the map only once the window has its final size -- the fit inside
        __init__ still runs against the pre-maximised viewport."""
        super().showEvent(event)
        if not self._did_initial_fit:
            self._did_initial_fit = True
            QTimer.singleShot(0, self.view.zoom_fit)

    def _on_zoom_changed(self, scale: float):
        """Zoomabhaengige Anzeige nachziehen (Beschriftungen + Statusleiste).

        Update zoom-dependent display (labels + status bar)."""
        self._update_label_zoom()
        if hasattr(self, "zoom_label"):
            self.zoom_label.setText(tr("window.status_zoom", pct=round(scale * 100)))
