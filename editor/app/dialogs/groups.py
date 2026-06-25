from __future__ import annotations
from ..common import *


class GroupsDialog(QDialog):
    """Gruppen verwalten: MiningGroup, BuildingGroup und ReinforceGroup.

    EN: Manage groups: MiningGroup, BuildingGroup and ReinforceGroup.
    """
    def __init__(self, parent, mining_groups, building_groups, reinforce_groups, objects, player_count):
        super().__init__(parent)
        self.setWindowTitle(tr("groups.window_title"))
        self.resize(880, 560)
        self.groups = (
            [MiningGroupSpec(**asdict(g)) for g in mining_groups] +
            [BuildingGroupSpec(**asdict(g)) for g in building_groups] +
            [
                ReinforceGroupSpec(
                    name=g.name,
                    player=g.player,
                    unit_ids=list(g.unit_ids),
                    targets=[ReinforceTargetSpec(**asdict(t)) for t in g.targets],
                )
                for g in reinforce_groups
            ]
        )
        self.objects = list(objects)
        self._idx = -1
        self._loading = False
        self.rect_pick_request: int | None = None

        # Knotenpositionen / platzierte Objekte nach map_id fuer die Gruppen-Dropdowns auswaehlen.
        # EN: Each comprehension selects placed objects by map_id to populate the group-type dropdowns.
        self.mines = [o for o in self.objects if o.map_id in ("mapCommonOreMine", "mapRareOreMine")]
        self.smelters = [o for o in self.objects if o.map_id in ("mapCommonOreSmelter", "mapRareOreSmelter")]
        self.trucks = [o for o in self.objects if o.map_id == "mapCargoTruck"]
        self.builders = [
            o for o in self.objects
            if o.map_id in ("mapStructureFactory", "mapVehicleFactory", "mapConVec", "mapEarthworker")
        ]
        self.reinforce_factories = [
            o for o in self.objects
            if o.map_id in ("mapVehicleFactory", "mapArachnidFactory")
        ]

        self.glist = QListWidget()
        self.glist.currentRowChanged.connect(self._on_select)
        add_mining = QPushButton(tr("groups.add_mining")); add_mining.clicked.connect(self._add_mining)
        add_building = QPushButton(tr("groups.add_building")); add_building.clicked.connect(self._add_building)
        add_reinforce = QPushButton(tr("groups.add_reinforce")); add_reinforce.clicked.connect(self._add_reinforce)
        rm = QPushButton(tr("groups.remove")); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(QLabel(tr("groups.groups_label"))); left.addWidget(self.glist, 1)
        left.addWidget(add_mining); left.addWidget(add_building); left.addWidget(add_reinforce); left.addWidget(rm)

        self.name = QLineEdit()
        self.gtype = QComboBox(); self.gtype.addItems(["MiningGroup", "BuildingGroup", "ReinforceGroup"]); self.gtype.setEnabled(False)
        self.player = QSpinBox(); self.player.setRange(0, max(0, player_count - 1))
        self.mine = QComboBox()
        self.smelter = QComboBox()
        self.rect_x = QSpinBox(); self.rect_x.setRange(0, 1023)
        self.rect_y = QSpinBox(); self.rect_y.setRange(0, 1023)
        self.rect_w = QSpinBox(); self.rect_w.setRange(1, 256); self.rect_w.setValue(8)
        self.rect_h = QSpinBox(); self.rect_h.setRange(1, 256); self.rect_h.setValue(8)
        pick_rect = QPushButton(tr("groups.pick_rect"))
        pick_rect.clicked.connect(self._pick_rect)
        self.pick_rect = pick_rect
        self.unit_list = QListWidget()
        self.target_text = QPlainTextEdit()
        self.target_text.setPlaceholderText(tr("groups.target_placeholder"))
        self.target_text.setMaximumHeight(120)

        self._fill_object_combo(self.mine, self.mines)
        self._fill_object_combo(self.smelter, self.smelters)

        self.form = QFormLayout()
        self.form.addRow(tr("groups.row_name"), self.name)
        self.form.addRow(tr("groups.row_type"), self.gtype)
        self.form.addRow(tr("groups.row_player"), self.player)
        self.form.addRow(tr("groups.row_mine"), self.mine)
        self.form.addRow(tr("groups.row_smelter"), self.smelter)
        self.form.addRow(tr("groups.row_rect_x"), self.rect_x)
        self.form.addRow(tr("groups.row_rect_y"), self.rect_y)
        self.form.addRow(tr("groups.row_rect_width"), self.rect_w)
        self.form.addRow(tr("groups.row_rect_height"), self.rect_h)
        self.form.addRow("", pick_rect)
        self.form.addRow(tr("groups.row_units"), self.unit_list)
        self.form.addRow(tr("groups.row_targets"), self.target_text)

        self.name.textChanged.connect(self._store_current)
        for w in (self.player, self.rect_x, self.rect_y, self.rect_w, self.rect_h):
            w.valueChanged.connect(self._store_current)
        for w in (self.mine, self.smelter):
            w.currentIndexChanged.connect(self._store_current)
        self.unit_list.itemChanged.connect(self._store_current)
        self.target_text.textChanged.connect(self._store_current)

        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(self.form, 2)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self._refresh_list()
        if self.groups:
            self.glist.setCurrentRow(0)
        else:
            self._set_form_enabled(False)

    def mining_groups(self):
        return [g for g in self.groups if isinstance(g, MiningGroupSpec)]

    def building_groups(self):
        return [g for g in self.groups if isinstance(g, BuildingGroupSpec)]

    def reinforce_groups(self):
        return [g for g in self.groups if isinstance(g, ReinforceGroupSpec)]

    def _fill_object_combo(self, combo, objects):
        combo.clear()
        combo.addItem(tr("groups.combo_empty"), "")
        for o in objects:
            combo.addItem(self._object_label(o), o.uid)

    def _object_label(self, o):
        name = f"{o.unit_name}: " if o.unit_name else ""
        return f"{name}{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})"

    def _summary(self, group):
        if isinstance(group, MiningGroupSpec):
            return mining_group_summary(group)
        if isinstance(group, ReinforceGroupSpec):
            return reinforce_group_summary(group)
        return building_group_summary(group)

    def _set_form_enabled(self, on):
        for w in (self.name, self.player, self.mine, self.smelter, self.rect_x,
                  self.rect_y, self.rect_w, self.rect_h, self.unit_list, self.target_text):
            w.setEnabled(on)

    def _refresh_list(self):
        self.glist.blockSignals(True)
        cur = self.glist.currentRow()
        self.glist.clear()
        for group in self.groups:
            self.glist.addItem(self._summary(group))
        if 0 <= cur < len(self.groups):
            self.glist.setCurrentRow(cur)
        self.glist.blockSignals(False)

    def _on_select(self, row):
        if not (0 <= row < len(self.groups)):
            self._idx = -1
            self._set_form_enabled(False)
            return
        self._set_form_enabled(True)
        self._idx = row
        self._load(row)

    def _add_mining(self):
        smelter = self.smelters[0] if self.smelters else None
        player = smelter.player if smelter else 0
        rect_x = max(0, smelter.tile_x - 3) if smelter else 0
        rect_y = max(0, smelter.tile_y - 3) if smelter else 0
        group = MiningGroupSpec(
            name=f"MiningGroup{len(self.mining_groups()) + 1}",
            player=player,
            has_setup=False,
            mine_x=0, mine_y=0,
            smelter_x=0, smelter_y=0,
            rect_x=rect_x, rect_y=rect_y,
            rect_width=8, rect_height=8,
            truck_ids=[o.uid for o in self.trucks if o.player == player],
        )
        self.groups.append(group)
        self._refresh_list()
        self.glist.setCurrentRow(len(self.groups) - 1)

    def _add_building(self):
        group = BuildingGroupSpec(
            name=f"BuildingGroup{len(self.building_groups()) + 1}",
            player=0,
            rect_x=0, rect_y=0,
            rect_width=8, rect_height=8,
            unit_ids=[o.uid for o in self.builders if o.player == 0],
        )
        self.groups.append(group)
        self._refresh_list()
        self.glist.setCurrentRow(len(self.groups) - 1)

    def _add_reinforce(self):
        group = ReinforceGroupSpec(
            name=f"ReinforceGroup{len(self.reinforce_groups()) + 1}",
            player=0,
            unit_ids=[o.uid for o in self.reinforce_factories if o.player == 0],
            targets=[
                ReinforceTargetSpec(group.name, 1500)
                for group in self.mining_groups() + self.building_groups()
            ],
        )
        self.groups.append(group)
        self._refresh_list()
        self.glist.setCurrentRow(len(self.groups) - 1)

    def _remove(self):
        if not (0 <= self._idx < len(self.groups)):
            return
        del self.groups[self._idx]
        self._idx = -1
        self._refresh_list()
        if self.groups:
            self.glist.setCurrentRow(min(self.glist.currentRow(), len(self.groups) - 1))
        else:
            self._set_form_enabled(False)

    def _pick_rect(self):
        if not (0 <= self._idx < len(self.groups)):
            return
        self._store_current()
        self.rect_pick_request = self._idx
        self.accept()

    def _load(self, i):
        group = self.groups[i]
        is_mining = isinstance(group, MiningGroupSpec)
        is_reinforce = isinstance(group, ReinforceGroupSpec)
        self._loading = True
        self.name.setText(group.name)
        if is_mining:
            self.gtype.setCurrentText("MiningGroup")
        elif is_reinforce:
            self.gtype.setCurrentText("ReinforceGroup")
        else:
            self.gtype.setCurrentText("BuildingGroup")
        self.player.setValue(group.player)
        self.form.setRowVisible(self.mine, is_mining)
        self.form.setRowVisible(self.smelter, is_mining)
        for widget in (self.rect_x, self.rect_y, self.rect_w, self.rect_h, self.pick_rect):
            self.form.setRowVisible(widget, not is_reinforce)
        self.form.setRowVisible(self.target_text, is_reinforce)
        if is_mining:
            self._select_combo_by_pos(self.mine, self.mines, group.mine_x, group.mine_y)
            self._select_combo_by_pos(self.smelter, self.smelters, group.smelter_x, group.smelter_y)
            if not getattr(group, "has_setup", True):
                self.mine.setCurrentIndex(0)
                self.smelter.setCurrentIndex(0)
        if not is_reinforce:
            self.rect_x.setValue(group.rect_x)
            self.rect_y.setValue(group.rect_y)
            self.rect_w.setValue(group.rect_width)
            self.rect_h.setValue(group.rect_height)
        else:
            self.target_text.setPlainText(self._targets_to_text(group.targets))
        self._refresh_units(group)
        self._loading = False

    def _select_combo_by_pos(self, combo, objects, x, y):
        for i, o in enumerate(objects, start=1):
            if o.tile_x == x and o.tile_y == y:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

    def _refresh_units(self, group):
        self.unit_list.blockSignals(True)
        self.unit_list.clear()
        if isinstance(group, MiningGroupSpec):
            objects = self.trucks
            selected = set(group.truck_ids)
        elif isinstance(group, ReinforceGroupSpec):
            objects = self.reinforce_factories
            selected = set(group.unit_ids)
        else:
            objects = self.builders
            selected = set(group.unit_ids)
        for o in objects:
            item = QListWidgetItem(self._object_label(o))
            item.setData(Qt.UserRole, o.uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if o.uid in selected else Qt.Unchecked)
            self.unit_list.addItem(item)
        self.unit_list.blockSignals(False)

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.groups)):
            return
        group = self.groups[self._idx]
        if isinstance(group, MiningGroupSpec):
            fallback = "MiningGroup"
        elif isinstance(group, ReinforceGroupSpec):
            fallback = "ReinforceGroup"
        else:
            fallback = "BuildingGroup"
        group.name = self.name.text().strip() or f"{fallback}{self._idx + 1}"
        group.player = self.player.value()
        if isinstance(group, MiningGroupSpec):
            mine = self._object_by_uid(self.mine.currentData())
            smelter = self._object_by_uid(self.smelter.currentData())
            group.has_setup = bool(mine and smelter)
            if mine:
                group.mine_x, group.mine_y = mine.tile_x, mine.tile_y
            if smelter:
                group.smelter_x, group.smelter_y = smelter.tile_x, smelter.tile_y
        if not isinstance(group, ReinforceGroupSpec):
            group.rect_x = self.rect_x.value()
            group.rect_y = self.rect_y.value()
            group.rect_width = self.rect_w.value()
            group.rect_height = self.rect_h.value()
        selected = []
        for i in range(self.unit_list.count()):
            item = self.unit_list.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        if isinstance(group, MiningGroupSpec):
            group.truck_ids = selected
        else:
            group.unit_ids = selected
        if isinstance(group, ReinforceGroupSpec):
            group.targets = self._targets_from_text(self.target_text.toPlainText())
        item = self.glist.item(self._idx)
        if item:
            item.setText(self._summary(group))

    def _targets_to_text(self, targets):
        return "\n".join(f"{target.group_name}={target.priority}" for target in targets)

    def _targets_from_text(self, text):
        targets = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "=" in line:
                name, priority_text = line.split("=", 1)
            elif ":" in line:
                name, priority_text = line.split(":", 1)
            else:
                name, priority_text = line, "1000"
            name = name.strip()
            if not name:
                continue
            try:
                priority = int(priority_text.strip())
            except ValueError:
                priority = 1000
            targets.append(ReinforceTargetSpec(name, priority))
        return targets

    def _object_by_uid(self, uid):
        for o in self.objects:
            if o.uid == uid:
                return o
        return None


