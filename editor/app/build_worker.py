from __future__ import annotations
from .common import *

from . import mission_project


class BuildWorker(QThread):
    """
    ``QThread``, der den self-contained Mission-Ordner schreibt und msbuild
    abseits des UI-Threads ausfuehrt; sendet ``ok(dll_path)`` bei Erfolg
    oder ``err(message)`` bei einem Fehler.

    ``QThread`` that writes the self-contained mission folder and runs msbuild
    off the UI thread, emitting ``ok(dll_path)`` on success or ``err(message)``
    on failure.
    """
    ok = Signal(str)
    err = Signal(str)

    def __init__(self, mission, folder: Path, write_files: dict):
        super().__init__()
        self.mission = mission
        self.folder = Path(folder)
        # Vorberechnete Save-Daten: damit der Worker keine Qt-Zustaende vom
        # Main-Thread anfasst (alles wird im UI-Thread eingesammelt).
        self.write_files = write_files

    def run(self):
        try:
            cpp = generate_levelmain(self.mission)
            mission_project.write_mission_folder(
                self.folder, level_main_cpp=cpp, **self.write_files
            )
            dll = build_mod.build_folder(self.folder)
            # op2-ki (Submodul): ihre DLL, wenn ein Spieler sie nutzt -- die
            # fertige aus dem op2-ki-Release, auf Wunsch selbst gebaut.
            # op2-ki (submodule): its DLL when a player uses it -- the
            # ready-built one from the op2-ki release, optionally self-built.
            self.op2ki_dll = None
            if '#include "op2ki.hpp"' in cpp:
                self.op2ki_dll = appconfig.op2ki_dll()
            self.ok.emit(str(dll))
        except SystemExit as e:
            self.err.emit(str(e))
        except Exception:
            self.err.emit(traceback.format_exc())
