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

    def _migrate_wave_fight_groups(self):
        """Alte Speicherstaende (vor FightGroups als eigenem Gruppentyp) hatten
        bei sendAttackWave ein Freitextfeld `group_var_name`, das spontan eine
        FightGroup erzeugte. Fuer jeden solchen Namen ohne passenden
        FightGroupSpec-Eintrag legen wir jetzt automatisch einen an, damit die
        Mission unveraendert weiterfunktioniert.

        Old saves (before FightGroups became their own group type) had a
        free-text `group_var_name` field on sendAttackWave that spontaneously
        created a FightGroup. For every such name without a matching
        FightGroupSpec entry, auto-create one now so the mission keeps working.
        """
        existing = {g.name for g in self.fight_groups}
        added = {}

        def walk(actions):
            for a in (actions or []):
                if a.kind == "sendAttackWave":
                    name = (getattr(a, "group_var_name", "") or "").strip()
                    if name and name not in existing and name not in added:
                        added[name] = FightGroupSpec(
                            name=name,
                            player=int(getattr(a, "player", 0)),
                            idle_x=int(getattr(a, "idle_x", 0)),
                            idle_y=int(getattr(a, "idle_y", 0)),
                            idle_width=max(1, int(getattr(a, "idle_x2", 0)) - int(getattr(a, "idle_x", 0)) + 1),
                            idle_height=max(1, int(getattr(a, "idle_y2", 0)) - int(getattr(a, "idle_y", 0)) + 1),
                        )
                walk(getattr(a, "then_actions", None))
                walk(getattr(a, "else_actions", None))

        for t in self.triggers:
            walk(t.actions)
        if added:
            self.fight_groups.extend(added.values())

    def _migrate_start_mining_groups(self):
        """Alte Speicherstaende (vor MiningGroups als eigenem Gruppentyp)
        hatten bei startMining kein `group_name` -- die Gruppe wurde spontan
        und anonym im Codegen erzeugt, mit hartkodiertem Abladebereich
        (Smelter ±4/±3). Fuer jede solche Aktion legen wir jetzt automatisch
        eine MiningGroupSpec an, mit EXAKT demselben Bereich (Breite 8, Hoehe
        6 -- (x2+4)-(x2-4) bzw. (y2+3)-(y2-3)), damit generierter Code fuer
        unveraenderte Altmissionen gleich bleibt.

        Old saves (before MiningGroups became their own group type) had no
        `group_name` on startMining -- the group was spontaneously and
        anonymously created in codegen, with a hardcoded unload area
        (smelter ±4/±3). For every such action we now auto-create a
        MiningGroupSpec with the EXACT same area (width 8, height 6 --
        (x2+4)-(x2-4) resp. (y2+3)-(y2-3)), so generated code for unchanged
        old missions stays identical.
        """
        existing = {g.name for g in self.mining_groups}
        added = {}
        counter = len(self.mining_groups)

        def walk(actions):
            nonlocal counter
            for a in (actions or []):
                if a.kind == "startMining" and not (getattr(a, "group_name", "") or "").strip():
                    counter += 1
                    name = f"MiningGroup{counter}"
                    while name in existing or name in added:
                        counter += 1
                        name = f"MiningGroup{counter}"
                    added[name] = MiningGroupSpec(
                        name=name,
                        player=int(getattr(a, "player", 0)),
                        idle_x=int(getattr(a, "x2", 0)) - 4,
                        idle_y=int(getattr(a, "y2", 0)) - 3,
                        idle_width=8,
                        idle_height=6,
                    )
                    a.group_name = name
                walk(getattr(a, "then_actions", None))
                walk(getattr(a, "else_actions", None))

        for t in self.triggers:
            walk(t.actions)
        if added:
            self.mining_groups.extend(added.values())

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
            "fight_groups": [asdict(g) for g in self.fight_groups],
            "mining_groups": [asdict(g) for g in self.mining_groups],
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
        self._clear_undo()
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
        self.fight_groups = []
        for gd in data.get("fight_groups", []):
            try:
                self.fight_groups.append(FightGroupSpec(**gd))
            except Exception:
                continue
        self.mining_groups = []
        for gd in data.get("mining_groups", []):
            try:
                self.mining_groups.append(MiningGroupSpec(**gd))
            except Exception:
                continue
        self._migrate_wave_fight_groups()
        self._migrate_start_mining_groups()
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
        self.trigger_panel.load()
        self.groups_panel.load()
        self._redraw_planned_actions()
        self._refresh_overview()
        self.statusBar().showMessage(
            tr("window.status_loaded", path=path, n=len(self.objects),
               g=len(self.building_groups) + len(self.reinforce_groups) + len(self.fight_groups)
               + len(self.mining_groups)))
