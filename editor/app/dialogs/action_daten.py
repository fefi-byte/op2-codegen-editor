"""Konstanten und kleine Helfer des Aktions-Editors (Befehle, Produkte).

Aus `action_editor.py` herausgeloest; `action_editor` reicht die oeffentlichen
Klassen weiter.

Constants and small helpers of the action editor.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox

from ..common import *
from ..summary import action_kind_label, action_params_summary
from ..style import (ACTION_CATEGORY_COLOR, ACTION_SECTION_COLOR, CONDITION_SECTION_COLOR,
                     IF_LOOP_COLOR, SURFACE1, apply_role, tint_button_stylesheet, tint_stylesheet)


class _NoWheelFilter(QObject):
    """Blockiert Mausrad-Events auf nicht fokussierten Eingabefeldern.

    Blocks wheel events on unfocused input widgets so scrolling the panel
    does not accidentally change values."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            return True
        return super().eventFilter(obj, ev)


# Aktionstypen, die per Dialog (mit Parametern) angelegt werden:
# Action kinds that are created via a dialog (with parameters):
_DIALOG_KINDS = {label: k for label, k in ACTION_KINDS.items()
                 if k not in ("if", "noop", "custom", "defendArea")}


# Gruppen-Befehle je Gruppentyp (MiningGroups sind jetzt vordefinierte
# Gruppen wie die anderen, bekommen aber bewusst keine Befehle hier -- kein
# Angriff-/Bewachen-/Patrouille-Verhalten zum Steuern).
# Group commands per group type (MiningGroups are now predefined groups like
# the others, but deliberately have no commands here -- no attack/guard/
# patrol behavior to control).
# Group commands: list of (internal_value, i18n_key). Display label comes
# from tr("action_editor.<key>") at usage time (see _fill_group_commands).
_GROUP_COMMANDS = {
    "FightGroup": [
        ("attackArea", "gc_attack_area"),
        ("attackEnemy", "gc_attack_enemy"),
        ("guardArea", "gc_guard_area"),
        ("patrol", "gc_patrol"),
        ("exitMap", "gc_exit_map"),
        ("combineFireOn", "gc_combine_fire_on"),
        ("combineFireOff", "gc_combine_fire_off"),
        ("setIdleRect", "gc_set_idle_rect"),
        ("addUnit", "gc_add_unit"),
        ("removeUnit", "gc_remove_unit"),
    ],
    "BuildingGroup": [
        ("setBuildRect", "gc_set_build_rect"),
        ("reinforceGroup", "gc_reinforce_group"),
        ("unReinforceGroup", "gc_un_reinforce_group"),
        ("addUnit", "gc_add_unit"),
        ("removeUnit", "gc_remove_unit"),
    ],
}


_GROUP_COMMANDS_COMMON = [
    ("lightsOn", "gc_lights_on"),
    ("lightsOff", "gc_lights_off"),
    ("clearTargCount", "gc_clear_targ_count"),
]


# Befehle, die eine Ziel-Einheit brauchen (benannte Einheit oder Schleifen-
# Einheit) statt eines Rechteck-Bereichs.
# Commands that need a target unit (named unit or loop unit) instead of a rect.
_GROUP_COMMANDS_UNIT_TARGET = {"addUnit", "removeUnit"}


# Unit commands per unit kind: list of (internal_value, i18n_key).
_UNIT_COMMANDS_VEHICLE = [
    ("move", "uc_move"),
    ("patrol", "uc_patrol"),
    ("repair", "uc_repair"),
    ("stop", "uc_stop"),
    ("lightsOn", "uc_lights_on"),
    ("lightsOff", "uc_lights_off"),
    ("selfDestruct", "uc_self_destruct"),
    ("remove", "uc_remove"),
    ("transfer", "uc_transfer"),
]


_UNIT_COMMANDS_BUILDING = [
    ("idle", "uc_idle"),
    ("unidle", "uc_unidle"),
    ("selfDestruct", "uc_self_destruct"),
    ("remove", "uc_remove"),
    ("transfer", "uc_transfer"),
]


_VEHICLE_IDS = {m for _, m, _ in VEHICLES}


# Gebaeude mit Produktionsbefehl (DoProduce); der Spaceport kann zusaetzlich
# Raketen starten (DoLaunch).
# Buildings with a production command (DoProduce); the Spaceport can also
# launch rockets (DoLaunch).
_FACTORY_IDS = {"mapVehicleFactory", "mapStructureFactory",
                "mapArachnidFactory", "mapSpaceport"}


def produce_items_for(map_id: str) -> list[tuple[str, str]]:
    """Baubare Produkte je Fabriktyp / producible items per factory type."""
    if map_id == "mapSpaceport":
        return list(SPACEPORT_PRODUCTS)
    if map_id == "mapArachnidFactory":
        return [(d, m) for d, m in VEHICLE_UNITS if m in ("mapSpider", "mapScorpion")]
    if map_id == "mapVehicleFactory":
        return [(d, m) for d, m in VEHICLE_UNITS if m not in ("mapSpider", "mapScorpion")]
    if map_id == "mapStructureFactory":
        # Structure Kits -- gleiche map_ids wie die Gebaeude selbst.
        # Structure kits -- same map_ids as the buildings themselves.
        return [(d, m) for d, m, _ in STRUCTURES]
    return []


def unit_commands_for(map_id: str) -> list[tuple[str, str]]:
    """Befehlsliste passend zur Einheitenart / command list matching the unit kind.

    Returns a list of (internal_value, i18n_key) tuples.
    """
    if map_id == "<loop>":
        # Typ der Schleifen-Einheit ist erst zur Laufzeit bekannt -> alles anbieten
        # The loop unit's type is only known at runtime -> offer everything
        cmds = list(_UNIT_COMMANDS_VEHICLE)
        cmds.insert(2, ("attackGround", "uc_attack_ground"))
        cmds += [c for c in _UNIT_COMMANDS_BUILDING if c not in cmds]
        return cmds
    if map_id in _VEHICLE_IDS:
        cmds = list(_UNIT_COMMANDS_VEHICLE)
        if map_id in WEAPON_UNITS:
            cmds.insert(2, ("attackGround", "uc_attack_ground"))
        return cmds
    if map_id in _FACTORY_IDS:
        cmds = [("produce", "uc_produce")]
        if map_id == "mapSpaceport":
            cmds.append(("launch", "uc_launch"))
        return cmds + list(_UNIT_COMMANDS_BUILDING)
    return list(_UNIT_COMMANDS_BUILDING)


# ---------------------------------------------------------------------------
# Schleifen-Ebenen: dieselben Namen wie der Codegenerator (codegen_actions.
# _loop_var): aeusserste "Fuer jede Einheit"-Schleife "unit", darin "unit2" ...
# Loop levels: the same names the code generator uses.
# ---------------------------------------------------------------------------

def schleifen_var(tiefe: int) -> str:
    return "unit" if tiefe <= 1 else f"unit{tiefe}"


def schleifen_ref_name(ref: str, tiefe: int) -> str | None:
    """"<loop>"/"<loop:outer>" -> Variablenname an dieser Stelle, None ausserhalb."""
    if tiefe < 1:
        return None
    if ref == "<loop:outer>" and tiefe >= 2:
        return schleifen_var(tiefe - 1)
    return schleifen_var(tiefe)


def schleifen_ref_text(ref: str, tiefe) -> str:
    """Beschriftung fuer die Auswahl "aktuelle/aeussere Schleife" mit dem
    konkreten Namen, z.B. "Schleifen-Einheit unit2 (aktuelle Schleife)"."""
    schl = "action_editor.loop_ref_current" if ref == "<loop>" else "action_editor.loop_ref_outer"
    if tiefe is None:
        return tr(schl)
    name = schleifen_ref_name(ref, tiefe)
    if name is None:
        return tr(schl) + "  ⚠ " + tr("action_editor.loop_none_here")
    if ref == "<loop:outer>" and tiefe < 2:
        return tr(schl) + f" → {name}  (" + tr("action_editor.loop_outer_is_current") + ")"
    return tr(schl) + f" → {name}"


def zaehler_var(ebene: int) -> str:
    """Zaehler der N-mal-Schleife je Ebene: i, i2, i3 (wie im Codegenerator)."""
    return "i" if ebene <= 1 else f"i{ebene}"
