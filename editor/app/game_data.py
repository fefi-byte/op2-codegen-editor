from __future__ import annotations

# Footprints from building.txt (X-size, Y-size).
# map_ids match TitanAPI MapID enum: MapID::Xxx -> "mapXxx".

STRUCTURES = [
    # Power
    ("Command Center",       "mapCommandCenter",      (3, 2)),
    ("Tokamak",              "mapTokamak",             (2, 2)),
    ("MHD Generator",        "mapMHDGenerator",        (2, 2)),
    ("Solar Power Array",    "mapSolarPowerArray",     (3, 2)),
    ("Geothermal Plant",     "mapGeothermalPlant",     (2, 1)),
    # Production
    ("Structure Factory",    "mapStructureFactory",    (4, 3)),
    ("Vehicle Factory",      "mapVehicleFactory",      (4, 3)),
    ("Arachnid Factory",     "mapArachnidFactory",     (2, 2)),
    ("Consumer Factory",     "mapConsumerFactory",     (3, 3)),
    # Mining & Storage
    ("Common Ore Mine",      "mapCommonOreMine",       (2, 1)),
    ("Rare Ore Mine",        "mapRareOreMine",         (2, 1)),
    ("Common Ore Smelter",   "mapCommonOreSmelter",    (4, 3)),
    ("Rare Ore Smelter",     "mapRareOreSmelter",      (4, 3)),
    ("Common Storage",       "mapCommonStorage",       (1, 2)),
    ("Rare Storage",         "mapRareStorage",         (1, 2)),
    ("Magma Well",           "mapMagmaWell",           (2, 1)),
    # Research
    ("Basic Lab",            "mapBasicLab",            (2, 2)),
    ("Standard Lab",         "mapStandardLab",         (3, 2)),
    ("Advanced Lab",         "mapAdvancedLab",         (3, 3)),
    ("Observatory",          "mapObservatory",         (2, 2)),
    # Residential & Population
    ("Residence",            "mapResidence",           (2, 2)),
    ("Reinforced Residence", "mapReinforcedResidence", (3, 2)),
    ("Advanced Residence",   "mapAdvancedResidence",   (3, 3)),
    ("Nursery",              "mapNursery",             (2, 2)),
    ("University",           "mapUniversity",          (2, 2)),
    ("Medical Center",       "mapMedicalCenter",       (2, 2)),
    # Food & Services
    ("Agridome",             "mapAgridome",            (3, 2)),
    ("GORF",                 "mapGORF",                (3, 2)),
    # Community
    ("Recreation Facility",  "mapRecreationFacility",  (2, 2)),
    ("Forum",                "mapForum",               (2, 2)),
    ("Trade Center",         "mapTradeCenter",         (2, 2)),
    ("DIRT",                 "mapDIRT",                (3, 2)),
    # Military & Defense
    ("Guard Post",           "mapGuardPost",           (1, 1)),
    ("Light Tower",          "mapLightTower",          (1, 1)),
    ("Meteor Defense",       "mapMeteorDefense",       (2, 2)),
    ("Garage",               "mapGarage",              (3, 2)),
    ("Robot Command",        "mapRobotCommand",        (2, 2)),
    # Space
    ("Spaceport",            "mapSpaceport",           (5, 4)),
]

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

# Truck cargo: display name -> internal cargo code
TRUCK_CARGO = {
    "Common Ore":   "truckCommonOre",
    "Rare Ore":     "truckRareOre",
    "Food":         "truckFood",
    "Common Metal": "truckCommonMetal",
    "Rare Metal":   "truckRareMetal",
    "Empty":        "truckEmpty",
}
TRUCK_CARGO_BY_ID = {value: label for label, value in TRUCK_CARGO.items()}
ORE_TYPES = {"Random": -1, "Common": 0, "Rare": 1}
YIELDS = {"Random": -1, "Bar3 (high)": 0, "Bar2 (medium)": 1, "Bar1 (low)": 2}

# Victory/defeat conditions: display name -> (kind, [fields used])
CONDITIONS = {
    "Zeit überstehen":    ("time",          ["marks", "objective"]),
    "Letzter Überlebender": ("lastStanding", []),
    "Raumschiff bauen":   ("starship",       []),
    "Gebäude-Anzahl":     ("buildingCount",  ["player", "count", "compare", "objective"]),
    "Fahrzeug-Anzahl":    ("vehicleCount",   ["player", "count", "compare", "objective"]),
    "Technologie erforscht": ("research",    ["player", "tech_id", "objective"]),
    "Ressource erreicht": ("resource",       ["player", "resource", "amount", "compare", "objective"]),
    "Gebäude operativ":   ("operational",    ["player", "building", "count", "compare", "objective"]),
    "Kein Command Center": ("noCC",          ["player"]),
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
}

ACTION_KINDS = {
    "Leere Aktion (Platzhalter)":        "noop",
    "Wenn / Dann / Sonst (Bedingungsblock)": "if",
    "Nachricht anzeigen":                "message",
    "Einheit erzeugen":                  "createUnit",
    "Katastrophe ausloesen":             "createDisaster",
    "Anderen Trigger erstellen (Laufzeit)": "createTrigger",
    "RecordBuilding":                    "recordBuilding",
    "RecordTube-Linie":                  "recordTube",
    "RecordWall-Linie":                  "recordWall",
    "SetTargCount":                      "setTargCount",
    "Gebäude einer Gruppe zuweisen":     "assignToGroup",
    "Variable ändern":                   "modVar",
}

# IF conditions per action: display name -> (kind, [fields])
METEOR_SIZES = {
    "Zufaellig": -1,
    "Klein": 0,
    "Mittel": 1,
    "Gross": 2,
}

DISASTER_TYPES = {
    "Meteor": "meteor",
    "Erdbeben": "earthquake",
    "Sturm": "storm",
    "Vortex": "vortex",
    "Vulkan (Eruption)": "eruption",
    "Blight setzen": "blight",
    "Blight entfernen": "unblight",
}

# IF conditions per action: display name -> (kind, [fields])
ACTION_CONDITION_KINDS = {
    "Gebäude an Position vorhanden": ("buildingAtLocation", ["player", "building", "x", "y"]),
    "Gebäude-Schaden an Position":   ("unitDamage",         ["player", "building", "x", "y", "compare", "value"]),
    "Spieler-Ressource":             ("playerResource",     ["player", "resource", "compare", "value"]),
    "Gebäude-Anzahl":                ("buildingCount",      ["player", "building", "compare", "value"]),
    "Technologie erforscht":         ("hasTech",            ["player", "tech_id"]),
    "Variable prüfen":               ("varCheck",           ["var_name", "compare", "value"]),
}
