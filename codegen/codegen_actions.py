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
    _CMD_TYPE, _compare, _cpp_string, _expr_or_int, _ident, _line_tiles, _loc_expr,
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
        expr = "true /* TODO(editor): unsupported ActionCondition kind */"

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
    emitter = _EMITTER.get(k)
    if emitter is None:
        return _unbekannt(indent, k)
    return emitter(action, indent, ctx, depth, k)


def _unbekannt(indent: str, k: str) -> list[str]:
    return [f"{indent}// TODO(editor) unsupported action kind: {k}"]


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


# Am Ende importiert: die Emitter brauchen die Helfer oben.
# Imported last: the emitters need the helpers above.
from codegen_action_kinds import _EMITTER  # noqa: E402
