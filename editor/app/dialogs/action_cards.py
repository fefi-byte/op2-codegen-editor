"""Karten-Ansicht: Bedingungslisten, Aktionslisten und die Aktionskarte.

Aus `action_editor.py` herausgeloest; `action_editor` reicht die oeffentlichen
Klassen weiter.

Card view: condition lists, action lists and the action card.
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
)
from .condition_dialog import ConditionEditDialog
from .action_form import ActionInlineForm


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
        # Restplatz unten aufsaugen: Karten behalten ihre natuerliche Hoehe,
        # statt auf die volle Panelhoehe auseinandergezogen zu werden.
        # Soak up leftover space below: cards keep their natural height
        # instead of being stretched across the full panel height.
        self.box.addStretch(1)
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
        for gkey, kinds in ACTION_MENU_GROUPS.items():
            sub = menu.addMenu(tr(f"action_groups.{gkey}"))
            for k in kinds:
                sub.addAction(tr(f"action_kinds.{k}")).setData(k)
        # Designer-Aktionen als eigenes Untermenue (dynamisch aus dem Kontext)
        # Designer actions as their own submenu (dynamic from the context)
        custom_defs = (self.ctx.get("custom_actions") or []
                       if isinstance(self.ctx, dict) else [])
        if custom_defs:
            sub = menu.addMenu(tr("action_groups.custom"))
            for d in custom_defs:
                if d.get("name"):
                    sub.addAction(d["name"]).setData(("custom", d["name"]))
        picked = menu.exec(QCursor.pos())
        if picked is None:
            return
        k = picked.data()
        if isinstance(k, tuple):
            self.actions.append(TriggerAction(kind="custom", custom_name=k[1]))
            self.rebuild(expand_last=True)
            return
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

        # Autoren-Kommentar der Aktion auch auf der zugeklappten Karte zeigen.
        # Show the action's author comment on the collapsed card as well.
        self._comment_lbl = QLabel("")
        self._comment_lbl.setWordWrap(True)
        self._comment_lbl.setStyleSheet(
            "color: #a6adc8; font-style: italic; font-size: 10pt; padding: 0 2px 0 6px;")
        lay.addWidget(self._comment_lbl)
        self._refresh_comment()

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

    def _refresh_comment(self):
        c = (getattr(self.a, "comment", "") or "").strip()
        self._comment_lbl.setText(f"💬 {c}" if c else "")
        self._comment_lbl.setVisible(bool(c))

    def _on_form_changed(self):
        if self._det is not None:
            self._det.setText(action_params_summary(self.a))
        self._refresh_comment()
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
