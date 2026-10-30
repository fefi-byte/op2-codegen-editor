"""Sichtbarer Rueckgaengig-Verlauf: was zurueckgenommen wuerde, auf einen Blick.

Beim Malen war schwer zu sehen, was ein Strg+Z gerade zuruecknimmt. Das Dock
"Verlauf" listet die Schritte (der neueste oben), die wiederherstellbaren
grau darunter. Ein Klick springt dorthin: alles darueber wird
zurueckgenommen bzw. wiederhergestellt.

Visible undo history: lists the steps (newest on top), redoable ones greyed
below; clicking an entry undoes or redoes up to that point.
"""
from __future__ import annotations

from .common import *


class _VerlaufMixin:
    def _build_verlauf(self):
        dock = QDockWidget(tr("window.dock_verlauf"), self)
        dock.setObjectName("dock_verlauf")
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.verlauf_liste = QListWidget()
        self.verlauf_liste.itemClicked.connect(self._verlauf_springen)
        dock.setWidget(self.verlauf_liste)
        self.verlauf_dock = dock
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        # Als Reiter neben der Uebersicht -- kein zusaetzlicher Platz.
        self.tabifyDockWidget(self.overview_dock, dock)
        self.overview_dock.raise_()
        if self._view_menu is not None:
            act = dock.toggleViewAction()
            act.setText(tr("window.dock_verlauf"))
            self._view_menu.addAction(act)
        self._verlauf_auffrischen()

    def _verlauf_text(self, op: str, obj) -> str:
        if op == "terrain":
            was = getattr(obj, "was", "") or tr("window.verlauf_gelaende")
            return tr("window.verlauf_terrain", was=was, n=len(obj.changes))
        if op == "bereich":
            x, y, w, h = obj["neu"]
            return tr("window.verlauf_bereich", name=obj["name"], x=x, y=y, w=w, h=h)
        if op == "place":
            return tr("window.verlauf_place", display=obj.display)
        return tr("window.verlauf_remove", display=obj.display)

    def _verlauf_auffrischen(self):
        liste = self.verlauf_liste
        if liste is None:
            return
        liste.clear()
        # Wiederherstellbares (grau) oben, dann die Rueckgaengig-Kette, der
        # neueste Schritt direkt unter dem Strich.
        for k, (op, obj) in enumerate(self._redo_stack or []):
            item = QListWidgetItem("↷ " + self._verlauf_text(op, obj))
            item.setForeground(QBrush(QColor(108, 112, 134)))
            item.setData(Qt.UserRole, ("redo", len(self._redo_stack) - k))
            liste.addItem(item)
        stapel = list(self._undo_stack or [])
        for k, (op, obj) in enumerate(reversed(stapel)):
            item = QListWidgetItem(self._verlauf_text(op, obj))
            if k == 0:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            item.setData(Qt.UserRole, ("undo", k))
            liste.addItem(item)
        if not stapel and not self._redo_stack:
            leer = QListWidgetItem(tr("window.verlauf_leer"))
            leer.setForeground(QBrush(QColor(108, 112, 134)))
            liste.addItem(leer)

    def _verlauf_springen(self, item):
        ziel = item.data(Qt.UserRole)
        if not ziel:
            return
        art, n = ziel
        # "undo", k: die k neueren Schritte zuruecknehmen (der angeklickte
        # bleibt stehen). "redo", n: n Schritte wiederherstellen.
        for _ in range(n):
            if art == "undo":
                self.undo()
            else:
                self.redo()
