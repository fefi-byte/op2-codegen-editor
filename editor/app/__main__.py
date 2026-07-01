from __future__ import annotations
import sys
from .common import QApplication, QIcon, ICON_PATH
from .window import EditorWindow


def main():
    """
    Einstiegspunkt des Editors: erstellt die ``QApplication``, zeigt das
    ``EditorWindow`` an und startet die Ereignisschleife.

    The editor entry point: create the ``QApplication``, show the
    ``EditorWindow`` and run the event loop.
    """
    app = QApplication(sys.argv)
    from .style import build_stylesheet
    app.setStyleSheet(build_stylesheet())
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("op2.mission.editor")
    except Exception:
        pass
    # App-weites Icon (greift auch fuer alle Dialoge).
    # Application-wide icon (also applies to all dialogs).
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    win = EditorWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
