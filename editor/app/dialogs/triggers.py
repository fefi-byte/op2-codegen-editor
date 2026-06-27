from __future__ import annotations
import dataclasses
from collections import defaultdict
from ..common import *
from .action_editor import ActionListWidget


class UnitChecksWidget(QFrame):
    """Editor fuer eine Liste von FindUnitCheck-Eintraegen (Trigger 'findUnit').

    Jeder Eintrag ist eine Zeile: Unit-Typ, Tile-X, Tile-Y, Loesch-Knopf.
    `+ Position` haengt einen neuen Eintrag an. Aenderungen aktualisieren
    direkt das uebergebene `checks`-List-Objekt (referenziell).
    """
    def __init__(self, checks, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.checks = checks
        self._rows: list[QWidget] = []
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Positionen (alle müssen einsatzbereit sein, AND-verknüpft):"))
        self.list_box = QVBoxLayout()
        outer.addLayout(self.list_box)
        add_btn = QPushButton("+ Position hinzufügen")
        add_btn.clicked.connect(self._add)
        outer.addWidget(add_btn)
        self._rebuild()

    def _rebuild(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        for i, c in enumerate(self.checks):
            self._rows.append(self._make_row(i, c))
            self.list_box.addWidget(self._rows[-1])

    def _make_row(self, idx, c):
        row = QWidget()
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
        unit = QComboBox()
        for d, m, _ in STRUCTURES:
            unit.addItem(d, m)
        bidx = unit.findData(c.unit_type)
        if bidx >= 0:
            unit.setCurrentIndex(bidx)
        unit.currentIndexChanged.connect(lambda _, i=idx, w=unit: self._set_type(i, w))
        sx = QSpinBox(); sx.setRange(0, 1023); sx.setValue(int(c.x))
        sy = QSpinBox(); sy.setRange(0, 1023); sy.setValue(int(c.y))
        sx.valueChanged.connect(lambda v, i=idx: self._set_x(i, v))
        sy.valueChanged.connect(lambda v, i=idx: self._set_y(i, v))
        rm = QPushButton("✕"); rm.setMaximumWidth(30)
        rm.clicked.connect(lambda _, i=idx: self._remove(i))
        h.addWidget(QLabel("Typ:")); h.addWidget(unit, 2)
        h.addWidget(QLabel("X:")); h.addWidget(sx)
        h.addWidget(QLabel("Y:")); h.addWidget(sy)
        h.addWidget(rm)
        return row

    def _set_type(self, i, w):
        if 0 <= i < len(self.checks):
            self.checks[i].unit_type = w.currentData() or "mapCommandCenter"

    def _set_x(self, i, v):
        if 0 <= i < len(self.checks):
            self.checks[i].x = int(v)

    def _set_y(self, i, v):
        if 0 <= i < len(self.checks):
            self.checks[i].y = int(v)

    def _add(self):
        self.checks.append(FindUnitCheck())
        self._rebuild()

    def _remove(self, i):
        if 0 <= i < len(self.checks):
            del self.checks[i]
            self._rebuild()


class TriggersDialog(QDialog):
    """Benutzerdefinierte Trigger: Bedingung + Aktionen, mit Laufzeit-Erstellung.

    Trigger koennen optional in benannte Ordner gruppiert werden (visuell, kein
    Einfluss auf den generierten Code). Trigger ohne Ordner erscheinen direkt
    in der Liste; Trigger mit Ordner werden unter einem aufklappbaren Knoten
    zusammengefasst.
    """
    def __init__(
        self, parent, triggers, building_groups=None, target_groups=None,
        reinforce_groups=None, objects=None, initial_trigger_index=0,
        initial_action_index=-1, diff_setup=None, variables=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("triggers.title"))
        self.resize(900, 620)
        self.triggers = [self._copy(t) for t in triggers]
        self.building_groups = list(building_groups or [])
        self.target_groups = list(target_groups or self.building_groups)
        self.reinforce_groups = list(reinforce_groups or [])
        self.target_group_types = {
            group.name: (
                "BuildingGroup" if isinstance(group, BuildingGroupSpec)
                else "FightGroup"
            )
            for group in self.target_groups
        }
        self._idx = -1
        self._initial_trigger_index = initial_trigger_index
        self._initial_action_index = initial_action_index
        self._loading = False
        self.map_pick_request = None
        self._diff_setup = diff_setup
        self._variables = list(variables or [])
        self._diff_values = (
            (diff_setup.hard, diff_setup.normal, diff_setup.easy)
            if diff_setup else None
        )

        # --- Trigger-Liste (QTreeWidget mit Ordner-Unterstützung) ---
        self.tlist = QTreeWidget()
        self.tlist.setHeaderHidden(True)
        self.tlist.currentItemChanged.connect(self._on_item_changed)
        add = QPushButton(tr("triggers.btn_add_trigger")); add.clicked.connect(self._add)
        rm = QPushButton(tr("triggers.btn_remove_trigger")); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(QLabel(tr("triggers.lbl_trigger_list"))); left.addWidget(self.tlist, 1)
        left.addWidget(add); left.addWidget(rm)

        # --- Trigger-Eigenschaften ---
        self.name = QLineEdit()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(tr("triggers.folder_placeholder"))
        self.at_start = QCheckBox(tr("triggers.chk_at_start"))
        self.one_shot = QCheckBox(tr("triggers.chk_one_shot"))
        self.cond = QComboBox(); fill_combo(self.cond, TRIGGER_CONDITIONS, "trigger_conditions")
        self.cond.currentIndexChanged.connect(self._update_cond_fields)
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.marks = ExprEdit(diff_values=self._diff_values)
        self.marks.setValue(100)
        self.marks.setPlaceholderText("z.B. 600 oder ceil(600 * diff / 10)")
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

        # --- Bedingung-Tab ---
        cond_tab = QWidget()
        cond_layout = QVBoxLayout(cond_tab)
        cond_layout.addLayout(self.form)
        self.unit_checks_container = QWidget()
        self.unit_checks_layout = QVBoxLayout(self.unit_checks_container)
        self.unit_checks_layout.setContentsMargins(0, 0, 0, 0)
        self.unit_checks_widget = None
        cond_layout.addWidget(self.unit_checks_container)
        self.unit_checks_container.setVisible(False)
        cond_layout.addStretch(1)

        # --- Aktionen-Tab (Karten-Editor) ---
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
            self._select_idx(max(0, min(self._initial_trigger_index, len(self.triggers) - 1)))
            if self._initial_action_index >= 0:
                self.tabs.setCurrentIndex(1)
        else:
            self._set_form_enabled(False)

    def _action_ctx(self):
        all_groups = ([(g.name, "BuildingGroup") for g in self.building_groups]
                      + [(g.name, "ReinforceGroup") for g in self.reinforce_groups])
        return {
            "triggers": self.triggers,
            "building_groups": self.building_groups,
            "reinforce_groups": self.reinforce_groups,
            "target_groups": self.target_groups,
            "target_group_types": self.target_group_types,
            "all_groups": all_groups,
            "on_map_pick": self._on_action_map_pick,
            "variables": self._variables,
            "diff_values": self._diff_values,
        }

    def _on_action_map_pick(self, action, field: str):
        action_index = -1
        if 0 <= self._idx < len(self.triggers):
            try:
                action_index = self.triggers[self._idx].actions.index(action)
            except ValueError:
                action_index = -1
        self.map_pick_request = {
            "kind": "action_field",
            "trigger_index": self._idx,
            "action_index": action_index,
            "action": action,
            "field": field,
        }
        self.accept()

    @staticmethod
    def _copy(t):
        d = asdict(t)
        acts = [action_from_dict(a) for a in d.pop("actions", [])]
        checks = [FindUnitCheck(**c) for c in d.pop("unit_checks", [])]
        valid = {f.name for f in dataclasses.fields(TriggerDef)} - {"actions", "unit_checks"}
        d = {k: v for k, v in d.items() if k in valid}
        return TriggerDef(actions=acts, unit_checks=checks, **d)

    def _set_form_enabled(self, on):
        for w in list(self._cond_rows.values()) + [self.name, self.folder, self.at_start,
                                                    self.one_shot, self.cond]:
            w.setEnabled(on)

    # --- Trigger-Liste (QTreeWidget) ---

    def _refresh_list(self):
        self.tlist.blockSignals(True)
        prev_idx = self._idx
        self.tlist.clear()

        folder_order = []
        by_folder = defaultdict(list)
        for i, t in enumerate(self.triggers):
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
                font = f_item.font(0); font.setBold(True); f_item.setFont(0, font)
                self.tlist.addTopLevelItem(f_item)
                f_item.setExpanded(True)
            else:
                f_item = None
            for i in indices:
                t = self.triggers[i]
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

    def _select_idx(self, idx):
        """Sucht und selektiert das QTreeWidgetItem fuer Trigger-Index `idx`."""
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
        if idx is None:  # Ordner-Header angeklickt
            self._idx = -1
            self._set_form_enabled(False)
            return
        self._set_form_enabled(True)
        self._idx = idx
        self._load(idx)

    def _add(self):
        name = f"Trigger{len(self.triggers) + 1}"
        self.triggers.append(TriggerDef(name=name))
        self._refresh_list()
        self._select_idx(len(self.triggers) - 1)

    def _remove(self):
        if not (0 <= self._idx < len(self.triggers)):
            return
        old_idx = self._idx
        del self.triggers[self._idx]
        self._idx = -1
        self._refresh_list()
        if self.triggers:
            self._select_idx(min(old_idx, len(self.triggers) - 1))
        else:
            self._set_form_enabled(False)

    # --- Eigenschaften laden/speichern ---

    def _load(self, i):
        t = self.triggers[i]
        self._loading = True
        self.name.setText(t.name)
        self.folder.setText(getattr(t, 'folder', '') or '')
        self.at_start.setChecked(t.enabled_at_start)
        self.one_shot.setChecked(t.one_shot)
        label = {v[0]: k for k, v in TRIGGER_CONDITIONS.items()}.get(t.condition, "Zeit (Marks)")
        self.cond.setCurrentIndex(self.cond.findData(label))
        self.player.setValue(t.player); self.marks.setValue(t.marks if t.marks is not None else 100)
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
        if self.unit_checks_widget is not None:
            self.unit_checks_layout.removeWidget(self.unit_checks_widget)
            self.unit_checks_widget.deleteLater()
            self.unit_checks_widget = None
        self.unit_checks_widget = UnitChecksWidget(t.unit_checks)
        self.unit_checks_layout.addWidget(self.unit_checks_widget)
        self._loading = False
        self._update_cond_fields()
        self.act_scroll.setWidget(ActionListWidget(t.actions, self._action_ctx()))

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.triggers)):
            return
        t = self.triggers[self._idx]
        t.name = self.name.text() or f"Trigger{self._idx + 1}"
        t.folder = self.folder.text().strip()
        t.enabled_at_start = self.at_start.isChecked()
        t.one_shot = self.one_shot.isChecked()
        t.condition = TRIGGER_CONDITIONS[self.cond.currentData()][0]
        t.player = self.player.value(); t.marks = self.marks.value()  # int oder str
        t.count = self.count.value(); t.compare = COMPARE[self.compare.currentText()]
        t.tech_id = self.tech_id.value()
        t.resource = RESOURCES[self.resource.currentText()]
        t.amount = self.amount.value(); t.building = self.building.currentData()
        t.x = self.x.value(); t.y = self.y.value()
        t.width = self.width.value(); t.height = self.height.value()
        item = self.tlist.currentItem()
        if item and item.data(0, Qt.UserRole) is not None:
            item.setText(0, trigger_summary(t))

    def _update_cond_fields(self):
        fields = TRIGGER_CONDITIONS[self.cond.currentData()][1]
        for key, w in self._cond_rows.items():
            self.form.setRowVisible(w, key in fields)
        self.unit_checks_container.setVisible("unit_checks" in fields)
