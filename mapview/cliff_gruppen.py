"""Die geschuerften Klippengruppen, nachschlagbar nach FORM.

Das aeltere `cliff_patches` haelt dieselben Gruppen, aber ueber die Fuellung
indiziert. Beim Setzen lautet die Frage aber nicht "kenne ich diese
Kachelfolge", sondern "hier steht diese Stufe -- welche Kacheln gehoeren da
hin?". Nach Fuellung indiziert muss man dafuer alle Gruppen durchgehen; nach
Form indiziert schlaegt man einmal nach.

Eine Gruppe beschreibt die KLIPPE, nicht das Gelaende daneben: wo Boden liegt,
steht `BODEN` und die Gruppe sagt darueber nichts. Sonst zerfiele der Vorrat in
Einzelfaelle, weil jede Bodenvariante eine eigene Gruppe waere.

Groessen von gross nach klein: 6x4, 4x6, 4x3, 3x4, 3x3, 2x2. Keine allein
reicht -- die grosse traegt die Richtung eines Laufs, die kleine deckt, was
uebrig bleibt. Anteil der Klippenzellen, die in einer Gruppe ab 10 Vorkommen
liegen: 6x4 80,2 %, 4x3 90,3 %, 3x3 93,6 %, 2x2 97,4 %.

The mined cliff groups, looked up by SHAPE. When placing, the question is
"this step is here, which tiles belong in it?" -- keying by filling makes that
a search, keying by shape makes it a lookup.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

HIER = Path(__file__).resolve().parent
MODELL_PFAD = HIER / "cliff_gruppen_model.npz"

BODEN = -1          # dort liegt Gelaende
RAND = -2           # Auffuellung, weil die Groessen verschieden sind


class CliffGroupModel:
    """Gruppen, nach (Groesse, Form) nachschlagbar."""

    def __init__(self, pfad: Path | str = MODELL_PFAD):
        d = np.load(pfad, allow_pickle=True)
        self.groesse = d["groesse"]                  # (N, 2) bw, bh
        self.form = d["form"]                        # (N, 24) 1/0/RAND
        self.kacheln = d["kacheln"]                  # (N, 24) Kachel/BODEN
        self.anzahl = d["anzahl"]
        self.familie = d["familie"]
        self.familien_namen = [str(s) for s in d["familien_namen"]]
        self.karten = int(d["karten"])
        self.mindest = int(d["mindest"])

        # Der Index: (bw, bh, Form als Bytes, Familie) -> Zeilen, haeufigste
        # zuerst. Einmal beim Laden, danach ist jede Abfrage ein Nachschlagen.
        self._index: dict = defaultdict(list)
        for i in range(len(self.anzahl)):
            bw, bh = int(self.groesse[i, 0]), int(self.groesse[i, 1])
            f = self.form[i, :bw * bh].astype(bool).tobytes()
            self._index[(bw, bh, f, int(self.familie[i]))].append(i)
        for zeilen in self._index.values():
            zeilen.sort(key=lambda i: -int(self.anzahl[i]))
        self._index = dict(self._index)

        # Die Groessen, gross zuerst -- so probiert der Setzer sie auch.
        gesehen = []
        for i in range(len(self.anzahl)):
            g = (int(self.groesse[i, 0]), int(self.groesse[i, 1]))
            if g not in gesehen:
                gesehen.append(g)
        self.groessen = sorted(gesehen, key=lambda g: -(g[0] * g[1]))

    def __len__(self) -> int:
        return len(self.anzahl)

    def fuellung(self, i: int) -> np.ndarray:
        """Die Kacheln der Gruppe `i` als (bh, bw); `BODEN` wo Gelaende."""
        bw, bh = int(self.groesse[i, 0]), int(self.groesse[i, 1])
        return self.kacheln[i, :bw * bh].reshape(bh, bw)

    def maske(self, i: int) -> np.ndarray:
        bw, bh = int(self.groesse[i, 0]), int(self.groesse[i, 1])
        return self.form[i, :bw * bh].astype(bool).reshape(bh, bw)

    def zu_form(self, maske: np.ndarray, familie: int) -> list:
        """Alle Gruppen mit genau dieser Form -> Zeilen, haeufigste zuerst."""
        bh, bw = maske.shape
        return self._index.get((bw, bh, maske.tobytes(), int(familie)), [])

    def passend(self, maske: np.ndarray, vorhanden: np.ndarray,
                familie: int) -> list:
        """Gruppen, die zur Form passen UND zu dem, was schon steht.

        `vorhanden` ist so gross wie `maske` und enthaelt die bereits gesetzten
        Kacheln; -1 heisst "noch frei". Nur belegte Zellen binden -- Boden
        gehoert nicht dazu, sonst zaehlte er als Bedingung und die Trefferquote
        bricht ein (gemessen 13,9 auf 4,2 Prozent, als das einmal falsch war).

        -> [(Zeile, Fuellung)], haeufigste zuerst.
        """
        aus = []
        for i in self.zu_form(maske, familie):
            f = self.fuellung(i)
            if np.all((vorhanden < 0) | (f == vorhanden)):
                aus.append((i, f))
        return aus

    def formen_je_groesse(self) -> dict:
        """Nur zur Auskunft: wieviele Formen es je Groesse gibt."""
        z: dict = defaultdict(set)
        for (bw, bh, f, _fam) in self._index:
            z[(bw, bh)].add(f)
        return {g: len(v) for g, v in sorted(z.items(),
                                             key=lambda t: -(t[0][0]*t[0][1]))}


_zwischen: dict[str, CliffGroupModel] = {}


def modell(pfad: Path | str = MODELL_PFAD) -> CliffGroupModel:
    """Das Modell, einmal geladen und dann gemerkt."""
    s = str(pfad)
    if s not in _zwischen:
        _zwischen[s] = CliffGroupModel(pfad)
    return _zwischen[s]
