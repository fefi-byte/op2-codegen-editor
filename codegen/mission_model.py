"""Mission-Modell: die sprachunabhaengige Beschreibung einer Outpost-2-Mission.

Das ist das Herzstueck. Eine GUI wuerde spaeter genau diese Objekte
befuellen; der Codegen (codegen.py) liest sie und erzeugt LevelMain.cpp.
Hier wird absichtlich KEIN C++ erwaehnt -- reine Daten.

Mission model: the language-independent description of an Outpost 2 mission.

This is the core piece. A GUI would later populate exactly these objects;
the codegen (codegen.py) reads them and produces LevelMain.cpp.
Deliberately NO C++ is mentioned here -- pure data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class MissionType(IntEnum):
    """Entspricht MissionTypes in RequiredExports.h.

    Corresponds to MissionTypes in RequiredExports.h.
    """
    Colony = -1
    AutoDemo = -2
    Tutorial = -3
    MultiLandRush = -4
    MultiSpaceRace = -5
    MultiResourceRace = -6
    MultiMidas = -7
    MultiLastOneStanding = -8


class Colony(IntEnum):
    Eden = 0
    Plymouth = 1


@dataclass
class DifficultySetup:
    """Schwierigkeits-Multiplikatoren fuer drei Stufen.

    Difficulty multipliers for three levels.
    """
    hard: int = 13
    normal: int = 10
    easy: int = 5


@dataclass
class VariableDef:
    """Eine benutzerdefinierte Skript-Variable.

    A user-defined script variable.
    """
    name: str
    var_type: str = "int"     # "int" | "bool"
    initial_value: int = 0


@dataclass
class PlayerSpec:
    """Konfiguration eines Spielers.

    Configuration of a player.
    """
    colony: Colony = Colony.Eden
    is_human: bool = True          # True -> GoHuman, False -> GoAI
                                   # True -> GoHuman, False -> GoAI
    tech_level: int = 12           # 12 = alle Technologien (SetTechLevel)
                                   # 12 = all technologies (SetTechLevel)
    init_resources: bool = True    # Startressourcen via OP2Helper setzen
                                   # set starting resources via OP2Helper
    # Kolonisten (None = nicht explizit setzen)
    # Colonists (None = do not set explicitly)
    kids: int | None = None
    workers: int | None = None
    scientists: int | None = None
    # Ressourcen (None = nicht explizit setzen; str = Ausdruck mit 'diff')
    # Resources (None = do not set explicitly; str = expression containing 'diff')
    common_ore: int | str | None = None
    rare_ore: int | str | None = None
    food: int | str | None = None
    # Einzelne Vorab-Forschungen (Tech-IDs) zusaetzlich zu tech_level
    # Individual pre-researches (tech IDs) in addition to tech_level
    researches: list[int] = field(default_factory=list)


@dataclass
class UnitSpec:
    """Eine zu platzierende Einheit/Gebaeude.

    `unit_type` ist eine map_id (z.B. "mapCommandCenter"), Koordinaten
    sind 0-basierte Editor-Tile-Koordinaten. Der Codegen wandelt sie vor
    MkXY/XYPos/MkRect auf die 1-basierten OP2-Koordinaten um.

    A unit/building to be placed.

    `unit_type` is a map_id (e.g. "mapCommandCenter"); coordinates are
    0-based editor tile coordinates. The codegen converts them to the
    1-based OP2 coordinates before MkXY/XYPos/MkRect.
    """
    unit_type: str
    x: int
    y: int
    player: int = 0
    cargo: str = "mapNone"   # weaponCargoType bei CreateUnit
                             # weaponCargoType at CreateUnit
    rotation: int = 0
    truck_cargo: str | None = None   # Cargo Truck: SetTruckCargo(truck_cargo, truck_amount)
                                     # Cargo Truck: SetTruckCargo(truck_cargo, truck_amount)
    truck_amount: int = 1000
    convec_kit: str | None = None    # ConVec: SetCargo(convec_kit, mapNone) -- Gebaeude-Bausatz
                                     # ConVec: SetCargo(convec_kit, mapNone) -- building kit
    uid: str = ""                    # Editor-interne ID fuer Gruppenreferenzen
                                     # editor-internal ID for group references
    unit_name: str = ""              # Optionaler ScriptGlobal-Name fuer Zugriff nach Save/Load
                                     # optional ScriptGlobal name for access after Save/Load


def action_from_dict(d: dict) -> "TriggerAction":
    """Baut eine TriggerAction rekursiv aus einem Dict (inkl. Bedingungen + then/else).

    Builds a TriggerAction recursively from a dict (incl. conditions + then/else).
    Unknown keys (e.g. from older save files) are silently dropped.
    """
    import dataclasses
    d = dict(d)
    conds = [ActionCondition(**c) for c in d.pop("conditions", [])]
    then = [action_from_dict(a) for a in d.pop("then_actions", [])]
    els = [action_from_dict(a) for a in d.pop("else_actions", [])]
    valid = {f.name for f in dataclasses.fields(TriggerAction)} - {"conditions", "then_actions", "else_actions"}
    d = {k: v for k, v in d.items() if k in valid}
    return TriggerAction(conditions=conds, then_actions=then, else_actions=els, **d)


@dataclass
class BeaconSpec:
    """Mining Beacon / Magma Vent / Fumarole (Geysir).

    Mining Beacon / Magma Vent / Fumarole (geyser).
    """
    beacon_type: str          # mapMiningBeacon / mapMagmaVent / mapFumarole
                              # mapMiningBeacon / mapMagmaVent / mapFumarole
    x: int
    y: int
    ore_type: int = -1        # -1 zufaellig, 0 common, 1 rare (nur Mining Beacon)
                              # -1 random, 0 common, 1 rare (Mining Beacon only)
    yield_bars: int = -1      # -1 zufaellig, 0=Bar3, 1=Bar2, 2=Bar1
                              # -1 random, 0=Bar3, 1=Bar2, 2=Bar1
    variant: int = -1         # -1 zufaellig, 0..2
                              # -1 random, 0..2


@dataclass
class WallTubeSpec:
    """Mauer oder Rohr (einzelne Kachel).

    Wall or tube (single tile).
    """
    wall_type: str            # mapTube / mapWall / mapLavaWall / mapMicrobeWall
                              # mapTube / mapWall / mapLavaWall / mapMicrobeWall
    x: int
    y: int


@dataclass
class BuildingGroupSpec:
    """BuildingGroup: Builder-Einheiten und Standardbereich.

    BuildingGroup: builder units and default area.
    """
    name: str
    player: int = 0
    rect_x: int = 0
    rect_y: int = 0
    rect_width: int = 8
    rect_height: int = 8
    unit_ids: list[str] = field(default_factory=list)
    folder: str = ""


@dataclass
class ReinforceTargetSpec:
    """Zielgruppe, die von einer ReinforceGroup Fahrzeuge anfordern darf.

    Target group that is allowed to request vehicles from a ReinforceGroup.
    """
    group_name: str
    priority: int = 1000


@dataclass
class ReinforceGroupSpec:
    """ReinforceGroup: BuildingGroup mit Vehicle-Factories fuer Fahrzeugnachschub.

    ReinforceGroup: BuildingGroup with vehicle factories for vehicle resupply.
    """
    name: str
    player: int = 0
    unit_ids: list[str] = field(default_factory=list)
    targets: list[ReinforceTargetSpec] = field(default_factory=list)
    folder: str = ""


@dataclass
class ActionCondition:
    """Eine IF-Bedingung, die eine einzelne Aktion gated (Home-Assistant-Stil).

    kind: buildingAtLocation | unitDamage | playerResource | buildingCount | hasTech | varCheck

    An IF condition that gates a single action (Home Assistant style).

    kind: buildingAtLocation | unitDamage | playerResource | buildingCount | hasTech | varCheck
    """
    kind: str
    negate: bool = False
    player: int = 0
    building_type: str = "mapCommandCenter"
    x: int = 0
    y: int = 0
    compare: str = "cmpGreaterEqual"
    value: int | str = 0      # int oder Ausdruck (z.B. "5 * diff / 10")
    resource: str = "resCommonOre"
    tech_id: int = 0
    var_name: str = ""        # fuer varCheck: Variable die geprueft wird


@dataclass
class TriggerAction:
    """Eine Aktion in der Callback-Funktion eines Triggers.

    An action inside the callback function of a trigger.
    """
    kind: str                 # "message" | "createUnit" | "createTrigger" | "recordBuilding" | "recordTube" | "recordWall" | "setTargCount" | "assignToGroup" | "modVar" | "createDisaster" | legacy: "createMeteor" | "createEarthquake" | "createStorm" | "createVortex" | "createBlight" | "unsetBlight"
    text: str = ""
    unit_type: str = "mapScout"
    weapon_type: str = "mapNone"
    target_count: int | str = 1   # int oder Ausdruck (z.B. "ceil(5 * diff / 10)")
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    player: int = 0
    target: str = ""          # createTrigger -> Name eines anderen Triggers (Laufzeit-Erstellung)
    group_name: str = ""      # BuildingGroup-Aktionen
    source_group_name: str = ""  # ReinforceGroup, die SetTargCount-Zielgruppe beliefert
    reinforce_priority: int = 1000
    building_type: str = "mapCommandCenter"
    wall_type: str = "mapWall"
    conditions: list["ActionCondition"] = field(default_factory=list)
    condition_logic: str = "and"
    then_actions: list["TriggerAction"] = field(default_factory=list)
    else_actions: list["TriggerAction"] = field(default_factory=list)
    # modVar: Variable modifizieren
    var_name: str = ""        # Name der Variablen
    mod_mode: str = "inc"     # "inc" (+1) | "dec" (-1) | "expr" (Ausdruck)
    var_expr: str = ""        # Ausdruck fuer mod_mode=="expr"
    # Disaster actions: expression-based coordinates, shared by point/path effects.
    disaster_type: str = "meteor"   # meteor | earthquake | storm | vortex | eruption | blight | unblight
    x_expr: int | str = 0
    y_expr: int | str = 0
    x2_expr: int | str = 0
    y2_expr: int | str = 0
    size: int = -1            # -1=random, 0=large, 1=medium, 2=small
    magnitude: int | str = 1
    duration: int | str = 100
    spread_speed: int = 15    # eruption lava spread speed (15=very slow, 45=medium)
    lava_zone: list = field(default_factory=list)  # [[x, y], ...] tiles for setLavaPossible
    now: bool = False


@dataclass
class FindUnitCheck:
    """Eine Position + erwarteter Unit-Typ fuer den `findUnit`-Trigger.

    Im generierten Code uebersetzt sich jeder Check zu:
        Unit b = GameMap::unitOnTile({x+1, y+1});
        bool ready = b.isLive() && b.type() == MapID::<unit_type> && b.enabled();
    Mehrere Checks innerhalb eines Triggers werden UND-verknuepft.
    """
    unit_type: str = "mapCommandCenter"
    x: int = 0
    y: int = 0


@dataclass
class TriggerDef:
    """Ein benutzerdefinierter Trigger: Bedingung + Aktionen.

    `enabled_at_start`: True -> wird in InitProc erzeugt; False -> entsteht nur,
    wenn ein anderer Trigger ihn per createTrigger-Aktion erstellt (Laufzeit).
    `condition` waehlt die OP2-Trigger-Funktion; genutzte Felder je condition:
      time          -> marks
      point         -> player, x, y
      rect          -> player, x, y, width, height
      buildingCount -> player, count, compare
      vehicleCount  -> player, count, compare
      research      -> player, tech_id
      resource      -> player, resource, amount, compare
      operational   -> player, building, count, compare
      findUnit      -> unit_checks  (alle UND-verknuepft, `enabled()`-Check pro Eintrag)

    A user-defined trigger: condition + actions.
    """
    name: str
    enabled_at_start: bool = True
    one_shot: bool = True
    condition: str = "time"
    marks: int | str = 100    # int oder Ausdruck (z.B. "600 * diff / 10")
    player: int = 0
    count: int = 1
    compare: str = "cmpGreaterEqual"
    tech_id: int = 0
    resource: str = "resCommonOre"
    amount: int = 1000
    building: str = "mapCommandCenter"
    x: int = 0
    y: int = 0
    width: int = 1
    height: int = 1
    actions: list[TriggerAction] = field(default_factory=list)
    unit_checks: list[FindUnitCheck] = field(default_factory=list)
    folder: str = ""


@dataclass
class StartMessage:
    """Nachricht, die zu Spielbeginn allen Spielern angezeigt wird.

    Message shown to all players at the start of the game.
    """
    text: str


@dataclass
class Condition:
    """Eine Sieg- oder Niederlage-Bedingung.

    `kind` waehlt die OP2-Trigger-/Helper-Funktion; je nach kind werden nur
    bestimmte Felder verwendet:
      time          -> marks, objective
      lastStanding  -> (Helper, Sieg)
      starship      -> (Helper, Sieg)
      noCC          -> player (Helper, Niederlage)
      buildingCount -> player, count, compare, objective
      vehicleCount  -> player, count, compare, objective
      research      -> player, tech_id, objective
      resource      -> player, resource, amount, compare, objective
      operational   -> player, building, count, compare, objective

    A victory or defeat condition.

    `kind` selects the OP2 trigger/helper function; depending on kind only
    certain fields are used:
      time          -> marks, objective
      lastStanding  -> (helper, victory)
      starship      -> (helper, victory)
      noCC          -> player (helper, defeat)
      buildingCount -> player, count, compare, objective
      vehicleCount  -> player, count, compare, objective
      research      -> player, tech_id, objective
      resource      -> player, resource, amount, compare, objective
      operational   -> player, building, count, compare, objective
    """
    kind: str
    objective: str = ""
    player: int = 0
    marks: int = 600
    count: int = 1
    compare: str = "cmpGreaterEqual"
    tech_id: int = 0
    resource: str = "resCommonOre"
    amount: int = 1000
    building: str = "mapCommandCenter"


@dataclass
class Mission:
    """Vollstaendige Missionsbeschreibung -- der Wurzelknoten des Modells.

    Complete mission description -- the root node of the model.
    """
    name: str
    map: str
    tech_tree: str = "MULTITEK.TXT"
    type: MissionType = MissionType.Colony
    num_players: int = 1

    players: list[PlayerSpec] = field(default_factory=lambda: [PlayerSpec()])
    units: list[UnitSpec] = field(default_factory=list)
    beacons: list[BeaconSpec] = field(default_factory=list)
    walls_tubes: list[WallTubeSpec] = field(default_factory=list)
    building_groups: list[BuildingGroupSpec] = field(default_factory=list)
    reinforce_groups: list[ReinforceGroupSpec] = field(default_factory=list)
    triggers: list[TriggerDef] = field(default_factory=list)
    start_message: StartMessage | None = None
    victories: list[Condition] = field(default_factory=list)
    defeats: list[Condition] = field(default_factory=list)
    difficulty: DifficultySetup = field(default_factory=DifficultySetup)
    variables: list[VariableDef] = field(default_factory=list)
