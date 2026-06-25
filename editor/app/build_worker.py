from __future__ import annotations
from .common import *


class BuildWorker(QThread):
    """
    Ein ``QThread``, der LevelMain.cpp schreibt und den msbuild-Build
    abseits des UI-Threads ausfuehrt; sendet ``ok(dll_path)`` bei Erfolg
    oder ``err(message)`` bei einem Fehler.

    A ``QThread`` that writes LevelMain.cpp and runs the msbuild build off
    the UI thread, emitting ``ok(dll_path)`` on success or ``err(message)``
    on failure.
    """
    ok = Signal(str)
    err = Signal(str)

    def __init__(self, mission):
        super().__init__()
        self.mission = mission

    def run(self):
        try:
            build_mod.write_levelmain(generate_levelmain(self.mission))
            self.ok.emit(str(build_mod.build()))
        # SystemExit wird separat behandelt: build.py loest bei einem
        # kontrollierten Fehler ein SystemExit aus (saubere Meldung), waehrend
        # der generische Exception-Zweig einen vollen Traceback liefert.
        # SystemExit is caught separately: build.py raises SystemExit on a
        # controlled failure (clean message), vs. the generic Exception branch
        # which reports a full traceback.
        except SystemExit as e:
            self.err.emit(str(e))
        except Exception:
            self.err.emit(traceback.format_exc())


