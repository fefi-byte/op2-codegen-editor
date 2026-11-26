"""Forschungsbaum: Tech-Datei lesen, aendern, schreiben, pruefen.

Braucht die Spielinstallation (config.ini -> game_path); ohne sie werden die
Tests mit den Originaldateien uebersprungen.

Tech tree model tests; the ones using the stock files need the game install.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
for p in (WURZEL / "editor", WURZEL / "codegen", WURZEL / "mapview"):
    sys.path.insert(0, str(p))

import techtree_model as tm  # noqa: E402

BEISPIEL = '''; Kopf
BEGIN_TECH "Alpha" 03401
    CATEGORY        4   ; Kommentar
    COST            800
    MAX_SCIENTISTS  10
    LAB             2
END_TECH

BEGIN_TECH "Beta" 05110
    CATEGORY        6
    DESCRIPTION     "Zwei
Zeilen"
    REQUIRES        03401
    EDEN_COST       2800
    PLYMOUTH_COST   -1
    MAX_SCIENTISTS  12
    LAB             3
    UNIT_PROP CON_TRUCK Hit_Points 375
    PLAYER_PROP Foo 1
END_TECH
; Anhang
'''


def _techs_dir() -> Path | None:
    try:
        import appconfig
        from op2res import content_root
        d = content_root(appconfig.game_path()) / "base" / "techs"
        return d if (d / "multitek.txt").is_file() else None
    except Exception:
        return None


def test_beispiel_rundreise_und_werte():
    tf = tm.parse(BEISPIEL)
    assert tf.text() == BEISPIEL
    a, b = tf.techs
    assert (a.eden_cost, a.plymouth_cost, a.same_cost) == (800, 800, True)
    assert b.description == "ZweiZeilen"
    assert b.requires == [3401] and b.plymouth_cost == -1
    assert b.props == [tm.UnitProp("CON_TRUCK", "Hit_Points", 375)]
    assert any(x.startswith("PLAYER_PROP") for x in b.extra_lines)
    assert not tf.changed()


def test_aendern_schreibt_nur_das_thema_neu(tmp_path):
    tf = tm.parse(BEISPIEL)
    b = tf.get(5110)
    b.props[0].value = 400
    assert tf.changed()
    text = tf.text()
    assert "; Kopf" in text and "; Anhang" in text and "CATEGORY        4   ; Kommentar" in text
    assert "UNIT_PROP CON_TRUCK Hit_Points 400" in text and "PLAYER_PROP Foo 1" in text
    p = tmp_path / "X.TXT"
    p.write_text("alt")
    tf.save(p)
    assert (tmp_path / "X.TXT.bak").read_text() == "alt"
    again = tm.load(p)
    assert again.get(5110).props[0].value == 400 and not again.changed()


def test_nummer_aendern_und_loeschen_ziehen_voraussetzungen_mit():
    tf = tm.parse(BEISPIEL)
    tf.change_id(tf.get(3401), 3402)
    assert tf.get(5110).requires == [3402]
    tf.remove(tf.get(3402))
    assert tf.get(5110).requires == []


def test_neues_thema_einfuegen_und_pruefen():
    tf = tm.parse(BEISPIEL)
    t = tm.Tech(id=tf.free_id(5110), name="Gamma", category=7, requires=[5110],
                eden_cost=1000, plymouth_cost=1000, same_cost=True, max_scientists=10, lab=2)
    tf.add(t, after=tf.get(5110))
    assert t.id == 5111
    text = tf.text()
    assert text.index('"Beta"') < text.index('"Gamma"') < text.index("; Anhang")
    assert "    COST            1000" in tm.format_tech(t, "\n")
    codes = {p.code for p in tm.validate(tm.parse(text))}
    # Plymouth kann Beta nicht erforschen, also Gamma nie erreichen.
    assert "unreachable" in codes


def test_pruefung_findet_fehler():
    tf = tm.parse(BEISPIEL)
    b = tf.get(5110)
    b.requires.append(9999)
    b.props.append(tm.UnitProp("LIGHT_TANK", "Armor", 7))
    b.lab = 5
    a = tf.get(3401)
    a.requires.append(5110)                    # Kreis
    a.name = "x" * (tm.MAX_NAME + 1)
    codes = {p.code for p in tm.validate(tf)}
    assert {"req_missing", "armor", "lab", "cycle", "name_long"} <= codes


def test_anordnung_von_links_nach_rechts():
    tf = tm.parse(BEISPIEL)
    pos = tm.layout(tf.techs)
    assert pos[3401][0] == 0 and pos[5110][0] == 1


@pytest.mark.skipif(_techs_dir() is None, reason="keine Spielinstallation")
@pytest.mark.parametrize("name", ["multitek.txt", "edentek.txt", "ply_tek.txt", "tutortek.txt"])
def test_originale_byte_genau(name):
    d = _techs_dir()
    raw = (d / name).read_bytes()
    tf = tm.load(d / name)
    assert tf.text().encode("latin-1") == raw
    assert not tf.load_problems
    # Neu formatiert ergibt dieselben Werte.
    for t in tf.techs:
        t.raw = None
    again = tm.parse(tf.text())
    assert [t.key() for t in again.techs] == [t.key() for t in tf.techs]
    assert not [p for p in tm.validate(tf) if p.level == "error"]


@pytest.mark.skipif(_techs_dir() is None, reason="keine Spielinstallation")
def test_grundwerte_aus_den_tabellen():
    sheets = tm.read_sheets(_techs_dir().parent / "sheets")
    assert tm.base_value(sheets, "CON_TRUCK", "Hit_Points") is not None
    assert tm.base_value(sheets, "LASER", "Rate_Of_Fire") is not None
    assert "EMP_MISSILE" in sheets
