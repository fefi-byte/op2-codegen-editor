"""Regionen: Rauschfelder, Familienfelder, Symmetrie, Vulkane, Details.

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

Regions: noise and family fields, symmetry, volcanoes, details. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # nur fuer Typangaben
    from mapgen_modell import TileModel  # noqa: F401


import numpy as np

from mapgen_basis import (  # noqa: E402
    MapGenParams,
    SYM_MIRROR_X,
    SYM_MIRROR_Y,
    SYM_QUAD,
    SYM_ROT180,
)


# --------------------------------------------------------------------------
# Regionen / regions

def _value_noise(rng: np.random.Generator, h: int, w: int, freq: int) -> np.ndarray:
    """Weiches Rauschfeld in [0,1) per bilinearer Interpolation."""
    freq = max(2, int(freq))
    base = rng.random((freq + 1, freq + 1))
    ys = np.linspace(0, freq, h, endpoint=False)
    xs = np.linspace(0, freq, w, endpoint=False)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    fy = fy * fy * (3 - 2 * fy)      # smoothstep
    fx = fx * fx * (3 - 2 * fx)
    v00 = base[np.ix_(y0, x0)]
    v01 = base[np.ix_(y0, x0 + 1)]
    v10 = base[np.ix_(y0 + 1, x0)]
    v11 = base[np.ix_(y0 + 1, x0 + 1)]
    top = v00 * (1 - fx) + v01 * fx
    bottom = v10 * (1 - fx) + v11 * fx
    return top * (1 - fy) + bottom * fy


def _family_field(params: MapGenParams, rng: np.random.Generator,
                  fam_names: list[str]) -> np.ndarray:
    """Welche Familie bekommt welche Zelle? -> (h, w) Familienindex."""
    h, w = params.height, params.width
    # Zerkluefung steuert die Frequenz: wenige grosse Flaechen vs. viele kleine.
    # Roughness controls the frequency: few large areas vs. many small ones.
    base_freq = 3 + params.roughness * 14
    scores = []
    order = []
    targets = []
    total = sum(v for v in params.mix.values() if v > 0) or 1.0
    for name, weight in params.mix.items():
        if weight <= 0 or name not in fam_names:
            continue
        noise = (_value_noise(rng, h, w, base_freq)
                 + 0.5 * _value_noise(rng, h, w, base_freq * 2)) / 1.5
        scores.append(noise)
        order.append(fam_names.index(name))
        targets.append(weight / total)
    if not scores:
        return np.zeros((h, w), dtype=np.int16)

    stack = np.stack(scores)
    target = np.array(targets)
    # Je Familie einen Versatz einregeln, bis die Flaechenanteile den
    # gewuenschten entsprechen. Ein fester Bonus je Gewicht trifft die
    # Vorgabe nicht -- die Rauschfelder ueberlagern sich zu unterschiedlich.
    # Tune a per-family offset until the area shares match the request. A
    # fixed bonus per weight misses the target -- the noise fields overlap
    # too differently.
    offsets = np.zeros(len(scores))
    picked = np.argmax(stack, axis=0)
    for _ in range(40):
        picked = np.argmax(stack + offsets[:, None, None], axis=0)
        shares = np.array([(picked == i).mean() for i in range(len(scores))])
        error = target - shares
        if np.abs(error).max() < 0.015:
            break
        offsets += 0.4 * error
    lookup = np.array(order, dtype=np.int16)
    return lookup[picked]


def _smooth_families(field_: np.ndarray, passes: int = 2, radius: int = 2) -> np.ndarray:
    """Kleinstflecken aufloesen: jede Zelle bekommt die Mehrheitsfamilie ihrer
    Umgebung.

    Ohne das entstehen ueberall Ein-Kachel-Inseln -- genau die Sprenkel, die
    eine erzeugte Karte unruhig aussehen lassen.

    Dissolve tiny patches: every cell takes the majority family of its
    surroundings. Without this the map is littered with one-tile islands.
    """
    out = field_
    kinds = int(out.max()) + 1
    for _ in range(max(0, passes)):
        counts = np.zeros((kinds,) + out.shape, dtype=np.int16)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                shifted = np.roll(np.roll(out, dy, axis=0), dx, axis=1)
                for k in range(kinds):
                    counts[k] += (shifted == k)
        out = np.argmax(counts, axis=0).astype(np.int16)
    return out


def _components(mask: np.ndarray):
    """Zusammenhaengende Flaechen einzeln liefern.

    Yield connected areas one by one."""
    h, w = mask.shape
    besucht = np.zeros_like(mask)
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or besucht[sy, sx]:
                continue
            stack = [(sx, sy)]
            besucht[sy, sx] = True
            teil = np.zeros_like(mask)
            while stack:
                x, y = stack.pop()
                teil[y, x] = True
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not besucht[ny, nx]:
                        besucht[ny, nx] = True
                        stack.append((nx, ny))
            yield teil


def _mirror_region(grid: np.ndarray, mode: str) -> None:
    """Gesetzte Formationen auf die gespiegelte Haelfte uebertragen.

    Die Regionen sind schon symmetrisch; die Formationen werden zufaellig
    gesetzt und muessen daher nachgezogen werden, sonst ist die Karte fuer
    Mehrspieler unfair.

    Copy placed formations to the mirrored half: the regions are already
    symmetric, but the formations are placed randomly and must follow, or the
    map is unfair for multiplayer."""
    h, w = grid.shape
    if mode == SYM_MIRROR_X:
        grid[:, w // 2:] = grid[:, :w // 2][:, ::-1]
    elif mode == SYM_MIRROR_Y:
        grid[h // 2:, :] = grid[:h // 2, :][::-1, :]
    elif mode == SYM_ROT180:
        grid[h // 2:, :] = grid[:h // 2, :][::-1, ::-1]
    elif mode == SYM_QUAD:
        grid[:, w // 2:] = grid[:, :w // 2][:, ::-1]
        grid[h // 2:, :] = grid[:h // 2, :][::-1, :]


def _naht_passt(grid: np.ndarray, tm: "TileModel", tiles: np.ndarray,
                x: int, y: int) -> bool:
    """Passt der Rand eines Stempels zu dem, was schon daneben liegt?"""
    h, w = grid.shape
    dh, dw = tiles.shape
    def erlaubt(quelle, ziel, richtung):
        k, _ = tm.nachbarn(int(quelle), richtung)
        return k is None or int(ziel) in k

    for i in range(dw):
        if y > 0 and not erlaubt(grid[y - 1, x + i], tiles[0, i], "unten"):
            return False
        if y + dh < h and not erlaubt(tiles[dh - 1, i], grid[y + dh, x + i], "unten"):
            return False
    for j in range(dh):
        if x > 0 and not erlaubt(grid[y + j, x - 1], tiles[j, 0], "rechts"):
            return False
        if x + dw < w and not erlaubt(tiles[j, dw - 1], grid[y + j, x + dw], "rechts"):
            return False
    return True


def _scatter_details(grid, fam_field, tm, rng, ziel_zellen, gesperrt):
    """Steine, Risse und Krater ins passende Biom streuen.

    Immer als ganzer Stempel und nur dort, wo der Untergrund zur Familie
    passt -- eine Sandduene mitten im Fels sieht falsch aus. Die Dichte
    orientiert sich an den Originalkarten (rund 3 % der Flaeche).

    Scatter stones, cracks and craters into the matching biome: always as a
    whole stamp and only where the ground matches the family -- a sand dune in
    the middle of rock looks wrong. Density follows the original maps.
    """
    if ziel_zellen <= 0 or not tm.details:
        return 0
    h, w = grid.shape
    gesetzt = 0
    versuche = 0
    while gesetzt < ziel_zellen and versuche < ziel_zellen * 6 + 200:
        versuche += 1
        tiles, fam = tm.details[int(rng.integers(len(tm.details)))]
        dh, dw = tiles.shape
        if dw + 2 >= w or dh + 2 >= h:
            continue
        x = int(rng.integers(1, w - dw - 1))
        y = int(rng.integers(1, h - dh - 1))
        if gesperrt[y:y + dh, x:x + dw].any():
            continue
        # Naht pruefen: der Stempel wird als Ganzes ueber fertigen Boden
        # gelegt. Ohne Pruefung entstehen an seinem Rand Kachelpaare, die es
        # im Original nie gab -- gemessen 1.047 Stueck je drei Karten.
        # Check the seam: the stamp is laid over finished ground as a whole.
        # Without checking, its border creates tile pairs that never existed in
        # the originals -- measured 1,047 across three maps.
        if not _naht_passt(grid, tm, tiles, x, y):
            continue
        if fam and fam in tm.families:
            unter = fam_field[y:y + dh, x:x + dw]
            if float((unter == tm.families.index(fam)).mean()) < 0.75:
                continue
        grid[y:y + dh, x:x + dw] = tiles
        gesperrt[y:y + dh, x:x + dw] = True
        gesetzt += dw * dh
    return gesetzt


# Wie oft welche Art von Paket gewaehlt wird. Wrackteile bleiben selten --
# eine Absturzstelle je Karte erzaehlt etwas, zehn sind Schrottplatz.
# How often each kind of package is chosen; wrecks stay rare.
PAKET_GEWICHT = {"stein": 0.40, "riss": 0.28, "krater": 0.22, "wrack": 0.10, "ruine": 0.0}
PAKET_ZONE_MAX = 140          # Detailkacheln je Fundgebiet hoechstens
# Anteil der Gebiete, die sich an Klippen anlehnen (falls es welche gibt).
# Share of areas that lean on cliffs (if there are any).
PAKET_AN_KLIPPE = {"fuss": 0.35, "kante": 0.15}
PAKET_AN_KLIPPE_MAX = 12       # groesste Paketkante an der Wand
PAKET_THEMA_KLIPPE = {"fuss": {"riss": 0.6, "stein": 0.4},
                      "kante": {"riss": 0.65, "stein": 0.35}}


def _streue_pakete(grid, fam_field, tm, rng, ziel_zellen, gesperrt, pakete_liste=None,
                   klippen=None, H=None):
    """Streugut als Fundgebiete aus ganzen Detail-Paketen.

    Statt ueberall einzelne Steine gibt es wenige Gebiete mit einem Thema --
    ein Kraterfeld, ein Steinfeld, eine Bruchzone, hoechstens eine
    Absturzstelle -- und dort liegen mehrere Pakete beieinander. Ein Paket
    ist eine zusammengehoerige Gruppe aus den Originalkarten; gesetzt werden
    nur seine Details, nur auf seinen eigenen Boden, nie auf Uebergaenge.
    Der Rest der Karte bleibt ruhig.

    Mit Klippen (`klippen` = Klippenkacheln, `H` = 0 Tiefland / 1 Hochland)
    lehnen sich Gebiete an sie an: Geroell am Fuss, entlang der Wand
    aufgereiht, und Risse an der Abbruchkante oben. Ein Paket liegt immer
    ganz auf einer Ebene.

    Scatter as a few themed areas made of whole detail packages; the rest of
    the map stays calm. With cliffs, areas lean on them: rubble along the
    foot, cracks along the edge above. A package always sits on one level.
    """
    if ziel_zellen <= 0:
        return 0
    if pakete_liste is None:
        try:
            import pakete as _pk
            pakete_liste = _pk.laden()
        except Exception:
            pakete_liste = []
    if not pakete_liste:
        return _scatter_details(grid, fam_field, tm, rng, ziel_zellen, gesperrt)
    from scipy import ndimage as ndi
    h, w = grid.shape
    namen = tm.families
    lav = namen.index("lav") if "lav" in namen else -1
    nach: dict = {}
    for p in pakete_liste:
        if p.boden in namen and all(0 <= k < len(tm.family_of) for _, _, k in p.teile):
            nach.setdefault((p.boden, p.art), []).append(p)
    if not nach:
        return 0

    # Hart gesperrt (Klippen, Vulkane, Merkmale): kein Detail darauf und
    # keins direkt daneben. Ein Paketrahmen darf darueber ragen -- sonst
    # passt am Klippenfuss nie etwas hin. Gesetzte Pakete belegen dagegen
    # ihren ganzen Rahmen.
    # Hard-blocked: no detail on it or right next to it; a package frame may
    # reach over it. Placed packages occupy their whole frame.
    hart = gesperrt.copy()
    hart_nah = ndi.binary_dilation(hart, structure=np.ones((3, 3), bool))
    belegt = np.zeros(grid.shape, dtype=bool)
    ebene = (np.asarray(H) > 0) if H is not None and np.shape(H) == grid.shape \
        else np.zeros(grid.shape, dtype=bool)

    # Baender an den Klippen: Fuss (unten) und Kante (oben), 2-6 Kacheln weit.
    # Bands along the cliffs: foot (below) and edge (above).
    fuss = kante = None
    if klippen is not None and np.shape(klippen) == grid.shape and np.any(klippen):
        abst = ndi.distance_transform_edt(~np.asarray(klippen, bool))
        band = (abst >= 2) & (abst <= 6) & ~hart_nah
        band[:6, :] = band[-6:, :] = False
        band[:, :6] = band[:, -6:] = False
        fuss = np.argwhere(band & ~ebene)
        kante = np.argwhere(band & ebene)
        fuss = fuss if len(fuss) else None
        kante = kante if len(kante) else None

    def boden_bei(x, y) -> str:
        f = int(fam_field[y, x])
        n = namen[f] if 0 <= f < len(namen) else ""
        return "roc" if n == "lav" else n

    def setzen(p, x, y) -> bool:
        x0, y0 = x - p.breite // 2, y - p.hoehe // 2
        if x0 < 2 or y0 < 2 or x0 + p.breite > w - 2 or y0 + p.hoehe > h - 2:
            return False
        rahmen = (slice(y0, y0 + p.hoehe), slice(x0, x0 + p.breite))
        if belegt[rahmen].any():
            return False
        frei = ~hart[rahmen]
        if not frei.any():
            return False
        soll = namen.index(p.boden)
        # Boden und Ebene zaehlen nur auf der Seite, auf der das Paket liegt:
        # am Klippenfuss darf der Rahmen ueber die Wand ragen, die Details
        # selbst bleiben unten.
        # Ground counts only on the package's own level: at the cliff foot the
        # frame may reach over the wall, the details themselves stay below.
        stufe = bool(ebene[y0 + p.teile[0][1], x0 + p.teile[0][0]])
        seite = frei & (ebene[rahmen] == stufe)
        unter = fam_field[rahmen]
        passt = (unter == soll) | ((unter == lav) if p.boden == "roc" else False)
        if not seite.any() or float(passt[seite].mean()) < 0.9:
            return False
        for dx, dy, _k in p.teile:
            yy, xx = y0 + dy, x0 + dx
            if hart_nah[yy, xx] or bool(ebene[yy, xx]) != stufe:
                return False
            g = int(grid[yy, xx])
            fg = int(tm.family_of[g]) if 0 <= g < len(tm.family_of) else -1
            if tm.ist_uebergang[g] or not (fg == soll or (p.boden == "roc" and fg == lav)):
                return False
        for dx, dy, k in p.teile:
            grid[y0 + dy, x0 + dx] = k
        rand = (slice(max(0, y0 - 1), y0 + p.hoehe + 1), slice(max(0, x0 - 1), x0 + p.breite + 1))
        belegt[rand] = True
        gesperrt[rand] = True
        return True

    gesetzt = 0
    benutzt: dict = {}                    # Name -> wie oft auf der Karte
    # Grundzahl der Gebiete nach Kartengroesse; reicht die Dichte nicht (ein
    # Gebiet fasst nur so viel), kommen weitere hinzu.
    # Base number of areas by map size; more follow if the density needs it.
    zonen = max(2, int(round(h * w / 5500)))
    budget = min(ziel_zellen / zonen, PAKET_ZONE_MAX)
    wrack_zone = rng.random() < 0.7
    themen = [a for a in PAKET_GEWICHT if a not in ("wrack", "ruine")]
    streuung = 4.0 + 0.03 * max(h, w)
    for _z in range(zonen * 3 + int(ziel_zellen // 30)):   # Fehlversuche einplanen
        if gesetzt >= ziel_zellen:
            break
        # Wo liegt das Gebiet? Am Klippenfuss (Geroell), an der Kante oben
        # (Risse) oder frei in der Flaeche.
        # Where is the area: at the cliff foot, at the edge above, or free.
        art = "frei"
        if not wrack_zone:
            r = rng.random()
            if fuss is not None and r < PAKET_AN_KLIPPE["fuss"]:
                art = "fuss"
            elif kante is not None and r < PAKET_AN_KLIPPE["fuss"] + PAKET_AN_KLIPPE["kante"]:
                art = "kante"
        band = fuss if art == "fuss" else kante if art == "kante" else None
        if band is not None:
            my, mx = (int(v) for v in band[int(rng.integers(len(band)))])
            nahe = band[np.abs(band[:, 0] - my) + np.abs(band[:, 1] - mx) <= 2 * streuung]
        else:
            for _ in range(60):
                mx, my = int(rng.integers(8, w - 8)), int(rng.integers(8, h - 8))
                if not hart_nah[my, mx] and not belegt[my, mx] \
                        and any(k[0] == boden_bei(mx, my) for k in nach):
                    break
            else:
                continue
        boden = boden_bei(mx, my)
        # In den Originalen liegen an Klippen vor allem Risse, dann Steine;
        # weiter weg ist es umgekehrt (gemessen ueber alle Karten).
        # In the originals cliffs carry mostly cracks, then stones; further
        # away it is the other way round (measured over all maps).
        gewichte = PAKET_THEMA_KLIPPE.get(art, PAKET_GEWICHT)
        if wrack_zone and art == "frei" and (boden, "wrack") in nach:
            thema = "wrack"
            wrack_zone = False
        else:
            moeglich = [a for a in themen if (boden, a) in nach and gewichte.get(a, 0) > 0]
            if not moeglich:
                continue
            g = np.array([gewichte[a] for a in moeglich])
            thema = moeglich[int(rng.choice(len(moeglich), p=g / g.sum()))]
        liste = nach[(boden, thema)]
        # Eine Absturzstelle bekommt Krater und Steine als Beiwerk.
        beiwerk = [p for a in ("krater", "stein") for p in nach.get((boden, a), [])] \
            if thema == "wrack" else []
        zone_gesetzt = 0
        in_zone: set = set()
        zone_kacheln: set = set()
        # Nebenthema: ein Steinfeld hat auch mal einen Riss, ein Kraterfeld Steine.
        neben = [p for a in themen if a != thema for p in nach.get((boden, a), [])]
        for versuch in range(80):
            if zone_gesetzt >= min(budget, ziel_zellen - gesetzt):
                break
            if thema == "wrack":
                quelle = liste if (versuch == 0 or not beiwerk) else beiwerk
            else:
                quelle = neben if (neben and versuch > 0 and rng.random() < 0.3) else liste
            # Nie dasselbe Paket zweimal in einer Zone, und auf der Karte erst
            # die noch ungenutzten -- sonst sieht man das Kopieren sofort.
            # Never the same package twice in a zone; prefer unused ones.
            # Auch keine zwei Pakete aus fast denselben Kacheln (die kleinen
            # Kiesel-Haeufchen gibt es in mehreren Varianten).
            # Nor two packages made of almost the same tiles.
            frei_q = [p for p in quelle if p.name not in in_zone
                      and sum(k in zone_kacheln for _, _, k in p.teile) < 0.6 * len(p.teile)]
            if band is not None:
                # An der Wand ist wenig Platz: nur kleine Pakete.
                # Little room at the wall: small packages only.
                frei_q = [p for p in frei_q if max(p.breite, p.hoehe) <= PAKET_AN_KLIPPE_MAX]
            if not frei_q:
                continue
            # Ungenutzte bevorzugen, aber nicht ausschliesslich -- ein grosses
            # Paket, das nirgends hinpasst, darf die kleinen nicht aussperren.
            # Prefer unused packages, but not exclusively.
            gew = np.array([1.0 / (1 + 3 * benutzt.get(p.name, 0)) for p in frei_q])
            p = frei_q[int(rng.choice(len(frei_q), p=gew / gew.sum()))]
            if band is not None:
                # Entlang der Wand aufreihen statt rund um einen Punkt.
                # Line up along the wall instead of around a point.
                y, x = (int(v) for v in nahe[int(rng.integers(len(nahe)))])
            else:
                s = streuung * (0.3 if versuch == 0 else 1.0)
                x = int(round(mx + rng.normal(0, s)))
                y = int(round(my + rng.normal(0, s)))
            if setzen(p, x, y):
                zone_gesetzt += len(p.teile)
                in_zone.add(p.name)
                zone_kacheln.update(k for _, _, k in p.teile)
                benutzt[p.name] = benutzt.get(p.name, 0) + 1
        gesetzt += zone_gesetzt
    return gesetzt


def _volcano_sites(fam_field: np.ndarray, params: "MapGenParams",
                   rng: np.random.Generator, rock_family: int) -> list[tuple[int, int]]:
    """Standorte fuer Vulkane suchen und die Umgebung auf Fels stellen.

    Der Vulkan selbst ist ein Kachel-Stempel, die Lava kommt spaeter im Spiel
    aus dem Ausbruch -- hier wird nur der Untergrund vorbereitet.

    Find volcano sites and turn their surroundings into rock. The volcano
    itself is a tile stamp; the lava comes from the eruption in-game -- this
    only prepares the ground.
    """
    if params.volcanoes <= 0:
        return []
    h, w = fam_field.shape
    radius = max(6, int(round((params.lava_zone_tiles / np.pi) ** 0.5)))
    margin = radius + 4
    if w <= 2 * margin or h <= 2 * margin:
        return []

    def mirrored(cx: int, cy: int) -> list[tuple[int, int]]:
        if params.symmetry == SYM_MIRROR_X:
            return [(w - 1 - cx, cy)]
        if params.symmetry == SYM_MIRROR_Y:
            return [(cx, h - 1 - cy)]
        if params.symmetry == SYM_ROT180:
            return [(w - 1 - cx, h - 1 - cy)]
        if params.symmetry == SYM_QUAD:
            return [(w - 1 - cx, cy), (cx, h - 1 - cy), (w - 1 - cx, h - 1 - cy)]
        return []

    ys, xs = np.mgrid[0:h, 0:w]
    centres: list[tuple[int, int]] = []
    wanted = params.volcanoes
    guard = 0
    while len(centres) < wanted and guard < 40:
        guard += 1
        cx = int(rng.integers(margin, w - margin))
        cy = int(rng.integers(margin, h - margin))
        if any((cx - ox) ** 2 + (cy - oy) ** 2 < (3 * radius) ** 2 for ox, oy in centres):
            continue
        for gx, gy in [(cx, cy)] + mirrored(cx, cy):
            if len(centres) >= wanted:
                break
            # Vulkane stehen im Fels -- die Umgebung entsprechend setzen,
            # mit unregelmaessigem Rand statt Kreis.
            # Volcanoes sit in rock -- set the surroundings accordingly, with
            # an irregular rim instead of a circle.
            wobble = 0.75 + 0.5 * _value_noise(rng, h, w, 8)
            dist = np.sqrt((xs - gx) ** 2 + (ys - gy) ** 2)
            fam_field[dist < radius * wobble] = rock_family
            centres.append((gx, gy))
    return centres


def _lava_zone(centre: tuple[int, int], shape: tuple[int, int],
               tiles: int, rng: np.random.Generator) -> list[tuple[int, int]]:
    """Flaeche, in der beim Ausbruch Lava fliessen darf (lavaPossible).

    Kein Gelaende, sondern eine Angabe fuer die Mission: der Codegen setzt
    daraus `GameMap::SetLavaPossible(...)`.

    The area in which lava may flow during an eruption. Not terrain but a
    mission fact: codegen turns it into `GameMap::SetLavaPossible(...)`.
    """
    h, w = shape
    cx, cy = centre
    radius = max(4, int(round((tiles / np.pi) ** 0.5)))
    wobble = 0.7 + 0.6 * _value_noise(rng, h, w, 10)
    ys, xs = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    mask = dist < radius * wobble
    ys_i, xs_i = np.nonzero(mask)
    return [(int(x), int(y)) for x, y in zip(xs_i, ys_i)]


def _stamp_volcanoes(grid: np.ndarray, centres: list[tuple[int, int]],
                     tm: "TileModel", rng: np.random.Generator) -> list[tuple[int, int]]:
    """In jedes Lavagebiet einen Vulkan setzen (echter Stempel aus der Karte)."""
    placed = []
    if not tm.volcanoes:
        return placed
    h, w = grid.shape
    for cx, cy in centres:
        name, vw, vh, block = max(tm.volcanoes, key=lambda v: v[1] * v[2])
        if vw > w or vh > h:
            name, vw, vh, block = min(tm.volcanoes, key=lambda v: v[1] * v[2])
        x0 = int(np.clip(cx - vw // 2, 0, w - vw))
        y0 = int(np.clip(cy - vh // 2, 0, h - vh))
        grid[y0:y0 + vh, x0:x0 + vw] = block
        placed.append((x0 + vw // 2, y0 + vh // 2))
    return placed


def _dissolve_small_biomes(field_: np.ndarray, min_cells: int) -> np.ndarray:
    """Zu kleine Biomflecken im umgebenden Biom aufloesen.

    Ein paar Kacheln Sand mitten in der Erde sehen nach Rauschen aus, nicht
    nach Landschaft. Jede zusammenhaengende Flaeche unter `min_cells` bekommt
    die Familie ihrer haeufigsten Nachbarn.

    Dissolve biome patches that are too small. A few tiles of sand in the
    middle of dirt look like noise, not landscape: every connected area below
    `min_cells` takes the family of its most common neighbours.
    """
    if min_cells <= 1:
        return field_
    h, w = field_.shape
    out = field_.copy()
    besucht = np.zeros(field_.shape, dtype=bool)
    for sy in range(h):
        for sx in range(w):
            if besucht[sy, sx]:
                continue
            fam = int(field_[sy, sx])
            stack = [(sx, sy)]
            besucht[sy, sx] = True
            zellen = []
            rand = []
            while stack:
                x, y = stack.pop()
                zellen.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if int(field_[ny, nx]) == fam:
                        if not besucht[ny, nx]:
                            besucht[ny, nx] = True
                            stack.append((nx, ny))
                    else:
                        rand.append(int(field_[ny, nx]))
            if len(zellen) >= min_cells or not rand:
                continue
            werte, anzahl = np.unique(np.array(rand), return_counts=True)
            ersatz = int(werte[int(np.argmax(anzahl))])
            for x, y in zellen:
                out[y, x] = ersatz
    return out


def _apply_symmetry(field_: np.ndarray, mode: str) -> np.ndarray:
    """Regionen spiegeln -- gespiegelt wird die LAGE, nicht die Kachelgrafik.

    Mirror the regions -- the layout is mirrored, not the tile graphics
    (a mirrored tile index would not be a mirrored picture)."""
    out = field_.copy()
    h, w = out.shape
    if mode == SYM_MIRROR_X:
        out[:, w // 2:] = out[:, :w // 2][:, ::-1]
    elif mode == SYM_MIRROR_Y:
        out[h // 2:, :] = out[:h // 2, :][::-1, :]
    elif mode == SYM_ROT180:
        out[h // 2:, :] = out[:h // 2, :][::-1, ::-1]
    elif mode == SYM_QUAD:
        out[:, w // 2:] = out[:, :w // 2][:, ::-1]
        out[h // 2:, :] = out[:h // 2, :][::-1, :]
    return out
