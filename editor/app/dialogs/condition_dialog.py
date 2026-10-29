"""Dialog fuer eine einzelne Bedingung einer if-Aktion.

Aus `action_editor.py` herausgeloest; `action_editor` reicht die oeffentlichen
Klassen weiter.

Dialog for a single condition of an if action.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox

from ..common import *
from ..summary import action_kind_label, action_params_summary
from ..style import (ACTION_CATEGORY_COLOR, ACTION_SECTION_COLOR, CONDITION_SECTION_COLOR,
                     IF_LOOP_COLOR, SURFACE1, apply_role, tint_button_stylesheet, tint_stylesheet)


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
        # Einheits-/Frachttyp fuer Schleifen-Einheit-Bedingungen
        # Unit/cargo type for loop-unit conditions
        self.unit = QComboBox()
        for d, m in ALL_UNITS:
            self.unit.addItem(d, m)
        for d, m in WEAPONS:
            if m != "mapNone":
                self.unit.addItem(tr("action_editor.label_weapon_suffix", d=d), m)
        self.negate = QCheckBox(tr("action_editor.chk_negate"))
        # Befehlszustand fuer "Schleifen-Einheit: Befehl ist"
        # Command state for "loop unit: command is"
        self.command_type = QComboBox()
        for label, value in UNIT_COMMAND_STATES.items():
            self.command_type.addItem(label, value)
        # Schleifenebene fuer alle "Schleifen-Einheit: ..."-Bedingungen (bei
        # verschachtelten forEach-Schleifen: aktuelle oder aeussere Ebene).
        # Loop level for all "loop unit: ..." conditions (nested forEach
        # loops: current or outer level).
        self.loop_level = QComboBox()
        self.loop_level.addItem(tr("action_editor.loop_level_current"), "current")
        self.loop_level.addItem(tr("action_editor.loop_level_outer"), "outer")
        self.form = QFormLayout()
        # Label ueber dem Widget: macht die Formularspalte deutlich schmaler.
        # Label above the widget: makes the form column much narrower.
        self.form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.form.addRow(tr("action_editor.lbl_type"), self.kind)
        self._rows = {"player": self.player, "building": self.building, "x": self.x, "y": self.y,
                      "compare": self.compare, "value": self.value, "resource": self.resource,
                      "tech_id": self.tech_id, "var_name": self.var_name, "unit": self.unit,
                      "command": self.command_type, "loop_level": self.loop_level}
        labels = {"player": tr("action_editor.lbl_player"), "building": tr("action_editor.lbl_building"),
                  "x": tr("action_editor.lbl_x"), "y": tr("action_editor.lbl_y"),
                  "compare": tr("action_editor.lbl_compare"), "value": tr("action_editor.lbl_value"),
                  "resource": tr("action_editor.lbl_resource"), "tech_id": tr("action_editor.lbl_tech_id"),
                  "var_name": tr("action_editor.lbl_var_name"),
                  "unit": tr("action_editor.lbl_unit"),
                  "command": "Befehl:",
                  "loop_level": "Schleifenebene:"}
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
        ui = self.unit.findData(c.building_type)
        if ui >= 0:
            self.unit.setCurrentIndex(ui)
        self.compare.setCurrentText({v: k for k, v in COMPARE.items()}.get(c.compare, "≥"))
        self.value.setValue(c.value)
        self.resource.setCurrentText({v: k for k, v in RESOURCES.items()}.get(c.resource, "Common Ore"))
        self.tech_id.setValue(c.tech_id)
        self.negate.setChecked(c.negate)
        vn = getattr(c, 'var_name', '') or ''
        i = self.var_name.findData(vn)
        if i >= 0:
            self.var_name.setCurrentIndex(i)
        ci = self.command_type.findData(getattr(c, 'command_type', 'Move') or 'Move')
        if ci >= 0:
            self.command_type.setCurrentIndex(ci)
        li = self.loop_level.findData(getattr(c, 'loop_level', 'current') or 'current')
        if li >= 0:
            self.loop_level.setCurrentIndex(li)

    def result(self):
        kind, fields = ACTION_CONDITION_KINDS[self.kind.currentData()]
        # Schleifen-Einheit-Bedingungen speichern den Typ im building_type-Feld
        # Loop-unit conditions store the type in the building_type field
        btype = (self.unit.currentData() if "unit" in fields
                 else self.building.currentData())
        return ActionCondition(
            kind=kind,
            negate=self.negate.isChecked(), player=self.player.value(),
            building_type=btype, x=self.x.value(), y=self.y.value(),
            compare=COMPARE[self.compare.currentText()], value=self.value.value(),
            resource=RESOURCES[self.resource.currentText()], tech_id=self.tech_id.value(),
            var_name=self.var_name.currentData() or "",
            command_type=self.command_type.currentData() or "Move",
            loop_level=self.loop_level.currentData() or "current")
