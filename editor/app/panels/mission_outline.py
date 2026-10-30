"""Missionsgliederung: die linke Liste des neuen Layouts.

Statt sechs Reitern (Platzieren, Trigger, Gruppen, Objekte, Sieg &
Niederlage, Gelaende) steht links EINE durchsuchbare Gliederung der Mission:
Einstellungen, Spieler, Objekte, Gruppen (nach Ordnern), Ablauf (nach Zeit /
bei Ereignis) und Sieg & Niederlage. Ein Klick zeigt das Element auf der
Karte, ein Doppelklick oeffnet es zum Bearbeiten. Befunde der Validierung
stehen als Markierung direkt am Eintrag.

Mission outline -- the left list of the new layout: one searchable outline
instead of six tabs. Click shows on the map, double-click edits; validation
findings are marked on the entry itself.
"""
from __future__ import annotations

from collections import defaultdict

from ..common import *
from ..style import apply_role

# Farben der Markierungen / marker colours
_WARN = QColor(249, 226, 175)
_FEHLER = QColor(243, 139, 168)
_GEDIMMT = QColor(166, 173, 200)

_TYP_FARBE = {
    "BuildingGroupSpec": QColor(250, 179, 135),
    "ReinforceGroupSpec": QColor(137, 220, 235),
    "FightGroupSpec": QColor(243, 139, 168),
    "MiningGroupSpec": QColor(249, 226, 175),
}


def _punkt(farbe: QColor, groesse: int = 10, rund: bool = False) -> QIcon:
    pix = QPixmap(groesse, groesse)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(farbe))
    p.setPen(Qt.NoPen)
    if rund:
        p.drawEllipse(1, 1, groesse - 2, groesse - 2)
    else:
        p.drawRoundedRect(1, 1, groesse - 2, groesse - 2, 2, 2)
    p.end()
    return QIcon(pix)


class MissionOutline(QWidget):
    """Gliederung der Mission. Signale tragen (Art, Bezug):

    art: "setup" | "player" | "object" | "group" | "trigger" | "win" | "lose"
    bezug: Index (player/object/trigger/win/lose) oder Gruppenname
    """
    ausgewaehlt = Signal(str, object)
    bearbeiten = Signal(str, object)
    neu = Signal(str)

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._offen: dict[str, bool] = {"objekte": False, "spieler": False}
        self._laden = False

        self.suche = QLineEdit()
        self.suche.setPlaceholderText(tr("outline.search"))
        self.suche.setClearButtonEnabled(True)
        self.suche.textChanged.connect(self._filtern)

        self.neu_menue = QMenu(self)
        gruppen = self.neu_menue.addMenu(tr("outline.new_group"))
        for schluessel, art in (("groups.add_building", "group_building"),
                                ("groups.add_reinforce", "group_reinforce"),
                                ("groups.add_fight", "group_fight"),
                                ("groups.add_mining", "group_mining")):
            act = QAction(tr(schluessel), self)
            act.triggered.connect(lambda _=False, a=art: self.neu.emit(a))
            gruppen.addAction(act)
        for schluessel, art in (("outline.new_trigger", "trigger"),
                                ("outline.new_win", "win"),
                                ("outline.new_lose", "lose")):
            act = QAction(tr(schluessel), self)
            act.triggered.connect(lambda _=False, a=art: self.neu.emit(a))
            self.neu_menue.addAction(act)
        neu_knopf = QPushButton(tr("outline.new"))
        neu_knopf.setMenu(self.neu_menue)
        apply_role(neu_knopf, "primary")

        kopf = QHBoxLayout()
        kopf.setContentsMargins(0, 0, 0, 0)
        kopf.addWidget(self.suche, 1)
        kopf.addWidget(neu_knopf)

        self.baum = QTreeWidget()
        self.baum.setHeaderHidden(True)
        self.baum.setIndentation(14)
        self.baum.setUniformRowHeights(True)
        self.baum.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.baum.currentItemChanged.connect(self._geaendert)
        self.baum.itemDoubleClicked.connect(self._doppelklick)
        self.baum.itemExpanded.connect(lambda it: self._merken(it, True))
        self.baum.itemCollapsed.connect(lambda it: self._merken(it, False))

        hinweis = QLabel(tr("outline.hint"))
        hinweis.setProperty("secondary", "true")
        hinweis.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        lay.addLayout(kopf)
        lay.addWidget(self.baum, 1)
        lay.addWidget(hinweis)

    # ------------------------------------------------------------------
    def _merken(self, item, offen):
        schl = item.data(0, Qt.UserRole + 1)
        if schl:
            self._offen[schl] = offen

    def _abschnitt(self, schl: str, titel: str, anzahl: int | str) -> QTreeWidgetItem:
        it = QTreeWidgetItem([f"{titel}  ·  {anzahl}"])
        it.setData(0, Qt.UserRole + 1, schl)
        it.setFlags(Qt.ItemIsEnabled)
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        it.setForeground(0, QBrush(_GEDIMMT))
        self.baum.addTopLevelItem(it)
        it.setExpanded(self._offen.get(schl, True))
        return it

    def _zwischen(self, eltern, schl: str, titel: str) -> QTreeWidgetItem:
        it = QTreeWidgetItem([titel])
        it.setData(0, Qt.UserRole + 1, schl)
        it.setFlags(Qt.ItemIsEnabled)
        it.setForeground(0, QBrush(_GEDIMMT))
        eltern.addChild(it)
        it.setExpanded(self._offen.get(schl, True))
        return it

    def _eintrag(self, eltern, text, art, bezug, befunde=None, icon=None):
        it = QTreeWidgetItem([text])
        it.setData(0, Qt.UserRole, (art, bezug))
        if icon is not None:
            it.setIcon(0, icon)
        if befunde:
            fehler = any(s == "error" for s, _ in befunde)
            it.setForeground(0, QBrush(_FEHLER if fehler else _WARN))
            it.setToolTip(0, "\n".join(t for _s, t in befunde))
            it.setText(0, f"{text}   ⚠")
        eltern.addChild(it)
        return it

    # ------------------------------------------------------------------
    def aktualisieren(self) -> None:
        """Gliederung neu aufbauen; Auswahl und Aufklappzustand bleiben."""
        w = self._window
        alt = self.auswahl()
        self._laden = True
        self.baum.clear()
        try:
            from ..validation import validate_mission
            befunde_liste = validate_mission(w)
        except Exception as e:                       # Gliederung geht trotzdem
            print(f"Gliederung: Validierung fehlgeschlagen ({e})")
            befunde_liste = []
        befunde: dict = defaultdict(list)
        for schwere, text, ziel in befunde_liste:
            if ziel:
                befunde[tuple(ziel)].append((schwere, text))

        # Einstellungen
        top = QTreeWidgetItem([tr("outline.setup")])
        top.setData(0, Qt.UserRole, ("setup", None))
        self.baum.addTopLevelItem(top)

        # Spieler
        sp = self._abschnitt("spieler", tr("outline.players"), len(w.players))
        for i, p in enumerate(w.players):
            mensch = tr("outline.human") if getattr(p, "is_human", False) else tr("outline.ai")
            farbe = PLAYER_COLORS[i % len(PLAYER_COLORS)]
            self._eintrag(sp, f"P{i} · {mensch}", "player", i,
                          befunde.get(("player", i)), _punkt(farbe))

        # Objekte, je Spieler
        ob = self._abschnitt("objekte", tr("outline.objects"), len(w.objects))
        je_spieler: dict = defaultdict(list)
        for i, o in enumerate(w.objects):
            je_spieler[o.player if o.kind in ("structure", "vehicle") else -1].append(i)
        for sp_nr in sorted(je_spieler):
            titel = f"P{sp_nr}" if sp_nr >= 0 else tr("outline.neutral")
            zw = self._zwischen(ob, f"objekte_{sp_nr}",
                                f"{titel} · {len(je_spieler[sp_nr])}")
            farbe = PLAYER_COLORS[sp_nr % len(PLAYER_COLORS)] if sp_nr >= 0 else _GEDIMMT
            for i in je_spieler[sp_nr]:
                o = w.objects[i]
                name = o.unit_name or o.display
                self._eintrag(zw, f"{name}  ({o.tile_x},{o.tile_y})", "object", i,
                              befunde.get(("object", i)), _punkt(farbe, rund=True))

        # Gruppen, nach Ordnern
        alle = ([*w.building_groups] + [*w.reinforce_groups]
                + [*w.fight_groups] + [*w.mining_groups])
        gr = self._abschnitt("gruppen", tr("outline.groups"), len(alle))
        ordner: dict = defaultdict(list)
        for g in alle:
            ordner[getattr(g, "folder", "") or ""].append(g)
        for name in sorted(ordner, key=lambda n: (n == "", n.lower())):
            eltern = gr if not name else self._zwischen(gr, f"gordner_{name}", name)
            for g in ordner[name]:
                farbe = _TYP_FARBE.get(type(g).__name__, _GEDIMMT)
                self._eintrag(eltern, g.name, "group", g.name,
                              befunde.get(("group", g.name)), _punkt(farbe))

        # Ablauf: nach Zeit / bei Ereignis
        zeit = [(i, t) for i, t in enumerate(w.triggers) if t.condition == "time"]
        rest = [(i, t) for i, t in enumerate(w.triggers) if t.condition != "time"]
        ab = self._abschnitt("ablauf", tr("outline.flow"),
                             tr("outline.n_triggers", n=len(w.triggers)))
        if zeit:
            zw = self._zwischen(ab, "ablauf_zeit",
                                tr("outline.by_time", n=len(zeit)))

            def marke(t):
                try:
                    return int(t.marks)
                except (TypeError, ValueError):
                    return 10 ** 9
            for i, t in sorted(zeit, key=lambda it: marke(it[1])):
                wdh = "1×" if t.one_shot else "↻"
                self._eintrag(zw, f"M {t.marks}  {t.name}   {wdh}", "trigger", i,
                              befunde.get(("trigger", i)))
        if rest:
            zw = self._zwischen(ab, "ablauf_ereignis",
                                tr("outline.by_event", n=len(rest)))
            for i, t in rest:
                wdh = "1×" if t.one_shot else "↻"
                art = tr(f"trigger_conditions.{t.condition}")
                self._eintrag(zw, f"{t.name}  ·  {art}   {wdh}", "trigger", i,
                              befunde.get(("trigger", i)))

        # Sieg & Niederlage
        sn = self._abschnitt("sieg", tr("outline.conditions"),
                             f"{len(w.victories)} / {len(w.defeats)}")
        for i, c in enumerate(w.victories):
            self._eintrag(sn, tr("outline.win_prefix") + " " + condition_summary(c), "win", i,
                          befunde.get(("conditions", None)) if i == 0 else None)
        for i, c in enumerate(w.defeats):
            self._eintrag(sn, tr("outline.lose_prefix") + " " + condition_summary(c), "lose", i)

        self._laden = False
        if alt is not None:
            self.waehle(*alt, signal=False)
        self._filtern(self.suche.text())

    # ------------------------------------------------------------------
    def auswahl(self):
        it = self.baum.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else None

    def waehle(self, art: str, bezug, signal: bool = True) -> None:
        """Eintrag (art, bezug) markieren, z.B. nach einem Klick auf der Karte."""
        def suchen(it):
            if it.data(0, Qt.UserRole) == (art, bezug):
                return it
            for k in range(it.childCount()):
                r = suchen(it.child(k))
                if r is not None:
                    return r
            return None
        for k in range(self.baum.topLevelItemCount()):
            treffer = suchen(self.baum.topLevelItem(k))
            if treffer is not None:
                eltern = treffer.parent()
                while eltern is not None:
                    eltern.setExpanded(True)
                    eltern = eltern.parent()
                self.baum.blockSignals(not signal)
                self.baum.setCurrentItem(treffer)
                self.baum.blockSignals(False)
                self.baum.scrollToItem(treffer)
                return
        if not signal:
            self.baum.blockSignals(True)
            self.baum.setCurrentItem(None)
            self.baum.blockSignals(False)

    def _geaendert(self, aktuell, _vorher):
        if self._laden or aktuell is None:
            return
        daten = aktuell.data(0, Qt.UserRole)
        if daten:
            self.ausgewaehlt.emit(daten[0], daten[1])

    def _doppelklick(self, item, _spalte):
        daten = item.data(0, Qt.UserRole)
        if daten:
            self.bearbeiten.emit(daten[0], daten[1])

    def _filtern(self, text: str) -> None:
        text = (text or "").strip().lower()

        def zeigen(it) -> bool:
            eigen = not text or text in it.text(0).lower()
            kinder = False
            for k in range(it.childCount()):
                if zeigen(it.child(k)):
                    kinder = True
            sichtbar = eigen or kinder
            it.setHidden(not sichtbar)
            if text and kinder:
                it.setExpanded(True)
            return sichtbar
        for k in range(self.baum.topLevelItemCount()):
            zeigen(self.baum.topLevelItem(k))
