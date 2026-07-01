from __future__ import annotations
from ..common import *


class MissionSetupDialog(QDialog):
    """Globale Mission-Einstellungen: Name, Typ, Techtree, Schwierigkeit, Variablen.

    Global mission settings: name, type, tech tree, difficulty, variables.
    """
    def __init__(self, parent, mission_name: str, mission_type: MissionType,
                 tech_tree: str, diff_setup: DifficultySetup,
                 variables: list[VariableDef],
                 map_names: list[str] | None = None, current_map: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("setup.title"))
        self.resize(560, 580)

        # --- Basisdaten ---
        self.map_combo = QComboBox()
        for n in (map_names or []):
            self.map_combo.addItem(n)
        idx = self.map_combo.findText(current_map)
        if idx >= 0:
            self.map_combo.setCurrentIndex(idx)

        self.name_edit = QLineEdit(mission_name)
        self.type_combo = QComboBox()
        for mt, label in [
            (MissionType.Colony,               "Colony (-1)"),
            (MissionType.AutoDemo,             "AutoDemo (-2)"),
            (MissionType.Tutorial,             "Tutorial (-3)"),
            (MissionType.MultiLandRush,        "Multi: Land Rush (-4)"),
            (MissionType.MultiSpaceRace,       "Multi: Space Race (-5)"),
            (MissionType.MultiResourceRace,    "Multi: Resource Race (-6)"),
            (MissionType.MultiMidas,           "Multi: Midas (-7)"),
            (MissionType.MultiLastOneStanding, "Multi: Last One Standing (-8)"),
        ]:
            self.type_combo.addItem(label, mt)
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == mission_type:
                self.type_combo.setCurrentIndex(i)
                break
        self.tech_edit = QLineEdit(tech_tree)

        form = QFormLayout()
        form.addRow(tr("setup.lbl_map"), self.map_combo)
        form.addRow(tr("setup.lbl_mission_name"), self.name_edit)
        form.addRow(tr("setup.lbl_mission_type"), self.type_combo)
        form.addRow(tr("setup.lbl_tech_tree"), self.tech_edit)

        # --- Schwierigkeit ---
        self.hard_spin = QSpinBox(); self.hard_spin.setRange(0, 1000); self.hard_spin.setValue(diff_setup.hard)
        self.norm_spin = QSpinBox(); self.norm_spin.setRange(0, 1000); self.norm_spin.setValue(diff_setup.normal)
        self.easy_spin = QSpinBox(); self.easy_spin.setRange(0, 1000); self.easy_spin.setValue(diff_setup.easy)

        diff_group = QWidget()
        diff_form = QFormLayout(diff_group)
        diff_form.setContentsMargins(0, 0, 0, 0)
        diff_form.addRow(tr("setup.lbl_diff_hard"), self.hard_spin)
        diff_form.addRow(tr("setup.lbl_diff_normal"), self.norm_spin)
        diff_form.addRow(tr("setup.lbl_diff_easy"), self.easy_spin)

        hint = QLabel(tr("setup.lbl_diff_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 9pt;")

        # --- Variablen-Tabelle ---
        self.var_table = QTableWidget(0, 3)
        self.var_table.setHorizontalHeaderLabels([
            tr("setup.var_col_name"),
            tr("setup.var_col_type"),
            tr("setup.var_col_init"),
        ])
        self.var_table.horizontalHeader().setStretchLastSection(True)
        self.var_table.setSelectionBehavior(QTableWidget.SelectRows)
        for v in variables:
            self._add_var_row(v.name, v.var_type, v.initial_value)

        btn_add_var = QPushButton(tr("setup.btn_add_var"))
        btn_add_var.clicked.connect(self._add_variable)
        btn_rm_var = QPushButton(tr("setup.btn_remove_var"))
        btn_rm_var.clicked.connect(self._remove_variable)
        var_btns = QHBoxLayout()
        var_btns.addWidget(btn_add_var); var_btns.addWidget(btn_rm_var); var_btns.addStretch(1)

        # --- Layout zusammensetzen ---
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addSpacing(8)
        root.addWidget(QLabel(f"<b>{tr('setup.section_diff')}</b>"))
        root.addWidget(diff_group)
        root.addWidget(hint)
        root.addSpacing(8)
        root.addWidget(QLabel(f"<b>{tr('setup.section_vars')}</b>"))
        root.addWidget(self.var_table, 1)
        root.addLayout(var_btns)
        root.addWidget(btns)

    # --- Variablen-Tabelle ---

    def _add_var_row(self, name: str = "", var_type: str = "int", initial_value: int = 0):
        row = self.var_table.rowCount()
        self.var_table.insertRow(row)
        count = row + 1
        self.var_table.setItem(row, 0, QTableWidgetItem(name or f"var{count}"))
        cb = QComboBox()
        cb.addItem("int", "int")
        cb.addItem("bool", "bool")
        cb.setCurrentIndex(0 if var_type != "bool" else 1)
        self.var_table.setCellWidget(row, 1, cb)
        self.var_table.setItem(row, 2, QTableWidgetItem(str(initial_value)))

    def _add_variable(self):
        self._add_var_row()

    def _remove_variable(self):
        rows = {idx.row() for idx in self.var_table.selectedIndexes()}
        for row in sorted(rows, reverse=True):
            self.var_table.removeRow(row)

    # --- Ergebnis auslesen ---

    @property
    def map_name(self) -> str:
        return self.map_combo.currentText()

    @property
    def mission_name(self) -> str:
        return self.name_edit.text().strip() or "Editor Mission"

    @property
    def mission_type(self) -> MissionType:
        return self.type_combo.currentData() or MissionType.Colony

    @property
    def tech_tree(self) -> str:
        return self.tech_edit.text().strip() or "MULTITEK.TXT"

    @property
    def diff_setup(self) -> DifficultySetup:
        return DifficultySetup(
            hard=self.hard_spin.value(),
            normal=self.norm_spin.value(),
            easy=self.easy_spin.value(),
        )

    @property
    def variables(self) -> list[VariableDef]:
        result = []
        for row in range(self.var_table.rowCount()):
            name_item = self.var_table.item(row, 0)
            type_cb = self.var_table.cellWidget(row, 1)
            val_item = self.var_table.item(row, 2)
            name = (name_item.text().strip() if name_item else "") or f"var{row + 1}"
            var_type = (type_cb.currentData() if type_cb else "int") or "int"
            try:
                init_val = int(val_item.text().strip() if val_item else "0")
            except (ValueError, AttributeError):
                init_val = 0
            result.append(VariableDef(name=name, var_type=var_type, initial_value=init_val))
        return result
