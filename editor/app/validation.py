from __future__ import annotations

"""Missionvalidierung: prueft das Editor-Modell auf stille Fehler.

Mission validation: checks the editor model for silent errors that would
otherwise only surface as `// TODO(editor)` comments in the generated C++ or as a
mission that does nothing in-game.

Jede Prueffunktion liefert Befunde als (severity, text, target)-Tupel:
  severity: "error" | "warning"
  target:   ("trigger", index) | ("player", index) | ("object", index)
            | ("group", None) | ("conditions", None) | None
Each check yields findings as (severity, text, target) tuples.
"""

from .common import tr


def validate_mission(w) -> list[tuple[str, str, tuple | None]]:
    """Alle Pruefungen auf dem EditorWindow-Zustand `w` ausfuehren.

    Run all checks against the EditorWindow state `w`."""
    findings: list[tuple[str, str, tuple | None]] = []
    findings += _check_players(w)
    findings += _check_triggers(w)
    findings += _check_variables(w)
    findings += _check_groups(w)
    findings += _check_conditions(w)
    findings += _check_sdk_gotchas(w)
    findings += _check_building_group_builders(w)
    findings += _check_unit_names(w)
    findings += _check_repair_actions(w)
    findings += _check_mine_beacons(w)
    findings += _check_loop_refs(w)
    findings += _check_dialogs(w)
    findings += _check_campaign(w)
    findings += _check_custom_actions(w)
    findings += _check_text_vars(w)
    return findings


def _check_players(w):
    out = []
    # Welche Spieler besitzen ein Command Center?
    # Which players own a Command Center?
    cc_players = {o.player for o in w.objects
                  if o.map_id == "mapCommandCenter"}
    used_players = {o.player for o in w.objects if o.kind in ("structure", "vehicle")}
    for i in range(len(w.players)):
        if i in used_players and i not in cc_players:
            out.append(("warning", tr("validation.player_no_cc", i=i), ("player", i)))
    # Objekte, die einem nicht (mehr) existierenden Spieler gehoeren
    # Objects owned by a player that does not (or no longer) exist(s)
    for oi, o in enumerate(w.objects):
        if o.kind in ("structure", "vehicle") and o.player >= len(w.players):
            out.append(("error",
                        tr("validation.object_bad_player", label=o.unit_name or o.display,
                           p=o.player, n=len(w.players)),
                        ("object", oi)))
    return out


def _check_triggers(w):
    out = []
    names = {t.name for t in w.triggers}
    created = {a.target for t in w.triggers for a in t.actions
               if a.kind == "createTrigger" and a.target}
    for ti, t in enumerate(w.triggers):
        if not t.actions:
            out.append(("warning", tr("validation.trigger_no_actions", name=t.name),
                        ("trigger", ti)))
        for a in t.actions:
            if a.kind == "createTrigger":
                if not a.target:
                    out.append(("error", tr("validation.create_trigger_empty", name=t.name),
                                ("trigger", ti)))
                elif a.target not in names:
                    out.append(("error",
                                tr("validation.create_trigger_missing", name=t.name, target=a.target),
                                ("trigger", ti)))
        if not t.enabled_at_start and t.name not in created:
            out.append(("warning", tr("validation.trigger_unreachable", name=t.name),
                        ("trigger", ti)))
    return out


def _check_variables(w):
    out = []
    var_names = {v.name for v in w.variables}
    # verwendet: modVar-Aktionen und varCheck-Bedingungen
    # used: modVar actions and varCheck conditions
    set_vars, read_vars = set(), set()
    for t in w.triggers:
        for a in _walk_actions(t.actions):
            if a.kind == "modVar" and a.var_name:
                set_vars.add(a.var_name)
                if a.var_name not in var_names:
                    out.append(("error", tr("validation.var_undeclared", name=a.var_name), None))
            for c in getattr(a, "conditions", None) or []:
                if getattr(c, "kind", "") == "varCheck" and getattr(c, "var_name", ""):
                    read_vars.add(c.var_name)
                    if c.var_name not in var_names:
                        out.append(("error", tr("validation.var_undeclared", name=c.var_name), None))
    for v in w.variables:
        if v.name in read_vars and v.name not in set_vars:
            out.append(("warning", tr("validation.var_never_set", name=v.name), None))
        if v.name not in read_vars and v.name not in set_vars:
            out.append(("warning", tr("validation.var_unused", name=v.name), None))
    return out


def _walk_actions(actions):
    """Aktionen inkl. verschachtelter then/else-Zweige durchlaufen.

    Walk actions including nested then/else branches."""
    for a in actions:
        yield a
        yield from _walk_actions(getattr(a, "then_actions", None) or [])
        yield from _walk_actions(getattr(a, "else_actions", None) or [])


def _check_building_group_builders(w):
    """Bau-Voraussetzungen von BuildingGroups (Sirbombers W9-Rezept): damit
    RecordBuilding-Eintraege tatsaechlich gebaut werden, braucht die Gruppe
    ConVecs + eine StructureFactory im Roster (fuer Minen: einen RoboMiner)
    und der Besitzer muss ein KI-Spieler sein.

    Build prerequisites of BuildingGroups (Sirbomber's W9 recipe): for
    RecordBuilding entries to actually get built, the group needs ConVecs +
    a StructureFactory in its roster (for mines: a RoboMiner) and the owner
    must be an AI player.
    """
    out = []
    # Welche Gruppen bekommen recordBuilding-Eintraege (per Gruppen-Panel
    # spielt keine Rolle -- entscheidend sind die Aktionen)?
    recorded: dict[str, set] = {}
    for t in (getattr(w, "triggers", None) or []):
        for a in _walk_actions(t.actions):
            if a.kind != "recordBuilding" or not getattr(a, "group_name", ""):
                continue
            entries = list(getattr(a, "building_list", None) or [])
            if not entries:
                entries = [{"building_type": getattr(a, "building_type", "")}]
            types = {e.get("building_type", "") for e in entries}
            recorded.setdefault(a.group_name, set()).update(types)
    if not recorded:
        return out
    uid_types = {getattr(o, "uid", ""): getattr(o, "map_id", "")
                 for o in (getattr(w, "objects", None) or [])}
    players = getattr(w, "players", None) or []
    mine_types = {"mapCommonOreMine", "mapRareOreMine"}
    for g in (getattr(w, "building_groups", None) or []):
        if g.name not in recorded:
            continue
        roster = {uid_types.get(uid, "") for uid in (getattr(g, "unit_ids", None) or [])}
        records_mines = bool(recorded[g.name] & mine_types)
        records_other = bool(recorded[g.name] - mine_types)
        # Minen baut ein Robo-Miner (Beacon-Deploy), keine ConVec+Kit-Kette.
        # Mines are built by a Robo-Miner (beacon deploy), not ConVec+kit.
        if records_mines and "mapRoboMiner" not in roster:
            out.append(("warning", tr("validation.bg_no_miner", name=g.name),
                        ("group", None)))
        if records_other:
            if "mapConVec" not in roster:
                out.append(("warning", tr("validation.bg_no_convec", name=g.name),
                            ("group", None)))
            if "mapStructureFactory" not in roster:
                out.append(("warning", tr("validation.bg_no_structure_factory", name=g.name),
                            ("group", None)))
        p = int(getattr(g, "player", 0))
        if 0 <= p < len(players) and getattr(players[p], "is_human", True):
            out.append(("warning", tr("validation.bg_human_player", name=g.name, p=p),
                        ("group", None)))
    # Mehrere record_all-Gruppen desselben Spielers rekordieren dieselben
    # Gebaeude doppelt -- beide Gruppen wuerden um den Wiederaufbau
    # konkurrieren.
    # Several record_all groups of the same player record the same
    # buildings twice -- both groups would compete for the rebuild.
    from collections import Counter
    ra = Counter(int(getattr(g, "player", 0))
                 for g in (getattr(w, "building_groups", None) or [])
                 if getattr(g, "record_all", True))
    for p, n in sorted(ra.items()):
        if n > 1:
            out.append(("warning", tr("validation.record_all_conflict", p=p, n=n),
                        ("group", None)))
    return out


def _check_unit_names(w):
    """Benannte Gebaeude-Anker: Namen muessen eindeutig sein; Referenzen
    (MiningGroup mine_ref/smelter_ref, plan:-Roster) muessen existieren und
    zum Gebaeudetyp passen.

    Named building anchors: names must be unique; references (MiningGroup
    mine_ref/smelter_ref, plan: roster entries) must exist and match the
    building type.
    """
    out = []
    # Namensregister: platzierte Einheiten + geplante recordBuilding-Eintraege
    name_types: dict[str, str] = {}
    dups = set()
    for o in (getattr(w, "objects", None) or []):
        n = (getattr(o, "unit_name", "") or "").strip()
        if not n:
            continue
        if n in name_types:
            dups.add(n)
        name_types[n] = getattr(o, "map_id", "")
    for t in (getattr(w, "triggers", None) or []):
        for a in _walk_actions(t.actions):
            if getattr(a, "kind", "") != "recordBuilding":
                continue
            for e in (getattr(a, "building_list", None) or []):
                n = (e.get("unit_name", "") or "").strip()
                if not n:
                    continue
                if n in name_types:
                    dups.add(n)
                name_types[n] = e.get("building_type", "")
    for n in sorted(dups):
        out.append(("error", tr("validation.dup_unit_name", name=n), None))
    mine_types = {"mapCommonOreMine", "mapRareOreMine"}
    smelter_types = {"mapCommonOreSmelter", "mapRareOreSmelter"}
    for g in (getattr(w, "mining_groups", None) or []):
        for (field_name, ref, ok_types, key_missing) in (
            ("mine_ref", (getattr(g, "mine_ref", "") or "").strip(), mine_types,
             "validation.mining_no_mine_ref"),
            ("smelter_ref", (getattr(g, "smelter_ref", "") or "").strip(), smelter_types,
             "validation.mining_no_smelter_ref"),
        ):
            if not ref:
                out.append(("warning", tr(key_missing, name=g.name), ("group", None)))
            elif ref not in name_types:
                out.append(("error", tr("validation.ref_unknown", name=g.name, ref=ref),
                            ("group", None)))
            elif name_types[ref] not in ok_types:
                out.append(("error", tr("validation.ref_wrong_type", name=g.name, ref=ref,
                                        t=name_types[ref]), ("group", None)))
    for attr in ("building_groups", "reinforce_groups", "fight_groups", "mining_groups"):
        for g in (getattr(w, attr, None) or []):
            for uid in (getattr(g, "unit_ids", None) or []):
                if isinstance(uid, str) and uid.startswith("plan:"):
                    if uid[5:].strip() not in name_types:
                        out.append(("error",
                                    tr("validation.roster_plan_unknown", name=g.name,
                                       ref=uid[5:].strip()), ("group", None)))
    # Truck-Nachschub der MiningGroups: ohne ReinforceGroup werden verlorene
    # Trucks nie ersetzt; gesetzte Quelle muss existieren.
    # Mining truck resupply: without a ReinforceGroup, lost trucks are never
    # replaced; a configured source must exist.
    rg_names = {g.name for g in (getattr(w, "reinforce_groups", None) or [])}
    for g in (getattr(w, "mining_groups", None) or []):
        src_name = (getattr(g, "source_group_name", "") or "").strip()
        if not src_name:
            out.append(("warning", tr("validation.mining_no_source", name=g.name),
                        ("group", None)))
        elif src_name not in rg_names:
            out.append(("error", tr("validation.mining_source_missing", name=g.name,
                                    ref=src_name), ("group", None)))
    return out


def _check_repair_actions(w):
    """repairBuildings v2: Gruppe muss existieren und ein reparaturfaehiges
    Fahrzeug (RepairVehicle/Spider/ConVec) im Roster haben.

    repairBuildings v2: the group must exist and have a repair-capable
    vehicle (RepairVehicle/Spider/ConVec) in its roster.
    """
    out = []
    uid_types = {getattr(o, "uid", ""): getattr(o, "map_id", "")
                 for o in (getattr(w, "objects", None) or [])}
    bg_by_name = {g.name: g for g in (getattr(w, "building_groups", None) or [])}
    repair_caps = {"mapRepairVehicle", "mapSpider", "mapConVec"}
    for ti, t in enumerate(getattr(w, "triggers", None) or []):
        for a in _walk_actions(t.actions):
            if a.kind != "repairBuildings":
                continue
            gname = getattr(a, "group_name", "") or ""
            if not gname or gname not in bg_by_name:
                out.append(("error", tr("validation.repair_no_group", name=t.name),
                            ("trigger", ti)))
                continue
            roster = {uid_types.get(uid, "") for uid in
                      (getattr(bg_by_name[gname], "unit_ids", None) or [])}
            if not (roster & repair_caps):
                out.append(("warning", tr("validation.repair_no_vehicle",
                                          name=gname), ("trigger", ti)))
    return out


def _check_mine_beacons(w):
    """Eine Mine entsteht nur AUF einem Mining Beacon ("Beacon vor Mine").
    Rekordierte Minen-Positionen ohne Beacon werden nie gebaut.

    A mine only appears ON a mining beacon ("beacon before mine"). Recorded
    mine positions without a beacon never get built.
    """
    out = []
    beacon_tiles = {(int(o.tile_x), int(o.tile_y))
                    for o in (getattr(w, "objects", None) or [])
                    if getattr(o, "kind", "") == "beacon"}
    mine_types = {"mapCommonOreMine", "mapRareOreMine"}
    for ti, t in enumerate(getattr(w, "triggers", None) or []):
        for a in _walk_actions(t.actions):
            if a.kind != "recordBuilding":
                continue
            entries = list(getattr(a, "building_list", None) or [])
            if not entries:
                entries = [{"building_type": getattr(a, "building_type", ""),
                            "x": getattr(a, "x", 0), "y": getattr(a, "y", 0)}]
            for e in entries:
                if e.get("building_type", "") in mine_types:
                    pos = (int(e.get("x", 0)), int(e.get("y", 0)))
                    if pos not in beacon_tiles:
                        out.append(("warning",
                                    tr("validation.mine_no_beacon",
                                       name=t.name, x=pos[0], y=pos[1]),
                                    ("trigger", ti)))
    return out


def _check_sdk_gotchas(w):
    """Bekannte Engine-/SDK-Fallen aus dem OP2-Coding-Wiki.

    Known engine/SDK gotchas from the OP2 coding wiki."""
    out = []
    mt = int(getattr(w, "mission_type", -1))
    is_multi = mt <= -4      # MultiLandRush=-4 .. MultiLastOneStanding=-8
    # 1) Failure-Conditions in Multiplayer: beim Ausloesen bekommen die
    #    Mitspieler eine "Lost Contact"-Pause.
    if is_multi and getattr(w, "defeats", None):
        out.append(("warning", tr("validation.multi_failure_pause"), ("conditions", None)))
    # 2) Sieg-Trigger mit Spieler > 0 feuern erfahrungsgemaess beim Spielstart
    #    (Fire-Plague-Gotcha) -- Spieler 0 bevorzugen.
    for c in (getattr(w, "victories", None) or []):
        if int(getattr(c, "player", 0)) > 0:
            out.append(("warning",
                        tr("validation.victory_player_nonzero", p=c.player),
                        ("conditions", None)))
    # 3) Land Rush mit KI-Spieler funktioniert nicht (Coding 101 W11).
    if mt == -4 and any(not p.is_human for p in (getattr(w, "players", None) or [])):
        out.append(("warning", tr("validation.landrush_ai"), None))
    # 4) mapSmallCapacityAirTransport crasht beim Bewegen (Header-Kommentar).
    bad = "mapSmallCapacityAirTransport"
    for oi, o in enumerate(getattr(w, "objects", None) or []):
        if getattr(o, "map_id", "") == bad:
            out.append(("error", tr("validation.air_transport_crash"), ("object", oi)))
    for ti, t in enumerate(getattr(w, "triggers", None) or []):
        for a in _walk_actions(t.actions):
            types = [getattr(a, "unit_type", "")]
            types += [e.get("unit_type", "") for e in (getattr(a, "unit_list", None) or [])]
            if a.kind == "createUnit" and bad in types:
                out.append(("error", tr("validation.air_transport_crash"), ("trigger", ti)))
        # 5) Referenzen der neuen Trigger-Bedingungen pruefen.
        #    Check the new trigger conditions' references.
        all_group_names = ({g.name for g in getattr(w, "fight_groups", None) or []}
                           | {g.name for g in getattr(w, "building_groups", None) or []}
                           | {g.name for g in getattr(w, "reinforce_groups", None) or []}
                           | {g.name for g in getattr(w, "mining_groups", None) or []})
        named_units = {getattr(o, "unit_name", "") for o in (getattr(w, "objects", None) or [])
                       if getattr(o, "unit_name", "")}
        if t.condition in ("attacked", "damaged"):
            if not getattr(t, "group_name", "") or t.group_name not in all_group_names:
                out.append(("error", tr("validation.trigger_group_missing", name=t.name),
                            ("trigger", ti)))
        if t.condition in ("specialTarget", "unitDied"):
            if not getattr(t, "target_unit", "") or t.target_unit not in named_units:
                out.append(("error", tr("validation.trigger_unit_missing", name=t.name),
                            ("trigger", ti)))
    return out


def _check_groups(w):
    out = []
    fight_group_names = {g.name for g in w.fight_groups}
    mining_group_names = {g.name for g in w.mining_groups}
    group_names = ({g.name for g in w.building_groups}
                   | {g.name for g in w.reinforce_groups}
                   | fight_group_names
                   | mining_group_names)
    # ReinforceGroup-Ziele (Zielgruppe=Prioritaet-Textfeld): Name muss zu einer
    # bestehenden Gruppe passen, sonst wird beim Bauen stillschweigend nichts
    # erzeugt (kein recordVehReinforceGroup-Aufruf).
    # ReinforceGroup targets ("target=priority" text field): the name must
    # match an existing group, otherwise nothing gets generated when building
    # (no recordVehReinforceGroup call).
    for g in w.reinforce_groups:
        for t in (getattr(g, "targets", None) or []):
            if t.group_name not in group_names:
                out.append(("error",
                            tr("validation.reinforce_target_missing",
                               group=g.name, target=t.group_name),
                            ("group", None)))
    for t in w.triggers:
        for a in _walk_actions(t.actions):
            gname = getattr(a, "group_name", "") or ""
            if a.kind in ("recordBuilding", "recordTube", "recordWall", "assignToGroup") and gname:
                if gname not in group_names:
                    out.append(("error",
                                tr("validation.group_missing", group=gname, name=t.name),
                                ("group", None)))
            if a.kind == "setTargCount":
                # Ziel der Sollstaerke: das Feld heisst "group_name", nicht
                # "target_group" (das gibt es auf TriggerAction gar nicht --
                # die Pruefung griff bisher nie).
                # Target of the count: the field is "group_name", not
                # "target_group" (that doesn't exist on TriggerAction -- this
                # check never fired before).
                tg = getattr(a, "group_name", "") or ""
                if not tg:
                    out.append(("error", tr("validation.targcount_no_group", name=t.name),
                                ("group", None)))
                elif tg not in group_names:
                    out.append(("error",
                                tr("validation.group_missing", group=tg, name=t.name),
                                ("group", None)))
                src = getattr(a, "source_group_name", "") or ""
                if src and src not in {g.name for g in w.reinforce_groups}:
                    out.append(("error",
                                tr("validation.group_missing", group=src, name=t.name),
                                ("group", None)))
            if a.kind == "sendAttackWave":
                wave_name = getattr(a, "group_var_name", "") or ""
                if not wave_name:
                    out.append(("error", tr("validation.wave_no_group", name=t.name),
                                ("group", None)))
                elif wave_name not in fight_group_names:
                    out.append(("error",
                                tr("validation.wave_unknown_group", group=wave_name, name=t.name),
                                ("group", None)))
                if (getattr(a, "spawn_mode", "spawn") == "reinforce"):
                    src = getattr(a, "source_group_name", "") or ""
                    if not src:
                        out.append(("error", tr("validation.wave_no_source", name=t.name),
                                    ("group", None)))
                    elif src not in {g.name for g in w.reinforce_groups}:
                        out.append(("error",
                                    tr("validation.group_missing", group=src, name=t.name),
                                    ("group", None)))
                if not (getattr(a, "wave_units", None) or []):
                    out.append(("warning", tr("validation.wave_empty", name=t.name), None))
            if a.kind == "startMining":
                mgname = getattr(a, "group_name", "") or ""
                if not mgname:
                    out.append(("error", tr("validation.mining_no_group", name=t.name),
                                ("group", None)))
                elif mgname not in mining_group_names:
                    out.append(("error",
                                tr("validation.mining_unknown_group", group=mgname, name=t.name),
                                ("group", None)))
            if a.kind == "fightGroupCmd":
                target = getattr(a, "group_name", "") or ""
                if not target:
                    out.append(("error", tr("validation.fg_cmd_no_group", name=t.name), None))
                elif target not in group_names:
                    out.append(("error",
                                tr("validation.fg_cmd_unknown_group", group=target, name=t.name),
                                None))
                cmd = getattr(a, "fg_command", "") or ""
                if cmd in ("reinforceGroup", "unReinforceGroup"):
                    tgt = getattr(a, "target", "") or ""
                    if not tgt or tgt not in fight_group_names:
                        out.append(("error",
                                    tr("validation.fg_cmd_unknown_group", group=tgt or "?", name=t.name),
                                    None))
                elif cmd in ("addUnit", "removeUnit"):
                    tgt = getattr(a, "target", "") or ""
                    unit_names = {o.unit_name for o in w.objects if getattr(o, "unit_name", "")}
                    if not tgt:
                        out.append(("error", tr("validation.fg_cmd_no_unit", name=t.name), None))
                    elif tgt not in ("<loop>", "<loop:outer>") and tgt not in unit_names:
                        out.append(("error",
                                    tr("validation.unit_cmd_unknown_unit", unit=tgt, name=t.name),
                                    None))
            if a.kind == "unitCmd":
                unit_names = {o.unit_name for o in w.objects if getattr(o, "unit_name", "")}
                uref = getattr(a, "unit_ref", "") or ""
                if not uref:
                    out.append(("error", tr("validation.unit_cmd_no_unit", name=t.name), None))
                elif uref not in ("<loop>", "<loop:outer>") and uref not in unit_names:
                    out.append(("error",
                                tr("validation.unit_cmd_unknown_unit", unit=uref, name=t.name),
                                None))
                trg = getattr(a, "target", "") or ""
                if getattr(a, "fg_command", "") == "repair" and trg \
                        and trg not in ("<loop>", "<loop:outer>") and trg not in unit_names:
                    out.append(("error",
                                tr("validation.unit_cmd_unknown_unit", unit=trg, name=t.name),
                                None))
    return out


def _check_conditions(w):
    out = []
    if not w.victories:
        out.append(("warning", tr("validation.no_victory"), ("conditions", None)))
    if not w.defeats:
        out.append(("warning", tr("validation.no_defeat"), ("conditions", None)))
    # lastStanding braucht mindestens einen KI-Gegner
    # lastStanding needs at least one AI opponent
    if any(c.kind == "lastStanding" for c in w.victories):
        if not any(not p.is_human for p in w.players):
            out.append(("error", tr("validation.last_standing_no_ai"), ("conditions", None)))
    return out


def _check_loop_refs(w):
    """Schleifen-Referenzen (<loop>/<loop:outer>) ausserhalb einer
    forEach-Schleife emittieren keinen Code -- als Fehler melden.

    Loop references (<loop>/<loop:outer>) outside a forEach loop emit no
    code -- report as an error."""
    out = []

    def loop_fields(a):
        """Nur die Felder pruefen, die die Aktion bei ihrem aktuellen Befehl
        tatsaechlich benutzt -- das Formular speichert auch unbenutzte
        Combo-Staende (z.B. das Reparatur-Ziel bei einem Transfer-Befehl).

        Only check the fields the action actually uses with its current
        command -- the form also persists unused combo states (e.g. the
        repair target while a transfer command is selected)."""
        k = getattr(a, "kind", "")
        if k == "unitCmd":
            fields = ["unit_ref"]
            if (getattr(a, "fg_command", "") or "") == "repair":
                fields.append("target")
            return fields
        if k == "fightGroupCmd":
            if (getattr(a, "fg_command", "") or "") in ("addUnit", "removeUnit"):
                return ["target"]
            return []
        if k == "startMining":
            return ["mine_ref", "smelter_ref"]
        return []

    def walk(actions, depth, ti, tname):
        for a in (actions or []):
            d = depth
            if getattr(a, "kind", "") == "if" and                     (getattr(a, "loop_mode", "none") or "none") == "forEach":
                d = depth + 1
            if getattr(a, "kind", "") != "if":
                for f in loop_fields(a):
                    v = getattr(a, f, "") or ""
                    if v in ("<loop>", "<loop:outer>") and depth == 0:
                        out.append(("error",
                                    tr("validation.loop_ref_outside",
                                       t=tname, kind=getattr(a, "kind", "?")),
                                    ("trigger", ti)))
                        break
            walk(getattr(a, "then_actions", None), d, ti, tname)
            walk(getattr(a, "else_actions", None), d, ti, tname)

    for ti, t in enumerate(getattr(w, "triggers", None) or []):
        walk(t.actions, 0, ti, t.name)
    return out


def _check_dialogs(w):
    """MsgBox blockiert das lokale Spiel bis OK -- in Multiplayer-Missionen
    droht damit Desync/Haenger.

    MsgBox blocks the local game until OK -- in multiplayer missions that
    risks desync/hangs."""
    out = []
    mt = int(getattr(w, "mission_type", -1))
    if mt > -4:      # nur Multiplayer (-4..-8) betrifft es / multiplayer only
        return out
    has_dialog = bool((getattr(w, "briefing", "") or "").strip())
    def walk(actions):
        nonlocal has_dialog
        for a in (actions or []):
            if getattr(a, "kind", "") == "showDialog":
                has_dialog = True
            walk(getattr(a, "then_actions", None))
            walk(getattr(a, "else_actions", None))
    for t in (getattr(w, "triggers", None) or []):
        walk(t.actions)
    if has_dialog:
        out.append(("warning", tr("validation.dialog_multiplayer"), None))
    return out


def _check_campaign(w):
    """Kampagnenregeln: DLL-Name e##/p##, Kolonie passend, und ab Mission 2
    keine harten Kolonisten-/Forschungswerte (die Engine reicht sie via
    MissionResults aus der Vormission weiter).

    Campaign rules: DLL name e##/p##, matching colony, and from mission 2 on
    no hard colonist/research values (the engine hands them over from the
    previous mission via MissionResults)."""
    out = []
    camp = getattr(w, "campaign", "") or ""
    if not camp:
        return out
    num = int(getattr(w, "campaign_mission", 1) or 1)
    prefix = "e" if camp == "eden" else "p"
    dll = (getattr(w, "dll_name", "") or "").lower()
    base = dll[:-4] if dll.endswith(".dll") else dll
    import re
    if not re.fullmatch(rf"{prefix}\d+", base):
        out.append(("warning", tr("validation.campaign_dll_name",
                                  want=f"{prefix}{num:02d}.dll", have=dll or "?"),
                    None))
    players = getattr(w, "players", None) or []
    if players:
        from mission_model import Colony
        want = Colony.Eden if camp == "eden" else Colony.Plymouth
        if players[0].colony != want:
            out.append(("warning", tr("validation.campaign_colony",
                                      c="Eden" if camp == "eden" else "Plymouth"),
                        ("player", 0)))
        if num >= 2:
            p0 = players[0]
            hard = (p0.kids is not None or p0.workers is not None
                    or p0.scientists is not None or (p0.researches or [])
                    or (p0.tech_level not in (None, 0)))
            if hard:
                out.append(("warning", tr("validation.campaign_carryover"),
                            ("player", 0)))
    return out


def _check_custom_actions(w):
    """Designer-Aktionen: unbekannte Referenzen und Platzhalter ohne
    passenden Parameter melden.

    Designer actions: report unknown references and placeholders without a
    matching parameter."""
    import re as _re
    out = []
    defs = {d.get("name"): d for d in (getattr(w, "custom_actions", None) or [])}
    for name, d in defs.items():
        pnames = {p.get("name") for p in (d.get("params") or [])}
        for tok in set(_re.findall(r"\$(\w+)", d.get("code", "") or "")):
            if tok not in pnames:
                out.append(("warning", tr("validation.custom_unknown_param",
                                          name=name, p=tok), None))
        if not (d.get("code") or "").strip():
            out.append(("warning", tr("validation.custom_empty", name=name), None))

    def walk(actions, ti, tname):
        for a in (actions or []):
            if getattr(a, "kind", "") == "custom":
                cn = getattr(a, "custom_name", "") or ""
                if cn not in defs:
                    out.append(("error", tr("validation.custom_missing",
                                            t=tname, name=cn or "?"),
                                ("trigger", ti)))
            walk(getattr(a, "then_actions", None), ti, tname)
            walk(getattr(a, "else_actions", None), ti, tname)

    for ti, t in enumerate(getattr(w, "triggers", None) or []):
        walk(t.actions, ti, t.name)
    return out


def _check_text_vars(w):
    """$name in Nachricht/Dialog, das keine Missions-Variable ist -> Hinweis
    (bleibt woertlich im Text stehen).

    $name in message/dialog that is no mission variable -> notice (stays
    verbatim in the text)."""
    import re as _re
    out = []
    names = {v.name for v in (getattr(w, "variables", None) or [])}

    def walk(actions, ti, tname):
        for a in (actions or []):
            if getattr(a, "kind", "") in ("message", "showDialog"):
                for tok in set(_re.findall(r"\$(\w+)", getattr(a, "text", "") or "")):
                    if tok not in names:
                        out.append(("warning", tr("validation.text_var_unknown",
                                                  t=tname, v=tok), ("trigger", ti)))
            walk(getattr(a, "then_actions", None), ti, tname)
            walk(getattr(a, "else_actions", None), ti, tname)

    for ti, t in enumerate(getattr(w, "triggers", None) or []):
        walk(t.actions, ti, t.name)
    return out
