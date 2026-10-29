"""Die Formularfelder des Aktionsformulars, je Aktionsart eine Baumethode.

Aus `action_editor.py` herausgeloest; `action_editor` reicht die oeffentlichen
Klassen weiter.

Form fields of the action form, one builder method per action kind.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox

from ..common import *
from ..summary import action_kind_label, action_params_summary
from ..style import (ACTION_CATEGORY_COLOR, ACTION_SECTION_COLOR, CONDITION_SECTION_COLOR,
                     IF_LOOP_COLOR, SURFACE1, apply_role, tint_button_stylesheet, tint_stylesheet)


class _FelderMixin:
    """Baut die Eingabefelder; wird von ActionInlineForm geerbt."""

    def _baue_custom_und_allgemein(self, ctx):
        diff_values = self._diff_values
        # custom: dynamisches Parameterformular je Designer-Definition
        # custom: dynamic parameter form per designer definition
        self.custom_box = QWidget()
        self.custom_form = QFormLayout(self.custom_box)
        self.custom_form.setContentsMargins(0, 0, 0, 0)
        self.custom_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self._custom_widgets = {}
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

    def _baue_mining(self, ctx):
        diff_values = self._diff_values
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

    def _baue_zielanzahl(self, ctx):
        diff_values = self._diff_values
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

    @staticmethod
    def _mk_spin():
        # Ohne Auf/Ab-Pfeile: schmaler; Werte per Tastatur oder Mausrad bei Fokus.
        # Without up/down arrows: narrower; edit via keyboard or wheel when focused.
        s = QSpinBox(); s.setRange(0, 1023)
        s.setButtonSymbols(QAbstractSpinBox.NoButtons)
        s.setMinimumWidth(36)
        return s

    def _mk_rect_row(self, spins, pick_field, tooltip):
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

    def _baue_wellen_und_gruppen(self, ctx):
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


        self.idle_x, self.idle_y = self._mk_spin(), self._mk_spin()
        self.idle_x2, self.idle_y2 = self._mk_spin(), self._mk_spin()
        self.idle_rect_w = self._mk_rect_row(
            (self.idle_x, self.idle_y, self.idle_x2, self.idle_y2),
            "idle_rect", tr("action_editor.tooltip_pick_idle_rect"))
        self.stage_x, self.stage_y = self._mk_spin(), self._mk_spin()
        self.stage_x2, self.stage_y2 = self._mk_spin(), self._mk_spin()
        self.staging_rect_w = self._mk_rect_row(
            (self.stage_x, self.stage_y, self.stage_x2, self.stage_y2),
            "staging_rect", tr("action_editor.tooltip_pick_staging_rect"))
        self.attack_x, self.attack_y = self._mk_spin(), self._mk_spin()
        self.attack_x2, self.attack_y2 = self._mk_spin(), self._mk_spin()
        self.attack_rect_w = self._mk_rect_row(
            (self.attack_x, self.attack_y, self.attack_x2, self.attack_y2),
            "attack_rect", tr("action_editor.tooltip_pick_attack_rect"))

    def _baue_befehle(self, ctx):
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
        self.cmd_x, self.cmd_y = self._mk_spin(), self._mk_spin()
        self.cmd_x2, self.cmd_y2 = self._mk_spin(), self._mk_spin()
        self.cmd_rect_w = self._mk_rect_row(
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
        # Produkt fuer den Produktionsbefehl (Inhalt haengt am Fabriktyp).
        # Product for the produce command (contents depend on factory type).
        self.produce_item = QComboBox()
        self.produce_item.currentIndexChanged.connect(self._save)
        self._fill_unit_commands()
        # Ziel-Einheit fuer den Reparieren-Befehl / target unit for repair
        self.cmd_unit_target = QComboBox()
        self.cmd_unit_target.addItem(tr("action_editor.loop_ref_current"), "<loop>")
        self.cmd_unit_target.addItem(tr("action_editor.loop_ref_outer"), "<loop:outer>")
        for name, mid in (ctx.get("named_units") or [] if isinstance(ctx, dict) else []):
            self.cmd_unit_target.addItem(f"{name} ({mid.replace('map', '')})", name)

    def _baue_patrouille_und_wellen(self, ctx):
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
        self.patrol_x = self._mk_spin()
        self.patrol_y = self._mk_spin()
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

    def _baue_listen_einheiten_bauten(self, ctx):
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
        self.cu_x, self.cu_y = self._mk_spin(), self._mk_spin()
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
        self.rb_x, self.rb_y = self._mk_spin(), self._mk_spin()
        self.building_list_tree = QTreeWidget()
        self.building_list_tree.setHeaderLabels([tr("action_editor.col_building"), tr("action_editor.col_cargo"), "X", "Y", tr("action_editor.col_name")])
        self.building_list_tree.setRootIsDecorated(False)
        self.building_list_tree.setMaximumHeight(110)
        rb_add_btn = QPushButton("+"); rb_add_btn.setFixedWidth(28)
        rb_add_btn.clicked.connect(self._rb_add)
        rb_rm_btn = QPushButton("−"); rb_rm_btn.setFixedWidth(28)
        rb_rm_btn.clicked.connect(self._rb_remove)
        rb_pick_btn = QPushButton("📍"); rb_pick_btn.setFixedWidth(28)
        rb_pick_btn.setToolTip(tr("action_editor.tooltip_pick_mine"))
        rb_pick_btn.clicked.connect(lambda: self._request_pick("primary"))
        self.rb_name = QLineEdit()
        self.rb_name.setPlaceholderText(tr("action_editor.ph_rb_name"))
        self.rb_name.setToolTip(tr("action_editor.tooltip_rb_name"))
        rb_row = QHBoxLayout()
        rb_row.addWidget(self.rb_building, 3)
        rb_row.addWidget(self.rb_weapon, 2)
        rb_row.addWidget(self.rb_x, 1)
        rb_row.addWidget(self.rb_y, 1)
        rb_row.addWidget(self.rb_name, 2)
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
        self.rt_x, self.rt_y = self._mk_spin(), self._mk_spin()
        self.rt_x2, self.rt_y2 = self._mk_spin(), self._mk_spin()
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
        self.rw_x, self.rw_y = self._mk_spin(), self._mk_spin()
        self.rw_x2, self.rw_y2 = self._mk_spin(), self._mk_spin()
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

    def _baue_moral_musik_werte(self, ctx):
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

    def _baue_reparatur_und_bedingung(self, ctx):
        diff_values = self._diff_values
        # --- repairBuildings v2: Zonenliste + Schwellenliste + Standard ---
        # repairBuildings v2: zone list + threshold list + default
        self.rz_x, self.rz_y = QSpinBox(), QSpinBox()
        self.rz_x2, self.rz_y2 = QSpinBox(), QSpinBox()
        for w in (self.rz_x, self.rz_y, self.rz_x2, self.rz_y2):
            w.setRange(0, 1023)
        self.repair_zones_tree = QTreeWidget()
        self.repair_zones_tree.setHeaderLabels(["X1", "Y1", "X2", "Y2"])
        self.repair_zones_tree.setRootIsDecorated(False)
        self.repair_zones_tree.setMaximumHeight(90)
        rz_pick_btn = QPushButton("📍"); rz_pick_btn.setFixedWidth(28)
        rz_pick_btn.setToolTip(tr("action_editor.tooltip_pick_repair_zone"))
        rz_pick_btn.clicked.connect(lambda: self._request_pick("repair_zone"))
        rz_add_btn = QPushButton("+"); rz_add_btn.setFixedWidth(28)
        rz_add_btn.clicked.connect(self._rz_add)
        rz_rm_btn = QPushButton("−"); rz_rm_btn.setFixedWidth(28)
        rz_rm_btn.clicked.connect(self._rz_remove)
        rz_row = QHBoxLayout()
        for w in (self.rz_x, self.rz_y, self.rz_x2, self.rz_y2):
            rz_row.addWidget(w, 1)
        rz_row.addWidget(rz_pick_btn)
        rz_row.addWidget(rz_add_btn)
        rz_row.addWidget(rz_rm_btn)
        self.repair_zones_editor = QWidget()
        self.repair_zones_editor.setToolTip(tr("action_editor.tooltip_repair_zones"))
        rz_lay = QVBoxLayout(self.repair_zones_editor)
        rz_lay.setContentsMargins(0, 0, 0, 0)
        rz_lay.addWidget(self.repair_zones_tree)
        rz_lay.addLayout(rz_row)

        self.rth_building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.rth_building.addItem(d, m)
        self.rth_damage = QSpinBox()
        self.rth_damage.setRange(1, 100000)
        self.rth_damage.setValue(200)
        self.repair_thresholds_tree = QTreeWidget()
        self.repair_thresholds_tree.setHeaderLabels(
            [tr("action_editor.col_building"), tr("action_editor.col_damage")])
        self.repair_thresholds_tree.setRootIsDecorated(False)
        self.repair_thresholds_tree.setMaximumHeight(90)
        rth_add_btn = QPushButton("+"); rth_add_btn.setFixedWidth(28)
        rth_add_btn.clicked.connect(self._rth_add)
        rth_rm_btn = QPushButton("−"); rth_rm_btn.setFixedWidth(28)
        rth_rm_btn.clicked.connect(self._rth_remove)
        rth_row = QHBoxLayout()
        rth_row.addWidget(self.rth_building, 2)
        rth_row.addWidget(self.rth_damage, 1)
        rth_row.addWidget(rth_add_btn)
        rth_row.addWidget(rth_rm_btn)
        self.repair_thresholds_editor = QWidget()
        self.repair_thresholds_editor.setToolTip(tr("action_editor.tooltip_repair_thresholds"))
        rth_lay = QVBoxLayout(self.repair_thresholds_editor)
        rth_lay.setContentsMargins(0, 0, 0, 0)
        rth_lay.addWidget(self.repair_thresholds_tree)
        rth_lay.addLayout(rth_row)

        # --- addVictory/addDefeat: eingebettetes Bedingungsformular ---
        # (dasselbe Formular wie im Sieg&Niederlage-Panel; Karten-Pick-Buttons
        # aus, weil die Aktion in einer Karte steckt, die sich beim Pick neu
        # aufbauen wuerde)
        # --- addVictory/addDefeat: embedded condition form (same form as the
        # victory&defeat panel; map-pick buttons off because the action lives
        # in a card that would rebuild during the pick) ---
        from ..condition_form import ConditionFormWidget
        self.cond_editor = ConditionFormWidget(
            diff_values=diff_values, show_pick_buttons=False)
        cond_groups = [name for name, _t in
                       (ctx.get("all_command_groups") or [] if isinstance(ctx, dict) else [])]
        cond_units = list(ctx.get("named_units") or [] if isinstance(ctx, dict) else [])
        self.cond_editor.set_context(cond_groups, cond_units)
        self.cond_editor.changed.connect(self._save)
