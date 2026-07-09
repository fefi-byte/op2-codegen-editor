from __future__ import annotations

from ..common import *
from ..validation import validate_mission


class ValidationPanel(QWidget):
    """Live-Warnliste: zeigt Missionprobleme, Doppelklick springt zum Problem.

    Live warning list: shows mission problems; double-click jumps to the
    problem's editor."""

    def __init__(self, window):
        super().__init__()
        self._window = window

        lay = QVBoxLayout(self)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.itemDoubleClicked.connect(self._on_activate)
        lay.addWidget(self.list, 1)
        self.status_lbl = QLabel("")
        lay.addWidget(self.status_lbl)

    def refresh(self):
        findings = validate_mission(self._window)
        self.list.clear()
        errors = sum(1 for s, _, _ in findings if s == "error")
        warnings = len(findings) - errors
        for severity, text, target in findings:
            icon = "🛑" if severity == "error" else "⚠️"
            item = QTreeWidgetItem([f"{icon} {text}"])
            item.setData(0, Qt.UserRole, target)
            if severity == "error":
                item.setForeground(0, QBrush(QColor(243, 139, 168)))
            else:
                item.setForeground(0, QBrush(QColor(249, 226, 175)))
            self.list.addTopLevelItem(item)
        if not findings:
            ok = QTreeWidgetItem([tr("validation.all_ok")])
            ok.setForeground(0, QBrush(QColor(166, 227, 161)))
            self.list.addTopLevelItem(ok)
        self.status_lbl.setText(tr("validation.status", e=errors, w=warnings))

    def _on_activate(self, item, _col=0):
        target = item.data(0, Qt.UserRole)
        if not target:
            return
        kind, index = target
        w = self._window
        if kind == "trigger":
            w._pending_trigger_index = index if index is not None else 0
            w._pending_action_index = -1
            w.edit_triggers()
        elif kind == "player":
            w.edit_players()
        elif kind == "group":
            w.edit_groups()
        elif kind == "conditions":
            w.edit_conditions()
        elif kind == "object" and index is not None and 0 <= index < len(w.objects):
            o = w.objects[index]
            w.view.centerOn(o.tile_x * SCENE_TILE, o.tile_y * SCENE_TILE)
