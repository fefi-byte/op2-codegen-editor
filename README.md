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
- PySide6, numpy, Pillow (`pip install PySide6 numpy Pillow`)
- Visual Studio Build Tools 2019+ with the **C++ x86/x64 Build Tools** component (for `msbuild`)
- Outpost 2 installed (OPU 1.4.1 recommended)

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

[ui]
language = auto
```

- `game_path` — Outpost 2 install folder. The editor reads the **extracted OPU
  1.4.1 layout** (`OPU\base\maps`, `OPU\maps`, `OPU\base\tilesets`,
  `OPU\base\techs`) — no `.vol` archives needed. If there is no `OPU` subfolder,
  `game_path` itself is treated as the content root.
- `msvs_path` — Visual Studio install folder (must contain `Common7\Tools\VsDevCmd.bat`).
- `output_dir` — where the built DLL is copied (empty = `game_path`).
- `language` — UI language (see [Language](#language) below).

A `[build]` section can override the MSBuild toolset on newer Visual Studio
versions (e.g. `platform_toolset = v143` for VS2022, `v145` for VS2026, when the
v142/VS2019 toolset isn't installed).

`config.ini` is git-ignored (machine-specific paths).

### Language

The UI ships in **German and English**. The active language comes from
`config.ini [ui] language`:

```ini
[ui]
language = auto    # auto = follow the OS language; or a fixed code: de, en
```

- `auto` detects the system language on startup and uses the matching
  `lang.<code>.ini` if one exists, otherwise falls back to German.
- Switch at runtime via the **Language** menu (applies on restart). Picking a
  language pins it; "Automatic (system)" sets it back to `auto`.
- To add a language, copy `lang.en.ini` to `lang.<code>.ini`, translate the
  values (keys and `{placeholders}` stay unchanged), and select it — no code
  changes needed.

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

The compiled DLL is written to the path set in `config.ini`.

## Cloning

The `LevelTemplate/` folder is a **git submodule** of [OutpostUniverse/LevelTemplate](https://github.com/OutpostUniverse/LevelTemplate), which itself contains the nested SDK submodules (Outpost2DLL, OP2Helper, HFL). Clone with `--recursive`:

```powershell
git clone --recursive https://github.com/fefi-byte/op2-codegen-editor.git
```

If you already cloned without `--recursive`, run:

```powershell
git submodule update --init --recursive
```

## SDK sources

`LevelTemplate/OP2MissionSDK/` contains the SDK headers and libraries (pulled in via the submodule):

- [Outpost2DLL](https://github.com/OutpostUniverse/Outpost2DLL) — core game API
- [OP2Helper](https://github.com/OutpostUniverse/OP2Helper) — helper macros
- [HFL](https://github.com/OutpostUniverse/HFL) — extended unit/player API (UnitEx, PlayerEx, TethysGameEx)
- [odasl](https://github.com/OutpostUniverse/odasl) — audio lib

The SDK sources are bundled directly (no git submodules) so the project builds without any additional clones.
