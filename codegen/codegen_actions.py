"""Emission der Trigger-Aktionen (inkl. if/forEach-Schleifen, Wellen, Patrouillen).

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
    _compare, _cpp_string, _expr_or_int, _ident, _line_tiles, _loc_expr,
    _rect, _resource, _strip_map, _visible_expr, _xy, _xypos, _xypos_expr,
    _validate_cpp_expr, mapid,
)


_VEHICLE_MAPIDS = {
    "mapCargoTruck", "mapConVec", "mapEarthworker", "mapEvacuationTransport",
    "mapGeoCon", "mapLynx", "mapPanther", "mapRepairVehicle", "mapRoboDozer",
    "mapRoboMiner", "mapRoboSurveyor", "mapScorpion", "mapSpider", "mapTiger",
    "mapScout",
}




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
        return _loop_var(depth) if depth >= 1 else None
    if ref == "<loop:outer>":
        # In einer einfachen (nicht verschachtelten) Schleife IST die
        # "aeussere" Schleife die aktuelle -- sonst fiele der Befehl trotz
        # klarer Nutzerabsicht stillschweigend weg.
        # In a plain (non-nested) loop the "outer" loop IS the current one --
        # otherwise the command would silently vanish despite clear intent.
        if depth >= 2:
            return _loop_var(depth - 1)
        return _loop_var(depth) if depth >= 1 else None
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




# ---------------------------------------------------------------------------
# TriggerActions: emit C++ statements (recursive for if/then/else).
# ---------------------------------------------------------------------------

def _text_with_vars(text: str, ctx: dict) -> tuple[str, list[str]]:
    """$variablenname im Text -> snprintf-Format (%d) + Argumentliste.

    Nur Namen, die als Missions-Variable existieren, werden ersetzt --
    beliebige andere $-Vorkommen bleiben woertlich erhalten. Ohne Treffer
    kommt eine leere Argumentliste zurueck (Aufrufer emittiert das Literal).

    $varname in the text -> snprintf format (%d) + argument list. Only
    names that exist as mission variables are substituted -- any other $
    occurrences stay verbatim. With no hits the argument list is empty
    (caller emits the plain literal).
    """
    names = ctx.get("var_names") or set()
    args: list[str] = []
    # Literal-% zuerst schuetzen, dann Variablen ersetzen.
    # Protect literal % first, then substitute variables.
    fmt_text = (text or "").replace("%", "%%")

    def _sub(m):
        n = m.group(1)
        if n in names:
            args.append(f"(int){n}")
            return "%d"
        return m.group(0)

    import re as _re
    fmt_text = _re.sub(r"\$(\w+)", _sub, fmt_text)
    if not args:
        return "", []
    return _cpp_string(fmt_text), args


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
        target = int(getattr(action, "msg_player", -1))
        fmt, args = _text_with_vars(action.text, ctx)
        if not args:
            return [f"{indent}AddGameMessage({_cpp_string(action.text)}, "
                    f"sndMessage2, {target});"]
        return [
            f"{indent}{{",
            f"{indent}    char _msg[240];",
            f"{indent}    snprintf(_msg, sizeof(_msg), {fmt}, {', '.join(args)});",
            f"{indent}    AddGameMessage(_msg, sndMessage2, {target});",
            f"{indent}}}",
        ]

    if k == "customCode":
        # Handgeschriebener Code, woertlich uebernommen; eigener {}-Scope,
        # damit lokale Variablen keine Nachbar-Aktionen stoeren.
        # Hand-written code taken verbatim; its own {} scope so locals
        # don't clash with neighbouring actions.
        lines = [f"{indent}{{"]
        for cl in (getattr(action, "code", "") or "").splitlines():
            lines.append(f"{indent}    {cl}" if cl.strip() else "")
        lines.append(f"{indent}}}")
        return lines

    if k == "custom":
        # Designer-Aktion: Code-Template mit $param-Platzhaltern.
        # Designer action: code template with $param placeholders.
        defs = {d.get("name", ""): d for d in (ctx.get("custom_actions") or [])}
        cdef = defs.get(getattr(action, "custom_name", "") or "")
        if not cdef:
            return [f"{indent}// TODO custom action "
                    f"[{getattr(action, 'custom_name', '?')}] not defined"]
        code = cdef.get("code", "") or ""
        args = getattr(action, "custom_args", None) or {}
        # Laengere Namen zuerst ersetzen ($count vor $c).
        # Substitute longer names first ($count before $c).
        params = sorted(cdef.get("params") or [],
                        key=lambda p: -len(p.get("name", "")))
        for p in params:
            pname = p.get("name", "")
            if not pname:
                continue
            ptype = p.get("type", "int")
            v = args.get(pname, p.get("default"))
            if ptype in ("int", "player"):
                try:
                    rep = str(int(v))
                except (TypeError, ValueError):
                    rep = "0"
            elif ptype == "text":
                rep = _cpp_string("" if v is None else str(v))
            elif ptype == "unit_type":
                rep = mapid(str(v or "mapNone"))
            elif ptype == "position":
                pos = v if isinstance(v, dict) else {}
                rep = _xy(int(pos.get("x", 0)), int(pos.get("y", 0)))
            else:
                rep = "0"
            code = code.replace(f"${pname}", rep)
        lines = [f"{indent}{{"]
        for cl in code.splitlines():
            lines.append(f"{indent}    {cl}" if cl.strip() else "")
        lines.append(f"{indent}}}")
        return lines

    if k == "showDialog":
        # Echte Dialogbox ueber dem Spiel (HFL TethysGameEx::MsgBox).
        # Blockiert bis OK -- fuer Story-Dialoge in Einzelspieler-Missionen.
        # Real dialog box over the game (HFL TethysGameEx::MsgBox).
        # Blocks until OK -- for story dialogs in single-player missions.
        cap = (getattr(action, "caption", "") or "").strip() \
            or ctx.get("mission_name", "Outpost 2")
        fmt, args = _text_with_vars(action.text, ctx)
        if not args:
            return [f"{indent}TethysGameEx::MsgBox(NULL, {_cpp_string(action.text)}, "
                    f"{_cpp_string(cap)}, MB_OK | MB_ICONINFORMATION);"]
        return [
            f"{indent}{{",
            f"{indent}    char _msg[512];",
            f"{indent}    snprintf(_msg, sizeof(_msg), {fmt}, {', '.join(args)});",
            f"{indent}    TethysGameEx::MsgBox(NULL, _msg, {_cpp_string(cap)}, "
            f"MB_OK | MB_ICONINFORMATION);",
            f"{indent}}}",
        ]

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
            if bt == "mapRareOreMine":
                # Rare-Ore-Mine nie direkt bauen (Coding 101 W9): als
                # CommonOreMine rekordieren -- auf einem Rare-Beacon macht
                # die Engine daraus die Rare-Variante.
                # Never build a rare ore mine directly (Coding 101 W9):
                # record a CommonOreMine -- on a rare beacon the engine
                # turns it into the rare variant.
                bt = "mapCommonOreMine"
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
        if cmd == "produce":
            # HFL DoProduce: kann -- anders als Unit::DoDevelop -- auch
            # Lynx/Panther/Tiger mit Waffe bauen; am Spaceport landen
            # SULV/RLV/EMP Missile direkt auf der Startrampe.
            # HFL DoProduce: unlike Unit::DoDevelop it can also build
            # Lynx/Panther/Tiger with a weapon; at the Spaceport,
            # SULV/RLV/EMP Missile end up on the launch pad directly.
            ut = mapid(getattr(action, "unit_type", "") or "mapSULV")
            wt = getattr(action, "weapon_type", "") or "mapNone"
            wt = mapid(wt) if wt != "mapNone" else "mapNone"
            return [f"{indent}{uvar}.DoProduce({ut}, {wt});"]
        if cmd == "launch":
            # DoLaunch erwartet PIXEL-Koordinaten (Kachel * 32, +16 =
            # Kachelmitte) -- gleiche Offset-Logik wie XYPos/MkXY.
            # DoLaunch expects PIXEL coordinates (tile * 32, +16 = tile
            # centre) -- same offset logic as XYPos/MkXY.
            return [
                f"{indent}{{",
                f"{indent}    LOCATION _lp = {pos};",
                f"{indent}    {uvar}.DoLaunch(_lp.x * 32 + 16, _lp.y * 32 + 16, 1);",
                f"{indent}}}",
            ]
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
        # Makro v2: schaltet den Reparatur-Scan scharf; das eigentliche
        # Pruefen/Beauftragen macht der missionsweite Reparatur-Timer
        # (Zonen, Schwellen-Hysterese, Fahrzeug-Praeferenz).
        # Macro v2: arms the repair scan; the actual checking/tasking runs
        # in the mission-wide repair timer (zones, threshold hysteresis,
        # vehicle preference).
        armed_var = ctx.get("repair_action_vars", {}).get(id(action))
        if not armed_var:
            return [f"{indent}// TODO repairBuildings: armed flag not declared"]
        return [f"{indent}{armed_var} = true;"]

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

    if k in ("addVictory", "addDefeat"):
        # Zur Laufzeit eine neue Sieg-/Niederlage-Bedingung registrieren --
        # derselbe Baukasten (_emit_condition/_trigger_call) wie in InitProc,
        # abgesichert ueber ein g_save-Flag (auch unter wiederholenden
        # Triggern wird die Bedingung nur EINMAL hinzugefuegt und ueberlebt
        # Save/Load, weil die Engine Trigger selbst persistiert).
        # Register a new victory/defeat condition at runtime -- same builder
        # (_emit_condition/_trigger_call) as in InitProc, guarded by a g_save
        # flag (even under repeating triggers the condition is added only
        # ONCE and survives save/load because the engine persists triggers
        # itself).
        from codegen_triggers import _emit_condition  # spaeter Import: zyklische Modulabhaengigkeit
        spec = dict(getattr(action, "condition_spec", None) or {})
        spec.setdefault("kind", "time")
        try:
            cond = Condition(**spec)
        except TypeError:
            return [f"{indent}// TODO {k}: invalid condition_spec {spec!r}"]
        inner = _emit_condition(cond, k == "addVictory", ctx.get("mission"), ctx)
        done_var = ctx.get("addcond_action_vars", {}).get(id(action))
        if not done_var:
            return [f"{indent}{line.lstrip()}" for line in inner]
        lines = [f"{indent}if (!{done_var}) {{",
                 f"{indent}    {done_var} = true;"]
        lines += [f"{indent}    {line.lstrip()}" for line in inner]
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
    (bekanntes Engine-Verhalten, siehe Wiki) -- beide muessen den Aufruf
    ueberleben, deshalb `static`. Jede Emissionsstelle hat ihren eigenen
    Block-Scope und damit ihre eigene statische Kopie.

    PatrolRoute setup for a FightGroup: waypoint array (always terminated
    with x = -1, see Structs.h) + SetPatrolMode + DoPatrolOnly.

    IMPORTANT: The engine KEEPS the pointer to the route and waypoint list
    (known engine behaviour, see wiki) -- both must outlive the call, hence
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
# Fahrzeug-map_ids: entscheidet, ob eine "type"-Quelle den Fahrzeug- oder den
# Gebaeude-Enumerator braucht (PlayerUnitEnum liefert KEINE Gebaeude!).
# Vehicle map_ids: decides whether a "type" source needs the vehicle or the
# building enumerator (PlayerUnitEnum does NOT yield buildings!).




def _building_pass_prologue(ev: str, player_expr: str, depth: int,
                            with_vehicles: bool) -> tuple[list[str], str, int]:
    """Prolog + while-Bedingung fuer 'alle Gebaeude eines Spielers'.

    PlayerBuildingEnum kennt KEIN Wildcard -- mapAny liefert schlicht
    nichts (in-game bestaetigt). Daher eine Typ-Schleife ueber den
    zusammenhaengenden Gebaeude-Block mapCommonOreMine..mapTokamak, pro
    Typ ein frischer typgenauer Enumerator (der ist in-game bewaehrt).
    Mit with_vehicles laeuft davor eine Extra-Runde ueber den
    Fahrzeug-Enumerator (der Gebaeude-Enumerator bekommt in dieser Runde
    einen Fahrzeugtyp als Filter und bleibt damit garantiert leer).

    PlayerBuildingEnum has NO wildcard -- mapAny simply yields nothing
    (confirmed in-game). So we loop over the contiguous building block
    mapCommonOreMine..mapTokamak with a fresh type-exact enumerator per
    type (that one is battle-tested in-game). With with_vehicles an extra
    leading pass runs the vehicle enumerator (the building enumerator gets
    a vehicle type as filter in that pass, guaranteed empty).
    """
    bt = f"_bt{depth}"
    start = f"(int)mapCommonOreMine{' - 1' if with_vehicles else ''}"
    pro = []
    if with_vehicles:
        pro.append(f"PlayerVehicleEnum {ev}v({player_expr});")
    pro.append(f"for (int {bt} = {start}; {bt} <= (int)mapTokamak; ++{bt}) {{")
    if with_vehicles:
        pro.append(f"    PlayerBuildingEnum {ev}b({player_expr}, "
                   f"{bt} < (int)mapCommonOreMine ? mapCargoTruck : (map_id){bt});")
        cond = (f"({bt} < (int)mapCommonOreMine ? "
                f"{ev}v.GetNext(@U@) : {ev}b.GetNext(@U@))")
    else:
        pro.append(f"    PlayerBuildingEnum {ev}b({player_expr}, (map_id){bt});")
        cond = f"{ev}b.GetNext(@U@)"
    return pro, cond, 1




def _for_each_prologue(action, depth: int) -> tuple[list[str], str, list[str], int]:
    """Liefert (Prolog, while-Bedingung mit @U@-Platzhalter, Filter, Klammern).

    WICHTIG: PlayerUnitEnum/PlayerVehicleEnum enumerieren nur Fahrzeuge --
    Gebaeude kommen ausschliesslich ueber den typgenauen PlayerBuildingEnum
    (siehe _building_pass_prologue).
    IMPORTANT: PlayerUnitEnum/PlayerVehicleEnum only enumerate vehicles --
    buildings only come via the type-exact PlayerBuildingEnum (see
    _building_pass_prologue).
    """
    src = getattr(action, "enum_source", "rect") or "rect"
    p = int(getattr(action, "player", 0))
    ev = f"_e{depth}"
    if src == "player":
        pro, cond, braces = _building_pass_prologue(ev, str(p), depth,
                                                    with_vehicles=True)
        return pro, cond, [], braces
    if src == "playerVehicles":
        return [f"PlayerVehicleEnum {ev}({p});"], f"{ev}.GetNext(@U@)", [], 0
    if src == "playerBuildings":
        pro, cond, braces = _building_pass_prologue(ev, str(p), depth,
                                                    with_vehicles=False)
        return pro, cond, [], braces
    if src in ("all", "type"):
        # Alle Spieler durchlaufen (die Engine hat keinen globalen Enumerator).
        # Iterate all players (the engine has no global enumerator).
        pv = f"_pi{depth}"
        ut = getattr(action, "unit_type", "") or "mapAny"
        head = f"for (int {pv} = 0; {pv} < TethysGame::NoPlayers(); ++{pv}) {{"
        if src == "type" and ut not in ("mapAny", "mapNone"):
            if ut in _VEHICLE_MAPIDS:
                pro = [head, f"    PlayerVehicleEnum {ev}({pv});"]
                return pro, f"{ev}.GetNext(@U@)", \
                    [f"unit.GetType() == {mapid(ut)}"], 1
            pro = [head, f"    PlayerBuildingEnum {ev}({pv}, {mapid(ut)});"]
            return pro, f"{ev}.GetNext(@U@)", [], 1
        inner_pro, cond, _ = _building_pass_prologue(ev, pv, depth,
                                                     with_vehicles=True)
        pro = [head] + [f"    {l}" for l in inner_pro]
        return pro, cond, [], 2
    # default: rect
    rect = _rect(action.x, action.y, action.x2, action.y2)
    return ([f"MAP_RECT _rr{depth} = {rect};",
             f"InRectEnumerator {ev}(_rr{depth});"],
            f"{ev}.GetNext(@U@)", [], 0)




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
    # Autoren-Kommentar der Aktion vor deren Code stellen (auch verschachtelt).
    # Endender Backslash wuerde die naechste Codezeile in den Kommentar ziehen
    # (Zeilen-Splice) -> abschneiden.
    # Put the action's author comment above its code (also when nested).
    # A trailing backslash would splice the next code line into the comment
    # -> strip it.
    _comment_lines = [f"{indent}// {cl.strip().rstrip(chr(92)).strip()}"
                      for cl in ((getattr(action, "comment", "") or "").strip()).splitlines()]

    if action.kind == "if":
        out: list[str] = list(_comment_lines)
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
            pro, cond, filters, pro_braces = _for_each_prologue(action, inner_depth)
            out.append(f"{indent}{{")
            for l in pro:
                out.append(f"{indent}    {l}")
            pro_pad = "    " * pro_braces
            out.append(f"{indent}    {pro_pad}UnitEx {var};")
            out.append(f"{indent}    {pro_pad}while ({cond.replace('@U@', var)}) {{")
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
        return _comment_lines + _emit_action_body(action, indent, ctx, depth)
    body = _emit_action_body(action, indent + "    ", ctx, depth)
    return [*_comment_lines, f"{indent}if ({cond}) {{", *body, f"{indent}}}"]




def _emit_action_list(actions: list[TriggerAction], indent: str, ctx: dict, depth: int = 0) -> list[str]:
    out: list[str] = []
    for a in (actions or []):
        out.extend(_emit_action(a, indent, ctx, depth))
    return out


# ---------------------------------------------------------------------------
# Custom Triggers: emit the exported callback + a small creator helper.
# ---------------------------------------------------------------------------
