"""Gelernter Kartengenerator im eigenen Thread: OP2MappingLib (maplib.skizze,
maplib.generieren_gelernt).

The learned map generator in its own thread, computed by OP2MappingLib.
"""
from __future__ import annotations

from .common import *
from . import maplib


class NetzWorker(QThread):
    """Rechnet erst die Skizze, dann die Karte; abbrechbar.

    Computes the sketch first, then the map; can be cancelled."""
    skizze_fertig = Signal(object)
    fortschritt = Signal(int)
    ok = Signal(object)
    err = Signal(str)

    def __init__(self, params, stufe: str, skizze=None, threads: int = 0):
        super().__init__()
        self.params = params
        self.stufe = stufe
        self.skizze = skizze
        self.threads = threads
        self.abgebrochen = False
        self._stop = False

    def abbrechen(self):
        self._stop = True

    def run(self):
        try:
            halt = lambda: self._stop
            sk = self.skizze
            if sk is None:
                sk = maplib.skizze(self.params, self.threads, halt)
            self.skizze_fertig.emit(sk)
            gen = maplib.generieren_gelernt(
                self.params, self.stufe, self.threads,
                lambda a: self.fortschritt.emit(int(100 * a)), halt)
            self.ok.emit(gen)
        except maplib.Abgebrochen:
            self.abgebrochen = True
        except Exception as e:
            self.err.emit(f"{type(e).__name__}: {e}")
