"""Die geschuerften Gruppen benutzen: welche Gruppe passt auf diese Form?

`learn_cliff_patches.py` schuerft, dieses Modul fragt. Getrennt gehalten, damit
der Trainer die Originalkarten braucht und der Editor nur die `.npz`.

Die FORM ist die harte Bedingung. Eine Gruppe darf nur dort liegen, wo genau die
Zellen Klippe sind, die in ihr Klippe sind -- wo die Form stimmt, kommen die
Kacheln mit. Deshalb sind die Gruppen nach ihrer Form abgelegt und nicht nach
ihren Kacheln: gesucht wird immer mit einer Form in der Hand.

Der Setzer nimmt die groesste Gruppe, die passt, und faellt auf kleinere zurueck
-- grosse tragen den Lauf, kleine decken die Flaeche. Was gar keine Gruppe
abdeckt, macht danach die Nachbarschaftstabelle in `cliff_tiles.py`.

Using the mined groups: the SHAPE is the constraint, so groups are indexed by
shape, not by tiles. Largest first, falling back to smaller ones.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODELL_PFAD = HERE / "cliff_patches_model.npz"


class CliffPatchModel:
    """Geschuerfte Gruppen, nach Groesse und Form nachschlagbar."""

    def __init__(self, pfad: Path | str = MODELL_PFAD):
        d = np.load(pfad)
        self._kacheln = d["kacheln"]
        self._zelltypen = d["zelltypen"]
        self._groesse = d["groesse"]
        self.anzahl = d["anzahl"]
        self.familie = d["familie"]
        self.familien_namen = [str(n) for n in d["familien_namen"]]
        self.karten = int(d["karten"])
        self.mindest = int(d["mindest"])
        self.wildcard = int(d["wildcard"])

        # Groessen in der Reihenfolge, in der sie geschuerft wurden: gross zuerst
        self.groessen: list[tuple[int, int]] = []
        for bw, bh in self._groesse:
            g = (int(bw), int(bh))
            if g not in self.groessen:
                self.groessen.append(g)

        # (bw, bh) -> Formschluessel -> [(kacheln, zelltypen, anzahl, familie)]
        self._nach_form: dict = {}
        for i in range(len(self.anzahl)):
            bw, bh = int(self._groesse[i, 0]), int(self._groesse[i, 1])
            bloc = self._kacheln[i, :bw * bh].reshape(bh, bw)
            zt = self._zelltypen[i, :bw * bh].reshape(bh, bw)
            schl = (bloc != self.wildcard).tobytes()
            self._nach_form.setdefault((bw, bh), {}).setdefault(
                schl, []).append((bloc, zt, int(self.anzahl[i]),
                                  int(self.familie[i])))
        for tab in self._nach_form.values():
            for liste in tab.values():
                liste.sort(key=lambda t: -t[2])

    def __len__(self) -> int:
        return len(self.anzahl)

    def passend(self, maske: np.ndarray, vorhanden: np.ndarray | None = None,
                familie: int | None = None,
                zelltypen: np.ndarray | None = None) -> list:
        """Gruppen, die auf diese Form passen -> [(kacheln, zelltypen, anzahl)].

        `maske` ist ein (bh, bw)-Wahrheitsfeld: welche Zelle ist Klippe.
        `vorhanden` ist wahlweise ein gleich grosses Feld mit bereits gesetzten
        Kacheln; -1 heisst "noch offen". Eine Gruppe passt nur, wenn sie den
        gesetzten Kacheln nicht widerspricht.

        `zelltypen` ist wahlweise das Feld der geforderten Zelltypen. Es ist
        eine EINGABE und nichts, was sich aus der Form ergibt: dieselbe Kontur
        gibt es mit dem Hochland oben und mit dem Hochland unten. Wer es
        weglaesst, waehlt die Seite blind -- gemessen 16,8 % der Zellen mit
        vertauschter Hoch- und Tiefseite.

        Haeufigste zuerst. Leer heisst: fuer diese Form gibt es keine Gruppe.
        """
        bh, bw = maske.shape
        kand = self._nach_form.get((bw, bh), {}).get(maske.tobytes(), [])
        aus = []
        for bloc, zt, n, fam in kand:
            if familie is not None and fam != familie:
                continue
            if zelltypen is not None and not np.array_equal(
                    zt[maske], zelltypen[maske]):
                continue
            if vorhanden is not None:
                gesetzt = vorhanden >= 0
                if gesetzt.any() and not np.array_equal(
                        bloc[gesetzt], vorhanden[gesetzt]):
                    continue
            aus.append((bloc, zt, n))
        return aus

    def formen(self, bw: int, bh: int) -> int:
        """Wieviele verschiedene Formen sind fuer diese Groesse bekannt?"""
        return len(self._nach_form.get((bw, bh), {}))


_modell: CliffPatchModel | None = None


def modell(pfad: Path | str = MODELL_PFAD) -> CliffPatchModel:
    """Das Modell einmal laden und behalten."""
    global _modell
    if _modell is None:
        _modell = CliffPatchModel(pfad)
    return _modell
