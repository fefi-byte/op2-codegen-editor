"""Emission von Basis-Layout, Gruppen, Rostern und dem Reparatur-Timer.

Mechanisch aus codegen.py ausgelagert -- reine Emissions-Helfer,
keine Logikaenderung. / Mechanically split out of codegen.py --
pure emission helpers, no logic changes.
"""

from __future__ import annotations

import re

from mission_model import (
    ActionCondition, BuildingGroupSpec, Colony, Condition, DifficultySetup, FindUnitCheck,
    Mission, MissionType, PlayerSpec, ReinforceGroupSpec, TriggerAction, TriggerDef, VariableDef,
)


from codegen_cpp import (
    _compare, _cpp_string, _expr_or_int, _ident, _line_tiles, _rect,
    _strip_map, _xy, _xypos, mapid,
)
from codegen_actions import (
    _emit_action_list, _resolve_loop_ref, _wave_attack_lines,
    _wave_geometry, _wave_staging_lines,
)




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

    # Lavafelder: legen fest, WO Lava ueberhaupt fliessen kann. Bewusst hier
    # im InitProc und nicht an einem Ausbruch-Trigger -- der Ausbruch ist
    # Missionslogik, die Lavaflaeche gehoert zur Karte.
    # Lava fields: define WHERE lava can flow at all. Deliberately here in
    # InitProc rather than on an eruption trigger -- the eruption is mission
    # logic, the lava area belongs to the map.
    lava = list(getattr(mission, "lava_fields", None) or [])
    if lava:
        lines.append("")
        lines.append(f"    // --- Lava fields ({len(lava)} tiles) ---")
        for tile in lava:
            lines.append(
                f"    GameMap::SetLavaPossible({_xy(int(tile[0]), int(tile[1]))}, 1);")

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
            vtype = mapid(u.unit_type)
            lines.append(
                f"        TethysGame::CreateUnit({uvar}, {vtype}, "
                f"{_xy(u.x, u.y)}, {pidx}, {weapon}, {facing});")
            # Cargo Truck: initial freight (quantity, or a starship-part
            # subtype for truckSpaceport/truckGarbage -- see game_data.py
            # truck_cargo_items()). "truckEmpty" is the spawn default -- no
            # call needed (SetTruckCargo(truckEmpty, N) would show a bogus
            # amount on an empty truck). ConVec: building-kit cargo.
            truck_cargo = getattr(u, "truck_cargo", None)
            if vtype == "mapCargoTruck" and truck_cargo and truck_cargo != "truckEmpty":
                lines.append(
                    f"        {uvar}.SetTruckCargo({truck_cargo}, "
                    f"{_expr_or_int(getattr(u, 'truck_amount', 0) or 0)});")
            convec_kit = getattr(u, "convec_kit", None)
            if vtype == "mapConVec" and convec_kit:
                lines.append(f"        {uvar}.SetCargo({mapid(convec_kit)}, mapNone);")

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
        # Start-Gebaeude des Rosters rekordieren: "This should include any
        # buildings the AI starts the game with" (W9) -- sonst baut die
        # Gruppe zerstoerte Startgebaeude nie wieder auf.
        # Record the roster's starting buildings: "This should include any
        # buildings the AI starts the game with" (W9) -- otherwise the
        # group never rebuilds destroyed starting buildings.
        record_entries = list(_roster_building_entries(mission, g))
        if getattr(g, "record_all", True):
            seen = {(x, y) for (_t, _c, x, y) in record_entries}
            for entry in _player_start_buildings(mission, int(g.player)):
                if (entry[2], entry[3]) not in seen:
                    record_entries.append(entry)
                    seen.add((entry[2], entry[3]))
        if record_entries:
            lines.append(f"    {{")
            lines.append(f"        LOCATION _l;")
            for (btype, cargo, x, y) in record_entries:
                lines.append(f"        _l = {_xy(x, y)};")
                lines.append(f"        {var}.RecordBuilding(_l, {btype}, {cargo});")
            lines.append(f"    }}")
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




def _roster_building_entries(mission: Mission, group) -> list[tuple[str, str, int, int]]:
    """Roster-GEBAEUDE einer Gruppe als (map_id, editor_x, editor_y).

    Nur Gebaeude: der Selbstheil-Callback nimmt zerstoerte + von der Engine
    an derselben Stelle wieder errichtete Gebaeude erneut auf; verlorene
    FAHRZEUGE ersetzt stattdessen die Sollstaerke (SetTargCount +
    ReinforceGroup). mapRareOreMine wird wie im BaseLayout als
    mapCommonOreMine behandelt (Rare-Ore-Mine-Gotcha).

    A group's roster BUILDINGS as (map_id, cargo, editor_x, editor_y). Buildings
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
    out: list[tuple[str, str, int, int]] = []
    for uid in uids:
        u = by_uid.get(uid)
        if u is None:
            continue
        if _strip_map(u.unit_type) not in _BUILDING_TYPES:
            continue
        btype = mapid(u.unit_type)
        if btype == "mapRareOreMine":
            btype = "mapCommonOreMine"
        cargo = mapid(u.cargo) if (u.cargo and u.cargo != "mapNone") else "mapNone"
        out.append((btype, cargo, int(u.x), int(u.y)))
    return out




def _player_start_buildings(mission: Mission, player: int) -> list[tuple[str, str, int, int]]:
    """ALLE Start-Gebaeude eines Spielers als (map_id, cargo, x, y) --
    fuer record_all-BuildingGroups (Basis-Wiederaufbau). Minen ausgenommen:
    deren Wiederaufbau braucht eine eigene Gruppe mit Robo-Miner
    (klassisches RebuildMines-Muster), die Eintraege kommen dort ueber das
    Roster.

    ALL of a player's starting buildings as (map_id, cargo, x, y) -- for
    record_all building groups (base rebuild). Mines excluded: rebuilding
    them needs a dedicated group with a Robo-Miner (classic RebuildMines
    pattern); those entries come via that group's roster.
    """
    out: list[tuple[str, str, int, int]] = []
    for u in (mission.units or []):
        if int(u.player) != int(player):
            continue
        if _strip_map(u.unit_type) not in _BUILDING_TYPES:
            continue
        btype = mapid(u.unit_type)
        if btype in ("mapCommonOreMine", "mapRareOreMine"):
            continue
        cargo = mapid(u.cargo) if (u.cargo and u.cargo != "mapNone") else "mapNone"
        out.append((btype, cargo, int(u.x), int(u.y)))
    return out




def _repair_building_take_lines(group, var: str,
                                entries: list[tuple[str, str, int, int]]) -> list[str]:
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
    for n, (btype, _cargo, x, y) in enumerate(entries):
        seen = f"_seen_{_ident(group.name)}_{n}"
        out += [
            f"{{",
            f"    PlayerBuildingEnum _e({int(group.player)}, {btype});",
            f"    UnitEx _u;",
            f"    LOCATION _a = {_xy(x, y)};",
            f"    while (_e.GetNext(_u)) {{",
            f"        LOCATION _loc = _u.Location();",
            f"        if (!(_loc == _a)) continue;",
            f"        static int {seen} = 0;",
            f"        if (!isCompleted(_u)) {{ {seen} = 0; continue; }}",
            f"        if ({seen} != _u.unitID) {{",
            f"            {seen} = _u.unitID;",
            f"            continue;  // erst 1 Mark stabil fertig, dann uebernehmen",
            f"        }}",
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
        f"if (isCompleted(_mine) && isCompleted(_smelter)) {{",
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

    # --- Benannte Gebaeude-Anker neu binden: steht an der Anker-Kachel ein
    # fertiges Gebaeude des Typs mit anderer unitID (Neubau nach
    # Zerstoerung ODER erstmals gebautes geplantes Gebaeude), wird das
    # Handle umgebogen -- der Name bleibt damit dauerhaft ansprechbar. ---
    # --- Rebind named building anchors: if a completed building of the
    # right type with a different unitID stands on the anchor tile (rebuilt
    # after destruction OR a planned building built for the first time),
    # the handle is redirected -- the name stays addressable forever. ---
    for ai, (aname, avar, aplayer, atype, ax, ay) in enumerate(ctx.get("anchors", [])):
        seen = f"_seen_anchor_{ai}"
        body += [
            f"{{",
            f"    PlayerBuildingEnum _e({aplayer}, {atype});",
            f"    UnitEx _u;",
            f"    LOCATION _a = {_xy(ax, ay)};",
            f"    static int {seen} = 0;",
            f"    while (_e.GetNext(_u)) {{",
            f"        if (!(_u.Location() == _a)) continue;",
            f"        if (!isCompleted(_u)) {{ {seen} = 0; break; }}",
            f"        if ({seen} != _u.unitID) {{ {seen} = _u.unitID; break; }}",
            f"        if ({avar}.unitID != _u.unitID) {{",
            f"            {avar} = _u;",
            f'            op2::log::linef("Anker [{aname}] -> Einheit %d gebunden", _u.unitID);',
            f"        }}",
            f"        break;",
            f"    }}",
            f"}}",
        ]

    # --- Geplante benannte Gebaeude (plan:<Name> im Roster) in ihre Gruppe
    # aufnehmen, sobald der Anker gebunden ist. ---
    # --- Take planned named buildings (plan:<name> in the roster) into
    # their group once the anchor is bound. ---
    for attr in ("building_groups", "reinforce_groups", "mining_groups"):
        for g in (getattr(mission, attr, None) or []):
            var = ctx["group_vars"][g.name]
            for uid in (getattr(g, "unit_ids", None) or []):
                if not (isinstance(uid, str) and uid.startswith("plan:")):
                    continue
                hvar = ctx.get("unit_vars", {}).get(uid[5:].strip())
                if not hvar:
                    continue
                body += [
                    f"if (isCompleted({hvar})) {{",
                    f"    bool _member = false;",
                    f"    GroupEnumerator _ge({var});",
                    f"    UnitEx _m;",
                    f"    while (_ge.GetNext(_m)) {{",
                    f"        if (_m.unitID == {hvar}.unitID) {{ _member = true; break; }}",
                    f"    }}",
                    f"    if (!_member) {{",
                    f"        {var}.TakeUnit({hvar});",
                    f'        op2::log::linef("Roster: [{uid[5:].strip()}] (Einheit %d) -> Gruppe {g.name}", {hvar}.unitID);',
                    f"    }}",
                    f"}}",
                ]

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
        # Referenz-Aufloesung: Gruppen-Definition (mine_ref/smelter_ref der
        # MiningGroup) hat Vorrang; dann Aktions-Referenzen; zuletzt
        # Positions-Lookup.
        # Reference resolution: the group definition (mine_ref/smelter_ref
        # of the MiningGroup) wins; then action-level refs; finally the
        # position lookup.
        mine_ref = ((getattr(spec, "mine_ref", "") or "").strip()
                    or getattr(action, "mine_ref", "") or "")
        smelter_ref = ((getattr(spec, "smelter_ref", "") or "").strip()
                       or getattr(action, "smelter_ref", "") or "")
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
        body.append(f"    if (isCompleted(_mine) && isCompleted(_smelter) &&")
        body.append(f"        (_mine.unitID != {ids_var}[0] || _smelter.unitID != {ids_var}[1])) {{")
        body.append(f"        MAP_RECT _area = {area};")
        body.append(f"        {var}.Setup(_mine, _smelter, _area);")
        body.append(f"        {var}.SetTargCount(mapCargoTruck, mapNone, {n});")
        body.append(f"        {ids_var}[0] = _mine.unitID;")
        body.append(f"        {ids_var}[1] = _smelter.unitID;")
        # Truck-Nachschub: die in der Gruppe hinterlegte ReinforceGroup
        # produziert fuer die Sollstaerke (Prioritaet nie 0!).
        # Truck resupply: the group's configured ReinforceGroup produces
        # for the target count (priority never 0!).
        src_name = (getattr(spec, "source_group_name", "") or "").strip()
        src_var = ctx["group_vars"].get(src_name) if src_name else None
        if src_var:
            prio = max(1, int(getattr(spec, "reinforce_priority", 1000) or 1000))
            body.append(f"        {src_var}.RecordVehReinforceGroup({var}, {prio});")
        body.append(f'        op2::log::linef("MiningGroup [{action.group_name}] aktiviert '
                    f'(Mine %d, Smelter %d)", _mine.unitID, _smelter.unitID);')
        body.append(f"    }}")
        body.append(f"}}")

    for action, armed_var in ctx.get("assign_actions", []):
        var = ctx["group_vars"].get(action.group_name, None)
        if not var:
            continue
        seen = f"_seen_assign_{armed_var.rsplit('_', 1)[-1]}"
        body.append(f"if ({armed_var}) {{")
        body.append(f"    UnitEx _b = unitOnTile({_xy(action.x, action.y)});")
        body.append(f"    static int {seen} = 0;")
        body.append(f"    if (!isCompleted(_b)) {seen} = 0;")
        body.append(f"    else if ({seen} != _b.unitID) {seen} = _b.unitID;  // erst 1 Mark stabil")
        body.append(f"    else if (_b.GetType() == {mapid(action.building_type)}) {{")
        body.append(f"        bool _member = false;")
        body.append(f"        GroupEnumerator _ge({var});")
        body.append(f"        UnitEx _m;")
        body.append(f"        while (_ge.GetNext(_m)) {{")
        body.append(f"            if (_m.unitID == _b.unitID) {{ _member = true; break; }}")
        body.append(f"        }}")
        body.append(f"        if (!_member) {var}.TakeUnit(_b);")
        body.append(f"    }}")
        body.append(f"}}")

    # --- Reparatur-Makro v2: Zonen scannen, ab Schwelle beauftragen ---
    # --- Repair macro v2: scan zones, task vehicles from the threshold up ---
    for ridx, (action, armed_var) in enumerate(ctx.get("repair_actions", [])):
        gvar = ctx["group_vars"].get(getattr(action, "group_name", "") or "")
        if not gvar:
            continue
        gplayer = 0
        colony_eden = True
        for attr in ("building_groups", "reinforce_groups"):
            for g in (getattr(mission, attr, None) or []):
                if g.name == (getattr(action, "group_name", "") or ""):
                    gplayer = int(g.player)
        players = mission.players or []
        if 0 <= gplayer < len(players):
            colony_eden = (players[gplayer].colony == Colony.Eden)
        # Kolonie-Spezialist zuerst, ConVec als Rueckfall. Repair Vehicle ist
        # Eden-exklusiv, Spider Plymouth-exklusiv -- kein Kreuz-Fallback.
        # Colony specialist first, ConVec as fallback. Repair Vehicle is
        # Eden-only, Spider Plymouth-only -- no cross-colony fallback.
        specialist = "mapRepairVehicle" if colony_eden else "mapSpider"
        zones = list(getattr(action, "repair_zones", None) or [])
        if not zones:
            zones = [{"x": action.x, "y": action.y, "x2": action.x2, "y2": action.y2}]
        thresholds = list(getattr(action, "repair_thresholds", None) or [])
        # Ohne Listeneintrag wird ab jedem Schaden repariert (Schwelle 1);
        # die Liste hebt die Schwelle nur fuer einzelne Gebaeude an.
        # Without a list entry, any damage triggers repair (threshold 1);
        # the list only raises the threshold for individual buildings.
        thr_lines = ["        int _thr = 1;"]
        first_kw = "if"
        for t in thresholds:
            bt = mapid(t.get("building_type", ""))
            if not bt or bt == "mapNone":
                continue
            thr_lines.append(f"        {first_kw} (_bt == {bt}) _thr = {int(t.get('damage', 1))};")
            first_kw = "else if"
        body.append(f"if ({armed_var}) {{")
        body.append(f"    int _issued[8]; int _nIssued = 0;")
        for z in zones:
            zrect = _rect(int(z.get("x", 0)), int(z.get("y", 0)),
                          int(z.get("x2", 0)), int(z.get("y2", 0)))
            body.append(f"    {{")
            body.append(f"    MAP_RECT _z = {zrect};")
            body.append(f"    InRectEnumerator _e(_z);")
            body.append(f"    UnitEx _b;")
            body.append(f"    while (_e.GetNext(_b)) {{")
            body.append(f"        if (!_b.IsBuilding() || !_b.IsLive() || _b.OwnerID() != {gplayer}) continue;")
            body.append(f"        map_id _bt = _b.GetType();")
            body.extend(thr_lines)
            body.append(f"        if (_b.GetDamage() < _thr) continue;")
            body.append(f"        // freies Fahrzeug der Gruppe suchen (Praeferenz-Rangfolge)")
            body.append(f"        UnitEx _best; int _bestRank = 99;")
            body.append(f"        GroupEnumerator _ge({gvar});")
            body.append(f"        UnitEx _v;")
            body.append(f"        while (_ge.GetNext(_v)) {{")
            body.append(f"            if (!_v.IsVehicle() || !_v.IsLive()) continue;")
            body.append(f"            if (_v.GetLastCommand() != ctNop) continue;")
            body.append(f"            bool _busy = false;")
            body.append(f"            for (int _i = 0; _i < _nIssued; ++_i) if (_issued[_i] == _v.unitID) _busy = true;")
            body.append(f"            if (_busy) continue;")
            body.append(f"            int _rank = 99;")
            body.append(f"            map_id _vt = _v.GetType();")
            body.append(f"            if (_vt == {specialist}) _rank = 0;")
            body.append(f"            else if (_vt == mapConVec) _rank = 1;")
            body.append(f"            if (_rank < _bestRank) {{ _bestRank = _rank; _best = _v; }}")
            body.append(f"        }}")
            body.append(f"        if (_bestRank < 99 && _nIssued < 8) {{")
            body.append(f"            _best.DoRepair(_b);")
            body.append(f"            _issued[_nIssued++] = _best.unitID;")
            body.append(f'            op2::log::linef("Repair-Auftrag: Fahrzeug %d -> Gebaeude %d (Schaden %d)", _best.unitID, _b.unitID, _b.GetDamage());')
            body.append(f"        }}")
            body.append(f"    }}")
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
