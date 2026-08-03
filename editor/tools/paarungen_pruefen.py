"""Paarungen pruefen und nachbessern: wo widerspricht die Zuordnung den Karten?

Aufruf:  python editor/tools/paarungen_pruefen.py

Aus `cliff_kanten.json` folgt, welche Kacheln aneinander passen: die
beruehrenden Muster muessen gleich sein. Dagegen stehen die Originalkarten, die
sagen, was tatsaechlich nebeneinander liegt. Vier Faelle:

    passt + belegt          in Ordnung
    passt + unbelegt        neu -- geht nach der Zuordnung, wurde nie gebaut
    passt NICHT + belegt    Widerspruch -- die Karten bauen es, die Zuordnung
                            verbietet es
    passt nicht + unbelegt  uninteressant

Gezeigt werden die Widersprueche, die haeufigsten zuerst. Sie sind der einzige
Fall, in dem die Originalkarten der Zuordnung widersprechen koennen -- und
damit der einzige, bei dem sich ein Fehler beweisen laesst.

Bedienung:
    Klick auf einen Abschnitt   umschalten (beide Kacheln sind editierbar)
    Pfeil links/rechts          zum vorigen/naechsten Widerspruch
    1 / 2                       nur Paare mit genau einem / hoechstens zwei
                                abweichenden Abschnitten
    Strg+Z                      zurueck, Strg+S speichern (geht auch selbst)

Gemessen an der ersten Zuordnung fuer mud: von 4484 belegten Paaren sind 1300
Widersprueche (29 %), und die allermeisten weichen nur in EINEM Abschnitt ab.
Bei vier Abschnitten zu acht Pixeln faellt eine schraege Grenze mitten in einen
Abschnitt, und zwei Kacheln runden sie verschieden.

Reviewing pairings: which pairs does the manual assignment forbid that the
original maps actually build? Those are the only provable mistakes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import (QColor, QImage, QKeySequence, QMouseEvent, QPainter,
                           QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QVBoxLayout, QWidget)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
if str(ROOT / "mapview") not in sys.path:
    sys.path.insert(0, str(ROOT / "mapview"))

ZIEL = ROOT / "mapview" / "cliff_kanten.json"
SEITEN = ("N", "O", "S", "W")
GEGEN = {"N": "S", "O": "W", "S": "N", "W": "O"}


def _passt(x, y):
    """Passen zwei Abschnitte? `egal` passt zu beidem."""
    return x == y or x == EGAL or y == EGAL
# 0 = Biom, 1 = Fels, 2 = egal -- siehe kanten_zuordnen.py
BIOM, FELS, EGAL = 0, 1, 2
NAME = {BIOM: "Biom", FELS: "Fels", EGAL: "egal"}
TON = {BIOM: QColor("#3a8ac9"), FELS: QColor("#c98a3a"),
       EGAL: QColor("#6f7a55")}
STREIT = QColor("#e04030")

# Kachelpaare unter dieser Haeufigkeit werden uebergangen. 1 heisst: keine.
#
# Die Haeufigkeit sagt, wie FOLGENREICH ein Widerspruch ist, nicht wie GROB.
# Gefiltert wird darum nach Schwere (MINDEST_ABWEICHUNG), nicht nach
# Haeufigkeit -- ein Paar mit einem Vorkommen und vier abweichenden
# Abschnitten ist ein Fehler, eines mit 900 Vorkommen und einem abweichenden
# Abschnitt meist nur eine Rundung.
MINDEST_VORKOMMEN = 1

# Wieviele Abschnitte mindestens abweichen muessen, damit ein Paar gezeigt
# wird. Gemessen am Stand der Zuordnung:
#
#   abweichende Abschnitte   Paare   Vorkommen   Kanten
#            1                787      10271       364
#            2                170        908       173
#            3                 49        166        62
#            4                 13         56        23
#
# Bei 4 Abschnitten zu acht Pixeln faellt eine schraege Fels-Boden-Grenze
# mitten in einen Abschnitt, und zwei Kacheln runden sie verschieden -- daher
# die 787 Faelle mit einer einzigen Abweichung. Wer die groben Fehler sucht,
# faengt weiter oben an.
#
# How many sections must differ for a pair to be shown: one differing section
# is usually just rounding at a diagonal boundary, three or four is a mistake.
MINDEST_ABWEICHUNG = 3

Z = 12          # Zoom der Kacheln -- 32 mal 32 ist sonst nicht
                # zu lesen, und es geht um Pixelkanten
BAND = 22       # Hoehe eines Abschnittsbandes


class Tafel(QWidget):
    """Vier Kacheln als 2x2, die Naht mittendurch.

    Zwei Kacheln allein sind bei 32 mal 32 Pixeln schwer zu lesen -- man sieht
    die Kante, aber nicht, wohin die Wand laeuft. Darum stehen die beiden
    Nachbarn dabei, die in den Originalkarten am haeufigsten dort liegen: aus
    dem Paar wird ein Stueck Wand.

    Bei einer Ost-Naht liegen a und b oben nebeneinander, darunter ihre
    haeufigsten Sued-Nachbarn. Bei einer Sued-Naht liegen a und b links
    untereinander, rechts daneben ihre haeufigsten Ost-Nachbarn. So laeuft die
    Naht in beiden Faellen mitten durch das Quadrat.

    Editierbar sind nur die Baender des Paares; die beiden Nachbarn stehen als
    Zusammenhang da.

    Four tiles as a 2x2 with the seam through the middle: two tiles alone are
    hard to read at 32 by 32, and the neighbours show where the wall runs.
    """

    def __init__(self, fenster):
        super().__init__()
        self.f = fenster
        seite = 2 * 32 * Z + 2 * BAND
        self.setFixedSize(seite, seite)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _lage(self):
        """-> (richtung, a, b, felder) mit felder = [(x, y, kachel, ist_paar)]

        Nach LAGE gefuehrt, nicht nach Kachelnummer: dieselbe Kachel kann
        zweimal im Quadrat stehen -- etwa wenn `a` zugleich der haeufigste
        Nachbar von `b` ist. In einem Woerterbuch nach Kachelnummer
        ueberschreibt der zweite Eintrag den ersten und ein Feld bleibt leer.

        Kept by POSITION, not by tile id: the same tile can appear twice in the
        square, and a dict keyed by id would drop one of the two.
        """
        p = self.f.paar_jetzt()
        if not p:
            return None
        r, a, b, _n = p
        quer = "S" if r == "O" else "O"
        za = self.f.haeufigster_nachbar(a, quer)
        zb = self.f.haeufigster_nachbar(b, quer)
        g = 32 * Z
        if r == "O":
            felder = [(0, 0, a, True), (g + BAND, 0, b, True),
                      (0, g + BAND, za, False),
                      (g + BAND, g + BAND, zb, False)]
        else:
            felder = [(0, 0, a, True), (g + BAND, 0, za, False),
                      (0, g + BAND, b, True),
                      (g + BAND, g + BAND, zb, False)]
        return r, a, b, felder

    def _felder(self):
        """-> [(QRect, kachel, seite, abschnitt)] fuer die zwei Baender."""
        lage = self._lage()
        if not lage:
            return []
        r, a, b, _felder = lage
        n = self.f.abschnitte
        gross = 32 * Z
        aus = []
        if r == "O":
            hoch = gross // n
            x0 = gross
            for i in range(n):
                aus.append((QRect(x0, i * hoch, BAND // 2, hoch), a, "O", i))
                aus.append((QRect(x0 + BAND // 2, i * hoch, BAND // 2, hoch),
                            b, "W", i))
        else:
            breit = gross // n
            y0 = gross
            for i in range(n):
                aus.append((QRect(i * breit, y0, breit, BAND // 2), a, "S", i))
                aus.append((QRect(i * breit, y0 + BAND // 2, breit, BAND // 2),
                            b, "N", i))
        return aus

    def paintEvent(self, e):                             # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e22"))
        lage = self._lage()
        if not lage:
            p.end()
            return
        r, a, b, felder = lage
        gross = 32 * Z
        for x, y, kachel, ist_paar in felder:
            if kachel is None:
                continue
            p.drawPixmap(x, y, self.f.pixmap(kachel).scaled(gross, gross))
            if not ist_paar:
                p.fillRect(x, y, gross, gross, QColor(20, 20, 24, 90))
        p.setPen(QPen(QColor("#e8e8ee"), 2))
        for x, y, kachel, ist_paar in felder:
            if ist_paar:
                p.drawRect(x, y, gross, gross)
        streit = self.f.streit_abschnitte()
        for rect, kachel, seite, i in self._felder():
            wert = self.f.muster[kachel][seite][i]
            p.fillRect(rect, STREIT if i in streit else TON[wert])
            p.setPen(QPen(QColor("#1e1e22"), 1))
            p.drawRect(rect)
            if i in streit or wert == EGAL:
                p.setPen(QPen(QColor("#fff"), 1))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                           "FB?"[wert])
        p.end()

    def mousePressEvent(self, e: QMouseEvent):           # noqa: N802
        for rect, kachel, seite, i in self._felder():
            if rect.contains(e.position().toPoint()):
                self.f.umschalten(kachel, seite, i)
                return


class Fenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Paarungen pruefen")

        d = np.load(ROOT / "mapview" / "cliff_pixels_model.npz")
        self.kacheln = [int(t) for t in d["kacheln"]]
        self.bilder = d["bilder"]
        self.abschnitte = int(d["abschnitte"])
        self.platz = {t: i for i, t in enumerate(self.kacheln)}
        from cliff_tiles import modell as _ctm
        self.ct = _ctm()

        roh = json.loads(ZIEL.read_text(encoding="utf-8"))
        self.muster = {int(k): {s: [int(x) for x in v] for s, v in e.items()}
                       for k, e in roh["kanten"].items()}
        self.bearbeitet = set(int(t) for t in roh.get("bearbeitet", []))
        # Welche Kachelseiten schon von Hand entschieden sind. Eine Naht
        # entscheidet ZWEI davon auf einmal -- die muessen nicht noch
        # einmal angefasst werden.
        self.festgelegt = set(roh.get("festgelegt", []))

        self.hoechstens = 4          # Obergrenze
        self.mindestens = MINDEST_ABWEICHUNG
        self.rueckgaengig = []
        self.stelle = 0
        self._sammeln()

        self.spar_uhr = QTimer(self)
        self.spar_uhr.setSingleShot(True)
        self.spar_uhr.setInterval(700)
        self.spar_uhr.timeout.connect(self._speichern)

        haupt = QWidget()
        self.setCentralWidget(haupt)
        aussen = QVBoxLayout(haupt)
        self.kopf = QLabel()
        self.kopf.setStyleSheet("font-size: 15px; padding: 4px;")
        aussen.addWidget(self.kopf)

        mitte = QHBoxLayout()
        aussen.addLayout(mitte, 1)
        self.tafel = Tafel(self)
        mitte.addWidget(self.tafel, 0, Qt.AlignmentFlag.AlignTop)
        rechts = QVBoxLayout()
        mitte.addLayout(rechts, 1)
        self.text = QLabel()
        self.text.setStyleSheet("font-family: monospace; color: #ddd;")
        self.text.setWordWrap(True)
        rechts.addWidget(self.text)
        rechts.addStretch(1)
        mitte.addStretch(1)

        fuss = QHBoxLayout()
        aussen.addLayout(fuss)
        for text, schritt in (("<< vorheriger", -1), ("naechster >>", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=schritt: self._blaettern(s))
            fuss.addWidget(b)
        for text, lo, hi in (("nur grobe (3+)", 3, 4), ("ab 2", 2, 4),
                             ("alle", 1, 4)):
            b = QPushButton(text)
            b.clicked.connect(
                lambda _=False, lo=lo, hi=hi: self._filter(lo, hi))
            fuss.addWidget(b)
        fuss.addStretch(1)
        b = QPushButton("speichern")
        b.clicked.connect(self._speichern)
        fuss.addWidget(b)

        for taste, schritt in (("Left", -1), ("Right", 1),
                               ("PgUp", -10), ("PgDown", 10)):
            QShortcut(QKeySequence(taste), self,
                      lambda s=schritt: self._blaettern(s))
        QShortcut(QKeySequence("1"), self, lambda: self._filter(1))
        QShortcut(QKeySequence("2"), self, lambda: self._filter(2))
        QShortcut(QKeySequence("3"), self, lambda: self._filter(3))
        QShortcut(QKeySequence("Ctrl+Z"), self, self._zurueck)
        QShortcut(QKeySequence("Ctrl+S"), self, self._speichern)

        self.resize(1180, 900)
        self._zeigen()

    # -- Daten ----------------------------------------------------------
    def _sammeln(self):
        """Alle Widersprueche einsammeln, haeufigste zuerst."""
        beteiligt = [t for t in self.bearbeitet
                     if t in self.muster and self.ct.ist_klippe(t)]
        aus = []
        for r in ("O", "S"):
            for a in beteiligt:
                nb = self.ct.nachbarn(a, r)
                for b, n in nb.items():
                    if b not in self.muster or b not in self.bearbeitet:
                        continue
                    if n < MINDEST_VORKOMMEN:
                        continue
                    k = sum(1 for i in range(self.abschnitte)
                            if not _passt(self.muster[a][r][i],
                                          self.muster[b][GEGEN[r]][i]))
                    if k:
                        aus.append((r, a, b, n, k))
        aus.sort(key=lambda t: -t[3])
        self.alle_paare = aus
        self._filter_anwenden()

    def _filter_anwenden(self):
        self.paare = [p for p in self.alle_paare
                      if self.mindestens <= p[4] <= self.hoechstens]
        self.stelle = min(self.stelle, max(0, len(self.paare) - 1))

    def paar_jetzt(self):
        if not self.paare:
            return None
        r, a, b, n, _k = self.paare[self.stelle]
        return r, a, b, n

    def streit_abschnitte(self):
        p = self.paar_jetzt()
        if not p:
            return set()
        r, a, b, _n = p
        return {i for i in range(self.abschnitte)
                if not _passt(self.muster[a][r][i],
                              self.muster[b][GEGEN[r]][i])}

    def wirkung(self, kachel, seite):
        """Was haengt an dieser Kachelseite? -> (Vorkommen, davon stimmig)

        Eine Kante gehoert allen Nachbarn dieser Kachel auf dieser Seite
        gleichzeitig. Wer sie aendert, aendert JEDE Paarung, in der sie
        vorkommt -- gemessen hat eine Korrektur an `94 Sued` prompt die Paarung
        `94 -> 97` aufgerissen, die 1130 mal in den Karten steht.
        """
        ges = gut = 0
        for b, n in self.ct.nachbarn(kachel, seite).items():
            if b not in self.muster or n < MINDEST_VORKOMMEN:
                continue
            ges += n
            if all(_passt(x, y) for x, y in
                   zip(self.muster[kachel][seite],
                       self.muster[b][GEGEN[seite]])):
                gut += n
        return ges, gut

    def haeufigster_nachbar(self, kachel, seite):
        """Welche Kachel liegt in den Originalen dort am haeufigsten?

        Nur als Zusammenhang zum Ansehen -- damit aus dem Paar ein Stueck Wand
        wird und man sieht, wohin die Naht gehoert.
        """
        z = self.ct.nachbarn(kachel, seite)
        z = {b: n for b, n in z.items() if b in self.platz}
        return max(z, key=z.get) if z else None

    def pixmap(self, kachel):
        b = self.bilder[self.platz[kachel]]
        h, w, _ = b.shape
        return QPixmap.fromImage(
            QImage(b.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888))

    def _speichern(self):
        roh = json.loads(ZIEL.read_text(encoding="utf-8"))
        roh["kanten"] = {str(k): v for k, v in sorted(self.muster.items())}
        roh["bearbeitet"] = sorted(self.bearbeitet)
        roh["festgelegt"] = sorted(self.festgelegt)
        ZIEL.write_text(json.dumps(roh, indent=1, ensure_ascii=False),
                        encoding="utf-8")
        self.spar_uhr.stop()
        self._kopf()

    def closeEvent(self, e):                             # noqa: N802
        self._speichern()
        super().closeEvent(e)

    # -- Bedienung ------------------------------------------------------
    def umschalten(self, kachel, seite, i):
        """Ein Klick schliesst die NAHT, nicht nur eine Seite.

        Eine Kante gehoert immer zweien. Wer nur eine Seite kippt, macht das
        Paar nicht heil, sondern verschiebt den Widerspruch -- und muss die
        andere Seite gleich darauf auch anfassen. Also entscheidet der Klick,
        was an dieser Naht liegt, und BEIDE Kacheln uebernehmen es. Damit sind
        zwei Kachelseiten auf einmal erledigt.

        A click closes the SEAM: an edge belongs to two tiles, so both take the
        clicked value at once, settling two tile edges in one go.
        """
        p = self.paar_jetzt()
        if not p:
            return
        r, a, b, _n = p
        partner, gegen = (b, GEGEN[r]) if kachel == a else (a, r)
        neu = {FELS: BIOM, BIOM: EGAL, EGAL: FELS}[
            self.muster[kachel][seite][i]]
        self.rueckgaengig.append(
            ((kachel, seite, i, self.muster[kachel][seite][i]),
             (partner, gegen, i, self.muster[partner][gegen][i])))
        self.muster[kachel][seite][i] = neu
        self.muster[partner][gegen][i] = neu
        self.bearbeitet.add(kachel)
        self.bearbeitet.add(partner)
        self.festgelegt.add("%d:%s" % (kachel, seite))
        self.festgelegt.add("%d:%s" % (partner, gegen))
        self.spar_uhr.start()
        self._zeigen()

    def _zurueck(self):
        if not self.rueckgaengig:
            return
        for kachel, seite, i, wert in self.rueckgaengig.pop():
            self.muster[kachel][seite][i] = wert
        self.spar_uhr.start()
        self._zeigen()

    def _blaettern(self, schritt):
        if self.spar_uhr.isActive():
            self._speichern()
        if self.paare:
            self.stelle = (self.stelle + schritt) % len(self.paare)
        self._zeigen()

    def _filter(self, lo, hi=4):
        self.mindestens, self.hoechstens = lo, hi
        self._filter_anwenden()
        self._zeigen()

    def _wirkung_text(self, kachel, seite):
        ges, gut = self.wirkung(kachel, seite)
        fest = "  (festgelegt)" if "%d:%s" % (kachel, seite) \
            in self.festgelegt else ""
        if not ges:
            return f"\n   {kachel} {seite}: kein Nachbar gemessen{fest}"
        return (f"\n   {kachel} {seite}: {ges} Vorkommen, davon stimmig "
                f"{gut} ({100*gut/ges:.0f} %){fest}")

    # -- Anzeige --------------------------------------------------------
    def _kopf(self):
        offen = sum(1 for p in self.alle_paare
                    if any(not _passt(self.muster[p[1]][p[0]][i],
                                      self.muster[p[2]][GEGEN[p[0]]][i])
                           for i in range(self.abschnitte)))
        p = self.paar_jetzt()
        if not p:
            self.kopf.setText("kein Widerspruch mehr")
            return
        r, a, b, n = p
        self.kopf.setText(
            f"{a} {r} an {b}   —   {n} mal in den Originalkarten   |   "
            f"{self.stelle + 1} von {len(self.paare)} "
            f"(ab {self.mindestens} abweichenden Abschnitten)   |   "
            f"noch offen insgesamt: {offen}")

    def _zeigen(self):
        p = self.paar_jetzt()
        if p:
            r, a, b, n = p
            streit = self.streit_abschnitte()
            def zeile(kachel, s):
                return " ".join(
                    f"[{NAME[self.muster[kachel][s][i]]}]" if i in streit
                    else f" {NAME[self.muster[kachel][s][i]]} "
                    for i in range(self.abschnitte))

            self.text.setText(
                f"{a} {r}:   " + zeile(a, r)
                + f"\n{b} {GEGEN[r]}:   " + zeile(b, GEGEN[r])
                + f"\n\n{len(streit)} von {self.abschnitte} Abschnitten "
                  f"verschieden.  Die Originalkarten setzen diese "
                  f"beiden {n} mal nebeneinander."
                + "\n\nWas an diesen Kanten haengt:"
                + self._wirkung_text(a, r)
                + self._wirkung_text(b, GEGEN[r])
                + "\n\nEin Klick setzt BEIDE Seiten -- die Naht "
                  "ist damit entschieden."
                + "\n\nDie zwei abgedunkelten Kacheln sind nur "
                  "Zusammenhang:\nder haeufigste Nachbar aus den "
                  "Originalkarten.")
        self.tafel.update()
        self._kopf()


def main():
    if not ZIEL.exists():
        print(f"{ZIEL} fehlt -- erst mit kanten_zuordnen.py zuordnen.")
        return
    app = QApplication(sys.argv)
    f = Fenster()
    f.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
