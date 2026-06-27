# PyInstaller entry point — kein relativer Import, app wird als Paket importiert
import sys
import os
from pathlib import Path

# editor/ zum Suchpfad hinzufügen damit "import app" als Paket funktioniert
_here = Path(__file__).resolve().parent
_editor = _here / "editor"
if str(_editor) not in sys.path:
    sys.path.insert(0, str(_editor))

from app.__main__ import main

if __name__ == "__main__":
    main()
