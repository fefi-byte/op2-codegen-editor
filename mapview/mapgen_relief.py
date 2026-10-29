"""Relief: Hoehenfeld, Landschaftsmodus, Konturen und Merkmale (Tal, Berg, ...).

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

Relief: height field, landscape mode, contours and features. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # nur fuer Typangaben
    from mapgen_basis import MapGenParams  # noqa: F401
    from mapgen_modell import TileModel  # noqa: F401


import numpy as np

import shapegen  # noqa: E402
from mapgen_basis import (  # noqa: E402
    FEATURE_KINDS,
    FEAT_BERG,
    FEAT_ENGE,
    FEAT_FREI,
    FEAT_PLATEAU,
    FEAT_TAL,
    GEGENUEBER,
    SEKTOREN,
    SYM_MIRROR_X,
    SYM_MIRROR_Y,
    SYM_NONE,
    SYM_QUAD,
    SYM_ROT180,
)
from mapgen_felder import (  # noqa: E402
    _components,
    _smooth_families,
)


def _hoehenfeld(params: "MapGenParams", rng: np.random.Generator,
                layout: list) -> np.ndarray:
    """Wo soll Hochland sein? Die Form der Klippen, noch ohne eine Kachel.

    Merkmale liefern gezielte Formen (Berg, Tal, Engstelle), der
    Klippen-Regler streut zusaetzliche Blobs. Alles frei erzeugt -- es wird
    nichts mehr aus den Originalkarten kopiert, deshalb gibt es auch keine
    geraden Schnittkanten mehr.

    Where should highland be? The shape of the cliffs, still without a single
    tile. Features contribute deliberate shapes, the cliff slider scatters
    additional blobs. All generated freely -- nothing is copied from the
    original maps any more, which is why there are no straight cut edges left.
    """
    h, w = params.height, params.width
    H = np.zeros((h, w), dtype=np.int8)
    for eintrag in layout:
        kind = eintrag["feat"].kind
        if kind == FEAT_BERG:
            H |= shapegen.blob((h, w), (eintrag["x"], eintrag["y"]),
                               eintrag["radius"], rng, rauheit=0.5)
        elif kind == FEAT_PLATEAU:
            # Plateaus sind flacher und runder als Berge -- man soll oben
            # bauen koennen.
            # Plateaus are flatter and rounder than mountains -- you should be
            # able to build on top.
            H |= shapegen.blob((h, w), (eintrag["x"], eintrag["y"]),
                               int(eintrag["radius"] * 1.3), rng, rauheit=0.25)
        elif kind == FEAT_TAL:
            H |= shapegen.korridor((h, w), eintrag["pfad"], eintrag["breite"], rng)
        elif kind == FEAT_ENGE:
            pfad = eintrag["pfad"]
            mitte = len(pfad) // 2 + int(rng.integers(-len(pfad) // 6,
                                                      len(pfad) // 6 + 1))
            H |= shapegen.riegel((h, w), pfad, mitte,
                                 max(2, eintrag["breite"] // 2), rng)
    anzahl = int(round(params.cliffs * w * h / 900))
    for _ in range(anzahl):
        cx = int(rng.integers(6, max(7, w - 6)))
        cy = int(rng.integers(6, max(7, h - 6)))
        r = int(rng.integers(6, 16))
        H |= shapegen.blob((h, w), (cx, cy), r, rng, rauheit=0.55)
    # Freiflaechen ausstanzen -- dort soll gebaut werden koennen.
    # Punch out clearings -- they are meant to be buildable.
    for eintrag in layout:
        if eintrag["feat"].kind == FEAT_FREI:
            # Mit Zuschlag ausstanzen: das Wandband ist drei Zellen dick und
            # sein Fuss laege sonst noch in der Freiflaeche.
            # Punch with margin: the wall band is three cells thick and its
            # foot would otherwise still lie inside the clearing.
            H = (H & ~_feature_maske(eintrag, (h, w), rand=4)).astype(np.int8)
    if H.any():
        # Kante rasten, sonst franst die Klippe zellenweise aus.
        # Snap the edge, otherwise the cliff frays cell by cell.
        H = shapegen.begradige(H, block=3)
        H = shapegen.entferne_kleinkram(H, mindest=24)
        H[:3, :] = 0
        H[-3:, :] = 0
        H[:, :3] = 0
        H[:, -3:] = 0
    return H


# --------------------------------------------------------------------------
# Landschaftsmodus: ein Relief statt gestreuter Flecken. Das Hochland ist ein
# Massiv an einer Kartenseite plus freistehende Mesas; ausgetrocknete
# Flussbetten schneiden Schluchten hindurch. Die Klippen entstehen NICHT mehr
# ueber das Zelltypband (_male_klippen), sondern indem die Hochlandkontur als
# Linienzug abgelaufen und mit `klippe_algo.klippe_aus_linie` gesetzt wird --
# derselbe Gelaende-Loeser wie beim Klippenpinsel im Editor.
#
# Landscape mode: one relief instead of scattered patches. The highland is a
# massif anchored at one map side plus free-standing mesas; dry riverbeds cut
# gorges through it. Cliffs are no longer derived from the cell-type band
# (_male_klippen) but by walking the highland contour as a polyline and
# covering it with `klippe_algo.klippe_aus_linie` -- the same terrain solver
# as the editor's cliff brush.

# Moore-Nachbarschaft im Uhrzeigersinn, beginnend im Westen.
# Moore neighbourhood clockwise, starting west.
_MOORE = [(-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1)]


def _fluss_pfad(start, ziel, shape, rng: np.random.Generator
                ) -> list[tuple[int, int]]:
    """Maeandernder Pfad von `start` Richtung `ziel` -> [(x, y)].

    Ein ausgetrocknetes Flussbett ist kein Zufallslauf: es haelt grob die
    Richtung und pendelt seitlich aus. Kurs zum Ziel plus eine langsam
    laufende Seitwaertswelle ergibt genau das; Zufall steckt nur in Phase,
    Wellenlaenge und Auslenkung.

    A meandering path: heading towards the target plus a slowly running
    sideways wave; randomness only in phase, wavelength and amplitude.
    """
    h, w = shape
    x, y = float(start[0]), float(start[1])
    tx, ty = float(ziel[0]), float(ziel[1])
    punkte = [(int(round(x)), int(round(y)))]
    phase = float(rng.uniform(0, 2 * np.pi))
    takt = float(rng.uniform(0.05, 0.09))
    auslenkung = float(rng.uniform(0.5, 0.85))
    for schritt in range(4 * (w + h)):
        dx, dy = tx - x, ty - y
        if float(np.hypot(dx, dy)) < 2.0:
            break
        winkel = float(np.arctan2(dy, dx))
        winkel += auslenkung * float(np.sin(phase + schritt * takt))
        x = min(max(x + float(np.cos(winkel)), 1.0), w - 2.0)
        y = min(max(y + float(np.sin(winkel)), 1.0), h - 2.0)
        p = (int(round(x)), int(round(y)))
        if p != punkte[-1]:
            punkte.append(p)
        if p[0] <= 1 or p[0] >= w - 2 or p[1] <= 1 or p[1] >= h - 2:
            break
    return punkte


def _pfad_band(shape, punkte, radius: float) -> np.ndarray:
    """Zellen im Abstand <= radius um den Pfad -- das Bett bzw. die Schlucht."""
    h, w = shape
    band = np.zeros((h, w), dtype=bool)
    r = int(np.ceil(radius))
    for px, py in punkte:
        y0, y1 = max(0, py - r), min(h, py + r + 1)
        x0, x1 = max(0, px - r), min(w, px + r + 1)
        ys, xs = np.ogrid[y0:y1, x0:x1]
        band[y0:y1, x0:x1] |= ((xs - px) ** 2 + (ys - py) ** 2) <= radius ** 2
    return band


def _dehne(mask: np.ndarray, schritte: int) -> np.ndarray:
    """4er-Dehnung um `schritte` Zellen (randfest, ohne np.roll-Umlauf)."""
    out = mask.copy()
    for _ in range(max(0, schritte)):
        gewachsen = out.copy()
        gewachsen[1:, :] |= out[:-1, :]
        gewachsen[:-1, :] |= out[1:, :]
        gewachsen[:, 1:] |= out[:, :-1]
        gewachsen[:, :-1] |= out[:, 1:]
        out = gewachsen
    return out


def _landschaft_hoehenfeld(params: "MapGenParams", rng: np.random.Generator
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Relief des Landschaftsmodus -> (H, Flussbetten).

    Ein Massiv, an einer zufaelligen Kartenseite verankert, ein bis drei
    freistehende Mesas, und die Flussbetten schneiden Schluchten durch das
    Massiv. Die Kanten werden auf ein Viererraster gerastet: Laeufe unter vier
    Zellen kann der Blockweg nicht sauber belegen (mud-Bloecke sind 3 bis 5
    lang), und ein groeberes Raster erzeugt genau die "mehrere Kacheln
    geradeaus, dann sauber abbiegen"-Kanten der Originalkarten.

    The relief of landscape mode -> (H, riverbeds). A massif anchored at a
    random map side, one to three mesas, riverbeds cutting gorges through the
    massif. Edges are snapped to a four-cell grid: the block path cannot
    cleanly cover runs shorter than four cells.
    """
    h, w = params.height, params.width
    flaeche = w * h
    H = np.zeros((h, w), dtype=np.int8)
    # 0 = West, 1 = Ost, 2 = Nord, 3 = Sued.
    seite = int(rng.integers(4))
    # Zielanteil des Massivs an der Karte; der Klippenregler stockt auf.
    # Target share of the massif; the cliff slider adds to it.
    ziel = 0.16 + 0.45 * params.cliffs
    grundradius = int(round(np.sqrt(flaeche) / 5.5))
    for _ in range(10):
        if float((H > 0).mean()) >= ziel:
            break
        r = int(rng.integers(max(4, grundradius - 4), grundradius + 5))
        laengs = float(rng.uniform(0.08, 0.92))
        tiefe = float(rng.uniform(0.0, 0.55)) * r
        if seite == 0:
            cx, cy = int(tiefe), int(laengs * h)
        elif seite == 1:
            cx, cy = w - 1 - int(tiefe), int(laengs * h)
        elif seite == 2:
            cx, cy = int(laengs * w), int(tiefe)
        else:
            cx, cy = int(laengs * w), h - 1 - int(tiefe)
        H |= shapegen.blob((h, w), (cx, cy), r, rng, rauheit=0.35)
    massiv = H.astype(bool)

    # Mesas: freistehende Tafelberge im Tiefland, mit Abstand vom Massiv.
    # Mesas: free-standing table mountains in the lowland, clear of the massif.
    anzahl_mesas = max(1, int(round(flaeche / 12000)))
    sperr = _dehne(massiv, 8)
    for _ in range(anzahl_mesas * 6):
        if anzahl_mesas <= 0:
            break
        r = int(rng.integers(5, 9))
        cx = int(rng.integers(r + 4, w - r - 4))
        cy = int(rng.integers(r + 4, h - r - 4))
        if sperr[cy, cx]:
            continue
        mesa = shapegen.blob((h, w), (cx, cy), r, rng, rauheit=0.3)
        H |= mesa
        sperr |= _dehne(mesa.astype(bool), 8)
        anzahl_mesas -= 1

    # Flussbetten: Quelle im Massiv, Muendung am gegenueberliegenden Rand.
    # Durch das Massiv wird eine Schlucht geschnitten -- breit genug fuer
    # zwei Wandbaender (je 3) und einen begehbaren Boden dazwischen.
    # Riverbeds: source inside the massif, mouth at the opposite border. The
    # gorge is wide enough for two wall bands (3 each) plus a walkable floor.
    anzahl = params.fluesse
    if anzahl < 0:
        anzahl = max(1, int(round(np.sqrt(flaeche) / 128.0)))
    betten = np.zeros((h, w), dtype=bool)
    innen = massiv & ~_dehne(~massiv, 6)
    ys, xs = np.nonzero(innen if innen.any() else massiv)
    for _ in range(anzahl):
        if not len(ys):
            break
        i = int(rng.integers(len(ys)))
        start = (int(xs[i]), int(ys[i]))
        if seite == 0:
            muendung = (w - 2, int(rng.integers(h // 6, h - h // 6)))
        elif seite == 1:
            muendung = (1, int(rng.integers(h // 6, h - h // 6)))
        elif seite == 2:
            muendung = (int(rng.integers(w // 6, w - w // 6)), h - 2)
        else:
            muendung = (int(rng.integers(w // 6, w - w // 6)), 1)
        pfad = _fluss_pfad(start, muendung, (h, w), rng)
        schlucht = _pfad_band((h, w), pfad, 5.0)
        H[schlucht] = 0
        betten |= _pfad_band((h, w), pfad, 2.1)
        # Gelegentliche Aufweitungen: ein trockener Fluss hat Kolke.
        # Occasional widenings: a dry river has scour pools.
        for px, py in pfad[:: max(1, len(pfad) // 4)][1:]:
            if rng.random() < 0.5:
                betten |= _pfad_band((h, w), [(px, py)],
                                     float(rng.uniform(3.0, 4.0)))

    if H.any():
        # Erst glaetten, dann auf ein FUENFERraster rasten. Fuenf, weil der
        # senkrechte mud-Laufblock genau 5 Zellen hoch ist: jeder Lauf der
        # Kontur laesst sich dann mit ganzen Bloecken belegen. Feinere Raster
        # ergaben Zickzackkanten aus 3er/4er-Stuecken, und die zerlegte der
        # Blockweg sichtbar in Haken; frei gelassene Schraegen zerfielen als
        # duenne Nordkanten-Treppen in Stummel. Rechtwinklige Zuege mit langen
        # Laeufen sind gemessen die fehlerfreie Gangart des Blockwegs (0 bis
        # 3,4 % unbelegte Paare, docs/klippen-stand.md, 10) -- und genau so
        # sehen die Waelle der Originalkarten aus.
        # Smooth first, then snap to a FIVE-cell grid. Five because the
        # vertical mud run block is exactly 5 cells tall: every contour run
        # can then be covered with whole blocks. Finer grids gave zigzag edges
        # the block path took apart into hooks; free diagonals crumbled into
        # stubs of thin north-edge stairs. Rectilinear strokes with long runs
        # are the block path's measured error-free gait.
        H = shapegen.glaette(H, 2)
        H = shapegen.begradige(H, block=5)
        H = shapegen.entferne_kleinkram(
            H, mindest=max(24, int(round(0.0015 * flaeche))))
        # Nur die Ankerseite darf bis an den Rand: dort laeuft das Hochland
        # aus dem Bild, und die Kontur wird am Rand bewusst NICHT gezeichnet.
        # Die uebrigen Raender bleiben frei wie ueberall im Generator.
        # Only the anchored side may reach the border -- the highland runs off
        # the map there and the contour is deliberately not drawn along it.
        if seite != 0:
            H[:, :3] = 0
        if seite != 1:
            H[:, -3:] = 0
        if seite != 2:
            H[:3, :] = 0
        if seite != 3:
            H[-3:, :] = 0
    # Eine Zelle Abstand zur Wand: der Wandfuss gehoert der Wandfamilie,
    # direkt daneben darf das Bett beginnen.
    # One cell clear of the wall: the footing belongs to the wall family, the
    # bed may start right beside it.
    betten &= ~_dehne(H > 0, 1)
    return H, betten


def _landschaft_familien(fam_field: np.ndarray, H: np.ndarray,
                         betten: np.ndarray | None, tm: "TileModel") -> None:
    """Ein Biom je Wand: jede Hochflaeche samt Saum wird einfarbig.

    Ein Wandzug behaelt die Familie seines ersten Punkts; laeuft er ueber eine
    Biomgrenze, stehen seine Kacheln dort gegen fremden Boden (gemessen 118
    harte Bodenkanten an einem einzigen Zug, docs/klippen-stand.md, 12).
    Deshalb bekommt jede Hochflaeche einen einfarbigen Saum, BEVOR die
    Uebergaenge festgelegt werden.

    Die Farbe je Komponente ist die Mehrheitsfamilie ihres Umfelds: eine Mesa
    mitten im Sand bekommt Sandklippen statt eines Erdrings, der dort wie ein
    Hof aussaehe. Nur Erde und Sand haben Klippenbloecke; alles andere wird
    Erde -- dort laufen ausserdem alle Reparaturen (Kantenzuordnung nur mud).

    One biome per wall: each highland component plus rim becomes one colour --
    the majority family of its surroundings. A mesa amid sand gets sand
    cliffs instead of a dirt ring. Only dirt and sand have cliff blocks;
    everything else becomes dirt, where all repairs are active too.
    """
    if "mud" not in tm.families:
        return
    mud = tm.families.index("mud")
    san = tm.families.index("san") if "san" in tm.families else -1
    for comp in _components(H > 0):
        saum = _dehne(comp, 4)
        # Saum 4: Wandband 3 plus eine Zelle Fuss.
        # Rim 4: wall band of 3 plus one cell of footing.
        werte, anzahl = np.unique(fam_field[saum], return_counts=True)
        mehrheit = int(werte[int(np.argmax(anzahl))])
        fam_field[saum] = mehrheit if mehrheit in (mud, san) else mud
    if betten is not None and betten.any() and san >= 0:
        fam_field[betten] = san


def _rand_zyklus(comp: np.ndarray) -> list[tuple[int, int]]:
    """Geordneter Randzyklus einer Komponente (Moore-Randverfolgung).

    Ordered boundary cycle of one component (Moore boundary tracing)."""
    h, w = comp.shape
    ys, xs = np.nonzero(comp)
    if not len(ys):
        return []
    sy = int(ys.min())
    sx = int(xs[ys == sy].min())

    def drin(x, y):
        return 0 <= x < w and 0 <= y < h and comp[y, x]

    zyklus = [(sx, sy)]
    bx, by = sx - 1, sy
    cx, cy = sx, sy
    for _ in range(int(comp.sum()) * 8 + 8):
        start_i = _MOORE.index((bx - cx, by - cy))
        naechster = None
        for k in range(1, 9):
            dx, dy = _MOORE[(start_i + k) % 8]
            nx, ny = cx + dx, cy + dy
            if drin(nx, ny):
                naechster = (nx, ny)
                pdx, pdy = _MOORE[(start_i + k - 1) % 8]
                bx, by = cx + pdx, cy + pdy
                break
        if naechster is None:
            return zyklus                      # Einzelzelle / single cell
        cx, cy = naechster
        if (cx, cy) == (sx, sy):
            return zyklus
        zyklus.append((cx, cy))
    return zyklus


def _kontur_vereinfachen(punkte: list[tuple[int, int]], eps: float = 1.0
                         ) -> list[tuple[int, int]]:
    """Randzellenfolge zu Eckpunkten eindampfen (Ramer-Douglas-Peucker).

    eps = 1.0 behaelt jede echte Ecke: auf dem Fuenferraster des Hoehenfelds
    werden die Waende reine waagerecht/senkrecht-Zuege mit Eckbloecken --
    die gemessen fehlerfreie Gangart des Blockwegs. Ein groesseres eps (2,9)
    ist probiert und verworfen: es fasste Rasterstufen zu freien Schraegen
    zusammen, und deren Treppen zerfielen als haarfeine Nordkanten sichtbar
    in Stummel (Seed 7, Schlucht und Massiv-Suedkante).

    Boil the boundary run down to corner points (RDP). eps = 1.0 keeps every
    true corner: on the five-cell grid the walls become pure horizontal/
    vertical runs with corner blocks -- the block path's measured error-free
    gait. A larger eps (2.9) was tried and dropped: it merged grid steps into
    free diagonals whose stairs crumbled into visible stubs.
    """
    if len(punkte) < 3:
        return list(punkte)
    p = np.asarray(punkte, dtype=float)
    a, b = p[0], p[-1]
    ab = b - a
    laenge = float(np.hypot(*ab)) or 1.0
    quer = np.abs(ab[0] * (p[:, 1] - a[1]) - ab[1] * (p[:, 0] - a[0])) / laenge
    i = int(np.argmax(quer))
    if quer[i] <= eps:
        return [(int(a[0]), int(a[1])), (int(b[0]), int(b[1]))]
    links = _kontur_vereinfachen(punkte[:i + 1], eps)
    rechts = _kontur_vereinfachen(punkte[i:], eps)
    return links[:-1] + rechts


def _kontur_hand(punkte, comp: np.ndarray) -> str:
    """Liegt das Hochland links oder rechts der Laufrichtung? -> hoch_seite.

    Nicht aus der Umlaufrichtung hergeleitet, sondern nachgesehen: neben
    mehreren Segmentmitten wird gezaehlt, auf welcher Seite die Komponente
    liegt. Links von (dx, dy) ist (dy, -dx) -- y waechst nach unten.

    Does the highland lie left or right of the walking direction? Not derived
    from the winding order but looked up beside several segment midpoints.
    """
    h, w = comp.shape
    links = rechts = 0
    for (x1, y1), (x2, y2) in zip(punkte, punkte[1:]):
        dx = int(np.sign(x2 - x1))
        dy = int(np.sign(y2 - y1))
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        for k in (1, 2, 3):
            lx, ly = mx + dy * k, my - dx * k
            rx, ry = mx - dy * k, my + dx * k
            if 0 <= lx < w and 0 <= ly < h and comp[ly, lx]:
                links += 1
            if 0 <= rx < w and 0 <= ry < h and comp[ry, rx]:
                rechts += 1
    return "links" if links >= rechts else "rechts"


def _kontur_boegen(zyklus: list, comp: np.ndarray, luecken: int,
                   rng: np.random.Generator, luecke_laenge: int = 9
                   ) -> list[list]:
    """Zyklus in offene Boegen teilen: Kartenrand raus, Rampenluecken rein.

    Am Kartenrand wird keine Wand gezeichnet -- das Hochland laeuft dort aus
    dem Bild, wie auf den Originalkarten. Die Rampenluecken sitzen bevorzugt
    auf waagerechten Laeufen, weil es nur dort Abschlussstuecke gibt
    (senkrechte Wandenden bleiben im Kachelsatz ohne Abschluss).

    Split the cycle into open arcs: drop border-hugging stretches, cut ramp
    gaps. Gaps prefer horizontal runs because only those have end caps.
    """
    h, w = comp.shape
    n = len(zyklus)
    am_rand = [x <= 1 or y <= 1 or x >= w - 2 or y >= h - 2
               for x, y in zyklus]
    weg = list(am_rand)
    if luecken > 0 and n >= 40:
        # Waagerechte Laufmitte als Kandidaten fuer eine Luecke.
        # Middle of a horizontal run as gap candidates.
        kandidaten = [i for i in range(n)
                      if not weg[i]
                      and zyklus[i][1] == zyklus[(i + 1) % n][1]
                      and zyklus[i][1] == zyklus[i - 1][1]]
        if not kandidaten:
            kandidaten = [i for i in range(n) if not weg[i]]
        for k in range(luecken):
            if not kandidaten:
                break
            ziel = int(round((k + 0.5) * n / luecken))
            i = min(kandidaten,
                    key=lambda j: min(abs(j - ziel), n - abs(j - ziel)))
            for d in range(-(luecke_laenge // 2), luecke_laenge // 2 + 1):
                weg[(i + d) % n] = True
    if not any(weg):
        return [zyklus + [zyklus[0]]]          # geschlossen / closed figure
    # Offene Boegen einsammeln: beim ersten entfernten Punkt beginnen, dann
    # laufen die Boegen nicht ueber den Zyklusanfang.
    # Collect the open arcs: start at the first removed point, then no arc
    # wraps around the cycle start.
    versatz = weg.index(True)
    boegen: list[list] = []
    lauf: list = []
    for i in range(n + 1):
        j = (versatz + i) % n
        if i == n or weg[j]:
            if len(lauf) >= 6:
                boegen.append(lauf)
            lauf = []
        else:
            lauf.append(zyklus[j])
    return boegen


# Wie stark der Versatz innerhalb einer Schraegen schwankt. Gemessen an 41
# schraegen Kantenstuecken aus 6 Originalkarten: KEINES benutzt lauter gleiche
# Versaetze, 39 % benutzen vier verschiedene Werte, die Streuung innerhalb
# einer Folge liegt im Median bei 1,31.
#
#     0  0  0 -1  0 -1 -2 -2 -1  0 -1 -2 -4 -3 -2 -4 -2  0  0
#     0  0 -1 -2  0  0 -1 -3 -1 -3 -2 -3 -4 -1  0 -1  0  0 -1 +1
#
# Darin steckt dreierlei: Nullen mittendrin (die Wand laeuft ein Stueck
# senkrecht weiter), grosse Spruenge neben kleinen, und gelegentlich eine
# Gegenbewegung. Eine gleichmaessige Treppe -2, -2, -2 kommt nirgends vor --
# und genau deshalb sieht man bei ihr jede Stufe einzeln.
#
# How much the offset varies inside a slope. Measured on 41 diagonal edge runs
# from 6 original maps: not one uses uniform offsets, 39 % use four different
# values, and the spread within a run has a median of 1.31.
#
# Diese Streuung war lange die einzige Vorgabe, und daran ist der Erzeuger
# gescheitert: Mittelwert und Streuung legen eine Verteilung nicht fest. Die
# Verteilung selbst ist unten gemessen und wird direkt benutzt.
# Mean and spread do not pin down a distribution; the distribution itself is
# measured below and used directly.

# Die Treppe einer Schraegen -- Trittlaenge und Sprunghoehe, direkt gemessen.
#
# Gezaehlt an 206 Schraegen aus den 54 Stockkarten (974 Tritte): die Oberkante
# eines Klippenbandes Spalte fuer Spalte verfolgt und gezaehlt, wie viele
# Spalten sie gleich bleibt, bevor sie springt.
#
#   Trittlaenge   1  41,1 %   2  23,4 %   3  12,1 %   4  7,8 %   5  6,1 %
#                 Median 2, Mittel 2,62, laenger kommt vor, aber selten
#   Sprunghoehe   1  75,5 %   2  24,5 %   -- drei Zeilen NIE
#
# Die Trittlaengen sind fast genau geometrisch: mit q = 1 - 1/2,62 sagt die
# Verteilung 38,2 / 23,6 / 14,6 / 9,0 / 5,6 % gegen gemessene
# 41,1 / 23,4 / 12,1 / 7,8 / 6,1 %. Erzeugt wird deshalb geometrisch mit dem
# Mittel, das die verlangte Neigung fordert -- die FORM der Verteilung ist
# gemessen, ihr Mittelwert kommt aus der gezeichneten Linie.
#
# Vorher wurde die Folge aus Mittelwert und Streuung gebaut. Das lieferte 17 %
# Schritte <= 0 -- ein Tritt der Laenge 0 ist kein Tritt, sondern zwei Absaetze
# uebereinander, und die Wand faellt in EINER Spalte um zwei Zeilen. An genau
# diesen Stellen sassen 79 % der Kachelpaare, die in keiner Originalkarte
# vorkommen. Mit einer Untergrenze allein wurde es nicht besser, sondern
# anders schlecht: die geforderte Streuung war dann nur noch ueber Extreme zu
# erreichen (lauter Einsen und Vieren), und ueber Eck stand 20 % lang dieselbe
# Kachel statt der gemessenen 1,31 %.
#
# Measured on 206 slopes from the 54 stock maps: tread lengths are all but
# exactly geometric, and a riser is one row (75,5 %) or two (24,5 %), never
# three. The distribution's SHAPE is measured; its mean comes from the drawn
# line.
# Die Naht an der Stufe laesst sich NICHT ueber die Blockwahl verbessern -- der
# Blockweg hat dafuer keinen Spielraum. Gemessen:
#
#   Bloecke je Familie insgesamt            mud 18, san 17
#   Bloecke je Laufrichtung                 1 bis 3
#   Blockpaare mit mehr als einem
#     gezaehlten Versatz                    38 von 482 (8 %)
#
# Ein Gewicht auf der Naht wurde gebaut und gemessen: Faktoren von 0 bis 200
# aendern kein einziges Ergebnis, weil `waehle` meist genau einen Kandidaten
# hat. Die Wand, die der Blockweg baut, ist praktisch festgelegt.
#
# The seam cannot be improved through the block choice: with 18 blocks per
# family, 1 to 3 per direction and a single counted offset for 92 % of pairs,
# there is nothing to weight. Seam weights from 0 to 200 changed no result.


def _sektor_punkt(where: str, w: int, h: int, rng: np.random.Generator,
                  symmetry: str = SYM_NONE) -> tuple[int, int]:
    """Punkt im gewuenschten Sektor, leicht verwackelt."""
    fx, fy = SEKTOREN.get(where, (float(rng.random()), float(rng.random())))
    if where not in SEKTOREN:
        fx = 0.15 + 0.70 * fx
        fy = 0.15 + 0.70 * fy
    x = int(np.clip(fx * w + rng.normal(0, 0.04 * w), 4, w - 5))
    y = int(np.clip(fy * h + rng.normal(0, 0.04 * h), 4, h - 5))
    # Bei Symmetrie in die Grundhaelfte falten -- die Spiegelung zieht das
    # Merkmal danach auf die andere Seite, sonst wird es ueberschrieben.
    # With symmetry fold into the base half -- mirroring copies the feature to
    # the other side afterwards, otherwise it would be overwritten.
    if symmetry in (SYM_MIRROR_X, SYM_ROT180, SYM_QUAD) and x >= w // 2:
        x = w - 1 - x
    if symmetry in (SYM_MIRROR_Y, SYM_QUAD) and y >= h // 2:
        y = h - 1 - y
    return x, y


def _feature_layout(params: "MapGenParams",
                    rng: np.random.Generator) -> list[dict]:
    """Konkrete Geometrie je Merkmal festlegen (vor allem anderen).

    Muss vor der Vulkansuche laufen, damit Freiflaechen dort schon als
    verboten gelten.

    Fix the concrete geometry per feature, before everything else. Must run
    before the volcano search so clearings are already off limits there.
    """
    w, h = params.width, params.height
    klein = min(w, h)
    layout = []
    for feat in params.features:
        if feat.kind not in FEATURE_KINDS:
            continue
        groesse = float(np.clip(feat.size, 0.0, 1.0))
        x, y = _sektor_punkt(feat.where, w, h, rng, params.symmetry)
        eintrag = {"feat": feat, "x": x, "y": y}
        if feat.kind in (FEAT_TAL, FEAT_ENGE):
            ziel = feat.to or GEGENUEBER.get(feat.where or "c", "")
            zx, zy = _sektor_punkt(ziel, w, h, rng, params.symmetry)
            eintrag["pfad"] = _merkmal_pfad((x, y), (zx, zy), rng)
            eintrag["breite"] = (3 + int(round(5 * groesse)) if feat.kind == FEAT_TAL
                                 else 2 + int(round(9 * groesse)))
        else:
            eintrag["radius"] = int(round((0.06 + 0.10 * groesse) * klein))
        layout.append(eintrag)
    return layout


def _merkmal_pfad(start: tuple[int, int], ende: tuple[int, int],
                  rng: np.random.Generator) -> list[tuple[int, int]]:
    """Verwackelte Linie von A nach B.

    Eine gerade Schneise sieht nach Lineal aus; die Stuetzpunkte werden quer
    zur Achse versetzt und dann geglaettet.

    A jittered line from A to B: a straight cut looks like it was drawn with a
    ruler, so the control points are offset across the axis and smoothed.
    """
    x0, y0 = start
    x1, y1 = ende
    laenge = max(abs(x1 - x0), abs(y1 - y0), 1)
    schritte = max(4, laenge // 8)
    dx, dy = (x1 - x0) / laenge, (y1 - y0) / laenge
    quer = (-dy, dx)
    punkte = []
    for i in range(schritte + 1):
        t = i / schritte
        versatz = 0.0 if i in (0, schritte) else float(rng.normal(0, 0.06 * laenge))
        punkte.append((x0 + (x1 - x0) * t + quer[0] * versatz,
                       y0 + (y1 - y0) * t + quer[1] * versatz))
    fein = []
    for i in range(len(punkte) - 1):
        ax, ay = punkte[i]
        bx, by = punkte[i + 1]
        n = max(2, int(max(abs(bx - ax), abs(by - ay))))
        for k in range(n):
            t = k / n
            fein.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    fein.append(punkte[-1])
    return [(int(round(px)), int(round(py))) for px, py in fein]


def _steer_feature_families(fam_field: np.ndarray, layout: list[dict],
                            tm: "TileModel") -> None:
    """Untergrund unter den Merkmalen auf eine Familie mit Formationen stellen.

    271 der 327 Formationen sind Erde, 38 Sand, 18 Fels -- auf Gras oder
    Schnee gaebe es nichts zu setzen. Deshalb bekommt der Bereich vorher den
    passenden Untergrund, sonst faellt das Merkmal mangels Material aus.

    Set the ground under a feature to a family that actually has formations:
    271 of 327 are dirt, 38 sand, 18 rock -- on grass or snow there would be
    nothing to place, so the area gets suitable ground beforehand.
    """
    if not layout:
        return
    h, w = fam_field.shape
    erde = tm.families.index("mud") if "mud" in tm.families else 0
    sand = tm.families.index("san") if "san" in tm.families else erde
    beruehrt = False
    for eintrag in layout:
        if eintrag["feat"].kind == FEAT_FREI:
            continue
        maske = _feature_maske(eintrag, (h, w), rand=3)
        if not maske.any():
            continue
        # Sand behalten, wenn der Bereich ohnehin ueberwiegend Sand ist --
        # sonst klebt ein Erdfleck mitten in der Wueste.
        # Keep sand if the area is mostly sand anyway, otherwise a dirt patch
        # sits in the middle of the desert.
        sand_anteil = float((fam_field[maske] == sand).mean())
        fam_field[maske] = sand if sand_anteil > 0.5 else erde
        beruehrt = True
    if beruehrt:
        # Kante weichzeichnen -- sonst bleibt der Umriss der Steuerflaeche als
        # Naht im Gelaende stehen.
        # Blur the edge, otherwise the outline of the steered area remains
        # visible as a seam in the terrain.
        fam_field[:, :] = _smooth_families(fam_field, 1)


def _feature_maske(eintrag: dict, shape: tuple[int, int], rand: int = 0) -> np.ndarray:
    """Flaeche, die ein Merkmal beansprucht."""
    h, w = shape
    maske = np.zeros((h, w), dtype=bool)
    kind = eintrag["feat"].kind
    if kind in (FEAT_TAL, FEAT_ENGE):
        # Scheiben statt Quadrate: aneinandergereihte Quadrate ergeben ein
        # achsenparalleles Band, und die Familiensteuerung malt dieses Band
        # als hartkantiges Rechteck in die Biomkarte -- genau der Fehler, der
        # als Schnee- und Sandbloecke auf der Karte auftauchte.
        # Discs instead of squares: chained squares form an axis-aligned band,
        # and the family steering paints that band into the biome map as a
        # hard-edged rectangle -- exactly the defect that showed up as snow and
        # sand blocks on the map.
        r = eintrag["breite"] + rand + (4 if kind == FEAT_TAL else 0)
        ys, xs = np.ogrid[:h, :w]
        for px, py in eintrag["pfad"][::2]:
            maske |= ((xs - px) ** 2 + (ys - py) ** 2) <= r * r
    else:
        r = eintrag["radius"] + rand
        cx, cy = eintrag["x"], eintrag["y"]
        ys, xs = np.ogrid[:h, :w]
        maske = ((xs - cx) ** 2 + (ys - cy) ** 2) <= r * r
    return maske


def _apply_features(grid, fam_field, tm, rng, layout, gesperrt,
                    volcanoes, lava_zones, params, H, klippen) -> dict:
    """Zaehlen, was von den Merkmalen tatsaechlich auf der Karte gelandet ist.

    Gebaut wird nichts mehr hier -- die Form steckt im Hoehenfeld, die Kacheln
    hat die Nachschlagetabelle gesetzt. Diese Funktion meldet nur noch, wie
    viele Klippenzellen je Merkmal entstanden sind, und traegt das Lavafeld
    eines Tals nach.

    Count what actually ended up on the map. Nothing is built here any more --
    the shape lives in the height field and the tiles were placed by the lookup
    table. This only reports how many cliff cells each feature produced and
    adds the lava field of a valley.
    """
    bericht = {k: 0 for k in FEATURE_KINDS}
    h, w = grid.shape
    for eintrag in layout:
        kind = eintrag["feat"].kind
        maske = _feature_maske(eintrag, (h, w), rand=4)
        if kind == FEAT_FREI:
            gesperrt |= maske
            bericht[kind] += 1
            continue
        bericht[kind] += int((klippen & maske).sum())
        # Merkmalsflaechen fuer Streugut und Vulkane sperren, damit die
        # gewuenschte Form nicht zugestellt wird.
        # Block feature areas against scatter and volcanoes so the requested
        # shape does not get cluttered.
        gesperrt |= maske
        if kind == FEAT_TAL and eintrag["feat"].lava:
            # Keine Lavakacheln -- nur das Feld, auf dem im Spiel Lava
            # fliessen darf. Die Sohle ist der Weg zwischen den Waenden.
            # No lava tiles -- only the field on which lava may flow in-game.
            # The floor is the path between the walls.
            sohle = []
            for px, py in eintrag["pfad"]:
                for dx in range(-eintrag["breite"], eintrag["breite"] + 1):
                    for dy in range(-eintrag["breite"], eintrag["breite"] + 1):
                        x, y = px + dx, py + dy
                        if 0 <= x < w and 0 <= y < h and not H[y, x]:
                            sohle.append((x, y))
            if sohle:
                lava_zones.append(sorted(set(sohle)))
    return bericht
