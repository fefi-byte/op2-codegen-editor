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
    for cl in ((getattr(t, "comment", "") or "").strip()).splitlines():
        lines.append(f"// {cl.strip().rstrip(chr(92)).strip()}")

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
