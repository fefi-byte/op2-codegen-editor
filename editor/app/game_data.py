from __future__ import annotations

# Gebaeude (Anzeige, map_id, Footprint aus building.txt)
# Buildings (display name, map_id, footprint from building.txt)
STRUCTURES = [
    ("Command Center", "mapCommandCenter", (3, 2)),
    ("Tokamak", "mapTokamak", (2, 2)),
    ("Common Ore Smelter", "mapCommonOreSmelter", (4, 3)),
    ("Rare Ore Smelter", "mapRareOreSmelter", (4, 3)),
    ("Structure Factory", "mapStructureFactory", (4, 3)),
    ("Vehicle Factory", "mapVehicleFactory", (4, 3)),
    ("Arachnid Factory", "mapArachnidFactory", (4, 3)),
    ("Agridome", "mapAgridome", (3, 2)),
    ("Nursery", "mapNursery", (2, 2)),
    ("University", "mapUniversity", (2, 2)),
    ("Residence", "mapResidence", (2, 2)),
    ("Common Ore Mine", "mapCommonOreMine", (2, 1)),
    ("Rare Ore Mine", "mapRareOreMine", (2, 1)),
    ("Magma Well", "mapMagmaWell", (2, 1)),
    ("Spaceport", "mapSpaceport", (5, 4)),
    ("Guard Post", "mapGuardPost", (1, 1)),
]
VEHICLES = [
    ("Scout", "mapScout", (1, 1)),
    ("Cargo Truck", "mapCargoTruck", (1, 1)),
    ("ConVec", "mapConVec", (1, 1)),
    ("Robo-Miner", "mapRoboMiner", (1, 1)),
    ("Robo-Dozer", "mapRoboDozer", (1, 1)),
    ("Earthworker", "mapEarthworker", (1, 1)),
    ("Repair Vehicle", "mapRepairVehicle", (1, 1)),
    ("Lynx", "mapLynx", (1, 1)),
    ("Panther", "mapPanther", (1, 1)),
    ("Tiger", "mapTiger", (1, 1)),
]
# Mauern/Rohre (auch vom Trigger-Dialog genutzt)
# Walls/tubes (also used by the trigger dialog)
WALL_ITEMS = [
    ("Rohr (Tube)", "mapTube", (1, 1)),
    ("Mauer (Wall)", "mapWall", (1, 1)),
    ("Lava-Mauer", "mapLavaWall", (1, 1)),
    ("Microbe-Mauer", "mapMicrobeWall", (1, 1)),
]
# Kategorie -> (kind, items)
# Category -> (kind, items)
CATALOG = {
    "Gebäude": ("structure", STRUCTURES),
    "Fahrzeuge": ("vehicle", VEHICLES),
    # Beacons, Magma Vents, Geysire, Mauern & Rohre in einer Kategorie.
    # Beacons, magma vents, geysers, walls & tubes in one category.
    # Eintraege mit 4. Element ueberschreiben den Standard-Kind der Kategorie.
    # Entries with a 4th element override the category's default kind.
    "Beacons & Mauern": ("beacon", [
        ("Mining Beacon", "mapMiningBeacon", (1, 1)),
        ("Magma Vent", "mapMagmaVent", (1, 1)),
        ("Fumarole / Geysir", "mapFumarole", (1, 1)),
    ] + [(d, m, fp, "wall") for d, m, fp in WALL_ITEMS]),
}
# Einheiten/Gebaeude, die eine Waffe tragen koennen (Waffenauswahl beim Platzieren)
# Units/buildings that can carry a weapon (weapon choice when placing)
WEAPON_UNITS = {"mapLynx", "mapPanther", "mapTiger", "mapGuardPost"}
# Einheiten/Gebaeude fuer "Einheit erzeugen"-Aktionen (Anzeige -> map_id)
# Units/buildings for "create unit" actions (display name -> map_id)
ALL_UNITS = [(d, m) for d, m, _ in STRUCTURES] + [(d, m) for d, m, _ in VEHICLES]
VEHICLE_UNITS = [(d, m) for d, m, _ in VEHICLES]
MILITARY_VEHICLES = [
    (d, m) for d, m, _ in VEHICLES
    if m in ("mapLynx", "mapPanther", "mapTiger")
]
# BuildingGroup darf alle Builder-Einheiten produzieren -- nicht nur ConVec.
BUILDING_GROUP_VEHICLES = [
    ("ConVec",        "mapConVec"),
    ("Robo-Miner",    "mapRoboMiner"),
    ("Robo-Surveyor", "mapRoboSurveyor"),
    ("Robo-Dozer",    "mapRoboDozer"),
    ("Earthworker",   "mapEarthworker"),
    ("Repair Vehicle","mapRepairVehicle"),
    ("Cargo Truck",   "mapCargoTruck"),
    ("Scout",         "mapScout"),
]
# ReinforceGroup ist eine BuildingGroup mit Vehicle Factories.
REINFORCE_GROUP_VEHICLES = BUILDING_GROUP_VEHICLES + MILITARY_VEHICLES
SET_TARG_VEHICLES_BY_GROUP_TYPE = {
    "BuildingGroup": BUILDING_GROUP_VEHICLES,
    "ReinforceGroup": REINFORCE_GROUP_VEHICLES,
    "FightGroup": MILITARY_VEHICLES,
}
STRUCTURE_FOOTPRINTS = {mid: fp for _, mid, fp in STRUCTURES}
WEAPONS = [
    ("Keine", "mapNone"),
    ("Laser", "mapLaser"),
    ("Microwave", "mapMicrowave"),
    ("Rail Gun", "mapRailGun"),
    ("RPG", "mapRPG"),
    ("EMP", "mapEMP"),
    ("ESG", "mapESG"),
    ("Stickyfoam", "mapStickyfoam"),
    ("Thor's Hammer", "mapThorsHammer"),
    ("Energy Cannon", "mapEnergyCannon"),
    ("Starflare", "mapStarflare"),
    ("Supernova", "mapSupernova"),
]

# Truck-Ladung: Anzeige -> interner Cargo-Code
# Truck cargo: display name -> internal cargo code
TRUCK_CARGO = {
    "Common Ore": "truckCommonOre", "Rare Ore": "truckRareOre",
    "Food": "truckFood", "Common Metal": "truckCommonMetal",
    "Rare Metal": "truckRareMetal", "Leer": "truckEmpty",
}
TRUCK_CARGO_BY_ID = {value: label for label, value in TRUCK_CARGO.items()}
ORE_TYPES = {"Zufällig": -1, "Common": 0, "Rare": 1}
YIELDS = {"Zufällig": -1, "Bar3 (viel)": 0, "Bar2 (mittel)": 1, "Bar1 (wenig)": 2}

# Sieg-/Niederlage-Bedingungen: Anzeige -> (kind, [genutzte Felder])
# Victory/defeat conditions: display name -> (kind, [fields used])
CONDITIONS = {
    "Zeit überstehen": ("time", ["marks", "objective"]),
    "Letzter Überlebender": ("lastStanding", []),
    "Raumschiff bauen": ("starship", []),
    "Gebäude-Anzahl": ("buildingCount", ["player", "count", "compare", "objective"]),
    "Fahrzeug-Anzahl": ("vehicleCount", ["player", "count", "compare", "objective"]),
    "Technologie erforscht": ("research", ["player", "tech_id", "objective"]),
    "Ressource erreicht": ("resource", ["player", "resource", "amount", "compare", "objective"]),
    "Gebäude operativ": ("operational", ["player", "building", "count", "compare", "objective"]),
    "Kein Command Center": ("noCC", ["player"]),
}
COMPARE = {"≥": "cmpGreaterEqual", "≤": "cmpLowerEqual", "=": "cmpEqual",
           ">": "cmpGreater", "<": "cmpLower"}
RESOURCES = {"Common Ore": "resCommonOre", "Rare Ore": "resRareOre", "Food": "resFood",
             "Kids": "resKids", "Workers": "resWorkers", "Scientists": "resScientists"}

# Trigger-Bedingungen: Anzeige -> (kind, [Felder])
# Trigger conditions: display name -> (kind, [fields])
TRIGGER_CONDITIONS = {
    "Zeit (Marks)": ("time", ["marks"]),
    "Punkt erreicht": ("point", ["player", "x", "y"]),
    "Rechteck betreten": ("rect", ["player", "x", "y", "width", "height"]),
    "Gebäude-Anzahl": ("buildingCount", ["player", "count", "compare"]),
    "Fahrzeug-Anzahl": ("vehicleCount", ["player", "count", "compare"]),
    "Technologie erforscht": ("research", ["player", "tech_id"]),
    "Ressource erreicht": ("resource", ["player", "resource", "amount", "compare"]),
    "Gebäude operativ": ("operational", ["player", "building", "count", "compare"]),
    "Einheit(en) an Position(en) bereit": ("findUnit", ["unit_checks"]),
}
ACTION_KINDS = {
    "Leere Aktion (Platzhalter)": "noop",
    "Wenn / Dann / Sonst (Bedingungsblock)": "if",
    "Nachricht anzeigen": "message",
    "Einheit erzeugen": "createUnit",
    "Anderen Trigger erstellen (Laufzeit)": "createTrigger",
    "RecordBuilding": "recordBuilding",
    "RecordTube-Linie": "recordTube",
    "RecordWall-Linie": "recordWall",
    "SetTargCount": "setTargCount",
    "Gebäude einer Gruppe zuweisen": "assignToGroup",
    "Variable ändern": "modVar",
}

# IF-Bedingungen pro Aktion: Anzeige -> kind, und welche Felder genutzt werden
# IF conditions per action: display name -> kind, and which fields are used
ACTION_CONDITION_KINDS = {
    "Gebäude an Position vorhanden": ("buildingAtLocation", ["player", "building", "x", "y"]),
    "Gebäude-Schaden an Position": ("unitDamage", ["player", "building", "x", "y", "compare", "value"]),
    "Spieler-Ressource": ("playerResource", ["player", "resource", "compare", "value"]),
    "Gebäude-Anzahl": ("buildingCount", ["player", "building", "compare", "value"]),
    "Technologie erforscht": ("hasTech", ["player", "tech_id"]),
    "Variable prüfen": ("varCheck", ["var_name", "compare", "value"]),
}
