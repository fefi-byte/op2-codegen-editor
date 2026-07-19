from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from . import i18n
from .game_data import COMPARE
from mission_model import (
    BuildingGroupSpec, Condition, FightGroupSpec, MiningGroupSpec, ReinforceGroupSpec,
)

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
    if c.kind == "loopUnitType":
        return f"{neg}unit.type == {(c.building_type or '?').replace('map', '')}"
    if c.kind == "loopUnitDamage":
        return f"{neg}unit.damage {cmp} {c.value}"
    if c.kind == "loopUnitCargo":
        return f"{neg}unit.weapon == {(c.building_type or '?').replace('map', '')}"
    if c.kind == "loopUnitCommand":
        return f"{neg}unit.command == {getattr(c, 'command_type', 'Move') or 'Move'}"
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
        base = tr("sum.act_if", n=len(getattr(a, "conditions", [])), logic=logic,
                  then=len(getattr(a, "then_actions", [])), els=len(getattr(a, "else_actions", [])))
        loop = getattr(a, "loop_mode", "none") or "none"
        if loop == "count":
            base = f"{getattr(a, 'loop_count', 1)}× " + base
        elif loop == "forEach":
            ut = (getattr(a, "unit_type", "mapAny") or "mapAny").replace("map", "")
            base = f"∀ {ut} in ({a.x},{a.y})-({a.x2},{a.y2}): " + base
        return base
    if a.kind == "message":
        return tr("sum.act_message", text=a.text)
    if a.kind == "createUnit":
        entries = list(getattr(a, "unit_list", None) or [])
        if not entries:
            entries = [{"unit_type": a.unit_type, "weapon_type": a.weapon_type, "x": a.x, "y": a.y}]
        if len(entries) == 1:
            e = entries[0]
            weapon = "" if e.get("weapon_type", "mapNone") == "mapNone" else f" / {e.get('weapon_type')}"
            return tr("sum.act_createunit", unit=e.get("unit_type", "?"), weapon=weapon,
                      x=e.get("x", 0), y=e.get("y", 0), p=a.player)
        comp = ", ".join(f"{e.get('unit_type', '?')}@({e.get('x', 0)},{e.get('y', 0)})" for e in entries)
        return f"CreateUnit(P{a.player}, {len(entries)}x: {comp})"
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
    if a.kind == "createTrigger":
        return tr("sum.act_createtrigger", target=a.target)
    if a.kind == "recordBuilding":
        entries = list(getattr(a, "building_list", None) or [])
        if not entries:
            entries = [{"building_type": a.building_type, "x": a.x, "y": a.y}]
        if len(entries) == 1:
            e = entries[0]
            return tr("sum.act_recordbuilding", g=a.group_name, b=e.get("building_type", "?"),
                      x=e.get("x", 0), y=e.get("y", 0))
        comp = ", ".join(f"{e.get('building_type', '?')}@({e.get('x', 0)},{e.get('y', 0)})" for e in entries)
        return f"{a.group_name}.RecordBuilding({len(entries)}x: {comp})"
    if a.kind == "recordTube":
        entries = list(getattr(a, "tube_list", None) or [])
        if not entries:
            entries = [{"x": a.x, "y": a.y, "x2": a.x2, "y2": a.y2}]
        if len(entries) == 1:
            e = entries[0]
            return f"{a.group_name}.RecordTubeLine(({e.get('x', 0)},{e.get('y', 0)}) -> ({e.get('x2', 0)},{e.get('y2', 0)}))"
        comp = ", ".join(
            f"({e.get('x', 0)},{e.get('y', 0)})->({e.get('x2', 0)},{e.get('y2', 0)})" for e in entries)
        return f"{a.group_name}.RecordTube({len(entries)}x: {comp})"
    if a.kind == "recordWall":
        entries = list(getattr(a, "wall_list", None) or [])
        if not entries:
            entries = [{"wall_type": a.wall_type, "x": a.x, "y": a.y, "x2": a.x2, "y2": a.y2}]
        if len(entries) == 1:
            e = entries[0]
            return (f"{a.group_name}.RecordWallLine({e.get('wall_type', '?')}, "
                    f"({e.get('x', 0)},{e.get('y', 0)}) -> ({e.get('x2', 0)},{e.get('y2', 0)}))")
        comp = ", ".join(
            f"{e.get('wall_type', '?')}@({e.get('x', 0)},{e.get('y', 0)})->({e.get('x2', 0)},{e.get('y2', 0)})"
            for e in entries)
        return f"{a.group_name}.RecordWall({len(entries)}x: {comp})"
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
    if a.kind == "startMining":
        gname = getattr(a, "group_name", "") or "?"
        return f"{gname}.StartMining(Mine ({a.x},{a.y}) -> Smelter ({a.x2},{a.y2}), {a.target_count} Trucks)"
    if a.kind == "sendAttackWave":
        waves = getattr(a, "wave_units", None) or []
        comp = ", ".join(f"{w.get('count', 1)}x {w.get('unit_type', '?')}" for w in waves) \
            or f"{a.target_count}x {a.unit_type}"
        mode = "Reinforce" if getattr(a, "spawn_mode", "spawn") == "reinforce" else "Spawn"
        name = getattr(a, "group_var_name", "") or ""
        tag = f" '{name}'" if name else ""
        return f"AttackWave{tag}(P{a.player}, {mode}: {comp})"
    if a.kind == "fightGroupCmd":
        cmd = _GROUP_CMD_LABELS.get(getattr(a, "fg_command", "attackArea"), "?")
        return f"Gruppe '{getattr(a, 'group_name', '?')}': {cmd}"
    if a.kind == "unitCmd":
        cmd = _UNIT_CMD_LABELS.get(getattr(a, "fg_command", "move"), "?")
        return f"Einheit '{getattr(a, 'unit_ref', '?')}': {cmd}"
    if a.kind == "defendArea":
        return f"DefendArea(P{a.player}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "repairBuildings":
        return f"RepairBuildings(P{a.player}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "empMissile":
        return f"EMP-Rakete(P{a.player}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "setMorale":
        mode = getattr(a, "morale_mode", "good") or "good"
        p = "alle" if int(getattr(a, "player", 0)) < 0 else f"P{a.player}"
        return f"Moral: {mode} ({p})"
    if a.kind == "setMusic":
        n = len(getattr(a, "songs", None) or [])
        return f"Musik-Playlist ({n} Songs, Loop ab {getattr(a, 'repeat_start', 0)})"
    if a.kind == "lavaFlowAni":
        fn = "FreezeFlow" if getattr(a, "flow_freeze", False) else "AnimateFlow"
        return f"{fn}{getattr(a, 'flow_dir', 'S')} @ ({a.x},{a.y})"
    if a.kind == "modUnitStats":
        n = len(getattr(a, "stat_mods", None) or [])
        return f"UnitInfo {getattr(a, 'unit_type', '?')}: {n} Werte (P{a.player})"
    return a.kind


# Befehls-Labels fuer Zusammenfassungen / command labels for summaries
_GROUP_CMD_LABELS = {
    "attackArea": "Bereich angreifen", "attackEnemy": "Feind jagen",
    "guardArea": "Bereich bewachen", "patrol": "Patrouillieren",
    "exitMap": "Karte verlassen",
    "combineFireOn": "Feuer bündeln: an", "combineFireOff": "Feuer bündeln: aus",
    "setBuildRect": "Baubereich setzen",
    "reinforceGroup": "Verstärkung starten", "unReinforceGroup": "Verstärkung stoppen",
    "lightsOn": "Lichter an", "lightsOff": "Lichter aus",
    "clearTargCount": "Sollstärken löschen",
}
_UNIT_CMD_LABELS = {
    "move": "Bewegen", "patrol": "Patrouillieren", "attackGround": "Position angreifen",
    "repair": "Reparieren",
    "stop": "Stopp", "idle": "Stilllegen", "unidle": "Aktivieren",
    "selfDestruct": "Selbstzerstörung", "remove": "Entfernen",
    "transfer": "An Spieler übergeben",
    "lightsOn": "Lichter an", "lightsOff": "Lichter aus",
}

_KIND_TITLE = {
    "noop": "Platzhalter",
    "if": "Logik (Wenn / Schleife)",
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
    "startMining": "Mining starten",
    "sendAttackWave": "Angriffswelle",
    "fightGroupCmd": "Gruppen-Befehl",
    "unitCmd": "Einheiten-Befehl",
    "defendArea": "Gebiet verteidigen",
    "repairBuildings": "Gebäude reparieren",
    "empMissile": "EMP-Rakete",
    "setMorale": "Moral setzen",
    "setMusic": "Musik-Playlist",
    "lavaFlowAni": "Lavastrom-Animation",
    "modUnitStats": "Einheiten-Werte",
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
        entries = list(getattr(a, "unit_list", None) or [])
        if not entries:
            entries = [{"unit_type": getattr(a, "unit_type", "?"),
                        "weapon_type": getattr(a, "weapon_type", "mapNone"),
                        "x": getattr(a, "x", 0), "y": getattr(a, "y", 0)}]
        if len(entries) == 1:
            e = entries[0]
            weapon = e.get("weapon_type", "mapNone")
            w = "" if weapon == "mapNone" else f"  Waffe: {weapon}"
            return f"Einheit: {e.get('unit_type', '?')}{w}  P{getattr(a, 'player', 0)}  @ ({e.get('x', 0)},{e.get('y', 0)})"
        return f"{len(entries)} Einheiten  P{getattr(a, 'player', 0)}"
    if a.kind == "createDisaster":
        dtype = getattr(a, "disaster_type", "meteor")
        x, y = getattr(a, "x_expr", 0), getattr(a, "y_expr", 0)
        if dtype in ("storm", "vortex"):
            return f"Typ: {dtype}  ({x},{y}) → ({getattr(a, 'x2_expr', 0)},{getattr(a, 'y2_expr', 0)})"
        return f"Typ: {dtype}  @ ({x},{y})"
    if a.kind == "createTrigger":
        return f"→ {getattr(a, 'target', '?')}"
    if a.kind == "recordBuilding":
        entries = list(getattr(a, "building_list", None) or [])
        if len(entries) <= 1:
            e = entries[0] if entries else {"building_type": getattr(a, "building_type", "?"),
                                             "x": getattr(a, "x", 0), "y": getattr(a, "y", 0)}
            return f"{getattr(a, 'group_name', '?')}  ·  {e.get('building_type', '?')}  @ ({e.get('x', 0)},{e.get('y', 0)})"
        return f"{getattr(a, 'group_name', '?')}  ·  {len(entries)} Gebäude"
    if a.kind == "recordTube":
        entries = list(getattr(a, "tube_list", None) or [])
        if len(entries) <= 1:
            e = entries[0] if entries else {"x": getattr(a, "x", 0), "y": getattr(a, "y", 0),
                                             "x2": getattr(a, "x2", 0), "y2": getattr(a, "y2", 0)}
            return f"{getattr(a, 'group_name', '?')}  ·  ({e.get('x', 0)},{e.get('y', 0)}) → ({e.get('x2', 0)},{e.get('y2', 0)})"
        return f"{getattr(a, 'group_name', '?')}  ·  {len(entries)} Leitungen"
    if a.kind == "recordWall":
        entries = list(getattr(a, "wall_list", None) or [])
        if len(entries) <= 1:
            e = entries[0] if entries else {"wall_type": getattr(a, "wall_type", "?"),
                                             "x": getattr(a, "x", 0), "y": getattr(a, "y", 0),
                                             "x2": getattr(a, "x2", 0), "y2": getattr(a, "y2", 0)}
            return (f"{getattr(a, 'group_name', '?')}  ·  {e.get('wall_type', '?')}  "
                    f"({e.get('x', 0)},{e.get('y', 0)}) → ({e.get('x2', 0)},{e.get('y2', 0)})")
        return f"{getattr(a, 'group_name', '?')}  ·  {len(entries)} Abschnitte"
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
    if a.kind == "startMining":
        gname = getattr(a, "group_name", "") or "?"
        return (f"'{gname}'  Mine ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → "
                f"Smelter ({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})  Trucks: {getattr(a, 'target_count', 1)}")
    if a.kind == "sendAttackWave":
        waves = getattr(a, "wave_units", None) or []
        comp = ", ".join(f"{w.get('count', 1)}× {w.get('unit_type', '?').replace('map', '')}"
                         for w in waves) or f"{getattr(a, 'target_count', 1)}× {getattr(a, 'unit_type', '?')}"
        mode = "Reinforce" if getattr(a, "spawn_mode", "spawn") == "reinforce" else "Spawn"
        name = getattr(a, "group_var_name", "") or ""
        tag = f"'{name}'  " if name else ""
        return (f"{tag}P{getattr(a, 'player', 0)}  [{mode}]  {comp}  "
                f"Sammeln ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → "
                f"Angriff ({getattr(a, 'attack_x', 0)},{getattr(a, 'attack_y', 0)})")
    if a.kind == "fightGroupCmd":
        cmd = _GROUP_CMD_LABELS.get(getattr(a, "fg_command", "attackArea"), "?")
        extra = ""
        if getattr(a, "fg_command", "") in ("attackArea", "guardArea", "setBuildRect", "patrol"):
            extra = f"  ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → ({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})"
        elif getattr(a, "fg_command", "") in ("reinforceGroup", "unReinforceGroup"):
            extra = f"  → '{getattr(a, 'target', '?')}'"
        return f"'{getattr(a, 'group_name', '?')}'  {cmd}{extra}"
    if a.kind == "unitCmd":
        cmd = _UNIT_CMD_LABELS.get(getattr(a, "fg_command", "move"), "?")
        extra = ""
        if getattr(a, "fg_command", "") in ("move", "attackGround"):
            extra = f"  @ ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)})"
        elif getattr(a, "fg_command", "") == "patrol":
            pts = getattr(a, "patrol_points", None) or []
            extra = (f"  {len(pts)} Wegpunkte" if pts
                     else f"  ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) ↔ ({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})")
        elif getattr(a, "fg_command", "") == "transfer":
            extra = f"  → P{getattr(a, 'player', 0)}"
        elif getattr(a, "fg_command", "") == "repair":
            extra = f"  → '{getattr(a, 'target', '?')}'"
        return f"'{getattr(a, 'unit_ref', '?')}'  {cmd}{extra}"
    if a.kind in ("defendArea", "repairBuildings"):
        return (f"P{getattr(a, 'player', 0)}  Rect ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → "
                f"({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})")
    if a.kind == "empMissile":
        return (f"P{getattr(a, 'player', 0)}  Start ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → "
                f"Ziel ({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})")
    if a.kind == "setMorale":
        p = "alle" if int(getattr(a, "player", 0)) < 0 else f"P{getattr(a, 'player', 0)}"
        return f"{getattr(a, 'morale_mode', 'good')}  ·  {p}"
    if a.kind == "setMusic":
        songs = getattr(a, "songs", None) or []
        return f"{len(songs)} Songs  ·  Loop ab Index {getattr(a, 'repeat_start', 0)}"
    if a.kind == "lavaFlowAni":
        mode = "Stoppen" if getattr(a, "flow_freeze", False) else "Starten"
        return f"{mode}  ·  Richtung {getattr(a, 'flow_dir', 'S')}  @ ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)})"
    if a.kind == "modUnitStats":
        mods = getattr(a, "stat_mods", None) or []
        comp = ", ".join(f"{m.get('stat', '?')}={m.get('value', 0)}" for m in mods[:3])
        more = "…" if len(mods) > 3 else ""
        return f"{getattr(a, 'unit_type', '?')}  P{getattr(a, 'player', 0)}  {comp}{more}"
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


def fight_group_summary(g: FightGroupSpec) -> str:
    """Bildet eine FightGroup auf ein lesbares Listenlabel ab."""
    return tr("sum.group_fight", name=g.name, p=g.player, rx=g.idle_x, ry=g.idle_y,
              rw=g.idle_width, rh=g.idle_height, n=len(g.unit_ids))


def mining_group_summary(g: MiningGroupSpec) -> str:
    """Bildet eine MiningGroup auf ein lesbares Listenlabel ab."""
    return tr("sum.group_mining_idle", name=g.name, p=g.player, rx=g.idle_x, ry=g.idle_y,
              rw=g.idle_width, rh=g.idle_height, n=len(g.unit_ids))


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
