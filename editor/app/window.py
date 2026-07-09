from __future__ import annotations

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


class EditorWindow(
    _MenuMixin, _SidebarMixin, _OverviewMixin,
    _PlacementMixin, _MapPickMixin, _ProjectMixin,
    _BuildMixin, _OverlaysMixin, QMainWindow,
):
    def __init__(self):
        super().__init__()
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

        self.scene = QGraphicsScene(self)
        self.view = MapView(self.scene)
        self.view.tileClicked.connect(self.on_place)
        self.view.tileRemoved.connect(self.on_remove)
        self.view.tileHover.connect(self._on_tile_hover)
        self.view.rectDragStarted.connect(self._rect_drag_start)
        self.view.rectDragMoved.connect(self._rect_drag_move)
        self.view.rectDragFinished.connect(self._rect_drag_finish)
        self.view.rectDragCanceled.connect(self._rect_drag_cancel)
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
        self.trigger_panel.load()
        self.groups_panel.load()
        self._build_overview()
        self._refresh_player_range()

        self.coord_label = QLabel("Tile: –")
        self.statusBar().addPermanentWidget(self.coord_label)
        self.statusBar().showMessage(tr("window.status_ready"))
        self.load_map(self.map_name)
        self._refresh_overview()
        QTimer.singleShot(0, self._maybe_reopen_last_mission)
