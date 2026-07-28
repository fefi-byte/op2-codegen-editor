from __future__ import annotations

from .common import *
from .panels.validation_panel import ValidationPanel


class _OverviewMixin:
    def _build_overview(self):
        self._build_validation_dock()
        dock = QDockWidget(tr("window.dock_overview"), self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        self.overview = QTreeWidget()
        self.overview.setHeaderHidden(True)
        self.overview.itemDoubleClicked.connect(self._overview_activated)
        lay.addWidget(self.overview, 1)
        # Kennzahlen statt eigener Baumabschnitte: Spieler/Gruppen/Objekte/
        # Sieg-Niederlage haben je einen eigenen Sidebar-Tab -- der Baum zeigt
        # nur noch den Ablauf.
        # Key figures instead of separate tree sections: players/groups/objects/
        # victory-defeat each have their own sidebar tab -- the tree now shows
        # the flow only.
        self.overview_stats = QLabel("")
        self.overview_stats.setWordWrap(True)
        self.overview_stats.setProperty("secondary", "true")
        lay.addWidget(self.overview_stats)
        hint = QLabel(tr("window.overview_hint"))
        hint.setWordWrap(True)
        hint.setProperty("secondary", "true")
        lay.addWidget(hint)
        dock.setWidget(panel)
        # Die Uebersicht ist ein Begleiter, kein Hauptbereich -- schmal halten
        # und der Karte den Platz lassen (per Splitter jederzeit breiter).
        # The overview is a companion, not a main area -- keep it narrow and
        # leave the room to the map (widen via the splitter any time).
        dock.setMinimumWidth(150)
        self.overview_dock = dock
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.resizeDocks([dock], [230], Qt.Horizontal)
        self._add_dock_toggles()

    def _add_dock_toggles(self):
        """Ein-/Ausblenden der Docks ueber das Ansicht-Menue anbieten.

        Offer showing/hiding the docks from the View menu."""
        menu = getattr(self, "_view_menu", None)
        if menu is None:
            return
        menu.addSeparator()
        for dock, key in ((self.overview_dock, "window.dock_overview"),
                          (self.validation_dock, "window.dock_validation")):
            act = dock.toggleViewAction()
            act.setText(tr(key))
            menu.addAction(act)

    def _build_validation_dock(self):
        # Unten statt rechts: die Warnliste ist kurz und breit, rechts hat sie
        # die halbe Hoehe der Uebersicht belegt.
        # At the bottom instead of the right: the warning list is short and
        # wide; on the right it used to eat half the overview's height.
        dock = QDockWidget(tr("window.dock_validation"), self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.validation_panel = ValidationPanel(self)
        dock.setWidget(self.validation_panel)
        self.validation_dock = dock
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [120], Qt.Vertical)

    def _ov_add(self, parent, text, kind=None, index=None, sub=None):
        item = QTreeWidgetItem([text])
        if kind is not None:
            item.setData(0, Qt.UserRole, (kind, index, sub))
        if isinstance(parent, QTreeWidgetItem):
            parent.addChild(item)
        else:
            parent.addTopLevelItem(item)
        return item

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
        if hasattr(self, "objects_panel"):
            self.objects_panel.refresh()
        if hasattr(self, "validation_panel"):
            self.validation_panel.refresh()
        if hasattr(self, "_overlay_items"):
            self._refresh_overlays()
        # Geplante Gebaeude/Leitungen aus Trigger-Aktionen neu zeichnen --
        # jede Trigger-/Aktions-Aenderung laeuft ueber _refresh_overview.
        # Redraw planned buildings/lines from trigger actions -- every
        # trigger/action edit goes through _refresh_overview.
        if hasattr(self, "_planned_items"):
            self._redraw_planned_actions()
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

        groups_total = (len(self.building_groups) + len(self.reinforce_groups)
                        + len(self.fight_groups) + len(self.mining_groups))
        self.overview_stats.setText(tr(
            "window.ov_stats", p=len(self.players), g=groups_total,
            o=len(self.objects), w=len(self.victories), l=len(self.defeats)))

        for i in range(self.overview.topLevelItemCount()):
            it = self.overview.topLevelItem(i)
            it.setExpanded(not expanded or it.text(0).split(" (")[0] in expanded)
        sec_flow.setExpanded(True)

    def _overview_activated(self, item, _col=0):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        # Der Baum enthaelt nur noch Trigger-Eintraege; Spieler/Gruppen/
        # Objekte/Sieg-Niederlage haben je einen eigenen Sidebar-Tab.
        # The tree only holds trigger entries now; players/groups/objects/
        # victory-defeat each have their own sidebar tab.
        kind, index, sub = data
        if kind == "triggers":
            self._pending_trigger_index = index if index is not None else 0
            self._pending_action_index = sub if sub is not None else -1
            self.edit_triggers()
