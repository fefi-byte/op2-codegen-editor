from __future__ import annotations

import subprocess

import numpy as np

from .common import *
from .placed_object import PlacedObject
from .build_worker import BuildWorker
from .cpp_highlight import CppHighlighter
from . import mission_project
from .dialogs.output_dialog import OutputDialog
from .dialogs.players import PlayersDialog
from .dialogs.setup import MissionSetupDialog


class _BuildMixin:
    def _read_map_bytes(self, name: str) -> bytes:
        """Karte laden -- bearbeitete Karten liegen im Missionsordner, alle
        anderen im Spielordner.

        Load a map -- edited maps live in the mission folder, all others in
        the game folder."""
        for folder in (self._map_search_folder, self.mission_folder):
            if folder:
                cand = Path(folder) / name
                if cand.is_file():
                    return cand.read_bytes()
        return self.res.read_file(name)

    def load_map(self, name):
        try:
            self.map = Op2Map(self._read_map_bytes(name))
            arr = np.ascontiguousarray(render_array(self.map, self.res))
            qimg = QImage(arr.data, arr.shape[1], arr.shape[0], arr.shape[1] * 3, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg.copy())
        except Exception as e:
            QMessageBox.critical(self, tr("window.error_title"), f"{e}\n\n{traceback.format_exc()}")
            return
        self.map_name = name
        self.objects.clear()
        self.building_groups.clear()
        self.reinforce_groups.clear()
        self._next_object_id = 1
        self.scene.clear()
        self.view.rect_select_enabled = False
        self._placement_active = False
        self._placement_preview_items = []
        self._rect_pick_group = None
        self._rect_pick_start = None
        self._rect_pick_item = None
        self._action_pick = None
        self._action_pick_start = None
        self._action_preview_items = []
        self._planned_items = []
        self._lava_paint_items = []
        self._lava_paint_set: set = set()
        self._lava_brush_size = 3
        self._lava_brush_cursor_item = None
        # Handle merken: der Gelaende-Editor zeichnet einzelne Kacheln direkt
        # in dieses Pixmap nach, statt die ganze Karte neu zu rendern.
        # Keep the handle: the terrain editor repaints individual tiles into
        # this pixmap instead of re-rendering the whole map.
        self._map_pixmap = pix
        self._map_item = self.scene.addPixmap(pix)
        self.scene.setSceneRect(QRectF(pix.rect()))
        self._reset_terrain_state()
        self.view.zoom_fit()
        self.statusBar().showMessage(tr("window.status_map_loaded", name=name, w=self.map.width, h=self.map.height))
        self._refresh_overview()

    def choose_output(self):
        dlg = OutputDialog(self, self.output_dir, self.dll_name)
        if dlg.exec() == QDialog.Accepted:
            name = dlg.name_edit.text().strip() or DEFAULT_DLL_NAME
            if not name.lower().endswith(".dll"):
                name += ".dll"
            self.output_dir = dlg.dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
            self.dll_name = name
            appconfig.set_output(self.output_dir, self.dll_name)
            self.statusBar().showMessage(tr("window.status_output_set", path=Path(self.output_dir) / self.dll_name))

    def edit_setup(self):
        dlg = MissionSetupDialog(
            self, self.mission_name, self.mission_type,
            self.tech_tree, self.diff_setup, self.variables,
            map_names=self.res.names(), current_map=self.map_name or "",
            briefing=self.briefing, campaign=self.campaign,
            campaign_mission=self.campaign_mission,
            max_tech_level=self.max_tech_level,
            custom_code=self.custom_code,
        )
        if dlg.exec() == QDialog.Accepted:
            self.mission_name = dlg.mission_name
            self.briefing = dlg.briefing
            self.custom_code = dlg.custom_code
            self.campaign = dlg.campaign
            self.campaign_mission = dlg.campaign_mission
            self.max_tech_level = dlg.max_tech_level
            if self.campaign:
                # Engine-Namensschema: e## (Eden) / p## (Plymouth) -- der
                # DLL-Name entscheidet, zu welcher Kampagne die Mission
                # gehoert und welche Mission danach kommt.
                # Engine naming scheme: e## (Eden) / p## (Plymouth) -- the
                # DLL name decides which campaign the mission belongs to
                # and which mission follows.
                prefix = "e" if self.campaign == "eden" else "p"
                self.dll_name = f"{prefix}{self.campaign_mission:02d}.dll"
                appconfig.set_output(self.output_dir, self.dll_name)
                self.statusBar().showMessage(
                    tr("window.status_campaign_dll", name=self.dll_name))
            self.mission_type = dlg.mission_type
            self.tech_tree = dlg.tech_tree
            self.diff_setup = dlg.diff_setup
            self.variables = dlg.variables
            if dlg.map_name and dlg.map_name != self.map_name:
                self.load_map(dlg.map_name)
            self.setWindowTitle(f"OP2 Mission Editor — {self.mission_name}"
                                + (f"  [{self.mission_folder.name}]" if self.mission_folder else ""))

    def edit_custom_actions(self):
        from .dialogs.custom_actions import CustomActionsDialog
        dlg = CustomActionsDialog(self, self.custom_actions)
        if dlg.exec() == QDialog.Accepted:
            self.custom_actions = dlg.defs
            # Aktionsformulare/Menues neu aufbauen (Kontext hat sich geaendert)
            # Rebuild action forms/menus (the context changed)
            self.trigger_panel.refresh()
            self.statusBar().showMessage(
                tr("window.status_custom_actions", n=len(self.custom_actions)))

    def edit_players(self):
        dlg = PlayersDialog(self, self.players, diff_setup=self.diff_setup)
        if dlg.exec() == QDialog.Accepted:
            self.players = dlg.players
            self._refresh_player_range()
            self._refresh_overview()
            self.statusBar().showMessage(tr("window.status_players_configured", n=len(self.players)))

    def edit_triggers(self):
        """Trigger links bearbeiten (auch Rueckkehr nach einem Karten-Pick)."""
        idx, aidx = self._pending_trigger_index, self._pending_action_index
        self._pending_trigger_index = 0
        self._pending_action_index = -1
        if not self.triggers:
            self._bearbeiten_oeffnen("triggers", None)
            return
        idx = max(0, min(idx, len(self.triggers) - 1))
        b = self._bearbeitung
        if b is None or b["art"] not in ("trigger", "triggers"):
            self._bearbeiten_oeffnen("trigger", idx)
        else:
            self._sidebar_tabs.setCurrentWidget(self.trigger_panel)
            self._linke_seite.setCurrentIndex(1)
        self.trigger_panel.select(idx, aidx)

    def edit_conditions(self):
        """Sieg & Niederlage links bearbeiten (ganze Liste)."""
        b = self._bearbeitung
        if b is not None and b["art"] in ("win", "lose", "conditions"):
            self._sidebar_tabs.setCurrentWidget(self.conditions_panel)
            self._linke_seite.setCurrentIndex(1)
            return
        self._bearbeiten_oeffnen("conditions", None)

    def edit_groups(self, name=None):
        if name:
            self._bearbeiten_oeffnen("group", name)
        else:
            self._bearbeiten_oeffnen("groups", None)

    def build_mission(self) -> Mission:
        # Bearbeitetes Gelaende bekommt einen eigenen Kartennamen -- muss VOR
        # der Codeerzeugung feststehen, sonst verweist die DLL auf die
        # Originalkarte.
        # Edited terrain gets its own map name -- must be settled BEFORE code
        # generation, otherwise the DLL points at the original map.
        self._ensure_custom_map_name()
        units, beacons, walls = [], [], []
        for o in self.objects:
            if o.kind in ("structure", "vehicle"):
                units.append(UnitSpec(
                    o.map_id, x=o.tile_x, y=o.tile_y, player=o.player,
                    cargo=o.params.get("weapon", "mapNone"),
                    truck_cargo=o.params.get("truck_cargo"),
                    truck_amount=o.params.get("truck_amount", 1000),
                    convec_kit=o.params.get("convec_kit"),
                    uid=o.uid,
                    unit_name=o.unit_name,
                ))
            elif o.kind == "beacon":
                beacons.append(BeaconSpec(
                    o.map_id, x=o.tile_x, y=o.tile_y,
                    ore_type=o.params.get("ore_type", -1),
                    yield_bars=o.params.get("yield_bars", -1),
                ))
            elif o.kind == "wall":
                walls.append(WallTubeSpec(o.map_id, x=o.tile_x, y=o.tile_y))
        return Mission(
            name=self.mission_name, map=self.map_name,
            lava_fields=[list(t) for t in getattr(self, "lava_fields", [])],
            type=self.mission_type, tech_tree=self.tech_tree,
            num_players=len(self.players),
            # World-/Wraparound-Karten sind 512 Tiles breit; dort gilt der
            # Engine-Offset -1/-1 statt +31/-1 (Codegen definiert MkXY um).
            # World/wraparound maps are 512 tiles wide; there the engine
            # offset is -1/-1 instead of +31/-1 (codegen redefines MkXY).
            world_map=bool(getattr(getattr(self, "map", None), "width", 0) >= 512),
            players=[PlayerSpec(**asdict(p)) for p in self.players],
            units=units, beacons=beacons, walls_tubes=walls,
            building_groups=[BuildingGroupSpec(**asdict(g)) for g in self.building_groups],
            reinforce_groups=[
                ReinforceGroupSpec(
                    name=g.name,
                    player=g.player,
                    unit_ids=list(g.unit_ids),
                    targets=[ReinforceTargetSpec(**asdict(t)) for t in g.targets],
                )
                for g in self.reinforce_groups
            ],
            fight_groups=[FightGroupSpec(**asdict(g)) for g in self.fight_groups],
            mining_groups=[MiningGroupSpec(**asdict(g)) for g in self.mining_groups],
            triggers=list(self.triggers),
            start_message=StartMessage(tr("window.default_start_message")),
            briefing=self.briefing,
            custom_code=self.custom_code,
            custom_actions=[dict(d) for d in self.custom_actions],
            campaign=self.campaign,
            campaign_mission=self.campaign_mission,
            max_tech_level=self.max_tech_level,
            victories=list(self.victories), defeats=list(self.defeats),
            difficulty=DifficultySetup(
                hard=self.diff_setup.hard,
                normal=self.diff_setup.normal,
                easy=self.diff_setup.easy,
            ),
            variables=list(self.variables),
        )

    def show_code(self):
        self._editor_uebernehmen()
        if self.map is None:
            return
        try:
            code = generate_levelmain(self.build_mission())
        except Exception:
            code = traceback.format_exc()
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("window.code_dialog_title"))
        dlg.resize(760, 640)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(code)
        text.setFont(QFont("Consolas", 10))
        text.setLineWrapMode(QPlainTextEdit.NoWrap)
        text.setStyleSheet("QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; }")
        dlg._highlighter = CppHighlighter(text.document())
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay = QVBoxLayout(dlg)
        lay.addWidget(text)
        lay.addWidget(btns)
        dlg.exec()

    def do_build(self):
        self._editor_uebernehmen()
        if self.map is None:
            return
        if self.mission_folder is None or not self.mission_folder.is_dir():
            self.save_project_as()
        if self.mission_folder is None or not self.mission_folder.is_dir():
            return
        if not self._luecken_bestaetigt():
            return
        self._progress = QProgressDialog(tr("window.build_progress"), None, 0, 0, self)
        self._progress.setWindowTitle("Build")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setCancelButton(None)
        self._progress.show()
        self.statusBar().showMessage(tr("window.status_build_running"))
        self._worker = BuildWorker(
            self.build_mission(), self.mission_folder, self._mission_write_kwargs()
        )
        self._worker.ok.connect(self._build_ok)
        self._worker.err.connect(self._build_err)
        self._worker.start()

    def _luecken_bestaetigt(self) -> bool:
        """Vor dem Bauen: hat der Generator Luecken hinterlassen?

        Was der Codegenerator nicht umsetzen kann (Gruppe nicht angelegt,
        unbekannte Aktion, ...), wird zu einem `// TODO(editor)`-Kommentar im
        C++ -- die DLL baut trotzdem, und im Spiel passiert an der Stelle
        einfach nichts. Deshalb hier anhalten und die Stellen zeigen; bauen
        nur, wenn man das ausdruecklich will.

        Before building: stop if the generator left gaps (`// TODO(editor)`),
        show them, and build only on explicit request.
        """
        try:
            cpp = generate_levelmain(self.build_mission())
        except Exception:
            return True        # der Build selbst meldet den Fehler ausfuehrlich
        luecken = [z.strip() for z in cpp.splitlines() if "TODO(editor)" in z]
        if not luecken:
            return True
        liste = "\n".join(f"- {z[:140]}" for z in luecken[:15])
        if len(luecken) > 15:
            liste += "\n- ..."
        box = QMessageBox(QMessageBox.Warning, tr("window.build_gaps_title"),
                          tr("window.build_gaps_text", n=len(luecken), liste=liste),
                          parent=self)
        trotzdem = box.addButton(tr("window.build_gaps_anyway"), QMessageBox.DestructiveRole)
        abbrechen = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(abbrechen)
        box.exec()
        return box.clickedButton() is trotzdem

    def _build_ok(self, dll):
        self._progress.close()
        targets = []
        for folder in (Path(self.output_dir), CONTENT_ROOT):
            t = folder / self.dll_name
            if t not in targets:
                targets.append(t)
        try:
            for t in targets:
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dll, t)
        except Exception as e:
            QMessageBox.warning(self, tr("window.copy_failed_title"),
                                tr("window.copy_failed_text", target=t, e=e))
            self.statusBar().showMessage(tr("window.status_copy_failed", e=e))
            return
        dests = "\n".join(str(t) for t in targets)
        self.statusBar().showMessage(tr("window.status_build_ok", target=targets[0]))
        text = tr("window.build_success_text", n=len(self.objects), target=dests)
        if self._op2launcher_path().exists():
            box = QMessageBox(QMessageBox.Information, tr("window.build_success_title"), text, parent=self)
            launch_btn = box.addButton(tr("window.launch_op2"), QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is launch_btn:
                self._launch_op2()
        else:
            QMessageBox.information(self, tr("window.build_success_title"), text)

    def _build_err(self, msg):
        self._progress.close()
        self.statusBar().showMessage(tr("window.status_build_failed"))
        QMessageBox.critical(self, tr("window.build_failed_title"), msg)

    def _op2launcher_path(self) -> Path:
        return CONTENT_ROOT / "op2launcher.exe"

    def _launch_op2(self):
        self._editor_uebernehmen()
        launcher = self._op2launcher_path()
        if not launcher.exists():
            QMessageBox.warning(self, tr("window.launcher_missing_title"),
                                tr("window.launcher_missing_text", path=launcher))
            return
        try:
            subprocess.Popen([str(launcher), self.dll_name], cwd=str(CONTENT_ROOT))
            self.statusBar().showMessage(tr("window.status_launching_op2", dll=self.dll_name))
        except Exception as e:
            QMessageBox.critical(self, tr("window.launcher_failed_title"),
                                 tr("window.launcher_failed_text", e=e))
