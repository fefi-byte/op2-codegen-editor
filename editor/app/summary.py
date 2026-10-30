from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from . import i18n
from .game_data import (
    ALL_UNITS, COMPARE, SPACEPORT_PRODUCTS, WEAPONS, condition_cargo_items,
    truck_cargo_items,
)
from mission_model import (
    BuildingGroupSpec, Condition, FightGroupSpec, MiningGroupSpec, ReinforceGroupSpec,
)

tr = i18n.tr


def _cmp_sym(compare):
    return {v: k for k, v in COMPARE.items()}.get(compare, compare)


def _display_map() -> dict[str, str]:
    """map_id/Cargo-Code -> Anzeigename, einmalig aufgebaut.

    map_id/cargo code -> display name, built once."""
    global _DISPLAY_NAMES
    if _DISPLAY_NAMES is None:
        names = {m: d for d, m in ALL_UNITS}
        names.update({m: d for d, m in SPACEPORT_PRODUCTS})
        names.update({m: d for d, m in WEAPONS})
        names.update({v: k for k, v in truck_cargo_items()})
        for unit in ("mapCargoTruck", "mapEvacuationTransport", "mapConVec"):
            names.update({v: k for k, v in condition_cargo_items(unit)})
        _DISPLAY_NAMES = names
    return _DISPLAY_NAMES


_DISPLAY_NAMES: dict[str, str] | None = None


def display_name(code) -> str:
    """Interner Code (mapCargoTruck, truckFood, …) -> Anzeigename.

    Zusammenfassungen sollen lesbare Namen zeigen, keine SDK-Bezeichner;
    Unbekanntes wird unveraendert durchgereicht.

    Internal code (mapCargoTruck, truckFood, …) -> display name. Summaries
    should show readable names, not SDK identifiers; anything unknown is
    passed through unchanged."""
    if not code:
        return code
    text = str(code)
    return _display_map().get(text, text)


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
    if a.kind in ("addVictory", "addDefeat"):
        spec = dict(getattr(a, "condition_spec", None) or {})
        spec.setdefault("kind", "time")
        try:
            detail = condition_summary(Condition(**spec))
        except TypeError:
            detail = spec.get("kind", "time")
        key = "sum.act_addvictory" if a.kind == "addVictory" else "sum.act_adddefeat"
        return tr(key, cond=detail)
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
    if a.kind == "stopTrigger":
        return tr("sum.act_stoptrigger", target=a.target)
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
    if a.kind == "showDialog":
        t = (a.text or "").replace("\n", " ")
        return f"MsgBox({t[:40]}{'…' if len(t) > 40 else ''})"
    if a.kind == "customCode":
        first = next((l.strip() for l in (getattr(a, "code", "") or "").splitlines()
                      if l.strip()), "")
        return f"C++: {first[:44]}{'…' if len(first) > 44 else ''}"
    if a.kind == "custom":
        return f"{getattr(a, 'custom_name', '') or '?'}(…)"
    if a.kind == "setTargCount":
        source = f" via {a.source_group_name} P{a.reinforce_priority}" if a.source_group_name else ""
        entries = list(getattr(a, "targ_counts", None) or [])
        if entries:
            comp = ", ".join(
                f"{e.get('count', 1)}x {e.get('unit_type', '?')}"
                + ("" if (e.get('weapon_type') or 'mapNone') == 'mapNone'
                   else f"/{e.get('weapon_type')}")
                for e in entries)
            return f"{a.group_name}.SetTargCount({comp}){source}"
        weapon = "" if a.weapon_type == "mapNone" else f", {a.weapon_type}"
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
        # v2: Mine/Smelter kommen als benannte Anker von der MiningGroup --
        # die Legacy-Koordinaten der Aktion sind hier bedeutungslos.
        # v2: mine/smelter come from the MiningGroup's named anchors -- the
        # action's legacy coordinates are meaningless here.
        gname = getattr(a, "group_name", "") or "?"
        return f"{gname}.StartMining({a.target_count} Trucks)"
    if a.kind == "sendAttackWave":
        waves = getattr(a, "wave_units", None) or []
        comp = ", ".join(f"{w.get('count', 1)}x {w.get('unit_type', '?')}" for w in waves) \
            or f"{a.target_count}x {a.unit_type}"
        mode = "Reinforce" if getattr(a, "spawn_mode", "spawn") == "reinforce" else "Spawn"
        name = getattr(a, "group_var_name", "") or ""
        tag = f" '{name}'" if name else ""
        return f"AttackWave{tag}(P{a.player}, {mode}: {comp})"
    if a.kind == "fightGroupCmd":
        cmd = _cmd_label(_GROUP_CMD_KEYS, getattr(a, "fg_command", "attackArea"))
        return tr("sum.act_group_cmd", g=getattr(a, 'group_name', '?'), cmd=cmd)
    if a.kind == "unitCmd":
        cmd = _cmd_label(_UNIT_CMD_KEYS, getattr(a, "fg_command", "move"))
        return tr("sum.act_unit_cmd", u=getattr(a, 'unit_ref', '?'), cmd=cmd)
    if a.kind == "defendArea":
        return f"DefendArea(P{a.player}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "repairBuildings":
        return f"RepairBuildings(P{a.player}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "empMissile":
        return f"EMP-Rakete(P{a.player}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "setMorale":
        mode = getattr(a, "morale_mode", "good") or "good"
        p = tr("sum.all_players") if int(getattr(a, "player", 0)) < 0 else f"P{a.player}"
        return f"Moral: {mode} ({p})"
    if a.kind == "setMusic":
        n = len(getattr(a, "songs", None) or [])
        return tr("sum.act_music", n=n, start=getattr(a, 'repeat_start', 0))
    if a.kind == "lavaFlowAni":
        fn = "FreezeFlow" if getattr(a, "flow_freeze", False) else "AnimateFlow"
        return f"{fn}{getattr(a, 'flow_dir', 'S')} @ ({a.x},{a.y})"
    if a.kind == "modUnitStats":
        n = len(getattr(a, "stat_mods", None) or [])
        return tr("sum.act_unit_stats", u=getattr(a, 'unit_type', '?'), n=n, p=a.player)
    return a.kind


# Befehls-Labels fuer Zusammenfassungen: dieselben i18n-Schluessel wie die
# Auswahlfelder im Aktions-Editor (action_editor.gc_*/uc_*), damit die
# Zusammenfassung in derselben Sprache steht wie die restliche Oberflaeche.
# Command labels for summaries: the same i18n keys as the action editor's
# combo boxes (action_editor.gc_*/uc_*) so the summary is in the same
# language as the rest of the UI.
_GROUP_CMD_KEYS = {
    "attackArea": "gc_attack_area", "attackEnemy": "gc_attack_enemy",
    "guardArea": "gc_guard_area", "patrol": "gc_patrol",
    "exitMap": "gc_exit_map",
    "combineFireOn": "gc_combine_fire_on", "combineFireOff": "gc_combine_fire_off",
    "setBuildRect": "gc_set_build_rect", "setIdleRect": "gc_set_idle_rect",
    "reinforceGroup": "gc_reinforce_group", "unReinforceGroup": "gc_un_reinforce_group",
    "addUnit": "gc_add_unit", "removeUnit": "gc_remove_unit",
    "lightsOn": "gc_lights_on", "lightsOff": "gc_lights_off",
    "clearTargCount": "gc_clear_targ_count",
}
_UNIT_CMD_KEYS = {
    "move": "uc_move", "patrol": "uc_patrol", "repair": "uc_repair",
    "stop": "uc_stop", "idle": "uc_idle", "unidle": "uc_unidle",
    "selfDestruct": "uc_self_destruct", "remove": "uc_remove",
    "transfer": "uc_transfer",
    "lightsOn": "uc_lights_on", "lightsOff": "uc_lights_off",
}


def _cmd_label(keys: dict, cmd: str) -> str:
    """Uebersetztes Befehls-Label oder der interne Name als Rueckfallebene.

    Translated command label, falling back to the internal name."""
    key = keys.get(cmd)
    if not key:
        return cmd or "?"
    label = tr(f"action_editor.{key}")
    return cmd if label == f"action_editor.{key}" else label

_KIND_TITLE = {
    "noop": "Platzhalter",
    "if": "Logik (Wenn / Schleife)",
    "message": "Nachricht",
    "createUnit": "Einheit erzeugen",
    "createDisaster": "Katastrophe",
    "createTrigger": "Trigger starten",
    "stopTrigger": "Trigger beenden",
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
    "addVictory": "Siegbedingung hinzufügen",
    "addDefeat": "Niederlagebedingung hinzufügen",
}


def action_kind_label(kind: str) -> str:
    """Titel einer Aktionskarte -- bevorzugt aus der Sprachdatei
    ([action_kinds]), damit die Karten nicht deutsch bleiben, wenn die
    Oberflaeche englisch laeuft.

    Title of an action card -- preferably from the language file
    ([action_kinds]) so the cards don't stay German while the UI is English."""
    label = tr(f"action_kinds.{kind}")
    if label != f"action_kinds.{kind}":
        return label
    return _KIND_TITLE.get(kind, kind)


def action_params_summary(a) -> str:
    """Kompakte einzeilige Parameterübersicht für eine Aktionskarte (leer für noop/if)."""
    if a.kind in ("noop", "if"):
        return ""
    if a.kind == "message":
        return f'"{getattr(a, "text", "")}"'
    if a.kind in ("addVictory", "addDefeat"):
        spec = dict(getattr(a, "condition_spec", None) or {})
        spec.setdefault("kind", "time")
        try:
            return condition_summary(Condition(**spec))
        except TypeError:
            return spec.get("kind", "time")
    if a.kind == "createUnit":
        entries = list(getattr(a, "unit_list", None) or [])
        if not entries:
            entries = [{"unit_type": getattr(a, "unit_type", "?"),
                        "weapon_type": getattr(a, "weapon_type", "mapNone"),
                        "x": getattr(a, "x", 0), "y": getattr(a, "y", 0)}]
        if len(entries) == 1:
            e = entries[0]
            weapon = e.get("weapon_type", "mapNone")
            w = "" if weapon == "mapNone" else "  " + tr("sum.p_weapon", w=weapon)
            return tr("sum.p_unit_at", u=e.get('unit_type', '?'), w=w,
                      p=getattr(a, 'player', 0), x=e.get('x', 0), y=e.get('y', 0))
        return tr("sum.p_units_n", n=len(entries), p=getattr(a, 'player', 0))
    if a.kind == "createDisaster":
        dtype = getattr(a, "disaster_type", "meteor")
        x, y = getattr(a, "x_expr", 0), getattr(a, "y_expr", 0)
        if dtype in ("storm", "vortex"):
            return tr("sum.p_disaster_area", t=dtype, x=x, y=y,
                      x2=getattr(a, 'x2_expr', 0), y2=getattr(a, 'y2_expr', 0))
        return tr("sum.p_disaster_at", t=dtype, x=x, y=y)
    if a.kind == "createTrigger":
        return f"→ {getattr(a, 'target', '?')}"
    if a.kind == "stopTrigger":
        return f"■ {getattr(a, 'target', '?')}"
    if a.kind == "recordBuilding":
        entries = list(getattr(a, "building_list", None) or [])
        if len(entries) <= 1:
            e = entries[0] if entries else {"building_type": getattr(a, "building_type", "?"),
                                             "x": getattr(a, "x", 0), "y": getattr(a, "y", 0)}
            return f"{getattr(a, 'group_name', '?')}  ·  {e.get('building_type', '?')}  @ ({e.get('x', 0)},{e.get('y', 0)})"
        return tr("sum.p_buildings_n", g=getattr(a, 'group_name', '?'), n=len(entries))
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
    if a.kind == "customCode":
        first = next((l.strip() for l in (getattr(a, "code", "") or "").splitlines()
                      if l.strip()), "")
        return f"C++  {first[:48]}{'…' if len(first) > 48 else ''}"
    if a.kind == "custom":
        cn = getattr(a, "custom_name", "") or "?"
        args = getattr(a, "custom_args", None) or {}
        comp = ", ".join(f"{k}={v}" for k, v in list(args.items())[:4])
        return f"{cn}({comp})"
    if a.kind == "showDialog":
        t = (getattr(a, "text", "") or "").replace("\n", " ")
        return f"\u201e{t[:48]}{'…' if len(t) > 48 else ''}\u201c"
    if a.kind == "setTargCount":
        gname = getattr(a, "group_name", "") or "?"
        src = getattr(a, "source_group_name", "") or ""
        via = f"  via {src} P{getattr(a, 'reinforce_priority', 0)}" if src else ""
        entries = list(getattr(a, "targ_counts", None) or [])
        if entries:
            comp = ", ".join(
                f"{e.get('count', 1)}× {(e.get('unit_type') or '?').replace('map', '')}"
                for e in entries)
            return f"{gname}  ·  {comp}{via}"
        return f"{gname}  ·  {getattr(a, 'unit_type', '?')}  = {getattr(a, 'target_count', 0)}{via}"
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
        # Mine/Smelter kommen als benannte Anker von der MiningGroup, nicht
        # aus den Legacy-Koordinaten der Aktion.
        # Mine/smelter come from the MiningGroup's named anchors, not from
        # the action's legacy coordinates.
        gname = getattr(a, "group_name", "") or "?"
        return f"'{gname}'  Trucks: {getattr(a, 'target_count', 1)}"
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
        cmd = _cmd_label(_GROUP_CMD_KEYS, getattr(a, "fg_command", "attackArea"))
        extra = ""
        if getattr(a, "fg_command", "") in ("attackArea", "guardArea", "setBuildRect", "patrol"):
            extra = f"  ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)}) → ({getattr(a, 'x2', 0)},{getattr(a, 'y2', 0)})"
        elif getattr(a, "fg_command", "") in ("reinforceGroup", "unReinforceGroup"):
            extra = f"  → '{getattr(a, 'target', '?')}'"
        return f"'{getattr(a, 'group_name', '?')}'  {cmd}{extra}"
    if a.kind == "unitCmd":
        cmd = _cmd_label(_UNIT_CMD_KEYS, getattr(a, "fg_command", "move"))
        extra = ""
        if getattr(a, "fg_command", "") in ("move", "attackGround"):
            extra = f"  @ ({getattr(a, 'x', 0)},{getattr(a, 'y', 0)})"
        elif getattr(a, "fg_command", "") == "patrol":
            pts = getattr(a, "patrol_points", None) or []
            extra = ("  " + tr("sum.p_waypoints", n=len(pts)) if pts
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
                + tr("sum.p_target", x=getattr(a, 'x2', 0), y=getattr(a, 'y2', 0)))
    if a.kind == "setMorale":
        p = tr("sum.all_players") if int(getattr(a, "player", 0)) < 0 else f"P{getattr(a, 'player', 0)}"
        return f"{getattr(a, 'morale_mode', 'good')}  ·  {p}"
    if a.kind == "setMusic":
        songs = getattr(a, "songs", None) or []
        return tr("sum.p_music", n=len(songs), start=getattr(a, 'repeat_start', 0))
    if a.kind == "lavaFlowAni":
        mode = tr("sum.p_stop") if getattr(a, "flow_freeze", False) else tr("sum.p_start")
        return tr("sum.p_lava_flow", mode=mode, dir=getattr(a, 'flow_dir', 'S'),
                  x=getattr(a, 'x', 0), y=getattr(a, 'y', 0))
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
    if k == "vehicleCargo":
        return tr("sum.win_vehiclecargo", u=display_name(c.unit_type), c=display_name(c.cargo),
                  cmp=cmp, n=c.count, p=c.player)
    if k == "research":
        return tr("sum.win_research", tech=c.tech_id, p=c.player)
    if k == "resource":
        return tr("sum.win_resource", res=c.resource, cmp=cmp, amt=c.amount, p=c.player)
    if k == "operational":
        return tr("sum.win_operational", b=display_name(c.building), cmp=cmp, n=c.count, p=c.player)
    if k == "point":
        return tr("sum.win_point", p=c.player, x=c.x, y=c.y)
    if k == "rect":
        return tr("sum.win_rect", p=c.player, x=c.x, y=c.y, w=c.width, h=c.height)
    if k == "attacked":
        return tr("sum.win_attacked", g=c.group_name)
    if k == "damaged":
        return tr("sum.win_damaged", g=c.group_name, d=c.damage_type)
    if k == "specialTarget":
        return tr("sum.win_specialtarget", u=c.target_unit, s=display_name(c.source_unit_type))
    if k == "onePlayerLeft":
        return tr("conditions.onePlayerLeft")
    if k == "evac":
        return tr("sum.win_evac", p=c.player)
    if k == "midas":
        return tr("sum.win_midas", marks=c.marks)
    if k == "kit":
        return tr("sum.win_kit", b=display_name(c.building), cmp=cmp, n=c.count, p=c.player)
    if k == "escape":
        return tr("sum.win_escape", u=display_name(c.unit_type), c=display_name(c.cargo), n=c.count,
                  x=c.x, y=c.y, w=c.width, h=c.height, p=c.player)
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
