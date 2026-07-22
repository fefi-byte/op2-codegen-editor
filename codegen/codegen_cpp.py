"""C++-Basishelfer: Escaping, Koordinaten (MkXY/MkRect), map_ids, Ausdruecke.

Mechanisch aus codegen.py ausgelagert -- reine Emissions-Helfer,
keine Logikaenderung. / Mechanically split out of codegen.py --
pure emission helpers, no logic changes.
"""

from __future__ import annotations

import re

from mission_model import (
    ActionCondition, BuildingGroupSpec, Colony, Condition, DifficultySetup, FindUnitCheck,
    Mission, MissionType, PlayerSpec, ReinforceGroupSpec, TriggerAction, TriggerDef, VariableDef,
)




def _expr_or_int(v) -> str:
    """Gibt den Wert als C++-Literal-String zurueck: int oder Ausdruck unveraendert."""
    if isinstance(v, str):
        _validate_cpp_expr(v)
        return v
    return str(int(v))




def _validate_cpp_expr(expr: str) -> None:
    """Very small preflight check for obviously broken inline expressions."""
    text = (expr or "").strip()
    if not text:
        return
    pairs = {")": "(", "]": "[", "}": "{"}
    opens = set(pairs.values())
    stack: list[str] = []
    for ch in text:
        if ch in opens:
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                raise ValueError(f"Ungueltiger Ausdruck: {expr}")
            stack.pop()
    if stack:
        raise ValueError(f"Ungueltiger Ausdruck: {expr}")




def _visible_expr(v) -> str:
    """Editor-Tile (0-based) -> sichtbare OP2-Koordinate (1-based), als C++-Ausdruck."""
    if isinstance(v, str):
        _validate_cpp_expr(v)
        return f"(int(({v}) + 1))"
    return str(int(v) + 1)




def _loc_expr(x, y) -> str:
    """Emit a LOCATION literal (engine coords via MkXY) that may contain runtime expressions."""
    return f"MkXY({_visible_expr(x)}, {_visible_expr(y)})"




def _xypos_expr(x, y) -> str:
    """Emit the two-int engine-coordinate pair (XYPos macro) for APIs taking raw tileX, tileY."""
    return f"XYPos({_visible_expr(x)}, {_visible_expr(y)})"


# ---------------------------------------------------------------------------
# Mapping tables: editor strings -> classic SDK enum members. The editor's
# id strings ("mapCommandCenter", "cmpEqual", "resFood") ARE the classic
# Outpost2DLL enum member names, so most mappings are identity.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Mapping tables: editor strings -> classic SDK enum members. The editor's
# id strings ("mapCommandCenter", "cmpEqual", "resFood") ARE the classic
# Outpost2DLL enum member names, so most mappings are identity.
# ---------------------------------------------------------------------------

def _strip_map(name: str) -> str:
    """`mapCommandCenter` -> `CommandCenter`. Empty stays empty."""
    name = (name or "").strip()
    if name.startswith("map"):
        name = name[3:]
    return name




def mapid(name: str) -> str:
    """Editor map id -> classic `map_id` enum member (identical names)."""
    name = (name or "").strip()
    return name if name else "mapNone"




def _resource(name: str) -> str:
    """Editor resource id -> classic `trig_res` enum member (identical names)."""
    name = (name or "").strip()
    return name if name.startswith("res") else "resCommonOre"




def _compare(name: str) -> str:
    """Editor compare id -> classic `compare_mode` enum member (identical names)."""
    name = (name or "").strip()
    return name if name.startswith("cmp") else "cmpGreaterEqual"


# Editor tiles are 0-based (top-left = (0,0)); the visible in-game tiles are
# 1-based. MkXY(visible_x, visible_y) (OP2Helper) converts visible -> engine
# LOCATION (adds +31/-1). Use _xy() everywhere the generator emits a LOCATION.




# Editor tiles are 0-based (top-left = (0,0)); the visible in-game tiles are
# 1-based. MkXY(visible_x, visible_y) (OP2Helper) converts visible -> engine
# LOCATION (adds +31/-1). Use _xy() everywhere the generator emits a LOCATION.
def _xy(x: int, y: int) -> str:
    return f"MkXY({int(x) + 1}, {int(y) + 1})"




def _xypos(x: int, y: int) -> str:
    """Two-int engine-coordinate pair for APIs taking raw tileX, tileY."""
    return f"XYPos({int(x) + 1}, {int(y) + 1})"




def _rect(x1: int, y1: int, x2: int, y2: int) -> str:
    """MAP_RECT literal (engine coords via MkRect)."""
    return f"MkRect({int(x1) + 1}, {int(y1) + 1}, {int(x2) + 1}, {int(y2) + 1})"


# UnitEx::GetLastCommand() liefert HFLs CommandType (ct*-Konstanten); der
# Editor speichert die Kurznamen ("Move", "Attack", ...).
# UnitEx::GetLastCommand() returns HFL's CommandType (ct* constants); the
# editor stores the short names ("Move", "Attack", ...).
_CMD_TYPE = {
    "Nop": "ctNop",
    "Move": "ctMoMove",
    "Stop": "ctMoStop",
    "Idle": "ctMoIdle",
    "Unidle": "ctMoUnidle",
    "Attack": "ctMoAttackObj",
    "Guard": "ctMoGuard",
    "Patrol": "ctMoPatrol",
    "RepairObj": "ctMoRepairObj",
    "Reprogram": "ctMoReprogram",
    "Dismantle": "ctMoDismantle",
    "Build": "ctMoBuild",
    "Develop": "ctMoDevelop",
    "UnDevelop": "ctMoUnDevelop",
    "Dock": "ctMoDock",
    "Transfer": "ctMoTransfer",
    "Research": "ctMoResearch",
    "SelfDestruct": "ctMoSelfDestruct",
}


# Expands a straight line segment (recordTube/recordWall) into its individual
# tiles -- same algorithm as the map-preview drawing in
# editor/app/window_map_pick.py's _line_tiles(), kept in sync so the tiles the
# UI shows as "planned" are exactly the tiles the generated C++ creates.




# Expands a straight line segment (recordTube/recordWall) into its individual
# tiles -- same algorithm as the map-preview drawing in
# editor/app/window_map_pick.py's _line_tiles(), kept in sync so the tiles the
# UI shows as "planned" are exactly the tiles the generated C++ creates.
def _line_tiles(x1: int, y1: int, x2: int, y2: int) -> list[tuple[int, int]]:
    tiles = []
    if abs(x2 - x1) >= abs(y2 - y1):
        step = 1 if x2 >= x1 else -1
        for x in range(x1, x2 + step, step):
            tiles.append((x, y1))
        if y2 != y1:
            step_y = 1 if y2 >= y1 else -1
            for y in range(y1 + step_y, y2 + step_y, step_y):
                tiles.append((x2, y))
    else:
        step = 1 if y2 >= y1 else -1
        for y in range(y1, y2 + step, step):
            tiles.append((x1, y))
        if x2 != x1:
            step_x = 1 if x2 >= x1 else -1
            for x in range(x1 + step_x, x2 + step_x, step_x):
                tiles.append((x, y2))
    return tiles


# ---------------------------------------------------------------------------
# String helpers.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# String helpers.
# ---------------------------------------------------------------------------

def _cpp_string(text: str) -> str:
    """Escape a Python string for a C++ string literal."""
    if text is None:
        return '""'
    out = (text.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t"))
    return f'"{out}"'




def _ident(text: str) -> str:
    """Lower the chance of a generated identifier colliding with a C++ keyword."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text or "")
    s = s.strip("_") or "id"
    if s[0].isdigit():
        s = "_" + s
    return s




def _mission_type_literal(mt: MissionType) -> str:
    """Map MissionType IntEnum -> classic `MissionTypes` enum member."""
    name = {
        MissionType.Colony: "Colony",
        MissionType.AutoDemo: "AutoDemo",
        MissionType.Tutorial: "Tutorial",
        MissionType.MultiLandRush: "MultiLandRush",
        MissionType.MultiSpaceRace: "MultiSpaceRace",
        MissionType.MultiResourceRace: "MultiResourceRace",
        MissionType.MultiMidas: "MultiMidas",
        MissionType.MultiLastOneStanding: "MultiLastOneStanding",
    }.get(mt, "Colony")
    return name


# ---------------------------------------------------------------------------
# Code emission.
# ---------------------------------------------------------------------------
