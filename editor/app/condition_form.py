"""Wiederverwendbares Formular fuer EINE Sieg-/Niederlage-Bedingung.

Wird vom Sieg&Niederlage-Panel (conditions_panel) und vom Aktions-Editor
(addVictory/addDefeat-Aktionen) gemeinsam benutzt -- ein Formular, eine
Feldliste (CONDITIONS), ein Hilfetext pro Typ.

Reusable form for ONE victory/defeat condition. Shared by the victory&defeat
panel (conditions_panel) and the action editor (addVictory/addDefeat actions)
-- one form, one field list (CONDITIONS), one help text per kind.
"""
from __future__ import annotations

from .common import *


class ConditionFormWidget(QWidget):
    """Formular mit typabhaengigen Feldern + Hilfetext + Karten-Pick-Buttons.

    `changed` feuert bei jeder Nutzereingabe (nicht waehrend `load()`).
    `pick_requested` meldet "point" (Klick) oder "rect" (Drag) nach oben --
    das Einsammeln der Koordinaten macht der Aufrufer (Hauptfenster).

    Form with kind-dependent fields + help text + map-pick buttons. `changed`
    fires on every user edit (not during `load()`). `pick_requested` reports
    "point" (click) or "rect" (drag) upwards -- collecting the coordinates is
    the caller's (main window's) job.
    """
    changed = Signal()
    pick_requested = Signal(str)   # "point" | "rect"

    def __init__(self, parent=None, *, diff_values=None, show_pick_buttons=True):
        super().__init__(parent)
        self._loading = False
        self._objective_allowed = True

        self.kind = QComboBox()
        fill_combo(self.kind, CONDITIONS, "conditions")
        self.kind.currentIndexChanged.connect(self._on_kind_changed)
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.marks = ExprEdit(diff_values=diff_values)
        self.marks.setValue(600)
        self.marks.setPlaceholderText(tr("cond_form.marks_placeholder"))
        self.marks_hint = QLabel()
        self.marks_hint.setWordWrap(True)
        self.marks_hint.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self.count = QSpinBox(); self.count.setRange(0, 1000); self.count.setValue(1)
        self.compare = QComboBox(); self.compare.addItems(COMPARE.keys())
        self.tech_id = QSpinBox(); self.tech_id.setRange(0, 20000)
        self.resource = QComboBox(); self.resource.addItems(RESOURCES.keys())
        self.amount = QSpinBox(); self.amount.setRange(0, 1000000); self.amount.setValue(1000)
        self.building = QComboBox()
        for disp, mid, _ in STRUCTURES:
            self.building.addItem(disp, mid)
        self.unit_type = QComboBox()
        for disp, mid in VEHICLE_UNITS:
            self.unit_type.addItem(disp, mid)
        self.unit_type.currentIndexChanged.connect(self._update_cargo_options)
        self.cargo = QComboBox()
        self.x = QSpinBox(); self.x.setRange(0, 1023)
        self.y = QSpinBox(); self.y.setRange(0, 1023)
        self.width = QSpinBox(); self.width.setRange(1, 256); self.width.setValue(4)
        self.height = QSpinBox(); self.height.setRange(1, 256); self.height.setValue(4)
        self.trigger_group = QComboBox()
        self.damage_type = QComboBox()
        fill_combo(self.damage_type, DAMAGE_TYPES, "damage_types")
        self.target_unit = QComboBox()
        self.source_unit_type = QComboBox()
        for disp, mid, *_ in VEHICLES:
            self.source_unit_type.addItem(disp, mid)
        sidx = self.source_unit_type.findData("mapScout")
        if sidx >= 0:
            self.source_unit_type.setCurrentIndex(sidx)
        self.objective = QLineEdit()
        self.objective.setPlaceholderText(tr("cond_form.objective_placeholder"))

        # Punkt-8-Verhalten: Beschreibung leer lassen ist ok; Platzhalter
        # statt Vorbefuellung, damit kein Standardtext im Spiel landet.
        # Point-8 behaviour: leaving the description empty is fine;
        # placeholder instead of prefill so no default text ends up in-game.

        # Hilfetext je Typ / help text per kind
        self.help_lbl = QLabel()
        self.help_lbl.setWordWrap(True)
        self.help_lbl.setStyleSheet("color: #6c7086; font-size: 9pt;")

        # Karten-Pick-Buttons / map pick buttons
        self.pick_point_btn = QPushButton(tr("cond_form.btn_pick_point"))
        self.pick_point_btn.clicked.connect(lambda: self.pick_requested.emit("point"))
        self.pick_rect_btn = QPushButton(tr("cond_form.btn_pick_rect"))
        self.pick_rect_btn.clicked.connect(lambda: self.pick_requested.emit("rect"))
        self._show_pick_buttons = show_pick_buttons

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.addRow(tr("cond_form.lbl_type"), self.kind)
        self.form.addRow("", self.help_lbl)
        self._rows = {
            "player": self.player, "marks": self.marks, "count": self.count,
            "compare": self.compare, "tech_id": self.tech_id, "resource": self.resource,
            "amount": self.amount, "building": self.building,
            "unit_type": self.unit_type, "cargo": self.cargo,
            "x": self.x, "y": self.y, "width": self.width, "height": self.height,
            "trigger_group": self.trigger_group, "damage_type": self.damage_type,
            "target_unit": self.target_unit, "source_unit_type": self.source_unit_type,
            "objective": self.objective,
        }
        labels = {
            "player": tr("cond_form.lbl_player"), "marks": tr("cond_form.lbl_marks"),
            "count": tr("cond_form.lbl_count"), "compare": tr("cond_form.lbl_compare"),
            "tech_id": tr("cond_form.lbl_tech_id"), "resource": tr("cond_form.lbl_resource"),
            "amount": tr("cond_form.lbl_amount"), "building": tr("cond_form.lbl_building"),
            "unit_type": tr("cond_form.lbl_unit_type"), "cargo": tr("cond_form.lbl_cargo"),
            "x": tr("cond_form.lbl_x"), "y": tr("cond_form.lbl_y"),
            "width": tr("cond_form.lbl_width"), "height": tr("cond_form.lbl_height"),
            "trigger_group": tr("cond_form.lbl_group"),
            "damage_type": tr("cond_form.lbl_damage_type"),
            "target_unit": tr("cond_form.lbl_target_unit"),
            "source_unit_type": tr("cond_form.lbl_source_unit_type"),
            "objective": tr("cond_form.lbl_objective"),
        }
        for key, w in self._rows.items():
            self.form.addRow(labels[key], w)
            if key == "marks":
                self.form.addRow("", self.marks_hint)
        self.form.addRow("", self.pick_point_btn)
        self.form.addRow("", self.pick_rect_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.form)

        # Aenderungssignale -> changed / change signals -> changed
        for w in (self.kind, self.compare, self.resource, self.building,
                  self.unit_type, self.cargo, self.trigger_group,
                  self.damage_type, self.target_unit, self.source_unit_type):
            w.currentIndexChanged.connect(self._emit_changed)
        for w in (self.player, self.count, self.tech_id, self.amount,
                  self.x, self.y, self.width, self.height):
            w.valueChanged.connect(self._emit_changed)
        self.marks.valueChanged.connect(self._on_marks_changed)
        self.objective.textChanged.connect(self._emit_changed)

        self._update_cargo_options()
        self._update_fields()

    # --- Kontext (Gruppen / benannte Einheiten) ---

    def set_context(self, group_names=(), named_units=()):
        """Combos fuer Gruppen und benannte Einheiten (neu) befuellen.

        Repopulate the group / named-unit combos.
        """
        self._loading = True
        cur_g = self.trigger_group.currentData()
        self.trigger_group.clear()
        for name in group_names:
            self.trigger_group.addItem(name, name)
        gi = self.trigger_group.findData(cur_g)
        if gi >= 0:
            self.trigger_group.setCurrentIndex(gi)
        cur_u = self.target_unit.currentData()
        self.target_unit.clear()
        for uname, mid in named_units:
            self.target_unit.addItem(f"{uname} ({mid.replace('map', '')})", uname)
        ui = self.target_unit.findData(cur_u)
        if ui >= 0:
            self.target_unit.setCurrentIndex(ui)
        self._loading = False

    # --- Laden / Speichern ---

    def load(self, cond: Condition):
        self._loading = True
        internal = cond.kind
        for i in range(self.kind.count()):
            if CONDITIONS[self.kind.itemData(i)][0] == internal:
                self.kind.setCurrentIndex(i)
                break
        self.player.setValue(int(cond.player or 0))
        self.marks.setValue(cond.marks if cond.marks is not None else 600)
        self.count.setValue(int(cond.count or 0))
        self.compare.setCurrentText({v: k for k, v in COMPARE.items()}.get(cond.compare, "≥"))
        self.tech_id.setValue(int(cond.tech_id or 0))
        self.resource.setCurrentText(
            {v: k for k, v in RESOURCES.items()}.get(cond.resource, "Common Ore"))
        self.amount.setValue(int(cond.amount or 0))
        bi = self.building.findData(cond.building)
        if bi >= 0:
            self.building.setCurrentIndex(bi)
        ui = self.unit_type.findData(getattr(cond, "unit_type", "mapCargoTruck") or "mapCargoTruck")
        if ui >= 0:
            self.unit_type.setCurrentIndex(ui)
        self._update_cargo_options()
        ci = self.cargo.findData(getattr(cond, "cargo", "mapAny") or "mapAny")
        if ci >= 0:
            self.cargo.setCurrentIndex(ci)
        self.x.setValue(int(getattr(cond, "x", 0) or 0))
        self.y.setValue(int(getattr(cond, "y", 0) or 0))
        self.width.setValue(max(1, int(getattr(cond, "width", 1) or 1)))
        self.height.setValue(max(1, int(getattr(cond, "height", 1) or 1)))
        gi = self.trigger_group.findData(getattr(cond, "group_name", "") or "")
        if gi >= 0:
            self.trigger_group.setCurrentIndex(gi)
        di = self.damage_type.findData(
            {v: k for k, v in DAMAGE_TYPES.items()}.get(int(getattr(cond, "damage_type", 3) or 3)))
        if di >= 0:
            self.damage_type.setCurrentIndex(di)
        ti = self.target_unit.findData(getattr(cond, "target_unit", "") or "")
        if ti >= 0:
            self.target_unit.setCurrentIndex(ti)
        si = self.source_unit_type.findData(
            getattr(cond, "source_unit_type", "mapScout") or "mapScout")
        if si >= 0:
            self.source_unit_type.setCurrentIndex(si)
        self.objective.setText(cond.objective or "")
        self._loading = False
        self._update_fields()

    def current_kind(self) -> str:
        return CONDITIONS[self.kind.currentData()][0]

    def apply_to(self, cond: Condition):
        """Formularwerte IN das bestehende Condition-Objekt schreiben.

        Write the form values INTO the existing Condition object (in place,
        so map-pick references to the object stay valid).
        """
        cond.kind = self.current_kind()
        cond.objective = self.objective.text().strip()
        cond.player = self.player.value()
        cond.marks = self.marks.value()
        cond.count = self.count.value()
        cond.compare = COMPARE[self.compare.currentText()]
        cond.tech_id = self.tech_id.value()
        cond.resource = RESOURCES[self.resource.currentText()]
        cond.amount = self.amount.value()
        cond.building = self.building.currentData()
        cond.unit_type = self.unit_type.currentData() or "mapCargoTruck"
        cond.cargo = self.cargo.currentData() or "mapAny"
        cond.x = self.x.value()
        cond.y = self.y.value()
        cond.width = self.width.value()
        cond.height = self.height.value()
        cond.group_name = self.trigger_group.currentData() or ""
        cond.damage_type = DAMAGE_TYPES.get(self.damage_type.currentData(), 3)
        cond.target_unit = self.target_unit.currentData() or ""
        cond.source_unit_type = self.source_unit_type.currentData() or "mapScout"

    def make(self) -> Condition:
        cond = Condition(kind=self.current_kind())
        self.apply_to(cond)
        return cond

    # --- Sichtbarkeit / visibility ---

    def set_objective_visible(self, on: bool):
        """Beschreibung ein-/ausblenden (Niederlagen brauchen keine --
        die Engine ignoriert den Text dort).

        Show/hide the description (defeats don't need one -- the engine
        ignores the text there)."""
        self._objective_allowed = bool(on)
        self._update_fields()

    def _fields_for_current(self):
        return CONDITIONS[self.kind.currentData()][1]

    def _update_fields(self):
        fields = self._fields_for_current()
        for key, w in self._rows.items():
            visible = key in fields
            if key == "objective":
                visible = visible and self._objective_allowed
            self.form.setRowVisible(w, visible)
        kind = self.current_kind()
        # Hilfetext / help text
        self.help_lbl.setText(tr(f"cond_help.{kind}"))
        # Marks-Umrechnung / marks conversion hint
        self._update_marks_hint()
        self.form.setRowVisible(self.marks_hint, "marks" in fields)
        # Pick-Buttons: Punkt bei point, Bereich bei rect/escape
        # pick buttons: point for point, area for rect/escape
        show_point = self._show_pick_buttons and kind == "point"
        show_rect = self._show_pick_buttons and kind in ("rect", "escape")
        self.form.setRowVisible(self.pick_point_btn, show_point)
        self.form.setRowVisible(self.pick_rect_btn, show_rect)

    def _update_cargo_options(self):
        self.cargo.clear()
        for label, value in condition_cargo_items(self.unit_type.currentData()):
            self.cargo.addItem(label, value)
        self.cargo.setEnabled(self.cargo.count() > 1)

    def _update_marks_hint(self):
        # 1 Mark = 100 Ticks, 4 Ticks/s -> 1 Mark = 25 s Echtzeit.
        # 1 mark = 100 ticks at 4 ticks/s -> 1 mark = 25 s real time.
        v = self.marks.value()
        if isinstance(v, int) and v > 0:
            total_s = v * 25
            h, rest = divmod(total_s, 3600)
            m, s = divmod(rest, 60)
            txt = f"{h}h {m:02d}min" if h else (f"{m}min {s:02d}s" if m else f"{s}s")
            self.marks_hint.setText(tr("cond_form.marks_hint", time=txt))
        else:
            self.marks_hint.setText("")

    # --- interne Signale / internal signals ---

    def _on_kind_changed(self):
        self._update_fields()
        self._emit_changed()

    def _on_marks_changed(self):
        self._update_marks_hint()
        self._emit_changed()

    def _emit_changed(self):
        if not self._loading:
            self.changed.emit()
