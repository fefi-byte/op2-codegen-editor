from __future__ import annotations

from .common import *


class _MenuMixin:
    def _build_menu(self):
        m = self.menuBar().addMenu(tr("window.menu_file"))
        a = QAction(tr("window.open_project"), self); a.triggered.connect(self.open_project); m.addAction(a)
        a = QAction(tr("window.save_project"), self); a.triggered.connect(self.save_project); m.addAction(a)
        a = QAction(tr("window.save_project_as"), self); a.triggered.connect(self.save_project_as); m.addAction(a)
        m.addSeparator()
        a = QAction(tr("window.choose_output"), self); a.triggered.connect(self.choose_output); m.addAction(a)
        m.addSeparator()
        a = QAction(tr("window.quit"), self); a.triggered.connect(self.close); m.addAction(a)

        edit_menu = self.menuBar().addMenu(tr("window.menu_edit"))
        undo_act = QAction(tr("window.undo"), self)
        undo_act.setShortcut("Ctrl+Z")
        undo_act.triggered.connect(self.undo)
        edit_menu.addAction(undo_act)
        redo_act = QAction(tr("window.redo"), self)
        redo_act.setShortcut("Ctrl+Y")
        redo_act.triggered.connect(self.redo)
        edit_menu.addAction(redo_act)

        view_menu = self.menuBar().addMenu(tr("window.menu_view"))
        # Kachelgitter-Umschalter; Anfangszustand aus config.ini.
        # Tile-grid toggle; initial state from config.ini.
        grid_on = appconfig.show_grid()
        self.view.set_grid(grid_on)
        self.grid_action = QAction(tr("window.show_grid"), self)
        self.grid_action.setCheckable(True)
        self.grid_action.setChecked(grid_on)
        self.grid_action.toggled.connect(self._toggle_grid)
        view_menu.addAction(self.grid_action)
        # Overlays: Trigger-Zonen und Gruppen-Bereiche auf der Karte.
        # Overlays: trigger zones and group areas on the map.
        self.trigger_overlay_action = QAction(tr("window.show_trigger_zones"), self)
        self.trigger_overlay_action.setCheckable(True)
        self.trigger_overlay_action.toggled.connect(self._toggle_trigger_overlay)
        view_menu.addAction(self.trigger_overlay_action)
        self.group_overlay_action = QAction(tr("window.show_group_areas"), self)
        self.group_overlay_action.setCheckable(True)
        self.group_overlay_action.toggled.connect(self._toggle_group_overlay)
        view_menu.addAction(self.group_overlay_action)
        view_menu.addSeparator()
        # Zoom-Voreinstellungen; das Mausrad zoomt weiterhin frei.
        # Zoom presets; the mouse wheel still free-zooms.
        zoom_def = QAction(tr("window.zoom_default"), self)
        zoom_def.triggered.connect(self.view.zoom_default)
        view_menu.addAction(zoom_def)
        zoom_fit = QAction(tr("window.zoom_fit"), self)
        zoom_fit.triggered.connect(self.view.zoom_fit)
        view_menu.addAction(zoom_fit)

        lang_menu = self.menuBar().addMenu(tr("window.menu_language"))
        configured = appconfig.language().strip().lower()
        auto_act = QAction(tr("window.lang_auto"), self)
        auto_act.setCheckable(True)
        auto_act.setChecked(configured in ("", "auto"))
        auto_act.triggered.connect(lambda _checked=False: self._set_language("auto"))
        lang_menu.addAction(auto_act)
        lang_menu.addSeparator()
        for code in i18n.available():
            act = QAction(tr(f"languages.{code}"), self)
            act.setCheckable(True)
            act.setChecked(configured == code)
            act.triggered.connect(lambda _checked=False, c=code: self._set_language(c))
            lang_menu.addAction(act)

        # "Mission"-Aktionen als obere Werkzeugleiste statt Menue.
        # "Mission" actions as a top toolbar instead of a menu.
        tb = QToolBar("Mission", self)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        for label, slot in [
            (tr("window.tb_setup"), self.edit_setup),
            (tr("window.tb_players"), self.edit_players),
            (tr("window.tb_conditions"), self.edit_conditions),
        ]:
            act = QAction(label, self)
            act.triggered.connect(slot)
            tb.addAction(act)
        tb.addSeparator()
        for label, slot in [
            (tr("window.tb_show_code"), self.show_code),
            (tr("window.tb_build"), self.do_build),
            (tr("window.tb_test_op2"), self._launch_op2),
        ]:
            act = QAction(label, self)
            act.triggered.connect(slot)
            tb.addAction(act)
        tb.addSeparator()
        act = QAction(tr("window.tb_clear"), self)
        act.triggered.connect(self.clear_objects)
        tb.addAction(act)

    def _set_language(self, code):
        appconfig.set_language(code)
        QMessageBox.information(self, tr("window.lang_changed_title"), tr("window.lang_changed_text"))

    def _toggle_grid(self, on):
        # Gitter ein-/ausblenden und Einstellung in config.ini sichern.
        # Show/hide the grid and persist the setting in config.ini.
        self.view.set_grid(on)
        appconfig.set_show_grid(on)
