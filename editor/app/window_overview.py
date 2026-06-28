from __future__ import annotations

from .common import *


class _OverviewMixin:
    def _build_overview(self):
        dock = QDockWidget(tr("window.dock_overview"), self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        bar = QHBoxLayout()
        add_btn = QPushButton(tr("window.add_trigger_btn")); add_btn.clicked.connect(self._add_trigger)
        bar.addWidget(add_btn); bar.addStretch(1)
        lay.addLayout(bar)
        self.overview = QTreeWidget()
        self.overview.setHeaderHidden(True)
        self.overview.itemDoubleClicked.connect(self._overview_activated)
        lay.addWidget(self.overview, 1)
        lay.addWidget(QLabel(tr("window.overview_hint")))
        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _ov_add(self, parent, text, kind=None, index=None, sub=None):
        item = QTreeWidgetItem([text])
        if kind is not None:
            item.setData(0, Qt.UserRole, (kind, index, sub))
        if isinstance(parent, QTreeWidgetItem):
            parent.addChild(item)
        else:
            parent.addTopLevelItem(item)
        return item

    def _add_trigger(self):
        name = f"Trigger{len(self.triggers) + 1}"
        self.triggers.append(TriggerDef(name=name))
        self._refresh_overview()
        self.statusBar().showMessage(tr("window.status_trigger_added", name=name))

    def _trigger_cond_text(self, t):
        return tr(f"trigger_conditions.{t.condition}")

    def _add_flow_trigger(self, parent, ti, path, prefix=""):
        t = self.triggers[ti]
        tag = "[Start] " if t.enabled_at_start else ""
        item = self._ov_add(parent, f"{prefix}{tag}{t.name}  ({self._trigger_cond_text(t)})",
                             "triggers", ti)
        new_path = path | {ti}
        for ai, a in enumerate(t.actions):
            if a.kind == "createTrigger" and a.target in self._trig_idx_by_name:
                tgt = self._trig_idx_by_name[a.target]
                if tgt in new_path:
                    self._ov_add(item, f"⟶ {a.target} {tr('window.see_above')}", "triggers", tgt)
                else:
                    self._add_flow_trigger(item, tgt, new_path, prefix="⟶ ")
            else:
                self._ov_add(item, "· " + action_summary(a), "triggers", ti, ai)
        return item

    def _refresh_overview(self):
        if not hasattr(self, "overview"):
            return
        expanded = {self.overview.topLevelItem(i).text(0).split(" (")[0]
                    for i in range(self.overview.topLevelItemCount())
                    if self.overview.topLevelItem(i).isExpanded()}
        self.overview.clear()
        self._trig_idx_by_name = {t.name: i for i, t in enumerate(self.triggers)}
        created = {a.target for t in self.triggers for a in t.actions
                   if a.kind == "createTrigger" and a.target}

        sec_flow = self._ov_add(self.overview, tr("window.ov_flow", n=len(self.triggers)))
        for i, t in enumerate(self.triggers):
            if t.enabled_at_start:
                self._add_flow_trigger(sec_flow, i, set())
        for i, t in enumerate(self.triggers):
            if not t.enabled_at_start and t.name not in created:
                self._add_flow_trigger(sec_flow, i, set(), prefix=tr("window.unbound_prefix") + " ")

        sec_players = self._ov_add(self.overview, tr("window.ov_players", n=len(self.players)))
        for i, p in enumerate(self.players):
            colony = "Eden" if p.colony == Colony.Eden else "Plymouth"
            self._ov_add(sec_players,
                         tr("players.list_label", i=i, colony=colony,
                            type=(tr("players.human") if p.is_human else tr("players.ai")),
                            tech=p.tech_level),
                         "players", i)

        groups_total = len(self.building_groups) + len(self.reinforce_groups)
        sec_groups = self._ov_add(self.overview, tr("window.ov_groups", n=groups_total))
        for g in self.building_groups:
            self._ov_add(sec_groups, building_group_summary(g), "groups")
        for g in self.reinforce_groups:
            self._ov_add(sec_groups, reinforce_group_summary(g), "groups")

        sec_cond = self._ov_add(self.overview,
                                tr("window.ov_conditions", w=len(self.victories), l=len(self.defeats)))
        for c in self.victories:
            self._ov_add(sec_cond, tr("window.ov_victory", s=condition_summary(c)), "conditions")
        for c in self.defeats:
            self._ov_add(sec_cond, tr("window.ov_defeat", s=condition_summary(c)), "conditions")

        sec_obj = self._ov_add(self.overview, tr("window.ov_objects", n=len(self.objects)))
        for oi, o in enumerate(self.objects):
            name = f"{o.unit_name}: " if getattr(o, "unit_name", "") else ""
            self._ov_add(sec_obj, f"{name}{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})",
                         "objects", oi)

        for i in range(self.overview.topLevelItemCount()):
            it = self.overview.topLevelItem(i)
            it.setExpanded(not expanded or it.text(0).split(" (")[0] in expanded)
        sec_flow.setExpanded(True)

    def _overview_activated(self, item, _col=0):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, index, sub = data
        if kind == "players":
            self.edit_players()
        elif kind == "groups":
            self.edit_groups()
        elif kind == "conditions":
            self.edit_conditions()
        elif kind == "triggers":
            self._pending_trigger_index = index if index is not None else 0
            self._pending_action_index = sub if sub is not None else -1
            self.edit_triggers()
        elif kind == "objects" and index is not None and 0 <= index < len(self.objects):
            o = self.objects[index]
            self.view.centerOn(o.tile_x * SCENE_TILE, o.tile_y * SCENE_TILE)
            self._edit_object_at(o.tile_x, o.tile_y)
