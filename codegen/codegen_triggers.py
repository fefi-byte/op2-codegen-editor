"""Emission der Trigger-Callbacks und Sieg-/Niederlagen-Bedingungen.

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
    _compare, _cpp_string, _expr_or_int, _ident, _rect, _resource,
    _strip_map, _xy, _xypos, mapid,
)
from codegen_actions import _emit_action_list




def _cond_var(cond) -> str:
    # Stabiler Hash (crc32) statt hash(): Python salzt hash() pro Prozess,
    # damit waere der generierte Code nicht reproduzierbar.
    # Stable hash (crc32) instead of hash(): Python salts hash() per process,
    # which would make the generated code non-reproducible.
    import zlib
    return f"_v_{zlib.crc32(repr(cond).encode()) & 0xFFFF}"




# ---------------------------------------------------------------------------
# Shared trigger-kind registry: ONE place mapping "kind" -> the OP2 engine
# call, used identically by Condition (victory/defeat, wrapped in
# CreateVictoryCondition/CreateFailureCondition with a no-op callback) and
# TriggerDef (a real callback running actions). Adding a new Trigger.h
# function only needs a branch here to become usable in BOTH systems --
# see mission_model.TriggerDef/Condition docstrings.
# ---------------------------------------------------------------------------

def _vehicle_cargo_expr(cargo_val: str) -> str:
    """"code" / "mapAny" / "mapNone" / "code:part" -> a map_id C++ expression.

    cargoOrWeapon (CreateCountTrigger) is declared as map_id in Trigger.h but
    a Truck_Cargo value (SetTruckCargo's type) must be cast across for cargo
    trucks. For truckSpaceport/truckGarbage the value is not a plain code but
    a part subtype packed in (cargoType | (subtype << 4), matching
    Unit.SetTruckCargo/UnitEx.GetCargoAmount) -- the editor encodes that
    choice as "truckSpaceport:mapEDWARDSatellite" etc.
    """
    cargo_val = cargo_val or "mapAny"
    if ":" in cargo_val:
        base, subtype = cargo_val.split(":", 1)
        return f"(map_id)(({base}) | (({subtype}) << 4))"
    if cargo_val in ("mapAny", "mapNone"):
        return cargo_val
    return f"(map_id){cargo_val}"


def _trigger_call(kind: str, obj, ctx: dict, bEnabled: str, bOneShot: str, callback: str) -> str | None:
    """Return the `CreateXTrigger(...)` call expression for a shared trigger
    kind (all of TriggerDef.condition / Condition.kind EXCEPT the
    Condition-only helper kinds time/lastStanding/starship/noCC -- wait, time
    IS shared -- and the trigger-only polling kinds findUnit/unitDied).

    None means the caller must handle it: attacked/damaged/specialTarget
    return None when their group/named-unit reference isn't declared (so the
    caller can emit its own "not declared" comment); findUnit/unitDied and any
    truly unknown kind also fall through to None.
    """
    cmp_ = _compare(getattr(obj, "compare", "cmpGreaterEqual"))
    player = int(getattr(obj, "player", 0))
    if kind == "time":
        return f'CreateTimeTrigger({bEnabled}, {bOneShot}, ({_expr_or_int(obj.marks)}) * kTicksPerMark, "{callback}")'
    if kind == "point":
        return f'CreatePointTrigger({bEnabled}, {bOneShot}, {player}, {_xypos(obj.x, obj.y)}, "{callback}")'
    if kind == "rect":
        return (f'CreateRectTrigger({bEnabled}, {bOneShot}, {player}, {_xypos(obj.x, obj.y)}, '
                f'{int(obj.width)}, {int(obj.height)}, "{callback}")')
    if kind == "buildingCount":
        return f'CreateBuildingCountTrigger({bEnabled}, {bOneShot}, {player}, {int(obj.count)}, {cmp_}, "{callback}")'
    if kind == "vehicleCount":
        return f'CreateVehicleCountTrigger({bEnabled}, {bOneShot}, {player}, {int(obj.count)}, {cmp_}, "{callback}")'
    if kind == "vehicleCargo":
        cargo_expr = _vehicle_cargo_expr(obj.cargo)
        return (f'CreateCountTrigger({bEnabled}, {bOneShot}, {player}, {mapid(obj.unit_type)}, '
                f'{cargo_expr}, {int(obj.count)}, {cmp_}, "{callback}")')
    if kind == "research":
        return f'CreateResearchTrigger({bEnabled}, {bOneShot}, {int(obj.tech_id)}, {player}, "{callback}")'
    if kind == "resource":
        return (f'CreateResourceTrigger({bEnabled}, {bOneShot}, {_resource(obj.resource)}, '
                f'{int(obj.amount)}, {player}, {cmp_}, "{callback}")')
    if kind == "operational":
        return (f'CreateOperationalTrigger({bEnabled}, {bOneShot}, {player}, {mapid(obj.building)}, '
                f'{int(obj.count)}, {cmp_}, "{callback}")')
    if kind == "attacked":
        gvar = ctx.get("group_vars", {}).get((getattr(obj, "group_name", "") or "").strip())
        return f'CreateAttackedTrigger({bEnabled}, {bOneShot}, {gvar}, "{callback}")' if gvar else None
    if kind == "damaged":
        gvar = ctx.get("group_vars", {}).get((getattr(obj, "group_name", "") or "").strip())
        if not gvar:
            return None
        dmg = int(getattr(obj, "damage_type", 3) or 3)
        return f'CreateDamagedTrigger({bEnabled}, {bOneShot}, {gvar}, {dmg}, "{callback}")'
    if kind == "specialTarget":
        uvar = ctx.get("unit_vars", {}).get((getattr(obj, "target_unit", "") or "").strip())
        if not uvar:
            return None
        src = mapid(getattr(obj, "source_unit_type", "mapScout") or "mapScout")
        return f'CreateSpecialTarget({bEnabled}, {bOneShot}, {uvar}, {src}, "{callback}")'
    if kind == "onePlayerLeft":
        # Engine-native "Last One Standing" -- no player/extra fields at all.
        return f'CreateOnePlayerLeftTrigger({bEnabled}, {bOneShot}, "{callback}")'
    if kind == "evac":
        return f'CreateEvacTrigger({bEnabled}, {bOneShot}, {player}, "{callback}")'
    if kind == "midas":
        return f'CreateMidasTrigger({bEnabled}, {bOneShot}, ({_expr_or_int(obj.marks)}) * kTicksPerMark, "{callback}")'
    if kind == "kit":
        # No compare_mode in this Trigger.h signature -- the engine's own
        # (undocumented, presumably >=) comparison applies.
        return (f'CreateKitTrigger({bEnabled}, {bOneShot}, {player}, {mapid(obj.building)}, '
                f'{int(obj.count)}, "{callback}")')
    if kind == "escape":
        # cargoType/cargoAmount are two SEPARATE plain-int params here (unlike
        # CreateCountTrigger's packed map_id) -- "code:part" splits cleanly
        # across them, a bare code falls back to the numeric `amount` field.
        cargo_val = obj.cargo or "mapAny"
        if ":" in cargo_val:
            cargo_type, cargo_amount = cargo_val.split(":", 1)
        else:
            cargo_type, cargo_amount = cargo_val, _expr_or_int(getattr(obj, "amount", 0) or 0)
        return (f'CreateEscapeTrigger({bEnabled}, {bOneShot}, {player}, {_xypos(obj.x, obj.y)}, '
                f'{int(obj.width)}, {int(obj.height)}, {int(obj.count)}, {mapid(obj.unit_type)}, '
                f'{cargo_type}, {cargo_amount}, "{callback}")')
    return None


def _emit_condition(cond: Condition, is_victory: bool, mission: Mission | None = None,
                    ctx: dict | None = None) -> list[str]:
    """Emit one win/lose condition (called from InitProc()).

    Klassisches Muster: einen (bedingungslosen) Engine-Trigger mit dem No-Op-
    Callback "NoResponseToTrigger" erzeugen und in CreateVictoryCondition /
    CreateFailureCondition einhaengen -- die Engine wertet den Sieg selbst aus.
    Fuer die meisten Kinds kommt dieser Trigger aus dem _trigger_call-Register,
    das sich Condition und TriggerDef teilen; lastStanding/starship/noCC
    bleiben Condition-eigene OP2Helper-Mehrfach-Aufrufe.

    Classic pattern: create a (condition) engine trigger with the no-op
    callback "NoResponseToTrigger" and wrap it in CreateVictoryCondition /
    CreateFailureCondition -- the engine evaluates the win itself. For most
    kinds this trigger comes from the shared _trigger_call registry (shared
    with TriggerDef); lastStanding/starship/noCC stay Condition-only
    multi-call OP2Helper conveniences.
    """
    lines: list[str] = []
    ctx = ctx if ctx is not None else {}
    obj = _cpp_string(cond.objective or ("Mission objective" if is_victory else ""))

    def _wrap(trigger_expr: str, var: str) -> None:
        lines.append(f"    Trigger {var} = {trigger_expr};")
        if is_victory:
            lines.append(f"    CreateVictoryCondition(1, 0, {var}, {obj});")
        else:
            lines.append(f'    CreateFailureCondition(1, 0, {var}, "");')

    if cond.kind == "noCC":
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
    else:
        expr = _trigger_call(cond.kind, cond, ctx, "1", "1", "NoResponseToTrigger")
        if expr is not None:
            _wrap(expr, _cond_var(cond))
        elif cond.kind in ("attacked", "damaged"):
            lines.append(f"    // TODO {cond.kind}: group '{getattr(cond, 'group_name', '')}' not declared")
        elif cond.kind == "specialTarget":
            lines.append(f"    // TODO specialTarget: unit '{getattr(cond, 'target_unit', '')}' not declared")
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
    cb_fn = f"{helper}_cb"
    ctx.setdefault("trigger_cb_names", {})[helper] = cb_fn

    lines: list[str] = []
    lines.append(f"// Trigger '{t.name}' (condition={t.condition})")
    for cl in ((getattr(t, "comment", "") or "").strip()).splitlines():
        lines.append(f"// {cl.strip().rstrip(chr(92)).strip()}")

    # --- Callback als exportierte Funktion / callback as an exported function ---
    if t.condition in ("time", "buildingCount", "vehicleCount", "vehicleCargo",
                       "research", "resource", "operational", "point", "rect",
                       "attacked", "damaged", "specialTarget",
                       "onePlayerLeft", "evac", "midas", "kit", "escape"):
        # Alle diese Kinds sind native Engine-Trigger -- die Bedingung selbst
        # wird von der Engine geprueft, der Callback muss nur die Aktionen
        # ausfuehren (siehe _trigger_call fuer die Trigger-Erzeugung unten).
        # All these kinds are native engine triggers -- the engine itself
        # checks the condition, the callback just has to run the actions (see
        # _trigger_call below for the trigger creation).
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
            lines.append(f"    bool _ready{i} = isCompleted(_u{i}) "
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
    if t.condition in ("findUnit", "unitDied"):
        lines.append(f'    g_save.{helper}_self = CreateTimeTrigger(1, 0, 10, "{cb_fn}");')
    else:
        expr = _trigger_call(t.condition, t, ctx, "1", one_shot, cb_fn)
        if expr is not None:
            lines.append(f"    {expr};")
        elif t.condition in ("attacked", "damaged"):
            lines.append(f"    // TODO {t.condition}: group '{getattr(t, 'group_name', '')}' not declared")
        elif t.condition == "specialTarget":
            lines.append(f"    // TODO specialTarget: unit '{getattr(t, 'target_unit', '')}' not declared")
        else:
            lines.append(f"    // TODO unsupported trigger condition: {t.condition}")
    lines.append(f"}}")
    return lines


# ---------------------------------------------------------------------------
# Groups: building / reinforce / fight / mining.
# ---------------------------------------------------------------------------
