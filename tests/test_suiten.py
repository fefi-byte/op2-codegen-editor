"""Die drei Pruefsuiten unter pytest.

Die Suiten bleiben eigenstaendige Skripte (`python mapview/tests/mapgen_test.py`
usw.). Diese Datei macht sie zusaetzlich mit `pytest` lauffaehig -- jede
`check_*`-Gruppe der Kartensuite als eigener Test, damit `pytest -n auto`
(pytest-xdist) sie parallel abarbeiten kann:

    pip install -r requirements-dev.txt
    pytest -n auto

Runs the three check suites under pytest; every check group of the map suite
is its own test so pytest-xdist can run them in parallel.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "mapview"))


def _modul(pfad: Path):
    spec = importlib.util.spec_from_file_location(pfad.stem, pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_KARTEN = _modul(WURZEL / "mapview" / "tests" / "mapgen_test.py")
_GRUPPEN = [n for n in vars(_KARTEN) if n.startswith("check_")]


@pytest.mark.parametrize("gruppe", _GRUPPEN)
def test_karten(gruppe):
    vorher = len(_KARTEN._failures)
    getattr(_KARTEN, gruppe)()
    neu = _KARTEN._failures[vorher:]
    assert not neu, f"rot: {neu}"


def _skript(pfad: Path, **env):
    umgebung = dict(os.environ, **env)
    r = subprocess.run([sys.executable, str(pfad)], cwd=pfad.parent.parent,
                       capture_output=True, text=True, env=umgebung)
    rot = [z for z in r.stdout.splitlines() if z.startswith("FAIL")]
    assert r.returncode == 0, "\n".join(rot) or r.stderr[-2000:]


def test_kartendatei_rundreise():
    _skript(WURZEL / "mapview" / "tests" / "map_roundtrip.py")


def test_editor_oberflaeche():
    _skript(WURZEL / "editor" / "tests" / "ui_smoke.py", QT_QPA_PLATFORM="offscreen")
