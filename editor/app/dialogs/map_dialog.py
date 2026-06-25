from __future__ import annotations
from ..common import *


class MapDialog(QDialog):
    """Missionsname und zugehoerige .map-Datei auswaehlen.

    EN: Choose the mission name and the associated .map file.
    """
    def __init__(self, parent, names, current_map, mission_name):
        super().__init__(parent)
        self.setWindowTitle(tr("map_dialog.title"))
        self.name_edit = QLineEdit(mission_name)
        self.combo = QComboBox()
        self.combo.addItems(sorted(n for n in names if n.lower().endswith(".map")))
        if self.combo.findText(current_map) >= 0:
            self.combo.setCurrentText(current_map)
        form = QFormLayout()
        form.addRow(tr("map_dialog.mission_name"), self.name_edit)
        form.addRow(tr("map_dialog.map"), self.combo)
        hint = QLabel(tr("map_dialog.hint"))
        hint.setStyleSheet("color: gray;")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(btns)


