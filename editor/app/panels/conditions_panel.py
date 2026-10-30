"""Seitenpanel "Sieg & Niederlage": Bedingungen anlegen, bearbeiten, sortieren.

Ersetzt den frueheren modalen ConditionsDialog. Aenderungen im Formular werden
sofort in die ausgewaehlte Bedingung geschrieben (Live-Speichern wie im
Trigger-Panel); point/rect/escape koennen direkt auf der Karte gepickt werden.

Side panel "Victory & Defeat": create, edit and order conditions. Replaces
the former modal ConditionsDialog. Form edits are written into the selected
condition immediately (live-save like the trigger panel); point/rect/escape
can be picked directly on the map.
"""
from __future__ import annotations

from PySide6.QtWidgets import QSplitter

from ..common import *
from ..condition_form import ConditionFormWidget
from ..style import apply_role


class ConditionsPanel(QWidget):
    map_pick_requested = Signal(dict)

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._loading = False
        self._current = None   # ("win"|"lose", index) | None

        # --- Liste (oben): zwei Wurzeln Sieg / Niederlage ---
        # --- list (top): two roots victory / defeat ---
        and_hint = QLabel(tr("conditions_panel.and_hint"))
        and_hint.setWordWrap(True)
        and_hint.setStyleSheet("color: #6c7086; font-size: 9pt;")

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._on_item_changed)

        add_win = QPushButton(tr("conditions_panel.btn_add_win"))
        add_win.clicked.connect(lambda: self._add("win"))
        apply_role(add_win, "primary")
        add_lose = QPushButton(tr("conditions_panel.btn_add_lose"))
        add_lose.clicked.connect(lambda: self._add("lose"))
        rm_btn = QPushButton(tr("conditions_panel.btn_remove"))
        rm_btn.clicked.connect(self._remove)
        apply_role(rm_btn, "danger")
        swap_btn = QPushButton(tr("conditions_panel.btn_swap"))
        swap_btn.setToolTip(tr("conditions_panel.tooltip_swap"))
        swap_btn.clicked.connect(self._swap_side)
        up_btn = QPushButton("↑")
        up_btn.setFixedWidth(28)
        up_btn.setToolTip(tr("conditions_panel.tooltip_order"))
        up_btn.clicked.connect(lambda: self._move(-1))
        dn_btn = QPushButton("↓")
        dn_btn.setFixedWidth(28)
        dn_btn.setToolTip(tr("conditions_panel.tooltip_order"))
        dn_btn.clicked.connect(lambda: self._move(1))

        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.addWidget(and_hint)
        top_lay.addWidget(self.tree, 1)
        row1 = QHBoxLayout()
        row1.addWidget(add_win)
        row1.addWidget(add_lose)
        row1.addWidget(rm_btn)
        top_lay.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(swap_btn, 1)
        row2.addWidget(up_btn)
        row2.addWidget(dn_btn)
        top_lay.addLayout(row2)

        # --- Formular (unten) ---
        # --- form (bottom) ---
        self.cond_form = ConditionFormWidget(diff_values=self._diff_values())
        self.cond_form.changed.connect(self._store_current)
        self.cond_form.pick_requested.connect(self._on_pick_requested)
        form_inner = QWidget()
        fi_lay = QVBoxLayout(form_inner)
        fi_lay.setContentsMargins(0, 0, 0, 0)
        fi_lay.addWidget(self.cond_form)
        fi_lay.addStretch(1)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        form_scroll.setWidget(form_inner)

        self._listenteil = top
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top)
        splitter.addWidget(form_scroll)
        splitter.setSizes([220, 380])

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(splitter)

        self.cond_form.setEnabled(False)

    # --- Oeffentliche API / public API ---

    def als_editor(self, an: bool) -> None:
        """Im neuen Layout: nur das Formular zeigen, die Liste steht links in
        der Missionsgliederung. / Show the form only; the list lives in the
        mission outline."""
        self._listenteil.setVisible(not an)

    def load(self):
        """Panel-Inhalt aus dem Fensterzustand neu aufbauen."""
        self._current = None
        self._refresh_context()
        self._refresh_tree()
        first = self._first_selectable()
        if first is not None:
            self._select(first[0], first[1])
        else:
            self.cond_form.setEnabled(False)

    def refresh(self):
        self._refresh_tree()

    def reload_current(self):
        """Nach einem Karten-Pick: Formular aus der Bedingung neu laden."""
        if self._current is None:
            return
        side, idx = self._current
        data = self._list(side)
        if 0 <= idx < len(data):
            self._loading = True
            self.cond_form.load(data[idx])
            self._loading = False
            self._refresh_tree()
            self._select(side, idx)

    # --- Intern / internal ---

    def _diff_values(self):
        ds = getattr(self._window, "diff_setup", None)
        if ds is not None and hasattr(ds, "hard"):
            return (ds.hard, ds.normal, ds.easy)
        return None

    def _list(self, side):
        return self._window.victories if side == "win" else self._window.defeats

    def _refresh_context(self):
        w = self._window
        group_names = [g.name for g in (list(w.fight_groups) + list(w.building_groups)
                                        + list(w.reinforce_groups) + list(w.mining_groups))]
        named_units = [(o.unit_name, o.map_id) for o in w.objects
                       if getattr(o, "unit_name", "")]
        self.cond_form.set_context(group_names, named_units)

    def _refresh_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._win_root = QTreeWidgetItem([tr("conditions_panel.win_root")])
        self._lose_root = QTreeWidgetItem([tr("conditions_panel.lose_root")])
        for root, side in ((self._win_root, "win"), (self._lose_root, "lose")):
            for i, c in enumerate(self._list(side)):
                it = QTreeWidgetItem([condition_summary(c)])
                it.setData(0, Qt.UserRole, (side, i))
                root.addChild(it)
        self.tree.addTopLevelItem(self._win_root)
        self.tree.addTopLevelItem(self._lose_root)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _first_selectable(self):
        if self._window.victories:
            return ("win", 0)
        if self._window.defeats:
            return ("lose", 0)
        return None

    def _select(self, side, idx):
        root = self._win_root if side == "win" else self._lose_root
        if 0 <= idx < root.childCount():
            self.tree.setCurrentItem(root.child(idx))

    def _on_item_changed(self, item, _prev):
        data = item.data(0, Qt.UserRole) if item is not None else None
        if data is None:
            # Wurzel angeklickt -> Formular deaktivieren, Auswahl behalten.
            # Root clicked -> disable the form, keep the selection.
            self._current = None
            self.cond_form.setEnabled(False)
            return
        side, idx = data
        conds = self._list(side)
        if not (0 <= idx < len(conds)):
            return
        self._current = (side, idx)
        self._loading = True
        self._refresh_context()
        self.cond_form.load(conds[idx])
        # Niederlagen brauchen keine Beschreibung (Engine ignoriert sie).
        # Defeats need no description (the engine ignores it).
        self.cond_form.set_objective_visible(side == "win")
        self._loading = False
        self.cond_form.setEnabled(True)

    def _store_current(self):
        if self._loading or self._current is None:
            return
        side, idx = self._current
        conds = self._list(side)
        if not (0 <= idx < len(conds)):
            return
        self.cond_form.apply_to(conds[idx])
        # Listenlabel aktualisieren ohne Neuaufbau (Selektion bleibt).
        # Update the list label without a rebuild (selection stays).
        root = self._win_root if side == "win" else self._lose_root
        if idx < root.childCount():
            root.child(idx).setText(0, condition_summary(conds[idx]))
        self._window._refresh_overview()

    def _add(self, side):
        cond = (Condition(kind="time", marks=600) if side == "win"
                else Condition(kind="noCC", player=0))
        self._list(side).append(cond)
        self._refresh_tree()
        self._select(side, len(self._list(side)) - 1)
        self._window._refresh_overview()

    def _remove(self):
        if self._current is None:
            return
        side, idx = self._current
        conds = self._list(side)
        if not (0 <= idx < len(conds)):
            return
        del conds[idx]
        self._current = None
        self._refresh_tree()
        if conds:
            self._select(side, min(idx, len(conds) - 1))
        else:
            self.cond_form.setEnabled(False)
        self._window._refresh_overview()

    def _swap_side(self):
        """Ausgewaehlte Bedingung zwischen Sieg und Niederlage verschieben."""
        if self._current is None:
            return
        side, idx = self._current
        src = self._list(side)
        if not (0 <= idx < len(src)):
            return
        cond = src.pop(idx)
        other = "lose" if side == "win" else "win"
        self._list(other).append(cond)
        self._current = None
        self._refresh_tree()
        self._select(other, len(self._list(other)) - 1)
        self._window._refresh_overview()

    def _move(self, delta):
        if self._current is None:
            return
        side, idx = self._current
        conds = self._list(side)
        j = idx + delta
        if not (0 <= idx < len(conds)) or not (0 <= j < len(conds)):
            return
        conds[idx], conds[j] = conds[j], conds[idx]
        self._current = None
        self._refresh_tree()
        self._select(side, j)
        self._window._refresh_overview()

    def _on_pick_requested(self, mode: str):
        """"point"/"rect" vom Formular -> Pick-Request ans Hauptfenster."""
        if self._current is None:
            return
        side, idx = self._current
        conds = self._list(side)
        if not (0 <= idx < len(conds)):
            return
        # Erst den aktuellen Formularstand sichern, dann auf der Karte picken.
        # Persist the current form state first, then pick on the map.
        self.cond_form.apply_to(conds[idx])
        self.map_pick_requested.emit({
            "kind": "cond_field",
            "field": mode,          # "point" | "rect"
            "cond": conds[idx],
        })
