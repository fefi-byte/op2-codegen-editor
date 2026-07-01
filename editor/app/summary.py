from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from . import i18n
from .game_data import COMPARE
from mission_model import BuildingGroupSpec, Condition, ReinforceGroupSpec

tr = i18n.tr


def _cmp_sym(compare):
    return {v: k for k, v in COMPARE.items()}.get(compare, compare)


def action_condition_summary(c) -> str:
    """Bildet eine IF-Aktionsbedingung auf ein lesbares Listenlabel ab."""
    cmp = _cmp_sym(c.compare)
    neg = (tr("sum.not") + " ") if c.negate else ""
    if c.kind == "buildingAtLocation":
        return tr("sum.cond_building_at", neg=neg, b=c.building_type, x=c.x, y=c.y, p=c.player)
    if c.kind == "unitDamage":
        return tr("sum.cond_damage", neg=neg, b=c.building_type, x=c.x, y=c.y, cmp=cmp, v=c.value, p=c.player)
    if c.kind == "playerResource":
        return tr("sum.cond_resource", neg=neg, res=c.resource, cmp=cmp, v=c.value, p=c.player)
    if c.kind == "buildingCount":
        return tr("sum.cond_count", neg=neg, b=c.building_type, cmp=cmp, v=c.value, p=c.player)
    if c.kind == "hasTech":
        return tr("sum.cond_tech", neg=neg, tech=c.tech_id, p=c.player)
    if c.kind == "varCheck":
        var = getattr(c, 'var_name', '') or '?'
        return f"{neg}{var} {cmp} {c.value}"
    return c.kind


def trigger_summary(t) -> str:
    """Bildet ein Trigger-Objekt auf ein lesbares Listenlabel ab."""
    cond = tr(f"trigger_conditions.{t.condition}")
    start = tr("sum.trig_start") if t.enabled_at_start else tr("sum.trig_runtime")
    return tr("sum.trigger", name=t.name, start=start, cond=cond, n=len(t.actions))


def action_summary(a) -> str:
    """Bildet ein Aktions-Objekt auf ein lesbares Listenlabel ab (inkl. IF-Praefix)."""
    prefix = (tr("sum.if_prefix", n=len(a.conditions)) + " ") if getattr(a, "conditions", None) else ""
    return prefix + _action_summary_core(a)


def _action_summary_core(a) -> str:
    if a.kind == "noop":
        return tr("action_kinds.noop")
    if a.kind == "if":
        logic = tr("sum.or") if getattr(a, "condition_logic", "and") == "or" else tr("sum.and")
        return tr("sum.act_if", n=len(getattr(a, "conditions", [])), logic=logic,
                  then=len(getattr(a, "then_actions", [])), els=len(getattr(a, "else_actions", [])))
    if a.kind == "message":
        return tr("sum.act_message", text=a.text)
    if a.kind == "createUnit":
        weapon = "" if a.weapon_type == "mapNone" else f" / {a.weapon_type}"
        return tr("sum.act_createunit", unit=a.unit_type, weapon=weapon, x=a.x, y=a.y, p=a.player)
    if a.kind == "createMeteor":
        size_map = {-1: "random", 0: "small", 1: "medium", 2: "large"}
        size = size_map.get(getattr(a, "size", -1), getattr(a, "size", -1))
        now = " now" if getattr(a, "now", False) else ""
        return f"Meteor({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}, {size}{now})"
    if a.kind == "createDisaster":
        dtype = getattr(a, "disaster_type", "meteor")
        if dtype == "meteor":
            size_map = {-1: "random", 0: "small", 1: "medium", 2: "large"}
            size = size_map.get(getattr(a, "size", -1), getattr(a, "size", -1))
            now = " now" if getattr(a, "now", False) else ""
            return f"Disaster: Meteor({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}, {size}{now})"
        if dtype == "earthquake":
            now = " now" if getattr(a, "now", False) else ""
            return f"Disaster: Earthquake({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}, mag={getattr(a, 'magnitude', 1)}{now})"
        if dtype == "storm":
            now = " now" if getattr(a, "now", False) else ""
            return f"Disaster: Storm(({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}) -> ({getattr(a, 'x2_expr', 0)}, {getattr(a, 'y2_expr', 0)}), t={getattr(a, 'duration', 100)}{now})"
        if dtype == "vortex":
            now = " now" if getattr(a, "now", False) else ""
            return f"Disaster: Vortex(({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}) -> ({getattr(a, 'x2_expr', 0)}, {getattr(a, 'y2_expr', 0)}), t={getattr(a, 'duration', 100)}{now})"
        if dtype == "blight":
            return f"Disaster: Blight({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)})"
        if dtype == "unblight":
            return f"Disaster: UnsetBlight({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)})"
        return f"Disaster: {dtype}"
    if a.kind == "createEarthquake":
        now = " now" if getattr(a, "now", False) else ""
        return f"Earthquake({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}, mag={getattr(a, 'magnitude', 1)}{now})"
    if a.kind == "createStorm":
        now = " now" if getattr(a, "now", False) else ""
        return f"Storm(({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}) -> ({getattr(a, 'x2_expr', 0)}, {getattr(a, 'y2_expr', 0)}), t={getattr(a, 'duration', 100)}{now})"
    if a.kind == "createVortex":
        now = " now" if getattr(a, "now", False) else ""
        return f"Vortex(({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)}) -> ({getattr(a, 'x2_expr', 0)}, {getattr(a, 'y2_expr', 0)}), t={getattr(a, 'duration', 100)}{now})"
    if a.kind == "createBlight":
        return f"Blight({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)})"
    if a.kind == "unsetBlight":
        return f"UnsetBlight({getattr(a, 'x_expr', 0)}, {getattr(a, 'y_expr', 0)})"
    if a.kind == "createTrigger":
        return tr("sum.act_createtrigger", target=a.target)
    if a.kind == "recordBuilding":
        return tr("sum.act_recordbuilding", g=a.group_name, b=a.building_type, x=a.x, y=a.y)
    if a.kind == "recordTube":
        return f"{a.group_name}.RecordTubeLine(({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "recordWall":
        return f"{a.group_name}.RecordWallLine({a.wall_type}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "setTargCount":
        weapon = "" if a.weapon_type == "mapNone" else f", {a.weapon_type}"
        source = f" via {a.source_group_name} P{a.reinforce_priority}" if a.source_group_name else ""
        return f"{a.group_name}.SetTargCount({a.unit_type}{weapon}) = {a.target_count}{source}"
    if a.kind == "assignToGroup":
        return tr("sum.act_assign", b=a.building_type, x=a.x, y=a.y, g=a.group_name, p=a.player)
    if a.kind == "modVar":
        var = getattr(a, 'var_name', '') or '?'
        mode = getattr(a, 'mod_mode', 'inc') or 'inc'
        if mode == 'inc':
            return f"{var} +1"
        if mode == 'dec':
            return f"{var} −1"
        expr = getattr(a, 'var_expr', '') or '…'
        return f"{var} = {expr}"
    return a.kind


_KIND_TITLE = {
    "noop": "Platzhalter",
    "if": "Wenn / Dann / Sonst",
    "message": "Nachricht",
    "createUnit": "Einheit erzeugen",
    "createDisaster": "Katastrophe",
    "createTrigger": "Trigger starten",
    "recordBuilding": "recordBuilding",
    "recordTube": "recordTube",
    "recordWall": "recordWall",
    "setTargCount": "setTargCount",
    "assignToGroup": "Gruppe zuweisen",
    "modVar": "Variable ändern",
}


def action_kind_label(kind: str) -> str:
    return _KIND_TITLE.get(kind, kind)


def action_params_summary(a) -> str:
    """Kompakte einzeilige Parameterübersicht für eine Aktionskarte (leer für noop/if)."""
    if a.kind in ("noop", "if"):
        return ""
    if a.kind == "message":
        return f'"{getattr(a, "text", "")}"'
    if a.kind == "createUnit":
        weapon = getattr(a, "weapon_type", "mapNone")
        w = "" if weapon == "mapNone" else f"  Waffe: {weapon}"
        return f"Einheit: {getattr(a, 'unit_type', '?')}{w}  P{getattr(a, 'player', 0)}  @ ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)})"
    if a.kind == "createDisaster":
        dtype = getattr(a, "disaster_type", "meteor")
        x, y = getattr(a, "x_expr", 0), getattr(a, "y_expr", 0)
        if dtype in ("storm", "vortex"):
            return f"Typ: {dtype}  ({x},{y}) → ({getattr(a, 'x2_expr', 0)},{getattr(a, 'y2_expr', 0)})"
        return f"Typ: {dtype}  @ ({x},{y})"
    if a.kind == "createTrigger":
        return f"→ {getattr(a, 'target', '?')}"
    if a.kind == "recordBuilding":
        return f"{getattr(a, 'group_name', '?')}  ·  {getattr(a, 'building_type', '?')}  @ ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)})"
    if a.kind == "recordTube":
        return f"{getattr(a, 'group_name', '?')}  ·  ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → ({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})"
    if a.kind == "recordWall":
        return f"{getattr(a, 'group_name', '?')}  ·  {getattr(a, 'wall_type', '?')}  ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → ({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})"
    if a.kind == "setTargCount":
        return f"{getattr(a, 'group_name', '?')}  ·  {getattr(a, 'unit_type', '?')}  = {getattr(a, 'target_count', 0)}  P{getattr(a, 'reinforce_priority', 0)}"
    if a.kind == "assignToGroup":
        return f"→ {getattr(a, 'group_name', '?')}  ·  {getattr(a, 'building_type', '?')}  @ ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)})  P{getattr(a, 'player', 0)}"
    if a.kind == "modVar":
        var = getattr(a, "var_name", "") or "?"
        mode = getattr(a, "mod_mode", "inc") or "inc"
        if mode == "inc":
            return f"{var} +1"
        if mode == "dec":
            return f"{var} −1"
        return f"{var} = {getattr(a, 'var_expr', '…') or '…'}"
    return ""


def condition_summary(c: Condition) -> str:
    """Kurzbeschreibung einer Bedingung fuer die Liste."""
    cmp = _cmp_sym(c.compare)
    k = c.kind
    if k == "time":
        return tr("sum.win_time", marks=c.marks)
    if k == "lastStanding":
        return tr("conditions.lastStanding")
    if k == "starship":
        return tr("conditions.starship")
    if k == "noCC":
        return tr("sum.win_nocc", p=c.player)
    if k == "buildingCount":
        return tr("sum.win_buildingcount", cmp=cmp, n=c.count, p=c.player)
    if k == "vehicleCount":
        return tr("sum.win_vehiclecount", cmp=cmp, n=c.count, p=c.player)
    if k == "research":
        return tr("sum.win_research", tech=c.tech_id, p=c.player)
    if k == "resource":
        return tr("sum.win_resource", res=c.resource, cmp=cmp, amt=c.amount, p=c.player)
    if k == "operational":
        return tr("sum.win_operational", b=c.building, cmp=cmp, n=c.count, p=c.player)
    return k


def building_group_summary(g: BuildingGroupSpec) -> str:
    """Bildet eine Gebaeude-Gruppe auf ein lesbares Listenlabel ab."""
    return tr("sum.group_building", name=g.name, p=g.player, rx=g.rect_x, ry=g.rect_y,
              rw=g.rect_width, rh=g.rect_height, n=len(g.unit_ids))


def reinforce_group_summary(g: ReinforceGroupSpec) -> str:
    """Bildet eine Reinforce-Gruppe auf ein lesbares Listenlabel ab."""
    return tr("sum.group_reinforce", name=g.name, p=g.player, f=len(g.unit_ids), t=len(g.targets))


class ExprEdit(QWidget):
    """Zahlenfeld das Integer oder C++-Ausdruck akzeptiert.

    Zeigt eine Vorschau 'Hard: X · Normal: Y · Easy: Z' wenn 'diff' im
    Text vorkommt und diff_values gesetzt ist.
    """
    valueChanged = Signal(object)

    def __init__(self, parent=None, diff_values=None):
        super().__init__(parent)
        self._diff = diff_values  # (hard, normal, easy) oder None

        self._edit = QLineEdit()
        self._preview = QLabel()
        self._preview.setStyleSheet("color: gray; font-size: 9pt;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        lay.addWidget(self._edit)
        lay.addWidget(self._preview)
        self._preview.setVisible(False)

        self._edit.textChanged.connect(self._on_changed)

    def set_diff_values(self, hard, normal, easy):
        self._diff = (hard, normal, easy)
        self._on_changed(self._edit.text())

    def _on_changed(self, text=""):
        text = self._edit.text().strip()
        self._update_preview(text)
        self.valueChanged.emit(self.value())

    def _update_preview(self, text):
        if not self._diff or 'diff' not in text:
            self._preview.setVisible(False)
            return
        import math
        safe_locals = {"ceil": math.ceil, "floor": math.floor,
                       "round": round, "abs": abs, "max": max, "min": min}
        labels = ('Hard', 'Normal', 'Easy')
        parts = []
        for label, dv in zip(labels, self._diff):
            try:
                val = eval(text.replace('diff', str(dv)), {"__builtins__": {}}, safe_locals)
                parts.append(f"{label}: {int(val)}")
            except Exception:
                parts.append(f"{label}: ?")
        self._preview.setText("  ·  ".join(parts))
        self._preview.setVisible(True)

    def setValue(self, v):
        if v is None:
            self._edit.setText("")
        else:
            self._edit.setText(str(v))

    def value(self):
        """Gibt int zurueck wenn reiner Integer, sonst str."""
        text = self._edit.text().strip()
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            return text

    def text(self):
        return self._edit.text().strip()

    def setPlaceholderText(self, t):
        self._edit.setPlaceholderText(t)
