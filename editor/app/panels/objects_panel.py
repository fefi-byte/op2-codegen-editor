from __future__ import annotations

from ..common import *


# Kategorie-Filter: Anzeige-Key -> PlacedObject.kind
# Category filter: display key -> PlacedObject.kind
_KIND_FILTERS = [
    ("objects.filter_all", None),
    ("objects.filter_structures", "structure"),
    ("objects.filter_vehicles", "vehicle"),
    ("objects.filter_beacons", "beacon"),
    ("objects.filter_walls", "wall"),
]


class ObjectsPanel(QWidget):
    """Sortierbare Liste aller platzierten Objekte mit Filter & Suche.

    Sortable list of all placed objects with filter & search. Clicking a row
    centers the map on the object and flashes a highlight; double-click opens
    the object editor.
    """

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._highlight_item = None

        lay = QVBoxLayout(self)

        # --- Filterzeile / filter row ---
        filter_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("objects.search_placeholder"))
        self.search.textChanged.connect(self.refresh)
        filter_row.addWidget(self.search, 1)
        lay.addLayout(filter_row)

        combos = QHBoxLayout()
        self.kind_combo = QComboBox()
        for key, kind in _KIND_FILTERS:
            self.kind_combo.addItem(tr(key), kind)
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        combos.addWidget(self.kind_combo, 1)

        self.player_combo = QComboBox()
        self.player_combo.addItem(tr("objects.filter_all_players"), None)
        self.player_combo.currentIndexChanged.connect(self.refresh)
        combos.addWidget(self.player_combo, 1)
        lay.addLayout(combos)

        # --- Tabelle / table ---
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            tr("objects.col_name"), tr("objects.col_type"),
            tr("objects.col_player"), tr("objects.col_pos"),
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        lay.addWidget(self.table, 1)

        self.count_lbl = QLabel("")
        lay.addWidget(self.count_lbl)

    # ------------------------------------------------------------------
    def refresh(self, *_args):
        """Tabelle aus window.objects neu befuellen (Filter beruecksichtigt).

        Refill the table from window.objects (applying active filters)."""
        objects = self._window.objects
        # Spieler-Filter aktualisieren ohne die Auswahl zu verlieren
        # Update the player filter without losing the selection
        current_player = self.player_combo.currentData()
        players_present = sorted({o.player for o in objects})
        self.player_combo.blockSignals(True)
        self.player_combo.clear()
        self.player_combo.addItem(tr("objects.filter_all_players"), None)
        for p in players_present:
            self.player_combo.addItem(f"P{p}", p)
        idx = self.player_combo.findData(current_player)
        self.player_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.player_combo.blockSignals(False)

        kind = self.kind_combo.currentData()
        player = self.player_combo.currentData()
        needle = self.search.text().strip().lower()

        rows = []
        for oi, o in enumerate(objects):
            if kind is not None and o.kind != kind:
                continue
            if player is not None and o.player != player:
                continue
            label = f"{o.unit_name} {o.display}".lower()
            if needle and needle not in label:
                continue
            rows.append((oi, o))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, (oi, o) in enumerate(rows):
            name_item = QTableWidgetItem(o.unit_name or "—")
            name_item.setData(Qt.UserRole, oi)
            type_item = QTableWidgetItem(o.display)
            player_item = QTableWidgetItem(f"P{o.player}" if o.kind in ("structure", "vehicle") else "—")
            pos_item = QTableWidgetItem(f"{o.tile_x:4d},{o.tile_y:4d}")
            for c, item in enumerate((name_item, type_item, player_item, pos_item)):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.count_lbl.setText(tr("objects.count", shown=len(rows), total=len(objects)))

    # ------------------------------------------------------------------
    def _selected_object(self):
        row_items = self.table.selectedItems()
        if not row_items:
            return None
        oi = self.table.item(row_items[0].row(), 0).data(Qt.UserRole)
        objects = self._window.objects
        if oi is None or not (0 <= oi < len(objects)):
            return None
        return objects[oi]

    def _on_selection(self):
        obj = self._selected_object()
        if obj is None:
            return
        w = self._window
        w.view.centerOn(obj.tile_x * SCENE_TILE, obj.tile_y * SCENE_TILE)
        self._flash_highlight(obj)

    def _on_double_click(self, _item):
        obj = self._selected_object()
        if obj is not None:
            self._window._edit_object_at(obj.tile_x, obj.tile_y)

    def _flash_highlight(self, obj):
        """Kurzer Blink-Rahmen um das Objekt auf der Karte.

        Brief flashing frame around the object on the map."""
        self._clear_highlight()
        fw, fh = obj.footprint
        x0 = (obj.tile_x - fw // 2) * SCENE_TILE
        y0 = (obj.tile_y - fh // 2) * SCENE_TILE
        rect = QGraphicsRectItem(x0 - 4, y0 - 4, fw * SCENE_TILE + 8, fh * SCENE_TILE + 8)
        rect.setPen(QPen(QColor(255, 255, 255), 3, Qt.DashLine))
        rect.setZValue(1200)
        self._window.scene.addItem(rect)
        self._highlight_item = rect
        QTimer.singleShot(1500, self._clear_highlight)

    def _clear_highlight(self):
        if self._highlight_item is not None:
            try:
                self._window.scene.removeItem(self._highlight_item)
            except RuntimeError:
                pass  # Szene wurde neu aufgebaut / scene was rebuilt
            self._highlight_item = None
