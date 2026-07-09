# OP2 Mission Editor — Feature Manual

Alpha release. Documentation reflects the current editor state.

## Contents

1. [Main window](#main-window)
2. [Map view](#map-view)
3. [Place panel](#place-panel)
4. [Groups panel](#groups-panel)
5. [Triggers panel](#triggers-panel)
6. [Objects panel](#objects-panel)
7. [Mission overview & validation](#mission-overview--validation)
8. [Dialog: Settings](#dialog-settings)
9. [Dialog: Players](#dialog-players)
10. [Dialog: Victory & Defeat](#dialog-victory--defeat)
11. [Action editor](#action-editor)
12. [Self-healing groups](#self-healing-groups)
13. [Expression fields](#expression-fields)
14. [Code generation](#code-generation)
15. [Project format](#project-format)

---

## Main window

![Main window](docs/images/Main.png)

Three regions:

- **Left sidebar** — the currently active side panel: Place / Triggers / Groups / Objects. Switch tabs at the top.
- **Centre** — the map view.
- **Right sidebar** — the live validation report (top) and the mission overview (bottom).

### Toolbar

| Button | What it does |
|---|---|
| **Settings** | Mission name, mission type, tech tree, difficulty multipliers, custom variables |
| **Players** | Colonies, human/AI, tech levels, resources, pre-researched techs |
| **Victory / Defeat** | Win/lose conditions |
| **Show code** | Preview the generated C++ with syntax highlighting |
| **Build → DLL** | Compile and copy the DLL to the OP2 folder |
| **Test in OP2** | Launch OP2 with this mission via `op2launcher.exe` |
| **Clear objects** | Remove all placed units and buildings |

### Menus

- **File** — Open / Save / Save as project · Choose map · Set output directory · Quit
- **Edit** — Undo / Redo of placement steps
- **View** — Toggle tile grid · Zoom 1:1 · Fit map to window
- **Language** — Automatic (system) · Deutsch · English (applies on next launch)

---

## Map view

### Mouse

| Action | Effect |
|---|---|
| **Left click** | Place the currently selected object; or, without a selection, open the object at that tile for editing |
| **Right click** | Remove an object |
| **Middle drag** | Pan |
| **Wheel** | Zoom in / out |
| **Left drag** | Draw a rectangle (for area-based actions and group build rects), or a straight line (for tube/wall pickers — axis-locked to X or Y so lines stay straight) |

### Visual cues

- **Placement preview** — dashed footprint at the cursor
- **Action line preview** — the tiles a recordTube / recordWall action would place
- **Action area preview** — the rectangle an area-based action operates on, highlighted while the action is expanded
- **Player colours** — six distinct colours (blue / red / green / yellow / purple / cyan)
- **Beacons** in orange, walls / tubes in grey
- Optional 1 px tile grid (View menu)

---

## Place panel

Left sidebar → **Place** tab.

- **Category** — Buildings · Vehicles · Beacons & Walls
- **Unit list** — every placeable type with its tile footprint
- **Player** — 0 – 5
- **Unit name** *(optional)* — gives the unit a script-visible name (e.g. `mainSmelter`), so actions can reference it directly instead of by tile coordinates
- Context parameters that appear per unit:
  - Cargo Truck: cargo type + amount
  - ConVec: kit (which structure it carries)
  - Mining Beacon: ore type (random / common / rare), yield tier
  - Combat vehicles + Guard Post: weapon type

Left-click places, right-click removes.

---

## Groups panel

Left sidebar → **Groups** tab.

![Groups panel](docs/images/Groups.png)

Four group types, each with its own creation button:

### BuildingGroup

Reconstructs buildings inside a rect using its assigned builder units (ConVecs, Robo-Miners, etc.).

| Field | Purpose |
|---|---|
| Name / Folder | Identifier and optional grouping |
| Player | Owner |
| Build rect (X / Y / Width / Height) | Area the group builds in — draggable directly on the map with **Drag SetRect on map** |
| Units | Checkable list of the placed builders that belong to the group |

### ReinforceGroup

Feeds other groups with fresh vehicles from its factories.

| Field | Purpose |
|---|---|
| Reinforce targets | One target-group per line: `GroupName=Priority`. Non-empty priorities have to be ≥ 1 (the engine hangs on priority 0). |
| Units | Checkable list of vehicle factories that belong to the group |

### FightGroup

Predefined combat group. Attack waves (`sendAttackWave`) and group commands reference it by name.

| Field | Purpose |
|---|---|
| Idle area | Fallback / staging area on the map |
| Units | Checkable list of military vehicles belonging to the group |

### MiningGroup

Predefined ore hauling group. A `startMining` action attaches a mine + smelter and sets a truck target count.

| Field | Purpose |
|---|---|
| Idle area | Unload / staging area for the trucks — trucks must be inside this rect at the moment `setupMining` runs, so it typically sits around the smelter |
| Units | Checkable list of Cargo Trucks belonging to the group |

Groups are shown in a tree with optional folder grouping. Any panel that references groups (action editor dropdowns, trigger dropdowns) refreshes automatically when you add or remove one.

---

## Triggers panel

Left sidebar → **Triggers** tab.

![Triggers panel](docs/images/Trigger.png)

The panel has two sections stacked vertically:

1. **Trigger list** with **Add trigger** / **Remove trigger** side by side.
2. Below the selected trigger, two tabs: **Trigger** (the trigger's own cause + settings) and **Actions** (its action list).

### Trigger settings (Trigger tab)

| Field | Purpose |
|---|---|
| Name / Folder | Identifier and optional grouping |
| Active at start | Registered in `initProc` — otherwise created at runtime via a `createTrigger` action |
| One-shot | Auto-disabled after firing once |
| Trigger (cause) | What causes it to fire (see below) |

### Trigger causes

| Cause | Extra fields |
|---|---|
| Time (marks) | Marks (expression, difficulty-aware) |
| Point reached | Player, X, Y |
| Rectangle entered | Player, X, Y, Width, Height |
| Building count | Player, building type, compare, count |
| Vehicle count | Player, compare, count |
| Technology researched | Player, tech ID |
| Resource reached | Player, resource, compare, amount |
| Building operational | Player, building type, compare, count |
| Find unit | List of `(unit type, X, Y)` checks — polls every 10 ticks, fires when *all* checks pass. Useful for "wait until the mine AND the smelter have been built". |

### Actions tab

The action list of the selected trigger. Actions can be added, edited, removed and reordered. If/for blocks nest arbitrarily.

---

## Objects panel

Left sidebar → **Objects** tab. Flat list of every placed unit, building, beacon, wall and tube. Handy for bulk editing / cleanup.

---

## Mission overview & validation

Right sidebar, always visible:

- **Validation** *(top)* — live error/warning report. Updates on every edit. Examples: unused variable, undeclared group referenced by an action, no victory/defeat condition set. Warnings show a count at the bottom (`0 errors, 3 warnings`).
- **Mission overview** *(bottom)* — dynamic tree with the whole mission at a glance:
  - **Flow / Triggers** — trigger execution order with flow arrows (⟶) and cycle detection
  - **Players** — one line per player
  - **Groups** — every BuildingGroup / ReinforceGroup / FightGroup / MiningGroup
  - **Victory / Defeat**
  - **Objects** — total object count

Double-clicking any entry opens the corresponding editor.

---

## Dialog: Settings

Toolbar → **Settings**.

### Basics

| Field | Description |
|---|---|
| Mission name | Shown in OP2's mission list |
| Mission type | Colony · AutoDemo · Tutorial · Multi (Land Rush, Space Race, Resource Race, Midas, Last One Standing) |
| Tech tree file | Path to the technology file (default: `MULTITEK.TXT`) |

### Difficulty

Three integers (Hard / Normal / Easy — defaults 13 / 10 / 5). Available as the `diff` identifier in all [expression fields](#expression-fields).

### Custom variables

Table with **Name · Type (int/bool) · Initial value**. Variables are declared as `static` in the generated C++, persist across save/load, and can be:

- modified by `modVar` actions
- tested by `varCheck` conditions
- referenced in expression fields

---

## Dialog: Players

Toolbar → **Players**.

| Field | Description |
|---|---|
| Colony | Eden or Plymouth |
| Type | Human or AI |
| Tech level | 0 – 12 (12 = all techs pre-granted) |
| Set starting resources | Enables the initResources flag |
| Set colonists explicitly | Workers / Scientists / Kids |
| Set resources explicitly | Common Ore / Rare Ore / Food (expression fields) |
| Pre-researched | Add individual technologies by name |

---

## Dialog: Victory & Defeat

Toolbar → **Victory / Defeat**.

Same condition types as trigger causes (survive time, last one standing, build starship, no CC, building/vehicle count, tech, resource, building operational). Each condition has a description field that becomes the in-game objective text.

Any number of victory and defeat conditions can be combined.

---

## Action editor

Every action added to a trigger opens the inline action form.

### Action kinds

| Kind | Purpose |
|---|---|
| **noop** | Placeholder |
| **If / Then / Else** | Condition block. Can carry a **loop** (`count` — repeat N times; `forEach` — iterate over units matching a source: all / by player / by type / in rect / vehicles-only / buildings-only). Then/else branches nest arbitrarily. Card is colour-outlined (blue = plain If, sky = count, pink = forEach). |
| **Show message** | Text shown to the player |
| **Create unit** | List of unit + weapon + X + Y entries — the action can spawn several units in one shot |
| **Create disaster** | Meteor / Earthquake / Storm / Vortex / Blight / Unblight / Eruption. Position is expression-based (e.g. `randBetween(20, 40)`) |
| **Create another trigger** | Runtime-creates another trigger by name |
| **RecordBuilding** | List of `(building type, cargo, X, Y)` entries recorded into a BuildingGroup |
| **RecordTube line** | List of `(X, Y) → (X2, Y2)` line segments (expanded per-tile in codegen) |
| **RecordWall line** | Same, but with a wall type per entry |
| **SetTargCount** | List of `(unit, weapon, count)` entries — target strength that a linked ReinforceGroup keeps producing |
| **Assign building to group** | Attaches an existing building at (X, Y) to a group — polls until it appears |
| **Modify variable** | inc / dec / assign expression |
| **Start mining** | Attaches mine + smelter to a MiningGroup and sets a Cargo Truck target count. See below. |
| **Send attack wave** | Fills a predefined FightGroup with vehicles and sends it |
| **Group command** | Attack / guard / patrol / add-unit / remove-unit / set idle rect / … per group type |
| **Unit command** | move / patrol / repair / transfer / stop / self-destruct / … on a named unit or on the current loop unit |
| **Defend area** | Macro: patrol + attack in the given rect |
| **Repair buildings** | Macro: keep a ConVec repairing anything damaged in the rect |

### IF conditions (per-action gating)

Any leaf action can be guarded by one or more conditions (AND / OR):

| Kind | Fields |
|---|---|
| Building present at position | Player, building type, X, Y |
| Building damage | Player, building type, compare, value |
| Player resource | Player, resource, compare, value |
| Building count | Player, building type, compare, value |
| Technology researched | Player, tech ID |
| Variable check | Variable, compare, value |
| Loop unit type / damage / cargo / command | (only inside a forEach loop) — inspects the current loop unit |

Each condition has a **Negate (NOT)** checkbox. Nested loops can address the outer or inner level via the loop_level field.

### The `startMining` action in detail

Two use modes, one action:

1. **Direct mode** — mine and smelter already exist. Pick them from the "Mine (placed)" / "Smelter (placed)" dropdowns (auto-fills the X/Y) or type coordinates. Put the action in an always-fire trigger (`Time (marks) = 0`).
2. **Wait mode** — the AI/player still has to build them. Create a trigger with cause = **Find unit** and add two checks: one for the mine tile+type, one for the smelter tile+type. Put the same `startMining` action in that trigger's action list. The action form even shows a live hint spelling out the exact coordinates to use:

  > 💡 To only start once the mine and smelter have been built: create a trigger with the "Unit found" condition and add two checks — the mine's unit type at position (X, Y) and the smelter's unit type at position (X2, Y2). Put this mining action in that trigger's action list.

**Inside a forEach loop?** Switch **Mine** or **Smelter** from "-- Position (X/Y) --" to *"Loop unit (current loop)"* / *"Loop unit (outer loop)"* — the action then uses whatever building the loop is currently on, no coordinates needed. Named units in the "Unit name" field are also selectable.

Target count is a `Group::setTargCount(CargoTruck, ...)` value that a linked ReinforceGroup will replenish over time.

---

## Self-healing groups

The engine automatically rebuilds destroyed structures at the same tile. When a group's factory, mine or smelter is destroyed and rebuilt, the group has to re-attach to the new instance — or it stays broken.

The editor handles this automatically: on every generated mission, a **single mission-wide `onTick(1 mark, …, /*oneShot=*/false)`** timer walks

- every BuildingGroup / ReinforceGroup / MiningGroup roster (re-`takeUnit` any live unit standing on an assigned tile — including replacements)
- every position-based `startMining` action (re-run `setupMining` + `setTargCount` if the mine/smelter is present)

This costs exactly **one** of the engine's 64 callback slots, regardless of how many groups or mining actions the mission has. No opt-in, no configuration — it's on for every mission.

---

## Expression fields

Wherever a numeric input is difficulty-aware, an **expression field** replaces the plain spin box. It accepts either:

- a plain integer (`600`), or
- a C++ expression using the identifier `diff` and custom variables (`ceil(600 * diff / 10)`)

Available functions: `ceil`, `floor`, `round`, `abs`, `max`, `min`. Available randomness: `getRand(N)`, `randBetween(a, b)`.

### Difficulty preview

If `diff` appears in the expression, a live preview shows the computed value for each difficulty:

```
Hard: 780  ·  Normal: 600  ·  Easy: 300
```

Values come from the Settings dialog's Hard / Normal / Easy triple.

### Where expression fields are used

- Trigger marks (Time cause)
- setTargCount count
- Player resources (Common Ore / Rare Ore / Food)
- ActionCondition value (playerResource, buildingCount, unitDamage, varCheck)
- Disaster position (X / Y expressions, e.g. `randBetween(20, 40)`)

---

## Code generation

The editor emits a single self-contained `mission.cpp` targeting the TitanAPI facade.

### File shape

```cpp
// mission.cpp -- generated from the editor model
#include "op2.hpp"
#include "op2/trigger.hpp"
#include "op2/base.hpp"
#include "op2/groups.hpp"
// ...
using namespace op2;

static const int kDiff[] = {5, 10, 13};
static const int diff = kDiff[(int)Player(0).difficulty()];

struct MissionSave {                     // POD, registered via GetSaveRegions()
    int  cbCount = 0;
    unsigned char cbSlot[64] = {};
    int  myCounter = 0;                  // custom variables
    bool _mining_armed_0 = false;        // startMining "armed" flags
    Group _grp_0_BG1{};                  // group handles
    Unit  _unit_mainSmelter{};           // named unit handles
};
static MissionSave g_save;
static int&  myCounter    = g_save.myCounter;
static Group& _grp_0_BG1  = g_save._grp_0_BG1;
// ...

extern "C" __declspec(dllexport) char LevelDesc[]    = "...";
extern "C" __declspec(dllexport) char MapName[]      = "...";
extern "C" __declspec(dllexport) char TechtreeName[] = "MULTITEK.TXT";

static void initProc() {
    // player setup
    // base layout
    // group creation + roster take-in (one-shot)
    // one shared onTick(kTicksPerMark, ...) that re-attaches destroyed-and-rebuilt buildings
    // start message
    // victory / defeat conditions
    // enabled-at-start trigger helpers
}
```

### Coordinates

Editor tiles are 0-based; TitanAPI tiles are 1-based. The generator adds +1 on every X/Y automatically. Every emitted `{ x, y }` literal is what OP2's status bar shows.

### Save-game safety

All persistent state (variables, group handles, unit handles, custom `startMining` armed flags, callback slot table) lives in one trivially-copyable `MissionSave` struct that gets registered with `GetSaveRegions()`. OP2 does **not** call `InitProc` again on load — instead the saved struct is restored byte-for-byte and the callback slot table is re-registered from it.

---

## Project format

A project is a folder:

```
MyMission/
├── project.json     — every editor field
├── mission.cpp      — last-generated C++ (rebuilt on every Build)
└── mission.dll      — compiled mission DLL
```

### `project.json` fields

| Key | Content |
|---|---|
| `mission_name`, `mission_type`, `tech_tree`, `map` | Basic identity |
| `difficulty` | `{hard, normal, easy}` |
| `variables` | List of `{name, var_type, initial_value}` |
| `players` | Full PlayerSpec per player |
| `objects` | Every placed unit / building |
| `beacons`, `walls_tubes` | Map-level features |
| `building_groups`, `reinforce_groups`, `fight_groups`, `mining_groups` | The four group types |
| `triggers` | Trigger definitions including nested actions, conditions and loops |
| `victories`, `defeats` | Win / lose conditions |
| `node_positions` | Timeline node layout (visual state) |

All fields are backwards-compatible: unknown keys are ignored on load, missing keys use the dataclass default. Legacy saved missions without predefined FightGroups or MiningGroups are auto-migrated on open (see `_migrate_wave_fight_groups`, `_migrate_start_mining_groups`).
