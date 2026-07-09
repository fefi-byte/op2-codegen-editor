from __future__ import annotations
from collections import defaultdict

from PySide6.QtWidgets import QSplitter

from ..common import *
from ..dialogs.triggers import UnitChecksWidget
from ..dialogs.action_editor import ActionListWidget
from ..style import apply_role


class TriggerPanel(QWidget):
    map_pick_requested = Signal(dict)

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._idx = -1
        self._loading = False

        # --- Trigger-Liste (links) ---
        self.tlist = QTreeWidget()
        self.tlist.setHeaderHidden(True)
        self.tlist.currentItemChanged.connect(self._on_item_changed)
        add_btn = QPushButton(tr("triggers.btn_add_trigger"))
        add_btn.clicked.connect(self._add)
        apply_role(add_btn, "primary")
        rm_btn = QPushButton(tr("triggers.btn_remove_trigger"))
        rm_btn.clicked.connect(self._remove)
        apply_role(rm_btn, "danger")
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        list_lbl = QLabel(tr("triggers.lbl_trigger_list"))
        list_lbl.setProperty("role", "section")
        left_lay.addWidget(list_lbl)
        left_lay.addWidget(self.tlist, 1)
        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rm_btn)
        left_lay.addLayout(btn_row)

        # --- Bedingung-Felder ---
        self.name = QLineEdit()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(tr("triggers.folder_placeholder"))
        self.at_start = QCheckBox(tr("triggers.chk_at_start"))
        self.one_shot = QCheckBox(tr("triggers.chk_one_shot"))
        self.cond = QComboBox()
        fill_combo(self.cond, TRIGGER_CONDITIONS, "trigger_conditions")
        self.cond.currentIndexChanged.connect(self._update_cond_fields)
        self.player = QSpinBox()
        self.player.setRange(0, 5)
        self.marks = ExprEdit()
        self.marks.setValue(100)
        self.marks.setPlaceholderText("z.B. 600 oder ceil(600 * diff / 10)")
        self.count = QSpinBox()
        self.count.setRange(0, 1000)
        self.count.setValue(1)
        self.compare = QComboBox()
        self.compare.addItems(COMPARE.keys())
        self.tech_id = QSpinBox()
        self.tech_id.setRange(0, 20000)
        self.resource = QComboBox()
        self.resource.addItems(RESOURCES.keys())
        self.amount = QSpinBox()
        self.amount.setRange(0, 1000000)
        self.amount.setValue(1000)
        self.building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.building.addItem(d, m)
        self.x = QSpinBox()
        self.x.setRange(0, 1023)
        self.y = QSpinBox()
        self.y.setRange(0, 1023)
        self.width = QSpinBox()
        self.width.setRange(1, 256)
        self.width.setValue(4)
        self.height = QSpinBox()
        self.height.setRange(1, 256)
        self.height.setValue(4)

        self.form = QFormLayout()
        self.form.addRow(tr("triggers.lbl_name"), self.name)
        self.form.addRow(tr("triggers.lbl_folder"), self.folder)
        self.form.addRow(self.at_start)
        self.form.addRow(self.one_shot)
        self.form.addRow(tr("triggers.lbl_condition"), self.cond)
        self._cond_rows = {
            "player": self.player, "marks": self.marks, "count": self.count,
            "compare": self.compare, "tech_id": self.tech_id, "resource": self.resource,
            "amount": self.amount, "building": self.building,
            "x": self.x, "y": self.y, "width": self.width, "height": self.height,
        }
        clabels = {
            "player": tr("triggers.lbl_player"), "marks": tr("triggers.lbl_marks"),
            "count": tr("triggers.lbl_count"), "compare": tr("triggers.lbl_compare"),
            "tech_id": tr("triggers.lbl_tech_id"), "resource": tr("triggers.lbl_resource"),
            "amount": tr("triggers.lbl_amount"), "building": tr("triggers.lbl_building"),
            "x": tr("triggers.lbl_x"), "y": tr("triggers.lbl_y"),
            "width": tr("triggers.lbl_width"), "height": tr("triggers.lbl_height"),
        }
        for key, w in self._cond_rows.items():
            self.form.addRow(clabels[key], w)

        self.name.textChanged.connect(self._store_current)
        self.folder.textChanged.connect(self._store_current)
        self.folder.editingFinished.connect(self._refresh_list)
        for w in (self.cond, self.compare, self.resource, self.building):
            w.currentIndexChanged.connect(self._store_current)
        for w in (self.player, self.count, self.tech_id, self.amount,
                  self.x, self.y, self.width, self.height):
            w.valueChanged.connect(self._store_current)
        self.marks.valueChanged.connect(self._store_current)
        for w in (self.at_start, self.one_shot):
            w.toggled.connect(self._store_current)

        # --- Bedingungsformular ---
        cond_inner = QWidget()
        cond_inner.setMinimumWidth(0)
        cond_layout = QVBoxLayout(cond_inner)
        cond_layout.addLayout(self.form)
        self.unit_checks_container = QWidget()
        self.unit_checks_layout = QVBoxLayout(self.unit_checks_container)
        self.unit_checks_layout.setContentsMargins(0, 0, 0, 0)
        self.unit_checks_widget = None
        cond_layout.addWidget(self.unit_checks_container)
        self.unit_checks_container.setVisible(False)
        cond_layout.addStretch(1)
        cond_scroll = QScrollArea()
        cond_scroll.setWidgetResizable(True)
        cond_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cond_scroll.setWidget(cond_inner)

        cond_section = QWidget()
        cs_lay = QVBoxLayout(cond_section)
        cs_lay.setContentsMargins(0, 4, 0, 0)
        cs_lay.setSpacing(2)
        cs_lay.addWidget(cond_scroll)

        # --- Aktionsliste ---
        act_widget = QWidget()
        act_layout = QVBoxLayout(act_widget)
        act_layout.setContentsMargins(0, 4, 0, 0)
        act_layout.setSpacing(2)
        self.act_scroll = QScrollArea()
        self.act_scroll.setWidgetResizable(True)
        act_layout.addWidget(self.act_scroll)

        # Bedingung und Aktionen als eigene Tabs statt gestapelter Bereiche --
        # dadurch bekommt die jeweils aktive Ansicht (v.a. die Aktionsliste)
        # deutlich mehr Hoehe.
        # Condition and actions as separate tabs instead of stacked sections --
        # this gives whichever view is active (especially the action list)
        # much more vertical space.
        detail_tabs = QTabWidget()
        detail_tabs.addTab(cond_section, tr("triggers.lbl_section_condition"))
        detail_tabs.addTab(act_widget, tr("triggers.lbl_section_actions"))

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(left)
        splitter.addWidget(detail_tabs)
        splitter.setSizes([150, 450])

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(splitter)

        self._set_form_enabled(False)

    # --- Öffentliche API ---

    def load(self):
        self._idx = -1
        self._refresh_list()
        if self._window.triggers:
            self._select_idx(0)
        else:
            self._set_form_enabled(False)

    def refresh(self):
        self._refresh_list()

    def refresh_actions(self, expand_index: int = -1):
        if 0 <= self._idx < len(self._window.triggers):
            self._window.clear_action_area_preview()
            t = self._window.triggers[self._idx]
            w = ActionListWidget(t.actions, self._action_ctx())
            self.act_scroll.setWidget(w)
            if expand_index >= 0:
                w.expand_index(expand_index)

    def select(self, idx, action_idx=-1):
        self._select_idx(idx)

    # --- Interne Hilfsmethoden ---

    def _diff_values(self):
        ds = self._window.diff_setup
        if ds and hasattr(ds, 'hard'):
            return (ds.hard, ds.normal, ds.easy)
        return None

    def _action_ctx(self):
        w = self._window
        # setTargCount ist eine Group-Basismethode -- gilt fuer alle drei
        # Gruppentypen, nicht nur BuildingGroup.
        # setTargCount is a base Group method -- applies to all three group
        # types, not just BuildingGroup.
        target_group_types = {
            **{g.name: "BuildingGroup" for g in w.building_groups},
            **{g.name: "ReinforceGroup" for g in w.reinforce_groups},
            **{g.name: "FightGroup" for g in w.fight_groups},
        }
        target_groups = list(w.building_groups) + list(w.reinforce_groups) + list(w.fight_groups)
        all_groups = (
            [(g.name, "BuildingGroup") for g in w.building_groups]
            + [(g.name, "ReinforceGroup") for g in w.reinforce_groups]
        )
        # FightGroups sind jetzt vordefinierte Gruppen (Gruppen-Panel), keine
        # spontanen Wellen-Gruppen mehr -- direkt aus w.fight_groups lesen.
        # FightGroups are now predefined groups (Groups panel), no more
        # ad-hoc wave groups -- read directly from w.fight_groups.
        wave_groups = [g.name for g in w.fight_groups]
        # Alle befehligbaren Gruppen mit Typ (fuer den Gruppen-Befehl)
        # All commandable groups with their type (for the group command)
        all_command_groups = (
            [(g.name, "FightGroup") for g in w.fight_groups]
            + [(g.name, "BuildingGroup") for g in w.building_groups]
            + [(g.name, "ReinforceGroup") for g in w.reinforce_groups]
        )
        # Benannte platzierte Einheiten (fuer den Einheiten-Befehl)
        # Named placed units (for the unit command)
        named_units = [(o.unit_name, o.map_id) for o in w.objects
                       if getattr(o, "unit_name", "")]
        # Platzierte Mine-/Smelter-Gebaeude (fuer die Mine-/Smelter-Auswahl der
        # startMining-Aktion -- Bequemlichkeit statt X/Y-Koordinaten eintippen).
        # Placed mine/smelter buildings (for startMining's mine/smelter picker
        # -- convenience instead of typing X/Y coordinates).
        mine_objects = [o for o in w.objects
                        if o.map_id in ("mapCommonOreMine", "mapRareOreMine")]
        smelter_objects = [o for o in w.objects
                           if o.map_id in ("mapCommonOreSmelter", "mapRareOreSmelter")]
        return {
            "triggers": w.triggers,
            "wave_groups": wave_groups,
            "fight_groups": wave_groups,
            "all_command_groups": all_command_groups,
            "named_units": named_units,
            "building_groups": w.building_groups,
            "reinforce_groups": w.reinforce_groups,
            "fight_group_specs": w.fight_groups,
            "mining_groups": w.mining_groups,
            "mine_objects": mine_objects,
            "smelter_objects": smelter_objects,
            "target_groups": target_groups,
            "target_group_types": target_group_types,
            "all_groups": all_groups,
            "on_map_pick": self._on_action_map_pick,
            "on_area_preview": self._on_area_preview,
            "variables": w.variables,
            "diff_values": self._diff_values(),
        }

    def _on_area_preview(self, action):
        """Bereiche der aufgeklappten Aktion auf der Karte zeigen (None = weg).

        Show the expanded action's areas on the map (None = clear)."""
        w = self._window
        if action is None:
            w.clear_action_area_preview()
        else:
            w.show_action_area_preview(action)

    def _on_action_map_pick(self, action, field: str):
        triggers = self._window.triggers
        action_index = -1
        if 0 <= self._idx < len(triggers):
            try:
                action_index = triggers[self._idx].actions.index(action)
            except ValueError:
                action_index = -1
        kind = "lava_paint" if field == "lava_zone" else "action_field"
        self.map_pick_requested.emit({
            "kind": kind,
            "trigger_index": self._idx,
            "action_index": action_index,
            "action": action,
            "field": field,
        })

    def _set_form_enabled(self, on):
        for w in list(self._cond_rows.values()) + [
            self.name, self.folder, self.at_start, self.one_shot, self.cond
        ]:
            w.setEnabled(on)

    def _refresh_list(self):
        triggers = self._window.triggers
        self.tlist.blockSignals(True)
        prev_idx = self._idx
        self.tlist.clear()

        folder_order = []
        by_folder = defaultdict(list)
        for i, t in enumerate(triggers):
            f = getattr(t, 'folder', '') or ''
            if f not in by_folder:
                folder_order.append(f)
            by_folder[f].append(i)

        found_item = None
        for folder in folder_order:
            indices = by_folder[folder]
            if folder:
                f_item = QTreeWidgetItem([folder])
                f_item.setFlags(Qt.ItemIsEnabled)
                font = f_item.font(0)
                font.setBold(True)
                f_item.setFont(0, font)
                self.tlist.addTopLevelItem(f_item)
                f_item.setExpanded(True)
            else:
                f_item = None
            for i in indices:
                t = triggers[i]
                t_item = QTreeWidgetItem([trigger_summary(t)])
                t_item.setData(0, Qt.UserRole, i)
                if f_item is not None:
                    f_item.addChild(t_item)
                else:
                    self.tlist.addTopLevelItem(t_item)
                if i == prev_idx:
                    found_item = t_item

        self.tlist.blockSignals(False)
        if found_item:
            self.tlist.setCurrentItem(found_item)
        elif prev_idx >= 0 and not triggers:
            self._idx = -1
            self._set_form_enabled(False)

    def _select_idx(self, idx):
        def find_in(parent):
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.data(0, Qt.UserRole) == idx:
                    return child
                found = find_in(child)
                if found:
                    return found
            return None
        item = find_in(self.tlist.invisibleRootItem())
        if item:
            self.tlist.setCurrentItem(item)

    def _on_item_changed(self, current, previous):
        if current is None:
            self._idx = -1
            self._set_form_enabled(False)
            return
        idx = current.data(0, Qt.UserRole)
        if idx is None:
            self._idx = -1
            self._set_form_enabled(False)
            return
        # Waehrend des Umschaltens keine Stores zulassen: Signale der noch mit
        # den ALTEN Werten gefuellten Widgets wuerden sonst den NEUEN Trigger
        # ueberschreiben (self._idx zeigt bereits auf ihn).
        # Block stores while switching: signals from widgets still holding the
        # OLD values would otherwise overwrite the NEW trigger (self._idx
        # already points at it).
        self._loading = True
        self._set_form_enabled(True)
        self._idx = idx
        self._load(idx)

    def _add(self):
        triggers = self._window.triggers
        name = f"Trigger{len(triggers) + 1}"
        triggers.append(TriggerDef(name=name))
        self._window._refresh_overview()
        self._refresh_list()
        self._select_idx(len(triggers) - 1)

    def _remove(self):
        triggers = self._window.triggers
        if not (0 <= self._idx < len(triggers)):
            return
        old_idx = self._idx
        del triggers[self._idx]
        self._idx = -1
        self._window._refresh_overview()
        self._refresh_list()
        if triggers:
            self._select_idx(min(old_idx, len(triggers) - 1))
        else:
            self._set_form_enabled(False)

    def _load(self, i):
        triggers = self._window.triggers
        t = triggers[i]
        self._loading = True
        dv = self._diff_values()
        if dv:
            # set_diff_values loest valueChanged aus -> muss im Guard laufen
            # set_diff_values emits valueChanged -> must run inside the guard
            self.marks.set_diff_values(*dv)
        self.name.setText(t.name)
        self.folder.setText(getattr(t, 'folder', '') or '')
        self.at_start.setChecked(t.enabled_at_start)
        self.one_shot.setChecked(t.one_shot)
        label = {v[0]: k for k, v in TRIGGER_CONDITIONS.items()}.get(t.condition, "Zeit (Marks)")
        self.cond.setCurrentIndex(self.cond.findData(label))
        self.player.setValue(t.player)
        self.marks.setValue(t.marks if t.marks is not None else 100)
        self.count.setValue(t.count)
        self.compare.setCurrentText({v: k for k, v in COMPARE.items()}.get(t.compare, "≥"))
        self.tech_id.setValue(t.tech_id)
        self.resource.setCurrentText({v: k for k, v in RESOURCES.items()}.get(t.resource, "Common Ore"))
        self.amount.setValue(t.amount)
        bidx = self.building.findData(t.building)
        if bidx >= 0:
            self.building.setCurrentIndex(bidx)
        self.x.setValue(t.x)
        self.y.setValue(t.y)
        self.width.setValue(t.width)
        self.height.setValue(t.height)
        if self.unit_checks_widget is not None:
            self.unit_checks_layout.removeWidget(self.unit_checks_widget)
            self.unit_checks_widget.deleteLater()
            self.unit_checks_widget = None
        self.unit_checks_widget = UnitChecksWidget(t.unit_checks)
        self.unit_checks_layout.addWidget(self.unit_checks_widget)
        self._loading = False
        self._update_cond_fields()
        self._window.clear_action_area_preview()
        self.act_scroll.setWidget(ActionListWidget(t.actions, self._action_ctx()))

    def _store_current(self):
        triggers = self._window.triggers
        if self._loading or not (0 <= self._idx < len(triggers)):
            return
        t = triggers[self._idx]
        t.name = self.name.text() or f"Trigger{self._idx + 1}"
        t.folder = self.folder.text().strip()
        t.enabled_at_start = self.at_start.isChecked()
        t.one_shot = self.one_shot.isChecked()
        t.condition = TRIGGER_CONDITIONS[self.cond.currentData()][0]
        t.player = self.player.value()
        t.marks = self.marks.value()
        t.count = self.count.value()
        t.compare = COMPARE[self.compare.currentText()]
        t.tech_id = self.tech_id.value()
        t.resource = RESOURCES[self.resource.currentText()]
        t.amount = self.amount.value()
        t.building = self.building.currentData()
        t.x = self.x.value()
        t.y = self.y.value()
        t.width = self.width.value()
        t.height = self.height.value()
        item = self.tlist.currentItem()
        if item and item.data(0, Qt.UserRole) is not None:
            item.setText(0, trigger_summary(t))
        self._window._refresh_overview()

    def _update_cond_fields(self):
        fields = TRIGGER_CONDITIONS[self.cond.currentData()][1]
        for key, w in self._cond_rows.items():
            self.form.setRowVisible(w, key in fields)
        self.unit_checks_container.setVisible("unit_checks" in fields)
