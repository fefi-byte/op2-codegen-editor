# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [0.5.0-alpha] - 2026-08-05

The editor grew a **map side**. Until now it edited missions on maps that
already existed; it can now generate terrain, paint it, and draw cliffs — and
write the result back as a playable `.map`.

Everything the terrain code places is taken from the original maps rather than
invented. Which tile may sit next to which is counted across the 107 stock
maps, and the cliff tiles carry a by-hand assignment of what each of their four
sides shows: rock or ground.

### Added — terrain and maps
- **Map generator**: terrain templates, features (mountain, valley, narrows,
  clearing), symmetry, spawn points, volcanoes with lava zones — and the result
  is written back as a playable `.map`.
- **Terrain painting**: ground families, lava, building ground and volcanoes
  are painted as intent into layers; the tiles are derived from them, including
  the transitions between grounds.
- **Cliff brush**: each click sets a point of the edge, then you choose which
  side is high and place it. Runs, corners and end pieces are assembled from
  whole tile groups; a corner is picked by the sides its wall has to show *and*
  by where the highland lies, so it can no longer end up rotated.
- **Continuing a cliff**: start or end a line at an existing one. Blue rings
  mark open ends and every click snaps to them within five tiles. Meeting a
  wall halfway works too — a dashed ring under the cursor shows where the click
  will land, and the cross wall stays intact.
- **Erasing cliffs**: the *Lowland* brush lowers the ground again and takes the
  cliff with it.
- **Cliffs from the terrain instead of from blocks** (new switch *Terrain, not
  blocks*, on by default): rather than laying down ready-made blocks and
  repairing afterwards, every tile is derived from what the terrain requires at
  that spot. The terrain is described four times finer than the tile grid, and
  only a tile whose hand-assigned edges show exactly that is placed. A tile
  showing rock into open ground is therefore never chosen — hard transitions
  are ruled out rather than repaired.

  The wall also stopped looking like a staircase. Its height varies instead of
  being fixed, and the number of solid fill tiles is capped, which brings in the
  tiles whose slope is only a small corner. Measured against the 51 stock maps:

  |                            | drawn walls   | stock maps |
  |----------------------------|---------------|------------|
  | hard transitions           | 0             | —          |
  | severed seams              | 0             | —          |
  | same tile repeated in a row| 1.00 – 1.04   | 1.01       |
  | wall height                | 3.54 – 3.63   | 3.54       |
  | seam mismatch (pixels)     | 20.8 – 22.0   | 18.4       |

  This path needs the by-hand tile-edge assignment and currently covers *dirt*
  only; on sand and snow the editor quietly falls back to blocks.
- **Lava brush** with a variable, round brush size instead of dragging
  rectangles.

### Added — missions
- **Briefing** as a real pre-game dialog, using the technique from *Rising From
  The Ashes*, plus a new *Show dialog* action for a message box over the running
  game.
- **Variable text and target players** for messages and dialogs.
- **Action designer** for building your own actions, with export/import as
  `.op2action` files so they can be shared.
- **Hand-written C++** can be added alongside the generated code.
- **Unit orders**: production in factories and rocket launches at the spaceport.
- **Campaign missions**: positive `missionType` and the `e##`/`p##` naming
  scheme.
- **Demo mission** *(Demo Showcase)*: a tour through the editor's features.
- **Code editors** with word completion, syntax highlighting and automatic
  indentation.

### Changed
- **The highland brush is gone.** Deriving a cliff from a painted area was the
  path that failed: area → height field → cell-type band → tile, and after three
  derivations it was no longer known where the wall was meant to be. Highland
  now appears where a drawn cliff puts it. *Lowland* stays as the eraser.
- The terrain tab preselects *Dirt* instead of *Highland*, so the first click
  cannot take anything away.
- The eyedropper picks the ground even on highland.
- The action menu is grouped into submenus instead of one long flat list.
- **TitanAPI removed completely** — the classic Outpost 2 Mission SDK is now the
  only backend.
- `codegen.py` split into four modules (2713 lines → five files of roughly 200
  to 1000).

### Fixed
- `forEach` loops over buildings found no units.
- `PlayerBuildingEnum(mapAny)` returns nothing; the generator uses a loop over
  building types instead.
- `<loop:outer>` inside a simple loop dropped the order.
- Loop validation checked fields that were not in use.
- Validation printed a literal `\n` instead of a line break; the tube check was
  removed.
- Briefing text was black on black, then white; it is now the Outpost 2 menu
  green.
- Nine form labels sat in the `[triggers]` section instead of `[action_editor]`.
- *(Own action)* and *defendArea* removed from the action-type dropdown.

## [0.4.0-alpha] - 2026-07-20

The editor now generates missions on top of the classic **Outpost 2 Mission
SDK** instead of TitanAPI. In short: missions can do a lot more, and the AI
behaves much more like in the original campaigns.

### Added
- **Bases that rebuild themselves**: building groups now really reconstruct
  destroyed structures — including mines — exactly where they stood. Buildings
  that exist at game start can be included automatically.
- **Named buildings**: give a building a name and the mission keeps track of
  it across destruction and rebuild. Groups and mining setups refer to
  buildings by name instead of coordinates.
- **Smarter mining**: a mining group finds its mine and smelter on its own,
  starts hauling ore once both are standing, and can be resupplied with new
  cargo trucks when some are lost.
- **Repair crews**: define areas to watch and let a group repair damaged
  buildings automatically. Per-building damage thresholds are possible (e.g.
  only repair the Tokamak once it is badly damaged); Eden uses the Repair
  Vehicle, Plymouth the Spider, ConVecs fill in.
- **New actions**: launch an EMP missile, change morale, set the music
  playlist, animate lava flows, and tweak unit stats (speed, armor, …).
- **New trigger conditions**: group attacked, group badly damaged, a scout
  scanning a special target, and a specific unit dying.
- **World maps**: 512-wide wraparound maps are handled correctly.
- **Comments**: triggers and actions have an optional comment field; comments
  also show up in the generated code.
- **Map preview of planned buildings**: buildings that a trigger will
  construct later are drawn dashed on the map, labelled with their trigger.
- Many new validation checks that warn about common mission-scripting traps
  before you even build.

### Changed
- Slimmer editing panels: field labels sit above their inputs, long
  validation messages wrap, and action cards only take the height they need.
- Mission summaries on the action cards now show what will actually happen
  (e.g. the real vehicle list instead of a leftover default).

### Removed
- Building mission DLLs on Linux. The classic SDK requires Visual Studio
  (MSVC) on Windows; the editor itself still runs anywhere Python does.

## [0.3.1-alpha] - 2026-07-09

### Fixed
- Building a mission from the extracted release ZIP no longer fails with a
  missing `op2.hpp` include.

## [0.3.0-alpha] - 2026-07-09

### Added
- Fight groups and mining groups, self-healing unit groups, and a large
  cleanup of legacy code paths.
- **Linux support**: the editor GUI and the DLL build step now run on Linux
  (Debian, Ubuntu, Arch, Fedora, Steam Deck). The game is expected to run under
  Wine; compiled missions are still Win32 DLLs.
- `requirements.txt` for Python dependencies (`numpy`, `Pillow`, `PySide6`).
- `build.sh` template — MinGW cross-compile script generated alongside
  `build.bat` into every mission folder (executable bit set automatically).
- `codegen/build._find_make_tool()` — auto-detects Ninja or GNU make so
  CMake can configure on Linux without manual generator selection.
- `codegen/build._find_mingw32()` — locates the `i686-w64-mingw32` toolchain
  and provides clear install instructions if missing.
- CI: `build-linux` job on `ubuntu-latest` validates imports and toolchain on
  every tag push (`.github/workflows/release.yml`).

### Changed
- `codegen/build.build_folder()`: branches on platform — Windows uses the VS
  generator as before; Linux uses Ninja/make with MinGW i686-w64-mingw32.
  Stale `CMakeCache.txt` from a prior build is deleted automatically before
  re-configuring.
- `codegen/appconfig.py`: default paths are empty on Linux; `msvs_path` is
  omitted from the auto-generated `config.ini` on non-Windows.
- `CMakeLists.txt.template`: MSVC guard widened to include `MINGW`; compiler
  flags split into MSVC and MinGW branches (static runtime for MinGW).
- `op2_crash.hpp`: SEH (`__try`/`__except`) guarded by `#ifdef _MSC_VER`;
  MinGW gets no-op stubs.
- `TitanAPI/op2/abi/memory.hpp`: calling-convention templates (`callFast`,
  `member`, …) enabled for `__MINGW32__` in addition to `_MSC_VER`.
- `config.example.ini`: Linux `game_path` example added; `msvs_path` marked
  as Windows-only.

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
