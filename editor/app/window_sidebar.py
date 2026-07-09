from __future__ import annotations

from .common import *
from .panels.trigger_panel import TriggerPanel
from .panels.groups_panel import GroupsPanel
from .panels.objects_panel import ObjectsPanel


class _SidebarMixin:
    def _build_sidebar(self):
        dock = QDockWidget(tr("window.dock_place"), self)
        # Breit genug fuer die Aktions-Formulare; per Splitter frei veraenderbar.
        # Wide enough for the action forms; freely resizable via the splitter.
        dock.setMinimumWidth(390)

        # --- Tab 0: Platzieren ---
        place_widget = self._build_place_widget()

        # --- Tab 1: Trigger ---
        self.trigger_panel = TriggerPanel(self)
        self.trigger_panel.map_pick_requested.connect(self._on_trigger_map_pick)

        # --- Tab 2: Gruppen ---
        self.groups_panel = GroupsPanel(self)
        self.groups_panel.rect_pick_requested.connect(self._begin_rect_pick)

        # --- Tab 3: Objekte ---
        self.objects_panel = ObjectsPanel(self)

        self._sidebar_tabs = QTabWidget()
        self._sidebar_tabs.addTab(place_widget, tr("window.tab_place"))
        self._sidebar_tabs.addTab(self.trigger_panel, tr("window.tab_triggers"))
        self._sidebar_tabs.addTab(self.groups_panel, tr("window.tab_groups"))
        self._sidebar_tabs.addTab(self.objects_panel, tr("window.tab_objects"))

        dock.setWidget(self._sidebar_tabs)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [560], Qt.Horizontal)
        self._fill_list(self.cat_combo.currentData())

    def _on_trigger_map_pick(self, request: dict):
        self._begin_action_pick(request)

    def _build_place_widget(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)

        lay.addWidget(QLabel(tr("window.lbl_category")))
        self.cat_combo = QComboBox()
        fill_combo(self.cat_combo, CATALOG, "catalog")
        self.cat_combo.currentIndexChanged.connect(lambda *_: self._fill_list(self.cat_combo.currentData()))
        lay.addWidget(self.cat_combo)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_place_selection_changed)
        self.list.itemClicked.connect(lambda _item: self._activate_placement())
        lay.addWidget(self.list, 1)

        # Spieler / Player
        self.player_row = QWidget()
        pr = QFormLayout(self.player_row)
        pr.setContentsMargins(0, 0, 0, 0)
        self.player_spin = QSpinBox()
        self.player_spin.setRange(0, 5)
        pr.addRow(tr("window.lbl_player"), self.player_spin)
        lay.addWidget(self.player_row)

        self.unit_name_row = QWidget()
        nr = QFormLayout(self.unit_name_row)
        nr.setContentsMargins(0, 0, 0, 0)
        self.unit_name_edit = QLineEdit()
        self.unit_name_edit.setPlaceholderText(tr("window.unit_name_placeholder"))
        nr.addRow(tr("window.lbl_unit_name"), self.unit_name_edit)
        lay.addWidget(self.unit_name_row)

        # Cargo-Truck-Parameter / Cargo truck parameters
        self.cargo_row = QWidget()
        cr = QFormLayout(self.cargo_row)
        cr.setContentsMargins(0, 0, 0, 0)
        self.cargo_combo = QComboBox()
        fill_combo(self.cargo_combo, TRUCK_CARGO, "truck_cargo")
        self.cargo_combo.setCurrentIndex(self.cargo_combo.findData("Leer"))
        self.cargo_amount = QSpinBox()
        self.cargo_amount.setRange(0, 5000)
        self.cargo_amount.setValue(1000)
        cr.addRow(tr("window.lbl_cargo"), self.cargo_combo)
        cr.addRow(tr("window.lbl_amount"), self.cargo_amount)
        lay.addWidget(self.cargo_row)

        # ConVec-Bausatz / ConVec kit
        self.kit_row = QWidget()
        kr = QFormLayout(self.kit_row)
        kr.setContentsMargins(0, 0, 0, 0)
        self.kit_combo = QComboBox()
        self.kit_combo.addItem(tr("window.empty"), None)
        for disp, mid, _ in STRUCTURES:
            self.kit_combo.addItem(disp, mid)
        kr.addRow(tr("window.lbl_kit"), self.kit_combo)
        lay.addWidget(self.kit_row)

        # Beacon-Parameter / Beacon parameters
        self.beacon_row = QWidget()
        br = QFormLayout(self.beacon_row)
        br.setContentsMargins(0, 0, 0, 0)
        self.ore_combo = QComboBox()
        fill_combo(self.ore_combo, ORE_TYPES, "ore_types")
        self.yield_combo = QComboBox()
        fill_combo(self.yield_combo, YIELDS, "yields")
        br.addRow(tr("window.lbl_ore_type"), self.ore_combo)
        br.addRow(tr("window.lbl_yield"), self.yield_combo)
        lay.addWidget(self.beacon_row)

        # Waffe (Kampffahrzeuge + Guard Post) / Weapon (combat vehicles + Guard Post)
        self.weapon_row = QWidget()
        wr = QFormLayout(self.weapon_row)
        wr.setContentsMargins(0, 0, 0, 0)
        self.weapon_combo = QComboBox()
        for d, m in WEAPONS:
            self.weapon_combo.addItem(d, m)
        wr.addRow(tr("window.lbl_weapon"), self.weapon_combo)
        lay.addWidget(self.weapon_row)

        lay.addWidget(QLabel(tr("window.sidebar_hint")))
        return panel

    def _fill_list(self, category):
        default_kind, items = CATALOG[category]
        self.list.clear()
        for item in items:
            disp, mid, fp = item[0], item[1], item[2]
            kind = item[3] if len(item) > 3 else default_kind
            it = QListWidgetItem(f"{disp}  ({fp[0]}×{fp[1]})" if fp != (1, 1) else disp)
            it.setData(Qt.UserRole, (kind, disp, mid, fp))
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self._update_params()

    def _selected(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _on_place_selection_changed(self, *_args):
        self._update_params()
        self._activate_placement()

    def _activate_placement(self):
        sel = self._selected()
        if not sel:
            self._placement_active = False
            self._clear_placement_preview()
            return
        self._placement_active = True
        if self._action_pick is None and self._rect_pick_group is None:
            self.view.setCursor(Qt.CrossCursor)
        kind, display, _map_id, _footprint = sel
        if kind in ("structure", "vehicle"):
            self.statusBar().showMessage(tr("window.status_place_active", display=display))

    def _cancel_placement(self):
        self._placement_active = False
        self._clear_placement_preview()
        if self._action_pick is None and self._rect_pick_group is None:
            self.view.setCursor(Qt.ArrowCursor)
        self.statusBar().showMessage(tr("window.status_place_deselected"))

    def _update_params(self):
        sel = self._selected()
        if not sel:
            self._placement_active = False
            self._clear_placement_preview()
            return
        kind, disp, mid, fp = sel
        is_struct_or_veh = kind in ("structure", "vehicle")
        self.player_row.setVisible(is_struct_or_veh)
        self.unit_name_row.setVisible(is_struct_or_veh)
        self.cargo_row.setVisible(mid == "mapCargoTruck")
        self.kit_row.setVisible(mid == "mapConVec")
        self.beacon_row.setVisible(mid == "mapMiningBeacon")
        self.weapon_row.setVisible(mid in WEAPON_UNITS)

    def _refresh_player_range(self):
        self.player_spin.setMaximum(max(0, len(self.players) - 1))
