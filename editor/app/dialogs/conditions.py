from __future__ import annotations
from ..common import *


class ConditionsDialog(QDialog):
    """Sieg- und Niederlage-Bedingungen zusammenstellen."""
    def __init__(self, parent, victories, defeats):
        super().__init__(parent)
        self.setWindowTitle(tr("conditions_dlg.title"))
        self.resize(720, 460)
        self.victories = [Condition(**asdict(c)) for c in victories]
        self.defeats = [Condition(**asdict(c)) for c in defeats]

        # --- Formular (links) ---
        self.kind = QComboBox(); fill_combo(self.kind, CONDITIONS, "conditions")
        self.kind.currentTextChanged.connect(self._update_fields)
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.marks = QSpinBox(); self.marks.setRange(0, 200000); self.marks.setValue(600)
        self.count = QSpinBox(); self.count.setRange(0, 1000); self.count.setValue(1)
        self.compare = QComboBox(); self.compare.addItems(COMPARE.keys())
        self.tech_id = QSpinBox(); self.tech_id.setRange(0, 20000)
        self.resource = QComboBox(); self.resource.addItems(RESOURCES.keys())
        self.amount = QSpinBox(); self.amount.setRange(0, 1000000); self.amount.setValue(1000)
        self.building = QComboBox()
        for disp, mid, _ in STRUCTURES:
            self.building.addItem(disp, mid)
        self.objective = QLineEdit(tr("conditions_dlg.objective_default"))

        self.form = QFormLayout()
        self.form.addRow(tr("conditions_dlg.lbl_type"), self.kind)
        self._rows = {
            "player": self.player, "marks": self.marks, "count": self.count,
            "compare": self.compare, "tech_id": self.tech_id, "resource": self.resource,
            "amount": self.amount, "building": self.building, "objective": self.objective,
        }
        labels = {"player": tr("conditions_dlg.lbl_player"), "marks": tr("conditions_dlg.lbl_marks"),
                  "count": tr("conditions_dlg.lbl_count"),
                  "compare": tr("conditions_dlg.lbl_compare"), "tech_id": tr("conditions_dlg.lbl_tech_id"),
                  "resource": tr("conditions_dlg.lbl_resource"),
                  "amount": tr("conditions_dlg.lbl_amount"), "building": tr("conditions_dlg.lbl_building"),
                  "objective": tr("conditions_dlg.lbl_objective")}
        for key, w in self._rows.items():
            self.form.addRow(labels[key], w)

        add_win = QPushButton(tr("conditions_dlg.btn_add_win"))
        add_win.clicked.connect(lambda: self._add(True))
        add_lose = QPushButton(tr("conditions_dlg.btn_add_lose"))
        add_lose.clicked.connect(lambda: self._add(False))
        add_row = QHBoxLayout(); add_row.addWidget(add_win); add_row.addWidget(add_lose)

        left = QVBoxLayout()
        left.addLayout(self.form); left.addLayout(add_row); left.addStretch(1)

        # --- Listen (rechts) ---
        self.win_list = QListWidget()
        self.lose_list = QListWidget()
        rm_win = QPushButton(tr("conditions_dlg.btn_rm_win"))
        rm_win.clicked.connect(lambda: self._remove(True))
        rm_lose = QPushButton(tr("conditions_dlg.btn_rm_lose"))
        rm_lose.clicked.connect(lambda: self._remove(False))
        right = QVBoxLayout()
        right.addWidget(QLabel(tr("conditions_dlg.lbl_win_list"))); right.addWidget(self.win_list)
        right.addWidget(rm_win)
        right.addWidget(QLabel(tr("conditions_dlg.lbl_lose_list"))); right.addWidget(self.lose_list)
        right.addWidget(rm_lose)

        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(right, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self._refresh()
        self._update_fields()

    def _update_fields(self):
        fields = CONDITIONS[self.kind.currentData()][1]
        for key, w in self._rows.items():
            self.form.setRowVisible(w, key in fields)

    def _make(self) -> Condition:
        kind = CONDITIONS[self.kind.currentData()][0]
        return Condition(
            kind=kind, objective=self.objective.text(), player=self.player.value(),
            marks=self.marks.value(), count=self.count.value(),
            compare=COMPARE[self.compare.currentText()], tech_id=self.tech_id.value(),
            resource=RESOURCES[self.resource.currentText()], amount=self.amount.value(),
            building=self.building.currentData(),
        )

    def _add(self, is_victory):
        (self.victories if is_victory else self.defeats).append(self._make())
        self._refresh()

    def _remove(self, is_victory):
        lst = self.win_list if is_victory else self.lose_list
        data = self.victories if is_victory else self.defeats
        row = lst.currentRow()
        if 0 <= row < len(data):
            del data[row]
            self._refresh()

    def _refresh(self):
        self.win_list.clear(); self.lose_list.clear()
        for c in self.victories:
            self.win_list.addItem(condition_summary(c))
        for c in self.defeats:
            self.lose_list.addItem(condition_summary(c))


