from __future__ import annotations

"""Missionvalidierung: prueft das Editor-Modell auf stille Fehler.

Mission validation: checks the editor model for silent errors that would
otherwise only surface as `// TODO` comments in the generated C++ or as a
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
    findings += _check_mine_beacons(w)
    findings += _check_tubes(w)
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


def _check_tubes(w):
    """Gebaeude ohne Tube-Verbindung zum Command Center sind im Spiel
    DEAKTIVIERT -- eine Basis mit mehreren Gebaeuden, aber ganz ohne
    Tubes, kann nicht funktionieren (Fabriken produzieren nichts).

    Buildings without a tube connection to the Command Center are DISABLED
    in-game -- a base with several structures but no tubes at all cannot
    work (factories produce nothing).
    """
    objects = getattr(w, "objects", None) or []
    has_tube = any(getattr(o, "map_id", "") == "mapTube" for o in objects)
    if has_tube:
        return []
    out = []
    from collections import Counter
    per_player = Counter(o.player for o in objects
                         if getattr(o, "kind", "") == "structure")
    for p, n in sorted(per_player.items()):
        if n >= 2:
            out.append(("warning", tr("validation.no_tubes", p=p, n=n), None))
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
