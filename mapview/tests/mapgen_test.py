"""Pruefungen fuer "Neue Karte" ueber OP2MappingLib.

Aufruf:  python mapview/tests/mapgen_test.py
Exit 0 = alles gruen.

Erzeugt werden Karten nur noch von OP2MappingLib (C++). Geprueft wird hier
die Anbindung des Editors (`editor/app/maplib.py`): dass jede Vorlage in jeder
Groesse eine Karte liefert, die Regler ankommen, der gelernte Generator mit
Fortschritt und Abbruch laeuft, das Ergebnis eine gueltige .map wird und der
Editor ohne Bibliothek sauber meldet, dass die Kartenfunktionen fehlen. Wie
gut die Karten sind, prueft die Bibliothek in ihren eigenen Tests.

Unter Linux muss OP2MAPLIB_PATH auf eine gebaute libop2maplib.so zeigen.

Checks for "New map" via OP2MappingLib: every template in every size yields a
map, the sliders arrive, the learned generator runs with progress and cancel,
the result is a valid .map, and without the library the editor reports the
map functions as unavailable. Map quality is tested by the library itself.
On Linux OP2MAPLIB_PATH has to point to a built libop2maplib.so.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MAPVIEW = HERE.parent
EDITOR = MAPVIEW.parent / "editor"
for p in (MAPVIEW, EDITOR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import celltypes  # noqa: E402
import mapgen  # noqa: E402
from app import maplib  # noqa: E402
from op2map import Op2Map  # noqa: E402

from spielpfad import karte_lesen, spielordner  # noqa: E402
GAME = spielordner()
_failures: list[str] = []

KLASSISCH = [n for n, t in mapgen.TEMPLATES.items() if not t.get("netz")]
GROESSEN = (64, 128, 256)


def check(name: str, ok, info: str = "") -> bool:
    ok = bool(ok)
    print(("OK  " if ok else "FAIL") + f"  {name}" + (f"  {info}" if info else ""))
    if not ok:
        _failures.append(name)
    return ok


def bibliothek_da() -> bool:
    return maplib.verfuegbar()


def _par(tpl="plains", **kw):
    kw.setdefault("width", 64)
    kw.setdefault("height", 64)
    kw.setdefault("seed", 7)
    return mapgen.MapGenParams.from_template(tpl, **kw)


def _boden_anteil(gen, boden: str) -> float:
    return float(gen.family_share.get(boden, 0.0))


def check_vorlagen_groessen():
    """Jede klassische Vorlage in 64, 128 und 256."""
    for tpl in KLASSISCH:
        for n in GROESSEN:
            t0 = time.perf_counter()
            try:
                gen = maplib.generieren(_par(tpl, width=n, height=n, seed=3))
            except Exception as e:
                check(f"{tpl} {n}x{n} erzeugt", False, f"{type(e).__name__}: {e}")
                continue
            dauer = time.perf_counter() - t0
            check(f"{tpl} {n}x{n} erzeugt", gen.tiles.shape == (n, n)
                  and gen.cells.shape == (n, n), f"{dauer:.1f} s")
            check(f"{tpl} {n}x{n} ueberwiegend befahrbar", gen.passable_share > 0.4,
                  f"{100 * gen.passable_share:.0f} %")


def check_gelernt_groessen():
    """Der gelernte Generator (Vorlage "netz") in 64, 128 und 256, mit Fortschritt."""
    if not check("gelernter Generator verfuegbar", maplib.gelernt_verfuegbar(),
                 "op2maplib mit om_mapgen_generate_learned und profiles/op2-net.bin"):
        return
    for n in GROESSEN:
        stand: list[float] = []
        t0 = time.perf_counter()
        gen = maplib.generieren_gelernt(_par("netz", width=n, height=n, seed=5), "schnell",
                                        maplib.threads_vorgabe(), stand.append)
        dauer = time.perf_counter() - t0
        check(f"gelernt {n}x{n} erzeugt", gen.tiles.shape == (n, n), f"{dauer:.1f} s")
        check(f"gelernt {n}x{n} meldet Fortschritt bis 1",
              len(stand) > 1 and stand[-1] >= 0.999
              and all(b >= a for a, b in zip(stand, stand[1:])),
              f"{len(stand)} Meldungen, letzte {stand[-1] if stand else '-'}")


def check_gelernt_skizze_abbruch():
    if not maplib.gelernt_verfuegbar():
        return
    p = _par("netz", width=128, height=128, seed=9)
    sk = maplib.skizze(p)
    check("Skizze auf halber Aufloesung", sk.wand.shape == (64, 64), str(sk.wand.shape))
    check("Skizzenbild", maplib.skizzenbild(sk).shape == (64, 64, 3))
    gesehen = []
    try:
        maplib.generieren_gelernt(p, "schnell", 2, gesehen.append,
                                  abbruch=lambda: len(gesehen) >= 2)
        check("Abbruch bricht die Rechnung ab", False, "lief zu Ende")
    except maplib.Abgebrochen:
        check("Abbruch bricht die Rechnung ab", True, f"nach {len(gesehen)} Meldungen")
    gut = maplib.generieren_gelernt(_par("netz", seed=2), "gut", 2)
    check("Stufe gut liefert eine Karte", gut.tiles.shape == (64, 64))


def check_determinismus():
    a = maplib.generieren(_par(seed=42))
    b = maplib.generieren(_par(seed=42))
    c = maplib.generieren(_par(seed=43))
    check("gleicher Seed -> gleiche Karte", np.array_equal(a.tiles, b.tiles))
    check("anderer Seed -> andere Karte", not np.array_equal(a.tiles, c.tiles))
    check("gleicher Seed -> gleiche Karte, auch im naechsten Lauf",
          _karte_im_unterprozess(1) == _karte_im_unterprozess(2) == _md5(maplib.generieren(
              _par(width=48, height=48, seed=7))))
    if maplib.gelernt_verfuegbar():
        g1 = maplib.generieren_gelernt(_par("netz", seed=11), "schnell", 1)
        g2 = maplib.generieren_gelernt(_par("netz", seed=11), "schnell", 4)
        check("gelernt: gleicher Seed -> gleiche Karte, auch mit anderen Threads",
              np.array_equal(g1.tiles, g2.tiles))


def _md5(gen) -> str:
    return hashlib.md5(gen.tiles.astype(np.int32).tobytes()).hexdigest()


def _karte_im_unterprozess(hashseed: int) -> str:
    """Kartenpruefsumme aus einem eigenen Prozess mit gesetztem PYTHONHASHSEED."""
    umgebung = dict(os.environ, PYTHONHASHSEED=str(hashseed))
    quelle = ("import sys, hashlib, numpy as np; sys.path[:0] = [{m!r}, {e!r}];"
              "import mapgen; from app import maplib;"
              "g = maplib.generieren(mapgen.MapGenParams.from_template('plains', width=48, height=48, seed=7));"
              "print(hashlib.md5(g.tiles.astype(np.int32).tobytes()).hexdigest())"
              ).format(m=str(MAPVIEW), e=str(EDITOR))
    fertig = subprocess.run([sys.executable, "-c", quelle], cwd=str(MAPVIEW),
                            env=umgebung, capture_output=True, text=True)
    return fertig.stdout.strip().splitlines()[-1] if fertig.stdout.strip() else fertig.stderr


def check_regler():
    """Die Regler kommen in der Bibliothek an."""
    sand = maplib.generieren(_par(width=128, height=128, mix={"san": 0.9, "mud": 0.1}))
    erde = maplib.generieren(_par(width=128, height=128, mix={"mud": 0.9, "san": 0.1}))
    check("Mischung: viel Sand -> mehr Sand",
          _boden_anteil(sand, "san") > _boden_anteil(erde, "san") + 0.3,
          f"{_boden_anteil(sand, 'san'):.2f} gegen {_boden_anteil(erde, 'san'):.2f}")

    sp = maplib.generieren(_par(width=128, height=128, spawns=4))
    check("Startpunkte: vier gesetzt", len(sp.spawns) == 4, str(sp.spawns))
    check("Startpunkte verbunden", sp.connected)

    ohne = maplib.generieren(_par(width=128, height=128, cliffs=0.0, berge=0.0, hochebenen=0))
    mit = maplib.generieren(_par(width=128, height=128, cliffs=0.25, berge=0.0, hochebenen=0))
    check("Klippen: Hochflaeche waechst mit dem Regler",
          mit.plateau_share > ohne.plateau_share + 0.05,
          f"{ohne.plateau_share:.2f} -> {mit.plateau_share:.2f}")

    v = maplib.generieren(_par(width=128, height=128, volcanoes=2))
    check("Vulkane gesetzt", len(v.volcanoes) >= 1, str(v.volcanoes))
    check("Vulkane mit lavaPossible-Zone", v.lava_zones and all(v.lava_zones),
          f"{[len(z) for z in v.lava_zones]}")

    berge = maplib.generieren(_par(width=128, height=128, berge=0.15, hochebenen=2))
    check("Berge: Zonenbericht der Bibliothek", berge.zonen.get("berge", 0) >= 1,
          str(berge.zonen))
    flach = maplib.generieren(_par(width=128, height=128, berge=0.0, hochebenen=0))
    check("ohne Berge kein Zonenbericht", not flach.zonen, str(flach.zonen))

    wenig = maplib.generieren(_par(width=128, height=128, details=0.0))
    viel = maplib.generieren(_par(width=128, height=128, details=1.0))
    check("Details: Regler wirkt", viel.detail_share > wenig.detail_share,
          f"{wenig.detail_share:.3f} -> {viel.detail_share:.3f}")

    land = maplib.generieren(_par("newterra", width=128, height=128, seed=4))
    check("Landschaftsmodus (newterra) liefert Hochland", land.plateau_share > 0.02,
          f"{land.plateau_share:.2f}")


def check_symmetrie():
    for sym in ("mirror_x", "mirror_y", "rot180", "quad"):
        gen = maplib.generieren(_par(width=128, height=128, symmetry=sym, spawns=2 if sym != "quad" else 4))
        befahrbar = np.isin(gen.cells, [k for k, v in celltypes.SPEED_CLASS.items()
                                        if v in ("fast", "medium", "slow")])
        if sym == "mirror_x":
            gespiegelt = befahrbar[:, ::-1]
        elif sym == "mirror_y":
            gespiegelt = befahrbar[::-1, :]
        else:
            gespiegelt = befahrbar[::-1, ::-1]
        gleich = float((befahrbar == gespiegelt).mean())
        check(f"Symmetrie {sym}: Befahrbarkeit gespiegelt", gleich > 0.85, f"{100 * gleich:.0f} %")


def check_merkmale():
    p = _par(width=128, height=128, seed=6)
    p.features = [mapgen.Feature(kind=mapgen.FEAT_TAL, where="w", to="o", size=0.6),
                  mapgen.Feature(kind=mapgen.FEAT_FREI, where="c", size=0.5)]
    gen = maplib.generieren(p)
    check("Merkmale: Tal und Freiflaeche gesetzt",
          gen.features.get("tal", 0) >= 1 and gen.features.get("frei", 0) >= 1, str(gen.features))
    check("Merkmale: Lage gemeldet", len(gen.feature_spots) >= 2, str(gen.feature_spots))


def check_schreibt_karte():
    roh = karte_lesen("cm02.map")
    if not check("Vorlagenkarte gefunden", roh is not None,
                 f"in {GAME} -- OP2_GAME oder game_path in config.ini setzen"):
        return
    for name, gen in (("klassisch", maplib.generieren(_par(seed=3))),
                      ("gelernt", maplib.generieren_gelernt(_par("netz", seed=3))
                       if maplib.gelernt_verfuegbar() else None)):
        if gen is None:
            continue
        m = mapgen.apply_to_map(Op2Map(roh), gen)
        data = m.to_bytes()
        again = Op2Map(data)
        check(f"{name}: erzeugte Karte ist wieder lesbar",
              again.width == 64 and again.height == 64, f"{again.width}x{again.height}")
        check(f"{name}: erzeugte Karte schreibt sich stabil", again.to_bytes() == data)
        check(f"{name}: Kacheln und Zelltypen kamen an",
              all(again.tile_mapping_index(x, y) == int(gen.tiles[y, x])
                  and again.cell_type(x, y) == int(gen.cells[y, x])
                  for y in range(0, 64, 7) for x in range(0, 64, 7)))
        check(f"{name}: TileGroups der Vorlage uebernommen", len(again.tile_groups) > 100,
              f"{len(again.tile_groups)}")


def check_boeden():
    from app.boeden import boeden
    b = boeden()
    check("Boeden = Boeden des Profils",
          b.families == [maplib.profil().ground_id(g) for g in range(maplib.profil().ground_count)],
          str(b.families))
    check("Boeden: Uebergaenge bekannt", int(b.ist_uebergang.sum()) > 100, str(int(b.ist_uebergang.sum())))
    check("Boeden: Vulkanstempel im Profil", len(b.volcanoes) >= 1,
          str([(v.name, v.breite, v.hoehe) for v in b.volcanoes]))
    check("Boeden: Lava und Schnee nicht malbar, Erde/Fels/Sand schon",
          [b.familie_nutzbar(b.families.index(f)) for f in ("lav", "sno", "mud", "roc", "san")]
          == [False, False, True, True, True])


def check_ohne_bibliothek():
    """Ohne Bibliothek: klare Meldung statt Python-Ersatz."""
    umgebung = dict(os.environ, OP2MAPLIB_PATH=str(HERE / "gibt-es-nicht.so"))
    quelle = ("import sys; sys.path[:0] = [{m!r}, {e!r}];"
              "import mapgen; from app import maplib;"
              "print('verfuegbar', maplib.verfuegbar());"
              "\ntry:\n  maplib.generieren(mapgen.MapGenParams())\nexcept RuntimeError as e:\n  print('generieren', e)"
              "\nfrom app.paint_layers import PaintLayers"
              "\ntry:\n  PaintLayers(None)\nexcept RuntimeError as e:\n  print('malen', e)"
              ).format(m=str(MAPVIEW), e=str(EDITOR))
    r = subprocess.run([sys.executable, "-c", quelle], cwd=str(MAPVIEW), env=umgebung,
                       capture_output=True, text=True)
    aus = r.stdout
    check("ohne Bibliothek: nicht verfuegbar", "verfuegbar False" in aus, aus[-300:] + r.stderr[-300:])
    check("ohne Bibliothek: Neue Karte meldet es", "generieren OP2MappingLib nicht verfuegbar" in aus)
    check("ohne Bibliothek: Malen meldet es", "malen OP2MappingLib nicht verfuegbar" in aus)


GRUPPEN = [check_vorlagen_groessen, check_gelernt_groessen, check_gelernt_skizze_abbruch,
           check_determinismus, check_regler, check_symmetrie, check_merkmale,
           check_schreibt_karte, check_boeden, check_ohne_bibliothek]


def main() -> int:
    if not bibliothek_da():
        print("OP2MappingLib fehlt (OP2MAPLIB_PATH setzen) -- " + maplib.fehlt_text())
        return 1
    for g in GRUPPEN:
        g()
    print("\n" + ("Alle Pruefungen gruen." if not _failures
                  else f"{len(_failures)} Pruefung(en) rot: {_failures}"))
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
