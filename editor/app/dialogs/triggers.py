from __future__ import annotations
from ..common import *
from .action_editor import ActionListWidget


class TriggersDialog(QDialog):
    """Benutzerdefinierte Trigger: Bedingung + Aktionen, mit Laufzeit-Erstellung.

    Custom triggers: a condition plus a list of actions, with runtime creation
    of further triggers supported.
    """
    def __init__(
        self, parent, triggers, building_groups=None, target_groups=None,
        reinforce_groups=None, mining_groups=None, objects=None, initial_trigger_index=0,
        initial_action_index=-1,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("triggers.title"))
        self.resize(900, 620)
        self.triggers = [self._copy(t) for t in triggers]
        self.building_groups = list(building_groups or [])
        self.mining_groups = list(mining_groups or [])
        self.objects = list(objects or [])
        self.trucks = [o for o in self.objects if o.map_id == "mapCargoTruck"]
        self.target_groups = list(target_groups or self.building_groups)
        self.reinforce_groups = list(reinforce_groups or [])
        self.target_group_types = {
            group.name: (
                "MiningGroup" if isinstance(group, MiningGroupSpec)
                else "BuildingGroup" if isinstance(group, BuildingGroupSpec)
                else "FightGroup"
            )
            for group in self.target_groups
        }
        self._idx = -1
        self._initial_trigger_index = initial_trigger_index
        self._initial_action_index = initial_action_index
        self._loading = False
        self.map_pick_request = None

        # --- Trigger-Liste ---
        # --- Trigger list ---
        self.tlist = QListWidget()
        self.tlist.currentRowChanged.connect(self._on_select)
        add = QPushButton(tr("triggers.btn_add_trigger")); add.clicked.connect(self._add)
        rm = QPushButton(tr("triggers.btn_remove_trigger")); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(QLabel(tr("triggers.lbl_trigger_list"))); left.addWidget(self.tlist, 1)
        left.addWidget(add); left.addWidget(rm)

        # --- Trigger-Eigenschaften ---
        # --- Trigger properties ---
        self.name = QLineEdit()
        self.at_start = QCheckBox(tr("triggers.chk_at_start"))
        self.one_shot = QCheckBox(tr("triggers.chk_one_shot"))
        self.cond = QComboBox(); fill_combo(self.cond, TRIGGER_CONDITIONS, "trigger_conditions")
        self.cond.currentIndexChanged.connect(self._update_cond_fields)
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.marks = QSpinBox(); self.marks.setRange(0, 200000); self.marks.setValue(100)
        self.count = QSpinBox(); self.count.setRange(0, 1000); self.count.setValue(1)
        self.compare = QComboBox(); self.compare.addItems(COMPARE.keys())
        self.tech_id = QSpinBox(); self.tech_id.setRange(0, 20000)
        self.resource = QComboBox(); self.resource.addItems(RESOURCES.keys())
        self.amount = QSpinBox(); self.amount.setRange(0, 1000000); self.amount.setValue(1000)
        self.building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.building.addItem(d, m)
        self.x = QSpinBox(); self.x.setRange(0, 1023)
        self.y = QSpinBox(); self.y.setRange(0, 1023)
        self.width = QSpinBox(); self.width.setRange(1, 256); self.width.setValue(4)
        self.height = QSpinBox(); self.height.setRange(1, 256); self.height.setValue(4)

        self.form = QFormLayout()
        self.form.addRow(tr("triggers.lbl_name"), self.name)
        self.form.addRow(self.at_start)
        self.form.addRow(self.one_shot)
        self.form.addRow(tr("triggers.lbl_condition"), self.cond)
        # Feldname -> zugehoeriges Widget; Sichtbarkeit wird je nach gewaehlter
        # Bedingungsart durch _update_cond_fields() umgeschaltet.
        # Maps a field name -> its widget; visibility is toggled per selected
        # condition kind by _update_cond_fields().
        self._cond_rows = {
            "player": self.player, "marks": self.marks, "count": self.count,
            "compare": self.compare, "tech_id": self.tech_id, "resource": self.resource,
            "amount": self.amount, "building": self.building,
            "x": self.x, "y": self.y, "width": self.width, "height": self.height,
        }
        clabels = {"player": tr("triggers.lbl_player"), "marks": tr("triggers.lbl_marks"),
                   "count": tr("triggers.lbl_count"),
                   "compare": tr("triggers.lbl_compare"), "tech_id": tr("triggers.lbl_tech_id"),
                   "resource": tr("triggers.lbl_resource"),
                   "amount": tr("triggers.lbl_amount"), "building": tr("triggers.lbl_building"),
                   "x": tr("triggers.lbl_x"), "y": tr("triggers.lbl_y"),
                   "width": tr("triggers.lbl_width"), "height": tr("triggers.lbl_height")}
        for key, w in self._cond_rows.items():
            self.form.addRow(clabels[key], w)

        self.name.textChanged.connect(self._store_current)
        for w in (self.cond, self.compare, self.resource, self.building):
            w.currentIndexChanged.connect(self._store_current)
        for w in (self.player, self.marks, self.count, self.tech_id, self.amount,
                  self.x, self.y, self.width, self.height):
            w.valueChanged.connect(self._store_current)
        for w in (self.at_start, self.one_shot):
            w.toggled.connect(self._store_current)

        # --- Aktionen ---
        # --- Actions ---
        self.alist = QListWidget(); self.alist.setMaximumHeight(120)
        self.alist.currentRowChanged.connect(self._on_action_select)
        self.act_kind = QComboBox(); fill_combo(self.act_kind, ACTION_KINDS, "action_kinds")
        self.act_kind.currentIndexChanged.connect(self._update_action_fields)
        self.act_text = QLineEdit(tr("triggers.act_text_default"))
        self.act_unit = QComboBox()
        for d, m in ALL_UNITS:
            self.act_unit.addItem(d, m)
        self.act_vehicle = QComboBox()
        for d, m in VEHICLE_UNITS:
            self.act_vehicle.addItem(d, m)
        self.act_weapon = QComboBox()
        for d, m in WEAPONS:
            self.act_weapon.addItem(d, m)
        self.act_target_count = QSpinBox(); self.act_target_count.setRange(0, 1000); self.act_target_count.setValue(1)
        self.act_priority = QSpinBox(); self.act_priority.setRange(1, 65535); self.act_priority.setValue(1000)
        self.act_ore = QComboBox()
        fill_combo(self.act_ore, MINING_OPERATION_ORES, "mining_ores")
        self.act_rect_x = QSpinBox(); self.act_rect_x.setRange(0, 1023)
        self.act_rect_y = QSpinBox(); self.act_rect_y.setRange(0, 1023)
        self.act_rect_w = QSpinBox(); self.act_rect_w.setRange(1, 256); self.act_rect_w.setValue(8)
        self.act_rect_h = QSpinBox(); self.act_rect_h.setRange(1, 256); self.act_rect_h.setValue(8)
        self.act_truck_count = QSpinBox(); self.act_truck_count.setRange(0, 50); self.act_truck_count.setValue(0)
        self.act_mining_group = QComboBox()
        for group in self.mining_groups:
            self.act_mining_group.addItem(f"{group.name} [MiningGroup]", group.name)
        self.act_x = QSpinBox(); self.act_x.setRange(0, 1023)
        self.act_y = QSpinBox(); self.act_y.setRange(0, 1023)
        self.act_x2 = QSpinBox(); self.act_x2.setRange(0, 1023)
        self.act_y2 = QSpinBox(); self.act_y2.setRange(0, 1023)
        self.act_player = QSpinBox(); self.act_player.setRange(0, 5)
        self.act_target = QComboBox()
        self.act_group = QComboBox()
        for group in self.building_groups:
            self.act_group.addItem(f"{group.name} [BuildingGroup]", group.name)
        self.act_target_group = QComboBox()
        for group in self.target_groups:
            group_type = self.target_group_types.get(group.name, "BuildingGroup")
            self.act_target_group.addItem(f"{group.name} [{group_type}]", group.name)
        self.act_target_group.currentIndexChanged.connect(self._update_set_targ_vehicle_options)
        self.act_source_group = QComboBox()
        for group in self.reinforce_groups:
            self.act_source_group.addItem(f"{group.name} [ReinforceGroup]", group.name)
        # Zielgruppe fuer "Gebaeude einer Gruppe zuweisen": jede Gruppe (Mining/Building/Reinforce)
        # Target group for "assign building to a group": any group (Mining/Building/Reinforce)
        self.act_assign_group = QComboBox()
        for group in self.mining_groups:
            self.act_assign_group.addItem(f"{group.name} [MiningGroup]", group.name)
        for group in self.building_groups:
            self.act_assign_group.addItem(f"{group.name} [BuildingGroup]", group.name)
        for group in self.reinforce_groups:
            self.act_assign_group.addItem(f"{group.name} [ReinforceGroup]", group.name)
        self.act_building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.act_building.addItem(d, m)
        self.act_wall = QComboBox()
        for d, m, _ in WALL_ITEMS:
            if m != "mapTube":
                self.act_wall.addItem(d, m)
        self.act_form = QFormLayout()
        self.act_form.addRow(tr("triggers.lbl_action_kind"), self.act_kind)
        # Feldname -> zugehoeriges Widget; Sichtbarkeit wird je nach gewaehlter
        # Aktionsart durch _update_action_fields() umgeschaltet.
        # Maps a field name -> its widget; visibility is toggled per selected
        # action kind by _update_action_fields().
        self._act_rows = {"text": self.act_text, "unit": self.act_unit,
                          "vehicle": self.act_vehicle, "weapon": self.act_weapon,
                          "target_count": self.act_target_count, "priority": self.act_priority,
                          "ore": self.act_ore,
                          "rect_x": self.act_rect_x, "rect_y": self.act_rect_y,
                          "rect_w": self.act_rect_w, "rect_h": self.act_rect_h,
                          "truck_count": self.act_truck_count,
                          "mining_group": self.act_mining_group,
                          "x": self.act_x,
                          "y": self.act_y, "x2": self.act_x2, "y2": self.act_y2,
                          "player": self.act_player, "target": self.act_target,
                          "target_group": self.act_target_group,
                          "source_group": self.act_source_group,
                          "assign_group": self.act_assign_group,
                          "group": self.act_group, "building": self.act_building,
                          "wall": self.act_wall}
        alabels = {"text": tr("triggers.lbl_text"), "unit": tr("triggers.lbl_unit"),
                   "vehicle": tr("triggers.lbl_vehicle"),
                   "weapon": tr("triggers.lbl_weapon_cargo"), "target_count": tr("triggers.lbl_target_count"),
                   "priority": tr("triggers.lbl_priority"),
                   "ore": tr("triggers.lbl_ore"), "rect_x": tr("triggers.lbl_smelter_rect_x"),
                   "rect_y": tr("triggers.lbl_smelter_rect_y"), "rect_w": tr("triggers.lbl_smelter_rect_w"),
                   "rect_h": tr("triggers.lbl_smelter_rect_h"), "truck_count": tr("triggers.lbl_truck_count"),
                   "mining_group": "MiningGroup:",
                   "x": tr("triggers.lbl_x_mine_x"), "y": tr("triggers.lbl_y_mine_y"),
                   "x2": tr("triggers.lbl_x2_smelter_x"), "y2": tr("triggers.lbl_y2_smelter_y"),
                   "player": tr("triggers.lbl_player"),
                   "target": tr("triggers.lbl_target_trigger"), "group": "BuildingGroup:",
                   "target_group": tr("triggers.lbl_target_group"), "source_group": "ReinforceGroup:",
                   "assign_group": tr("triggers.lbl_target_group"),
                   "building": tr("triggers.lbl_building"), "wall": tr("triggers.lbl_wall_tube")}
        for key, w in self._act_rows.items():
            self.act_form.addRow(alabels[key], w)
        add_act = QPushButton(tr("triggers.btn_add_action")); add_act.clicked.connect(self._add_action)
        self.pick_on_map = QPushButton(tr("triggers.btn_pick_action_on_map"))
        self.pick_on_map.clicked.connect(self._pick_action_on_map)
        self.act_form.addRow("", self.pick_on_map)
        self.pick_mining_mine = QPushButton(tr("triggers.btn_pick_mine_on_map"))
        self.pick_mining_mine.clicked.connect(lambda: self._pick_mining_operation_on_map("mine"))
        self.act_form.addRow("", self.pick_mining_mine)
        self.pick_mining_smelter = QPushButton(tr("triggers.btn_pick_smelter_on_map"))
        self.pick_mining_smelter.clicked.connect(lambda: self._pick_mining_operation_on_map("smelter"))
        self.act_form.addRow("", self.pick_mining_smelter)
        self.pick_mining_rect = QPushButton(tr("triggers.btn_pick_smelter_rect_on_map"))
        self.pick_mining_rect.clicked.connect(lambda: self._pick_mining_operation_on_map("rect"))
        self.act_form.addRow("", self.pick_mining_rect)
        update_act = QPushButton(tr("triggers.btn_update_action")); update_act.clicked.connect(self._update_action)
        rm_act = QPushButton(tr("triggers.btn_remove_action")); rm_act.clicked.connect(self._remove_action)
        act_btns = QHBoxLayout(); act_btns.addWidget(add_act); act_btns.addWidget(update_act); act_btns.addWidget(rm_act)

        # --- IF-Bedingungen pro Aktion ---
        # --- Per-action IF conditions ---
        self._act_conditions = []
        self.cond_logic = QComboBox(); self.cond_logic.addItems([tr("triggers.logic_and"), tr("triggers.logic_or")])
        self.cond_list = QListWidget(); self.cond_list.setMaximumHeight(90)
        self.cc_kind = QComboBox(); fill_combo(self.cc_kind, ACTION_CONDITION_KINDS, "action_conditions")
        self.cc_kind.currentIndexChanged.connect(self._update_cc_fields)
        self.cc_player = QSpinBox(); self.cc_player.setRange(0, 5)
        self.cc_building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.cc_building.addItem(d, m)
        self.cc_x = QSpinBox(); self.cc_x.setRange(0, 1023)
        self.cc_y = QSpinBox(); self.cc_y.setRange(0, 1023)
        self.cc_compare = QComboBox(); self.cc_compare.addItems(COMPARE.keys())
        self.cc_value = QSpinBox(); self.cc_value.setRange(0, 1000000)
        self.cc_resource = QComboBox(); self.cc_resource.addItems(RESOURCES.keys())
        self.cc_tech = QSpinBox(); self.cc_tech.setRange(0, 20000)
        self.cc_negate = QCheckBox(tr("triggers.chk_negate"))
        self.cc_form = QFormLayout()
        self.cc_form.addRow(tr("triggers.lbl_cond_kind"), self.cc_kind)
        # Feldname -> zugehoeriges Widget; Sichtbarkeit wird je nach gewaehlter
        # Bedingungsart durch _update_cc_fields() umgeschaltet.
        # Maps a field name -> its widget; visibility is toggled per selected
        # condition kind by _update_cc_fields().
        self._cc_rows = {"player": self.cc_player, "building": self.cc_building,
                         "x": self.cc_x, "y": self.cc_y, "compare": self.cc_compare,
                         "value": self.cc_value, "resource": self.cc_resource, "tech_id": self.cc_tech}
        cclabels = {"player": tr("triggers.lbl_player"), "building": tr("triggers.lbl_building"),
                    "x": tr("triggers.lbl_x"), "y": tr("triggers.lbl_y"),
                    "compare": tr("triggers.lbl_compare"), "value": tr("triggers.lbl_value"),
                    "resource": tr("triggers.lbl_resource"),
                    "tech_id": tr("triggers.lbl_tech_id")}
        for k, w in self._cc_rows.items():
            self.cc_form.addRow(cclabels[k], w)
        self.cc_form.addRow("", self.cc_negate)
        add_cond = QPushButton(tr("triggers.btn_add_cond")); add_cond.clicked.connect(self._add_act_condition)
        rm_cond = QPushButton(tr("triggers.btn_remove_cond")); rm_cond.clicked.connect(self._remove_act_condition)
        cond_btns = QHBoxLayout(); cond_btns.addWidget(add_cond); cond_btns.addWidget(rm_cond)

        # Reiter "Bedingung": Trigger-Identitaet + Bedingung + deren Parameter
        # "Condition" tab: trigger identity + condition + its parameters
        cond_tab = QWidget()
        cond_layout = QVBoxLayout(cond_tab)
        cond_layout.addLayout(self.form)
        cond_layout.addStretch(1)

        # Reiter "Aktionen": verschachtelter Karten-Editor (Wenn/Dann/Sonst)
        # "Actions" tab: nested card editor (When/Then/Else)
        act_tab = QWidget()
        act_layout = QVBoxLayout(act_tab)
        act_layout.addWidget(QLabel(tr("triggers.lbl_actions_hint")))
        self.act_scroll = QScrollArea(); self.act_scroll.setWidgetResizable(True)
        act_layout.addWidget(self.act_scroll, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(cond_tab, tr("triggers.tab_condition"))
        self.tabs.addTab(act_tab, tr("triggers.tab_actions"))

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addWidget(self.tabs, 2)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self._refresh_list()
        if self.triggers:
            self.tlist.setCurrentRow(max(0, min(self._initial_trigger_index, len(self.triggers) - 1)))
            if self._initial_action_index >= 0:
                self.tabs.setCurrentIndex(1)  # direkt zum Aktionen-Reiter
                # jump straight to the Actions tab
        else:
            self._set_form_enabled(False)

    def _action_ctx(self):
        all_groups = ([(g.name, "MiningGroup") for g in self.mining_groups]
                      + [(g.name, "BuildingGroup") for g in self.building_groups]
                      + [(g.name, "ReinforceGroup") for g in self.reinforce_groups])
        return {
            "triggers": self.triggers,
            "building_groups": self.building_groups,
            "mining_groups": self.mining_groups,
            "reinforce_groups": self.reinforce_groups,
            "target_groups": self.target_groups,
            "target_group_types": self.target_group_types,
            "all_groups": all_groups,
        }

    @staticmethod
    def _copy(t):
        d = asdict(t)
        acts = [action_from_dict(a) for a in d.pop("actions", [])]
        return TriggerDef(actions=acts, **d)

    def _set_form_enabled(self, on):
        for w in list(self._cond_rows.values()) + [self.name, self.at_start, self.one_shot,
                                                    self.cond, self.alist]:
            w.setEnabled(on)

    # --- Trigger-Liste ---
    # --- Trigger list ---
    def _refresh_list(self):
        self.tlist.blockSignals(True)
        cur = self.tlist.currentRow()
        self.tlist.clear()
        for t in self.triggers:
            self.tlist.addItem(trigger_summary(t))
        if 0 <= cur < len(self.triggers):
            self.tlist.setCurrentRow(cur)
        self.tlist.blockSignals(False)

    def _on_select(self, row):
        if not (0 <= row < len(self.triggers)):
            self._idx = -1
            self._set_form_enabled(False)
            return
        self._set_form_enabled(True)
        self._idx = row
        self._load(row)

    def _add(self):
        name = f"Trigger{len(self.triggers) + 1}"
        self.triggers.append(TriggerDef(name=name))
        self._refresh_list()
        self.tlist.setCurrentRow(len(self.triggers) - 1)

    def _remove(self):
        if not (0 <= self._idx < len(self.triggers)):
            return
        del self.triggers[self._idx]
        self._idx = -1
        self._refresh_list()
        if self.triggers:
            self.tlist.setCurrentRow(min(self.tlist.currentRow(), len(self.triggers) - 1))
        else:
            self._set_form_enabled(False)

    # --- Eigenschaften laden/speichern ---
    # --- Load/store properties ---
    def _load(self, i):
        t = self.triggers[i]
        self._loading = True
        self.name.setText(t.name)
        self.at_start.setChecked(t.enabled_at_start)
        self.one_shot.setChecked(t.one_shot)
        label = {v[0]: k for k, v in TRIGGER_CONDITIONS.items()}.get(t.condition, "Zeit (Marks)")
        self.cond.setCurrentIndex(self.cond.findData(label))
        self.player.setValue(t.player); self.marks.setValue(t.marks)
        self.count.setValue(t.count)
        self.compare.setCurrentText({v: k for k, v in COMPARE.items()}.get(t.compare, "≥"))
        self.tech_id.setValue(t.tech_id)
        self.resource.setCurrentText({v: k for k, v in RESOURCES.items()}.get(t.resource, "Common Ore"))
        self.amount.setValue(t.amount)
        bidx = self.building.findData(t.building)
        if bidx >= 0:
            self.building.setCurrentIndex(bidx)
        self.x.setValue(t.x); self.y.setValue(t.y)
        self.width.setValue(t.width); self.height.setValue(t.height)
        self._loading = False
        self._update_cond_fields()
        self.act_scroll.setWidget(ActionListWidget(t.actions, self._action_ctx()))

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.triggers)):
            return
        t = self.triggers[self._idx]
        t.name = self.name.text() or f"Trigger{self._idx + 1}"
        t.enabled_at_start = self.at_start.isChecked()
        t.one_shot = self.one_shot.isChecked()
        t.condition = TRIGGER_CONDITIONS[self.cond.currentData()][0]
        t.player = self.player.value(); t.marks = self.marks.value()
        t.count = self.count.value(); t.compare = COMPARE[self.compare.currentText()]
        t.tech_id = self.tech_id.value()
        t.resource = RESOURCES[self.resource.currentText()]
        t.amount = self.amount.value(); t.building = self.building.currentData()
        t.x = self.x.value(); t.y = self.y.value()
        t.width = self.width.value(); t.height = self.height.value()
        item = self.tlist.item(self._idx)
        if item:
            item.setText(trigger_summary(t))

    def _update_cond_fields(self):
        fields = TRIGGER_CONDITIONS[self.cond.currentData()][1]
        for key, w in self._cond_rows.items():
            self.form.setRowVisible(w, key in fields)

    # --- Aktionen ---
    # --- Actions ---
    def _refresh_actions(self):
        self.alist.clear()
        if not (0 <= self._idx < len(self.triggers)):
            return
        for a in self.triggers[self._idx].actions:
            self.alist.addItem(action_summary(a))
        # Ziel-Trigger-Auswahl aktualisieren (andere Trigger)
        # Refresh the target-trigger selection (the other triggers)
        self.act_target.clear()
        for t in self.triggers:
            if t is not self.triggers[self._idx]:
                self.act_target.addItem(t.name, t.name)

    def _set_combo_data(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_action_kind(self, kind):
        for label, value in ACTION_KINDS.items():
            if value == kind:
                self.act_kind.setCurrentIndex(self.act_kind.findData(label))
                return

    def _on_action_select(self, row):
        if not (0 <= self._idx < len(self.triggers)):
            return
        actions = self.triggers[self._idx].actions
        if not (0 <= row < len(actions)):
            return
        self._load_action(actions[row])

    def _load_action(self, action):
        self._set_action_kind(action.kind)
        self.act_text.setText(action.text)
        self._set_combo_data(self.act_unit, action.unit_type)
        self._set_combo_data(self.act_weapon, action.weapon_type)
        self._set_combo_data(self.act_vehicle, action.unit_type)
        self.act_target_count.setValue(action.target_count)
        self.act_priority.setValue(action.reinforce_priority)
        self.act_x.setValue(action.x)
        self.act_y.setValue(action.y)
        self.act_x2.setValue(action.x2)
        self.act_y2.setValue(action.y2)
        self.act_rect_x.setValue(action.rect_x)
        self.act_rect_y.setValue(action.rect_y)
        self.act_rect_w.setValue(action.rect_width)
        self.act_rect_h.setValue(action.rect_height)
        self.act_truck_count.setValue(getattr(action, "truck_count", 0))
        self.act_player.setValue(action.player)
        self._set_combo_data(self.act_target, action.target)
        self._set_combo_data(self.act_group, action.group_name)
        self._set_combo_data(self.act_target_group, action.group_name)
        self._set_combo_data(self.act_assign_group, action.group_name)
        self._set_combo_data(self.act_mining_group, action.mining_group_name)
        self._set_combo_data(self.act_source_group, action.source_group_name)
        self._set_combo_data(self.act_building, action.building_type)
        self._set_combo_data(self.act_wall, action.wall_type)
        ore_label = {value: label for label, value in MINING_OPERATION_ORES.items()}.get(action.ore_type)
        if ore_label:
            self.act_ore.setCurrentIndex(self.act_ore.findData(ore_label))
        # IF-Bedingungen der Aktion laden
        # Load the action's IF conditions
        self._act_conditions = [ActionCondition(**asdict(c)) for c in getattr(action, "conditions", [])]
        self.cond_logic.setCurrentIndex(1 if getattr(action, "condition_logic", "and") == "or" else 0)
        self._refresh_act_conditions()
        self._update_action_fields()
        self._update_cond_fields()

    def _update_action_fields(self):
        kind = ACTION_KINDS[self.act_kind.currentData()]
        vis = {"text": kind == "message",
               "unit": kind == "createUnit",
               "x": kind in ("createUnit", "startMiningOperation"),
               "y": kind in ("createUnit", "startMiningOperation"),
               "vehicle": kind == "setTargCount",
               "weapon": kind == "createUnit",
               "target_count": kind == "setTargCount",
               "priority": kind == "setTargCount",
               "ore": kind == "startMiningOperation",
               "rect_x": kind == "startMiningOperation",
               "rect_y": kind == "startMiningOperation",
               "rect_w": kind == "startMiningOperation",
               "rect_h": kind == "startMiningOperation",
               "truck_count": kind == "startMiningOperation",
               "mining_group": kind == "startMiningOperation",
               "x2": kind == "startMiningOperation",
               "y2": kind == "startMiningOperation",
               "player": kind in ("createUnit", "startMiningOperation", "assignToGroup"),
               "target": kind == "createTrigger",
               "group": kind in ("recordBuilding", "recordTube", "recordWall", "startMiningOperation"),
               "target_group": kind == "setTargCount",
               "source_group": kind == "setTargCount",
               "assign_group": kind == "assignToGroup",
               "building": kind in ("recordBuilding", "assignToGroup"),
               "wall": kind == "recordWall"}
        if kind == "recordBuilding":
            vis["x"] = True
            vis["y"] = True
        if kind == "assignToGroup":
            vis["x"] = True
            vis["y"] = True
        if kind in ("recordTube", "recordWall"):
            vis["x"] = True
            vis["y"] = True
            vis["x2"] = True
            vis["y2"] = True
        for key, w in self._act_rows.items():
            self.act_form.setRowVisible(w, vis[key])
        # X/Y-Beschriftung kontextabhaengig
        # X/Y labels are context-dependent
        xlbl, ylbl = {
            "startMiningOperation": (tr("triggers.lbl_mine_x"), tr("triggers.lbl_mine_y")),
            "assignToGroup": (tr("triggers.lbl_building_x"), tr("triggers.lbl_building_y")),
        }.get(kind, (tr("triggers.lbl_x"), tr("triggers.lbl_y")))
        lx = self.act_form.labelForField(self.act_x)
        ly = self.act_form.labelForField(self.act_y)
        if lx:
            lx.setText(xlbl)
        if ly:
            ly.setText(ylbl)
        self.pick_on_map.setVisible(kind in ("recordBuilding", "recordTube", "recordWall", "assignToGroup"))
        self.pick_mining_mine.setVisible(kind == "startMiningOperation")
        self.pick_mining_smelter.setVisible(kind == "startMiningOperation")
        self.pick_mining_rect.setVisible(kind == "startMiningOperation")
        self._update_set_targ_vehicle_options()

    def _object_label(self, obj):
        name = f"{obj.unit_name}: " if obj.unit_name else ""
        return f"{name}{obj.display} P{obj.player} @ ({obj.tile_x},{obj.tile_y})"

    def _update_set_targ_vehicle_options(self):
        current = self.act_vehicle.currentData()
        group_name = self.act_target_group.currentData()
        group_type = self.target_group_types.get(group_name, "BuildingGroup")
        vehicles = SET_TARG_VEHICLES_BY_GROUP_TYPE.get(group_type, [])
        self.act_vehicle.blockSignals(True)
        self.act_vehicle.clear()
        for display, map_id in vehicles:
            self.act_vehicle.addItem(display, map_id)
        if current is not None:
            index = self.act_vehicle.findData(current)
            if index >= 0:
                self.act_vehicle.setCurrentIndex(index)
        self.act_vehicle.blockSignals(False)

    def _selected_building_group(self):
        group_name = self.act_group.currentData()
        if not group_name:
            QMessageBox.information(self, tr("triggers.msg_no_buildinggroup_title"), tr("triggers.msg_no_buildinggroup_text"))
            return None
        return group_name

    def _selected_set_targ_groups(self):
        target_group_name = self.act_target_group.currentData()
        if not target_group_name:
            QMessageBox.information(self, tr("triggers.msg_no_targetgroup_title"), tr("triggers.msg_no_targetgroup_settarg_text"))
            return None, None
        source_group_name = self.act_source_group.currentData()
        if not source_group_name:
            QMessageBox.information(self, tr("triggers.msg_no_reinforcegroup_title"), tr("triggers.msg_no_reinforcegroup_text"))
            return None, None
        if self.act_vehicle.currentData() is None:
            group_type = self.target_group_types.get(target_group_name, "BuildingGroup")
            QMessageBox.information(
                self, tr("triggers.msg_no_vehicle_title"),
                tr("triggers.msg_no_vehicle_text", group_type=group_type))
            return None, None
        return target_group_name, source_group_name

    def _selected_mining_group(self):
        group_name = self.act_mining_group.currentData()
        if not group_name:
            QMessageBox.information(self, tr("triggers.msg_no_mininggroup_title"), tr("triggers.msg_no_mininggroup_text"))
            return None
        return group_name

    def _pick_action_on_map(self):
        if not (0 <= self._idx < len(self.triggers)):
            return
        kind = ACTION_KINDS[self.act_kind.currentData()]
        if kind == "assignToGroup":
            group_name = self.act_assign_group.currentData()
            if not group_name:
                QMessageBox.information(self, tr("triggers.msg_no_targetgroup_title"), tr("triggers.msg_no_group_text"))
                return
            self.map_pick_request = {
                "trigger_index": self._idx,
                "kind": "assignToGroup",
                "group_name": group_name,
                "building_type": self.act_building.currentData(),
                "player": self.act_player.value(),
            }
            self.accept()
            return
        if kind not in ("recordBuilding", "recordTube", "recordWall"):
            return
        group_name = self._selected_building_group()
        if not group_name:
            return
        mining_group_name = self._selected_mining_group()
        if not mining_group_name:
            return
        self.map_pick_request = {
            "trigger_index": self._idx,
            "kind": kind,
            "group_name": group_name,
            "mining_group_name": mining_group_name,
            "building_type": self.act_building.currentData(),
            "wall_type": self.act_wall.currentData(),
        }
        self.accept()

    def _pick_mining_operation_on_map(self, mode):
        if not (0 <= self._idx < len(self.triggers)):
            return
        if ACTION_KINDS[self.act_kind.currentData()] != "startMiningOperation":
            return
        group_name = self._selected_building_group()
        if not group_name:
            return
        mining_group_name = self._selected_mining_group()
        if not mining_group_name:
            return
        action_index = self.alist.currentRow()
        if not (
            0 <= action_index < len(self.triggers[self._idx].actions)
            and self.triggers[self._idx].actions[action_index].kind == "startMiningOperation"
        ):
            action_index = -1
        self.map_pick_request = {
            "trigger_index": self._idx,
            "kind": "startMiningOperation",
            "mode": mode,
            "group_name": group_name,
            "mining_group_name": mining_group_name,
            "ore_type": MINING_OPERATION_ORES[self.act_ore.currentData()],
            "truck_count": self.act_truck_count.value(),
            "x": self.act_x.value(),
            "y": self.act_y.value(),
            "x2": self.act_x2.value(),
            "y2": self.act_y2.value(),
            "rect_x": self.act_rect_x.value(),
            "rect_y": self.act_rect_y.value(),
            "rect_width": self.act_rect_w.value(),
            "rect_height": self.act_rect_h.value(),
            "player": self.act_player.value(),
            "action_index": action_index,
        }
        self.accept()

    # --- Pro-Aktion-Bedingungen ---
    # --- Per-action conditions ---
    def _update_cc_fields(self):  # obsolet (alte Pro-Aktion-Bedingungs-UI; durch if-Block ersetzt)
        # obsolete (old per-action condition UI; replaced by the if-block)
        fields = ACTION_CONDITION_KINDS[self.cc_kind.currentData()][1]
        for k, w in self._cc_rows.items():
            self.cc_form.setRowVisible(w, k in fields)

    def _refresh_act_conditions(self):
        self.cond_list.clear()
        for c in self._act_conditions:
            self.cond_list.addItem(action_condition_summary(c))

    def _cond_from_form(self):
        kind = ACTION_CONDITION_KINDS[self.cc_kind.currentData()][0]
        return ActionCondition(
            kind=kind, negate=self.cc_negate.isChecked(), player=self.cc_player.value(),
            building_type=self.cc_building.currentData(), x=self.cc_x.value(), y=self.cc_y.value(),
            compare=COMPARE[self.cc_compare.currentText()], value=self.cc_value.value(),
            resource=RESOURCES[self.cc_resource.currentText()], tech_id=self.cc_tech.value())

    def _add_act_condition(self):
        self._act_conditions.append(self._cond_from_form())
        self._refresh_act_conditions()

    def _remove_act_condition(self):
        row = self.cond_list.currentRow()
        if 0 <= row < len(self._act_conditions):
            del self._act_conditions[row]
            self._refresh_act_conditions()

    def _action_from_form(self):
        a = self._base_action_from_form()
        if a is not None:
            a.conditions = [ActionCondition(**asdict(c)) for c in self._act_conditions]
            a.condition_logic = "or" if self.cond_logic.currentIndex() == 1 else "and"
        return a

    def _base_action_from_form(self):
        kind = ACTION_KINDS[self.act_kind.currentData()]
        if kind == "noop":
            return TriggerAction(kind="noop")
        if kind == "message":
            return TriggerAction(kind="message", text=self.act_text.text())
        if kind == "createUnit":
            return TriggerAction(kind="createUnit", unit_type=self.act_unit.currentData(),
                                 weapon_type=self.act_weapon.currentData(),
                                 x=self.act_x.value(), y=self.act_y.value(), player=self.act_player.value())
        if kind == "createTrigger":
            target = self.act_target.currentData()
            if not target:
                QMessageBox.information(self, tr("triggers.msg_no_target_title"), tr("triggers.msg_no_target_text"))
                return None
            return TriggerAction(kind="createTrigger", target=target)
        if kind == "assignToGroup":
            group_name = self.act_assign_group.currentData()
            if not group_name:
                QMessageBox.information(self, tr("triggers.msg_no_targetgroup_title"), tr("triggers.msg_no_group_text"))
                return None
            return TriggerAction(
                kind="assignToGroup", group_name=group_name,
                building_type=self.act_building.currentData(),
                x=self.act_x.value(), y=self.act_y.value(),
                player=self.act_player.value())
        if kind in ("recordBuilding", "recordTube", "recordWall", "startMiningOperation"):
            group_name = self._selected_building_group()
            if not group_name:
                return None
            if kind == "recordBuilding":
                return TriggerAction(
                    kind="recordBuilding", group_name=group_name,
                    building_type=self.act_building.currentData(),
                    x=self.act_x.value(), y=self.act_y.value())
            if kind == "recordTube":
                return TriggerAction(
                    kind="recordTube", group_name=group_name,
                    x=self.act_x.value(), y=self.act_y.value(),
                    x2=self.act_x2.value(), y2=self.act_y2.value())
            if kind == "recordWall":
                return TriggerAction(
                    kind="recordWall", group_name=group_name,
                    wall_type=self.act_wall.currentData(),
                    x=self.act_x.value(), y=self.act_y.value(),
                    x2=self.act_x2.value(), y2=self.act_y2.value())
            mining_group_name = self._selected_mining_group()
            if not mining_group_name:
                return None
            return TriggerAction(
                kind="startMiningOperation",
                group_name=group_name,
                mining_group_name=mining_group_name,
                ore_type=MINING_OPERATION_ORES[self.act_ore.currentData()],
                truck_count=self.act_truck_count.value(),
                x=self.act_x.value(), y=self.act_y.value(),
                x2=self.act_x2.value(), y2=self.act_y2.value(),
                rect_x=self.act_rect_x.value(), rect_y=self.act_rect_y.value(),
                rect_width=self.act_rect_w.value(), rect_height=self.act_rect_h.value(),
                player=self.act_player.value())
        group_name, source_group_name = self._selected_set_targ_groups()
        if not group_name or not source_group_name:
            return None
        return TriggerAction(
            kind="setTargCount", group_name=group_name,
            source_group_name=source_group_name,
            reinforce_priority=self.act_priority.value(),
            unit_type=self.act_vehicle.currentData(),
            weapon_type="mapNone",
            target_count=self.act_target_count.value())

    def _add_action(self):
        if not (0 <= self._idx < len(self.triggers)):
            return
        a = self._action_from_form()
        if a is None:
            return
        self.triggers[self._idx].actions.append(a)
        self._refresh_actions()
        self.tlist.item(self._idx).setText(trigger_summary(self.triggers[self._idx]))
        self.alist.setCurrentRow(len(self.triggers[self._idx].actions) - 1)

    def _update_action(self):
        row = self.alist.currentRow()
        if not (0 <= self._idx < len(self.triggers) and 0 <= row < len(self.triggers[self._idx].actions)):
            return
        action = self._action_from_form()
        if action is None:
            return
        self.triggers[self._idx].actions[row] = action
        self._refresh_actions()
        self.alist.setCurrentRow(row)
        self.tlist.item(self._idx).setText(trigger_summary(self.triggers[self._idx]))

    def _remove_action(self):
        row = self.alist.currentRow()
        if 0 <= self._idx < len(self.triggers) and 0 <= row < len(self.triggers[self._idx].actions):
            del self.triggers[self._idx].actions[row]
            self._refresh_actions()
            self.tlist.item(self._idx).setText(trigger_summary(self.triggers[self._idx]))


