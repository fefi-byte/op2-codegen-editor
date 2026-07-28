"""Liste der Gelaendemerkmale fuer den Kartengenerator.

Der Seed wuerfelt die ganze Karte. Merkmale sind der Gegenpol: eine grobe
Beschreibung dessen, was vorkommen soll -- ein Tal, ein Berg, eine Freiflaeche
fuer die Basis -- mit Lage im 3x3-Raster und Groesse. Bewusst grob: es geht
darum, den Zufall zu lenken, nicht die Karte von Hand zu malen.

List of terrain features for the map generator. The seed rolls the whole map;
features are the counterweight: a rough description of what should be there --
a valley, a mountain, a clearing for the base -- with a position in a 3x3 grid
and a size. Deliberately coarse: the point is to steer the randomness, not to
paint the map by hand.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSlider, QCheckBox

from ..common import *

import mapgen

# Reihenfolge bestimmt die Knopfreihe.
# Order determines the row of buttons.
KINDS = [mapgen.FEAT_TAL, mapgen.FEAT_BERG, mapgen.FEAT_PLATEAU,
         mapgen.FEAT_FREI, mapgen.FEAT_ENGE]

# Sektoren im Uhrzeigersinn, wie sie im Auswahlfeld erscheinen sollen.
# Sectors clockwise, in the order they should appear in the combo box.
SECTORS = ["", "nw", "n", "no", "w", "c", "o", "sw", "s", "so"]


class FeatureList(QWidget):
    """Liste + Editor fuer das ausgewaehlte Merkmal."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[mapgen.Feature] = []
        self._laden = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self.list = QListWidget()
        self.list.setMaximumHeight(96)
        self.list.currentRowChanged.connect(self._on_select)
        root.addWidget(self.list)

        add_row = QHBoxLayout()
        add_row.setSpacing(2)
        for kind in KINDS:
            btn = QPushButton(tr(f"newmap.feat_{kind}"))
            btn.setToolTip(tr(f"newmap.feat_{kind}_hint"))
            btn.clicked.connect(lambda _=False, k=kind: self._add(k))
            add_row.addWidget(btn)
        root.addLayout(add_row)

        self.remove_btn = QPushButton(tr("newmap.feat_remove"))
        self.remove_btn.clicked.connect(self._remove)
        root.addWidget(self.remove_btn)

        # Editor fuer das ausgewaehlte Merkmal -- ausgeblendet, solange nichts
        # ausgewaehlt ist, damit die Seitenleiste nicht mit toten Feldern
        # zugestellt ist.
        # Editor for the selected feature -- hidden while nothing is selected
        # so the sidebar is not cluttered with dead fields.
        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.setContentsMargins(0, 4, 0, 0)

        self.where = QComboBox()
        self.to = QComboBox()
        for combo in (self.where, self.to):
            for key in SECTORS:
                combo.addItem(tr(f"newmap.sector_{key or 'any'}"), key)
            combo.currentIndexChanged.connect(self._on_edit)
        form.addRow(tr("newmap.feat_where"), self.where)
        self.to_label = QLabel(tr("newmap.feat_to"))
        form.addRow(self.to_label, self.to)

        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(0, 100)
        self.size.setValue(50)
        self.size.valueChanged.connect(self._on_edit)
        form.addRow(tr("newmap.feat_size"), self.size)

        self.lava = QCheckBox(tr("newmap.feat_lava"))
        self.lava.setToolTip(tr("newmap.feat_lava_hint"))
        self.lava.toggled.connect(self._on_edit)
        form.addRow("", self.lava)

        root.addWidget(self.editor)
        self._update_editor()

    # ------------------------------------------------------------------
    def features(self) -> list:
        return list(self._items)

    def set_features(self, features: list) -> None:
        self._items = [f for f in features if f.kind in KINDS]
        self._refill()

    # ------------------------------------------------------------------
    def _add(self, kind: str) -> None:
        vorgabe = {"tal": ("w", "o"), "enge": ("n", "s")}.get(kind, ("c", ""))
        self._items.append(mapgen.Feature(kind=kind, where=vorgabe[0],
                                          to=vorgabe[1], size=0.5))
        self._refill()
        self.list.setCurrentRow(len(self._items) - 1)
        self.changed.emit()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self._items):
            del self._items[row]
            self._refill()
            self.changed.emit()

    def _refill(self) -> None:
        self._laden = True
        row = self.list.currentRow()
        self.list.clear()
        for feat in self._items:
            self.list.addItem(QListWidgetItem(self._beschriftung(feat)))
        if self._items:
            self.list.setCurrentRow(min(max(row, 0), len(self._items) - 1))
        self._laden = False
        self._update_editor()

    def _beschriftung(self, feat) -> str:
        teile = [tr(f"newmap.feat_{feat.kind}")]
        lage = tr(f"newmap.sector_{feat.where or 'any'}")
        if feat.kind in (mapgen.FEAT_TAL, mapgen.FEAT_ENGE):
            ziel = tr(f"newmap.sector_{feat.to or 'any'}")
            lage = f"{lage} → {ziel}"
        teile.append(lage)
        teile.append(tr("newmap.feat_size_klein") if feat.size < 0.34 else
                     tr("newmap.feat_size_gross") if feat.size > 0.66 else
                     tr("newmap.feat_size_mittel"))
        if feat.kind == mapgen.FEAT_TAL and feat.lava:
            teile.append(tr("newmap.feat_lava"))
        return " · ".join(teile)

    def _on_select(self, row: int) -> None:
        if self._laden:
            return
        self._update_editor()

    def _update_editor(self) -> None:
        row = self.list.currentRow()
        gueltig = 0 <= row < len(self._items)
        self.editor.setVisible(gueltig)
        self.remove_btn.setEnabled(gueltig)
        if not gueltig:
            return
        feat = self._items[row]
        self._laden = True
        self.where.setCurrentIndex(max(0, self.where.findData(feat.where)))
        self.to.setCurrentIndex(max(0, self.to.findData(feat.to)))
        self.size.setValue(int(round(100 * feat.size)))
        self.lava.setChecked(bool(feat.lava))
        # Zielsektor nur beim Tal und der Engstelle -- ein Berg hat keine
        # Richtung. Lava nur beim Tal.
        # Target sector only for valley and choke point -- a mountain has no
        # direction. Lava only for the valley.
        richtung = feat.kind in (mapgen.FEAT_TAL, mapgen.FEAT_ENGE)
        self.to.setVisible(richtung)
        self.to_label.setVisible(richtung)
        self.lava.setVisible(feat.kind == mapgen.FEAT_TAL)
        self._laden = False

    def _on_edit(self) -> None:
        row = self.list.currentRow()
        if self._laden or not (0 <= row < len(self._items)):
            return
        feat = self._items[row]
        feat.where = self.where.currentData() or ""
        feat.to = self.to.currentData() or ""
        feat.size = self.size.value() / 100.0
        feat.lava = self.lava.isChecked()
        self._laden = True
        self.list.item(row).setText(self._beschriftung(feat))
        self._laden = False
        self.changed.emit()
