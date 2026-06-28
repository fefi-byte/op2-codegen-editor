from __future__ import annotations

from .common import *
from . import mission_project
from .placed_object import PlacedObject


class _ProjectMixin:
    def _maybe_reopen_last_mission(self):
        """Bietet beim Start an, die zuletzt geoeffnete Mission wieder zu laden."""
        try:
            last = appconfig.last_mission()
        except Exception:
            last = ""
        if not last:
            return
        folder = Path(last)
        if not mission_project.is_mission_folder(folder):
            try:
                appconfig.set_last_mission("")
            except Exception:
                pass
            return
        title = tr("window.dlg_open_mission")
        text = tr("window.reopen_last_text", name=folder.name)
        if QMessageBox.question(self, title, text) != QMessageBox.Yes:
            return
        proj = folder / "mission.op2proj"
        if proj.is_file():
            self.open_project(preset_path=str(proj))

    def _missions_dir(self) -> Path:
        d = ROOT / "missions"
        d.mkdir(exist_ok=True)
        return d

    def _new_object_uid(self) -> str:
        while True:
            uid = f"obj{self._next_object_id}"
            self._next_object_id += 1
            if all(o.uid != uid for o in self.objects):
                return uid

    def _collect_project_data(self) -> dict:
        """Sammelt alle Mission-Daten in ein JSON-serialisierbares Dict."""
        return {
            "mission_name": self.mission_name,
            "mission_type": int(self.mission_type),
            "tech_tree": self.tech_tree,
            "difficulty": asdict(self.diff_setup),
            "variables": [asdict(v) for v in self.variables],
            "map": self.map_name,
            "players": [asdict(p) for p in self.players],
            "objects": [o.to_dict() for o in self.objects],
            "building_groups": [asdict(g) for g in self.building_groups],
            "reinforce_groups": [asdict(g) for g in self.reinforce_groups],
            "triggers": [asdict(t) for t in self.triggers],
            "victories": [asdict(c) for c in self.victories],
            "defeats": [asdict(c) for c in self.defeats],
            "node_positions": self.node_positions,
        }

    def _mission_write_kwargs(self) -> dict:
        """Argumente fuer mission_project.write_mission_folder() (ohne LevelMain)."""
        map_source = None
        if self.map_name:
            map_source = self.res._index.get(self.map_name.lower())
        return dict(
            mission_name=self.mission_name,
            map_name=self.map_name,
            project_data=self._collect_project_data(),
            map_source=Path(map_source) if map_source else None,
            techtree_source=None,
            dll_basename=mission_project.default_dll_basename(self.dll_name),
        )

    def _save_to_folder(self, folder: Path) -> bool:
        """Schreibt die Mission als self-contained Ordner. Gibt True bei Erfolg zurueck."""
        try:
            cpp = generate_levelmain(self.build_mission())
            mission_project.write_mission_folder(
                folder, level_main_cpp=cpp, **self._mission_write_kwargs()
            )
        except Exception as e:
            QMessageBox.critical(self, tr("window.save_failed_title"), str(e))
            return False
        self.mission_folder = folder
        self.setWindowTitle(f"OP2 Mission Editor — {self.mission_name}  [{folder.name}]")
        try:
            appconfig.set_last_mission(str(folder))
        except Exception:
            pass
        self.statusBar().showMessage(
            tr("window.status_saved", path=str(folder), n=len(self.objects))
        )
        return True

    def save_project(self):
        """Speichert in den bekannten Mission-Ordner; sonst fragt nach einem neuen."""
        if self.mission_folder and self.mission_folder.is_dir():
            self._save_to_folder(self.mission_folder)
            return
        self.save_project_as()

    def save_project_as(self):
        """Fragt nach einem Mission-Namen und schreibt die Mission self-contained."""
        from PySide6.QtWidgets import QInputDialog
        default_name = mission_project._slugify(self.mission_name)
        name, ok = QInputDialog.getText(
            self, tr("window.dlg_save_mission"),
            "Mission-Ordnername (wird unter missions/ angelegt):",
            text=default_name,
        )
        if not ok or not name.strip():
            return
        slug = mission_project._slugify(name.strip())
        folder = self._missions_dir() / slug
        if folder.is_dir() and any(folder.iterdir()):
            if QMessageBox.question(
                self, tr("window.dlg_save_mission"),
                f"'{folder.name}' existiert bereits. Inhalt ueberschreiben?",
            ) != QMessageBox.Yes:
                return
        self._save_to_folder(folder)

    def open_project(self, preset_path: str | None = None):
        if preset_path:
            path = preset_path
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, tr("window.dlg_open_mission"), str(self._missions_dir()),
                f"OP2 Mission (*.op2proj);;JSON (*.json);;{tr('window.filter_all')} (*.*)")
            if not path:
                return
        proj_path = mission_project.find_op2proj(Path(path))
        if proj_path is None:
            QMessageBox.critical(self, tr("window.open_failed_title"), "mission.op2proj nicht gefunden")
            return
        path = str(proj_path)
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, tr("window.open_failed_title"), str(e))
            return
        self.mission_name = data.get("mission_name", "Editor Mission")
        self.mission_type = MissionType(data.get("mission_type", int(MissionType.Colony)))
        self.tech_tree = data.get("tech_tree", "MULTITEK.TXT")
        if "difficulty" in data:
            try:
                self.diff_setup = DifficultySetup(**data["difficulty"])
            except Exception:
                self.diff_setup = DifficultySetup()
        if "variables" in data:
            self.variables = []
            for vd in data["variables"]:
                try:
                    self.variables.append(VariableDef(**vd))
                except Exception:
                    pass
        self.node_positions.clear()
        self.node_positions.update(data.get("node_positions", {}))
        if "players" in data and data["players"]:
            self.players = []
            for d in data["players"]:
                d = dict(d)
                d["colony"] = Colony(d.get("colony", 0))
                self.players.append(PlayerSpec(**d))
            self._refresh_player_range()
        if "victories" in data:
            self.victories = [Condition(**d) for d in data["victories"]]
        if "defeats" in data:
            self.defeats = [Condition(**d) for d in data["defeats"]]
        if "triggers" in data:
            self.triggers = []
            for td in data["triggers"]:
                try:
                    td = dict(td)
                    actions = [action_from_dict(a) for a in td.pop("actions", [])]
                    checks = [FindUnitCheck(**c) for c in td.pop("unit_checks", [])]
                    self.triggers.append(TriggerDef(actions=actions, unit_checks=checks, **td))
                except Exception:
                    continue
        self.setWindowTitle(f"OP2 Mission Editor — {self.mission_name}")
        self.load_map(data.get("map", self.map_name))
        used_uids = {d.get("uid") for d in data.get("objects", []) if d.get("uid")}
        for od in data.get("objects", []):
            try:
                obj = PlacedObject.from_dict(od)
            except Exception:
                continue
            if not obj.uid:
                while True:
                    obj.uid = self._new_object_uid()
                    if obj.uid not in used_uids:
                        used_uids.add(obj.uid)
                        break
            self._draw(obj)
            self.objects.append(obj)
        self.building_groups = []
        for gd in data.get("building_groups", []):
            try:
                self.building_groups.append(BuildingGroupSpec(**gd))
            except Exception:
                continue
        self.reinforce_groups = []
        for gd in data.get("reinforce_groups", []):
            try:
                gd = dict(gd)
                targets = [
                    ReinforceTargetSpec(**target)
                    for target in gd.pop("targets", [])
                ]
                self.reinforce_groups.append(ReinforceGroupSpec(targets=targets, **gd))
            except Exception:
                continue
        parent = Path(path).parent
        if mission_project.is_mission_folder(parent):
            self.mission_folder = parent
            self.setWindowTitle(f"OP2 Mission Editor — {self.mission_name}  [{parent.name}]")
            try:
                appconfig.set_last_mission(str(parent))
            except Exception:
                pass
        else:
            self.mission_folder = None
        self._redraw_planned_actions()
        self._refresh_overview()
        self.statusBar().showMessage(
            tr("window.status_loaded", path=path, n=len(self.objects),
               g=len(self.building_groups) + len(self.reinforce_groups)))
