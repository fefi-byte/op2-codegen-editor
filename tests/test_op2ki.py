"""op2-ki-Anbindung: der Codegen bindet die KI nur fuer markierte KI-Spieler ein.

op2-ki link: the codegen only wires the AI in for marked AI players.
"""
from __future__ import annotations

import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "codegen"))

from codegen import generate_levelmain  # noqa: E402
from mission_model import Colony, Mission, PlayerSpec  # noqa: E402


def _mission(*spieler):
    return Mission(name="KI Test", map="cm03.map", players=list(spieler))


def test_ohne_op2ki_kein_include():
    cpp = generate_levelmain(_mission(PlayerSpec(), PlayerSpec(is_human=False)))
    assert "op2ki" not in cpp
    assert "Player[1].GoAI();" in cpp


def test_op2ki_spieler():
    ki = PlayerSpec(colony=Colony.Plymouth, is_human=False, op2ki=True, op2ki_rolle=2, op2ki_x=160, op2ki_y=145,
                    op2ki_parameter="testPosten=60000\ntestPostenX=10;testPostenY=20\n# Kommentar\nohneGleich")
    cpp = generate_levelmain(_mission(PlayerSpec(), ki))
    assert '#include "op2ki.hpp"' in cpp
    assert "Player[1].GoHuman();" in cpp   # op2-ki-Spieler laufen als "Human"
    assert ('op2ki::parameterText[1] = "missionsModus=1\\nrolle=2\\ntestPosten=60000\\ntestPostenX=10\\n'
            'testPostenY=20\\n";') in cpp
    assert "op2ki::start(1, MkXY(1, 1), w, h, 160, 145, true, 3, 3, 500);" in cpp
    assert "op2ki::schritt(1);" in cpp


def test_op2ki_mehrspieler_und_kartenmitte():
    ki = PlayerSpec(is_human=False, op2ki=True, op2ki_rolle=0, op2ki_startbasis=False)
    cpp = generate_levelmain(_mission(PlayerSpec(), ki))
    assert "op2ki::parameterText" not in cpp   # Mehrspieler-Gegner ohne Stellschrauben
    assert "op2ki::start(1, MkXY(1, 1), w, h, w / 2, h / 2, false, 3, 3, 500);" in cpp


def test_menschlicher_spieler_nie_op2ki():
    cpp = generate_levelmain(_mission(PlayerSpec(op2ki=True)))
    assert "op2ki" not in cpp
