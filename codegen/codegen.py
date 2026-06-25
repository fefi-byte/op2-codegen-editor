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
    Colony, Condition, Mission, MissionType, PlayerSpec, TriggerDef,
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
                        lines.append(f"            {{ {{ {int(b.x)}, {int(b.y)} }}, {ore}, {yld} }},")
                lines.append(f"        }};")
            # tubes + walls (Gaia)
            tubes = [w for w in walls if w.wall_type == "mapTube"]
            wall_items = [w for w in walls if w.wall_type and w.wall_type != "mapTube"]
            if tubes:
                lines.append(f"        base.tubes = {{")
                for t in tubes:
                    lines.append(f"            {{ {{ {int(t.x)}, {int(t.y)} }}, {{ {int(t.x)}, {int(t.y)} }} }},")
                lines.append(f"        }};")
            if wall_items:
                lines.append(f"        base.walls = {{")
                for w in wall_items:
                    lines.append(f"            {{ {{ {int(w.x)}, {int(w.y)} }}, {{ {int(w.x)}, {int(w.y)} }} }},")
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
                    lines.append(f"            {{ {{ {int(u.x)}, {int(u.y)} }}, {mapid(u.unit_type)} }},")
                else:
                    lines.append(
                        f"            {{ {{ {int(u.x)}, {int(u.y)} }}, {mapid(u.unit_type)}, {cargo} }},"
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
                    f"            {{ {{ {int(u.x)}, {int(u.y)} }}, {mapid(u.unit_type)}, {weapon}, {facing} }},"
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


def _emit_trigger_stub(t: TriggerDef) -> list[str]:
    """Placeholder for a custom trigger; full porting is Phase 2.5.

    A trigger present in the editor model is emitted as a `// TODO` comment
    for now so the user knows it was dropped. The most common case (welcome
    message at mark N) is supported inline.
    """
    # Simple case: time trigger with a single "message" action -> emit it.
    if t.condition == "time" and len(t.actions) == 1 and (t.actions[0].kind == "message"):
        msg = _cpp_string(t.actions[0].text)
        return [f"    onMark({int(t.marks)}, [] {{ Game::addMessage({msg}); }});"]
    return [
        f"    // TODO custom trigger '{t.name}' (condition={t.condition}, "
        f"{len(t.actions)} actions) -- not yet ported to TitanAPI codegen.",
    ]


def generate_levelmain(mission: Mission) -> str:
    """Emit the full `mission.cpp` for `mission`.

    The output is a single self-contained translation unit using the TitanAPI
    op2:: facade. Folder writers in mission_project.write_mission_folder
    detect this output (it starts with a `//` comment and contains `op2.hpp`)
    and prefer it over the static template fallback.
    """
    out: list[str] = []
    add = out.append

    add(f"// mission.cpp -- generated from the editor model for: {mission.name}")
    add("// Built against TitanAPI (https://github.com/leviathan400/TitanAPI).")
    add("")
    add('#include "op2.hpp"')
    add('#include "op2/trigger.hpp"')
    add('#include "op2/base.hpp"')
    add('#include "op2_mission.hpp"')
    add('#include "op2_log.hpp"')
    add('#include "op2_crash.hpp"')
    add("")
    add("using namespace op2;")
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

    # Custom triggers (stubs / inline simple case)
    if mission.triggers:
        add("")
        add("    // --- Custom triggers ---")
        for t in mission.triggers:
            for line in _emit_trigger_stub(t):
                add(line)

    add("")
    add('    op2::ignore(Game::forceMoraleGood());')
    add('    log::line("InitProc: done");')
    add("}")
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
