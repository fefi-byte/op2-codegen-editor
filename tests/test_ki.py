"""Aufbau-KI: Codegen bindet sie ein, die Spur ist lesbar, der C++-Kern uebersetzt.

Building AI: the codegen wires it in, the trace parses, the C++ core compiles
(the compile check runs only when the `ziglang` package is installed --
`pip install ziglang`; it cross-compiles for 32-bit Windows like the game).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
for _p in ("codegen", "mapview", "."):
    sys.path.insert(0, str(WURZEL / _p))

from mission_model import Colony, Mission, PlayerSpec  # noqa: E402
import codegen  # noqa: E402


def _mission(**ki):
    return Mission(name="KI Test", map="test.map", num_players=2, map_width=64, map_height=64,
                   players=[PlayerSpec(colony=Colony.Eden, is_human=True),
                            PlayerSpec(colony=Colony.Plymouth, is_human=False, **ki)])


def test_codegen_bindet_ki_ein():
    cpp = codegen.generate_levelmain(_mission(ki_aufbau=True, ki_x=40, ki_y=30))
    assert '#include "op2_ki.hpp"' in cpp
    assert "ki::Zustand ki_1;" in cpp                       # im Spielstand
    assert "ki::start(g_save.ki_1, 1, MkXY(1, 1), 64, 64, 40, 30, true);" in cpp
    assert "ki::schritt(g_save.ki_1);" in cpp


def test_codegen_ohne_ki_unveraendert():
    cpp = codegen.generate_levelmain(_mission())
    assert "op2_ki" not in cpp and "ki::" not in cpp


def test_menschlicher_spieler_bekommt_keine_ki():
    m = _mission(ki_aufbau=True)
    m.players[0].ki_aufbau = True                            # Mensch: wird ignoriert
    cpp = codegen.generate_levelmain(m)
    assert "ki_0" not in cpp and "ki_1" in cpp


def test_kartenmitte_als_standard():
    cpp = codegen.generate_levelmain(_mission(ki_aufbau=True))
    assert "64, 64, 32, 32, true" in cpp


def test_spur_lesen():
    sys.path.insert(0, str(WURZEL / "editor"))
    pytest.importorskip("PySide6")
    from app.ki_spur import lese_spur, stand_bei
    zeilen = [
        {"t": 0, "art": "start", "p": 1, "bx": 10, "by": 10},
        {"t": 200, "art": "stand", "p": 1, "erz": 1},
        {"t": 0, "art": "start", "p": 1, "bx": 20, "by": 20},          # neuer Lauf
        {"t": 0, "art": "start", "p": 2, "bx": 50, "by": 50},          # zweiter KI-Spieler
        {"t": 200, "art": "stand", "p": 1, "erz": 2},
        {"t": 400, "art": "stand", "p": 1, "erz": 3},
        {"t": 210, "art": "entscheid", "p": 1, "was": "bau"},
    ]
    text = "\n".join(json.dumps(z) for z in zeilen) + "\nmuell\n{kaputt\n"
    spur = lese_spur(text)
    assert spur.spieler == [1, 2]
    assert spur.starts[1]["bx"] == 20
    assert [s["erz"] for s in spur.staende] == [2, 3]
    assert spur.fehlerhaft == 1
    assert stand_bei(spur, 300, 1)["erz"] == 2
    assert stand_bei(spur, 100, 1) is None


def test_cpp_uebersetzt(tmp_path):
    """Generierte Mission mit KI fuer 32-Bit-Windows uebersetzen (MinGW-Ziel)."""
    pytest.importorskip("ziglang")
    if not (WURZEL / "OP2MissionSDK" / "Outpost2DLL" / "Outpost2DLL.h").exists():
        pytest.skip("OP2MissionSDK nicht ausgecheckt (git submodule update --init --recursive)")
    vorlagen = WURZEL / "editor" / "app" / "templates"
    (tmp_path / "mission.cpp").write_text(
        codegen.generate_levelmain(_mission(ki_aufbau=True, ki_x=40, ki_y=30)), encoding="utf-8")
    for name in ("op2_ki.hpp", "op2_crash.hpp"):
        (tmp_path / name).write_text((vorlagen / name).read_text(encoding="utf-8"), encoding="utf-8")
    # op2_log deklariert Win32-Funktionen selbst (passend zu MSVC); MinGWs windows.h
    # typisiert sie strenger. Fuer die Pruefung die eigenen Deklarationen durch windows.h ersetzen.
    log = (vorlagen / "op2_log.hpp").read_text(encoding="utf-8")
    a = log.index('extern "C" {')
    b = log.index("}", a)
    log = log[:a] + "}\n#include <windows.h>\nnamespace op2::log {\n" + log[b + 1:]
    log = log.replace("GetLocalTime(st);", "GetLocalTime((SYSTEMTIME*)st);")
    (tmp_path / "op2_log.hpp").write_text(log, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "ziglang", "c++", "-target", "x86-windows-gnu", "-std=c++17", "-c",
         "-o", str(tmp_path / "mission.obj"), "-fms-extensions", "-Wall", "-Wno-unknown-pragmas",
         "-Wno-unused-function", "-Wno-unused-variable",
         f"-I{WURZEL / 'OP2MissionSDK'}", f"-I{tmp_path}", str(tmp_path / "mission.cpp")],
        capture_output=True, text=True, timeout=600)
    fehler = [z for z in r.stderr.splitlines() if "error" in z or ("warning:" in z and "OP2MissionSDK" not in z)]
    assert r.returncode == 0 and not fehler, "\n".join(fehler[:20]) or r.stderr[-2000:]
