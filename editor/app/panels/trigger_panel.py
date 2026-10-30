from __future__ import annotations
from collections import defaultdict

from PySide6.QtWidgets import QSplitter

from ..common import *
from ..dialogs.triggers import UnitChecksWidget
from ..dialogs.action_editor import ActionListWidget
from ..style import apply_role


class TriggerPanel(QWidget):
    map_pick_requested = Signal(dict)

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._idx = -1
        self._loading = False

        # --- Trigger-Liste (links) ---
        self.tlist = QTreeWidget()
        self.tlist.setHeaderHidden(True)
        self.tlist.currentItemChanged.connect(self._on_item_changed)
        add_btn = QPushButton(tr("triggers.btn_add_trigger"))
        add_btn.clicked.connect(self._add)
        apply_role(add_btn, "primary")
        rm_btn = QPushButton(tr("triggers.btn_remove_trigger"))
        rm_btn.clicked.connect(self._remove)
        apply_role(rm_btn, "danger")
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        list_lbl = QLabel(tr("triggers.lbl_trigger_list"))
        list_lbl.setProperty("role", "section")
        left_lay.addWidget(list_lbl)
        left_lay.addWidget(self.tlist, 1)
        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rm_btn)
        left_lay.addLayout(btn_row)

        # --- Bedingung-Felder ---
        self.name = QLineEdit()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(tr("triggers.folder_placeholder"))
        self.comment = QLineEdit()
        self.comment.setPlaceholderText(tr("triggers.comment_placeholder"))
        self.at_start = QCheckBox(tr("triggers.chk_at_start"))
        self.one_shot = QCheckBox(tr("triggers.chk_one_shot"))
        self.cond = QComboBox()
        fill_combo(self.cond, TRIGGER_CONDITIONS, "trigger_conditions")
        self.cond.currentIndexChanged.connect(self._update_cond_fields)
        self.player = QSpinBox()
        self.player.setRange(0, 5)
        self.marks = ExprEdit()
        self.marks.setValue(100)
        self.marks.setPlaceholderText("z.B. 600 oder ceil(600 * diff / 10)")
        self.count = QSpinBox()
        self.count.setRange(0, 1000)
        self.count.setValue(1)
        self.compare = QComboBox()
        self.compare.addItems(COMPARE.keys())
        self.tech_id = QSpinBox()
        self.tech_id.setRange(0, 20000)
        self.resource = QComboBox()
        self.resource.addItems(RESOURCES.keys())
        self.amount = QSpinBox()
        self.amount.setRange(0, 1000000)
        self.amount.setValue(1000)
        self.building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.building.addItem(d, m)
        self.x = QSpinBox()
        self.x.setRange(0, 1023)
        self.y = QSpinBox()
        self.y.setRange(0, 1023)
        self.width = QSpinBox()
        self.width.setRange(1, 256)
        self.width.setValue(4)
        self.height = QSpinBox()
        self.height.setRange(1, 256)
        self.height.setValue(4)
        # attacked/damaged: ueberwachte Gruppe; damaged: Zerstoerungs-Anteil.
        # attacked/damaged: watched group; damaged: destruction fraction.
        self.trigger_group = QComboBox()
        self.damage_type = QComboBox()
        fill_combo(self.damage_type, DAMAGE_TYPES, "damage_types")
        # specialTarget/unitDied: benannte Einheit; specialTarget: Scanner-Typ.
        # specialTarget/unitDied: named unit; specialTarget: scanner type.
        self.target_unit = QComboBox()
        self.source_unit_type = QComboBox()
        for d, m, *_ in VEHICLES:
            self.source_unit_type.addItem(d, m)
        sidx = self.source_unit_type.findData("mapScout")
        if sidx >= 0:
            self.source_unit_type.setCurrentIndex(sidx)
        # vehicleCargo/escape: Fahrzeugtyp + (nach Typ gefilterte) Ladung.
        # vehicleCargo/escape: vehicle type + (type-filtered) cargo.
        self.unit_type = QComboBox()
        for d, m in VEHICLE_UNITS:
            self.unit_type.addItem(d, m)
        self.unit_type.currentIndexChanged.connect(self._update_cargo_options)
        self.cargo = QComboBox()

        self.form = QFormLayout()
        self.form.addRow(tr("triggers.lbl_name"), self.name)
        self.form.addRow(tr("triggers.lbl_folder"), self.folder)
        # Farbe: nur fuer die Uebersicht in der Gliederung.
        # Colour: only for orientation in the outline.
        from ..style import TRIGGER_FARBEN
        self.farbe = QComboBox()
        self.farbe.addItem(tr("triggers.color_none"), "")
        for key, hexwert in TRIGGER_FARBEN.items():
            pm = QPixmap(12, 12)
            pm.fill(QColor(hexwert))
            self.farbe.addItem(QIcon(pm), tr(f"triggers.color_{key}"), key)
        self.form.addRow(tr("triggers.lbl_color"), self.farbe)
        self.form.addRow(tr("triggers.lbl_comment"), self.comment)
        self.form.addRow(self.at_start)
        self.form.addRow(self.one_shot)
        self.form.addRow(tr("triggers.lbl_condition"), self.cond)
        self._cond_rows = {
            "player": self.player, "marks": self.marks, "count": self.count,
            "compare": self.compare, "tech_id": self.tech_id, "resource": self.resource,
            "amount": self.amount, "building": self.building,
            "x": self.x, "y": self.y, "width": self.width, "height": self.height,
            "trigger_group": self.trigger_group, "damage_type": self.damage_type,
            "target_unit": self.target_unit, "source_unit_type": self.source_unit_type,
            "unit_type": self.unit_type, "cargo": self.cargo,
        }
        clabels = {
            "player": tr("triggers.lbl_player"), "marks": tr("triggers.lbl_marks"),
            "count": tr("triggers.lbl_count"), "compare": tr("triggers.lbl_compare"),
            "tech_id": tr("triggers.lbl_tech_id"), "resource": tr("triggers.lbl_resource"),
            "amount": tr("triggers.lbl_amount"), "building": tr("triggers.lbl_building"),
            "x": tr("triggers.lbl_x"), "y": tr("triggers.lbl_y"),
            "width": tr("triggers.lbl_width"), "height": tr("triggers.lbl_height"),
            "trigger_group": tr("triggers.lbl_group"),
            "damage_type": tr("triggers.lbl_damage_type"),
            "target_unit": tr("triggers.lbl_target_unit"),
            "source_unit_type": tr("triggers.lbl_source_unit_type"),
            "unit_type": tr("triggers.lbl_unit_type"), "cargo": tr("triggers.lbl_cargo"),
        }
        for key, w in self._cond_rows.items():
            self.form.addRow(clabels[key], w)

        self.name.textChanged.connect(self._store_current)
        self.name.editingFinished.connect(self.umbenennen_nachziehen)
        self.folder.textChanged.connect(self._store_current)
        self.farbe.currentIndexChanged.connect(self._store_current)
        self.at_start.toggled.connect(lambda *_: self.ablauf_auffrischen())
        self.comment.textChanged.connect(self._store_current)
        self.folder.editingFinished.connect(self._refresh_list)
        for w in (self.cond, self.compare, self.resource, self.building,
                  self.trigger_group, self.damage_type, self.target_unit,
                  self.source_unit_type, self.unit_type, self.cargo):
            w.currentIndexChanged.connect(self._store_current)
        for w in (self.player, self.count, self.tech_id, self.amount,
                  self.x, self.y, self.width, self.height):
            w.valueChanged.connect(self._store_current)
        self.marks.valueChanged.connect(self._store_current)
        for w in (self.at_start, self.one_shot):
            w.toggled.connect(self._store_current)

        # --- Bedingungsformular ---
        cond_inner = QWidget()
        cond_inner.setMinimumWidth(0)
        cond_layout = QVBoxLayout(cond_inner)
        cond_layout.addLayout(self.form)
        self.unit_checks_container = QWidget()
        self.unit_checks_layout = QVBoxLayout(self.unit_checks_container)
        self.unit_checks_layout.setContentsMargins(0, 0, 0, 0)
        self.unit_checks_widget = None
        cond_layout.addWidget(self.unit_checks_container)
        self.unit_checks_container.setVisible(False)
        # Zusaetzliche Bedingungen (UND/ODER) -- gelten zusaetzlich zum
        # Ausloeser. / Extra conditions on top of the trigger condition.
        self.zusatz_box = QWidget()
        zl = QVBoxLayout(self.zusatz_box)
        zl.setContentsMargins(0, 6, 0, 0)
        zt = QLabel(tr("triggers.lbl_extra"))
        zt.setProperty("role", "section")
        zl.addWidget(zt)
        zh = QLabel(tr("triggers.hint_extra"))
        zh.setWordWrap(True)
        zh.setProperty("secondary", "true")
        zl.addWidget(zh)
        self.zusatz_layout = QVBoxLayout()
        zl.addLayout(self.zusatz_layout)
        self.zusatz_widget = None
        cond_layout.addWidget(self.zusatz_box)
        cond_layout.addStretch(1)
        cond_scroll = QScrollArea()
        cond_scroll.setWidgetResizable(True)
        cond_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cond_scroll.setWidget(cond_inner)
        # Aufgeklappt nicht zu einem Schlitz zusammendruecken lassen, wenn
        # darunter viele Aktionen offen sind (Name/Ausloeser halb verdeckt).
        # Keep the expanded section from being squeezed to a sliver.
        cond_scroll.setMinimumHeight(250)

        cond_section = QWidget()
        cs_lay = QVBoxLayout(cond_section)
        cs_lay.setContentsMargins(0, 4, 0, 0)
        cs_lay.setSpacing(2)
        cs_lay.addWidget(cond_scroll)

        # --- Aktionsliste ---
        act_widget = QWidget()
        act_layout = QVBoxLayout(act_widget)
        act_layout.setContentsMargins(0, 4, 0, 0)
        act_layout.setSpacing(2)
        self.act_scroll = QScrollArea()
        self.act_scroll.setWidgetResizable(True)
        act_layout.addWidget(self.act_scroll)

        # Bedingung und Aktionen als eigene Tabs statt gestapelter Bereiche --
        # dadurch bekommt die jeweils aktive Ansicht (v.a. die Aktionsliste)
        # deutlich mehr Hoehe.
        # Condition and actions as separate tabs instead of stacked sections --
        # this gives whichever view is active (especially the action list)
        # much more vertical space.
        # Bedingung als einklappbare Kopfzeile ueber der Aktionsliste statt als
        # zweite Tab-Ebene: die Aktionen sind der Hauptinhalt und sofort
        # sichtbar, die Bedingung steht als Zusammenfassung darueber.
        # Condition as a collapsible header above the action list instead of a
        # second tab level: the actions are the main content and visible right
        # away, with the condition summarised above them.
        self.cond_toggle = QPushButton()
        self.cond_toggle.setCheckable(True)
        self.cond_toggle.setChecked(False)
        self.cond_toggle.toggled.connect(self._toggle_condition)
        cond_section.setVisible(False)
        self._cond_section = cond_section

        act_title = QLabel(tr("triggers.lbl_section_actions"))
        act_title.setProperty("role", "section")

        # Hinweis statt einer Wand ausgegrauter Felder, solange kein Trigger
        # gewaehlt ist. Gehoert NICHT in die einklappbare Bedingungssektion --
        # dort waere er im Leerzustand selbst unsichtbar.
        # A hint instead of a wall of greyed-out fields while no trigger is
        # selected. It must NOT live inside the collapsible condition section
        # -- there it would itself be invisible in the empty state.
        self.empty_hint = QLabel(tr("triggers.no_selection"))
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setProperty("secondary", "true")
        self.empty_hint.setContentsMargins(4, 6, 4, 6)

        detail = QWidget()
        d_lay = QVBoxLayout(detail)
        d_lay.setContentsMargins(0, 0, 0, 0)
        d_lay.setSpacing(2)
        d_lay.addWidget(self.empty_hint)
        d_lay.addWidget(self.cond_toggle)
        d_lay.addWidget(cond_section)
        # Bei vielen verschachtelten Wenn-Bloecken: alle auf einmal ein- oder
        # ausklappen. / Collapse or expand all if blocks at once.
        # Ablaufleiste: wer startet/beendet diesen Trigger, wen startet/
        # beendet er? Klick springt dorthin.
        # Flow strip: who starts/stops this trigger, whom does it start/stop.
        self.ablauf = QLabel("")
        self.ablauf.setWordWrap(True)
        self.ablauf.setTextFormat(Qt.RichText)
        self.ablauf.setStyleSheet(
            "QLabel { background: #1e1e2e; border: 1px solid #313244; border-radius: 4px;"
            " padding: 4px 6px; color: #a6adc8; }")
        self.ablauf.linkActivated.connect(self._ablauf_klick)
        self.ablauf.hide()
        d_lay.addWidget(self.ablauf)
        act_kopf = QHBoxLayout()
        act_kopf.addWidget(act_title)
        act_kopf.addStretch(1)
        for schl, zu in (("triggers.btn_blocks_collapse", True),
                         ("triggers.btn_blocks_expand", False)):
            b = QPushButton(tr(schl))
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, z=zu: self.bloecke_setzen(z))
            act_kopf.addWidget(b)
        d_lay.addLayout(act_kopf)
        d_lay.addWidget(act_widget, 1)

        self._listenteil = left
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(left)
        splitter.addWidget(detail)
        splitter.setSizes([150, 450])
        self._update_cond_header()

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(splitter)

        self._set_form_enabled(False)

    # --- Öffentliche API ---

    def als_editor(self, an: bool) -> None:
        """Im neuen Layout: nur das Formular zeigen, die Liste steht links in
        der Missionsgliederung. / Show the form only; the list lives in the
        mission outline."""
        self._listenteil.setVisible(not an)
        if an:
            # Doppelklick auf einen Trigger: Name und Ausloeser gleich zeigen.
            self.cond_toggle.setChecked(True)

    def load(self):
        self._idx = -1
        self._refresh_list()
        if self._window.triggers:
            self._select_idx(0)
        else:
            self._set_form_enabled(False)

    def refresh(self):
        self._refresh_list()

    def _struktur_geaendert(self):
        """Aktionen hinzugefuegt/verschoben/geloescht: Validierung, Overlays
        und Ablaufleiste nachziehen."""
        self._window._refresh_overview()
        self.ablauf_auffrischen()

    def _aktionen_neu_aufbauen(self):
        """Aktionsbaum neu aufbauen und die Scrollposition behalten."""
        bar = self.act_scroll.verticalScrollBar()
        pos = bar.value()
        self.refresh_actions()
        QTimer.singleShot(0, lambda: bar.setValue(pos))

    def ablauf_auffrischen(self):
        """Verweise von und zu diesem Trigger als Links anzeigen."""
        triggers = self._window.triggers
        if not (0 <= self._idx < len(triggers)):
            self.ablauf.hide()
            return
        t = triggers[self._idx]

        def alle(aktionen):
            for a in aktionen or []:
                yield a
                yield from alle(getattr(a, "then_actions", None))
                yield from alle(getattr(a, "else_actions", None))

        index = {}
        for i, x in enumerate(triggers):
            index.setdefault(x.name, i)

        def link(name):
            i = index.get(name)
            if i is None:
                return f"<span style='color:#f38ba8'>{name} ?</span>"
            return f"<a style='color:#89b4fa' href='trigger:{i}'>{name}</a>"

        gestartet_von = [x.name for x in triggers if x is not t and any(
            a.kind == "createTrigger" and a.target == t.name for a in alle(x.actions))]
        beendet_von = [x.name for x in triggers if x is not t and any(
            a.kind == "stopTrigger" and a.target == t.name for a in alle(x.actions))]
        startet = list(dict.fromkeys(a.target for a in alle(t.actions)
                                     if a.kind == "createTrigger" and a.target))
        beendet = list(dict.fromkeys(a.target for a in alle(t.actions)
                                     if a.kind == "stopTrigger" and a.target))
        zeilen = []
        quelle = [tr("triggers.flow_at_start")] if t.enabled_at_start else []
        quelle += [link(n) for n in gestartet_von]
        zeilen.append(tr("triggers.flow_started_by") + " " +
                      (", ".join(quelle) if quelle else
                       "<span style='color:#f9e2af'>" + tr("triggers.flow_never") + "</span>"))
        if startet:
            zeilen.append(tr("triggers.flow_starts") + " " + ", ".join(link(n) for n in startet))
        if beendet:
            zeilen.append(tr("triggers.flow_stops") + " " + ", ".join(link(n) for n in beendet))
        if beendet_von:
            zeilen.append(tr("triggers.flow_stopped_by") + " " + ", ".join(link(n) for n in beendet_von))
        self.ablauf.setText("<br>".join(zeilen))
        self.ablauf.show()

    def _ablauf_klick(self, href: str):
        if href.startswith("trigger:"):
            self._window._zu_trigger_springen(int(href.split(":", 1)[1]))

    def refresh_actions(self, expand_index: int = -1):
        if 0 <= self._idx < len(self._window.triggers):
            self._window.clear_action_area_preview()
            t = self._window.triggers[self._idx]
            w = ActionListWidget(t.actions, self._action_ctx())
            self.act_scroll.setWidget(w)
            if expand_index >= 0:
                w.expand_index(expand_index)

    def select(self, idx, action_idx=-1):
        self._select_idx(idx)

    # --- Interne Hilfsmethoden ---

    def _diff_values(self):
        ds = self._window.diff_setup
        if ds and hasattr(ds, 'hard'):
            return (ds.hard, ds.normal, ds.easy)
        return None

    def _action_ctx(self):
        w = self._window
        # setTargCount ist eine Group-Basismethode -- gilt fuer alle drei
        # Gruppentypen, nicht nur BuildingGroup.
        # setTargCount is a base Group method -- applies to all three group
        # types, not just BuildingGroup.
        target_group_types = {
            **{g.name: "BuildingGroup" for g in w.building_groups},
            **{g.name: "ReinforceGroup" for g in w.reinforce_groups},
            **{g.name: "FightGroup" for g in w.fight_groups},
        }
        target_groups = list(w.building_groups) + list(w.reinforce_groups) + list(w.fight_groups)
        all_groups = (
            [(g.name, "BuildingGroup") for g in w.building_groups]
            + [(g.name, "ReinforceGroup") for g in w.reinforce_groups]
        )
        # FightGroups sind jetzt vordefinierte Gruppen (Gruppen-Panel), keine
        # spontanen Wellen-Gruppen mehr -- direkt aus w.fight_groups lesen.
        # FightGroups are now predefined groups (Groups panel), no more
        # ad-hoc wave groups -- read directly from w.fight_groups.
        wave_groups = [g.name for g in w.fight_groups]
        # Alle befehligbaren Gruppen mit Typ (fuer den Gruppen-Befehl)
        # All commandable groups with their type (for the group command)
        all_command_groups = (
            [(g.name, "FightGroup") for g in w.fight_groups]
            + [(g.name, "BuildingGroup") for g in w.building_groups]
            + [(g.name, "ReinforceGroup") for g in w.reinforce_groups]
        )
        # Benannte platzierte Einheiten (fuer den Einheiten-Befehl)
        # Named placed units (for the unit command)
        named_units = [(o.unit_name, o.map_id) for o in w.objects
                       if getattr(o, "unit_name", "")]
        custom_actions = [dict(d) for d in getattr(w, "custom_actions", [])]
        # Platzierte Mine-/Smelter-Gebaeude (fuer die Mine-/Smelter-Auswahl der
        # startMining-Aktion -- Bequemlichkeit statt X/Y-Koordinaten eintippen).
        # Placed mine/smelter buildings (for startMining's mine/smelter picker
        # -- convenience instead of typing X/Y coordinates).
        mine_objects = [o for o in w.objects
                        if o.map_id in ("mapCommonOreMine", "mapRareOreMine")]
        smelter_objects = [o for o in w.objects
                           if o.map_id in ("mapCommonOreSmelter", "mapRareOreSmelter")]
        return {
            "triggers": w.triggers,
            "wave_groups": wave_groups,
            "fight_groups": wave_groups,
            "all_command_groups": all_command_groups,
            "named_units": named_units,
            "custom_actions": custom_actions,
            "building_groups": w.building_groups,
            "reinforce_groups": w.reinforce_groups,
            "fight_group_specs": w.fight_groups,
            "mining_groups": w.mining_groups,
            "mine_objects": mine_objects,
            "smelter_objects": smelter_objects,
            "target_groups": target_groups,
            "target_group_types": target_group_types,
            "all_groups": all_groups,
            "on_map_pick": self._on_action_map_pick,
            "on_area_preview": self._on_area_preview,
            "on_struktur": self._struktur_geaendert,
            "neu_aufbauen": self._aktionen_neu_aufbauen,
            "variables": w.variables,
            "diff_values": self._diff_values(),
        }

    def _on_area_preview(self, action):
        """Bereiche der aufgeklappten Aktion auf der Karte zeigen (None = weg).

        Show the expanded action's areas on the map (None = clear)."""
        w = self._window
        if action is None:
            w.clear_action_area_preview()
        else:
            w.show_action_area_preview(action)

    def _on_action_map_pick(self, action, field: str):
        triggers = self._window.triggers
        action_index = -1
        if 0 <= self._idx < len(triggers):
            try:
                action_index = triggers[self._idx].actions.index(action)
            except ValueError:
                action_index = -1
        kind = "lava_paint" if field == "lava_zone" else "action_field"
        self.map_pick_requested.emit({
            "kind": kind,
            "trigger_index": self._idx,
            "action_index": action_index,
            "action": action,
            "field": field,
        })

    def _set_form_enabled(self, on):
        for w in list(self._cond_rows.values()) + [
            self.name, self.folder, self.comment, self.at_start, self.one_shot,
            self.cond
        ]:
            w.setEnabled(on)
        # Ohne Auswahl gar nicht erst anzeigen: 18 leere Felder sagen nichts,
        # ein Satz schon.
        # Without a selection don't show them at all: 18 empty fields say
        # nothing, one sentence does.
        for w in (self.name, self.folder, self.comment, self.at_start,
                  self.one_shot, self.cond):
            self.form.setRowVisible(w, on)
        self.empty_hint.setVisible(not on)
        if on:
            self._update_cond_fields()
        else:
            for w in self._cond_rows.values():
                self.form.setRowVisible(w, False)
            self.unit_checks_container.setVisible(False)
            # Aktionsliste leeren -- der Hinweis oben erklaert den Zustand.
            # Clear the action list -- the hint above explains the state.
            self.act_scroll.setWidget(QWidget())
        self._update_cond_header()

    def _toggle_condition(self, on):
        self._cond_section.setVisible(bool(on))
        self._update_cond_header()

    def _update_cond_header(self):
        """Kopfzeile der Bedingung: Pfeil + Zusammenfassung des Triggers.

        Condition header: arrow + summary of the current trigger."""
        arrow = "▾" if self.cond_toggle.isChecked() else "▸"
        title = tr("triggers.lbl_section_condition")
        if 0 <= self._idx < len(self._window.triggers):
            n_extra = len(getattr(self._window.triggers[self._idx], "extra_conditions", None) or [])
            extra = ("  " + tr("triggers.extra_count", n=n_extra)) if n_extra else ""
            self.cond_toggle.setText(f"{arrow}  {title}:  {self.cond.currentText()}{extra}")
            self.cond_toggle.setEnabled(True)
        else:
            self.cond_toggle.setText(f"{arrow}  {title}")
            self.cond_toggle.setEnabled(False)

    def _refresh_list(self):
        triggers = self._window.triggers
        self.tlist.blockSignals(True)
        prev_idx = self._idx
        self.tlist.clear()

        folder_order = []
        by_folder = defaultdict(list)
        for i, t in enumerate(triggers):
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
                font = f_item.font(0)
                font.setBold(True)
                f_item.setFont(0, font)
                self.tlist.addTopLevelItem(f_item)
                f_item.setExpanded(True)
            else:
                f_item = None
            for i in indices:
                t = triggers[i]
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
        elif prev_idx >= 0 and not triggers:
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
        item = find_in(self.tlist.invisibleRootItem())
        if item:
            self.tlist.setCurrentItem(item)

    def _zusatz_laden(self, t):
        from ..dialogs.action_cards import ConditionListWidget
        if self.zusatz_widget is not None:
            self.zusatz_layout.removeWidget(self.zusatz_widget)
            self.zusatz_widget.deleteLater()
        panel = self

        class _Adapter:
            """Bietet dem Bedingungs-Widget die Felder eines Wenn-Blocks."""
            @property
            def conditions(self):
                return t.extra_conditions

            @property
            def condition_logic(self):
                return t.extra_logic

            @condition_logic.setter
            def condition_logic(self, wert):
                t.extra_logic = wert
                panel._window._refresh_overview()

        class _Liste(ConditionListWidget):
            def rebuild(self):
                super().rebuild()
                if getattr(self, "_fertig", False):
                    panel._window._refresh_overview()
                    panel._update_cond_header()

        w = _Liste(_Adapter(), ctx=self._action_ctx(), button_color=None)
        w._fertig = True
        # Verknuepfung erst ab zwei Bedingungen, hier in eigener Zeile.
        zeile = QHBoxLayout()
        zeile.addWidget(w.logic)
        zeile.addStretch(1)
        halter = QWidget()
        hl = QVBoxLayout(halter)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addLayout(zeile)
        hl.addWidget(w)
        self.zusatz_widget = halter
        self.zusatz_layout.addWidget(halter)

    def bloecke_setzen(self, zu: bool):
        from ..dialogs.action_cards import ActionCard
        w = self.act_scroll.widget()
        if w is None:
            return
        for karte in w.findChildren(ActionCard):
            karte.setze_block(zu)
            if zu:
                karte.collapse()

    def umbenennen_nachziehen(self):
        """Neuer Triggername -> createTrigger-Aktionen mitziehen (nach der
        Eingabe, nicht je Tastendruck). / Follow a rename in createTrigger."""
        triggers = self._window.triggers
        if not (0 <= self._idx < len(triggers)):
            return
        alt = getattr(self, "_name_alt", "")
        neu = triggers[self._idx].name
        if not alt or alt == neu:
            return
        andere = [t.name for j, t in enumerate(triggers) if j != self._idx]
        if alt not in andere and neu not in andere:
            self._window._trigger_umbenennen(alt, neu)
        self._name_alt = neu

    def _on_item_changed(self, current, previous):
        self.umbenennen_nachziehen()
        if current is None:
            self._idx = -1
            self._set_form_enabled(False)
            return
        idx = current.data(0, Qt.UserRole)
        if idx is None:
            self._idx = -1
            self._set_form_enabled(False)
            return
        # Waehrend des Umschaltens keine Stores zulassen: Signale der noch mit
        # den ALTEN Werten gefuellten Widgets wuerden sonst den NEUEN Trigger
        # ueberschreiben (self._idx zeigt bereits auf ihn).
        # Block stores while switching: signals from widgets still holding the
        # OLD values would otherwise overwrite the NEW trigger (self._idx
        # already points at it).
        self._loading = True
        self._set_form_enabled(True)
        self._idx = idx
        self._load(idx)

    def _add(self):
        triggers = self._window.triggers
        name = f"Trigger{len(triggers) + 1}"
        triggers.append(TriggerDef(name=name))
        self._window._refresh_overview()
        self._refresh_list()
        self._select_idx(len(triggers) - 1)

    def _remove(self):
        triggers = self._window.triggers
        if not (0 <= self._idx < len(triggers)):
            return
        old_idx = self._idx
        del triggers[self._idx]
        self._idx = -1
        self._window._refresh_overview()
        self._refresh_list()
        if triggers:
            self._select_idx(min(old_idx, len(triggers) - 1))
        else:
            self._set_form_enabled(False)

    def _load(self, i):
        triggers = self._window.triggers
        t = triggers[i]
        self._name_alt = t.name
        self._loading = True
        dv = self._diff_values()
        if dv:
            # set_diff_values loest valueChanged aus -> muss im Guard laufen
            # set_diff_values emits valueChanged -> must run inside the guard
            self.marks.set_diff_values(*dv)
        self.name.setText(t.name)
        self.folder.setText(getattr(t, 'folder', '') or '')
        self.comment.setText(getattr(t, 'comment', '') or '')
        self.at_start.setChecked(t.enabled_at_start)
        self.one_shot.setChecked(t.one_shot)
        label = {v[0]: k for k, v in TRIGGER_CONDITIONS.items()}.get(t.condition, "Zeit (Marks)")
        self.cond.setCurrentIndex(self.cond.findData(label))
        self.player.setValue(t.player)
        self.marks.setValue(t.marks if t.marks is not None else 100)
        self.count.setValue(t.count)
        self.compare.setCurrentText({v: k for k, v in COMPARE.items()}.get(t.compare, "≥"))
        self.tech_id.setValue(t.tech_id)
        self.resource.setCurrentText({v: k for k, v in RESOURCES.items()}.get(t.resource, "Common Ore"))
        self.amount.setValue(t.amount)
        bidx = self.building.findData(t.building)
        if bidx >= 0:
            self.building.setCurrentIndex(bidx)
        self.x.setValue(t.x)
        self.y.setValue(t.y)
        self.width.setValue(t.width)
        self.height.setValue(t.height)
        # Gruppen-/Einheiten-Combos frisch befuellen (Gruppen/benannte
        # Einheiten koennen sich seit dem letzten Laden geaendert haben).
        # Repopulate group/unit combos (groups/named units may have changed
        # since the last load).
        w = self._window
        self.trigger_group.clear()
        for g in (list(w.fight_groups) + list(w.building_groups)
                  + list(w.reinforce_groups) + list(w.mining_groups)):
            self.trigger_group.addItem(g.name, g.name)
        gidx = self.trigger_group.findData(getattr(t, "group_name", "") or "")
        if gidx >= 0:
            self.trigger_group.setCurrentIndex(gidx)
        self.target_unit.clear()
        for o in w.objects:
            uname = getattr(o, "unit_name", "") or ""
            if uname:
                self.target_unit.addItem(f"{uname} ({o.map_id})", uname)
        uidx = self.target_unit.findData(getattr(t, "target_unit", "") or "")
        if uidx >= 0:
            self.target_unit.setCurrentIndex(uidx)
        didx = self.damage_type.findData(
            {v: k for k, v in DAMAGE_TYPES.items()}.get(int(getattr(t, "damage_type", 3) or 3)))
        if didx >= 0:
            self.damage_type.setCurrentIndex(didx)
        sidx = self.source_unit_type.findData(getattr(t, "source_unit_type", "mapScout") or "mapScout")
        if sidx >= 0:
            self.source_unit_type.setCurrentIndex(sidx)
        utidx = self.unit_type.findData(getattr(t, "unit_type", "mapCargoTruck") or "mapCargoTruck")
        if utidx >= 0:
            self.unit_type.setCurrentIndex(utidx)
        self._update_cargo_options()
        cidx = self.cargo.findData(getattr(t, "cargo", "mapAny") or "mapAny")
        if cidx >= 0:
            self.cargo.setCurrentIndex(cidx)
        if self.unit_checks_widget is not None:
            self.unit_checks_layout.removeWidget(self.unit_checks_widget)
            self.unit_checks_widget.deleteLater()
            self.unit_checks_widget = None
        self.unit_checks_widget = UnitChecksWidget(t.unit_checks)
        self.unit_checks_layout.addWidget(self.unit_checks_widget)
        fi = self.farbe.findData(getattr(t, "color", "") or "")
        self.farbe.setCurrentIndex(max(0, fi))
        self._zusatz_laden(t)
        self._loading = False
        self._update_cond_fields()
        self._update_cond_header()
        self._window.clear_action_area_preview()
        self.act_scroll.setWidget(ActionListWidget(t.actions, self._action_ctx()))
        self.ablauf_auffrischen()

    def _store_current(self):
        triggers = self._window.triggers
        if self._loading or not (0 <= self._idx < len(triggers)):
            return
        t = triggers[self._idx]
        t.name = self.name.text() or f"Trigger{self._idx + 1}"
        t.folder = self.folder.text().strip()
        t.color = self.farbe.currentData() or ""
        t.comment = self.comment.text().strip()
        t.enabled_at_start = self.at_start.isChecked()
        t.one_shot = self.one_shot.isChecked()
        t.condition = TRIGGER_CONDITIONS[self.cond.currentData()][0]
        t.player = self.player.value()
        t.marks = self.marks.value()
        t.count = self.count.value()
        t.compare = COMPARE[self.compare.currentText()]
        t.tech_id = self.tech_id.value()
        t.resource = RESOURCES[self.resource.currentText()]
        t.amount = self.amount.value()
        t.building = self.building.currentData()
        t.x = self.x.value()
        t.y = self.y.value()
        t.width = self.width.value()
        t.height = self.height.value()
        t.group_name = self.trigger_group.currentData() or ""
        t.damage_type = DAMAGE_TYPES.get(self.damage_type.currentData(), 3)
        t.target_unit = self.target_unit.currentData() or ""
        t.source_unit_type = self.source_unit_type.currentData() or "mapScout"
        t.unit_type = self.unit_type.currentData() or "mapCargoTruck"
        t.cargo = self.cargo.currentData() or "mapAny"
        item = self.tlist.currentItem()
        if item and item.data(0, Qt.UserRole) is not None:
            item.setText(0, trigger_summary(t))
        self._update_cond_header()
        self._window._refresh_overview()

    def _update_cargo_options(self):
        """Ladung-Auswahl auf den gewaehlten Fahrzeugtyp zuschneiden (vehicleCargo/escape)."""
        self.cargo.clear()
        for label, value in condition_cargo_items(self.unit_type.currentData()):
            self.cargo.addItem(label, value)
        self.cargo.setEnabled(self.cargo.count() > 1)

    def _update_cond_fields(self):
        fields = TRIGGER_CONDITIONS[self.cond.currentData()][1]
        for key, w in self._cond_rows.items():
            self.form.setRowVisible(w, key in fields)
        self.unit_checks_container.setVisible("unit_checks" in fields)
