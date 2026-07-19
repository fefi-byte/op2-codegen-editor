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

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox

from ..common import *
from ..summary import action_kind_label, action_params_summary
from ..style import (ACTION_CATEGORY_COLOR, ACTION_SECTION_COLOR, CONDITION_SECTION_COLOR,
                     IF_LOOP_COLOR, SURFACE1, apply_role, tint_button_stylesheet, tint_stylesheet)


class _NoWheelFilter(QObject):
    """Blockiert Mausrad-Events auf nicht fokussierten Eingabefeldern.

    Blocks wheel events on unfocused input widgets so scrolling the panel
    does not accidentally change values."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            return True
        return super().eventFilter(obj, ev)

# Aktionstypen, die per Dialog (mit Parametern) angelegt werden:
# Action kinds that are created via a dialog (with parameters):
_DIALOG_KINDS = {label: k for label, k in ACTION_KINDS.items() if k not in ("if", "noop")}

# Gruppen-Befehle je Gruppentyp (MiningGroups sind jetzt vordefinierte
# Gruppen wie die anderen, bekommen aber bewusst keine Befehle hier -- kein
# Angriff-/Bewachen-/Patrouille-Verhalten zum Steuern).
# Group commands per group type (MiningGroups are now predefined groups like
# the others, but deliberately have no commands here -- no attack/guard/
# patrol behavior to control).
# Group commands: list of (internal_value, i18n_key). Display label comes
# from tr("action_editor.<key>") at usage time (see _fill_group_commands).
_GROUP_COMMANDS = {
    "FightGroup": [
        ("attackArea", "gc_attack_area"),
        ("attackEnemy", "gc_attack_enemy"),
        ("guardArea", "gc_guard_area"),
        ("patrol", "gc_patrol"),
        ("exitMap", "gc_exit_map"),
        ("combineFireOn", "gc_combine_fire_on"),
        ("combineFireOff", "gc_combine_fire_off"),
        ("setIdleRect", "gc_set_idle_rect"),
        ("addUnit", "gc_add_unit"),
        ("removeUnit", "gc_remove_unit"),
    ],
    "BuildingGroup": [
        ("setBuildRect", "gc_set_build_rect"),
        ("reinforceGroup", "gc_reinforce_group"),
        ("unReinforceGroup", "gc_un_reinforce_group"),
        ("addUnit", "gc_add_unit"),
        ("removeUnit", "gc_remove_unit"),
    ],
}
_GROUP_COMMANDS["ReinforceGroup"] = _GROUP_COMMANDS["BuildingGroup"]
_GROUP_COMMANDS_COMMON = [
    ("lightsOn", "gc_lights_on"),
    ("lightsOff", "gc_lights_off"),
    ("clearTargCount", "gc_clear_targ_count"),
]
# Befehle, die eine Ziel-Einheit brauchen (benannte Einheit oder Schleifen-
# Einheit) statt eines Rechteck-Bereichs.
# Commands that need a target unit (named unit or loop unit) instead of a rect.
_GROUP_COMMANDS_UNIT_TARGET = {"addUnit", "removeUnit"}

# Unit commands per unit kind: list of (internal_value, i18n_key).
_UNIT_COMMANDS_VEHICLE = [
    ("move", "uc_move"),
    ("patrol", "uc_patrol"),
    ("repair", "uc_repair"),
    ("stop", "uc_stop"),
    ("lightsOn", "uc_lights_on"),
    ("lightsOff", "uc_lights_off"),
    ("selfDestruct", "uc_self_destruct"),
    ("remove", "uc_remove"),
    ("transfer", "uc_transfer"),
]
_UNIT_COMMANDS_BUILDING = [
    ("idle", "uc_idle"),
    ("unidle", "uc_unidle"),
    ("selfDestruct", "uc_self_destruct"),
    ("remove", "uc_remove"),
    ("transfer", "uc_transfer"),
]
_VEHICLE_IDS = {m for _, m, _ in VEHICLES}


def unit_commands_for(map_id: str) -> list[tuple[str, str]]:
    """Befehlsliste passend zur Einheitenart / command list matching the unit kind.

    Returns a list of (internal_value, i18n_key) tuples.
    """
    if map_id == "<loop>":
        # Typ der Schleifen-Einheit ist erst zur Laufzeit bekannt -> alles anbieten
        # The loop unit's type is only known at runtime -> offer everything
        cmds = list(_UNIT_COMMANDS_VEHICLE)
        cmds.insert(2, ("attackGround", "uc_attack_ground"))
        cmds += [c for c in _UNIT_COMMANDS_BUILDING if c not in cmds]
        return cmds
    if map_id in _VEHICLE_IDS:
        cmds = list(_UNIT_COMMANDS_VEHICLE)
        if map_id in WEAPON_UNITS:
            cmds.insert(2, ("attackGround", "uc_attack_ground"))
        return cmds
    return list(_UNIT_COMMANDS_BUILDING)


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


class ActionInlineForm(QWidget):
    """Inline-Formular zum Bearbeiten einer Aktion direkt in der ActionCard.

    Inline form for editing an action directly inside its ActionCard.
    Changes are written to the action object immediately on every widget change.
    """
    changed = Signal()
    pick_requested = Signal(str)  # "primary" or "secondary"

    _VIS = {
        "message": ["text"],
        "createUnit": ["unit_editor", "player"],
        "createDisaster": ["disaster_type", "x_expr", "y_expr"],
        "createTrigger": ["target"],
        "recordBuilding": ["group", "building_editor"],
        "recordTube": ["group", "tube_editor"],
        "recordWall": ["group", "wall_editor"],
        "setTargCount": ["target_group", "source_group", "priority", "targ_editor"],
        "assignToGroup": ["assign_group", "building", "x", "y", "player"],
        "modVar": ["var_name", "mod_mode", "var_expr"],
        "startMining": ["player", "mining_group", "mine_ref", "mine_pick", "x", "y",
                        "smelter_ref", "smelter_pick", "x2", "y2",
                        "target_count", "mining_wait_hint"],
        "sendAttackWave": ["player", "spawn_mode", "group_var_name", "wave_editor",
                           "idle_rect_w", "staging_rect_w", "attack_rect_w", "now"],
        "fightGroupCmd": ["wave_group", "fg_command"],
        "unitCmd": ["unit_ref", "unit_command"],
        "defendArea": ["player", "x", "y", "x2", "y2"],
        "repairBuildings": ["player", "x", "y", "x2", "y2"],
        "empMissile": ["player", "x", "y", "x2", "y2"],
        "setMorale": ["morale_mode", "morale_player"],
        "setMusic": ["songs_editor", "repeat_start"],
        "lavaFlowAni": ["flow_dir", "flow_freeze", "x", "y"],
        "modUnitStats": ["stats_unit", "player", "stats_editor"],
    }

    _LABEL_OVERRIDES = {
        "recordTube": {"x": "Start X:", "y": "Start Y:", "x2": "Ende X:", "y2": "Ende Y:"},
        "recordWall": {"x": "Start X:", "y": "Start Y:", "x2": "Ende X:", "y2": "Ende Y:"},
        "startMining": {"x": "Mine X:", "y": "Mine Y:", "x2": "Smelter X:", "y2": "Smelter Y:"},
        "defendArea": {"x": "Ecke 1 X:", "y": "Ecke 1 Y:", "x2": "Ecke 2 X:", "y2": "Ecke 2 Y:"},
        "repairBuildings": {"x": "Ecke 1 X:", "y": "Ecke 1 Y:", "x2": "Ecke 2 X:", "y2": "Ecke 2 Y:"},
        "empMissile": {"x": "Start X:", "y": "Start Y:", "x2": "Ziel X:", "y2": "Ziel Y:"},
    }

    def __init__(self, action, ctx):
        super().__init__()
        self._action = action
        self._loading = False
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
        self.x_expr.setPlaceholderText(tr("action_editor.ph_x_expr"))
        self.y_expr.setPlaceholderText(tr("action_editor.ph_y_expr"))
        self.x2_expr.setPlaceholderText(tr("action_editor.ph_x2_expr"))
        self.y2_expr.setPlaceholderText(tr("action_editor.ph_y2_expr"))
        self.disaster_type = QComboBox()
        for value in DISASTER_TYPES:
            self.disaster_type.addItem(tr(f"disaster_types.{value}"), value)
        self.disaster_type.currentIndexChanged.connect(self._update)
        self.size = QComboBox()
        for value in METEOR_SIZES:
            self.size.addItem(tr(f"meteor_sizes.{value}"), value)
        self.magnitude = ExprEdit(diff_values=diff_values)
        self.magnitude.setPlaceholderText(tr("action_editor.ph_magnitude"))
        self.duration = ExprEdit(diff_values=diff_values)
        self.duration.setPlaceholderText(tr("action_editor.ph_duration"))
        self.spread_speed = QSpinBox()
        self.spread_speed.setRange(1, 200)
        self.spread_speed.setValue(15)
        self.spread_speed.setToolTip("Ausbreitungsgeschwindigkeit der Lava (15 = sehr langsam, 45 = mittel)")
        self._lava_paint_active = False
        self.lava_zone_btn = QPushButton(tr("action_editor.btn_lava_zone"))
        self.lava_zone_btn.clicked.connect(lambda: self._request_pick("lava_zone"))
        self.lava_zone_lbl = QLabel(tr("action_editor.lava_tiles_count", n=0))
        self.lava_zone_lbl.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self.now = QCheckBox(tr("action_editor.chk_now_meteor"))
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.target = QComboBox()
        for t in (ctx.get("triggers") or [] if isinstance(ctx, dict) else []):
            self.target.addItem(t.name, t.name)
        self.group = QComboBox()
        for g in (ctx.get("building_groups") or [] if isinstance(ctx, dict) else []):
            self.group.addItem(f"{g.name} [BuildingGroup]", g.name)
        self.mining_group = QComboBox()
        for g in (ctx.get("mining_groups") or [] if isinstance(ctx, dict) else []):
            self.mining_group.addItem(f"{g.name} [MiningGroup]", g.name)
        # Mine/Smelter aus bereits platzierten Gebaeuden waehlen (Modus 1:
        # existieren schon) -- fuellt nur die X/Y-Spinboxen, die bleiben die
        # eigentliche gespeicherte Referenz (wichtig fuer Modus 2, wo Mine/
        # Smelter noch NICHT existieren und man die Position frei eintippt).
        # Pick mine/smelter from already-placed buildings (mode 1: they
        # already exist) -- only fills the X/Y spinboxes, which remain the
        # actual stored reference (important for mode 2, where mine/smelter
        # do NOT exist yet and the position is typed in freely).
        self.mine_pick = QComboBox()
        self.mine_pick.addItem(tr("action_editor.pick_placeholder"), None)
        for o in (ctx.get("mine_objects") or [] if isinstance(ctx, dict) else []):
            self.mine_pick.addItem(f"{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})",
                                    (o.tile_x, o.tile_y))
        self.mine_pick.currentIndexChanged.connect(self._pick_mine_from_list)
        self.smelter_pick = QComboBox()
        self.smelter_pick.addItem(tr("action_editor.pick_placeholder"), None)
        for o in (ctx.get("smelter_objects") or [] if isinstance(ctx, dict) else []):
            self.smelter_pick.addItem(f"{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})",
                                       (o.tile_x, o.tile_y))
        self.smelter_pick.currentIndexChanged.connect(self._pick_smelter_from_list)
        # Mine/Smelter stattdessen per Referenz ansprechen: Schleifeneinheit
        # (wenn die Aktion in einer for-Schleife steht -- dann ist vorher
        # nicht bekannt, WELCHES Gebaeude gemeint ist) oder eine benannte
        # Einheit. "-- Position (X/Y) --" = wie bisher per Koordinaten.
        # Reference mine/smelter instead: loop unit (when the action sits
        # inside a for loop -- then it isn't known in advance WHICH building
        # is meant) or a named unit. "-- Position (X/Y) --" = as before, via
        # coordinates.
        self.mine_ref = QComboBox()
        self.mine_ref.addItem(tr("action_editor.ref_use_position"), "")
        self.mine_ref.addItem(tr("action_editor.loop_ref_current"), "<loop>")
        self.mine_ref.addItem(tr("action_editor.loop_ref_outer"), "<loop:outer>")
        for uname, mid in (ctx.get("named_units") or [] if isinstance(ctx, dict) else []):
            self.mine_ref.addItem(f"{uname} ({mid.replace('map', '')})", uname)
        self.mine_ref.currentIndexChanged.connect(self._update)
        self.smelter_ref = QComboBox()
        self.smelter_ref.addItem(tr("action_editor.ref_use_position"), "")
        self.smelter_ref.addItem(tr("action_editor.loop_ref_current"), "<loop>")
        self.smelter_ref.addItem(tr("action_editor.loop_ref_outer"), "<loop:outer>")
        for uname, mid in (ctx.get("named_units") or [] if isinstance(ctx, dict) else []):
            self.smelter_ref.addItem(f"{uname} ({mid.replace('map', '')})", uname)
        self.smelter_ref.currentIndexChanged.connect(self._update)
        # Live-Hinweis fuer Modus 2 (warten bis gebaut): erklaert genau, wie
        # ein findUnit-Ausloeser fuer die aktuellen Mine-/Smelter-Positionen
        # aussehen muss -- aktualisiert sich mit den X/Y-Werten.
        # Live hint for mode 2 (wait until built): explains exactly what a
        # findUnit trigger condition for the current mine/smelter positions
        # must look like -- updates together with the X/Y values.
        self.mining_wait_hint = QLabel()
        self.mining_wait_hint.setWordWrap(True)
        self.mining_wait_hint.setStyleSheet("color: #6c7086; font-size: 9pt;")
        for w in (self.x, self.y, self.x2, self.y2):
            w.valueChanged.connect(self._update_mining_wait_hint)
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
        # --- setTargCount als Liste: mehrere Fahrzeugtypen in einer Aktion ---
        # Eigene Widgets statt Wiederverwendung von self.vehicle/target_count:
        # letztere sind bereits als eigenstaendige Formularzeile fuer andere
        # Aktionstypen (z.B. startMining) vergeben -- ein Widget kann nur in
        # EINEM Qt-Layout gleichzeitig stecken.
        # --- setTargCount as a list: several vehicle types in one action ---
        # Dedicated widgets instead of reusing self.vehicle/target_count:
        # those are already claimed as a standalone form row for other action
        # kinds (e.g. startMining) -- a widget can only live in ONE Qt layout.
        self.targ_unit = QComboBox()
        self.targ_weapon = QComboBox()
        for d, m in WEAPONS:
            self.targ_weapon.addItem(d, m)
        self.targ_count_edit = ExprEdit(diff_values=diff_values)
        self.targ_count_edit.setValue(1)
        self.targ_list = QTreeWidget()
        self.targ_list.setHeaderLabels([tr("action_editor.col_unit"), tr("action_editor.col_weapon"), tr("action_editor.col_count")])
        self.targ_list.setRootIsDecorated(False)
        self.targ_list.setMaximumHeight(110)
        targ_add_btn = QPushButton("+")
        targ_add_btn.setFixedWidth(28)
        targ_add_btn.clicked.connect(self._targ_add)
        targ_rm_btn = QPushButton("−")
        targ_rm_btn.setFixedWidth(28)
        targ_rm_btn.clicked.connect(self._targ_remove)
        targ_row = QHBoxLayout()
        targ_row.addWidget(self.targ_unit, 2)
        targ_row.addWidget(self.targ_weapon, 2)
        targ_row.addWidget(self.targ_count_edit, 1)
        targ_row.addWidget(targ_add_btn)
        targ_row.addWidget(targ_rm_btn)
        self.targ_editor = QWidget()
        te_lay = QVBoxLayout(self.targ_editor)
        te_lay.setContentsMargins(0, 0, 0, 0)
        te_lay.addWidget(self.targ_list)
        te_lay.addLayout(targ_row)
        self.assign_group = QComboBox()
        for name, gtype in (ctx.get("all_groups") or [] if isinstance(ctx, dict) else []):
            self.assign_group.addItem(f"{name} [{gtype}]", name)
        self.var_name = QComboBox()
        for v in (ctx.get("variables") or [] if isinstance(ctx, dict) else []):
            self.var_name.addItem(v.name, v.name)
        self.mod_mode = QComboBox()
        self.mod_mode.addItem(tr("action_editor.mod_mode_inc"), "inc")
        self.mod_mode.addItem(tr("action_editor.mod_mode_dec"), "dec")
        self.mod_mode.addItem(tr("action_editor.mod_mode_expr"), "expr")
        self.mod_mode.currentIndexChanged.connect(self._update)
        self.var_expr = ExprEdit(diff_values=diff_values)

        # --- Angriffswellen-Editor (sendAttackWave) ---
        # --- Attack-wave editor (sendAttackWave) ---
        self.spawn_mode = QComboBox()
        self.spawn_mode.addItem("Direkt spawnen", "spawn")
        self.spawn_mode.addItem("Per ReinforceGroup produzieren", "reinforce")
        self.spawn_mode.currentIndexChanged.connect(self._update)
        # FightGroups muessen vorher im Gruppen-Panel definiert werden --
        # Pflichtauswahl statt Freitext.
        # FightGroups must be predefined in the Groups panel -- mandatory
        # selection instead of free text.
        self.group_var_name = QComboBox()
        for name in (ctx.get("fight_groups") or [] if isinstance(ctx, dict) else []):
            self.group_var_name.addItem(name, name)

        def _mk_spin():
            # Ohne Auf/Ab-Pfeile: schmaler; Werte per Tastatur oder Mausrad bei Fokus.
            # Without up/down arrows: narrower; edit via keyboard or wheel when focused.
            s = QSpinBox(); s.setRange(0, 1023)
            s.setButtonSymbols(QAbstractSpinBox.NoButtons)
            s.setMinimumWidth(36)
            return s

        def _mk_rect_row(spins, pick_field, tooltip):
            # Eine Zeile: X Y X2 Y2 + 📍-Button (Rechteck per Drag auf der Karte)
            # One row: X Y X2 Y2 + 📍 button (drag a rect on the map)
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            for s in spins:
                lay.addWidget(s, 1)
            btn = QPushButton("📍")
            btn.setFixedWidth(28)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda: self._request_pick(pick_field))
            lay.addWidget(btn)
            row.setToolTip(tooltip)
            return row

        self.idle_x, self.idle_y = _mk_spin(), _mk_spin()
        self.idle_x2, self.idle_y2 = _mk_spin(), _mk_spin()
        self.idle_rect_w = _mk_rect_row(
            (self.idle_x, self.idle_y, self.idle_x2, self.idle_y2),
            "idle_rect", tr("action_editor.tooltip_pick_idle_rect"))
        self.stage_x, self.stage_y = _mk_spin(), _mk_spin()
        self.stage_x2, self.stage_y2 = _mk_spin(), _mk_spin()
        self.staging_rect_w = _mk_rect_row(
            (self.stage_x, self.stage_y, self.stage_x2, self.stage_y2),
            "staging_rect", tr("action_editor.tooltip_pick_staging_rect"))
        self.attack_x, self.attack_y = _mk_spin(), _mk_spin()
        self.attack_x2, self.attack_y2 = _mk_spin(), _mk_spin()
        self.attack_rect_w = _mk_rect_row(
            (self.attack_x, self.attack_y, self.attack_x2, self.attack_y2),
            "attack_rect", tr("action_editor.tooltip_pick_attack_rect"))

        # --- Gruppen-Befehl (fightGroupCmd) ---
        # --- Group command (fightGroupCmd) ---
        self._group_types = dict(ctx.get("all_command_groups") or [] if isinstance(ctx, dict) else [])
        self.wave_group = QComboBox()
        for name, gtype in (ctx.get("all_command_groups") or [] if isinstance(ctx, dict) else []):
            self.wave_group.addItem(f"{name} [{gtype}]", name)
        self.wave_group.currentIndexChanged.connect(self._update_group_commands)
        self.fg_command = QComboBox()
        self.fg_command.currentIndexChanged.connect(self._update)
        self._fill_group_commands()
        # Ziel-Wellengruppe fuer Verstaerkungs-Befehle
        # Target wave group for reinforcement commands
        self.cmd_target = QComboBox()
        for name in (ctx.get("wave_groups") or [] if isinstance(ctx, dict) else []):
            self.cmd_target.addItem(name, name)
        self.cmd_x, self.cmd_y = _mk_spin(), _mk_spin()
        self.cmd_x2, self.cmd_y2 = _mk_spin(), _mk_spin()
        self.cmd_rect_w = _mk_rect_row(
            (self.cmd_x, self.cmd_y, self.cmd_x2, self.cmd_y2),
            "area_rect", tr("action_editor.tooltip_pick_area_rect"))

        # --- Einheiten-Befehl (unitCmd) ---
        # --- Unit command (unitCmd) ---
        self._named_unit_types = dict(ctx.get("named_units") or [] if isinstance(ctx, dict) else [])
        self._named_unit_types["<loop>"] = "<loop>"
        self._named_unit_types["<loop:outer>"] = "<loop>"
        self.unit_ref = QComboBox()
        self.unit_ref.addItem(tr("action_editor.loop_ref_current"), "<loop>")
        self.unit_ref.addItem(tr("action_editor.loop_ref_outer"), "<loop:outer>")
        for name, mid in (ctx.get("named_units") or [] if isinstance(ctx, dict) else []):
            self.unit_ref.addItem(f"{name} ({mid.replace('map', '')})", name)
        self.unit_ref.currentIndexChanged.connect(self._update_unit_commands)
        self.unit_command = QComboBox()
        self.unit_command.currentIndexChanged.connect(self._update)
        self._fill_unit_commands()
        # Ziel-Einheit fuer den Reparieren-Befehl / target unit for repair
        self.cmd_unit_target = QComboBox()
        self.cmd_unit_target.addItem(tr("action_editor.loop_ref_current"), "<loop>")
        self.cmd_unit_target.addItem(tr("action_editor.loop_ref_outer"), "<loop:outer>")
        for name, mid in (ctx.get("named_units") or [] if isinstance(ctx, dict) else []):
            self.cmd_unit_target.addItem(f"{name} ({mid.replace('map', '')})", name)

        # --- Patrouillen-Wegpunkte (bis 8) / patrol waypoints (up to 8) ---
        self.patrol_editor = QWidget()
        pe_lay = QVBoxLayout(self.patrol_editor)
        pe_lay.setContentsMargins(0, 0, 0, 0)
        self.patrol_list = QTreeWidget()
        self.patrol_list.setHeaderLabels(["#", "X", "Y"])
        self.patrol_list.setRootIsDecorated(False)
        self.patrol_list.setMaximumHeight(110)
        pe_lay.addWidget(self.patrol_list)
        prow = QHBoxLayout()
        self.patrol_x = _mk_spin()
        self.patrol_y = _mk_spin()
        prow.addWidget(self.patrol_x, 1)
        prow.addWidget(self.patrol_y, 1)
        p_add = QPushButton("+"); p_add.setFixedWidth(28)
        p_add.clicked.connect(self._patrol_add)
        p_rm = QPushButton("−"); p_rm.setFixedWidth(28)
        p_rm.clicked.connect(self._patrol_remove)
        p_up = QPushButton("↑"); p_up.setFixedWidth(28)
        p_up.clicked.connect(lambda: self._patrol_move(-1))
        p_dn = QPushButton("↓"); p_dn.setFixedWidth(28)
        p_dn.clicked.connect(lambda: self._patrol_move(1))
        p_pick = QPushButton("📍"); p_pick.setFixedWidth(28)
        p_pick.setToolTip(tr("action_editor.tooltip_pick_patrol"))
        p_pick.clicked.connect(lambda: self._request_pick("patrol_point"))
        for b in (p_add, p_rm, p_up, p_dn, p_pick):
            prow.addWidget(b)
        pe_lay.addLayout(prow)

        self.wave_editor = QWidget()
        we_lay = QVBoxLayout(self.wave_editor)
        we_lay.setContentsMargins(0, 0, 0, 0)
        self.wave_list = QTreeWidget()
        self.wave_list.setHeaderLabels([tr("action_editor.col_unit"), tr("action_editor.col_weapon"), tr("action_editor.col_count")])
        self.wave_list.setRootIsDecorated(False)
        self.wave_list.setMaximumHeight(110)
        we_lay.addWidget(self.wave_list)
        add_row = QHBoxLayout()
        self.wave_unit = QComboBox()
        for d, m in MILITARY_VEHICLES:
            self.wave_unit.addItem(d, m)
        self.wave_weapon = QComboBox()
        for d, m in WEAPONS:
            if m != "mapNone":
                self.wave_weapon.addItem(d, m)
        self.wave_count = QSpinBox(); self.wave_count.setRange(1, 99); self.wave_count.setValue(2)
        wave_add_btn = QPushButton("+")
        wave_add_btn.setFixedWidth(28)
        wave_add_btn.clicked.connect(self._wave_add)
        wave_rm_btn = QPushButton("−")
        wave_rm_btn.setFixedWidth(28)
        wave_rm_btn.clicked.connect(self._wave_remove)
        add_row.addWidget(self.wave_unit, 2)
        add_row.addWidget(self.wave_weapon, 2)
        add_row.addWidget(self.wave_count, 1)
        add_row.addWidget(wave_add_btn)
        add_row.addWidget(wave_rm_btn)
        we_lay.addLayout(add_row)

        # --- createUnit-Liste: mehrere Einheiten in einer Aktion erzeugen ---
        # createUnit list: create several units in one action.
        # Eigene Widgets statt self.unit/self.weapon/self.x/self.y -- die sind
        # bereits als Formularzeile fuer andere Aktionstypen vergeben.
        self.cu_unit = QComboBox()
        for d, m in ALL_UNITS:
            self.cu_unit.addItem(d, m)
        self.cu_weapon = QComboBox()
        for d, m in WEAPONS:
            self.cu_weapon.addItem(d, m)
        self.cu_x, self.cu_y = _mk_spin(), _mk_spin()
        self.unit_list_tree = QTreeWidget()
        self.unit_list_tree.setHeaderLabels([tr("action_editor.col_unit"), tr("action_editor.col_weapon"), "X", "Y"])
        self.unit_list_tree.setRootIsDecorated(False)
        self.unit_list_tree.setMaximumHeight(110)
        cu_add_btn = QPushButton("+"); cu_add_btn.setFixedWidth(28)
        cu_add_btn.clicked.connect(self._cu_add)
        cu_rm_btn = QPushButton("−"); cu_rm_btn.setFixedWidth(28)
        cu_rm_btn.clicked.connect(self._cu_remove)
        cu_pick_btn = QPushButton("📍"); cu_pick_btn.setFixedWidth(28)
        cu_pick_btn.setToolTip(tr("action_editor.tooltip_pick_mine"))
        cu_pick_btn.clicked.connect(lambda: self._request_pick("primary"))
        cu_row = QHBoxLayout()
        cu_row.addWidget(self.cu_unit, 3)
        cu_row.addWidget(self.cu_weapon, 2)
        cu_row.addWidget(self.cu_x, 1)
        cu_row.addWidget(self.cu_y, 1)
        cu_row.addWidget(cu_pick_btn)
        cu_row.addWidget(cu_add_btn)
        cu_row.addWidget(cu_rm_btn)
        self.unit_editor = QWidget()
        cu_lay = QVBoxLayout(self.unit_editor)
        cu_lay.setContentsMargins(0, 0, 0, 0)
        cu_lay.addWidget(self.unit_list_tree)
        cu_lay.addLayout(cu_row)

        # --- recordBuilding-Liste: mehrere Gebaeude fuer dieselbe Gruppe ---
        # recordBuilding list: several buildings for the same group.
        # self.building bleibt fuer assignToGroup vergeben -- eigenes Widget.
        self.rb_building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.rb_building.addItem(d, m)
        self.rb_weapon = QComboBox()
        for d, m in WEAPONS:
            self.rb_weapon.addItem(d, m)
        self.rb_x, self.rb_y = _mk_spin(), _mk_spin()
        self.building_list_tree = QTreeWidget()
        self.building_list_tree.setHeaderLabels([tr("action_editor.col_building"), tr("action_editor.col_cargo"), "X", "Y"])
        self.building_list_tree.setRootIsDecorated(False)
        self.building_list_tree.setMaximumHeight(110)
        rb_add_btn = QPushButton("+"); rb_add_btn.setFixedWidth(28)
        rb_add_btn.clicked.connect(self._rb_add)
        rb_rm_btn = QPushButton("−"); rb_rm_btn.setFixedWidth(28)
        rb_rm_btn.clicked.connect(self._rb_remove)
        rb_pick_btn = QPushButton("📍"); rb_pick_btn.setFixedWidth(28)
        rb_pick_btn.setToolTip(tr("action_editor.tooltip_pick_mine"))
        rb_pick_btn.clicked.connect(lambda: self._request_pick("primary"))
        rb_row = QHBoxLayout()
        rb_row.addWidget(self.rb_building, 3)
        rb_row.addWidget(self.rb_weapon, 2)
        rb_row.addWidget(self.rb_x, 1)
        rb_row.addWidget(self.rb_y, 1)
        rb_row.addWidget(rb_pick_btn)
        rb_row.addWidget(rb_add_btn)
        rb_row.addWidget(rb_rm_btn)
        self.building_editor = QWidget()
        rb_lay = QVBoxLayout(self.building_editor)
        rb_lay.setContentsMargins(0, 0, 0, 0)
        rb_lay.addWidget(self.building_list_tree)
        rb_lay.addLayout(rb_row)

        # --- recordTube-Liste: mehrere Rohrleitungen (Liniensegmente) ---
        # recordTube list: several tube lines (segments) in one action.
        self.rt_x, self.rt_y = _mk_spin(), _mk_spin()
        self.rt_x2, self.rt_y2 = _mk_spin(), _mk_spin()
        self.tube_list_tree = QTreeWidget()
        self.tube_list_tree.setHeaderLabels([tr("action_editor.col_start_x"), tr("action_editor.col_start_y"), tr("action_editor.col_end_x"), tr("action_editor.col_end_y")])
        self.tube_list_tree.setRootIsDecorated(False)
        self.tube_list_tree.setMaximumHeight(110)
        rt_add_btn = QPushButton("+"); rt_add_btn.setFixedWidth(28)
        rt_add_btn.clicked.connect(self._rt_add)
        rt_rm_btn = QPushButton("−"); rt_rm_btn.setFixedWidth(28)
        rt_rm_btn.clicked.connect(self._rt_remove)
        rt_pick_btn = QPushButton("📍"); rt_pick_btn.setFixedWidth(28)
        rt_pick_btn.setToolTip(tr("action_editor.tooltip_pick_wall_line"))
        rt_pick_btn.clicked.connect(lambda: self._request_pick("tube_line"))
        rt_row = QHBoxLayout()
        for w in (self.rt_x, self.rt_y, self.rt_x2, self.rt_y2):
            rt_row.addWidget(w, 1)
        rt_row.addWidget(rt_pick_btn)
        rt_row.addWidget(rt_add_btn)
        rt_row.addWidget(rt_rm_btn)
        self.tube_editor = QWidget()
        rt_lay = QVBoxLayout(self.tube_editor)
        rt_lay.setContentsMargins(0, 0, 0, 0)
        rt_lay.addWidget(self.tube_list_tree)
        rt_lay.addLayout(rt_row)

        # --- recordWall-Liste: mehrere Mauerabschnitte (Liniensegmente) ---
        # recordWall list: several wall sections (segments), each with its own type.
        self.rw_wall = QComboBox()
        for d, m, _ in WALL_ITEMS:
            if m != "mapTube":
                self.rw_wall.addItem(d, m)
        self.rw_x, self.rw_y = _mk_spin(), _mk_spin()
        self.rw_x2, self.rw_y2 = _mk_spin(), _mk_spin()
        self.wall_list_tree = QTreeWidget()
        self.wall_list_tree.setHeaderLabels([tr("action_editor.col_type"), tr("action_editor.col_start_x"), tr("action_editor.col_start_y"), tr("action_editor.col_end_x"), tr("action_editor.col_end_y")])
        self.wall_list_tree.setRootIsDecorated(False)
        self.wall_list_tree.setMaximumHeight(110)
        rw_add_btn = QPushButton("+"); rw_add_btn.setFixedWidth(28)
        rw_add_btn.clicked.connect(self._rw_add)
        rw_rm_btn = QPushButton("−"); rw_rm_btn.setFixedWidth(28)
        rw_rm_btn.clicked.connect(self._rw_remove)
        rw_pick_btn = QPushButton("📍"); rw_pick_btn.setFixedWidth(28)
        rw_pick_btn.setToolTip(tr("action_editor.tooltip_pick_wall_line"))
        rw_pick_btn.clicked.connect(lambda: self._request_pick("wall_line"))
        rw_row = QHBoxLayout()
        rw_row.addWidget(self.rw_wall, 2)
        for w in (self.rw_x, self.rw_y, self.rw_x2, self.rw_y2):
            rw_row.addWidget(w, 1)
        rw_row.addWidget(rw_pick_btn)
        rw_row.addWidget(rw_add_btn)
        rw_row.addWidget(rw_rm_btn)
        self.wall_editor = QWidget()
        rw_lay = QVBoxLayout(self.wall_editor)
        rw_lay.setContentsMargins(0, 0, 0, 0)
        rw_lay.addWidget(self.wall_list_tree)
        rw_lay.addLayout(rw_row)

        # --- setMorale: Modus + Spieler (inkl. "Alle") ---
        # setMorale: mode + player (incl. "all")
        self.morale_mode = QComboBox()
        fill_combo(self.morale_mode, MORALE_MODES, "morale_modes")
        self.morale_player = QComboBox()
        self.morale_player.addItem(tr("action_editor.player_all"), -1)
        for i in range(6):
            self.morale_player.addItem(str(i), i)

        # --- setMusic: Songliste + Loop-Startindex ---
        # setMusic: song list + loop start index
        self.song_combo = QComboBox()
        for s in SONG_IDS:
            self.song_combo.addItem(s, s)
        self.song_list = QListWidget()
        self.song_list.setMaximumHeight(110)
        song_add_btn = QPushButton("+"); song_add_btn.setFixedWidth(28)
        song_add_btn.clicked.connect(self._song_add)
        song_rm_btn = QPushButton("−"); song_rm_btn.setFixedWidth(28)
        song_rm_btn.clicked.connect(self._song_remove)
        song_row = QHBoxLayout()
        song_row.addWidget(self.song_combo, 1)
        song_row.addWidget(song_add_btn)
        song_row.addWidget(song_rm_btn)
        self.songs_editor = QWidget()
        song_lay = QVBoxLayout(self.songs_editor)
        song_lay.setContentsMargins(0, 0, 0, 0)
        song_lay.addWidget(self.song_list)
        song_lay.addLayout(song_row)
        self.repeat_start = QSpinBox()
        self.repeat_start.setRange(0, 25)

        # --- lavaFlowAni: Richtung + Freeze ---
        # lavaFlowAni: direction + freeze
        self.flow_dir = QComboBox()
        fill_combo(self.flow_dir, FLOW_DIRS, "flow_dirs")
        self.flow_freeze = QCheckBox(tr("action_editor.chk_flow_freeze"))

        # --- modUnitStats: Einheitentyp + Wert-Liste (HFL UnitInfo) ---
        # modUnitStats: unit type + value list (HFL UnitInfo)
        self.stats_unit = QComboBox()
        for d, m in ALL_UNITS:
            self.stats_unit.addItem(d, m)
        self.stat_combo = QComboBox()
        for s in UNIT_STATS:
            self.stat_combo.addItem(tr(f"unit_stats.{s}"), s)
        self.stat_value = QSpinBox()
        self.stat_value.setRange(0, 100000)
        self.stat_value.setValue(100)
        self.stats_tree = QTreeWidget()
        self.stats_tree.setHeaderLabels([tr("action_editor.col_stat"), tr("action_editor.col_value")])
        self.stats_tree.setRootIsDecorated(False)
        self.stats_tree.setMaximumHeight(110)
        stats_add_btn = QPushButton("+"); stats_add_btn.setFixedWidth(28)
        stats_add_btn.clicked.connect(self._stats_add)
        stats_rm_btn = QPushButton("−"); stats_rm_btn.setFixedWidth(28)
        stats_rm_btn.clicked.connect(self._stats_remove)
        stats_row = QHBoxLayout()
        stats_row.addWidget(self.stat_combo, 2)
        stats_row.addWidget(self.stat_value, 1)
        stats_row.addWidget(stats_add_btn)
        stats_row.addWidget(stats_rm_btn)
        self.stats_editor = QWidget()
        stats_lay = QVBoxLayout(self.stats_editor)
        stats_lay.setContentsMargins(0, 0, 0, 0)
        stats_lay.addWidget(self.stats_tree)
        stats_lay.addLayout(stats_row)

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
            "player": self.player,
            "spawn_mode": self.spawn_mode, "group_var_name": self.group_var_name,
            "wave_editor": self.wave_editor,
            "target": self.target,
            "group": self.group, "mining_group": self.mining_group,
            "mine_pick": self.mine_pick, "smelter_pick": self.smelter_pick,
            "mine_ref": self.mine_ref, "smelter_ref": self.smelter_ref,
            "mining_wait_hint": self.mining_wait_hint,
            "building": self.building, "wall": self.wall,
            "target_group": self.target_group, "source_group": self.source_group,
            "vehicle": self.vehicle, "priority": self.priority,
            "target_count": self.target_count, "assign_group": self.assign_group,
            "var_name": self.var_name, "mod_mode": self.mod_mode, "var_expr": self.var_expr,
            "idle_rect_w": self.idle_rect_w, "staging_rect_w": self.staging_rect_w,
            "attack_rect_w": self.attack_rect_w,
            "wave_group": self.wave_group, "fg_command": self.fg_command,
            "cmd_target": self.cmd_target, "cmd_rect_w": self.cmd_rect_w,
            "unit_ref": self.unit_ref, "unit_command": self.unit_command,
            "cmd_unit_target": self.cmd_unit_target, "patrol_editor": self.patrol_editor,
            "targ_editor": self.targ_editor,
            "unit_editor": self.unit_editor, "building_editor": self.building_editor,
            "tube_editor": self.tube_editor, "wall_editor": self.wall_editor,
            "morale_mode": self.morale_mode, "morale_player": self.morale_player,
            "songs_editor": self.songs_editor, "repeat_start": self.repeat_start,
            "flow_dir": self.flow_dir, "flow_freeze": self.flow_freeze,
            "stats_unit": self.stats_unit, "stats_editor": self.stats_editor,
        }
        labels = {
            "text": tr("action_editor.lbl_text"), "unit": tr("action_editor.lbl_unit"),
            "weapon": tr("action_editor.lbl_weapon_cargo"),
            "x": tr("action_editor.lbl_x"), "y": tr("action_editor.lbl_y"),
            "x2": tr("action_editor.lbl_x2"), "y2": tr("action_editor.lbl_y2"),
            "player": tr("action_editor.lbl_player"),
            "x_expr": tr("action_editor.lbl_x_expr"), "y_expr": tr("action_editor.lbl_y_expr"),
            "x2_expr": tr("action_editor.lbl_x2_expr"), "y2_expr": tr("action_editor.lbl_y2_expr"),
            "disaster_type": tr("action_editor.lbl_disaster_type"),
            "size": tr("action_editor.lbl_meteor_size"),
            "magnitude": tr("action_editor.lbl_magnitude"),
            "duration": tr("action_editor.lbl_duration"),
            "spread_speed": tr("action_editor.lbl_spread_speed"),
            "lava_zone_btn": "", "lava_zone_lbl": tr("action_editor.lbl_lava_zone"),
            "now": tr("action_editor.lbl_now"),
            "target": tr("action_editor.lbl_target_trigger"), "group": "BuildingGroup:",
            "mining_group": tr("action_editor.lbl_mining_group"),
            "mine_pick": tr("action_editor.lbl_mine_pick"),
            "smelter_pick": tr("action_editor.lbl_smelter_pick"),
            "mine_ref": tr("action_editor.lbl_mine_ref"),
            "smelter_ref": tr("action_editor.lbl_smelter_ref"),
            "mining_wait_hint": "",
            "building": tr("action_editor.lbl_building"), "wall": "Wall:",
            "target_group": tr("action_editor.lbl_target_group"), "source_group": "ReinforceGroup:",
            "vehicle": tr("action_editor.lbl_vehicle"), "priority": tr("action_editor.lbl_priority"),
            "target_count": tr("action_editor.lbl_target_count"),
            "targ_editor": tr("action_editor.lbl_vehicles"),
            "assign_group": tr("action_editor.lbl_target_group"),
            "var_name": tr("action_editor.lbl_var_name"), "mod_mode": tr("action_editor.lbl_mod_mode"),
            "var_expr": tr("action_editor.lbl_var_expr"),
            "spawn_mode": tr("action_editor.lbl_mod_mode"),
            "group_var_name": tr("action_editor.lbl_group_var_name"),
            "wave_editor": tr("action_editor.lbl_wave_units"),
            "idle_rect_w": tr("action_editor.lbl_idle_rect"),
            "staging_rect_w": tr("action_editor.lbl_staging_rect"),
            "attack_rect_w": tr("action_editor.lbl_attack_rect"),
            "wave_group": tr("action_editor.lbl_wave_group"),
            "fg_command": tr("action_editor.lbl_fg_command"),
            "cmd_target": tr("action_editor.lbl_cmd_target"),
            "cmd_rect_w": tr("action_editor.lbl_cmd_rect"),
            "unit_ref": tr("action_editor.lbl_unit_ref"),
            "unit_command": tr("action_editor.lbl_unit_command"),
            "cmd_unit_target": tr("action_editor.lbl_cmd_unit_target"),
            "patrol_editor": tr("action_editor.lbl_patrol_editor"),
            "unit_editor": tr("action_editor.lbl_unit_editor"),
            "building_editor": tr("action_editor.lbl_building_editor"),
            "tube_editor": tr("action_editor.lbl_tube_editor"),
            "wall_editor": tr("action_editor.lbl_wall_editor"),
            "morale_mode": tr("action_editor.lbl_morale_mode"),
            "morale_player": tr("action_editor.lbl_player"),
            "songs_editor": tr("action_editor.lbl_songs"),
            "repeat_start": tr("action_editor.lbl_repeat_start"),
            "flow_dir": tr("action_editor.lbl_flow_dir"),
            "flow_freeze": "",
            "stats_unit": tr("action_editor.lbl_unit"),
            "stats_editor": tr("action_editor.lbl_stats"),
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

        # Mausrad ueber Eingabefeldern soll nur bei Fokus Werte aendern
        # (sonst verstellt Scrollen im Panel versehentlich Werte).
        # The mouse wheel should only change values on focused widgets
        # (otherwise scrolling the panel accidentally edits values).
        self._wheel_filter = _NoWheelFilter(self)
        for w in self.findChildren(QSpinBox) + self.findChildren(QComboBox):
            w.setFocusPolicy(Qt.StrongFocus)
            w.installEventFilter(self._wheel_filter)

    # --- Interne Hilfsmethoden ---

    def _current_kind(self):
        return self.kind.currentData()

    # --- Gruppen-/Einheiten-Befehlslisten / group & unit command lists ---

    def _fill_group_commands(self):
        gtype = self._group_types.get(self.wave_group.currentData(), "FightGroup")
        cmds = _GROUP_COMMANDS.get(gtype, []) + _GROUP_COMMANDS_COMMON
        cur = self.fg_command.currentData()
        self.fg_command.blockSignals(True)
        self.fg_command.clear()
        for value, key in cmds:
            self.fg_command.addItem(tr(f"action_editor.{key}"), value)
        i = self.fg_command.findData(cur)
        if i >= 0:
            self.fg_command.setCurrentIndex(i)
        self.fg_command.blockSignals(False)

    def _update_group_commands(self):
        self._fill_group_commands()
        self._update()
        self._save()

    def _fill_unit_commands(self):
        mid = self._named_unit_types.get(self.unit_ref.currentData(), "")
        cur = self.unit_command.currentData()
        self.unit_command.blockSignals(True)
        self.unit_command.clear()
        for value, key in unit_commands_for(mid):
            self.unit_command.addItem(tr(f"action_editor.{key}"), value)
        i = self.unit_command.findData(cur)
        if i >= 0:
            self.unit_command.setCurrentIndex(i)
        self.unit_command.blockSignals(False)

    def _update_unit_commands(self):
        self._fill_unit_commands()
        self._update()
        self._save()

    # --- Patrouillen-Wegpunkte / patrol waypoints ---

    def _patrol_points(self) -> list:
        return [self.patrol_list.topLevelItem(i).data(0, Qt.UserRole)
                for i in range(self.patrol_list.topLevelItemCount())]

    def _patrol_refresh(self, points):
        self.patrol_list.clear()
        for n, (px, py) in enumerate(points[:8], 1):
            item = QTreeWidgetItem([str(n), str(px), str(py)])
            item.setData(0, Qt.UserRole, [int(px), int(py)])
            self.patrol_list.addTopLevelItem(item)

    def _patrol_add(self):
        pts = self._patrol_points()
        if len(pts) >= 8:
            return
        pts.append([self.patrol_x.value(), self.patrol_y.value()])
        self._patrol_refresh(pts)
        self._save()

    def _patrol_remove(self):
        idx = self.patrol_list.indexOfTopLevelItem(self.patrol_list.currentItem())
        if idx >= 0:
            pts = self._patrol_points()
            del pts[idx]
            self._patrol_refresh(pts)
            self._save()

    def _patrol_move(self, delta):
        idx = self.patrol_list.indexOfTopLevelItem(self.patrol_list.currentItem())
        pts = self._patrol_points()
        j = idx + delta
        if idx < 0 or not (0 <= j < len(pts)):
            return
        pts[idx], pts[j] = pts[j], pts[idx]
        self._patrol_refresh(pts)
        self.patrol_list.setCurrentItem(self.patrol_list.topLevelItem(j))
        self._save()

    # --- SetTargCount-Liste / setTargCount list ---

    def _targ_add(self):
        count = self.targ_count_edit.value()
        item = QTreeWidgetItem([
            self.targ_unit.currentText(), self.targ_weapon.currentText(), str(count)])
        item.setData(0, Qt.UserRole, (self.targ_unit.currentData(),
                                      self.targ_weapon.currentData(), count))
        self.targ_list.addTopLevelItem(item)
        self._save()

    def _targ_remove(self):
        idx = self.targ_list.indexOfTopLevelItem(self.targ_list.currentItem())
        if idx >= 0:
            self.targ_list.takeTopLevelItem(idx)
            self._save()

    def _targ_counts_from_list(self) -> list:
        out = []
        for i in range(self.targ_list.topLevelItemCount()):
            unit, weapon, count = self.targ_list.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"unit_type": unit, "weapon_type": weapon, "count": count})
        return out

    def _targ_list_load(self, targ_counts):
        self.targ_list.clear()
        by_id_weapon = {m: d for d, m in WEAPONS}
        for e in (targ_counts or []):
            unit = e.get("unit_type", "mapConVec")
            weapon = e.get("weapon_type", "mapNone")
            count = e.get("count", 1)
            unit_label = unit
            i = self.targ_unit.findData(unit)
            if i >= 0:
                unit_label = self.targ_unit.itemText(i)
            item = QTreeWidgetItem([unit_label, by_id_weapon.get(weapon, weapon), str(count)])
            item.setData(0, Qt.UserRole, (unit, weapon, count))
            self.targ_list.addTopLevelItem(item)

    # --- setMusic-Songliste / setMusic song list ---

    def _song_add(self):
        s = self.song_combo.currentData()
        if s:
            self.song_list.addItem(s)
            self._save()

    def _song_remove(self):
        row = self.song_list.currentRow()
        if row >= 0:
            self.song_list.takeItem(row)
            self._save()

    def _songs_from_list(self) -> list:
        return [self.song_list.item(i).text() for i in range(self.song_list.count())]

    def _song_list_load(self, songs):
        self.song_list.clear()
        for s in (songs or []):
            self.song_list.addItem(str(s))

    # --- modUnitStats-Liste / modUnitStats list ---

    def _stats_add(self):
        stat = self.stat_combo.currentData()
        if not stat:
            return
        item = QTreeWidgetItem([self.stat_combo.currentText(), str(self.stat_value.value())])
        item.setData(0, Qt.UserRole, (stat, self.stat_value.value()))
        self.stats_tree.addTopLevelItem(item)
        self._save()

    def _stats_remove(self):
        idx = self.stats_tree.indexOfTopLevelItem(self.stats_tree.currentItem())
        if idx >= 0:
            self.stats_tree.takeTopLevelItem(idx)
            self._save()

    def _stats_from_tree(self) -> list:
        out = []
        for i in range(self.stats_tree.topLevelItemCount()):
            stat, value = self.stats_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"stat": stat, "value": value})
        return out

    def _stats_list_load(self, stat_mods):
        self.stats_tree.clear()
        for m in (stat_mods or []):
            stat = m.get("stat", "")
            if not stat:
                continue
            i = self.stat_combo.findData(stat)
            label = self.stat_combo.itemText(i) if i >= 0 else stat
            item = QTreeWidgetItem([label, str(m.get("value", 0))])
            item.setData(0, Qt.UserRole, (stat, m.get("value", 0)))
            self.stats_tree.addTopLevelItem(item)

    # --- Angriffswellen-Liste / attack wave list ---

    def _wave_add(self):
        item = QTreeWidgetItem([
            self.wave_unit.currentText(), self.wave_weapon.currentText(),
            str(self.wave_count.value())])
        item.setData(0, Qt.UserRole, (self.wave_unit.currentData(),
                                      self.wave_weapon.currentData(),
                                      self.wave_count.value()))
        self.wave_list.addTopLevelItem(item)
        self._save()

    def _wave_remove(self):
        idx = self.wave_list.indexOfTopLevelItem(self.wave_list.currentItem())
        if idx >= 0:
            self.wave_list.takeTopLevelItem(idx)
            self._save()

    def _wave_units_from_list(self) -> list:
        out = []
        for i in range(self.wave_list.topLevelItemCount()):
            unit, weapon, count = self.wave_list.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"unit_type": unit, "weapon_type": weapon, "count": count})
        return out

    def _wave_list_load(self, wave_units):
        self.wave_list.clear()
        by_id_unit = {m: d for d, m in MILITARY_VEHICLES}
        by_id_weapon = {m: d for d, m in WEAPONS}
        for w in (wave_units or []):
            unit = w.get("unit_type", "mapLynx")
            weapon = w.get("weapon_type", "mapLaser")
            count = int(w.get("count", 1) or 1)
            item = QTreeWidgetItem([
                by_id_unit.get(unit, unit), by_id_weapon.get(weapon, weapon), str(count)])
            item.setData(0, Qt.UserRole, (unit, weapon, count))
            self.wave_list.addTopLevelItem(item)

    # --- createUnit-Liste / createUnit list ---

    def _cu_add(self):
        item = QTreeWidgetItem([
            self.cu_unit.currentText(), self.cu_weapon.currentText(),
            str(self.cu_x.value()), str(self.cu_y.value())])
        item.setData(0, Qt.UserRole, (self.cu_unit.currentData(), self.cu_weapon.currentData(),
                                      self.cu_x.value(), self.cu_y.value()))
        self.unit_list_tree.addTopLevelItem(item)
        self._save()

    def _cu_remove(self):
        idx = self.unit_list_tree.indexOfTopLevelItem(self.unit_list_tree.currentItem())
        if idx >= 0:
            self.unit_list_tree.takeTopLevelItem(idx)
            self._save()

    def _unit_list_from_tree(self) -> list:
        out = []
        for i in range(self.unit_list_tree.topLevelItemCount()):
            unit, weapon, x, y = self.unit_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"unit_type": unit, "weapon_type": weapon, "x": x, "y": y})
        return out

    def _unit_list_load(self, entries):
        self.unit_list_tree.clear()
        by_id_unit = {m: d for d, m in ALL_UNITS}
        by_id_weapon = {m: d for d, m in WEAPONS}
        for e in (entries or []):
            unit = e.get("unit_type", "mapScout")
            weapon = e.get("weapon_type", "mapNone")
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            item = QTreeWidgetItem([
                by_id_unit.get(unit, unit), by_id_weapon.get(weapon, weapon), str(x), str(y)])
            item.setData(0, Qt.UserRole, (unit, weapon, x, y))
            self.unit_list_tree.addTopLevelItem(item)

    # --- recordBuilding-Liste / recordBuilding list ---

    def _rb_add(self):
        item = QTreeWidgetItem([
            self.rb_building.currentText(), self.rb_weapon.currentText(),
            str(self.rb_x.value()), str(self.rb_y.value())])
        item.setData(0, Qt.UserRole, (self.rb_building.currentData(), self.rb_weapon.currentData(),
                                      self.rb_x.value(), self.rb_y.value()))
        self.building_list_tree.addTopLevelItem(item)
        self._save()

    def _rb_remove(self):
        idx = self.building_list_tree.indexOfTopLevelItem(self.building_list_tree.currentItem())
        if idx >= 0:
            self.building_list_tree.takeTopLevelItem(idx)
            self._save()

    def _building_list_from_tree(self) -> list:
        out = []
        for i in range(self.building_list_tree.topLevelItemCount()):
            building, weapon, x, y = self.building_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"building_type": building, "weapon_type": weapon, "x": x, "y": y})
        return out

    def _building_list_load(self, entries):
        self.building_list_tree.clear()
        by_id_building = {m: d for d, m, _ in STRUCTURES}
        by_id_weapon = {m: d for d, m in WEAPONS}
        for e in (entries or []):
            building = e.get("building_type", "mapCommandCenter")
            weapon = e.get("weapon_type", "mapNone")
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            item = QTreeWidgetItem([
                by_id_building.get(building, building), by_id_weapon.get(weapon, weapon), str(x), str(y)])
            item.setData(0, Qt.UserRole, (building, weapon, x, y))
            self.building_list_tree.addTopLevelItem(item)

    # --- recordTube-Liste / recordTube list ---

    def _rt_add(self):
        item = QTreeWidgetItem([
            str(self.rt_x.value()), str(self.rt_y.value()),
            str(self.rt_x2.value()), str(self.rt_y2.value())])
        item.setData(0, Qt.UserRole, (self.rt_x.value(), self.rt_y.value(),
                                      self.rt_x2.value(), self.rt_y2.value()))
        self.tube_list_tree.addTopLevelItem(item)
        self._save()

    def _rt_remove(self):
        idx = self.tube_list_tree.indexOfTopLevelItem(self.tube_list_tree.currentItem())
        if idx >= 0:
            self.tube_list_tree.takeTopLevelItem(idx)
            self._save()

    def _tube_list_from_tree(self) -> list:
        out = []
        for i in range(self.tube_list_tree.topLevelItemCount()):
            x, y, x2, y2 = self.tube_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"x": x, "y": y, "x2": x2, "y2": y2})
        return out

    def _tube_list_load(self, entries):
        self.tube_list_tree.clear()
        for e in (entries or []):
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            x2 = int(e.get("x2", 0) or 0)
            y2 = int(e.get("y2", 0) or 0)
            item = QTreeWidgetItem([str(x), str(y), str(x2), str(y2)])
            item.setData(0, Qt.UserRole, (x, y, x2, y2))
            self.tube_list_tree.addTopLevelItem(item)

    # --- recordWall-Liste / recordWall list ---

    def _rw_add(self):
        item = QTreeWidgetItem([
            self.rw_wall.currentText(), str(self.rw_x.value()), str(self.rw_y.value()),
            str(self.rw_x2.value()), str(self.rw_y2.value())])
        item.setData(0, Qt.UserRole, (self.rw_wall.currentData(), self.rw_x.value(), self.rw_y.value(),
                                      self.rw_x2.value(), self.rw_y2.value()))
        self.wall_list_tree.addTopLevelItem(item)
        self._save()

    def _rw_remove(self):
        idx = self.wall_list_tree.indexOfTopLevelItem(self.wall_list_tree.currentItem())
        if idx >= 0:
            self.wall_list_tree.takeTopLevelItem(idx)
            self._save()

    def _wall_list_from_tree(self) -> list:
        out = []
        for i in range(self.wall_list_tree.topLevelItemCount()):
            wall, x, y, x2, y2 = self.wall_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"wall_type": wall, "x": x, "y": y, "x2": x2, "y2": y2})
        return out

    def _wall_list_load(self, entries):
        self.wall_list_tree.clear()
        by_id_wall = {m: d for d, m, _ in WALL_ITEMS}
        for e in (entries or []):
            wall = e.get("wall_type", "mapWall")
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            x2 = int(e.get("x2", 0) or 0)
            y2 = int(e.get("y2", 0) or 0)
            item = QTreeWidgetItem([
                by_id_wall.get(wall, wall), str(x), str(y), str(x2), str(y2)])
            item.setData(0, Qt.UserRole, (wall, x, y, x2, y2))
            self.wall_list_tree.addTopLevelItem(item)

    # --- startMining: Mine/Smelter aus platzierten Gebaeuden waehlen ---

    def _pick_mine_from_list(self):
        data = self.mine_pick.currentData()
        if data:
            self.x.setValue(data[0])
            self.y.setValue(data[1])
        self._update_mining_wait_hint()

    def _pick_smelter_from_list(self):
        data = self.smelter_pick.currentData()
        if data:
            self.x2.setValue(data[0])
            self.y2.setValue(data[1])
        self._update_mining_wait_hint()

    def _update_mining_wait_hint(self):
        self.mining_wait_hint.setText(tr(
            "action_editor.mining_wait_hint",
            mx=self.x.value(), my=self.y.value(),
            sx=self.x2.value(), sy=self.y2.value(),
        ))

    def _current_disaster_type(self):
        return self.disaster_type.currentData() or "meteor"

    def _disaster_type_from_action(self, action):
        return getattr(action, "disaster_type", "meteor") or "meteor"

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
            "x_expr": tr("action_editor.lbl_x_expr"), "y_expr": tr("action_editor.lbl_y_expr"),
            "x2_expr": tr("action_editor.lbl_x2_expr"), "y2_expr": tr("action_editor.lbl_y2_expr"),
        }
        for key, default in defaults.items():
            widget = self._rows.get(key)
            if widget is None:
                continue
            label = self.form.labelForField(widget)
            if label is not None:
                label.setText(overrides.get(key, default))
        if kind == "sendAttackWave":
            self.pick_xy_btn.setText("📍 Sammelbereich Ecke 1 auf Karte setzen")
            self.pick_xy2_btn.setText("📍 Sammelbereich Ecke 2 auf Karte setzen")
        elif kind in ("recordTube", "recordWall"):
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
        if kind == "sendAttackWave" and self.spawn_mode.currentData() == "reinforce":
            fields = fields + ["source_group", "priority"]
        if kind == "fightGroupCmd":
            cmd = self.fg_command.currentData() or ""
            if cmd in ("attackArea", "guardArea", "setBuildRect", "setIdleRect"):
                fields = fields + ["cmd_rect_w"]
            elif cmd == "patrol":
                fields = fields + ["patrol_editor"]
            if cmd == "reinforceGroup":
                fields = fields + ["cmd_target", "priority"]
            elif cmd == "unReinforceGroup":
                fields = fields + ["cmd_target"]
            elif cmd in _GROUP_COMMANDS_UNIT_TARGET:
                fields = fields + ["cmd_unit_target"]
        if kind == "unitCmd":
            cmd = self.unit_command.currentData() or ""
            if cmd in ("move", "attackGround"):
                fields = fields + ["x", "y"]
            elif cmd == "patrol":
                fields = fields + ["patrol_editor"]
            elif cmd == "transfer":
                fields = fields + ["player"]
            elif cmd == "repair":
                fields = fields + ["cmd_unit_target"]
        if kind == "startMining":
            # Bei aktiver Referenz (Schleife/benannte Einheit) sind Position
            # und Positions-Picker fuer die jeweilige Seite ueberfluessig; der
            # Modus-2-Hinweis gilt nur fuer die positionsbasierte Variante.
            # With an active reference (loop/named unit), position and its
            # picker are moot for that side; the mode-2 hint only applies to
            # the position-based variant.
            mine_by_ref = bool(self.mine_ref.currentData())
            smelter_by_ref = bool(self.smelter_ref.currentData())
            if mine_by_ref:
                fields = [f for f in fields if f not in ("mine_pick", "x", "y")]
            if smelter_by_ref:
                fields = [f for f in fields if f not in ("smelter_pick", "x2", "y2")]
            if mine_by_ref or smelter_by_ref:
                fields = [f for f in fields if f != "mining_wait_hint"]
        for k, w in self._rows.items():
            self.form.setRowVisible(w, k in fields)
        if kind == "modVar":
            self.form.setRowVisible(self.var_expr, self.mod_mode.currentData() == "expr")
        if kind == "sendAttackWave":
            self.now.setText(tr("action_editor.chk_now_wave"))
        elif kind != "createDisaster":
            self.now.setText(tr("action_editor.chk_now_meteor"))
        if kind == "createDisaster":
            if self._current_disaster_type() == "eruption":
                self.now.setText(tr("action_editor.chk_now_eruption"))
            else:
                self.now.setText(tr("action_editor.chk_now_meteor"))
            # Vortex mit Dauer 0 = Permavortex (SDK-Quirk) -- am Label zeigen.
            # Vortex with duration 0 = permanent vortex (SDK quirk) -- show
            # the hint on the label.
            dur_label = self.form.labelForField(self.duration)
            if dur_label is not None:
                if self._current_disaster_type() == "vortex":
                    dur_label.setText(tr("action_editor.lbl_duration_vortex"))
                else:
                    dur_label.setText(tr("action_editor.lbl_duration"))
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
        # Gleiche Fahrzeugliste fuer die setTargCount-Liste (targ_editor)
        # Same vehicle list for the setTargCount list (targ_editor)
        targ_cur = self.targ_unit.currentData()
        self.targ_unit.blockSignals(True)
        self.targ_unit.clear()
        for d, m in vehicles:
            self.targ_unit.addItem(d, m)
        if targ_cur is not None:
            i = self.targ_unit.findData(targ_cur)
            if i >= 0:
                self.targ_unit.setCurrentIndex(i)
        self.targ_unit.blockSignals(False)

    def _load(self, a):
        # Waehrend des Ladens keine Saves: Combo-Signale (z.B. unit_ref ->
        # _update_unit_commands -> _save) wuerden sonst noch leere Widgets
        # in die Aktion zurueckschreiben.
        # Block saves while loading: combo signals would otherwise write
        # still-empty widgets back into the action.
        self._loading = True
        self._set_kind(a.kind)
        self.text.setText(a.text)
        self._set_combo(self.unit, a.unit_type)
        self._set_combo(self.weapon, a.weapon_type)
        self.x.setValue(a.x); self.y.setValue(a.y); self.x2.setValue(a.x2); self.y2.setValue(a.y2)
        # Eingabezeilen der neuen Listen-Editoren mit denselben (per Klick auf
        # der Karte gesetzten) Koordinaten vorbelegen -- so landet ein Klick
        # auf "📍" direkt bereit fuer den naechsten "+"-Klick.
        # Seed the new list editors' input rows with the same coordinates
        # (set via a map click) -- so clicking "📍" lands ready for the next
        # "+" click.
        self.cu_x.setValue(a.x); self.cu_y.setValue(a.y)
        self.rb_x.setValue(a.x); self.rb_y.setValue(a.y)
        self.rt_x.setValue(a.x); self.rt_y.setValue(a.y)
        self.rt_x2.setValue(a.x2); self.rt_y2.setValue(a.y2)
        self.rw_x.setValue(a.x); self.rw_y.setValue(a.y)
        self.rw_x2.setValue(a.x2); self.rw_y2.setValue(a.y2)
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
        self.lava_zone_lbl.setText(tr("action_editor.lava_tiles_count", n=n))
        self.now.setChecked(bool(getattr(a, "now", False)))
        self.player.setValue(a.player)
        self._set_combo(self.target, a.target)
        self._set_combo(self.group, a.group_name)
        self._set_combo(self.mining_group, a.group_name)
        self._set_combo(self.assign_group, a.group_name)
        self._set_combo(self.target_group, a.group_name)
        self._set_combo(self.building, a.building_type)
        self._set_combo(self.wall, a.wall_type)
        self._set_combo(self.source_group, a.source_group_name)
        self._update_vehicles()
        self._set_combo(self.vehicle, a.unit_type)
        self.priority.setValue(a.reinforce_priority)
        self.target_count.setValue(a.target_count)
        self._targ_list_load(getattr(a, "targ_counts", None))
        self._unit_list_load(getattr(a, "unit_list", None))
        self._building_list_load(getattr(a, "building_list", None))
        self._tube_list_load(getattr(a, "tube_list", None))
        self._wall_list_load(getattr(a, "wall_list", None))
        self._set_combo(self.spawn_mode, getattr(a, "spawn_mode", "spawn") or "spawn")
        self._set_combo(self.group_var_name, getattr(a, "group_var_name", "") or "")
        for spin, attr in ((self.attack_x, "attack_x"), (self.attack_y, "attack_y"),
                           (self.attack_x2, "attack_x2"), (self.attack_y2, "attack_y2"),
                           (self.idle_x, "idle_x"), (self.idle_y, "idle_y"),
                           (self.idle_x2, "idle_x2"), (self.idle_y2, "idle_y2")):
            spin.setValue(int(getattr(a, attr, 0) or 0))
        if a.kind == "sendAttackWave":
            self.stage_x.setValue(a.x); self.stage_y.setValue(a.y)
            self.stage_x2.setValue(a.x2); self.stage_y2.setValue(a.y2)
        if a.kind == "fightGroupCmd":
            self._set_combo(self.wave_group, getattr(a, "group_name", "") or "")
            self._fill_group_commands()
            self._set_combo(self.fg_command, getattr(a, "fg_command", "attackArea") or "attackArea")
            self._set_combo(self.cmd_target, getattr(a, "target", "") or "")
            self._set_combo(self.cmd_unit_target, getattr(a, "target", "") or "")
            self.cmd_x.setValue(a.x); self.cmd_y.setValue(a.y)
            self.cmd_x2.setValue(a.x2); self.cmd_y2.setValue(a.y2)
        if a.kind == "unitCmd":
            self._set_combo(self.unit_ref, getattr(a, "unit_ref", "") or "")
            self._fill_unit_commands()
            self._set_combo(self.unit_command, getattr(a, "fg_command", "move") or "move")
            self._set_combo(self.cmd_unit_target, getattr(a, "target", "") or "")
        self._patrol_refresh(list(getattr(a, "patrol_points", None) or []))
        self._wave_list_load(getattr(a, "wave_units", None))
        vn = getattr(a, 'var_name', '') or ''
        i = self.var_name.findData(vn)
        if i >= 0:
            self.var_name.setCurrentIndex(i)
        mm = getattr(a, 'mod_mode', 'inc') or 'inc'
        j = self.mod_mode.findData(mm)
        if j >= 0:
            self.mod_mode.setCurrentIndex(j)
        self.var_expr.setValue(getattr(a, 'var_expr', '') or '')
        self._set_combo(self.mine_ref, getattr(a, "mine_ref", "") or "")
        self._set_combo(self.smelter_ref, getattr(a, "smelter_ref", "") or "")
        self._update_mining_wait_hint()
        # fill_combo-Combos: itemData = Label -> Label aus Wert rueckwaerts suchen
        # fill_combo combos: itemData = label -> reverse-look up label from value
        morale_label = {v: k for k, v in MORALE_MODES.items()}.get(
            getattr(a, "morale_mode", "good") or "good")
        mi = self.morale_mode.findData(morale_label)
        if mi >= 0:
            self.morale_mode.setCurrentIndex(mi)
        mp = self.morale_player.findData(int(getattr(a, "player", 0)))
        if mp >= 0:
            self.morale_player.setCurrentIndex(mp)
        self._song_list_load(getattr(a, "songs", None))
        self.repeat_start.setValue(int(getattr(a, "repeat_start", 0) or 0))
        flow_label = {v: k for k, v in FLOW_DIRS.items()}.get(
            getattr(a, "flow_dir", "S") or "S")
        fi = self.flow_dir.findData(flow_label)
        if fi >= 0:
            self.flow_dir.setCurrentIndex(fi)
        self.flow_freeze.setChecked(bool(getattr(a, "flow_freeze", False)))
        self._set_combo(self.stats_unit, a.unit_type)
        self._stats_list_load(getattr(a, "stat_mods", None))
        self._loading = False
        self._update()

    def _connect_save_signals(self):
        self.text.textChanged.connect(self._save)
        self.group_var_name.currentIndexChanged.connect(self._save)
        for w in (self.x, self.y, self.x2, self.y2, self.player, self.priority, self.spread_speed,
                  self.attack_x, self.attack_y, self.attack_x2, self.attack_y2,
                  self.idle_x, self.idle_y, self.idle_x2, self.idle_y2,
                  self.stage_x, self.stage_y, self.stage_x2, self.stage_y2,
                  self.cmd_x, self.cmd_y, self.cmd_x2, self.cmd_y2):
            w.valueChanged.connect(self._save)
        for w in (self.x_expr, self.y_expr, self.x2_expr, self.y2_expr,
                  self.magnitude, self.duration, self.target_count, self.var_expr):
            w.valueChanged.connect(self._save)
        for w in (self.kind, self.unit, self.weapon, self.disaster_type, self.size,
                  self.target, self.group, self.mining_group, self.building, self.wall,
                  self.target_group, self.source_group, self.vehicle,
                  self.assign_group, self.var_name, self.mod_mode, self.spawn_mode,
                  self.wave_group, self.fg_command, self.cmd_target,
                  self.unit_ref, self.unit_command, self.cmd_unit_target,
                  self.mine_ref, self.smelter_ref,
                  self.morale_mode, self.morale_player, self.flow_dir, self.stats_unit):
            w.currentIndexChanged.connect(self._save)
        self.repeat_start.valueChanged.connect(self._save)
        self.now.toggled.connect(self._save)
        self.flow_freeze.toggled.connect(self._save)

    def _save(self):
        if self._loading:
            return
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
            a.source_group_name = self.source_group.currentData() or ""
            a.reinforce_priority = self.priority.value()
            a.targ_counts = self._targ_counts_from_list()
        elif k == "createUnit":
            a.unit_list = self._unit_list_from_tree()
        elif k == "recordBuilding":
            a.building_list = self._building_list_from_tree()
        elif k == "recordTube":
            a.tube_list = self._tube_list_from_tree()
        elif k == "recordWall":
            a.wall_list = self._wall_list_from_tree()
        elif k == "assignToGroup":
            a.group_name = self.assign_group.currentData() or ""
        elif k == "startMining":
            a.group_name = self.mining_group.currentData() or ""
            a.target_count = self.target_count.value()
            a.mine_ref = self.mine_ref.currentData() or ""
            a.smelter_ref = self.smelter_ref.currentData() or ""
        elif k == "sendAttackWave":
            a.spawn_mode = self.spawn_mode.currentData() or "spawn"
            a.group_var_name = self.group_var_name.currentData() or ""
            a.wave_units = self._wave_units_from_list()
            a.x = self.stage_x.value(); a.y = self.stage_y.value()
            a.x2 = self.stage_x2.value(); a.y2 = self.stage_y2.value()
            a.idle_x = self.idle_x.value(); a.idle_y = self.idle_y.value()
            a.idle_x2 = self.idle_x2.value(); a.idle_y2 = self.idle_y2.value()
            a.attack_x = self.attack_x.value(); a.attack_y = self.attack_y.value()
            a.attack_x2 = self.attack_x2.value(); a.attack_y2 = self.attack_y2.value()
            a.source_group_name = self.source_group.currentData() or ""
            a.reinforce_priority = self.priority.value()
        elif k == "fightGroupCmd":
            a.group_name = self.wave_group.currentData() or ""
            cmd = self.fg_command.currentData() or "attackArea"
            a.fg_command = cmd
            if cmd in _GROUP_COMMANDS_UNIT_TARGET:
                a.target = self.cmd_unit_target.currentData() or ""
            else:
                a.target = self.cmd_target.currentData() or ""
            a.reinforce_priority = self.priority.value()
            a.x = self.cmd_x.value(); a.y = self.cmd_y.value()
            a.x2 = self.cmd_x2.value(); a.y2 = self.cmd_y2.value()
        elif k == "unitCmd":
            a.unit_ref = self.unit_ref.currentData() or ""
            a.fg_command = self.unit_command.currentData() or "move"
            a.target = self.cmd_unit_target.currentData() or ""
        elif k == "setMorale":
            # fill_combo speichert das Label als itemData -> Wert nachschlagen
            # fill_combo stores the label as itemData -> look up the value
            a.morale_mode = MORALE_MODES.get(self.morale_mode.currentData(), "good")
            mp = self.morale_player.currentData()
            a.player = int(mp) if mp is not None else -1
        elif k == "setMusic":
            a.songs = self._songs_from_list()
            a.repeat_start = self.repeat_start.value()
        elif k == "lavaFlowAni":
            a.flow_dir = FLOW_DIRS.get(self.flow_dir.currentData(), "S")
            a.flow_freeze = self.flow_freeze.isChecked()
        elif k == "modUnitStats":
            a.unit_type = self.stats_unit.currentData() or "mapLynx"
            a.stat_mods = self._stats_from_tree()
        if k in ("unitCmd", "fightGroupCmd"):
            a.patrol_points = self._patrol_points()
        a.var_name = self.var_name.currentData() or ""
        a.mod_mode = self.mod_mode.currentData() or "inc"
        a.var_expr = self.var_expr.text()
        self.changed.emit()

    def _request_pick(self, field: str):
        self._save()
        if field == "lava_zone":
            self._lava_paint_active = not self._lava_paint_active
            self._update_lava_zone_btn()
        self.pick_requested.emit(field)

    def _update_lava_zone_btn(self):
        if self._lava_paint_active:
            self.lava_zone_btn.setText(tr("action_editor.btn_lava_zone_done"))
            self.lava_zone_btn.setStyleSheet(
                "background-color: #c45000; color: white; font-weight: bold; padding: 4px 8px;")
        else:
            self.lava_zone_btn.setText(tr("action_editor.btn_lava_zone"))
            self.lava_zone_btn.setStyleSheet("")


class ConditionListWidget(QWidget):
    """Wenn-Block: Liste von Bedingungen + Verknuepfung.

    When-block: list of conditions plus their AND/OR logic link.
    """
    def __init__(self, if_action, ctx=None, button_color: str | None = None):
        super().__init__()
        self.a = if_action
        self.ctx = ctx or {}
        self._button_color = button_color
        self._wheel_filter = _NoWheelFilter(self)
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
        logic.setFocusPolicy(Qt.StrongFocus)
        logic.installEventFilter(self._wheel_filter)
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
        if self._button_color:
            add.setStyleSheet(tint_button_stylesheet(self._button_color))
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
    def __init__(self, actions, ctx, button_color: str | None = None):
        super().__init__()
        self.actions = actions
        self.ctx = ctx
        self._button_color = button_color
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
        if self._button_color:
            add.setStyleSheet(tint_button_stylesheet(self._button_color))
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
        self._expanded = False
        self.setFrameShape(QFrame.StyledPanel)
        self._apply_card_style(action)
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
            lay.addWidget(self._build_loop_row(action, ctx))
            lay.addWidget(self._section(
                tr("action_editor.lbl_if"), ConditionListWidget(action, ctx=ctx, button_color=CONDITION_SECTION_COLOR),
                CONDITION_SECTION_COLOR))
            lay.addWidget(self._section(
                tr("action_editor.lbl_then"), ActionListWidget(action.then_actions, ctx, button_color=ACTION_SECTION_COLOR),
                ACTION_SECTION_COLOR))
            lay.addWidget(self._section(
                tr("action_editor.lbl_else"), ActionListWidget(action.else_actions, ctx, button_color=ACTION_SECTION_COLOR),
                ACTION_SECTION_COLOR))

    def _section(self, title: str, body: QWidget, color: str) -> QWidget:
        """Bedingungen-/Aktionen-Unterbereich eines if/for-Blocks, farblich abgehoben.

        Conditions/actions sub-section of an if/for block, visually tinted."""
        frame = QFrame()
        frame.setStyleSheet(tint_stylesheet(color, border_px=1, alpha=100))
        flay = QVBoxLayout(frame)
        flay.setContentsMargins(4, 4, 4, 4)
        lbl = QLabel(f"<b>{title}</b>")
        flay.addWidget(lbl)
        flay.addWidget(body)
        return frame

    def _build_loop_row(self, action, ctx) -> QWidget:
        """Schleifen-Steuerung des Logik-Blocks (Keine / N-mal / Für jede Einheit).

        Loop controls of the logic block (none / N times / for each unit)."""
        diff_values = ctx.get("diff_values") if isinstance(ctx, dict) else None
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("action_editor.lbl_loop")))
        self._loop_mode = QComboBox()
        self._loop_mode.addItem(tr("action_editor.loop_mode_none"), "none")
        self._loop_mode.addItem(tr("action_editor.loop_mode_count"), "count")
        self._loop_mode.addItem(tr("action_editor.loop_mode_foreach"), "forEach")
        mode_row.addWidget(self._loop_mode, 1)
        lay.addLayout(mode_row)

        # count: Anzahl (Ausdruck erlaubt)
        self._loop_count = ExprEdit(diff_values=diff_values)
        self._loop_count.setPlaceholderText(tr("action_editor.ph_loop_count"))
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel(tr("action_editor.lbl_loop_count")))
        count_row.addWidget(self._loop_count, 1)
        self._loop_count_row = QWidget(); self._loop_count_row.setLayout(count_row)
        lay.addWidget(self._loop_count_row)

        # forEach: Enumerator-Quelle + Einheitentyp-Filter + Spieler + Bereich
        # forEach: enumerator source + unit-type filter + player + rect
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel(tr("action_editor.lbl_enum_source")))
        self._loop_source = QComboBox()
        self._loop_source.addItem(tr("action_editor.enum_rect"), "rect")
        self._loop_source.addItem(tr("action_editor.enum_all"), "all")
        self._loop_source.addItem(tr("action_editor.enum_player"), "player")
        self._loop_source.addItem(tr("action_editor.enum_player_vehicles"), "playerVehicles")
        self._loop_source.addItem(tr("action_editor.enum_player_buildings"), "playerBuildings")
        self._loop_source.addItem(tr("action_editor.enum_type"), "type")
        src_row.addWidget(self._loop_source, 1)
        self._loop_src_row = QWidget(); self._loop_src_row.setLayout(src_row)
        lay.addWidget(self._loop_src_row)

        fe_row = QHBoxLayout()
        self._loop_unit = QComboBox()
        self._loop_unit.addItem(tr("action_editor.enum_all"), "mapAny")
        for d, m in ALL_UNITS:
            self._loop_unit.addItem(d, m)
        self._loop_unit.setToolTip(tr("action_editor.ph_enum_type"))
        fe_row.addWidget(self._loop_unit, 2)
        self._loop_player = QSpinBox()
        self._loop_player.setRange(-1, 5)
        self._loop_player.setSpecialValueText(tr("action_editor.player_all"))
        self._loop_player.setToolTip(tr("action_editor.ph_enum_player"))
        fe_row.addWidget(self._loop_player, 1)
        self._loop_fe_row1 = QWidget(); self._loop_fe_row1.setLayout(fe_row)
        lay.addWidget(self._loop_fe_row1)

        rect_row = QHBoxLayout()
        rect_row.addWidget(QLabel(tr("action_editor.lbl_enum_rect")))
        self._loop_rect_spins = []
        for _ in range(4):
            s = QSpinBox(); s.setRange(0, 1023)
            s.setButtonSymbols(QAbstractSpinBox.NoButtons)
            s.setMinimumWidth(36)
            rect_row.addWidget(s, 1)
            self._loop_rect_spins.append(s)
        pick = QPushButton("📍")
        pick.setFixedWidth(28)
        pick.setToolTip(tr("action_editor.tooltip_pick_enum_rect"))
        pick.clicked.connect(lambda: self._on_pick("area_rect"))
        rect_row.addWidget(pick)
        self._loop_fe_row2 = QWidget(); self._loop_fe_row2.setLayout(rect_row)
        lay.addWidget(self._loop_fe_row2)

        # Mausrad soll nur bei fokussierten Feldern Werte aendern -- sonst
        # verstellt Scrollen ueber der Karte (z.B. "Quelle") versehentlich
        # den Eintrag.
        # Wheel should only change values on focused widgets -- otherwise
        # scrolling over the card (e.g. "Quelle"/source) accidentally
        # changes the selection.
        self._loop_wheel_filter = _NoWheelFilter(box)
        for w in (self._loop_mode, self._loop_source, self._loop_unit, self._loop_player,
                  *self._loop_rect_spins):
            w.setFocusPolicy(Qt.StrongFocus)
            w.installEventFilter(self._loop_wheel_filter)

        # Werte laden / load values
        i = self._loop_mode.findData(getattr(action, "loop_mode", "none") or "none")
        if i >= 0:
            self._loop_mode.setCurrentIndex(i)
        s = self._loop_source.findData(getattr(action, "enum_source", "rect") or "rect")
        if s >= 0:
            self._loop_source.setCurrentIndex(s)
        self._loop_count.setValue(getattr(action, "loop_count", 1))
        j = self._loop_unit.findData(getattr(action, "unit_type", "mapAny") or "mapAny")
        if j >= 0:
            self._loop_unit.setCurrentIndex(j)
        self._loop_player.setValue(int(getattr(action, "player", -1)))
        for s, v in zip(self._loop_rect_spins,
                        (action.x, action.y, action.x2, action.y2)):
            s.setValue(int(v))

        def save(*_a):
            action.loop_mode = self._loop_mode.currentData() or "none"
            action.enum_source = self._loop_source.currentData() or "rect"
            action.loop_count = self._loop_count.value()
            action.unit_type = self._loop_unit.currentData() or "mapAny"
            action.player = self._loop_player.value()
            action.x, action.y, action.x2, action.y2 = (
                s.value() for s in self._loop_rect_spins)
            update_vis()
            self._apply_card_style(action)

        def update_vis():
            mode = self._loop_mode.currentData() or "none"
            self._loop_count_row.setVisible(mode == "count")
            self._loop_src_row.setVisible(mode == "forEach")
            self._loop_fe_row1.setVisible(mode == "forEach")
            self._loop_fe_row2.setVisible(mode == "forEach")

        self._loop_mode.currentIndexChanged.connect(save)
        self._loop_source.currentIndexChanged.connect(save)
        self._loop_unit.currentIndexChanged.connect(save)
        self._loop_player.valueChanged.connect(save)
        self._loop_count.valueChanged.connect(save)
        for s in self._loop_rect_spins:
            s.valueChanged.connect(save)
        update_vis()
        return box

    def _apply_card_style(self, action):
        kind = getattr(action, "kind", "noop")
        if kind == "if":
            # If-/For-Bloecke: der GANZE Block bekommt eine Umrandung (kein
            # Flaechenhintergrund, keine Einfaerbung der Beschriftungen) --
            # macht Wenn/Zaehlschleife/Enumerator-Schleife auf einen Blick
            # sichtbar, ohne grell zu wirken.
            # If/for blocks: the WHOLE block gets an outline (no background
            # fill, no tinted text) -- makes plain-if/count-loop/enumerator-
            # loop visible at a glance without looking garish.
            loop_mode = getattr(action, "loop_mode", "none") or "none"
            accent = IF_LOOP_COLOR.get(loop_mode, IF_LOOP_COLOR["none"])
            self.setStyleSheet(tint_stylesheet(accent, border_px=2))
        else:
            accent = ACTION_CATEGORY_COLOR.get(kind, SURFACE1)
            self.setStyleSheet(
                "QFrame {"
                " border: 1px solid #3a3a5c;"
                f" border-left: 3px solid {accent};"
                " border-radius: 4px;"
                " background-color: #252535;"
                "}"
            )

    def _notify_area_preview(self, action_or_none):
        cb = self.ctx.get("on_area_preview") if isinstance(self.ctx, dict) else None
        if callable(cb):
            cb(action_or_none)

    def _on_form_changed(self):
        if self._det is not None:
            self._det.setText(action_params_summary(self.a))
        self._title_lbl.setText(f"<b>{action_kind_label(self.a.kind)}</b>")
        self._apply_card_style(self.a)
        # Live-Update der Bereichs-Vorschau waehrend die Karte offen ist
        # Live-update the area preview while the card is open
        if self._expanded:
            self._notify_area_preview(self.a)

    def _on_pick(self, field: str):
        cb = self.ctx.get("on_map_pick") if isinstance(self.ctx, dict) else None
        if callable(cb):
            cb(self.a, field)

    def _toggle_form(self):
        if self._form is None:
            return
        if self._expanded:
            self.collapse()
        else:
            self.parent_list._collapse_all()
            self.expand()

    def expand(self):
        if self._form is not None:
            self._expanded = True
            self._form.setVisible(True)
            if self._toggle_btn is not None:
                self._toggle_btn.setText("▲")
            self._notify_area_preview(self.a)

    def collapse(self):
        if self._form is not None:
            was_expanded = self._expanded
            self._expanded = False
            self._form.setVisible(False)
            if self._toggle_btn is not None:
                self._toggle_btn.setText("▼")
            if was_expanded:
                self._notify_area_preview(None)
