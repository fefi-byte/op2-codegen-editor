# OP2 Mission Editor

A Python-based mission editor for Outpost 2 that generates native C++ mission source code and compiles it to a 32-bit DLL.

Recent changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## How it works

1. The **editor GUI** (PySide6) lets you place units, buildings, beacons, walls, configure players, triggers, and AI groups visually.
2. The **code generator** (`codegen/`) turns the mission model into a `.cpp` file.
3. **MSBuild / MSVC** compiles the `.cpp` into a 32-bit DLL that Outpost 2 loads directly.

## Repository layout

```
editor/         Python editor (PySide6)
  app/          Modular editor package (main entry point)
    dialogs/    All editor dialogs
  main.py       Legacy single-file editor (kept for reference)
codegen/        C++ code generator and mission data model
mapview/        Map tile renderer / inspection tools
missions/       Saved mission projects (.json)
LevelTemplate/  C++ mission template + bundled OP2 SDK sources
  OP2MissionSDK/
    Outpost2DLL/  Core SDK headers and lib
    OP2Helper/    Helper macros (MkXY, ExportLevelDetails, …)
    HFL/          Hooman's Function Library (UnitEx, PlayerEx, …)
    odasl/        odasl.lib
```

## Setup

### Requirements

- Python 3.11+
- PySide6 (`pip install PySide6`)
- Visual Studio Build Tools 2019+ with the **C++ x86/x64 Build Tools** component (for `msbuild`)
- Outpost 2 installed (OPU version recommended)

### Editor config

Paths live in a `config.ini` next to the executable (or in the project root when
running `python -m app`). It is created automatically on first start; copy
`config.example.ini` and adjust it, or edit the generated file:

```ini
[paths]
game_path = D:\Outpost 2
msvs_path = C:\Program Files\Microsoft Visual Studio\18\Community

[output]
output_dir =
dll_name = cEditorMission.dll
```

- `game_path` — Outpost 2 install folder. The editor reads the **extracted OPU
  1.4.1 layout** (`OPU\base\maps`, `OPU\maps`, `OPU\base\tilesets`,
  `OPU\base\techs`) — no `.vol` archives needed. If there is no `OPU` subfolder,
  `game_path` itself is treated as the content root.
- `msvs_path` — Visual Studio install folder (must contain `Common7\Tools\VsDevCmd.bat`).
- `output_dir` — where the built DLL is copied (empty = `game_path`).

`config.ini` is git-ignored (machine-specific paths).

### Start the editor

```powershell
cd editor
python -m app
```

### Build a mission DLL

Use the **Build** button in the editor, or run manually:

```powershell
cd LevelTemplate
msbuild OP2Script.vcxproj /p:Configuration=Release /p:Platform=Win32
```

The compiled DLL is written to the path set in `config.json`.

## SDK sources

`LevelTemplate/OP2MissionSDK/` contains the bundled SDK headers and libraries:

- [Outpost2DLL](https://github.com/OutpostUniverse/Outpost2DLL) — core game API
- [OP2Helper](https://github.com/OutpostUniverse/OP2Helper) — helper macros
- [HFL](https://github.com/OutpostUniverse/HFL) — extended unit/player API (UnitEx, PlayerEx, TethysGameEx)
- [odasl](https://github.com/OutpostUniverse/odasl) — audio lib

The SDK sources are bundled directly (no git submodules) so the project builds without any additional clones.
