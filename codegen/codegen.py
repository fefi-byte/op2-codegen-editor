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
    ActionCondition, BuildingGroupSpec, Colony, Condition, DifficultySetup, FindUnitCheck,
    Mission, MissionType, PlayerSpec, ReinforceGroupSpec, TriggerAction, TriggerDef, VariableDef,
)


def _expr_or_int(v) -> str:
    """Gibt den Wert als C++-Literal-String zurueck: int oder Ausdruck unveraendert."""
    if isinstance(v, str):
        _validate_cpp_expr(v)
        return v
    return str(int(v))


def _validate_cpp_expr(expr: str) -> None:
    """Very small preflight check for obviously broken inline expressions."""
    text = (expr or "").strip()
    if not text:
        return
    pairs = {")": "(", "]": "[", "}": "{"}
    opens = set(pairs.values())
    stack: list[str] = []
    for ch in text:
        if ch in opens:
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                raise ValueError(f"Ungueltiger Ausdruck: {expr}")
            stack.pop()
    if stack:
        raise ValueError(f"Ungueltiger Ausdruck: {expr}")


def _visible_expr(v) -> str:
    """Editor-Tile (0-based) -> sichtbare OP2-Koordinate (1-based), als C++-Ausdruck."""
    if isinstance(v, str):
        _validate_cpp_expr(v)
        return f"(int(({v}) + 1))"
    return str(int(v) + 1)


def _loc_expr(x, y) -> str:
    """Emit a Location literal that may contain runtime expressions."""
    return f"Location{{ {_visible_expr(x)}, {_visible_expr(y)} }}"


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

    # resources (support int and str expressions)
    if p.common_ore is not None:
        lines.append(f"    Game::player({idx}).setCommonOre({_expr_or_int(p.common_ore)});")
    if p.rare_ore is not None:
        lines.append(f"    Game::player({idx}).setRareOre({_expr_or_int(p.rare_ore)});")
    if p.food is not None:
        lines.append(f"    Game::player({idx}).setFood({_expr_or_int(p.food)});")

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
        expr = f"(Game::playerUnitCount({int(c.player)}, {mapid(c.building_type)}) {cmp_op} {_expr_or_int(c.value)})"
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
        expr = f"(Game::player({int(c.player)}).{getter}() {cmp_op} {_expr_or_int(c.value)})"
    elif c.kind == "hasTech":
        expr = f"Game::player({int(c.player)}).hasTechnology({int(c.tech_id)})"
    elif c.kind == "unitDamage":
        # Without a stable unit handle, the closest TitanAPI proxy is "any of
        # this player's units of this type below `value` HP" via the unit
        # range. Hand-emitted lambda; expensive at runtime but rarely used.
        expr = (f"std::ranges::any_of(Game::unitsOf({int(c.player)}), "
                f"[](Unit u){{ return (u.type() == {mapid(c.building_type)}) && (u.damage() {cmp_op} {_expr_or_int(c.value)}); }})")
    elif c.kind == "varCheck":
        var = getattr(c, "var_name", "") or "unknownVar"
        expr = f"({var} {cmp_op} {_expr_or_int(c.value)})"
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

    if k == "createDisaster":
        dtype = getattr(action, "disaster_type", "meteor") or "meteor"
        if dtype == "meteor":
            return [
                f"{indent}op2::ignore(Game::createMeteor("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
                f"{int(getattr(action, 'size', -1))}, "
                f"{'true' if getattr(action, 'now', False) else 'false'}));"
            ]
        if dtype == "earthquake":
            return [
                f"{indent}op2::ignore(Game::createEarthquake("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
                f"{_expr_or_int(getattr(action, 'magnitude', 1))}, "
                f"{'true' if getattr(action, 'now', False) else 'false'}));"
            ]
        if dtype == "storm":
            return [
                f"{indent}op2::ignore(Game::createStorm("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
                f"{_loc_expr(getattr(action, 'x2_expr', 0), getattr(action, 'y2_expr', 0))}, "
                f"{_expr_or_int(getattr(action, 'duration', 100))}, "
                f"{'true' if getattr(action, 'now', False) else 'false'}));"
            ]
        if dtype == "vortex":
            return [
                f"{indent}op2::ignore(Game::createVortex("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
                f"{_loc_expr(getattr(action, 'x2_expr', 0), getattr(action, 'y2_expr', 0))}, "
                f"{_expr_or_int(getattr(action, 'duration', 100))}, "
                f"{'true' if getattr(action, 'now', False) else 'false'}));"
            ]
        if dtype == "eruption":
            zone = getattr(action, "lava_zone", None) or []
            lines = []
            for xy in zone:
                lines.append(
                    f"{indent}GameMap::setLavaPossible({_loc_expr(int(xy[0]), int(xy[1]))}, true);"
                )
            lines.append(
                f"{indent}op2::ignore(Game::createEruption("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
                f"{int(getattr(action, 'spread_speed', 15))}, "
                f"{'true' if getattr(action, 'now', False) else 'false'}));"
            )
            return lines
        if dtype == "blight":
            return [
                f"{indent}Game::createBlight("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))});"
            ]
        if dtype == "unblight":
            return [
                f"{indent}Game::unsetBlight("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))});"
            ]
        return [f"{indent}// TODO unsupported disaster type: {dtype}"]

    if k == "createMeteor":
        return [
            f"{indent}op2::ignore(Game::createMeteor("
            f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
            f"{int(getattr(action, 'size', -1))}, "
            f"{'true' if getattr(action, 'now', False) else 'false'}));"
        ]

    if k == "createEarthquake":
        return [
            f"{indent}op2::ignore(Game::createEarthquake("
            f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
            f"{_expr_or_int(getattr(action, 'magnitude', 1))}, "
            f"{'true' if getattr(action, 'now', False) else 'false'}));"
        ]

    if k == "createStorm":
        return [
            f"{indent}op2::ignore(Game::createStorm("
            f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
            f"{_loc_expr(getattr(action, 'x2_expr', 0), getattr(action, 'y2_expr', 0))}, "
            f"{_expr_or_int(getattr(action, 'duration', 100))}, "
            f"{'true' if getattr(action, 'now', False) else 'false'}));"
        ]

    if k == "createVortex":
        return [
            f"{indent}op2::ignore(Game::createVortex("
            f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, "
            f"{_loc_expr(getattr(action, 'x2_expr', 0), getattr(action, 'y2_expr', 0))}, "
            f"{_expr_or_int(getattr(action, 'duration', 100))}, "
            f"{'true' if getattr(action, 'now', False) else 'false'}));"
        ]

    if k == "createBlight":
        return [
            f"{indent}Game::createBlight("
            f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))});"
        ]

    if k == "unsetBlight":
        return [
            f"{indent}Game::unsetBlight("
            f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))});"
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
            f"{_expr_or_int(action.target_count)});"
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

    if k == "modVar":
        var = getattr(action, "var_name", "") or "unknownVar"
        mode = getattr(action, "mod_mode", "inc") or "inc"
        if mode == "inc":
            return [f"{indent}{var}++;"]
        if mode == "dec":
            return [f"{indent}{var}--;"]
        expr = getattr(action, "var_expr", "") or "0"
        return [f"{indent}{var} = {expr};"]

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

def _emit_trigger_helper(t: TriggerDef, helper: str, ctx: dict) -> list[str]:
    """Emit `static void make_<name>() { ... onXXX(..., []{ ...actions... }); }`.

    The helper is invoked from initProc for triggers enabled at start, and
    from `createTrigger` actions at runtime for triggers created on demand.
    """
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
        lines.append(f"    onMark({_expr_or_int(t.marks)},")
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
    elif t.condition == "findUnit":
        # Pollt alle 10 Ticks, prueft jeden Eintrag der `unit_checks`-Liste
        # auf "einsatzbereit" (isLive && type match && enabled). Sobald
        # ALLE Eintraege gleichzeitig ready sind, feuern die Aktionen.
        checks = list(getattr(t, "unit_checks", None) or [])
        if not checks:
            lines.append(f"    // findUnit ohne Eintraege -- nichts zu pruefen")
            lines.append(f"}}")
            return lines
        # oneShot=false; wir disablen den Trigger nach erstem Match manuell,
        # damit die polling-Schleife wiederholt prueft, aber die Aktionen
        # nur einmal feuern.
        oneShot_inline = t.one_shot
        lines.append(f"    static Trigger _self;")
        lines.append(f"    _self = onTick(10, [] {{")
        for i, c in enumerate(checks):
            lines.append(f"        Unit _u{i} = GameMap::unitOnTile({_xy(c.x, c.y)});")
            lines.append(f"        bool _ready{i} = _u{i}.isLive() && _u{i}.type() == "
                         f"{mapid(c.unit_type)} && _u{i}.enabled();")
        all_ready = " && ".join(f"_ready{i}" for i in range(len(checks)))
        lines.append(f"        if (!({all_ready})) return;")
        for line in _emit_action_list(t.actions, "        ", ctx):
            lines.append(line)
        if oneShot_inline:
            lines.append(f"        _self.disable();")
        lines.append(f"    }}, /*oneShot=*/false);")
    else:
        lines.append(f"    // TODO unsupported trigger condition: {t.condition}")

    lines.append(f"}}")
    return lines


# ---------------------------------------------------------------------------
# Groups: building / reinforce.
# ---------------------------------------------------------------------------

def _emit_groups(mission: Mission, ctx: dict) -> list[str]:
    """Emit Group variable declarations + setup inside initProc."""
    lines: list[str] = []
    buildings = list(getattr(mission, "building_groups", None) or [])
    reinforces = list(getattr(mission, "reinforce_groups", None) or [])
    if not (buildings or reinforces):
        return lines

    lines.append("")
    lines.append("    // --- Groups (building / reinforce) ---")

    for g in buildings:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = createBuildingGroup(Game::player({int(g.player)}));")
        lines.append(f"    {var}.setBuildRect({_xy(g.rect_x, g.rect_y)}, "
                     f"{_xy(g.rect_x + g.rect_width, g.rect_y + g.rect_height)});")
        lines.extend(_emit_take_units(mission, g, var, label="BuildingGroup"))

    for g in reinforces:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = createBuildingGroup(Game::player({int(g.player)}));")
        # Vehicle-Factories (oder andere Builder-Einheiten) der ReinforceGroup
        # zuweisen, sonst hat sie keine Quelle fuer Verstaerkungen.
        lines.extend(_emit_take_units(mission, g, var, label="ReinforceGroup"))
        for t in (getattr(g, "targets", None) or []):
            target_var = ctx["group_vars"].get(t.group_name)
            if target_var:
                lines.append(f"    {var}.recordVehReinforceGroup({target_var}, "
                             f"{int(getattr(t, 'priority', 1000))});")

    return lines


def _emit_take_units(mission: Mission, group, var: str, *, label: str) -> list[str]:
    """Emit a Game::unitsOf-Schleife die im Editor markierte Units der Group zuweist.

    Sucht die UnitSpec-Eintraege mit passender uid in mission.units, sammelt
    ihre (visible) Tile-Position und generiert einen Loop, der die laufenden
    Units der passenden Player+Position via Group.takeUnit einschiebt.
    Funktioniert sowohl fuer Vehicles (Factories sind Buildings) als auch
    fuer Combat-Units / ConVecs / Trucks.
    """
    uids = list(getattr(group, "unit_ids", None) or [])
    if not uids:
        return []
    by_uid = {getattr(u, "uid", ""): u for u in (mission.units or [])
              if getattr(u, "uid", "")}
    positions: list[tuple[int, int]] = []
    for uid in uids:
        u = by_uid.get(uid)
        if u is None:
            continue
        positions.append((int(u.x), int(u.y)))
    if not positions:
        return []
    out: list[str] = []
    out.append(f"    {{")
    out.append(f"        // Einheiten der {label} '{group.name}' zuweisen")
    out.append(f"        for (Unit _u : Game::unitsOf({int(group.player)})) {{")
    out.append(f"            Location _loc = _u.location();")
    conds = " || ".join(
        f"(_loc.x == {x + 1} && _loc.y == {y + 1})" for (x, y) in positions
    )
    out.append(f"            if ({conds}) {var}.takeUnit(_u);")
    out.append(f"        }}")
    out.append(f"    }}")
    return out


def _build_codegen_context(mission: Mission) -> dict:
    """Collect names -> C++ variable / helper symbols so emitters can cross-reference."""
    ctx: dict = {
        "trigger_helpers": {},        # trigger name -> first-match helper (for createTrigger)
        "trigger_helpers_list": [],   # per-index unique helper names
        "group_vars": {},             # group name   -> "<g_n>"
    }
    for i, t in enumerate(mission.triggers or []):
        helper = f"_trigger_{i}_{_ident(t.name)}"
        ctx["trigger_helpers_list"].append(helper)
        if t.name not in ctx["trigger_helpers"]:
            ctx["trigger_helpers"][t.name] = helper
    idx = 0
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

    # Difficulty constants (always emitted so ExprEdit expressions compile)
    diff = getattr(mission, "difficulty", None)
    hard   = diff.hard   if diff else 13
    normal = diff.normal if diff else 10
    easy   = diff.easy   if diff else 5
    add(f"static const int kDiff[] = {{{easy}, {normal}, {hard}}};")
    add("static const int diff = kDiff[(int)Player(0).difficulty()];")
    add("")
    add("static int randBetween(int minValue, int maxValue) {")
    add("    if (maxValue < minValue) std::swap(minValue, maxValue);")
    add("    return minValue + Game::getRand(maxValue - minValue + 1);")
    add("}")
    add("")

    # Custom mission variables declared at file scope
    variables = getattr(mission, "variables", None) or []
    for v in variables:
        init = int(v.initial_value) if v.initial_value is not None else 0
        if v.var_type == "bool":
            add(f"static bool {v.name} = {'true' if init else 'false'};")
        else:
            add(f"static int {v.name} = {init};")
    if variables:
        add("")

    # Forward declarations for trigger helpers (so a `createTrigger` action
    # earlier in the file can invoke a trigger declared further down).
    for helper in ctx["trigger_helpers_list"]:
        add(f"static void {helper}();")
    if mission.triggers:
        add("")

    # Group variables live at file scope so any trigger callback can see them.
    # Real value is assigned in initProc -- this is just a forward declaration.
    for g in (getattr(mission, "building_groups", None) or []) \
           + (getattr(mission, "reinforce_groups", None) or []):
        add(f"static Group {ctx['group_vars'][g.name]};")
    if mission.building_groups or mission.reinforce_groups:
        add("")

    # --- Exports ---
    num_players = max(1, len(mission.players or []) or 1)
    add(f'extern "C" __declspec(dllexport) char LevelDesc[]    = {_cpp_string(mission.name)};')
    add(f'extern "C" __declspec(dllexport) char MapName[]      = {_cpp_string(mission.map)};')
    tech_tree = (getattr(mission, "tech_tree", None) or "MULTITEK.TXT").strip() or "MULTITEK.TXT"
    add(f'extern "C" __declspec(dllexport) char TechtreeName[] = {_cpp_string(tech_tree)};')
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
    enabled = [
        (i, t) for i, t in enumerate(mission.triggers or [])
        if getattr(t, "enabled_at_start", True)
    ]
    if enabled:
        add("")
        add("    // --- Custom triggers (enabled at start) ---")
        for i, t in enabled:
            add(f"    {ctx['trigger_helpers_list'][i]}();")

    add("")
    add('    op2::ignore(Game::forceMoraleGood());')
    add('    log::line("InitProc: done");')
    add("}")
    add("")

    # Custom-trigger helper functions live at file scope so they (a) can be
    # called from a createTrigger action via forward decl and (b) capture
    # the file-scope group vars via the global lookup.
    for i, t in enumerate(mission.triggers or []):
        for line in _emit_trigger_helper(t, ctx["trigger_helpers_list"][i], ctx):
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
