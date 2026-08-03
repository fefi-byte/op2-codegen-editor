"""Das Saeulenmodell benutzen: welches Band darf rechts neben welchem stehen?

`learn_cliff_columns.py` misst, dieses Modul fragt. Getrennt gehalten, damit
der Trainer die Originalkarten braucht und der Editor nur die `.npz`.

Eine Saeule ist ein senkrechtes Klippenband aus drei oder vier Kacheln -- der
Querschnitt einer Wand. Der senkrechte Versatz zum naechsten Band ist die
Neigung; eine Schraege entsteht also nicht aus einer gewuerfelten Stufenfolge,
sondern daraus, dass man Baender aneinanderreiht, die zueinander passen, und der
Versatz kommt mit.

Using the column model: which band may stand to the right of which. A column is
a three- or four-tile vertical cliff band, the cross-section of a wall, and the
vertical offset to the next band is the slope -- so a diagonal comes from
chaining bands that fit, not from a rolled sequence of steps.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODELL_PFAD = HERE / "cliff_columns_model.npz"


class CliffColumnModel:
    """Baender, ihre Haeufigkeit und die gezaehlten Uebergaenge."""

    def __init__(self, pfad: Path | str = MODELL_PFAD):
        d = np.load(pfad)
        # `saeulen` ist rechteckig mit -1 aufgefuellt, weil Baender drei oder
        # vier Kacheln hoch sind; `hoehe` sagt, wieviel davon gilt.
        self._roh = d["saeulen"]
        self.hoehe = d["hoehe"]
        self.haeufigkeit = d["haeufigkeit"]
        self._zelltypen = d["zelltypen"]
        self.familie = d["familie"]
        self.familien_namen = [str(n) for n in d["familien_namen"]]
        self.mindesthoehe = int(d["mindesthoehe"])
        self.hoechsthoehe = int(d["hoechsthoehe"])
        self.karten = int(d["karten"])
        # Nachfolger nachschlagbar: a -> [(b, versatz, anzahl)]
        self._nach: dict[int, list] = {}
        for a, b, v, n in zip(d["nb_a"], d["nb_b"], d["nb_versatz"],
                              d["nb_anzahl"]):
            self._nach.setdefault(int(a), []).append((int(b), int(v), int(n)))
        for liste in self._nach.values():
            liste.sort(key=lambda t: -t[2])

    def __len__(self) -> int:
        return len(self.hoehe)

    def saeule(self, i: int) -> tuple[int, ...]:
        """Die Kacheln von Band `i`, von oben nach unten, ohne Fuellrand."""
        return tuple(int(v) for v in self._roh[i, :int(self.hoehe[i])])

    def zelltypen(self, i: int) -> tuple[int, ...]:
        """Die Zelltypen von Band `i`, passend zu `saeule`."""
        return tuple(int(v) for v in self._zelltypen[i, :int(self.hoehe[i])])

    def nachfolger(self, a: int, familie: int | None = None) -> list:
        """Was darf rechts neben Band `a` stehen? -> [(b, versatz, anzahl)]"""
        aus = self._nach.get(int(a), [])
        if familie is None:
            return aus
        return [t for t in aus if int(self.familie[t[0]]) == familie]

    def der_familie(self, familie: str) -> np.ndarray:
        """Alle Baenderplaetze einer Familie, haeufigste zuerst."""
        if familie not in self.familien_namen:
            raise ValueError(f"unbekannte Familie: {familie}")
        fi = self.familien_namen.index(familie)
        return np.nonzero(self.familie == fi)[0]

    def kern(self, anteil: float = 0.9) -> np.ndarray:
        """Die haeufigsten Baender, die zusammen `anteil` der Vorkommen decken.

        Gemessen decken 32 Baender die Haelfte aller Vorkommen, 160 decken 80 %
        und 367 decken 90 %. Der lange Schwanz -- 49,6 % der Baender kommen in
        54 Karten genau einmal vor -- ist fuer einen Setzer wertlos und macht
        die Auswahl nur unuebersichtlich.
        The commonest bands covering `anteil` of all occurrences.
        """
        summe = np.cumsum(self.haeufigkeit)
        n = int(np.searchsorted(summe, anteil * summe[-1]) + 1)
        return np.arange(n)


_modell: CliffColumnModel | None = None


def modell(pfad: Path | str = MODELL_PFAD) -> CliffColumnModel:
    """Das Modell einmal laden und behalten."""
    global _modell
    if _modell is None:
        _modell = CliffColumnModel(pfad)
    return _modell
