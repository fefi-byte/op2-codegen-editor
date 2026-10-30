"""Headless-Rauchtest der Editor-Oberflaeche.

Startet das echte ``EditorWindow`` (ohne Nutzerinteraktion), klickt sich per
Code durch die Kernbedienpfade und prueft die Zusicherungen, die beim
Uebersichtlichkeits-Umbau entstanden sind: Katalogsuche, Platzieren,
Trigger-Leerzustand, einklappbare Bedingung, Gruppen-Menue, zoomabhaengiges
Gitter/Beschriftungen, Statusleiste und Sprachdateien.

Aufruf:  python editor/tests/ui_smoke.py
Rueckgabe: Exit-Code 0 = alle Pruefungen gruen, 1 = mindestens eine rot.

Headless smoke test of the editor UI. Boots the real ``EditorWindow``, drives
the core interaction paths from code and verifies the guarantees introduced by
the clarity rework. Exit code 0 = all green, 1 = at least one failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDITOR_DIR = HERE.parent
if str(EDITOR_DIR) not in sys.path:
    sys.path.insert(0, str(EDITOR_DIR))

# Die Oberflaeche enthaelt Zeichen wie "▸"; eine cp1252-Konsole (oder eine
# umgeleitete Ausgabe) soll daran nicht scheitern.
# The UI contains characters like "▸"; a cp1252 console (or redirected output)
# must not choke on them.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import (QApplication,           # noqa: E402
                               QGraphicsLineItem)

_failures: list[str] = []


def check(name: str, ok, info: str = "") -> bool:
    """Eine Pruefung protokollieren. / Record one assertion."""
    ok = bool(ok)
    print(("OK  " if ok else "FAIL") + f"  {name}" + (f"  {info}" if info else ""))
    if not ok:
        _failures.append(name)
    return ok


def pump(app, times: int = 30) -> None:
    """Ereignisschleife kurz laufen lassen (kein echtes exec()).

    Spin the event loop briefly (no real exec())."""
    for _ in range(times):
        app.processEvents()


# --- Einzelpruefungen / individual checks -----------------------------------

def check_catalog_search(win, app) -> None:
    win._sidebar_tabs.setCurrentIndex(0)
    win.place_search.setText("")
    pump(app)
    total = win.list.count()
    win.place_search.setText("agri")
    pump(app)
    filtered = win.list.count()
    check("Katalogsuche filtert", 0 < filtered < total, f"({total} -> {filtered})")
    win.place_search.setText("zzz-kein-treffer")
    pump(app)
    check("Katalogsuche ohne Treffer leert die Liste", win.list.count() == 0)
    win.place_search.setText("")
    pump(app)
    check("Katalogsuche zuruecksetzen", win.list.count() == total)


def place_one_object(win, app):
    """Ein Gebaeude ueber den normalen Platzierpfad setzen.

    Place one building through the regular placement path."""
    win._sidebar_tabs.setCurrentIndex(0)
    win.list.setCurrentRow(0)
    win._activate_placement()
    pump(app)
    win.on_place(60, 60)
    pump(app)
    check("Objekt platziert", len(win.objects) == 1, f"({len(win.objects)})")
    return win.objects[0] if win.objects else None


def check_placement_persistence(win, app) -> None:
    """Platzieren darf nicht unsichtbar abschalten (Rechtsklick/Esc/Tabs)."""
    win._sidebar_tabs.setCurrentIndex(0)
    win.list.setCurrentRow(0)
    win._activate_placement()
    pump(app)

    before = len(win.objects)
    win.on_place(64, 64)
    pump(app)
    check("erstes Objekt platziert", len(win.objects) == before + 1)

    # Rechtsklick auf leere Flaeche darf das Platzieren NICHT beenden
    win.on_remove(90, 90)
    pump(app)
    check("Rechtsklick ins Leere lässt das Platzieren an", win._placement_active)
    win.on_place(66, 64)
    pump(app)
    check("zweites Objekt platziert", len(win.objects) == before + 2,
          f"({before} -> {len(win.objects)})")

    # Rechtsklick auf ein Objekt entfernt es -- und das Platzieren bleibt an
    win.on_remove(66, 64)
    pump(app)
    check("Rechtsklick auf ein Objekt entfernt es",
          len(win.objects) == before + 1, f"({len(win.objects)})")
    check("Platzieren nach dem Entfernen weiter aktiv", win._placement_active)
    win.on_place(68, 64)
    pump(app)
    check("drittes Objekt platziert", len(win.objects) == before + 2)

    # Schnelle Klickfolge: der zweite Klick kommt vom System als
    # MouseButtonDblClick -- er darf nicht verschluckt werden.
    # Fast click sequence: the system delivers the second click as
    # MouseButtonDblClick -- it must not be swallowed.
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    win.list.setCurrentRow(0)
    win._activate_placement()
    win.view.zoom_default()
    win.view.centerOn(64 * 32, 64 * 32)
    pump(app)
    vp = win.view.viewport()

    def send(etype, x, y):
        buttons = Qt.NoButton if etype == QEvent.MouseButtonRelease else Qt.LeftButton
        app.sendEvent(vp, QMouseEvent(etype, QPointF(x, y), vp.mapToGlobal(QPoint(x, y)),
                                      Qt.LeftButton, buttons, Qt.NoModifier))

    count = len(win.objects)
    send(QEvent.MouseButtonPress, 300, 300)
    send(QEvent.MouseButtonRelease, 300, 300)
    pump(app)
    first = len(win.objects)
    send(QEvent.MouseButtonDblClick, 306, 300)
    send(QEvent.MouseButtonRelease, 306, 300)
    pump(app)
    check("schneller Doppelklick platziert zweimal",
          first == count + 1 and len(win.objects) == count + 2,
          f"({count} -> {first} -> {len(win.objects)})")

    # Esc hebt die Auswahl sichtbar auf
    win._escape_pressed()
    pump(app)
    check("Esc beendet den Platziermodus", not win._placement_active)
    check("Esc hebt auch die Katalogauswahl auf", win.list.currentItem() is None)


def check_zoom_thresholds(win, app, obj) -> None:
    from app.mapview import MapView
    labels = [i for i in (obj.items if obj else []) if hasattr(i, "text")]
    if not check("Objekt hat eine Beschriftung", bool(labels)):
        return
    label = labels[0]

    win.view.zoom_fit()
    pump(app)
    px = win.view.tile_screen_px()
    check("Herausgezoomt: Beschriftung ausgeblendet", not label.isVisible(), f"Kachel={px:.1f}px")
    check("Herausgezoomt: Gitter unterdrueckt", px < MapView.GRID_MIN_TILE_PX, f"Kachel={px:.1f}px")

    win.view.zoom_default()
    pump(app)
    px = win.view.tile_screen_px()
    check("1:1 : Beschriftung sichtbar", label.isVisible(), f"Kachel={px:.1f}px")
    check("1:1 : Gitter erlaubt", px >= MapView.GRID_MIN_TILE_PX, f"Kachel={px:.1f}px")
    check("Beschriftung zoomfest", bool(label.flags() & label.GraphicsItemFlag.ItemIgnoresTransformations))
    check("Zoomanzeige gefuellt", "%" in win.zoom_label.text(), repr(win.zoom_label.text()))


def check_trigger_panel(win, app) -> None:
    from mission_model import TriggerDef
    from app.game_data import TRIGGER_CONDITIONS

    tp = win.trigger_panel
    win.edit_triggers()
    pump(app)

    # Leerzustand: keine Formularwand / empty state: no wall of fields
    check("Leerzustand: Hinweis sichtbar", tp.empty_hint.isVisible())
    check("Leerzustand: Namensfeld verborgen", not tp.form.isRowVisible(tp.name))
    check("Leerzustand: Bedingungskopf deaktiviert", not tp.cond_toggle.isEnabled())

    win.triggers.append(TriggerDef(name="SmokeTrigger"))
    tp.load()
    pump(app)
    check("Trigger ausgewaehlt", tp._idx == 0, f"(idx={tp._idx})")
    check("Auswahl: Hinweis verborgen", not tp.empty_hint.isVisible())
    check("Bedingungskopf nennt die Bedingung", ":" in tp.cond_toggle.text(),
          repr(tp.cond_toggle.text()))
    check("Bedingung standardmaessig eingeklappt", not tp._cond_section.isVisible())

    tp.cond_toggle.setChecked(True)
    pump(app)
    check("Bedingung klappt auf", tp._cond_section.isVisible())
    check("Zeit-Trigger: Marks sichtbar", tp.form.isRowVisible(tp.marks))
    check("Zeit-Trigger: Tech-ID verborgen", not tp.form.isRowVisible(tp.tech_id))

    # Auf eine Forschungsbedingung umschalten / switch to a research condition
    target = next((label for label, spec in TRIGGER_CONDITIONS.items()
                   if spec[0] == "research"), None)
    if check("Bedingung 'research' vorhanden", target is not None):
        tp.cond.setCurrentIndex(tp.cond.findData(target))
        pump(app)
        check("Forschungs-Trigger: Tech-ID sichtbar", tp.form.isRowVisible(tp.tech_id))
        check("Forschungs-Trigger: Marks verborgen", not tp.form.isRowVisible(tp.marks))

    tp.cond_toggle.setChecked(False)
    pump(app)
    check("Bedingung klappt wieder zu", not tp._cond_section.isVisible())


def check_groups_panel(win, app) -> None:
    win.edit_groups()
    pump(app)
    gp = win.groups_panel
    actions = gp.add_menu.actions()
    check("Gruppen-Menue hat vier Eintraege", len(actions) == 4,
          str([a.text() for a in actions]))
    before = len(gp.groups)
    if actions:
        actions[0].trigger()
        pump(app)
    check("Gruppe ueber Menue angelegt", len(gp.groups) == before + 1)


def unbrauchbarer_boden(win) -> int:
    """Kacheln, deren Boden der Generator nirgends setzen kann.

    Schnee hat von 222 Kacheln keine einzige setzbare, Lava gar keine. Steht
    so etwas auf der Karte, hat es kein Pinsel dorthin gemalt -- gemessen kam
    es ueber den Klippenmaler herein, der beim Malen mit Erde ein Band von 28
    Schneekacheln quer ueber eine Sandkarte legte.

    Tiles whose ground the generator cannot place anywhere. Snow has not one
    placeable tile out of 222, lava none at all. If such a tile sits on the map,
    no brush painted it there -- measured, it came in through the cliff painter,
    which laid a band of 28 snow tiles across a sand map while painting dirt.
    """
    from mapgen import model as _mm
    tm = _mm()
    schlecht = {f for f in range(len(tm.families)) if not tm.familie_nutzbar(f)}
    return sum(1 for y in range(win.map.height) for x in range(win.map.width)
               if int(tm.family_of[win.map.tile_mapping_index(x, y)]) in schlecht)


def check_mission_layout(win, app) -> None:
    """Neues Layout: Gliederung, Doppelklick-Editor, Abbrechen, Ziehen."""
    import copy
    from mission_model import TriggerDef
    win._bearbeiten_bestaetigen() if win._bearbeitung else None
    win._modus_setzen("mission")
    pump(app)
    check("Gliederung sichtbar", win._linke_seite.currentIndex() == 0
          and win.outline.isVisible())
    check("rechte Docks aus", not win.overview_dock.isVisible())

    # Neue Baugruppe ueber "Neu" -> Editor links, Abbrechen entfernt sie.
    n = len(win.building_groups)
    win._neu_anlegen("group_building")
    pump(app)
    check("Neu oeffnet den Editor links", win._linke_seite.currentIndex() == 1
          and win.groups_panel.isVisible())
    check("Editor zeigt nur das Formular", not win.groups_panel._listenteil.isVisible())
    win._bearbeiten_abbrechen()
    pump(app)
    check("Abbrechen verwirft die neue Gruppe", len(win.building_groups) == n,
          f"{n} -> {len(win.building_groups)}")
    check("zurueck in der Gliederung", win._linke_seite.currentIndex() == 0)

    # Trigger umbenennen, bestaetigen -> bleibt.
    win.triggers.append(TriggerDef(name="ZeitTest", condition="time", marks=10))
    win._refresh_overview()
    i = len(win.triggers) - 1
    win._bearbeiten_oeffnen("trigger", i)
    pump(app)
    win.trigger_panel.trigger_name.setText("ZeitTest2") \
        if hasattr(win.trigger_panel, "trigger_name") else None
    win.triggers[i].name = "ZeitTest2"
    win._bearbeiten_bestaetigen()
    pump(app)
    check("Bestaetigen behaelt die Aenderung", win.triggers[i].name == "ZeitTest2")
    check("Auswahl nach Bestaetigen", win._auswahl == ("trigger", i))

    # Gruppenbereich auf der Karte ziehen.
    win._neu_anlegen("group_building")
    win._bearbeiten_bestaetigen()
    g = win.building_groups[-1]
    x, y = g.rect_x, g.rect_y
    win._auswahl = ("group", g.name)
    win._letzter_klick = (None, 0.0)
    win._karte_klick(x + 2, y + 2)
    win._karte_ziehen(x + 5, y + 4)
    win._karte_loslassen(x + 5, y + 4)
    check("Gruppenbereich laesst sich verschieben", (g.rect_x, g.rect_y) == (x + 3, y + 2),
          f"({x},{y}) -> ({g.rect_x},{g.rect_y})")
    w0 = g.rect_width
    win._letzter_klick = (None, 0.0)
    win._karte_klick(g.rect_x + g.rect_width - 1, g.rect_y + g.rect_height - 1)
    win._karte_ziehen(g.rect_x + g.rect_width + 1, g.rect_y + g.rect_height - 1)
    win._karte_loslassen(0, 0)
    check("Ecke zieht den Bereich auf", g.rect_width == w0 + 2, f"{w0} -> {g.rect_width}")
    check("Auswahl gezeichnet", len(win._auswahl_items) > 0)

    # Kampfgruppe: Bereich heisst idle_*, muss genauso zieh- und sichtbar sein;
    # der Baubereich wird dabei ausgeblendet.
    win.list.setCurrentRow(0)
    check("verdeckter Katalog schaltet das Platzieren nicht scharf",
          not win._placement_active)
    win._neu_anlegen("group_fight")
    f = win.fight_groups[-1]
    pump(app)
    texte = [it.text() for it in win._overlay_items if hasattr(it, "text")]
    check("Kampfgruppen-Bereich auf der Karte", f.name in texte, str(texte))
    check("Baubereich beim Kampfgruppen-Bearbeiten ausgeblendet", g.name not in texte)
    win._bearbeiten_bestaetigen()
    win._auswahl = ("group", f.name)
    x, y = f.idle_x, f.idle_y
    win._letzter_klick = (None, 0.0)
    win._karte_klick(x + 2, y + 2)
    win._karte_ziehen(x + 4, y + 3)
    win._karte_loslassen(0, 0)
    check("Kampfgruppen-Bereich laesst sich verschieben",
          (f.idle_x, f.idle_y) == (x + 2, y + 1), f"({x},{y}) -> ({f.idle_x},{f.idle_y})")
    check("nach Bestaetigen nicht im Platziermodus", not win._placement_active)

    # Neue Gruppe liegt im sichtbaren Ausschnitt, nicht oben links.
    win.view.centerOn(60 * 32, 60 * 32)
    pump(app)
    win._neu_anlegen("group_mining")
    m = win.groups_panel.groups[win.groups_panel._idx]
    check("neue Gruppe im Bildausschnitt", (m.idle_x, m.idle_y) != (0, 0),
          f"({m.idle_x},{m.idle_y})")
    win._bearbeiten_abbrechen()

    # Einheit erzeugen: Kartenklick traegt die Einheit in die Liste ein, und
    # die X/Y-Felder ohne Pfeile zeigen ihren Wert (Stylesheet-Falle).
    from mission_model import TriggerAction
    from app.dialogs.action_cards import ActionCard
    tu = TriggerDef(name="CU", condition="time", marks=5)
    tu.actions.append(TriggerAction(kind="createUnit"))
    win.triggers.append(tu)
    win._refresh_overview()
    win._bearbeiten_oeffnen("trigger", len(win.triggers) - 1)
    pump(app)
    karte = win.trigger_panel.act_scroll.widget().findChildren(ActionCard)[0]
    karte.expand()
    pump(app)
    karte._form._request_pick("primary")
    win.on_place(33, 34)
    pump(app)
    check("Einheit per Kartenklick in der Liste", tu.actions[0].unit_list
          and tu.actions[0].unit_list[-1]["x"] == 33, str(tu.actions[0].unit_list))
    form = win.trigger_panel.act_scroll.widget().findChildren(ActionCard)[0]._form
    check("X-Feld zeigt seinen Wert", form.cu_x.lineEdit().width() > 10,
          f"{form.cu_x.lineEdit().width()} px")
    win._bearbeiten_bestaetigen()

    # Umbenennen einer Gruppe zieht die Verweise in Triggern mit; Abbrechen
    # nimmt beides zurueck.
    bg = win.building_groups[0]
    alt = bg.name
    tr_ = TriggerDef(name="Ref", condition="time", marks=5)
    tr_.actions.append(TriggerAction(kind="recordBuilding", group_name=alt))
    win.triggers.append(tr_)
    win._refresh_overview()
    win._bearbeiten_oeffnen("group", alt)
    pump(app)
    win.groups_panel.name.setText(alt + "_neu")
    win._bearbeiten_bestaetigen()
    check("Umbenennen zieht Aktions-Verweis mit",
          win.triggers[-1].actions[0].group_name == alt + "_neu",
          win.triggers[-1].actions[0].group_name)
    win._bearbeiten_oeffnen("group", alt + "_neu")
    pump(app)
    win.groups_panel.name.setText("Zwischen")
    win.groups_panel.umbenennen_nachziehen()
    win._bearbeiten_abbrechen()
    check("Abbrechen nimmt Umbenennung samt Verweisen zurueck",
          win.building_groups[0].name == alt + "_neu"
          and win.triggers[-1].actions[0].group_name == alt + "_neu",
          f"{win.building_groups[0].name} / {win.triggers[-1].actions[0].group_name}")
    ziel = TriggerDef(name="Ziel", condition="time", marks=5)
    tr_ = win.triggers[-1]
    win.triggers.append(ziel)
    tr_.actions.append(TriggerAction(kind="createTrigger", target="Ziel"))
    win._refresh_overview()
    win._bearbeiten_oeffnen("trigger", len(win.triggers) - 1)
    pump(app)
    win.trigger_panel.name.setText("Ziel2")
    win._bearbeiten_bestaetigen()
    check("Trigger umbenennen zieht createTrigger mit",
          tr_.actions[-1].target == "Ziel2", tr_.actions[-1].target)

    # Einheit umbenennen zieht unitCmd mit.
    o = win.objects[0]
    o.unit_name = "Held"
    tr_.actions.append(TriggerAction(kind="unitCmd", unit_ref="Held"))
    o.unit_name = "Held2"
    win._einheit_umbenannt(o, "Held")
    check("Einheit umbenennen zieht unitCmd mit",
          tr_.actions[-1].unit_ref == "Held2", tr_.actions[-1].unit_ref)

    # Namen loeschen: Rueckfrage. "Behalten" stellt ihn her, "Leeren" leert.
    o.unit_name = ""
    win._name_loeschen_fragen = lambda *_a: False
    win._einheit_umbenannt(o, "Held2")
    check("Name loeschen -> behalten", o.unit_name == "Held2", o.unit_name)
    o.unit_name = ""
    win._name_loeschen_fragen = lambda *_a: True
    win._einheit_umbenannt(o, "Held2")
    check("Name loeschen -> Verweise geleert", tr_.actions[-1].unit_ref == "",
          tr_.actions[-1].unit_ref)
    del win._name_loeschen_fragen

    # Wenn-Bloecke einklappbar; Zustand uebersteht den Neuaufbau der Liste,
    # und der Seitenbereich wird beim Trigger breiter und danach wieder schmal.
    wenn = TriggerAction(kind="if", then_actions=[TriggerAction(kind="message")])
    tw = TriggerDef(name="Wenn", condition="time", marks=5)
    tw.actions.append(wenn)
    win.triggers.append(tw)
    win._refresh_overview()
    b0 = win._mission_dock.width()
    win._bearbeiten_oeffnen("trigger", len(win.triggers) - 1)
    pump(app)
    check("Seitenbereich beim Trigger breiter", win._mission_dock.width() > b0,
          f"{b0} -> {win._mission_dock.width()}")
    win.trigger_panel.bloecke_setzen(True)
    win.trigger_panel.refresh_actions()
    pump(app)
    karten = [k for k in win.trigger_panel.act_scroll.widget().findChildren(ActionCard)
              if k.a.kind == "if"]
    check("Wenn-Block bleibt nach Neuaufbau zu",
          karten and not karten[0]._if_body.isVisible() and karten[0]._if_kurz.isVisible())
    win._bearbeiten_bestaetigen()
    pump(app)
    check("Seitenbereich danach wieder schmal", abs(win._mission_dock.width() - b0) < 30,
          f"{win._mission_dock.width()} vs {b0}")

    # Bereich ziehen landet in Rueckgaengig/Wiederholen.
    g = win.building_groups[0]
    win._auswahl = ("group", g.name)
    x, y = g.rect_x, g.rect_y
    win._letzter_klick = (None, 0.0)
    win._karte_klick(x + 1, y + 1)
    win._karte_ziehen(x + 4, y + 1)
    win._karte_loslassen(0, 0)
    check("Bereich verschoben", g.rect_x == x + 3)
    win.undo()
    check("Rueckgaengig setzt Bereich zurueck", (g.rect_x, g.rect_y) == (x, y),
          f"({g.rect_x},{g.rect_y})")
    win.redo()
    check("Wiederholen verschiebt erneut", g.rect_x == x + 3, str(g.rect_x))

    # SetRect einer Mining-Gruppe trifft idle_* (nicht rect_*).
    win._neu_anlegen("group_mining")
    mg = win.groups_panel.groups[win.groups_panel._idx]
    win._begin_rect_pick(mg)
    win._rect_drag_start(20, 21)
    win._rect_drag_finish(25, 24)
    check("SetRect Mining-Gruppe setzt idle_*",
          (mg.idle_x, mg.idle_y, mg.idle_width, mg.idle_height) == (20, 21, 6, 4)
          and not hasattr(mg, "rect_x"),
          f"{mg.idle_x},{mg.idle_y},{mg.idle_width},{mg.idle_height}")
    win._bearbeiten_abbrechen()
    check("Abbrechen entfernt Bereichs-Schritt",
          not any(op == "bereich" and e["name"] == mg.name for op, e in win._undo_stack))


def check_terrain(win, app) -> None:
    """Gelaende-Tab: Overlay am Tab, Stempeln, Zelltyp, Rueckgaengig."""
    tabs = win._sidebar_tabs
    terrain_idx = win._terrain_tab_index
    panel = win.terrain_panel
    win._unbrauchbar_vorher = unbrauchbarer_boden(win)

    tabs.setCurrentIndex(0)
    pump(app)
    check("Overlay aus, solange der Tab zu ist", win._terrain_overlay_item is None)

    tabs.setCurrentIndex(terrain_idx)
    pump(app, 60)
    check("Geländemodus aktiv", win._terrain_active and win.view.terrain_paint_enabled)
    check("Overlay automatisch sichtbar", win._terrain_overlay_item is not None)
    check("Pinselleiste vorhanden", len(panel._buttons) >= 8,
          f"({len(panel._buttons)} Pinsel)")
    check("Erdpinsel ist vorausgewählt", panel.selected_brush() == "mud")

    # Overlay-Schalter / overlay toggle
    panel.overlay_toggle.setChecked(False)
    pump(app)
    check("Schalter blendet das Overlay aus", win._terrain_overlay_item is None)
    check("Modusauswahl ist bei ausgeschaltetem Overlay gesperrt",
          not panel.overlay_mode.isEnabled())
    panel.overlay_toggle.setChecked(True)
    pump(app)
    check("Schalter blendet das Overlay wieder ein", win._terrain_overlay_item is not None)
    panel.overlay_mode.setCurrentIndex(1)      # nur Hindernisse
    pump(app, 40)
    check("Hindernis-Modus aktiv", win._overlay_mode == "blocked"
          and win._terrain_overlay_item is not None)
    panel.overlay_mode.setCurrentIndex(0)
    pump(app, 40)

    # Malen: Hochland setzen -> es muss ein Klippenband entstehen. Das ist der
    # Kern des Umbaus: nicht die Kachel wird gemalt, sondern die Absicht.
    # Painting: set highland -> a cliff band has to appear. That is the core of
    # the rework: the intent is painted, not the tile.
    from celltypes import (NORTH_CLIFFS, CLIFFS_HIGH_SIDE, CLIFFS_LOW_SIDE,
                           default_cell_type, speed_class)
    KLIPPE = (NORTH_CLIFFS, CLIFFS_HIGH_SIDE, CLIFFS_LOW_SIDE)

    def klippen_um(cx, cy, r=16):
        return sum(1 for yy in range(max(0, cy - r), min(win.map.height, cy + r))
                   for xx in range(max(0, cx - r), min(win.map.width, cx + r))
                   if win.map.cell_type(xx, yy) in KLIPPE)

    # Einen Hochland-Pinsel gibt es nicht mehr -- Hochland kommt aus einer
    # gezeichneten Klippe (siehe den Klippenabschnitt weiter unten). Der Weg
    # dahinter, Hoehenebene -> `synth_region` -> Klippenband, bleibt aber
    # erreichbar: er laeuft an, sobald ein Bodenpinsel ueber eine Flaeche mit
    # Hochland geht. Deshalb wird hier eine Stelle der Karte gesucht, an der
    # schon Hochland liegt, und mit Erde darueber gemalt -- eine Handlung, die
    # es wirklich gibt.
    #
    # There is no highland brush any more; highland comes from a drawn cliff.
    # The path behind it stays reachable whenever a ground brush passes over an
    # area carrying highland, so a spot that already has highland is looked up
    # and painted over with dirt -- an action that actually exists.
    ebenen0 = win._paint_layers()
    ziel = next(((xx, yy)
                 for yy in range(8, win.map.height - 8)
                 for xx in range(8, win.map.width - 8)
                 if ebenen0.hoehe[yy, xx]), None)
    check("Hochland auf der Karte gefunden", ziel is not None, str(ziel))
    x, y = ziel if ziel else (40, 40)
    before = win.map.tiles[win.map.tile_index(x, y)]
    # Mit einer Familie malen, die dort noch NICHT liegt -- sonst aendert der
    # Strich nichts und die Pruefungen darunter haetten nichts zu pruefen.
    # Paint with a family not already there, otherwise the stroke changes
    # nothing and the checks below would have nothing to check.
    _namen = ebenen0.tm.families
    _da = int(ebenen0.familie[y, x])
    panel.set_brush(next((n for n in ("mud", "roc", "san")
                          if n in _namen and _namen.index(n) != _da), "mud"))
    panel.set_brush_size(9)
    win._terrain_stamp(x, y)
    pump(app)
    # Genau hier lag der Fehler: das Klippenband bestand aus Schneekacheln.
    # This is exactly where the bug sat: the cliff band consisted of snow tiles.
    nachher_unbrauchbar = unbrauchbarer_boden(win)
    check("Malen an einer Klippe bringt keinen unbrauchbaren Boden mit",
          nachher_unbrauchbar <= getattr(win, "_unbrauchbar_vorher", 0),
          f"({getattr(win, '_unbrauchbar_vorher', 0)} -> {nachher_unbrauchbar})")
    check("Karte als geändert markiert", win.map_edited)
    check("bearbeitete Karte serialisierbar", win.terrain_map_bytes() is not None)

    # Tiefland malen nimmt das Hochland weg -- der Radierer fuer Klippen.
    # Painting lowland takes the highland away -- the eraser for cliffs.
    panel.set_brush("tief")
    win._terrain_stamp(x, y)
    pump(app)
    # Live nachfragen: `_paint_layers()` baut die Ebenen neu, sobald sich der
    # Karteninhalt geaendert hat -- ein festgehaltenes Objekt ist danach alt.
    # Ask live: `_paint_layers()` rebuilds the layers once the map content has
    # changed, so a held reference is stale afterwards.
    check("Tiefland malen senkt wieder ab", not win._paint_layers().hoehe[y, x])

    # Bodenpinsel wechselt das Biom
    panel.set_brush("san")
    win._terrain_stamp(70, 40)
    pump(app)
    from mapgen import model as _model
    tm = _model()
    fam = tm.family_of[win.map.tile_mapping_index(70, 40)]
    check("Sandpinsel setzt Sandboden",
          fam == tm.families.index("san"),
          f"({tm.families[fam] if 0 <= fam < len(tm.families) else fam})")

    # Pinselgroesse / brush size
    panel.set_brush("mud")
    panel.set_brush_size(3)
    cells = win._terrain_cells(60, 60)
    check("Pinsel 3 deckt einen runden Fleck ab", 4 <= len(cells) <= 9,
          f"({len(cells)})")

    # Rueckgaengig / undo
    for _ in range(6):
        win.undo()
        pump(app)
    check("Rückgängig stellt die Ausgangskachel wieder her",
          win.map.tiles[win.map.tile_index(x, y)] == before,
          f"(0x{win.map.tiles[win.map.tile_index(x, y)]:08X} vs 0x{before:08X})")

    # Grossflaechig malen: waehrend des Ziehens wird nur gesammelt, gerechnet
    # wird einmal beim Loslassen. Sonst haengt der Editor bei jedem
    # Mausschritt ueber eine Sekunde.
    # Painting large areas: while dragging only the layers are collected, the
    # tiles are computed once on release. Otherwise the editor would stall for
    # over a second on every mouse step.
    from mapgen import model as _m2
    tm2 = _m2()
    panel.set_brush("san")

    # Kleiner Pinsel: waehrend des Ziehens wird live gerechnet.
    # Der Strich muss auf einem FREMDEN Boden liegen, sonst aendert der Pinsel
    # die Ebenen gar nicht und `_terrain_stamp` steigt sofort wieder aus. Die
    # Pruefung lag vorher bei (40,70) -- dort ist schon Sand, und dass sich die
    # Kachel trotzdem aenderte, lag allein am Klippenmaler: der setzte dort
    # Schneekacheln, deren Klippen-Zelltypen beim naechsten Strich als Hochland
    # zurueckgelesen wurden. (100,100) ist reine Erde ohne Hochland.
    # Small brush: computed live while dragging. The stroke has to sit on a
    # FOREIGN ground, otherwise the brush does not change the layers at all and
    # `_terrain_stamp` bails out immediately. The check used to sit at (40,70)
    # -- that is sand already, and the tile only changed there because the cliff
    # painter placed snow tiles whose cliff cell types were read back as
    # highland on the next stroke. (100,100) is pure dirt without highland.
    panel.set_brush_size(9)
    vor = win.map.tiles[win.map.tile_index(100, 100)]
    win._terrain_strich_beginnen()
    win._terrain_stamp(100, 100)
    pump(app)
    check("kleiner Pinsel rechnet live",
          win.map.tiles[win.map.tile_index(100, 100)] != vor
          and win._strich_rechteck is None)
    zwischen = len(win.undo_stack) if hasattr(win, "undo_stack") else None
    win._terrain_stamp(104, 100)
    win._terrain_strich_abschliessen()
    pump(app, 30)
    fam = tm2.family_of[win.map.tile_mapping_index(100, 100)]
    check("live gemalte Flaeche traegt den Boden",
          fam == tm2.families.index("san"),
          f"{tm2.families[fam] if 0 <= fam < len(tm2.families) else fam}")

    # Grosser Pinsel: sammeln, erst beim Loslassen rechnen.
    # Large brush: collect, compute on release.
    panel.set_brush_size(41)
    check("grosser Pinsel einstellbar", panel.brush_size.value() == 41,
          str(panel.brush_size.value()))
    vor_strich = win.map.tiles[win.map.tile_index(60, 40)]
    win._terrain_strich_beginnen()
    for schritt in range(3):
        win._terrain_stamp(54 + schritt * 4, 40)
    pump(app)
    check("grosser Pinsel sammelt waehrend des Ziehens",
          win._strich_rechteck is not None
          and win.map.tiles[win.map.tile_index(60, 40)] == vor_strich)
    win._terrain_strich_abschliessen()
    pump(app, 40)
    fam = tm2.family_of[win.map.tile_mapping_index(60, 40)]
    check("nach dem Loslassen ist die Flaeche gemalt",
          fam == tm2.families.index("san"),
          f"{tm2.families[fam] if 0 <= fam < len(tm2.families) else fam}")
    check("Strich ist abgeschlossen", win._strich_rechteck is None)

    # Der Pinsel muss genau das malen, was er soll: die beruehrten Zellen
    # tragen den gewaehlten Boden, der Uebergang bildet sich aussen herum.
    # The brush must paint exactly what it should: the touched cells carry the
    # chosen ground, the transition forms around them.
    panel.set_brush("san")
    panel.set_brush_size(7)
    win._terrain_strich_beginnen()
    win._terrain_stamp(30, 90)
    win._terrain_strich_abschliessen()
    pump(app, 30)
    getroffen = [(x, y) for y in range(87, 94) for x in range(27, 34)
                 if (x - 30) ** 2 + (y - 90) ** 2 <= 9]
    isan = tm2.families.index("san")
    rein = sum(1 for x, y in getroffen
               if tm2.family_of[win.map.tile_mapping_index(x, y)] == isan)
    check("gemalte Zellen tragen zu 100 % den gewaehlten Boden",
          rein == len(getroffen), f"{rein}/{len(getroffen)}")

    # Klippenpinsel: Punkte klicken statt Flaeche malen, dann setzen.
    # Cliff brush: click points instead of painting an area, then place.
    panel.set_brush("klippe")
    check("Klippenfeld erscheint mit dem Pinsel", panel.klippen_box.isVisible())
    check("Setzen ist ohne Punkte gesperrt",
          not panel.btn_klippe_setzen.isEnabled())
    for punkt in ((40, 100), (40, 118)):
        win._terrain_strich_beginnen()
        win._terrain_stamp(*punkt)
        win._terrain_strich_abschliessen()
    pump(app)
    check("zwei Stuetzpunkte gesetzt", len(win._klippen_punkte) == 2,
          str(win._klippen_punkte))
    check("Ziehen legt keine weiteren Punkte an",
          len(win._klippen_punkte) == 2)
    check("Vorschau zeigt Punkte und Linie", len(win._klippen_items) >= 3,
          f"{len(win._klippen_items)} Elemente")
    check("Setzen ist jetzt frei", panel.btn_klippe_setzen.isEnabled())
    vorher = [win.map.tile_mapping_index(x, 109) for x in range(37, 44)]
    win._klippe_setzen()
    pump(app, 30)
    nachher = [win.map.tile_mapping_index(x, 109) for x in range(37, 44)]
    check("Klippe hat Kacheln veraendert", vorher != nachher)
    klippen = sum(1 for x in range(37, 44) for y in range(100, 118)
                  if win.map.cell_type(x, y) in KLIPPE)
    check("Klippenzellen entstanden", klippen > 20, f"{klippen} Zellen")
    check("Punkte sind nach dem Setzen leer", not win._klippen_punkte)
    # Die Stuetzpunkte sind weg, aber die offenen Enden bleiben als Anker
    # sichtbar -- daran zeichnet man die Klippe weiter.
    ebenen = win._paint_layers()
    check("offene Enden als Anker gemerkt", len(ebenen.klippen_enden) == 2,
          str(ebenen.klippen_enden))
    anker = ebenen.offene_enden()
    check("Anker auch fuer vorhandene Klippen der Karte",
          len(anker) > len(ebenen.klippen_enden), f"{len(anker)} Anker")
    check("nur noch Ankerringe in der Vorschau",
          len(win._klippen_items) == len(anker),
          f"{len(win._klippen_items)} Elemente, {len(anker)} Anker")
    # Danebengeklickt muss der naechste Strich auf ein Ende einrasten.
    win._terrain_strich_beginnen()
    win._terrain_stamp(43, 121)
    win._terrain_strich_abschliessen()
    pump(app)
    check("Klick daneben rastet auf das Klippenende ein",
          win._klippen_punkte == [(40, 118)], str(win._klippen_punkte))
    # Der gemerkte, kachelgenaue Endpunkt gewinnt gegen den abgeleiteten Ring.
    # Der sitzt auf einem 3x3-Raster und kann naeher am Klick liegen; wer nur
    # den naechsten von beiden nimmt, rastet bis zu zwei Kacheln hinter dem
    # Wandende ein, und die Fortsetzung setzt am falschen Block an. Genau so war
    # es gebaut -- `min` sortiert nach Abstand und ignoriert die Reihenfolge der
    # Quellen, obwohl der Kommentar den Vorrang behauptete.
    treffer = [ebenen.klippen_anker(40 + dx, 118 + dy)
               for dx, dy in ((0, 0), (2, 0), (0, 3), (3, 3), (-2, 2))]
    check("gemerktes Ende gewinnt gegen den abgeleiteten Ring",
          all(t in ebenen.klippen_enden for t in treffer), str(treffer))
    # Ein schon gesetzter Punkt zieht den naechsten Klick nicht auf sich
    # zurueck -- sonst waere jede kurze Linie ein Punkt.
    check("gesetzter Punkt rastet nicht erneut ein",
          ebenen.klippen_anker(41, 117, ausser=[(40, 118)]) != (40, 118),
          str(ebenen.klippen_anker(41, 117, ausser=[(40, 118)])))
    # Mitten auf eine Wand zielen. Einen dauerhaften Ring gibt es dort nicht --
    # das waeren auf cm04 1017 statt 51 -- aber der Klick rastet trotzdem ein,
    # und der Editor zeigt EINEN Ring unter dem Zeiger.
    # Ohne Stuetzpunkte -- mit einem gesetzten zeigt die Vorschau die
    # Baurichtung statt eines Rings.
    win._klippen_verwerfen()
    pump(app)
    mitte = ebenen.klippen_anker(37, 109)
    check("Klick neben der Wandmitte rastet auf die Wand ein",
          mitte is not None and win.map.cell_type(*mitte) in KLIPPE, str(mitte))
    frei = next(((x, y) for y in range(3, win.map.height - 3, 7)
                 for x in range(3, win.map.width - 3, 7)
                 if all(win.map.cell_type(px, py) not in KLIPPE
                        for px in range(x - 3, x + 4)
                        for py in range(y - 3, y + 4))), None)
    check("ohne Klippe in Reichweite rastet nichts ein",
          frei is not None and ebenen.klippen_anker(*frei) is None,
          f"{frei} -> {ebenen.klippen_anker(*frei) if frei else '-'}")
    win._update_terrain_preview(37, 109)
    check("Zielring erscheint neben der Wandmitte",
          getattr(win, "_terrain_preview_item", None) is not None)
    win._update_terrain_preview(*frei)
    check("kein Zielring im freien Gelaende",
          getattr(win, "_terrain_preview_item", None) is None)
    win._clear_terrain_preview()

    # Baurichtungen: ab dem zweiten Punkt rastet der Klick auf eine der
    # gemessenen Neigungen, und solange ein Punkt steht, zeigt eine Linie
    # dorthin, wohin gebaut wuerde.
    import math

    import mapgen as _mg
    win._klippen_verwerfen()
    win._terrain_strich_beginnen()
    win._terrain_stamp(40, 60)
    win._terrain_strich_abschliessen()
    pump(app)
    check("erster Punkt gesetzt", len(win._klippen_punkte) == 1,
          str(win._klippen_punkte))
    win._update_terrain_preview(53, 66)
    check("nach dem ersten Klick zeigt eine Linie die Baurichtung",
          isinstance(getattr(win, "_terrain_preview_item", None),
                     QGraphicsLineItem))
    win._terrain_strich_beginnen()
    win._terrain_stamp(53, 66)          # 13 rechts, 6 runter -> nicht erlaubt
    win._terrain_strich_abschliessen()
    pump(app)
    zweiter = win._klippen_punkte[-1]
    dx, dy = zweiter[0] - 40, zweiter[1] - 60
    teiler = math.gcd(abs(dx), abs(dy)) or 1
    check("der zweite Punkt rastet auf eine erlaubte Richtung",
          (dx // teiler, dy // teiler) in _mg.klippen_richtungen(),
          f"{win._klippen_punkte} -> dx={dx}, dy={dy}")
    win._klippen_verwerfen()
    win._clear_terrain_preview()
    pump(app)
    win._klippen_verwerfen()
    pump(app)
    win.undo()
    pump(app, 30)
    check("Klippe laesst sich rueckgaengig machen",
          [win.map.tile_mapping_index(x, 109) for x in range(37, 44)] == vorher)
    panel.set_brush("san")
    check("Klippenfeld verschwindet wieder", not panel.klippen_box.isVisible())

    # Pipette / eyedropper
    win._terrain_pick(70, 70)
    pump(app)
    check("Pipette übernimmt den Untergrund als Pinsel",
          panel.selected_brush() in ("mud", "roc", "san", "veg", "sno"),
          panel.selected_brush())

    tabs.setCurrentIndex(0)
    pump(app)
    check("Overlay verschwindet mit dem Tab", win._terrain_overlay_item is None)
    check("Geländemodus aus", not win.view.terrain_paint_enabled)

    # Regression: der Gelaendemodus darf das Platzieren nicht dauerhaft
    # abschalten (der Tab-Wechsel hatte die Auswahl geloescht).
    # Regression: terrain mode must not switch off placing for good.
    tabs.setCurrentIndex(0)
    win.list.setCurrentRow(0)
    win._activate_placement()
    pump(app)
    was_active = win._placement_active
    tabs.setCurrentIndex(terrain_idx)
    pump(app, 20)
    check("Geländemodus pausiert das Platzieren", not win._placement_active)
    tabs.setCurrentIndex(0)
    pump(app, 20)
    check("Platzieren ist nach dem Tab-Wechsel wieder aktiv",
          win._placement_active == was_active)
    before = len(win.objects)
    win.on_place(70, 40)
    pump(app)
    check("nach dem Geländemodus lässt sich wieder platzieren",
          len(win.objects) == before + 1, f"({before} -> {len(win.objects)})")


def check_terrain_strokes(win, app) -> None:
    """Mehrere Malstriche hintereinander -- ueber echte Maus-Ereignisse.

    Direkt `_terrain_stamp()` aufzurufen prueft den Zeichenweg NICHT: der
    Fehler steckte im Loslassen der Maustaste, das den Malmodus abschaltete.

    Several strokes in a row -- via real mouse events. Calling `_terrain_stamp`
    directly does NOT exercise the drawing path: the defect was in the mouse
    release, which switched painting off."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    win._modus_setzen("map")
    pump(app, 40)
    panel = win.terrain_panel
    panel.set_brush("mud")
    panel.set_brush_size(5)
    pump(app)
    if not check("Pinsel für den Maltest gewählt", panel.selected_brush() == "mud"):
        return
    win.view.zoom_default()
    win.view.centerOn(64 * 32, 64 * 32)
    pump(app, 10)

    vp = win.view.viewport()

    def send(etype, x, y):
        buttons = Qt.NoButton if etype == QEvent.MouseButtonRelease else Qt.LeftButton
        app.sendEvent(vp, QMouseEvent(etype, QPointF(x, y), vp.mapToGlobal(QPoint(x, y)),
                                      Qt.LeftButton, buttons, Qt.NoModifier))

    strokes = 0
    for i in range(3):
        before = len(win._undo_stack)
        send(QEvent.MouseButtonPress, 300 + i * 60, 300)
        pump(app, 3)
        send(QEvent.MouseMove, 308 + i * 60, 300)
        pump(app, 3)
        send(QEvent.MouseButtonRelease, 308 + i * 60, 300)
        pump(app, 3)
        if len(win._undo_stack) > before:
            strokes += 1
    check("drei Malstriche nacheinander wirken", strokes == 3, f"({strokes}/3)")
    check("Malmodus bleibt nach dem Loslassen aktiv", win.view.rect_select_enabled)
    check("Cursor bleibt das Malkreuz",
          win.view.cursor().shape() == Qt.CrossCursor)


def check_new_map(win, app) -> None:
    """Erzeugte Karte in den Editor uebernehmen (Dialogweg ohne Dialog)."""
    import mapgen

    # Panel statt Dialog: es haengt in der Seitenleiste und baut die Karte
    # direkt in der grossen Ansicht auf.
    win.new_generated_map()
    pump(app, 20)
    panel = win.newmap_panel
    if not check("Karten-Panel in der Seitenleiste", panel is not None):
        return
    check("Panel als Bereich eingehaengt", win._sidebar_tabs.indexOf(panel) >= 0)
    panel.size_combo.setCurrentIndex(0)          # 64 x 64 -- schnell
    panel.spawns.setValue(2)
    panel._regenerate()
    pump(app, 30)
    check("Panel meldet Kennzahlen", "%" in panel.stats.text(), repr(panel.stats.text()))
    generated = panel.generated()
    params = panel.params()
    if not check("Karte erzeugt", generated is not None):
        return
    check("Karte steht sofort in der Ansicht",
          win.map.width == params.width and win.map.height == params.height)
    panel.keep()
    pump(app, 20)
    check("Panel nach Übernehmen wieder geschlossen", win.newmap_panel is None)
    check("Karte im Editor uebernommen",
          win.map.width == params.width and win.map.height == params.height,
          f"{win.map.width}x{win.map.height}")
    check("Startpunkte gemerkt", len(win.spawn_points) == len(generated.spawns))
    check("Seed im Projekt hinterlegt",
          (win.mapgen_params or {}).get("seed") == params.seed)
    check("erzeugte Karte gilt als bearbeitet", win.map_edited)

    # Vulkane: Lavafelder gehoeren zur Karte, NICHT zu einem Trigger.
    # Volcanoes: lava fields belong to the map, NOT to a trigger.
    trigger_vorher = len(win.triggers)
    win.new_generated_map()
    pump(app, 20)
    panel2 = win.newmap_panel
    panel2.size_combo.setCurrentIndex(0)
    panel2.volcanoes.setValue(1)
    panel2._regenerate()
    pump(app, 30)
    panel2.keep()
    pump(app, 20)
    check("Vulkan gesetzt", len(win.volcano_points) == 1, str(len(win.volcano_points)))
    check("Lavafelder gefuellt", len(win.lava_fields) > 100, f"{len(win.lava_fields)} Kacheln")
    check("KEIN Ausbruch-Trigger angelegt", len(win.triggers) == trigger_vorher,
          f"{trigger_vorher} -> {len(win.triggers)}")
    from codegen import generate_levelmain
    cpp = generate_levelmain(win.build_mission())
    check("SetLavaPossible steht im erzeugten Code",
          cpp.count("SetLavaPossible") == len(win.lava_fields),
          f"{cpp.count('SetLavaPossible')} Aufrufe")
    check("kein SetEruption erzwungen", cpp.count("SetEruption") == 0)

    # Eigenes Menue: Malmodus laedt die Felder und schreibt sie zurueck
    win.edit_lava_fields()
    pump(app, 10)
    check("Lavafeld-Malmodus aktiv", win.view.lava_paint_enabled)
    check("Malmodus laedt die vorhandenen Felder",
          len(win._lava_paint_set) == len(win.lava_fields))
    vorher = len(win.lava_fields)
    # Freie Stelle suchen statt (20,20) zu raten: liegt dort schon Lava --
    # das haengt davon ab, wo der Vulkan gelandet ist --, waechst die Zahl
    # nicht und der Test schlaegt scheinbar zufaellig fehl.
    # Look for a free spot instead of guessing (20,20): if lava is already
    # there -- which depends on where the volcano landed -- the count does not
    # grow and the test fails seemingly at random.
    frei = next(((x, y) for y in range(4, win.map.height - 4)
                 for x in range(4, win.map.width - 4)
                 if (x, y) not in win._lava_paint_set), None)
    if not check("freie Stelle zum Malen gefunden", frei is not None):
        return
    win._lava_stamp(frei[0], frei[1], add=True)
    win._end_lava_paint()
    pump(app, 10)
    check("gemalte Kacheln landen in den Lavafeldern", len(win.lava_fields) > vorher,
          f"{vorher} -> {len(win.lava_fields)}")
    check("Malmodus beendet", not win.view.lava_paint_enabled)
    check("Karte laesst sich schreiben", win.terrain_map_bytes() is not None)
    check("Objekte der Mission ueberlebten den Kartenwechsel", isinstance(win.objects, list))


def check_terrain_save(win, app) -> None:
    """Bearbeitete Karte speichern, Mission neu oeffnen, Aenderung pruefen."""
    import shutil
    import tempfile

    folder = Path(tempfile.mkdtemp(prefix="op2_ui_smoke_"))
    try:
        win.mission_name = "Terrain Smoke"
        win._sidebar_tabs.setCurrentIndex(win._terrain_tab_index)
        pump(app, 40)
        panel = win.terrain_panel
        panel.set_brush("mud")
        panel.set_brush_size(5)
        pump(app)
        if not check("Pinsel für den Speichertest gewählt",
                     panel.selected_brush() == "mud"):
            return
        pump(app)
        x, y = 50, 50
        win._terrain_stamp(x, y)
        pump(app)
        edited = win.map.tiles[win.map.tile_index(x, y)]
        old_name = win.map.__class__ and win.map_name

        check("Mission gespeichert", win._save_to_folder(folder))
        pump(app, 40)
        check("Karte bekam einen eigenen Dateinamen", win.map_name != old_name,
              f"{old_name} -> {win.map_name}")
        check("bearbeitete Karte liegt im Missionsordner",
              (folder / win.map_name).is_file())
        cpp = (folder / "mission.cpp").read_text(encoding="utf-8", errors="replace")
        check("mission.cpp verweist auf die eigene Karte", win.map_name in cpp)

        win.open_project(str(folder / "mission.op2proj"))
        pump(app, 60)
        check("Geländeänderung überlebt Speichern + Öffnen",
              win.map.tiles[win.map.tile_index(x, y)] == edited,
              f"0x{win.map.tiles[win.map.tile_index(x, y)]:08X} vs 0x{edited:08X}")
    finally:
        win._sidebar_tabs.setCurrentIndex(0)
        pump(app)
        shutil.rmtree(folder, ignore_errors=True)


def check_status_and_overview(win, app) -> None:
    win._refresh_overview()
    pump(app)
    check("Validierungszaehler in der Statusleiste", win.validation_label.text() != "",
          repr(win.validation_label.text()))
    stats = win.overview_stats.text()
    check("Kennzahlenzeile gefuellt", stats.strip() != "", repr(stats))
    check("Uebersicht zeigt nur den Ablauf", win.overview.topLevelItemCount() == 1,
          f"({win.overview.topLevelItemCount()} Abschnitte)")
    check("Validierungsdock liegt unten",
          win.dockWidgetArea(win.validation_dock).name.lower().startswith("bottom"),
          win.dockWidgetArea(win.validation_dock).name)


def check_languages() -> None:
    """Beide Sprachdateien muessen denselben Schluesselvorrat haben.

    Both language files must carry the same set of keys."""
    from app import i18n
    missing = sorted(i18n.missing_keys())
    check("Keine fehlenden Uebersetzungsschluessel", not missing, str(missing[:8]))

    de = set(i18n._load_lang("de"))
    en = set(i18n._load_lang("en"))
    only_de, only_en = sorted(de - en), sorted(en - de)
    check("Sprachdateien deckungsgleich (nur de)", not only_de, str(only_de[:8]))
    check("Sprachdateien deckungsgleich (nur en)", not only_en, str(only_en[:8]))


# --- Ablauf / driver --------------------------------------------------------

def run_checks(win, app) -> None:
    pump(app, 40)
    check_catalog_search(win, app)
    obj = place_one_object(win, app)
    check_zoom_thresholds(win, app, obj)
    check_placement_persistence(win, app)
    check_trigger_panel(win, app)
    check_groups_panel(win, app)
    check_terrain(win, app)
    check_terrain_strokes(win, app)
    win._modus_setzen("mission")
    check_mission_layout(win, app)
    check_new_map(win, app)
    check_terrain_save(win, app)
    check_status_and_overview(win, app)
    check_languages()


def main() -> int:
    app = QApplication(sys.argv)
    from app.style import build_stylesheet
    from app.window import EditorWindow

    app.setStyleSheet(build_stylesheet())
    win = EditorWindow()
    win.resize(1600, 950)
    win.show()

    # Ein zuletzt geoeffnetes Projekt wuerde einen Dialog aufmachen -- der Test
    # laeuft bewusst auf einer frischen, leeren Mission.
    # A last-opened project would pop up a dialog -- the test deliberately runs
    # on a fresh, empty mission.
    win._maybe_reopen_last_mission = lambda *_a, **_k: None

    result = {"code": 1}

    def go():
        try:
            run_checks(win, app)
        except Exception:
            import traceback
            traceback.print_exc()
            _failures.append("Ausnahme waehrend des Tests / exception during test")
        finally:
            print("\n" + ("Alle Pruefungen gruen." if not _failures
                          else f"{len(_failures)} Pruefung(en) rot: {_failures}"))
            result["code"] = 0 if not _failures else 1
            app.quit()

    QTimer.singleShot(1500, go)
    app.exec()
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
