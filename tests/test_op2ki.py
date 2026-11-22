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


# ---------------------------------------------------------------------------------------- Befehle (Drehbuch/Angriff)
from codegen_op2ki import befehl_text, kurz  # noqa: E402
from mission_model import ActionCondition, TriggerAction, TriggerDef  # noqa: E402


def test_befehl_phase():
    t = befehl_text({"art": "phase", "id": 2, "bauen": [{"typ": "mapTokamak", "n": 2, "x": -1, "y": -1},
                                                       {"typ": "mapGuardPost", "n": 3, "x": 50, "y": 60, "r": 4}],
                     "forschen": [2104, 0], "fahrzeuge": [{"typ": "mapLynx", "waffe": "mapLaser", "n": 4}],
                     "grund": False, "reihe": True})
    assert t == ("phase=2\nbauen=Tokamak:2,GuardPost:3@50,60,4\nforschen=2104\nfahrzeuge=Lynx/Laser:4\n"
                 "grundversorgung=0\nreihenfolge=1\n")


def test_befehl_angriff_verteidigung_frei():
    a = befehl_text({"art": "angriff", "ziel": "spieler", "zielspieler": 0, "angriffsart": "ueberfall",
                     "parallel": True, "emp": "aus", "truppe": "beste", "anzahl": 6, "rueckzug": 40, "frist": 0})
    assert a == "angriff=1\nziel=basis:0\nart=ueberfall\nparallel=1\nemp=0\neinheiten=beste:6\nrueckzug=40\n"
    v = befehl_text({"art": "verteidigung", "truppe": "beste", "anzahl": 5,
                     "bereich": {"x": 10, "y": 20, "width": 8, "height": 6}, "turm": "mapEMP", "patrouille": "an"})
    assert v == "verteidigung=1\nwache=5\nbereich=10,20,17,25\nturm=EMP\npatrouille=1\n"
    assert befehl_text({"art": "befehl", "text": "rolle=2; # aus\nzbWache=6\nkaputt"}) == "rolle=2\nzbWache=6\n"
    assert befehl_text({"art": "drehbuchAus"}) == "drehbuch=0\n"
    assert kurz({"spieler": 1, "art": "angriff", "ziel": "punkt", "angriffsart": "halten"}).startswith("P1: Angriff")


def test_befehl_aktion_bedingung_und_spielstand():
    ki = PlayerSpec(is_human=False, op2ki=True, op2ki_rolle=2)
    m = _mission(PlayerSpec(), ki)
    aktion = TriggerAction(kind="op2ki", op2ki={"spieler": 1, "art": "phase", "id": 1,
                                                 "bauen": [{"typ": "mapTokamak", "n": 1}]})
    wenn = TriggerAction(kind="if", conditions=[ActionCondition(kind="op2kiStatus", player=1, op2ki_code=101,
                                                                compare="cmpGreaterEqual", value="1")],
                         then_actions=[TriggerAction(kind="op2ki", op2ki={"spieler": 1, "art": "drehbuchAus"})])
    m.triggers = [TriggerDef(name="phasen", condition="time", marks=1, actions=[aktion, wenn])]
    cpp = generate_levelmain(m)
    assert 'op2ki::befehl(1, "phase=1\\nbauen=Tokamak:1\\ngrundversorgung=1\\nreihenfolge=0\\n");' in cpp
    assert "op2ki::status(1, 101) >= 1" in cpp
    assert 'op2ki::befehl(1, "drehbuch=0\\n");' in cpp
    assert "op2ki::Speicher op2ki;" in cpp          # Befehle ueberleben Speichern/Laden
    assert "op2ki::speicher(&g_save.op2ki);" in cpp
    assert "op2ki::fortsetzen();" in cpp
