"""Klippen aus einer frei erzeugten Form, statt aus kopierten Ausschnitten.

Der bisherige Weg schnitt fertige Klippengebilde aus den Originalkarten aus
und fuegte sie ein. Das sah aufgeklebt aus: ein Ausschnitt bringt seinen
eigenen Boden mit, und an der Naht treffen Kacheln aufeinander, die im
Original nie nebeneinander lagen -- sichtbar als schnurgerade Kanten.

Hier ist Form und Kachel getrennt:

1. Die Form ist ein Hoehenfeld (Hochland ja/nein), frei erzeugt -- Blobs fuer
   Berge, ein Korridor fuer Taeler. Beliebig geformt, nichts kopiert.
2. Der Zelltyp folgt aus der Form: aus dem 5x5-Hoehenfenster laesst sich zu
   92 % ablesen, welchen Zelltyp die Entwickler dort gesetzt haetten.
3. Die Kachel folgt aus dem Zelltyp-Umfeld und der Familie -- nachgeschlagen
   in dem, was die Originalkarten in genau dieser Situation verwendet haben.
4. Zusaetzlich muss jede Kachel zu ihrer linken und oberen Nachbarin passen
   (gelernte Nachbarschaft). Damit kann per Konstruktion keine Naht entstehen.

Cliffs from a freely generated shape instead of copied cutouts. The previous
approach cut finished cliff structures out of the original maps and pasted
them in, which looked glued on: a cutout brings its own ground along and at
the seam tiles meet that never sat next to each other in the original --
visible as dead straight edges. Here shape and tile are separated: the shape
is a height field, the cell type follows from the shape, the tile follows from
the cell-type neighbourhood and the family, and every tile additionally has to
fit its left and top neighbour.
"""
from __future__ import annotations

import numpy as np

import celltypes

ROLLE_TIEF, ROLLE_HOCH = 0, 1
ROLLE_NORD, ROLLE_HOCHSEITE, ROLLE_TIEFSEITE = 2, 3, 4

CLIFF_CELLS = (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
               celltypes.CLIFFS_LOW_SIDE)

ROLLE_VON_ZELLTYP = {
    celltypes.NORTH_CLIFFS: ROLLE_NORD,
    celltypes.CLIFFS_HIGH_SIDE: ROLLE_HOCHSEITE,
    celltypes.CLIFFS_LOW_SIDE: ROLLE_TIEFSEITE,
}


class ShapeTables:
    """Die beiden gelernten Tabellen, zum Nachschlagen aufbereitet."""

    def __init__(self, data):
        self.shape_keys = np.asarray(data["shape_keys"], dtype=np.int64)
        self.shape_cells = np.asarray(data["shape_cells"], dtype=np.int16)
        self.ctx_keys = np.asarray(data["ctx_keys"], dtype=np.int64)
        self.ctx_offsets = np.asarray(data["ctx_offsets"], dtype=np.int32)
        self.ctx_tiles = np.asarray(data["ctx_tiles"], dtype=np.int32)
        self.ctx_counts = np.asarray(data["ctx_counts"], dtype=np.int32)
        self.grob_keys = np.asarray(data.get("grob_keys", [0]), dtype=np.int64)
        self.grob_offsets = np.asarray(data.get("grob_offsets", [0, 0]), dtype=np.int32)
        self.grob_tiles = np.asarray(data.get("grob_tiles", [0]), dtype=np.int32)
        self.grob_counts = np.asarray(data.get("grob_counts", [0]), dtype=np.int32)

    @property
    def ok(self) -> bool:
        return len(self.shape_keys) > 1 and len(self.ctx_keys) > 1

    def zelltyp(self, fenster: np.ndarray) -> int:
        """Zelltyp fuer ein 5x5-Hoehenfenster (-1 = kein Klippenrand)."""
        k = 0
        for v in fenster.ravel():
            k = (k << 1) | int(v)
        i = int(np.searchsorted(self.shape_keys, k))
        if i < len(self.shape_keys) and self.shape_keys[i] == k:
            return int(self.shape_cells[i])
        return -1

    def grob(self, zelltyp: int, familie: int):
        """Rueckfall: irgendeine Kachel des richtigen Zelltyps in der Familie."""
        for fam in (familie, 7):
            schl = zelltyp * 8 + fam
            i = int(np.searchsorted(self.grob_keys, schl))
            if i < len(self.grob_keys) and self.grob_keys[i] == schl:
                lo, hi = int(self.grob_offsets[i]), int(self.grob_offsets[i + 1])
                if hi > lo:
                    return self.grob_tiles[lo:hi], self.grob_counts[lo:hi]
        return None, None

    def kacheln(self, fenster: np.ndarray, familie: int):
        """Kacheln und Haeufigkeiten fuer ein 3x3-Rollenfenster."""
        k = 0
        for v in fenster.ravel():
            k = k * 5 + int(v)
        for fam in (familie, 7):          # 7 = Familie unbekannt im Original
            schl = k * 8 + fam
            i = int(np.searchsorted(self.ctx_keys, schl))
            if i < len(self.ctx_keys) and self.ctx_keys[i] == schl:
                lo, hi = int(self.ctx_offsets[i]), int(self.ctx_offsets[i + 1])
                if hi > lo:
                    return self.ctx_tiles[lo:hi], self.ctx_counts[lo:hi]
        return None, None


def height_field_from_cells(ct: np.ndarray) -> np.ndarray:
    """Hochland/Tiefland aus den Zelltypen einer fertigen Karte zurueckgewinnen.

    Klippen trennen die Ebenen, ihre Zelltypen sagen welche Seite oben liegt.
    Gebraucht wird das beim Malen: eine geladene Karte -- auch eine
    Originalkarte -- muss ihre Hoehenebene zurueckbekommen, sonst weiss der
    Pinsel nicht, worauf er malt.

    Recover highland/lowland from the cell types of a finished map. Needed for
    painting: a loaded map -- an original one too -- has to get its height layer
    back, otherwise the brush does not know what it is painting on.
    """
    from collections import deque, Counter
    h, w = ct.shape
    klippe = np.isin(ct, CLIFF_CELLS)
    H = np.zeros(ct.shape, dtype=np.int8)
    besucht = np.zeros(ct.shape, dtype=bool)
    for sy in range(h):
        for sx in range(w):
            if klippe[sy, sx] or besucht[sy, sx]:
                continue
            q = deque([(sx, sy)])
            besucht[sy, sx] = True
            zellen = []
            stimmen = Counter()
            while q:
                x, y = q.popleft()
                zellen.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if klippe[ny, nx]:
                        stimmen[int(ct[ny, nx])] += 1
                    elif not besucht[ny, nx]:
                        besucht[ny, nx] = True
                        q.append((nx, ny))
            if stimmen[celltypes.CLIFFS_HIGH_SIDE] > stimmen[celltypes.CLIFFS_LOW_SIDE]:
                for x, y in zellen:
                    H[y, x] = 1
    H[ct == celltypes.CLIFFS_HIGH_SIDE] = 1
    H[ct == celltypes.NORTH_CLIFFS] = 1
    return H


def glaette(feld: np.ndarray, runden: int = 2) -> np.ndarray:
    """Mehrheitsglaettung -- macht aus kantigem Rauschen runde Formen."""
    f = feld.astype(np.int16)
    for _ in range(runden):
        summe = np.zeros_like(f)
        anzahl = np.zeros_like(f)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                summe += np.roll(np.roll(f, dy, axis=0), dx, axis=1)
                anzahl += 1
        f = (summe * 2 > anzahl).astype(np.int16)
    return f.astype(np.int8)


def begradige(feld: np.ndarray, block: int = 3) -> np.ndarray:
    """Kante auf ein groeberes Raster rasten.

    Ein Hoehenfeld aus Rauschen und Glaettung hat eine Grenze, die Zelle fuer
    Zelle wackelt -- die Klippe wirkt dann ausgefranst. In den Originalkarten
    laufen die Kanten mehrere Kacheln geradeaus und biegen dann sauber ab,
    weil sie mit einem Pinsel gezogen wurden. Mehrheitsentscheid je Block und
    wieder aufblasen ahmt genau das nach.

    Snap the edge to a coarser grid. A height field from noise and smoothing
    has a border that wobbles cell by cell, which makes the cliff look frayed.
    In the original maps the edges run straight for several tiles and then turn
    cleanly, because they were drawn with a brush. A majority vote per block,
    scaled back up, imitates exactly that.
    """
    if block < 2:
        return feld
    h, w = feld.shape
    hh, bb = (h + block - 1) // block, (w + block - 1) // block
    gefuellt = np.zeros((hh * block, bb * block), dtype=feld.dtype)
    gefuellt[:h, :w] = feld
    bloecke = gefuellt.reshape(hh, block, bb, block)
    mehrheit = (bloecke.sum(axis=(1, 3)) * 2 > block * block).astype(feld.dtype)
    grob = np.repeat(np.repeat(mehrheit, block, axis=0), block, axis=1)
    return grob[:h, :w]


def blob(shape, mitte, radius, rng, rauheit: float = 0.45) -> np.ndarray:
    """Runde, aber unregelmaessige Flaeche -- ein Berg von oben.

    Ein exakter Kreis sieht gestanzt aus, deshalb wird der Radius je Richtung
    verrauscht und die Kante anschliessend geglaettet.

    A round but irregular area -- a mountain seen from above. An exact circle
    looks stamped out, so the radius is perturbed per direction and the edge
    smoothed afterwards.
    """
    h, w = shape
    cx, cy = mitte
    ys, xs = np.ogrid[:h, :w]
    winkel = np.arctan2(ys - cy, xs - cx)
    # Wenige Oberwellen: viele ergaeben eine Seeigelform statt eines Bergs.
    # Few harmonics: many would give a sea urchin instead of a mountain.
    stoerung = np.zeros((h, w))
    for k in range(1, 5):
        stoerung += (float(rng.normal(0, 1)) * np.sin(k * winkel)
                     + float(rng.normal(0, 1)) * np.cos(k * winkel)) / k
    r = radius * (1.0 + rauheit * stoerung / 3.0)
    feld = (((xs - cx) ** 2 + (ys - cy) ** 2) <= np.maximum(r, 2) ** 2)
    return glaette(feld.astype(np.int8), 1)


def korridor(shape, pfad, breite: int, rng, rauheit: float = 0.35) -> np.ndarray:
    """Hochland links und rechts eines Wegs -- ein Tal.

    Erzeugt wird nicht das Tal, sondern die Umgebung: ein breites Band
    Hochland, aus dem der Korridor wieder ausgestanzt wird. So entstehen zwei
    Waende in beliebiger Laenge, ohne irgendetwas aneinanderzureihen.

    Generate not the valley but its surroundings: a wide band of highland from
    which the corridor is punched out again. That gives two walls of any
    length without chaining anything together.
    """
    h, w = shape
    band = np.zeros((h, w), dtype=np.int8)
    loch = np.zeros((h, w), dtype=np.int8)
    ys, xs = np.ogrid[:h, :w]
    aussen = breite + 8 + int(round(6 * rauheit))
    for i, (px, py) in enumerate(pfad):
        if i % 2:
            continue
        wackel = float(rng.normal(0, rauheit * 2.0))
        band |= (((xs - px) ** 2 + (ys - py) ** 2) <= (aussen + wackel) ** 2)
        loch |= (((xs - px) ** 2 + (ys - py) ** 2) <= (breite + wackel * 0.5) ** 2)
    return glaette((band & ~loch.astype(bool)).astype(np.int8), 1)


def riegel(shape, pfad, luecke_bei: int, luecke: int, rng) -> np.ndarray:
    """Sperre quer ueber die Karte mit einer Luecke -- die Engstelle."""
    h, w = shape
    feld = np.zeros((h, w), dtype=np.int8)
    ys, xs = np.ogrid[:h, :w]
    for i, (px, py) in enumerate(pfad):
        if abs(i - luecke_bei) <= luecke:
            continue
        r = 6 + float(rng.normal(0, 1.2))
        feld |= (((xs - px) ** 2 + (ys - py) ** 2) <= max(3.0, r) ** 2)
    return glaette(feld, 1)


def entferne_kleinkram(feld: np.ndarray, mindest: int = 24) -> np.ndarray:
    """Winzige Hochland-Flecken und Loecher wegraeumen.

    Ein Plateau von vier Kacheln ist keine Klippe, sondern ein Fleck -- und
    ein Loch derselben Groesse ist keine Schlucht.

    Remove tiny highland patches and holes: a four-tile plateau is a speck,
    not a cliff, and a hole of the same size is not a canyon.
    """
    from collections import deque
    out = feld.copy()
    h, w = feld.shape
    for wert in (1, 0):
        besucht = np.zeros(feld.shape, dtype=bool)
        for sy in range(h):
            for sx in range(w):
                if besucht[sy, sx] or out[sy, sx] != wert:
                    continue
                q = deque([(sx, sy)])
                besucht[sy, sx] = True
                zellen = []
                while q:
                    x, y = q.popleft()
                    zellen.append((x, y))
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if (0 <= nx < w and 0 <= ny < h and not besucht[ny, nx]
                                and out[ny, nx] == wert):
                            besucht[ny, nx] = True
                            q.append((nx, ny))
                if len(zellen) < mindest:
                    for x, y in zellen:
                        out[y, x] = 1 - wert
    return out


def _nachbar(feld: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """Verschobene Sicht auf ein Feld, Rand wird fortgesetzt statt umgeklappt."""
    out = np.roll(np.roll(feld, dy, axis=0), dx, axis=1)
    if dy > 0:
        out[:dy, :] = feld[:1, :]
    elif dy < 0:
        out[dy:, :] = feld[-1:, :]
    if dx > 0:
        out[:, :dx] = feld[:, :1]
    elif dx < 0:
        out[:, dx:] = feld[:, -1:]
    return out


def zelltypen_aus_form(H: np.ndarray, tab: ShapeTables) -> np.ndarray:
    """Wo welche Klippenzelle hingehoert.

    Das WO ist geometrisch eindeutig und wird nicht geraten: an der Grenze
    zwischen Hoch- und Tiefland liegt ein Band. In den Originalkarten ist es
    am haeufigsten drei Zellen dick -- zwei oben, eine unten. Ein einzelliger
    Rand, wie im ersten Anlauf, ergibt duenne Striche statt Waenden.

    Das WELCHE kommt aus der gelernten Tabelle; wo die nichts weiss, greift die
    ebenfalls gemessene Regel: Nordkante, wenn das Tiefland im Norden liegt,
    sonst Hochseite.

    Where each cliff cell belongs. The WHERE is geometrically unambiguous and
    not guessed: a band sits on the border between highland and lowland, most
    commonly three cells thick in the originals -- two above, one below. A
    single-cell edge, as in the first attempt, gives thin lines instead of
    walls. The WHICH comes from the learned table; where it knows nothing, the
    equally measured rule applies: north edge if the lowland lies north,
    otherwise high side.
    """
    # Mit fortgesetztem Rand rechnen. Ohne das bleiben die aeussersten zwei
    # Spalten und Zeilen ohne Klippenband, weil das 5x5-Fenster dort nicht
    # passt -- am Kartenrand stand dann jede Wand offen wie eine Rampe, und
    # ein Hoehenzug quer ueber die Karte trennte nichts.
    # Compute with a replicated border. Without it the outermost two columns
    # and rows never get a cliff band, because the 5x5 window does not fit --
    # every wall stood open at the map edge like a ramp, and a ridge across the
    # map separated nothing.
    H = np.pad(H, 2, mode="edge")
    h, w = H.shape
    out = np.full(H.shape, -1, dtype=np.int16)
    hoch = H.astype(bool)
    tief = ~hoch

    def beruehrt(maske, ziel):
        t = np.zeros(maske.shape, dtype=bool)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            t |= _nachbar(ziel, dx, dy)
        return maske & t

    rand_hoch = beruehrt(hoch, tief)               # oberste Kantenreihe
    innen_hoch = beruehrt(hoch & ~rand_hoch, rand_hoch)   # zweite Reihe
    rand_tief = beruehrt(tief, hoch)               # Fusszeile im Tiefland

    # Tiefland im Norden? Dann ist es eine Nordkante.
    # Lowland to the north? Then it is a north edge.
    tief_im_norden = _nachbar(tief, 0, -1)

    out[rand_tief] = celltypes.CLIFFS_LOW_SIDE
    out[innen_hoch] = celltypes.CLIFFS_HIGH_SIDE
    out[rand_hoch] = celltypes.CLIFFS_HIGH_SIDE
    out[rand_hoch & tief_im_norden] = celltypes.NORTH_CLIFFS

    # Wo die gelernte Tabelle etwas Genaueres weiss, hat sie Vorrang.
    # Where the learned table knows something more precise, it wins.
    ys, xs = np.nonzero(out >= 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if y < 2 or x < 2 or y >= h - 2 or x >= w - 2:
            continue
        gelernt = tab.zelltyp(H[y - 2:y + 3, x - 2:x + 3])
        if gelernt in CLIFF_CELLS:
            out[y, x] = gelernt
    return out[2:-2, 2:-2]


def rollen_aus_zelltypen(H: np.ndarray, zelltypen: np.ndarray) -> np.ndarray:
    """Rollenfeld bauen: Hoehe plus Klippenrolle."""
    rolle = H.astype(np.int8).copy()
    for zt, r in ROLLE_VON_ZELLTYP.items():
        rolle[zelltypen == zt] = r
    return rolle
