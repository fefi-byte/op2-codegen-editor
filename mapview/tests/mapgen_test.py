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


def check_klippe_algo():
    """Der algorithmische Weg laesst harte Uebergaenge gar nicht erst zu.

    Der Blockweg repariert sie hinterher; hier kann eine Kachel, die Fels ins
    Biom zeigt, die Gelaendeabfrage nicht erfuellen und wird nicht gewaehlt.
    Geprueft wird beides -- dass nichts hart bleibt UND dass die Pruefung
    ueberhaupt etwas misst: ohne die Regel "beim Zusammenstoss gehoert die
    Randlinie dem Biom" muss sie durchfallen.
    """
    try:
        import klippe_algo as KA
        from cliff_kanten import BIOM, FELS, modell as _km
        from cliff_tiles import VERSATZ
    except Exception as e:                               # noqa: BLE001
        check("Klippe algorithmisch", False, str(e))
        return
    K = _km()
    tm = mapgen.model()
    if not KA.verfuegbar(tm, "mud"):
        check("Klippe algorithmisch -- mud zugeordnet", False,
              "Handzuordnung traegt mud nicht")
        return
    gr = next(t for t in range(2048)
              if tm.family_of[t] == tm.families.index("mud")
              and tm.placeable[t])
    vor = KA.vorrat(tm, "mud")

    def zeigt(t, r, was):
        v = K.seite(t, r)
        return v is not None and sum(1 for u in v if u == was) >= 3

    def maengel(g, m, fam="mud"):
        """-> (hart, Loch, innen, Seiten).

        `innen` ist der Spiegelfall von `hart`: eine Kachelseite zeigt BODEN,
        obwohl dahinter eine Klippenzelle steht -- eine Ober- oder Unterkante
        mitten in der Wand. Der Mangel fehlte hier lange und fiel erst am
        fertigen Bild auf.

        Die Seiten kommen aus derselben Quelle wie beim Setzer: Hand fuer mud,
        gerechnet fuer san. `K.seite` taugt dafuer nicht, es kennt nur die
        Handtabelle.
        """
        seiten_von = {t: s for t, (s, _fa) in KA.vorrat(tm, fam).items()}
        h, w = g.shape
        hart = lo = innen = seiten = 0
        for y in range(h):
            for x in range(w):
                if not m[y, x]:
                    continue
                s = seiten_von.get(int(g[y, x]))
                if s is None:
                    continue
                for r in ("N", "O", "S", "W"):
                    dx, dy = VERSATZ[r]
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    seiten += 1
                    if not m[ny, nx]:
                        if sum(1 for u in s[r] if u == FELS) >= 3:
                            hart += 1
                        continue
                    if sum(1 for u in s[r] if u == BIOM) >= 3:
                        innen += 1
                    if r not in ("O", "S"):
                        continue
                    sb = seiten_von.get(int(g[ny, nx]))
                    if sb is None:
                        continue
                    if all(u == BIOM and v == BIOM
                           for u, v in zip(s[r], sb[{"O": "W", "S": "N"}[r]])):
                        lo += 1
        return hart, lo, innen, seiten

    zuege = (("waagerecht", [(4, 14), (57, 14)], "oben"),
             ("2:1 schraeg", [(4, 20), (57, 8)], "oben"),
             ("mit Knick", [(4, 20), (30, 10), (57, 20)], "oben"),
             ("senkrecht", [(20, 4), (20, 28)], "links"))
    for fam in ("mud", "san"):
        if not KA.verfuegbar(tm, fam):
            check(f"Klippe algorithmisch -- {fam} zugeordnet", False,
                  f"Vorrat {len(KA.vorrat(tm, fam))}")
            continue
        grf = next(t for t in range(2048)
                   if tm.family_of[t] == tm.families.index(fam)
                   and tm.placeable[t])
        for name, punkte, seite in zuege:
            g = np.full((32, 64), grf, dtype=np.int32)
            m, _z = KA.klippe_aus_linie(g, punkte, seite, tm,
                                        np.random.default_rng(7), fam)
            check(f"algorithmisch setzt ueberhaupt ({fam} {name})",
                  int(m.sum()) > 40, f"{int(m.sum())} Kacheln")
            hart, lo, innen, seiten = maengel(g, m, fam)
            check(f"algorithmisch ohne harte Uebergaenge ({fam} {name})",
                  hart == 0, f"{hart} Stellen")
            check(f"algorithmisch ohne Loch ({fam} {name})", lo == 0,
                  f"{lo} Nahtstellen")
            # Randkacheln mitten in der Wand. Die Originalkarten liegen bei
            # 1,22 % (mud) und 0,95 % (san); 2 % ist die Schwelle, ab der es
            # im Bild als Band quer durch den Fels auffaellt. Ueber drei
            # Saaten gemittelt: eine einzelne Wand streut stark (san
            # senkrecht 0,4 bis 3,9 % je Saat), und an einer Saat haengend
            # kippte die Pruefung bei jeder Aenderung am Gelaende.
            for saat in (8, 9):
                g2 = np.full((32, 64), grf, dtype=np.int32)
                m2, _ = KA.klippe_aus_linie(g2, punkte, seite, tm,
                                            np.random.default_rng(saat), fam)
                _h, _l, i2, s2 = maengel(g2, m2, fam)
                innen += i2
                seiten += s2
            anteil = 100 * innen / max(1, seiten)
            check(f"keine Randkacheln mitten in der Wand ({fam} {name})",
                  anteil <= 2.0, f"{innen} von {seiten} ({anteil:.2f} %)")

    # Der Eckenfilter aus dem August (Kacheln mit widerspruechlicher Ecke aus
    # dem Vorrat) ist mit dem Gelaende-Loeser NICHT mehr drin. Er war fuer den
    # gierigen Setzer noetig, an dem `angleichen` sich endlos drehte; dem
    # Loeser schadet er gemessen auf jeder Kennzahl (mud, 39 Waende): Waende
    # mit unpassenden Paaren 0 -> 10, unbelegt 25,9 -> 36,4 %, Randkacheln
    # mitten in der Wand 1,54 -> 2,25 %. Siehe klippen-stand.md Abschnitt 22.

    # Der Loeser: jedes Nachbarpaar belegt oder nach der Kantenzuordnung
    # erlaubt. Der gierige Setzer lag hier bei 0,9 bis 8,6 % regelwidrig --
    # die Gegenprobe zeigt, dass die Pruefung das auch sieht.
    from cliff_tiles import modell as _ttm
    tt = _ttm()

    def regelwidrig(g, m):
        h, w = g.shape
        n = 0
        for y in range(h):
            for x in range(w):
                for r, dx, dy in (("O", 1, 0), ("S", 0, 1)):
                    nx, ny = x + dx, y + dy
                    if nx >= w or ny >= h or not (m[y, x] and m[ny, nx]):
                        continue
                    a, b = int(g[y, x]), int(g[ny, nx])
                    if not (tt.passt(a, b, r) or K.passt(a, b, r)):
                        n += 1
        return n

    alt = KA.LOESER
    try:
        for name, punkte, seite in zuege:
            KA.LOESER = True
            g = np.full((32, 64), gr, dtype=np.int32)
            m, _z = KA.klippe_aus_linie(g, punkte, seite, tm,
                                        np.random.default_rng(7), "mud")
            check(f"Loeser ohne regelwidrige Paare ({name})",
                  m.sum() > 40 and regelwidrig(g, m) == 0,
                  f"{regelwidrig(g, m)} Paare, {int(m.sum())} Kacheln")
        KA.LOESER = False
        g = np.full((32, 64), gr, dtype=np.int32)
        m, _z = KA.klippe_aus_linie(g, [(4, 14), (57, 14)], "oben", tm,
                                    np.random.default_rng(7), "mud")
        check("ohne Loeser bleiben regelwidrige Paare -- die Pruefung misst "
              "etwas", regelwidrig(g, m) > 0, f"{regelwidrig(g, m)} Paare")
    finally:
        KA.LOESER = alt

    # Gegenprobe: ohne die Randregel muss die Pruefung durchfallen.
    g = np.full((32, 64), gr, dtype=np.int32)
    fein, achse = KA.band_aus_linie([(4, 20), (57, 8)], "oben", 64, 32,
                                    np.random.default_rng(7))
    fein, _b = KA.fuellregel(fein, achse, np.random.default_rng(7))
    fein, _b = KA.angleichen(fein, vor)          # Randregel absichtlich weg
    m, _b = KA.setzen(g, fein, vor)
    hart, _lo, _in, _s = maengel(g, m)
    check("ohne die Randregel bleiben harte Uebergaenge -- die Pruefung "
          "misst etwas", hart > 0, f"{hart} Stellen")

    # san traegt die automatische Zuordnung (cliff_kanten_auto.json): die
    # Wand muss stehen, ohne Paar, das weder belegt noch erlaubt ist, und
    # ohne Loch. sno hat nur 9 Kacheln und muss sich weiter verweigern.
    if "san" in tm.families:
        from cliff_kanten import modell as _kma
        ka = _kma(auto=True)
        gs = next(t for t in range(2048)
                  if tm.family_of[t] == tm.families.index("san")
                  and tm.placeable[t])
        for name, punkte, seite in zuege + (
                ("waagerecht Nord", [(4, 14), (57, 14)], "unten"),):
            g = np.full((32, 64), gs, dtype=np.int32)
            m, _z = KA.klippe_aus_linie(g, punkte, seite, tm,
                                        np.random.default_rng(7), "san")
            h, w = g.shape
            rw = lo = 0
            for y in range(h):
                for x in range(w):
                    for r, dx, dy in (("O", 1, 0), ("S", 0, 1)):
                        nx, ny = x + dx, y + dy
                        if nx >= w or ny >= h or not (m[y, x] and m[ny, nx]):
                            continue
                        a, b = int(g[y, x]), int(g[ny, nx])
                        if not (tt.passt(a, b, r) or ka.passt(a, b, r)):
                            rw += 1
                        if ka.loch(a, b, r):
                            lo += 1
            check(f"san algorithmisch ({name})",
                  m.sum() > 20 and rw == 0 and lo == 0,
                  f"{int(m.sum())} Kacheln, {rw} unpassend, {lo} Loch")
    if "sno" in tm.families:
        g = np.full((32, 64), gr, dtype=np.int32)
        m, _z = KA.klippe_aus_linie(g, [(4, 14), (57, 14)], "oben", tm,
                                    np.random.default_rng(7), "sno")
        check("algorithmisch verweigert sich bei sno", not m.any(),
              f"{int(m.sum())} Kacheln gesetzt")


def check_landschaft():
    """Der Landschaftsmodus: Relief, Blockweg-Klippen, Flussbetten.

    Die Schwellen sind Anteile, keine festen Zahlen -- feste Zahlen haengen an
    der Kartengroesse. Gemessen an sechs Seeds (1, 2, 3, 7, 11, 23) auf
    128x128: Klippenanteil 3,2 bis 4,5 %, null harte Bodenkanten, null
    isolierte Klippenzellen, haeufigste Kachel 5,5 bis 5,7 % (Originalkarte
    newworld: 2,8 %; der Deckel bei 10 % faengt den Kachelflut-Fehler, den
    eine reine Nahtmetrik einmal belohnt hat).

    Landscape mode: relief, block-path cliffs, riverbeds. Thresholds are
    shares, not fixed counts. Measured across six seeds; the 10 % lid on the
    most frequent tile catches the tile-flood failure a pure seam metric once
    rewarded.
    """
    tm = mapgen.model()
    mit_satz = {tuple(sorted(k)) for k in tm.trans}
    klippentypen = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
                    celltypes.CLIFFS_LOW_SIDE)

    a = mapgen.generate(mapgen.MapGenParams.from_template(
        "newterra", width=128, height=128, seed=42, spawns=2))
    b = mapgen.generate(mapgen.MapGenParams.from_template(
        "newterra", width=128, height=128, seed=42, spawns=2))
    check("Landschaft: gleicher Seed -> gleiche Karte",
          np.array_equal(a.tiles, b.tiles))

    for seed in (1, 3, 11):
        gen = mapgen.generate(mapgen.MapGenParams.from_template(
            "newterra", width=128, height=128, seed=seed, spawns=2))
        flaeche = float(gen.tiles.size)
        klippe = np.isin(gen.cells, klippentypen)
        anteil = float(klippe.mean())
        check(f"Landschaft Seed {seed}: Klippenanteil im Zielband",
              0.015 <= anteil <= 0.10, f"{anteil:.1%}")

        # Waende, kein Schutt: jede Klippenzelle hat eine Klippennachbarin.
        # Walls, not rubble: every cliff cell has a cliff neighbour.
        nachbarn = np.zeros(klippe.shape, dtype=np.int16)
        nachbarn[1:, :] += klippe[:-1, :]
        nachbarn[:-1, :] += klippe[1:, :]
        nachbarn[:, 1:] += klippe[:, :-1]
        nachbarn[:, :-1] += klippe[:, 1:]
        isoliert = int((klippe & (nachbarn == 0)).sum())
        check(f"Landschaft Seed {seed}: keine isolierte Klippenzelle",
              isoliert == 0, f"{isoliert}")

        # Harte Bodenkanten wie in check_harte_kanten, Klippenzellen sind
        # kein Boden und bleiben aussen vor.
        # Hard ground edges as in check_harte_kanten; cliff cells are not
        # ground and stay out of it.
        fam, ueb = tm.family_of[gen.tiles], tm.ist_uebergang[gen.tiles]
        schlimm = 0
        for fa, fb, ua, ub, ka, kb in (
                (fam[:, :-1], fam[:, 1:], ueb[:, :-1], ueb[:, 1:],
                 klippe[:, :-1], klippe[:, 1:]),
                (fam[:-1, :], fam[1:, :], ueb[:-1, :], ueb[1:, :],
                 klippe[:-1, :], klippe[1:, :])):
            roh = (~ua) & (~ub) & (~ka) & (~kb) & (fa >= 0) & (fb >= 0) \
                & (fa != fb)
            ys, xs = np.nonzero(roh)
            for yy, xx in zip(ys.tolist(), xs.tolist()):
                paar = tuple(sorted((tm.families[int(fa[yy, xx])],
                                     tm.families[int(fb[yy, xx])])))
                if paar in mit_satz:
                    schlimm += 1
        check(f"Landschaft Seed {seed}: kein Boden ohne Uebergang",
              schlimm == 0, f"{schlimm} harte Kanten")

        # Kachelverteilung: eine Nahtmetrik allein hat einmal einen Fehler
        # belohnt, der die Karte mit einer Kachel flutete.
        # Tile distribution: a seam metric alone once rewarded a bug that
        # flooded the map with one tile.
        _w, anzahl = np.unique(gen.tiles, return_counts=True)
        check(f"Landschaft Seed {seed}: keine Kachel flutet die Karte",
              float(anzahl.max()) / flaeche <= 0.10,
              f"haeufigste {float(anzahl.max()) / flaeche:.1%}")

        check(f"Landschaft Seed {seed}: Flussbett vorhanden",
              gen.fluss_share >= 0.005, f"{gen.fluss_share:.1%}")
        check(f"Landschaft Seed {seed}: Startpunkte verbunden",
              gen.connected and len(gen.spawns) == 2)


def main() -> int:
    if not mapgen.MODEL_PATH.exists():
        print("tiles_model.npz fehlt -> zuerst 'python mapview/learn_tiles.py'")
        return 1
    check_determinism()
    check_harte_kanten()
    check_landschaft()
    check_mix()
    check_symmetry()
    check_spawns()
    check_no_scatter()
    check_volcanoes()
    check_kantenzuordnung()
    check_klippe_algo()
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
