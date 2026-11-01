"""Positions-Liste des Trigger-Ausloesers 'Einheit(en) an Position(en) bereit'.

Position list of the 'unit(s) ready at position(s)' trigger condition.
"""
from __future__ import annotations
from ..common import *


class UnitChecksWidget(QFrame):
    """Editor fuer eine Liste von FindUnitCheck-Eintraegen (Trigger 'findUnit').

    Jeder Eintrag ist eine Zeile: Unit-Typ, Tile-X, Tile-Y, Loesch-Knopf.
    `+ Position` haengt einen neuen Eintrag an. Aenderungen aktualisieren
    direkt das uebergebene `checks`-List-Objekt (referenziell).
    """
    def __init__(self, checks, parent=None, on_pick=None, on_change=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.checks = checks
        self._on_pick = on_pick
        self._on_change = on_change
        self._rows: list[QWidget] = []
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(tr("triggers.unit_checks_title")))
        self.list_box = QVBoxLayout()
        outer.addLayout(self.list_box)
        add_btn = QPushButton(tr("triggers.unit_checks_add"))
        add_btn.clicked.connect(self._add)
        outer.addWidget(add_btn)
        self._rebuild()

    def _rebuild(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        for i, c in enumerate(self.checks):
            self._rows.append(self._make_row(i, c))
            self.list_box.addWidget(self._rows[-1])

    def _make_row(self, idx, c):
        row = QWidget()
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
        unit = QComboBox()
        for d, m, _ in STRUCTURES:
            unit.addItem(d, m)
        bidx = unit.findData(c.unit_type)
        if bidx >= 0:
            unit.setCurrentIndex(bidx)
        unit.currentIndexChanged.connect(lambda _, i=idx, w=unit: self._set_type(i, w))
        sx = QSpinBox(); sx.setRange(0, 1023); sx.setValue(int(c.x))
        sy = QSpinBox(); sy.setRange(0, 1023); sy.setValue(int(c.y))
        sx.valueChanged.connect(lambda v, i=idx: self._set_x(i, v))
        sy.valueChanged.connect(lambda v, i=idx: self._set_y(i, v))
        rm = QPushButton("✕"); rm.setMaximumWidth(30)
        rm.clicked.connect(lambda _, i=idx: self._remove(i))
        h.addWidget(QLabel(tr("triggers.unit_checks_type"))); h.addWidget(unit, 2)
        h.addWidget(QLabel("X:")); h.addWidget(sx)
        h.addWidget(QLabel("Y:")); h.addWidget(sy)
        if callable(self._on_pick):
            pick = QPushButton("📍"); pick.setMaximumWidth(30)
            pick.setToolTip(tr("triggers.tip_pick_map"))
            pick.clicked.connect(lambda _, cc=c: self._on_pick(cc))
            h.addWidget(pick)
        h.addWidget(rm)
        return row

    def _set_type(self, i, w):
        if 0 <= i < len(self.checks):
            self.checks[i].unit_type = w.currentData() or "mapCommandCenter"

    def _set_x(self, i, v):
        if 0 <= i < len(self.checks):
            self.checks[i].x = int(v)
            if callable(self._on_change):
                self._on_change()

    def _set_y(self, i, v):
        if 0 <= i < len(self.checks):
            self.checks[i].y = int(v)
            if callable(self._on_change):
                self._on_change()

    def _add(self):
        self.checks.append(FindUnitCheck())
        self._rebuild()
        if callable(self._on_change):
            self._on_change()

    def _remove(self, i):
        if 0 <= i < len(self.checks):
            del self.checks[i]
            self._rebuild()
            if callable(self._on_change):
                self._on_change()
