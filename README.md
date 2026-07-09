# OP2 Mission Editor

> **Alpha release.** Expect rough edges. Feedback and bug reports welcome.

A visual mission editor for *Outpost 2: Divided Destiny*. Design missions by clicking, generate native C++23 source code, compile it to a 32-bit DLL that Outpost 2 loads directly.

Built against [TitanAPI](https://github.com/leviathan400/TitanAPI), a modern header-only C++23 SDK by leviathan400.

![Main window](docs/images/Main.png)

**Feature manual:** [English](EDITOR_DOCS.md) · [Deutsch](EDITOR_DOKU.md) — full walk-through of every panel, dialog, and action type.

Recent changes: [CHANGELOG.md](CHANGELOG.md).

## What's in the editor

- **Visual placement** — buildings, vehicles, mining beacons, walls and tubes, drag-drop on a real tile map
- **Players** — up to 6 players, human or AI, per-player resources, tech level, pre-researched techs
- **Groups** — BuildingGroup / ReinforceGroup / FightGroup / MiningGroup, each with its own roster and behaviour
- **Triggers** — conditions (time, count, resource, findUnit, …) with nested if/then/else action blocks and forEach loops
- **Actions** — 15+ action kinds including createUnit, sendAttackWave, startMining, group commands, unit commands, disasters
- **Self-healing groups** — mission-wide watchdog that re-attaches rebuilt buildings/mines/smelters to their group automatically
- **Save-game safe** — persistent state (variables, groups, unit handles) lives in a single POD struct that survives save/load
- **Live validation** — mission-wide error/warning panel updates on every edit
- **Localised UI** — German and English, switch at runtime
- **One-click build** — MSBuild integration, DLL is copied straight into your OP2 folder

## Quick start

### Requirements

- Python 3.11+
- `pip install PySide6 numpy Pillow`
- Visual Studio Build Tools 2019+ with the **C++ x86 build tools** component (for the 32-bit DLL)
- Outpost 2 installed (OPU 1.4.1 recommended — the editor reads its extracted `OPU\base\` and `OPU\maps` layout, no `.vol` archives needed)

### Clone with the TitanAPI submodule

```powershell
git clone --recursive https://github.com/fefi-byte/op2-codegen-editor.git
```

If you cloned without `--recursive`:

```powershell
git submodule update --init --recursive
```

### Configure paths

The editor creates `config.ini` on first start next to the entry point. Copy `config.example.ini` as a template, or edit the generated file:

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

- `game_path` — Outpost 2 install folder. If it contains an `OPU\` subfolder, that's used as the content root; otherwise `game_path` itself is.
- `msvs_path` — must contain `Common7\Tools\VsDevCmd.bat`.
- `output_dir` — where the built DLL is copied (empty = `game_path`).
- `[ui] language` — `auto` (follow OS), `de`, or `en`. Switchable at runtime via the Language menu.

An optional `[build] platform_toolset = v143` (VS2022) or `v145` (VS2026) overrides MSBuild's default toolset if the older one isn't installed.

`config.ini` is git-ignored.

### Start the editor

```powershell
cd editor
python -m app
```

Or double-click `editor\Editor (modular) starten.bat`.

### Build a mission DLL

Use the **Build → DLL** button in the toolbar, or manually:

```powershell
cd LevelTemplate
msbuild OP2Script.vcxproj /p:Configuration=Release /p:Platform=Win32
```

## Repository layout

```
editor/
  app/              Editor package (PySide6, modular entry point)
    dialogs/        Modal dialogs (settings, players, victory/defeat, action editor, …)
    panels/         Sidebar panels (placement, triggers, groups, objects)
    Editor (modular) starten.bat
codegen/            Mission model + C++ code generator
mapview/            Tile renderer for the map view
missions/           Example mission projects
LevelTemplate/      C++ mission project template (MSBuild)
TitanAPI/           SDK submodule (leviathan400/TitanAPI)
lang.de.ini         German UI strings
lang.en.ini         English UI strings
```

## How it works

1. The editor loads a project into an in-memory **Mission model** (`codegen/mission_model.py`), a set of dataclasses describing every unit, group, trigger and action.
2. Every change is validated live (`editor/app/validation.py`) — errors and warnings appear in the right sidebar.
3. On **Build**, the code generator (`codegen/codegen.py`) walks the model and emits a single self-contained `mission.cpp` targeting the TitanAPI facade.
4. **MSBuild** compiles that C++ into a 32-bit DLL.
5. **Test in OP2** launches Outpost 2 with the mission preselected via `op2launcher.exe`.

## License

*(project-specific — add your preferred license file here)*
