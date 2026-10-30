"""Das Inline-Formular einer Aktion (Art waehlen, Felder, Laden/Speichern).

Aus `action_editor.py` herausgeloest; `action_editor` reicht die oeffentlichen
Klassen weiter.

Inline form of one action (kind, fields, load/save).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox

from ..common import *
from ..summary import action_kind_label, action_params_summary
from ..style import (ACTION_CATEGORY_COLOR, ACTION_SECTION_COLOR, CONDITION_SECTION_COLOR,
                     IF_LOOP_COLOR, SURFACE1, apply_role, tint_button_stylesheet, tint_stylesheet)
from .action_daten import (
    _NoWheelFilter,
    _DIALOG_KINDS,
    _GROUP_COMMANDS,
    _GROUP_COMMANDS_COMMON,
    _GROUP_COMMANDS_UNIT_TARGET,
    produce_items_for,
    unit_commands_for,
)
from .action_form_felder import _FelderMixin
from .action_form_listen import _ListenMixin


class ActionInlineForm(_FelderMixin, _ListenMixin, QWidget):
    """Inline-Formular zum Bearbeiten einer Aktion direkt in der ActionCard.

    Inline form for editing an action directly inside its ActionCard.
    Changes are written to the action object immediately on every widget change.
    """

    changed = Signal()

    pick_requested = Signal(str)  # "primary" or "secondary"

    _VIS = {
        "message": ["text", "msg_target"],
        "showDialog": ["caption", "dialog_text"],
        "customCode": ["code_editor"],
        "custom": ["custom_editor"],
        "createUnit": ["unit_editor", "player"],
        "createDisaster": ["disaster_type", "x_expr", "y_expr"],
        "createTrigger": ["target"],
        "stopTrigger": ["target"],
        "recordBuilding": ["group", "building_editor"],
        "recordTube": ["group", "tube_editor"],
        "recordWall": ["group", "wall_editor"],
        "setTargCount": ["target_group", "source_group", "priority", "targ_editor"],
        "assignToGroup": ["assign_group", "building", "x", "y", "player"],
        "modVar": ["var_name", "mod_mode", "var_expr"],
        "startMining": ["mining_group", "target_count", "mining_wait_hint"],
        "sendAttackWave": ["player", "spawn_mode", "group_var_name", "wave_editor",
                           "idle_rect_w", "staging_rect_w", "attack_rect_w", "now"],
        "fightGroupCmd": ["wave_group", "fg_command"],
        "unitCmd": ["unit_ref", "unit_command"],
        "defendArea": ["player", "x", "y", "x2", "y2"],
        "repairBuildings": ["group", "repair_zones_editor", "repair_thresholds_editor",
                            ],
        "empMissile": ["player", "x", "y", "x2", "y2"],
        "setMorale": ["morale_mode", "morale_player"],
        "setMusic": ["songs_editor", "repeat_start"],
        "lavaFlowAni": ["flow_dir", "flow_freeze", "x", "y"],
        "modUnitStats": ["stats_unit", "player", "stats_editor"],
        "addVictory": ["cond_editor"],
        "addDefeat": ["cond_editor"],
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
        self._diff_values = diff_values

        self.kind = QComboBox()
        for label, k in _DIALOG_KINDS.items():
            self.kind.addItem(tr(f"action_kinds.{k}"), k)
        self.kind.currentIndexChanged.connect(self._update)

        self.text = QLineEdit(tr("action_editor.default_message"))
        self.text.setToolTip(tr("action_editor.tooltip_text_vars"))
        # Nachricht: Zielspieler (-1 = alle)
        # Message: target player (-1 = all)
        self.msg_target = QComboBox()
        self.msg_target.addItem(tr("action_editor.msg_target_all"), -1)
        for _i in range(6):
            self.msg_target.addItem(f"P{_i}", _i)
        self.msg_target.currentIndexChanged.connect(self._save)
        # showDialog: Titel + mehrzeiliger Text
        # showDialog: caption + multi-line body
        self.caption = QLineEdit()
        self.caption.setPlaceholderText(tr("action_editor.caption_placeholder"))
        self.dialog_text = QPlainTextEdit()
        self.dialog_text.setPlaceholderText(tr("action_editor.dialog_placeholder"))
        self.dialog_text.setToolTip(tr("action_editor.tooltip_text_vars"))
        self.dialog_text.setMaximumHeight(110)
        # customCode: handgeschriebener C++-Block (Monospace)
        # customCode: hand-written C++ block (monospace)
        from ..code_editor import CodeEditor
        self.code_edit = CodeEditor(context_words=self._code_context_words())
        self.code_edit.setPlaceholderText(tr("action_editor.code_placeholder"))
        self.code_edit.setMinimumHeight(140)

        # Die Felder je Aktionsart werden in eigenen Methoden gebaut (frueher
        # ein Block von 800 Zeilen). Reihenfolge unveraendert.
        # Fields per action kind are built in separate methods; order unchanged.
        self._baue_custom_und_allgemein(ctx)
        self._baue_mining(ctx)
        self._baue_zielanzahl(ctx)
        self._baue_wellen_und_gruppen(ctx)
        self._baue_befehle(ctx)
        self._baue_patrouille_und_wellen(ctx)
        self._baue_listen_einheiten_bauten(ctx)
        self._baue_moral_musik_werte(ctx)
        self._baue_reparatur_und_bedingung(ctx)

        # Immer sichtbares, optionales Kommentarfeld (nicht in _rows, damit
        # _update es nie ausblendet).
        # Always-visible optional comment field (not in _rows, so _update
        # never hides it).
        self.comment = QLineEdit()
        self.comment.setPlaceholderText(tr("action_editor.comment_placeholder"))

        self.form = QFormLayout()
        # Label ueber dem Widget: macht die Formularspalte deutlich schmaler.
        # Label above the widget: makes the form column much narrower.
        self.form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.form.addRow(tr("action_editor.lbl_action_type"), self.kind)
        self.form.addRow(tr("action_editor.lbl_comment"), self.comment)
        self._rows = {
            "text": self.text, "unit": self.unit, "weapon": self.weapon,
            "caption": self.caption, "dialog_text": self.dialog_text,
            "msg_target": self.msg_target,
            "code_editor": self.code_edit, "custom_editor": self.custom_box,
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
            "produce_item": self.produce_item,
            "cmd_unit_target": self.cmd_unit_target, "patrol_editor": self.patrol_editor,
            "targ_editor": self.targ_editor,
            "unit_editor": self.unit_editor, "building_editor": self.building_editor,
            "tube_editor": self.tube_editor, "wall_editor": self.wall_editor,
            "repair_zones_editor": self.repair_zones_editor,
            "repair_thresholds_editor": self.repair_thresholds_editor,
            "morale_mode": self.morale_mode, "morale_player": self.morale_player,
            "songs_editor": self.songs_editor, "repeat_start": self.repeat_start,
            "flow_dir": self.flow_dir, "flow_freeze": self.flow_freeze,
            "stats_unit": self.stats_unit, "stats_editor": self.stats_editor,
            "cond_editor": self.cond_editor,
        }
        labels = {
            "text": tr("action_editor.lbl_text"), "unit": tr("action_editor.lbl_unit"),
            "caption": tr("action_editor.lbl_caption"),
            "msg_target": tr("action_editor.lbl_msg_target"),
            "dialog_text": tr("action_editor.lbl_dialog_text"),
            "code_editor": tr("action_editor.lbl_code"),
            "custom_editor": tr("action_editor.lbl_custom_params"),
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
            "produce_item": tr("action_editor.lbl_produce_item"),
            "cmd_unit_target": tr("action_editor.lbl_cmd_unit_target"),
            "patrol_editor": tr("action_editor.lbl_patrol_editor"),
            "unit_editor": tr("action_editor.lbl_unit_editor"),
            "building_editor": tr("action_editor.lbl_building_editor"),
            "tube_editor": tr("action_editor.lbl_tube_editor"),
            "wall_editor": tr("action_editor.lbl_wall_editor"),
            "repair_zones_editor": tr("action_editor.lbl_repair_zones"),
            "repair_thresholds_editor": tr("action_editor.lbl_repair_thresholds"),
            "morale_mode": tr("action_editor.lbl_morale_mode"),
            "morale_player": tr("action_editor.lbl_player"),
            "songs_editor": tr("action_editor.lbl_songs"),
            "repeat_start": tr("action_editor.lbl_repeat_start"),
            "flow_dir": tr("action_editor.lbl_flow_dir"),
            "flow_freeze": "",
            "stats_unit": tr("action_editor.lbl_unit"),
            "stats_editor": tr("action_editor.lbl_stats"),
            "cond_editor": tr("action_editor.lbl_condition"),
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

        # Schleifen-Einheit mit dem Namen, der an dieser Stelle gilt.
        # Loop-unit entries show the name valid at this spot.
        tiefe = ctx.get("foreach_tiefe", 0) if isinstance(ctx, dict) else None
        from .action_daten import schleifen_ref_text
        for cb in (getattr(self, n, None) for n in
                   ("mine_ref", "smelter_ref", "unit_ref", "cmd_unit_target")):
            if cb is None:
                continue
            for ref in ("<loop>", "<loop:outer>"):
                i = cb.findData(ref)
                if i >= 0:
                    cb.setItemText(i, schleifen_ref_text(ref, tiefe))

        # Auswahllisten nicht nach ihrem laengsten Eintrag bemessen -- sonst
        # ragen Zeilen mit mehreren Listen im Seitenbereich ueber den Rand.
        # Don't size combos by their longest entry; rows with several combos
        # would overflow the side area otherwise.
        for cb in self.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)

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

    def _current_kind(self):
        return self.kind.currentData()

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
        cur_item = self.produce_item.currentData()
        self.produce_item.blockSignals(True)
        self.produce_item.clear()
        for d, m in produce_items_for(mid):
            self.produce_item.addItem(d, m)
        j = self.produce_item.findData(cur_item)
        if j >= 0:
            self.produce_item.setCurrentIndex(j)
        self.produce_item.blockSignals(False)

    def _code_context_words(self) -> list[str]:
        """Eigene Namen fuer die Code-Vervollstaendigung: Missions-Variablen
        und Gruppennamen aus dem Kontext.

        Own names for code completion: mission variables and group names
        from the context."""
        if not isinstance(self.ctx, dict):
            return []
        words = [v.name for v in (self.ctx.get("variables") or [])]
        words += list((self.ctx.get("target_group_types") or {}).keys())
        return words

    def _custom_def(self, name):
        for d in (self.ctx.get("custom_actions") or [] if isinstance(self.ctx, dict) else []):
            if d.get("name") == name:
                return d
        return None

    def _rebuild_custom_form(self, a):
        """Parameterfelder passend zur Designer-Definition aufbauen.

        Build the parameter fields matching the designer definition."""
        while self.custom_form.rowCount():
            self.custom_form.removeRow(0)
        self._custom_widgets = {}
        if getattr(a, "kind", "") != "custom":
            return
        cdef = self._custom_def(getattr(a, "custom_name", "") or "")
        if not cdef:
            lbl = QLabel(tr("action_editor.custom_no_def",
                            name=getattr(a, "custom_name", "") or "?"))
            lbl.setWordWrap(True)
            self.custom_form.addRow(lbl)
            return
        args = getattr(a, "custom_args", None) or {}
        for p in (cdef.get("params") or []):
            pname = p.get("name", "")
            if not pname:
                continue
            ptype = p.get("type", "int")
            v = args.get(pname, p.get("default"))
            if ptype == "position":
                box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0)
                sx = QSpinBox(); sx.setRange(0, 1023)
                sy = QSpinBox(); sy.setRange(0, 1023)
                pos = v if isinstance(v, dict) else {}
                sx.setValue(int(pos.get("x", 0))); sy.setValue(int(pos.get("y", 0)))
                sx.valueChanged.connect(self._save); sy.valueChanged.connect(self._save)
                h.addWidget(sx, 1); h.addWidget(sy, 1)
                self.custom_form.addRow(f"{pname}:", box)
                self._custom_widgets[pname] = ("position", (sx, sy))
            elif ptype == "unit_type":
                cb = QComboBox()
                for d_, m_ in ALL_UNITS:
                    cb.addItem(d_, m_)
                i = cb.findData(v)
                if i >= 0:
                    cb.setCurrentIndex(i)
                cb.currentIndexChanged.connect(self._save)
                self.custom_form.addRow(f"{pname}:", cb)
                self._custom_widgets[pname] = ("unit_type", cb)
            elif ptype == "text":
                le = QLineEdit(str(v) if v is not None else "")
                le.textChanged.connect(self._save)
                self.custom_form.addRow(f"{pname}:", le)
                self._custom_widgets[pname] = ("text", le)
            else:  # int / player
                sp = QSpinBox()
                sp.setRange(0 if ptype == "player" else -1000000,
                            6 if ptype == "player" else 1000000)
                try:
                    sp.setValue(int(v))
                except (TypeError, ValueError):
                    pass
                sp.valueChanged.connect(self._save)
                self.custom_form.addRow(f"{pname}:", sp)
                self._custom_widgets[pname] = (ptype, sp)

    def _collect_custom_args(self) -> dict:
        out = {}
        for pname, (ptype, w) in self._custom_widgets.items():
            if ptype == "position":
                sx, sy = w
                out[pname] = {"x": sx.value(), "y": sy.value()}
            elif ptype == "unit_type":
                out[pname] = w.currentData() or "mapNone"
            elif ptype == "text":
                out[pname] = w.text()
            else:
                out[pname] = w.value()
        return out

    def _update_unit_commands(self):
        self._fill_unit_commands()
        self._update()
        self._save()

    def _current_disaster_type(self):
        return self.disaster_type.currentData() or "meteor"

    def _disaster_type_from_action(self, action):
        return getattr(action, "disaster_type", "meteor") or "meteor"

    def _set_kind(self, k):
        i = self.kind.findData(k)
        if i < 0:
            # Kind ist nicht im Angebot (Designer-Aktion oder Altbestand wie
            # defendArea): Eintrag nur fuer DIESE Aktion dynamisch ergaenzen,
            # damit die Anzeige stimmt.
            # Kind not on offer (designer action or legacy like defendArea):
            # add the entry dynamically for THIS action so the display is
            # correct.
            self.kind.blockSignals(True)
            self.kind.addItem(tr(f"action_kinds.{k}"), k)
            self.kind.blockSignals(False)
            i = self.kind.count() - 1
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
            elif cmd == "produce":
                # Waffe nur bei Kampffahrzeug-Fabriken sinnvoll.
                # Weapon only meaningful for combat-vehicle factories.
                mid = self._named_unit_types.get(self.unit_ref.currentData(), "")
                fields = fields + ["produce_item"]
                if mid in ("mapVehicleFactory", "mapArachnidFactory"):
                    fields = fields + ["weapon"]
            elif cmd == "launch":
                fields = fields + ["x", "y"]
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
        self.comment.setText(getattr(a, "comment", "") or "")
        self.text.setText(a.text)
        self.caption.setText(getattr(a, "caption", "") or "")
        self.dialog_text.setPlainText(a.text if a.kind == "showDialog" else "")
        self.code_edit.setPlainText(getattr(a, "code", "") or "")
        mi = self.msg_target.findData(int(getattr(a, "msg_player", -1)))
        self.msg_target.setCurrentIndex(mi if mi >= 0 else 0)
        self._rebuild_custom_form(a)
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
        # Auch die Typ-Combos der Eingabezeilen vorbelegen -- sonst springen
        # sie nach einem Karten-Pick (Formular-Neuaufbau) auf den ersten
        # Eintrag zurueck.
        # Seed the input rows' type combos too -- otherwise they jump back
        # to the first entry after a map pick (form rebuild).
        self._set_combo(self.cu_unit, a.unit_type)
        self._set_combo(self.cu_weapon, a.weapon_type)
        self._set_combo(self.rb_building, a.building_type)
        self._set_combo(self.rb_weapon, a.weapon_type)
        self._set_combo(self.rw_wall, a.wall_type)
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
            self._set_combo(self.produce_item, getattr(a, "unit_type", "") or "")
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
        self._rz_load(getattr(a, "repair_zones", None))
        self._rth_load(getattr(a, "repair_thresholds", None))
        # addVictory/addDefeat: eingebettetes Bedingungsformular befuellen.
        # addVictory/addDefeat: populate the embedded condition form.
        spec = dict(getattr(a, "condition_spec", None) or {})
        spec.setdefault("kind", "time")
        try:
            self.cond_editor.load(Condition(**spec))
        except TypeError:
            self.cond_editor.load(Condition(kind=spec.get("kind", "time")))
        self.cond_editor.set_objective_visible(a.kind != "addDefeat")
        self._loading = False
        self._update()

    def _connect_save_signals(self):
        self.text.textChanged.connect(self._save)
        self.comment.textChanged.connect(self._save)
        self.caption.textChanged.connect(self._save)
        self.dialog_text.textChanged.connect(self._save)
        self.code_edit.textChanged.connect(self._save)
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
                  self.morale_mode, self.morale_player, self.flow_dir, self.stats_unit,
                  self.cu_unit, self.cu_weapon, self.rb_building, self.rb_weapon,
                  self.rw_wall):
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
        a.comment = self.comment.text().strip()
        a.text = self.text.text()
        if k == "showDialog":
            a.text = self.dialog_text.toPlainText()
            a.caption = self.caption.text().strip()
        if k == "message":
            a.msg_player = self.msg_target.currentData()
            if a.msg_player is None:
                a.msg_player = -1
        if k == "customCode":
            a.code = self.code_edit.toPlainText()
        if k == "custom":
            a.custom_args = self._collect_custom_args()
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
            # Auswahl der Eingabezeile in den Legacy-Feldern merken, damit
            # sie den Karten-Pick-Roundtrip (Formular-Neuaufbau) ueberlebt.
            # Remember the input row's selection in the legacy fields so it
            # survives the map-pick round trip (form rebuild).
            a.unit_type = self.cu_unit.currentData() or a.unit_type
            a.weapon_type = self.cu_weapon.currentData() or "mapNone"
        elif k == "recordBuilding":
            a.building_list = self._building_list_from_tree()
            a.building_type = self.rb_building.currentData() or a.building_type
            a.weapon_type = self.rb_weapon.currentData() or "mapNone"
        elif k == "recordTube":
            a.tube_list = self._tube_list_from_tree()
        elif k == "recordWall":
            a.wall_list = self._wall_list_from_tree()
            a.wall_type = self.rw_wall.currentData() or a.wall_type
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
            if a.fg_command == "produce" and self.produce_item.currentData():
                a.unit_type = self.produce_item.currentData()
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
        elif k == "repairBuildings":
            a.repair_zones = self._rz_from_tree()
            a.repair_thresholds = self._rth_from_tree()
        elif k in ("addVictory", "addDefeat"):
            self.cond_editor.set_objective_visible(k == "addVictory")
            a.condition_spec = asdict(self.cond_editor.make())
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
