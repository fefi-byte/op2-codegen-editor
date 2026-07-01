"""Verschachtelter Aktions-Editor (Home-Assistant-Stil, Karten).

ActionListWidget rendert eine Liste von Aktionen als Karten + "+ Aktion".
Eine if-Aktion (kind == "if") ist eine Karte mit Wenn/Dann/Sonst, wobei Dann
und Sonst wieder ActionListWidgets enthalten (rekursiv).

Nested action editor (Home-Assistant style, card-based).
ActionListWidget renders a list of actions as cards plus a "+ Action" button.
An "if" action (kind == "if") is a card with When/Then/Else, where Then and
Else again contain ActionListWidgets (recursive nesting).
"""
from __future__ import annotations

from ..common import *
from ..summary import action_kind_label, action_params_summary
from ..style import ACTION_CATEGORY_COLOR, apply_role

# Aktionstypen, die per Dialog (mit Parametern) angelegt werden:
# Action kinds that are created via a dialog (with parameters):
_DIALOG_KINDS = {label: k for label, k in ACTION_KINDS.items() if k not in ("if", "noop")}


class ConditionEditDialog(QDialog):
    """Dialog zum Bearbeiten einer einzelnen Wenn-Bedingung einer if-Aktion.

    Dialog for editing a single When-condition of an "if" action.
    """
    def __init__(self, parent, condition=None, variables=None, diff_values=None):
        super().__init__(parent)
        self.setWindowTitle(tr("action_editor.dlg_condition_title"))
        self.kind = QComboBox(); fill_combo(self.kind, ACTION_CONDITION_KINDS, "action_conditions")
        self.kind.currentTextChanged.connect(self._update)
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.building.addItem(d, m)
        self.x = QSpinBox(); self.x.setRange(0, 1023)
        self.y = QSpinBox(); self.y.setRange(0, 1023)
        self.compare = QComboBox(); self.compare.addItems(COMPARE.keys())
        self.value = ExprEdit(diff_values=diff_values)
        self.value.setValue(0)
        self.resource = QComboBox(); self.resource.addItems(RESOURCES.keys())
        self.tech_id = QSpinBox(); self.tech_id.setRange(0, 20000)
        self.var_name = QComboBox()
        for v in (variables or []):
            self.var_name.addItem(v.name, v.name)
        self.negate = QCheckBox(tr("action_editor.chk_negate"))
        self.form = QFormLayout()
        self.form.addRow(tr("action_editor.lbl_type"), self.kind)
        self._rows = {"player": self.player, "building": self.building, "x": self.x, "y": self.y,
                      "compare": self.compare, "value": self.value, "resource": self.resource,
                      "tech_id": self.tech_id, "var_name": self.var_name}
        labels = {"player": tr("action_editor.lbl_player"), "building": tr("action_editor.lbl_building"),
                  "x": tr("action_editor.lbl_x"), "y": tr("action_editor.lbl_y"),
                  "compare": tr("action_editor.lbl_compare"), "value": tr("action_editor.lbl_value"),
                  "resource": tr("action_editor.lbl_resource"), "tech_id": tr("action_editor.lbl_tech_id"),
                  "var_name": tr("action_editor.lbl_var_name")}
        for k, w in self._rows.items():
            self.form.addRow(labels[k], w)
        self.form.addRow("", self.negate)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(self.form); lay.addWidget(btns)
        if condition is not None:
            self._load(condition)
        self._update()

    def _update(self):
        fields = ACTION_CONDITION_KINDS[self.kind.currentData()][1]
        for k, w in self._rows.items():
            self.form.setRowVisible(w, k in fields)

    def _load(self, c):
        for label, (kind, _) in ACTION_CONDITION_KINDS.items():
            if kind == c.kind:
                self.kind.setCurrentIndex(self.kind.findData(label)); break
        self.player.setValue(c.player)
        bi = self.building.findData(c.building_type)
        if bi >= 0:
            self.building.setCurrentIndex(bi)
        self.x.setValue(c.x); self.y.setValue(c.y)
        self.compare.setCurrentText({v: k for k, v in COMPARE.items()}.get(c.compare, "≥"))
        self.value.setValue(c.value)
        self.resource.setCurrentText({v: k for k, v in RESOURCES.items()}.get(c.resource, "Common Ore"))
        self.tech_id.setValue(c.tech_id)
        self.negate.setChecked(c.negate)
        vn = getattr(c, 'var_name', '') or ''
        i = self.var_name.findData(vn)
        if i >= 0:
            self.var_name.setCurrentIndex(i)

    def result(self):
        return ActionCondition(
            kind=ACTION_CONDITION_KINDS[self.kind.currentData()][0],
            negate=self.negate.isChecked(), player=self.player.value(),
            building_type=self.building.currentData(), x=self.x.value(), y=self.y.value(),
            compare=COMPARE[self.compare.currentText()], value=self.value.value(),
            resource=RESOURCES[self.resource.currentText()], tech_id=self.tech_id.value(),
            var_name=self.var_name.currentData() or "")


class ActionInlineForm(QWidget):
    """Inline-Formular zum Bearbeiten einer Aktion direkt in der ActionCard.

    Inline form for editing an action directly inside its ActionCard.
    Changes are written to the action object immediately on every widget change.
    """
    changed = Signal()
    pick_requested = Signal(str)  # "primary" or "secondary"

    _VIS = {
        "message": ["text"],
        "createUnit": ["unit", "weapon", "x", "y", "player"],
        "createDisaster": ["disaster_type", "x_expr", "y_expr"],
        "createTrigger": ["target"],
        "recordBuilding": ["group", "building", "x", "y"],
        "recordTube": ["group", "x", "y", "x2", "y2"],
        "recordWall": ["group", "wall", "x", "y", "x2", "y2"],
        "setTargCount": ["target_group", "source_group", "vehicle", "priority", "target_count"],
        "assignToGroup": ["assign_group", "building", "x", "y", "player"],
        "modVar": ["var_name", "mod_mode", "var_expr"],
    }

    _LABEL_OVERRIDES = {
        "recordTube": {"x": "Start X:", "y": "Start Y:", "x2": "Ende X:", "y2": "Ende Y:"},
        "recordWall": {"x": "Start X:", "y": "Start Y:", "x2": "Ende X:", "y2": "Ende Y:"},
    }

    def __init__(self, action, ctx):
        super().__init__()
        self._action = action
        self.ctx = ctx
        diff_values = ctx.get("diff_values") if isinstance(ctx, dict) else None

        self.kind = QComboBox()
        for label, k in _DIALOG_KINDS.items():
            self.kind.addItem(tr(f"action_kinds.{k}"), k)
        self.kind.currentIndexChanged.connect(self._update)

        self.text = QLineEdit(tr("action_editor.default_message"))
        self.unit = QComboBox()
        for d, m in ALL_UNITS:
            self.unit.addItem(d, m)
        self.weapon = QComboBox()
        for d, m in WEAPONS:
            self.weapon.addItem(d, m)
        self.x = QSpinBox(); self.x.setRange(0, 1023)
        self.y = QSpinBox(); self.y.setRange(0, 1023)
        self.x2 = QSpinBox(); self.x2.setRange(0, 1023)
        self.y2 = QSpinBox(); self.y2.setRange(0, 1023)
        self.x_expr = ExprEdit(diff_values=diff_values)
        self.y_expr = ExprEdit(diff_values=diff_values)
        self.x2_expr = ExprEdit(diff_values=diff_values)
        self.y2_expr = ExprEdit(diff_values=diff_values)
        self.x_expr.setPlaceholderText("z.B. 50, 50 + getRand(51), randBetween(50, 100)")
        self.y_expr.setPlaceholderText("z.B. 70 oder randBetween(20, 40)")
        self.x2_expr.setPlaceholderText("z.B. 80 oder randBetween(80, 120)")
        self.y2_expr.setPlaceholderText("z.B. 95")
        self.disaster_type = QComboBox()
        for label, value in DISASTER_TYPES.items():
            self.disaster_type.addItem(label, value)
        self.disaster_type.currentIndexChanged.connect(self._update)
        self.size = QComboBox()
        for label, value in METEOR_SIZES.items():
            self.size.addItem(label, value)
        self.magnitude = ExprEdit(diff_values=diff_values)
        self.magnitude.setPlaceholderText("z.B. 1, 5 oder ceil(8 * diff / 10)")
        self.duration = ExprEdit(diff_values=diff_values)
        self.duration.setPlaceholderText("Ticks, z.B. 300 oder 5 * 100")
        self.spread_speed = QSpinBox()
        self.spread_speed.setRange(1, 200)
        self.spread_speed.setValue(15)
        self.spread_speed.setToolTip("Ausbreitungsgeschwindigkeit der Lava (15 = sehr langsam, 45 = mittel)")
        self.lava_zone_btn = QPushButton("🌋 Lava Zone bearbeiten")
        self.lava_zone_btn.clicked.connect(lambda: self._request_pick("lava_zone"))
        self.lava_zone_lbl = QLabel("0 Kacheln definiert")
        self.lava_zone_lbl.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self.now = QCheckBox("Sofort einschlagen (ohne Warnphase)")
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.target = QComboBox()
        for t in (ctx.get("triggers") or [] if isinstance(ctx, dict) else []):
            self.target.addItem(t.name, t.name)
        self.group = QComboBox()
        for g in (ctx.get("building_groups") or [] if isinstance(ctx, dict) else []):
            self.group.addItem(f"{g.name} [BuildingGroup]", g.name)
        self.building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.building.addItem(d, m)
        self.wall = QComboBox()
        for d, m, _ in WALL_ITEMS:
            if m != "mapTube":
                self.wall.addItem(d, m)
        tgt_groups = ctx.get("target_groups") or [] if isinstance(ctx, dict) else []
        tgt_types = ctx.get("target_group_types") or {} if isinstance(ctx, dict) else {}
        self.target_group = QComboBox()
        for g in tgt_groups:
            self.target_group.addItem(f"{g.name} [{tgt_types.get(g.name, 'BuildingGroup')}]", g.name)
        self.target_group.currentIndexChanged.connect(self._update_vehicles)
        self.source_group = QComboBox()
        for g in (ctx.get("reinforce_groups") or [] if isinstance(ctx, dict) else []):
            self.source_group.addItem(f"{g.name} [ReinforceGroup]", g.name)
        self.vehicle = QComboBox()
        self.priority = QSpinBox(); self.priority.setRange(1, 65535); self.priority.setValue(1000)
        self.target_count = ExprEdit(diff_values=diff_values)
        self.target_count.setValue(1)
        self.assign_group = QComboBox()
        for name, gtype in (ctx.get("all_groups") or [] if isinstance(ctx, dict) else []):
            self.assign_group.addItem(f"{name} [{gtype}]", name)
        self.var_name = QComboBox()
        for v in (ctx.get("variables") or [] if isinstance(ctx, dict) else []):
            self.var_name.addItem(v.name, v.name)
        self.mod_mode = QComboBox()
        self.mod_mode.addItem("+1 (Inkrementieren)", "inc")
        self.mod_mode.addItem("-1 (Dekrementieren)", "dec")
        self.mod_mode.addItem("Ausdruck …", "expr")
        self.mod_mode.currentIndexChanged.connect(self._update)
        self.var_expr = ExprEdit(diff_values=diff_values)

        self.form = QFormLayout()
        self.form.addRow(tr("action_editor.lbl_action_type"), self.kind)
        self._rows = {
            "text": self.text, "unit": self.unit, "weapon": self.weapon,
            "x": self.x, "y": self.y, "x2": self.x2, "y2": self.y2,
            "x_expr": self.x_expr, "y_expr": self.y_expr,
            "x2_expr": self.x2_expr, "y2_expr": self.y2_expr,
            "disaster_type": self.disaster_type, "size": self.size,
            "magnitude": self.magnitude, "duration": self.duration,
            "spread_speed": self.spread_speed,
            "lava_zone_btn": self.lava_zone_btn, "lava_zone_lbl": self.lava_zone_lbl,
            "now": self.now,
            "player": self.player, "target": self.target,
            "group": self.group, "building": self.building, "wall": self.wall,
            "target_group": self.target_group, "source_group": self.source_group,
            "vehicle": self.vehicle, "priority": self.priority,
            "target_count": self.target_count, "assign_group": self.assign_group,
            "var_name": self.var_name, "mod_mode": self.mod_mode, "var_expr": self.var_expr,
        }
        labels = {
            "text": tr("action_editor.lbl_text"), "unit": tr("action_editor.lbl_unit"),
            "weapon": tr("action_editor.lbl_weapon_cargo"),
            "x": tr("action_editor.lbl_x"), "y": tr("action_editor.lbl_y"),
            "x2": tr("action_editor.lbl_x2"), "y2": tr("action_editor.lbl_y2"),
            "player": tr("action_editor.lbl_player"),
            "x_expr": "X (Ausdruck):", "y_expr": "Y (Ausdruck):",
            "x2_expr": "X2 (Ausdruck):", "y2_expr": "Y2 (Ausdruck):",
            "disaster_type": "Katastrophentyp:", "size": "Meteor-Größe:",
            "magnitude": "Magnitude:", "duration": "Dauer (Ticks):",
            "spread_speed": "Ausbreitungsgeschwindigkeit:",
            "lava_zone_btn": "", "lava_zone_lbl": "Lava Zone:",
            "now": "Sofort:",
            "target": tr("action_editor.lbl_target_trigger"), "group": "BuildingGroup:",
            "building": tr("action_editor.lbl_building"), "wall": "Wall:",
            "target_group": tr("action_editor.lbl_target_group"), "source_group": "ReinforceGroup:",
            "vehicle": tr("action_editor.lbl_vehicle"), "priority": tr("action_editor.lbl_priority"),
            "target_count": tr("action_editor.lbl_target_count"),
            "assign_group": tr("action_editor.lbl_target_group"),
            "var_name": tr("action_editor.lbl_var_name"), "mod_mode": tr("action_editor.lbl_mod_mode"),
            "var_expr": tr("action_editor.lbl_var_expr"),
        }
        for k, w in self._rows.items():
            self.form.addRow(labels[k], w)
        self.pick_xy_btn = QPushButton("📍 X / Y auf Karte setzen")
        self.pick_xy_btn.clicked.connect(lambda: self._request_pick("primary"))
        self.pick_xy2_btn = QPushButton("📍 X2 / Y2 auf Karte setzen")
        self.pick_xy2_btn.clicked.connect(lambda: self._request_pick("secondary"))
        self.form.addRow("", self.pick_xy_btn)
        self.form.addRow("", self.pick_xy2_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(self.form)

        self._load(action)
        self._connect_save_signals()

    # --- Interne Hilfsmethoden ---

    def _current_kind(self):
        return self.kind.currentData()

    def _current_disaster_type(self):
        return self.disaster_type.currentData() or "meteor"

    def _disaster_type_from_action(self, action):
        legacy = {
            "createMeteor": "meteor", "createEarthquake": "earthquake",
            "createStorm": "storm", "createVortex": "vortex",
            "createBlight": "blight", "unsetBlight": "unblight",
        }
        if getattr(action, "kind", "") == "createDisaster":
            return getattr(action, "disaster_type", "meteor") or "meteor"
        return legacy.get(getattr(action, "kind", ""), "meteor")

    def _set_kind(self, k):
        i = self.kind.findData(k)
        if i >= 0:
            self.kind.setCurrentIndex(i)

    def _set_combo(self, combo, value):
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _apply_labels(self, kind):
        overrides = self._LABEL_OVERRIDES.get(kind, {})
        defaults = {
            "x": tr("action_editor.lbl_x"), "y": tr("action_editor.lbl_y"),
            "x2": tr("action_editor.lbl_x2"), "y2": tr("action_editor.lbl_y2"),
            "x_expr": "X (Ausdruck):", "y_expr": "Y (Ausdruck):",
            "x2_expr": "X2 (Ausdruck):", "y2_expr": "Y2 (Ausdruck):",
        }
        for key, default in defaults.items():
            widget = self._rows.get(key)
            if widget is None:
                continue
            label = self.form.labelForField(widget)
            if label is not None:
                label.setText(overrides.get(key, default))
        if kind in ("recordTube", "recordWall"):
            self.pick_xy_btn.setText("📍 Startpunkt auf Karte setzen")
            self.pick_xy2_btn.setText("📍 Endpunkt auf Karte setzen")
        elif kind == "createDisaster" and self._current_disaster_type() in ("storm", "vortex"):
            self.pick_xy_btn.setText("📍 Startposition auf Karte setzen")
            self.pick_xy2_btn.setText("📍 Zielposition auf Karte setzen")
        else:
            self.pick_xy_btn.setText("📍 X / Y auf Karte setzen")
            self.pick_xy2_btn.setText("📍 X2 / Y2 auf Karte setzen")

    def _update(self):
        kind = self._current_kind()
        fields = self._VIS.get(kind, [])
        if kind == "createDisaster":
            dtype = self._current_disaster_type()
            if dtype == "meteor":
                fields = fields + ["size", "now"]
            elif dtype == "earthquake":
                fields = fields + ["magnitude", "now"]
            elif dtype in ("storm", "vortex"):
                fields = fields + ["x2_expr", "y2_expr", "duration", "now"]
            elif dtype == "eruption":
                fields = fields + ["spread_speed", "lava_zone_btn", "lava_zone_lbl", "now"]
        for k, w in self._rows.items():
            self.form.setRowVisible(w, k in fields)
        if kind == "modVar":
            self.form.setRowVisible(self.var_expr, self.mod_mode.currentData() == "expr")
        if kind == "createDisaster":
            if self._current_disaster_type() == "eruption":
                self.now.setText("Sofort ausbrechen (ohne Verzögerung)")
            else:
                self.now.setText("Sofort einschlagen (ohne Warnphase)")
        self._apply_labels(kind)
        has_primary_xy = (("x" in fields) and ("y" in fields)) or (("x_expr" in fields) and ("y_expr" in fields))
        self.form.setRowVisible(self.pick_xy_btn, has_primary_xy)
        has_secondary_xy = (("x2" in fields) and ("y2" in fields)) or (("x2_expr" in fields) and ("y2_expr" in fields))
        self.form.setRowVisible(self.pick_xy2_btn, has_secondary_xy)
        self._update_vehicles()

    def _update_vehicles(self):
        ctx = self.ctx
        gname = self.target_group.currentData()
        tgt_types = ctx.get("target_group_types", {}) if isinstance(ctx, dict) else {}
        gtype = tgt_types.get(gname, "BuildingGroup")
        vehicles = SET_TARG_VEHICLES_BY_GROUP_TYPE.get(gtype, [])
        cur = self.vehicle.currentData()
        self.vehicle.blockSignals(True)
        self.vehicle.clear()
        for d, m in vehicles:
            self.vehicle.addItem(d, m)
        if cur is not None:
            i = self.vehicle.findData(cur)
            if i >= 0:
                self.vehicle.setCurrentIndex(i)
        self.vehicle.blockSignals(False)

    def _load(self, a):
        if getattr(a, "kind", "") in {"createMeteor", "createEarthquake", "createStorm", "createVortex", "createBlight", "unsetBlight"}:
            self._set_kind("createDisaster")
        else:
            self._set_kind(a.kind)
        self.text.setText(a.text)
        self._set_combo(self.unit, a.unit_type)
        self._set_combo(self.weapon, a.weapon_type)
        self.x.setValue(a.x); self.y.setValue(a.y); self.x2.setValue(a.x2); self.y2.setValue(a.y2)
        self._set_combo(self.disaster_type, self._disaster_type_from_action(a))
        self.x_expr.setValue(getattr(a, "x_expr", 0))
        self.y_expr.setValue(getattr(a, "y_expr", 0))
        self.x2_expr.setValue(getattr(a, "x2_expr", 0))
        self.y2_expr.setValue(getattr(a, "y2_expr", 0))
        self._set_combo(self.size, getattr(a, "size", -1))
        self.magnitude.setValue(getattr(a, "magnitude", 1))
        self.duration.setValue(getattr(a, "duration", 100))
        self.spread_speed.setValue(int(getattr(a, "spread_speed", 15) or 15))
        n = len(getattr(a, "lava_zone", None) or [])
        self.lava_zone_lbl.setText(f"{n} Kacheln definiert")
        self.now.setChecked(bool(getattr(a, "now", False)))
        self.player.setValue(a.player)
        self._set_combo(self.target, a.target)
        self._set_combo(self.group, a.group_name)
        self._set_combo(self.assign_group, a.group_name)
        self._set_combo(self.target_group, a.group_name)
        self._set_combo(self.building, a.building_type)
        self._set_combo(self.wall, a.wall_type)
        self._set_combo(self.source_group, a.source_group_name)
        self._update_vehicles()
        self._set_combo(self.vehicle, a.unit_type)
        self.priority.setValue(a.reinforce_priority)
        self.target_count.setValue(a.target_count)
        vn = getattr(a, 'var_name', '') or ''
        i = self.var_name.findData(vn)
        if i >= 0:
            self.var_name.setCurrentIndex(i)
        mm = getattr(a, 'mod_mode', 'inc') or 'inc'
        j = self.mod_mode.findData(mm)
        if j >= 0:
            self.mod_mode.setCurrentIndex(j)
        self.var_expr.setValue(getattr(a, 'var_expr', '') or '')
        self._update()

    def _connect_save_signals(self):
        self.text.textChanged.connect(self._save)
        for w in (self.x, self.y, self.x2, self.y2, self.player, self.priority, self.spread_speed):
            w.valueChanged.connect(self._save)
        for w in (self.x_expr, self.y_expr, self.x2_expr, self.y2_expr,
                  self.magnitude, self.duration, self.target_count, self.var_expr):
            w.valueChanged.connect(self._save)
        for w in (self.kind, self.unit, self.weapon, self.disaster_type, self.size,
                  self.target, self.group, self.building, self.wall,
                  self.target_group, self.source_group, self.vehicle,
                  self.assign_group, self.var_name, self.mod_mode):
            w.currentIndexChanged.connect(self._save)
        self.now.toggled.connect(self._save)

    def _save(self):
        a = self._action
        k = self._current_kind()
        a.kind = k
        a.text = self.text.text()
        a.unit_type = self.unit.currentData() or ""
        a.weapon_type = self.weapon.currentData() or "mapNone"
        a.x = self.x.value(); a.y = self.y.value()
        a.x2 = self.x2.value(); a.y2 = self.y2.value()
        dtype = self._current_disaster_type()
        a.disaster_type = dtype
        a.x_expr = self.x_expr.value(); a.y_expr = self.y_expr.value()
        a.x2_expr = self.x2_expr.value(); a.y2_expr = self.y2_expr.value()
        a.size = self.size.currentData()
        a.magnitude = self.magnitude.value()
        a.duration = self.duration.value()
        a.spread_speed = self.spread_speed.value()
        a.now = self.now.isChecked()
        a.player = self.player.value()
        a.target = self.target.currentData() or ""
        a.group_name = self.group.currentData() or ""
        a.building_type = self.building.currentData() or ""
        a.wall_type = self.wall.currentData() or ""
        if k == "setTargCount":
            a.group_name = self.target_group.currentData() or ""
            a.unit_type = self.vehicle.currentData() or ""
            a.weapon_type = "mapNone"
            a.source_group_name = self.source_group.currentData() or ""
            a.reinforce_priority = self.priority.value()
            a.target_count = self.target_count.value()
        elif k == "assignToGroup":
            a.group_name = self.assign_group.currentData() or ""
        a.var_name = self.var_name.currentData() or ""
        a.mod_mode = self.mod_mode.currentData() or "inc"
        a.var_expr = self.var_expr.text()
        self.changed.emit()

    def _request_pick(self, field: str):
        self._save()
        self.pick_requested.emit(field)


class ConditionListWidget(QWidget):
    """Wenn-Block: Liste von Bedingungen + Verknuepfung.

    When-block: list of conditions plus their AND/OR logic link.
    """
    def __init__(self, if_action, ctx=None):
        super().__init__()
        self.a = if_action
        self.ctx = ctx or {}
        self.box = QVBoxLayout(self); self.box.setContentsMargins(0, 0, 0, 0)
        self.rebuild()

    def rebuild(self):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        logic_row = QHBoxLayout()
        logic = QComboBox(); logic.addItems([tr("action_editor.logic_and"), tr("action_editor.logic_or")])
        logic.setCurrentIndex(1 if self.a.condition_logic == "or" else 0)
        logic.currentIndexChanged.connect(self._set_logic)
        logic_row.addWidget(QLabel(tr("action_editor.lbl_logic"))); logic_row.addWidget(logic); logic_row.addStretch(1)
        self.box.addLayout(logic_row)
        for c in list(self.a.conditions):
            row = QHBoxLayout()
            row.addWidget(QLabel(((tr("action_editor.not_prefix") + " ") if c.negate else "") + action_condition_summary(c)), 1)
            edit = QPushButton("✎"); edit.setFixedWidth(28); edit.clicked.connect(lambda _, cc=c: self._edit(cc))
            rm = QPushButton("✕"); rm.setFixedWidth(28); rm.clicked.connect(lambda _, cc=c: self._remove(cc))
            row.addWidget(edit); row.addWidget(rm)
            self.box.addLayout(row)
        add = QPushButton(tr("action_editor.btn_add_condition")); add.clicked.connect(self._add)
        self.box.addWidget(add)

    def _set_logic(self, idx):
        self.a.condition_logic = "or" if idx == 1 else "and"

    def _add(self):
        dlg = ConditionEditDialog(self,
                                  variables=self.ctx.get("variables"),
                                  diff_values=self.ctx.get("diff_values"))
        if dlg.exec() == QDialog.Accepted:
            self.a.conditions.append(dlg.result())
            self.rebuild()

    def _edit(self, c):
        dlg = ConditionEditDialog(self, c,
                                  variables=self.ctx.get("variables"),
                                  diff_values=self.ctx.get("diff_values"))
        if dlg.exec() == QDialog.Accepted:
            self.a.conditions[self.a.conditions.index(c)] = dlg.result()
            self.rebuild()

    def _remove(self, c):
        self.a.conditions.remove(c)
        self.rebuild()


class ActionListWidget(QWidget):
    """Liste von Aktionen als Karten + '+ Aktion hinzufügen'.

    List of actions rendered as cards plus an '+ Add action' button;
    the recursive container of the card-based nested action editor.
    """
    def __init__(self, actions, ctx):
        super().__init__()
        self.actions = actions
        self.ctx = ctx
        self.box = QVBoxLayout(self); self.box.setContentsMargins(0, 0, 0, 0)
        self.rebuild()

    def rebuild(self, expand_last=False):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for a in list(self.actions):
            self.box.addWidget(ActionCard(a, self, self.ctx))
        add = QPushButton(tr("action_editor.btn_add_action")); add.clicked.connect(self._add)
        self.box.addWidget(add)
        if expand_last:
            self._expand_last()

    def _expand_last(self):
        for i in range(self.box.count() - 1, -1, -1):
            w = self.box.itemAt(i).widget()
            if isinstance(w, ActionCard):
                w.expand()
                break

    def expand_index(self, idx: int):
        card_idx = 0
        for i in range(self.box.count()):
            w = self.box.itemAt(i).widget()
            if isinstance(w, ActionCard):
                if card_idx == idx:
                    w.expand()
                    return
                card_idx += 1

    def _collapse_all(self):
        for i in range(self.box.count()):
            item = self.box.itemAt(i)
            if item:
                w = item.widget()
                if isinstance(w, ActionCard):
                    w.collapse()

    def _add(self):
        menu = QMenu(self)
        for label, k in ACTION_KINDS.items():
            menu.addAction(tr(f"action_kinds.{k}")).setData(k)
        picked = menu.exec(QCursor.pos())
        if picked is None:
            return
        k = picked.data()
        self.actions.append(TriggerAction(kind=k))
        self.rebuild(expand_last=(k not in ("noop", "if")))

    def _remove(self, a):
        self.actions.remove(a)
        self.rebuild()

    def _move(self, a, delta):
        i = self.actions.index(a)
        j = i + delta
        if 0 <= j < len(self.actions):
            self.actions[i], self.actions[j] = self.actions[j], self.actions[i]
            self.rebuild()


class ActionCard(QFrame):
    """Eine einzelne Aktions-Karte (Kopfzeile + Inline-Formular; bei 'if' Wenn/Dann/Sonst).

    A single action card with a toggle button that expands an inline edit form.
    For 'if' actions the When/Then/Else blocks are shown directly.
    """
    def __init__(self, action, parent_list, ctx):
        super().__init__()
        self.a = action
        self.parent_list = parent_list
        self.ctx = ctx
        self.setFrameShape(QFrame.StyledPanel)
        self._apply_card_style(action.kind)
        lay = QVBoxLayout(self)
        lay.setSpacing(2)

        self._title_lbl = QLabel(f"<b>{action_kind_label(action.kind)}</b>")
        header = QHBoxLayout()
        header.addWidget(self._title_lbl, 1)
        up = QPushButton("↑"); up.setFixedWidth(26); up.clicked.connect(lambda: parent_list._move(action, -1))
        dn = QPushButton("↓"); dn.setFixedWidth(26); dn.clicked.connect(lambda: parent_list._move(action, 1))
        header.addWidget(up); header.addWidget(dn)
        if action.kind not in ("if", "noop"):
            self._toggle_btn = QPushButton("▼"); self._toggle_btn.setFixedWidth(24)
            self._toggle_btn.clicked.connect(self._toggle_form)
            header.addWidget(self._toggle_btn)
        else:
            self._toggle_btn = None
        rm = QPushButton("✕"); rm.setFixedWidth(28); rm.clicked.connect(lambda: parent_list._remove(action))
        apply_role(rm, "danger")
        header.addWidget(rm)
        lay.addLayout(header)

        if action.kind not in ("if", "noop"):
            params = action_params_summary(action)
            self._det = QLabel(params if params else "")
            self._det.setWordWrap(True)
            self._det.setStyleSheet("color: #6c7086; font-size: 10pt; padding: 0 2px 2px 6px;")
            lay.addWidget(self._det)

            self._form = ActionInlineForm(action, ctx)
            self._form.setVisible(False)
            self._form.changed.connect(self._on_form_changed)
            self._form.pick_requested.connect(self._on_pick)
            lay.addWidget(self._form)
        else:
            self._det = None
            self._form = None

        if action.kind == "if":
            lay.addWidget(QLabel(tr("action_editor.lbl_if")))
            lay.addWidget(ConditionListWidget(action, ctx=ctx))
            lay.addWidget(QLabel(tr("action_editor.lbl_then")))
            lay.addWidget(ActionListWidget(action.then_actions, ctx))
            lay.addWidget(QLabel(tr("action_editor.lbl_else")))
            lay.addWidget(ActionListWidget(action.else_actions, ctx))

    def _apply_card_style(self, kind: str):
        accent = ACTION_CATEGORY_COLOR.get(kind, "#45475a")
        self.setStyleSheet(
            "QFrame {"
            " border: 1px solid #3a3a5c;"
            f" border-left: 3px solid {accent};"
            " border-radius: 4px;"
            " background-color: #252535;"
            "}"
        )

    def _on_form_changed(self):
        if self._det is not None:
            self._det.setText(action_params_summary(self.a))
        self._title_lbl.setText(f"<b>{action_kind_label(self.a.kind)}</b>")
        self._apply_card_style(self.a.kind)

    def _on_pick(self, field: str):
        cb = self.ctx.get("on_map_pick") if isinstance(self.ctx, dict) else None
        if callable(cb):
            cb(self.a, field)

    def _toggle_form(self):
        if self._form is None:
            return
        if self._form.isVisible():
            self.collapse()
        else:
            self.parent_list._collapse_all()
            self.expand()

    def expand(self):
        if self._form is not None:
            self._form.setVisible(True)
            if self._toggle_btn is not None:
                self._toggle_btn.setText("▲")

    def collapse(self):
        if self._form is not None:
            self._form.setVisible(False)
            if self._toggle_btn is not None:
                self._toggle_btn.setText("▼")
