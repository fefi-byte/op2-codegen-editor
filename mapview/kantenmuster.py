"""Uebergangskacheln nach ihren bedeckten Kanten einordnen.

Bisher bekam jede Uebergangskachel eine von acht Richtungen, geschaetzt aus
dem Farbverlauf der Nachbarschaft. Ein Winkel ist dafuer die falsche Groesse:
er kann "Fels im Norden", "Fels im Osten" und "Nordost-Ecke" nicht
auseinanderhalten, weil er alles auf eine Achse projiziert. Genau daran lagen
Kacheln in der falschen Zeile.

Hier wird stattdessen aus dem Kachelbild selbst abgelesen, welche der vier
Kanten vom anderen Boden bedeckt sind -- vier Ja/Nein statt eines Winkels.
Beim Setzen ist dieselbe Groesse exakt bekannt: das Familienfeld sagt, welche
der vier Nachbarzellen zum anderen Boden gehoeren. Kein Schaetzen mehr.

Classify transition tiles by their covered edges. Previously every transition
tile got one of eight directions, estimated from the colour gradient of its
surroundings. An angle is the wrong quantity for that: it cannot tell "rock to
the north", "rock to the east" and "north-east corner" apart, because it
projects everything onto a single axis -- which is why tiles ended up in the
wrong row. Here it is read off the tile graphic itself: which of the four edges
are covered by the other ground. When placing, the same quantity is known
exactly from the family field, so there is nothing left to estimate.
"""
from __future__ import annotations

import numpy as np

# Reihenfolge der Kanten im Muster.
# Order of the edges within the pattern.
KANTEN = ("N", "O", "S", "W")

# Wie tief in die Kachel hinein gemessen wird, als Bruchteil der Kachelbreite.
# Zu schmal misst nur die Pixelkante, zu breit verwaescht die Aussage.
# How far into the tile the strip reaches, as a fraction of the tile width.
# Too narrow measures only the pixel border, too wide blurs the statement.
STREIFEN = 1 / 6


def muster_code(bedeckt: tuple[bool, bool, bool, bool]) -> int:
    """Vier Kanten als Zahl 0..15 (Norden ist das hoechste Bit)."""
    wert = 0
    for b in bedeckt:
        wert = (wert << 1) | int(bool(b))
    return wert


def code_text(code: int) -> str:
    """Lesbare Form, etwa 'N+O' oder '-' fuer keine Kante."""
    teile = [KANTEN[i] for i in range(4) if code & (1 << (3 - i))]
    return "+".join(teile) if teile else "-"


def kachel_muster(pixel: np.ndarray, farbe_a: np.ndarray,
                  farbe_b: np.ndarray) -> int:
    """Welche Kanten der Kachel gehoeren zu Boden B?

    Jeder Kantenstreifen wird mit den Mittelfarben der beiden reinen Boeden
    verglichen und der naeheren zugeschlagen.

    Which edges of the tile belong to ground B? Each edge strip is compared
    with the mean colours of the two pure grounds and assigned to the nearer
    one.
    """
    h, w, _ = pixel.shape
    d = max(2, int(round(min(h, w) * STREIFEN)))
    # JEDES Pixel zuordnen, dann zaehlen. Den Streifen zu mitteln geht bei
    # gesprenkelten Kacheln schief: der Mittelwert liegt immer irgendwo
    # zwischen beiden Boeden, und welcher naeher ist, haengt dann am Abstand
    # der beiden Mittelfarben statt an der Kachel. Gemessen kamen so bei
    # Fels|Sand fast nur noch Kacheln mit drei oder vier bedeckten Kanten
    # heraus.
    # Classify EVERY pixel, then count. Averaging the strip fails on dithered
    # tiles: the mean always lands somewhere between the two grounds, and which
    # one is nearer then depends on the distance between the two mean colours
    # rather than on the tile. Measured, rock|sand produced almost only tiles
    # with three or four covered edges that way.
    flach = pixel.reshape(-1, 3).astype(np.float64)
    ist_b = (np.linalg.norm(flach - farbe_b, axis=1)
             < np.linalg.norm(flach - farbe_a, axis=1)).reshape(h, w)
    streifen = (ist_b[:d, :], ist_b[:, -d:], ist_b[-d:, :], ist_b[:, :d])
    return muster_code(tuple(float(s.mean()) > 0.5 for s in streifen))


def noetiges_muster(fam_field: np.ndarray, x: int, y: int,
                    eigen: int, fremd: int) -> int:
    """Welches Muster braucht diese Zelle?

    Aus dem Familienfeld: welche der vier Nachbarzellen gehoeren zum anderen
    Boden. Das ist dieselbe Groesse, die `kachel_muster` aus dem Bild liest --
    deshalb passen Bedarf und Angebot direkt zusammen.

    Which pattern does this cell need? From the family field: which of the four
    neighbours belong to the other ground. That is the same quantity
    `kachel_muster` reads from the picture, so demand and supply match directly.
    """
    h, w = fam_field.shape
    bedeckt = []
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):     # N, O, S, W
        nx, ny = x + dx, y + dy
        if not (0 <= nx < w and 0 <= ny < h):
            bedeckt.append(False)
            continue
        bedeckt.append(int(fam_field[ny, nx]) == fremd)
    return muster_code(tuple(bedeckt))


def aehnlichkeit(a: int, b: int) -> int:
    """Wie viele der vier Kanten stimmen ueberein?"""
    return 4 - bin(a ^ b).count("1")
