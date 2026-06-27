# OP2 Mission Editor — Feature Documentation

Last updated: 2026-06-27

---

## Table of Contents

1. [Overview](#overview)
2. [Main Window](#main-window)
3. [Map View](#map-view)
4. [Dialog: Settings (Setup)](#dialog-settings-setup)
5. [Dialog: Players](#dialog-players)
6. [Dialog: Victory & Defeat](#dialog-victory--defeat)
7. [Dialog: Groups](#dialog-groups)
8. [Dialog: Triggers](#dialog-triggers)
9. [Dialog: Action Editor (If/Then/Else)](#dialog-action-editor-ifthenelse)
10. [Expression Fields (ExprEdit)](#expression-fields-expresedit)
11. [Code Generation](#code-generation)
12. [Project Format (Save/Load)](#project-format-saveload)

---

## Overview

The OP2 Mission Editor is a visual editor for missions in *Outpost 2: Divided Destiny*. It converts the visual mission model directly into C++23 source code (via TitanAPI) and can compile it to a DLL with a single click, then launch the mission in OP2.

**Technology:** Python 3 · PySide6 · TitanAPI (C++23, header-only)

---

## Main Window

### Toolbar (left to right)

| Button | Function |
|---|---|
| **Settings** | Mission name, type, tech tree, difficulty multipliers, custom variables |
| **Players** | Colony, human/AI, tech level, resources, pre-researched technologies |
| **Victory & Defeat** | Victory and defeat conditions |
| **Groups** | Manage BuildingGroups and ReinforceGroups |
| **Triggers** | Triggers with conditions and actions |
| **Show Code** | Preview generated C++ code with syntax highlighting |
| **Build → DLL** | Compile C++ and copy DLL to OP2 folder |
| **Test in OP2** | Launch mission directly in OP2 (via op2launcher.exe) |
| **Clear Objects** | Remove all placed units/buildings from the map |

### Menu

- **File:** Open project · Save project · Save as · Choose map · Output location · Quit
- **View:** Toggle grid · Zoom 1:1 · Zoom fit map
- **Language:** Automatic (system) · Deutsch · English (takes effect on next start)

### Left Sidebar — Placement Panel

- **Category:** Buildings · Vehicles · Beacons & Walls
- **Unit list** with footprint display
- **Player selector** (0–5)
- **Unit name** (optional, for scripting references)
- Context-sensitive parameters:
  - Cargo Truck: cargo type + amount
  - ConVec: kit (which building it carries)
  - Mining Beacon: ore type (random/common/rare) + yield (Bar1–3)
  - Combat vehicles (Lynx/Panther/Tiger) + Guard Post: weapon type

### Right Sidebar — Mission Overview

Dynamic tree with the following sections:

- **Flow / Triggers** — hierarchy of all triggers with execution order (⟶) and cycle detection
- **Players** — summary of all player configurations
- **Groups** — list of all BuildingGroups and ReinforceGroups
- **Victory/Defeat** — victory and defeat conditions
- **Objects** — count of placed units, buildings, beacons, walls

Double-clicking any entry opens its edit dialog.

---

## Map View

### Mouse Controls

| Action | Function |
|---|---|
| Left-click | Place selected object (if selection active) or edit existing object |
| Right-click | Remove object |
| Middle-drag | Pan the map |
| Mouse wheel | Zoom (1.25× / 0.8× per step) |
| Left-drag | Draw rectangle (for SetRect / tube-wall line recording) |

### Visual Elements

- **Placement preview:** Dashed rectangle + label showing where the object will land
- **Action line:** L-shaped line for tube/wall recording actions
- **Action area:** Transparent rectangle for area-based actions
- **Player colors:** 6 distinct colors (blue/red/green/yellow/purple/cyan)
- **Beacon color:** Orange
- **Wall/Tube color:** Gray
- **Tile grid:** Optional 1px line grid (toggle via View menu)

---

## Dialog: Settings (Setup)

Opened via the **Settings** toolbar button.

### Basic Data

| Field | Description |
|---|---|
| Mission name | Displayed in OP2's mission list |
| Mission type | Colony, AutoDemo, Tutorial, Multi variants (Land Rush, Space Race, …) |
| Tech tree file | Path to the technology file (default: `MULTITEK.TXT`) |

### Difficulty

Three numeric values (Hard / Normal / Easy, defaults: 13 / 10 / 5).

These values are available as the `diff` variable in all **expression fields**. Example: a trigger time of `ceil(600 * diff / 10)` results in 780 marks on Hard, 600 on Normal, 300 on Easy.

### Custom Variables

Table with columns **Name · Type · Initial Value**:

- **Type:** `int` or `bool`
- **Initial value:** Integer (for `bool`: 0 = false, anything else = true)
- Variables are declared as `static` variables in the generated C++
- They can be modified with `modVar` actions and tested with `varCheck` conditions

---

## Dialog: Players

Opened via the **Players** toolbar button.

### Player List

Left side: list of all players with summary info. Buttons to add and remove players.

### Player Configuration

| Field | Description |
|---|---|
| Colony | Eden or Plymouth |
| Type | Human or AI |
| Tech level | 0–12 (12 = all techs from the tech tree granted automatically) |
| Set starting resources | Enables the initResources flag |
| Set colonists explicitly | Sets workers / scientists / kids to exact numbers |
| Set resources explicitly | Sets Common Ore / Rare Ore / Food to exact values (expressions supported) |
| Pre-researched | Select individual technologies by name and add them |

Resource fields (Common Ore, Rare Ore, Food) support **expression fields** with difficulty preview.

---

## Dialog: Victory & Defeat

Opened via the **Victory & Defeat** toolbar button.

### Condition Types

| Type | Fields |
|---|---|
| Survive time | Marks |
| Last one standing | Player |
| Build starship | Player |
| No Command Center | Player |
| Building count | Player, building type, compare, count |
| Vehicle count | Player, compare, count |
| Technology researched | Player, tech ID |
| Resource reached | Player, resource, compare, amount |
| Building operational | Player, building type, compare, count |

Each condition has a description field for the objective text shown in-game.

Any number of victory and defeat conditions can be combined.

---

## Dialog: Groups

Opened via the **Groups** toolbar button.

Groups are displayed as a tree (optionally with folder grouping).

### BuildingGroup

A BuildingGroup manages a set of buildings that should be automatically rebuilt.

| Field | Description |
|---|---|
| Name | Unique identifier |
| Folder | Optional folder name for grouping |
| Player | Which player owns the group |
| Rect X/Y/Width/Height | Map area (0–1023) searched for buildings |
| Units | Checkboxes for building/vehicle types in the group |

**Drag SetRect on map:** Draw a rectangle on the map with the mouse instead of typing coordinates.

### ReinforceGroup

A ReinforceGroup supplies other groups with units (via Vehicle Factories).

| Field | Description |
|---|---|
| Reinforce targets | Text area: one target group per line, format `GroupName=Priority` |
| Units | Checkboxes for factory types |

---

## Dialog: Triggers

Opened via the **Triggers** toolbar button or the "Trigger +" button in the overview.

### Trigger List

Tree with folder grouping. Each trigger shows its condition type and action count.

### Trigger Properties

| Field | Description |
|---|---|
| Name | Unique identifier |
| Folder | Optional folder name for grouping |
| Active at start | Trigger is registered immediately in initProc |
| Trigger only once | Trigger is deactivated after first firing (oneShot) |

### Trigger Conditions

| Type | Fields |
|---|---|
| Time (marks) | Marks (expression field with difficulty preview) |
| Point reached | Player, X, Y |
| Rectangle entered | Player, X, Y, Width, Height |
| Building count | Player, building type, compare, count |
| Vehicle count | Player, compare, count |
| Technology researched | Player, tech ID |
| Resource reached | Player, resource, compare, amount |
| Building operational | Player, building type, compare, count |
| Find unit | List of unit checks (type, X, Y) |

### Action List

Below the condition: list of all trigger actions. Actions can be added, edited, or removed via "+ Add action".

IF blocks can be nested to any depth.

---

## Dialog: Action Editor (If/Then/Else)

Appears when adding or editing an action.

### Action Types

| Type | Fields | Codegen Output |
|---|---|---|
| Empty action (noop) | — | `// (empty action)` |
| Show message | Text | `Game::addMessage(...)` |
| Create unit | Unit type, weapon, X, Y, player | `Game::createUnit(...)` |
| Create another trigger | Target trigger | Calls trigger helper function |
| RecordBuilding | Group, building type, X, Y | `group.recordBuilding(...)` |
| RecordTube line | Group, X→X2, Y→Y2 | `Game::createTube(...)` |
| RecordWall line | Group, wall type, X→X2, Y→Y2 | `Game::createWall(...)` |
| SetTargCount | Group, unit, weapon, target count (expr) | `group.setTargCount(...)` |
| Assign building to group | Group, building type, X, Y, player | `onTick(10, [...takeUnit])` |
| Modify variable | Variable, mode (inc/dec/expr), expression | `var++` / `var--` / `var = expr` |
| If / Then / Else | Conditions, then-actions, else-actions | `if (cond) { ... } else { ... }` |

### IF Conditions (action gating)

Each action can be guarded by one or more conditions (AND/OR):

| Type | Fields |
|---|---|
| Building present at position | Player, building type, X, Y |
| Building damage | Player, building type, compare, value (expr) |
| Player resource | Player, resource, compare, value (expr) |
| Building count | Player, building type, compare, value (expr) |
| Technology researched | Player, tech ID |
| Check variable | Variable (from variable list), compare, value (expr) |

Each condition can be inverted with the **Negate (NOT)** checkbox.

---

## Expression Fields (ExprEdit)

Wherever a plain number field used to appear, there are now **expression fields** that accept either:

- a plain **integer** (`600`), or
- a **C++ expression** containing the identifier `diff` and custom variable names (`ceil(600 * diff / 10)`)

### Difficulty Preview

When `diff` appears in the expression, a live preview is shown directly below the field:

```
Hard: 780  ·  Normal: 600  ·  Easy: 300
```

(calculated using the values from the Setup dialog)

### Supported Functions in Expressions

`ceil`, `floor`, `round`, `abs`, `max`, `min`

### Fields with Expression Support

- Trigger marks (time condition)
- SetTargCount target count
- Player resources (Common Ore, Rare Ore, Food)
- ActionCondition value (playerResource, buildingCount, unitDamage, varCheck)

---

## Code Generation

The editor generates a single C++23 source file (`mission.cpp`) from the model.

### Output Structure

```cpp
// mission.cpp -- generated ...
#include "op2.hpp"
...
using namespace op2;

static const int kDiff[] = {13, 10, 5};
static const int diff = kDiff[(int)Game::difficulty()];

static int myVar = 0;           // custom variables
static bool flagActive = false;

static void make_MyTrigger();   // forward declarations
static Group g_0;               // group variables

extern "C" ... LevelDesc[]      // OP2 DLL exports
extern "C" ... MapName[]
extern "C" ... TechtreeName[]
extern "C" ... DescBlock        // mission type, player count
extern "C" ... DescBlockEx

static void initProc() {
    // player setup
    // base layout (buildings, vehicles, beacons, walls)
    // group initialization
    // start message
    // victory/defeat conditions
    // enable triggers
}

static void make_MyTrigger() {
    onMark(ceil(600 * diff / 10), [] {
        if (myVar >= 3) {
            Game::addMessage("You win!");
        }
    }, /*oneShot=*/true);
}

static void aiProc() {}

extern "C" InitProc() { crash::guard("InitProc", &initProc); }
extern "C" AIProc()   { crash::guard("AIProc",   &aiProc); }
```

### Coordinates

The editor uses 0-based coordinates. The code generator automatically adds +1 to X and Y, since OP2 expects 1-based tile coordinates.

---

## Project Format (Save/Load)

A project is saved as a **folder** containing all files:

```
MyMission/
├── project.json      ← all editor data
├── mission.cpp       ← generated C++ code
└── mission.dll       ← compiled DLL (after Build)
```

### `project.json` — Fields

| Field | Content |
|---|---|
| `mission_name` | Mission name |
| `mission_type` | Integer (MissionType enum) |
| `tech_tree` | Tech tree filename |
| `difficulty` | `{hard, normal, easy}` |
| `variables` | List of `{name, var_type, initial_value}` |
| `map` | Map filename |
| `players` | List of all player configurations |
| `objects` | List of all placed units/buildings |
| `building_groups` | BuildingGroup definitions |
| `reinforce_groups` | ReinforceGroup definitions |
| `triggers` | Trigger definitions (including nested actions) |
| `victories` | Victory conditions |
| `defeats` | Defeat conditions |
| `node_positions` | Timeline node positions (visual layout) |

All fields are backwards-compatible: unknown keys are ignored on load, missing keys receive their default values.
