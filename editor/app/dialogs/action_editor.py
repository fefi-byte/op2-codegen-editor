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


class ActionEditDialog(QDialog):
    """Dialog zum Anlegen/Bearbeiten einer einzelnen Aktion (parametergesteuert).

    Dialog for creating/editing a single action; fields shown depend on the
    selected action kind (card-based nested action editor, Home-Assistant style).
    """
    def __init__(self, parent, ctx, action=None, fixed_kind=None):
        super().__init__(parent)
        self.setWindowTitle(tr("action_editor.dlg_action_title"))
        self.ctx = ctx
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
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.target = QComboBox()
        for t in ctx["triggers"]:
            self.target.addItem(t.name, t.name)
        self.group = QComboBox()
        for g in ctx["building_groups"]:
            self.group.addItem(f"{g.name} [BuildingGroup]", g.name)
        self.building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.building.addItem(d, m)
        self.wall = QComboBox()
        for d, m, _ in WALL_ITEMS:
            if m != "mapTube":
                self.wall.addItem(d, m)
        self.target_group = QComboBox()
        for g in ctx["target_groups"]:
            self.target_group.addItem(f"{g.name} [{ctx['target_group_types'].get(g.name, 'BuildingGroup')}]", g.name)
        self.target_group.currentIndexChanged.connect(self._update_vehicles)
        self.source_group = QComboBox()
        for g in ctx["reinforce_groups"]:
            self.source_group.addItem(f"{g.name} [ReinforceGroup]", g.name)
        self.vehicle = QComboBox()
        self.priority = QSpinBox(); self.priority.setRange(1, 65535); self.priority.setValue(1000)
        diff_values = ctx.get("diff_values")
        self.target_count = ExprEdit(diff_values=diff_values)
        self.target_count.setValue(1)
        self.assign_group = QComboBox()
        for name, gtype in ctx["all_groups"]:
            self.assign_group.addItem(f"{name} [{gtype}]", name)
        # modVar: Variable aendern
        self.var_name = QComboBox()
        for v in ctx.get("variables", []):
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
            "text": self.text, "unit": self.unit, "weapon": self.weapon, "x": self.x, "y": self.y,
            "x2": self.x2, "y2": self.y2, "player": self.player, "target": self.target,
            "group": self.group, "building": self.building, "wall": self.wall,
            "target_group": self.target_group,
            "source_group": self.source_group, "vehicle": self.vehicle, "priority": self.priority,
            "target_count": self.target_count, "assign_group": self.assign_group,
            "var_name": self.var_name, "mod_mode": self.mod_mode, "var_expr": self.var_expr,
        }
        labels = {"text": tr("action_editor.lbl_text"), "unit": tr("action_editor.lbl_unit"),
                  "weapon": tr("action_editor.lbl_weapon_cargo"), "x": tr("action_editor.lbl_x"),
                  "y": tr("action_editor.lbl_y"), "x2": tr("action_editor.lbl_x2"),
                  "y2": tr("action_editor.lbl_y2"), "player": tr("action_editor.lbl_player"),
                  "target": tr("action_editor.lbl_target_trigger"), "group": "BuildingGroup:",
                  "building": tr("action_editor.lbl_building"), "wall": "Wall:",
                  "target_group": tr("action_editor.lbl_target_group"), "source_group": "ReinforceGroup:",
                  "vehicle": tr("action_editor.lbl_vehicle"), "priority": tr("action_editor.lbl_priority"),
                  "target_count": tr("action_editor.lbl_target_count"),
                  "assign_group": tr("action_editor.lbl_target_group"),
                  "var_name": tr("action_editor.lbl_var_name"),
                  "mod_mode": tr("action_editor.lbl_mod_mode"),
                  "var_expr": tr("action_editor.lbl_var_expr")}
        for k, w in self._rows.items():
            self.form.addRow(labels[k], w)
        # "Auf Karte setzen"-Knoepfe: einmal pro Koordinaten-Gruppe.
        # Klick speichert den Dialog mit `self.pick_field` und schliesst ihn;
        # die ActionCard reicht das ueber ctx['on_map_pick'] hoch, der
        # TriggersDialog laesst den Editor die Map-Auswahl durchfuehren und
        # oeffnet den Trigger-Dialog danach wieder.
        self.pick_field: str | None = None
        self.pick_xy_btn = QPushButton("📍 X / Y auf Karte setzen")
        self.pick_xy_btn.clicked.connect(lambda: self._request_pick("primary"))
        self.pick_xy2_btn = QPushButton("📍 X2 / Y2 auf Karte setzen")
        self.pick_xy2_btn.clicked.connect(lambda: self._request_pick("secondary"))
        self.form.addRow("", self.pick_xy_btn)
        self.form.addRow("", self.pick_xy2_btn)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(self.form); lay.addWidget(btns)

        if action is not None:
            self._load(action)
        elif fixed_kind is not None:
            self._set_kind(fixed_kind)
        self._update()

    # --- Sichtbarkeit pro Aktionstyp ---
    # --- Field visibility per action kind ---
    _VIS = {
        "message": ["text"],
        "createUnit": ["unit", "weapon", "x", "y", "player"],
        "createTrigger": ["target"],
        "recordBuilding": ["group", "building", "x", "y"],
        "recordTube": ["group", "x", "y", "x2", "y2"],
        "recordWall": ["group", "wall", "x", "y", "x2", "y2"],
        "setTargCount": ["target_group", "source_group", "vehicle", "priority", "target_count"],
        "assignToGroup": ["assign_group", "building", "x", "y", "player"],
        "modVar": ["var_name", "mod_mode", "var_expr"],
    }

    def _current_kind(self):
        return self.kind.currentData()

    def _set_kind(self, k):
        i = self.kind.findData(k)
        if i >= 0:
            self.kind.setCurrentIndex(i)

    # Pro Aktionstyp die kontextuellen Labels.
    # Per action kind: contextual labels for the coordinate fields.
    _LABEL_OVERRIDES = {
        "recordTube": {
            "x": "Start X:", "y": "Start Y:", "x2": "Ende X:", "y2": "Ende Y:",
        },
        "recordWall": {
            "x": "Start X:", "y": "Start Y:", "x2": "Ende X:", "y2": "Ende Y:",
        },
    }

    def _apply_labels(self, kind):
        """Setzt die Form-Labels passend zur Aktion."""
        overrides = self._LABEL_OVERRIDES.get(kind, {})
        defaults = {
            "x": tr("action_editor.lbl_x"), "y": tr("action_editor.lbl_y"),
            "x2": tr("action_editor.lbl_x2"), "y2": tr("action_editor.lbl_y2"),
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
        else:
            self.pick_xy_btn.setText("📍 X / Y auf Karte setzen")
            self.pick_xy2_btn.setText("📍 X2 / Y2 auf Karte setzen")

    def _update(self):
        kind = self._current_kind()
        fields = self._VIS.get(kind, [])
        for k, w in self._rows.items():
            self.form.setRowVisible(w, k in fields)
        # var_expr nur sichtbar wenn modVar + Modus "Ausdruck"
        if kind == "modVar":
            self.form.setRowVisible(self.var_expr, self.mod_mode.currentData() == "expr")
        self._apply_labels(kind)
        # Pick-Knoepfe nur anbieten wenn die Aktion die Felder ueberhaupt nutzt.
        self.form.setRowVisible(self.pick_xy_btn,  ("x" in fields) and ("y" in fields))
        self.form.setRowVisible(self.pick_xy2_btn, ("x2" in fields) and ("y2" in fields))
        self._update_vehicles()

    def _request_pick(self, field: str):
        """Markiert das gewuenschte Pick-Feld und schliesst den Dialog mit Accept."""
        self.pick_field = field
        self.accept()

    def _update_vehicles(self):
        gname = self.target_group.currentData()
        gtype = self.ctx["target_group_types"].get(gname, "BuildingGroup")
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

    def _set_combo(self, combo, value):
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _load(self, a):
        self._set_kind(a.kind)
        self.text.setText(a.text)
        self._set_combo(self.unit, a.unit_type)
        self._set_combo(self.weapon, a.weapon_type)
        self.x.setValue(a.x); self.y.setValue(a.y); self.x2.setValue(a.x2); self.y2.setValue(a.y2)
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
        # modVar
        vn = getattr(a, 'var_name', '') or ''
        i = self.var_name.findData(vn)
        if i >= 0: self.var_name.setCurrentIndex(i)
        mm = getattr(a, 'mod_mode', 'inc') or 'inc'
        j = self.mod_mode.findData(mm)
        if j >= 0: self.mod_mode.setCurrentIndex(j)
        self.var_expr.setValue(getattr(a, 'var_expr', '') or '')

    def result(self):
        k = self._current_kind()
        if k == "message":
            return TriggerAction(kind="message", text=self.text.text())
        if k == "createUnit":
            return TriggerAction(kind="createUnit", unit_type=self.unit.currentData(),
                                 weapon_type=self.weapon.currentData(),
                                 x=self.x.value(), y=self.y.value(), player=self.player.value())
        if k == "createTrigger":
            return TriggerAction(kind="createTrigger", target=self.target.currentData() or "")
        if k == "recordBuilding":
            return TriggerAction(kind="recordBuilding", group_name=self.group.currentData(),
                                 building_type=self.building.currentData(),
                                 x=self.x.value(), y=self.y.value())
        if k == "recordTube":
            return TriggerAction(kind="recordTube", group_name=self.group.currentData(),
                                 x=self.x.value(), y=self.y.value(), x2=self.x2.value(), y2=self.y2.value())
        if k == "recordWall":
            return TriggerAction(kind="recordWall", group_name=self.group.currentData(),
                                 wall_type=self.wall.currentData(),
                                 x=self.x.value(), y=self.y.value(), x2=self.x2.value(), y2=self.y2.value())
        if k == "setTargCount":
            return TriggerAction(kind="setTargCount", group_name=self.target_group.currentData(),
                                 source_group_name=self.source_group.currentData(),
                                 unit_type=self.vehicle.currentData(), weapon_type="mapNone",
                                 reinforce_priority=self.priority.value(), target_count=self.target_count.value())
        if k == "assignToGroup":
            return TriggerAction(kind="assignToGroup", group_name=self.assign_group.currentData(),
                                 building_type=self.building.currentData(),
                                 x=self.x.value(), y=self.y.value(), player=self.player.value())
        if k == "modVar":
            return TriggerAction(kind="modVar",
                                 var_name=self.var_name.currentData() or "",
                                 mod_mode=self.mod_mode.currentData() or "inc",
                                 var_expr=self.var_expr.text())
        return TriggerAction(kind="noop")


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

    def rebuild(self):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for a in list(self.actions):
            self.box.addWidget(ActionCard(a, self, self.ctx))
        add = QPushButton(tr("action_editor.btn_add_action")); add.clicked.connect(self._add)
        self.box.addWidget(add)

    def _add(self):
        menu = QMenu(self)
        for label, k in ACTION_KINDS.items():
            menu.addAction(tr(f"action_kinds.{k}")).setData(k)
        picked = menu.exec(QCursor.pos())
        if picked is None:
            return
        k = picked.data()
        if k == "noop":
            self.actions.append(TriggerAction(kind="noop"))
            self.rebuild()
        elif k == "if":
            self.actions.append(TriggerAction(kind="if"))
            self.rebuild()
        else:
            dlg = ActionEditDialog(self, self.ctx, fixed_kind=k)
            if dlg.exec() == QDialog.Accepted:
                new_action = dlg.result()
                self.actions.append(new_action)
                self.rebuild()
                cb = self.ctx.get("on_map_pick") if isinstance(self.ctx, dict) else None
                if dlg.pick_field and callable(cb):
                    cb(new_action, dlg.pick_field)

    def _remove(self, a):
        self.actions.remove(a)
        self.rebuild()

    def _replace(self, a, new):
        self.actions[self.actions.index(a)] = new
        self.rebuild()

    def _move(self, a, delta):
        i = self.actions.index(a)
        j = i + delta
        if 0 <= j < len(self.actions):
            self.actions[i], self.actions[j] = self.actions[j], self.actions[i]
            self.rebuild()


class ActionCard(QFrame):
    """Eine einzelne Aktions-Karte (Kopfzeile + Buttons; bei 'if' Wenn/Dann/Sonst).

    A single action card (header plus buttons; for an 'if' action it shows the
    nested When/Then/Else blocks).
    """
    def __init__(self, action, parent_list, ctx):
        super().__init__()
        self.a = action
        self.parent_list = parent_list
        self.ctx = ctx
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("QFrame { border: 1px solid #555; border-radius: 6px; }")
        lay = QVBoxLayout(self)

        header = QHBoxLayout()
        title = tr("action_editor.card_if_title") if action.kind == "if" else action_summary(action)
        header.addWidget(QLabel(f"<b>{title}</b>"), 1)
        up = QPushButton("↑"); up.setFixedWidth(26); up.clicked.connect(lambda: parent_list._move(action, -1))
        dn = QPushButton("↓"); dn.setFixedWidth(26); dn.clicked.connect(lambda: parent_list._move(action, 1))
        header.addWidget(up); header.addWidget(dn)
        if action.kind != "if":
            edit = QPushButton(tr("action_editor.btn_edit")); edit.clicked.connect(self._edit)
            header.addWidget(edit)
        rm = QPushButton("✕"); rm.setFixedWidth(28); rm.clicked.connect(lambda: parent_list._remove(action))
        header.addWidget(rm)
        lay.addLayout(header)

        if action.kind == "if":
            lay.addWidget(QLabel(tr("action_editor.lbl_if")))
            lay.addWidget(ConditionListWidget(action, ctx=ctx))
            lay.addWidget(QLabel(tr("action_editor.lbl_then")))
            lay.addWidget(ActionListWidget(action.then_actions, ctx))
            lay.addWidget(QLabel(tr("action_editor.lbl_else")))
            lay.addWidget(ActionListWidget(action.else_actions, ctx))

    def _edit(self):
        dlg = ActionEditDialog(self, self.ctx, action=self.a)
        if dlg.exec() == QDialog.Accepted:
            new_action = dlg.result()
            self.parent_list._replace(self.a, new_action)
            # Map-Pick angefordert? Den Roundtrip uebergeben wir an ctx['on_map_pick'].
            cb = self.ctx.get("on_map_pick") if isinstance(self.ctx, dict) else None
            if dlg.pick_field and callable(cb):
                cb(new_action, dlg.pick_field)
