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


class _Rauschen:
    """Wertrauschen, an beliebigen (auch verzogenen) Stellen abfragbar.

    Value noise that can be sampled anywhere, including warped coordinates."""

    def __init__(self, rng: np.random.Generator, freq: float):
        self.freq = max(2.0, float(freq))
        n = int(np.ceil(self.freq)) * 3 + 4      # Rand fuer verzogene Abfragen
        self.basis = rng.random((n, n))
        self.mitte = n / 2.0

    def __call__(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """u, v: Kartenkoordinaten in Einheiten der Kartenbreite, Mitte 0."""
        n = self.basis.shape[0]
        x = np.clip(u * self.freq + self.mitte, 0, n - 1.001)
        y = np.clip(v * self.freq + self.mitte, 0, n - 1.001)
        x0, y0 = x.astype(int), y.astype(int)
        fx, fy = x - x0, y - y0
        fx = fx * fx * (3 - 2 * fx)
        fy = fy * fy * (3 - 2 * fy)
        b = self.basis
        oben = b[y0, x0] * (1 - fx) + b[y0, x0 + 1] * fx
        unten = b[y0 + 1, x0] * (1 - fx) + b[y0 + 1, x0 + 1] * fx
        return oben * (1 - fy) + unten * fy


def _geologie(params: MapGenParams, rng: np.random.Generator):
    """Gemeinsame Verzerrung fuer alle Boeden einer Karte.

    Auf einem echten Planeten gehoert das Gelaende zusammen: Duenen liegen
    quer zum Wind, Gesteinsbaender folgen derselben Schichtung. Frueher hatte
    jeder Boden sein eigenes, rundes Rauschen -- es entstanden Kreisflecken
    ohne Bezug zueinander. Jetzt teilen sich alle Boeden eine Hauptrichtung
    und ein gemeinsames Verwirbelungsfeld (domain warping); die Formen werden
    laenglich, fliessend und greifen ineinander.

    Shared distortion for all grounds of a map: one main direction and one
    warp field, so shapes become elongated and flowing and relate to each
    other instead of being unrelated round blobs.
    """
    h, w = params.height, params.width
    winkel = float(rng.uniform(0, np.pi))
    wirbel_a = _Rauschen(rng, 2.5)
    wirbel_b = _Rauschen(rng, 2.5)
    fein_a = _Rauschen(rng, 7.0)
    fein_b = _Rauschen(rng, 7.0)
    seite = float(max(h, w))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    u = (xx - w / 2.0) / seite
    v = (yy - h / 2.0) / seite
    # Verwirbeln: grob fuer den Fluss, fein fuer ausgefranste Raender.
    # Warp: coarse for the flow, fine for frayed edges.
    staerke = 0.22 + 0.10 * params.roughness
    du = staerke * (wirbel_a(u, v) - 0.5) + 0.05 * (fein_a(u, v) - 0.5)
    dv = staerke * (wirbel_b(u, v) - 0.5) + 0.05 * (fein_b(u, v) - 0.5)
    u, v = u + du, v + dv
    # In die Hauptrichtung drehen. / rotate into the main direction
    c, s = np.cos(winkel), np.sin(winkel)
    laengs = c * u + s * v
    quer = -s * u + c * v
    return laengs, quer


# Wie stark ein Boden in der Hauptrichtung gestreckt wird: Sand bildet lange
# Duenenfelder, Fels Gesteinsbaender, Erde bleibt am rundesten.
# How much a ground is stretched along the main direction.
_STRECKUNG = {"san": 2.6, "roc": 1.9, "sno": 1.7, "veg": 1.3, "mud": 1.3}


def _family_field(params: MapGenParams, rng: np.random.Generator,
                  fam_names: list[str]) -> np.ndarray:
    """Welche Familie bekommt welche Zelle? -> (h, w) Familienindex."""
    h, w = params.height, params.width
    # Zerkluefung steuert die Frequenz: wenige grosse Flaechen vs. viele kleine.
    # Roughness controls the frequency: few large areas vs. many small ones.
    base_freq = 3 + params.roughness * 14
    laengs, quer = _geologie(params, rng)
    scores = []
    order = []
    targets = []
    total = sum(v for v in params.mix.values() if v > 0) or 1.0
    for name, weight in params.mix.items():
        if weight <= 0 or name not in fam_names:
            continue
        streck = _STRECKUNG.get(name, 1.4)
        grob = _Rauschen(rng, base_freq)
        fein = _Rauschen(rng, base_freq * 2)
        noise = (grob(laengs / streck, quer)
                 + 0.5 * fein(laengs / streck, quer)) / 1.5
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


def _scatter_details(grid, fam_field, tm, rng, ziel_zellen, gesperrt,
                     klippen=None, vulkane=None):
    """Streugut als zusammengehoerige Felder statt gleichmaessig verteilt.

    Frueher fiel jeder Stempel an eine beliebige Stelle der Karte -- die Karte
    war dann gleichmaessig mit Einzelsteinen, Rissen und sogar Wrackteilen
    gesprenkelt, nichts gehoerte zusammen. Jetzt entstehen wenige Felder mit
    einem Thema, und das Thema haengt am Gelaende:

    - Geroellhalden am Fuss der Klippen und rund um Vulkane (Felsen),
    - Kraterfelder: ein grosser Einschlag, kleinere drumherum,
    - Bruchlinien: Risse entlang einer gewundenen Linie,
    - hoechstens eine Absturzstelle: Wrackteile auf einer Schleifspur.

    Immer als ganzer Stempel und nur dort, wo der Untergrund zur Familie passt.
    Die Gesamtdichte bleibt wie bisher (Regler 0.5 = rund 3 % der Flaeche).

    Scatter as coherent fields instead of evenly spread: few fields with a
    theme tied to the terrain -- scree at cliff feet and around volcanoes,
    crater fields, fault lines of cracks, at most one crash site. Always whole
    stamps on matching ground; the overall density stays as before.
    """
    if ziel_zellen <= 0 or not tm.details:
        return 0
    import detail_themen as dt
    h, w = grid.shape
    # Stempel je (Familie, Thema), groessere zuerst fuer die Feldmitte.
    # Stamps per (ground, theme).
    vorrat: dict = {}
    for kacheln, fam in tm.details:
        vorrat.setdefault((fam, dt.thema(kacheln)), []).append(kacheln)

    def stempel_fuer(fam: str, thema: str):
        liste = vorrat.get((fam, thema))
        if not liste and thema == dt.KRATER:
            liste = vorrat.get((fam, dt.RISSE))     # Erde: Mulden statt Krater
        return liste or []

    namen = tm.families
    offen = ~gesperrt
    gesetzt = 0

    def setze(kacheln, x, y) -> bool:
        nonlocal gesetzt
        dh, dw = kacheln.shape
        if x < 1 or y < 1 or x + dw >= w - 1 or y + dh >= h - 1:
            return False
        if gesperrt[y:y + dh, x:x + dw].any():
            return False
        if not _naht_passt(grid, tm, kacheln, x, y):
            return False
        grid[y:y + dh, x:x + dw] = kacheln
        # Ein Rand von einer Kachel bleibt frei -- zwei Stempel direkt
        # aneinander ergeben Naehte, die es im Original nicht gibt.
        gesperrt[max(0, y - 1):y + dh + 1, max(0, x - 1):x + dw + 1] = True
        gesetzt += dw * dh
        return True

    def boden_bei(x, y) -> str:
        f = int(fam_field[y, x])
        return namen[f] if 0 <= f < len(namen) else ""

    def passt_boden(kacheln, fam, x, y) -> bool:
        dh, dw = kacheln.shape
        if not fam or fam not in namen:
            return True
        unter = fam_field[max(0, y):y + dh, max(0, x):x + dw]
        return unter.size > 0 and float((unter == namen.index(fam)).mean()) >= 0.75

    def feld(mx, my, thema, budget, streuung, richtung=None):
        """Stempel um (mx, my) setzen -- dicht in der Mitte, duenn am Rand.
        Mit `richtung` laufen sie als Linie (Bruchlinie, Schleifspur)."""
        fam = boden_bei(mx, my)
        liste = stempel_fuer(fam, thema)
        if not liste:
            return 0
        vorher = gesetzt
        groesste = sorted(liste, key=lambda t: -t.size)
        versuche = 0
        erstes = True
        px, py = float(mx), float(my)
        while gesetzt - vorher < budget and versuche < budget * 4 + 30:
            versuche += 1
            if erstes and thema == dt.KRATER:
                kacheln = groesste[0]          # der grosse Einschlag in der Mitte
            else:
                kacheln = liste[int(rng.integers(len(liste)))]
            dh, dw = kacheln.shape
            if richtung is not None:
                # Ein Stueck weiter entlang der (leicht pendelnden) Linie.
                richtung = richtung + float(rng.normal(0.0, 0.35))
                px += np.cos(richtung) * (max(dw, dh) + 1.5)
                py += np.sin(richtung) * (max(dw, dh) + 1.5)
                x = int(round(px + rng.normal(0.0, 0.8))) - dw // 2
                y = int(round(py + rng.normal(0.0, 0.8))) - dh // 2
                if not (0 <= px < w and 0 <= py < h):
                    break
            else:
                s = streuung * (0.35 if erstes else 1.0)
                x = int(round(mx + rng.normal(0.0, s))) - dw // 2
                y = int(round(my + rng.normal(0.0, s))) - dh // 2
            if not passt_boden(kacheln, fam, x, y):
                continue
            if setze(kacheln, x, y):
                erstes = False
        return gesetzt - vorher

    # --- Ankerpunkte aus dem Gelaende / anchors from the terrain ---------
    def zufallspunkt(maske):
        ys, xs = np.nonzero(maske)
        if len(xs) == 0:
            return None
        k = int(rng.integers(len(xs)))
        return int(xs[k]), int(ys[k])

    rand = np.zeros_like(offen)
    rand[3:h - 3, 3:w - 3] = True
    frei = offen & rand
    # Wandfuss: freie Zellen 1-3 Kacheln neben einer Klippe.
    fuss = np.zeros_like(offen)
    if klippen is not None and klippen.any():
        nah = klippen.copy()
        for _ in range(3):
            n2 = nah.copy()
            n2[1:, :] |= nah[:-1, :]
            n2[:-1, :] |= nah[1:, :]
            n2[:, 1:] |= nah[:, :-1]
            n2[:, :-1] |= nah[:, 1:]
            nah = n2
        fuss = nah & ~klippen & frei
    vulkan_rand = np.zeros_like(offen)
    for vx, vy in (vulkane or []):
        yy, xx = np.ogrid[:h, :w]
        d2 = (xx - vx) ** 2 + (yy - vy) ** 2
        vulkan_rand |= (d2 >= 9 ** 2) & (d2 <= 15 ** 2)
    vulkan_rand &= frei

    # Budget verteilen: Geroell 40 %, Krater 25 %, Bruchlinien 25 %, Wrack 10 %.
    flaeche = h * w
    feld_groesse = max(24, int(round(ziel_zellen / max(2, flaeche / 2600))))
    plan = []
    rest = ziel_zellen
    if rng.random() < 0.6 and ziel_zellen >= 60:
        plan.append(dt.WRACK)
    while rest > 0 and len(plan) < 200:
        r = rng.random()
        plan.append(dt.FELSEN if r < 0.45 else dt.KRATER if r < 0.72 else dt.RISSE)
        rest -= feld_groesse
    fehlversuche = 0
    for thema in plan:
        if gesetzt >= ziel_zellen or fehlversuche > 40:
            break
        budget = min(feld_groesse, ziel_zellen - gesetzt)
        if thema == dt.FELSEN:
            quelle = vulkan_rand if (vulkan_rand.any() and rng.random() < 0.35) else \
                fuss if (fuss.any() and rng.random() < 0.75) else frei
            punkt = zufallspunkt(quelle)
            n = feld(*punkt, thema, budget, streuung=3.5) if punkt else 0
        elif thema == dt.KRATER:
            punkt = zufallspunkt(frei & ~fuss)
            n = feld(*punkt, thema, budget, streuung=4.5) if punkt else 0
        elif thema == dt.RISSE:
            punkt = zufallspunkt(frei)
            n = feld(*punkt, thema, budget, streuung=0.0,
                     richtung=float(rng.uniform(0, 2 * np.pi))) if punkt else 0
        else:
            punkt = zufallspunkt(frei & ~fuss)
            n = 0
            if punkt:
                # Einschlag der Absturzstelle, dann die Schleifspur dahinter.
                n = feld(*punkt, dt.KRATER, max(6, budget // 3), streuung=1.5)
                n += feld(*punkt, dt.WRACK, budget, streuung=0.0,
                          richtung=float(rng.uniform(0, 2 * np.pi)))
        fehlversuche = fehlversuche + 1 if n == 0 else 0
    # Was die Felder nicht unterbrachten (zu wenig passender Boden), kommt in
    # weitere Felder -- nie als Einzelstein ins Nichts.
    runde = 0
    while gesetzt < ziel_zellen * 0.8 and runde < 60:
        runde += 1
        punkt = zufallspunkt(frei)
        if punkt is None:
            break
        feld(*punkt, dt.FELSEN if runde % 2 else dt.KRATER,
             min(feld_groesse, ziel_zellen - gesetzt), streuung=3.5)
    return gesetzt


def _volcano_sites(fam_field: np.ndarray, params: "MapGenParams",
                   rng: np.random.Generator, rock_family: int,
                   formen: list | None = None) -> list[tuple[int, int]]:
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
            # Vulkane stehen im Fels. Statt einer runden Scheibe laufen
            # Lavafels-Zungen den Hang hinunter -- erstarrte Stroeme, die zum
            # Vulkan gehoeren. Spaeter fliesst auch die Lava dort entlang.
            # Volcanoes sit in rock. Instead of a round disc, tongues of lava
            # rock run downhill -- frozen flows belonging to the volcano. Lava
            # will later flow along them too.
            form = _lavazungen(gx, gy, radius, (h, w), rng)
            fam_field[form] = rock_family
            if formen is not None:
                formen.append(((gx, gy), form))
            centres.append((gx, gy))
    return centres


def _lavazungen(cx: int, cy: int, radius: int, shape: tuple[int, int],
                rng: np.random.Generator) -> np.ndarray:
    """Kegel plus 3-5 erstarrte Lavastroeme, die vom Vulkan weglaufen.

    Cone plus 3-5 frozen lava flows running away from the volcano."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w]
    dx, dy = xs - cx, ys - cy
    dist = np.sqrt(dx * dx + dy * dy)
    winkel = np.arctan2(dy, dx)
    reich = np.full((h, w), 0.8 * radius, dtype=np.float64)
    for _ in range(int(rng.integers(3, 6))):
        richtung = float(rng.uniform(-np.pi, np.pi))
        laenge = radius * float(rng.uniform(1.6, 2.8))
        breite = float(rng.uniform(0.18, 0.32))
        diff = np.angle(np.exp(1j * (winkel - richtung)))
        reich = np.maximum(reich, laenge * np.exp(-(diff / breite) ** 2))
    rand = 0.8 + 0.4 * _value_noise(rng, h, w, 12)
    form = dist < reich * rand
    # Duenne Spitzen weg (Oeffnen mit 1 Zelle): eine Zunge, schmaler als die
    # Uebergangszone, ergaebe nur Mischkacheln ohne Boden dazwischen.
    # Remove thin tips (opening by 1 cell).
    def schrumpf(m):
        o = m.copy()
        o[1:, :] &= m[:-1, :]
        o[:-1, :] &= m[1:, :]
        o[:, 1:] &= m[:, :-1]
        o[:, :-1] &= m[:, 1:]
        return o

    def wachs(m):
        o = m.copy()
        o[1:, :] |= m[:-1, :]
        o[:-1, :] |= m[1:, :]
        o[:, 1:] |= m[:, :-1]
        o[:, :-1] |= m[:, 1:]
        return o
    return wachs(wachs(schrumpf(schrumpf(form))))


def _lava_zone(centre: tuple[int, int], shape: tuple[int, int],
               tiles: int, rng: np.random.Generator,
               form: np.ndarray | None = None) -> list[tuple[int, int]]:
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
    if form is not None and form[min(max(cy, 0), h - 1), min(max(cx, 0), w - 1)]:
        # Die Lava folgt den erstarrten Stroemen: die naechsten `tiles` Zellen
        # der Zungen, vom Krater aus gezaehlt.
        # Lava follows the frozen flows: the nearest `tiles` cells of them.
        kandidaten = np.nonzero(form.ravel())[0]
        reihe = kandidaten[np.argsort(dist.ravel()[kandidaten], kind="stable")]
        mask = np.zeros(h * w, dtype=bool)
        mask[reihe[:max(1, int(tiles * 1.4))]] = True
        mask = mask.reshape(h, w)
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
