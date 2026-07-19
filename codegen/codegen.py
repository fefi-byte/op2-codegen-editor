"""Codegen: Mission-Modell -> mission.cpp (OP2MissionSDK / Outpost2DLL + OP2Helper + HFL).

Reads a Mission object (mission_model.py) and produces the C++ source code
that compiles against the classic Outpost 2 Mission SDK
(https://github.com/OutpostUniverse/OP2MissionSDK) into a runnable mission DLL.

Koordinaten: Editor-Tiles sind 0-basiert; die im Spiel sichtbaren Koordinaten
sind 1-basiert (visible = editor + 1); die Engine-internen LOCATIONs haben
zusaetzlich den Karten-Offset (+31, -1) -- OP2Helpers MkXY(visible_x,
visible_y) erledigt genau das. Der Codegen emittiert deshalb ueberall
MkXY(editor+1, editor+1) bzw. MkRect/XYPos.

Coordinates: editor tiles are 0-based; the in-game visible coordinates are
1-based (visible = editor + 1); engine-internal LOCATIONs additionally carry
the map offset (+31, -1) -- OP2Helper's MkXY(visible_x, visible_y) does
exactly that. The codegen therefore emits MkXY(editor+1, editor+1) resp.
MkRect/XYPos everywhere.

Savegames: Trigger sind Engine-Objekte (ScStubs), ihre Callbacks werden ueber
den EXPORTIERTEN Funktionsnamen aufgeloest -- auch nach einem Load. Es gibt
daher keine Callback-Slot-Buchfuehrung mehr (kein trackCb/trackLost); nur
g_save (Variablen, Gruppen-/Unit-/Trigger-Stubs, armed-Flags) wird ueber
ExportSaveLoadData mitgespeichert.

Savegames: triggers are engine objects (ScStubs); their callbacks resolve via
the EXPORTED function name -- after a load too. So there is no callback-slot
bookkeeping anymore (no trackCb/trackLost); only g_save (variables,
group/unit/trigger stubs, armed flags) is saved via ExportSaveLoadData.
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
    """Emit a LOCATION literal (engine coords via MkXY) that may contain runtime expressions."""
    return f"MkXY({_visible_expr(x)}, {_visible_expr(y)})"


def _xypos_expr(x, y) -> str:
    """Emit the two-int engine-coordinate pair (XYPos macro) for APIs taking raw tileX, tileY."""
    return f"XYPos({_visible_expr(x)}, {_visible_expr(y)})"


# ---------------------------------------------------------------------------
# Mapping tables: editor strings -> classic SDK enum members. The editor's
# id strings ("mapCommandCenter", "cmpEqual", "resFood") ARE the classic
# Outpost2DLL enum member names, so most mappings are identity.
# ---------------------------------------------------------------------------

def _strip_map(name: str) -> str:
    """`mapCommandCenter` -> `CommandCenter`. Empty stays empty."""
    name = (name or "").strip()
    if name.startswith("map"):
        name = name[3:]
    return name


def mapid(name: str) -> str:
    """Editor map id -> classic `map_id` enum member (identical names)."""
    name = (name or "").strip()
    return name if name else "mapNone"


def _resource(name: str) -> str:
    """Editor resource id -> classic `trig_res` enum member (identical names)."""
    name = (name or "").strip()
    return name if name.startswith("res") else "resCommonOre"


def _compare(name: str) -> str:
    """Editor compare id -> classic `compare_mode` enum member (identical names)."""
    name = (name or "").strip()
    return name if name.startswith("cmp") else "cmpGreaterEqual"


# Editor tiles are 0-based (top-left = (0,0)); the visible in-game tiles are
# 1-based. MkXY(visible_x, visible_y) (OP2Helper) converts visible -> engine
# LOCATION (adds +31/-1). Use _xy() everywhere the generator emits a LOCATION.
def _xy(x: int, y: int) -> str:
    return f"MkXY({int(x) + 1}, {int(y) + 1})"


def _xypos(x: int, y: int) -> str:
    """Two-int engine-coordinate pair for APIs taking raw tileX, tileY."""
    return f"XYPos({int(x) + 1}, {int(y) + 1})"


def _rect(x1: int, y1: int, x2: int, y2: int) -> str:
    """MAP_RECT literal (engine coords via MkRect)."""
    return f"MkRect({int(x1) + 1}, {int(y1) + 1}, {int(x2) + 1}, {int(y2) + 1})"


# UnitEx::GetLastCommand() liefert HFLs CommandType (ct*-Konstanten); der
# Editor speichert die Kurznamen ("Move", "Attack", ...).
# UnitEx::GetLastCommand() returns HFL's CommandType (ct* constants); the
# editor stores the short names ("Move", "Attack", ...).
_CMD_TYPE = {
    "Nop": "ctNop",
    "Move": "ctMoMove",
    "Stop": "ctMoStop",
    "Idle": "ctMoIdle",
    "Unidle": "ctMoUnidle",
    "Attack": "ctMoAttackObj",
    "Guard": "ctMoGuard",
    "Patrol": "ctMoPatrol",
    "RepairObj": "ctMoRepairObj",
    "Reprogram": "ctMoReprogram",
    "Dismantle": "ctMoDismantle",
    "Build": "ctMoBuild",
    "Develop": "ctMoDevelop",
    "UnDevelop": "ctMoUnDevelop",
    "Dock": "ctMoDock",
    "Transfer": "ctMoTransfer",
    "Research": "ctMoResearch",
    "SelfDestruct": "ctMoSelfDestruct",
}


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
    """Map MissionType IntEnum -> classic `MissionTypes` enum member."""
    name = {
        MissionType.Colony: "Colony",
        MissionType.AutoDemo: "AutoDemo",
        MissionType.Tutorial: "Tutorial",
        MissionType.MultiLandRush: "MultiLandRush",
        MissionType.MultiSpaceRace: "MultiSpaceRace",
        MissionType.MultiResourceRace: "MultiResourceRace",
        MissionType.MultiMidas: "MultiMidas",
        MissionType.MultiLastOneStanding: "MultiLastOneStanding",
    }.get(mt, "Colony")
    return name


# ---------------------------------------------------------------------------
# Code emission.
# ---------------------------------------------------------------------------

def _emit_player_setup(idx: int, p: PlayerSpec) -> list[str]:
    """One Player's setup block (called from InitProc())."""
    lines = [f"    // --- Player {idx} ---"]
    lines.append(f"    Player[{idx}].{'GoEden' if p.colony == Colony.Eden else 'GoPlymouth'}();")
    lines.append(f"    Player[{idx}].{'GoHuman' if p.is_human else 'GoAI'}();")

    if p.tech_level is not None and p.tech_level != 0:
        lines.append(f"    Player[{idx}].SetTechLevel({int(p.tech_level)});")

    # population
    if (p.workers is not None) or (p.scientists is not None) or (p.kids is not None):
        lines.append(f"    Player[{idx}].SetWorkers({0 if p.workers is None else int(p.workers)});")
        lines.append(f"    Player[{idx}].SetScientists({0 if p.scientists is None else int(p.scientists)});")
        lines.append(f"    Player[{idx}].SetKids({0 if p.kids is None else int(p.kids)});")

    # resources (support int and str expressions)
    if p.common_ore is not None:
        lines.append(f"    Player[{idx}].SetOre({_expr_or_int(p.common_ore)});")
    if p.rare_ore is not None:
        lines.append(f"    Player[{idx}].SetRareOre({_expr_or_int(p.rare_ore)});")
    if p.food is not None:
        lines.append(f"    Player[{idx}].SetFoodStored({_expr_or_int(p.food)});")

    # individual researches (on top of tech_level)
    for tech in (p.researches or []):
        lines.append(f"    Player[{idx}].MarkResearchComplete({int(tech)});")

    return lines


def _emit_base_layout(mission: Mission, ctx: dict) -> list[str]:
    """Emit the initial base per player: beacons, tubes/walls, buildings, vehicles.

    The classic SDK has no BaseLayout convenience -- everything is created
    directly via TethysGame::CreateBeacon / CreateWallOrTube / CreateUnit.

    Einheiten, die spaeter referenziert werden (Gruppen-Roster, benannte
    Einheiten), werden DIREKT in ihr Handle erzeugt (ctx["uid_handle_vars"])
    -- das klassische, bewaehrte Muster. Positions-Enumeration in InitProc
    entfaellt damit komplett.

    Units that are referenced later (group rosters, named units) are created
    DIRECTLY into their handle (ctx["uid_handle_vars"]) -- the classic,
    proven pattern. No position enumeration in InitProc anymore.
    """
    by_player_units: dict[int, list] = {}
    for u in (mission.units or []):
        by_player_units.setdefault(int(u.player), []).append(u)

    # beacons + walls are world-owned (Gaia), but the editor groups them with
    # player 0 in practice; we attach beacons to player 0's block.
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
        lines.append(f"        Unit _u;")

        if pidx == 0:
            # beacons (player-agnostic, but only emit once -> on player 0)
            for b in beacons:
                if (b.beacon_type or "").endswith("MiningBeacon"):
                    # ore_type: -1 random, 0 common, 1 rare
                    ore = {0: "OreTypeCommon", 1: "OreTypeRare"}.get(
                        int(getattr(b, "ore_type", -1)), "OreTypeRandom")
                    # yield_bars: -1 random, 0=Bar3, 1=Bar2, 2=Bar1
                    yld = {0: "Bar3", 1: "Bar2", 2: "Bar1"}.get(
                        int(getattr(b, "yield_bars", -1)), "BarRandom")
                    lines.append(
                        f"        TethysGame::CreateBeacon(mapMiningBeacon, "
                        f"{_xypos(b.x, b.y)}, {ore}, {yld}, VariantRandom);")
            # tubes + walls (Gaia)
            for w in walls:
                wt = w.wall_type or "mapTube"
                lines.append(
                    f"        TethysGame::CreateWallOrTube({_xypos(w.x, w.y)}, 0, {mapid(wt)});")

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

        handle_vars = ctx.get("uid_handle_vars", {})
        beacon_tiles = {(int(b.x), int(b.y)) for b in beacons}
        for u in buildings:
            cargo = mapid(u.cargo) if (u.cargo and u.cargo != "mapNone") else "mapNone"
            btype = mapid(u.unit_type)
            if btype == "mapRareOreMine":
                # Per DLL erzeugte Rare-Ore-Mines funktionieren nicht (Coding
                # 101 W9): stattdessen Rare-Beacon + CommonOreMine auf dem
                # Feld -- die Engine macht daraus eine echte Rare-Ore-Mine.
                # Liegt schon ein (Editor-)Beacon auf dem Feld, wird keiner
                # doppelt erzeugt.
                # DLL-created rare ore mines do not work (Coding 101 W9):
                # emit a rare beacon + CommonOreMine instead -- the engine
                # turns that into a working rare ore mine. If an (editor)
                # beacon already sits on the tile, none is duplicated.
                if (int(u.x), int(u.y)) not in beacon_tiles:
                    lines.append(
                        f"        TethysGame::CreateBeacon(mapMiningBeacon, "
                        f"{_xypos(u.x, u.y)}, OreTypeRare, BarRandom, VariantRandom);")
                btype = "mapCommonOreMine"
            uvar = handle_vars.get(getattr(u, "uid", ""), "_u")
            lines.append(
                f"        TethysGame::CreateUnit({uvar}, {btype}, "
                f"{_xy(u.x, u.y)}, {pidx}, {cargo}, 0);")

        for u in vehicles:
            weapon = mapid(u.cargo) if (u.cargo and u.cargo != "mapNone") else "mapNone"
            facing_idx = int(getattr(u, "rotation", 0)) % 8
            facing = ("East", "SouthEast", "South", "SouthWest",
                      "West", "NorthWest", "North", "NorthEast")[facing_idx]
            uvar = handle_vars.get(getattr(u, "uid", ""), "_u")
            lines.append(
                f"        TethysGame::CreateUnit({uvar}, {mapid(u.unit_type)}, "
                f"{_xy(u.x, u.y)}, {pidx}, {weapon}, {facing});")

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


def _cond_var(cond) -> str:
    return f"_v_{abs(hash(repr(cond))) & 0xFFFF}"


def _emit_condition(cond: Condition, is_victory: bool, mission: Mission | None = None,
                    ctx: dict | None = None) -> list[str]:
    """Emit one win/lose condition (called from InitProc()).

    Klassisches Muster: einen (bedingungslosen) Engine-Trigger mit dem No-Op-
    Callback "NoResponseToTrigger" erzeugen und in CreateVictoryCondition /
    CreateFailureCondition einhaengen -- die Engine wertet den Sieg selbst aus.

    Classic pattern: create a (condition) engine trigger with the no-op
    callback "NoResponseToTrigger" and wrap it in CreateVictoryCondition /
    CreateFailureCondition -- the engine evaluates the win itself.
    """
    lines: list[str] = []
    obj = _cpp_string(cond.objective or ("Mission objective" if is_victory else ""))
    cmp_ = _compare(cond.compare)

    def _wrap(trigger_expr: str, var: str) -> None:
        lines.append(f"    Trigger {var} = {trigger_expr};")
        if is_victory:
            lines.append(f"    CreateVictoryCondition(1, 0, {var}, {obj});")
        else:
            lines.append(f'    CreateFailureCondition(1, 0, {var}, "");')

    if cond.kind == "time":
        _wrap(f'CreateTimeTrigger(1, 1, {int(cond.marks)} * kTicksPerMark, "NoResponseToTrigger")',
              _cond_var(cond))
    elif cond.kind == "noCC":
        # OP2Helper: CreateOperationalTrigger(CC == 0) + FailureCondition.
        lines.append(f"    CreateNoCommandCenterFailureCondition({int(cond.player)});")
    elif cond.kind == "lastStanding":
        # Win when every enemy (AI) colony is wiped out. OP2 ANDs victory
        # conditions, so one building-count-below-1 condition per enemy player
        # means ALL of them must fall before the win fires.
        enemies = [i for i, p in enumerate((mission.players if mission else []) or [])
                   if not p.is_human]
        if enemies:
            lo_obj = _cpp_string(cond.objective or "Eliminate all enemy colonies")
            for n, e in enumerate(enemies):
                var = f"{_cond_var(cond)}_{n}"
                lines.append(
                    f'    Trigger {var} = CreateBuildingCountTrigger(1, 1, {e}, 1, '
                    f'cmpLower, "NoResponseToTrigger");')
                lines.append(f"    CreateVictoryCondition(1, 0, {var}, {lo_obj});")
        else:
            lines.append(f"    // last-one-standing: no AI players in this mission -> nothing to destroy")
    elif cond.kind == "starship":
        # Starship evacuation: fires once an Evacuation Module has been
        # launched (same CreateCountTrigger idiom as OP2Helper's
        # CreateStarshipVictoryCondition).
        ss_obj = _cpp_string(
            cond.objective
            or "Evacuate 200 colonists and 10000 units of Common and Rare Metals to the starship.")
        var = _cond_var(cond)
        lines.append(
            f'    Trigger {var} = CreateCountTrigger(1, 1, {int(cond.player)}, '
            f'mapEvacuationModule, mapAny, 1, cmpGreaterEqual, "NoResponseToTrigger");')
        lines.append(f"    CreateVictoryCondition(1, 0, {var}, {ss_obj});")
    elif cond.kind == "buildingCount":
        _wrap(f'CreateBuildingCountTrigger(1, 1, {int(cond.player)}, {int(cond.count)}, '
              f'{cmp_}, "NoResponseToTrigger")', _cond_var(cond))
    elif cond.kind == "vehicleCount":
        _wrap(f'CreateVehicleCountTrigger(1, 1, {int(cond.player)}, {int(cond.count)}, '
              f'{cmp_}, "NoResponseToTrigger")', _cond_var(cond))
    elif cond.kind == "research":
        _wrap(f'CreateResearchTrigger(1, 1, {int(cond.tech_id)}, {int(cond.player)}, '
              f'"NoResponseToTrigger")', _cond_var(cond))
    elif cond.kind == "resource":
        res = _resource(cond.resource)
        _wrap(f'CreateResourceTrigger(1, 1, {res}, {int(cond.amount)}, {int(cond.player)}, '
              f'{cmp_}, "NoResponseToTrigger")', _cond_var(cond))
    elif cond.kind == "operational":
        _wrap(f'CreateOperationalTrigger(1, 1, {int(cond.player)}, {mapid(cond.building)}, '
              f'{int(cond.count)}, {cmp_}, "NoResponseToTrigger")', _cond_var(cond))
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


_CMP_OP = {
    "cmpEqual": "==",
    "cmpLowerEqual": "<=",
    "cmpGreaterEqual": ">=",
    "cmpLower": "<",
    "cmpGreater": ">",
}


def _emit_action_condition_expr(c: ActionCondition, depth: int = 0) -> str:
    """Returns a single C++ bool expression for `c`, already negated if needed."""
    cmp_op = _CMP_OP.get(c.compare, ">=")

    if c.kind == "buildingAtLocation":
        expr = f"(unitOnTile({_xy(c.x, c.y)}).GetType() == {mapid(c.building_type)})"
    elif c.kind == "buildingCount":
        expr = f"(countUnitsOfType({int(c.player)}, {mapid(c.building_type)}) {cmp_op} {_expr_or_int(c.value)})"
    elif c.kind == "playerResource":
        # Map editor resource string -> _Player getter.
        p = int(c.player)
        getter = {
            "resCommonOre": f"Player[{p}].Ore()",
            "resRareOre": f"Player[{p}].RareOre()",
            "resFood": f"Player[{p}].FoodStored()",
            "resKids": f"Player[{p}].Kids()",
            "resWorkers": f"Player[{p}].Workers()",
            "resScientists": f"Player[{p}].Scientists()",
            "resColonists": f"(Player[{p}].Kids() + Player[{p}].Workers() + Player[{p}].Scientists())",
        }.get(c.resource, f"Player[{p}].Ore()")
        expr = f"({getter} {cmp_op} {_expr_or_int(c.value)})"
    elif c.kind == "hasTech":
        expr = f"Player[{int(c.player)}].HasTechnology({int(c.tech_id)})"
    elif c.kind == "unitDamage":
        # Without a stable unit handle: "any of this player's units of this
        # type with damage `cmp` value". IIFE lambda over PlayerUnitEnum;
        # GetDamage() is HFL/UnitEx. Expensive at runtime but rarely used.
        expr = (f"([&]{{ PlayerUnitEnum _pe({int(c.player)}); UnitEx _pu; "
                f"while (_pe.GetNext(_pu)) if (_pu.GetType() == {mapid(c.building_type)} "
                f"&& (_pu.GetDamage() {cmp_op} {_expr_or_int(c.value)})) return true; "
                f"return false; }}())")
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
            expr = f"({uv}.GetType() == {mapid(c.building_type)})"
        elif c.kind == "loopUnitDamage":
            expr = f"({uv}.GetDamage() {cmp_op} {_expr_or_int(c.value)})"
        elif c.kind == "loopUnitCargo":
            expr = f"({uv}.GetWeapon() == {mapid(c.building_type)})"
        else:
            cmd_name = getattr(c, "command_type", "Move") or "Move"
            expr = f"({uv}.GetLastCommand() == {_CMD_TYPE.get(cmd_name, 'ctMoMove')})"
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
        return [f"{indent}AddGameMessage({_cpp_string(action.text)});"]

    if k == "createUnit":
        entries = list(getattr(action, "unit_list", None) or [])
        if not entries:
            entries = [{"unit_type": action.unit_type, "weapon_type": action.weapon_type,
                        "x": action.x, "y": action.y}]
        lines = [f"{indent}{{", f"{indent}    Unit _u;"]
        for e in entries:
            wt = e.get("weapon_type") or "mapNone"
            weapon = mapid(wt) if wt != "mapNone" else "mapNone"
            utype = mapid(e.get("unit_type", "mapScout"))
            if utype == "mapRareOreMine":
                # Per DLL erzeugte Rare-Ore-Mines funktionieren nicht (Coding
                # 101 W9): Rare-Beacon + CommonOreMine emittieren.
                # DLL-created rare ore mines do not work (Coding 101 W9):
                # emit a rare beacon + CommonOreMine instead.
                lines.append(
                    f"{indent}    TethysGame::CreateBeacon(mapMiningBeacon, "
                    f"{_xypos(e.get('x', 0), e.get('y', 0))}, OreTypeRare, BarRandom, VariantRandom);")
                utype = "mapCommonOreMine"
            lines.append(
                f"{indent}    TethysGame::CreateUnit(_u, {utype}, "
                f"{_xy(e.get('x', 0), e.get('y', 0))}, {int(action.player)}, {weapon}, 0);"
            )
        lines.append(f"{indent}}}")
        return lines

    if k == "createDisaster":
        dtype = getattr(action, "disaster_type", "meteor") or "meteor"
        xy = _xypos_expr(getattr(action, "x_expr", 0), getattr(action, "y_expr", 0))
        xy2 = _xypos_expr(getattr(action, "x2_expr", 0), getattr(action, "y2_expr", 0))
        if dtype == "meteor":
            # Kein "sofort"-Flag in der Engine -- die Vorwarnzeit haengt von
            # der Meteorabwehr-Forschung ab. / No "now" flag in the engine.
            return [f"{indent}TethysGame::SetMeteor({xy}, {int(getattr(action, 'size', -1))});"]
        if dtype == "earthquake":
            return [f"{indent}TethysGame::SetEarthquake({xy}, "
                    f"{_expr_or_int(getattr(action, 'magnitude', 1))});"]
        if dtype == "storm":
            return [f"{indent}TethysGame::SetLightning({xy}, "
                    f"{_expr_or_int(getattr(action, 'duration', 100))}, {xy2});"]
        if dtype == "vortex":
            now = "1" if getattr(action, "now", False) else "0"
            return [f"{indent}TethysGame::SetTornado({xy}, "
                    f"{_expr_or_int(getattr(action, 'duration', 100))}, {xy2}, {now});"]
        if dtype == "eruption":
            zone = getattr(action, "lava_zone", None) or []
            lines = []
            for p in zone:
                lines.append(
                    f"{indent}GameMap::SetLavaPossible({_xy(int(p[0]), int(p[1]))}, 1);")
            spread = int(getattr(action, "spread_speed", 15))
            lines.append(f"{indent}TethysGame::SetEruption({xy}, {spread});")
            # Ohne SetLavaSpeed fliesst die Lava nicht mit der erwarteten
            # Geschwindigkeit (klassisches Rezept: beide Aufrufe, siehe
            # Coding 101 W4). / Without SetLavaSpeed the lava does not flow
            # at the expected speed (classic recipe: both calls).
            lines.append(f"{indent}TethysGame::SetLavaSpeed({spread});")
            return lines
        if dtype == "blight":
            # Der Blight hat KEINE automatische Warnmeldung -- eine eigene
            # message-Aktion davor ist empfehlenswert. Spread skaliert mit
            # der Kartengroesse. / The blight has NO automatic warning
            # message -- a preceding message action is recommended. Spread
            # scales with map size.
            spread = int(getattr(action, "spread_speed", 15)) or 15
            return [
                f"{indent}GameMap::SetVirusUL("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, 1);",
                f"{indent}TethysGame::SetMicrobeSpreadSpeed({spread});",
            ]
        if dtype == "unblight":
            return [
                f"{indent}GameMap::SetVirusUL("
                f"{_loc_expr(getattr(action, 'x_expr', 0), getattr(action, 'y_expr', 0))}, 0);"
            ]
        return [f"{indent}// TODO unsupported disaster type: {dtype}"]

    if k == "createTrigger":
        # Editor model: "createTrigger" creates ANOTHER editor-defined trigger
        # at runtime -- re-invoking the trigger factory helper does that.
        target = ctx["trigger_helpers"].get(action.target, None)
        if target:
            return [f"{indent}{target}();"]
        return [f"{indent}// TODO createTrigger target '{action.target}' not found"]

    if k == "recordBuilding":
        # Editor: pick a BuildingGroup, then add a building to its roster so
        # the group rebuilds it. Classic: BuildingGroup::RecordBuilding.
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            return [f"{indent}// TODO recordBuilding: building group '{action.group_name}' not declared"]
        entries = list(getattr(action, "building_list", None) or [])
        if not entries:
            entries = [{"building_type": action.building_type, "weapon_type": action.weapon_type,
                        "x": action.x, "y": action.y}]
        # RecordBuilding nimmt LOCATION& (non-const) -- benannte lokale Variable.
        # RecordBuilding takes LOCATION& (non-const) -- named local variable.
        lines = [f"{indent}{{", f"{indent}    LOCATION _l;"]
        for e in entries:
            wt = e.get("weapon_type") or "mapNone"
            cargo = mapid(wt) if wt != "mapNone" else "mapNone"
            bt = mapid(e.get("building_type", "mapCommandCenter"))
            lines.append(f"{indent}    _l = {_xy(e.get('x', 0), e.get('y', 0))};")
            lines.append(f"{indent}    {var}.RecordBuilding(_l, {bt}, {cargo});")
            lines.append(
                f'{indent}    op2::log::linef("RecordBuilding: {bt} @ ({int(e.get("x", 0))},'
                f'{int(e.get("y", 0))}) -> Gruppe mit %d Einheiten", {var}.TotalUnitCount());')
        lines.append(f"{indent}}}")
        return lines

    if k == "recordTube":
        entries = list(getattr(action, "tube_list", None) or [])
        if not entries:
            entries = [{"x": action.x, "y": action.y, "x2": action.x2, "y2": action.y2}]
        lines = []
        for e in entries:
            for tx, ty in _line_tiles(int(e.get("x", 0)), int(e.get("y", 0)),
                                       int(e.get("x2", 0)), int(e.get("y2", 0))):
                lines.append(f"{indent}TethysGame::CreateWallOrTube({_xypos(tx, ty)}, 0, mapTube);")
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
                lines.append(f"{indent}TethysGame::CreateWallOrTube({_xypos(tx, ty)}, 0, {mapid(wt)});")
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
            weapon = mapid(wt) if wt != "mapNone" else "mapNone"
            lines.append(
                f"{indent}{var}.SetTargCount({mapid(e.get('unit_type', 'mapConVec'))}, {weapon}, "
                f"{_expr_or_int(e.get('count', 1))});"
            )
        # Optionale Verknuepfung: die im Formular gewaehlte ReinforceGroup soll
        # tatsaechlich fuer DIESE Gruppe produzieren.
        # Optional link: the ReinforceGroup chosen in the form should actually
        # produce for THIS group.
        src_name = getattr(action, "source_group_name", "") or ""
        if src_name:
            src_var = ctx["group_vars"].get(src_name)
            if src_var:
                # Prioritaet 0 haengt das Spiel (siehe Groups.h) -- min. 1.
                # Priority 0 hangs the game (see Groups.h) -- at least 1.
                prio = max(1, int(getattr(action, "reinforce_priority", 1000) or 1000))
                lines.append(f"{indent}{src_var}.RecordVehReinforceGroup({var}, {prio});")
            else:
                lines.append(f"{indent}// TODO setTargCount: ReinforceGroup '{src_name}' not declared")
        return lines

    if k == "assignToGroup":
        # Frueher ein eigener Poll-Timer pro Aktion; jetzt nur ein armed-Flag
        # setzen -- der missionsweite Reparatur-Timer (_emit_group_repair)
        # uebernimmt das Polling (und heilt gleich mit, wenn das Gebaeude
        # spaeter zerstoert und neu errichtet wird).
        # Used to be its own poll timer per action; now just set an armed flag
        # -- the mission-wide repair timer (_emit_group_repair) does the
        # polling (and self-heals when the building is later destroyed and
        # rebuilt).
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            return [f"{indent}// TODO assignToGroup: target group '{action.group_name}' not declared"]
        armed_var = ctx.get("assign_action_vars", {}).get(id(action))
        if not armed_var:
            return [f"{indent}// TODO assignToGroup: armed flag not declared"]
        return [f"{indent}{armed_var} = true;"]

    if k == "startMining":
        # Referenziert eine vordefinierte MiningGroup (group_name -> group_vars).
        # Der Abladebereich kommt aus der MiningGroupSpec (idle_x/y/width/height);
        # die anfaengliche Truck-Roster (unit_ids) wird bereits einmalig in
        # InitProc zugewiesen (_emit_groups).
        # References a predefined MiningGroup (group_name -> group_vars). The
        # unload area comes from the MiningGroupSpec (idle_x/y/width/height);
        # the initial truck roster (unit_ids) is already assigned once in
        # InitProc (_emit_groups).
        var = ctx["group_vars"].get(action.group_name, None)
        spec = ctx.get("mining_group_specs", {}).get(action.group_name)
        if not var or spec is None:
            return [f"{indent}// TODO startMining: MiningGroup '{action.group_name}' not declared"]
        mine_ref = getattr(action, "mine_ref", "") or ""
        smelter_ref = getattr(action, "smelter_ref", "") or ""
        if mine_ref in ("<loop>", "<loop:outer>") or smelter_ref in ("<loop>", "<loop:outer>"):
            # Schleifenreferenz: nur HIER gueltig -- die Schleifenvariable
            # existiert nur innerhalb dieser Iteration, kann also nicht in den
            # missionsweiten Reparatur-Callback verschoben werden. Bleibt ein
            # einmaliger Inline-Block (kein Self-Heal fuer diesen Fall).
            # Loop reference: only valid HERE -- the loop variable only exists
            # within this iteration, so it can't be moved into the
            # mission-wide repair callback. Stays a one-shot inline block (no
            # self-heal for this case).
            mine_expr = (_resolve_loop_ref(mine_ref, depth) or ctx.get("unit_vars", {}).get(mine_ref)
                         if mine_ref else None) or f"unitOnTile({_xy(action.x, action.y)})"
            smelter_expr = (_resolve_loop_ref(smelter_ref, depth) or ctx.get("unit_vars", {}).get(smelter_ref)
                            if smelter_ref else None) or f"unitOnTile({_xy(action.x2, action.y2)})"
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
        # (_emit_group_repair) -- diese Aktion setzt hier nur das Flag.
        # Position or named-unit reference: globally valid. The actual linking
        # (including re-linking after destruction+rebuild) happens centrally
        # in the recurring repair callback (_emit_group_repair) -- this action
        # only sets the flag checked there.
        armed_var = ctx.get("mining_action_vars", {}).get(id(action))
        if not armed_var:
            return [f"{indent}// TODO startMining: armed flag not declared"]
        return [f"{indent}{armed_var} = true;"]

    if k == "sendAttackWave":
        # High-level attack wave. Composition comes from wave_units
        # ([{unit_type, weapon_type, count}, ...]; falls back to the single
        # unit_type/target_count pair from older saves). Two modes:
        #   spawn     -- create the units instantly in the staging rect
        #   reinforce -- a ReinforceGroup produces them (SetTargCount +
        #                RecordVehReinforceGroup); optional auto-attack once full
        # Staging rect: (x,y)-(x2,y2). Attack rect: (attack_x,attack_y)-(attack_x2,attack_y2).
        p = int(action.player)
        waves = list(getattr(action, "wave_units", None) or [])
        if not waves:
            waves = [{"unit_type": action.unit_type or "mapLynx",
                      "weapon_type": action.weapon_type or "mapLaser",
                      "count": action.target_count}]
        mode = getattr(action, "spawn_mode", "spawn") or "spawn"
        auto_attack = bool(getattr(action, "now", False))
        geo = _wave_geometry(action)
        ix, iy, iw = geo["ix"], geo["iy"], geo["iw"]

        # Angriffswellen referenzieren zwingend eine VORHER definierte FightGroup
        # (Gruppen-Panel). Die Gruppe selbst wird bereits einmalig in InitProc
        # angelegt (_emit_groups).
        # Attack waves must reference a PRE-DEFINED FightGroup (Groups panel).
        # The group itself is already created once in InitProc (_emit_groups).
        wave_name = getattr(action, "group_var_name", "") or ""
        fg = ctx["group_vars"].get(wave_name)
        if not fg:
            return [f"{indent}// TODO sendAttackWave: FightGroup '{wave_name}' not declared"]

        lines = [f"{indent}{{",
                 f"{indent}    MAP_RECT _r = {geo['idle_rect']};",
                 f"{indent}    {fg}.SetRect(_r);"]

        if mode == "spawn":
            i = 0
            for w in waves:
                wt = w.get("weapon_type") or "mapLaser"
                weapon = mapid(wt) if wt != "mapNone" else "mapNone"
                n = int(w.get("count", 1) or 1)
                lines.append(f"{indent}    for (int _i = {i}; _i < {i + n}; ++_i) {{")
                lines.append(f"{indent}        Unit _u;")
                lines.append(
                    f"{indent}        if (TethysGame::CreateUnit(_u, {mapid(w.get('unit_type', 'mapLynx'))}, "
                    f"MkXY({ix + 1} + (_i % {iw}), {iy + 1} + (_i / {iw})), {p}, {weapon}, 0)) "
                    f"{fg}.TakeUnit(_u);")
                lines.append(f"{indent}    }}")
                i += n
            if auto_attack:
                lines.extend(f"{indent}    {l}" for l in _wave_attack_lines(fg, geo))
            elif geo["has_staging"]:
                # Ohne Auto-Angriff: im Sammelbereich sammeln und warten
                lines.extend(f"{indent}    {l}" for l in _wave_staging_lines(fg, geo))
        else:
            # reinforce: Sollstaerke setzen, Nachschub anfordern
            total = 0
            for w in waves:
                wt = w.get("weapon_type") or "mapLaser"
                weapon = mapid(wt) if wt != "mapNone" else "mapNone"
                n = int(w.get("count", 1) or 1)
                total += n
                lines.append(
                    f"{indent}    {fg}.SetTargCount({mapid(w.get('unit_type', 'mapLynx'))}, {weapon}, {n});")
            src_var = ctx["group_vars"].get(getattr(action, "source_group_name", "") or "", None)
            if src_var:
                prio = max(1, int(getattr(action, "reinforce_priority", 1000) or 1000))
                lines.append(f"{indent}    {src_var}.RecordVehReinforceGroup({fg}, {prio});")
            else:
                lines.append(f"{indent}    // TODO sendAttackWave: ReinforceGroup "
                             f"'{getattr(action, 'source_group_name', '')}' not declared")
            if auto_attack or geo["has_staging"]:
                # Wenn voll: Angriff bzw. Sammelbereich. Das Polling macht der
                # missionsweite Reparatur-Timer; hier nur das armed-Flag setzen.
                # When full: attack resp. staging area. The mission-wide repair
                # timer does the polling; only set the armed flag here.
                armed_var = ctx.get("wave_action_vars", {}).get(id(action))
                if armed_var:
                    lines.append(f"{indent}    {armed_var} = true;")
                else:
                    lines.append(f"{indent}    // TODO sendAttackWave: armed flag not declared")
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
        rect = _rect(action.x, action.y, action.x2, action.y2)
        # FightGroup-Befehle
        if cmd == "attackArea":
            return [
                f"{indent}{{",
                f"{indent}    MAP_RECT _r = {rect};",
                f"{indent}    {gvar}.SetAttackType(mapAny);",
                f"{indent}    {gvar}.ClearGuarderdRects();",
                f"{indent}    {gvar}.AddGuardedRect(_r);",
                f"{indent}    {gvar}.DoGuardRect();",
                f"{indent}}}",
            ]
        if cmd == "attackEnemy":
            return [
                f"{indent}{gvar}.SetAttackType(mapAny);",
                f"{indent}{gvar}.DoAttackEnemy();",
            ]
        if cmd == "guardArea":
            return [
                f"{indent}{{",
                f"{indent}    MAP_RECT _r = {rect};",
                f"{indent}    {gvar}.ClearGuarderdRects();",
                f"{indent}    {gvar}.SetRect(_r);",
                f"{indent}    {gvar}.AddGuardedRect(_r);",
                f"{indent}    {gvar}.DoGuardRect();",
                f"{indent}}}",
            ]
        if cmd == "patrol":
            return _emit_patrol_route(indent, action, f"{gvar}")
        if cmd == "exitMap":
            return [f"{indent}{gvar}.DoExitMap();"]
        if cmd == "combineFireOn":
            return [f"{indent}{gvar}.SetCombineFire();"]
        if cmd == "combineFireOff":
            return [f"{indent}{gvar}.ClearCombineFire();"]
        # BuildingGroup-/ReinforceGroup-Befehle
        if cmd == "setBuildRect":
            return [
                f"{indent}{{",
                f"{indent}    MAP_RECT _r = {rect};",
                f"{indent}    {gvar}.SetRect(_r);",
                f"{indent}}}",
            ]
        if cmd in ("reinforceGroup", "unReinforceGroup"):
            tname = getattr(action, "target", "") or ""
            tvar = ctx.get("group_vars", {}).get(tname)
            if not tvar:
                return [f"{indent}// TODO groupCmd: target group '{tname}' not declared"]
            if cmd == "reinforceGroup":
                prio = max(1, int(getattr(action, "reinforce_priority", 1000) or 1000))
                return [f"{indent}{gvar}.RecordVehReinforceGroup({tvar}, {prio});"]
            return [f"{indent}{gvar}.UnRecordVehGroup({tvar});"]
        # Bearbeiten der Gruppenzusammensetzung / editing group composition
        if cmd == "setIdleRect":
            return [
                f"{indent}{{",
                f"{indent}    MAP_RECT _r = {rect};",
                f"{indent}    {gvar}.SetRect(_r);",
                f"{indent}}}",
            ]
        if cmd in ("addUnit", "removeUnit"):
            tname = getattr(action, "target", "") or ""
            tvar = _resolve_loop_ref(tname, depth) or ctx.get("unit_vars", {}).get(tname)
            if not tvar:
                return [f"{indent}// TODO groupCmd: unit '{tname}' not declared"]
            method = "TakeUnit" if cmd == "addUnit" else "RemoveUnit"
            return [f"{indent}{gvar}.{method}({tvar});"]
        # Befehle fuer alle Gruppentypen
        if cmd == "lightsOn":
            return [f"{indent}{gvar}.SetLights(1);"]
        if cmd == "lightsOff":
            return [f"{indent}{gvar}.SetLights(0);"]
        if cmd == "clearTargCount":
            return [f"{indent}{gvar}.ClearTargCount();"]
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
        simple = {
            "stop": "DoStop()", "selfDestruct": "DoSelfDestruct()",
            "remove": "DoDeath()", "idle": "DoIdle()", "unidle": "DoUnIdle()",
            "lightsOn": "DoSetLights(1)", "lightsOff": "DoSetLights(0)",
        }
        if cmd in simple:
            return [f"{indent}{uvar}.{simple[cmd]};"]
        if cmd == "move":
            return [f"{indent}{uvar}.DoMove({pos});"]
        if cmd == "attackGround":
            # UnitEx::DoAttack(LOCATION) -- Bodenziel / ground target (HFL)
            return [f"{indent}{uvar}.DoAttack({pos});"]
        if cmd == "patrol":
            # Die Engine kennt Patrouille nur als FightGroup-Konzept: die
            # Einheit wandert in eine kleine Einweg-FightGroup mit Route.
            # The engine only knows patrol as a FightGroup concept: the unit
            # goes into a small one-way FightGroup with a route.
            lines = [
                f"{indent}{{",
                f"{indent}    FightGroup _pfg = CreateFightGroup(Player[{uvar}.OwnerID()]);",
                f"{indent}    _pfg.TakeUnit({uvar});",
            ]
            lines.extend(_emit_patrol_route(indent + "    ", action, "_pfg", braces=False))
            lines.append(f"{indent}}}")
            return lines
        if cmd == "transfer":
            return [f"{indent}{uvar}.DoTransfer({int(action.player)});"]
        if cmd == "repair":
            tname = getattr(action, "target", "") or ""
            tvar = _resolve_loop_ref(tname, depth) or ctx.get("unit_vars", {}).get(tname)
            if not tvar:
                return [f"{indent}// TODO unitCmd repair: target unit '{tname}' not declared"]
            return [
                f'{indent}op2::log::linef("repair target id=%d owner=%d", {tvar}.unitID, {tvar}.OwnerID());',
                f"{indent}{uvar}.DoRepair({tvar});",
            ]
        return [f"{indent}// TODO unitCmd: unknown command '{cmd}'"]

    if k == "defendArea":
        # High-level: put the player's armed vehicles inside the rect into a
        # FightGroup that guards that rect.
        p = int(action.player)
        return [
            f"{indent}{{",
            f"{indent}    FightGroup _fg = CreateFightGroup(Player[{p}]);",
            f"{indent}    MAP_RECT _r = {_rect(action.x, action.y, action.x2, action.y2)};",
            f"{indent}    _fg.SetRect(_r);",
            f"{indent}    _fg.AddGuardedRect(_r);",
            f"{indent}    InRectEnumerator _e(_r);",
            f"{indent}    UnitEx _u;",
            f"{indent}    while (_e.GetNext(_u)) {{",
            f"{indent}        if (_u.OwnerID() == {p} && _u.IsVehicle() "
            f"&& _u.GetWeapon() != mapNone) _fg.TakeUnit(_u);",
            f"{indent}    }}",
            f"{indent}    _fg.DoGuardRect();",
            f"{indent}}}",
        ]

    if k == "repairBuildings":
        # High-level: collect the player's Repair Vehicles (and ConVecs as
        # fallback repairers) into a group guarding the rect -- guarding
        # repair units auto-repair damaged structures in their area.
        p = int(action.player)
        return [
            f"{indent}{{",
            f"{indent}    FightGroup _fg = CreateFightGroup(Player[{p}]);",
            f"{indent}    MAP_RECT _r = {_rect(action.x, action.y, action.x2, action.y2)};",
            f"{indent}    _fg.SetRect(_r);",
            f"{indent}    _fg.AddGuardedRect(_r);",
            f"{indent}    PlayerUnitEnum _e({p});",
            f"{indent}    UnitEx _u;",
            f"{indent}    while (_e.GetNext(_u)) {{",
            f"{indent}        if (_u.GetType() == mapRepairVehicle "
            f"|| _u.GetType() == mapConVec) _fg.TakeUnit(_u);",
            f"{indent}    }}",
            f"{indent}    _fg.DoGuardRect();",
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

    if k == "empMissile":
        # SetEMPMissile(launchTileX, launchTileY, sourcePlayerNum, destX, destY).
        # Startet auch ohne Spaceport ("may be launched from off screen");
        # feuert nur, wenn der Quellspieler Plymouth ist (Engine-Regel).
        # Launches even without a spaceport ("may be launched from off
        # screen"); only fires if the source player is Plymouth (engine rule).
        return [
            f"{indent}TethysGame::SetEMPMissile({_xypos(action.x, action.y)}, "
            f"{int(action.player)}, {_xypos(action.x2, action.y2)});"
        ]

    if k == "setMorale":
        mode = getattr(action, "morale_mode", "good") or "good"
        p = int(action.player)
        fn = {"great": "ForceMoraleGreat", "good": "ForceMoraleGood",
              "ok": "ForceMoraleOK", "poor": "ForceMoralePoor",
              "rotten": "ForceMoraleRotten", "free": "FreeMoraleLevel"}.get(mode, "ForceMoraleGood")
        if mode == "free" or p < 0:
            arg = "PlayerNum::PlayerAll" if p < 0 else str(p)
            return [f"{indent}TethysGame::{fn}({arg});"]
        # ForceMoraleX ist bei konkreter Spielernummer buggy -- der Aufruf
        # muss laut TethysGame.h-Kommentar ggf. DOPPELT erfolgen.
        # ForceMoraleX is buggy for a specific player number -- per the
        # TethysGame.h comment the call may need to happen TWICE.
        return [
            f"{indent}TethysGame::{fn}({p});",
            f"{indent}TethysGame::{fn}({p});  // Engine-Bug-Workaround: doppelt aufrufen",
        ]

    if k == "setMusic":
        songs = [s for s in (getattr(action, "songs", None) or []) if s]
        if not songs:
            return [f"{indent}// TODO setMusic: no songs selected"]
        rep = max(0, min(int(getattr(action, "repeat_start", 0) or 0), len(songs) - 1))
        return [
            f"{indent}{{",
            f"{indent}    static SongIds _songs[] = {{ {', '.join(songs)} }};",
            f"{indent}    TethysGame::SetMusicPlayList({len(songs)}, {rep}, _songs);",
            f"{indent}}}",
        ]

    if k == "lavaFlowAni":
        # OP2Helper Lava.h: Animations-/Freeze-Funktionen fuer den Vulkanhang.
        # OP2Helper Lava.h: animation/freeze helpers for the volcano side.
        d = getattr(action, "flow_dir", "S") or "S"
        d = d if d in ("S", "SW", "SE") else "S"
        fn = ("FreezeFlow" if getattr(action, "flow_freeze", False) else "AnimateFlow") + d
        return [f"{indent}{fn}({_xy(action.x, action.y)});"]

    if k == "modUnitStats":
        # HFL UnitInfo: Sheet-Werte eines Einheitentyps (pro Spieler) zur
        # Laufzeit aendern -- z.B. HitPoints, Kosten, Reichweiten.
        # HFL UnitInfo: change a unit type's sheet values (per player) at
        # runtime -- e.g. hit points, costs, ranges.
        mods = [m for m in (getattr(action, "stat_mods", None) or [])
                if m.get("stat")]
        if not mods:
            return [f"{indent}// TODO modUnitStats: no stats selected"]
        lines = [f"{indent}{{",
                 f"{indent}    UnitInfo _ui({mapid(action.unit_type)});"]
        for m in mods:
            stat = re.sub(r"[^A-Za-z0-9_]", "", str(m.get("stat", "")))
            lines.append(f"{indent}    _ui.Set{stat}({int(action.player)}, "
                         f"{_expr_or_int(m.get('value', 0))});")
        lines.append(f"{indent}}}")
        return lines

    return [f"{indent}// TODO unsupported action kind: {k}"]


def _patrol_locations(action) -> list[str]:
    """Wegpunkte einer Patrouille als LOCATION-Literale (max. 8).

    Patrol waypoints as LOCATION literals (max 8). Falls back to the two
    x,y / x2,y2 points when the patrol_points list is empty."""
    pts = list(getattr(action, "patrol_points", None) or [])[:8]
    if pts:
        return [_xy(int(p[0]), int(p[1])) for p in pts]
    return [_xy(action.x, action.y), _xy(action.x2, action.y2)]


def _emit_patrol_route(indent: str, action, gvar: str, *, braces: bool = True) -> list[str]:
    """PatrolRoute-Setup fuer eine FightGroup: Wegpunkt-Array (immer mit
    x = -1 terminiert, siehe Structs.h) + SetPatrolMode + DoPatrolOnly.

    WICHTIG: Die Engine BEHAELT den Pointer auf Route und Wegpunktliste
    (verifiziert in TitanAPI groups.hpp) -- beide muessen den Aufruf
    ueberleben, deshalb `static`. Jede Emissionsstelle hat ihren eigenen
    Block-Scope und damit ihre eigene statische Kopie.

    PatrolRoute setup for a FightGroup: waypoint array (always terminated
    with x = -1, see Structs.h) + SetPatrolMode + DoPatrolOnly.

    IMPORTANT: The engine KEEPS the pointer to the route and waypoint list
    (verified in TitanAPI groups.hpp) -- both must outlive the call, hence
    `static`. Each emission site has its own block scope and therefore its
    own static copy.
    """
    pts = _patrol_locations(action) + ["LOCATION(-1, -1)"]
    out = []
    if braces:
        out.append(f"{indent}{{")
        inner = indent + "    "
    else:
        inner = indent
    out.append(f"{inner}static LOCATION _wps[] = {{ {', '.join(pts)} }};")
    out.append(f"{inner}static PatrolRoute _route = {{ 0, _wps }};")
    out.append(f"{inner}{gvar}.SetPatrolMode(_route);")
    out.append(f"{inner}{gvar}.DoPatrolOnly();")
    if braces:
        out.append(f"{indent}}}")
    return out


def _wave_geometry(action) -> dict:
    """Gemeinsame Rechteck-/Spawn-Geometrie einer sendAttackWave-Aktion.

    Shared rect/spawn geometry of a sendAttackWave action (used both by the
    inline action body and by the mission-wide repair callback)."""
    ix, iy = int(getattr(action, "idle_x", 0)), int(getattr(action, "idle_y", 0))
    ix2, iy2 = int(getattr(action, "idle_x2", 0)), int(getattr(action, "idle_y2", 0))
    # Idle-Rect = Bau-/Spawnort; leer (alles 0) -> Sammelbereich verwenden.
    # Idle rect = build/spawn spot; empty (all zero) -> fall back to staging.
    if not any((ix, iy, ix2, iy2)):
        ix, iy, ix2, iy2 = int(action.x), int(action.y), int(action.x2), int(action.y2)
    has_staging = any((int(action.x), int(action.y), int(action.x2), int(action.y2))) \
        and (int(action.x), int(action.y), int(action.x2), int(action.y2)) != (ix, iy, ix2, iy2)
    return {
        "ix": ix, "iy": iy,
        "iw": max(1, abs(ix2 - ix) + 1),
        "idle_rect": _rect(ix, iy, ix2, iy2),
        "staging_rect": _rect(action.x, action.y, action.x2, action.y2),
        "attack_rect": _rect(getattr(action, "attack_x", 0), getattr(action, "attack_y", 0),
                              getattr(action, "attack_x2", 0), getattr(action, "attack_y2", 0)),
        "has_staging": has_staging,
    }


def _wave_attack_lines(fg: str, geo: dict) -> list[str]:
    return [
        f"MAP_RECT _ar = {geo['attack_rect']};",
        f"{fg}.SetAttackType(mapAny);",
        f"{fg}.ClearGuarderdRects();",
        f"{fg}.AddGuardedRect(_ar);",
        f"{fg}.DoGuardRect();",
    ]


def _wave_staging_lines(fg: str, geo: dict) -> list[str]:
    return [
        f"MAP_RECT _sr = {geo['staging_rect']};",
        f"{fg}.ClearGuarderdRects();",
        f"{fg}.AddGuardedRect(_sr);",
        f"{fg}.DoGuardRect();",
    ]


# forEach-Enumeratoren: Quelle -> (Prolog-Zeilen vor der while-Schleife,
# Enumerator-Variablenname, zusaetzliche Filter-Templates, Anzahl offener
# Klammern des Prologs).
# forEach enumerators: source -> (prologue lines before the while loop,
# enumerator variable name, extra filter templates, number of open braces
# the prologue contributes).
def _for_each_prologue(action, depth: int) -> tuple[list[str], str, list[str], int]:
    src = getattr(action, "enum_source", "rect") or "rect"
    p = int(getattr(action, "player", 0))
    ev = f"_e{depth}"
    if src == "player":
        return [f"PlayerUnitEnum {ev}({p});"], ev, [], 0
    if src == "playerVehicles":
        return [f"PlayerVehicleEnum {ev}({p});"], ev, [], 0
    if src == "playerBuildings":
        return [f"PlayerUnitEnum {ev}({p});"], ev, ["unit.IsBuilding()"], 0
    if src in ("all", "type"):
        # Alle Spieler durchlaufen (die Engine hat keinen globalen Enumerator).
        # Iterate all players (the engine has no global enumerator).
        pv = f"_pi{depth}"
        pro = [f"for (int {pv} = 0; {pv} < TethysGame::NoPlayers(); ++{pv}) {{",
               f"    PlayerUnitEnum {ev}({pv});"]
        filters = []
        if src == "type":
            ut = getattr(action, "unit_type", "") or "mapAny"
            if ut not in ("mapAny", "mapNone"):
                filters.append(f"unit.GetType() == {mapid(ut)}")
        return pro, ev, filters, 1
    # default: rect
    rect = _rect(action.x, action.y, action.x2, action.y2)
    return [f"MAP_RECT _rr{depth} = {rect};",
            f"InRectEnumerator {ev}(_rr{depth});"], ev, [], 0


def _emit_action(action: TriggerAction, indent: str, ctx: dict, depth: int = 0) -> list[str]:
    """Emit one action; recurses for kind == 'if' (then/else blocks).

    Ein Logik-Block (kind == 'if') kann eine Schleife tragen (loop_mode):
      count   -> for (int i = 0; i < N; ++i) { if (cond) {...} }
      forEach -> Enumerator-Schleife (PlayerUnitEnum/InRectEnumerator/...)
                 mit UnitEx-Laufvariable; <filter> if (cond) {...}
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
        extra_close = 0
        if loop_mode == "count":
            n = _expr_or_int(getattr(action, "loop_count", 1))
            out.append(f"{indent}for (int i = 0; i < {n}; ++i) {{")
            inner = indent + "    "
        elif loop_mode == "forEach":
            inner_depth = depth + 1
            var = _loop_var(inner_depth)
            src = getattr(action, "enum_source", "rect") or "rect"
            pro, ev, filters, pro_braces = _for_each_prologue(action, inner_depth)
            out.append(f"{indent}{{")
            for l in pro:
                out.append(f"{indent}    {l}")
            pro_pad = "    " * pro_braces
            out.append(f"{indent}    {pro_pad}UnitEx {var};")
            out.append(f"{indent}    {pro_pad}while ({ev}.GetNext({var})) {{")
            inner = indent + "        " + pro_pad
            extra_close = 1 + pro_braces
            filters = [f.replace("unit.", f"{var}.") for f in filters]
            ut = getattr(action, "unit_type", "") or ""
            if src != "type" and ut and ut not in ("mapAny", "mapNone"):
                filters.append(f"{var}.GetType() == {mapid(ut)}")
            if src in ("all", "type", "rect") and int(getattr(action, "player", 0)) >= 0:
                filters.append(f"{var}.OwnerID() == {int(action.player)}")
            if src != "rect" and any((int(action.x), int(action.y),
                                      int(action.x2), int(action.y2))):
                out.append(f"{inner}MAP_RECT _fr{inner_depth} = "
                           f"{_rect(action.x, action.y, action.x2, action.y2)};")
                out.append(f"{inner}LOCATION _l{inner_depth} = {var}.Location();")
                filters.append(f"_fr{inner_depth}.Check(_l{inner_depth})")
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
        if loop_mode == "count":
            out.append(f"{indent}}}")
        elif loop_mode == "forEach":
            # while + evtl. Spieler-for + umschliessender Block schliessen
            # close the while + optional player-for + enclosing block
            for j in range(extra_close, 0, -1):
                out.append(f"{indent}{'    ' * j}}}")
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
# Custom Triggers: emit the exported callback + a small creator helper.
# ---------------------------------------------------------------------------

def _emit_trigger_helper(t: TriggerDef, helper: str, ctx: dict) -> list[str]:
    """Emit the trigger's callback as an EXPORTED function plus a slim helper.

    `Export void <helper>_cb() { ...actions... }`  -- the callback body; the
    engine looks callbacks up BY EXPORTED NAME (also after a savegame load,
    so no registry bookkeeping is needed).
    `static void <helper>() { Create...Trigger(..., "<helper>_cb"); }`

    The helper is invoked from InitProc for triggers enabled at start, and
    from `createTrigger` actions at runtime for triggers created on demand.
    """
    one_shot = "1" if t.one_shot else "0"
    cmp_ = _compare(t.compare)
    cb_fn = f"{helper}_cb"
    ctx.setdefault("trigger_cb_names", {})[helper] = cb_fn

    lines: list[str] = []
    lines.append(f"// Trigger '{t.name}' (condition={t.condition})")

    # --- Callback als exportierte Funktion / callback as an exported function ---
    if t.condition in ("time", "buildingCount", "vehicleCount", "research",
                       "resource", "operational", "point", "rect",
                       "attacked", "damaged", "specialTarget"):
        # point/rect/attacked/damaged/specialTarget: die Engine prueft die
        # Bedingung selbst (native Trigger).
        # point/rect/attacked/damaged/specialTarget: the engine checks the
        # condition itself (native triggers).
        lines.append(f"Export void {cb_fn}() {{")
        lines.extend(_emit_action_list(t.actions, "    ", ctx))
        lines.append(f"}}")
    elif t.condition == "unitDied":
        # Kein API-Trigger auf "Einheit stirbt" (Coding 101 W6) -- Poll alle
        # 10 Ticks auf !IsLive(); der Trigger-Stub liegt in g_save und wird
        # nach dem ersten Feuern deaktiviert (one_shot).
        # No API trigger for "unit dies" (Coding 101 W6) -- poll !IsLive()
        # every 10 ticks; the trigger stub lives in g_save and is disabled
        # after the first fire (one_shot).
        uvar = ctx.get("unit_vars", {}).get((t.target_unit or "").strip())
        lines.append(f"Export void {cb_fn}() {{")
        if uvar:
            lines.append(f"    if ({uvar}.unitID == 0 || {uvar}.IsLive()) return;")
        else:
            lines.append(f"    return;  // TODO unitDied: unit '{t.target_unit}' not declared")
        lines.extend(_emit_action_list(t.actions, "    ", ctx))
        if t.one_shot:
            lines.append(f"    g_save.{helper}_self.Disable();")
        lines.append(f"}}")
    elif t.condition == "findUnit":
        # Pollt jede 10 Ticks (wiederholender TimeTrigger), prueft jeden
        # Eintrag der `unit_checks`-Liste auf "vorhanden & lebt". Sobald ALLE
        # Eintraege gleichzeitig ready sind, feuern die Aktionen.
        # Polls every 10 ticks (repeating time trigger), checks each entry of
        # the `unit_checks` list for "present & alive". Once ALL entries are
        # ready at the same time, the actions fire.
        checks = list(getattr(t, "unit_checks", None) or [])
        if not checks:
            lines.append(f"Export void {cb_fn}() {{}}  // findUnit ohne Eintraege")
            lines.append(f"static void {helper}() {{}}")
            return lines
        ctx.setdefault("trigger_self_vars", []).append(f"{helper}_self")
        lines.append(f"Export void {cb_fn}() {{")
        for i, c in enumerate(checks):
            lines.append(f"    UnitEx _u{i} = unitOnTile({_xy(c.x, c.y)});")
            lines.append(f"    bool _ready{i} = _u{i}.unitID != 0 && _u{i}.IsLive() "
                         f"&& _u{i}.GetType() == {mapid(c.unit_type)};")
        all_ready = " && ".join(f"_ready{i}" for i in range(len(checks)))
        lines.append(f"    if (!({all_ready})) return;")
        for line in _emit_action_list(t.actions, "    ", ctx):
            lines.append(line)
        if t.one_shot:
            lines.append(f"    g_save.{helper}_self.Disable();")
        lines.append(f"}}")
    else:
        lines.append(f"Export void {cb_fn}() {{}}  // TODO unsupported condition: {t.condition}")

    # --- Helper: erzeugt den Engine-Trigger / creates the engine trigger ---
    lines.append(f"static void {helper}() {{")
    if t.condition == "time":
        lines.append(f'    CreateTimeTrigger(1, {one_shot}, ({_expr_or_int(t.marks)}) * kTicksPerMark, "{cb_fn}");')
    elif t.condition == "buildingCount":
        lines.append(f'    CreateBuildingCountTrigger(1, {one_shot}, {int(t.player)}, '
                     f'{int(t.count)}, {cmp_}, "{cb_fn}");')
    elif t.condition == "vehicleCount":
        lines.append(f'    CreateVehicleCountTrigger(1, {one_shot}, {int(t.player)}, '
                     f'{int(t.count)}, {cmp_}, "{cb_fn}");')
    elif t.condition == "research":
        lines.append(f'    CreateResearchTrigger(1, {one_shot}, {int(t.tech_id)}, '
                     f'{int(t.player)}, "{cb_fn}");')
    elif t.condition == "resource":
        lines.append(f'    CreateResourceTrigger(1, {one_shot}, {_resource(t.resource)}, '
                     f'{int(t.amount)}, {int(t.player)}, {cmp_}, "{cb_fn}");')
    elif t.condition == "operational":
        lines.append(f'    CreateOperationalTrigger(1, {one_shot}, {int(t.player)}, '
                     f'{mapid(t.building)}, {int(t.count)}, {cmp_}, "{cb_fn}");')
    elif t.condition == "point":
        lines.append(f'    CreatePointTrigger(1, {one_shot}, {int(t.player)}, '
                     f'{_xypos(t.x, t.y)}, "{cb_fn}");')
    elif t.condition == "rect":
        lines.append(f'    CreateRectTrigger(1, {one_shot}, {int(t.player)}, '
                     f'{_xypos(t.x, t.y)}, {int(t.width)}, {int(t.height)}, "{cb_fn}");')
    elif t.condition in ("attacked", "damaged"):
        gvar = ctx.get("group_vars", {}).get((getattr(t, "group_name", "") or "").strip())
        if gvar:
            if t.condition == "attacked":
                lines.append(f'    CreateAttackedTrigger(1, {one_shot}, {gvar}, "{cb_fn}");')
            else:
                dmg = int(getattr(t, "damage_type", 3) or 3)
                lines.append(f'    CreateDamagedTrigger(1, {one_shot}, {gvar}, {dmg}, "{cb_fn}");')
        else:
            lines.append(f"    // TODO {t.condition}: group '{getattr(t, 'group_name', '')}' not declared")
    elif t.condition == "specialTarget":
        uvar = ctx.get("unit_vars", {}).get((getattr(t, "target_unit", "") or "").strip())
        if uvar:
            src = mapid(getattr(t, "source_unit_type", "mapScout") or "mapScout")
            lines.append(f'    CreateSpecialTarget(1, {one_shot}, {uvar}, {src}, "{cb_fn}");')
        else:
            lines.append(f"    // TODO specialTarget: unit '{getattr(t, 'target_unit', '')}' not declared")
    elif t.condition in ("findUnit", "unitDied"):
        lines.append(f'    g_save.{helper}_self = CreateTimeTrigger(1, 0, 10, "{cb_fn}");')
    else:
        lines.append(f"    // TODO unsupported trigger condition: {t.condition}")
    lines.append(f"}}")
    return lines


# ---------------------------------------------------------------------------
# Groups: building / reinforce / fight / mining.
# ---------------------------------------------------------------------------

def _emit_groups(mission: Mission, ctx: dict) -> list[str]:
    """Emit group creation + setup inside InitProc (variables live in g_save)."""
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
        lines.append(f"    {var} = CreateBuildingGroup(Player[{int(g.player)}]);")
        lines.append(f"    {{ MAP_RECT _r = {_rect(g.rect_x, g.rect_y, g.rect_x + g.rect_width, g.rect_y + g.rect_height)}; {var}.SetRect(_r); }}")
        lines.extend(_emit_take_units(mission, g, var, ctx, label="BuildingGroup"))
        # Sollstaerken fuer die Baufahrzeuge (klassisches W9-Rezept) -- sonst
        # ersetzt die Gruppe verlorene ConVecs/RoboMiner/Earthworker nicht.
        # Target counts for the builder vehicles (classic W9 recipe) --
        # otherwise the group does not replace lost ConVecs/miners/earthworkers.
        for (t, w, n) in _roster_targ_counts(mission, g):
            lines.append(f"    {var}.SetTargCount({t}, {w}, {n});")
        # Diagnose ins Log: 0 Einheiten => Positions-Uebernahme fehlgeschlagen.
        # Diagnostics to the log: 0 units => position take-over failed.
        lines.append(f'    op2::log::linef("InitProc: BuildingGroup \'{g.name}\' -> %d Einheiten", '
                     f"{var}.TotalUnitCount());")

    for g in reinforces:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = CreateBuildingGroup(Player[{int(g.player)}]);")
        # Vehicle-Factories (oder andere Builder-Einheiten) der ReinforceGroup
        # zuweisen, sonst hat sie keine Quelle fuer Verstaerkungen.
        lines.extend(_emit_take_units(mission, g, var, ctx, label="ReinforceGroup"))
        for t in (getattr(g, "targets", None) or []):
            target_var = ctx["group_vars"].get(t.group_name)
            if target_var:
                # Prioritaet 0 haengt das Spiel (siehe Groups.h) -- min. 1.
                lines.append(f"    {var}.RecordVehReinforceGroup({target_var}, "
                             f"{max(1, int(getattr(t, 'priority', 1000)))});")
            else:
                lines.append(f"    // TODO ReinforceGroup '{g.name}': target group "
                             f"'{t.group_name}' not found (check spelling/case)")

    for g in fights:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = CreateFightGroup(Player[{int(g.player)}]);")
        lines.append(f"    {{ MAP_RECT _r = {_rect(g.idle_x, g.idle_y, g.idle_x + g.idle_width, g.idle_y + g.idle_height)}; {var}.SetRect(_r); }}")
        lines.extend(_emit_take_units(mission, g, var, ctx, label="FightGroup"))

    for g in minings:
        var = ctx["group_vars"][g.name]
        lines.append(f"    {var} = CreateMiningGroup(Player[{int(g.player)}]);")
        # Kein SetRect() hier: der Abladebereich einer MiningGroup kommt
        # ausschliesslich ueber Setup()'s Bereichsargument -- das passiert je
        # Aktion (siehe "startMining" in _emit_action_body), nicht hier.
        # No SetRect() here: a MiningGroup's unload area only ever comes via
        # Setup()'s area argument -- that happens per action (see
        # "startMining" in _emit_action_body), not here at group creation.
        lines.extend(_emit_take_units(mission, g, var, ctx, label="MiningGroup"))

    return lines


def _roster_targ_counts(mission: Mission, group) -> list[tuple[str, str, int]]:
    """Sollstaerken aus dem Gruppen-Roster ableiten: je Fahrzeugtyp (+Waffe)
    die Anzahl der zugewiesenen Einheiten. Klassisches W9-Rezept
    (Construction.SetTargCount(mapConVec, mapNone, 3)) -- ohne Sollstaerke
    ersetzt die Gruppe verlorene Baufahrzeuge nicht.

    Derive target counts from the group's roster: per vehicle type (+weapon)
    the number of assigned units. Classic W9 recipe
    (Construction.SetTargCount(mapConVec, mapNone, 3)) -- without a target
    count the group does not replace lost builder vehicles.
    """
    uids = set(getattr(group, "unit_ids", None) or [])
    if not uids:
        return []
    counts: dict[tuple[str, str], int] = {}
    for u in (mission.units or []):
        if getattr(u, "uid", "") not in uids:
            continue
        t = _strip_map(u.unit_type)
        if t in _BUILDING_TYPES:
            continue  # nur Fahrzeuge / vehicles only
        weapon = mapid(u.cargo) if (u.cargo and u.cargo != "mapNone") else "mapNone"
        key = (mapid(u.unit_type), weapon)
        counts[key] = counts.get(key, 0) + 1
    return [(t, w, n) for (t, w), n in sorted(counts.items())]


def _roster_building_entries(mission: Mission, group) -> list[tuple[str, int, int]]:
    """Roster-GEBAEUDE einer Gruppe als (map_id, editor_x, editor_y).

    Nur Gebaeude: der Selbstheil-Callback nimmt zerstoerte + von der Engine
    an derselben Stelle wieder errichtete Gebaeude erneut auf; verlorene
    FAHRZEUGE ersetzt stattdessen die Sollstaerke (SetTargCount +
    ReinforceGroup). mapRareOreMine wird wie im BaseLayout als
    mapCommonOreMine behandelt (Rare-Ore-Mine-Gotcha).

    A group's roster BUILDINGS as (map_id, editor_x, editor_y). Buildings
    only: the self-heal callback re-takes destroyed buildings the engine
    rebuilt in place; lost VEHICLES are replaced via target counts
    (SetTargCount + ReinforceGroup) instead. mapRareOreMine is treated as
    mapCommonOreMine, same as in the base layout (rare ore mine gotcha).
    """
    uids = list(getattr(group, "unit_ids", None) or [])
    if not uids:
        return []
    by_uid = {getattr(u, "uid", ""): u for u in (mission.units or [])
              if getattr(u, "uid", "")}
    out: list[tuple[str, int, int]] = []
    for uid in uids:
        u = by_uid.get(uid)
        if u is None:
            continue
        if _strip_map(u.unit_type) not in _BUILDING_TYPES:
            continue
        btype = mapid(u.unit_type)
        if btype == "mapRareOreMine":
            btype = "mapCommonOreMine"
        out.append((btype, int(u.x), int(u.y)))
    return out


def _repair_building_take_lines(group, var: str,
                                entries: list[tuple[str, int, int]]) -> list[str]:
    """Selbstheil-Bloecke fuer Roster-Gebaeude: je Gebaeude eine
    PlayerBuildingEnum-Suche (typgenau, engine-seitige Gebaeudeliste) mit
    exaktem Positionsvergleich -- die Engine baut Gebaeude immer exakt an
    ihrer alten Position wieder auf, und Location() liefert die
    CreateUnit-Koordinate 1:1 zurueck. Dazu Mitglieds-Guard --
    wiederholtes TakeUnit wuerde den Bau-Zustand der Gruppen-KI jede Mark
    zuruecksetzen.

    Self-heal blocks for roster buildings: one PlayerBuildingEnum search
    per building (type-exact, engine-side building list) with an exact
    position match -- the engine always rebuilds buildings at their exact
    old spot, and Location() returns the CreateUnit coordinate 1:1. Plus
    a membership guard -- repeated TakeUnit would reset the group AI's
    build state every mark.
    """
    out: list[str] = []
    for (btype, x, y) in entries:
        out += [
            f"{{",
            f"    PlayerBuildingEnum _e({int(group.player)}, {btype});",
            f"    UnitEx _u;",
            f"    LOCATION _a = {_xy(x, y)};",
            f"    while (_e.GetNext(_u)) {{",
            f"        LOCATION _loc = _u.Location();",
            f"        if (!(_loc == _a)) continue;",
            f"        bool _member = false;",
            f"        GroupEnumerator _ge({var});",
            f"        UnitEx _m;",
            f"        while (_ge.GetNext(_m)) {{",
            f"            if (_m.unitID == _u.unitID) {{ _member = true; break; }}",
            f"        }}",
            f"        if (!_member) {{",
            f"            {var}.TakeUnit(_u);",
            f'            op2::log::linef("Repair: {btype} (Einheit %d) -> Gruppe wieder aufgenommen", _u.unitID);',
            f"        }}",
            f"    }}",
            f"}}",
        ]
    return out


def _emit_take_units(mission: Mission, group, var: str, ctx: dict, *, label: str) -> list[str]:
    """Roster-Einheiten der Group EINMALIG (InitProc) per DIREKTEM Handle
    zuweisen -- die Handles wurden in _emit_base_layout von CreateUnit
    befuellt (klassisches Muster, exakt wie Sirbombers W9-Beispiel).

    Assign the group's roster units ONCE (InitProc) via DIRECT handle --
    the handles were filled by CreateUnit in _emit_base_layout (classic
    pattern, exactly like Sirbomber's W9 example).
    """
    uids = [u for u in (getattr(group, "unit_ids", None) or []) if u]
    handle_vars = ctx.get("uid_handle_vars", {})
    out: list[str] = []
    for uid in uids:
        hvar = handle_vars.get(uid)
        if not hvar:
            continue
        if not out:
            out.append(f"    // Einheiten der {label} '{group.name}' zuweisen")
        out.append(f"    if ({hvar}.unitID != 0) {var}.TakeUnit({hvar});")
    return out


def _mining_link_lines(var: str, spec, mine_expr: str, smelter_expr: str, n) -> list[str]:
    """Existenz-Check + Setup + SetTargCount, gegeben bereits aufgeloeste
    Mine-/Smelter-Ausdruecke (kein Einrueck-Praefix).

    Existence check + Setup + SetTargCount, given already-resolved
    mine/smelter expressions (no indent prefix)."""
    area = _rect(spec.idle_x, spec.idle_y,
                 spec.idle_x + spec.idle_width, spec.idle_y + spec.idle_height)
    return [
        f"UnitEx _mine = {mine_expr};",
        f"UnitEx _smelter = {smelter_expr};",
        f"if (_mine.unitID != 0 && _smelter.unitID != 0) {{",
        f"    MAP_RECT _area = {area};",
        f"    {var}.Setup(_mine, _smelter, _area);",
        f"    {var}.SetTargCount(mapCargoTruck, mapNone, {n});",
        f"}}",
    ]


def _walk_actions(actions):
    """Alle Aktionen inkl. verschachtelter then/else-Zweige durchlaufen.

    Walk all actions including nested then/else branches."""
    for a in (actions or []):
        yield a
        yield from _walk_actions(getattr(a, "then_actions", None))
        yield from _walk_actions(getattr(a, "else_actions", None))


def _emit_group_repair_body(mission: Mission, ctx: dict) -> list[str]:
    """Der Rumpf des missionsweiten wiederkehrenden Reparatur-Callbacks:
    zerstoerte und von der Engine an derselben Stelle wieder errichtete
    Gebaeude automatisch erneut in ihre Gruppe aufnehmen, armed
    MiningGroup-Verknuepfungen herstellen, armed assignToGroup-Zuweisungen
    pollen und volle Verstaerkungswellen losschicken. Liefert eine leere
    Liste, wenn es nichts zu pruefen gibt (dann wird auch kein Timer
    registriert).

    The body of the mission-wide recurring repair callback: automatically
    re-take destroyed-and-rebuilt (same position, by the engine) buildings
    into their group, establish armed MiningGroup links, poll armed
    assignToGroup assignments, and launch full reinforcement waves. Returns
    an empty list if there is nothing to check (then no timer is registered
    either).
    """
    body: list[str] = []

    # WICHTIG: alles hier laeuft jede Mark und MUSS idempotent sein --
    # wiederholtes TakeUnit/Setup setzt den Arbeitszustand der Gruppen-KI
    # zurueck (die Gruppe baut/faehrt dann nie fertig).
    # IMPORTANT: everything here runs every mark and MUST be idempotent --
    # repeated TakeUnit/Setup resets the group AI's work state (the group
    # then never finishes building/hauling).
    for attr in ("building_groups", "reinforce_groups", "mining_groups"):
        for g in (getattr(mission, attr, None) or []):
            var = ctx["group_vars"][g.name]
            entries = _roster_building_entries(mission, g)
            if entries:
                body.extend(_repair_building_take_lines(g, var, entries))

    for action, armed_var in ctx.get("mining_actions", []):
        var = ctx["group_vars"].get(action.group_name, None)
        spec = ctx.get("mining_group_specs", {}).get(action.group_name)
        if not var or spec is None:
            continue
        ids_var = ctx.get("mining_ids_vars", {}).get(id(action))
        mine_ref = getattr(action, "mine_ref", "") or ""
        smelter_ref = getattr(action, "smelter_ref", "") or ""
        mine_expr = ((ctx.get("unit_vars", {}).get(mine_ref) if mine_ref else None)
                     or f"unitOnTile({_xy(action.x, action.y)})")
        smelter_expr = ((ctx.get("unit_vars", {}).get(smelter_ref) if smelter_ref else None)
                        or f"unitOnTile({_xy(action.x2, action.y2)})")
        n = _expr_or_int(action.target_count)
        area = _rect(spec.idle_x, spec.idle_y,
                     spec.idle_x + spec.idle_width, spec.idle_y + spec.idle_height)
        body.append(f"if ({armed_var}) {{")
        body.append(f"    UnitEx _mine = {mine_expr};")
        body.append(f"    UnitEx _smelter = {smelter_expr};")
        # Setup nur beim ERSTEN Mal bzw. wenn Mine/Smelter neue Einheiten
        # sind (nach Zerstoerung + Wiederaufbau) -- sonst wuerde die
        # Truck-Route jede Mark neu gestartet.
        # Run Setup only the FIRST time resp. when mine/smelter are new
        # units (after destruction + rebuild) -- otherwise the truck route
        # would restart every mark.
        body.append(f"    if (_mine.unitID != 0 && _smelter.unitID != 0 &&")
        body.append(f"        (_mine.unitID != {ids_var}[0] || _smelter.unitID != {ids_var}[1])) {{")
        body.append(f"        MAP_RECT _area = {area};")
        body.append(f"        {var}.Setup(_mine, _smelter, _area);")
        body.append(f"        {var}.SetTargCount(mapCargoTruck, mapNone, {n});")
        body.append(f"        {ids_var}[0] = _mine.unitID;")
        body.append(f"        {ids_var}[1] = _smelter.unitID;")
        body.append(f"    }}")
        body.append(f"}}")

    for action, armed_var in ctx.get("assign_actions", []):
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            continue
        body.append(f"if ({armed_var}) {{")
        body.append(f"    UnitEx _b = unitOnTile({_xy(action.x, action.y)});")
        body.append(f"    if (_b.unitID != 0 && _b.GetType() == {mapid(action.building_type)}) {{")
        body.append(f"        bool _member = false;")
        body.append(f"        GroupEnumerator _ge({var});")
        body.append(f"        UnitEx _m;")
        body.append(f"        while (_ge.GetNext(_m)) {{")
        body.append(f"            if (_m.unitID == _b.unitID) {{ _member = true; break; }}")
        body.append(f"        }}")
        body.append(f"        if (!_member) {var}.TakeUnit(_b);")
        body.append(f"    }}")
        body.append(f"}}")

    for action, armed_var, launched_var in ctx.get("wave_actions", []):
        fg = ctx["group_vars"].get(getattr(action, "group_var_name", "") or "")
        if not fg:
            continue
        waves = list(getattr(action, "wave_units", None) or [])
        if not waves:
            waves = [{"count": action.target_count}]
        total = sum(int(w.get("count", 1) or 1) for w in waves)
        geo = _wave_geometry(action)
        auto_attack = bool(getattr(action, "now", False))
        launch = _wave_attack_lines(fg, geo) if auto_attack else _wave_staging_lines(fg, geo)
        body.append(f"if ({armed_var} && !{launched_var} && {fg}.TotalUnitCount() >= {total}) {{")
        body.append(f"    {launched_var} = true;")
        body.extend(f"    {line}" for line in launch)
        if auto_attack:
            # Sirbomber-Muster (Coding 101 W10): sobald die Welle angreift,
            # den Nachschub kappen -- sonst produziert die ReinforceGroup
            # endlos Einzel-Einheiten, die der kaempfenden Gruppe direkt in
            # die Spielerbasis hinterherlaufen.
            # Sirbomber pattern (Coding 101 W10): once the wave attacks, cut
            # the supply -- otherwise the ReinforceGroup endlessly produces
            # single units that trail the fighting group straight into the
            # player's base.
            src_var = ctx["group_vars"].get(getattr(action, "source_group_name", "") or "")
            if src_var:
                body.append(f"    {src_var}.UnRecordVehGroup({fg});")
            body.append(f"    {fg}.ClearTargCount();")
        body.append(f"}}")

    return body


def _build_codegen_context(mission: Mission) -> dict:
    """Collect names -> C++ variable / helper symbols so emitters can cross-reference."""
    ctx: dict = {
        "trigger_helpers": {},        # trigger name -> first-match helper (for createTrigger)
        "trigger_helpers_list": [],   # per-index unique helper names
        "group_vars": {},             # group name   -> "<g_n>"
        "group_class": {},            # group name   -> C++ class (BuildingGroup/FightGroup/MiningGroup)
        "trigger_self_vars": [],      # findUnit trigger handles kept in g_save
    }
    for i, t in enumerate(mission.triggers or []):
        helper = f"_trigger_{i}_{_ident(t.name)}"
        ctx["trigger_helpers_list"].append(helper)
        if t.name not in ctx["trigger_helpers"]:
            ctx["trigger_helpers"][t.name] = helper
    idx = 0
    for g in (getattr(mission, "building_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
        ctx["group_class"][g.name] = "BuildingGroup"
    for g in (getattr(mission, "reinforce_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
        ctx["group_class"][g.name] = "BuildingGroup"
    for g in (getattr(mission, "fight_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
        ctx["group_class"][g.name] = "FightGroup"
    for g in (getattr(mission, "mining_groups", None) or []):
        ctx["group_vars"][g.name] = f"_grp_{idx}_{_ident(g.name)}"; idx += 1
        ctx["group_class"][g.name] = "MiningGroup"
    # Nachschlage-Dict Name -> MiningGroupSpec: _emit_action_body bekommt nur
    # ctx (nie mission) durchgereicht, braucht fuer "startMining" aber die
    # Idle-Rect-Geometrie der referenzierten Gruppe.
    # Name -> MiningGroupSpec lookup: _emit_action_body only ever receives
    # ctx (never mission), but "startMining" needs the referenced group's
    # idle-rect geometry.
    ctx["mining_group_specs"] = {g.name: g for g in (getattr(mission, "mining_groups", None) or [])}
    # Aktionen, die beim Ausfuehren nur ein "armed"-Flag setzen; die
    # eigentliche (wiederholbare) Arbeit passiert zentral im missionsweiten
    # Reparatur-Callback (_emit_group_repair_body). Jede Aktion braucht dafuer
    # ein eigenes, stabiles Flag -- id(action) als Schluessel, da
    # TriggerAction (dataclass) keinen stabilen Namen/Hash hat.
    # Actions that only set an "armed" flag when they run; the actual
    # (repeatable) work happens centrally in the mission-wide repair callback
    # (_emit_group_repair_body). Each action needs its own stable flag --
    # id(action) as the key, since TriggerAction (a dataclass) has no stable
    # name/hash.
    #
    # Schleifenreferenzen ("<loop>"/"<loop:outer>") bleiben bei startMining
    # ausgeschlossen -- die Schleifenvariable ist nur innerhalb ihrer
    # Iteration gueltig. Muss mit der gleichen Pruefung in
    # _emit_action_body("startMining") synchron bleiben.
    # Loop references ("<loop>"/"<loop:outer>") stay excluded for startMining
    # -- the loop variable is only valid within its own iteration. Must stay
    # in sync with the same check in _emit_action_body("startMining").
    ctx["mining_action_vars"] = {}
    ctx["mining_ids_vars"] = {}
    ctx["mining_actions"] = []
    ctx["assign_action_vars"] = {}
    ctx["assign_actions"] = []
    ctx["wave_action_vars"] = {}
    ctx["wave_actions"] = []
    mining_idx = 0
    assign_idx = 0
    wave_idx = 0
    for t in (mission.triggers or []):
        for a in _walk_actions(t.actions):
            if a.kind == "startMining":
                mine_ref = getattr(a, "mine_ref", "") or ""
                smelter_ref = getattr(a, "smelter_ref", "") or ""
                if mine_ref in ("<loop>", "<loop:outer>") or smelter_ref in ("<loop>", "<loop:outer>"):
                    continue
                armed_var = f"_mining_armed_{mining_idx}"
                ctx["mining_action_vars"][id(a)] = armed_var
                ctx["mining_ids_vars"][id(a)] = f"_mining_ids_{mining_idx}"
                ctx["mining_actions"].append((a, armed_var))
                mining_idx += 1
            elif a.kind == "assignToGroup":
                armed_var = f"_assign_armed_{assign_idx}"
                ctx["assign_action_vars"][id(a)] = armed_var
                ctx["assign_actions"].append((a, armed_var))
                assign_idx += 1
            elif a.kind == "sendAttackWave":
                mode = getattr(a, "spawn_mode", "spawn") or "spawn"
                if mode == "spawn":
                    continue
                geo = _wave_geometry(a)
                if not (bool(getattr(a, "now", False)) or geo["has_staging"]):
                    continue
                armed_var = f"_wave_armed_{wave_idx}"
                launched_var = f"_wave_launched_{wave_idx}"
                ctx["wave_action_vars"][id(a)] = armed_var
                ctx["wave_actions"].append((a, armed_var, launched_var))
                wave_idx += 1
    # Benannte platzierte Einheiten: UnitEx-Handles in g_save fuer unitCmd.
    # Named placed units: UnitEx handles in g_save for unitCmd actions.
    ctx["unit_vars"] = {}
    ctx["unit_vars_by_uid"] = {}
    for u in (mission.units or []):
        name = (getattr(u, "unit_name", "") or "").strip()
        if name and name not in ctx["unit_vars"]:
            var = f"_unit_{_ident(name)}"
            ctx["unit_vars"][name] = var
            if getattr(u, "uid", ""):
                ctx["unit_vars_by_uid"][u.uid] = var
    # uid -> Handle-Variable fuer ALLE spaeter referenzierten Einheiten:
    # benannte Einheiten (g_save-Var) + Gruppen-Roster (_boot_N, file-scope).
    # Sie werden in _emit_base_layout DIREKT per CreateUnit befuellt --
    # klassisches Muster, keine Positions-Enumeration in InitProc.
    # uid -> handle variable for ALL units referenced later: named units
    # (g_save var) + group rosters (_boot_N, file scope). They are filled
    # DIRECTLY by CreateUnit in _emit_base_layout -- classic pattern, no
    # position enumeration in InitProc.
    ctx["uid_handle_vars"] = dict(ctx["unit_vars_by_uid"])
    ctx["boot_handle_vars"] = []
    boot_idx = 0
    for attr in ("building_groups", "reinforce_groups", "fight_groups", "mining_groups"):
        for g in (getattr(mission, attr, None) or []):
            for uid in (getattr(g, "unit_ids", None) or []):
                if uid and uid not in ctx["uid_handle_vars"]:
                    var = f"_boot_{boot_idx}"
                    ctx["uid_handle_vars"][uid] = var
                    ctx["boot_handle_vars"].append(var)
                    boot_idx += 1
    return ctx


def generate_levelmain(mission: Mission) -> str:
    """Emit the full `mission.cpp` for `mission`.

    The output is a single self-contained translation unit built against the
    classic OP2MissionSDK (Outpost2DLL + OP2Helper + HFL). Folder writers in
    mission_project.write_mission_folder detect this output (it starts with a
    `//` comment and contains `Outpost2DLL.h`) and prefer it over the static
    template fallback.
    """
    out: list[str] = []
    add = out.append
    ctx = _build_codegen_context(mission)

    add(f"// mission.cpp -- generated from the editor model for: {mission.name}")
    add("// Built against OP2MissionSDK (Outpost2DLL + OP2Helper + HFL).")
    add("// https://github.com/OutpostUniverse/OP2MissionSDK")
    add("")
    add("#include <Outpost2DLL/Outpost2DLL.h>")
    add("#include <OP2Helper/OP2Helper.h>")
    add("#include <HFL/Source/HFL.h>")
    add('#include "op2_log.hpp"')
    add('#include "op2_crash.hpp"')
    add("")

    if getattr(mission, "world_map", False):
        add("// World-/Wraparound-Karte (512 Tiles breit): Engine-Offset ist -1/-1")
        add("// statt +31/-1 -- die OP2Helper-Makros werden passend umdefiniert.")
        add("// World/wraparound map (512 tiles wide): engine offset is -1/-1")
        add("// instead of +31/-1 -- redefine the OP2Helper macros accordingly.")
        add("#undef MkXY")
        add("#undef MkRect")
        add("#undef XYPos")
        add("#undef RectPos")
        add("#define MkXY(x,y) (LOCATION((x)-1, (y)-1))")
        add("#define MkRect(x1,y1,x2,y2) (MAP_RECT(LOCATION((x1)-1,(y1)-1), LOCATION((x2)-1,(y2)-1)))")
        add("#define XYPos(x,y) (x)-1,(y)-1")
        add("#define RectPos(x1,y1,x2,y2) (x1)-1,(y1)-1,(x2)-1,(y2)-1")
        add("")

    # 1 Mark = 100 Ticks (Engine-Konstante; CreateTimeTrigger rechnet in Ticks).
    # 1 mark = 100 ticks (engine constant; CreateTimeTrigger counts in ticks).
    add("static const int kTicksPerMark = 100;")
    add("")

    # Difficulty constants (always emitted so ExprEdit expressions compile).
    # `diff` wird in InitProc gesetzt UND in AIProc nachgefuehrt, damit der
    # Wert auch nach einem Spielstand-Load stimmt (InitProc laeuft dann nicht).
    # `diff` is set in InitProc AND refreshed in AIProc so the value is also
    # correct after a savegame load (InitProc does not run then).
    diff = getattr(mission, "difficulty", None)
    hard   = diff.hard   if diff else 13
    normal = diff.normal if diff else 10
    easy   = diff.easy   if diff else 5
    add(f"static const int kDiff[] = {{{easy}, {normal}, {hard}}};")
    add(f"static int diff = {normal};")
    add("")
    add("static int randBetween(int minValue, int maxValue) {")
    add("    if (maxValue < minValue) { int _t = minValue; minValue = maxValue; maxValue = _t; }")
    add("    return minValue + TethysGame::GetRand(maxValue - minValue + 1);")
    add("}")
    add("")
    add("// Erste Einheit auf einer Kachel (LOCATION in Engine-Koordinaten, MkXY).")
    add("// First unit on a tile (LOCATION in engine coordinates, MkXY).")
    add("static UnitEx unitOnTile(LOCATION where) {")
    add("    LocationEnumerator _e(where);")
    add("    UnitEx _u;")
    add("    if (_e.GetNext(_u)) return _u;")
    add("    return UnitEx();")
    add("}")
    add("")
    add("// Einheit eines Typs/Spielers auf einer Kachel (fuer Fahrzeug-Capture).")
    add("// Unit of a type/player on a tile (for vehicle capture).")
    add("static UnitEx findUnitAt(LOCATION where, map_id type, int owner) {")
    add("    LocationEnumerator _e(where);")
    add("    UnitEx _u;")
    add("    while (_e.GetNext(_u)) {")
    add("        if (_u.GetType() == type && _u.OwnerID() == owner) return _u;")
    add("    }")
    add("    return UnitEx();")
    add("}")
    add("")
    add("static int countUnitsOfType(int playerNum, map_id type) {")
    add("    int _n = 0;")
    add("    PlayerUnitEnum _e(playerNum);")
    add("    UnitEx _u;")
    add("    while (_e.GetNext(_u)) if (_u.GetType() == type) ++_n;")
    add("    return _n;")
    add("}")
    add("")

    # ------------------------------------------------------------------
    # Save-Struktur: ALLES, was ein Spielstand-Load ueberleben muss, liegt
    # in EINEM struct, das ueber ExportSaveLoadData() mitgespeichert und beim
    # Laden von der Engine byte-genau restauriert wird: Missionsvariablen,
    # Group-/Unit-/Trigger-Stubs (jeweils nur ein Engine-Index) und die
    # armed-Flags. OP2 ruft beim Laden eines Spielstands InitProc NICHT
    # erneut auf; Trigger-Callbacks loest die Engine ueber den exportierten
    # Funktionsnamen selbst wieder auf.
    #
    # Save struct: EVERYTHING that must survive a savegame load lives in ONE
    # struct saved via ExportSaveLoadData(): mission variables,
    # group/unit/trigger stubs (each just an engine index) and the armed
    # flags. OP2 does NOT call InitProc again when loading a saved game;
    # the engine re-resolves trigger callbacks via the exported function
    # name on its own.
    # ------------------------------------------------------------------
    variables = getattr(mission, "variables", None) or []
    group_specs = (getattr(mission, "building_groups", None) or []) \
        + (getattr(mission, "reinforce_groups", None) or []) \
        + (getattr(mission, "fight_groups", None) or []) \
        + (getattr(mission, "mining_groups", None) or [])
    add("struct MissionSave {")
    for v in variables:
        init = int(v.initial_value) if v.initial_value is not None else 0
        if v.var_type == "bool":
            add(f"    bool {v.name} = {'true' if init else 'false'};")
        else:
            add(f"    int {v.name} = {init};")
    for armed_var in ctx.get("mining_action_vars", {}).values():
        add(f"    bool {armed_var} = false;")
    for ids_var in ctx.get("mining_ids_vars", {}).values():
        # unitIDs der aktuell verknuepften Mine/Smelter -- Setup laeuft nur
        # bei Aenderung erneut (siehe _emit_group_repair_body).
        # unitIDs of the currently linked mine/smelter -- Setup only re-runs
        # on change (see _emit_group_repair_body).
        add(f"    int {ids_var}[2] = {{ 0, 0 }};")
    for armed_var in ctx.get("assign_action_vars", {}).values():
        add(f"    bool {armed_var} = false;")
    for (_a, armed_var, launched_var) in ctx.get("wave_actions", []):
        add(f"    bool {armed_var} = false;")
        add(f"    bool {launched_var} = false;")
    for g in group_specs:
        add(f"    {ctx['group_class'][g.name]} {ctx['group_vars'][g.name]};")
    for var in ctx["unit_vars"].values():
        add(f"    UnitEx {var};")
    # findUnit-/unitDied-Trigger-Handles (zum Disable nach dem ersten Feuern)
    # findUnit/unitDied trigger handles (to Disable after the first fire)
    for i, t in enumerate(mission.triggers or []):
        if t.condition == "findUnit" and list(getattr(t, "unit_checks", None) or []):
            add(f"    Trigger {ctx['trigger_helpers_list'][i]}_self;")
        elif t.condition == "unitDied":
            add(f"    Trigger {ctx['trigger_helpers_list'][i]}_self;")
    add("};")
    add("static MissionSave g_save;")
    add("")
    # Referenzen, damit Ausdruecke/Aktionen die gewohnten Namen benutzen koennen.
    # References so expressions/actions keep using the familiar names.
    for v in variables:
        ctype = "bool" if v.var_type == "bool" else "int"
        add(f"static {ctype}& {v.name} = g_save.{v.name};")
    for armed_var in ctx.get("mining_action_vars", {}).values():
        add(f"static bool& {armed_var} = g_save.{armed_var};")
    for ids_var in ctx.get("mining_ids_vars", {}).values():
        add(f"static int (&{ids_var})[2] = g_save.{ids_var};")
    for armed_var in ctx.get("assign_action_vars", {}).values():
        add(f"static bool& {armed_var} = g_save.{armed_var};")
    for (_a, armed_var, launched_var) in ctx.get("wave_actions", []):
        add(f"static bool& {armed_var} = g_save.{armed_var};")
        add(f"static bool& {launched_var} = g_save.{launched_var};")
    for g in group_specs:
        var = ctx["group_vars"][g.name]
        add(f"static {ctx['group_class'][g.name]}& {var} = g_save.{var};")
    for var in ctx["unit_vars"].values():
        add(f"static UnitEx& {var} = g_save.{var};")
    add("")

    # Handles fuer Gruppen-Roster-Einheiten ohne Namen: werden im BaseLayout
    # direkt von CreateUnit befuellt und in InitProc per TakeUnit uebergeben.
    # Nur fuer InitProc gebraucht -> kein g_save noetig.
    # Handles for unnamed group roster units: filled directly by CreateUnit
    # in the base layout and handed over via TakeUnit in InitProc. Only
    # needed during InitProc -> no g_save required.
    for var in ctx.get("boot_handle_vars", []):
        add(f"static UnitEx {var};")
    if ctx.get("boot_handle_vars"):
        add("")

    # No-Op-Callback fuer Trigger, die nur als Sieg-/Niederlagen-Bedingung
    # dienen (klassische Konvention, wird auch von OP2Helper referenziert).
    # No-op callback for triggers that only serve as victory/defeat
    # conditions (classic convention, also referenced by OP2Helper).
    add("Export void NoResponseToTrigger() {}")
    add("")

    # Forward declarations for trigger helpers (so a `createTrigger` action
    # earlier in the file can invoke a trigger declared further down).
    for helper in ctx["trigger_helpers_list"]:
        add(f"static void {helper}();")
    if mission.triggers:
        add("")

    # --- Exports (Level-Metadaten) ---
    num_players = max(1, len(mission.players or []) or 1)
    tech_tree = (getattr(mission, "tech_tree", None) or "MULTITEK.TXT").strip() or "MULTITEK.TXT"
    # Multiplayer-Missionen mit KI-Spielern brauchen DescBlockEx.aiPlayerCount
    # (sonst kennt OP2 die KI-Slots nicht); bei Colony/Kampagne bleibt 0.
    # Multiplayer missions with AI players need DescBlockEx.aiPlayerCount
    # (otherwise OP2 does not know about the AI slots); Colony/campaign: 0.
    num_ai = 0
    if mission.type not in (MissionType.Colony, MissionType.AutoDemo, MissionType.Tutorial):
        num_ai = sum(1 for p in (mission.players or []) if not p.is_human)
        # AIModDesc.numPlayers zaehlt in Multiplayer nur MENSCHLICHE Spieler
        # (max 6); KI-Slots meldet DescBlockEx (Coding 101 W11).
        # In multiplayer AIModDesc.numPlayers counts HUMAN players only
        # (max 6); AI slots are reported via DescBlockEx (Coding 101 W11).
        num_players = max(1, num_players - num_ai)
    add(f"ExportLevelDetailsFull({_cpp_string(mission.name)}, {_cpp_string(mission.map)}, "
        f"{_cpp_string(tech_tree)}, {_mission_type_literal(mission.type)}, {num_players}, 12, 0)")
    add(f"Export const AIModDescEx DescBlockEx = {{ {num_ai} }};")
    add("")

    # --- InitProc ---
    add("static void initProc() {")
    add('    op2::log::line("InitProc: starting");')
    add("    if (HFLInit() != HFLLOADED) {")
    add('        op2::log::line("InitProc: HFLInit FAILED");')
    add("    }")
    add("    diff = kDiff[Player[0].Difficulty()];")
    add("")

    # Players
    for idx, p in enumerate(mission.players or []):
        for line in _emit_player_setup(idx, p):
            add(line)
        add("")

    # Base layout. Benannte Einheiten + Gruppen-Roster-Einheiten werden
    # darin DIREKT in ihre Handles erzeugt (kein findUnitAt/Enumeration --
    # klassisches Muster, verlaesslich auch waehrend InitProc).
    # Base layout. Named units + group roster units are created DIRECTLY
    # into their handles inside it (no findUnitAt/enumeration -- classic
    # pattern, reliable during InitProc too).
    for line in _emit_base_layout(mission, ctx):
        add(line)

    # Groups (declared in g_save, assigned here)
    for line in _emit_groups(mission, ctx):
        add(line)

    # Selbstheilende Gruppen: EIN wiederkehrender TimeTrigger fuer die ganze
    # Mission (Callback: _repairGroups_cb, per Export-Namen aufgeloest --
    # ueberlebt damit auch Spielstand-Loads).
    # Self-healing groups: ONE recurring time trigger for the whole mission
    # (callback: _repairGroups_cb, resolved via export name -- thus also
    # survives savegame loads).
    repair_body = _emit_group_repair_body(mission, ctx)
    if repair_body:
        add("")
        add("    // --- Gruppen-Reparatur: zerstoerte, von der Engine an derselben")
        add("    // Stelle wieder errichtete Gebaeude automatisch neu zuweisen/")
        add("    // verknuepfen (ein einziger wiederkehrender Timer). ---")
        add('    CreateTimeTrigger(1, 0, kTicksPerMark, "_repairGroups_cb");')

    # Start message
    if mission.start_message and (mission.start_message.text or "").strip():
        add("")
        add(f"    AddGameMessage({_cpp_string(mission.start_message.text)});")

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
    add("    TethysGame::ForceMoraleGood(PlayerNum::PlayerAll);")
    add('    op2::log::line("InitProc: done");')
    add("}")
    add("")

    # Custom-trigger helper functions live at file scope so they (a) can be
    # called from a createTrigger action via forward decl and (b) reach the
    # g_save-backed group/unit references.
    for i, t in enumerate(mission.triggers or []):
        for line in _emit_trigger_helper(t, ctx["trigger_helpers_list"][i], ctx):
            add(line)
        add("")

    # Missionsweiter Reparatur-Callback (per Export-Namen registriert).
    # Mission-wide repair callback (registered via export name).
    if repair_body:
        add("Export void _repairGroups_cb() {")
        for line in repair_body:
            add(f"    {line}")
        add("}")
        add("")

    # --- aiProc ---
    add("static void aiProc() {")
    add("    // diff nachfuehren: nach einem Spielstand-Load laeuft InitProc nicht.")
    add("    // Refresh diff: InitProc does not run after a savegame load.")
    add("    diff = kDiff[Player[0].Difficulty()];")
    add("}")
    add("")

    # --- Guarded exports + DllMain ---
    add('Export int InitProc() { op2::crash::guard("InitProc", &initProc); return 1; }')
    add('Export void AIProc()  { op2::crash::guard("AIProc",   &aiProc); }')
    add("")
    add("// SaveRegion: g_save wird von der Engine mit dem Spielstand gespeichert")
    add("// und beim Laden byte-genau restauriert (Variablen, Gruppen-/Unit-/")
    add("// Trigger-Stubs, armed-Flags).")
    add("ExportSaveLoadData(g_save)")
    add("")
    add('extern "C" int __stdcall DllMain(void*, unsigned long reason, void*) {')
    add("    if (reason == 1 /* DLL_PROCESS_ATTACH */) {")
    add('        op2::crash::installHandler();')
    add('        op2::log::setTickSource([] { return TethysGame::Tick(); });')
    add("    }")
    add("    return 1;")
    add("}")

    return "\n".join(out) + "\n"
