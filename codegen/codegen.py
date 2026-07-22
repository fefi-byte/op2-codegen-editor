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


from codegen_cpp import (
    _compare, _cpp_string, _expr_or_int, _ident, _mission_type_literal,
    _rect, _resource, _strip_map, _validate_cpp_expr, _xy, _xypos, mapid,
)
from codegen_actions import (
    _emit_action, _emit_action_list, _for_each_prologue, _wave_geometry,
)
from codegen_triggers import _emit_condition, _emit_trigger_helper
from codegen_groups import (
    _emit_base_layout, _emit_group_repair_body, _emit_groups,
    _emit_player_setup, _player_start_buildings, _roster_building_entries,
    _roster_targ_counts, _walk_actions, _BUILDING_TYPES,
)




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
    ctx["mission_name"] = mission.name
    ctx["custom_actions"] = list(getattr(mission, "custom_actions", None) or [])
    ctx["var_names"] = {v.name for v in (getattr(mission, "variables", None) or [])}
    ctx["wave_action_vars"] = {}
    ctx["wave_actions"] = []
    ctx["repair_action_vars"] = {}
    ctx["repair_actions"] = []
    mining_idx = 0
    assign_idx = 0
    wave_idx = 0
    repair_idx = 0
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
            elif a.kind == "repairBuildings":
                armed_var = f"_repair_armed_{repair_idx}"
                ctx["repair_action_vars"][id(a)] = armed_var
                ctx["repair_actions"].append((a, armed_var))
                repair_idx += 1
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
    # Benannte Gebaeude-Anker: Name -> (var, player, konvertierter Typ, x, y).
    # Der Reparatur-Timer bindet das Handle nach Bau/Wiederaufbau neu.
    # Named building anchors: name -> (var, player, converted type, x, y).
    # The repair timer rebinds the handle after build/rebuild.
    ctx["anchors"] = []
    _conv = lambda t: "mapCommonOreMine" if mapid(t) == "mapRareOreMine" else mapid(t)
    for u in (mission.units or []):
        name = (getattr(u, "unit_name", "") or "").strip()
        if name and name not in ctx["unit_vars"]:
            var = f"_unit_{_ident(name)}"
            ctx["unit_vars"][name] = var
            if getattr(u, "uid", ""):
                ctx["unit_vars_by_uid"][u.uid] = var
            if _strip_map(u.unit_type) in _BUILDING_TYPES:
                ctx["anchors"].append((name, var, int(u.player),
                                       _conv(u.unit_type), int(u.x), int(u.y)))
    # GEPLANTE Gebaeude (recordBuilding-Eintraege mit unit_name) werden
    # ebenfalls benannte Anker -- Besitzer ist der Spieler der Zielgruppe.
    # PLANNED buildings (recordBuilding entries with unit_name) become named
    # anchors too -- owner is the target group's player.
    group_players = {g.name: int(g.player)
                     for g in (getattr(mission, "building_groups", None) or [])}
    for t in (mission.triggers or []):
        for a in _walk_actions(t.actions):
            if a.kind != "recordBuilding":
                continue
            gp = group_players.get(getattr(a, "group_name", "") or "")
            if gp is None:
                continue
            entries = list(getattr(a, "building_list", None) or [])
            if not entries:
                entries = [{"building_type": a.building_type, "x": a.x, "y": a.y,
                            "unit_name": ""}]
            for e in entries:
                name = (e.get("unit_name", "") or "").strip()
                if not name or name in ctx["unit_vars"]:
                    continue
                var = f"_unit_{_ident(name)}"
                ctx["unit_vars"][name] = var
                ctx["anchors"].append((name, var, gp,
                                       _conv(e.get("building_type", "mapCommandCenter")),
                                       int(e.get("x", 0)), int(e.get("y", 0))))
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
    add("// Fertig UND ruhig? WHITELIST auf moDone: alles andere (moDevelop =")
    add("// im Bau, moOperationalWait = wartet auf Inbetriebnahme, HFL-Sentinels")
    add("// bei nicht initialisiertem HFL) zaehlt als NICHT bereit -- ein")
    add("// TakeUnit in diesen Zustaenden macht das Gebaeude kaputt.")
    add("// Finished AND quiet? WHITELIST on moDone: anything else (moDevelop =")
    add("// under construction, moOperationalWait = waiting to go operational,")
    add("// HFL sentinels when HFL is not initialized) counts as NOT ready --")
    add("// a TakeUnit in those states corrupts the building.")
    add("static bool isCompleted(UnitEx u) {")
    add("    if (u.unitID == 0 || !u.IsLive()) return false;")
    add("    return u.GetCurAction() == moDone;")
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
    for armed_var in ctx.get("repair_action_vars", {}).values():
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
    for armed_var in ctx.get("repair_action_vars", {}).values():
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
    # Kampagne: positiver missionType = Missionsnummer (RequiredExports.h);
    # sonst der klassische Enum-Name. max_tech_level begrenzt die Forschung.
    # Campaign: positive missionType = mission number (RequiredExports.h);
    # otherwise the classic enum name. max_tech_level caps research.
    if getattr(mission, "campaign", ""):
        mt_literal = str(max(1, int(getattr(mission, "campaign_mission", 1) or 1)))
    else:
        mt_literal = _mission_type_literal(mission.type)
    max_tech = int(getattr(mission, "max_tech_level", 12) or 12)
    add(f"ExportLevelDetailsFull({_cpp_string(mission.name)}, {_cpp_string(mission.map)}, "
        f"{_cpp_string(tech_tree)}, {mt_literal}, {num_players}, {max_tech}, 0)")
    add(f"Export const AIModDescEx DescBlockEx = {{ {num_ai} }};")
    add("")

    has_briefing = bool((getattr(mission, "briefing", "") or "").strip())
    if has_briefing:
        add("// Vor-Spielstart-Briefing (briefing_dialog.cpp + briefing.rc):")
        add("// modaler Dialog waehrend der Missions-Initialisierung.")
        add("// Pre-game briefing (briefing_dialog.cpp + briefing.rc):")
        add("// modal dialog during mission initialization.")
        add("extern void ShowBriefing();")
        add("extern void* g_briefing_hinst;")
        add("")

    # --- InitProc ---
    add("static void initProc() {")
    if has_briefing:
        add("    // Briefing VOR dem Spielstart anzeigen (blockiert bis CONTINUE).")
        add("    // Show the briefing BEFORE game start (blocks until CONTINUE).")
        add("    ShowBriefing();")
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

    # Handgeschriebener Missions-Code (Datei-Ebene): vor den Callbacks,
    # damit Callbacks/customCode-Bloecke ihn aufrufen koennen.
    # Hand-written mission code (file scope): before the callbacks so
    # callbacks/customCode blocks can call into it.
    if (getattr(mission, "custom_code", "") or "").strip():
        add("// --- Eigener Missions-Code (Missions-Einstellungen) ---")
        add("// --- Custom mission code (mission settings) ---")
        for cl in mission.custom_code.splitlines():
            add(cl)
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
    add("    // Nach einem Spielstand-Load laeuft InitProc NICHT erneut -- HFL")
    add("    // muss hier nachinitialisiert werden (intern idempotent), sonst")
    add("    // liefern UnitEx-Abfragen wie GetCurAction nur Sentinel-Werte.")
    add("    // After a savegame load InitProc does NOT run again -- HFL must")
    add("    // be (re)initialized here (internally idempotent), otherwise")
    add("    // UnitEx queries like GetCurAction only return sentinel values.")
    add("    HFLInit();")
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
    add('extern "C" int __stdcall DllMain(void* inst, unsigned long reason, void*) {')
    add("    if (reason == 1 /* DLL_PROCESS_ATTACH */) {")
    if has_briefing:
        add("        g_briefing_hinst = inst;")
    add('        op2::crash::installHandler();')
    add('        op2::log::setTickSource([] { return TethysGame::Tick(); });')
    add("    }")
    add("    return 1;")
    add("}")

    return "\n".join(out) + "\n"
