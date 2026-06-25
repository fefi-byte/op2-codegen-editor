# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project follows [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-06-24

### Added
- "Test in OP2": after a successful build a **Launch OP2** button, plus a
  **Test in OP2** toolbar button, boot Outpost 2 straight into the mission via
  `op2launcher.exe` (run from the OPU folder). Falls back to a clear message if
  `op2launcher.exe` isn't in the OPU folder. (`editor/app/window.py`)

### Changed
- The built mission DLL is now placed in the **OPU folder only** — where the OPU
  version of Outpost 2 looks for missions and where `op2launcher.exe` lives —
  never in the game root. The default output folder is now `<game>\OPU`.

## [0.2.0] - 2026-06-24

### Added
- Standalone Windows executable built with PyInstaller (via the
  `editor/run_app.py` launcher) — runs without a Python install; ships with the
  `lang.*.ini` files next to the exe and the app icon baked in. (The in-editor
  **Build → DLL** still needs the dev setup: `LevelTemplate` + Visual Studio.)
- **View** menu with a tile-grid toggle (remembered in `config.ini [ui]
  show_grid`) and zoom presets — Default (1:1, OP2 in-game scale) and Zoomed out
  (fit map); the mouse wheel still free-zooms. (`editor/app/mapview.py`)
- C++ syntax highlighting in the "Show code" preview, on a dark theme.
  (`editor/app/cpp_highlight.py`)
- Application and window icon (`Structure.ico`).
- Multi-language UI (German/English) via INI string tables (`lang.de.ini`,
  `lang.en.ini`) and a small `tr()` lookup layer (`editor/app/i18n.py`). The
  language is set in `config.ini [ui] language`; `auto` detects the OS language
  on startup (falling back to German). A **Language** menu switches at runtime
  (applies on restart). Adding a language needs only a new `lang.<code>.ini`.
- Standard Windows-BMP tileset decoding, so the editor renders the extracted
  OPU 1.4.1 tilesets (`base/tilesets/well####.bmp`), which are plain BMP rather
  than the `.vol` `PBMP` format. (`mapview/tileset.py`, `mapview/render.py`)
- `config.ini` (next to the executable, or the project root when running
  `python -m app`) for machine-specific settings — `game_path`, `msvs_path`,
  optional build overrides, and DLL output. Auto-created on first run;
  `config.example.ini` is committed as a template. (`codegen/appconfig.py`)
- Folder-based resource loading for the extracted **OPU 1.4.1** layout: maps from
  `OPU\base\maps`, `OPU\maps`, and loose `OPU\*.map`; tilesets from
  `OPU\base\tilesets`; tech trees from `OPU\base\techs`. No `.vol` archive is
  needed. The content root auto-detects `<game>\OPU`, falling back to `<game>`.
  (`mapview/op2res.py`)
- `[build]` overrides `platform_toolset` / `windows_sdk`, so the MSBuild step can
  target a Visual Studio without the v142 (VS2019) toolset — e.g. `v143` (VS2022)
  or `v145` (VS2026).
- Graceful startup error dialog when the game path is wrong or no maps are found;
  it points at `config.ini` instead of crashing.

### Changed
- All Python source comments and docstrings are now bilingual (German + English).
- Game and Visual Studio paths now come from `config.ini` instead of being
  hardcoded. (`editor/app/common.py`, `codegen/build.py`)
- The editor reads maps, tilesets, and tech trees as loose files from the OPU
  folder tree instead of `maps.vol`. (`editor/app/window.py`)
- The player/research dialog loads technologies from `OPU\base\techs\multitek.txt`
  (previously a flat path that did not exist, leaving the research list empty).
- README setup/config section rewritten for the INI config and OPU folder layout.

### Removed
- `editor/config.example.json` (superseded by `config.example.ini`).
- Hardcoded GOG game path and hardcoded Visual Studio install path.

### Fixed
- Map rendering in OPU folder mode: the extracted OPU tilesets are standard BMP,
  which the previous `PBMP`-only decoder rejected (every map failed to render).
- The mission DLL build now succeeds on machines without the VS2019 (v142) build
  tools by retargeting through the configurable `platform_toolset` / `windows_sdk`
  (verified producing `ctest.dll` with v145 + Windows SDK 10.0.26100.0).
