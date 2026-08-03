"""Die Kachelfolge entlang einer Klippenkante abfragen.

`learn_cliff_walk.py` laeuft die Kanten der Originalkarten ab und zaehlt, welche
Kachel auf welche folgt; dieses Modul fragt.

Der Setzer laeuft damit die Kante entlang statt Bloecke zu stapeln:

    naechste(kante, vorvorige, vorige, sprung)

`sprung` ist der Versatz der Kante zur naechsten Stelle -- der oertliche Winkel
der Wand. Fehlt der Zusammenhang, faellt die Abfrage von selbst auf die Ordnung
darunter zurueck (nur die vorige Kachel), und erst dann gibt sie auf. Auf
ungesehenen Karten fehlt der Zusammenhang zweiter Ordnung in 8,4 % der Faelle,
die Ordnung darunter faengt den groessten Teil davon.

Querying the tile sequence along a cliff edge, with backoff from order 2 to
order 1.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODELL_PFAD = HERE / "cliff_walk_model.npz"


class CliffWalkModel:
    """Welche Kachel folgt entlang der Kante auf welche."""

    def __init__(self, pfad: Path | str = MODELL_PFAD):
        d = np.load(pfad)
        self.kanten = [str(k) for k in d["kanten"]]
        self.familie = d["familie"]
        self.familien_namen = [str(n) for n in d["familien_namen"]]
        self.karten = int(d["karten"])
        self.laeufe = int(d["laeufe"])
        self.sprung_grenze = int(d["sprung_grenze"])
        self._zwei: dict = {}
        for s, n in zip(d["zwei_schluessel"], d["zwei_anzahl"]):
            self._zwei.setdefault(tuple(int(v) for v in s[:4]), {})[
                int(s[4])] = int(n)
        self._eins: dict = {}
        for s, n in zip(d["eins_schluessel"], d["eins_anzahl"]):
            self._eins.setdefault(tuple(int(v) for v in s[:3]), {})[
                int(s[3])] = int(n)
        self._anfang: dict = {}
        for s, n in zip(d["anfang_schluessel"], d["anfang_anzahl"]):
            self._anfang.setdefault(tuple(int(v) for v in s[:2]), {})[
                int(s[2])] = int(n)

    def _ki(self, kante) -> int:
        return kante if isinstance(kante, int) else self.kanten.index(kante)

    def naechste(self, kante, vorvorige: int | None, vorige: int,
                 sprung: int, familie: int | None = None) -> dict:
        """Was folgt hier? -> {kachel: Anzahl}, leer wenn nichts bekannt.

        Erst Ordnung 2, dann Ordnung 1. Der Rueckfall ist noetig: auf
        ungesehenen Karten kennt Ordnung 2 den Zusammenhang in 8,4 % der Faelle
        nicht, und ein Setzer, der dort stehen bleibt, bricht mitten in der Wand
        ab.
        """
        ki = self._ki(kante)
        aus: dict = {}
        if vorvorige is not None:
            aus = dict(self._zwei.get(
                (ki, int(vorvorige), int(vorige), int(sprung)), {}))
        if not aus:
            aus = dict(self._eins.get((ki, int(vorige), int(sprung)), {}))
        if familie is not None:
            aus = {t: n for t, n in aus.items()
                   if 0 <= t < len(self.familie)
                   and int(self.familie[t]) == familie}
        return aus

    def anfang(self, kante, sprung: int,
               familie: int | None = None) -> dict:
        """Womit faengt ein Kantenlauf an? -> {kachel: Anzahl}"""
        aus = dict(self._anfang.get((self._ki(kante), int(sprung)), {}))
        if familie is not None:
            aus = {t: n for t, n in aus.items()
                   if 0 <= t < len(self.familie)
                   and int(self.familie[t]) == familie}
        return aus

    def eindeutig(self, kante, vorvorige: int, vorige: int,
                  sprung: int) -> bool:
        """Steht die naechste Kachel fest? Gemessen in 73 % der Faelle."""
        c = self._zwei.get((self._ki(kante), int(vorvorige), int(vorige),
                            int(sprung)))
        return bool(c) and len(c) == 1


_modell: CliffWalkModel | None = None


def modell(pfad: Path | str = MODELL_PFAD) -> CliffWalkModel:
    """Das Modell einmal laden und behalten."""
    global _modell
    if _modell is None:
        _modell = CliffWalkModel(pfad)
    return _modell
