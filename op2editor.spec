# op2editor.spec — PyInstaller build spec for the OP2 Mission Builder
#
# Build:
#   pip install pyinstaller
#   pyinstaller op2editor.spec
#
# Output: dist/OP2MissionBuilder/OP2MissionBuilder.exe  (one-folder build)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import (collect_data_files, collect_dynamic_libs,
                                     collect_submodules)

ROOT = Path(SPECPATH)          # repo root (op2-cpp-poc/)
EDITOR = ROOT / "editor"
APP    = EDITOR / "app"

# op2maplib.dll aus den Quellen des Submoduls gebaut, nicht die fertige DLL
# des Submoduls. Der Release-Workflow baut sie vor diesem Schritt; lokal:
#   cmake -S OP2MappingLib -B build-op2maplib -A x64 -DOP2MAPLIB_BUILD_TESTS=OFF
#   cmake --build build-op2maplib --config Release
# op2maplib.dll built from the submodule's sources, not its prebuilt DLL. The
# release workflow builds it before this step; locally use the two commands above.
OP2MAPLIB_DLL = ROOT / "build-op2maplib" / "bin" / "Release" / "op2maplib.dll"
if not OP2MAPLIB_DLL.is_file():
    raise SystemExit(f"op2maplib.dll fehlt / missing: {OP2MAPLIB_DLL}\n"
                     "Zuerst aus den Quellen bauen / build it from source first:\n"
                     "  cmake -S OP2MappingLib -B build-op2maplib -A x64 -DOP2MAPLIB_BUILD_TESTS=OFF\n"
                     "  cmake --build build-op2maplib --config Release")

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
    (str(APP / "resources" / "unit_anims.json"), "app/resources"),
    # C++ mission templates (written to project folder by mission_project.py)
    (str(APP / "templates"), "app/templates"),
    # codegen + mapview Python sources
    (str(ROOT / "codegen"), "codegen"),
    # OP2MissionSDK (Outpost2DLL headers + Outpost2.lib, OP2Helper + HFL
    # sources) — the generated mission CMakeLists.txt finds it via the path
    # appconfig.op2sdk_dir() resolves to (sys._MEIPASS in the frozen build).
    (str(ROOT / "OP2MissionSDK" / "Outpost2DLL"), "OP2MissionSDK/Outpost2DLL"),
    (str(ROOT / "OP2MissionSDK" / "OP2Helper"), "OP2MissionSDK/OP2Helper"),
    (str(ROOT / "OP2MissionSDK" / "HFL"), "OP2MissionSDK/HFL"),
    # op2-ki (Submodul, im Release auf dem neuesten op2-ki-Release): Quellen
    # fuer den Rust-Build von op2ki.dll auf dem PC und die zwei Missions-Header
    # (appconfig.op2ki_dir() -> sys._MEIPASS/op2-ki).
    # op2-ki (submodule, in a release on the latest op2-ki release): sources
    # for building op2ki.dll on the PC and the two mission headers.
    (str(ROOT / "op2-ki" / "Cargo.toml"), "op2-ki"),
    (str(ROOT / "op2-ki" / "Cargo.lock"), "op2-ki"),
    (str(ROOT / "op2-ki" / "LICENSE"), "op2-ki"),
    (str(ROOT / "op2-ki" / "kern"), "op2-ki/kern"),
    (str(ROOT / "op2-ki" / "dll"), "op2-ki/dll"),
    (str(ROOT / "op2-ki" / "missionen" / "gemeinsam"), "op2-ki/missionen/gemeinsam"),
    (str(ROOT / "op2-ki" / "fertig" / "op2ki.dll"), "op2-ki/fertig"),
    # OP2MappingLib (Submodul): Python-Binding und Profil fuer Gelaendepinsel,
    # Klippen und Kartengenerator (appconfig.op2maplib_dir() ->
    # sys._MEIPASS/OP2MappingLib). Die DLL kommt NICHT fertig aus dem Submodul,
    # sondern aus dem eigenen Build der Quellen (OP2MAPLIB_DLL, siehe unten).
    # OP2MappingLib (submodule): Python binding and profile. The DLL is NOT the
    # submodule's prebuilt one but our own build of its sources (see below).
    (str(ROOT / "OP2MappingLib" / "bindings" / "python" / "op2maplib"),
     "OP2MappingLib/bindings/python/op2maplib"),
    (str(OP2MAPLIB_DLL), "OP2MappingLib/bin"),
    (str(ROOT / "OP2MappingLib" / "profiles" / "op2.json"), "OP2MappingLib/profiles"),
    (str(ROOT / "OP2MappingLib" / "LICENSE"), "OP2MappingLib"),
    (str(ROOT / "OP2MappingLib" / "THIRD-PARTY-NOTICES.md"), "OP2MappingLib"),
    # mapview ohne gecachte PNG-Renders (werden zur Laufzeit aus OP2-Pfad geladen)
    *[
        (str(f), "mapview")
        for f in (ROOT / "mapview").iterdir()
        if f.is_file() and f.suffix != ".png"
    ],
    # Die mapview-Module landen im PYZ, ihr __file__ zeigt dann auf _internal/
    # statt _internal/mapview/. Sie suchen ihre Modelle neben __file__
    # (tiles_model.npz, celltypes.json, cliff_*.npz, ...), also die Daten
    # zusaetzlich dorthin legen -- sonst kann kein Gelaendepinsel malen.
    # The mapview modules end up in the PYZ, so their __file__ points to
    # _internal/ instead of _internal/mapview/. They look for their models
    # next to __file__, so put the data there too -- otherwise no terrain
    # brush can paint.
    *[
        (str(f), ".")
        for f in (ROOT / "mapview").iterdir()
        if f.is_file() and f.suffix in (".npz", ".json", ".pkl", ".onnx")
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
    # gelernter Kartengenerator / learned map generator
    "onnxruntime",
    "mapgen_netz",
    "mapgen_netz_fels",
    "mapgen_netz_gross",
    "mapgen_netz_deko",
    "mapgen_netz_waende",
    # codegen modules (added to sys.path at runtime, not a proper package import)
    "mission_model",
    "codegen",
    "codegen_cpp",
    "codegen_actions",
    "codegen_triggers",
    "codegen_groups",
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
    binaries=collect_dynamic_libs("onnxruntime"),
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
    name="OP2MissionBuilder",
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
    # onnxruntime vertraegt kein UPX / onnxruntime does not survive UPX
    upx_exclude=["onnxruntime.dll", "onnxruntime_pybind11_state.pyd"],
    name="OP2MissionBuilder",
)
