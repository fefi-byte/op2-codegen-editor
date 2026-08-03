"""Die Nachbarschaftstabelle benutzen: was darf neben Kachel x stehen?

`learn_cliff_tiles.py` zaehlt aus, dieses Modul fragt. Getrennt gehalten, damit
der Trainer die Originalkarten braucht und der Editor nur die `.npz`.

Zwei Fragen, die auseinandergehalten werden muessen:

    passt(a, b, "O")        darf rechts von a die Klippenkachel b stehen?
    boden_anteil(a, "N")    wie oft liegt noerdlich von a offenes Gelaende?

Wo eine Klippenkachel an offenes Gelaende grenzt, darf dort jede Bodenkachel
stehen -- die Klippenliste ist dann leer und sagt nichts aus, obwohl die
Richtung natuerlich erlaubt ist. Wer beides in einen Topf wirft, misst
Beliebigkeit, wo eine scharfe Regel steht.

Using the adjacency table. Cliff neighbours and "ground allowed here" are two
different questions and are answered separately.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODELL_PFAD = HERE / "cliff_tiles_model.npz"

# Teil des Dateiformats: 0..3 gerade (harte Bedingung), 4..7 schraeg (Gewicht).
RICHTUNGEN = ("N", "O", "S", "W", "NO", "SO", "SW", "NW")
VERSATZ = {"N": (0, -1), "O": (1, 0), "S": (0, 1), "W": (-1, 0),
           "NO": (1, -1), "SO": (1, 1), "SW": (-1, 1), "NW": (-1, -1)}
GEGEN = {"N": "S", "O": "W", "S": "N", "W": "O",
         "NO": "SW", "SO": "NW", "SW": "NO", "NW": "SO"}

# Wie stark eine Diagonale mitreden darf, wenn mit Anteilen gerechnet wird.
# Ausschliessen darf sie nie (siehe `moeglich`), nur bevorzugen: das Gewicht
# reicht von 1 (die Kachel kam dort nie vor) bis 1 + SCHRAEG_GEWICHT.
#
# Gemessen, nicht gesetzt. Ueber drei Karten, Vorhersage aus den echten
# Nachbarn, gegen die Wiederholungsrate der Originale (gerade 0,85 %):
#
#   rohe Zahlen             87,8 % Platz 1     1,64 % gleicher gerader Nachbar
#   Anteile, schraeg  x0    87,9 %             1,30 %
#   Anteile, schraeg  x1    88,1 %             1,29 %      <- gewaehlt
#   Anteile, schraeg  x9    88,0 %             1,35 %
#   Anteile, schraeg x20    87,7 %             1,40 %
#
# Der Unterschied ist klein, geht aber in beide Richtungen zugleich in die
# richtige: mehr Treffer UND weniger Wiederholung.
# How strongly a diagonal may weigh in; it may never exclude, only prefer.
SCHRAEG_GEWICHT = 1.0

# In `moeglich` statt einer Kachelnummer: dort liegt offenes Gelaende.
#
# Das ist keine fehlende Angabe, sondern eine harte Bedingung. 186 der 307
# Kacheln haben nach Norden nie Boden, nach Sueden 62 -- "dort oben liegt
# Gelaende" schliesst also mehr als die Haelfte des Vorrats aus. Wer diese
# Richtungen einfach weglaesst, weil dort keine Klippe steht, wirft die
# Information weg, die die Kachel festlegt.
# Not a missing value but a hard constraint: 186 of 307 tiles never have ground
# to the north.
BODEN = "Boden"


def _ri(r: int | str) -> int:
    return r if isinstance(r, int) else RICHTUNGEN.index(r)


class CliffTileModel:
    """Welche Kachel darf in welcher Richtung neben welcher stehen."""

    def __init__(self, pfad: Path | str = MODELL_PFAD):
        d = np.load(pfad)
        self.kacheln = d["kacheln"]
        self.vorkommen = d["vorkommen"]
        self.zelltyp = d["zelltyp"]
        self.familie = d["familie"]
        self.familien_namen = [str(n) for n in d["familien_namen"]]
        self._boden = d["boden"]
        self._rand = d["kartenrand"]
        self.karten = int(d["karten"])
        self.gerade = int(d["gerade"])
        self._platz = {int(t): i for i, t in enumerate(self.kacheln)}
        # (richtung, a) -> {b: anzahl}, alles in Kachelnummern, nicht Plaetzen
        self._nach: dict = {}
        for r, a, b, n in zip(d["nb_richtung"], d["nb_a"], d["nb_b"],
                              d["nb_anzahl"]):
            schl = (int(r), int(self.kacheln[a]))
            self._nach.setdefault(schl, {})[int(self.kacheln[b])] = int(n)

    def __len__(self) -> int:
        return len(self.kacheln)

    def ist_klippe(self, kachel: int) -> bool:
        """Kommt diese Kachel in den Originalen ueberhaupt als Klippe vor?"""
        return int(kachel) in self._platz

    def nachbarn(self, kachel: int, richtung: int | str) -> dict:
        """Erlaubte Klippennachbarn -> {kachel: Anzahl}. Leer heisst: keine.

        Leer bedeutet NICHT "hier darf nichts stehen" -- es bedeutet, dass dort
        nie eine Klippenkachel stand. Ob Boden erlaubt ist, sagt `boden_anteil`.
        """
        return dict(self._nach.get((_ri(richtung), int(kachel)), {}))

    def besten(self, kachel: int, richtung: int | str,
               anteil: float = 0.95) -> list:
        """Die haeufigsten Nachbarn, die zusammen `anteil` der Faelle decken.

        Der Schwanz ist lang und duenn: im Median decken vier bis fuenf Kacheln
        95 % der Faelle, obwohl sieben bis neun ueberhaupt vorkommen.
        """
        z = self.nachbarn(kachel, richtung)
        if not z:
            return []
        ges = sum(z.values())
        aus, s = [], 0
        for b, n in sorted(z.items(), key=lambda t: -t[1]):
            aus.append((b, n))
            s += n
            if s >= anteil * ges:
                break
        return aus

    def passt(self, a: int, b: int, richtung: int | str) -> bool:
        """Stand b in den Originalen je in `richtung` neben a?"""
        return int(b) in self._nach.get((_ri(richtung), int(a)), {})

    def boden_anteil(self, kachel: int, richtung: int | str) -> float:
        """Anteil der Faelle, in denen dort offenes Gelaende lag (0 bis 1).

        0.0 heisst: dort stand nie Boden -- eine harte Bedingung. 1.0 heisst:
        dort stand nie eine Klippe.
        """
        i = self._platz.get(int(kachel))
        if i is None:
            return 0.0
        r = _ri(richtung)
        b = int(self._boden[i, r])
        k = sum(self._nach.get((r, int(kachel)), {}).values())
        return b / (b + k) if b + k else 0.0

    def moeglich(self, umgebung: dict, familie: int | None = None,
                 normiert: bool = True,
                 schraeg_gewicht: float = SCHRAEG_GEWICHT) -> dict:
        """Welche Kacheln passen zu den Nachbarn? -> {kachel: Gewicht}

        `umgebung` ist {richtung: nachbarkachel}, wobei `BODEN` fuer offenes
        Gelaende steht; unbekannte Richtungen laesst man weg. Eine Richtung
        wegzulassen, weil dort keine Klippe steht, ist etwas anderes, als dort
        `BODEN` einzutragen -- siehe die Erklaerung bei `BODEN`.

        Die vier geraden Richtungen sind harte Bedingung, die vier Diagonalen
        gehen nur ins Gewicht ein: eine Diagonale darf nichts ausschliessen,
        sonst steht der Setzer dreimal so oft vor einer Zelle, in die gar nichts
        passt (0,70 % gegen 2,37 %, auf ungesehenen Karten gemessen).

        Das Gewicht ist das Produkt ueber die Richtungen: Haeufiges wird
        bevorzugt, Seltenes bleibt moeglich.

        `normiert` teilt dabei jede Richtung durch ihre eigene Summe, rechnet
        also mit Anteilen statt mit rohen Zahlen. Mit rohen Zahlen gewinnt, wer
        insgesamt haeufig ist, und der Setzer legt dieselbe Kachel zu oft
        nebeneinander: gemessen 2,4 bis 8,6 % gleiche gerade Nachbarn, wo die
        Originalkarten 0,85 % haben (ueber Eck 7,4 % gegen 1,31 %).
        Normalised weights use shares per direction instead of raw counts; raw
        counts favour globally common tiles and visibly tile the surface.
        """
        kand: dict | None = None
        weich = []
        for r, nachbar in umgebung.items():
            if nachbar is None:
                continue
            name = r if isinstance(r, str) else RICHTUNGEN[_ri(r)]
            if nachbar == BODEN:
                hier = {int(t): int(self._boden[i, _ri(name)])
                        for i, t in enumerate(self.kacheln)
                        if self._boden[i, _ri(name)] > 0}
            else:
                # von nachbar aus zurueck: was darf auf unserer Seite stehen?
                hier = self.nachbarn(nachbar, GEGEN[name])
            if normiert and hier:
                s = sum(hier.values())
                hier = {b: n / s for b, n in hier.items()}
            if _ri(name) >= self.gerade:
                weich.append(hier)
                continue
            if kand is None:
                kand = dict(hier)
            else:
                kand = {b: kand[b] * n for b, n in hier.items() if b in kand}
            if not kand:
                return {}
        if kand is None:
            kand = {int(t): int(v) for t, v in zip(self.kacheln,
                                                   self.vorkommen)}
        for hier in weich:
            if hier:
                kand = {b: n * (1 + schraeg_gewicht * hier.get(b, 0))
                        for b, n in kand.items()}
        if familie is not None:
            kand = {b: n for b, n in kand.items()
                    if int(self.familie[self._platz[b]]) == familie}
        return kand

    def der_familie(self, familie: str) -> np.ndarray:
        """Alle Klippenkacheln einer Familie, haeufigste zuerst."""
        if familie not in self.familien_namen:
            raise ValueError(f"unbekannte Familie: {familie}")
        fi = self.familien_namen.index(familie)
        return self.kacheln[self.familie == fi]


_modell: CliffTileModel | None = None


def modell(pfad: Path | str = MODELL_PFAD) -> CliffTileModel:
    """Das Modell einmal laden und behalten."""
    global _modell
    if _modell is None:
        _modell = CliffTileModel(pfad)
    return _modell
