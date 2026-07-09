"""Codegen: Mission-Modell -> mission.cpp (TitanAPI C++23).

Reads a Mission object (mission_model.py) and produces the C++23 source
code that the TitanAPI library compiles into a runnable mission DLL.
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


# Expands a straight line segment (recordTube/recordWall) into its individual
# tiles -- same algorithm as the map-preview drawing in
# editor/app/window_map_pick.py's _line_tiles(), kept in sync so the tiles the
# UI shows as "planned" are exactly the tiles the generated C++ creates.
def _line_tiles(x1: int, y1: int, x2: int, y2: int) -> list[tuple[int, int]]:
    tiles = []
    if abs(x2 - x1) >= abs(y2 - y1):
        step = 1 if x2 >= x1 else -1
        for x in range(x1, x2 + step, step):
            tiles.append((x, y1))
        if y2 != y1:
            step_y = 1 if y2 >= y1 else -1
            for y in range(y1 + step_y, y2 + step_y, step_y):
                tiles.append((x2, y))
    else:
        step = 1 if y2 >= y1 else -1
        for y in range(y1, y2 + step, step):
            tiles.append((x1, y))
        if x2 != x1:
            step_x = 1 if x2 >= x1 else -1
            for x in range(x1 + step_x, x2 + step_x, step_x):
                tiles.append((x, y2))
    return tiles


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


# Building types in the editor (mapped from editor/app/game_data.py STRUCTURES,
# "map" prefix stripped). Anything else placed as a "unit" is treated as a
# vehicle by _emit_base_layout and the named-unit capture in generate_levelmain.
_BUILDING_TYPES = {
    "CommandCenter", "Tokamak", "MHDGenerator", "SolarPowerArray", "GeothermalPlant",
    "StructureFactory", "VehicleFactory", "ArachnidFactory", "ConsumerFactory",
    "CommonOreMine", "RareOreMine", "CommonOreSmelter", "RareOreSmelter",
    "CommonStorage", "RareStorage", "MagmaWell",
    "BasicLab", "StandardLab", "AdvancedLab", "Observatory",
    "Residence", "ReinforcedResidence", "AdvancedResidence",
    "Nursery", "University", "MedicalCenter",
    "Agridome", "GORF",
    "RecreationFacility", "Forum", "TradeCenter", "DIRT",
    "GuardPost", "LightTower", "MeteorDefense", "Garage", "RobotCommand",
    "Spaceport",
}


def _emit_condition(cond: Condition, is_victory: bool, mission: Mission | None = None,
                    ctx: dict | None = None) -> list[str]:
    """Emit one win/lose condition (called from initProc())."""
    lines: list[str] = []
    obj = _cpp_string(cond.objective or ("Mission objective" if is_victory else ""))
    cmp_ = _COMPARE.get(cond.compare, "Compare::GreaterEqual")

    if cond.kind == "time":
        # time victory: win at mark M. There is no direct "win at mark X" helper,
        # but onMark(M, <cb>) does the same thing. The callback is a NAMED
        # function registered via trackCb so its slot survives savegame loads.
        entry = (ctx or {}).get("time_cb_by_id", {}).get(id(cond))
        if entry:
            name, idx = entry
            lines.append(f"    onMark({int(cond.marks)}, trackCb(&{name}, {idx}));")
        else:
            cb = f"[] {{ op2::win({obj}); }}" if is_victory else "[] { op2::lose(); }"
            lines.append(f"    onMark({int(cond.marks)}, {cb});")
    elif cond.kind == "noCC":
        lines.append(f"    loseIfNoCommandCenter({int(cond.player)});")
    elif cond.kind == "lastStanding":
        # Win when every enemy (AI) colony is wiped out. OP2 ANDs victory
        # conditions, so one winWhenColonyDestroyed per enemy player means
        # ALL of them must fall before the win fires.
        enemies = [i for i, p in enumerate((mission.players if mission else []) or [])
                   if not p.is_human]
        if enemies:
            lo_obj = _cpp_string(cond.objective or "Eliminate all enemy colonies")
            for e in enemies:
                lines.append(f"    victoryWhen(onBuildingCount({e}, Compare::Lower, 1), {lo_obj});")
        else:
            lines.append(f"    // last-one-standing: no AI players in this mission -> nothing to destroy")
    elif cond.kind == "starship":
        # Starship evacuation: fires once an Evacuation Module has been
        # launched (same CreateCountTrigger idiom as OP2Helper's
        # CreateStarshipVictoryCondition).
        ss_obj = _cpp_string(
            cond.objective
            or "Evacuate 200 colonists and 10000 units of Common and Rare Metals to the starship.")
        lines.append(
            f"    victoryWhen(onUnitCount({int(cond.player)}, MapID::EvacuationModule, "
            f"MapID::Any, Compare::GreaterEqual, 1), {ss_obj});")
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

# ---------------------------------------------------------------------------
# forEach loop nesting: each level gets its own C++ variable name so a nested
# loop's "unit" doesn't shadow an outer loop's -- depth 1 (outermost) is
# named "unit", depth 2 "unit2", depth 3 "unit3", etc.
# ---------------------------------------------------------------------------

def _loop_var(depth: int) -> str:
    return "unit" if depth <= 1 else f"unit{depth}"


def _resolve_loop_ref(ref: str, depth: int) -> str | None:
    """Resolve a "<loop>"/"<loop:outer>" sentinel to a concrete loop variable
    name at the given nesting depth. Returns None if `ref` isn't a loop
    sentinel (caller should fall back to a named-unit lookup)."""
    if ref == "<loop>":
        return _loop_var(depth)
    if ref == "<loop:outer>":
        return _loop_var(depth - 1) if depth >= 2 else None
    return None


def _emit_action_condition_expr(c: ActionCondition, depth: int = 0) -> str:
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
    # Bedingungen auf die Schleifen-Einheit einer forEach-Schleife. Bei
    # verschachtelten Schleifen waehlt c.loop_level, welche Ebene gemeint ist.
    # Conditions on a forEach loop unit. For nested loops, c.loop_level picks
    # which level is meant.
    elif c.kind in ("loopUnitType", "loopUnitDamage", "loopUnitCargo", "loopUnitCommand"):
        lvl_depth = depth - 1 if getattr(c, "loop_level", "current") == "outer" else depth
        uv = _loop_var(lvl_depth) if lvl_depth >= 1 else "unit"
        if c.kind == "loopUnitType":
            expr = f"({uv}.type() == {mapid(c.building_type)})"
        elif c.kind == "loopUnitDamage":
            expr = f"({uv}.damage() {cmp_op} {_expr_or_int(c.value)})"
        elif c.kind == "loopUnitCargo":
            expr = f"({uv}.weapon() == {mapid(c.building_type)})"
        else:
            cmd_name = getattr(c, "command_type", "Move") or "Move"
            expr = f"({uv}.command() == int(abi::CommandType::{cmd_name}))"
    else:
        expr = "true /* TODO: unsupported ActionCondition kind */"

    if getattr(c, "negate", False):
        return f"!({expr})"
    return expr


def _emit_action_conditions_combined(action: TriggerAction, depth: int = 0) -> str | None:
    """Combine an action's `conditions` list via `condition_logic` (AND/OR)."""
    if not action.conditions:
        return None
    parts = [_emit_action_condition_expr(c, depth) for c in action.conditions]
    op = " && " if (action.condition_logic or "and").lower() == "and" else " || "
    if len(parts) == 1:
        return parts[0]
    return "(" + op.join(parts) + ")"


# ---------------------------------------------------------------------------
# TriggerActions: emit C++ statements (recursive for if/then/else).
# ---------------------------------------------------------------------------

def _emit_action_body(action: TriggerAction, indent: str, ctx: dict, depth: int = 0) -> list[str]:
    """Emit the raw statements for one non-`if` action (without the IF gate).

    For `if` we instead emit an `if (...) { ... } else { ... }` block via
    `_emit_action()` so each branch can recurse with its own gating.

    `depth` is the current forEach-loop nesting depth (0 = not inside any
    loop); it resolves "<loop>"/"<loop:outer>" unit references to the right
    per-level C++ variable name (see _loop_var/_resolve_loop_ref).
    """
    k = action.kind
    if k == "noop":
        return [f"{indent}// (empty action)"]

    if k == "message":
        return [f"{indent}Game::addMessage({_cpp_string(action.text)});"]

    if k == "createUnit":
        entries = list(getattr(action, "unit_list", None) or [])
        if not entries:
            entries = [{"unit_type": action.unit_type, "weapon_type": action.weapon_type,
                        "x": action.x, "y": action.y}]
        lines = []
        for e in entries:
            wt = e.get("weapon_type") or "mapNone"
            weapon = mapid(wt) if wt != "mapNone" else "MapID::None"
            lines.append(
                f"{indent}op2::ignore(Game::createUnit({mapid(e.get('unit_type', 'mapScout'))}, "
                f"{_xy(e.get('x', 0), e.get('y', 0))}, Game::player({int(action.player)}), {weapon}));"
            )
        return lines

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
        entries = list(getattr(action, "building_list", None) or [])
        if not entries:
            entries = [{"building_type": action.building_type, "weapon_type": action.weapon_type,
                        "x": action.x, "y": action.y}]
        lines = []
        for e in entries:
            wt = e.get("weapon_type") or "mapNone"
            cargo = mapid(wt) if wt != "mapNone" else "MapID::None"
            lines.append(
                f"{indent}{var}.recordBuilding({_xy(e.get('x', 0), e.get('y', 0))}, "
                f"{mapid(e.get('building_type', 'mapCommandCenter'))}, {cargo});"
            )
        return lines

    if k == "recordTube":
        entries = list(getattr(action, "tube_list", None) or [])
        if not entries:
            entries = [{"x": action.x, "y": action.y, "x2": action.x2, "y2": action.y2}]
        lines = []
        for e in entries:
            for tx, ty in _line_tiles(int(e.get("x", 0)), int(e.get("y", 0)),
                                       int(e.get("x2", 0)), int(e.get("y2", 0))):
                lines.append(f"{indent}Game::createTube({_xy(tx, ty)});")
        return lines

    if k == "recordWall":
        entries = list(getattr(action, "wall_list", None) or [])
        if not entries:
            entries = [{"wall_type": action.wall_type, "x": action.x, "y": action.y,
                        "x2": action.x2, "y2": action.y2}]
        lines = []
        for e in entries:
            wt = e.get("wall_type") or "mapWall"
            for tx, ty in _line_tiles(int(e.get("x", 0)), int(e.get("y", 0)),
                                       int(e.get("x2", 0)), int(e.get("y2", 0))):
                lines.append(f"{indent}Game::createWall({mapid(wt)}, {_xy(tx, ty)});")
        return lines

    if k == "setTargCount":
        # Tell a group "keep this many of (unit, weapon) on strength" -- one
        # call per entry in targ_counts (falls back to the single legacy
        # unit_type/weapon_type/target_count fields for older saves).
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            return [f"{indent}// TODO setTargCount: group '{action.group_name}' not declared"]
        entries = list(getattr(action, "targ_counts", None) or [])
        if not entries:
            entries = [{"unit_type": action.unit_type, "weapon_type": action.weapon_type,
                       "count": action.target_count}]
        lines = []
        for e in entries:
            wt = e.get("weapon_type") or "mapNone"
            weapon = mapid(wt) if wt != "mapNone" else "MapID::None"
            lines.append(
                f"{indent}{var}.setTargCount({mapid(e.get('unit_type', 'mapConVec'))}, {weapon}, "
                f"{_expr_or_int(e.get('count', 1))});"
            )
        # Optionale Verknuepfung: die im Formular gewaehlte ReinforceGroup soll
        # tatsaechlich fuer DIESE Gruppe produzieren. Bisher wurden
        # source_group_name/reinforce_priority nur gespeichert, aber nie in
        # Code uebersetzt -- die Sollstaerke haette ohne recordVehReinforceGroup
        # nie einen Lieferanten gehabt.
        # Optional link: the ReinforceGroup chosen in the form should actually
        # produce for THIS group. Previously source_group_name/reinforce_priority
        # were only saved, never translated into code -- without
        # recordVehReinforceGroup the target count would never have a supplier.
        src_name = getattr(action, "source_group_name", "") or ""
        if src_name:
            src_var = ctx["group_vars"].get(src_name)
            if src_var:
                prio = int(getattr(action, "reinforce_priority", 1000) or 1000)
                lines.append(f"{indent}{src_var}.recordVehReinforceGroup({var}, {prio});")
            else:
                lines.append(f"{indent}// TODO setTargCount: ReinforceGroup '{src_name}' not declared")
        return lines

    if k == "assignToGroup":
        # Poll once for a building at (x,y); once found, hand it to the group.
        # TitanAPI's recurring trigger is onTick(N, cb, oneShot=false) -- we use
        # a 10-tick interval matching the legacy codegen pattern.
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            return [f"{indent}// TODO assignToGroup: target group '{action.group_name}' not declared"]
        return [
            f"{indent}onTick(10, trackLost([] {{",
            f"{indent}    Unit _u = GameMap::unitOnTile({_xy(action.x, action.y)});",
            f"{indent}    if (_u.id() && _u.type() == {mapid(action.building_type)}) {{",
            f"{indent}        {var}.takeUnit(_u);",
            f"{indent}    }}",
            f"{indent}}}), /*oneShot=*/false);",
        ]

    if k == "startMining":
        # Referenziert eine vordefinierte MiningGroup (group_name -> group_vars).
        # Der Abladebereich kommt aus der MiningGroupSpec (idle_x/y/width/height);
        # die anfaengliche Truck-Roster (unit_ids) wird bereits einmalig in
        # initProc zugewiesen (_emit_groups).
        # References a predefined MiningGroup (group_name -> group_vars). The
        # unload area comes from the MiningGroupSpec (idle_x/y/width/height);
        # the initial truck roster (unit_ids) is already assigned once in
        # initProc (_emit_groups).
        var = ctx["group_vars"].get(action.group_name, None)
        spec = ctx.get("mining_group_specs", {}).get(action.group_name)
        if not var or spec is None:
            return [f"{indent}// TODO startMining: MiningGroup '{action.group_name}' not declared"]
        mine_ref = getattr(action, "mine_ref", "") or ""
        smelter_ref = getattr(action, "smelter_ref", "") or ""
        if mine_ref in ("<loop>", "<loop:outer>") or smelter_ref in ("<loop>", "<loop:outer>"):
            # Schleifenreferenz: nur HIER, an dieser Stelle, gueltig -- die
            # Schleifenvariable existiert nur innerhalb dieser Iteration, kann
            # also nicht in den missionsweiten Reparatur-Callback verschoben
            # werden (der laeuft ausserhalb jeder Schleife). Bleibt deshalb
            # ein einmaliger Inline-Block, wie zuvor -- kein Self-Heal fuer
            # diesen Fall (eine "aktuelle Schleifeneinheit" hat ohnehin keine
            # stabile Identitaet, die man spaeter reparieren koennte).
            # Loop reference: only valid HERE, at this spot -- the loop
            # variable only exists within this iteration, so it can't be
            # moved into the mission-wide repair callback (which runs outside
            # any loop). Stays a one-shot inline block like before -- no
            # self-heal for this case (a "current loop unit" has no stable
            # identity to repair later anyway).
            mine_expr = (_resolve_loop_ref(mine_ref, depth) or ctx.get("unit_vars", {}).get(mine_ref)
                         if mine_ref else None) or f"GameMap::unitOnTile({_xy(action.x, action.y)})"
            smelter_expr = (_resolve_loop_ref(smelter_ref, depth) or ctx.get("unit_vars", {}).get(smelter_ref)
                            if smelter_ref else None) or f"GameMap::unitOnTile({_xy(action.x2, action.y2)})"
            if mine_ref and not (_resolve_loop_ref(mine_ref, depth) or ctx.get("unit_vars", {}).get(mine_ref)):
                return [f"{indent}// TODO startMining: mine reference '{mine_ref}' not declared"]
            if smelter_ref and not (_resolve_loop_ref(smelter_ref, depth) or ctx.get("unit_vars", {}).get(smelter_ref)):
                return [f"{indent}// TODO startMining: smelter reference '{smelter_ref}' not declared"]
            n = _expr_or_int(action.target_count)
            body = _mining_link_lines(var, spec, mine_expr, smelter_expr, n)
            return [f"{indent}{{"] + [f"{indent}    {line}" for line in body] + [f"{indent}}}"]
        # Positions- oder benannte Referenz: global gueltig. Die eigentliche
        # Verknuepfung (inkl. Wiederholung nach Zerstoerung+Wiederaufbau)
        # passiert zentral im wiederkehrenden Reparatur-Callback
        # (_emit_group_repair) -- diese Aktion setzt hier nur das Flag, das
        # dort geprueft wird.
        # Position or named-unit reference: globally valid. The actual
        # linking (including re-linking after destruction+rebuild) happens
        # centrally in the recurring repair callback (_emit_group_repair) --
        # this action only sets the flag checked there.
        armed_var = ctx.get("mining_action_vars", {}).get(id(action))
        if not armed_var:
            return [f"{indent}// TODO startMining: armed flag not declared"]
        return [f"{indent}{armed_var} = true;"]

    if k == "sendAttackWave":
        # High-level attack wave. Composition comes from wave_units
        # ([{unit_type, weapon_type, count}, ...]; falls back to the single
        # unit_type/target_count pair from older saves). Two modes:
        #   spawn     -- create the units instantly in the staging rect
        #   reinforce -- a ReinforceGroup produces them (setTargCount +
        #                recordVehReinforceGroup); optional auto-attack once full
        # Staging rect: (x,y)-(x2,y2). Attack rect: (attack_x,attack_y)-(attack_x2,attack_y2).
        p = int(action.player)
        waves = list(getattr(action, "wave_units", None) or [])
        if not waves:
            waves = [{"unit_type": action.unit_type or "mapLynx",
                      "weapon_type": action.weapon_type or "mapLaser",
                      "count": action.target_count}]
        mode = getattr(action, "spawn_mode", "spawn") or "spawn"
        auto_attack = bool(getattr(action, "now", False))
        stl, sbr = _xy(action.x, action.y), _xy(action.x2, action.y2)
        atl = _xy(getattr(action, "attack_x", 0), getattr(action, "attack_y", 0))
        abr = _xy(getattr(action, "attack_x2", 0), getattr(action, "attack_y2", 0))
        # Idle-Rect = Bau-/Spawnort; leer (alles 0) -> Sammelbereich verwenden.
        # Idle rect = build/spawn spot; empty (all zero) -> fall back to staging.
        ix, iy = int(getattr(action, "idle_x", 0)), int(getattr(action, "idle_y", 0))
        ix2, iy2 = int(getattr(action, "idle_x2", 0)), int(getattr(action, "idle_y2", 0))
        if not any((ix, iy, ix2, iy2)):
            ix, iy, ix2, iy2 = int(action.x), int(action.y), int(action.x2), int(action.y2)
        itl, ibr = _xy(ix, iy), _xy(ix2, iy2)
        iw = max(1, abs(ix2 - ix) + 1)   # Idle-Bereich-Breite / idle area width
        has_staging = any((int(action.x), int(action.y), int(action.x2), int(action.y2))) \
            and (int(action.x), int(action.y), int(action.x2), int(action.y2)) != (ix, iy, ix2, iy2)

        # Angriffswellen referenzieren zwingend eine VORHER definierte FightGroup
        # (Gruppen-Panel) -- keine spontane Gruppenerzeugung mehr. Die Gruppe
        # selbst wird bereits einmalig in initProc angelegt (_emit_groups).
        # Attack waves must reference a PRE-DEFINED FightGroup (Groups panel)
        # -- no more ad-hoc group creation. The group itself is already
        # created once in initProc (_emit_groups).
        wave_name = getattr(action, "group_var_name", "") or ""
        fg = ctx["group_vars"].get(wave_name)
        if not fg:
            return [f"{indent}// TODO sendAttackWave: FightGroup '{wave_name}' not declared"]

        lines = [f"{indent}{{", f"{indent}    Player _p({p});"]
        lines.append(f"{indent}    {fg}.setIdleRect({itl}, {ibr});")

        def _attack_lines(pre):
            return [
                f"{pre}{fg}.setAttackType(MapID::Any);",
                f"{pre}{fg}.clearGuardedRects();",
                f"{pre}{fg}.addGuardedRect({atl}, {abr});",
                f"{pre}{fg}.doGuardRect();",
            ]

        def _staging_lines(pre):
            return [
                f"{pre}{fg}.clearGuardedRects();",
                f"{pre}{fg}.addGuardedRect({stl}, {sbr});",
                f"{pre}{fg}.doGuardRect();",
            ]

        if mode == "spawn":
            i = 0
            for w in waves:
                wt = w.get("weapon_type") or "mapLaser"
                weapon = mapid(wt) if wt != "mapNone" else "MapID::None"
                n = int(w.get("count", 1) or 1)
                lines.append(f"{indent}    for (int _i = {i}; _i < {i + n}; ++_i) {{")
                lines.append(
                    f"{indent}        auto _u = Game::createUnit({mapid(w.get('unit_type', 'mapLynx'))}, "
                    f"{{ {ix + 1} + (_i % {iw}), {iy + 1} + (_i / {iw}) }}, _p, {weapon});")
                lines.append(f"{indent}        if (_u) {fg}.takeUnit(*_u);")
                lines.append(f"{indent}    }}")
                i += n
            if auto_attack:
                lines.extend(f"{indent}    {l}" for l in _attack_lines(""))
            elif has_staging:
                # Ohne Auto-Angriff: im Sammelbereich sammeln und warten
                lines.extend(f"{indent}    {l}" for l in _staging_lines(""))
        else:
            # reinforce: Sollstaerke setzen, Nachschub anfordern
            total = 0
            for w in waves:
                wt = w.get("weapon_type") or "mapLaser"
                weapon = mapid(wt) if wt != "mapNone" else "MapID::None"
                n = int(w.get("count", 1) or 1)
                total += n
                lines.append(
                    f"{indent}    {fg}.setTargCount({mapid(w.get('unit_type', 'mapLynx'))}, {weapon}, {n});")
            src_var = ctx["group_vars"].get(getattr(action, "source_group_name", "") or "", None)
            if src_var:
                prio = int(getattr(action, "reinforce_priority", 1000) or 1000)
                lines.append(f"{indent}    {src_var}.recordVehReinforceGroup({fg}, {prio});")
            else:
                lines.append(f"{indent}    // TODO sendAttackWave: ReinforceGroup "
                             f"'{getattr(action, 'source_group_name', '')}' not declared")
            if auto_attack or has_staging:
                # Wenn voll: Angriff bzw. Sammelbereich (einmalig; static-Flag).
                # trackLost: dieser Laufzeit-Poller ist nach einem Spielstand-
                # Load nicht wiederherstellbar (Lambda mit Zustand). `fg` ist
                # eine file-scope Variable, braucht daher kein Capture.
                lines.append(f"{indent}    onTick(50, trackLost([]() {{")
                lines.append(f"{indent}        static bool _launched = false;")
                lines.append(f"{indent}        if (_launched || {fg}.totalUnitCount() < {total}) return;")
                lines.append(f"{indent}        _launched = true;")
                body = _attack_lines("") if auto_attack else _staging_lines("")
                for l in body:
                    lines.append(f"{indent}        {l}")
                lines.append(f"{indent}    }}), /*oneShot=*/false);")
        lines.append(f"{indent}}}")
        return lines

    if k == "fightGroupCmd":
        # Gruppen-Befehl: FightGroup, BuildingGroup oder ReinforceGroup (alle
        # vordefiniert im Gruppen-Panel). Die Befehlsliste ist im Editor nach
        # Gruppentyp gefiltert.
        # Group command: FightGroup, BuildingGroup or ReinforceGroup (all
        # predefined in the Groups panel). The editor filters the command
        # list by group type.
        gname = getattr(action, "group_name", "") or ""
        gvar = ctx.get("group_vars", {}).get(gname)
        if not gvar:
            return [f"{indent}// TODO groupCmd: group '{gname}' not declared"]
        cmd = getattr(action, "fg_command", "attackArea") or "attackArea"
        tl, br = _xy(action.x, action.y), _xy(action.x2, action.y2)
        # FightGroup-Befehle
        if cmd == "attackArea":
            return [
                f"{indent}{gvar}.setAttackType(MapID::Any);",
                f"{indent}{gvar}.clearGuardedRects();",
                f"{indent}{gvar}.addGuardedRect({tl}, {br});",
                f"{indent}{gvar}.doGuardRect();",
            ]
        if cmd == "attackEnemy":
            return [
                f"{indent}{gvar}.setAttackType(MapID::Any);",
                f"{indent}{gvar}.doAttackEnemy();",
            ]
        if cmd == "guardArea":
            return [
                f"{indent}{gvar}.clearGuardedRects();",
                f"{indent}{gvar}.setIdleRect({tl}, {br});",
                f"{indent}{gvar}.addGuardedRect({tl}, {br});",
                f"{indent}{gvar}.doGuardRect();",
            ]
        if cmd == "patrol":
            pts = _patrol_locations(action)
            return [
                f"{indent}{gvar}.setPatrolMode({{ {', '.join(pts)} }});",
                f"{indent}{gvar}.doPatrolOnly();",
            ]
        if cmd == "exitMap":
            return [f"{indent}{gvar}.doExitMap();"]
        if cmd == "combineFireOn":
            return [f"{indent}{gvar}.setCombineFire();"]
        if cmd == "combineFireOff":
            return [f"{indent}{gvar}.clearCombineFire();"]
        # BuildingGroup-/ReinforceGroup-Befehle
        if cmd == "setBuildRect":
            return [f"{indent}{gvar}.setBuildRect({tl}, {br});"]
        if cmd in ("reinforceGroup", "unReinforceGroup"):
            tname = getattr(action, "target", "") or ""
            tvar = ctx.get("group_vars", {}).get(tname)
            if not tvar:
                return [f"{indent}// TODO groupCmd: target group '{tname}' not declared"]
            if cmd == "reinforceGroup":
                prio = int(getattr(action, "reinforce_priority", 1000) or 1000)
                return [f"{indent}{gvar}.recordVehReinforceGroup({tvar}, {prio});"]
            return [f"{indent}{gvar}.unRecordVehGroup({tvar});"]
        # Bearbeiten der Gruppenzusammensetzung / editing group composition
        if cmd == "setIdleRect":
            return [f"{indent}{gvar}.setIdleRect({tl}, {br});"]
        if cmd in ("addUnit", "removeUnit"):
            tname = getattr(action, "target", "") or ""
            tvar = _resolve_loop_ref(tname, depth) or ctx.get("unit_vars", {}).get(tname)
            if not tvar:
                return [f"{indent}// TODO groupCmd: unit '{tname}' not declared"]
            method = "takeUnit" if cmd == "addUnit" else "removeUnit"
            return [f"{indent}{gvar}.{method}({tvar});"]
        # Befehle fuer alle Gruppentypen
        if cmd == "lightsOn":
            return [f"{indent}{gvar}.setLights(true);"]
        if cmd == "lightsOff":
            return [f"{indent}{gvar}.setLights(false);"]
        if cmd == "clearTargCount":
            return [f"{indent}{gvar}.clearTargCount();"]
        return [f"{indent}// TODO groupCmd: unknown command '{cmd}'"]

    if k == "unitCmd":
        # Einheiten-Befehl an eine benannte platzierte Einheit ODER die
        # Schleifen-Einheit einer (ggf. verschachtelten) forEach-Schleife
        # (unit_ref == "<loop>" bzw. "<loop:outer>").
        # Unit command for a named placed unit OR a forEach loop unit
        # (possibly nested; "<loop>"/"<loop:outer>").
        uname = getattr(action, "unit_ref", "") or ""
        uvar = _resolve_loop_ref(uname, depth) or ctx.get("unit_vars", {}).get(uname)
        if not uvar:
            return [f"{indent}// TODO unitCmd: unit '{uname}' not declared"]
        cmd = getattr(action, "fg_command", "move") or "move"
        pos = _xy(action.x, action.y)
        pos2 = _xy(action.x2, action.y2)
        simple = {
            "stop": "stop()", "selfDestruct": "selfDestruct()",
            "remove": "remove()", "idle": "idle()", "unidle": "unidle()",
            "lightsOn": "setLights(true)", "lightsOff": "setLights(false)",
        }
        if cmd in simple:
            return [f"{indent}op2::ignore({uvar}.{simple[cmd]});"]
        if cmd == "move":
            return [f"{indent}op2::ignore({uvar}.move({pos}));"]
        if cmd == "attackGround":
            return [f"{indent}op2::ignore({uvar}.attack(Location{pos}));"]
        if cmd == "patrol":
            pts = _patrol_locations(action)
            if len(pts) <= 2:
                return [f"{indent}op2::ignore({uvar}.patrol({pos}, {pos2}));"]
            return [
                f"{indent}{{",
                f"{indent}    Location _wps[] = {{ {', '.join(pts)} }};",
                f"{indent}    op2::ignore({uvar}.patrol(_wps));",
                f"{indent}}}",
            ]
        if cmd == "transfer":
            return [f"{indent}op2::ignore({uvar}.transfer({int(action.player)}));"]
        if cmd == "repair":
            tname = getattr(action, "target", "") or ""
            tvar = _resolve_loop_ref(tname, depth) or ctx.get("unit_vars", {}).get(tname)
            if not tvar:
                return [f"{indent}// TODO unitCmd repair: target unit '{tname}' not declared"]
            return [
                f"{indent}{{",
                f'{indent}    log::linef("repair target id=%d owner=%d", {tvar}.id(), {tvar}.ownerId());',
                f"{indent}    auto _res = {uvar}.repair({tvar});",
                f'{indent}    log::linef("repair {uvar} -> {tvar}: %s", _res ? "ok" : "FAILED");',
                f"{indent}}}",
            ]
        return [f"{indent}// TODO unitCmd: unknown command '{cmd}'"]

    if k == "defendArea":
        # High-level: put the player's armed vehicles inside the rect into a
        # FightGroup that guards that rect.
        p = int(action.player)
        tl, br = _xy(action.x, action.y), _xy(action.x2, action.y2)
        return [
            f"{indent}{{",
            f"{indent}    Player _p({p});",
            f"{indent}    Group _fg = createFightGroup(_p);",
            f"{indent}    _fg.setIdleRect({tl}, {br});",
            f"{indent}    _fg.addGuardedRect({tl}, {br});",
            f"{indent}    for (Unit _u : Game::unitsInRect({tl}, {br})) {{",
            f"{indent}        if (_u.ownerId() == {p} && _u.isVehicle() "
            f"&& Game::isWeaponPlatform(_u.type())) _fg.takeUnit(_u);",
            f"{indent}    }}",
            f"{indent}    _fg.doGuardRect();",
            f"{indent}}}",
        ]

    if k == "repairBuildings":
        # High-level: collect the player's Repair Vehicles (and ConVecs as
        # fallback repairers) into a group guarding the rect -- guarding
        # repair units auto-repair damaged structures in their area.
        p = int(action.player)
        tl, br = _xy(action.x, action.y), _xy(action.x2, action.y2)
        return [
            f"{indent}{{",
            f"{indent}    Player _p({p});",
            f"{indent}    Group _fg = createFightGroup(_p);",
            f"{indent}    _fg.setIdleRect({tl}, {br});",
            f"{indent}    _fg.addGuardedRect({tl}, {br});",
            f"{indent}    for (Unit _u : Game::unitsOf({p})) {{",
            f"{indent}        if (_u.type() == MapID::RepairVehicle "
            f"|| _u.type() == MapID::ConVec) _fg.takeUnit(_u);",
            f"{indent}    }}",
            f"{indent}    _fg.doGuardRect();",
            f"{indent}}}",
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


def _patrol_locations(action) -> list[str]:
    """Wegpunkte einer Patrouille als Location-Literale (max. 8).

    Patrol waypoints as Location literals (max 8). Falls back to the two
    x,y / x2,y2 points when the patrol_points list is empty."""
    pts = list(getattr(action, "patrol_points", None) or [])[:8]
    if pts:
        return [_xy(int(p[0]), int(p[1])) for p in pts]
    return [_xy(action.x, action.y), _xy(action.x2, action.y2)]


# forEach-Enumeratoren: Quelle -> (Range-Ausdruck, zusaetzliche Filter-Templates)
# forEach enumerators: source -> (range expression, extra filter templates)
def _for_each_range(action) -> tuple[str, list[str]]:
    src = getattr(action, "enum_source", "rect") or "rect"
    p = int(getattr(action, "player", 0))
    tl, br = _xy(action.x, action.y), _xy(action.x2, action.y2)
    if src == "all":
        return "Game::units()", []
    if src == "player":
        return f"Game::unitsOf({p})", []
    if src == "playerVehicles":
        return f"Game::unitsOf({p})", ["unit.isVehicle()"]
    if src == "playerBuildings":
        return f"Game::unitsOf({p})", ["unit.isBuilding()"]
    if src == "type":
        ut = getattr(action, "unit_type", "") or "mapAny"
        return f"Game::unitsOfType({mapid(ut)})", []
    # default: rect
    return f"Game::unitsInRect({tl}, {br})", []


def _emit_action(action: TriggerAction, indent: str, ctx: dict, depth: int = 0) -> list[str]:
    """Emit one action; recurses for kind == 'if' (then/else blocks).

    Ein Logik-Block (kind == 'if') kann eine Schleife tragen (loop_mode):
      count   -> for (int i = 0; i < N; ++i) { if (cond) {...} }
      forEach -> for (Unit unit : Game::unitsInRect(...)) { <filter> if (cond) {...} }
    Die Laufvariablen `i` bzw. `unit` sind in Ausdruecken nutzbar.

    `depth` is the current forEach-loop nesting depth (0 outside any loop).
    Each forEach level gets its own variable name (_loop_var) so a nested
    loop doesn't shadow an outer one -- "unit" (depth 1), "unit2" (depth 2), ...
    """
    if action.kind == "if":
        out: list[str] = []
        loop_mode = getattr(action, "loop_mode", "none") or "none"
        inner = indent
        inner_depth = depth
        if loop_mode == "count":
            n = _expr_or_int(getattr(action, "loop_count", 1))
            out.append(f"{indent}for (int i = 0; i < {n}; ++i) {{")
            inner = indent + "    "
        elif loop_mode == "forEach":
            inner_depth = depth + 1
            var = _loop_var(inner_depth)
            range_expr, filters = _for_each_range(action)
            src = getattr(action, "enum_source", "rect") or "rect"
            out.append(f"{indent}for (Unit {var} : {range_expr}) {{")
            inner = indent + "    "
            filters = [f.replace("unit.", f"{var}.") for f in filters]
            ut = getattr(action, "unit_type", "") or ""
            if src != "type" and ut and ut not in ("mapAny", "mapNone"):
                filters.append(f"{var}.type() == {mapid(ut)}")
            if src in ("all", "type", "rect") and int(getattr(action, "player", 0)) >= 0:
                filters.append(f"{var}.ownerId() == {int(action.player)}")
            if src != "rect" and any((int(action.x), int(action.y),
                                      int(action.x2), int(action.y2))):
                tl, br = _xy(action.x, action.y), _xy(action.x2, action.y2)
                out.append(f"{inner}const Location _l{inner_depth} = {var}.location();")
                filters.append(
                    f"_l{inner_depth}.x >= {int(action.x) + 1} && _l{inner_depth}.x <= {int(action.x2) + 1} "
                    f"&& _l{inner_depth}.y >= {int(action.y) + 1} && _l{inner_depth}.y <= {int(action.y2) + 1}")
            if filters:
                out.append(f"{inner}if (!({' && '.join(filters)})) continue;")
        cond = _emit_action_conditions_combined(action, inner_depth) or "true"
        out.append(f"{inner}if ({cond}) {{")
        for child in (action.then_actions or []):
            out.extend(_emit_action(child, inner + "    ", ctx, inner_depth))
        if action.else_actions:
            out.append(f"{inner}}} else {{")
            for child in action.else_actions:
                out.extend(_emit_action(child, inner + "    ", ctx, inner_depth))
        out.append(f"{inner}}}")
        if loop_mode in ("count", "forEach"):
            out.append(f"{indent}}}")
        return out

    # Non-`if`: wrap the body in an IF gate if the action has its own conditions.
    cond = _emit_action_conditions_combined(action, depth)
    if cond is None:
        return _emit_action_body(action, indent, ctx, depth)
    body = _emit_action_body(action, indent + "    ", ctx, depth)
    return [f"{indent}if ({cond}) {{", *body, f"{indent}}}"]


def _emit_action_list(actions: list[TriggerAction], indent: str, ctx: dict, depth: int = 0) -> list[str]:
    out: list[str] = []
    for a in (actions or []):
        out.extend(_emit_action(a, indent, ctx, depth))
    return out


# ---------------------------------------------------------------------------
# Custom Triggers: emit a small helper that creates the trigger + callback.
# ---------------------------------------------------------------------------

def _emit_trigger_helper(t: TriggerDef, helper: str, ctx: dict) -> list[str]:
    """Emit the trigger's callback as a NAMED function plus a slim helper.

    `static void <helper>_cb() { ...actions... }`   -- the callback body
    `static void <helper>() { onXXX(..., &<helper>_cb, ...); }`

    The helper is invoked from initProc for triggers enabled at start, and
    from `createTrigger` actions at runtime for triggers created on demand.

    The callback is a named function (not an inline lambda) so it can be
    re-registered after a savegame load: OP2 restores its triggers from the
    save WITHOUT calling InitProc, and the TitanAPI callback registry must
    be repopulated in the same order (see registerSavegameCallbacks).
    """
    one_shot = "true" if t.one_shot else "false"
    cmp_ = _COMPARE.get(t.compare, "Compare::GreaterEqual")
    cb_fn = f"{helper}_cb"
    ctx.setdefault("trigger_cb_names", {})[helper] = cb_fn

    lines: list[str] = []
    lines.append(f"// Trigger '{t.name}' (condition={t.condition})")

    # --- Callback als benannte Funktion / callback as a named function ---
    if t.condition in ("time", "buildingCount", "vehicleCount", "research",
                       "resource", "operational"):
        lines.append(f"static void {cb_fn}() {{")
        lines.extend(_emit_action_list(t.actions, "    ", ctx))
        lines.append(f"}}")
    elif t.condition == "point":
        # TitanAPI has no native point trigger in this header pass; approximate
        # with a polling onTick(10, ..., oneShot=false) checking the tile.
        lines.append(f"static void {cb_fn}() {{")
        lines.append(f"    Unit _u = GameMap::unitOnTile({_xy(t.x, t.y)});")
        lines.append(f"    if (_u.id() && _u.ownerId() == {int(t.player)}) {{")
        for line in _emit_action_list(t.actions, "        ", ctx):
            lines.append(line)
        lines.append(f"    }}")
        lines.append(f"}}")
    elif t.condition == "rect":
        lines.append(f"static void {cb_fn}() {{")
        lines.append(f"    Region _r{{ {_xy(t.x, t.y)}, "
                     f"{_xy(t.x + t.width, t.y + t.height)} }};")
        lines.append(f"    for (Unit _u : _r.units()) if (_u.ownerId() == {int(t.player)}) {{")
        for line in _emit_action_list(t.actions, "        ", ctx):
            lines.append(line)
        lines.append(f"        break;")
        lines.append(f"    }}")
        lines.append(f"}}")
    elif t.condition == "findUnit":
        # Pollt alle 10 Ticks, prueft jeden Eintrag der `unit_checks`-Liste
        # auf "einsatzbereit" (isLive && type match && enabled). Sobald
        # ALLE Eintraege gleichzeitig ready sind, feuern die Aktionen.
        checks = list(getattr(t, "unit_checks", None) or [])
        if not checks:
            lines.append(f"static void {cb_fn}() {{}}  // findUnit ohne Eintraege")
            lines.append(f"static void {helper}() {{}}")
            return lines
        # oneShot=false; wir disablen den Trigger nach erstem Match manuell.
        lines.append(f"static Trigger {helper}_self;")
        lines.append(f"static void {cb_fn}() {{")
        for i, c in enumerate(checks):
            lines.append(f"    Unit _u{i} = GameMap::unitOnTile({_xy(c.x, c.y)});")
            lines.append(f"    bool _ready{i} = _u{i}.isLive() && _u{i}.type() == "
                         f"{mapid(c.unit_type)} && _u{i}.enabled();")
        all_ready = " && ".join(f"_ready{i}" for i in range(len(checks)))
        lines.append(f"    if (!({all_ready})) return;")
        for line in _emit_action_list(t.actions, "    ", ctx):
            lines.append(line)
        if t.one_shot:
            lines.append(f"    {helper}_self.disable();")
        lines.append(f"}}")
    else:
        lines.append(f"static void {cb_fn}() {{}}  // TODO unsupported condition: {t.condition}")

    # --- Helper: erzeugt den Engine-Trigger / creates the engine trigger ---
    # trackCb registriert den Callback mit Buchfuehrung in g_save, damit der
    # Slot nach einem Spielstand-Load wiederhergestellt werden kann.
    idx = ctx.get("trigger_cb_idx", {}).get(helper)
    cb_arg = f"trackCb(&{cb_fn}, {idx})" if idx is not None else f"&{cb_fn}"
    lines.append(f"static void {helper}() {{")
    if t.condition == "time":
        lines.append(f"    onMark({_expr_or_int(t.marks)}, {cb_arg}, /*oneShot=*/{one_shot});")
    elif t.condition == "buildingCount":
        lines.append(f"    onBuildingCount({int(t.player)}, {cmp_}, {int(t.count)}, "
                     f"{cb_arg}, /*oneShot=*/{one_shot});")
    elif t.condition == "vehicleCount":
        lines.append(f"    onVehicleCount({int(t.player)}, {cmp_}, {int(t.count)}, "
                     f"{cb_arg}, /*oneShot=*/{one_shot});")
    elif t.condition == "research":
        lines.append(f"    onResearch({int(t.tech_id)}, {cb_arg}, {int(t.player)}, "
                     f"/*oneShot=*/{one_shot});")
    elif t.condition == "resource":
        res = _RESOURCE.get(t.resource, "Resource::CommonOre")
        lines.append(f"    onResource({res}, {cmp_}, {int(t.amount)}, {cb_arg}, "
                     f"{int(t.player)}, /*oneShot=*/{one_shot});")
    elif t.condition == "operational":
        lines.append(f"    onOperational({int(t.player)}, {mapid(t.building)}, {cmp_}, "
                     f"{int(t.count)}, {cb_arg}, /*oneShot=*/{one_shot});")
    elif t.condition in ("point", "rect"):
        lines.append(f"    onTick(10, {cb_arg}, /*oneShot=*/false);")
    elif t.condition == "findUnit":
        lines.append(f"    {helper}_self = onTick(10, {cb_arg}, /*oneShot=*/false);")
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
    fights = list(getattr(mission, "fight_groups", None) or [])
    minings = list(getattr(mission, "mining_groups", None) or [])
    if not (buildings or reinforces or fights or minings):
        return lines

    lines.append("")
    lines.append("    // --- Groups (building / reinforce / fight / mining) ---")

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
            else:
                # Name im Zielgruppe=Prioritaet-Textfeld passt zu keiner
                # bestehenden Gruppe -- vorher wurde das stillschweigend
                # uebersprungen (kein Fehler, kein Kommentar, kein Code).
                # Name in the "target=priority" text field doesn't match any
                # existing group -- this used to be silently skipped (no
                # error, no comment, no code).
                lines.append(f"    // TODO ReinforceGroup '{g.name}': target group "
                             f"'{t.group_name}' not found (check spelling/case)")

    for g in fights:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = createFightGroup(Game::player({int(g.player)}));")
        lines.append(f"    {var}.setIdleRect({_xy(g.idle_x, g.idle_y)}, "
                     f"{_xy(g.idle_x + g.idle_width, g.idle_y + g.idle_height)});")
        lines.extend(_emit_take_units(mission, g, var, label="FightGroup"))

    for g in minings:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = createMiningGroup(Game::player({int(g.player)}));")
        # Kein setIdleRect() hier: das ist laut TitanAPI [FightGroup]-spezifisch.
        # Der Abladebereich fuer eine MiningGroup kommt ausschliesslich ueber
        # setupMining()'s Bereichsargument -- das passiert je Aktion (siehe
        # "startMining" in _emit_action_body), nicht hier bei der Erzeugung.
        # No setIdleRect() here: per TitanAPI that's [FightGroup]-specific.
        # A MiningGroup's unload area only ever comes via setupMining()'s area
        # argument -- that happens per action (see "startMining" in
        # _emit_action_body), not here at group creation.
        lines.extend(_emit_take_units(mission, g, var, label="MiningGroup"))

    return lines


def _take_units_positions(mission: Mission, group) -> list[tuple[int, int]]:
    """Resolve a group's assigned unit_ids to their (visible) tile positions.

    Sucht die UnitSpec-Eintraege mit passender uid in mission.units und
    sammelt ihre (visible) Tile-Position.
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
    return positions


def _take_units_loop(group, var: str, positions: list[tuple[int, int]]) -> list[str]:
    """Der reine for-Loop, der eine lebende Einheit an `positions` per
    Group.takeUnit uebernimmt. Kein umschliessender Scope-Block noetig -- der
    for-Loop-Koerper ist bereits sein eigener Scope, mehrere solcher Bloecke
    lassen sich gefahrlos in EINER Funktion aneinanderreihen (z.B. im
    wiederkehrenden Reparatur-Callback, siehe _emit_group_repair).

    The bare for-loop that assigns any live unit at `positions` to `var` via
    takeUnit(). No enclosing scope-block needed -- the for-loop body is
    already its own scope, so several of these can safely be concatenated in
    ONE function (e.g. the recurring repair callback, see
    _emit_group_repair).
    """
    if not positions:
        return []
    conds = " || ".join(
        f"(_loc.x == {x + 1} && _loc.y == {y + 1})" for (x, y) in positions
    )
    return [
        f"for (Unit _u : Game::unitsOf({int(group.player)})) {{",
        f"    Location _loc = _u.location();",
        f"    if ({conds}) {var}.takeUnit(_u);",
        f"}}",
    ]


def _emit_take_units(mission: Mission, group, var: str, *, label: str) -> list[str]:
    """Emit a Game::unitsOf-Schleife die im Editor markierte Units der Group
    EINMALIG (InitProc) zuweist. Funktioniert sowohl fuer Vehicles (Factories
    sind Buildings) als auch fuer Combat-Units / ConVecs / Trucks.
    """
    positions = _take_units_positions(mission, group)
    if not positions:
        return []
    out: list[str] = [f"    {{", f"        // Einheiten der {label} '{group.name}' zuweisen"]
    out.extend(f"        {line}" for line in _take_units_loop(group, var, positions))
    out.append(f"    }}")
    return out


def _mining_link_lines(var: str, spec, mine_expr: str, smelter_expr: str, n) -> list[str]:
    """Existenz-Check + setupMining + setTargCount, gegeben bereits
    aufgeloeste Mine-/Smelter-Ausdruecke (kein Einrueck-Praefix).

    Existence check + setupMining + setTargCount, given already-resolved
    mine/smelter expressions (no indent prefix)."""
    itl = _xy(spec.idle_x, spec.idle_y)
    ibr = _xy(spec.idle_x + spec.idle_width, spec.idle_y + spec.idle_height)
    return [
        f"Unit _mine = {mine_expr};",
        f"Unit _smelter = {smelter_expr};",
        f"if (_mine.id() && _smelter.id()) {{",
        f"    {var}.setupMining(_mine, _smelter, {itl}, {ibr});",
        f"    {var}.setTargCount(MapID::CargoTruck, MapID::None, {n});",
        f"}}",
    ]


def _walk_actions(actions):
    """Alle Aktionen inkl. verschachtelter then/else-Zweige durchlaufen.

    Walk all actions including nested then/else branches."""
    for a in (actions or []):
        yield a
        yield from _walk_actions(getattr(a, "then_actions", None))
        yield from _walk_actions(getattr(a, "else_actions", None))


def _emit_group_repair(mission: Mission, ctx: dict) -> list[str]:
    """Ein einziger, missionsweiter wiederkehrender Check -- EIN Timer-Slot
    fuer die gesamte Mission (siehe trigger.hpp: nur 64 Slots insgesamt, nie
    freigegeben) --, der zerstoerte und von der Engine an derselben Stelle
    wieder errichtete Gebaeude automatisch erneut in ihre Gruppe aufnimmt
    bzw. eine MiningGroup neu verknuepft. Liefert eine leere Liste (kein
    Slot verbraucht), wenn es nichts zu pruefen gibt.

    A single, mission-wide recurring check -- ONE timer slot for the whole
    mission (see trigger.hpp: only 64 slots total, never released) -- that
    automatically re-takes destroyed-and-rebuilt (same position, by the
    engine) buildings into their group, or re-links a MiningGroup. Returns an
    empty list (no slot spent) if there is nothing to check.
    """
    body: list[str] = []

    for attr in ("building_groups", "reinforce_groups", "mining_groups"):
        for g in (getattr(mission, attr, None) or []):
            var = ctx["group_vars"][g.name]
            positions = _take_units_positions(mission, g)
            if positions:
                body.extend(_take_units_loop(g, var, positions))

    for action, armed_var in ctx.get("mining_actions", []):
        var = ctx["group_vars"].get(action.group_name, None)
        spec = ctx.get("mining_group_specs", {}).get(action.group_name)
        if not var or spec is None:
            continue
        mine_ref = getattr(action, "mine_ref", "") or ""
        smelter_ref = getattr(action, "smelter_ref", "") or ""
        mine_expr = ((ctx.get("unit_vars", {}).get(mine_ref) if mine_ref else None)
                     or f"GameMap::unitOnTile({_xy(action.x, action.y)})")
        smelter_expr = ((ctx.get("unit_vars", {}).get(smelter_ref) if smelter_ref else None)
                        or f"GameMap::unitOnTile({_xy(action.x2, action.y2)})")
        n = _expr_or_int(action.target_count)
        link = _mining_link_lines(var, spec, mine_expr, smelter_expr, n)
        body.append(f"if ({armed_var}) {{")
        body.extend(f"    {line}" for line in link)
        body.append(f"}}")

    if not body:
        return []
    out = [
        "",
        "    // --- Gruppen-Reparatur: zerstoerte, von der Engine an derselben",
        "    // Stelle wieder errichtete Gebaeude automatisch neu zuweisen/",
        "    // verknuepfen (ein einziger Timer fuer die ganze Mission). ---",
        "    onTick(kTicksPerMark, trackLost([] {",
    ]
    out.extend(f"        {line}" for line in body)
    out.append("    }), /*oneShot=*/false);")
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
    for g in (getattr(mission, "fight_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
    for g in (getattr(mission, "mining_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
    # Nachschlage-Dict Name -> MiningGroupSpec: _emit_action_body bekommt nur
    # ctx (nie mission) durchgereicht, braucht fuer "startMining" aber die
    # Idle-Rect-Geometrie der referenzierten Gruppe, nicht nur ihren
    # C++-Variablennamen (den liefert group_vars bereits).
    # Name -> MiningGroupSpec lookup: _emit_action_body only ever receives
    # ctx (never mission), but "startMining" needs the referenced group's
    # idle-rect geometry, not just its C++ variable name (group_vars already
    # provides that).
    ctx["mining_group_specs"] = {g.name: g for g in (getattr(mission, "mining_groups", None) or [])}
    # startMining-Aktionen setzen beim Ausfuehren nur noch ein "armed"-Flag
    # (statt Mine/Smelter direkt zu verknuepfen); die eigentliche Verknuepfung
    # -- inkl. Wiederholung nach Zerstoerung+Wiederaufbau -- passiert zentral
    # im wiederkehrenden Reparatur-Callback (_emit_group_repair). Jede Aktion
    # braucht dafuer ein eigenes, stabiles Flag -- id(action) als Schluessel,
    # da TriggerAction (dataclass) keinen stabilen Namen/Hash hat.
    # startMining actions now only set an "armed" flag when they run (instead
    # of directly linking mine/smelter); the actual linking -- including
    # re-linking after destruction+rebuild -- happens centrally in the
    # recurring repair callback (_emit_group_repair). Each action needs its
    # own stable flag for that -- id(action) as the key, since TriggerAction
    # (a dataclass) has no stable name/hash.
    # Schleifenreferenzen ("<loop>"/"<loop:outer>") bleiben ausgeschlossen --
    # die Schleifenvariable ist nur innerhalb ihrer Iteration gueltig, kann
    # also kein Flag im missionsweiten Reparatur-Callback bekommen (der laeuft
    # ausserhalb jeder Schleife). Muss mit der gleichen Pruefung in
    # _emit_action_body("startMining") synchron bleiben.
    # Loop references ("<loop>"/"<loop:outer>") stay excluded -- the loop
    # variable is only valid within its own iteration, so it can't get a flag
    # in the mission-wide repair callback (which runs outside any loop). Must
    # stay in sync with the same check in _emit_action_body("startMining").
    ctx["mining_action_vars"] = {}
    ctx["mining_actions"] = []
    mining_idx = 0
    for t in (mission.triggers or []):
        for a in _walk_actions(t.actions):
            if a.kind == "startMining":
                mine_ref = getattr(a, "mine_ref", "") or ""
                smelter_ref = getattr(a, "smelter_ref", "") or ""
                if mine_ref in ("<loop>", "<loop:outer>") or smelter_ref in ("<loop>", "<loop:outer>"):
                    continue
                armed_var = f"_mining_armed_{mining_idx}"
                ctx["mining_action_vars"][id(a)] = armed_var
                ctx["mining_actions"].append((a, armed_var))
                mining_idx += 1
    # FightGroups sind jetzt vordefinierte Gruppen (siehe fight_groups oben)
    # und ueber group_vars erreichbar wie jede andere Gruppe. wave_group_vars
    # bleibt als leeres Dict fuer Rueckwaertskompatibilitaet der .get()-Aufrufe
    # in sendAttackWave/fightGroupCmd erhalten.
    # FightGroups are now predefined groups (see fight_groups above) and
    # reachable via group_vars like any other group. wave_group_vars stays an
    # empty dict for backward compatibility of the .get() calls in
    # sendAttackWave/fightGroupCmd.
    ctx["wave_group_vars"] = {}
    # Benannte platzierte Einheiten: file-scope Unit-Variablen fuer unitCmd.
    # Named placed units: file-scope Unit variables for unitCmd actions.
    ctx["unit_vars"] = {}
    for u in (mission.units or []):
        name = (getattr(u, "unit_name", "") or "").strip()
        if name and name not in ctx["unit_vars"]:
            ctx["unit_vars"][name] = f"_unit_{_ident(name)}"
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
    add("#include <functional>")
    add("#include <type_traits>")
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

    # ------------------------------------------------------------------
    # Save-Struktur: ALLES, was ein Spielstand-Load ueberleben muss, liegt
    # in EINEM trivially-copyable struct, das ueber GetSaveRegions() mit
    # gespeichert und beim Laden von der Engine byte-genau restauriert wird:
    # Missionsvariablen, Group-/Unit-Handles und die Callback-Slot-Tabelle
    # (welcher TitanTriggerN-Slot zu welchem Callback gehoert). OP2 ruft beim
    # Laden eines Spielstands InitProc NICHT erneut auf!
    #
    # Save struct: EVERYTHING that must survive a savegame load lives in ONE
    # trivially copyable struct registered via GetSaveRegions(): mission
    # variables, group/unit handles and the callback slot table (which
    # TitanTriggerN slot maps to which callback). OP2 does NOT call InitProc
    # again when loading a saved game!
    # ------------------------------------------------------------------
    variables = getattr(mission, "variables", None) or []
    group_specs = (getattr(mission, "building_groups", None) or []) \
        + (getattr(mission, "reinforce_groups", None) or []) \
        + (getattr(mission, "fight_groups", None) or []) \
        + (getattr(mission, "mining_groups", None) or [])
    add("struct MissionSave {")
    add("    int cbCount = 0;                 // belegte Callback-Slots / used callback slots")
    add("    unsigned char cbSlot[64] = {};   // Slot -> Index in g_cbTable (0xFF = nicht wiederherstellbar)")
    for v in variables:
        init = int(v.initial_value) if v.initial_value is not None else 0
        if v.var_type == "bool":
            add(f"    bool {v.name} = {'true' if init else 'false'};")
        else:
            add(f"    int {v.name} = {init};")
    for armed_var in ctx.get("mining_action_vars", {}).values():
        add(f"    bool {armed_var} = false;")
    for g in group_specs:
        add(f"    Group {ctx['group_vars'][g.name]}{{}};")
    for var in ctx["wave_group_vars"].values():
        add(f"    Group {var}{{}};")
    for var in ctx["unit_vars"].values():
        add(f"    Unit {var}{{}};")
    add("};")
    add('static_assert(std::is_trivially_copyable_v<MissionSave>, "SaveRegion braucht POD-Daten");')
    add("static MissionSave g_save;")
    add("")
    # Referenzen, damit Ausdruecke/Aktionen die gewohnten Namen benutzen koennen.
    # References so expressions/actions keep using the familiar names.
    for v in variables:
        ctype = "bool" if v.var_type == "bool" else "int"
        add(f"static {ctype}& {v.name} = g_save.{v.name};")
    for armed_var in ctx.get("mining_action_vars", {}).values():
        add(f"static bool& {armed_var} = g_save.{armed_var};")
    for g in group_specs:
        var = ctx["group_vars"][g.name]
        add(f"static Group& {var} = g_save.{var};")
    for var in ctx["wave_group_vars"].values():
        add(f"static Group& {var} = g_save.{var};")
    for var in ctx["unit_vars"].values():
        add(f"static Unit& {var} = g_save.{var};")
    if variables or group_specs or ctx["wave_group_vars"] or ctx["unit_vars"] or ctx.get("mining_action_vars"):
        add("")

    # Callback-Registrierung mit Buchfuehrung: trackCb() merkt sich in g_save,
    # welcher Slot zu welchem Table-Eintrag gehoert; trackLost() belegt einen
    # Slot fuer Laufzeit-Lambdas mit Captures, die nach einem Load nicht
    # rekonstruierbar sind (Sentinel 0xFF).
    # Callback registration with bookkeeping: trackCb() records in g_save
    # which slot maps to which table entry; trackLost() burns a slot for
    # runtime lambdas with captures that cannot be rebuilt after a load.
    add("static std::function<void()> trackCb(void (*fn)(), int tableIdx) {")
    add("    if (g_save.cbCount < 64) g_save.cbSlot[g_save.cbCount++] = (unsigned char)tableIdx;")
    add("    return fn;")
    add("}")
    add("static std::function<void()> trackLost(std::function<void()> cb) {")
    add("    if (g_save.cbCount < 64) g_save.cbSlot[g_save.cbCount++] = 0xFF;")
    add("    return cb;")
    add("}")
    add("")

    # Forward declarations for trigger helpers (so a `createTrigger` action
    # earlier in the file can invoke a trigger declared further down).
    for helper in ctx["trigger_helpers_list"]:
        add(f"static void {helper}();")
    if mission.triggers:
        add("")

    # Callback-Tabelle vorbereiten: Zeitsieg/-niederlage-Callbacks als
    # benannte Funktionen VOR initProc definieren; Trigger-Callbacks
    # (<helper>_cb) bekommen hier ihre festen Table-Indizes.
    # Prepare the callback table: time win/lose callbacks as named functions
    # BEFORE initProc; trigger callbacks (<helper>_cb) get their fixed
    # table indices here.
    ctx["cb_table"] = []
    ctx["time_cb_by_id"] = {}
    for is_vic, conds in ((True, mission.victories or []), (False, mission.defeats or [])):
        for c in conds:
            if c.kind != "time":
                continue
            n = len(ctx["cb_table"])
            name = f"_cb_time{'win' if is_vic else 'lose'}_{n}"
            if is_vic:
                obj = _cpp_string(c.objective or "Mission objective")
                add(f"static void {name}() {{ op2::win({obj}); }}")
            else:
                add(f"static void {name}() {{ op2::lose(); }}")
            ctx["cb_table"].append(name)
            ctx["time_cb_by_id"][id(c)] = (name, n)
    ctx["trigger_cb_idx"] = {}
    for helper in ctx["trigger_helpers_list"]:
        ctx["trigger_cb_idx"][helper] = len(ctx["cb_table"])
        ctx["cb_table"].append(f"{helper}_cb")
    if ctx["time_cb_by_id"]:
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

    # Benannte Einheiten einfangen: nach dem BaseLayout steht jede Einheit noch
    # auf ihrer Platzierungs-Kachel. GameMap::unitOnTile ist NUR fuer Gebaeude/
    # Mauern/Rohre gepflegt (Footprint-Tabelle) -- bei Fahrzeugen liefert es
    # immer ein Null-Handle (siehe game.hpp: "Vehicles move and are not
    # tracked per-tile"). Fahrzeuge muessen daher ueber eine Positions-/Typ-
    # Suche in Game::unitsInRect() gefunden werden.
    #
    # Capture named units: right after the base layout every unit still sits
    # on its placement tile. GameMap::unitOnTile is ONLY maintained for
    # buildings/walls/tubes (a per-tile footprint table) -- for vehicles it
    # always returns a null handle (see game.hpp: "Vehicles move and are not
    # tracked per-tile"). Vehicles must instead be found via a position/type
    # search over Game::unitsInRect().
    if ctx["unit_vars"]:
        add("")
        add("    // --- Named units ---")
        for u in (mission.units or []):
            name = (getattr(u, "unit_name", "") or "").strip()
            var = ctx["unit_vars"].get(name)
            if not var:
                continue
            if _strip_map(u.unit_type) in _BUILDING_TYPES:
                add(f"    {var} = GameMap::unitOnTile({_xy(u.x, u.y)});")
            else:
                loc = _xy(u.x, u.y)
                add(f"    for (Unit _u : Game::unitsInRect({loc}, {loc})) {{")
                add(f"        if (_u.type() == {mapid(u.unit_type)} "
                    f"&& _u.ownerId() == {int(u.player)}) {{ {var} = _u; break; }}")
                add(f"    }}")

    # Groups (declared at file scope, assigned here)
    for line in _emit_groups(mission, ctx):
        add(line)

    # Selbstheilende Gruppen: EIN wiederkehrender Timer fuer die ganze Mission
    # Self-healing groups: ONE recurring timer for the whole mission
    for line in _emit_group_repair(mission, ctx):
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
            for line in _emit_condition(c, is_victory=True, mission=mission, ctx=ctx):
                add(line)
    if mission.defeats:
        add("")
        add("    // --- Defeat conditions ---")
        for c in mission.defeats:
            for line in _emit_condition(c, is_victory=False, mission=mission, ctx=ctx):
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

    # --- Savegame-Restore: Callback-Registry aus g_save wiederherstellen ---
    if ctx["cb_table"]:
        add("// Alle statisch bekannten Trigger-Callbacks (Index = cbSlot-Wert in g_save).")
        add("// All statically known trigger callbacks (index = cbSlot value in g_save).")
        add("static void (* const g_cbTable[])() = {")
        for name in ctx["cb_table"]:
            add(f"    &{name},")
        add("};")
        add("static constexpr int kNumKnownCbs = int(sizeof(g_cbTable) / sizeof(g_cbTable[0]));")
    else:
        add("static void (* const g_cbTable[1])() = { nullptr };")
        add("static constexpr int kNumKnownCbs = 0;")
    add("")
    add("// Beim Laden eines Spielstands ruft OP2 InitProc NICHT erneut auf. Die")
    add("// Engine stellt ihre Trigger (inkl. TitanTriggerN-Stubnamen) aus dem")
    add("// Spielstand wieder her -- aber die Callback-Registry der DLL ist leer.")
    add("// g_save (SaveRegion) enthaelt die Slot->Callback-Zuordnung; hier wird")
    add("// die Registry daraus wiederaufgebaut. Slots mit 0xFF (Laufzeit-Lambdas")
    add("// mit Captures) sind nicht wiederherstellbar und bleiben leer.")
    add("//")
    add("// On savegame load OP2 does NOT call InitProc again. The engine restores")
    add("// its triggers (incl. TitanTriggerN stub names) from the save -- but the")
    add("// DLL's callback registry is empty. g_save (SaveRegion) holds the")
    add("// slot->callback mapping; rebuild the registry from it here.")
    add("static void restoreCallbacksAfterLoad() {")
    add("    using namespace op2::trigger_detail;")
    add("    if (g_count != 0 || g_save.cbCount <= 0) return;  // frische Session / nichts zu tun")
    add("    int lost = 0;")
    add("    for (int i = 0; i < g_save.cbCount && i < kMaxCallbacks; ++i) {")
    add("        const int idx = g_save.cbSlot[i];")
    add("        if (idx >= 0 && idx < kNumKnownCbs) g_callbacks[i] = g_cbTable[idx];")
    add("        else ++lost;")
    add("    }")
    add("    g_count = g_save.cbCount;")
    add('    log::linef("Savegame-Load: %d Trigger-Callbacks wiederhergestellt, %d nicht wiederherstellbar",')
    add("               g_save.cbCount - lost, lost);")
    add("}")
    add("")

    # --- aiProc ---
    add("static void aiProc() {")
    add("    // Fallback: falls OnLoadSavedGame von dieser OPU-Version nicht gerufen")
    add("    // wird, stellt der erste AIProc-Tick nach einem Load die Registry her.")
    add("    restoreCallbacksAfterLoad();")
    add("}")
    add("")

    # --- Guarded exports + DllMain ---
    add('extern "C" __declspec(dllexport) int  InitProc() { crash::guard("InitProc", &initProc); return 1; }')
    add('extern "C" __declspec(dllexport) void AIProc()   { crash::guard("AIProc",   &aiProc); }')
    add("")
    add("// SaveRegion: g_save wird von der Engine mit dem Spielstand gespeichert")
    add("// und beim Laden byte-genau restauriert (Variablen, Gruppen, Einheiten,")
    add("// Callback-Slots).")
    add('extern "C" __declspec(dllexport) void GetSaveRegions(mission::SaveRegion* p) {')
    add('    if (p) { p->pData = &g_save; p->size = sizeof(g_save); }')
    add('}')
    add("")
    add('extern "C" __declspec(dllexport) int OnLoadSavedGame(mission::OnLoadSavedGameArgs*) {')
    add('    crash::guard("OnLoadSavedGame", &restoreCallbacksAfterLoad);')
    add("    return 1;")
    add("}")
    add("")
    add('extern "C" int __stdcall DllMain(void*, unsigned long reason, void*) {')
    add("    if (reason == 1 /* DLL_PROCESS_ATTACH */) {")
    add('        crash::installHandler();')
    add('        log::setTickSource([] { return Game::tick(); });')
    add("    }")
    add("    return 1;")
    add("}")

    return "\n".join(out) + "\n"
