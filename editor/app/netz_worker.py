"""Gelernter Kartengenerator im eigenen Thread (siehe `mapview/mapgen_netz.py`).

The learned map generator in its own thread.
"""
from __future__ import annotations

from .common import *

import mapgen_netz


class NetzWorker(QThread):
    """Rechnet erst die Skizze, dann die Karte; abbrechbar.

    Computes the sketch first, then the map; can be cancelled."""
    skizze_fertig = Signal(object)
    fortschritt = Signal(int)
    ok = Signal(object)
    err = Signal(str)

    def __init__(self, params, stufe: str, skizze=None):
        super().__init__()
        self.params = params
        self.stufe = stufe
        self.skizze = skizze
        self.abgebrochen = False
        self._stop = False

    def abbrechen(self):
        self._stop = True

    def run(self):
        try:
            halt = lambda: self._stop
            sk = self.skizze
            if sk is None:
                sk = mapgen_netz.skizze(self.params, halt)
            self.skizze_fertig.emit(sk)
            gen = mapgen_netz.karte(
                self.params, sk, self.stufe,
                lambda a: self.fortschritt.emit(int(100 * a)), halt)
            self.ok.emit(gen)
        except mapgen_netz.Abgebrochen:
            self.abgebrochen = True
        except Exception as e:
            self.err.emit(f"{type(e).__name__}: {e}")
