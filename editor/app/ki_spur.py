"""KI-Spur: was die Aufbau-KI im Spiel getan hat, auf der Karte nachsehen.

Die Missions-DLL (op2_ki.hpp) schreibt nach <Spiel>/OPU/logs/<Mission>-KI.jsonl
eine JSON-Zeile je Ereignis: "start" (Karte, Basismitte), "stand" (Momentauf-
nahme: Rohstoffe, Gebaeude, Fahrzeuge, geplante Bauplaetze, Roehren) und
"entscheid" (was die KI beschlossen hat und warum). Dieses Dock liest die Datei,
zeigt einen Schieberegler ueber die Momentaufnahmen und malt den jeweiligen Stand
auf die Karte. Im Live-Modus liest es die Datei waehrend des Spiels nach.

AI trace: replay what the building AI did in the game, on the map. The mission
DLL writes one JSON line per event to <Mission>-KI.jsonl; this dock reads it,
offers a slider over the snapshots and draws the state onto the map. In live
mode it re-reads the file while the game runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QSlider

from .common import *
from . import game_data


# ---------------------------------------------------------------------------
# Datei lesen / reading the file (ohne Qt, testbar)

@dataclass
class Spur:
    start: dict | None = None
    staende: list = field(default_factory=list)       # Momentaufnahmen, nach Tick
    entscheide: list = field(default_factory=list)    # Entscheidungen, nach Tick
    spieler: list = field(default_factory=list)       # vorkommende Spielernummern
    starts: dict = field(default_factory=dict)        # Spieler -> "start"-Zeile
    fehlerhaft: int = 0                               # unlesbare Zeilen


def lese_spur(text: str) -> Spur:
    """Liest eine KI-Spur. Bei mehreren Laeufen in einer Datei gilt der letzte
    (jeder Spielstart schreibt eine "start"-Zeile).

    Reads an AI trace; with several runs in one file the last one counts."""
    spur = Spur()
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if not zeile.startswith("{"):
            continue
        try:
            d = json.loads(zeile)
        except ValueError:
            spur.fehlerhaft += 1
            continue
        art = d.get("art")
        if art == "start":
            # Startet ein Spieler erneut, beginnt ein neuer Lauf -- der alte
            # faellt weg. Mehrere KI-Spieler eines Laufs starten nacheinander.
            # A player starting again begins a new run; the old one is dropped.
            p = int(d.get("p", 0))
            if p in spur.spieler:
                spur = Spur(fehlerhaft=spur.fehlerhaft)
            if spur.start is None:
                spur.start = d
            spur.starts[p] = d
            spur.spieler.append(p)
        elif art == "stand":
            spur.staende.append(d)
        elif art == "entscheid":
            spur.entscheide.append(d)
    spur.staende.sort(key=lambda s: int(s.get("t", 0)))
    spur.entscheide.sort(key=lambda s: int(s.get("t", 0)))
    if not spur.spieler:
        spur.spieler = sorted({int(s.get("p", 0)) for s in spur.staende})
    return spur


# Grundflaechen nach dem Namen ohne "map" (so schreibt die DLL die Typen)
_GROESSE = {mid[3:]: fp for _anzeige, mid, fp in game_data.STRUCTURES}

_FARBE_PLATZ = {
    1: QColor(249, 226, 175),     # ConVec unterwegs
    2: QColor(250, 179, 135),     # im Bau
    3: QColor(166, 227, 161),     # steht
    9: QColor(243, 139, 168),     # gesperrt
}
_FARBE_WAS = {
    "fehler": QColor(243, 139, 168),
    "warte": QColor(249, 226, 175),
    "bau": QColor(166, 227, 161),
    "fertig": QColor(166, 227, 161),
    "kit": QColor(137, 180, 250),
    "fahrzeug": QColor(137, 180, 250),
    "forschung": QColor(203, 166, 247),
    "mine": QColor(250, 179, 135),
    "vermessen": QColor(250, 179, 135),
    "roehre": QColor(148, 226, 213),
}
_FZ_KURZ = {"ConVec": "CV", "CargoTruck": "LKW", "RoboMiner": "Mi", "RoboSurveyor": "Su",
            "Earthworker": "EW", "RoboDozer": "Dz", "Scout": "Sc"}


def stand_bei(spur: Spur, tick: int, spieler: int) -> dict | None:
    """Letzte Momentaufnahme bis `tick` fuer einen Spieler."""
    letzte = None
    for s in spur.staende:
        if int(s.get("p", 0)) != spieler:
            continue
        if int(s.get("t", 0)) > tick:
            break
        letzte = s
    return letzte


# ---------------------------------------------------------------------------
# Dock

class _KiSpurMixin:
    """Dock "KI-Spur" und das Kartenbild dazu.

    "AI trace" dock and its map drawing."""

    def _build_ki_spur(self):
        self._ki_spur = Spur()
        self._ki_pfad: Path | None = None
        self._ki_items: list = []
        self._ki_marke: list = []
        self._ki_groesse = (-1, 0.0)
        dock = QDockWidget(tr("ki_spur.title"), self)
        dock.setObjectName("dock_ki_spur")
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        w = QWidget()
        lay = QVBoxLayout(w)
        kopf = QHBoxLayout()
        oeffnen = QPushButton(tr("ki_spur.open"))
        oeffnen.clicked.connect(self._ki_oeffnen)
        self._ki_live = QCheckBox(tr("ki_spur.live"))
        self._ki_live.setToolTip(tr("ki_spur.live_tip"))
        self._ki_live.toggled.connect(self._ki_live_umschalten)
        self._ki_karte = QCheckBox(tr("ki_spur.on_map"))
        self._ki_karte.setChecked(True)
        self._ki_karte.toggled.connect(lambda _on: self._ki_zeigen())
        kopf.addWidget(oeffnen); kopf.addWidget(self._ki_live); kopf.addWidget(self._ki_karte); kopf.addStretch(1)
        lay.addLayout(kopf)
        self._ki_datei = QLabel(tr("ki_spur.no_file"))
        self._ki_datei.setWordWrap(True)
        lay.addWidget(self._ki_datei)
        reihe = QHBoxLayout()
        self._ki_spieler = QComboBox()
        self._ki_spieler.currentIndexChanged.connect(lambda _i: self._ki_zeigen())
        reihe.addWidget(QLabel(tr("ki_spur.player"))); reihe.addWidget(self._ki_spieler); reihe.addStretch(1)
        lay.addLayout(reihe)
        self._ki_regler = QSlider(Qt.Horizontal)
        self._ki_regler.setRange(0, 0)
        self._ki_regler.valueChanged.connect(lambda _v: self._ki_zeigen())
        lay.addWidget(self._ki_regler)
        self._ki_zeit = QLabel("")
        lay.addWidget(self._ki_zeit)
        self._ki_werte = QLabel("")
        self._ki_werte.setWordWrap(True)
        self._ki_werte.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self._ki_werte)
        self._ki_liste = QListWidget()
        self._ki_liste.itemClicked.connect(self._ki_springen)
        lay.addWidget(self._ki_liste, 1)
        dock.setWidget(w)
        self.ki_spur_dock = dock
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.visibilityChanged.connect(lambda sichtbar: self._ki_zeigen() if sichtbar else self._ki_weg())
        if self._view_menu is not None:
            act = dock.toggleViewAction()
            act.setText(tr("ki_spur.title"))
            self._view_menu.addAction(act)
        self._ki_timer = QTimer(self)
        self._ki_timer.setInterval(1000)
        self._ki_timer.timeout.connect(self._ki_nachlesen)

    # -- Datei ---------------------------------------------------------------
    def _ki_logordner(self) -> Path:
        basis = Path(appconfig.game_path())
        for kandidat in (basis / "OPU" / "logs", basis / "logs", basis):
            if kandidat.is_dir():
                return kandidat
        return Path.home()

    def _ki_oeffnen(self):
        pfad, _f = QFileDialog.getOpenFileName(self, tr("ki_spur.open"), str(self._ki_logordner()),
                                               tr("ki_spur.filter"))
        if pfad:
            self.ki_spur_laden(Path(pfad))

    def ki_spur_laden(self, pfad: Path):
        self._ki_pfad = Path(pfad)
        self._ki_groesse = (-1, 0.0)
        self._ki_nachlesen(erzwingen=True)

    def _ki_live_umschalten(self, an):
        if an:
            self._ki_timer.start()
        else:
            self._ki_timer.stop()

    def _ki_nachlesen(self, erzwingen: bool = False):
        if self._ki_pfad is None:
            return
        try:
            st = self._ki_pfad.stat()
            groesse = (st.st_size, st.st_mtime)
            if not erzwingen and groesse == self._ki_groesse:
                return
            text = self._ki_pfad.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._ki_datei.setText(tr("ki_spur.unreadable", path=str(self._ki_pfad)))
            return
        self._ki_groesse = groesse
        am_ende = self._ki_regler.value() >= self._ki_regler.maximum()
        self._ki_spur = lese_spur(text)
        sp = self._ki_spur
        self._ki_datei.setText(tr("ki_spur.file_info", name=self._ki_pfad.name,
                                  staende=len(sp.staende), entscheide=len(sp.entscheide)))
        alt = self._ki_spieler.currentData()
        self._ki_spieler.blockSignals(True)
        self._ki_spieler.clear()
        for p in sp.spieler or [0]:
            self._ki_spieler.addItem(str(p), p)
        if alt is not None and alt in (sp.spieler or [0]):
            self._ki_spieler.setCurrentIndex((sp.spieler or [0]).index(alt))
        self._ki_spieler.blockSignals(False)
        self._ki_regler.blockSignals(True)
        self._ki_regler.setRange(0, max(0, len(self._ki_ticks()) - 1))
        if am_ende or erzwingen:
            self._ki_regler.setValue(self._ki_regler.maximum())
        self._ki_regler.blockSignals(False)
        self._ki_zeigen()

    def _ki_ticks(self) -> list[int]:
        p = self._ki_spieler.currentData() if self._ki_spieler.count() else 0
        return [int(s.get("t", 0)) for s in self._ki_spur.staende if int(s.get("p", 0)) == (p or 0)] or [0]

    # -- Anzeige ---------------------------------------------------------------
    def _ki_weg(self):
        for item in self._ki_items + self._ki_marke:
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
        self._ki_items = []
        self._ki_marke = []

    def _ki_zeigen(self):
        if not hasattr(self, "_ki_regler"):
            return
        ticks = self._ki_ticks()
        i = min(self._ki_regler.value(), len(ticks) - 1)
        tick = ticks[i] if ticks else 0
        p = self._ki_spieler.currentData() or 0
        self._ki_zeit.setText(tr("ki_spur.time", tick=tick, mark=tick // 100))
        stand = stand_bei(self._ki_spur, tick, p)
        if stand:
            strom = stand.get("strom", [0, 0])
            self._ki_werte.setText(tr(
                "ki_spur.values", erz=stand.get("erz", 0), erzmax=stand.get("erzMax", 0),
                nahrung=stand.get("nahrung", 0), netto=stand.get("nahrungNetto", 0),
                strom_an=strom[0] if len(strom) > 0 else 0, strom_ab=strom[1] if len(strom) > 1 else 0,
                arbeiter=stand.get("arbeiter", 0), wiss=stand.get("wiss", 0), kinder=stand.get("kinder", 0),
                wohnraum=stand.get("wohnraum", 0), geb=len(stand.get("geb", [])), fz=len(stand.get("fz", []))))
        else:
            self._ki_werte.setText("")
        # Entscheidungen bis zum gewaehlten Zeitpunkt, die neueste oben
        self._ki_liste.clear()
        bis = [e for e in self._ki_spur.entscheide if int(e.get("p", 0)) == p and int(e.get("t", 0)) <= tick]
        for e in reversed(bis[-300:]):
            text = f"{e.get('t', 0):>6}  {e.get('was', '')}: {e.get('typ', '')} — {e.get('warum', '')}"
            item = QListWidgetItem(text)
            farbe = _FARBE_WAS.get(e.get("was", ""))
            if farbe is not None:
                item.setForeground(QBrush(farbe))
            item.setData(Qt.UserRole, (int(e.get("x", 0)), int(e.get("y", 0))))
            item.setToolTip(text)
            self._ki_liste.addItem(item)
        self._ki_malen(stand)

    def _ki_malen(self, stand):
        self._ki_weg()
        if not stand or not self._ki_karte.isChecked() or not self.ki_spur_dock.isVisible():
            return
        T = SCENE_TILE

        def merken(item, z=950):
            item.setZValue(z)
            self.scene.addItem(item)
            self._ki_items.append(item)
            return item

        # Roehren
        for x1, y1, x2, y2, zust in stand.get("roehren", []):
            farbe = QColor(148, 226, 213) if zust == 2 else QColor(249, 226, 175) if zust == 1 else QColor(180, 180, 190)
            r = QGraphicsRectItem(x1 * T + T * 0.3, y1 * T + T * 0.3, (x2 - x1 + 0.4) * T, (y2 - y1 + 0.4) * T)
            r.setPen(QPen(farbe, 1, Qt.SolidLine if zust == 2 else Qt.DashLine))
            r.setBrush(QBrush(QColor(farbe.red(), farbe.green(), farbe.blue(), 70)))
            merken(r, 940)
        # Geplante Plaetze
        for name, x0, y0, w, h, zust in stand.get("plaetze", []):
            if zust == 0:
                continue
            farbe = _FARBE_PLATZ.get(zust, QColor(200, 200, 200))
            r = QGraphicsRectItem(x0 * T, y0 * T, w * T, h * T)
            r.setPen(QPen(farbe, 2, Qt.DashLine))
            r.setBrush(QBrush(QColor(farbe.red(), farbe.green(), farbe.blue(), 25)))
            merken(r, 945)
        # Gebaeude (Ort = Mitte, wie im Editor)
        weiss = QColor(240, 240, 245)
        for name, x, y, *_rest in stand.get("geb", []):
            w, h = _GROESSE.get(name, (2, 2))
            x0, y0 = x - w // 2, y - h // 2
            r = QGraphicsRectItem(x0 * T, y0 * T, w * T, h * T)
            r.setPen(QPen(QColor(166, 227, 161), 2))
            r.setBrush(QBrush(QColor(166, 227, 161, 45)))
            merken(r, 950)
            t = QGraphicsSimpleTextItem(name)
            t.setBrush(QBrush(weiss))
            t.setPos(x0 * T + 3, y0 * T + 2)
            merken(t, 951)
        # Fahrzeuge
        for eintrag in stand.get("fz", []):
            name, x, y = eintrag[0], eintrag[1], eintrag[2]
            fracht = eintrag[3] if len(eintrag) > 3 else "-"
            cx, cy = x * T + T / 2, y * T + T / 2
            rad = T * 0.35
            d = QGraphicsEllipseItem(cx - rad, cy - rad, 2 * rad, 2 * rad)
            d.setPen(QPen(QColor(137, 180, 250), 2))
            d.setBrush(QBrush(QColor(137, 180, 250, 120)))
            merken(d, 955)
            kurz = _FZ_KURZ.get(name, name[:3])
            if fracht not in ("-", "?", ""):
                kurz += "→" + fracht
            t = QGraphicsSimpleTextItem(kurz)
            t.setBrush(QBrush(weiss))
            t.setPos(cx + rad, cy - rad)
            merken(t, 956)
        # Basismitte
        start = self._ki_spur.starts.get(self._ki_spieler.currentData() or 0) or self._ki_spur.start
        if start:
            bx, by = int(start.get("bx", 0)), int(start.get("by", 0))
            kreuz = QGraphicsPathItem()
            pfad = QPainterPath()
            pfad.moveTo((bx - 1) * T, by * T + T / 2); pfad.lineTo((bx + 2) * T, by * T + T / 2)
            pfad.moveTo(bx * T + T / 2, (by - 1) * T); pfad.lineTo(bx * T + T / 2, (by + 2) * T)
            kreuz.setPath(pfad)
            kreuz.setPen(QPen(QColor(243, 139, 168), 2))
            merken(kreuz, 957)

    def _ki_springen(self, item):
        ziel = item.data(Qt.UserRole)
        if not ziel:
            return
        x, y = ziel
        T = SCENE_TILE
        for m in self._ki_marke:
            try:
                self.scene.removeItem(m)
            except RuntimeError:
                pass
        self._ki_marke = []
        r = QGraphicsEllipseItem(x * T - T, y * T - T, 3 * T, 3 * T)
        r.setPen(QPen(QColor(243, 139, 168), 3))
        r.setZValue(960)
        self.scene.addItem(r)
        self._ki_marke.append(r)
        self.view.centerOn(QPointF(x * T + T / 2, y * T + T / 2))
