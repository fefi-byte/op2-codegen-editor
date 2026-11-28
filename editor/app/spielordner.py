"""Outpost-2-Ordner beim Start pruefen und bei Bedarf waehlen lassen.

Gueltig ist ein Outpost-2-1.4.1-Ordner mit OPU/OPULauncher.exe. Fehlt er unter
``game_path`` aus der config.ini, waehlt der Nutzer ihn per Ordnerdialog; der
Pfad wird dann in die config.ini geschrieben.

Checks the Outpost 2 folder at start-up and lets the user choose it if needed.
A valid folder is an Outpost 2 1.4.1 folder with OPU/OPULauncher.exe. If it is
missing under ``game_path`` from config.ini, the user picks it in a folder
dialog and the path is written to config.ini.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (_ROOT / "codegen", _ROOT / "mapview"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import appconfig
from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import i18n
from .i18n import tr


def ist_op2_ordner(ordner: Path) -> bool:
    """True, wenn ``ordner`` OPU/OPULauncher.exe enthaelt (Outpost 2 1.4.1)."""
    return (ordner / "OPU" / "OPULauncher.exe").is_file()


def _normalisieren(ordner: Path) -> Path:
    # Wer den OPU-Ordner selbst waehlt, meint dessen Elternordner.
    # Choosing the OPU folder itself means its parent.
    if ordner.name.lower() == "opu" and (ordner / "OPULauncher.exe").is_file():
        return ordner.parent
    return ordner


def sicherstellen() -> bool:
    """Gueltigen Spielordner sicherstellen. False = Nutzer hat abgebrochen.

    Make sure a valid game folder is configured. False = the user cancelled.
    """
    appconfig.ensure_default_file()
    i18n.init(appconfig.language())
    aktuell = appconfig.game_path()
    if ist_op2_ordner(aktuell):
        return True

    text = tr("op2_folder.missing_text", path=aktuell)
    start = str(aktuell if aktuell.is_dir() else Path.home())
    while True:
        antwort = QMessageBox.question(
            None, tr("op2_folder.title"), text,
            QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Ok)
        if antwort != QMessageBox.Ok:
            return False
        gewaehlt = QFileDialog.getExistingDirectory(
            None, tr("op2_folder.dialog_title"), start)
        if not gewaehlt:
            continue
        ordner = _normalisieren(Path(gewaehlt))
        if ist_op2_ordner(ordner):
            appconfig.set_game_path(str(ordner))
            return True
        start = gewaehlt
        text = tr("op2_folder.invalid_text", path=ordner)
