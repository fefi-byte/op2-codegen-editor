"""Seitenleisten-Navigation als Schalterraster statt einreihiger Tab-Leiste.

Sechs Bereiche passen in einer Reihe nicht mehr nebeneinander -- Qt schiebt
dann Pfeiltasten ein und blendet Tabs aus. Stattdessen: ein Raster aus
Umschaltknoepfen (voreingestellt drei je Reihe) ueber einem QStackedWidget.

Die Schnittstelle ist absichtlich die eines QTabWidget (addTab,
setCurrentIndex, currentIndex, count, tabText, currentChanged), damit der
restliche Code und die Tests unveraendert bleiben.

Sidebar navigation as a button grid instead of a single-row tab bar. Six
sections no longer fit side by side -- Qt would add scroll arrows and hide
tabs. Instead: a grid of toggle buttons (three per row by default) above a
QStackedWidget. The interface deliberately mirrors QTabWidget's.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup, QGridLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .style import apply_role


class SidebarNav(QWidget):
    currentChanged = Signal(int)

    def __init__(self, columns: int = 3, parent=None):
        super().__init__(parent)
        self._columns = columns
        self._buttons: list[QPushButton] = []

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.setCurrentIndex)

        self._stack = QStackedWidget()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(self._grid)
        lay.addWidget(self._stack, 1)

    # --- QTabWidget-kompatible Schnittstelle / QTabWidget-like interface ---

    def addTab(self, widget: QWidget, text: str) -> int:
        index = self._stack.count()
        button = QPushButton(text)
        button.setCheckable(True)
        button.setChecked(index == 0)
        apply_role(button, "navtab")
        self._group.addButton(button, index)
        self._grid.addWidget(button, index // self._columns, index % self._columns)
        self._buttons.append(button)
        self._stack.addWidget(widget)
        return index

    def removeTab(self, index: int) -> None:
        """Bereich wieder entfernen (fuer Panels, die nur zeitweise da sind).

        Remove a section again (for panels that are only there temporarily)."""
        if not (0 <= index < self._stack.count()):
            return
        widget = self._stack.widget(index)
        self._stack.removeWidget(widget)
        widget.setParent(None)
        button = self._buttons.pop(index)
        self._group.removeButton(button)
        self._grid.removeWidget(button)
        button.deleteLater()
        # Raster neu aufbauen: die Positionen der Folgeknoepfe verschieben sich.
        # Rebuild the grid: the following buttons shift position.
        for i, btn in enumerate(self._buttons):
            self._group.setId(btn, i)
            self._grid.removeWidget(btn)
            self._grid.addWidget(btn, i // self._columns, i % self._columns)
        new_index = min(index, self._stack.count() - 1)
        if new_index >= 0:
            self._stack.setCurrentIndex(new_index)
            self._buttons[new_index].setChecked(True)
            self.currentChanged.emit(new_index)

    def indexOf(self, widget: QWidget) -> int:
        return self._stack.indexOf(widget)

    def setCurrentIndex(self, index: int) -> None:
        if not (0 <= index < self._stack.count()) or index == self._stack.currentIndex():
            # Auch ohne Wechsel den Knopf richtig setzen (Klick auf den
            # bereits aktiven Bereich).
            # Keep the button in sync even without a change (click on the
            # already active section).
            if 0 <= index < len(self._buttons):
                self._buttons[index].setChecked(True)
            return
        self._stack.setCurrentIndex(index)
        self._buttons[index].setChecked(True)
        self.currentChanged.emit(index)

    def currentIndex(self) -> int:
        return self._stack.currentIndex()

    def count(self) -> int:
        return self._stack.count()

    def tabText(self, index: int) -> str:
        return self._buttons[index].text() if 0 <= index < len(self._buttons) else ""

    def widget(self, index: int) -> QWidget | None:
        return self._stack.widget(index)
