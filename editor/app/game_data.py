from __future__ import annotations

from . import i18n

# Footprints from building.txt (X-size, Y-size).
# map_ids match the classic Outpost2DLL map_id enum member names ("mapXxx").

# Alphabetically sorted so the placement panel is predictable.
STRUCTURES = sorted([
    ("Command Center",       "mapCommandCenter",      (3, 2)),
    ("Tokamak",              "mapTokamak",             (2, 2)),
    ("MHD Generator",        "mapMHDGenerator",        (2, 2)),
    ("Solar Power Array",    "mapSolarPowerArray",     (3, 2)),
    ("Geothermal Plant",     "mapGeothermalPlant",     (2, 1)),
    ("Structure Factory",    "mapStructureFactory",    (4, 3)),
    ("Vehicle Factory",      "mapVehicleFactory",      (4, 3)),
    ("Arachnid Factory",     "mapArachnidFactory",     (2, 2)),
    ("Consumer Factory",     "mapConsumerFactory",     (3, 3)),
    ("Common Ore Mine",      "mapCommonOreMine",       (2, 1)),
    ("Rare Ore Mine",        "mapRareOreMine",         (2, 1)),
    ("Common Ore Smelter",   "mapCommonOreSmelter",    (4, 3)),
    ("Rare Ore Smelter",     "mapRareOreSmelter",      (4, 3)),
    ("Common Storage",       "mapCommonStorage",       (1, 2)),
    ("Rare Storage",         "mapRareStorage",         (1, 2)),
    ("Magma Well",           "mapMagmaWell",           (2, 1)),
    ("Basic Lab",            "mapBasicLab",            (2, 2)),
    ("Standard Lab",         "mapStandardLab",         (3, 2)),
    ("Advanced Lab",         "mapAdvancedLab",         (3, 3)),
    ("Observatory",          "mapObservatory",         (2, 2)),
    ("Residence",            "mapResidence",           (2, 2)),
    ("Reinforced Residence", "mapReinforcedResidence", (3, 2)),
    ("Advanced Residence",   "mapAdvancedResidence",   (3, 3)),
    ("Nursery",              "mapNursery",             (2, 2)),
    ("University",           "mapUniversity",          (2, 2)),
    ("Medical Center",       "mapMedicalCenter",       (2, 2)),
    ("Agridome",             "mapAgridome",            (3, 2)),
    ("GORF",                 "mapGORF",                (3, 2)),
    ("Recreation Facility",  "mapRecreationFacility",  (2, 2)),
    ("Forum",                "mapForum",               (2, 2)),
    ("Trade Center",         "mapTradeCenter",         (2, 2)),
    ("DIRT",                 "mapDIRT",                (3, 2)),
    ("Guard Post",           "mapGuardPost",           (1, 1)),
    ("Light Tower",          "mapLightTower",          (1, 1)),
    ("Meteor Defense",       "mapMeteorDefense",       (2, 2)),
    ("Garage",               "mapGarage",              (3, 2)),
    ("Robot Command",        "mapRobotCommand",        (2, 2)),
    ("Spaceport",            "mapSpaceport",           (5, 4)),
], key=lambda s: s[0].lower())

VEHICLES = [
    # Utility
    ("Scout",                   "mapScout",                   (1, 1)),
    ("Cargo Truck",             "mapCargoTruck",              (1, 1)),
    ("ConVec",                  "mapConVec",                  (1, 1)),
    ("Robo-Miner",              "mapRoboMiner",               (1, 1)),
    ("Robo-Surveyor",           "mapRoboSurveyor",            (1, 1)),
    ("Robo-Dozer",              "mapRoboDozer",               (1, 1)),
    ("Earthworker",             "mapEarthworker",             (1, 1)),
    ("Repair Vehicle",          "mapRepairVehicle",           (1, 1)),
    ("Geo-Con",                 "mapGeoCon",                  (1, 1)),
    ("Evacuation Transport",    "mapEvacuationTransport",     (1, 1)),
    # Combat
    ("Lynx",                    "mapLynx",                    (1, 1)),
    ("Panther",                 "mapPanther",                 (1, 1)),
    ("Tiger",                   "mapTiger",                   (1, 1)),
    ("Spider",                  "mapSpider",                  (1, 1)),
    ("Scorpion",                "mapScorpion",                (1, 1)),
    # Packs
    ("Spider 3-Pack",           "mapSpider3Pack",             (1, 1)),
    ("Scorpion 3-Pack",         "mapScorpion3Pack",           (1, 1)),
]

# Walls & tubes (also used by the trigger dialog)
WALL_ITEMS = [
    ("Tube",         "mapTube",        (1, 1)),
    ("Wall",         "mapWall",        (1, 1)),
    ("Lava Wall",    "mapLavaWall",    (1, 1)),
    ("Microbe Wall", "mapMicrobeWall", (1, 1)),
]

# Category -> (kind, items)
CATALOG = {
    "Gebäude": ("structure", STRUCTURES),
    "Fahrzeuge": ("vehicle", VEHICLES),
    # Beacons, magma vents, geysers, walls & tubes in one category.
    # Entries with a 4th element override the category's default kind.
    "Beacons & Mauern": ("beacon", [
        ("Mining Beacon", "mapMiningBeacon", (1, 1)),
        ("Magma Vent",    "mapMagmaVent",    (1, 1)),
        ("Fumarole",      "mapFumarole",     (1, 1)),
    ] + [(d, m, fp, "wall") for d, m, fp in WALL_ITEMS]),
}

# Units/buildings that can carry a weapon (weapon choice when placing)
WEAPON_UNITS = {"mapLynx", "mapPanther", "mapTiger", "mapSpider", "mapScorpion", "mapGuardPost"}

# Units/buildings for "create unit" actions (display name -> map_id)
ALL_UNITS = [(d, m) for d, m, _ in STRUCTURES] + [(d, m) for d, m, _ in VEHICLES]
VEHICLE_UNITS = [(d, m) for d, m, _ in VEHICLES]

# Spaceport-Produkte: Raketen, Satelliten und Starship-Module (map_id-Enum
# 0x58-0x6B). Werden per DoProduce am Spaceport gebaut; SULV/RLV/EMP Missile
# landen auf der Startrampe statt in einer Bucht.
# Spaceport products: rockets, satellites and starship modules (map_id enum
# 0x58-0x6B). Built via DoProduce at the Spaceport; SULV/RLV/EMP Missile end
# up on the launch pad instead of in a bay.
SPACEPORT_PRODUCTS = [
    ("SULV (Rakete)",          "mapSULV"),
    ("RLV (wiederverwendbar)", "mapRLV"),
    ("EMP Missile",            "mapEMPMissile"),
    ("EDWARD Satellite",       "mapEDWARDSatellite"),
    ("Solar Power Satellite",  "mapSolarSatellite"),
    ("Ion Drive Module",       "mapIonDriveModule"),
    ("Fusion Drive Module",    "mapFusionDriveModule"),
    ("Command Module",         "mapCommandModule"),
    ("Fueling Systems",        "mapFuelingSystems"),
    ("Habitat Ring",           "mapHabitatRing"),
    ("Sensor Package",         "mapSensorPackage"),
    ("Skydock",                "mapSkydock"),
    ("Stasis Systems",         "mapStasisSystems"),
    ("Orbital Package",        "mapOrbitalPackage"),
    ("Phoenix Module",         "mapPhoenixModule"),
    ("Evacuation Module",      "mapEvacuationModule"),
    ("Children Module",        "mapChildrenModule"),
]
# Cargo-Truck-Subtyp bei Ladung Raumschiffteil/Schrott (Truck_Cargo
# truckSpaceport/truckGarbage): die "Menge" ist dort keine Stueckzahl, sondern
# waehlt (wie in Unit.SetTruckCargo/UnitEx.GetCargoAmount gepackt: cargoType |
# (subtype << 4)) genau dieses Teil aus. Andere Teilemenge als bei
# SPACEPORT_PRODUCTS (dort fehlen die drei Cargo-Pseudo-Einheiten, dafuer sind
# SULV/RLV/EMP Missile drin, die ein Truck nie transportiert).
#
# Cargo Truck subtype for Spaceport/Garbage cargo (Truck_Cargo
# truckSpaceport/truckGarbage): the "amount" there is not a quantity but
# (packed as in Unit.SetTruckCargo/UnitEx.GetCargoAmount: cargoType |
# (subtype << 4)) selects exactly this part. Different set of parts than
# SPACEPORT_PRODUCTS (which lacks the three cargo pseudo-units but includes
# SULV/RLV/EMP Missile, which a truck never carries).
TRUCK_SPACESHIP_PARTS = [
    ("EDWARD Satellite",       "mapEDWARDSatellite"),
    ("Solar Power Satellite",  "mapSolarSatellite"),
    ("Ion Drive Module",       "mapIonDriveModule"),
    ("Fusion Drive Module",    "mapFusionDriveModule"),
    ("Command Module",        "mapCommandModule"),
    ("Fueling Systems",       "mapFuelingSystems"),
    ("Habitat Ring",          "mapHabitatRing"),
    ("Sensor Package",        "mapSensorPackage"),
    ("Skydock",               "mapSkydock"),
    ("Stasis Systems",        "mapStasisSystems"),
    ("Orbital Package",       "mapOrbitalPackage"),
    ("Phoenix Module",        "mapPhoenixModule"),
    ("Rare Metals Cargo",     "mapRareMetalsCargo"),
    ("Common Metals Cargo",   "mapCommonMetalsCargo"),
    ("Food Cargo",            "mapFoodCargo"),
    ("Evacuation Module",     "mapEvacuationModule"),
    ("Children Module",       "mapChildrenModule"),
]
# Truck_Cargo-Codes, deren "Menge" ein Teil-Subtyp ist (siehe oben) statt einer
# Stueckzahl.
TRUCK_CARGO_SUBTYPED_CODES = {"truckSpaceport", "truckGarbage"}

MILITARY_VEHICLES = [
    (d, m) for d, m, _ in VEHICLES
    if m in ("mapLynx", "mapPanther", "mapTiger", "mapSpider", "mapScorpion")
]

# BuildingGroup may produce all builder units
BUILDING_GROUP_VEHICLES = [
    ("ConVec",               "mapConVec"),
    ("Robo-Miner",           "mapRoboMiner"),
    ("Robo-Surveyor",        "mapRoboSurveyor"),
    ("Robo-Dozer",           "mapRoboDozer"),
    ("Earthworker",          "mapEarthworker"),
    ("Geo-Con",              "mapGeoCon"),
    ("Repair Vehicle",       "mapRepairVehicle"),
    ("Cargo Truck",          "mapCargoTruck"),
    ("Evacuation Transport", "mapEvacuationTransport"),
    ("Scout",                "mapScout"),
]

# ReinforceGroup is a BuildingGroup with Vehicle Factories
REINFORCE_GROUP_VEHICLES = BUILDING_GROUP_VEHICLES + MILITARY_VEHICLES
SET_TARG_VEHICLES_BY_GROUP_TYPE = {
    "BuildingGroup":  BUILDING_GROUP_VEHICLES,
    "ReinforceGroup": REINFORCE_GROUP_VEHICLES,
    "FightGroup":     MILITARY_VEHICLES,
}

STRUCTURE_FOOTPRINTS = {mid: fp for _, mid, fp in STRUCTURES}

WEAPONS = [
    ("None",          "mapNone"),
    ("Laser",         "mapLaser"),
    ("Microwave",     "mapMicrowave"),
    ("Rail Gun",      "mapRailGun"),
    ("RPG",           "mapRPG"),
    ("EMP",           "mapEMP"),
    ("ESG",           "mapESG"),
    ("Stickyfoam",    "mapStickyfoam"),
    ("Thor's Hammer", "mapThorsHammer"),
    ("Energy Cannon", "mapEnergyCannon"),
    ("Starflare",     "mapStarflare"),
    ("Supernova",     "mapSupernova"),
    ("Acid Cloud",    "mapAcidCloud"),
    ("BFG",           "mapBFG"),
]

# Truck_Cargo-Codes mit einer echten Stueckzahl (amount = Menge). Spaceport/
# Garbage sind bewusst ausgeschlossen -- dort ist amount ein Teil-Subtyp
# (siehe truck_cargo_items() unten).
# Truck_Cargo codes with a real quantity (amount = quantity). Spaceport/
# Garbage are deliberately excluded -- there amount is a part subtype
# (see truck_cargo_items() below).
QUANTIFIED_TRUCK_CARGO_CODES = [
    "truckCommonOre", "truckRareOre", "truckFood",
    "truckCommonMetal", "truckRareMetal",
    "truckCommonRubble", "truckRareRubble",
]


def truck_cargo_items() -> list[tuple[str, str]]:
    """(Anzeigename, Wert)-Paare fuer die Cargo-Truck-Ladung beim Platzieren.

    Menge-Frachten kommen zuerst; Spaceport/Schrott folgen als "code:teil"
    (siehe TRUCK_SPACESHIP_PARTS), Leer am Ende.

    (Display name, value) pairs for the Cargo Truck cargo dropdown when
    placing a unit. Quantified cargos first; Spaceport/Garbage follow as
    "code:part" (see TRUCK_SPACESHIP_PARTS), Empty last.
    """
    tr = i18n.tr
    items = [(tr(f"truck_cargo.{code}"), code) for code in QUANTIFIED_TRUCK_CARGO_CODES]
    for base_code in ("truckSpaceport", "truckGarbage"):
        base_label = tr(f"truck_cargo.{base_code}")
        for part_label, part_id in TRUCK_SPACESHIP_PARTS:
            items.append((f"{base_label}: {part_label}", f"{base_code}:{part_id}"))
    items.append((tr("truck_cargo.truckEmpty"), "truckEmpty"))
    return items

# "Fahrzeug mit Ladung"-Bedingung (Sieg&Niederlage-Panel): welche Ladungsoptionen je
# nach gewaehltem Fahrzeugtyp angezeigt werden -- ConVec traegt Gebaeude-
# Bausaetze (map_id wie beim Bau-Kit), Cargo Trucks tragen Frachtgueter
# (Truck_Cargo, cast auf map_id im Codegen), die drei Kampffahrzeuge tragen
# Waffen (map_id), alle anderen Fahrzeuge haben keine sinnvolle Ladung.
#
# "Vehicle with cargo" condition (victory&defeat panel): which cargo options are
# shown depending on the selected vehicle type -- ConVecs carry building kits
# (map_id, like the construction kit), Cargo Trucks carry freight
# (Truck_Cargo, cast to map_id in codegen), the three combat vehicles carry
# weapons (map_id), every other vehicle has no meaningful cargo.
CARGO_CONDITION_TRUCK_CODES = [
    "truckCommonOre", "truckRareOre", "truckFood",
    "truckCommonRubble", "truckRareRubble",
    "truckSpaceport", "truckGarbage", "truckEmpty",
]
CARGO_CONDITION_WEAPON_VEHICLES = {"mapLynx", "mapPanther", "mapTiger"}


def condition_cargo_items(unit_type: str) -> list[tuple[str, str]]:
    """(Anzeigename, Wert)-Paare fuer das Ladung-Dropdown der Kinds
    vehicleCargo/escape (Sieg&Niederlage-Panel UND TriggerPanel teilen sich das),
    gefiltert nach Fahrzeugtyp: ConVec -> Gebaeude-Bausaetze, Cargo Truck ->
    Frachtgueter (inkl. Spaceport/Schrott-Teile), Lynx/Panther/Tiger ->
    Waffen, sonst nur "Keine" (mapNone).
    """
    tr = i18n.tr
    items: list[tuple[str, str]] = []
    if unit_type == "mapConVec":
        items.append((tr("truck_cargo.mapAny"), "mapAny"))
        items.append((tr("truck_cargo.mapNone"), "mapNone"))
        items += [(disp, mid) for disp, mid, _ in STRUCTURES]
    elif unit_type == "mapCargoTruck":
        items.append((tr("truck_cargo.mapAny"), "mapAny"))
        for code in CARGO_CONDITION_TRUCK_CODES:
            items.append((tr(f"truck_cargo.{code}"), code))
            if code in TRUCK_CARGO_SUBTYPED_CODES:
                base_label = tr(f"truck_cargo.{code}")
                for part_label, part_id in TRUCK_SPACESHIP_PARTS:
                    items.append((f"{base_label}: {part_label}", f"{code}:{part_id}"))
    elif unit_type in CARGO_CONDITION_WEAPON_VEHICLES:
        items.append((tr("truck_cargo.mapAny"), "mapAny"))
        items += list(WEAPONS)
    else:
        items.append((tr("truck_cargo.mapNone"), "mapNone"))
    return items


ORE_TYPES = {"Random": -1, "Common": 0, "Rare": 1}
YIELDS = {"Random": -1, "Bar3 (high)": 0, "Bar2 (medium)": 1, "Bar1 (low)": 2}

# Victory/defeat conditions: display name -> (kind, [fields used])
CONDITIONS = {
    "Zeit überstehen":    ("time",          ["marks", "objective"]),
    "Letzter Überlebender": ("lastStanding", []),
    "Raumschiff bauen":   ("starship",       []),
    "Gebäude-Anzahl":     ("buildingCount",  ["player", "count", "compare", "objective"]),
    "Fahrzeug-Anzahl":    ("vehicleCount",   ["player", "count", "compare", "objective"]),
    "Fahrzeug mit Ladung": ("vehicleCargo",  ["player", "unit_type", "cargo", "count", "compare", "objective"]),
    "Technologie erforscht": ("research",    ["player", "tech_id", "objective"]),
    "Ressource erreicht": ("resource",       ["player", "resource", "amount", "compare", "objective"]),
    "Gebäude operativ":   ("operational",    ["player", "building", "count", "compare", "objective"]),
    "Kein Command Center": ("noCC",          ["player"]),
    "Punkt erreicht":     ("point",          ["player", "x", "y", "objective"]),
    "Rechteck betreten":  ("rect",           ["player", "x", "y", "width", "height", "objective"]),
    "Gruppe wird angegriffen": ("attacked",  ["trigger_group", "objective"]),
    "Gruppe beschädigt":  ("damaged",        ["trigger_group", "damage_type", "objective"]),
    "Einheit scannt Gebäude": ("specialTarget", ["target_unit", "source_unit_type", "objective"]),
    "Nur ein Spieler übrig (Engine)": ("onePlayerLeft", ["objective"]),
    "Evakuierung (Spacerace)": ("evac",      ["player", "objective"]),
    "Midas-Modus":        ("midas",          ["marks", "objective"]),
    "Bausatz-Anzahl":     ("kit",            ["player", "building", "count", "objective"]),
    "Flucht-Zone":        ("escape",         ["player", "x", "y", "width", "height",
                                              "unit_type", "cargo", "count", "amount", "objective"]),
}
COMPARE = {"≥": "cmpGreaterEqual", "≤": "cmpLowerEqual", "=": "cmpEqual",
           ">": "cmpGreater", "<": "cmpLower"}
RESOURCES = {
    "Common Ore": "resCommonOre", "Rare Ore": "resRareOre", "Food": "resFood",
    "Kids": "resKids", "Workers": "resWorkers", "Scientists": "resScientists",
}

# Trigger conditions: display name -> (kind, [fields])
TRIGGER_CONDITIONS = {
    "Zeit (Marks)":           ("time",          ["marks"]),
    "Punkt erreicht":         ("point",         ["player", "x", "y"]),
    "Rechteck betreten":      ("rect",          ["player", "x", "y", "width", "height"]),
    "Gebäude-Anzahl":         ("buildingCount", ["player", "count", "compare"]),
    "Fahrzeug-Anzahl":        ("vehicleCount",  ["player", "count", "compare"]),
    "Technologie erforscht":  ("research",      ["player", "tech_id"]),
    "Ressource erreicht":     ("resource",      ["player", "resource", "amount", "compare"]),
    "Gebäude operativ":       ("operational",   ["player", "building", "count", "compare"]),
    "Einheit(en) an Position(en) bereit": ("findUnit", ["unit_checks"]),
    "Gruppe wird angegriffen": ("attacked",     ["trigger_group"]),
    "Gruppe beschädigt":      ("damaged",       ["trigger_group", "damage_type"]),
    "Einheit scannt Gebäude": ("specialTarget", ["target_unit", "source_unit_type"]),
    "Einheit zerstört":       ("unitDied",      ["target_unit"]),
    "Fahrzeug mit Ladung":    ("vehicleCargo",  ["player", "unit_type", "cargo", "count", "compare"]),
    "Nur ein Spieler übrig (Engine)": ("onePlayerLeft", []),
    "Evakuierung (Spacerace)": ("evac",         ["player"]),
    "Midas-Modus":            ("midas",         ["marks"]),
    "Bausatz-Anzahl":         ("kit",           ["player", "building", "count"]),
    "Flucht-Zone":            ("escape",        ["player", "x", "y", "width", "height",
                                                  "unit_type", "cargo", "count", "amount"]),
}

# CreateDamagedTrigger: Anteil der zerstoerten Gruppe (DamageType-Enum).
# CreateDamagedTrigger: fraction of the group destroyed (DamageType enum).
DAMAGE_TYPES = {
    "50 % zerstört":  3,   # Damage50
    "75 % zerstört":  2,   # Damage75
    "100 % zerstört": 1,   # Damage100
}

ACTION_KINDS = {
    "Leere Aktion (Platzhalter)":        "noop",
    "Wenn / Dann / Sonst (Bedingungsblock)": "if",
    "Nachricht anzeigen":                "message",
    "Dialog anzeigen":                   "showDialog",
    "Einheit erzeugen":                  "createUnit",
    "Katastrophe ausloesen":             "createDisaster",
    "Anderen Trigger erstellen (Laufzeit)": "createTrigger",
    "Trigger beenden":                   "stopTrigger",
    "RecordBuilding":                    "recordBuilding",
    "RecordTube-Linie":                  "recordTube",
    "RecordWall-Linie":                  "recordWall",
    "SetTargCount":                      "setTargCount",
    "Gebäude einer Gruppe zuweisen":     "assignToGroup",
    "Variable ändern":                   "modVar",
    "Mining starten (Makro)":            "startMining",
    "Angriffswelle senden (Makro)":      "sendAttackWave",
    "Gruppen-Befehl":                    "fightGroupCmd",
    "Einheiten-Befehl":                  "unitCmd",
    "Gebiet verteidigen (Makro)":        "defendArea",
    "Gebäude reparieren (Makro)":        "repairBuildings",
    "EMP-Rakete abfeuern":               "empMissile",
    "Moral setzen":                      "setMorale",
    "Musik-Playlist setzen":             "setMusic",
    "Lavastrom-Animation":               "lavaFlowAni",
    "Einheiten-Werte ändern (HFL)":      "modUnitStats",
    "Eigener C++-Code":                  "customCode",
    "Eigene Aktion (Designer)":          "custom",
    "Siegbedingung hinzufügen":          "addVictory",
    "Niederlagebedingung hinzufügen":    "addDefeat",
}

# Gruppierung des "+ Aktion"-Menues (Untermenue -> Aktions-Kinds).
# "noop" und "defendArea" werden bewusst NICHT mehr angeboten (Platzhalter
# bzw. durch FightGroups + Gruppen-Befehl abgeloest); bestehende Projekte
# mit diesen Aktionen laden und bauen aber weiterhin.
# Grouping of the "+ add action" menu (submenu -> action kinds).
# "noop" and "defendArea" are deliberately NOT offered any more (placeholder
# resp. superseded by FightGroups + group command); existing projects using
# them still load and build.
ACTION_MENU_GROUPS = {
    "general":  ["if", "message", "showDialog", "modVar", "createTrigger", "stopTrigger",
                 "addVictory", "addDefeat", "customCode"],
    "units":    ["createUnit", "unitCmd", "fightGroupCmd",
                 "assignToGroup", "setTargCount"],
    "record":   ["recordBuilding", "recordTube", "recordWall"],
    "macros":   ["startMining", "sendAttackWave", "repairBuildings"],
    "effects":  ["createDisaster", "empMissile", "lavaFlowAni",
                 "setMorale", "setMusic", "modUnitStats"],
}

# setMorale: Modus -> ForceMoraleX/FreeMoraleLevel
MORALE_MODES = {
    "Sehr gut (Great)":   "great",
    "Gut (Good)":         "good",
    "Mittel (OK)":        "ok",
    "Schlecht (Poor)":    "poor",
    "Miserabel (Rotten)": "rotten",
    "Freigeben (frei berechnen)": "free",
}

# lavaFlowAni: Fliessrichtung am Vulkanhang (OP2Helper Lava.h)
FLOW_DIRS = {
    "Süd":      "S",
    "Südwest":  "SW",
    "Südost":   "SE",
}

# setMusic: alle SongIds aus Outpost2DLL Enums.h (Reihenfolge = Enum-Wert).
SONG_IDS = [
    "songEden11", "songEden21", "songEden22", "songEden31", "songEden32",
    "songEden33", "songEP41", "songEP42", "songEP43", "songEP51", "songEP52",
    "songEP61", "songEP62", "songEP63", "songPlymth11", "songPlymth12",
    "songPlymth21", "songPlymth22", "songPlymth31", "songPlymth32",
    "songPlymth33", "songStatic01", "songStatic02", "songStatic03",
    "songStatic04", "songStatic05",
]

# modUnitStats: HFL-UnitInfo-Setter (Anzeige-Label kommt aus i18n
# unit_stats.<Name>, C++-Aufruf ist Set<Name>(player, value)).
UNIT_STATS = [
    "HitPoints", "Armor", "OreCost", "RareOreCost", "BuildTime",
    "SightRange", "WeaponRange", "PowerRequired", "MovePoints",
    "ConcussionDamage", "PenetrationDamage", "ReloadTime",
    "StorageCapacity", "ProductionRate", "CargoCapacity",
    "WorkersRequired", "ScientistsRequired",
]

# IF conditions per action: display name -> (kind, [fields])
# Ordered lists of internal ids. Display labels come from i18n at usage
# time (tr("meteor_sizes.<id>") / tr("disaster_types.<id>")).
METEOR_SIZES = [-1, 0, 1, 2]
DISASTER_TYPES = ["meteor", "earthquake", "storm", "vortex", "eruption", "blight", "unblight"]

# IF conditions per action: display name -> (kind, [fields])
ACTION_CONDITION_KINDS = {
    "Gebäude an Position vorhanden": ("buildingAtLocation", ["player", "building", "x", "y"]),
    "Gebäude-Schaden an Position":   ("unitDamage",         ["player", "building", "x", "y", "compare", "value"]),
    "Spieler-Ressource":             ("playerResource",     ["player", "resource", "compare", "value"]),
    "Gebäude-Anzahl":                ("buildingCount",      ["player", "building", "compare", "value"]),
    "Technologie erforscht":         ("hasTech",            ["player", "tech_id"]),
    "Variable prüfen":               ("varCheck",           ["var_name", "compare", "value"]),
    # Bedingungen auf die Schleifen-Einheit `unit` (nur in forEach-Schleifen)
    # Conditions on the forEach loop unit `unit`
    "Schleifen-Einheit: Typ ist":        ("loopUnitType",   ["unit", "loop_level"]),
    "Schleifen-Einheit: Schaden":        ("loopUnitDamage", ["compare", "value", "loop_level"]),
    "Schleifen-Einheit: Fracht/Waffe":   ("loopUnitCargo",  ["unit", "loop_level"]),
    "Schleifen-Einheit: Befehl ist":     ("loopUnitCommand", ["command", "loop_level"]),
}

# Auswahl fuer "Schleifen-Einheit: Befehl ist" -> Anzeige -> abi::CommandType-Name.
# Choices for "loop unit: command is" -> display -> abi::CommandType name.
UNIT_COMMAND_STATES = {
    "Kein Befehl (Nop)":       "Nop",
    "Bewegen (Move)":          "Move",
    "Stopp":                   "Stop",
    "Leerlauf (Idle)":         "Idle",
    "Aktiv (Unidle)":          "Unidle",
    "Angreifen (Attack)":      "Attack",
    "Bewachen (Guard)":        "Guard",
    "Patrouillieren (Patrol)": "Patrol",
    "Reparieren (RepairObj)":  "RepairObj",
    "Umprogrammieren (Reprogram)": "Reprogram",
    "Demontieren (Dismantle)": "Dismantle",
    "Bauen (Build)":           "Build",
    "Im Bau (Develop)":        "Develop",
    "Abriss (UnDevelop)":      "UnDevelop",
    "Docken (Dock)":           "Dock",
    "Übergeben (Transfer)":    "Transfer",
    "Erforschen (Research)":   "Research",
    "Selbstzerstörung":        "SelfDestruct",
}
