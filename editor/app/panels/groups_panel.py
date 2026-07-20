from __future__ import annotations
from collections import defaultdict

from PySide6.QtWidgets import QSplitter

from ..common import *
from ..style import apply_role


class GroupsPanel(QWidget):
    rect_pick_requested = Signal(object)  # emits the BuildingGroupSpec object

    def __init__(self, window):
        super().__init__()
        self._window = window
        self.groups: list = []
        self._idx = -1
        self._loading = False

        # --- Gruppen-Liste (links) ---
        self.glist = QTreeWidget()
        self.glist.setHeaderHidden(True)
        self.glist.currentItemChanged.connect(self._on_item_changed)
        add_building = QPushButton(tr("groups.add_building"))
        add_building.clicked.connect(self._add_building)
        apply_role(add_building, "primary")
        add_reinforce = QPushButton(tr("groups.add_reinforce"))
        add_reinforce.clicked.connect(self._add_reinforce)
        apply_role(add_reinforce, "primary")
        add_fight = QPushButton(tr("groups.add_fight"))
        add_fight.clicked.connect(self._add_fight)
        apply_role(add_fight, "primary")
        add_mining = QPushButton(tr("groups.add_mining"))
        add_mining.clicked.connect(self._add_mining)
        apply_role(add_mining, "primary")
        rm_btn = QPushButton(tr("groups.remove"))
        rm_btn.clicked.connect(self._remove)
        apply_role(rm_btn, "danger")
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(QLabel(tr("groups.groups_label")))
        left_lay.addWidget(self.glist, 1)
        left_lay.addWidget(add_building)
        left_lay.addWidget(add_reinforce)
        left_lay.addWidget(add_fight)
        left_lay.addWidget(add_mining)
        left_lay.addWidget(rm_btn)

        # --- Detailformular ---
        self.name = QLineEdit()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(tr("groups.folder_placeholder"))
        self.gtype = QComboBox()
        self.gtype.addItems(["BuildingGroup", "ReinforceGroup", "FightGroup", "MiningGroup"])
        self.gtype.setEnabled(False)
        self.player = QSpinBox()
        self.player.setRange(0, 5)
        self.rect_x = QSpinBox()
        self.rect_x.setRange(0, 1023)
        self.rect_y = QSpinBox()
        self.rect_y.setRange(0, 1023)
        self.rect_w = QSpinBox()
        self.rect_w.setRange(1, 256)
        self.rect_w.setValue(8)
        self.rect_h = QSpinBox()
        self.rect_h.setRange(1, 256)
        self.rect_h.setValue(8)
        self.pick_rect = QPushButton(tr("groups.pick_rect"))
        self.pick_rect.clicked.connect(self._pick_rect)
        self.unit_list = QListWidget()
        self.target_text = QPlainTextEdit()
        self.target_text.setPlaceholderText(tr("groups.target_placeholder"))
        self.target_text.setMaximumHeight(120)

        self.rect_section_label = QLabel(tr("groups.row_build_rect"))
        self.rect_section_label.setProperty("role", "section")

        self.form = QFormLayout()
        self.form.addRow(tr("groups.row_name"), self.name)
        self.form.addRow(tr("groups.lbl_folder"), self.folder)
        self.form.addRow(tr("groups.row_type"), self.gtype)
        self.form.addRow(tr("groups.row_player"), self.player)
        self.form.addRow(self.rect_section_label)
        self.form.addRow(tr("groups.row_rect_x"), self.rect_x)
        self.form.addRow(tr("groups.row_rect_y"), self.rect_y)
        self.form.addRow(tr("groups.row_rect_width"), self.rect_w)
        self.form.addRow(tr("groups.row_rect_height"), self.rect_h)
        self.form.addRow("", self.pick_rect)
        self.form.addRow(tr("groups.row_units"), self.unit_list)
        self.record_all = QCheckBox(tr("groups.chk_record_all"))
        self.record_all.setToolTip(tr("groups.tooltip_record_all"))
        self.form.addRow(self.record_all)
        # MiningGroup: Mine/Smelter als benannte Gebaeude-Anker referenzieren
        # (platziert ODER per recordBuilding geplant). Handle wird nach
        # Zerstoerung + Wiederaufbau automatisch neu gebunden.
        # MiningGroup: reference mine/smelter as named building anchors
        # (placed OR planned via recordBuilding). Handle rebinds after
        # destruction + rebuild automatically.
        self.mine_ref = QComboBox()
        self.mine_ref.setToolTip(tr("groups.tooltip_mine_ref"))
        self.smelter_ref = QComboBox()
        self.smelter_ref.setToolTip(tr("groups.tooltip_smelter_ref"))
        self.form.addRow(tr("groups.row_mine_ref"), self.mine_ref)
        self.form.addRow(tr("groups.row_smelter_ref"), self.smelter_ref)
        self.mining_source = QComboBox()
        self.mining_source.setToolTip(tr("groups.tooltip_mining_source"))
        self.mining_prio = QSpinBox()
        self.mining_prio.setRange(1, 65535)
        self.mining_prio.setValue(1000)
        self.form.addRow(tr("groups.row_mining_source"), self.mining_source)
        self.form.addRow(tr("groups.row_mining_prio"), self.mining_prio)
        self.unit_list.setToolTip(tr("groups.tooltip_roster"))
        self.form.addRow(tr("groups.row_targets"), self.target_text)

        self.name.textChanged.connect(self._store_current)
        self.folder.textChanged.connect(self._store_current)
        self.folder.editingFinished.connect(self._refresh_list)
        for w in (self.player, self.rect_x, self.rect_y, self.rect_w, self.rect_h):
            w.valueChanged.connect(self._store_current)
        self.unit_list.itemChanged.connect(self._store_current)
        self.record_all.toggled.connect(self._store_current)
        self.mine_ref.currentIndexChanged.connect(self._store_current)
        self.smelter_ref.currentIndexChanged.connect(self._store_current)
        self.mining_source.currentIndexChanged.connect(self._store_current)
        self.mining_prio.valueChanged.connect(self._store_current)
        self.target_text.textChanged.connect(self._store_current)

        detail_inner = QWidget()
        detail_inner.setLayout(self.form)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(detail_inner)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(left)
        splitter.addWidget(detail_scroll)
        splitter.setSizes([160, 380])

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(splitter)

        self._set_form_enabled(False)

    # --- Öffentliche API ---

    def load(self):
        w = self._window
        self.groups = (list(w.building_groups) + list(w.reinforce_groups)
                       + list(w.fight_groups) + list(w.mining_groups))
        self._idx = -1
        self.player.setRange(0, max(0, len(w.players) - 1))
        self._refresh_list()
        if self.groups:
            self._select_idx(0)
        else:
            self._set_form_enabled(False)

    def refresh(self):
        # Resync group objects (e.g. rect changed after map pick)
        self._refresh_list()
        # Reload form if a group is selected
        if 0 <= self._idx < len(self.groups):
            self._load(self._idx)

    def select(self, group_name):
        for i, g in enumerate(self.groups):
            if g.name == group_name:
                self._select_idx(i)
                return

    # --- Interne Hilfsmethoden ---

    def _planned_named_buildings(self, types=None):
        """Per recordBuilding GEPLANTE Gebaeude mit unit_name: [(name, type, x, y)].

        PLANNED buildings (recordBuilding entries) with a unit_name."""
        out = []
        seen = set()
        for t in self._window.triggers:
            stack = list(t.actions)
            while stack:
                a = stack.pop()
                stack.extend(getattr(a, "then_actions", None) or [])
                stack.extend(getattr(a, "else_actions", None) or [])
                if getattr(a, "kind", "") != "recordBuilding":
                    continue
                for e in (getattr(a, "building_list", None) or []):
                    name = (e.get("unit_name", "") or "").strip()
                    bt = e.get("building_type", "")
                    if not name or name in seen:
                        continue
                    if types is not None and bt not in types:
                        continue
                    seen.add(name)
                    out.append((name, bt, int(e.get("x", 0)), int(e.get("y", 0))))
        return out

    def _all_unit_names(self):
        names = {getattr(o, "unit_name", "") for o in self._window.objects
                 if getattr(o, "unit_name", "")}
        names |= {n for (n, _t, _x, _y) in self._planned_named_buildings()}
        return names

    def _auto_name(self, base):
        """Eindeutigen Namen wie Mine1/Smelter2 erzeugen. / Generate a unique name."""
        names = self._all_unit_names()
        i = 1
        while f"{base}{i}" in names:
            i += 1
        return f"{base}{i}"

    def _fill_ref_combo(self, combo, placed_types, base, current):
        """Ref-Combo befuellen: leer + platzierte (benannt/unbenannt) +
        geplante benannte Gebaeude der passenden Typen.

        Fill a ref combo: empty + placed (named/unnamed) + planned named
        buildings of the matching types."""
        # String-Daten statt Tupel: QComboBox.findData matcht Python-Tupel
        # nicht zuverlaessig. / String data instead of tuples: findData does
        # not reliably match Python tuples.
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("groups.ref_none"), "")
        for o in self._window.objects:
            if getattr(o, "map_id", "") not in placed_types:
                continue
            uname = getattr(o, "unit_name", "") or ""
            if uname:
                combo.addItem(f"{uname}  ({o.display} @ {o.tile_x},{o.tile_y})",
                              f"name:{uname}")
            else:
                combo.addItem(tr("groups.ref_unnamed", d=o.display, x=o.tile_x, y=o.tile_y),
                              f"uid:{o.uid}")
        for (name, bt, x, y) in self._planned_named_buildings(placed_types):
            combo.addItem(tr("groups.ref_planned", name=name, x=x, y=y), f"name:{name}")
        idx = combo.findData(f"name:{current}") if current else 0
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _resolve_ref_combo(self, combo, base):
        """Auswahl der Ref-Combo -> Unit-Name; unbenannte platzierte
        Gebaeude bekommen dabei automatisch einen eindeutigen Namen.

        Resolve a ref combo selection to a unit name; unnamed placed
        buildings automatically receive a unique name."""
        data = combo.currentData()
        if not data or not isinstance(data, str):
            return ""
        if data.startswith("name:"):
            return data[5:]
        if data.startswith("uid:"):
            for o in self._window.objects:
                if getattr(o, "uid", "") == data[4:]:
                    name = self._auto_name(base)
                    o.unit_name = name
                    return name
        return ""

    def _builders(self):
        return [
            o for o in self._window.objects
            if o.map_id in ("mapStructureFactory", "mapVehicleFactory", "mapConVec", "mapEarthworker")
        ]

    def _reinforce_factories(self):
        return [
            o for o in self._window.objects
            if o.map_id in ("mapVehicleFactory", "mapArachnidFactory")
        ]

    def _fight_vehicles(self):
        military_ids = {m for _, m in MILITARY_VEHICLES}
        return [o for o in self._window.objects if o.map_id in military_ids]

    def _trucks(self):
        return [o for o in self._window.objects if o.map_id == "mapCargoTruck"]

    def _building_groups(self):
        return [g for g in self.groups if isinstance(g, BuildingGroupSpec)]

    def _reinforce_groups(self):
        return [g for g in self.groups if isinstance(g, ReinforceGroupSpec)]

    def _fight_groups(self):
        return [g for g in self.groups if isinstance(g, FightGroupSpec)]

    def _mining_groups(self):
        return [g for g in self.groups if isinstance(g, MiningGroupSpec)]

    def _sync_to_window(self):
        self._window.building_groups = self._building_groups()
        self._window.reinforce_groups = self._reinforce_groups()
        self._window.fight_groups = self._fight_groups()
        self._window.mining_groups = self._mining_groups()
        self._window._refresh_overview()
        # Bereits offene Aktionsformulare (z.B. eine startMining-Aktion, deren
        # Gruppen-Dropdown noch den alten Gruppen-Stand zeigt) mit dem
        # aktuellen Gruppen-Stand neu aufbauen -- sonst taucht eine gerade
        # erst angelegte Gruppe dort nicht auf, bis man den Trigger wechselt.
        # Rebuild already-open action forms (e.g. a startMining action whose
        # group dropdown still shows the old group list) with the current
        # group state -- otherwise a just-created group won't show up there
        # until the user switches triggers.
        self._window.trigger_panel.refresh_actions()

    def _object_label(self, o):
        name = f"{o.unit_name}: " if o.unit_name else ""
        return f"{name}{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})"

    def _summary(self, group):
        if isinstance(group, ReinforceGroupSpec):
            return reinforce_group_summary(group)
        if isinstance(group, FightGroupSpec):
            return fight_group_summary(group)
        if isinstance(group, MiningGroupSpec):
            return mining_group_summary(group)
        return building_group_summary(group)

    def _set_form_enabled(self, on):
        for w in (self.name, self.folder, self.player, self.rect_x,
                  self.rect_y, self.rect_w, self.rect_h, self.unit_list, self.target_text):
            w.setEnabled(on)

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
                font = f_item.font(0)
                font.setBold(True)
                f_item.setFont(0, font)
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
        elif prev_idx >= 0 and not self.groups:
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
        builders = self._builders()
        group = BuildingGroupSpec(
            name=f"BuildingGroup{len(self._building_groups()) + 1}",
            player=0,
            rect_x=0, rect_y=0,
            rect_width=8, rect_height=8,
            unit_ids=[o.uid for o in builders if o.player == 0],
        )
        self.groups.append(group)
        self._sync_to_window()
        self._refresh_list()
        self._select_idx(len(self.groups) - 1)

    def _add_reinforce(self):
        factories = self._reinforce_factories()
        group = ReinforceGroupSpec(
            name=f"ReinforceGroup{len(self._reinforce_groups()) + 1}",
            player=0,
            unit_ids=[o.uid for o in factories if o.player == 0],
            targets=[ReinforceTargetSpec(g.name, 1500) for g in self._building_groups()],
        )
        self.groups.append(group)
        self._sync_to_window()
        self._refresh_list()
        self._select_idx(len(self.groups) - 1)

    def _add_fight(self):
        vehicles = self._fight_vehicles()
        group = FightGroupSpec(
            name=f"FightGroup{len(self._fight_groups()) + 1}",
            player=0,
            idle_x=0, idle_y=0,
            idle_width=8, idle_height=8,
            unit_ids=[o.uid for o in vehicles if o.player == 0],
        )
        self.groups.append(group)
        self._sync_to_window()
        self._refresh_list()
        self._select_idx(len(self.groups) - 1)

    def _add_mining(self):
        smelters = [o for o in self._window.objects
                    if o.map_id in ("mapCommonOreSmelter", "mapRareOreSmelter")]
        s = smelters[0] if smelters else None
        idle_x = max(0, s.tile_x - 4) if s else 0
        idle_y = max(0, s.tile_y - 3) if s else 0
        player = s.player if s else 0
        trucks = self._trucks()
        group = MiningGroupSpec(
            name=f"MiningGroup{len(self._mining_groups()) + 1}",
            player=player,
            idle_x=idle_x, idle_y=idle_y,
            idle_width=9, idle_height=7,
            unit_ids=[o.uid for o in trucks if o.player == player],
        )
        self.groups.append(group)
        self._sync_to_window()
        self._refresh_list()
        self._select_idx(len(self.groups) - 1)

    def _remove(self):
        if not (0 <= self._idx < len(self.groups)):
            return
        old_idx = self._idx
        del self.groups[self._idx]
        self._idx = -1
        self._sync_to_window()
        self._refresh_list()
        if self.groups:
            self._select_idx(min(old_idx, len(self.groups) - 1))
        else:
            self._set_form_enabled(False)

    def _pick_rect(self):
        if not (0 <= self._idx < len(self.groups)):
            return
        self._store_current()
        self.rect_pick_requested.emit(self.groups[self._idx])

    def _load(self, i):
        group = self.groups[i]
        is_reinforce = isinstance(group, ReinforceGroupSpec)
        is_fight = isinstance(group, FightGroupSpec)
        is_mining = isinstance(group, MiningGroupSpec)
        has_rect = not is_reinforce
        self._loading = True
        self.name.setText(group.name)
        self.folder.setText(getattr(group, 'folder', '') or '')
        gtype_name = ("MiningGroup" if is_mining else
                      "FightGroup" if is_fight else
                      "ReinforceGroup" if is_reinforce else "BuildingGroup")
        self.gtype.setCurrentText(gtype_name)
        self.player.setValue(group.player)
        for widget in (self.rect_x, self.rect_y, self.rect_w, self.rect_h, self.pick_rect):
            self.form.setRowVisible(widget, has_rect)
        self.form.setRowVisible(self.target_text, is_reinforce)
        is_building = not (is_reinforce or is_fight or is_mining)
        self.form.setRowVisible(self.record_all, is_building)
        if is_building:
            self.record_all.setChecked(bool(getattr(group, "record_all", True)))
        self.form.setRowVisible(self.mine_ref, is_mining)
        self.form.setRowVisible(self.smelter_ref, is_mining)
        self.form.setRowVisible(self.mining_source, is_mining)
        self.form.setRowVisible(self.mining_prio, is_mining)
        if is_mining:
            self._fill_ref_combo(self.mine_ref,
                                 ("mapCommonOreMine", "mapRareOreMine"), "Mine",
                                 getattr(group, "mine_ref", "") or "")
            self._fill_ref_combo(self.smelter_ref,
                                 ("mapCommonOreSmelter", "mapRareOreSmelter"), "Smelter",
                                 getattr(group, "smelter_ref", "") or "")
            self.mining_source.blockSignals(True)
            self.mining_source.clear()
            self.mining_source.addItem(tr("groups.ref_none"), "")
            for rg in self._reinforce_groups():
                self.mining_source.addItem(f"{rg.name} [ReinforceGroup]", rg.name)
            si = self.mining_source.findData(getattr(group, "source_group_name", "") or "")
            self.mining_source.setCurrentIndex(si if si >= 0 else 0)
            self.mining_source.blockSignals(False)
            self.mining_prio.setValue(int(getattr(group, "reinforce_priority", 1000) or 1000))
        rect_label = tr("groups.row_idle_rect") if (is_fight or is_mining) else tr("groups.row_build_rect")
        self.form.setRowVisible(self.rect_section_label, has_rect)
        self.rect_section_label.setText(rect_label)
        if is_fight or is_mining:
            self.rect_x.setValue(group.idle_x)
            self.rect_y.setValue(group.idle_y)
            self.rect_w.setValue(group.idle_width)
            self.rect_h.setValue(group.idle_height)
        elif has_rect:
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
            objects = self._reinforce_factories()
        elif isinstance(group, FightGroupSpec):
            objects = self._fight_vehicles()
        elif isinstance(group, MiningGroupSpec):
            objects = self._trucks()
        else:
            objects = self._builders()
        selected = set(group.unit_ids)
        for o in objects:
            item = QListWidgetItem(self._object_label(o))
            item.setData(Qt.UserRole, o.uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if o.uid in selected else Qt.Unchecked)
            self.unit_list.addItem(item)
        # Geplante benannte Gebaeude (recordBuilding + unit_name): werden nach
        # dem Bau automatisch ins Roster uebernommen (plan:<Name>).
        # Planned named buildings (recordBuilding + unit_name): taken into
        # the roster automatically once built (plan:<name>).
        plan_types = None
        if isinstance(group, ReinforceGroupSpec):
            plan_types = ("mapVehicleFactory", "mapArachnidFactory")
        elif not isinstance(group, (FightGroupSpec, MiningGroupSpec)):
            plan_types = ("mapStructureFactory",)
        if plan_types is not None:
            for (name, bt, x, y) in self._planned_named_buildings(plan_types):
                pid = f"plan:{name}"
                item = QListWidgetItem(tr("groups.roster_planned", name=name, x=x, y=y))
                item.setData(Qt.UserRole, pid)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if pid in selected else Qt.Unchecked)
                self.unit_list.addItem(item)
        self.unit_list.blockSignals(False)

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.groups)):
            return
        group = self.groups[self._idx]
        is_reinforce = isinstance(group, ReinforceGroupSpec)
        is_fight = isinstance(group, FightGroupSpec)
        is_mining = isinstance(group, MiningGroupSpec)
        fallback = ("MiningGroup" if is_mining else
                    "FightGroup" if is_fight else
                    "ReinforceGroup" if is_reinforce else "BuildingGroup")
        group.name = self.name.text().strip() or f"{fallback}{self._idx + 1}"
        group.folder = self.folder.text().strip()
        group.player = self.player.value()
        if is_fight or is_mining:
            group.idle_x = self.rect_x.value()
            group.idle_y = self.rect_y.value()
            group.idle_width = self.rect_w.value()
            group.idle_height = self.rect_h.value()
        elif not is_reinforce:
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
        if not (is_reinforce or is_fight or is_mining):
            group.record_all = self.record_all.isChecked()
        if is_mining:
            group.mine_ref = self._resolve_ref_combo(self.mine_ref, "Mine")
            group.smelter_ref = self._resolve_ref_combo(self.smelter_ref, "Smelter")
            group.source_group_name = self.mining_source.currentData() or ""
            group.reinforce_priority = self.mining_prio.value()
        if is_reinforce:
            group.targets = self._targets_from_text(self.target_text.toPlainText())
        item = self.glist.currentItem()
        if item and item.data(0, Qt.UserRole) is not None:
            item.setText(0, self._summary(group))
        self._window._refresh_overview()

    def _targets_to_text(self, targets):
        return "\n".join(f"{t.group_name}={t.priority}" for t in targets)

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
