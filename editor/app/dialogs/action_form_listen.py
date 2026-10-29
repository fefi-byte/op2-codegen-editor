"""Listen im Aktionsformular: hinzufuegen, entfernen, laden, auslesen.

Aus `action_editor.py` herausgeloest; `action_editor` reicht die oeffentlichen
Klassen weiter.

Lists inside the action form: add, remove, load, read.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox

from ..common import *
from ..summary import action_kind_label, action_params_summary
from ..style import (ACTION_CATEGORY_COLOR, ACTION_SECTION_COLOR, CONDITION_SECTION_COLOR,
                     IF_LOOP_COLOR, SURFACE1, apply_role, tint_button_stylesheet, tint_stylesheet)


class _ListenMixin:
    """Listenhelfer (Wegpunkte, Wellen, Bauten, ...); von ActionInlineForm geerbt."""

    def _patrol_points(self) -> list:
        return [self.patrol_list.topLevelItem(i).data(0, Qt.UserRole)
                for i in range(self.patrol_list.topLevelItemCount())]

    def _patrol_refresh(self, points):
        self.patrol_list.clear()
        for n, (px, py) in enumerate(points[:8], 1):
            item = QTreeWidgetItem([str(n), str(px), str(py)])
            item.setData(0, Qt.UserRole, [int(px), int(py)])
            self.patrol_list.addTopLevelItem(item)

    def _patrol_add(self):
        pts = self._patrol_points()
        if len(pts) >= 8:
            return
        pts.append([self.patrol_x.value(), self.patrol_y.value()])
        self._patrol_refresh(pts)
        self._save()

    def _patrol_remove(self):
        idx = self.patrol_list.indexOfTopLevelItem(self.patrol_list.currentItem())
        if idx >= 0:
            pts = self._patrol_points()
            del pts[idx]
            self._patrol_refresh(pts)
            self._save()

    def _patrol_move(self, delta):
        idx = self.patrol_list.indexOfTopLevelItem(self.patrol_list.currentItem())
        pts = self._patrol_points()
        j = idx + delta
        if idx < 0 or not (0 <= j < len(pts)):
            return
        pts[idx], pts[j] = pts[j], pts[idx]
        self._patrol_refresh(pts)
        self.patrol_list.setCurrentItem(self.patrol_list.topLevelItem(j))
        self._save()

    def _targ_add(self):
        count = self.targ_count_edit.value()
        item = QTreeWidgetItem([
            self.targ_unit.currentText(), self.targ_weapon.currentText(), str(count)])
        item.setData(0, Qt.UserRole, (self.targ_unit.currentData(),
                                      self.targ_weapon.currentData(), count))
        self.targ_list.addTopLevelItem(item)
        self._save()

    def _targ_remove(self):
        idx = self.targ_list.indexOfTopLevelItem(self.targ_list.currentItem())
        if idx >= 0:
            self.targ_list.takeTopLevelItem(idx)
            self._save()

    def _targ_counts_from_list(self) -> list:
        out = []
        for i in range(self.targ_list.topLevelItemCount()):
            unit, weapon, count = self.targ_list.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"unit_type": unit, "weapon_type": weapon, "count": count})
        return out

    def _targ_list_load(self, targ_counts):
        self.targ_list.clear()
        by_id_weapon = {m: d for d, m in WEAPONS}
        for e in (targ_counts or []):
            unit = e.get("unit_type", "mapConVec")
            weapon = e.get("weapon_type", "mapNone")
            count = e.get("count", 1)
            unit_label = unit
            i = self.targ_unit.findData(unit)
            if i >= 0:
                unit_label = self.targ_unit.itemText(i)
            item = QTreeWidgetItem([unit_label, by_id_weapon.get(weapon, weapon), str(count)])
            item.setData(0, Qt.UserRole, (unit, weapon, count))
            self.targ_list.addTopLevelItem(item)

    def _song_add(self):
        s = self.song_combo.currentData()
        if s:
            self.song_list.addItem(s)
            self._save()

    def _song_remove(self):
        row = self.song_list.currentRow()
        if row >= 0:
            self.song_list.takeItem(row)
            self._save()

    def _songs_from_list(self) -> list:
        return [self.song_list.item(i).text() for i in range(self.song_list.count())]

    def _song_list_load(self, songs):
        self.song_list.clear()
        for s in (songs or []):
            self.song_list.addItem(str(s))

    def _stats_add(self):
        stat = self.stat_combo.currentData()
        if not stat:
            return
        item = QTreeWidgetItem([self.stat_combo.currentText(), str(self.stat_value.value())])
        item.setData(0, Qt.UserRole, (stat, self.stat_value.value()))
        self.stats_tree.addTopLevelItem(item)
        self._save()

    def _stats_remove(self):
        idx = self.stats_tree.indexOfTopLevelItem(self.stats_tree.currentItem())
        if idx >= 0:
            self.stats_tree.takeTopLevelItem(idx)
            self._save()

    def _stats_from_tree(self) -> list:
        out = []
        for i in range(self.stats_tree.topLevelItemCount()):
            stat, value = self.stats_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"stat": stat, "value": value})
        return out

    def _stats_list_load(self, stat_mods):
        self.stats_tree.clear()
        for m in (stat_mods or []):
            stat = m.get("stat", "")
            if not stat:
                continue
            i = self.stat_combo.findData(stat)
            label = self.stat_combo.itemText(i) if i >= 0 else stat
            item = QTreeWidgetItem([label, str(m.get("value", 0))])
            item.setData(0, Qt.UserRole, (stat, m.get("value", 0)))
            self.stats_tree.addTopLevelItem(item)

    def _rz_add(self):
        vals = (self.rz_x.value(), self.rz_y.value(), self.rz_x2.value(), self.rz_y2.value())
        item = QTreeWidgetItem([str(v) for v in vals])
        item.setData(0, Qt.UserRole, vals)
        self.repair_zones_tree.addTopLevelItem(item)
        self._save()

    def _rz_remove(self):
        idx = self.repair_zones_tree.indexOfTopLevelItem(self.repair_zones_tree.currentItem())
        if idx >= 0:
            self.repair_zones_tree.takeTopLevelItem(idx)
            self._save()

    def _rz_from_tree(self) -> list:
        out = []
        for i in range(self.repair_zones_tree.topLevelItemCount()):
            x, y, x2, y2 = self.repair_zones_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"x": x, "y": y, "x2": x2, "y2": y2})
        return out

    def _rz_load(self, zones):
        self.repair_zones_tree.clear()
        for z in (zones or []):
            vals = (int(z.get("x", 0)), int(z.get("y", 0)),
                    int(z.get("x2", 0)), int(z.get("y2", 0)))
            item = QTreeWidgetItem([str(v) for v in vals])
            item.setData(0, Qt.UserRole, vals)
            self.repair_zones_tree.addTopLevelItem(item)

    def _rth_add(self):
        item = QTreeWidgetItem([self.rth_building.currentText(), str(self.rth_damage.value())])
        item.setData(0, Qt.UserRole, (self.rth_building.currentData(), self.rth_damage.value()))
        self.repair_thresholds_tree.addTopLevelItem(item)
        self._save()

    def _rth_remove(self):
        idx = self.repair_thresholds_tree.indexOfTopLevelItem(
            self.repair_thresholds_tree.currentItem())
        if idx >= 0:
            self.repair_thresholds_tree.takeTopLevelItem(idx)
            self._save()

    def _rth_from_tree(self) -> list:
        out = []
        for i in range(self.repair_thresholds_tree.topLevelItemCount()):
            bt, dmg = self.repair_thresholds_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"building_type": bt, "damage": dmg})
        return out

    def _rth_load(self, thresholds):
        self.repair_thresholds_tree.clear()
        by_id_building = {m: d for d, m, _ in STRUCTURES}
        for t in (thresholds or []):
            bt = t.get("building_type", "mapTokamak")
            dmg = int(t.get("damage", 200))
            item = QTreeWidgetItem([by_id_building.get(bt, bt), str(dmg)])
            item.setData(0, Qt.UserRole, (bt, dmg))
            self.repair_thresholds_tree.addTopLevelItem(item)

    def _wave_add(self):
        item = QTreeWidgetItem([
            self.wave_unit.currentText(), self.wave_weapon.currentText(),
            str(self.wave_count.value())])
        item.setData(0, Qt.UserRole, (self.wave_unit.currentData(),
                                      self.wave_weapon.currentData(),
                                      self.wave_count.value()))
        self.wave_list.addTopLevelItem(item)
        self._save()

    def _wave_remove(self):
        idx = self.wave_list.indexOfTopLevelItem(self.wave_list.currentItem())
        if idx >= 0:
            self.wave_list.takeTopLevelItem(idx)
            self._save()

    def _wave_units_from_list(self) -> list:
        out = []
        for i in range(self.wave_list.topLevelItemCount()):
            unit, weapon, count = self.wave_list.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"unit_type": unit, "weapon_type": weapon, "count": count})
        return out

    def _wave_list_load(self, wave_units):
        self.wave_list.clear()
        by_id_unit = {m: d for d, m in MILITARY_VEHICLES}
        by_id_weapon = {m: d for d, m in WEAPONS}
        for w in (wave_units or []):
            unit = w.get("unit_type", "mapLynx")
            weapon = w.get("weapon_type", "mapLaser")
            count = int(w.get("count", 1) or 1)
            item = QTreeWidgetItem([
                by_id_unit.get(unit, unit), by_id_weapon.get(weapon, weapon), str(count)])
            item.setData(0, Qt.UserRole, (unit, weapon, count))
            self.wave_list.addTopLevelItem(item)

    def _cu_add(self):
        item = QTreeWidgetItem([
            self.cu_unit.currentText(), self.cu_weapon.currentText(),
            str(self.cu_x.value()), str(self.cu_y.value())])
        item.setData(0, Qt.UserRole, (self.cu_unit.currentData(), self.cu_weapon.currentData(),
                                      self.cu_x.value(), self.cu_y.value()))
        self.unit_list_tree.addTopLevelItem(item)
        self._save()

    def _cu_remove(self):
        idx = self.unit_list_tree.indexOfTopLevelItem(self.unit_list_tree.currentItem())
        if idx >= 0:
            self.unit_list_tree.takeTopLevelItem(idx)
            self._save()

    def _unit_list_from_tree(self) -> list:
        out = []
        for i in range(self.unit_list_tree.topLevelItemCount()):
            unit, weapon, x, y = self.unit_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"unit_type": unit, "weapon_type": weapon, "x": x, "y": y})
        return out

    def _unit_list_load(self, entries):
        self.unit_list_tree.clear()
        by_id_unit = {m: d for d, m in ALL_UNITS}
        by_id_weapon = {m: d for d, m in WEAPONS}
        for e in (entries or []):
            unit = e.get("unit_type", "mapScout")
            weapon = e.get("weapon_type", "mapNone")
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            item = QTreeWidgetItem([
                by_id_unit.get(unit, unit), by_id_weapon.get(weapon, weapon), str(x), str(y)])
            item.setData(0, Qt.UserRole, (unit, weapon, x, y))
            self.unit_list_tree.addTopLevelItem(item)

    def _rb_add(self):
        name = self.rb_name.text().strip()
        item = QTreeWidgetItem([
            self.rb_building.currentText(), self.rb_weapon.currentText(),
            str(self.rb_x.value()), str(self.rb_y.value()), name])
        item.setData(0, Qt.UserRole, (self.rb_building.currentData(), self.rb_weapon.currentData(),
                                      self.rb_x.value(), self.rb_y.value(), name))
        self.building_list_tree.addTopLevelItem(item)
        self.rb_name.clear()
        self._save()

    def _rb_remove(self):
        idx = self.building_list_tree.indexOfTopLevelItem(self.building_list_tree.currentItem())
        if idx >= 0:
            self.building_list_tree.takeTopLevelItem(idx)
            self._save()

    def _building_list_from_tree(self) -> list:
        out = []
        for i in range(self.building_list_tree.topLevelItemCount()):
            data = self.building_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            building, weapon, x, y = data[0], data[1], data[2], data[3]
            name = data[4] if len(data) > 4 else ""
            out.append({"building_type": building, "weapon_type": weapon,
                        "x": x, "y": y, "unit_name": name})
        return out

    def _building_list_load(self, entries):
        self.building_list_tree.clear()
        by_id_building = {m: d for d, m, _ in STRUCTURES}
        by_id_weapon = {m: d for d, m in WEAPONS}
        for e in (entries or []):
            building = e.get("building_type", "mapCommandCenter")
            weapon = e.get("weapon_type", "mapNone")
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            name = (e.get("unit_name", "") or "").strip()
            item = QTreeWidgetItem([
                by_id_building.get(building, building), by_id_weapon.get(weapon, weapon),
                str(x), str(y), name])
            item.setData(0, Qt.UserRole, (building, weapon, x, y, name))
            self.building_list_tree.addTopLevelItem(item)

    def _rt_add(self):
        item = QTreeWidgetItem([
            str(self.rt_x.value()), str(self.rt_y.value()),
            str(self.rt_x2.value()), str(self.rt_y2.value())])
        item.setData(0, Qt.UserRole, (self.rt_x.value(), self.rt_y.value(),
                                      self.rt_x2.value(), self.rt_y2.value()))
        self.tube_list_tree.addTopLevelItem(item)
        self._save()

    def _rt_remove(self):
        idx = self.tube_list_tree.indexOfTopLevelItem(self.tube_list_tree.currentItem())
        if idx >= 0:
            self.tube_list_tree.takeTopLevelItem(idx)
            self._save()

    def _tube_list_from_tree(self) -> list:
        out = []
        for i in range(self.tube_list_tree.topLevelItemCount()):
            x, y, x2, y2 = self.tube_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"x": x, "y": y, "x2": x2, "y2": y2})
        return out

    def _tube_list_load(self, entries):
        self.tube_list_tree.clear()
        for e in (entries or []):
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            x2 = int(e.get("x2", 0) or 0)
            y2 = int(e.get("y2", 0) or 0)
            item = QTreeWidgetItem([str(x), str(y), str(x2), str(y2)])
            item.setData(0, Qt.UserRole, (x, y, x2, y2))
            self.tube_list_tree.addTopLevelItem(item)

    def _rw_add(self):
        item = QTreeWidgetItem([
            self.rw_wall.currentText(), str(self.rw_x.value()), str(self.rw_y.value()),
            str(self.rw_x2.value()), str(self.rw_y2.value())])
        item.setData(0, Qt.UserRole, (self.rw_wall.currentData(), self.rw_x.value(), self.rw_y.value(),
                                      self.rw_x2.value(), self.rw_y2.value()))
        self.wall_list_tree.addTopLevelItem(item)
        self._save()

    def _rw_remove(self):
        idx = self.wall_list_tree.indexOfTopLevelItem(self.wall_list_tree.currentItem())
        if idx >= 0:
            self.wall_list_tree.takeTopLevelItem(idx)
            self._save()

    def _wall_list_from_tree(self) -> list:
        out = []
        for i in range(self.wall_list_tree.topLevelItemCount()):
            wall, x, y, x2, y2 = self.wall_list_tree.topLevelItem(i).data(0, Qt.UserRole)
            out.append({"wall_type": wall, "x": x, "y": y, "x2": x2, "y2": y2})
        return out

    def _wall_list_load(self, entries):
        self.wall_list_tree.clear()
        by_id_wall = {m: d for d, m, _ in WALL_ITEMS}
        for e in (entries or []):
            wall = e.get("wall_type", "mapWall")
            x = int(e.get("x", 0) or 0)
            y = int(e.get("y", 0) or 0)
            x2 = int(e.get("x2", 0) or 0)
            y2 = int(e.get("y2", 0) or 0)
            item = QTreeWidgetItem([
                by_id_wall.get(wall, wall), str(x), str(y), str(x2), str(y2)])
            item.setData(0, Qt.UserRole, (wall, x, y, x2, y2))
            self.wall_list_tree.addTopLevelItem(item)

    def _pick_mine_from_list(self):
        data = self.mine_pick.currentData()
        if data:
            self.x.setValue(data[0])
            self.y.setValue(data[1])
        self._update_mining_wait_hint()

    def _pick_smelter_from_list(self):
        data = self.smelter_pick.currentData()
        if data:
            self.x2.setValue(data[0])
            self.y2.setValue(data[1])
        self._update_mining_wait_hint()

    def _update_mining_wait_hint(self):
        # Mine/Smelter kommen jetzt aus der Gruppen-Definition (benannte
        # Anker); der Hinweis erklaert den neuen Ablauf statisch.
        # Mine/smelter now come from the group definition (named anchors);
        # the hint explains the new flow statically.
        self.mining_wait_hint.setText(tr("action_editor.mining_wait_hint"))
