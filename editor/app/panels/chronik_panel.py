"""Chronik-Editor fuer "Neue Karte": die Geschichte der Karte in Kapiteln.

Jedes Kapitel ist eine kleine Karte: was passiert (Spaltenausbruch,
Einschlag ...), wo, wie stark und -- bei Wind und Absturz -- in welche
Richtung. Die Reihenfolge zaehlt: spaetere Kapitel ueberlagern fruehere.

Chronicle editor for "New map": the map's story in chapters.
"""
from __future__ import annotations

from PySide6.QtWidgets import QSlider

from ..common import *

import chronik

SYMBOL = {"urland": "⛰", "spalte": "🌋", "einschlag": "☄", "sandsturm": "🌪",
          "kolonie": "🏚", "absturz": "🛸", "flechten": "🌿"}
MIT_RICHTUNG = ("sandsturm", "absturz")


class KapitelKarte(QFrame):
    geaendert = Signal()
    entfernen = Signal(object)
    schieben = Signal(object, int)

    def __init__(self, nummer: int, k: chronik.Kapitel):
        super().__init__()
        self.k = k
        self.setObjectName("kapitel")
        self.setStyleSheet("QFrame#kapitel { background: #181825; border: 1px solid #313244;"
                           " border-radius: 6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 6, 6)
        lay.setSpacing(4)
        kopf = QHBoxLayout()
        titel = QLabel(f"<b>{nummer}. {SYMBOL.get(k.art, '')}  {tr('chronik.art_' + k.art)}</b>")
        kopf.addWidget(titel, 1)
        for text, delta in (("▲", -1), ("▼", 1)):
            b = QPushButton(text)
            b.setFixedWidth(26)
            b.clicked.connect(lambda _=False, d=delta: self.schieben.emit(self, d))
            kopf.addWidget(b)
        weg = QPushButton("✕")
        weg.setFixedWidth(26)
        weg.clicked.connect(lambda: self.entfernen.emit(self))
        kopf.addWidget(weg)
        lay.addLayout(kopf)
        hinweis = QLabel(tr("chronik.hint_" + k.art))
        hinweis.setWordWrap(True)
        hinweis.setProperty("secondary", "true")
        lay.addWidget(hinweis)

        zeile = QHBoxLayout()
        self.wo = QComboBox()
        for o in chronik.ORTE:
            self.wo.addItem(tr("chronik.ort_" + o), o)
        self.wo.setCurrentIndex(max(0, self.wo.findData(k.wo)))
        self.wo.setToolTip(tr("chronik.tip_wo"))
        self.wo.currentIndexChanged.connect(self._uebernehmen)
        zeile.addWidget(self.wo, 1)
        self.richtung = None
        if k.art in MIT_RICHTUNG:
            self.richtung = QComboBox()
            for r in chronik.RICHTUNGEN:
                self.richtung.addItem(tr("chronik.richtung_" + r), r)
            self.richtung.setCurrentIndex(max(0, self.richtung.findData(k.richtung)))
            self.richtung.setToolTip(tr("chronik.tip_richtung_" + k.art))
            self.richtung.currentIndexChanged.connect(self._uebernehmen)
            zeile.addWidget(self.richtung, 1)
        lay.addLayout(zeile)
        st = QHBoxLayout()
        st.addWidget(QLabel(tr("chronik.lbl_staerke_" + k.art)))
        self.staerke = QSlider(Qt.Horizontal)
        self.staerke.setRange(0, 100)
        self.staerke.setValue(int(round(100 * k.staerke)))
        self.staerke.sliderReleased.connect(self._uebernehmen)
        self.staerke.valueChanged.connect(
            lambda *_: None if self.staerke.isSliderDown() else self._uebernehmen())
        st.addWidget(self.staerke, 1)
        lay.addLayout(st)

    def _uebernehmen(self, *_):
        self.k.wo = self.wo.currentData() or "zufall"
        self.k.staerke = self.staerke.value() / 100.0
        if self.richtung is not None:
            self.k.richtung = self.richtung.currentData() or "zufall"
        self.geaendert.emit()


class ChronikEditor(QWidget):
    """Vorlage + Kapitelliste + Hinzufuegen. Meldet jede Aenderung."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kapitel: list[chronik.Kapitel] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        zeile = QHBoxLayout()
        zeile.addWidget(QLabel(tr("chronik.lbl_vorlage")))
        self.vorlage = QComboBox()
        for key in chronik.VORLAGEN:
            self.vorlage.addItem(tr("chronik.vorlage_" + key), key)
        self.vorlage.addItem(tr("chronik.vorlage_eigene"), "")
        self.vorlage.currentIndexChanged.connect(self._vorlage_gewaehlt)
        zeile.addWidget(self.vorlage, 1)
        lay.addLayout(zeile)
        self.beschreibung = QLabel("")
        self.beschreibung.setWordWrap(True)
        self.beschreibung.setProperty("secondary", "true")
        lay.addWidget(self.beschreibung)
        self.liste = QVBoxLayout()
        self.liste.setSpacing(5)
        lay.addLayout(self.liste)
        self.dazu = QPushButton(tr("chronik.btn_add"))
        self.dazu.clicked.connect(self._menue)
        lay.addWidget(self.dazu)
        self._vorlage_gewaehlt()

    def kapitel(self) -> list[chronik.Kapitel]:
        return [chronik.Kapitel(**k.als_dict()) for k in self._kapitel]

    def setze_kapitel(self, kapitel: list[chronik.Kapitel]) -> None:
        self._kapitel = [chronik.Kapitel(**k.als_dict()) for k in kapitel]
        self._neu()

    def _vorlage_gewaehlt(self, *_):
        key = self.vorlage.currentData()
        self.beschreibung.setText(tr("chronik.vorlage_" + key + "_text") if key else
                                  tr("chronik.vorlage_eigene_text"))
        if key:
            self._kapitel = [chronik.Kapitel(**k.als_dict()) for k in chronik.VORLAGEN[key]]
            self._neu()
            self.changed.emit()

    def _als_eigene(self):
        """Nach einer Aenderung ist es keine Vorlage mehr."""
        i = self.vorlage.findData("")
        if self.vorlage.currentIndex() != i:
            self.vorlage.blockSignals(True)
            self.vorlage.setCurrentIndex(i)
            self.vorlage.blockSignals(False)
            self.beschreibung.setText(tr("chronik.vorlage_eigene_text"))

    def _neu(self):
        while self.liste.count():
            it = self.liste.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        for i, k in enumerate(self._kapitel, 1):
            karte = KapitelKarte(i, k)
            karte.geaendert.connect(self._geaendert)
            karte.entfernen.connect(self._entfernen)
            karte.schieben.connect(self._schieben)
            self.liste.addWidget(karte)

    def _geaendert(self):
        self._als_eigene()
        self.changed.emit()

    def _entfernen(self, karte):
        if karte.k in self._kapitel:
            self._kapitel.remove(karte.k)
        self._als_eigene()
        self._neu()
        self.changed.emit()

    def _schieben(self, karte, delta):
        i = self._kapitel.index(karte.k)
        j = i + delta
        if 0 <= j < len(self._kapitel):
            self._kapitel[i], self._kapitel[j] = self._kapitel[j], self._kapitel[i]
            self._als_eigene()
            self._neu()
            self.changed.emit()

    def _menue(self):
        m = QMenu(self)
        for art in chronik.ARTEN:
            a = m.addAction(f"{SYMBOL.get(art, '')}  {tr('chronik.art_' + art)}")
            a.setData(art)
        gewaehlt = m.exec(self.dazu.mapToGlobal(self.dazu.rect().bottomLeft()))
        if gewaehlt is None:
            return
        self._kapitel.append(chronik.Kapitel(gewaehlt.data()))
        self._als_eigene()
        self._neu()
        self.changed.emit()


def geschichte(kapitel: list[chronik.Kapitel], orte: list[dict] | None = None) -> str:
    """Die Chronik als kurzer Text -- als Vorschlag fuer das Briefing.

    Jeder Satz beginnt mit der Zeitangabe ("Vor langer Zeit", "Spaeter",
    "Zuletzt"), danach folgt das Verb -- so passt die Reihenfolge im Deutschen
    wie im Englischen ohne Umbau."""
    saetze = []
    verschuettet = {o.get("kapitel") for o in (orte or []) if o.get("verschuettet")}
    ereignisse = [k for k in kapitel if k.art != "urland"]
    for i, k in enumerate(kapitel):
        wo = tr("chronik.ort_satz_" + (k.wo if k.wo in chronik.ORTE else "zufall"))
        richtung = tr("chronik.richtung_satz_" + (k.richtung if k.richtung in chronik.RICHTUNGEN
                                                   else "zufall"))
        if k.art == "urland":
            zeit = tr("chronik.zeit_immer")
        elif k is ereignisse[0]:
            zeit = tr("chronik.zeit_frueh")
        elif k is ereignisse[-1]:
            zeit = tr("chronik.zeit_zuletzt")
        else:
            zeit = tr("chronik.zeit_spaeter")
        saetze.append(tr("chronik.satz_" + k.art, zeit=zeit, wo=wo, richtung=richtung))
        if i in verschuettet:
            saetze.append(tr("chronik.satz_verschuettet"))
    return " ".join(saetze)
