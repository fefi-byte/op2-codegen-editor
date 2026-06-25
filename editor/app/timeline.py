"""Interaktive Missions-Timeline / Node-Canvas (Node-RED-artig).

Trigger und Gruppen sind Knoten; Aktionen, die etwas referenzieren, werden als
gerichtete Verbindungen (Draehte) gezeichnet. Knoten sind verschiebbar,
Doppelklick oeffnet den passenden Editor, im Verbinden-Modus zieht man neue
Verbindungen (Trigger -> Trigger / Trigger -> Gruppe).

Interactive mission timeline / node canvas (Node-RED-style).

Triggers and groups are nodes; actions that reference something are drawn as
directed connections (wires). Nodes can be moved, a double-click opens the
matching editor, and in connect mode you drag new connections
(trigger -> trigger / trigger -> group).
"""
from __future__ import annotations

from .common import *

NODE_W = 180
NODE_H = 56
COL_X_TRIGGERS = 20
COL_X_GROUPS = 280
Y_GAP = 92
Y_START = 20

NODE_COLORS = {
    "trigger_start": QColor(70, 130, 200),
    "trigger": QColor(95, 95, 125),
    "mining": QColor(200, 150, 60),
    "building": QColor(80, 160, 90),
    "reinforce": QColor(165, 95, 165),
}
WIRE_COLORS = {
    "createTrigger": QColor(120, 200, 255),
    "assignToGroup": QColor(255, 210, 90),
    "startMiningOperation": QColor(255, 170, 70),
    "setTargCount": QColor(140, 230, 140),
    "recordBuilding": QColor(200, 200, 200),
    "recordTube": QColor(120, 220, 255),
    "recordWall": QColor(255, 160, 100),
}


class NodeItem(QGraphicsRectItem):
    """Rechteckiger Knoten fuer einen Trigger oder eine Gruppe auf der Timeline.

    Rectangular node representing a trigger or a group on the timeline.

    Traegt Titel/Untertitel, einen Eingangs-Port oben (jeder Knoten kann Ziel
    sein) und bei Triggern zusaetzlich einen Ausgangs-Port unten. Knoten sind
    verschieb- und auswaehlbar.
    Carries title/subtitle, an input port at the top (every node can be a
    target) and, for triggers, an additional output port at the bottom. Nodes
    are movable and selectable.
    """
    def __init__(self, key, kind, index, title, subtitle, timeline, color_key=None):
        super().__init__(0, 0, NODE_W, NODE_H)
        self.key = key
        # "trigger" | "mining" | "building" | "reinforce"
        self.kind = kind            # "trigger" | "mining" | "building" | "reinforce"
        # Trigger-Index (oder -1)
        # Trigger index (or -1)
        self.index = index          # Trigger-Index (oder -1)
        self.timeline = timeline
        color = NODE_COLORS.get(color_key or kind, QColor(110, 110, 110))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(20, 20, 20), 1.5))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        t = QGraphicsSimpleTextItem(title, self)
        t.setBrush(QBrush(Qt.white)); t.setPos(8, 6)
        s = QGraphicsSimpleTextItem(subtitle, self)
        s.setBrush(QBrush(QColor(225, 225, 225))); s.setPos(8, 28)
        # Eingangs-Port oben (alle Knoten koennen Ziel sein)
        # Input port at the top (all nodes can be a target)
        pin = QGraphicsEllipseItem(NODE_W / 2 - 6, -6, 12, 12, self)
        pin.setBrush(QBrush(QColor(220, 220, 220))); pin.setPen(QPen(QColor(20, 20, 20), 1))
        # Ausgangs-Port unten nur fuer Trigger
        # Output port at the bottom, only for triggers
        if kind == "trigger":
            pout = QGraphicsEllipseItem(NODE_W / 2 - 6, NODE_H - 6, 12, 12, self)
            pout.setBrush(QBrush(QColor(255, 255, 255))); pout.setPen(QPen(QColor(20, 20, 20), 1))

    def output_pos(self):
        return self.scenePos() + QPointF(NODE_W / 2, NODE_H)

    def input_pos(self):
        return self.scenePos() + QPointF(NODE_W / 2, 0)

    def center(self):
        return self.scenePos() + QPointF(NODE_W / 2, NODE_H / 2)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.timeline._on_node_moved(self)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if self.timeline.connect_mode:
            self.timeline._connect_click(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.timeline._edit_node(self)
        event.accept()


class WireItem(QGraphicsPathItem):
    """Gerichtete Verbindung (Draht) zwischen zwei Knoten, eingefaerbt nach Aktionsart.

    Directed connection (wire) between two nodes, coloured by action kind.

    Zeichnet eine kubische Bezier-Kurve vom Ausgang des Quell- zum Eingang des
    Zielknotens samt Pfeilspitze; folgt den Knoten beim Verschieben.
    Draws a cubic Bezier curve from the source node's output to the target
    node's input, plus an arrowhead; follows the nodes when they move.
    """
    def __init__(self, src, dst, action_kind):
        super().__init__()
        self.src = src
        self.dst = dst
        color = WIRE_COLORS.get(action_kind, QColor(180, 180, 180))
        self.setPen(QPen(color, 2.2))
        self.setBrush(QBrush(color))
        self.setZValue(4)
        self.update_path()

    def update_path(self):
        # Neuberechnung der Kurve: kubische Bezier (Quelle->Ziel) + Pfeilspitzen-Polygon.
        # Recompute the curve: cubic Bezier (source->target) + arrowhead polygon.
        p1 = self.src.output_pos()   # unten am Quellknoten
        # bottom of the source node
        p2 = self.dst.input_pos()    # oben am Zielknoten
        # top of the target node
        path = QPainterPath(p1)
        dy = max(40.0, abs(p2.y() - p1.y()) * 0.5)
        path.cubicTo(p1.x(), p1.y() + dy, p2.x(), p2.y() - dy, p2.x(), p2.y())
        # Pfeilspitze nach unten ins Ziel
        # Arrowhead pointing down into the target
        path.addPolygon(QPolygonF([
            QPointF(p2.x(), p2.y()),
            QPointF(p2.x() - 6, p2.y() - 12),
            QPointF(p2.x() + 6, p2.y() - 12),
        ]))
        self.setPath(path)


class TimelineView(QGraphicsView):
    """Scroll-/zoombare Ansicht, die Trigger- und Gruppenknoten samt Draehten haelt.

    Scrollable/zoomable view that holds the trigger and group nodes and their wires.

    Baut die Szene aus dem Missionsmodell auf, persistiert Knotenpositionen und
    sendet Signale fuer Bearbeiten/Hinzufuegen/Loeschen/Verbinden.
    Builds the scene from the mission model, persists node positions, and emits
    signals for edit/add/delete/connect.
    """
    editTrigger = Signal(int)
    editGroups = Signal()
    addTrigger = Signal()
    # (Quell-Trigger-Name, Ziel-Knoten-Key)
    connectMade = Signal(str, str)   # (Quell-Trigger-Name, Ziel-Knoten-Key)
    # Trigger-Index
    deleteTrigger = Signal(int)      # Trigger-Index

    def __init__(self, positions: dict):
        self._scene = QGraphicsScene()
        super().__init__(self._scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        # key -> [x, y], wird persistiert
        # key -> [x, y], gets persisted
        self.positions = positions          # key -> [x, y], wird persistiert
        self.nodes: dict[str, NodeItem] = {}
        self.wires: list[WireItem] = []
        self.connect_mode = False
        self.connect_src: NodeItem | None = None
        self._suppress_save = False

    # --- Aufbau ---
    # --- Build-up ---
    def rebuild(self, triggers, mining_groups, building_groups, reinforce_groups):
        self._scene.clear()
        self.nodes.clear()
        self.wires.clear()
        self.connect_src = None

        name_to_key = {}
        for g in mining_groups:
            name_to_key[g.name] = f"mining:{g.name}"
        for g in building_groups:
            name_to_key[g.name] = f"building:{g.name}"
        for g in reinforce_groups:
            name_to_key[g.name] = f"reinforce:{g.name}"

        self._suppress_save = True
        # Trigger-Knoten: senkrechte Spalte links, nach Startzeit von oben nach unten
        # Trigger nodes: vertical column on the left, by start time top to bottom
        order = sorted(range(len(triggers)),
                       key=lambda i: (not triggers[i].enabled_at_start, triggers[i].marks))
        for row, ti in enumerate(order):
            t = triggers[ti]
            node_kind = "trigger_start" if t.enabled_at_start else "trigger"
            cond = tr(f"trigger_conditions.{t.condition}")
            sub = tr("timeline.node_sub", cond=cond, n=len(t.actions))
            node = NodeItem(f"trigger:{t.name}", "trigger", ti, t.name, sub, self, color_key=node_kind)
            self._place(node, COL_X_TRIGGERS, Y_START + row * Y_GAP)
            self.nodes[f"trigger:{t.name}"] = node
            self._scene.addItem(node)

        # Gruppen-Knoten: senkrechte Spalte rechts
        # Group nodes: vertical column on the right
        row = 0
        for gkind, groups in (("mining", mining_groups), ("building", building_groups),
                              ("reinforce", reinforce_groups)):
            for g in groups:
                node = NodeItem(f"{gkind}:{g.name}", gkind, -1, g.name, tr(f"timeline.{gkind}"), self)
                self._place(node, COL_X_GROUPS, Y_START + row * Y_GAP)
                self.nodes[f"{gkind}:{g.name}"] = node
                self._scene.addItem(node)
                row += 1
        self._suppress_save = False

        # Verbindungen aus Aktionen
        # Connections derived from actions
        for ti, t in enumerate(triggers):
            src = self.nodes.get(f"trigger:{t.name}")
            if src is None:
                continue
            for a in t.actions:
                dst_key = self._target_key(a, name_to_key)
                if dst_key and dst_key in self.nodes:
                    wire = WireItem(src, self.nodes[dst_key], a.kind)
                    self._scene.addItem(wire)
                    self.wires.append(wire)

        rect = self._scene.itemsBoundingRect()
        self._scene.setSceneRect(rect.adjusted(-80, -80, 80, 80))

    def _target_key(self, action, name_to_key):
        """Liefert den Knoten-Key, auf den eine Aktion zeigt (oder None).

        Returns the node key an action points at (or None).

        createTrigger -> Ziel-Trigger; startMiningOperation -> Mining-Gruppe;
        assignToGroup/setTargCount/recordBuilding/recordTube/recordWall -> Gruppe.
        createTrigger -> target trigger; startMiningOperation -> mining group;
        assignToGroup/setTargCount/recordBuilding/recordTube/recordWall -> group.
        """
        k = action.kind
        if k == "createTrigger" and action.target:
            return f"trigger:{action.target}"
        if k == "startMiningOperation" and action.mining_group_name:
            return name_to_key.get(action.mining_group_name)
        if k in ("assignToGroup", "setTargCount", "recordBuilding", "recordTube", "recordWall"):
            return name_to_key.get(action.group_name)
        return None

    def _place(self, node, default_x, default_y):
        pos = self.positions.get(node.key)
        if pos:
            node.setPos(pos[0], pos[1])
        else:
            node.setPos(default_x, default_y)

    def auto_layout(self):
        self.positions.clear()
        # Beim naechsten rebuild werden Standardpositionen verwendet.
        # On the next rebuild the default positions will be used.

    # --- Callbacks von Knoten ---
    # --- Callbacks from nodes ---
    def _on_node_moved(self, node):
        if not self._suppress_save:
            p = node.scenePos()
            self.positions[node.key] = [p.x(), p.y()]
        for w in self.wires:
            w.update_path()

    def _edit_node(self, node):
        if node.kind == "trigger":
            self.editTrigger.emit(node.index)
        else:
            self.editGroups.emit()

    def _connect_click(self, node):
        if self.connect_src is None:
            if node.kind != "trigger":
                # Verbindungen starten nur an Triggern
                # Connections can only start at triggers
                return  # Verbindungen starten nur an Triggern
            self.connect_src = node
            node.setPen(QPen(QColor(255, 255, 0), 3))
        else:
            src_name = self.connect_src.key.split(":", 1)[1]
            self.connect_src.setPen(QPen(QColor(20, 20, 20), 1.5))
            self.connect_src = None
            if node is not None and node.key != f"trigger:{src_name}":
                self.connectMade.emit(src_name, node.key)

    def set_connect_mode(self, on):
        self.connect_mode = on
        if self.connect_src is not None:
            self.connect_src.setPen(QPen(QColor(20, 20, 20), 1.5))
            self.connect_src = None
        self.setDragMode(QGraphicsView.NoDrag if on else QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for item in self._scene.selectedItems():
                if isinstance(item, NodeItem) and item.kind == "trigger":
                    self.deleteTrigger.emit(item.index)
                    return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        f = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)
