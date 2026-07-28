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
from PySide6.QtWidgets import QApplication             # noqa: E402

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
    win._sidebar_tabs.setCurrentIndex(1)
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
    win._sidebar_tabs.setCurrentIndex(2)
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


def check_terrain(win, app) -> None:
    """Gelaende-Tab: Overlay am Tab, Stempeln, Zelltyp, Rueckgaengig."""
    tabs = win._sidebar_tabs
    terrain_idx = win._terrain_tab_index
    panel = win.terrain_panel

    tabs.setCurrentIndex(0)
    pump(app)
    check("Overlay aus, solange der Tab zu ist", win._terrain_overlay_item is None)

    tabs.setCurrentIndex(terrain_idx)
    pump(app, 60)
    check("Geländemodus aktiv", win._terrain_active and win.view.terrain_paint_enabled)
    check("Overlay automatisch sichtbar", win._terrain_overlay_item is not None)
    check("Pinselleiste vorhanden", len(panel._buttons) >= 8,
          f"({len(panel._buttons)} Pinsel)")
    check("Hochland ist vorausgewählt", panel.selected_brush() == "hoch")

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

    x, y = 40, 40
    before = win.map.tiles[win.map.tile_index(x, y)]
    vorher = klippen_um(x, y)
    panel.set_brush("hoch")
    panel.set_brush_size(9)
    win._terrain_stamp(x, y)
    pump(app)
    check("Hochland malen erzeugt ein Klippenband",
          klippen_um(x, y) > vorher, f"({vorher} -> {klippen_um(x, y)})")
    check("Ebene merkt sich das Hochland", bool(win._layers.hoehe[y, x]))
    check("Karte als geändert markiert", win.map_edited)
    check("bearbeitete Karte serialisierbar", win.terrain_map_bytes() is not None)

    # Tiefland malen nimmt es wieder weg -- die Kante muss sich schliessen.
    # Painting lowland takes it away again; the edge has to close.
    panel.set_brush("tief")
    win._terrain_stamp(x, y)
    pump(app)
    check("Tiefland malen senkt wieder ab", not win._layers.hoehe[y, x])

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
    panel.set_brush("hoch")
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

    # Pipette / eyedropper
    win._terrain_pick(70, 70)
    pump(app)
    check("Pipette übernimmt den Untergrund als Pinsel",
          panel.selected_brush() in ("hoch", "mud", "roc", "san", "veg", "sno"),
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

    win._sidebar_tabs.setCurrentIndex(win._terrain_tab_index)
    pump(app, 40)
    panel = win.terrain_panel
    panel.set_brush("hoch")
    panel.set_brush_size(5)
    pump(app)
    if not check("Pinsel für den Maltest gewählt", panel.selected_brush() == "hoch"):
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
    win._lava_stamp(20, 20, add=True)
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
        panel.set_brush("hoch")
        panel.set_brush_size(5)
        pump(app)
        if not check("Pinsel für den Speichertest gewählt",
                     panel.selected_brush() == "hoch"):
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
