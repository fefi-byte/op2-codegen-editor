"""Wie gut passen zwei Kacheln an ihrer Beruehrungskante? -- in Pixeln.

`learn_cliff_pixels.py` sammelt die Randreihen, dieses Modul vergleicht sie.

    naht(a, b, "O")   mittlerer Farbabstand zwischen der rechten Reihe von a
                      und der linken Reihe von b

Das ist das einzige Mass im Projekt, das ohne die 54 Originalkarten auskommt.
Alle anderen fragen "kam das vor?" und schweigen ueber die 97 % der moeglichen
Paare, die nie vorkamen. Gemessen liegen belegte Paare bei einem Abstand um 24,
unbelegte um 40, und das trennt sie zu 81 bis 85 %.

Gebraucht wird es dort, wo die gezaehlte Tabelle mehrere Kacheln erlaubt -- im
Schnitt 4,5 -- und nur sagen kann, welche haeufiger ist. Welche PASST, sagt
erst die Naht.

The only measure here that does not consult the stock maps: how well two tiles
match along their touching pixel rows.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODELL_PFAD = HERE / "cliff_pixels_model.npz"

GEGEN = {"N": "S", "O": "W", "S": "N", "W": "O"}


class CliffPixelModel:
    """Die Randreihen der Klippenkacheln und ihr Abstand."""

    def __init__(self, pfad: Path | str = MODELL_PFAD):
        d = np.load(pfad)
        self.kacheln = d["kacheln"]
        self._raender = d["raender"].astype(np.int16)
        self.kanten = [str(k) for k in d["kanten"]]
        self.karten = int(d["karten"])
        self._platz = {int(t): i for i, t in enumerate(self.kacheln)}
        self._tafeln: dict[str, np.ndarray] = {}

    def __len__(self) -> int:
        return len(self.kacheln)

    def hat(self, kachel: int) -> bool:
        return int(kachel) in self._platz

    def rand(self, kachel: int, richtung: str) -> np.ndarray | None:
        i = self._platz.get(int(kachel))
        if i is None:
            return None
        return self._raender[i, self.kanten.index(richtung)]

    def naht(self, a: int, b: int, richtung: str) -> float | None:
        """Mittlerer Farbabstand der Beruehrungskante. None, wenn unbekannt.

        Klein ist gut: belegte Paare liegen um 24, unbelegte um 40.
        """
        ia, ib = self._platz.get(int(a)), self._platz.get(int(b))
        if ia is None or ib is None:
            return None
        return float(self._tafel(richtung)[ia, ib])

    def _tafel(self, richtung: str) -> np.ndarray:
        """Alle Abstaende dieser Richtung auf einmal -- einmal gerechnet.

        Der Loeser fragt die Naht fuer JEDEN Kandidaten an JEDEM Suchknoten.
        Einzeln aus 32 Pixeln gerechnet hat das die Suche so verlangsamt, dass
        zwei von sechs Waenden in acht Sekunden nicht mehr fertig wurden -- die
        ohne das Mass in 0,0 Sekunden loesten. Als Tafel sind es 307 x 307
        Zahlen je Richtung, also nichts.

        The solver asks for the seam of every candidate at every node; computed
        from 32 pixels each time that made two of six walls time out. As a table
        it is 307 x 307 numbers per direction.
        """
        if richtung in self._tafeln:
            return self._tafeln[richtung]
        i = self.kanten.index(richtung)
        j = self.kanten.index(GEGEN[richtung])
        # Die beruehrenden Reihen laufen bei gegenueberliegenden Kanten in
        # derselben Richtung -- oben/unten von links nach rechts, links/rechts
        # von oben nach unten. Also direkt vergleichen.
        a = self._raender[:, i, :, :].astype(np.int32)
        b = self._raender[:, j, :, :].astype(np.int32)
        tafel = np.abs(a[:, None, :, :] - b[None, :, :, :]).mean(axis=(2, 3))
        self._tafeln[richtung] = tafel.astype(np.float32)
        return self._tafeln[richtung]


_modell: CliffPixelModel | None = None


def modell(pfad: Path | str = MODELL_PFAD) -> CliffPixelModel:
    """Das Modell einmal laden und behalten."""
    global _modell
    if _modell is None:
        _modell = CliffPixelModel(pfad)
    return _modell
