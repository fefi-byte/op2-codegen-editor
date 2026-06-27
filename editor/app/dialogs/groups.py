from __future__ import annotations
import dataclasses
from collections import defaultdict
from ..common import *


class GroupsDialog(QDialog):
    """Gruppen verwalten: BuildingGroup und ReinforceGroup.

    Gruppen koennen optional in benannte Ordner gruppiert werden (visuell,
    kein Einfluss auf den generierten Code).
    """
    def __init__(self, parent, building_groups, reinforce_groups, objects, player_count):
        super().__init__(parent)
        self.setWindowTitle(tr("groups.window_title"))
        self.resize(880, 560)
        self.groups = (
            [BuildingGroupSpec(**asdict(g)) for g in building_groups] +
            [
                ReinforceGroupSpec(
                    name=g.name,
                    player=g.player,
                    unit_ids=list(g.unit_ids),
                    targets=[ReinforceTargetSpec(**asdict(t)) for t in g.targets],
                    folder=getattr(g, 'folder', ''),
                )
                for g in reinforce_groups
            ]
        )
        self.objects = list(objects)
        self._idx = -1
        self._loading = False
        self.rect_pick_request: int | None = None

        self.builders = [
            o for o in self.objects
            if o.map_id in ("mapStructureFactory", "mapVehicleFactory", "mapConVec", "mapEarthworker")
        ]
        self.reinforce_factories = [
            o for o in self.objects
            if o.map_id in ("mapVehicleFactory", "mapArachnidFactory")
        ]

        # --- Gruppen-Liste (QTreeWidget mit Ordner-Unterstützung) ---
        self.glist = QTreeWidget()
        self.glist.setHeaderHidden(True)
        self.glist.currentItemChanged.connect(self._on_item_changed)
        add_building = QPushButton(tr("groups.add_building")); add_building.clicked.connect(self._add_building)
        add_reinforce = QPushButton(tr("groups.add_reinforce")); add_reinforce.clicked.connect(self._add_reinforce)
        rm = QPushButton(tr("groups.remove")); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(QLabel(tr("groups.groups_label"))); left.addWidget(self.glist, 1)
        left.addWidget(add_building); left.addWidget(add_reinforce); left.addWidget(rm)

        self.name = QLineEdit()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(tr("groups.folder_placeholder"))
        self.gtype = QComboBox(); self.gtype.addItems(["BuildingGroup", "ReinforceGroup"]); self.gtype.setEnabled(False)
        self.player = QSpinBox(); self.player.setRange(0, max(0, player_count - 1))
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

        self.form = QFormLayout()
        self.form.addRow(tr("groups.row_name"), self.name)
        self.form.addRow(tr("groups.lbl_folder"), self.folder)
        self.form.addRow(tr("groups.row_type"), self.gtype)
        self.form.addRow(tr("groups.row_player"), self.player)
        self.form.addRow(tr("groups.row_rect_x"), self.rect_x)
        self.form.addRow(tr("groups.row_rect_y"), self.rect_y)
        self.form.addRow(tr("groups.row_rect_width"), self.rect_w)
        self.form.addRow(tr("groups.row_rect_height"), self.rect_h)
        self.form.addRow("", pick_rect)
        self.form.addRow(tr("groups.row_units"), self.unit_list)
        self.form.addRow(tr("groups.row_targets"), self.target_text)

        self.name.textChanged.connect(self._store_current)
        self.folder.textChanged.connect(self._store_current)
        self.folder.editingFinished.connect(self._refresh_list)
        for w in (self.player, self.rect_x, self.rect_y, self.rect_w, self.rect_h):
            w.valueChanged.connect(self._store_current)
        self.unit_list.itemChanged.connect(self._store_current)
        self.target_text.textChanged.connect(self._store_current)

        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(self.form, 2)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self._refresh_list()
        if self.groups:
            self._select_idx(0)
        else:
            self._set_form_enabled(False)

    def building_groups(self):
        return [g for g in self.groups if isinstance(g, BuildingGroupSpec)]

    def reinforce_groups(self):
        return [g for g in self.groups if isinstance(g, ReinforceGroupSpec)]

    def _object_label(self, o):
        name = f"{o.unit_name}: " if o.unit_name else ""
        return f"{name}{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})"

    def _summary(self, group):
        if isinstance(group, ReinforceGroupSpec):
            return reinforce_group_summary(group)
        return building_group_summary(group)

    def _set_form_enabled(self, on):
        for w in (self.name, self.folder, self.player, self.rect_x,
                  self.rect_y, self.rect_w, self.rect_h, self.unit_list, self.target_text):
            w.setEnabled(on)

    # --- Gruppen-Liste (QTreeWidget) ---

    def _refresh_list(self):
        self.glist.blockSignals(True)
        prev_idx = self._idx
        self.glist.clear()

        folder_order = []
        by_folder = defaultdict(list)
        for i, g in enumerate(self.groups):
            f = getattr(g, 'folder', '') or ''
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
                self.glist.addTopLevelItem(f_item)
                f_item.setExpanded(True)
            else:
                f_item = None
            for i in indices:
                g = self.groups[i]
                g_item = QTreeWidgetItem([self._summary(g)])
                g_item.setData(0, Qt.UserRole, i)
                if f_item is not None:
                    f_item.addChild(g_item)
                else:
                    self.glist.addTopLevelItem(g_item)
                if i == prev_idx:
                    found_item = g_item

        self.glist.blockSignals(False)
        if found_item:
            self.glist.setCurrentItem(found_item)

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
        item = find_in(self.glist.invisibleRootItem())
        if item:
            self.glist.setCurrentItem(item)

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
        self._set_form_enabled(True)
        self._idx = idx
        self._load(idx)

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
        self._select_idx(len(self.groups) - 1)

    def _add_reinforce(self):
        group = ReinforceGroupSpec(
            name=f"ReinforceGroup{len(self.reinforce_groups()) + 1}",
            player=0,
            unit_ids=[o.uid for o in self.reinforce_factories if o.player == 0],
            targets=[
                ReinforceTargetSpec(g.name, 1500)
                for g in self.building_groups()
            ],
        )
        self.groups.append(group)
        self._refresh_list()
        self._select_idx(len(self.groups) - 1)

    def _remove(self):
        if not (0 <= self._idx < len(self.groups)):
            return
        old_idx = self._idx
        del self.groups[self._idx]
        self._idx = -1
        self._refresh_list()
        if self.groups:
            self._select_idx(min(old_idx, len(self.groups) - 1))
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
        is_reinforce = isinstance(group, ReinforceGroupSpec)
        self._loading = True
        self.name.setText(group.name)
        self.folder.setText(getattr(group, 'folder', '') or '')
        self.gtype.setCurrentText("ReinforceGroup" if is_reinforce else "BuildingGroup")
        self.player.setValue(group.player)
        for widget in (self.rect_x, self.rect_y, self.rect_w, self.rect_h, self.pick_rect):
            self.form.setRowVisible(widget, not is_reinforce)
        self.form.setRowVisible(self.target_text, is_reinforce)
        if not is_reinforce:
            self.rect_x.setValue(group.rect_x)
            self.rect_y.setValue(group.rect_y)
            self.rect_w.setValue(group.rect_width)
            self.rect_h.setValue(group.rect_height)
        else:
            self.target_text.setPlainText(self._targets_to_text(group.targets))
        self._refresh_units(group)
        self._loading = False

    def _refresh_units(self, group):
        self.unit_list.blockSignals(True)
        self.unit_list.clear()
        if isinstance(group, ReinforceGroupSpec):
            objects = self.reinforce_factories
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
        is_reinforce = isinstance(group, ReinforceGroupSpec)
        fallback = "ReinforceGroup" if is_reinforce else "BuildingGroup"
        group.name = self.name.text().strip() or f"{fallback}{self._idx + 1}"
        group.folder = self.folder.text().strip()
        group.player = self.player.value()
        if not is_reinforce:
            group.rect_x = self.rect_x.value()
            group.rect_y = self.rect_y.value()
            group.rect_width = self.rect_w.value()
            group.rect_height = self.rect_h.value()
        selected = []
        for i in range(self.unit_list.count()):
            item = self.unit_list.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        group.unit_ids = selected
        if is_reinforce:
            group.targets = self._targets_from_text(self.target_text.toPlainText())
        item = self.glist.currentItem()
        if item and item.data(0, Qt.UserRole) is not None:
            item.setText(0, self._summary(group))

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
