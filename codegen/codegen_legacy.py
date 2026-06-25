"""Codegen: Mission-Modell  ->  LevelMain.cpp (Outpost-2-SDK-C++).

Liest ein Mission-Objekt (mission_model.py) und erzeugt den C++-Quelltext,
der mit der bewiesenen Pipeline (LevelTemplate + msbuild) zu einer
lauffaehigen Mission-DLL kompiliert.

Codegen: mission model -> LevelMain.cpp (Outpost 2 SDK C++).

Reads a mission object (mission_model.py) and produces the C++ source code
that, via the proven pipeline (LevelTemplate + msbuild), compiles into a
runnable mission DLL.
"""
from __future__ import annotations

from mission_model import Colony, Mission


BUILDING_FOOTPRINTS = {
    "mapCommandCenter": (3, 2),
    "mapTokamak": (2, 2),
    "mapCommonOreSmelter": (4, 3),
    "mapRareOreSmelter": (4, 3),
    "mapStructureFactory": (4, 3),
    "mapVehicleFactory": (4, 3),
    "mapArachnidFactory": (4, 3),
    "mapAgridome": (3, 2),
    "mapNursery": (2, 2),
    "mapUniversity": (2, 2),
    "mapResidence": (2, 2),
    "mapCommonOreMine": (2, 1),
    "mapRareOreMine": (2, 1),
    "mapMagmaWell": (2, 1),
    "mapSpaceport": (5, 4),
    "mapGuardPost": (1, 1),
}
SET_TARG_ALLOWED_UNITS = {
    "MiningGroup": {"mapCargoTruck"},
    "BuildingGroup": {"mapConVec"},
    "FightGroup": {"mapLynx", "mapPanther", "mapTiger"},
}
MINING_OPERATION_TYPES = {
    "common": ("mapCommonOreMine", "mapCommonOreSmelter"),
    "rare": ("mapRareOreMine", "mapRareOreSmelter"),
}


def _cpp_string(text: str) -> str:
    """Escaped einen Python-String fuer ein C++-String-Literal.

    Escapes a Python string for use as a C++ string literal.
    """
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Editor-Kachelkoordinaten sind 0-basiert; OP2 erwartet 1-basierte Koordinaten,
# daher +1. Das Ergebnis wird anschliessend von den SDK-Makros weiterverarbeitet:
# MkXY(x,y)=LOCATION(x+31,y-1) und XYPos(x,y)=x+31,y-1 -> Welt-Versatz +32 in X.
# Editor tile coordinates are 0-based; OP2 expects 1-based coordinates, hence +1.
# The result then feeds the SDK macros MkXY(x,y)=LOCATION(x+31,y-1) and
# XYPos(x,y)=x+31,y-1, giving a net world offset of +32 in X.
def _op2_coord(value: int) -> int:
    return value + 1


# Baut den MkXY()-SDK-Aufruf aus 0-basierten Editor-Koordinaten (siehe _op2_coord).
# Builds the MkXY() SDK call from 0-based editor coordinates (see _op2_coord).
def _mkxy(x: int, y: int) -> str:
    return f"MkXY({_op2_coord(x)}, {_op2_coord(y)})"


# Baut den XYPos()-SDK-Aufruf aus 0-basierten Editor-Koordinaten (siehe _op2_coord).
# Builds the XYPos() SDK call from 0-based editor coordinates (see _op2_coord).
def _xypos(x: int, y: int) -> str:
    return f"XYPos({_op2_coord(x)}, {_op2_coord(y)})"


# Baut den MkRect()-SDK-Aufruf; jede Ecke wird via _op2_coord 1-basiert gemacht.
# Builds the MkRect() SDK call; each corner is made 1-based via _op2_coord.
def _mkrect(x1: int, y1: int, x2: int, y2: int) -> str:
    return (
        f"MkRect({_op2_coord(x1)}, {_op2_coord(y1)}, "
        f"{_op2_coord(x2)}, {_op2_coord(y2)})"
    )


def _cpp_ident(text: str, fallback: str = "Item") -> str:
    """Erzeugt einen gueltigen C++-Identifier aus Editor-Namen/IDs.

    Produces a valid C++ identifier from editor names/IDs.
    """
    s = "".join(c if c.isalnum() else "_" for c in text).strip("_")
    if not s:
        s = fallback
    if s[0].isdigit():
        s = "_" + s
    return s


def _unique_ident(text: str, used: set[str], fallback: str = "Item") -> str:
    base = _cpp_ident(text, fallback)
    ident = base
    counter = 2
    while ident in used:
        ident = f"{base}_{counter}"
        counter += 1
    used.add(ident)
    return ident


def _global_names(mission: Mission) -> dict:
    """Baut parallele Namens-Maps fuer generierte C++-Variablen.

    Fuer Einheiten, Gruppen und Trigger werden mehrere Nachschlage-Tabellen
    aufgebaut: nach Editor-Index vs. nach uid, einfacher Ausdruck vs.
    Get_*()-Getter, sowie ScriptGlobal-Save-Slots fuer jene Objekte (Units,
    Groups, Trigger), die ueber Save/Load hinweg erhalten bleiben muessen.
    Das zurueckgegebene dict buendelt all diese Maps plus die Feldliste fuer
    die ScriptGlobal-Struktur, damit die uebrigen Generator-Funktionen
    konsistent denselben C++-Variablennamen verwenden.

    Builds parallel name maps for generated C++ variables. For units, groups
    and triggers it assembles several lookup tables: by editor index vs. by
    uid, plain expression vs. Get_*() getter, plus ScriptGlobal save slots for
    those objects (units, groups, triggers) that must survive save/load. The
    returned dict bundles all these maps together with the field list for the
    ScriptGlobal struct, so the remaining generator functions consistently use
    the same C++ variable name.
    """
    used: set[str] = set()
    runtime_mining_group_names = {
        action.mining_group_name
        for trigger in mission.triggers
        for action in trigger.actions
        if action.kind == "startMiningOperation" and action.mining_group_name
    }
    runtime_unit_uids = {
        uid
        for group in mission.mining_groups
        if group.name in runtime_mining_group_names
        for uid in group.truck_ids
        if uid
    }
    fields: list[tuple[str, str, str]] = []
    unit_by_index: dict[int, str] = {}
    unit_save_by_index: dict[int, str] = {}
    unit_by_uid: dict[str, str] = {}
    unit_getter_by_uid: dict[str, str] = {}
    mining_by_index: dict[int, str] = {}
    mining_save_by_index: dict[int, str] = {}
    building_by_index: dict[int, str] = {}
    building_save_by_index: dict[int, str] = {}
    building_getter_by_name: dict[str, str] = {}
    mining_getter_by_name: dict[str, str] = {}
    reinforce_by_index: dict[int, str] = {}
    reinforce_save_by_index: dict[int, str] = {}
    reinforce_getter_by_name: dict[str, str] = {}
    group_type_by_name: dict[str, str] = {}
    assign_save_by_id: dict[int, str] = {}
    assign_getter_by_id: dict[int, str] = {}

    for i, unit in enumerate(mission.units):
        if unit.unit_name.strip() or unit.uid in runtime_unit_uids:
            ident_source = unit.unit_name.strip() or unit.uid
            ident = _unique_ident(f"u_{ident_source}", used, f"u_unit{i + 1}")
            fields.append(("int", ident, "Unit"))
            expr = f"unit_{ident}"
            unit_by_index[i] = expr
            unit_save_by_index[i] = f"scriptGlobal.{ident}"
            if unit.uid:
                unit_by_uid[unit.uid] = expr
                unit_getter_by_uid[unit.uid] = f"Get_{ident}()"

    for i, group in enumerate(mission.mining_groups):
        ident = _unique_ident(f"g_{group.name}", used, f"g_mining{i + 1}")
        fields.append(("int", ident, "MiningGroup"))
        mining_by_index[i] = f"group_{ident}"
        mining_save_by_index[i] = f"scriptGlobal.{ident}"
        mining_getter_by_name[group.name] = f"Get_{ident}()"
        group_type_by_name[group.name] = "MiningGroup"

    for i, group in enumerate(mission.building_groups):
        ident = _unique_ident(f"g_{group.name}", used, f"g_building{i + 1}")
        fields.append(("int", ident, "BuildingGroup"))
        building_by_index[i] = f"group_{ident}"
        building_save_by_index[i] = f"scriptGlobal.{ident}"
        building_getter_by_name[group.name] = f"Get_{ident}()"
        group_type_by_name[group.name] = "BuildingGroup"

    for i, group in enumerate(mission.reinforce_groups):
        ident = _unique_ident(f"g_{group.name}", used, f"g_reinforce{i + 1}")
        fields.append(("int", ident, "BuildingGroup"))
        reinforce_by_index[i] = f"group_{ident}"
        reinforce_save_by_index[i] = f"scriptGlobal.{ident}"
        reinforce_getter_by_name[group.name] = f"Get_{ident}()"
        building_getter_by_name[group.name] = f"Get_{ident}()"
        group_type_by_name[group.name] = "ReinforceGroup"

    # Pro assignToGroup-Aktion ein Trigger-Handle (fuer den 10-Tik-Poll, der sich
    # nach dem Fund selbst per Destroy() beendet). Rekursiv durch if-Bloecke,
    # per id(action) geschluesselt (eindeutig auch bei Verschachtelung).
    # One trigger handle per assignToGroup action (for the 10-tick poll that
    # ends itself via Destroy() once found). Walked recursively through if
    # blocks, keyed by id(action) (unique even when nested).
    _an = [0]

    def _walk_assign(actions):
        for action in actions:
            if action.kind == "assignToGroup":
                ident = _unique_ident(f"t_assign{_an[0]}", used, f"t_assign{_an[0]}")
                _an[0] += 1
                fields.append(("int", ident, "Trigger"))
                assign_save_by_id[id(action)] = f"scriptGlobal.{ident}"
                assign_getter_by_id[id(action)] = f"Get_{ident}()"
            if action.kind == "if":
                _walk_assign(action.then_actions)
                _walk_assign(action.else_actions)

    for trigger in mission.triggers:
        _walk_assign(trigger.actions)

    return {
        "fields": fields,
        "unit_by_index": unit_by_index,
        "unit_save_by_index": unit_save_by_index,
        "unit_by_uid": unit_by_uid,
        "unit_getter_by_uid": unit_getter_by_uid,
        "mining_by_index": mining_by_index,
        "mining_save_by_index": mining_save_by_index,
        "building_by_index": building_by_index,
        "building_save_by_index": building_save_by_index,
        "building_getter_by_name": building_getter_by_name,
        "mining_getter_by_name": mining_getter_by_name,
        "reinforce_by_index": reinforce_by_index,
        "reinforce_save_by_index": reinforce_save_by_index,
        "reinforce_getter_by_name": reinforce_getter_by_name,
        "group_type_by_name": group_type_by_name,
        "assign_save_by_id": assign_save_by_id,
        "assign_getter_by_id": assign_getter_by_id,
    }


def _gen_script_global(names: dict) -> str:
    fields = names["fields"]
    if not fields:
        return "struct ScriptGlobal { } scriptGlobal;"
    lines = ["struct ScriptGlobal", "{"]
    for field_type, ident, _ in fields:
        lines.append(f"\t{field_type} {ident};")
    lines.append("} scriptGlobal;")
    return "\n".join(lines)


def _gen_global_helpers(names: dict) -> str:
    blocks: list[str] = []
    for _, ident, kind in names["fields"]:
        if kind == "Unit":
            blocks.append(
                f"UnitEx& Get_{ident}()\n{{\n"
                f"\treturn *reinterpret_cast<UnitEx*>(&scriptGlobal.{ident});\n"
                f"}}"
            )
        elif kind in ("MiningGroup", "BuildingGroup"):
            var_type = kind
            blocks.append(
                f"{var_type}& Get_{ident}()\n{{\n"
                f"\treturn *reinterpret_cast<{var_type}*>(&scriptGlobal.{ident});\n"
                f"}}"
            )
        elif kind == "Trigger":
            blocks.append(
                f"Trigger& Get_{ident}()\n{{\n"
                f"\treturn *reinterpret_cast<Trigger*>(&scriptGlobal.{ident});\n"
                f"}}"
            )
    return "\n\n".join(blocks)


def _gen_init_proc(mission: Mission, names: dict) -> str:
    lines: list[str] = []
    referenced_unit_ids = {
        uid for group in mission.mining_groups for uid in group.truck_ids if uid
    }
    referenced_unit_ids.update(
        uid for group in mission.building_groups for uid in group.unit_ids if uid
    )
    referenced_unit_ids.update(
        uid for group in mission.reinforce_groups for uid in group.unit_ids if uid
    )
    unit_var_by_uid: dict[str, str] = {}

    # --- Spieler einrichten ---
    # --- Set up players ---
    for i, player in enumerate(mission.players):
        go = "GoEden" if player.colony == Colony.Eden else "GoPlymouth"
        lines.append(f"\tPlayer[{i}].{go}();")
        lines.append(f"\tPlayer[{i}].{'GoHuman' if player.is_human else 'GoAI'}();")
        lines.append(f"\tPlayer[{i}].SetTechLevel({player.tech_level});")
        for tech_id in player.researches:
            lines.append(f"\tPlayer[{i}].MarkResearchComplete({tech_id});")
        if player.init_resources:
            lines.append(f"\tInitPlayerResources({i});")
        # Explizite Kolonisten/Ressourcen ueberschreiben die Standardwerte.
        # Explicit colonists/resources override the default values.
        if player.workers is not None:
            lines.append(f"\tPlayer[{i}].SetWorkers({player.workers});")
        if player.scientists is not None:
            lines.append(f"\tPlayer[{i}].SetScientists({player.scientists});")
        if player.kids is not None:
            lines.append(f"\tPlayer[{i}].SetKids({player.kids});")
        if player.common_ore is not None:
            lines.append(f"\tPlayer[{i}].SetOre({player.common_ore});")
        if player.rare_ore is not None:
            lines.append(f"\tPlayer[{i}].SetRareOre({player.rare_ore});")
        if player.food is not None:
            lines.append(f"\tPlayer[{i}].SetFoodStored({player.food});")
    lines.append("")

    # --- Startnachricht ---
    # --- Start message ---
    if mission.start_message:
        lines.append(f"\tAddGameMessage({_cpp_string(mission.start_message.text)});")
        lines.append("")

    # --- Beacons / Magma Vents / Geysire ---
    # --- Beacons / magma vents / geysers ---
    # WICHTIG: vor den Einheiten erzeugen, damit Minen auf einem Beacon stehen koennen.
    # IMPORTANT: create before the units, so mines can sit on top of a beacon.
    if mission.beacons:
        for b in mission.beacons:
            lines.append(
                f"\tTethysGame::CreateBeacon({b.beacon_type}, {_xypos(b.x, b.y)}, "
                f"{b.ore_type}, {b.yield_bars}, {b.variant});"
            )
        lines.append("")

    # --- Einheiten platzieren ---
    # --- Place units ---
    if mission.units:
        if any(
            i not in names["unit_by_index"] and u.uid not in referenced_unit_ids
            for i, u in enumerate(mission.units)
        ):
            lines.append("\tUnitEx unit;")
        for i, u in enumerate(mission.units):
            unit_var = names["unit_by_index"].get(i, "unit")
            if i in names["unit_by_index"]:
                lines.append(f"\tUnitEx {unit_var};")
            if u.uid and u.uid in referenced_unit_ids and i not in names["unit_by_index"]:
                unit_var = f"unit_{_cpp_ident(u.uid)}"
                lines.append(f"\tUnitEx {unit_var};")
            if u.uid:
                unit_var_by_uid[u.uid] = unit_var
            lines.append(
                f"\tTethysGame::CreateUnit({unit_var}, {u.unit_type}, "
                f"{_mkxy(u.x, u.y)}, {u.player}, {u.cargo}, {u.rotation});"
            )
            if u.truck_cargo and u.truck_cargo != "truckEmpty" and u.truck_amount > 0:
                lines.append(f"\t{unit_var}.SetTruckCargo({u.truck_cargo}, {u.truck_amount});")
            if u.convec_kit:
                lines.append(f"\t{unit_var}.SetCargo({u.convec_kit}, mapNone);")
            if i in names["unit_save_by_index"]:
                lines.append(f"\t{names['unit_save_by_index'][i]} = {unit_var}.unitID;")
        lines.append("")

    # --- Mauern & Rohre ---
    # --- Walls & tubes ---
    if mission.walls_tubes:
        for w in mission.walls_tubes:
            lines.append(f"\tTethysGame::CreateWallOrTube({_xypos(w.x, w.y)}, 0, {w.wall_type});")
        lines.append("")

    # --- MiningGroups ---
    # --- Mining groups ---
    if mission.mining_groups:
        lines += _gen_mining_groups(mission, names, unit_var_by_uid)
        lines.append("")

    # --- BuildingGroups ---
    # --- Building groups ---
    if mission.building_groups:
        lines += _gen_building_groups(mission, names, unit_var_by_uid)
        lines.append("")

    # --- ReinforceGroups ---
    # --- Reinforce groups ---
    if mission.reinforce_groups:
        lines += _gen_reinforce_groups(mission, names, unit_var_by_uid)
        lines.append("")

    # --- Benutzerdefinierte Trigger (die beim Start aktiv sind) ---
    # --- Custom triggers (those active at start) ---
    start_triggers = [t for t in mission.triggers if t.enabled_at_start]
    if start_triggers:
        for t in start_triggers:
            lines.append(f"\t{_trigger_create_expr(t)};")
        lines.append("")

    # --- Sieg- und Niederlage-Bedingungen ---
    # --- Victory and defeat conditions ---
    counter = [0]  # gemeinsamer Zaehler fuer eindeutige Trigger-Variablennamen
    # shared counter for unique trigger variable names
    for cond in mission.victories:
        lines += _gen_condition(cond, is_victory=True, counter=counter)
    for cond in mission.defeats:
        lines += _gen_condition(cond, is_victory=False, counter=counter)
    if mission.victories or mission.defeats:
        lines.append("")

    lines.append("\treturn true;")
    return "\n".join(lines)


def _gen_mining_groups(mission: Mission, names: dict, unit_var_by_uid: dict[str, str]) -> list[str]:
    lines: list[str] = []
    used: set[str] = set()
    for i, group in enumerate(mission.mining_groups):
        base = _cpp_ident(group.name, f"MiningGroup{i + 1}")
        if base in used:
            base = f"{base}_{i + 1}"
        used.add(base)
        group_var = names["mining_by_index"][i]
        lines.append(f"\tMiningGroup {group_var} = CreateMiningGroup(Player[{group.player}]);")
        lines.append(f"\t{names['mining_save_by_index'][i]} = {group_var}.Id();")
        if getattr(group, "has_setup", True):
            # Sofort eingerichtete Gruppe: Setup + Trucks bei Init.
            # Immediately set-up group: Setup + trucks at init time.
            rx2 = group.rect_x + group.rect_width - 1
            ry2 = group.rect_y + group.rect_height - 1
            lines.append(f"\tLOCATION {base}Mine = {_mkxy(group.mine_x, group.mine_y)};")
            lines.append(f"\tLOCATION {base}Smelter = {_mkxy(group.smelter_x, group.smelter_y)};")
            lines.append(f"\tMAP_RECT {base}Rect = {_mkrect(group.rect_x, group.rect_y, rx2, ry2)};")
            lines.append(f"\t{group_var}.Setup({base}Mine, {base}Smelter, {base}Rect);")
            for uid in group.truck_ids:
                unit_var = unit_var_by_uid.get(uid)
                if unit_var:
                    lines.append(f"\t{group_var}.TakeUnit({unit_var});")
        else:
            # Verzoegerte Gruppe: NUR erstellen. Setup + TakeUnit erfolgen zur
            # Laufzeit (startMiningOperation), sonst steht der Truck in einer
            # nicht eingerichteten Gruppe und faehrt nie eine Route.
            # Deferred group: only create it. Setup + TakeUnit happen at
            # runtime (startMiningOperation); otherwise the truck sits in an
            # un-set-up group and never drives a route.
            lines.append(f"\t// {group_var}: Setup + Trucks folgen zur Laufzeit")
    return lines


def _gen_building_groups(mission: Mission, names: dict, unit_var_by_uid: dict[str, str]) -> list[str]:
    lines: list[str] = []
    used: set[str] = set()
    for i, group in enumerate(mission.building_groups):
        base = _cpp_ident(group.name, f"BuildingGroup{i + 1}")
        if base in used:
            base = f"{base}_{i + 1}"
        used.add(base)
        rx2 = group.rect_x + group.rect_width - 1
        ry2 = group.rect_y + group.rect_height - 1
        group_var = names["building_by_index"][i]
        lines.append(f"\tMAP_RECT {base}Rect = {_mkrect(group.rect_x, group.rect_y, rx2, ry2)};")
        lines.append(f"\tBuildingGroup {group_var} = CreateBuildingGroup(Player[{group.player}]);")
        lines.append(f"\t{names['building_save_by_index'][i]} = {group_var}.Id();")
        lines.append(f"\t{group_var}.SetRect({base}Rect);")
        for uid in group.unit_ids:
            unit_var = unit_var_by_uid.get(uid)
            if unit_var:
                lines.append(f"\t{group_var}.TakeUnit({unit_var});")
    return lines


def _group_getter_by_name(names: dict, group_name: str) -> str | None:
    return (
        names["mining_getter_by_name"].get(group_name)
        or names["building_getter_by_name"].get(group_name)
        or names["reinforce_getter_by_name"].get(group_name)
    )


def _gen_reinforce_groups(mission: Mission, names: dict, unit_var_by_uid: dict[str, str]) -> list[str]:
    lines: list[str] = []
    used: set[str] = set()
    for i, group in enumerate(mission.reinforce_groups):
        base = _cpp_ident(group.name, f"ReinforceGroup{i + 1}")
        if base in used:
            base = f"{base}_{i + 1}"
        used.add(base)
        group_var = names["reinforce_by_index"][i]
        lines.append(f"\tBuildingGroup {group_var} = CreateBuildingGroup(Player[{group.player}]);")
        lines.append(f"\t{names['reinforce_save_by_index'][i]} = {group_var}.Id();")
        for uid in group.unit_ids:
            unit_var = unit_var_by_uid.get(uid)
            if unit_var:
                lines.append(f"\t{group_var}.TakeUnit({unit_var});")
        for target_index, target in enumerate(group.targets):
            target_expr = _group_getter_by_name(names, target.group_name)
            if target_expr is not None:
                target_var = f"{base}Target_{target_index}_{_cpp_ident(target.group_name)}"
                lines.append(f"\tScGroup& {target_var} = {target_expr};")
                lines.append(f"\t{group_var}.RecordVehReinforceGroup({target_var}, {target.priority});")
    return lines


def _trig_fn_name(name: str) -> str:
    """Sanitisierter, eindeutiger C-Funktionsname fuer einen Trigger-Callback.

    Sanitized, unique C function name for a trigger callback.
    """
    s = "".join(c if c.isalnum() else "_" for c in name).strip("_") or "Trig"
    return "TrigCB_" + s


def _trigger_create_expr(t) -> str:
    """C++-Ausdruck, der den Trigger erzeugt (ohne Semikolon).

    C++ expression that creates the trigger (without trailing semicolon).
    """
    os = 1 if t.one_shot else 0
    cb = f'"{_trig_fn_name(t.name)}"'
    k = t.condition
    if k == "time":
        return f"CreateTimeTrigger(1, {os}, {t.marks}, {cb})"
    if k == "point":
        return f"CreatePointTrigger(1, {os}, {t.player}, {_xypos(t.x, t.y)}, {cb})"
    if k == "rect":
        return f"CreateRectTrigger(1, {os}, {t.player}, {_xypos(t.x, t.y)}, {t.width}, {t.height}, {cb})"
    if k == "buildingCount":
        return f"CreateBuildingCountTrigger(1, {os}, {t.player}, {t.count}, {t.compare}, {cb})"
    if k == "vehicleCount":
        return f"CreateVehicleCountTrigger(1, {os}, {t.player}, {t.count}, {t.compare}, {cb})"
    if k == "research":
        return f"CreateResearchTrigger(1, {os}, {t.tech_id}, {t.player}, {cb})"
    if k == "resource":
        return f"CreateResourceTrigger(1, {os}, {t.resource}, {t.amount}, {t.player}, {t.compare}, {cb})"
    if k == "operational":
        return f"CreateOperationalTrigger(1, {os}, {t.player}, {t.building}, {t.count}, {t.compare}, {cb})"
    return f"CreateTimeTrigger(1, {os}, {t.marks}, {cb})"


_CMP_OP = {"cmpEqual": "==", "cmpLowerEqual": "<=", "cmpGreaterEqual": ">=",
           "cmpLower": "<", "cmpGreater": ">"}
_RES_METHOD = {"resCommonOre": "Ore()", "resRareOre": "RareOre()", "resFood": "FoodStored()",
               "resKids": "Kids()", "resWorkers": "Workers()", "resScientists": "Scientists()"}


def _condition_code(c, var):
    """Gibt (setup_zeilen, bool_ausdruck) fuer eine ActionCondition zurueck.

    Returns (setup_lines, bool_expression) for an ActionCondition.
    """
    op = _CMP_OP.get(c.compare, ">=")
    k = c.kind
    if k == "playerResource":
        return [], f"(Player[{c.player}].{_RES_METHOD.get(c.resource, 'Ore()')} {op} {c.value})"
    if k == "hasTech":
        return [], f"(Player[{c.player}].HasTechnology({c.tech_id}) != 0)"
    if k == "buildingAtLocation":
        return ([
            f"\tbool {var} = false;",
            f"\t{{ UnitEx _cur; LOCATION _loc = {_mkxy(c.x, c.y)}; PlayerBuildingEnum _e({c.player}, {c.building_type});",
            f"\t  while (_e.GetNext(_cur)) {{ if (_cur.Location() == _loc) {{ {var} = true; break; }} }} }}",
        ], var)
    if k == "buildingCount":
        return ([
            f"\tint {var}_n = 0; {{ UnitEx _cur; PlayerBuildingEnum _e({c.player}, {c.building_type}); while (_e.GetNext(_cur)) {var}_n++; }}",
            f"\tbool {var} = ({var}_n {op} {c.value});",
        ], var)
    if k == "unitDamage":
        return ([
            f"\tbool {var} = false;",
            f"\t{{ UnitEx _cur; LOCATION _loc = {_mkxy(c.x, c.y)}; PlayerBuildingEnum _e({c.player}, {c.building_type});",
            f"\t  while (_e.GetNext(_cur)) {{ if (_cur.Location() == _loc) {{ {var} = (_cur.GetDamage() {op} {c.value}); break; }} }} }}",
        ], var)
    return [], "true"


def _build_action_conditions(action, ai):
    """Gibt (setup_zeilen, kombinierter_bool_ausdruck) fuer die Bedingungen einer Aktion.

    Returns (setup_lines, combined_bool_expression) for an action's conditions.
    """
    setups, exprs = [], []
    for ci, c in enumerate(getattr(action, "conditions", None) or []):
        s, e = _condition_code(c, f"cond_{ai}_{ci}")
        if getattr(c, "negate", False):
            e = f"!({e})"
        setups.extend(s)
        exprs.append(e)
    joiner = " || " if getattr(action, "condition_logic", "and") == "or" else " && "
    return setups, (joiner.join(exprs) if exprs else "true")


def _any_create_unit(actions):
    for a in actions:
        if a.kind == "createUnit":
            return True
        if a.kind == "if" and (_any_create_unit(a.then_actions) or _any_create_unit(a.else_actions)):
            return True
    return False


def _emit_action_list(actions, ctx):
    lines = []
    for a in actions:
        lines.extend(_emit_action(a, ctx))
    return lines


def _emit_action(a, ctx):
    """Erzeugt die C++-Zeilen fuer eine Aktion (Basis-Einrueckung ein Tab).

    Produces the C++ lines for one action (base indentation is one tab).
    """
    uid = ctx["counter"][0]
    ctx["counter"][0] += 1
    if a.kind == "if":
        setup, combined = _build_action_conditions(a, uid)
        out = list(setup)
        out.append(f"\tif ({combined}) {{")
        out += ["\t" + ln for ln in _emit_action_list(a.then_actions, ctx)]
        out.append("\t}")
        else_lines = _emit_action_list(a.else_actions, ctx)
        if else_lines:
            out.append("\telse {")
            out += ["\t" + ln for ln in else_lines]
            out.append("\t}")
        return out
    act = _emit_single_action(a, uid, ctx)
    if getattr(a, "conditions", None):
        setup, combined = _build_action_conditions(a, uid)
        out = list(setup)
        out.append(f"\tif ({combined}) {{")
        out += ["\t" + ln for ln in act]
        out.append("\t}")
        return out
    return act


def _emit_single_action(a, uid, ctx):
    """Erzeugt die Zeilen einer einfachen (nicht-if) Aktion als Liste.

    Produces the lines of a simple (non-if) action as a list.
    """
    names = ctx["names"]
    extra_blocks = ctx["extra_blocks"]
    trig_fn = ctx["trig_fn"]
    act: list[str] = []
    if a.kind == "message":
        act.append(f"\tAddGameMessage({_cpp_string(a.text)});")
    elif a.kind == "createUnit":
        act.append(f"\tTethysGame::CreateUnit(u, {a.unit_type}, {_mkxy(a.x, a.y)}, {a.player}, {a.weapon_type}, 0);")
    elif a.kind == "createTrigger":
        tgt = ctx["by_name"].get(a.target)
        if tgt is not None:
            act.append(f"\t{_trigger_create_expr(tgt)};")
    elif a.kind == "recordBuilding":
        group_expr = names["building_getter_by_name"].get(a.group_name)
        if group_expr is not None:
            loc = f"recordLoc_{uid}_{_cpp_ident(a.group_name)}"
            group_var = f"recordGroup_{uid}_{_cpp_ident(a.group_name)}"
            act.append(f"\tBuildingGroup& {group_var} = {group_expr};")
            act.append(f"\tLOCATION {loc} = {_mkxy(a.x, a.y)};")
            act.append(f"\t{group_var}.RecordBuilding({loc}, {a.building_type}, mapNone);")
    elif a.kind == "recordTube":
        group_expr = names["building_getter_by_name"].get(a.group_name)
        if group_expr is not None:
            group_var = f"recordGroup_{uid}_{_cpp_ident(a.group_name)}"
            act.append(f"\tBuildingGroup& {group_var} = {group_expr};")
            act.append(f"\tRecordTubeLine({group_var}, {_mkxy(a.x, a.y)}, {_mkxy(a.x2, a.y2)});")
    elif a.kind == "recordWall":
        group_expr = names["building_getter_by_name"].get(a.group_name)
        if group_expr is not None:
            group_var = f"recordGroup_{uid}_{_cpp_ident(a.group_name)}"
            helper = {
                "mapLavaWall": "RecordLavaWallLine",
                "mapMicrobeWall": "RecordMicrobeWallLine",
            }.get(a.wall_type, "RecordWallLine")
            act.append(f"\tBuildingGroup& {group_var} = {group_expr};")
            act.append(f"\t{helper}({group_var}, {_mkxy(a.x, a.y)}, {_mkxy(a.x2, a.y2)});")
    elif a.kind == "setTargCount":
        target_expr = _group_getter_by_name(names, a.group_name)
        source_expr = names["reinforce_getter_by_name"].get(a.source_group_name)
        target_type = names["group_type_by_name"].get(a.group_name)
        allowed_units = SET_TARG_ALLOWED_UNITS.get(target_type, set())
        if target_expr is not None and a.unit_type in allowed_units:
            target_var = f"targetGroup_{uid}_{_cpp_ident(a.group_name)}"
            act.append(f"\tScGroup& {target_var} = {target_expr};")
            if source_expr is not None:
                source_var = f"sourceGroup_{uid}_{_cpp_ident(a.source_group_name)}"
                act.append(f"\tBuildingGroup& {source_var} = {source_expr};")
                act.append(f"\t{source_var}.RecordVehReinforceGroup({target_var}, {a.reinforce_priority});")
            act.append(f"\t{target_var}.SetTargCount({a.unit_type}, {a.weapon_type}, {a.target_count});")
    elif a.kind == "startMiningOperation":
        # Mehrstufige Laufzeit-Operation: Mine + Smelter beim Builder vormerken,
        # dessen Ziel-Anzahlen setzen, dann operative Trigger verketten
        # (Smelter fertig -> danach Mine fertig). Im Ready-Callback schliesslich
        # die MiningGroup einrichten (Setup) und die Trucks zuteilen (TakeUnit).
        # Multi-stage runtime operation: record mine + smelter on the builder,
        # set its target counts, then chain operational triggers (smelter ready
        # -> then mine ready). In the ready callback, finally Setup the
        # MiningGroup and TakeUnit the trucks.
        group_expr = names["building_getter_by_name"].get(a.group_name)
        mining_expr = names["mining_getter_by_name"].get(a.mining_group_name)
        mining_group_spec = ctx["mining_group_by_name"].get(a.mining_group_name)
        if group_expr is not None and mining_expr is not None and mining_group_spec is not None:
            mine_type, smelter_type = MINING_OPERATION_TYPES.get(
                a.ore_type, MINING_OPERATION_TYPES["common"])
            builder_group = ctx["building_group_by_name"].get(a.group_name)
            op_player = builder_group.player if builder_group else mining_group_spec.player
            base = f"miningOp_{uid}_{_cpp_ident(a.group_name)}"
            rx2 = a.rect_x + a.rect_width - 1
            ry2 = a.rect_y + a.rect_height - 1
            act.append(f"\tBuildingGroup& {base}Builder = {group_expr};")
            act.append(f"\tLOCATION {base}Mine = {_mkxy(a.x, a.y)};")
            act.append(f"\tLOCATION {base}Smelter = {_mkxy(a.x2, a.y2)};")
            act.append(f"\t{base}Builder.RecordBuilding({base}Mine, {mine_type}, mapNone);")
            act.append(f"\t{base}Builder.RecordBuilding({base}Smelter, {smelter_type}, mapNone);")
            act.append(f"\t{base}Builder.SetTargCount(mapRoboMiner, mapNone, 1);")
            act.append(f"\t{base}Builder.SetTargCount({mine_type}, mapNone, 1);")
            act.append(f"\t{base}Builder.SetTargCount({smelter_type}, mapNone, 1);")
            mine_baseline = sum(1 for u in ctx["units"] if u.unit_type == mine_type and u.player == op_player)
            smelter_baseline = sum(1 for u in ctx["units"] if u.unit_type == smelter_type and u.player == op_player)
            smelter_cb = f"{trig_fn}_SmelterReady_{uid}"
            ready_cb = f"{trig_fn}_MineReady_{uid}"
            act.append(
                f"\tCreateOperationalTrigger(1, 1, {op_player}, {smelter_type}, "
                f"{smelter_baseline + 1}, cmpGreaterEqual, \"{smelter_cb}\");")
            extra_blocks.append(
                f"Export void {smelter_cb}()\n{{\n"
                f"\tCreateOperationalTrigger(1, 1, {op_player}, {mine_type}, "
                f"{mine_baseline + 1}, cmpGreaterEqual, \"{ready_cb}\");\n}}")
            ready = [
                f"\tMiningGroup& {base}Group = {mining_expr};",
                f"\tLOCATION {base}MineLoc = {_mkxy(a.x, a.y)};",
                f"\tLOCATION {base}SmelterLoc = {_mkxy(a.x2, a.y2)};",
                f"\tMAP_RECT {base}Rect = {_mkrect(a.rect_x, a.rect_y, rx2, ry2)};",
                f"\tUnitEx {base}MineUnit, {base}SmelterUnit, {base}Cur;",
                f"\tPlayerBuildingEnum {base}MineEnum({op_player}, {mine_type});",
                f"\twhile ({base}MineEnum.GetNext({base}Cur)) {{",
                f"\t\tif ({base}Cur.Location() == {base}MineLoc) {{ {base}MineUnit = {base}Cur; break; }}",
                f"\t}}",
                f"\tPlayerBuildingEnum {base}SmelterEnum({op_player}, {smelter_type});",
                f"\twhile ({base}SmelterEnum.GetNext({base}Cur)) {{",
                f"\t\tif ({base}Cur.Location() == {base}SmelterLoc) {{ {base}SmelterUnit = {base}Cur; break; }}",
                f"\t}}",
                f"\t{base}Group.Setup({base}MineUnit, {base}SmelterUnit, {base}Rect);",
            ]
            taken_trucks = 0
            for truck_index, tuid in enumerate(mining_group_spec.truck_ids):
                truck_expr = names["unit_getter_by_uid"].get(tuid)
                if truck_expr is not None:
                    ready.append(f"\tUnitEx& {base}Truck_{truck_index} = {truck_expr};")
                    ready.append(f"\t{base}Group.TakeUnit({base}Truck_{truck_index});")
                    taken_trucks += 1
            target_trucks = a.truck_count if getattr(a, "truck_count", 0) > 0 else max(1, taken_trucks)
            ready.append(f"\t{base}Group.SetTargCount(mapCargoTruck, mapNone, {target_trucks});")
            extra_blocks.append(f"Export void {ready_cb}()\n{{\n" + "\n".join(ready) + "\n}")
    elif a.kind == "assignToGroup":
        # 10-Tik-Polling-Zeittrigger, der nach dem Gebaeude bei (x,y) sucht;
        # sobald es gefunden ist, wird die Einheit der Gruppe hinzugefuegt und
        # der Trigger beendet sich selbst per Destroy().
        # A 10-tick polling time-trigger that scans for the building at (x,y);
        # once found it adds the unit to the group and Destroy()s its own
        # trigger.
        group_expr = _group_getter_by_name(names, a.group_name)
        if group_expr is not None:
            base = f"assign_{uid}_{_cpp_ident(a.group_name)}"
            check_cb = f"{trig_fn}_AssignCheck_{uid}"
            save_expr = names["assign_save_by_id"][id(a)]
            getter = names["assign_getter_by_id"][id(a)]
            act.append(f"\tTrigger {base}Check = CreateTimeTrigger(1, 0, 10, \"{check_cb}\");")
            act.append(f"\t{save_expr} = {base}Check.Id();")
            extra_blocks.append(
                f"Export void {check_cb}()\n{{\n" + "\n".join([
                    f"\tLOCATION {base}Loc = {_mkxy(a.x, a.y)};",
                    f"\tUnitEx {base}Found, {base}Cur;",
                    f"\tint {base}Ok = 0;",
                    f"\tPlayerBuildingEnum {base}Enum({a.player}, {a.building_type});",
                    f"\twhile ({base}Enum.GetNext({base}Cur)) {{",
                    f"\t\tif ({base}Cur.Location() == {base}Loc) {{ {base}Found = {base}Cur; {base}Ok = 1; break; }}",
                    f"\t}}",
                    f"\tif ({base}Ok) {{",
                    f"\t\tScGroup& {base}Group = {group_expr};",
                    f"\t\t{base}Group.TakeUnit({base}Found);",
                    f"\t\t{getter}.Destroy();",
                    f"\t}}",
                ]) + "\n}")
    return act


def _gen_callbacks(mission, names: dict) -> str:
    """Erzeugt die Export-Callback-Funktionen aller Trigger (rekursiv fuer if-Bloecke).

    Generates the Export callback functions for all triggers (recursively for
    if blocks).
    """
    by_name = {t.name: t for t in mission.triggers}
    mining_group_by_name = {group.name: group for group in mission.mining_groups}
    building_group_by_name = {group.name: group for group in mission.building_groups}
    blocks = []
    extra_blocks: list[str] = []
    for t in mission.triggers:
        ctx = {
            "names": names, "by_name": by_name,
            "mining_group_by_name": mining_group_by_name,
            "building_group_by_name": building_group_by_name,
            "extra_blocks": extra_blocks, "counter": [0],
            "trig_fn": _trig_fn_name(t.name), "units": mission.units,
        }
        body: list[str] = []
        if _any_create_unit(t.actions):
            body.append("\tUnitEx u;")
        body += _emit_action_list(t.actions, ctx)
        if not body:
            # no actions
            body.append("\t// keine Aktionen")
        blocks.append(f"Export void {_trig_fn_name(t.name)}()\n{{\n" + "\n".join(body) + "\n}")
    return "\n\n".join(blocks + extra_blocks)


def _gen_condition(cond, is_victory: bool, counter: list[int]) -> list[str]:
    """Erzeugt C++ fuer eine Sieg-/Niederlage-Bedingung.

    Trigger werden deaktiviert (bEnabled=0) erzeugt; die Create*Condition-
    Funktion aktiviert sie. Helper-Bedingungen (lastStanding/starship/noCC)
    brauchen keinen Trigger und keinen ScriptGlobal-Zustand -> Save-Struktur
    bleibt unveraendert.

    Generates C++ for a victory/defeat condition.

    Triggers are created disabled (bEnabled=0); the Create*Condition function
    enables them. Helper conditions (lastStanding/starship/noCC) need no
    trigger and no ScriptGlobal state -> the save struct stays unchanged.
    """
    k = cond.kind
    # Helper-Bedingungen ohne eigenen Trigger
    # Helper conditions without their own trigger
    if k == "lastStanding":
        return ["\tCreateLastOneStandingVictoryCondition();"]
    if k == "starship":
        return ["\tCreateStarshipVictoryCondition();"]
    if k == "noCC":
        return [f"\tCreateNoCommandCenterFailureCondition({cond.player});"]

    # Trigger-basierte Bedingungen
    # Trigger-based conditions
    n = counter[0]
    counter[0] += 1
    var = f"cond{n}"
    # bEnabled=1: der Trigger muss aktiviert sein, sonst feuert die Bedingung nie.
    # bEnabled=1: the trigger must be enabled, otherwise the condition never fires.
    if k == "time":
        trig = f'CreateTimeTrigger(1, 1, {cond.marks}, "NoResponseToTrigger")'
    elif k == "buildingCount":
        trig = f'CreateBuildingCountTrigger(1, 1, {cond.player}, {cond.count}, {cond.compare}, "NoResponseToTrigger")'
    elif k == "vehicleCount":
        trig = f'CreateVehicleCountTrigger(1, 1, {cond.player}, {cond.count}, {cond.compare}, "NoResponseToTrigger")'
    elif k == "research":
        trig = f'CreateResearchTrigger(1, 1, {cond.tech_id}, {cond.player}, "NoResponseToTrigger")'
    elif k == "resource":
        trig = f'CreateResourceTrigger(1, 1, {cond.resource}, {cond.amount}, {cond.player}, {cond.compare}, "NoResponseToTrigger")'
    elif k == "operational":
        trig = f'CreateOperationalTrigger(1, 1, {cond.player}, {cond.building}, {cond.count}, {cond.compare}, "NoResponseToTrigger")'
    else:
        return [f"\t// Unbekannte Bedingung: {k}"]

    wrapper = "CreateVictoryCondition" if is_victory else "CreateFailureCondition"
    last_arg = _cpp_string(cond.objective) if is_victory else '""'
    return [
        f"\tTrigger {var} = {trig};",
        f"\t{wrapper}(1, 0, {var}, {last_arg});",
    ]


def generate_levelmain(mission: Mission) -> str:
    """Erzeugt den kompletten Inhalt von LevelMain.cpp.

    Generates the complete contents of LevelMain.cpp.
    """
    names = _global_names(mission)
    details = ", ".join([
        _cpp_string(mission.name),
        _cpp_string(mission.map),
        _cpp_string(mission.tech_tree),
        f"MissionTypes::{mission.type.name}",
        str(mission.num_players),
    ])

    callbacks = _gen_callbacks(mission, names)
    callbacks_block = ("\n\n" + callbacks) if callbacks else ""
    helpers = _gen_global_helpers(names)
    helpers_block = ("\n\n" + helpers) if helpers else ""

    return f"""// === AUTO-GENERIERT vom Python-Codegen -- nicht von Hand editieren ===
#include <Outpost2DLL/Outpost2DLL.h>
#include <OP2Helper/OP2Helper.h>
#include <HFL/Source/HFL.h>

ExportLevelDetails({details})

{_gen_script_global(names)}
ExportSaveLoadData(scriptGlobal);{helpers_block}

Export int InitProc()
{{
{_gen_init_proc(mission, names)}
}}

Export void AIProc() {{ }}

Export void NoResponseToTrigger() {{ }}{callbacks_block}
"""


if __name__ == "__main__":
    from demo_mission import build_demo
    print(generate_levelmain(build_demo()))
