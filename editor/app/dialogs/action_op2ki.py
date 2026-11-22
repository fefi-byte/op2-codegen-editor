"""Unterformular der Aktion "op2-ki-Befehl": Drehbuch-Phase, Angriff, Verteidigung, Drehbuch beenden, freier Befehl.

Die Daten liegen als dict in TriggerAction.op2ki (Aufbau: codegen/codegen_op2ki.py); daraus baut der Codegen den
Befehlstext fuer op2ki::befehl. Orte und Bereiche lassen sich auf der Karte waehlen (ctx["on_punkt_pick"]).

Sub-form of the "op2-ki command" action: script phase, attack, defence, end script, free command.
"""
from __future__ import annotations

from PySide6.QtWidgets import QStackedWidget

from ..common import *
from .action_form import DictZiel

ARTEN = ["phase", "angriff", "verteidigung", "drehbuchAus", "befehl"]
ZIELE = ["basis", "spieler", "punkt", "schwaechste"]
ANGRIFFSARTEN = ["basis", "ziel", "ueberfall", "halten"]
TRUPPEN = ["auto", "beste", "liste", "vorhanden"]


class EinheitenTabelle(QWidget):
    """Liste "Typ / Waffe / Anzahl" (Fahrzeuge) -- mit Hinzufuegen/Entfernen.

    List "type / weapon / count" with add/remove."""
    changed = Signal()

    def __init__(self, mit_waffe=True):
        super().__init__()
        self._mit_waffe = mit_waffe
        self.tab = QTableWidget(0, 3 if mit_waffe else 2)
        kopf = [tr("op2ki_form.col_typ")] + ([tr("op2ki_form.col_waffe")] if mit_waffe else []) + [tr("op2ki_form.col_anzahl")]
        self.tab.setHorizontalHeaderLabels(kopf)
        self.tab.horizontalHeader().setStretchLastSection(True)
        self.tab.verticalHeader().setVisible(False)
        self.tab.setMaximumHeight(120)
        plus = QPushButton("+"); plus.setFixedWidth(28); plus.clicked.connect(lambda: (self._zeile({}), self.changed.emit()))
        minus = QPushButton("−"); minus.setFixedWidth(28); minus.clicked.connect(self._weg)
        knoepfe = QHBoxLayout(); knoepfe.addWidget(plus); knoepfe.addWidget(minus); knoepfe.addStretch(1)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.tab); lay.addLayout(knoepfe)

    def _zeile(self, e: dict):
        r = self.tab.rowCount(); self.tab.insertRow(r)
        typ = QComboBox()
        for d, m in VEHICLE_UNITS:
            typ.addItem(d, m)
        i = typ.findData(e.get("typ", "mapLynx")); typ.setCurrentIndex(max(i, 0))
        typ.currentIndexChanged.connect(self.changed)
        self.tab.setCellWidget(r, 0, typ)
        sp = 1
        if self._mit_waffe:
            w = QComboBox()
            for d, m in WEAPONS:
                w.addItem(d, m)
            i = w.findData(e.get("waffe", "mapNone")); w.setCurrentIndex(max(i, 0))
            w.currentIndexChanged.connect(self.changed)
            self.tab.setCellWidget(r, 1, w); sp = 2
        n = QSpinBox(); n.setRange(1, 64); n.setValue(int(e.get("n", 1) or 1)); n.valueChanged.connect(self.changed)
        self.tab.setCellWidget(r, sp, n)

    def _weg(self):
        r = self.tab.currentRow()
        if r < 0:
            r = self.tab.rowCount() - 1
        if r >= 0:
            self.tab.removeRow(r); self.changed.emit()

    def laden(self, liste):
        self.tab.setRowCount(0)
        for e in liste or []:
            self._zeile(e)

    def daten(self) -> list:
        out = []
        for r in range(self.tab.rowCount()):
            e = {"typ": self.tab.cellWidget(r, 0).currentData()}
            if self._mit_waffe:
                e["waffe"] = self.tab.cellWidget(r, 1).currentData()
            e["n"] = self.tab.cellWidget(r, 2 if self._mit_waffe else 1).value()
            out.append(e)
        return out


class Op2kiAktionForm(QWidget):
    """Formular fuer TriggerAction.op2ki."""
    changed = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx if isinstance(ctx, dict) else {}
        self._aktion = None
        self._d: dict = {}
        self._loading = False
        self.spieler = QSpinBox(); self.spieler.setRange(0, 6); self.spieler.setValue(1)
        self.art = QComboBox()
        for a in ARTEN:
            self.art.addItem(tr(f"op2ki_form.art_{a}"), a)
        self.stapel = QStackedWidget()
        self.stapel.addWidget(self._seite_phase())
        self.stapel.addWidget(self._seite_angriff())
        self.stapel.addWidget(self._seite_verteidigung())
        hinweis = QLabel(tr("op2ki_form.drehbuch_aus_hinweis")); hinweis.setWordWrap(True)
        self.stapel.addWidget(hinweis)
        self.text = QPlainTextEdit(); self.text.setPlaceholderText("rolle=2\nzbWache=6\naussenposten=10,20,4")
        self.text.setMaximumHeight(90); self.text.textChanged.connect(self._geaendert)
        self.stapel.addWidget(self.text)
        form = QFormLayout(); form.setContentsMargins(0, 0, 0, 0)
        form.addRow(tr("op2ki_form.spieler"), self.spieler)
        form.addRow(tr("op2ki_form.art"), self.art)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addLayout(form); lay.addWidget(self.stapel)
        self.spieler.valueChanged.connect(self._geaendert)
        self.art.currentIndexChanged.connect(lambda: (self.stapel.setCurrentIndex(self.art.currentIndex()), self._geaendert()))

    # ---------------------------------------------------------------------------------------------- Seiten
    def _seite_phase(self):
        w = QWidget(); f = QFormLayout(w); f.setContentsMargins(0, 0, 0, 0)
        self.ph_id = QSpinBox(); self.ph_id.setRange(1, 99); self.ph_id.valueChanged.connect(self._geaendert)
        self.ph_grund = QCheckBox(tr("op2ki_form.grund")); self.ph_grund.setChecked(True); self.ph_grund.setToolTip(tr("op2ki_form.grund_tip"))
        self.ph_reihe = QCheckBox(tr("op2ki_form.reihe")); self.ph_reihe.setToolTip(tr("op2ki_form.reihe_tip"))
        for c in (self.ph_grund, self.ph_reihe):
            c.toggled.connect(self._geaendert)
        # Bauliste: Typ, Anzahl, Ort (X, Y, Umkreis; X = -1 ohne Ort)
        self.bau = QTableWidget(0, 5)
        self.bau.setHorizontalHeaderLabels([tr("op2ki_form.col_typ"), tr("op2ki_form.col_anzahl"), "X", "Y", tr("op2ki_form.col_umkreis")])
        self.bau.horizontalHeader().setStretchLastSection(True); self.bau.verticalHeader().setVisible(False); self.bau.setMaximumHeight(140)
        plus = QPushButton("+"); plus.setFixedWidth(28); plus.clicked.connect(lambda: (self._bau_zeile({}), self._geaendert()))
        minus = QPushButton("−"); minus.setFixedWidth(28); minus.clicked.connect(self._bau_weg)
        ort = QPushButton(tr("op2ki_form.ort_waehlen")); ort.clicked.connect(self._bau_ort)
        k = QHBoxLayout(); k.addWidget(plus); k.addWidget(minus); k.addWidget(ort); k.addStretch(1)
        bau = QWidget(); bl = QVBoxLayout(bau); bl.setContentsMargins(0, 0, 0, 0); bl.addWidget(self.bau); bl.addLayout(k)
        # Forschung: Auswahl nach Namen + Liste
        self.techs = load_techs(TECHS_DIR / "multitek.txt")
        self.tech_wahl = QComboBox()
        for tid, nm in self.techs:
            if nm != "NOT AVAILABLE":
                self.tech_wahl.addItem(f"{nm}  ({tid})", tid)
        tplus = QPushButton(tr("op2ki_form.tech_dazu")); tplus.clicked.connect(self._tech_dazu)
        tminus = QPushButton("−"); tminus.setFixedWidth(28); tminus.clicked.connect(self._tech_weg)
        self.tech_liste = QListWidget(); self.tech_liste.setMaximumHeight(90)
        tk = QHBoxLayout(); tk.addWidget(self.tech_wahl, 1); tk.addWidget(tplus); tk.addWidget(tminus)
        fo = QWidget(); fl = QVBoxLayout(fo); fl.setContentsMargins(0, 0, 0, 0); fl.addLayout(tk); fl.addWidget(self.tech_liste)
        self.ph_fz = EinheitenTabelle(); self.ph_fz.changed.connect(self._geaendert)
        f.addRow(tr("op2ki_form.phase_nr"), self.ph_id)
        f.addRow("", self.ph_grund); f.addRow("", self.ph_reihe)
        f.addRow(tr("op2ki_form.bauen"), bau)
        f.addRow(tr("op2ki_form.forschen"), fo)
        f.addRow(tr("op2ki_form.fahrzeuge"), self.ph_fz)
        return w

    def _seite_angriff(self):
        w = QWidget(); f = QFormLayout(w); f.setContentsMargins(0, 0, 0, 0)
        self.an_ziel = QComboBox()
        for z in ZIELE:
            self.an_ziel.addItem(tr(f"op2ki_form.ziel_{z}"), z)
        self.an_zielspieler = QSpinBox(); self.an_zielspieler.setRange(0, 6)
        self.an_x = QSpinBox(); self.an_x.setRange(0, 1023); self.an_y = QSpinBox(); self.an_y.setRange(0, 1023)
        pick = QPushButton(tr("op2ki_form.ort_waehlen")); pick.clicked.connect(self._angriff_ort)
        ort = QWidget(); ol = QHBoxLayout(ort); ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(QLabel("X")); ol.addWidget(self.an_x); ol.addWidget(QLabel("Y")); ol.addWidget(self.an_y); ol.addWidget(pick); ol.addStretch(1)
        self.an_art = QComboBox()
        for a in ANGRIFFSARTEN:
            self.an_art.addItem(tr(f"op2ki_form.angriffsart_{a}"), a)
        self.an_parallel = QCheckBox(tr("op2ki_form.parallel")); self.an_parallel.setToolTip(tr("op2ki_form.parallel_tip"))
        self.an_emp = QComboBox()
        for e in ("", "an", "aus"):
            self.an_emp.addItem(tr(f"op2ki_form.emp_{e or 'selbst'}"), e)
        self.an_truppe = QComboBox()
        for t in TRUPPEN:
            self.an_truppe.addItem(tr(f"op2ki_form.truppe_{t}"), t)
        self.an_anzahl = QSpinBox(); self.an_anzahl.setRange(1, 64); self.an_anzahl.setValue(8)
        self.an_einheiten = EinheitenTabelle(); self.an_einheiten.changed.connect(self._geaendert)
        self.an_rueckzug = QSpinBox(); self.an_rueckzug.setRange(0, 95); self.an_rueckzug.setSuffix(" %"); self.an_rueckzug.setToolTip(tr("op2ki_form.rueckzug_tip"))
        self.an_frist = QSpinBox(); self.an_frist.setRange(0, 200000); self.an_frist.setSingleStep(1000); self.an_frist.setValue(20000); self.an_frist.setToolTip(tr("op2ki_form.frist_tip"))
        for c in (self.an_ziel, self.an_art, self.an_emp, self.an_truppe):
            c.currentIndexChanged.connect(self._geaendert)
        for s in (self.an_zielspieler, self.an_x, self.an_y, self.an_anzahl, self.an_rueckzug, self.an_frist):
            s.valueChanged.connect(self._geaendert)
        self.an_parallel.toggled.connect(self._geaendert)
        f.addRow(tr("op2ki_form.ziel"), self.an_ziel)
        f.addRow(tr("op2ki_form.zielspieler"), self.an_zielspieler)
        f.addRow(tr("op2ki_form.ort"), ort)
        f.addRow(tr("op2ki_form.angriffsart"), self.an_art)
        f.addRow("", self.an_parallel)
        f.addRow(tr("op2ki_form.emp"), self.an_emp)
        f.addRow(tr("op2ki_form.truppe"), self.an_truppe)
        f.addRow(tr("op2ki_form.anzahl"), self.an_anzahl)
        f.addRow(tr("op2ki_form.einheiten"), self.an_einheiten)
        f.addRow(tr("op2ki_form.rueckzug"), self.an_rueckzug)
        f.addRow(tr("op2ki_form.frist"), self.an_frist)
        self._an_form = f
        return w

    def _seite_verteidigung(self):
        w = QWidget(); f = QFormLayout(w); f.setContentsMargins(0, 0, 0, 0)
        self.ve_truppe = QComboBox()
        for t in TRUPPEN[:3]:
            self.ve_truppe.addItem(tr(f"op2ki_form.truppe_{t}"), t)
        self.ve_anzahl = QSpinBox(); self.ve_anzahl.setRange(0, 64); self.ve_anzahl.setValue(6)
        self.ve_einheiten = EinheitenTabelle(); self.ve_einheiten.changed.connect(self._geaendert)
        self.ve_bereich = QLabel()
        pick = QPushButton(tr("op2ki_form.bereich_waehlen")); pick.clicked.connect(self._vert_bereich)
        weg = QPushButton(tr("op2ki_form.bereich_weg")); weg.clicked.connect(lambda: (self._d.__setitem__("bereich", {}), self._bereich_text(), self._geaendert()))
        be = QWidget(); bl = QHBoxLayout(be); bl.setContentsMargins(0, 0, 0, 0); bl.addWidget(self.ve_bereich, 1); bl.addWidget(pick); bl.addWidget(weg)
        self.ve_turm = QComboBox(); self.ve_turm.addItem(tr("op2ki_form.turm_selbst"), "")
        for d, m in WEAPONS:
            if m != "mapNone":
                self.ve_turm.addItem(d, m)
        self.ve_patr = QComboBox()
        for e in ("", "an", "aus"):
            self.ve_patr.addItem(tr(f"op2ki_form.patr_{e or 'selbst'}"), e)
        for c in (self.ve_truppe, self.ve_turm, self.ve_patr):
            c.currentIndexChanged.connect(self._geaendert)
        self.ve_anzahl.valueChanged.connect(self._geaendert)
        f.addRow(tr("op2ki_form.truppe"), self.ve_truppe)
        f.addRow(tr("op2ki_form.anzahl"), self.ve_anzahl)
        f.addRow(tr("op2ki_form.einheiten"), self.ve_einheiten)
        f.addRow(tr("op2ki_form.bereich"), be)
        f.addRow(tr("op2ki_form.turm"), self.ve_turm)
        f.addRow(tr("op2ki_form.patrouille"), self.ve_patr)
        return w

    # ---------------------------------------------------------------------------------------------- Bauliste/Forschung
    def _bau_zeile(self, b: dict):
        r = self.bau.rowCount(); self.bau.insertRow(r)
        typ = QComboBox()
        for d, m, _ in STRUCTURES:
            typ.addItem(d, m)
        i = typ.findData(b.get("typ", "mapTokamak")); typ.setCurrentIndex(max(i, 0))
        typ.currentIndexChanged.connect(self._geaendert)
        self.bau.setCellWidget(r, 0, typ)
        for sp, (lo, hi, std) in enumerate([(1, 99, b.get("n", 1)), (-1, 1023, b.get("x", -1)), (-1, 1023, b.get("y", -1)), (1, 40, b.get("r", 6))], start=1):
            s = QSpinBox(); s.setRange(lo, hi); s.setValue(int(std))
            if sp in (2, 3):
                s.setSpecialValueText("–")
            s.valueChanged.connect(self._geaendert)
            self.bau.setCellWidget(r, sp, s)

    def _bau_weg(self):
        r = self.bau.currentRow()
        if r < 0:
            r = self.bau.rowCount() - 1
        if r >= 0:
            self.bau.removeRow(r); self._geaendert()

    def _bau_daten(self) -> list:
        return [{"typ": self.bau.cellWidget(r, 0).currentData(), "n": self.bau.cellWidget(r, 1).value(),
                 "x": self.bau.cellWidget(r, 2).value(), "y": self.bau.cellWidget(r, 3).value(),
                 "r": self.bau.cellWidget(r, 4).value()} for r in range(self.bau.rowCount())]

    def _tech_dazu(self):
        tid = self.tech_wahl.currentData()
        if tid is None or tid in self._tech_ids():
            return
        it = QListWidgetItem(self.tech_wahl.currentText()); it.setData(Qt.UserRole, tid)
        self.tech_liste.addItem(it); self._geaendert()

    def _tech_weg(self):
        r = self.tech_liste.currentRow()
        if r >= 0:
            self.tech_liste.takeItem(r); self._geaendert()

    def _tech_ids(self) -> list:
        return [self.tech_liste.item(i).data(Qt.UserRole) for i in range(self.tech_liste.count())]

    # ---------------------------------------------------------------------------------------------- Karte
    def _pick(self, ziel: dict, modus: str):
        """ziel muss in self._d haengen (vorher _geaendert(), sonst ersetzt das naechste Speichern es)."""
        cb = self.ctx.get("on_punkt_pick")
        if callable(cb):
            # Ohne eigenes `danach`: die Aktionskarten werden neu aufgebaut und laden aktion.op2ki frisch.
            cb(DictZiel(ziel), modus, None, self._aktion)

    def _bau_ort(self):
        r = self.bau.currentRow()
        if r < 0:
            return
        self._geaendert()
        self._pick(self._d["bauen"][r], "point")

    def _angriff_ort(self):
        self._geaendert()
        self._pick(self._d, "point")

    def _vert_bereich(self):
        self._geaendert()
        self._d["bereich"] = b = dict(self._d.get("bereich") or {})
        self._pick(b, "rect")

    def _bereich_text(self):
        b = self._d.get("bereich") or {}
        if int(b.get("width", 0) or 0) > 0:
            self.ve_bereich.setText(f"{b.get('x', 0)},{b.get('y', 0)}  {b['width']}×{b.get('height', 0)}")
        else:
            self.ve_bereich.setText(tr("op2ki_form.bereich_keiner"))

    # ---------------------------------------------------------------------------------------------- Laden/Speichern
    def laden(self, aktion):
        self._aktion = aktion
        self._d = dict(getattr(aktion, "op2ki", None) or {})
        aktion.op2ki = self._d
        d = self._d
        self._loading = True
        self.spieler.setValue(int(d.get("spieler", 1) or 0))
        i = self.art.findData(d.get("art", "phase")); self.art.setCurrentIndex(max(i, 0)); self.stapel.setCurrentIndex(max(i, 0))
        self.ph_id.setValue(int(d.get("id", 1) or 1))
        self.ph_grund.setChecked(bool(d.get("grund", True))); self.ph_reihe.setChecked(bool(d.get("reihe", False)))
        self.bau.setRowCount(0)
        for b in d.get("bauen") or []:
            self._bau_zeile(b)
        self.tech_liste.clear()
        namen = dict(self.techs)
        for tid in d.get("forschen") or []:
            it = QListWidgetItem(f"{namen.get(int(tid), '?')}  ({tid})"); it.setData(Qt.UserRole, int(tid)); self.tech_liste.addItem(it)
        self.ph_fz.laden(d.get("fahrzeuge"))
        for combo, key, std in ((self.an_ziel, "ziel", "basis"), (self.an_art, "angriffsart", "basis"), (self.an_emp, "emp", ""),
                                (self.an_truppe, "truppe", "auto"), (self.ve_turm, "turm", ""), (self.ve_patr, "patrouille", "")):
            j = combo.findData(d.get(key, std)); combo.setCurrentIndex(max(j, 0))
        self.an_zielspieler.setValue(int(d.get("zielspieler", 0) or 0))
        self.an_x.setValue(int(d.get("x", 0) or 0)); self.an_y.setValue(int(d.get("y", 0) or 0))
        self.an_parallel.setChecked(bool(d.get("parallel", False)))
        self.an_anzahl.setValue(int(d.get("anzahl", 8) or 8))
        self.an_einheiten.laden(d.get("einheiten") if d.get("art") == "angriff" else [])
        self.an_rueckzug.setValue(int(d.get("rueckzug", 0) or 0)); self.an_frist.setValue(int(d.get("frist", 20000) or 0))
        j = self.ve_truppe.findData(d.get("truppe", "auto")); self.ve_truppe.setCurrentIndex(max(j, 0))
        self.ve_anzahl.setValue(int(d.get("anzahl", 6) or 0))
        self.ve_einheiten.laden(d.get("einheiten") if d.get("art") == "verteidigung" else [])
        self._bereich_text()
        self.text.setPlainText(d.get("text", "") or "")
        self._loading = False

    def daten(self) -> dict:
        art = self.art.currentData()
        d: dict = {"spieler": self.spieler.value(), "art": art}
        if art == "phase":
            d.update(id=self.ph_id.value(), grund=self.ph_grund.isChecked(), reihe=self.ph_reihe.isChecked(),
                     bauen=self._bau_daten(), forschen=self._tech_ids(), fahrzeuge=self.ph_fz.daten())
        elif art == "angriff":
            d.update(ziel=self.an_ziel.currentData(), zielspieler=self.an_zielspieler.value(), x=self.an_x.value(), y=self.an_y.value(),
                     angriffsart=self.an_art.currentData(), parallel=self.an_parallel.isChecked(), emp=self.an_emp.currentData(),
                     truppe=self.an_truppe.currentData(), anzahl=self.an_anzahl.value(), einheiten=self.an_einheiten.daten(),
                     rueckzug=self.an_rueckzug.value(), frist=self.an_frist.value())
        elif art == "verteidigung":
            d.update(truppe=self.ve_truppe.currentData(), anzahl=self.ve_anzahl.value(), einheiten=self.ve_einheiten.daten(),
                     bereich=dict(self._d.get("bereich") or {}), turm=self.ve_turm.currentData(), patrouille=self.ve_patr.currentData())
        elif art == "befehl":
            d["text"] = self.text.toPlainText()
        return d

    def _geaendert(self, *_):
        if self._loading:
            return
        if self._aktion is not None:
            self._d.clear(); self._d.update(self.daten())
            self._aktion.op2ki = self._d
        self.changed.emit()
