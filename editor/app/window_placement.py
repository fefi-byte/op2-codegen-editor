from __future__ import annotations

from .common import *
from .mapview import MapView
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
        self._verlauf_auffrischen()

    def _clear_undo(self):
        if hasattr(self, "_undo_stack"):
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._verlauf_auffrischen()

    def undo(self):
        if not self._undo_stack:
            self.statusBar().showMessage(tr("window.status_nothing_to_undo"))
            return
        op, obj = self._undo_stack.pop()
        self._apply_inverse(op, obj)
        self._redo_stack.append((op, obj))
        self.klippen_anker_auffrischen()
        self._verlauf_auffrischen()

    def redo(self):
        if not self._redo_stack:
            self.statusBar().showMessage(tr("window.status_nothing_to_redo"))
            return
        op, obj = self._redo_stack.pop()
        self._apply_forward(op, obj)
        self._undo_stack.append((op, obj))
        self._verlauf_auffrischen()

    def _apply_inverse(self, op: str, obj):
        if op == "terrain":
            self._apply_terrain_changes(obj, forward=False)
            self.statusBar().showMessage(tr("terrain.status_undo", n=len(obj.changes)))
            return
        if op == "bereich":
            self._bereich_anwenden(obj, rueck=True)
            self._refresh_overview()
            return
        if op == "place":
            self._delete_object_silent(obj)
            self.statusBar().showMessage(tr("window.status_undo_place", display=obj.display))
        else:  # "remove" rueckgaengig -> Objekt wiederherstellen
            self._restore_object_silent(obj)
            self.statusBar().showMessage(tr("window.status_undo_remove", display=obj.display))
        self._refresh_overview()

    def _apply_forward(self, op: str, obj):
        if op == "terrain":
            self._apply_terrain_changes(obj, forward=True)
            self.statusBar().showMessage(tr("terrain.status_redo", n=len(obj.changes)))
            return
        if op == "bereich":
            self._bereich_anwenden(obj, rueck=False)
        elif op == "place":
            self._restore_object_silent(obj)
        else:
            self._delete_object_silent(obj)
        self._refresh_overview()

    def _delete_object_silent(self, obj: PlacedObject):
        if obj in self.objects:
            for item in obj.items:
                self.scene.removeItem(item)
            self.objects.remove(obj)
            if self._auswahl and self._auswahl[0] == "object":
                self._auswahl = None

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
        if kind in ("structure", "vehicle"):
            waffe = self.weapon_combo.currentData() if self.weapon_row.isVisible() else None
            geist = self._sprite_item(_map_id, self.player_spin.value(), tx, ty, alpha=0.75,
                                      waffe=waffe)
            if geist is not None:
                geist.setZValue(1049)
                rect.setBrush(Qt.NoBrush)
                self._placement_preview_items.append(geist)
        label = QGraphicsSimpleTextItem(display.split()[0][:10])
        label.setBrush(QBrush(Qt.white))
        label.setPos(x0 + 2, y0 + 1)
        # Vorschau-Beschriftung immer lesbar: feste Bildschirmgroesse,
        # unabhaengig vom Zoom (der Rahmen zeigt die echte Groesse).
        # Preview label always readable: constant screen size, independent of
        # zoom (the frame shows the real footprint).
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        label.setZValue(1051)
        self.scene.addItem(label)
        self._placement_preview_items = [rect, label]

    def _on_tile_hover(self, tx, ty):
        self.coord_label.setText(f"Tile: {tx}, {ty}")
        if self._terrain_active:
            self._update_terrain_preview(tx, ty)
            return
        if self._action_pick is not None and self._action_pick.get("kind") == "lava_paint":
            self._lava_update_brush_cursor(tx, ty)
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

    def _sprites(self):
        """Spielgrafik (lazy). None, wenn op2_art.prt/OP2_ART.BMP fehlen."""
        if getattr(self, "_sprite_satz", None) is None:
            from .sprites import SpriteSatz
            self._sprite_satz = SpriteSatz(OP2_DIR)
        return self._sprite_satz if self._sprite_satz.verfuegbar else None

    def _ist_plymouth(self, spieler: int) -> bool:
        if 0 <= spieler < len(self.players):
            return self.players[spieler].colony == Colony.Plymouth
        return False

    def _sprite_item(self, map_id, spieler, tx, ty, alpha=1.0, waffe=None):
        """QGraphicsPixmapItem mit der echten Grafik -- Eden oder Plymouth je
        nach Kolonie des Spielers, in seiner Spielerfarbe. None ohne Grafik."""
        satz = self._sprites()
        if satz is None:
            return None
        b = satz.bild(map_id, self._ist_plymouth(spieler), spieler, waffe)
        if b is None:
            return None
        pm, off = b
        it = QGraphicsPixmapItem(pm)
        it.setPos(tx * SCENE_TILE + SCENE_TILE / 2 + off.x(),
                  ty * SCENE_TILE + SCENE_TILE / 2 + off.y())
        # Weiter unten stehende Einheiten verdecken die oberen (wie im Spiel).
        it.setZValue(5 + ty * 0.001)
        it.setOpacity(alpha)
        self.scene.addItem(it)
        return it

    def _objekte_neu_zeichnen(self):
        """Alle Objekte neu zeichnen -- z.B. wenn ein Spieler die Kolonie
        (Eden/Plymouth) wechselt."""
        for o in self.objects:
            self._redraw_object(o)
        self._update_label_zoom()

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
        # Ein Doppelklick liefert zwei Klick-Ereignisse; ohne diese Sperre
        # oeffnet sich der Dialog zweimal hintereinander.
        # A double-click delivers two click events; without this guard the
        # dialog opens twice in a row.
        if self._object_dialog_open:
            return
        self._object_dialog_open = True
        try:
            dlg = ObjectEditDialog(self, obj, len(self.players))
            if dlg.exec() == QDialog.Accepted:
                alt = obj.unit_name
                dlg.apply_to(obj)
                self._redraw_object(obj)
                self._einheit_umbenannt(obj, alt)
                label = obj.unit_name or obj.display
                self.statusBar().showMessage(tr("window.status_updated", label=label))
        finally:
            self._object_dialog_open = False

    def _einheit_umbenannt(self, obj, alt):
        """Neuer Einheitenname -> Verweise (unitCmd, Bedingungen, Mine/Smelter
        der Mining-Gruppen) mitziehen, sofern der alte Name eindeutig war.
        Follow a unit rename in unit_ref/target_unit/mine_ref/smelter_ref."""
        neu = obj.unit_name
        felder = ("unit_ref", "target_unit", "mine_ref", "smelter_ref")
        if not alt or alt == neu:
            return
        if any(o is not obj and o.unit_name == alt for o in self.objects):
            return              # alter Name weiter vergeben -> Verweise stimmen
        if not neu:
            # Name geloescht: haengen noch Verweise daran, fragen statt sie
            # ins Leere zeigen zu lassen. alt -> alt zaehlt nur.
            # Name cleared: if references remain, ask instead of leaving them
            # dangling. Renaming alt -> alt only counts them.
            n = self._verweise_umbenennen(felder, alt, alt)
            if not n:
                return
            if self._name_loeschen_fragen(alt, n):
                self._verweise_umbenennen(felder, alt, "")
                self.statusBar().showMessage(tr("window.status_unit_refs_cleared", alt=alt, n=n))
            else:
                obj.unit_name = alt
                self._redraw_object(obj)
                self.statusBar().showMessage(tr("window.status_unit_name_kept", alt=alt))
                return
            self.trigger_panel.refresh_actions()
            self.conditions_panel.load()
            self.groups_panel.load()
            self._refresh_overview()
            return
        if any(o is not obj and o.unit_name == neu for o in self.objects):
            return
        n = self._verweise_umbenennen(felder, alt, neu)
        if n:
            self.trigger_panel.refresh_actions()
            self.conditions_panel.load()
            self.groups_panel.load()
            self._refresh_overview()
            self.statusBar().showMessage(tr("outline.status_renamed_unit", alt=alt, neu=neu, n=n))

    def _name_loeschen_fragen(self, alt, n) -> bool:
        """True = Verweise leeren, False = Namen behalten."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(tr("window.unit_name_cleared_title"))
        box.setText(tr("window.unit_name_cleared_text", alt=alt, n=n))
        behalten = box.addButton(tr("window.unit_name_keep"), QMessageBox.RejectRole)
        box.addButton(tr("window.unit_refs_clear"), QMessageBox.DestructiveRole)
        box.setDefaultButton(behalten)
        box.exec()
        return box.clickedButton() is not behalten

    def on_place(self, tx, ty):
        if self._action_pick and self._action_pick.get("kind") == "lava_paint":
            self._lava_stamp(tx, ty, add=True)
            return
        # Sieg-/Niederlage-Bedingung: Punkt per Klick setzen (point-Kind).
        # Victory/defeat condition: set the point via click (point kind).
        if self._action_pick and self._action_pick["kind"] == "cond_field" \
                and self._action_pick.get("field") == "point":
            if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
                return
            cond = self._action_pick["cond"]
            cond.x, cond.y = tx, ty
            self.statusBar().showMessage(tr("window.status_cond_point_set", x=tx, y=ty))
            self._end_action_pick()
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
                if getattr(action, "kind", "") == "createUnit":
                    # Der Klick setzt die Einheit direkt in die Liste -- vorher
                    # landeten nur X/Y in der Eingabezeile, und das "+" dazu
                    # lag im schmalen Seitenbereich ausserhalb des Sichtfelds.
                    # The click adds the unit to the list right away.
                    liste = list(getattr(action, "unit_list", None) or [])
                    liste.append({"unit_type": action.unit_type or "mapLynx",
                                  "weapon_type": getattr(action, "weapon_type", "") or "mapNone",
                                  "x": tx, "y": ty})
                    action.unit_list = liste
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
            self._karte_klick(tx, ty)
            return
        sel = self._selected()
        if not sel:
            return
        kind, disp, mid, fp = sel
        params = {}
        if mid == "mapCargoTruck":
            raw_cargo = self.cargo_combo.currentData() or "truckEmpty"
            if ":" in raw_cargo:
                truck_cargo, part = raw_cargo.split(":", 1)
                params["truck_cargo"] = truck_cargo
                params["truck_amount"] = part
            else:
                params["truck_cargo"] = raw_cargo
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
        if self._terrain_active:
            self._terrain_pick(tx, ty)
            return
        if self._action_pick is not None and self._action_pick.get("kind") == "lava_paint":
            self._lava_stamp(tx, ty, add=False)
            return
        if self._action_pick is not None:
            self._end_action_pick()
            self.statusBar().showMessage(tr("window.status_action_canceled"))
            return
        # Rechtsklick entfernt das Objekt unter dem Zeiger -- auch waehrend
        # des Platzierens. Frueher brach jeder Rechtsklick zuerst den
        # Platziermodus ab; der Katalogeintrag blieb dabei markiert, sodass
        # die Oberflaeche weiter "scharf" aussah, Linksklicks aber nur noch
        # den Objekt-Editor oeffneten.
        # Right-click removes the object under the cursor -- while placing,
        # too. Previously every right-click cancelled placement first, leaving
        # the catalog entry highlighted so the UI still looked armed while
        # left-clicks only opened the object editor.
        obj = self._object_at(tx, ty)
        if obj is None:
            # Auf leerer Flaeche passiert bewusst NICHTS mehr. Frueher brach
            # der Rechtsklick hier den Platziermodus ab -- ein Klick daneben
            # beendete das Platzieren, ohne dass man es sah. Abbrechen macht
            # jetzt Esc.
            # On empty ground nothing happens on purpose. This right-click used
            # to cancel placement -- one click beside the target ended placing
            # invisibly. Esc is the cancel now.
            if self._placement_active:
                self.statusBar().showMessage(tr("window.status_nothing_to_remove"))
            return
        if obj is not None:
            for item in obj.items:
                self.scene.removeItem(item)
            self.objects.remove(obj)
            # Objekt-Auswahl laeuft ueber den Index -- nach dem Entfernen
            # zeigte sie sonst auf das naechste Objekt.
            # Object selection is by index; it would now point at the next one.
            if self._auswahl and self._auswahl[0] == "object":
                self._auswahl = None
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
        sprite = self._sprite_item(obj.map_id, obj.player, obj.tile_x, obj.tile_y,
                                   waffe=(obj.params or {}).get("weapon")) \
            if obj.kind in ("structure", "vehicle") else None
        if sprite is not None:
            # Echte Grafik: das Rechteck bleibt nur als feiner Rahmen der
            # belegten Kacheln in Spielerfarbe.
            # Real graphics: the rect stays as a thin footprint outline.
            pen = QPen(QColor(color.red(), color.green(), color.blue(), 150), 1)
            pen.setCosmetic(True)
            rect.setPen(pen)
            rect.setBrush(Qt.NoBrush)
        else:
            rect.setPen(QPen(color, 2))
            rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 120)))
        self.scene.addItem(rect)
        text = obj.unit_name or obj.display.split()[0]
        label = QGraphicsSimpleTextItem(text[:10])
        label.setBrush(QBrush(Qt.black if obj.kind == "beacon" else Qt.white))
        label.setPos(x0 + 2, y0 + 1)
        self._style_map_label(label)
        if sprite is not None and not obj.unit_name:
            # Mit echter Grafik ist der Typ zu sehen -- Beschriftung nur fuer
            # benannte Einheiten. / With real graphics only named units get a label.
            label.setData(1, "ohne")
            label.setVisible(False)
        self.scene.addItem(label)
        # Weit herausgezoomt: Punkt in Spielerfarbe in fester Bildschirmgroesse,
        # damit Objekte nicht zu Kruemeln werden.
        # Zoomed far out: a constant-size dot in the player colour.
        marke = QGraphicsEllipseItem(-5, -5, 10, 10)
        marke.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        marke.setPos(obj.tile_x * SCENE_TILE + SCENE_TILE / 2,
                     obj.tile_y * SCENE_TILE + SCENE_TILE / 2)
        marke.setBrush(QBrush(color))
        marke.setPen(QPen(QColor(17, 17, 27), 1.5))
        marke.setZValue(1090)
        marke.setData(0, "marke")
        self.scene.addItem(marke)
        obj.items = [rect, label, marke] + ([sprite] if sprite is not None else [])
        an = self._objekte_sichtbar
        for it in obj.items:
            it.setVisible(an and it.isVisible())
        marke.setVisible(an and self.view.tile_screen_px() < MapView.LABEL_MIN_TILE_PX)

    # --- Beschriftungen auf der Karte / map labels ---------------------

    def _style_map_label(self, label):
        """Beschriftung in fester Bildschirmgroesse zeichnen und bei starkem
        Herauszoomen ausblenden (sonst unlesbare Kruemel bzw. Ueberlappung).

        Draw the label at a constant screen size and hide it when zoomed far
        out (otherwise unreadable specks resp. overlapping text)."""
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        label.setZValue(1100)
        label.setVisible(self.view.tile_screen_px() >= MapView.LABEL_MIN_TILE_PX)

    def _update_label_zoom(self, *_args):
        """Sichtbarkeit aller Kartenbeschriftungen an den Zoom anpassen.

        Update the visibility of all map labels for the current zoom."""
        visible = self.view.tile_screen_px() >= MapView.LABEL_MIN_TILE_PX
        an = self._objekte_sichtbar
        for obj in self.objects:
            for item in obj.items:
                if isinstance(item, QGraphicsSimpleTextItem):
                    item.setVisible(an and visible and item.data(1) != "ohne")
                elif item.data(0) == "marke":
                    item.setVisible(an and not visible)

    def clear_objects_fragen(self):
        """Alle Objekte und Gruppen loeschen -- erst nach Rueckfrage."""
        n = len(self.objects)
        g = (len(self.building_groups) + len(self.reinforce_groups)
             + len(self.fight_groups) + len(self.mining_groups))
        if QMessageBox.question(
                self, tr("window.clear_confirm_title"),
                tr("window.clear_confirm_text", n=n, g=g),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.clear_objects()

    def clear_objects(self):
        self._editor_schliessen()
        for obj in self.objects:
            for it in obj.items:
                self.scene.removeItem(it)
        self.objects.clear()
        self._clear_undo()
        self.building_groups.clear()
        self.reinforce_groups.clear()
        self.fight_groups.clear()
        self.mining_groups.clear()      # fehlte: Mining-Gruppen blieben stehen
        self.groups_panel.load()
        self._refresh_overview()
        self.statusBar().showMessage(tr("window.status_objects_cleared"))
