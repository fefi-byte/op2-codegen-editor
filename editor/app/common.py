from __future__ import annotations

import json
import shutil
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np

# editor/app
HERE = Path(__file__).resolve().parent      # editor/app
# editor
EDITOR_DIR = HERE.parent                      # editor
# op2-cpp-poc
ROOT = EDITOR_DIR.parent                       # op2-cpp-poc
for _p in (ROOT / "codegen", ROOT / "mapview", EDITOR_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Fenster-/App-Icon (liegt im Paket unter resources/).
# Window/app icon (lives in the package under resources/).
ICON_PATH = HERE / "resources" / "Structure.ico"

from PySide6.QtCore import Qt, QLineF, QRectF, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
    QFileDialog, QFormLayout, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressDialog, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem, QMenu, QFrame, QScrollArea,
)
from PySide6.QtGui import QFont, QPainterPath, QPolygonF, QCursor
from PySide6.QtCore import QPointF

from op2map import Op2Map
from op2res import FolderResources, content_root
from render import render_array
from tileset import TILE
from vol import VolFile

import appconfig
from . import i18n
import build as build_mod
from codegen import generate_levelmain
from mission_model import (
    ActionCondition, BeaconSpec, BuildingGroupSpec, Colony, Condition, DifficultySetup,
    FindUnitCheck, Mission, MissionType, PlayerSpec, ReinforceGroupSpec, ReinforceTargetSpec,
    StartMessage, TriggerAction, TriggerDef, UnitSpec, VariableDef, WallTubeSpec, action_from_dict,
)
from techs import load_techs

# Pfade kommen aus config.ini (neben der EXE bzw. im Projekt-Root).
# Paths come from config.ini (next to the EXE or in the project root).
appconfig.ensure_default_file()
OP2_DIR = appconfig.game_path()
# OPU 1.4.1: Karten/Tilesets/Techs liegen entpackt unter <game>/OPU (kein .vol).
# OPU 1.4.1: maps/tilesets/techs are unpacked under <game>/OPU (no .vol).
CONTENT_ROOT = content_root(OP2_DIR)
TECHS_DIR = CONTENT_ROOT / "base" / "techs"
# native 32px -> scharf
SCENE_TILE = TILE  # native 32px -> scharf

# Standard-Ausgabeort der Mission-DLL. Colony-Missionen brauchen den Praefix "c".
# Default output location of the mission DLL. Colony missions need the prefix "c".
DEFAULT_OUTPUT_DIR = appconfig.output_dir()
DEFAULT_DLL_NAME = appconfig.dll_name()

# --- Mehrsprachigkeit ---
# --- Internationalisation ---
# i18n-Bruecke: tr("section.key", **fmt) schlaegt den Text in der aktiven
# Sprach-INI nach (Fallback de -> Schluessel). fill_combo zeigt uebersetzten
# Text an, speichert aber das urspruengliche (deutsche) Dict-Label als itemData,
# damit bestehende `DICT[combo.currentData()]`-Lookups weiter funktionieren.
# i18n bridge: tr("section.key", **fmt) looks the text up in the active-language
# INI (fallback de -> the key). fill_combo shows translated text but stores the
# original (German) dict label as itemData, so existing
# `DICT[combo.currentData()]` lookups keep working.
i18n.init(appconfig.language())
tr = i18n.tr


def fill_combo(combo, mapping, section):
    """Befuellt eine QComboBox aus einem {label: value|tuple}-Dict sprachneutral.

    Anzeige = uebersetzt via tr(f"{section}.{interner_wert}"); itemData = das
    urspruengliche (deutsche) Label, damit bestehende `DICT[combo.currentData()]`-
    Lookups unveraendert funktionieren. Zum Setzen: combo.setCurrentIndex(
    combo.findData(label)).

    Fills a QComboBox from a {label: value|tuple} dict in a language-neutral way.

    Display = translated via tr(f"{section}.{internal_value}"); itemData = the
    original (German) label, so existing `DICT[combo.currentData()]` lookups keep
    working unchanged. To select: combo.setCurrentIndex(combo.findData(label)).
    """
    for label, val in mapping.items():
        internal = val[0] if isinstance(val, tuple) else val
        combo.addItem(tr(f"{section}.{internal}"), label)

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
# Damit kann setTargCount auf einer BuildingGroup einen RoboMiner anfordern,
# der dann die Mine baut (typischer OP2-Flow ueber Vehicle Factory + ConVec).
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
# ReinforceGroup ist eine BuildingGroup mit Vehicle Factories; sie reicht
# alle Builder + Combat-Units fuer Reinforcement weiter.
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

PLAYER_COLORS = [QColor(80, 160, 255), QColor(255, 90, 90), QColor(90, 220, 90),
                 QColor(240, 220, 70), QColor(220, 120, 240), QColor(120, 230, 230)]
BEACON_COLOR = QColor(255, 200, 40)
WALL_COLOR = QColor(180, 180, 180)

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
    # findUnit: pollt mehrere Tiles auf einsatzbereite (enabled) Einheiten;
    # alle Eintraege werden UND-verknuepft. Die Eintragsliste hat eine eigene
    # UI-Sektion im Trigger-Dialog ("unit_checks").
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


def _cmp_sym(compare):
    return {v: k for k, v in COMPARE.items()}.get(compare, compare)


def action_condition_summary(c) -> str:
    """Bildet eine IF-Aktionsbedingung auf ein lesbares Listenlabel ab.

    Maps an IF-action condition object to a human-readable list label.
    """
    cmp = _cmp_sym(c.compare)
    neg = (tr("sum.not") + " ") if c.negate else ""
    if c.kind == "buildingAtLocation":
        return tr("sum.cond_building_at", neg=neg, b=c.building_type, x=c.x, y=c.y, p=c.player)
    if c.kind == "unitDamage":
        return tr("sum.cond_damage", neg=neg, b=c.building_type, x=c.x, y=c.y, cmp=cmp, v=c.value, p=c.player)
    if c.kind == "playerResource":
        return tr("sum.cond_resource", neg=neg, res=c.resource, cmp=cmp, v=c.value, p=c.player)
    if c.kind == "buildingCount":
        return tr("sum.cond_count", neg=neg, b=c.building_type, cmp=cmp, v=c.value, p=c.player)
    if c.kind == "hasTech":
        return tr("sum.cond_tech", neg=neg, tech=c.tech_id, p=c.player)
    if c.kind == "varCheck":
        var = getattr(c, 'var_name', '') or '?'
        return f"{neg}{var} {cmp} {c.value}"
    return c.kind


def trigger_summary(t) -> str:
    """Bildet ein Trigger-Objekt auf ein lesbares Listenlabel ab.

    Maps a trigger object to a human-readable list label.
    """
    cond = tr(f"trigger_conditions.{t.condition}")
    start = tr("sum.trig_start") if t.enabled_at_start else tr("sum.trig_runtime")
    return tr("sum.trigger", name=t.name, start=start, cond=cond, n=len(t.actions))


def action_summary(a) -> str:
    """Bildet ein Aktions-Objekt auf ein lesbares Listenlabel ab (inkl. IF-Praefix).

    Maps an action object to a human-readable list label (including IF prefix).
    """
    prefix = (tr("sum.if_prefix", n=len(a.conditions)) + " ") if getattr(a, "conditions", None) else ""
    return prefix + _action_summary_core(a)


def _action_summary_core(a) -> str:
    if a.kind == "noop":
        return tr("action_kinds.noop")
    if a.kind == "if":
        logic = tr("sum.or") if getattr(a, "condition_logic", "and") == "or" else tr("sum.and")
        return tr("sum.act_if", n=len(getattr(a, "conditions", [])), logic=logic,
                  then=len(getattr(a, "then_actions", [])), els=len(getattr(a, "else_actions", [])))
    if a.kind == "message":
        return tr("sum.act_message", text=a.text)
    if a.kind == "createUnit":
        weapon = "" if a.weapon_type == "mapNone" else f" / {a.weapon_type}"
        return tr("sum.act_createunit", unit=a.unit_type, weapon=weapon, x=a.x, y=a.y, p=a.player)
    if a.kind == "createTrigger":
        return tr("sum.act_createtrigger", target=a.target)
    if a.kind == "recordBuilding":
        return tr("sum.act_recordbuilding", g=a.group_name, b=a.building_type, x=a.x, y=a.y)
    if a.kind == "recordTube":
        return f"{a.group_name}.RecordTubeLine(({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "recordWall":
        return f"{a.group_name}.RecordWallLine({a.wall_type}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "setTargCount":
        weapon = "" if a.weapon_type == "mapNone" else f", {a.weapon_type}"
        source = f" via {a.source_group_name} P{a.reinforce_priority}" if a.source_group_name else ""
        return f"{a.group_name}.SetTargCount({a.unit_type}{weapon}) = {a.target_count}{source}"
    if a.kind == "assignToGroup":
        return tr("sum.act_assign", b=a.building_type, x=a.x, y=a.y, g=a.group_name, p=a.player)
    if a.kind == "modVar":
        var = getattr(a, 'var_name', '') or '?'
        mode = getattr(a, 'mod_mode', 'inc') or 'inc'
        if mode == 'inc':
            return f"{var} +1"
        if mode == 'dec':
            return f"{var} −1"
        expr = getattr(a, 'var_expr', '') or '…'
        return f"{var} = {expr}"
    return a.kind


def condition_summary(c: Condition) -> str:
    """Kurzbeschreibung einer Bedingung fuer die Liste.

    Short description of a victory/defeat condition for the list (maps the model
    object to a human-readable list label).
    """
    cmp = _cmp_sym(c.compare)
    k = c.kind
    if k == "time":
        return tr("sum.win_time", marks=c.marks)
    if k == "lastStanding":
        return tr("conditions.lastStanding")
    if k == "starship":
        return tr("conditions.starship")
    if k == "noCC":
        return tr("sum.win_nocc", p=c.player)
    if k == "buildingCount":
        return tr("sum.win_buildingcount", cmp=cmp, n=c.count, p=c.player)
    if k == "vehicleCount":
        return tr("sum.win_vehiclecount", cmp=cmp, n=c.count, p=c.player)
    if k == "research":
        return tr("sum.win_research", tech=c.tech_id, p=c.player)
    if k == "resource":
        return tr("sum.win_resource", res=c.resource, cmp=cmp, amt=c.amount, p=c.player)
    if k == "operational":
        return tr("sum.win_operational", b=c.building, cmp=cmp, n=c.count, p=c.player)
    return k


def building_group_summary(g: BuildingGroupSpec) -> str:
    """Bildet eine Gebaeude-Gruppe auf ein lesbares Listenlabel ab.

    Maps a building group to a human-readable list label.
    """
    return tr("sum.group_building", name=g.name, p=g.player, rx=g.rect_x, ry=g.rect_y,
              rw=g.rect_width, rh=g.rect_height, n=len(g.unit_ids))


def reinforce_group_summary(g: ReinforceGroupSpec) -> str:
    """Bildet eine Reinforce-Gruppe auf ein lesbares Listenlabel ab.

    Maps a reinforce group to a human-readable list label.
    """
    return tr("sum.group_reinforce", name=g.name, p=g.player, f=len(g.unit_ids), t=len(g.targets))


class ExprEdit(QWidget):
    """Zahlenfeld das Integer oder C++-Ausdruck akzeptiert.

    Zeigt eine Vorschau 'Hard: X · Normal: Y · Easy: Z' wenn 'diff' im
    Text vorkommt und diff_values gesetzt ist.
    """
    valueChanged = Signal(object)

    def __init__(self, parent=None, diff_values=None):
        super().__init__(parent)
        self._diff = diff_values  # (hard, normal, easy) oder None

        self._edit = QLineEdit()
        self._preview = QLabel()
        self._preview.setStyleSheet("color: gray; font-size: 9pt;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        lay.addWidget(self._edit)
        lay.addWidget(self._preview)
        self._preview.setVisible(False)

        self._edit.textChanged.connect(self._on_changed)

    def set_diff_values(self, hard, normal, easy):
        self._diff = (hard, normal, easy)
        self._on_changed(self._edit.text())

    def _on_changed(self, text=""):
        text = self._edit.text().strip()
        self._update_preview(text)
        self.valueChanged.emit(self.value())

    def _update_preview(self, text):
        if not self._diff or 'diff' not in text:
            self._preview.setVisible(False)
            return
        import math
        safe_locals = {"ceil": math.ceil, "floor": math.floor,
                       "round": round, "abs": abs, "max": max, "min": min}
        labels = ('Hard', 'Normal', 'Easy')
        parts = []
        for label, dv in zip(labels, self._diff):
            try:
                val = eval(text.replace('diff', str(dv)), {"__builtins__": {}}, safe_locals)
                parts.append(f"{label}: {int(val)}")
            except Exception:
                parts.append(f"{label}: ?")
        self._preview.setText("  ·  ".join(parts))
        self._preview.setVisible(True)

    def setValue(self, v):
        if v is None:
            self._edit.setText("")
        else:
            self._edit.setText(str(v))

    def value(self):
        """Gibt int zurueck wenn reiner Integer, sonst str."""
        text = self._edit.text().strip()
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            return text

    def text(self):
        return self._edit.text().strip()

    def setPlaceholderText(self, t):
        self._edit.setPlaceholderText(t)

