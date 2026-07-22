from __future__ import annotations

from .common import *

# Action-Felder, die per Rechteck-Drag gesetzt werden. Wert: (x, y, x2, y2)-
# Attributnamen auf der TriggerAction.
# Action fields set via rect drag. Value: (x, y, x2, y2) attribute names.
_RECT_PICK_FIELDS = {
    "staging_rect": ("x", "y", "x2", "y2"),
    "area_rect": ("x", "y", "x2", "y2"),
    "attack_rect": ("attack_x", "attack_y", "attack_x2", "attack_y2"),
    "idle_rect": ("idle_x", "idle_y", "idle_x2", "idle_y2"),
}

# Action-Felder, die per Linien-Drag gesetzt werden (nur X- oder nur
# Y-Richtung, keine Diagonalen) -- fuer die Listenzeilen von recordTube/
# recordWall. Ziel sind immer die generischen x/y/x2/y2-Attribute.
# Action fields set via line drag (X or Y direction only, no diagonals) --
# for recordTube/recordWall list rows. Always targets the generic x/y/x2/y2
# attributes.
_LINE_PICK_FIELDS = {"tube_line", "wall_line"}


class _MapPickMixin:
    def _begin_rect_pick(self, group):
        self._placement_active = False
        self._clear_placement_preview()
        self._rect_pick_group = group
        self._rect_pick_start = None
        if self._rect_pick_item is not None:
            self.scene.removeItem(self._rect_pick_item)
            self._rect_pick_item = None
        self.view.rect_select_enabled = True
        self.view.setCursor(Qt.CrossCursor)
        self.statusBar().showMessage(tr("window.status_setrect_begin", name=group.name))

    def _end_rect_pick(self):
        self.view.rect_select_enabled = False
        self.view.setCursor(Qt.ArrowCursor)
        self._rect_pick_group = None
        self._rect_pick_start = None
        if self._rect_pick_item is not None:
            self.scene.removeItem(self._rect_pick_item)
            self._rect_pick_item = None

    def _rect_from_tiles(self, x1, y1, x2, y2):
        if self.map is None:
            return 0, 0, 1, 1
        left = max(0, min(x1, x2, self.map.width - 1))
        right = max(0, min(max(x1, x2), self.map.width - 1))
        top = max(0, min(y1, y2, self.map.height - 1))
        bottom = max(0, min(max(y1, y2), self.map.height - 1))
        return left, top, right - left + 1, bottom - top + 1

    def _clamp_tile(self, tx, ty):
        if self.map is None:
            return tx, ty
        return (
            max(0, min(tx, self.map.width - 1)),
            max(0, min(ty, self.map.height - 1)),
        )

    def _axis_lock(self, sx, sy, tx, ty):
        """Zwingt (tx,ty) auf dieselbe X- oder Y-Achse wie (sx,sy) -- keine
        Diagonalen, damit Tube-/Wall-Linien immer gerade bleiben.

        Forces (tx,ty) onto the same X or Y axis as (sx,sy) -- no diagonals,
        so tube/wall lines always stay straight."""
        if abs(tx - sx) >= abs(ty - sy):
            return tx, sy
        return sx, ty

    def _update_rect_overlay(self, x, y, w, h):
        if self._rect_pick_item is not None:
            self.scene.removeItem(self._rect_pick_item)
        self._rect_pick_item = QGraphicsRectItem(
            x * SCENE_TILE, y * SCENE_TILE, w * SCENE_TILE, h * SCENE_TILE)
        self._rect_pick_item.setPen(QPen(QColor(255, 255, 255), 3))
        self._rect_pick_item.setBrush(QBrush(QColor(255, 255, 255, 60)))
        self._rect_pick_item.setZValue(1000)
        self.scene.addItem(self._rect_pick_item)

    def _rect_drag_start(self, tx, ty):
        if self._action_pick and self._action_pick.get("kind") == "lava_paint":
            self._lava_stamp(tx, ty, add=True)
            self._lava_update_brush_cursor(tx, ty)
            return
        if self._action_pick and self._action_pick["kind"] == "action_field" \
                and self._action_pick.get("field") in ({"rect", "repair_zone"} | set(_RECT_PICK_FIELDS)):
            tx, ty = self._clamp_tile(tx, ty)
            self._action_pick_start = (tx, ty)
            x, y, w, h = self._rect_from_tiles(tx, ty, tx, ty)
            self._update_rect_overlay(x, y, w, h)
            return
        if self._action_pick and self._action_pick["kind"] == "action_field" \
                and self._action_pick.get("field") in _LINE_PICK_FIELDS:
            tx, ty = self._clamp_tile(tx, ty)
            self._action_pick_start = (tx, ty)
            color = (QColor(120, 220, 255) if self._action_pick["field"] == "tube_line"
                     else QColor(255, 180, 80))
            self._draw_action_line_preview(tx, ty, tx, ty, color)
            return
        if self._action_pick and self._action_pick["kind"] in ("recordTube", "recordWall"):
            tx, ty = self._clamp_tile(tx, ty)
            self._action_pick_start = (tx, ty)
            color = QColor(120, 220, 255) if self._action_pick["kind"] == "recordTube" else QColor(255, 180, 80)
            self._draw_action_line_preview(tx, ty, tx, ty, color)
            return
        if self._rect_pick_group is None:
            return
        self._rect_pick_start = (tx, ty)
        x, y, w, h = self._rect_from_tiles(tx, ty, tx, ty)
        self._update_rect_overlay(x, y, w, h)

    def _rect_drag_move(self, tx, ty):
        if self._action_pick and self._action_pick.get("kind") == "lava_paint":
            self._lava_stamp(tx, ty, add=True)
            self._lava_update_brush_cursor(tx, ty)
            self.coord_label.setText(
                tr("window.lava_brush_coord", x=tx, y=ty, s=self._lava_brush_size))
            return
        if self._action_pick and self._action_pick["kind"] == "action_field" \
                and self._action_pick.get("field") in ({"rect", "repair_zone"} | set(_RECT_PICK_FIELDS)) \
                and self._action_pick_start is not None:
            sx, sy = self._action_pick_start
            x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
            self._update_rect_overlay(x, y, w, h)
            self.coord_label.setText(f"Bereich: {x}, {y}, {w}x{h}")
            return
        if self._action_pick and self._action_pick["kind"] == "action_field" \
                and self._action_pick.get("field") in _LINE_PICK_FIELDS \
                and self._action_pick_start is not None:
            tx, ty = self._clamp_tile(tx, ty)
            sx, sy = self._action_pick_start
            tx, ty = self._axis_lock(sx, sy, tx, ty)
            color = (QColor(120, 220, 255) if self._action_pick["field"] == "tube_line"
                     else QColor(255, 180, 80))
            self._draw_action_line_preview(sx, sy, tx, ty, color)
            self.coord_label.setText(tr("window.coord_line", sx=sx, sy=sy, tx=tx, ty=ty))
            return
        if self._action_pick and self._action_pick_start is not None:
            tx, ty = self._clamp_tile(tx, ty)
            sx, sy = self._action_pick_start
            color = QColor(120, 220, 255) if self._action_pick["kind"] == "recordTube" else QColor(255, 180, 80)
            self._draw_action_line_preview(sx, sy, tx, ty, color)
            self.coord_label.setText(tr("window.coord_line", sx=sx, sy=sy, tx=tx, ty=ty))
            return
        if self._rect_pick_group is None or self._rect_pick_start is None:
            return
        sx, sy = self._rect_pick_start
        x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
        self._update_rect_overlay(x, y, w, h)
        self.coord_label.setText(f"SetRect: {x}, {y}, {w}x{h}")

    def _rect_drag_finish(self, tx, ty):
        if self._action_pick and self._action_pick.get("kind") == "lava_paint":
            self._lava_stamp(tx, ty, add=True)
            return
        if self._action_pick and self._action_pick["kind"] == "action_field" \
                and self._action_pick.get("field") in ({"rect", "repair_zone"} | set(_RECT_PICK_FIELDS)):
            if self._action_pick_start is None:
                self._end_action_pick()
                return
            sx, sy = self._action_pick_start
            x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
            action = self._action_pick["action"]
            field = self._action_pick.get("field")
            if field == "repair_zone":
                zones = list(getattr(action, "repair_zones", None) or [])
                zones.append({"x": x, "y": y, "x2": x + w - 1, "y2": y + h - 1})
                action.repair_zones = zones
            elif field == "rect":
                action.rect_x, action.rect_y = x, y
                action.rect_width, action.rect_height = w, h
            else:
                ax, ay, ax2, ay2 = _RECT_PICK_FIELDS[field]
                setattr(action, ax, x); setattr(action, ay, y)
                setattr(action, ax2, x + w - 1); setattr(action, ay2, y + h - 1)
            self.statusBar().showMessage(f"Bereich gesetzt: ({x},{y}) {w}x{h}")
            self._pending_trigger_index = self._action_pick.get("trigger_index", 0)
            self._pending_action_index = self._action_pick.get("action_index", -1)
            self._end_action_pick()
            return
        if self._action_pick and self._action_pick["kind"] == "action_field" \
                and self._action_pick.get("field") in _LINE_PICK_FIELDS:
            if self._action_pick_start is None:
                self._end_action_pick()
                return
            tx, ty = self._clamp_tile(tx, ty)
            sx, sy = self._action_pick_start
            tx, ty = self._axis_lock(sx, sy, tx, ty)
            action = self._action_pick["action"]
            action.x, action.y = sx, sy
            action.x2, action.y2 = tx, ty
            self.statusBar().showMessage(f"Linie gesetzt: ({sx},{sy}) -> ({tx},{ty})")
            self._pending_trigger_index = self._action_pick.get("trigger_index", 0)
            self._pending_action_index = self._action_pick.get("action_index", -1)
            self._end_action_pick()
            return
        if self._action_pick and self._action_pick_start is not None:
            tx, ty = self._clamp_tile(tx, ty)
            sx, sy = self._action_pick_start
            kind = self._action_pick["kind"]
            if kind == "recordTube":
                action = TriggerAction(
                    kind="recordTube", group_name=self._action_pick["group_name"],
                    x=sx, y=sy, x2=tx, y2=ty)
            else:
                action = TriggerAction(
                    kind="recordWall", group_name=self._action_pick["group_name"],
                    wall_type=self._action_pick["wall_type"],
                    x=sx, y=sy, x2=tx, y2=ty)
            self._add_action_from_pick(action)
            self.statusBar().showMessage(tr("window.status_action_added", summary=action_summary(action)))
            self._end_action_pick()
            return
        if self._rect_pick_group is None or self._rect_pick_start is None:
            self._end_rect_pick()
            return
        sx, sy = self._rect_pick_start
        x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
        group = self._rect_pick_group
        # FightGroup speichert den Bereich als Idle-Rect (idle_x/y/width/height)
        # statt rect_x/y/width/height wie Building-/ReinforceGroup.
        # FightGroup stores the area as an idle rect (idle_x/y/width/height)
        # instead of rect_x/y/width/height like Building/Reinforce groups.
        if isinstance(group, FightGroupSpec):
            group.idle_x, group.idle_y = x, y
            group.idle_width, group.idle_height = w, h
        else:
            group.rect_x, group.rect_y = x, y
            group.rect_width, group.rect_height = w, h
        name = group.name
        self._end_rect_pick()
        self.statusBar().showMessage(tr("window.status_setrect_done", name=name, x=x, y=y, w=w, h=h))
        self.groups_panel.refresh()

    def _rect_drag_cancel(self):
        if self._action_pick is not None and self._action_pick.get("kind") == "lava_paint":
            return  # Rechtsklick im Lava-Modus wird über tileRemoved behandelt
        if self._action_pick is not None:
            self._end_action_pick()
            self.statusBar().showMessage(tr("window.status_action_canceled"))
            return
        if self._rect_pick_group is None:
            return
        self._end_rect_pick()
        self.statusBar().showMessage(tr("window.status_setrect_canceled"))

    def _clear_action_preview(self):
        for item in self._action_preview_items:
            self.scene.removeItem(item)
        self._action_preview_items = []

    def _begin_lava_paint(self, request):
        self._action_pick = request
        self._lava_paint_set = {(xy[0], xy[1]) for xy in (request["action"].lava_zone or [])}
        self._lava_paint_items = []
        if not hasattr(self, "_lava_brush_size"):
            self._lava_brush_size = 3
        self._lava_brush_cursor_item = None
        self.view.rect_select_enabled = True
        self.view.lava_paint_enabled = True
        self.view.setCursor(Qt.CrossCursor)
        self._redraw_lava_paint_tiles()
        self.statusBar().showMessage(
            tr("window.lava_paint_hint", size=self._lava_brush_size))

    def _end_lava_paint(self):
        action = self._action_pick["action"]
        action.lava_zone = [list(xy) for xy in sorted(self._lava_paint_set)]
        action_index = self._action_pick.get("action_index", -1)
        self.view.rect_select_enabled = False
        self.view.lava_paint_enabled = False
        self.view.setCursor(Qt.ArrowCursor)
        self._clear_lava_brush_cursor()
        self._clear_lava_paint_items()
        self._action_pick = None
        self.trigger_panel.refresh_actions(expand_index=action_index)
        self._redraw_planned_actions()

    def _lava_brush_tiles(self, tx, ty):
        """Kacheln unter dem runden Pinsel (Durchmesser s, zentriert).

        Bei s <= 2 ist Kreis == Quadrat; ab s == 3 schneidet die Kreismaske
        die Ecken ab (s=3 -> Plus, s=5 -> Scheibe mit 21 Kacheln, ...).

        Tiles under the round brush (diameter s, centred). For s <= 2 the
        circle equals the square; from s == 3 on the circular mask cuts the
        corners (s=3 -> plus shape, s=5 -> 21-tile disc, ...)."""
        s = self._lava_brush_size
        lo, hi = -(s // 2), s - s // 2 - 1
        c = (lo + hi) / 2.0
        limit = (s / 2.0) ** 2 - 0.25
        for dx in range(lo, hi + 1):
            for dy in range(lo, hi + 1):
                if s > 2 and (dx - c) ** 2 + (dy - c) ** 2 >= limit:
                    continue
                x, y = tx + dx, ty + dy
                if self.map and 0 <= x < self.map.width and 0 <= y < self.map.height:
                    yield (x, y)

    def _lava_stamp(self, tx, ty, add=True):
        """Pinselabdruck setzen/radieren (ein Redraw pro Abdruck).

        Apply/erase one brush stamp (a single redraw per stamp)."""
        tiles = set(self._lava_brush_tiles(tx, ty))
        before = len(self._lava_paint_set)
        if add:
            self._lava_paint_set |= tiles
        else:
            self._lava_paint_set -= tiles
        if len(self._lava_paint_set) != before:
            self._save_lava_zone()
            self._redraw_lava_paint_tiles()

    def _lava_brush_step(self, delta):
        if not (self._action_pick and self._action_pick.get("kind") == "lava_paint"):
            return
        self._lava_brush_size = max(1, min(9, self._lava_brush_size + delta))
        self.statusBar().showMessage(
            tr("window.lava_paint_hint", size=self._lava_brush_size))
        if self._lava_brush_cursor_item is not None:
            r = self._lava_brush_cursor_item.rect()
            cx = int(r.center().x() // SCENE_TILE)
            cy = int(r.center().y() // SCENE_TILE)
            self._lava_update_brush_cursor(cx, cy)

    def _lava_update_brush_cursor(self, tx, ty):
        """Pinsel-Umriss am Cursor / brush outline at the cursor."""
        self._clear_lava_brush_cursor()
        s = self._lava_brush_size
        x0 = (tx - s // 2) * SCENE_TILE
        y0 = (ty - s // 2) * SCENE_TILE
        # Runder Umriss passend zur Kreismaske (eckig nur bei s <= 2).
        # Round outline matching the circular mask (square only for s <= 2).
        if s <= 2:
            item = QGraphicsRectItem(x0, y0, s * SCENE_TILE, s * SCENE_TILE)
        else:
            item = QGraphicsEllipseItem(x0, y0, s * SCENE_TILE, s * SCENE_TILE)
        item.setPen(QPen(QColor(255, 200, 0), 2, Qt.DashLine))
        item.setBrush(QBrush(QColor(255, 160, 0, 30)))
        item.setZValue(1070)
        self.scene.addItem(item)
        self._lava_brush_cursor_item = item

    def _clear_lava_brush_cursor(self):
        if getattr(self, "_lava_brush_cursor_item", None) is not None:
            self.scene.removeItem(self._lava_brush_cursor_item)
            self._lava_brush_cursor_item = None

    def _save_lava_zone(self):
        self._action_pick["action"].lava_zone = [list(xy) for xy in sorted(self._lava_paint_set)]

    def _clear_lava_paint_items(self):
        for item in self._lava_paint_items:
            self.scene.removeItem(item)
        self._lava_paint_items = []

    def _redraw_lava_paint_tiles(self):
        self._clear_lava_paint_items()
        for (tx, ty) in self._lava_paint_set:
            rect = QGraphicsRectItem(tx * SCENE_TILE, ty * SCENE_TILE, SCENE_TILE, SCENE_TILE)
            rect.setPen(QPen(QColor(255, 100, 0), 1))
            rect.setBrush(QBrush(QColor(255, 100, 0, 110)))
            rect.setZValue(1050)
            self.scene.addItem(rect)
            self._lava_paint_items.append(rect)

    def _begin_action_pick(self, request):
        if request["kind"] == "lava_paint":
            if self._action_pick is not None and self._action_pick.get("kind") == "lava_paint":
                self._end_lava_paint()
                return
            if self._action_pick is not None:
                self._end_action_pick(reopen=False)
            self._placement_active = False
            self._clear_placement_preview()
            self._begin_lava_paint(request)
            return
        self._placement_active = False
        self._clear_placement_preview()
        self._action_pick = request
        self._action_pick_start = None
        self._clear_action_preview()
        if (
            request["kind"] in ("recordTube", "recordWall")
            or (request["kind"] == "action_field"
                and request.get("field") in ({"rect", "repair_zone"} | set(_RECT_PICK_FIELDS) | _LINE_PICK_FIELDS))
        ):
            self.view.rect_select_enabled = True
        self.view.setCursor(Qt.CrossCursor)
        labels = {
            "recordBuilding": tr("window.pick_record_building"),
            "assignToGroup": tr("window.pick_assign_group"),
            "recordTube": tr("window.pick_record_tube"),
            "recordWall": tr("window.pick_record_wall"),
            "action_field": {
                "primary": "Klick: Position (X, Y) der Aktion setzen",
                "secondary": "Klick: zweite Position (X2, Y2) der Aktion setzen",
                "rect": "Klick: Bereich-Ecke (rect X, rect Y) der Aktion setzen",
                "staging_rect": "Sammelbereich aufziehen (Klick + Ziehen)",
                "attack_rect": "Angriffsbereich aufziehen (Klick + Ziehen)",
                "idle_rect": "Idle-Bereich aufziehen (Klick + Ziehen)",
                "area_rect": "Zielbereich aufziehen (Klick + Ziehen)",
                "patrol_point": "Wegpunkte anklicken (bis 8) — Rechtsklick beendet",
                "repair_zone": "Reparatur-Zone aufziehen (Klick + Ziehen)",
                "tube_line": "Rohrleitung aufziehen (nur X oder Y, Klick + Ziehen)",
                "wall_line": "Mauerabschnitt aufziehen (nur X oder Y, Klick + Ziehen)",
            }.get(request.get("field"), "Klick: Karte fuer Aktion picken"),
        }
        label = labels.get(request["kind"], "Klick: Karte fuer Aktion picken")
        self.statusBar().showMessage(tr("window.status_pick_hint", label=label))

    def _end_action_pick(self, reopen=True):
        action_index = self._action_pick.get("action_index", -1) if self._action_pick else -1
        self.view.rect_select_enabled = False
        self.view.setCursor(Qt.ArrowCursor)
        self._action_pick = None
        self._action_pick_start = None
        self._clear_action_preview()
        if reopen:
            self.trigger_panel.refresh_actions(expand_index=action_index)

    def _draw_action_building_preview(self, tx, ty):
        self._clear_action_preview()
        # Typ entweder direkt im Pick-Request (Legacy-Pfade) oder aus der
        # Aktion des Formular-Picks (recordBuilding/createUnit-Eingabezeile).
        # Type either directly in the pick request (legacy paths) or from
        # the form pick's action (recordBuilding/createUnit input row).
        building_type = self._action_pick.get("building_type")
        if not building_type:
            action = self._action_pick.get("action")
            if getattr(action, "kind", "") == "createUnit":
                building_type = getattr(action, "unit_type", "")
            else:
                building_type = getattr(action, "building_type", "")
        fw, fh = STRUCTURE_FOOTPRINTS.get(building_type, (1, 1))
        x0 = (tx - fw // 2) * SCENE_TILE
        y0 = (ty - fh // 2) * SCENE_TILE
        rect = QGraphicsRectItem(x0, y0, fw * SCENE_TILE, fh * SCENE_TILE)
        rect.setPen(QPen(QColor(255, 255, 255), 3, Qt.DashLine))
        rect.setBrush(QBrush(QColor(255, 255, 255, 45)))
        rect.setZValue(1100)
        self.scene.addItem(rect)
        self._action_preview_items = [rect]

    # Liefert die Kacheln einer L-foermigen (achsenparallelen) Linie von (x1,y1)
    # nach (x2,y2); es wird zuerst entlang der laengeren Achse geschritten.
    def _line_tiles(self, x1, y1, x2, y2):
        tiles = []
        if abs(x2 - x1) >= abs(y2 - y1):
            step = 1 if x2 >= x1 else -1
            for x in range(x1, x2 + step, step):
                tiles.append((x, y1))
            if y2 != y1:
                step_y = 1 if y2 >= y1 else -1
                for y in range(y1 + step_y, y2 + step_y, step_y):
                    tiles.append((x2, y))
        else:
            step = 1 if y2 >= y1 else -1
            for y in range(y1, y2 + step, step):
                tiles.append((x1, y))
            if x2 != x1:
                step_x = 1 if x2 >= x1 else -1
                for x in range(x1 + step_x, x2 + step_x, step_x):
                    tiles.append((x, y2))
        return tiles

    def _draw_action_line_preview(self, x1, y1, x2, y2, color):
        self._clear_action_preview()
        for tx, ty in self._line_tiles(x1, y1, x2, y2):
            rect = QGraphicsRectItem(tx * SCENE_TILE, ty * SCENE_TILE, SCENE_TILE, SCENE_TILE)
            rect.setPen(QPen(color, 2, Qt.DashLine))
            rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 55)))
            rect.setZValue(1100)
            self.scene.addItem(rect)
            self._action_preview_items.append(rect)

    def _add_action_from_pick(self, action):
        idx = self._action_pick["trigger_index"]
        if 0 <= idx < len(self.triggers):
            action_index = self._action_pick.get("action_index", -1)
            actions = self.triggers[idx].actions
            if 0 <= action_index < len(actions) and actions[action_index].kind == action.kind:
                actions[action_index] = action
            else:
                actions.append(action)
                action_index = len(actions) - 1
            self._pending_trigger_index = idx
            self._pending_action_index = action_index
        self._redraw_planned_actions()

    def _clear_planned_actions(self):
        for item in self._planned_items:
            self.scene.removeItem(item)
        self._planned_items = []

    def _add_planned_rect(self, x, y, w, h, color, brush_style=Qt.BDiagPattern,
                          tooltip="", label=""):
        rect = QGraphicsRectItem(x * SCENE_TILE, y * SCENE_TILE, w * SCENE_TILE, h * SCENE_TILE)
        rect.setPen(QPen(color, 2, Qt.DashLine))
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 80))
        brush.setStyle(brush_style)
        rect.setBrush(brush)
        rect.setZValue(900)
        if tooltip:
            rect.setToolTip(tooltip)
        self.scene.addItem(rect)
        self._planned_items.append(rect)
        if label:
            t = QGraphicsSimpleTextItem(label)
            f = QFont()
            f.setPointSize(7)
            t.setFont(f)
            t.setBrush(QBrush(color))
            t.setPos(x * SCENE_TILE + 2, y * SCENE_TILE + 1)
            t.setZValue(901)
            if tooltip:
                t.setToolTip(tooltip)
            self.scene.addItem(t)
            self._planned_items.append(t)

    def _add_planned_building(self, x, y, building_type, color, tooltip="", label=""):
        fw, fh = STRUCTURE_FOOTPRINTS.get(building_type, (1, 1))
        self._add_planned_rect(x - fw // 2, y - fh // 2, fw, fh, color,
                               tooltip=tooltip, label=label)

    def _redraw_planned_actions(self):
        """Alle durch Trigger-Aktionen GEPLANTEN Gebaeude/Einheiten/Leitungen
        gestrichelt auf der Karte zeigen -- inkl. Listen-Eintraegen
        (building_list/unit_list/...) und verschachtelten Wenn/Dann-Aktionen.
        Tooltip + Label nennen den verursachenden Trigger.

        Show everything trigger actions PLAN to build (buildings/units/
        tubes/walls) as dashed outlines on the map -- incl. list entries
        (building_list/unit_list/...) and nested if/then actions. Tooltip +
        label name the owning trigger.
        """
        self._clear_planned_actions()

        def walk(actions):
            for a in (actions or []):
                yield a
                yield from walk(getattr(a, "then_actions", None))
                yield from walk(getattr(a, "else_actions", None))

        for trigger in self.triggers:
            tip = tr("map_overlay.planned_by_trigger", name=trigger.name)
            for action in walk(trigger.actions):
                if action.kind == "recordBuilding":
                    entries = list(getattr(action, "building_list", None) or [])
                    if not entries:
                        entries = [{"building_type": action.building_type,
                                    "x": action.x, "y": action.y}]
                    for e in entries:
                        bt = e.get("building_type", "mapCommandCenter")
                        short = bt[3:] if bt.startswith("map") else bt
                        self._add_planned_building(
                            int(e.get("x", 0)), int(e.get("y", 0)), bt,
                            QColor(255, 120, 255),
                            tooltip=f"{tip}\n{bt}",
                            label=f"{trigger.name} · {short}")
                elif action.kind == "createUnit":
                    entries = list(getattr(action, "unit_list", None) or [])
                    if not entries:
                        entries = [{"unit_type": action.unit_type,
                                    "x": action.x, "y": action.y}]
                    color = PLAYER_COLORS[int(getattr(action, "player", 0)) % len(PLAYER_COLORS)]
                    for e in entries:
                        ut = e.get("unit_type", "mapScout")
                        short = ut[3:] if ut.startswith("map") else ut
                        self._add_planned_building(
                            int(e.get("x", 0)), int(e.get("y", 0)), ut,
                            color, tooltip=f"{tip}\n{ut}",
                            label=f"{trigger.name} · {short}")
                elif action.kind == "recordTube":
                    entries = list(getattr(action, "tube_list", None) or [])
                    if not entries:
                        entries = [{"x": action.x, "y": action.y,
                                    "x2": action.x2, "y2": action.y2}]
                    for e in entries:
                        for tx, ty in self._line_tiles(int(e.get("x", 0)), int(e.get("y", 0)),
                                                       int(e.get("x2", 0)), int(e.get("y2", 0))):
                            self._add_planned_rect(tx, ty, 1, 1, QColor(120, 220, 255),
                                                   Qt.Dense4Pattern, tooltip=tip)
                elif action.kind == "recordWall":
                    entries = list(getattr(action, "wall_list", None) or [])
                    if not entries:
                        entries = [{"x": action.x, "y": action.y,
                                    "x2": action.x2, "y2": action.y2}]
                    for e in entries:
                        for tx, ty in self._line_tiles(int(e.get("x", 0)), int(e.get("y", 0)),
                                                       int(e.get("x2", 0)), int(e.get("y2", 0))):
                            self._add_planned_rect(tx, ty, 1, 1, QColor(255, 180, 80),
                                                   Qt.Dense4Pattern, tooltip=tip)
                elif (action.kind == "createDisaster"
                      and getattr(action, "disaster_type", "") == "eruption"):
                    for xy in getattr(action, "lava_zone", []) or []:
                        self._add_planned_rect(xy[0], xy[1], 1, 1, QColor(255, 100, 0),
                                               tooltip=tip)
