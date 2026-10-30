"""Neues Layout: Missionsgliederung links, Bearbeiten links, Karte als Werkzeug.

- Links steht die Gliederung (`MissionOutline`). Ein Klick zeigt das Element
  auf der Karte, ein Doppelklick oeffnet es links zum Bearbeiten -- mit
  "Bestaetigen" und "Abbrechen". Abbrechen stellt den Stand vom Oeffnen
  wieder her.
- Oben schaltet "Mission | Map Editor" zwischen Missionsarbeit und Gelaende.
- Auf der Karte waehlt ein Klick ein Objekt, eine Gruppe oder einen
  Trigger-Ort aus; ein Doppelklick bearbeitet es. Den Bereich einer
  Baugruppe verschiebt man durch Ziehen, an den Ecken zieht man ihn auf.

New layout: outline on the left, editing on the left with confirm/cancel,
mode switch Mission | Map Editor, and the map as the main tool (click
selects, double-click edits, drag moves or resizes a group area).
"""
from __future__ import annotations

import copy
import time

from .common import *
from PySide6.QtWidgets import QButtonGroup, QSizePolicy, QStackedWidget
from .panels.mission_outline import MissionOutline
from .style import apply_role

_AUSWAHL = QColor(137, 180, 250)       # blau / blue
_TRIGGER = QColor(243, 139, 168)       # rosa / pink

_LISTEN = ("building_groups", "reinforce_groups", "fight_groups",
           "mining_groups", "triggers", "victories", "defeats")


def bereich_felder(g):
    """Attributnamen (x, y, breite, hoehe) des Kartenbereichs einer Gruppe.

    Baugruppen haben rect_*, Kampf- und Mining-Gruppen idle_*,
    Verstaerkungsgruppen keinen Bereich (None)."""
    if g is None:
        return None
    if hasattr(g, "rect_x"):
        return ("rect_x", "rect_y", "rect_width", "rect_height")
    if hasattr(g, "idle_x"):
        return ("idle_x", "idle_y", "idle_width", "idle_height")
    return None


class _MissionMixin:
    # ------------------------------------------------------------------
    # Aufbau / construction

    def _baue_linke_seite(self, dock):
        """Die linke Seite: Gliederung (Seite 0) und Bearbeiten (Seite 1)."""
        self.outline = MissionOutline(self)
        self.outline.ausgewaehlt.connect(self._auswahl_aus_liste)
        self.outline.bearbeiten.connect(self._bearbeiten_oeffnen)
        self.outline.neu.connect(self._neu_anlegen)

        editor = QWidget()
        ev = QVBoxLayout(editor)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(0)
        kopf = QWidget()
        kl = QHBoxLayout(kopf)
        kl.setContentsMargins(10, 8, 10, 8)
        self._editor_pfad = QLabel("")
        self._editor_pfad.setProperty("secondary", "true")
        kl.addWidget(self._editor_pfad, 1)
        ev.addWidget(kopf)
        ev.addWidget(self._sidebar_tabs, 1)
        self._editor_fuss = QWidget()
        fl = QHBoxLayout(self._editor_fuss)
        fl.setContentsMargins(10, 8, 10, 10)
        self._btn_loeschen = QPushButton(tr("outline.delete"))
        self._btn_loeschen.setFlat(True)
        self._btn_loeschen.clicked.connect(self._bearbeiten_loeschen)
        self._btn_abbrechen = QPushButton(tr("outline.cancel"))
        self._btn_abbrechen.clicked.connect(self._bearbeiten_abbrechen)
        self._btn_bestaetigen = QPushButton(tr("outline.confirm"))
        apply_role(self._btn_bestaetigen, "primary")
        self._btn_bestaetigen.clicked.connect(self._bearbeiten_bestaetigen)
        fl.addWidget(self._btn_loeschen)
        fl.addStretch(1)
        fl.addWidget(self._btn_abbrechen)
        fl.addWidget(self._btn_bestaetigen)
        ev.addWidget(self._editor_fuss)

        self._linke_seite = QStackedWidget()
        self._linke_seite.addWidget(self.outline)
        self._linke_seite.addWidget(editor)
        dock.setWidget(self._linke_seite)
        # Kein Titel ueber der Seite: der Modus steht oben in der Leiste.
        dock.setTitleBarWidget(QWidget())
        self._sidebar_tabs.knoepfe_zeigen(False)
        dock.setMinimumWidth(340)

    def _baue_kopfleiste(self, tb):
        """Kopfleiste: Mission | Map Editor, Werkzeuge, rechts Bauen."""
        self._titel = QLabel("")
        f = self._titel.font()
        f.setBold(True)
        self._titel.setFont(f)
        tb.addWidget(self._titel)
        tb.addSeparator()

        self._modus_gruppe = QButtonGroup(self)
        self._modus_gruppe.setExclusive(True)
        for schl, modus in (("window.mode_mission", "mission"),
                            ("window.mode_map", "map")):
            b = QPushButton(tr(schl))
            b.setCheckable(True)
            apply_role(b, "navtab")
            b.setChecked(modus == "mission")
            b.clicked.connect(lambda _=False, m=modus: self._modus_setzen(m))
            self._modus_gruppe.addButton(b)
            tb.addWidget(b)
        tb.addSeparator()

        self._werkzeug_gruppe = QButtonGroup(self)
        self._werkzeug_gruppe.setExclusive(True)
        self._werkzeug_knoepfe = {}
        self._werkzeug_aktionen = []
        for schl, wz in (("window.tool_select", "auswahl"),
                         ("window.tool_place", "platzieren")):
            b = QPushButton(tr(schl))
            b.setCheckable(True)
            b.setChecked(wz == "auswahl")
            apply_role(b, "navtab")
            b.clicked.connect(lambda _=False, w=wz: self._werkzeug_setzen(w))
            self._werkzeug_gruppe.addButton(b)
            self._werkzeug_knoepfe[wz] = b
            self._werkzeug_aktionen.append(tb.addWidget(b))

        abstand = QWidget()
        abstand.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(abstand)
        for schl, slot in (("window.tb_show_code", self.show_code),
                           ("window.tb_test_op2", self._launch_op2)):
            b = QPushButton(tr(schl))
            b.clicked.connect(slot)
            tb.addWidget(b)
        bauen = QPushButton(tr("window.tb_build_short"))
        apply_role(bauen, "primary")
        bauen.clicked.connect(self.do_build)
        tb.addWidget(bauen)

    def _titel_aktualisieren(self):
        if getattr(self, "_titel", None) is None:
            return
        karte = self.map_name or ""
        self._titel.setText(f"{self.mission_name}   ·   {karte}")

    # ------------------------------------------------------------------
    # Modus und Werkzeug / mode and tool

    def _modus_setzen(self, modus: str):
        if self._bearbeitung is not None:
            self._bearbeiten_bestaetigen()
        self._modus = modus
        for b in self._modus_gruppe.buttons():
            b.setChecked((b.text() == tr("window.mode_map")) == (modus == "map"))
        for act in self._werkzeug_aktionen:
            act.setVisible(modus == "mission")
        if modus == "map":
            ziel = self.newmap_panel if self.newmap_panel is not None else self.terrain_panel
            self._sidebar_tabs.setCurrentWidget(ziel)
            self._editor_zeigen(tr("window.mode_map"), fuss=False)
        else:
            self._sidebar_tabs.setCurrentIndex(0)      # verlaesst den Gelaendemodus
            self._werkzeug_setzen("auswahl")
            self._linke_seite.setCurrentIndex(0)
        self._auswahl_zeichnen()

    def _werkzeug_setzen(self, werkzeug: str):
        self._werkzeug_knoepfe[werkzeug].setChecked(True)
        if werkzeug == "platzieren":
            if self._bearbeitung is not None:
                self._bearbeiten_bestaetigen()
            self._sidebar_tabs.setCurrentIndex(0)
            self._editor_zeigen(tr("window.tool_place"), fuss=True, nur_fertig=True)
        else:
            if self._placement_active:
                self._cancel_placement()
            if self._bearbeitung is None and self._modus == "mission":
                self._linke_seite.setCurrentIndex(0)

    def _editor_zeigen(self, pfad: str, fuss: bool, nur_fertig: bool = False):
        self._editor_pfad.setText(pfad)
        self._editor_fuss.setVisible(fuss)
        self._btn_loeschen.setVisible(not nur_fertig)
        self._btn_abbrechen.setVisible(not nur_fertig)
        self._btn_bestaetigen.setText(tr("outline.done") if nur_fertig
                                      else tr("outline.confirm"))
        self._linke_seite.setCurrentIndex(1)

    # ------------------------------------------------------------------
    # Bearbeiten / editing

    def _stand_sichern(self):
        return {name: copy.deepcopy(getattr(self, name)) for name in _LISTEN}

    def _panels_laden(self):
        self.groups_panel.load()
        self.trigger_panel.load()
        self.conditions_panel.load()

    def _bearbeiten_oeffnen(self, art: str, bezug, stand=None):
        if art == "setup":
            self.edit_setup()
            return
        if art == "player":
            self.edit_players()
            return
        if art == "object":
            if 0 <= bezug < len(self.objects):
                o = self.objects[bezug]
                self._edit_object_at(o.tile_x, o.tile_y)
                self._gliederung_auffrischen()
            return
        if self._bearbeitung is not None:
            self._bearbeiten_bestaetigen()
        if stand is None:
            stand = self._stand_sichern()
        if self._placement_active:
            self._cancel_placement()
        if art == "group":
            self.groups_panel.load()
            self._sidebar_tabs.setCurrentWidget(self.groups_panel)
            self.groups_panel.als_editor(True)
            self.groups_panel.select(bezug)
            pfad = f"{tr('outline.groups')}  ›  {bezug}"
        elif art == "trigger":
            self._sidebar_tabs.setCurrentWidget(self.trigger_panel)
            self.trigger_panel.als_editor(True)
            self.trigger_panel.select(bezug)
            name = self.triggers[bezug].name if 0 <= bezug < len(self.triggers) else ""
            pfad = f"{tr('outline.flow')}  ›  {name}"
        elif art in ("win", "lose"):
            self.conditions_panel.load()
            self._sidebar_tabs.setCurrentWidget(self.conditions_panel)
            self.conditions_panel.als_editor(True)
            self.conditions_panel._select(art, bezug)
            pfad = f"{tr('outline.conditions')}  ›  " + (
                tr("outline.win_prefix") if art == "win" else tr("outline.lose_prefix"))
        elif art in ("groups", "triggers", "conditions"):
            # Ganze Liste mit Formular -- aus dem Menue oder der Validierung.
            panel = {"groups": self.groups_panel, "triggers": self.trigger_panel,
                     "conditions": self.conditions_panel}[art]
            panel.load()
            panel.als_editor(False)
            self._sidebar_tabs.setCurrentWidget(panel)
            pfad = tr({"groups": "outline.groups", "triggers": "outline.flow",
                       "conditions": "outline.conditions"}[art])
        else:
            return
        self._bearbeitung = {"art": art, "bezug": bezug, "stand": stand}
        self._editor_zeigen(f"{tr('outline.mission')}  ›  {pfad}", fuss=True)
        self._btn_loeschen.setVisible(art in ("group", "trigger", "win", "lose"))
        if art in ("groups", "triggers", "conditions"):
            return
        self._auswahl = (art, bezug)
        self._auswahl_zeichnen()
        self._ort_zeigen(self._auswahl_ort(art, bezug))

    def _bearbeiten_ende(self):
        for p in (self.groups_panel, self.trigger_panel, self.conditions_panel):
            p.als_editor(False)
        self._bearbeitung = None
        # Erst die Gliederung zeigen, dann den Bereich wechseln -- sonst
        # wandert der Tastaturfokus in die Katalogliste, die dabei ihren
        # ersten Eintrag waehlt und das Platzieren scharf schaltet.
        self._linke_seite.setCurrentIndex(0)
        self._sidebar_tabs.setCurrentIndex(0)

    def _bearbeiten_bestaetigen(self):
        if self._placement_active:
            self._cancel_placement()
        b = self._bearbeitung
        if b is None:
            # "Fertig" beim Platzieren
            self._werkzeug_knoepfe["auswahl"].setChecked(True)
            self._linke_seite.setCurrentIndex(0)
            self._sidebar_tabs.setCurrentIndex(0)
            self._gliederung_auffrischen()
            return
        art, bezug = b["art"], b["bezug"]
        if art in ("groups", "triggers", "conditions"):
            self._bearbeiten_ende()
            self._gliederung_auffrischen()
            self._refresh_overlays()
            return
        if art == "group":
            # Der Name kann sich geaendert haben.
            idx = self.groups_panel._idx
            if 0 <= idx < len(self.groups_panel.groups):
                bezug = self.groups_panel.groups[idx].name
        self._bearbeiten_ende()
        self._gliederung_auffrischen()
        self._auswahl = (art, bezug)
        self.outline.waehle(art, bezug, signal=False)
        self._refresh_overlays()
        self._auswahl_zeichnen()

    def _bearbeiten_abbrechen(self):
        b = self._bearbeitung
        if b is None:
            self._bearbeiten_bestaetigen()
            return
        for name, wert in b["stand"].items():
            setattr(self, name, wert)
        self._bearbeiten_ende()
        self._panels_laden()
        self._gliederung_auffrischen()
        self._refresh_overlays()
        self._auswahl_zeichnen()
        self.statusBar().showMessage(tr("outline.status_cancelled"))

    def _bearbeiten_loeschen(self):
        b = self._bearbeitung
        if b is None:
            return
        if QMessageBox.question(self, tr("outline.delete_title"),
                                tr("outline.delete_text"),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        art = b["art"]
        if art == "group":
            self.groups_panel._remove()
        elif art == "trigger":
            self.trigger_panel._remove()
        elif art in ("win", "lose"):
            self.conditions_panel._remove()
        self._bearbeiten_ende()
        self._auswahl = None
        self._gliederung_auffrischen()
        self._refresh_overlays()
        self._auswahl_zeichnen()

    def _neu_anlegen(self, art: str):
        stand = self._stand_sichern()
        if art.startswith("group_"):
            {"group_building": self.groups_panel._add_building,
             "group_reinforce": self.groups_panel._add_reinforce,
             "group_fight": self.groups_panel._add_fight,
             "group_mining": self.groups_panel._add_mining}[art]()
            idx = self.groups_panel._idx
            if 0 <= idx < len(self.groups_panel.groups):
                g = self.groups_panel.groups[idx]
                f = bereich_felder(g)
                # Bauvorlage ohne Bereich: neuen Bereich dorthin, wo man schaut.
                if f and self.map is not None and art == "group_building":
                    mitte = self.view.mapToScene(self.view.viewport().rect().center())
                    setattr(g, f[0], max(0, int(mitte.x() // SCENE_TILE) - getattr(g, f[2]) // 2))
                    setattr(g, f[1], max(0, int(mitte.y() // SCENE_TILE) - getattr(g, f[3]) // 2))
                self._bearbeiten_oeffnen("group", self.groups_panel.groups[idx].name, stand)
        elif art == "trigger":
            self.trigger_panel._add()
            self._bearbeiten_oeffnen("trigger", len(self.triggers) - 1, stand)
        elif art in ("win", "lose"):
            self.conditions_panel.load()
            self.conditions_panel._add(art)
            liste = self.victories if art == "win" else self.defeats
            self._bearbeiten_oeffnen(art, len(liste) - 1, stand)

    def _gliederung_auffrischen(self):
        if getattr(self, "outline", None) is None:
            return
        # Waehrend des Bearbeitens ist die Gliederung verdeckt -- jeder
        # Tastendruck im Formular wuerde sie sonst neu aufbauen.
        if self._bearbeitung is not None:
            return
        self.outline.aktualisieren()
        self._titel_aktualisieren()

    # ------------------------------------------------------------------
    # Auswahl und Karte / selection and map

    def _auswahl_aus_liste(self, art: str, bezug):
        self._auswahl = (art, bezug)
        self._auswahl_zeichnen()
        self._ort_zeigen(self._auswahl_ort(art, bezug))

    def _ort_zeigen(self, ort):
        """Nur verschieben, wenn der Ort nicht schon zu sehen ist."""
        if ort is None:
            return
        p = QPointF(ort[0] * SCENE_TILE, ort[1] * SCENE_TILE)
        sichtbar = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        if not sichtbar.adjusted(64, 64, -64, -64).contains(p):
            self.view.centerOn(p)

    def _gruppe_nach_name(self, name):
        for liste in (self.building_groups, self.reinforce_groups,
                      self.fight_groups, self.mining_groups):
            for g in liste:
                if g.name == name:
                    return g
        return None

    def _alle_gruppen(self):
        return (list(self.building_groups) + list(self.reinforce_groups)
                + list(self.fight_groups) + list(self.mining_groups))

    def _gruppen_rechteck(self, g):
        f = bereich_felder(g)
        if f is None:
            return None
        x, y, w, h = (getattr(g, n) for n in f)
        return (x, y, max(1, w), max(1, h))

    def _bereich_setzen(self, g, x, y, w=None, h=None):
        f = bereich_felder(g)
        setattr(g, f[0], x)
        setattr(g, f[1], y)
        if w is not None:
            setattr(g, f[2], w)
            setattr(g, f[3], h)

    def _auswahl_ort(self, art, bezug):
        """Mittelpunkt (Kacheln) des Elements, oder None."""
        if art == "object" and 0 <= bezug < len(self.objects):
            o = self.objects[bezug]
            return (o.tile_x + 0.5, o.tile_y + 0.5)
        if art == "group":
            r = self._gruppen_rechteck(self._gruppe_nach_name(bezug))
            if r:
                return (r[0] + r[2] / 2, r[1] + r[3] / 2)
        if art == "trigger" and 0 <= bezug < len(self.triggers):
            t = self.triggers[bezug]
            if t.condition in ("rect", "point") or (t.x or t.y):
                return (t.x + max(1, t.width) / 2, t.y + max(1, t.height) / 2)
            for a in t.actions:
                if getattr(a, "x", 0) or getattr(a, "y", 0):
                    return (a.x + 0.5, a.y + 0.5)
        return None

    def _auswahl_weg(self):
        for it in self._auswahl_items:
            try:
                self.scene.removeItem(it)
            except RuntimeError:
                pass
        self._auswahl_items = []

    def _neu_item(self, item, z):
        item.setZValue(z)
        self.scene.addItem(item)
        self._auswahl_items.append(item)
        return item

    def _griff(self, tx, ty):
        """Eckkachel hervorheben: dort zieht man den Bereich auf."""
        T = SCENE_TILE
        g = QGraphicsRectItem(tx * T, ty * T, T, T)
        g.setBrush(QBrush(QColor(137, 180, 250, 150)))
        pen = QPen(QColor(205, 225, 255), 2)
        pen.setCosmetic(True)
        g.setPen(pen)
        return self._neu_item(g, 960)

    def _auswahl_zeichnen(self):
        self._auswahl_weg()
        # Die Gruppenbereiche haengen an der Auswahl (nur gleicher Typ).
        typ = None
        if self._auswahl and self._auswahl[0] == "group":
            typ = type(self._gruppe_nach_name(self._auswahl[1]))
        if typ is not getattr(self, "_overlay_typ", None):
            self._overlay_typ = typ
            self._refresh_overlays()
        if self.map is None or self._auswahl is None or self._modus != "mission":
            return
        art, bezug = self._auswahl
        T = SCENE_TILE
        if art == "group":
            r = self._gruppen_rechteck(self._gruppe_nach_name(bezug))
            if r is None:
                return
            x, y, w, h = r
            rect = QGraphicsRectItem(x * T, y * T, w * T, h * T)
            rect.setPen(QPen(_AUSWAHL, 3))
            rect.setBrush(QBrush(QColor(137, 180, 250, 50)))
            self._neu_item(rect, 950)
            for gx, gy in {(x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)}:
                self._griff(gx, gy)
        elif art == "object" and 0 <= bezug < len(self.objects):
            o = self.objects[bezug]
            fw, fh = o.footprint
            x0, y0 = o.tile_x - fw // 2, o.tile_y - fh // 2
            rect = QGraphicsRectItem(x0 * T - 3, y0 * T - 3, fw * T + 6, fh * T + 6)
            pen = QPen(_AUSWAHL, 3)
            pen.setCosmetic(True)
            rect.setPen(pen)
            self._neu_item(rect, 950)
            ring = QGraphicsEllipseItem(-11, -11, 22, 22)
            ring.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            ring.setPos((o.tile_x + 0.5) * T, (o.tile_y + 0.5) * T)
            ring.setPen(QPen(_AUSWAHL, 3))
            self._neu_item(ring, 1095)
        elif art == "trigger" and 0 <= bezug < len(self.triggers):
            # Karte abdunkeln, nur die Bezuege des Triggers bleiben hell.
            dunkel = QGraphicsRectItem(self.scene.sceneRect())
            dunkel.setBrush(QBrush(QColor(17, 17, 27, 140)))
            dunkel.setPen(QPen(Qt.NoPen))
            self._neu_item(dunkel, 880)
            t = self.triggers[bezug]
            if t.condition == "rect":
                rect = QGraphicsRectItem(t.x * T, t.y * T, max(1, t.width) * T,
                                         max(1, t.height) * T)
                rect.setPen(QPen(_TRIGGER, 3))
                rect.setBrush(QBrush(QColor(243, 139, 168, 50)))
                self._neu_item(rect, 950)
            for a in t.actions:
                ax, ay = getattr(a, "x", 0), getattr(a, "y", 0)
                ax2, ay2 = getattr(a, "x2", 0), getattr(a, "y2", 0)
                if (ax2 or ay2) and (ax or ay) and getattr(a, "kind", "") in (
                        "defendArea", "repairBuildings", "fightGroupCmd"):
                    x0, y0 = min(ax, ax2), min(ay, ay2)
                    rect = QGraphicsRectItem(x0 * T, y0 * T, (abs(ax2 - ax) + 1) * T,
                                             (abs(ay2 - ay) + 1) * T)
                    rect.setPen(QPen(_TRIGGER, 2, Qt.DashLine))
                    self._neu_item(rect, 950)
                elif ax or ay:
                    pin = QGraphicsEllipseItem(-9, -9, 18, 18)
                    pin.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
                    pin.setPos((ax + 0.5) * T, (ay + 0.5) * T)
                    pin.setBrush(QBrush(_TRIGGER))
                    pin.setPen(QPen(QColor(17, 17, 27), 2))
                    self._neu_item(pin, 1095)
            # Gruppen, auf die sich Aktionen beziehen
            namen = {getattr(a, "group_name", "") or "" for a in t.actions}
            namen.add(getattr(t, "group_name", "") or "")
            for name in namen - {""}:
                r = self._gruppen_rechteck(self._gruppe_nach_name(name))
                if r:
                    x, y, w, h = r
                    rect = QGraphicsRectItem(x * T, y * T, w * T, h * T)
                    rect.setPen(QPen(_TRIGGER, 2))
                    rect.setBrush(QBrush(QColor(243, 139, 168, 40)))
                    self._neu_item(rect, 950)

    def _gruppe_sichtbar(self, g):
        """Ist eine Gruppe gewaehlt oder in Bearbeitung, zeigt die Karte nur
        Bereiche desselben Typs -- der Baubereich stoert beim Setzen eines
        Kampfgruppen-Bereichs. / With a group selected, only areas of the
        same type are shown."""
        if self._modus != "mission":
            return True
        aktiv = None
        b = self._bearbeitung
        if b is not None and b["art"] == "group":
            idx = self.groups_panel._idx
            if 0 <= idx < len(self.groups_panel.groups):
                aktiv = self.groups_panel.groups[idx]
        elif self._auswahl and self._auswahl[0] == "group":
            aktiv = self._gruppe_nach_name(self._auswahl[1])
        return aktiv is None or type(g) is type(aktiv)

    def _treffer(self, tx, ty):
        """Was liegt auf der Kachel? -> (art, bezug) | None."""
        for i in range(len(self.objects) - 1, -1, -1):
            if self.objects[i].covers(tx, ty):
                return ("object", i)
        for g in self._alle_gruppen():
            if not self._gruppe_sichtbar(g):
                continue
            r = self._gruppen_rechteck(g)
            if r and r[0] <= tx < r[0] + r[2] and r[1] <= ty < r[1] + r[3]:
                return ("group", g.name)
        for i, t in enumerate(self.triggers):
            if t.condition == "rect" and t.x <= tx < t.x + max(1, t.width) \
                    and t.y <= ty < t.y + max(1, t.height):
                return ("trigger", i)
            if t.condition == "point" and (t.x, t.y) == (tx, ty):
                return ("trigger", i)
        return None

    def _karte_klick(self, tx, ty):
        """Linksklick mit dem Auswahlwerkzeug."""
        jetzt = time.monotonic()
        vorher, wann = self._letzter_klick
        self._letzter_klick = ((tx, ty), jetzt)
        doppelt = vorher == (tx, ty) and \
            jetzt - wann < QApplication.doubleClickInterval() / 1000.0
        # Ziehen eines gewaehlten Gruppenbereichs beginnen?
        if self._auswahl and self._auswahl[0] == "group":
            g = self._gruppe_nach_name(self._auswahl[1])
            r = self._gruppen_rechteck(g)
            if r:
                x, y, w, h = r
                ecken = {(x, y): (x + w - 1, y + h - 1), (x + w - 1, y): (x, y + h - 1),
                         (x, y + h - 1): (x + w - 1, y), (x + w - 1, y + h - 1): (x, y)}
                if (tx, ty) in ecken and not doppelt:
                    self._zug = {"art": "ecke", "g": g, "fest": ecken[(tx, ty)]}
                    return
                if x <= tx < x + w and y <= ty < y + h and not doppelt:
                    self._zug = {"art": "schieben", "g": g, "start": (tx, ty),
                                 "rect": (x, y)}
                    return
        treffer = self._treffer(tx, ty)
        if treffer is None:
            self._auswahl = None
            self.outline.waehle("", None, signal=False)
            self._auswahl_zeichnen()
            return
        if doppelt:
            self._bearbeiten_oeffnen(*treffer)
            return
        self._auswahl = treffer
        self.outline.waehle(*treffer, signal=False)
        self._auswahl_zeichnen()

    def _karte_ziehen(self, tx, ty):
        z = self._zug
        if z is None:
            return
        g = z["g"]
        if z["art"] == "schieben":
            dx, dy = tx - z["start"][0], ty - z["start"][1]
            self._bereich_setzen(g, max(0, z["rect"][0] + dx), max(0, z["rect"][1] + dy))
        else:
            fx, fy = z["fest"]
            tx, ty = max(0, tx), max(0, ty)
            self._bereich_setzen(g, min(fx, tx), min(fy, ty),
                                 abs(tx - fx) + 1, abs(ty - fy) + 1)
        self._refresh_overlays()
        self._auswahl_zeichnen()
        x, y, w, h = self._gruppen_rechteck(g)
        self.statusBar().showMessage(
            tr("outline.status_area", name=g.name, x=x, y=y, w=w, h=h))

    def _karte_loslassen(self, _tx, _ty):
        if self._zug is None:
            return
        self._zug = None
        if self._bearbeitung is not None and self._bearbeitung["art"] == "group":
            self.groups_panel._load(self.groups_panel._idx)
        self._refresh_overview()

    # ------------------------------------------------------------------
    # Ebenen auf der Karte / map layers

    def _baue_ebenenleiste(self):
        leiste = QFrame(self.view)
        leiste.setObjectName("ebenenleiste")
        leiste.setStyleSheet(
            "QFrame#ebenenleiste { background: rgba(17,17,27,225);"
            " border: 1px solid #313244; border-radius: 6px; }")
        lay = QHBoxLayout(leiste)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self._ebenen_knoepfe = {}
        for schl, art, an in (("window.layer_objects", "objekte", True),
                              ("window.layer_groups", "gruppen", True),
                              ("window.layer_triggers", "trigger", True)):
            b = QPushButton(tr(schl))
            b.setCheckable(True)
            b.setChecked(an)
            apply_role(b, "navtab")
            b.toggled.connect(lambda on, a=art: self._ebene_setzen(a, on))
            lay.addWidget(b)
            self._ebenen_knoepfe[art] = b
        leiste.adjustSize()
        self.view.unten_links = leiste
        self.view.ecken_platzieren()
        # Gruppen und Trigger-Orte von Anfang an zeigen.
        self.group_overlay_action.setChecked(True)
        self.trigger_overlay_action.setChecked(True)
        self.group_overlay_action.toggled.connect(
            lambda on: self._ebenen_knoepfe["gruppen"].setChecked(on))
        self.trigger_overlay_action.toggled.connect(
            lambda on: self._ebenen_knoepfe["trigger"].setChecked(on))

    def _ebene_setzen(self, art, an):
        if art == "gruppen":
            self.group_overlay_action.setChecked(an)
        elif art == "trigger":
            self.trigger_overlay_action.setChecked(an)
        else:
            self._objekte_sichtbar = an
            for o in self.objects:
                for it in o.items:
                    it.setVisible(an)
            self._update_label_zoom()
