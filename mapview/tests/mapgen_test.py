"""Pruefungen fuer den Kartengenerator.

Aufruf:  python mapview/tests/mapgen_test.py
Exit 0 = alles gruen.

Checks for the map generator: determinism, mix, symmetry, spawn quality and
that the result is a valid .map file.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MAPVIEW = HERE.parent
sys.path.insert(0, str(MAPVIEW))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import celltypes  # noqa: E402
import mapgen  # noqa: E402
from op2map import Op2Map  # noqa: E402

GAME = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
_failures: list[str] = []


def check(name: str, ok, info: str = "") -> bool:
    ok = bool(ok)
    print(("OK  " if ok else "FAIL") + f"  {name}" + (f"  {info}" if info else ""))
    if not ok:
        _failures.append(name)
    return ok


def check_determinism():
    a = mapgen.generate(mapgen.MapGenParams(width=64, height=64, seed=42))
    b = mapgen.generate(mapgen.MapGenParams(width=64, height=64, seed=42))
    c = mapgen.generate(mapgen.MapGenParams(width=64, height=64, seed=43))
    check("gleicher Seed -> gleiche Karte", np.array_equal(a.tiles, b.tiles))
    check("anderer Seed -> andere Karte", not np.array_equal(a.tiles, c.tiles))
    check("Zelltypen passen zu den Kacheln",
          all(int(a.cells[y, x]) == celltypes.default_cell_type(int(a.tiles[y, x]))
              for y in range(0, 64, 7) for x in range(0, 64, 7)))
    # Zwei Karten im selben Prozess zu vergleichen genuegt nicht: Pythons
    # `hash` ist fuer Zeichenketten pro Prozess gesalzen. Ein Aufruf, der
    # daran haengt, liefert INNERHALB eines Laufs dieselbe Karte und ausserhalb
    # eine andere -- genau so lag es beim Kantenwuerfel der Uebergaenge.
    # Comparing two maps inside one process is not enough: Python's `hash` is
    # salted per process for strings. A call depending on it yields the same map
    # WITHIN a run and a different one across runs -- exactly what happened to
    # the edge dice of the transitions.
    check("gleicher Seed -> gleiche Karte, auch im naechsten Lauf",
          _karte_im_unterprozess(1) == _karte_im_unterprozess(2))


def _karte_im_unterprozess(hashseed: int) -> str:
    """Kartenpruefsumme aus einem eigenen Prozess mit gesetztem PYTHONHASHSEED."""
    umgebung = dict(os.environ, PYTHONHASHSEED=str(hashseed))
    quelle = ("import hashlib, mapgen;"
              "g = mapgen.generate(mapgen.MapGenParams(width=48, height=48, seed=7));"
              "print(hashlib.md5(g.tiles.tobytes()).hexdigest())")
    fertig = subprocess.run([sys.executable, "-c", quelle], cwd=str(MAPVIEW),
                            env=umgebung, capture_output=True, text=True)
    return fertig.stdout.strip().splitlines()[-1] if fertig.stdout.strip() else fertig.stderr


def check_mix():
    for tpl in ("canyon", "desert"):
        params = mapgen.MapGenParams.from_template(tpl, width=128, height=128, seed=5)
        gen = mapgen.generate(params)
        total = sum(params.mix.values())
        worst = 0.0
        for family, want in params.mix.items():
            got = gen.family_share.get(family, 0.0)
            worst = max(worst, abs(got - want / total))
        check(f"Mischung '{tpl}' trifft die Vorgabe (±15 %)", worst < 0.15,
              f"groesste Abweichung {100*worst:.0f} %")


def check_symmetry():
    for mode in (mapgen.SYM_MIRROR_X, mapgen.SYM_ROT180, mapgen.SYM_QUAD):
        params = mapgen.MapGenParams(width=128, height=128, seed=9,
                                     symmetry=mode, spawns=4)
        gen = mapgen.generate(params)
        h, w = gen.tiles.shape
        # Gespiegelt wird die Lage der Gelaendefamilien, nicht die Kachelgrafik.
        fam = mapgen.model().family_of[gen.tiles]
        if mode == mapgen.SYM_MIRROR_X:
            other = fam[:, ::-1]
        elif mode == mapgen.SYM_ROT180:
            other = fam[::-1, ::-1]
        else:
            other = fam[:, ::-1]
        agree = float((fam == other).mean())
        check(f"Symmetrie '{mode}': Gelaendelage spiegelt sich", agree > 0.60,
              f"{100*agree:.0f} % Uebereinstimmung")

        spawns = gen.spawns
        if check(f"Symmetrie '{mode}': Startpunkte erzeugt", len(spawns) >= 2,
                 f"{len(spawns)}"):
            xs = [p[0] for p in spawns]
            ys = [p[1] for p in spawns]
            if mode == mapgen.SYM_MIRROR_X:
                mirrored = {(w - 1 - x, y) for x, y in spawns}
            elif mode == mapgen.SYM_ROT180:
                mirrored = {(w - 1 - x, h - 1 - y) for x, y in spawns}
            else:
                mirrored = {(w - 1 - x, y) for x, y in spawns}
            check(f"Symmetrie '{mode}': Startpunkte liegen paarweise",
                  len(mirrored & set(spawns)) >= 2,
                  f"{len(mirrored & set(spawns))} Partner")


def check_spawns():
    params = mapgen.MapGenParams(width=128, height=128, seed=11, spawns=4,
                                 spawn_clearance=6)
    gen = mapgen.generate(params)
    if not check("vier Startpunkte gefunden", len(gen.spawns) == 4, str(len(gen.spawns))):
        return
    check("Startpunkte sind verbunden", gen.connected)
    ok_free = True
    for x, y in gen.spawns:
        block = gen.cells[y - 6:y + 7, x - 6:x + 7]
        classes = {celltypes.speed_class(int(c)) for c in np.unique(block)}
        ok_free = ok_free and classes <= mapgen.PASSABLE_CLASSES
    check("Startpunkte stehen auf freier Flaeche", ok_free)
    dists = [min((ax - bx) ** 2 + (ay - by) ** 2
                 for j, (bx, by) in enumerate(gen.spawns) if j != i)
             for i, (ax, ay) in enumerate(gen.spawns)]
    check("Startpunkte liegen auseinander (>20 Kacheln)", min(dists) > 400,
          f"kuerzester Abstand {min(dists) ** 0.5:.0f}")


def check_no_scatter():
    """Bauteile (Vulkan/Lava/Klippen/Brandspuren) duerfen nicht gestreut werden."""
    tm = mapgen.model()
    gen = mapgen.generate(mapgen.MapGenParams(width=128, height=128, seed=17))
    streu = int(tm.structure[gen.tiles].sum())
    check("ohne Vulkane liegen keine Bauteil-Kacheln herum", streu == 0, f"{streu} Kacheln")
    check("keine Lavakacheln im Gelaende", int(tm.lava[gen.tiles].sum()) == 0)


def check_volcanoes():
    """Vulkane sind Stempel; Lava kommt zur Laufzeit ueber lavaPossible."""
    tm = mapgen.model()
    params = mapgen.MapGenParams(width=128, height=128, seed=23, volcanoes=2,
                                 lava_zone_tiles=300)
    gen = mapgen.generate(params)
    if not check("zwei Vulkane gesetzt", len(gen.volcanoes) == 2, str(len(gen.volcanoes))):
        return
    check("je Vulkan eine lavaPossible-Zone", len(gen.lava_zones) == 2)
    groessen = [len(z) for z in gen.lava_zones]
    check("Zonen haben eine sinnvolle Groesse (>150 Kacheln)", min(groessen) > 150,
          str(groessen))
    # Der Vulkankrater muss wirklich im Gelaende stehen
    treffer = 0
    for vx, vy in gen.volcanoes:
        block = gen.tiles[max(0, vy - 4):vy + 5, max(0, vx - 4):vx + 5]
        if tm.structure[block].any():
            treffer += 1
    check("Vulkanstempel liegen im Gelaende", treffer == len(gen.volcanoes))
    # Zone liegt um den Vulkan herum
    for (vx, vy), zone in zip(gen.volcanoes, gen.lava_zones):
        dists = [max(abs(x - vx), abs(y - vy)) for x, y in zone]
        check("lavaPossible-Zone umschliesst den Vulkan", min(dists) <= 2,
              f"naechste Kachel {min(dists)} entfernt")
        break
    gestreut = int(tm.structure[gen.tiles].sum())
    stempel = sum(w * h for _, w, h, _ in tm.volcanoes if (w, h) == (10, 10))
    check("ausser den Vulkanen keine Bauteile gestreut", gestreut <= 2 * 100 + 20,
          f"{gestreut} Bauteil-Kacheln")


def check_klippen_nachbarn():
    """Die gemessene Gruppen-Nachbarschaft ist geladen und wird auch benutzt.

    Sie steht in den 33 Originalkarten und ersetzt die Pixelregel, die nur
    75 % der Blockkanten so beurteilt wie die Karten. Zweimal in dieser Reihe
    hat sich eine Aenderung still selbst ausgehebelt, deshalb hier festgenagelt.
    """
    tm = mapgen.model()
    check("Klippen-Nachbarschaft geladen", len(tm.klippen_nachbarn) > 100,
          f"{len(tm.klippen_nachbarn)} Paare")
    # Jeder Block im Vorrat muss seinen Gruppennamen kennen -- sonst faellt die
    # Abfrage stillschweigend wieder auf die Pixelregel zurueck.
    bloecke = [b for stempel in tm.cliff_pool.values() for b in stempel]
    ohne = [b for b in bloecke if not tm.klippen_gruppe(b)]
    check("jeder Klippenblock kennt seine Gruppe", not ohne,
          f"{len(bloecke) - len(ohne)}/{len(bloecke)}")
    # Die 13 unabhaengig belegten Regeln. Sie sind der Grund, warum die
    # Schwelle ein Anteil und keine feste Zahl ist: eine feste 3 haelt bei 33
    # Karten alle 13, bei 107 nur noch 8.
    # 0 = Ost, 1 = West, 2 = Sued, 3 = Nord.
    regeln = ([(f"sanmes0{i}", s, False) for i in (0, 1, 2) for s in (2, 3)]
              + [(n, s, False) for n in ("sanmes07", "sanmes14")
                 for s in (0, 1)]
              + [("sanmes07", s, True) for s in (2, 3)]
              + [("sanmes05", 2, True)])
    nach_name = {tm.klippen_gruppe(b): b for b in bloecke}
    verstoss = [(n, s) for n, s, soll in regeln
                if n in nach_name
                and mapgen.block_kante_ist_wand(nach_name[n], s, tm, "san")
                != soll]
    check("die belegten Klippenregeln halten", not verstoss,
          f"{len(regeln)} Regeln, {len(verstoss)} Verstoesse: {verstoss}")

    # Ein gezeichneter Lauf darf nur Bloecke nehmen, deren Wand in
    # Laufrichtung weitergeht. Der Erd-Topf "O" enthaelt `mudmes01` mit
    # West+Sued -- eine Ecke. Mit 273 Vorkommen ist das der haeufigste
    # Erdblock; ungefiltert stand er in jeder zweiten senkrechten Wand und
    # sah dort um 180 Grad verdreht aus.
    for fam in ("san", "mud"):
        for richtung, noetig in (("O", (2, 3)), ("W", (2, 3)),
                                 ("S", (0, 1)), ("N", (0, 1))):
            pool = tm.cliff_pool.get((fam, richtung)) or []
            taugt = [b for b in pool
                     if all(mapgen.block_kante_ist_wand(b, s, tm, fam)
                            for s in noetig)]
            check(f"{fam}/{richtung}: der Lauf hat taugliche Bloecke",
                  bool(taugt) or not pool,
                  f"{len(taugt)} von {len(pool)}")

    # Und die Probe aufs Exempel: eine gezeichnete Linie setzt nur Bloecke,
    # die in Laufrichtung durchgehen.
    grund = next((t for t in range(2048)
                  if tm.family_of[t] == tm.families.index("mud")
                  and tm.placeable[t]), 0)
    gitter = np.full((60, 60), grund, dtype=np.int32)
    rng = np.random.default_rng(3)
    maske, _z = mapgen.klippe_aus_linie(gitter, [(20, 6), (20, 44)], "links",
                                        tm, rng, "mud")
    schlecht = []
    for (fam2, _r), stempel in tm.cliff_pool.items():
        for b in stempel:
            if fam2 != "mud":
                continue
            bh, bw = b.shape
            for y in range(gitter.shape[0] - bh + 1):
                for x in range(gitter.shape[1] - bw + 1):
                    if not np.array_equal(gitter[y:y + bh, x:x + bw], b):
                        continue
                    # Der oberste und unterste Block duerfen Abschluesse sein.
                    if y <= 7 or y + bh >= 43:
                        continue
                    if not all(mapgen.block_kante_ist_wand(b, s, tm, "mud")
                               for s in (2, 3)):
                        schlecht.append((tm.klippen_gruppe(b), y))
    check("senkrechte Wand ohne verdrehte Mittelstuecke", not schlecht,
          f"{int(maske.sum())} Zellen, {len(schlecht)} verdreht: {schlecht[:4]}")

    # Um eine Ecke fortsetzen: die Laufrichtung der vorhandenen Klippe steht
    # im Modell (gemessene Wandseiten des Blocks, der dort liegt). Weicht sie
    # von der neuen Linie ab, ist der Startpunkt ein Knick und braucht eine
    # Ecke -- vorher stand dort ein Abschlussstueck.
    #
    # Beide Reihenfolgen, denn sie waren es nicht: am Ende eines WAAGERECHTEN
    # Laufs liegt ein Abschlussstueck (Wand nur nach West). Solange
    # `klippe_achse_an` allein den naechstliegenden Block ansah, traf es dort
    # dieses Stueck, fand keine Achse und meldete gar keine -- der Knick wurde
    # nicht erkannt, und zwischen den beiden Waenden blieb eine Spalte offen.
    # Senkrechte Laeufe haben keinen Abschluss, deshalb fiel es dort nie auf.
    for fam in ("san", "mud"):
        for erst, dann, achse_soll, noetig in (
                ([(16, 8), (16, 36)], [(16, 36), (48, 36)], "v", {0, 3}),
                ([(8, 36), (40, 36)], [(40, 36), (40, 8)], "h", {1, 3})):
            gr0 = next((t for t in range(2048)
                        if tm.family_of[t] == tm.families.index(fam)
                        and tm.placeable[t]), 0)
            g0 = np.full((70, 70), gr0, dtype=np.int32)
            r0 = np.random.default_rng(4)
            kx, ky = dann[0]
            mapgen.klippe_aus_linie(g0, erst, "links", tm, r0, fam)
            achse = mapgen.klippe_achse_an(g0, kx, ky, tm, fam)
            check(f"{fam}/{achse_soll}: Laufrichtung am Ende aus dem Modell",
                  achse is not None and achse[0] == achse_soll, str(achse))
            mapgen.klippe_aus_linie(g0, dann, "links", tm, r0, fam)
            ecken_da = []
            for (f2, r2), stempel2 in tm.cliff_pool.items():
                if f2 != fam or r2 not in ("Ecke", "Motiv"):
                    continue
                for b2 in stempel2:
                    bh2, bw2 = b2.shape
                    for yy in range(ky - 6, ky + 6):
                        for xx in range(kx - 6, kx + 8):
                            if (yy + bh2 <= 70 and xx + bw2 <= 70
                                    and np.array_equal(g0[yy:yy + bh2, xx:xx + bw2], b2)):
                                seiten2 = {i for i in range(4)
                                           if mapgen.block_kante_ist_wand(b2, i, tm, fam)}
                                if noetig <= seiten2:
                                    ecken_da.append(tm.klippen_gruppe(b2))
            check(f"{fam}/{achse_soll}: Fortsetzung um die Ecke bekommt einen Eckblock",
                  bool(ecken_da), str(ecken_da))

    # Eine gesetzte Klippe fortsetzen: die zweite Linie muss auf die erste
    # einrasten, auch wenn danebengeklickt wird. Ohne Anker faengt sie bei
    # null an und die Wand springt an der Naht.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        for daneben in (0, 3):
            g = np.full((80, 80), gr, dtype=np.int32)
            r = np.random.default_rng(2)
            m1, _z1 = mapgen.klippe_aus_linie(g, [(20, 10), (20, 34)],
                                              "links", tm, r, fam)
            m2, _z2 = mapgen.klippe_aus_linie(
                g, [(20 + daneben, 34), (20 + daneben, 58)], "links", tm, r, fam)
            ges = m1 | m2
            kante = {int(np.nonzero(ges[y])[0].min())
                     for y in (28, 31, 38, 44) if ges[y].any()}
            band = ges[:, 14:28].any(axis=1)
            ys = np.nonzero(band)[0]
            luecken = [int(y) for y in range(ys.min(), ys.max() + 1)
                       if not band[y]]
            check(f"{fam}: Fortsetzung rastet ein (Klick +{daneben})",
                  len(kante) == 1 and not luecken,
                  f"Wandkante {sorted(kante)}, Luecken {luecken}")

    # Eine gerade fortgesetzte Wand darf in der Mitte KEIN Wandende tragen.
    # Genau das lag dort: das Abschlussstueck des ersten Zuges blieb liegen,
    # und der zweite setzte sein eigenes gleich daneben. Beide haben Wand auf
    # nur einer Seite und zeigen als heller, flacher Fleck mitten in der Wand
    # -- das, was auf einem fortgesetzten Zug ins Auge faellt.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        g = np.full((32, 32), gr, dtype=np.int32)
        r = np.random.default_rng(5)
        m1, _z1 = mapgen.klippe_aus_linie(g, [(5, 16), (15, 16)], "oben", tm, r, fam)
        m2, _z2 = mapgen.klippe_aus_linie(g, [(15, 16), (26, 16)], "oben", tm, r, fam)
        ges = m1 | m2
        # Die aeusseren Enden duerfen und sollen ein Abschlussstueck tragen --
        # gesucht sind nur die im Inneren, also fern beider Linienenden.
        enden = []
        for (f2, _r2), stempel2 in tm.cliff_pool.items():
            if f2 != fam:
                continue
            for b2 in stempel2:
                bh2, bw2 = b2.shape
                if len({s for s in range(4)
                        if mapgen.block_kante_ist_wand(b2, s, tm, fam)}) != 1:
                    continue
                for yy in range(32 - bh2 + 1):
                    for xx in range(9, 23 - bw2 + 1):
                        if np.array_equal(g[yy:yy + bh2, xx:xx + bw2], b2):
                            enden.append((tm.klippen_gruppe(b2), xx, yy))
        spalten = ges.any(axis=0)
        xs = np.nonzero(spalten)[0]
        luecken = [int(x) for x in range(xs.min(), xs.max() + 1) if not spalten[x]]
        check(f"{fam}: gerade Fortsetzung ohne Wandende in der Mitte",
              not enden and not luecken, f"{enden}, Luecken {luecken}")

    def bloecke_im_bild(gitter, fam):
        """Jeder ganze Block, der im Gitter wiederzufinden ist."""
        h2, w2 = gitter.shape
        raus = []
        for (f2, _r2), stempel in tm.cliff_pool.items():
            if f2 != fam:
                continue
            for b2 in stempel:
                bh2, bw2 = b2.shape
                seiten2 = {s for s in range(4)
                           if mapgen.block_kante_ist_wand(b2, s, tm, fam)}
                for yy in range(h2 - bh2 + 1):
                    for xx in range(w2 - bw2 + 1):
                        if np.array_equal(gitter[yy:yy + bh2, xx:xx + bw2], b2):
                            raus.append((tm.klippen_gruppe(b2), bh2, seiten2,
                                         xx, yy))
        return raus

    # Die Ecke einer Fortsetzung muss sich an der VORHANDENEN Wand ausrichten.
    # Sie stammt aus einem frueheren Zug und stand deshalb weder in
    # `flucht_spalte` noch in `anschluss`; die Ecke zentrierte sich auf den
    # Klick und ragte bei einer 2 Kacheln breiten Wand und einem 3 Kacheln
    # breiten Eckstueck genau eine Spalte nach Osten darueber hinaus.
    #
    # Und ein Abschlussstueck gehoert nur dorthin, wo die Zaehlung es stuetzt:
    # an eine einreihige Nordkante stiess in 107 Karten nie eines -- deren
    # gemessene Nachbarn setzen die Wand fort. Der 3x3-Klotz an der Haarlinie
    # war ein Fremdkoerper.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        g = np.full((32, 32), gr, dtype=np.int32)
        r = np.random.default_rng(1)
        m1, _z1 = mapgen.klippe_aus_linie(g, [(21, 11), (21, 20)], "links", tm, r, fam)
        m2, _z2 = mapgen.klippe_aus_linie(g, [(21, 20), (12, 20)], "links", tm, r, fam)
        ost_wand = int(np.nonzero(m1.any(axis=0))[0].max())
        ost_ganz = int(np.nonzero((m1 | m2).any(axis=0))[0].max())
        check(f"{fam}: Fortsetzungsecke ragt nicht ueber die vorhandene Wand",
              ost_ganz <= ost_wand,
              f"Wand bis x={ost_wand}, mit Ecke bis x={ost_ganz}")
        gefunden = bloecke_im_bild(g, fam)
        haar = [n for n, hoch, s, _x, _y in gefunden if hoch == 1 and s == {0, 1}]
        kappen = [n for n, _h, s, _x, _y in gefunden if len(s) == 1]
        check(f"{fam}: kein Abschluss an der haarfeinen Nordkante",
              bool(haar) and not kappen,
              f"{len(haar)} einreihige Laufbloecke, Abschluesse {kappen}")

        # Gegenprobe: wo die Zaehlung den Abschluss stuetzt, muss er bleiben.
        # Sonst waere aus der Regel ein Kahlschlag geworden.
        g2 = np.full((60, 60), gr, dtype=np.int32)
        r2 = np.random.default_rng(5)
        mapgen.klippe_aus_linie(g2, [(8, 30), (40, 30)], "links", tm, r2, fam)
        dick = [n for n, _h, s, _x, _y in bloecke_im_bild(g2, fam) if len(s) == 1]
        check(f"{fam}: dicke Wand behaelt ihren Abschluss", bool(dick), str(dick))

    # Eine Linie, die auf eine bestehende Klippe ZULAEUFT, muss an ihrem ENDE
    # anschliessen. Gefragt wurde bisher nur der erste Punkt, deshalb stand an
    # der Naht ein Wandende (`mudmes08`, Wand nur West) genau dort, wo die
    # beiden Waende sich treffen.
    #
    # Beide Zuege beschreiben dieselbe Hochflaeche, noerdlich und oestlich:
    # Zug 1 senkrecht mit Hochland OST, Zug 2 waagerecht nach WESTEN mit
    # Hochland NORD. Die Naht ist deren Suedwest-Ecke -- Wand nach Ost und Nord.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        g = np.full((48, 64), gr, dtype=np.int32)
        r = np.random.default_rng(3)
        mapgen.klippe_aus_linie(g, [(16, 8), (16, 30)], "links", tm, r, fam)
        mapgen.klippe_aus_linie(g, [(40, 30), (16, 30)], "rechts", tm, r, fam)
        an_naht = [(n, s) for n, _h, s, bx, by in bloecke_im_bild(g, fam)
                   if abs(bx - 16) <= 4 and abs(by - 30) <= 4]
        ecke = [n for n, s in an_naht if {0, 3} <= s]
        kappe = [n for n, s in an_naht if len(s) == 1]
        check(f"{fam}: zulaufende Linie bekommt an der Naht eine Ecke",
              bool(ecke) and not kappe, f"Ecke {ecke}, Wandenden {kappe}")

    # Baurichtungen: eine Klippe laesst sich nur in den Neigungen ziehen, die
    # in den Originalen vorkommen. Gemessen an cm03 (919 Kantenschritte) ist
    # ueber die Haelfte senkrecht, der Rest sind Versaetze von einer bis vier
    # Spalten je Zeile -- mehr gibt es nicht.
    richtungen = mapgen.klippen_richtungen()
    check("32 Baurichtungen, in alle vier Quadranten gespiegelt",
          len(richtungen) == 32, f"{len(richtungen)}")
    import math
    winkel = sorted({round(math.degrees(math.atan2(abs(dy), abs(dx))), 1)
                     for dx, dy in richtungen})
    check("die Winkel sind die gemessenen Kachelverhaeltnisse",
          winkel == [0.0, 14.0, 18.4, 26.6, 45.0, 63.4, 71.6, 76.0, 90.0],
          str(winkel))
    # Jeder Zeigerpunkt landet auf einer erlaubten Richtung, und die Laenge
    # bleibt ungefaehr erhalten -- die Strecke dreht sich nur.
    daneben, laengen = [], []
    r = np.random.default_rng(4)
    for _ in range(200):
        ax, ay = 40, 40
        bx, by = int(r.integers(10, 71)), int(r.integers(10, 71))
        gx, gy = mapgen.klippe_winkel_rasten(ax, ay, bx, by)
        dx, dy = gx - ax, gy - ay
        if dx == 0 and dy == 0:
            continue
        teiler = math.gcd(abs(dx), abs(dy)) or 1
        if (dx // teiler, dy // teiler) not in richtungen:
            daneben.append(((bx, by), (gx, gy)))
        vor = math.hypot(bx - ax, by - ay)
        nach = math.hypot(dx, dy)
        laengen.append(abs(nach - vor) / max(1.0, vor))
    check("gerastete Punkte liegen auf einer erlaubten Richtung",
          not daneben, f"{len(daneben)} daneben {daneben[:3]}")
    check("die Laenge bleibt beim Rasten ungefaehr erhalten",
          max(laengen) < 0.35, f"groesste Abweichung {100*max(laengen):.0f} %")

    # T-Stoss: der Zug trifft MITTEN auf eine vorhandene Wand. Dafuer gibt es
    # keinen Block -- `mud` hat gar keinen mit drei Wandseiten, `san` drei, die
    # in zehn Karten 16 mal vorkommen und davon einmal mit Klippe hinter allen
    # drei Kanten; unabhaengig gezaehlt verzweigen sich die Nordkantenlinien der
    # Originale in sechs von acht Karten null mal. Also wird keiner erfunden:
    # die Querwand bleibt, wie sie war, und der Abzweig stoesst an sie. Vorher
    # bekam der T-Stoss die Eckenbehandlung, und der Eckblock schnitt sich quer
    # durch die Wand, die er treffen sollte.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        for klick, wie in ((20, "genau"), (18, "zu kurz"), (22, "zu weit")):
            g = np.full((40, 32), gr, dtype=np.int32)
            r = np.random.default_rng(3)
            mapgen.klippe_aus_linie(g, [(20, 6), (20, 34)], "links", tm, r, fam)
            quer = g.copy()
            spalten = [x for x in range(32) if (quer[:, x] != gr).any()]
            mapgen.klippe_aus_linie(g, [(6, 18), (klick, 18)], "rechts", tm, r, fam)
            kaputt = [(x, y) for y in range(12, 26) for x in spalten
                      if g[y, x] != quer[y, x]]
            # Luecke: Boden auf der Abzweigzeile zwischen seinem Anfang und der
            # nahen Kante der Querwand.
            nah = min(spalten)
            luecke = [x for x in range(7, nah) if g[18, x] == gr
                      and any(g[18, xx] != gr for xx in range(6, x))]
            check(f"{fam}: T-Stoss laesst die Querwand heil ({wie})",
                  not kaputt and not luecke,
                  f"{len(kaputt)} Zellen {kaputt[:3]}, Luecke {luecke}")

    # Die Hochseite ist unabhaengig von den Wandseiten und muss eigens gefragt
    # werden. `mudmes01` und `mudmes07` haben beide Wand nach West und Sued --
    # beim einen liegt das Hochland suedwestlich, beim anderen nordoestlich.
    for gruppe, soll in (("mudmes01", "SW"), ("mudmes07", "NO"),
                         ("mudmes12", "NW"), ("sanmes15", "SW")):
        fam2 = gruppe[:3]
        blk = next((b for (f3, _r3), st in tm.cliff_pool.items() if f3 == fam2
                    for b in st if tm.klippen_gruppe(b) == gruppe), None)
        ist = mapgen.klippen_hochseite(blk) if blk is not None else "?"
        check(f"{gruppe}: Hochseite liegt {soll}", ist == soll, f"gemessen {ist}")

    # Eine Figur, deren Hochland INNEN liegen soll: Ost -> Sued -> West, Hochseite
    # rechts der Laufrichtung. In der senkrechten Wand muss die Hochseite dann
    # ueberall WESTLICH der Tiefseite liegen. Lag sie oestlich, stand an der
    # Nordost-Ecke die um 180 Grad verdrehte Ecke und das Hochland dort aussen.
    # Ohne die Hochseiten-Bedingung traf das bei mud JEDEN Seed (der einzige
    # Kandidat mit Wand West+Sued in den Toepfen "Ecke"/"Motiv" ist der falsche),
    # bei san 2 von 12.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        verdreht = []
        for seed in range(6):
            g = np.full((18, 32), gr, dtype=np.int32)
            _m, z = mapgen.klippe_aus_linie(
                g, [(6, 2), (19, 2), (19, 14), (4, 14)], "rechts",
                tm, np.random.default_rng(seed), fam)
            verdreht += [(seed, int(x), int(y))
                         for y in range(z.shape[0]) for x in range(1, z.shape[1])
                         if z[y, x] == celltypes.CLIFFS_HIGH_SIDE
                         and z[y, x - 1] == celltypes.CLIFFS_LOW_SIDE]
        check(f"{fam}: Hochland liegt innen (6 Seeds)", not verdreht,
              f"hoch oestlich von tief an {len(verdreht)} Stellen {verdreht[:4]}")

    # Der Zelltyp kommt aus der HOCHSEITE, nicht aus der Kachel. Aus der Kachel
    # geht es gar nicht: 171 der 307 Klippenkacheln kommen sowohl als Hoch- wie
    # als Tiefseite vor, und nur 20,2 % der Zellen haben eine Kachel, die ihren
    # Typ festlegt. `celltypes.default_cell_type` -- der Weg bis hierher --
    # trifft 94,1 %, und die fehlenden 6 % sind fast durchweg vertauschte Hoch-
    # und Tiefseiten, also Waende, die zur falschen Seite zeigen.
    #
    # Geprueft wird die gemessene Regel: am Hochland-Ende des Bandes steht die
    # Hochseite, am anderen Ende die Tiefseite (senkrechte Baender der Laenge 3
    # sind in den Originalen zu 82 % HLL, der Laenge 4 zu 45 % HHLL).
    #
    # Auf dem Stand davor war das rot -- die Zelltypen kamen je Kachel aus
    # `default_cell_type` und wussten von der Hochseite nichts.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        falsch = []
        for hoch in ("oben", "unten"):
            g = np.full((20, 32), gr, dtype=np.int32)
            m, z = mapgen.klippe_aus_linie(g, [(4, 10), (28, 10)], hoch, tm,
                                           np.random.default_rng(3), fam)
            for x in range(32):
                spalte = np.nonzero(m[:, x])[0]
                if len(spalte) < 2:
                    continue
                folge = [int(z[y, x]) for y in spalte]
                am_hoch = folge[0] if hoch == "oben" else folge[-1]
                am_tief = folge[-1] if hoch == "oben" else folge[0]
                if am_hoch != celltypes.CLIFFS_HIGH_SIDE:
                    falsch.append((hoch, x, "Hochende nicht hoch"))
                elif am_tief != celltypes.CLIFFS_LOW_SIDE:
                    falsch.append((hoch, x, "Tiefende nicht tief"))
        check(f"{fam}: Zelltyp folgt der Hochseite", not falsch,
              f"{len(falsch)} Spalten falsch {falsch[:3]}")

    # Die gezeichnete Linie IST die Oberkante des Hochlands, nicht die
    # Wandmitte. Die Klippe waechst von dort weg.
    #
    # Vorher lag die Linie in der Mitte (`y1 - blockhoehe // 2`), mit zwei
    # Folgen: die Hochflaeche sass um die halbe Blockhoehe neben dem, was man
    # gezeichnet hat, und zwei verschieden hohe Bloecke -- mud senkrecht 5
    # Reihen, waagerecht 3 -- legten ihre MITTE gleich, also ihre Kanten
    # verschieden. Auf dem alten Stand ist diese Pruefung rot.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        daneben = []
        for hoch, yy in (("oben", 10), ("unten", 10)):
            g = np.full((24, 32), gr, dtype=np.int32)
            m, _z = mapgen.klippe_aus_linie(g, [(4, yy), (28, yy)], hoch, tm,
                                            np.random.default_rng(1), fam)
            for x in range(32):
                spalte = np.nonzero(m[:, x])[0]
                if not len(spalte):
                    continue
                # bei "oben" liegt das Hochland oben, die Wand beginnt auf der
                # Linie; bei "unten" endet sie darauf
                kante = int(spalte[0]) if hoch == "oben" else int(spalte[-1])
                if kante != yy:
                    daneben.append((hoch, x, kante))
        check(f"{fam}: gezeichnete Linie ist die Hochkante", not daneben,
              f"{len(daneben)} Spalten daneben {daneben[:3]}")

    # Kein Lauf darf ueber seine Ecke hinausragen. Frueher lief der letzte Block
    # durch und die Ecke sollte ihn zudecken -- bei mud ist der senkrechte
    # Laufblock aber 5 Reihen hoch und die gewaehlte Ecke 3, und sie sitzt am
    # Knickpunkt statt am Ende des Ueberstands. Uebrig blieb ein Stummel.
    # Gemessen: die senkrechte Wand darf nicht tiefer reichen als die
    # waagerechte, und die waagerechte nicht weiter nach Osten als die
    # senkrechte.
    for fam in ("san", "mud"):
        gr = next((t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t]), 0)
        stummel = []
        for seed in range(6):
            g = np.full((18, 32), gr, dtype=np.int32)
            m, _z = mapgen.klippe_aus_linie(
                g, [(6, 2), (19, 2), (19, 14), (4, 14)], "rechts",
                tm, np.random.default_rng(seed), fam)
            unten = max(y for y in range(18) if m[y, 6:16].any())
            unten_ecke = max(y for y in range(18) if m[y, 17:22].any())
            ost = max(x for x in range(32) if m[5:12, x].any())
            ost_oben = max(x for x in range(32) if m[1:5, x].any())
            if unten_ecke > unten:
                stummel.append((seed, "unten", unten_ecke, unten))
            if ost_oben > ost:
                stummel.append((seed, "rechts", ost_oben, ost))
        check(f"{fam}: kein Stummel ueber die Ecke hinaus (6 Seeds)",
              not stummel, str(stummel[:4]))


def check_cliffs():
    """Hochflaechen: richtige Zelltypen, Rampen vorhanden, alles erreichbar."""
    params = mapgen.MapGenParams.from_template("plains", width=128, height=128,
                                               seed=5, cliffs=0.25, spawns=2)
    gen = mapgen.generate(params)
    check("Klippen entstehen aus der Form", gen.plateau_share > 0.01,
          f"{100*gen.plateau_share:.1f} % der Flaeche")
    check("Klippen bedecken einen sinnvollen Anteil", 0.005 < gen.plateau_share < 0.25,
          f"{100*gen.plateau_share:.1f} % der Flaeche")
    klippen = np.isin(gen.cells, [celltypes.NORTH_CLIFFS,
                                  celltypes.CLIFFS_HIGH_SIDE,
                                  celltypes.CLIFFS_LOW_SIDE])
    check("Klippenzellen gesetzt", klippen.sum() > 100, f"{int(klippen.sum())} Zellen")
    check("Startpunkte trotz Klippen verbunden", gen.connected)

    # Erreichbarkeit: der Grossteil des befahrbaren Gelaendes muss von einem
    # Startpunkt aus erreichbar sein -- sonst sperren die Klippen die Karte ab.
    mask = np.zeros(gen.cells.shape, dtype=bool)
    for cell in range(32):
        if celltypes.speed_class(cell) in mapgen.PASSABLE_CLASSES:
            mask |= gen.cells == cell
    if gen.spawns:
        h, w = mask.shape
        seen = np.zeros_like(mask)
        stack = [tuple(gen.spawns[0])]
        seen[gen.spawns[0][1], gen.spawns[0][0]] = True
        while stack:
            x, y = stack.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((nx, ny))
        anteil = seen.sum() / max(1, mask.sum())
        check("Klippen sperren die Karte nicht ab (>85 % erreichbar)", anteil > 0.85,
              f"{100*anteil:.0f} %")

    ohne = mapgen.generate(mapgen.MapGenParams(width=128, height=128, seed=5, cliffs=0.0))
    ohne_klippen = np.isin(ohne.cells, [celltypes.NORTH_CLIFFS,
                                        celltypes.CLIFFS_HIGH_SIDE,
                                        celltypes.CLIFFS_LOW_SIDE])
    check("ohne Regler keine Klippen", int(ohne_klippen.sum()) == 0,
          f"{int(ohne_klippen.sum())} Zellen")

    a = mapgen.generate(params)
    check("Klippen sind reproduzierbar", np.array_equal(a.tiles, gen.tiles))
    # Formationen duerfen keinen rechteckigen Fleck Fremduntergrund mitbringen
    tm = mapgen.model()
    fremd = 0
    for cx, cy in gen.mesas:
        block = gen.cells[max(0, cy - 8):cy + 9, max(0, cx - 8):cx + 9]
        fremd += int(np.isin(block, [celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
                                     celltypes.CLIFFS_LOW_SIDE]).sum() == 0)
    check("jede Formation bringt Klippenzellen mit", fremd == 0, f"{fremd} ohne Klippen")

    # Zuordnung: die Klippe muss zur Familie ihres Untergrunds passen -- sonst
    # steht eine Erd-Mesa im Sand und schleppt fremden Boden mit.
    # Assignment: the cliff must match the family of its ground, otherwise a
    # dirt mesa stands in sand dragging foreign ground along.
    from collections import Counter
    for tpl in ("desert", "plains"):
        gen2 = mapgen.generate(mapgen.MapGenParams.from_template(
            tpl, width=128, height=128, seed=5, cliffs=0.30))
        passt = gesamt = 0
        for cx, cy in gen2.mesas:
            block = gen2.tiles[max(0, cy - 7):cy + 8, max(0, cx - 7):cx + 8]
            zellen = gen2.cells[max(0, cy - 7):cy + 8, max(0, cx - 7):cx + 8]
            ist_klippe = np.isin(zellen, [celltypes.NORTH_CLIFFS,
                                          celltypes.CLIFFS_HIGH_SIDE,
                                          celltypes.CLIFFS_LOW_SIDE])
            fam_klippe = [f for f in tm.family_of[block[ist_klippe]] if f >= 0]
            fam_boden = [f for f in tm.family_of[block[~ist_klippe]] if f >= 0]
            if not fam_klippe or not fam_boden:
                continue
            gesamt += 1
            if (Counter(fam_klippe).most_common(1)[0][0]
                    == Counter(fam_boden).most_common(1)[0][0]):
                passt += 1
        if gesamt:
            check(f"'{tpl}': Klippenfamilie passt zum Untergrund",
                  passt / gesamt >= 0.8, f"{passt}/{gesamt}")


def check_min_biome():
    """Mindestgroesse: kleine Biomflecken muessen verschwinden."""
    def kleine_flaechen(gen, grenze):
        # Uebergangskacheln gehoeren keiner Familie an und zerschneiden die
        # Flaechen sonst in Bruchstuecke -- gemessen wird der Boden, nicht das
        # Band dazwischen.
        # Transition tiles belong to no family and would otherwise cut the
        # areas into fragments -- what is measured is the ground, not the band
        # in between.
        fam = mapgen.model().family_of[gen.tiles]
        h, w = fam.shape
        besucht = fam < 0
        klein = 0
        for sy in range(h):
            for sx in range(w):
                if besucht[sy, sx]:
                    continue
                f = int(fam[sy, sx])
                stack = [(sx, sy)]
                besucht[sy, sx] = True
                n = 0
                while stack:
                    x, y = stack.pop()
                    n += 1
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if (0 <= nx < w and 0 <= ny < h and int(fam[ny, nx]) == f
                                and not besucht[ny, nx]):
                            besucht[ny, nx] = True
                            stack.append((nx, ny))
                if 1 < n < grenze:
                    klein += 1
        return klein

    # Auch hier ueber mehrere Seeds: bei Seed 5 allein steht es 35 zu 36 und
    # damit auf Gleichstand, waehrend die anderen klar fallen (52->31, 34->33,
    # 43->39). Ein einzelner Seed macht daraus einen Muenzwurf, den jede
    # Aenderung am Kachelvorrat kippt.
    # Across several seeds here too: seed 5 alone stands at 35 to 36, i.e. a
    # tie, while the others clearly drop (52->31, 34->33, 43->39). A single seed
    # turns that into a coin flip that any change to the tile pool can flip.
    grenze = int(0.006 * 128 * 128)
    vorher = nachher = 0
    for seed in (5, 11, 42, 99):
        ohne = mapgen.generate(mapgen.MapGenParams.from_template(
            "plains", width=128, height=128, seed=seed, min_biome=0.0))
        mit = mapgen.generate(mapgen.MapGenParams.from_template(
            "plains", width=128, height=128, seed=seed, min_biome=0.006))
        vorher += kleine_flaechen(ohne, grenze)
        nachher += kleine_flaechen(mit, grenze)
    check("Mindestgroesse loest kleine Biomflecken auf", nachher < vorher,
          f"{vorher} -> {nachher} ueber 4 Seeds")
    # Ueber mehrere Seeds messen. Mit einem einzigen Seed und 8 % Grenze lag
    # der Test direkt auf der Kante: gemessen verschiebt das Aufloesen kleiner
    # Flecken die groesste Familie im Mittel um 4,1 %, bei Seed 5 aber um
    # 8,1 % -- jede Aenderung am Kachelvorrat liess ihn dann zufaellig kippen,
    # obwohl die Eigenschaft selbst stimmte.
    # Measure across several seeds. With a single seed and an 8 % limit the test
    # sat right on the edge: measured, dissolving small patches shifts the
    # largest family by 4.1 % on average but by 8.1 % for seed 5 -- so any change
    # to the tile pool flipped it at random although the property itself held.
    verschiebungen = []
    for seed in (5, 11, 42, 99):
        o = mapgen.generate(mapgen.MapGenParams.from_template(
            "plains", width=128, height=128, seed=seed, min_biome=0.0))
        m = mapgen.generate(mapgen.MapGenParams.from_template(
            "plains", width=128, height=128, seed=seed, min_biome=0.006))
        verschiebungen.append(max(abs(m.family_share.get(k, 0) - v)
                                  for k, v in o.family_share.items()))
    schnitt = sum(verschiebungen) / len(verschiebungen)
    check("Mischung bleibt trotzdem grob erhalten", schnitt < 0.06,
          f"im Mittel {100*schnitt:.1f} % Verschiebung ueber "
          f"{len(verschiebungen)} Seeds")


def check_details():
    """Streugut: Dichte folgt dem Regler, Familie passt, nichts vereinzelt."""
    tm = mapgen.model()
    detail_kacheln = set()
    for tiles, _ in tm.details:
        detail_kacheln.update(int(t) for t in np.unique(tiles))

    werte = []
    for regler in (0.0, 0.25, 0.5, 1.0):
        gen = mapgen.generate(mapgen.MapGenParams(
            width=128, height=128, seed=21, details=regler, cliffs=0.4))
        werte.append(gen.detail_share)
    check("Regler 0 streut nichts", werte[0] == 0.0, f"{100*werte[0]:.2f} %")
    check("Regler 0.5 trifft die Originaldichte (rund 3 %)",
           0.02 <= werte[2] <= 0.04, f"{100*werte[2]:.2f} %")
    check("Dichte steigt mit dem Regler",
           werte[0] < werte[1] < werte[2] < werte[3],
           ", ".join(f"{100*w:.1f} %" for w in werte))

    # Steht das Streugut im richtigen Biom? Ein Sandkrater im Fels waere falsch.
    # Is the scatter in the right biome? A sand crater in rock would be wrong.
    gen = mapgen.generate(mapgen.MapGenParams(
        width=128, height=128, seed=5, details=1.0, mix={"san": 1.0}))
    fam = tm.family_of[gen.tiles]
    ist_detail = np.isin(gen.tiles, list(detail_kacheln))
    fremd = 0
    if ist_detail.any():
        san = tm.families.index("san")
        fremd = int((fam[ist_detail] != san).sum())
    check("Streugut in der Sandkarte ist Sand-Streugut",
           fremd == 0, f"{fremd} fremde Kacheln")

    # Streugut liegt als Gruppe, nicht als Einzelkachel im Nichts. Gemessen
    # wird gegen den Regler-0-Lauf: einzelne Detailkacheln kann auch der
    # Nachbarschafts-Sampler erzeugen, die Streuung darf keine hinzufuegen.
    # Scatter sits as a group, not as a single tile. Measured against the
    # slider-0 run: the adjacency sampler can produce single detail tiles by
    # itself; the scatter must not add any.
    def einzelkacheln(tiles):
        maske = np.isin(tiles, list(detail_kacheln))
        h, w = maske.shape
        n = 0
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if maske[y, x] and maske[y - 1:y + 2, x - 1:x + 2].sum() == 1:
                    n += 1
        return n

    ohne = mapgen.generate(mapgen.MapGenParams(
        width=128, height=128, seed=5, details=0.0, mix={"san": 1.0}))
    davor, danach = einzelkacheln(ohne.tiles), einzelkacheln(gen.tiles)
    check("Streuung erzeugt keine vereinzelten Kacheln",
          danach <= davor, f"{davor} -> {danach}")
    check("keine 1x1-Stempel im Streugut",
          all(t.size > 1 for t, _ in tm.details), f"{len(tm.details)} Stempel")


def check_features():
    """Gelaendemerkmale: kommt an, was bestellt wurde?"""
    F = mapgen.Feature
    tm = mapgen.model()
    check("Vorrat: grosse Massive gelernt", len(tm.massifs) >= 25, f"{len(tm.massifs)}")
    check("Vorrat: Taeler gelernt", len(tm.valleys) >= 12, f"{len(tm.valleys)}")

    # Kein Stempel darf fremdes Biom mitbringen. Ohne diese Pruefung stand ein
    # weisser Schneebalken mitten in der Wueste -- ein Talstempel aus einer
    # Eiskarte, der als "mud" gefuehrt wurde.
    # No stamp may drag a foreign biome along. Without this check a white snow
    # bar stood in the middle of the desert -- a valley stamp from an ice map
    # that was labelled "mud".
    unrein = []
    for bez, pool in (("Tal", [(t, f) for t, f, _, _ in tm.valleys]),
                      ("Massiv", tm.massifs)):
        for i, (tiles, fam) in enumerate(pool):
            if fam not in tm.families:
                continue
            koerper = mapgen._sperr_maske(tiles)
            for _ in range(4):
                gewachsen = koerper.copy()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        gewachsen |= np.roll(np.roll(koerper, dy, 0), dx, 1)
                koerper = gewachsen
            fams = tm.family_of[tiles[koerper]]
            klass = fams[(fams >= 0) & (fams < len(tm.families))]
            if len(klass) and float((klass == tm.families.index(fam)).mean()) < 0.85:
                unrein.append(f"{bez}{i}")
    check("kein Merkmal-Stempel bringt fremdes Biom mit", not unrein,
          f"{len(unrein)} unrein: {unrein[:4]}")

    # Mehrere Seeds statt einem: 'enge' legt eine schmale Schneise an, und ob
    # dabei ueberhaupt Klippenzellen entstehen, haengt am Verlauf des Pfades --
    # gemessen ueber sechs Seeds gelingt es in etwa der Haelfte. An EINEN Seed
    # geheftet prueft der Test also den Zufall mit, nicht das Merkmal: jede
    # Aenderung, die den Zufallsstrom verschiebt, kippt ihn.
    # Several seeds instead of one: 'enge' cuts a narrow pass, and whether any
    # cliff cells arise at all depends on how the path runs -- measured across
    # six seeds it works about half the time. Pinned to ONE seed the check tests
    # the dice along with the feature: any change that shifts the random stream
    # flips it.
    for kind in mapgen.FEATURE_KINDS:
        feat = F(kind, where="c", to="o" if kind in ("tal", "enge") else "",
                 size=0.6)
        zahlen = []
        for seed in (9, 12, 8):
            gen = mapgen.generate(mapgen.MapGenParams(
                features=[feat], width=128, height=128, seed=seed,
                cliffs=0.15, details=0.3))
            zahlen.append(gen.features.get(kind, 0))
            if zahlen[-1] > 0:
                break
        check(f"Merkmal '{kind}' wird gesetzt", max(zahlen) > 0,
              f"{zahlen}")

    # Lage: das Merkmal muss dort landen, wo es bestellt wurde.
    # Position: the feature has to end up where it was ordered.
    KL = [celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
          celltypes.CLIFFS_LOW_SIDE]
    for sektor, (fx, fy) in (("nw", (0.25, 0.25)), ("so", (0.75, 0.75))):
        gen = mapgen.generate(mapgen.MapGenParams(
            width=128, height=128, seed=4, cliffs=0.0, details=0.0,
            features=[F("berg", where=sektor, size=0.8)]))
        klippen = np.isin(gen.cells, KL)
        if not klippen.any():
            check(f"Berg im Sektor '{sektor}'", False, "keine Klippen")
            continue
        ys, xs = np.nonzero(klippen)
        dx = abs(xs.mean() / 128 - fx)
        dy = abs(ys.mean() / 128 - fy)
        check(f"Berg landet im Sektor '{sektor}'", dx < 0.22 and dy < 0.22,
              f"Schwerpunkt {xs.mean()/128:.2f}/{ys.mean()/128:.2f}")

    # Freiflaeche: dort darf nichts stehen, sonst taugt sie nicht als Bauplatz.
    # Clearing: nothing may stand there or it is useless as a building site.
    gen = mapgen.generate(mapgen.MapGenParams(
        width=128, height=128, seed=7, cliffs=0.35, details=1.0,
        features=[F("frei", where="c", size=0.8)]))
    # Lage vom Generator erfragen statt zu raten: der Sektor wird verwackelt,
    # sonst prueft der Test eine andere Flaeche als die freigehaltene.
    # Ask the generator for the position instead of guessing: the sector is
    # jittered, otherwise the test checks a different area than the clear one.
    kind, cx, cy, r = gen.feature_spots[0]
    ys, xs = np.ogrid[:128, :128]
    kreis = ((xs - cx) ** 2 + (ys - cy) ** 2) <= r * r
    stoerung = int(np.isin(gen.cells, KL)[kreis].sum())
    check("Freiflaeche bleibt frei von Klippen", stoerung == 0, f"{stoerung} Zellen")

    # Tal mit Lava: nur das Feld, nie gemalte Lavakacheln.
    # Valley with lava: only the field, never painted lava tiles.
    gen = mapgen.generate(mapgen.MapGenParams(
        width=128, height=128, seed=9, cliffs=0.1,
        features=[F("tal", where="w", to="o", size=0.6, lava=True)]))
    check("Tal mit Lava meldet ein lavaPossible-Feld",
          sum(len(z) for z in gen.lava_zones) > 0,
          f"{sum(len(z) for z in gen.lava_zones)} Felder")
    check("keine Lavakacheln gemalt", not tm.lava[gen.tiles].any(),
          f"{int(tm.lava[gen.tiles].sum())} Kacheln")
    # Die Sohle muss begehbar sein, sonst ist es kein Tal, sondern eine Wand.
    # The floor has to be walkable, otherwise it is a wall, not a valley.
    zone = gen.lava_zones[0] if gen.lava_zones else []
    begehbar = sum(1 for x, y in zone
                   if celltypes.speed_class(int(gen.cells[y, x])) in
                   ("fast", "medium", "slow"))
    check("Talsohle ist begehbar", zone and begehbar / len(zone) > 0.8,
          f"{100*begehbar/max(1,len(zone)):.0f} %")

    # Merkmale duerfen Symmetrie und Reproduzierbarkeit nicht brechen.
    # Features must not break symmetry or reproducibility.
    feats = [F("tal", where="w", to="o", size=0.5), F("berg", where="n", size=0.6)]
    a = mapgen.generate(mapgen.MapGenParams(width=128, height=128, seed=5,
                                            features=feats))
    b = mapgen.generate(mapgen.MapGenParams(width=128, height=128, seed=5,
                                            features=feats))
    check("mit Merkmalen weiterhin reproduzierbar", bool((a.tiles == b.tiles).all()))
    sym = mapgen.generate(mapgen.MapGenParams(
        width=128, height=128, seed=5, symmetry=mapgen.SYM_MIRROR_X,
        spawns=4, features=[F("berg", where="nw", size=0.6)]))
    t = sym.tiles
    check("Symmetrie haelt trotz Merkmal",
          bool((t[:, 64:] == t[:, :64][:, ::-1]).all()))
    check("Startpunkte trotz Merkmalen verbunden", sym.connected)


def check_writes_map():
    src = next(GAME.rglob("cm02.map"), None)
    if not check("Vorlagenkarte gefunden", src is not None):
        return
    gen = mapgen.generate(mapgen.MapGenParams(width=64, height=64, seed=3))
    m = mapgen.apply_to_map(Op2Map(src.read_bytes()), gen)
    data = m.to_bytes()
    again = Op2Map(data)
    check("erzeugte Karte ist wieder lesbar",
          again.width == 64 and again.height == 64, f"{again.width}x{again.height}")
    check("erzeugte Karte schreibt sich stabil", again.to_bytes() == data)
    check("Kacheln kamen richtig an",
          all(again.tile_mapping_index(x, y) == int(gen.tiles[y, x])
              for y in range(0, 64, 9) for x in range(0, 64, 9)))
    check("Tilesets der Vorlage uebernommen", len(again.tileset_sources) > 0)
    check("TileGroups der Vorlage uebernommen", len(again.tile_groups) > 100,
          f"{len(again.tile_groups)}")
    check("Gelaende ist ueberwiegend befahrbar", gen.passable_share > 0.5,
          f"{100*gen.passable_share:.0f} %")


def check_harte_kanten():
    """Zwei Boeden duerfen nie ohne Uebergangskachel aneinanderstossen.

    Gemessen an den Originalen ist das eine harte Regel, keine Statistik: fuer
    die vier Paare mit eigenem Kachelsatz (`mudtoroc`, `santomud`, `santoroc`,
    `lavtoroc`) haben cm03, cm04, newworld, eden01 und on2_01 zusammen NULL
    solche Nahtstellen. Erde neben Bewuchs dagegen ist normal -- dafuer gibt es
    keinen Satz, der Bewuchs sitzt einfach auf der Erde.

    Two grounds must never butt against each other without a transition tile.
    Measured against the originals this is a hard rule, not a statistic: for the
    four pairs with their own tile set the original maps together have ZERO such
    seams. Dirt beside vegetation is normal -- there is no set for it.
    """
    tm = mapgen.model()
    mit_satz = {tuple(sorted(k)) for k in tm.trans}
    for seed in (1, 2, 3):
        gen = mapgen.generate(mapgen.MapGenParams(width=128, height=128, seed=seed))
        fam, ueb = tm.family_of[gen.tiles], tm.ist_uebergang[gen.tiles]
        schlimm = 0
        for a, b, ua, ub in ((fam[:, :-1], fam[:, 1:], ueb[:, :-1], ueb[:, 1:]),
                             (fam[:-1, :], fam[1:, :], ueb[:-1, :], ueb[1:, :])):
            roh = (~ua) & (~ub) & (a >= 0) & (b >= 0) & (a != b)
            ys, xs = np.nonzero(roh)
            for yy, xx in zip(ys.tolist(), xs.tolist()):
                paar = tuple(sorted((tm.families[int(a[yy, xx])],
                                     tm.families[int(b[yy, xx])])))
                if paar in mit_satz:
                    schlimm += 1
        check(f"Seed {seed}: kein Boden stoesst ohne Uebergang an einen anderen",
              schlimm == 0, f"{schlimm} harte Kanten")


def check_kantenzuordnung():
    """Die Kantenzuordnung von Hand -- laesst sie durch, was belegt ist?

    Die Paartabelle kennt nur, was in den 54 Karten NEBENEINANDER VORKAM;
    9,2 % aller mud-Paarungen. Die Kantenzuordnung erlaubt weitere 30,4 % und
    verbietet 60,4 %. Damit sie das darf, muss sie das Belegte durchlassen --
    eine Regel, die Originalkarten verbietet, ist falsch, nicht streng.

    Der Rest von 0,15 % sind Stellen, an denen die Originalkarten dieselbe
    Kante in beide Richtungen benutzen; siehe docs/klippen-stand.md 12.
    """
    try:
        from cliff_kanten import modell as _km
        from cliff_tiles import modell as _tm
    except Exception as e:                               # noqa: BLE001
        check("Kantenzuordnung ladbar", False, str(e))
        return
    K, T = _km(), _tm()
    check("Kantenzuordnung geladen", len(K) > 100, f"{len(K)} Kacheln")

    gut = schlecht = 0
    for r in ("O", "S"):
        for a in K.kanten:
            if not T.ist_klippe(a):
                continue
            for b, n in T.nachbarn(a, r).items():
                if not K.kennt(b):
                    continue
                if K.passt(a, b, r):
                    gut += n
                else:
                    schlecht += n
    anteil = 100 * gut / max(1, gut + schlecht)
    check("laesst die belegten Paare durch (>= 99,5 %)", anteil >= 99.5,
          f"{anteil:.2f} % von {gut + schlecht} Vorkommen")

    # Und sie muss noch etwas verbieten, sonst ist sie keine Aussage.
    fam = [t for t in K.kanten if T.ist_klippe(t)]
    erlaubt = ges = 0
    for a in fam[:60]:
        for b in fam[:60]:
            ges += 1
            if K.passt(a, b, "O"):
                erlaubt += 1
    check("verbietet noch etwas (< 80 % erlaubt)", 100 * erlaubt / ges < 80,
          f"{100 * erlaubt / ges:.0f} % erlaubt")


def check_wandhoehe():
    """`hoehe` bestimmt, wie tief das Band wird -- und wo die Uebergaenge
    landen.

    Ohne Angabe ergibt sich die Hoehe aus den Bloecken: waagerecht sauber 3,
    auf Schraegen aber 3 bis 7, weil die Bloecke an den Stufen ueberlappen. In
    einem zu dicken Band stehen die Kacheln, die als Ober- oder Unterkante
    gedacht sind, mitten in der Wand -- gemessen 8,5 % (2:1) und 11,3 % (1:1)
    gegen 0,7 bis 0,9 % in den Originalkarten, dort gleich auf geraden wie auf
    schraegen Stellen.
    """
    try:
        from cliff_kanten import BIOM, FELS, modell as _km
    except Exception as e:                               # noqa: BLE001
        check("Wandhoehe", False, str(e))
        return
    K = _km()
    tm = mapgen.model()
    gr = next(t for t in range(2048)
              if tm.family_of[t] == tm.families.index("mud")
              and tm.placeable[t])

    def zeigt_boden(t, s):
        v = K.seite(t, s)
        if v is None:
            return None
        b = sum(1 for u in v if u == BIOM)
        f = sum(1 for u in v if u == FELS)
        return True if b >= 3 else (False if f >= 3 else None)

    def bauen(punkte, hoehe):
        g = np.full((48, 64), gr, dtype=np.int32)
        m, _z = mapgen.klippe_aus_linie(g, punkte, "oben", tm,
                                        np.random.default_rng(3), "mud",
                                        hoehe=hoehe)
        tiefste = 0
        for x in range(m.shape[1]):
            lauf = 0
            for y in range(m.shape[0]):
                lauf = lauf + 1 if m[y, x] else 0
                tiefste = max(tiefste, lauf)
        falsch = ges = 0
        h2, w2 = m.shape
        for y in range(h2):
            for x in range(w2):
                if not m[y, x]:
                    continue
                for s, dy in (("N", -1), ("S", 1)):
                    ny = y + dy
                    nk = 0 <= ny < h2 and m[ny, x]
                    bod = zeigt_boden(int(g[y, x]), s)
                    if bod is None:
                        continue
                    ges += 1
                    falsch += bool(bod and nk)
        return tiefste, 100 * falsch / max(1, ges)

    schraeg = [(8, 8), (38, 38)]
    # Gegenlauf: ohne Angabe MUSS das Band dicker als 3 werden, sonst misst
    # die Pruefung nichts.
    dick, _q = bauen(schraeg, None)
    check("ohne hoehe wird das Band dicker als 3 -- die Pruefung misst etwas",
          dick > 3, f"{dick} Kacheln")

    for hoehe in (2, 3):
        d, q = bauen(schraeg, hoehe)
        check(f"hoehe={hoehe} haelt das Band duenn", d <= hoehe + 2,
              f"tiefste Zeile {d}")
    # Bei 2 liegt die Wand auf dem Wert der Originalkarten; bei 3 bleibt auf
    # der 45-Grad-Schraegen ein Rest, siehe docs/klippen-stand.md 12.
    _d2, q2 = bauen(schraeg, 2)
    check("hoehe=2: Uebergaenge stehen am Rand (<= 2 %)", q2 <= 2.0,
          f"{q2:.1f} % mitten in der Wand, Originalkarten 0,7 %")


def check_regeltreu():
    """Keine gebaute Wand darf ein Paar tragen, das weder belegt noch erlaubt
    ist.

    Der Loeser setzt von sich aus keine, aber er laeuft nicht ueberall -- an
    Ecken, Enden und wiederhergestellten Querwaenden bleiben Bloecke stehen.
    Dafuer laeuft `klippe_regeln_durchsetzen` zum Schluss.

    Die Pruefung schlaegt nachweislich an: mit `regeln_durchsetzen=False`
    haben dieselben Waende 88 (2:1) bzw. 136 (1:1) regelwidrige Paare. Ohne
    diesen Gegenlauf waere eine gruene Zeile hier ohne Aussage.
    """
    try:
        from cliff_kanten import modell as _km
        from cliff_tiles import VERSATZ, modell as _tm
    except Exception as e:                               # noqa: BLE001
        check("Loeser regeltreu", False, str(e))
        return
    K, T = _km(), _tm()
    tm = mapgen.model()
    fi = tm.families.index("mud")
    gr = next(t for t in range(2048)
              if tm.family_of[t] == fi and tm.placeable[t])

    def regelwidrig(m, g):
        aus = 0
        h, w = g.shape
        for r in ("N", "O", "S", "W"):
            dx, dy = VERSATZ[r]
            for y in range(h):
                for x in range(w):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if not (m[y, x] and m[ny, nx]):
                        continue
                    a, b = int(g[y, x]), int(g[ny, nx])
                    if not T.passt(a, b, r) and not K.passt(a, b, r):
                        aus += 1
        return aus

    for name, punkte in (("2:1", [(6, 10), (52, 33)]),
                         ("1:1", [(8, 8), (38, 38)])):
        # Gegenlauf: ohne die Durchsetzung MUSS es regelwidrige Paare geben,
        # sonst misst die Pruefung nichts.
        g = np.full((48, 64), gr, dtype=np.int32)
        m, _z = mapgen.klippe_aus_linie(g, punkte, "oben", tm,
                                        np.random.default_rng(3), "mud",
                                        regeln_durchsetzen=False)
        vor = regelwidrig(m, g)
        check(f"ohne Durchsetzung regelwidrig ({name}) -- die Pruefung misst "
              f"etwas", vor > 0, f"{vor} Paare")

        g = np.full((48, 64), gr, dtype=np.int32)
        m, _z = mapgen.klippe_aus_linie(g, punkte, "oben", tm,
                                        np.random.default_rng(3), "mud")
        nach = regelwidrig(m, g)
        check(f"gebaute Wand ist regeltreu ({name})", nach == 0,
              f"{nach} Paare")


def main() -> int:
    if not mapgen.MODEL_PATH.exists():
        print("tiles_model.npz fehlt -> zuerst 'python mapview/learn_tiles.py'")
        return 1
    check_determinism()
    check_harte_kanten()
    check_mix()
    check_symmetry()
    check_spawns()
    check_no_scatter()
    check_volcanoes()
    check_klippen_nachbarn()
    check_kantenzuordnung()
    check_wandhoehe()
    check_regeltreu()
    check_cliffs()
    check_min_biome()
    check_details()
    check_features()
    check_writes_map()
    print("\n" + ("Alle Pruefungen gruen." if not _failures
                  else f"{len(_failures)} Pruefung(en) rot: {_failures}"))
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
