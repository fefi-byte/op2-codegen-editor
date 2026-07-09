from __future__ import annotations

import json
import shutil
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

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
    FightGroupSpec, FindUnitCheck, MiningGroupSpec, Mission, MissionType, PlayerSpec,
    ReinforceGroupSpec, ReinforceTargetSpec, StartMessage, TriggerAction, TriggerDef,
    UnitSpec, VariableDef, WallTubeSpec, action_from_dict,
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
i18n.init(appconfig.language())
tr = i18n.tr


def fill_combo(combo, mapping, section):
    """Befuellt eine QComboBox aus einem {label: value|tuple}-Dict sprachneutral.

    Fills a QComboBox from a {label: value|tuple} dict in a language-neutral way.
    """
    for label, val in mapping.items():
        internal = val[0] if isinstance(val, tuple) else val
        combo.addItem(tr(f"{section}.{internal}"), label)


PLAYER_COLORS = [QColor(80, 160, 255), QColor(255, 90, 90), QColor(90, 220, 90),
                 QColor(240, 220, 70), QColor(220, 120, 240), QColor(120, 230, 230)]
BEACON_COLOR = QColor(255, 200, 40)
WALL_COLOR = QColor(180, 180, 180)

from .game_data import *   # noqa: F401,F403
from .summary import *     # noqa: F401,F403
