# op2editor.spec — PyInstaller build spec for the OP2 Mission Editor
#
# Build:
#   pip install pyinstaller
#   pyinstaller op2editor.spec
#
# Output: dist/OP2MissionEditor/OP2MissionEditor.exe  (one-folder build)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)          # repo root (op2-cpp-poc/)
EDITOR = ROOT / "editor"
APP    = EDITOR / "app"

# ---------------------------------------------------------------------------
# Data files bundled next to the EXE
# ---------------------------------------------------------------------------
datas = [
    # Language files — loaded by i18n.py from base_dir() (== EXE folder)
    (str(ROOT / "lang.de.ini"),  "."),
    (str(ROOT / "lang.en.ini"),  "."),
    # config.example.ini so users can copy it
    (str(ROOT / "config.example.ini"), "."),
    # App icon
    (str(APP / "resources" / "Structure.ico"), "app/resources"),
    # C++ mission templates (written to project folder by mission_project.py)
    (str(APP / "templates"), "app/templates"),
    # codegen + mapview Python sources
    (str(ROOT / "codegen"), "codegen"),
    # mapview ohne gecachte PNG-Renders (werden zur Laufzeit aus OP2-Pfad geladen)
    *[
        (str(f), "mapview")
        for f in (ROOT / "mapview").iterdir()
        if f.is_file() and f.suffix != ".png"
    ],
]

# Nur die tatsächlich benötigten PySide6-Plugins (keine QML, kein WebEngine)
datas += collect_data_files("PySide6", includes=["plugins/platforms/*",
                                                   "plugins/styles/*",
                                                   "plugins/imageformats/*",
                                                   "plugins/iconengines/*"])

# ---------------------------------------------------------------------------
# Hidden imports that PyInstaller misses
# ---------------------------------------------------------------------------
hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # QtOpenGL nur wenn der Editor tatsächlich GL-Rendering nutzt (derzeit nicht)
    # "PySide6.QtOpenGL",
    # "PySide6.QtOpenGLWidgets",
    "PySide6.QtPrintSupport",
    "numpy",
    "PIL",
    "PIL.Image",
    "PIL.ImageQt",
    "ctypes",
    "ctypes.wintypes",
    # codegen modules (added to sys.path at runtime, not a proper package import)
    "mission_model",
    "codegen",
    "build",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(ROOT / "op2editor_entry.py")],
    pathex=[
        str(ROOT / "codegen"),
        str(ROOT / "mapview"),
        str(EDITOR),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "email",
        "html",
        "http",
        "xmlrpc",
        "xml",
    ],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# Nicht benötigte Binaries herausfiltern (spart ~90 MB)
# ---------------------------------------------------------------------------
_EXCLUDE_DLLS = {
    "opengl32sw.dll",         # Software-OpenGL-Fallback (nie gebraucht)
    "qt6quick.dll",           # QML Quick (kein QML im Editor)
    "qt6qml.dll",             # QML Engine
    "qt6qmlmodels.dll",
    "qt6pdf.dll",             # PDF (nicht gebraucht)
    "qt6pdfquick.dll",
    "libcrypto-3.dll",        # SSL (kein Netzwerk)
    "libcrypto-3-x64.dll",
    "libssl-3.dll",
    "libssl-3-x64.dll",
}
_EXCLUDE_PYDS = {
    "_avif.cp311-win_amd64.pyd",    # PIL AVIF-Plugin (nicht gebraucht)
    "_webp.cp311-win_amd64.pyd",    # PIL WebP (nicht gebraucht)
    "_heif.cp311-win_amd64.pyd",
}
_EXCLUDE_OPENBLAS = None   # OpenBLAS muss drin bleiben — numpy._multiarray_umath linkt dagegen

def _filter_binaries(binaries):
    result = []
    for name, path, kind in binaries:
        base = Path(name).name.lower()
        if base in _EXCLUDE_DLLS:
            continue
        if base in _EXCLUDE_PYDS:
            continue
        if _EXCLUDE_OPENBLAS and _EXCLUDE_OPENBLAS in base:
            continue
        result.append((name, path, kind))
    return result

def _filter_datas(datas):
    result = []
    for dest, src, kind in datas:
        base = Path(dest).name.lower()
        # Qt-Übersetzungen: nur de/en behalten
        if dest.endswith(".qm"):
            if not any(x in base for x in ("de", "en", "qt_")):
                continue
        result.append((dest, src, kind))
    return result

a.binaries = TOC(_filter_binaries(a.binaries))
a.datas    = TOC(_filter_datas(a.datas))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OP2MissionEditor",
    icon=str(APP / "resources" / "Structure.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # kein schwarzes Konsolenfenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OP2MissionEditor",
)
