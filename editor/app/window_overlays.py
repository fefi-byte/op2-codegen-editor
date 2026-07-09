from __future__ import annotations

from .common import *

# Overlay-Farben / overlay colors
_TRIGGER_COLOR = QColor(137, 180, 250)   # blau / blue
_GROUP_COLOR = QColor(250, 179, 135)     # orange


class _OverlaysMixin:
    """Karten-Overlays: Trigger-Zonen und Gruppen-Idle-Rects einblenden.

    Map overlays: show trigger zones and group idle rects. Toggled from the
    View menu; redrawn on every model refresh via _refresh_overlays()."""

    def _init_overlays(self):
        self._overlay_triggers_on = False
        self._overlay_groups_on = False
        self._overlay_items: list = []
        self._area_preview_items: list = []

    def _toggle_trigger_overlay(self, on):
        self._overlay_triggers_on = on
        self._refresh_overlays()

    def _toggle_group_overlay(self, on):
        self._overlay_groups_on = on
        self._refresh_overlays()

    def _clear_overlays(self):
        for item in self._overlay_items:
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
        self._overlay_items = []

    def _refresh_overlays(self):
        self._clear_overlays()
        if self.map is None:
            return
        if self._overlay_triggers_on:
            self._draw_trigger_overlays()
        if self._overlay_groups_on:
            self._draw_group_overlays()

    # ------------------------------------------------------------------
    def _overlay_rect(self, tx, ty, tw, th, color, label):
        rect = QGraphicsRectItem(tx * SCENE_TILE, ty * SCENE_TILE,
                                 tw * SCENE_TILE, th * SCENE_TILE)
        rect.setPen(QPen(color, 2, Qt.DashLine))
        rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 35)))
        rect.setZValue(900)
        self.scene.addItem(rect)
        self._overlay_items.append(rect)
        if label:
            text = QGraphicsSimpleTextItem(label)
            text.setBrush(QBrush(color))
            text.setPos(tx * SCENE_TILE + 3, ty * SCENE_TILE + 2)
            text.setZValue(901)
            self.scene.addItem(text)
            self._overlay_items.append(text)

    def _overlay_point(self, tx, ty, color, label):
        r = SCENE_TILE * 0.6
        cx, cy = tx * SCENE_TILE + SCENE_TILE / 2, ty * SCENE_TILE + SCENE_TILE / 2
        dot = QGraphicsEllipseItem(cx - r, cy - r, 2 * r, 2 * r)
        dot.setPen(QPen(color, 2))
        dot.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
        dot.setZValue(900)
        self.scene.addItem(dot)
        self._overlay_items.append(dot)
        if label:
            text = QGraphicsSimpleTextItem(label)
            text.setBrush(QBrush(color))
            text.setPos(cx + r, cy - r)
            text.setZValue(901)
            self.scene.addItem(text)
            self._overlay_items.append(text)

    def _draw_trigger_overlays(self):
        for t in self.triggers:
            if t.condition == "rect":
                self._overlay_rect(t.x, t.y, max(1, t.width), max(1, t.height),
                                   _TRIGGER_COLOR, t.name)
            elif t.condition == "point":
                self._overlay_point(t.x, t.y, _TRIGGER_COLOR, t.name)
            elif t.condition == "findUnit":
                for chk in (t.unit_checks or []):
                    self._overlay_point(chk.x, chk.y, _TRIGGER_COLOR, t.name)

    # ------------------------------------------------------------------
    # Bereichs-Vorschau fuer die gerade aufgeklappte Aktionskarte.
    # Area preview for the currently expanded action card.
    def clear_action_area_preview(self):
        for item in self._area_preview_items:
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
        self._area_preview_items = []

    def show_action_area_preview(self, action):
        self.clear_action_area_preview()
        if action is None or self.map is None:
            return
        # Waehrend der Vorschau in die Overlay-Item-Liste der Bereichs-Vorschau
        # zeichnen (nicht in die der Menue-Overlays).
        # Draw into the preview item list (not the menu-overlay one).
        items_backup = self._overlay_items
        self._overlay_items = self._area_preview_items
        try:
            k = getattr(action, "kind", "")
            def rect_of(x, y, x2, y2, color, label):
                if not any((x, y, x2, y2)):
                    return
                tx, ty = min(x, x2), min(y, y2)
                tw, th = abs(x2 - x) + 1, abs(y2 - y) + 1
                self._overlay_rect(tx, ty, tw, th, color, label)
            if k == "sendAttackWave":
                rect_of(action.idle_x, action.idle_y, action.idle_x2, action.idle_y2,
                        QColor(166, 227, 161), "Idle")
                rect_of(action.x, action.y, action.x2, action.y2,
                        QColor(137, 180, 250), "Sammeln")
                rect_of(action.attack_x, action.attack_y, action.attack_x2, action.attack_y2,
                        QColor(243, 139, 168), "Angriff")
            elif k in ("fightGroupCmd", "unitCmd") \
                    and getattr(action, "fg_command", "") == "patrol":
                pts = list(getattr(action, "patrol_points", None) or [])
                if not pts:
                    pts = [[action.x, action.y], [action.x2, action.y2]]
                for n, (px, py) in enumerate(pts[:8], 1):
                    self._overlay_point(int(px), int(py), QColor(249, 226, 175), str(n))
            elif k == "fightGroupCmd":
                rect_of(action.x, action.y, action.x2, action.y2,
                        QColor(243, 139, 168), "Ziel")
            elif k == "unitCmd" and getattr(action, "fg_command", "") in ("move", "attackGround"):
                self._overlay_point(action.x, action.y, QColor(243, 139, 168), "Ziel")
            elif k in ("defendArea", "repairBuildings"):
                rect_of(action.x, action.y, action.x2, action.y2,
                        QColor(137, 180, 250), "Bereich")
        finally:
            self._area_preview_items = self._overlay_items
            self._overlay_items = items_backup

    def _draw_group_overlays(self):
        for g in self.building_groups:
            self._overlay_rect(g.rect_x, g.rect_y,
                               max(1, g.rect_width), max(1, g.rect_height),
                               _GROUP_COLOR, g.name)
