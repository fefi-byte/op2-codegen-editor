"""PyInstaller-Einstiegsskript: startet das app-Paket wie `python -m app`.

Das app-Paket nutzt relative Importe und kann daher nicht direkt als
PyInstaller-Einstiegsskript dienen; dieser Wrapper importiert es regulaer.
Im gefrorenen --windowed-Build sind stdout/stderr None; sie werden auf eine
Logdatei neben der EXE umgeleitet, damit schreibende Bibliotheken nicht
abstuerzen und Startfehler sichtbar bleiben.

PyInstaller entry script: starts the app package like `python -m app`.

The app package uses relative imports and therefore cannot be the PyInstaller
entry script directly; this wrapper imports it normally. In a frozen
--windowed build stdout/stderr are None; they are redirected to a log file
next to the EXE so libraries that write don't crash and startup errors stay
visible.
"""
import sys
from pathlib import Path

# stdout/stderr im gefrorenen Build absichern.
# Guard stdout/stderr in the frozen build.
if getattr(sys, "frozen", False):
    try:
        _log = open(Path(sys.executable).resolve().parent / "OP2CodeGenEditor.log",
                    "w", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _log
        if sys.stderr is None:
            sys.stderr = _log
    except OSError:
        pass

from app.__main__ import main

if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Startfehler in eine Datei neben der EXE schreiben.
        # Write startup errors to a file next to the EXE.
        import traceback
        traceback.print_exc()
        try:
            (Path(sys.executable).resolve().parent / "crash.log").write_text(
                traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        raise
