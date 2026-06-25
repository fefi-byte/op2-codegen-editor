"""Codegen: Mission-Modell -> mission.cpp (TitanAPI C++23).

Reads a Mission object (mission_model.py) and produces the C++23 source
code that the TitanAPI library compiles into a runnable mission DLL.

Scope of this MVP:
  - LevelDesc / MapName / Techtree exports
  - DescBlock + DescBlockEx
  - Player setup (faction, human/AI, tech level, resources, population)
  - BaseLayout: buildings, vehicles, beacons, walls, tubes (visible tiles -- no offset)
  - Default victory/defeat conditions: noCC, time-based win/lose, building/vehicle counts

Not yet ported from the legacy codegen:
  - Custom triggers + per-trigger action lists (incl. if/then/else, conditions)
  - MiningGroup / BuildingGroup / ReinforceGroup
  - assignToGroup, startMiningOperation
A trigger / group present in the editor model is currently dropped with a
`// TODO` comment in the generated file.
"""
from __future__ import annotations

import re

from mission_model import (
    ActionCondition, BuildingGroupSpec, Colony, Condition, Mission, MissionType,
    MiningGroupSpec, PlayerSpec, ReinforceGroupSpec, TriggerAction, TriggerDef,
)


# ---------------------------------------------------------------------------
# Mapping tables: editor strings (legacy "mapFoo") -> TitanAPI enum members.
# ---------------------------------------------------------------------------

def _strip_map(name: str) -> str:
    """`mapCommandCenter` -> `CommandCenter`. Empty stays empty."""
    name = (name or "").strip()
    if name.startswith("map"):
        name = name[3:]
    return name


def mapid(name: str) -> str:
    """Editor map id -> `MapID::CommandCenter` style C++ literal."""
    stripped = _strip_map(name) or "None"
    return f"MapID::{stripped}"


_RESOURCE = {
    "resCommonOre": "Resource::CommonOre",
    "resRareOre": "Resource::RareOre",
    "resFood": "Resource::Food",
    "resKids": "Resource::Kids",
    "resWorkers": "Resource::Workers",
    "resScientists": "Resource::Scientists",
    "resColonists": "Resource::Colonists",
}

_COMPARE = {
    "cmpEqual": "Compare::Equal",
    "cmpLowerEqual": "Compare::LowerEqual",
    "cmpGreaterEqual": "Compare::GreaterEqual",
    "cmpLower": "Compare::Lower",
    "cmpGreater": "Compare::Greater",
}


# Editor tiles are 0-based (top-left = (0,0)); TitanAPI's visible tiles --
# the same numbers the in-game status bar shows -- are 1-based (top-left =
# (1,1)). So `visible = editor + 1` in both axes. Use _xy() everywhere the
# generator emits a Location literal.
def _xy(x: int, y: int) -> str:
    return f"{{ {int(x) + 1}, {int(y) + 1} }}"


# ---------------------------------------------------------------------------
# String helpers.
# ---------------------------------------------------------------------------

def _cpp_string(text: str) -> str:
    """Escape a Python string for a C++ string literal."""
    if text is None:
        return '""'
    out = (text.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t"))
    return f'"{out}"'


def _ident(text: str) -> str:
    """Lower the chance of a generated identifier colliding with a C++ keyword."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text or "")
    s = s.strip("_") or "id"
    if s[0].isdigit():
        s = "_" + s
    return s


def _mission_type_literal(mt: MissionType) -> str:
    """Map MissionType IntEnum -> `mission::MissionType::Colony` C++ literal."""
    name = {
        MissionType.Colony: "Colony",
        MissionType.AutoDemo: "AutoDemo",
        MissionType.Tutorial: "Tutorial",
        MissionType.MultiLandRush: "LandRush",
        MissionType.MultiSpaceRace: "SpaceRace",
        MissionType.MultiResourceRace: "ResourceRace",
        MissionType.MultiMidas: "Midas",
        MissionType.MultiLastOneStanding: "LastOneStanding",
    }.get(mt, "Colony")
    return f"mission::MissionType::{name}"


# ---------------------------------------------------------------------------
# Code emission.
# ---------------------------------------------------------------------------

def _emit_player_setup(idx: int, p: PlayerSpec) -> list[str]:
    """One Player's setup block (called from initProc())."""
    lines = [f"    // --- Player {idx} ---"]
    chain: list[str] = []
    chain.append("goEden()" if p.colony == Colony.Eden else "goPlymouth()")
    chain.append("goHuman()" if p.is_human else "goAI()")
    chain_str = ".".join(chain)
    lines.append(f"    Game::player({idx}).{chain_str};")

    if p.tech_level is not None and p.tech_level != 0:
        lines.append(f"    Game::player({idx}).setTechLevel({int(p.tech_level)});")

    # population
    w = 0 if p.workers     is None else int(p.workers)
    s = 0 if p.scientists  is None else int(p.scientists)
    k = 0 if p.kids        is None else int(p.kids)
    if (p.workers is not None) or (p.scientists is not None) or (p.kids is not None):
        lines.append(f"    Game::player({idx}).setPopulation({w}, {s}, {k});")

    # resources
    if p.common_ore is not None:
        lines.append(f"    Game::player({idx}).setCommonOre({int(p.common_ore)});")
    if p.rare_ore is not None:
        lines.append(f"    Game::player({idx}).setRareOre({int(p.rare_ore)});")
    if p.food is not None:
        lines.append(f"    Game::player({idx}).setFood({int(p.food)});")

    # individual researches (on top of tech_level)
    for tech in (p.researches or []):
        lines.append(f"    Game::player({idx}).markResearchComplete({int(tech)});")

    return lines


def _emit_base_layout(mission: Mission) -> list[str]:
    """Emit one BaseLayout (per player) and one createBase() call each.

    The editor stores units / beacons / walls per player; we partition by
    player and emit one layout block each so a multi-player mission still
    works.
    """
    by_player_units: dict[int, list] = {}
    for u in (mission.units or []):
        by_player_units.setdefault(int(u.player), []).append(u)

    # beacons + walls are world-owned (Gaia), but the editor groups them with
    # player 0 in practice; we attach beacons to player 0's layout (createMine
    # ignores the owner -- they belong to Gaia).
    beacons = list(mission.beacons or [])
    walls = list(mission.walls_tubes or [])

    players_with_content = set(by_player_units.keys()) | {0}
    lines: list[str] = []

    for pidx in sorted(players_with_content):
        units = by_player_units.get(pidx, [])
        if not (units or (pidx == 0 and (beacons or walls))):
            continue

        lines.append("")
        lines.append(f"    // --- Base layout for player {pidx} ---")
        lines.append(f"    {{")
        lines.append(f"        BaseLayout base;")

        if pidx == 0:
            # beacons (player-agnostic, but only emit once -> on player 0)
            if beacons:
                lines.append(f"        base.beacons = {{")
                for b in beacons:
                    if (b.beacon_type or "").endswith("MiningBeacon"):
                        # ore_type: -1 random, 0 common, 1 rare
                        ore = "abi::MineType::CommonOre"
                        if int(getattr(b, "ore_type", -1)) == 1:
                            ore = "abi::MineType::RareOre"
                        # yield_bars: -1 random, 0=Bar3, 1=Bar2, 2=Bar1
                        y = int(getattr(b, "yield_bars", -1))
                        yld = {0: "abi::OreYield::Bar3", 1: "abi::OreYield::Bar2",
                               2: "abi::OreYield::Bar1"}.get(y, "abi::OreYield::Bar2")
                        lines.append(f"            {{ {_xy(b.x, b.y)}, {ore}, {yld} }},")
                lines.append(f"        }};")
            # tubes + walls (Gaia)
            tubes = [w for w in walls if w.wall_type == "mapTube"]
            wall_items = [w for w in walls if w.wall_type and w.wall_type != "mapTube"]
            if tubes:
                lines.append(f"        base.tubes = {{")
                for t in tubes:
                    lines.append(f"            {{ {_xy(t.x, t.y)}, {_xy(t.x, t.y)} }},")
                lines.append(f"        }};")
            if wall_items:
                lines.append(f"        base.walls = {{")
                for w in wall_items:
                    lines.append(f"            {{ {_xy(w.x, w.y)}, {_xy(w.x, w.y)} }},")
                lines.append(f"        }};")

        # buildings vs vehicles for this player's units
        buildings = []
        vehicles = []
        for u in units:
            t = _strip_map(u.unit_type)
            # Heuristic: everything in BUILDING_FOOTPRINTS is a building; rest is a vehicle.
            if t in _BUILDING_TYPES:
                buildings.append(u)
            else:
                vehicles.append(u)

        if buildings:
            lines.append(f"        base.buildings = {{")
            for u in buildings:
                cargo = mapid(u.cargo) if (u.cargo and u.cargo != "mapNone") else "MapID::None"
                if cargo == "MapID::None":
                    lines.append(f"            {{ {_xy(u.x, u.y)}, {mapid(u.unit_type)} }},")
                else:
                    lines.append(
                        f"            {{ {_xy(u.x, u.y)}, {mapid(u.unit_type)}, {cargo} }},"
                    )
            lines.append(f"        }};")

        if vehicles:
            lines.append(f"        base.vehicles = {{")
            for u in vehicles:
                weapon = mapid(u.cargo) if (u.cargo and u.cargo != "mapNone") else "MapID::None"
                facing_idx = int(getattr(u, "rotation", 0)) % 8
                facing = ("UnitDirection::East", "UnitDirection::SouthEast", "UnitDirection::South",
                          "UnitDirection::SouthWest", "UnitDirection::West", "UnitDirection::NorthWest",
                          "UnitDirection::North", "UnitDirection::NorthEast")[facing_idx]
                lines.append(
                    f"            {{ {_xy(u.x, u.y)}, {mapid(u.unit_type)}, {weapon}, {facing} }},"
                )
            lines.append(f"        }};")

        lines.append(f"        createBase(Game::player({pidx}), base);")
        lines.append(f"    }}")

    return lines


# Building types in the editor (mapped from the legacy codegen). Anything
# else placed as a "unit" is treated as a vehicle by _emit_base_layout.
_BUILDING_TYPES = {
    "CommandCenter", "Tokamak", "CommonOreSmelter", "RareOreSmelter",
    "StructureFactory", "VehicleFactory", "ArachnidFactory",
    "Agridome", "Nursery", "University", "Residence",
    "CommonOreMine", "RareOreMine", "MagmaWell",
    "Spaceport", "GuardPost", "Observatory", "MedicalCenter",
    "RecreationFacility", "Forum", "DIRT", "MeteorDefense",
    "GORF", "Garage", "MagmaSmelter",
}


def _emit_condition(cond: Condition, is_victory: bool) -> list[str]:
    """Emit one win/lose condition (called from initProc())."""
    lines: list[str] = []
    obj = _cpp_string(cond.objective or ("Mission objective" if is_victory else ""))
    cmp_ = _COMPARE.get(cond.compare, "Compare::GreaterEqual")

    if cond.kind == "time":
        # time victory: win at mark M. There is no direct "win at mark X" helper,
        # but onMark(M, [] { op2::win(...) }) does the same thing.
        if is_victory:
            lines.append(
                f"    onMark({int(cond.marks)}, [] {{ op2::win({obj}); }});"
            )
        else:
            lines.append(
                f"    onMark({int(cond.marks)}, [] {{ op2::lose(); }});"
            )
    elif cond.kind == "noCC":
        lines.append(f"    loseIfNoCommandCenter({int(cond.player)});")
    elif cond.kind == "lastStanding":
        # Win when no other operational CC remains -- approximated with
        # onOperational for AllPlayers; in practice you'd give it a target
        # player. Punt to a TODO for now.
        lines.append(f"    // TODO last-one-standing victory not yet ported")
    elif cond.kind == "starship":
        lines.append(f"    // TODO starship victory not yet ported")
    elif cond.kind == "buildingCount":
        cond_var = f"_v_{abs(hash(repr(cond))) & 0xFFFF}"
        lines.append(
            f"    auto {cond_var} = onBuildingCount({int(cond.player)}, {cmp_}, {int(cond.count)});"
        )
        helper = "victoryWhen" if is_victory else "defeatWhen"
        if is_victory:
            lines.append(f"    {helper}({cond_var}, {obj});")
        else:
            lines.append(f"    {helper}({cond_var});")
    elif cond.kind == "vehicleCount":
        cond_var = f"_v_{abs(hash(repr(cond))) & 0xFFFF}"
        lines.append(
            f"    auto {cond_var} = onVehicleCount({int(cond.player)}, {cmp_}, {int(cond.count)});"
        )
        helper = "victoryWhen" if is_victory else "defeatWhen"
        if is_victory:
            lines.append(f"    {helper}({cond_var}, {obj});")
        else:
            lines.append(f"    {helper}({cond_var});")
    elif cond.kind == "research":
        cond_var = f"_v_{abs(hash(repr(cond))) & 0xFFFF}"
        lines.append(f"    auto {cond_var} = onResearch({int(cond.tech_id)}, {{}}, {int(cond.player)});")
        if is_victory:
            lines.append(f"    victoryWhen({cond_var}, {obj});")
        else:
            lines.append(f"    defeatWhen({cond_var});")
    elif cond.kind == "resource":
        res = _RESOURCE.get(cond.resource, "Resource::CommonOre")
        cond_var = f"_v_{abs(hash(repr(cond))) & 0xFFFF}"
        lines.append(
            f"    auto {cond_var} = onResource({res}, {cmp_}, {int(cond.amount)}, {{}}, {int(cond.player)});"
        )
        if is_victory:
            lines.append(f"    victoryWhen({cond_var}, {obj});")
        else:
            lines.append(f"    defeatWhen({cond_var});")
    elif cond.kind == "operational":
        cond_var = f"_v_{abs(hash(repr(cond))) & 0xFFFF}"
        lines.append(
            f"    auto {cond_var} = onOperational({int(cond.player)}, {mapid(cond.building)}, {cmp_}, {int(cond.count)});"
        )
        if is_victory:
            lines.append(f"    victoryWhen({cond_var}, {obj});")
        else:
            lines.append(f"    defeatWhen({cond_var});")
    else:
        lines.append(f"    // TODO unsupported condition kind: {cond.kind}")
    return lines


# ---------------------------------------------------------------------------
# ActionConditions: per-action gating predicates -> C++ bool expressions.
# ---------------------------------------------------------------------------

def _emit_action_condition_expr(c: ActionCondition) -> str:
    """Returns a single C++ bool expression for `c`, already negated if needed."""
    cmp_op = {
        "cmpEqual": "==",
        "cmpLowerEqual": "<=",
        "cmpGreaterEqual": ">=",
        "cmpLower": "<",
        "cmpGreater": ">",
    }.get(c.compare, ">=")

    if c.kind == "buildingAtLocation":
        expr = f"(GameMap::unitOnTile({_xy(c.x, c.y)}).type() == {mapid(c.building_type)})"
    elif c.kind == "buildingCount":
        expr = f"(Game::playerUnitCount({int(c.player)}, {mapid(c.building_type)}) {cmp_op} {int(c.value)})"
    elif c.kind == "playerResource":
        # Map editor resource string -> Player::xxx() reader.
        getter = {
            "resCommonOre": "commonOre",
            "resRareOre": "rareOre",
            "resFood": "food",
            "resKids": "kids",
            "resWorkers": "workers",
            "resScientists": "scientists",
            "resColonists": "population",
        }.get(c.resource, "commonOre")
        expr = f"(Game::player({int(c.player)}).{getter}() {cmp_op} {int(c.value)})"
    elif c.kind == "hasTech":
        expr = f"Game::player({int(c.player)}).hasTechnology({int(c.tech_id)})"
    elif c.kind == "unitDamage":
        # Without a stable unit handle, the closest TitanAPI proxy is "any of
        # this player's units of this type below `value` HP" via the unit
        # range. Hand-emitted lambda; expensive at runtime but rarely used.
        expr = (f"std::ranges::any_of(Game::unitsOf({int(c.player)}), "
                f"[](Unit u){{ return (u.type() == {mapid(c.building_type)}) && (u.damage() {cmp_op} {int(c.value)}); }})")
    else:
        expr = "true /* TODO: unsupported ActionCondition kind */"

    if getattr(c, "negate", False):
        return f"!({expr})"
    return expr


def _emit_action_conditions_combined(action: TriggerAction) -> str | None:
    """Combine an action's `conditions` list via `condition_logic` (AND/OR)."""
    if not action.conditions:
        return None
    parts = [_emit_action_condition_expr(c) for c in action.conditions]
    op = " && " if (action.condition_logic or "and").lower() == "and" else " || "
    if len(parts) == 1:
        return parts[0]
    return "(" + op.join(parts) + ")"


# ---------------------------------------------------------------------------
# TriggerActions: emit C++ statements (recursive for if/then/else).
# ---------------------------------------------------------------------------

def _emit_action_body(action: TriggerAction, indent: str, ctx: dict) -> list[str]:
    """Emit the raw statements for one non-`if` action (without the IF gate).

    For `if` we instead emit an `if (...) { ... } else { ... }` block via
    `_emit_action()` so each branch can recurse with its own gating.
    """
    k = action.kind
    if k == "noop":
        return [f"{indent}// (empty action)"]

    if k == "message":
        return [f"{indent}Game::addMessage({_cpp_string(action.text)});"]

    if k == "createUnit":
        weapon = (mapid(action.weapon_type) if (action.weapon_type and action.weapon_type != "mapNone")
                  else "MapID::None")
        return [
            f"{indent}op2::ignore(Game::createUnit({mapid(action.unit_type)}, "
            f"{_xy(action.x, action.y)}, Game::player({int(action.player)}), {weapon}));"
        ]

    if k == "createTrigger":
        # Editor model: "createTrigger" creates ANOTHER editor-defined trigger
        # at runtime. In TitanAPI we have first-class trigger handles, so
        # re-invoking the trigger factory is the equivalent. We emit a call
        # to a helper function the codegen generates per trigger (see ctx).
        target = ctx["trigger_helpers"].get(action.target, None)
        if target:
            return [f"{indent}{target}();"]
        return [f"{indent}// TODO createTrigger target '{action.target}' not found"]

    if k == "recordBuilding":
        # Editor: pick a BuildingGroup, then add a building to its roster so
        # the group rebuilds it. TitanAPI equivalent: Group::recordBuilding.
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            return [f"{indent}// TODO recordBuilding: building group '{action.group_name}' not declared"]
        cargo = (mapid(action.weapon_type) if (action.weapon_type and action.weapon_type != "mapNone")
                 else "MapID::None")
        return [
            f"{indent}{var}.recordBuilding({_xy(action.x, action.y)}, "
            f"{mapid(action.building_type)}, {cargo});"
        ]

    if k == "recordTube":
        return [f"{indent}Game::createTube({_xy(action.x, action.y)});"]

    if k == "recordWall":
        wt = action.wall_type or "mapWall"
        return [f"{indent}Game::createWall({mapid(wt)}, {_xy(action.x, action.y)});"]

    if k == "setTargCount":
        # Tell a Fight/Building group "keep this many of (unit, weapon) on strength".
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            return [f"{indent}// TODO setTargCount: group '{action.group_name}' not declared"]
        weapon = (mapid(action.weapon_type) if (action.weapon_type and action.weapon_type != "mapNone")
                  else "MapID::None")
        return [
            f"{indent}{var}.setTargCount({mapid(action.unit_type)}, {weapon}, "
            f"{int(action.target_count)});"
        ]

    if k == "startMiningOperation":
        # Look up the named mining group; resolve the mine + smelter via the
        # tile-occupancy index. The user sets {x,y} = mine, {x2,y2} = smelter
        # in the editor model.
        var = ctx["group_vars"].get(action.mining_group_name or action.group_name, None)
        if not var:
            return [f"{indent}// TODO startMiningOperation: mining group not declared"]
        ore = (action.ore_type or "common").lower()
        # Use the mine + smelter coordinates that the editor stored on the action.
        return [
            f"{indent}{{",
            f"{indent}    Unit _mine    = GameMap::unitOnTile({_xy(action.x, action.y)});",
            f"{indent}    Unit _smelter = GameMap::unitOnTile({_xy(action.x2, action.y2)});",
            f"{indent}    if (_mine.id() && _smelter.id())",
            f"{indent}        {var}.setupMining(_mine, _smelter, "
            f"{_xy(action.rect_x, action.rect_y)}, "
            f"{_xy(action.rect_x + action.rect_width, action.rect_y + action.rect_height)});",
            f"{indent}}}",
        ]

    if k == "assignToGroup":
        # Poll once for a building at (x,y); once found, hand it to the group.
        # TitanAPI's recurring trigger is onTick(N, cb, oneShot=false) -- we use
        # a 10-tick interval matching the legacy codegen pattern.
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            return [f"{indent}// TODO assignToGroup: target group '{action.group_name}' not declared"]
        return [
            f"{indent}onTick(10, [] {{",
            f"{indent}    Unit _u = GameMap::unitOnTile({_xy(action.x, action.y)});",
            f"{indent}    if (_u.id() && _u.type() == {mapid(action.building_type)}) {{",
            f"{indent}        {var}.takeUnit(_u);",
            f"{indent}    }}",
            f"{indent}}}, /*oneShot=*/false);",
        ]

    return [f"{indent}// TODO unsupported action kind: {k}"]


def _emit_action(action: TriggerAction, indent: str, ctx: dict) -> list[str]:
    """Emit one action; recurses for kind == 'if' (then/else blocks)."""
    if action.kind == "if":
        out: list[str] = []
        cond = _emit_action_conditions_combined(action) or "true"
        out.append(f"{indent}if ({cond}) {{")
        for child in (action.then_actions or []):
            out.extend(_emit_action(child, indent + "    ", ctx))
        if action.else_actions:
            out.append(f"{indent}}} else {{")
            for child in action.else_actions:
                out.extend(_emit_action(child, indent + "    ", ctx))
        out.append(f"{indent}}}")
        return out

    # Non-`if`: wrap the body in an IF gate if the action has its own conditions.
    cond = _emit_action_conditions_combined(action)
    if cond is None:
        return _emit_action_body(action, indent, ctx)
    body = _emit_action_body(action, indent + "    ", ctx)
    return [f"{indent}if ({cond}) {{", *body, f"{indent}}}"]


def _emit_action_list(actions: list[TriggerAction], indent: str, ctx: dict) -> list[str]:
    out: list[str] = []
    for a in (actions or []):
        out.extend(_emit_action(a, indent, ctx))
    return out


# ---------------------------------------------------------------------------
# Custom Triggers: emit a small helper that creates the trigger + callback.
# ---------------------------------------------------------------------------

def _emit_trigger_helper(t: TriggerDef, ctx: dict) -> list[str]:
    """Emit `static void make_<name>() { ... onXXX(..., []{ ...actions... }); }`.

    The helper is invoked from initProc for triggers enabled at start, and
    from `createTrigger` actions at runtime for triggers created on demand.
    """
    helper = ctx["trigger_helpers"][t.name]
    one_shot = "true" if t.one_shot else "false"
    cmp_ = _COMPARE.get(t.compare, "Compare::GreaterEqual")

    # Build the callback body from t.actions.
    body = _emit_action_list(t.actions, "        ", ctx)
    cb = ["    [] {"]
    cb.extend(body)
    cb.append("    }")
    cb_str = "\n".join(cb)

    lines: list[str] = []
    lines.append(f"// Trigger '{t.name}' (condition={t.condition})")
    lines.append(f"static void {helper}() {{")

    if t.condition == "time":
        lines.append(f"    onMark({int(t.marks)},")
        lines.append(cb_str + ",")
        lines.append(f"    /*oneShot=*/{one_shot});")
    elif t.condition == "buildingCount":
        lines.append(f"    onBuildingCount({int(t.player)}, {cmp_}, {int(t.count)},")
        lines.append(cb_str + ",")
        lines.append(f"    /*oneShot=*/{one_shot});")
    elif t.condition == "vehicleCount":
        lines.append(f"    onVehicleCount({int(t.player)}, {cmp_}, {int(t.count)},")
        lines.append(cb_str + ",")
        lines.append(f"    /*oneShot=*/{one_shot});")
    elif t.condition == "research":
        lines.append(f"    onResearch({int(t.tech_id)},")
        lines.append(cb_str + ",")
        lines.append(f"    {int(t.player)}, /*oneShot=*/{one_shot});")
    elif t.condition == "resource":
        res = _RESOURCE.get(t.resource, "Resource::CommonOre")
        lines.append(f"    onResource({res}, {cmp_}, {int(t.amount)},")
        lines.append(cb_str + ",")
        lines.append(f"    {int(t.player)}, /*oneShot=*/{one_shot});")
    elif t.condition == "operational":
        lines.append(f"    onOperational({int(t.player)}, {mapid(t.building)}, {cmp_}, {int(t.count)},")
        lines.append(cb_str + ",")
        lines.append(f"    /*oneShot=*/{one_shot});")
    elif t.condition == "point":
        # TitanAPI has no native point trigger in this header pass; approximate
        # with an onTick(1, ..., oneShot=false) that polls the tile.
        lines.append(f"    onTick(10, [] {{")
        lines.append(f"        Unit _u = GameMap::unitOnTile({_xy(t.x, t.y)});")
        lines.append(f"        if (_u.id() && _u.ownerId() == {int(t.player)}) {{")
        # Inline the actions (one extra indent step)
        for line in _emit_action_list(t.actions, "            ", ctx):
            lines.append(line)
        lines.append(f"        }}")
        lines.append(f"    }}, /*oneShot=*/false);")
    elif t.condition == "rect":
        lines.append(f"    onTick(10, [] {{")
        lines.append(f"        Region _r{{ {_xy(t.x, t.y)}, "
                     f"{_xy(t.x + t.width, t.y + t.height)} }};")
        lines.append(f"        for (Unit _u : _r.units()) if (_u.ownerId() == {int(t.player)}) {{")
        for line in _emit_action_list(t.actions, "            ", ctx):
            lines.append(line)
        lines.append(f"            break;")
        lines.append(f"        }}")
        lines.append(f"    }}, /*oneShot=*/false);")
    else:
        lines.append(f"    // TODO unsupported trigger condition: {t.condition}")

    lines.append(f"}}")
    return lines


# ---------------------------------------------------------------------------
# Groups: mining / building / reinforce.
# ---------------------------------------------------------------------------

def _emit_groups(mission: Mission, ctx: dict) -> list[str]:
    """Emit Group variable declarations + setup inside initProc."""
    lines: list[str] = []
    mining = list(getattr(mission, "mining_groups", None) or [])
    buildings = list(getattr(mission, "building_groups", None) or [])
    reinforces = list(getattr(mission, "reinforce_groups", None) or [])
    if not (mining or buildings or reinforces):
        return lines

    lines.append("")
    lines.append("    // --- Groups (mining / building / reinforce) ---")

    for g in mining:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = createMiningGroup(Game::player({int(g.player)}));")
        # The actual setupMining (mine + smelter unit handles) is normally
        # driven from a `startMiningOperation` action once the buildings are
        # placed. If the editor stored a static mine/smelter pair on the
        # group itself, wire it up here.
        if getattr(g, "has_setup", False) and (g.mine_x or g.mine_y or g.smelter_x or g.smelter_y):
            lines.append(f"    {{")
            lines.append(f"        Unit _mine    = GameMap::unitOnTile({_xy(g.mine_x, g.mine_y)});")
            lines.append(f"        Unit _smelter = GameMap::unitOnTile({_xy(g.smelter_x, g.smelter_y)});")
            lines.append(f"        if (_mine.id() && _smelter.id())")
            lines.append(f"            {var}.setupMining(_mine, _smelter, "
                         f"{_xy(g.rect_x, g.rect_y)}, "
                         f"{_xy(g.rect_x + g.rect_width, g.rect_y + g.rect_height)});")
            lines.append(f"    }}")

    for g in buildings:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = createBuildingGroup(Game::player({int(g.player)}));")
        lines.append(f"    {var}.setBuildRect({_xy(g.rect_x, g.rect_y)}, "
                     f"{_xy(g.rect_x + g.rect_width, g.rect_y + g.rect_height)});")

    for g in reinforces:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = createBuildingGroup(Game::player({int(g.player)}));")
        for t in (getattr(g, "targets", None) or []):
            target_var = ctx["group_vars"].get(t.group_name)
            if target_var:
                lines.append(f"    {var}.recordVehReinforceGroup({target_var}, "
                             f"{int(getattr(t, 'priority', 1000))});")

    return lines


def _build_codegen_context(mission: Mission) -> dict:
    """Collect names -> C++ variable / helper symbols so emitters can cross-reference."""
    ctx: dict = {
        "trigger_helpers": {},   # trigger name -> "make_<n>"
        "group_vars": {},        # group name   -> "<g_n>"
    }
    for i, t in enumerate(mission.triggers or []):
        ctx["trigger_helpers"][t.name] = f"_trigger_{i}_{_ident(t.name)}"
    idx = 0
    for g in (getattr(mission, "mining_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
    for g in (getattr(mission, "building_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
    for g in (getattr(mission, "reinforce_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
    return ctx


def generate_levelmain(mission: Mission) -> str:
    """Emit the full `mission.cpp` for `mission`.

    The output is a single self-contained translation unit using the TitanAPI
    op2:: facade. Folder writers in mission_project.write_mission_folder
    detect this output (it starts with a `//` comment and contains `op2.hpp`)
    and prefer it over the static template fallback.
    """
    out: list[str] = []
    add = out.append
    ctx = _build_codegen_context(mission)

    add(f"// mission.cpp -- generated from the editor model for: {mission.name}")
    add("// Built against TitanAPI (https://github.com/leviathan400/TitanAPI).")
    add("")
    add('#include "op2.hpp"')
    add('#include "op2/trigger.hpp"')
    add('#include "op2/base.hpp"')
    add('#include "op2/groups.hpp"')
    add('#include "op2_mission.hpp"')
    add('#include "op2_log.hpp"')
    add('#include "op2_crash.hpp"')
    add("#include <algorithm>")
    add("#include <ranges>")
    add("")
    add("using namespace op2;")
    add("")

    # Forward declarations for trigger helpers (so a `createTrigger` action
    # earlier in the file can invoke a trigger declared further down).
    for t in (mission.triggers or []):
        add(f"static void {ctx['trigger_helpers'][t.name]}();")
    if mission.triggers:
        add("")

    # Group variables live at file scope so any trigger callback can see them.
    # Real value is assigned in initProc -- this is just a forward declaration.
    for g in (getattr(mission, "mining_groups", None) or []) \
           + (getattr(mission, "building_groups", None) or []) \
           + (getattr(mission, "reinforce_groups", None) or []):
        add(f"static Group {ctx['group_vars'][g.name]};")
    if mission.mining_groups or mission.building_groups or mission.reinforce_groups:
        add("")

    # --- Exports ---
    num_players = max(1, len(mission.players or []) or 1)
    add(f'extern "C" __declspec(dllexport) char LevelDesc[]    = {_cpp_string(mission.name)};')
    add(f'extern "C" __declspec(dllexport) char MapName[]      = {_cpp_string(mission.map)};')
    add(f'extern "C" __declspec(dllexport) char TechtreeName[] = "MULTITEK.TXT";')
    add(f"extern \"C\" __declspec(dllexport) mission::ModDesc   DescBlock   = "
        f"{{ {_mission_type_literal(mission.type)}, {num_players}, 12, 0 }};")
    add('extern "C" __declspec(dllexport) mission::ModDescEx DescBlockEx = '
        '{ 0, 0, 0, 0, 0, 0, 0, 0 };')
    add("")

    # --- initProc ---
    add("static void initProc() {")
    add('    log::line("InitProc: starting");')
    add("")

    # Players
    for idx, p in enumerate(mission.players or []):
        for line in _emit_player_setup(idx, p):
            add(line)
        add("")

    # Base layout
    for line in _emit_base_layout(mission):
        add(line)

    # Groups (declared at file scope, assigned here)
    for line in _emit_groups(mission, ctx):
        add(line)

    # Start message
    if mission.start_message and (mission.start_message.text or "").strip():
        add("")
        add(f"    Game::addMessage({_cpp_string(mission.start_message.text)});")

    # Victory / defeat conditions
    if mission.victories:
        add("")
        add("    // --- Victory conditions ---")
        for c in mission.victories:
            for line in _emit_condition(c, is_victory=True):
                add(line)
    if mission.defeats:
        add("")
        add("    // --- Defeat conditions ---")
        for c in mission.defeats:
            for line in _emit_condition(c, is_victory=False):
                add(line)

    # Custom triggers: trigger HELPER functions are emitted at file scope
    # (see below); here we invoke the ones the editor marked as enabled at
    # start. Disabled-at-start triggers come into existence only when another
    # trigger calls them via a createTrigger action.
    enabled = [t for t in (mission.triggers or []) if getattr(t, "enabled_at_start", True)]
    if enabled:
        add("")
        add("    // --- Custom triggers (enabled at start) ---")
        for t in enabled:
            add(f"    {ctx['trigger_helpers'][t.name]}();")

    add("")
    add('    op2::ignore(Game::forceMoraleGood());')
    add('    log::line("InitProc: done");')
    add("}")
    add("")

    # Custom-trigger helper functions live at file scope so they (a) can be
    # called from a createTrigger action via forward decl and (b) capture
    # the file-scope group vars via the global lookup.
    for t in (mission.triggers or []):
        for line in _emit_trigger_helper(t, ctx):
            add(line)
        add("")

    # --- aiProc ---
    add("static void aiProc() {}")
    add("")

    # --- Guarded exports + DllMain ---
    add('extern "C" __declspec(dllexport) int  InitProc() { crash::guard("InitProc", &initProc); return 1; }')
    add('extern "C" __declspec(dllexport) void AIProc()   { crash::guard("AIProc",   &aiProc); }')
    add("")
    add('extern "C" __declspec(dllexport) void GetSaveRegions(mission::SaveRegion* p) {')
    add('    if (p) { p->pData = nullptr; p->size = 0; }')
    add('}')
    add("")
    add('extern "C" int __stdcall DllMain(void*, unsigned long reason, void*) {')
    add("    if (reason == 1 /* DLL_PROCESS_ATTACH */) {")
    add('        crash::installHandler();')
    add('        log::setTickSource([] { return Game::tick(); });')
    add("    }")
    add("    return 1;")
    add("}")

    return "\n".join(out) + "\n"
