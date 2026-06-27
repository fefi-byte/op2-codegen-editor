from __future__ import annotations
from ..common import *


class PlayersDialog(QDialog):
    """Spieler verwalten: Kolonie, Mensch/KI, Tech-Level, Kolonisten, Forschungen.

    EN: Manage players: colony, human/AI, tech level, colonists, researches.
    """
    def __init__(self, parent, players, diff_setup=None):
        super().__init__(parent)
        self.setWindowTitle(tr("players.title"))
        self.resize(640, 480)
        self.players = [PlayerSpec(**asdict(p)) for p in players] or [PlayerSpec()]
        self._diff_values = (
            (diff_setup.hard, diff_setup.normal, diff_setup.easy)
            if diff_setup else None
        )
        self._idx = 0
        self._loading = False
        self.all_techs = load_techs(TECHS_DIR / "multitek.txt")  # (id, name), sortiert
        # EN: (id, name), sorted
        self.tech_names = {tid: name for tid, name in self.all_techs}

        self.plist = QListWidget()
        add = QPushButton(tr("players.add_player")); add.clicked.connect(self._add)
        rm = QPushButton(tr("players.remove")); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(self.plist, 1); left.addWidget(add); left.addWidget(rm)

        self.colony = QComboBox(); self.colony.addItems(["Eden", "Plymouth"])
        self.ptype = QComboBox(); self.ptype.addItems([tr("players.human"), tr("players.ai")])
        self.tech = QSpinBox(); self.tech.setRange(0, 12)
        self.init_res = QCheckBox(tr("players.init_resources"))
        self.set_pop = QCheckBox(tr("players.set_population"))
        self.workers = QSpinBox(); self.workers.setRange(0, 5000)
        self.scientists = QSpinBox(); self.scientists.setRange(0, 5000)
        self.kids = QSpinBox(); self.kids.setRange(0, 5000)
        self.set_res = QCheckBox(tr("players.set_resources"))
        self.common = ExprEdit(diff_values=self._diff_values)
        self.common.setPlaceholderText("z.B. 2500 oder 2500 * diff / 10")
        self.rare = ExprEdit(diff_values=self._diff_values)
        self.rare.setPlaceholderText("z.B. 1000 oder ceil(1000 * diff / 10)")
        self.food = ExprEdit(diff_values=self._diff_values)

        # Forschungen: Auswahl per Name + "Tech hinzufügen" + Liste
        # EN: Researches: selection by name + "Add tech" + list
        self.tech_avail = QComboBox()
        add_tech = QPushButton(tr("players.add_tech"))
        add_tech.clicked.connect(self._add_tech)
        tech_add_row = QWidget(); tar = QHBoxLayout(tech_add_row); tar.setContentsMargins(0, 0, 0, 0)
        tar.addWidget(self.tech_avail, 1); tar.addWidget(add_tech)
        self.research_list = QListWidget()
        self.research_list.setMaximumHeight(110)
        rm_tech = QPushButton(tr("players.remove_research"))
        rm_tech.clicked.connect(self._remove_tech)

        form = QFormLayout()
        form.addRow(tr("players.colony"), self.colony)
        form.addRow(tr("players.type"), self.ptype)
        form.addRow(tr("players.tech_level"), self.tech)
        form.addRow(self.init_res)
        form.addRow(self.set_pop)
        form.addRow(tr("players.workers"), self.workers)
        form.addRow(tr("players.scientists"), self.scientists)
        form.addRow(tr("players.kids"), self.kids)
        form.addRow(self.set_res)
        form.addRow(tr("players.common_ore"), self.common)
        form.addRow(tr("players.rare_ore"), self.rare)
        form.addRow(tr("players.food"), self.food)
        form.addRow(tr("players.research"), tech_add_row)
        form.addRow(tr("players.pre_researched"), self.research_list)
        form.addRow("", rm_tech)

        # bei jeder Aenderung in den aktuellen Spieler schreiben
        # EN: on every change, write into the current player
        for w in (self.colony, self.ptype):
            w.currentIndexChanged.connect(self._store_current)
        for w in (self.workers, self.scientists, self.kids):
            w.valueChanged.connect(self._store_current)
        for w in (self.common, self.rare, self.food):
            w.valueChanged.connect(self._store_current)
        for w in (self.init_res, self.set_pop, self.set_res):
            w.toggled.connect(self._store_current)
        # Tech-Level beeinflusst auch die verfuegbaren Forschungen
        # EN: the tech level also affects the available researches
        self.tech.valueChanged.connect(self._on_tech_level_changed)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)

        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(form, 2)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self.plist.currentRowChanged.connect(self._on_select)
        self._refresh_list()
        self.plist.setCurrentRow(0)

    def _label(self, i, p):
        return tr("players.list_label",
                  i=i,
                  colony=("Eden" if p.colony == Colony.Eden else "Plymouth"),
                  type=(tr("players.human") if p.is_human else tr("players.ai")),
                  tech=p.tech_level)

    def _refresh_list(self):
        self.plist.blockSignals(True)
        cur = self.plist.currentRow()
        self.plist.clear()
        for i, p in enumerate(self.players):
            self.plist.addItem(self._label(i, p))
        self.plist.setCurrentRow(min(max(cur, 0), len(self.players) - 1))
        self.plist.blockSignals(False)

    def _on_select(self, row):
        if row < 0:
            return
        self._idx = row
        self._load(row)

    def _load(self, i):
        p = self.players[i]
        self._loading = True
        self.colony.setCurrentText("Eden" if p.colony == Colony.Eden else "Plymouth")
        self.ptype.setCurrentIndex(0 if p.is_human else 1)
        self.tech.setValue(p.tech_level)
        self.init_res.setChecked(p.init_resources)
        self.set_pop.setChecked(p.workers is not None or p.scientists is not None or p.kids is not None)
        self.workers.setValue(p.workers or 0)
        self.scientists.setValue(p.scientists or 0)
        self.kids.setValue(p.kids or 0)
        self.set_res.setChecked(p.common_ore is not None or p.rare_ore is not None or p.food is not None)
        self.common.setValue(p.common_ore if p.common_ore is not None else 0)
        self.rare.setValue(p.rare_ore if p.rare_ore is not None else 0)
        self.food.setValue(p.food if p.food is not None else 0)
        self._loading = False
        self._refresh_tech_avail(p.tech_level)
        self._refresh_research_list()

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.players)):
            return
        # Forschungen werden separat (Hinzufügen/Entfernen) verwaltet -> uebernehmen.
        # EN: researches are managed separately (add/remove) -> carry them over.
        researches = list(self.players[self._idx].researches)
        p = PlayerSpec(
            colony=Colony.Eden if self.colony.currentText() == "Eden" else Colony.Plymouth,
            is_human=(self.ptype.currentIndex() == 0),
            tech_level=self.tech.value(),
            init_resources=self.init_res.isChecked(),
            workers=self.workers.value() if self.set_pop.isChecked() else None,
            scientists=self.scientists.value() if self.set_pop.isChecked() else None,
            kids=self.kids.value() if self.set_pop.isChecked() else None,
            common_ore=self.common.value() if self.set_res.isChecked() else None,  # int | str
            rare_ore=self.rare.value() if self.set_res.isChecked() else None,
            food=self.food.value() if self.set_res.isChecked() else None,
            researches=researches,
        )
        self.players[self._idx] = p
        item = self.plist.item(self._idx)
        if item:
            item.setText(self._label(self._idx, p))

    def _on_tech_level_changed(self):
        if self._loading or not (0 <= self._idx < len(self.players)):
            return
        self._store_current()  # uebernimmt neues Tech-Level
        # EN: applies the new tech level
        lvl = self.players[self._idx].tech_level
        # Bereits durch das Tech-Level abgedeckte Forschungen entfernen.
        # EN: Remove researches that are already covered by the tech level.
        self.players[self._idx].researches = [
            t for t in self.players[self._idx].researches if t > lvl * 1000]
        self._refresh_tech_avail(lvl)
        self._refresh_research_list()

    def _refresh_tech_avail(self, tech_level: int):
        """Verfuegbare Techs = die NICHT schon durch das Tech-Level vergeben sind.

        EN: Available techs = those NOT already granted by the tech level.
        """
        self.tech_avail.clear()
        threshold = tech_level * 1000
        already = set(self.players[self._idx].researches) if 0 <= self._idx < len(self.players) else set()
        for tid, name in self.all_techs:
            if tid <= threshold or tid in already or name == "NOT AVAILABLE":
                continue
            self.tech_avail.addItem(f"{name}  ({tid})", tid)

    def _refresh_research_list(self):
        self.research_list.clear()
        if not (0 <= self._idx < len(self.players)):
            return
        for tid in self.players[self._idx].researches:
            name = self.tech_names.get(tid, "?")
            it = QListWidgetItem(f"{name}  ({tid})")
            it.setData(Qt.UserRole, tid)
            self.research_list.addItem(it)

    def _add_tech(self):
        tid = self.tech_avail.currentData()
        if tid is None or not (0 <= self._idx < len(self.players)):
            return
        p = self.players[self._idx]
        if tid not in p.researches:
            p.researches.append(tid)
            p.researches.sort()
        self._refresh_tech_avail(p.tech_level)
        self._refresh_research_list()

    def _remove_tech(self):
        it = self.research_list.currentItem()
        if it is None or not (0 <= self._idx < len(self.players)):
            return
        tid = it.data(Qt.UserRole)
        p = self.players[self._idx]
        if tid in p.researches:
            p.researches.remove(tid)
        self._refresh_tech_avail(p.tech_level)
        self._refresh_research_list()

    def _add(self):
        self.players.append(PlayerSpec())
        self._refresh_list()
        self.plist.setCurrentRow(len(self.players) - 1)

    def _remove(self):
        if len(self.players) <= 1:
            return
        del self.players[self._idx]
        self._idx = max(0, self._idx - 1)
        self._refresh_list()
        self.plist.setCurrentRow(self._idx)


