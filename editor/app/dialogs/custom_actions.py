"""Aktions-Designer: eigene Aktionen mit Parametern und C++-Template.

Eine Designer-Aktion besteht aus Name, Parameterliste (Name, Typ, Default)
und einem C++-Code-Template; $parametername wird beim Generieren durch den
im Trigger eingestellten Wert ersetzt. Die Definitionen liegen in der
Projektdatei und erscheinen im "+ Aktion"-Menue als eigenes Untermenue.

Action designer: custom actions with parameters and a C++ template. A
designer action consists of a name, a parameter list (name, type, default)
and a C++ code template; $paramname is replaced with the value configured
in the trigger at generation time. Definitions live in the project file and
show up as their own submenu in the "+ add action" menu.
"""
from __future__ import annotations

from ..common import *

PARAM_TYPES = ["int", "text", "unit_type", "position", "player"]


class CustomActionsDialog(QDialog):
    def __init__(self, parent, defs: list[dict]):
        super().__init__(parent)
        self.setWindowTitle(tr("custom_actions.title"))
        self.resize(760, 560)
        self._defs = [dict(d, params=[dict(p) for p in (d.get("params") or [])])
                      for d in (defs or [])]
        self._loading = False

        # --- linke Seite: Liste der Definitionen ---
        self.listw = QListWidget()
        self.listw.currentRowChanged.connect(self._load_row)
        btn_add = QPushButton("+"); btn_add.setFixedWidth(28)
        btn_add.clicked.connect(self._add_def)
        btn_rm = QPushButton("−"); btn_rm.setFixedWidth(28)
        btn_rm.clicked.connect(self._remove_def)
        lbtns = QHBoxLayout(); lbtns.addWidget(btn_add); lbtns.addWidget(btn_rm)
        lbtns.addStretch(1)
        left = QVBoxLayout()
        left.addWidget(self.listw, 1)
        left.addLayout(lbtns)

        # --- rechte Seite: Definition bearbeiten ---
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._store_row)

        self.param_table = QTableWidget(0, 3)
        self.param_table.setHorizontalHeaderLabels([
            tr("custom_actions.col_name"),
            tr("custom_actions.col_type"),
            tr("custom_actions.col_default"),
        ])
        self.param_table.horizontalHeader().setStretchLastSection(True)
        self.param_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.param_table.setMaximumHeight(160)
        self.param_table.itemChanged.connect(lambda *_: self._store_row())
        p_add = QPushButton(tr("custom_actions.btn_add_param"))
        p_add.clicked.connect(self._add_param)
        p_rm = QPushButton(tr("custom_actions.btn_remove_param"))
        p_rm.clicked.connect(self._remove_param)
        pbtns = QHBoxLayout(); pbtns.addWidget(p_add); pbtns.addWidget(p_rm)
        pbtns.addStretch(1)

        self.code_edit = QPlainTextEdit()
        f = self.code_edit.font(); f.setFamily("Consolas"); f.setStyleHint(QFont.Monospace)
        self.code_edit.setFont(f)
        self.code_edit.setPlaceholderText(tr("custom_actions.code_placeholder"))
        self.code_edit.textChanged.connect(self._store_row)

        legend = QLabel(tr("custom_actions.legend"))
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray; font-size: 9pt;")

        right = QVBoxLayout()
        rform = QFormLayout()
        rform.addRow(tr("custom_actions.lbl_name"), self.name_edit)
        right.addLayout(rform)
        right.addWidget(QLabel(f"<b>{tr('custom_actions.section_params')}</b>"))
        right.addWidget(self.param_table)
        right.addLayout(pbtns)
        right.addWidget(QLabel(f"<b>{tr('custom_actions.section_code')}</b>"))
        right.addWidget(self.code_edit, 1)
        right.addWidget(legend)

        body = QHBoxLayout()
        lw = QWidget(); lw.setLayout(left); lw.setMaximumWidth(220)
        rw = QWidget(); rw.setLayout(right)
        body.addWidget(lw)
        body.addWidget(rw, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addWidget(btns)

        self._refresh_list()
        if self._defs:
            self.listw.setCurrentRow(0)
        else:
            self._set_enabled(False)

    # --- Liste ---

    def _refresh_list(self):
        self.listw.blockSignals(True)
        row = self.listw.currentRow()
        self.listw.clear()
        for d in self._defs:
            self.listw.addItem(d.get("name") or tr("custom_actions.unnamed"))
        if 0 <= row < self.listw.count():
            self.listw.setCurrentRow(row)
        self.listw.blockSignals(False)

    def _set_enabled(self, on):
        for w in (self.name_edit, self.param_table, self.code_edit):
            w.setEnabled(on)

    def _add_def(self):
        n = len(self._defs) + 1
        self._defs.append({"name": f"MeineAktion{n}", "params": [], "code": ""})
        self._refresh_list()
        self._set_enabled(True)
        self.listw.setCurrentRow(len(self._defs) - 1)

    def _remove_def(self):
        row = self.listw.currentRow()
        if 0 <= row < len(self._defs):
            del self._defs[row]
            self._refresh_list()
            if self._defs:
                self.listw.setCurrentRow(min(row, len(self._defs) - 1))
            else:
                self._loading = True
                self.name_edit.clear(); self.code_edit.clear()
                self.param_table.setRowCount(0)
                self._loading = False
                self._set_enabled(False)

    # --- Definition laden/speichern ---

    def _load_row(self, row):
        if not (0 <= row < len(self._defs)):
            return
        d = self._defs[row]
        self._loading = True
        self._set_enabled(True)
        self.name_edit.setText(d.get("name", ""))
        self.code_edit.setPlainText(d.get("code", ""))
        self.param_table.setRowCount(0)
        for p in (d.get("params") or []):
            self._append_param_row(p.get("name", ""), p.get("type", "int"),
                                   p.get("default"))
        self._loading = False

    def _append_param_row(self, name="", ptype="int", default=None):
        r = self.param_table.rowCount()
        self.param_table.insertRow(r)
        self.param_table.setItem(r, 0, QTableWidgetItem(name or f"param{r + 1}"))
        cb = QComboBox()
        for t in PARAM_TYPES:
            cb.addItem(tr(f"custom_actions.ptype_{t}"), t)
        i = cb.findData(ptype)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.currentIndexChanged.connect(lambda *_: self._store_row())
        self.param_table.setCellWidget(r, 1, cb)
        self.param_table.setItem(r, 2, QTableWidgetItem(
            "" if default is None else str(default)))

    def _add_param(self):
        self._append_param_row()
        self._store_row()

    def _remove_param(self):
        rows = {i.row() for i in self.param_table.selectedIndexes()}
        for r in sorted(rows, reverse=True):
            self.param_table.removeRow(r)
        self._store_row()

    def _store_row(self):
        if self._loading:
            return
        row = self.listw.currentRow()
        if not (0 <= row < len(self._defs)):
            return
        params = []
        for r in range(self.param_table.rowCount()):
            name_item = self.param_table.item(r, 0)
            cb = self.param_table.cellWidget(r, 1)
            def_item = self.param_table.item(r, 2)
            pname = (name_item.text().strip() if name_item else "")
            if not pname:
                continue
            params.append({
                "name": pname,
                "type": (cb.currentData() if cb else "int") or "int",
                "default": (def_item.text().strip() if def_item else ""),
            })
        self._defs[row] = {
            "name": self.name_edit.text().strip(),
            "params": params,
            "code": self.code_edit.toPlainText(),
        }
        self._refresh_list()

    @property
    def defs(self) -> list[dict]:
        self._store_row()
        return [d for d in self._defs if d.get("name")]
