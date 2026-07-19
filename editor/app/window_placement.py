from __future__ import annotations

from .common import *
from .placed_object import PlacedObject
from .dialogs.object_edit import ObjectEditDialog


class _PlacementMixin:
    # --- Undo/Redo fuer Platzieren & Loeschen ---
    # --- Undo/redo for placing & removing ---
    def _init_undo(self):
        self._undo_stack: list[tuple[str, PlacedObject]] = []
        self._redo_stack: list[tuple[str, PlacedObject]] = []

    def _push_undo(self, op: str, obj: PlacedObject):
        if not hasattr(self, "_undo_stack"):
            self._init_undo()
        self._undo_stack.append((op, obj))
        if len(self._undo_stack) > 200:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _clear_undo(self):
        if hasattr(self, "_undo_stack"):
            self._undo_stack.clear()
            self._redo_stack.clear()

    def undo(self):
        if not getattr(self, "_undo_stack", None):
            self.statusBar().showMessage(tr("window.status_nothing_to_undo"))
            return
        op, obj = self._undo_stack.pop()
        self._apply_inverse(op, obj)
        self._redo_stack.append((op, obj))

    def redo(self):
        if not getattr(self, "_redo_stack", None):
            self.statusBar().showMessage(tr("window.status_nothing_to_redo"))
            return
        op, obj = self._redo_stack.pop()
        self._apply_forward(op, obj)
        self._undo_stack.append((op, obj))

    def _apply_inverse(self, op: str, obj: PlacedObject):
        if op == "place":
            self._delete_object_silent(obj)
            self.statusBar().showMessage(tr("window.status_undo_place", display=obj.display))
        else:  # "remove" rueckgaengig -> Objekt wiederherstellen
            self._restore_object_silent(obj)
            self.statusBar().showMessage(tr("window.status_undo_remove", display=obj.display))
        self._refresh_overview()

    def _apply_forward(self, op: str, obj: PlacedObject):
        if op == "place":
            self._restore_object_silent(obj)
        else:
            self._delete_object_silent(obj)
        self._refresh_overview()

    def _delete_object_silent(self, obj: PlacedObject):
        if obj in self.objects:
            for item in obj.items:
                self.scene.removeItem(item)
            self.objects.remove(obj)

    def _restore_object_silent(self, obj: PlacedObject):
        if obj not in self.objects:
            self._draw(obj)
            self.objects.append(obj)

    def _clear_placement_preview(self):
        for item in self._placement_preview_items:
            self.scene.removeItem(item)
        self._placement_preview_items = []

    def _draw_placement_preview(self, tx, ty):
        self._clear_placement_preview()
        if not self._placement_active:
            return
        sel = self._selected()
        if not sel:
            return
        kind, display, _map_id, footprint = sel
        if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
            return
        color = WALL_COLOR
        if kind == "beacon":
            color = BEACON_COLOR
        elif kind in ("structure", "vehicle"):
            color = PLAYER_COLORS[self.player_spin.value() % len(PLAYER_COLORS)]
        footprint_w, footprint_h = footprint
        x0 = (tx - footprint_w // 2) * SCENE_TILE
        y0 = (ty - footprint_h // 2) * SCENE_TILE
        rect = QGraphicsRectItem(
            x0, y0, footprint_w * SCENE_TILE, footprint_h * SCENE_TILE)
        rect.setPen(QPen(color, 2, Qt.DashLine))
        rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 55)))
        rect.setZValue(1050)
        self.scene.addItem(rect)
        label = QGraphicsSimpleTextItem(display.split()[0][:10])
        label.setBrush(QBrush(Qt.white))
        label.setPos(x0 + 2, y0 + 1)
        label.setZValue(1051)
        self.scene.addItem(label)
        self._placement_preview_items = [rect, label]

    def _on_tile_hover(self, tx, ty):
        self.coord_label.setText(f"Tile: {tx}, {ty}")
        # Footprint-Vorschau am Cursor: auch fuer den "primary"-Pick der
        # recordBuilding-/createUnit-/assignToGroup-Formulare (dort kommt
        # der Gebaeudetyp aus der Aktion, siehe _draw_action_building_preview).
        # Footprint preview at the cursor: also for the "primary" pick of
        # the recordBuilding/createUnit/assignToGroup forms (the building
        # type comes from the action there).
        hover_building_pick = (
            self._action_pick
            and (self._action_pick["kind"] in ("recordBuilding", "assignToGroup")
                 or (self._action_pick["kind"] == "action_field"
                     and self._action_pick.get("field") == "primary"
                     and getattr(self._action_pick.get("action"), "kind", "")
                     in ("recordBuilding", "createUnit", "assignToGroup")))
        )
        if hover_building_pick:
            if self.map is not None and 0 <= tx < self.map.width and 0 <= ty < self.map.height:
                self._draw_action_building_preview(tx, ty)
            else:
                self._clear_action_preview()
            self._clear_placement_preview()
        elif self._placement_active:
            self._draw_placement_preview(tx, ty)
        else:
            self._clear_placement_preview()

    def _object_at(self, tx, ty):
        for obj in reversed(self.objects):
            if obj.covers(tx, ty):
                return obj
        return None

    def _redraw_object(self, obj: PlacedObject):
        for item in obj.items:
            self.scene.removeItem(item)
        self._draw(obj)

    def _edit_object_at(self, tx, ty):
        obj = self._object_at(tx, ty)
        if obj is None:
            return
        if obj.kind not in ("structure", "vehicle"):
            self.statusBar().showMessage(tr("window.status_no_unit_params", display=obj.display))
            return
        dlg = ObjectEditDialog(self, obj, len(self.players))
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_to(obj)
            self._redraw_object(obj)
            label = obj.unit_name or obj.display
            self.statusBar().showMessage(tr("window.status_updated", label=label))

    def on_place(self, tx, ty):
        if self._action_pick and self._action_pick.get("kind") == "lava_paint":
            self._lava_paint_add(tx, ty)
            return
        # Generischer "auf Karte setzen"-Pfad fuer Action-Felder (vom Card-Editor).
        if self._action_pick and self._action_pick["kind"] == "action_field":
            field = self._action_pick["field"]
            if field == "rect":
                return
            if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
                return
            action = self._action_pick["action"]
            if field == "primary":
                if getattr(action, "kind", "") == "createDisaster":
                    action.x_expr, action.y_expr = tx, ty
                else:
                    action.x, action.y = tx, ty
            elif field == "secondary":
                if (getattr(action, "kind", "") == "createDisaster"
                        and getattr(action, "disaster_type", "meteor") in {"storm", "vortex"}):
                    action.x2_expr, action.y2_expr = tx, ty
                else:
                    action.x2, action.y2 = tx, ty
            elif field == "attack1":
                action.attack_x, action.attack_y = tx, ty
            elif field == "attack2":
                action.attack_x2, action.attack_y2 = tx, ty
            elif field == "patrol_point":
                # Mehrere Klicks erlaubt; Rechtsklick beendet den Pick.
                # Multiple clicks allowed; right-click ends the pick.
                pts = list(getattr(action, "patrol_points", None) or [])
                if len(pts) < 8:
                    pts.append([tx, ty])
                    action.patrol_points = pts
                    self.statusBar().showMessage(
                        f"Wegpunkt {len(pts)}/8 gesetzt: ({tx},{ty}) — Rechtsklick beendet")
                return  # Pick aktiv lassen / keep pick active
            self.statusBar().showMessage(tr("window.status_action_added", summary=action_summary(action)))
            self._pending_trigger_index = self._action_pick.get("trigger_index", 0)
            self._pending_action_index = self._action_pick.get("action_index", -1)
            self._end_action_pick()
            return
        if self._action_pick and self._action_pick["kind"] == "recordBuilding":
            if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
                return
            action = TriggerAction(
                kind="recordBuilding",
                group_name=self._action_pick["group_name"],
                building_type=self._action_pick["building_type"],
                x=tx, y=ty)
            self._add_action_from_pick(action)
            self.statusBar().showMessage(tr("window.status_action_added", summary=action_summary(action)))
            self._end_action_pick()
            return
        if self._action_pick and self._action_pick["kind"] == "assignToGroup":
            if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
                return
            action = TriggerAction(
                kind="assignToGroup",
                group_name=self._action_pick["group_name"],
                building_type=self._action_pick["building_type"],
                player=self._action_pick.get("player", 0),
                x=tx, y=ty)
            self._add_action_from_pick(action)
            self.statusBar().showMessage(tr("window.status_action_added", summary=action_summary(action)))
            self._end_action_pick()
            return
        if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
            return
        if not self._placement_active:
            self._edit_object_at(tx, ty)
            return
        sel = self._selected()
        if not sel:
            return
        kind, disp, mid, fp = sel
        params = {}
        if mid == "mapCargoTruck":
            params["truck_cargo"] = TRUCK_CARGO[self.cargo_combo.currentData()]
            params["truck_amount"] = self.cargo_amount.value()
        elif mid == "mapConVec":
            convec_kit = self.kit_combo.currentData()
            if convec_kit:
                params["convec_kit"] = convec_kit
        elif mid == "mapMiningBeacon":
            params["ore_type"] = ORE_TYPES[self.ore_combo.currentData()]
            params["yield_bars"] = YIELDS[self.yield_combo.currentData()]
        if mid in WEAPON_UNITS:
            params["weapon"] = self.weapon_combo.currentData()
        player = self.player_spin.value() if kind in ("structure", "vehicle") else 0
        unit_name = self.unit_name_edit.text().strip() if kind in ("structure", "vehicle") else ""
        obj = PlacedObject(kind, tx, ty, mid, fp, disp, player, params, self._new_object_uid(), unit_name)
        self._draw(obj)
        self.objects.append(obj)
        self._push_undo("place", obj)
        self._refresh_overview()
        label = unit_name or disp
        self.statusBar().showMessage(tr("window.status_placed", label=label, x=tx, y=ty, n=len(self.objects)))

    def on_remove(self, tx, ty):
        if self._action_pick is not None and self._action_pick.get("kind") == "lava_paint":
            self._lava_paint_remove(tx, ty)
            return
        if self._action_pick is not None:
            self._end_action_pick()
            self.statusBar().showMessage(tr("window.status_action_canceled"))
            return
        if self._placement_active:
            self._cancel_placement()
            return
        obj = self._object_at(tx, ty)
        if obj is not None:
            for item in obj.items:
                self.scene.removeItem(item)
            self.objects.remove(obj)
            self._push_undo("remove", obj)
            self._refresh_overview()
            self.statusBar().showMessage(tr("window.status_removed", display=obj.display, n=len(self.objects)))

    def _draw(self, obj: PlacedObject):
        if obj.kind == "beacon":
            color = BEACON_COLOR
        elif obj.kind == "wall":
            color = WALL_COLOR
        else:
            color = PLAYER_COLORS[obj.player % len(PLAYER_COLORS)]
        fw, fh = obj.footprint
        x0 = (obj.tile_x - fw // 2) * SCENE_TILE
        y0 = (obj.tile_y - fh // 2) * SCENE_TILE
        rect = QGraphicsRectItem(x0, y0, fw * SCENE_TILE, fh * SCENE_TILE)
        rect.setPen(QPen(color, 2))
        rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 120)))
        self.scene.addItem(rect)
        text = obj.unit_name or obj.display.split()[0]
        label = QGraphicsSimpleTextItem(text[:10])
        label.setBrush(QBrush(Qt.black if obj.kind == "beacon" else Qt.white))
        label.setPos(x0 + 2, y0 + 1)
        self.scene.addItem(label)
        obj.items = [rect, label]

    def clear_objects(self):
        for obj in self.objects:
            for it in obj.items:
                self.scene.removeItem(it)
        self.objects.clear()
        self._clear_undo()
        self.building_groups.clear()
        self.reinforce_groups.clear()
        self.fight_groups.clear()
        self.groups_panel.load()
        self._refresh_overview()
        self.statusBar().showMessage(tr("window.status_objects_cleared"))
