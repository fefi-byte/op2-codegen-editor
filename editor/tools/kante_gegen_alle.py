"""Eine Kachelseite und ALLE Gegenkacheln, die nicht dazu stimmen.

Aufruf:  python editor/tools/kante_gegen_alle.py

Paar fuer Paar durchzugehen ist der falsche Schnitt. Eine Kante gehoert allen
ihren Nachbarn gleichzeitig: wer sie aendert, aendert jede Paarung, in der sie
vorkommt. Gemessen hat eine Korrektur an `94 Sued` prompt die Paarung `94 an
97` aufgerissen, die 1130 mal in den Karten steht -- weil dort schon 580
Vorkommen stimmten.

Hier steht darum die KANTE im Mittelpunkt: links die Kachel mit ihrer Seite,
rechts alle Gegenkacheln, die nicht dazu passen, mit ihrer Haeufigkeit. Eine
Aenderung links wirkt auf alle rechts zugleich; eine Aenderung rechts nur auf
die eine.

Sortiert ist nach den Vorkommen, die an der Kante haengen und nicht stimmen --
die folgenreichste Kante zuerst.

Violett umrandet heisst ZERRISSEN: die Partner aus den Originalkarten
verlangen an diesem Abschnitt beides. Dort ist keine Festlegung richtig -- was
das eine Paar heilt, reisst das andere auf. Gemessen sitzen alle Widersprueche
an solchen Stellen.

Bedienung:
    Klick auf ein Band          Fels -> Biom -> egal -> Fels
    Z / Umschalt+Z              zerrissene Abschnitte auf egal (Kante / alle)
    Pfeil links/rechts          zur vorigen/naechsten Kante
    Strg+Z zurueck, Strg+S speichern (geht auch von selbst)

One tile edge and every counter-tile that disagrees with it. An edge belongs to
all its neighbours at once, so the edge -- not the pair -- is the right unit to
work on.
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
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
if str(ROOT / "mapview") not in sys.path:
    sys.path.insert(0, str(ROOT / "mapview"))

ZIEL = ROOT / "mapview" / "cliff_kanten.json"
SEITEN = ("N", "O", "S", "W")
SEITENNAME = {"N": "Nord", "O": "Ost", "S": "Sued", "W": "West"}
GEGEN = {"N": "S", "O": "W", "S": "N", "W": "O"}
BIOM, FELS, EGAL = 0, 1, 2
NAME = {BIOM: "Biom", FELS: "Fels", EGAL: "egal"}
TON = {BIOM: QColor("#3a8ac9"), FELS: QColor("#c98a3a"),
       EGAL: QColor("#6f7a55")}
STREIT = QColor("#e04030")
ZERRISS = QColor("#c060e0")

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

# Ab wievielen Vorkommen die Gegenmeinung zaehlt, damit ein Abschnitt als
# ZERRISSEN gilt.
#
# Eine Kachelseite trifft in den 54 Karten viele Partner. Verlangt Partner A
# an Abschnitt i Fels und Partner B dort Biom, ist kein Wert richtig: was das
# eine Paar heilt, reisst das andere auf. Gemessen sitzen ALLE 11347
# Widersprueche an solchen Stellen -- kein einziger ist durch einen anderen
# Wert loesbar.
#
# Was es kostet, sie auf egal zu setzen (mud, 156 Kacheln, 2496 Abschnitte):
#
#   Schwelle   Abschnitte   Rest an Widerspruechen   erlaubte Paare
#   von Hand            0        11347   (100,0 %)           24,2 %
#         50          135         1134   ( 10,0 %)           29,8 %
#         20          232          454   (  4,0 %)           34,8 %
#         10          318          218   (  1,9 %)           39,4 %
#          1          843            0   (  0,0 %)           63,0 %
#   alles egal       2466            0   (  0,0 %)          100,0 %
#
# 10 ist der Punkt, an dem fast nichts mehr widerspricht und die Zuordnung
# noch deutlich mehr als ein Drittel der Paare ablehnt. Alles auf egal zu
# setzen kostet dagegen die ganze Aussage.
#
# A section is TORN when the stock maps use it both ways; no single value can
# be right there. Every measured contradiction sits at such a section.
ZERRISS_SCHWELLE = 10

ZG = 9          # Zoom der grossen Kachel links
ZK = 3          # Zoom der Gegenkacheln -- sie stehen jetzt zu
                # neunt, also kleiner
BAND = 20


def _passt(x, y):
    return x == y or x == EGAL or y == EGAL


class Links(QWidget):
    """Die Kachel mit ihrer Seite -- eine Aenderung wirkt auf alle."""

    def __init__(self, f):
        super().__init__()
        self.f = f
        self.setFixedSize(32 * ZG + BAND + 4, 32 * ZG + BAND + 4)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _felder(self):
        k = self.f.kante_jetzt()
        if not k:
            return []
        kachel, seite, _v, _g = k
        n = self.f.abschnitte
        gross = 32 * ZG
        aus = []
        if seite in ("N", "S"):
            breit = gross // n
            y = 0 if seite == "N" else gross + 4
            for i in range(n):
                aus.append((QRect(i * breit, y, breit, BAND), kachel, seite, i))
        else:
            hoch = gross // n
            x = 0 if seite == "W" else gross + 4
            for i in range(n):
                aus.append((QRect(x, i * hoch, BAND, hoch), kachel, seite, i))
        return aus

    def paintEvent(self, e):                             # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e22"))
        k = self.f.kante_jetzt()
        if not k:
            p.end()
            return
        kachel, seite, _v, _g = k
        gross = 32 * ZG
        vx = BAND if seite == "W" else 0
        vy = BAND if seite == "N" else 0
        p.drawPixmap(vx, vy, self.f.pixmap(kachel).scaled(gross, gross))
        p.setPen(QPen(QColor("#e8e8ee"), 2))
        p.drawRect(vx, vy, gross, gross)
        for rect, _kc, s, i in self._felder():
            r2 = rect.translated(vx if seite in ("N", "S") else 0,
                                 vy if seite in ("O", "W") else 0)
            wert = self.f.muster[kachel][s][i]
            p.fillRect(r2, TON[wert])
            # Violett heisst: die Partner verlangen hier beides. Kein Wert
            # ist richtig, nur egal haelt beide aus.
            zer = self.f.ist_zerrissen(kachel, s, i)
            p.setPen(QPen(ZERRISS if zer else QColor("#1e1e22"),
                          3 if zer else 1))
            p.drawRect(r2.adjusted(1, 1, -1, -1) if zer else r2)
            p.setPen(QPen(QColor("#fff"), 1))
            p.drawText(r2, Qt.AlignmentFlag.AlignCenter, "BF?"[wert])
        p.end()

    def mousePressEvent(self, e: QMouseEvent):           # noqa: N802
        k = self.f.kante_jetzt()
        if not k:
            return
        _kc, seite, _v, _g = k
        gross = 32 * ZG
        vx = BAND if seite == "W" else 0
        vy = BAND if seite == "N" else 0
        for rect, kachel, s, i in self._felder():
            r2 = rect.translated(vx if seite in ("N", "S") else 0,
                                 vy if seite in ("O", "W") else 0)
            if r2.contains(e.position().toPoint()):
                self.f.umschalten(kachel, s, i)
                return


class Rechts(QWidget):
    """Alle Gegenkacheln, die nicht passen -- jede in einem Ring aus Nachbarn.

    Eine einzelne Kachel laesst sich bei 32 mal 32 schwer beurteilen: man sieht
    die Kante, aber nicht, in welcher Wand sie steckt. Darum steht jede
    Gegenkachel in einem 3x3. An der Nahtstelle sitzt die HAUPTkachel -- dort
    grenzen die beiden in den Originalkarten ja tatsaechlich aneinander --,
    ringsum die je haeufigsten Nachbarn.

    Das Band liegt an der Seite, um die es geht, also zwischen Hauptkachel und
    Gegenkachel.

    Each counter-tile inside a 3x3 ring: the MAIN tile sits at the seam
    position, the commonest neighbours fill the rest.
    """

    RINGE = {"N": (1, 0), "O": (2, 1), "S": (1, 2), "W": (0, 1),
             "NO": (2, 0), "SO": (2, 2), "SW": (0, 2), "NW": (0, 0)}

    def __init__(self, f):
        super().__init__()
        self.f = f
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(640)

    def _hoehe_zeile(self):
        return 3 * 32 * ZK + 18

    def _zeilen(self):
        """-> [(x, y, kachel, gegenseite, anzahl)] -- x,y ist die Ringecke."""
        k = self.f.kante_jetzt()
        if not k:
            return []
        _kc, seite, _v, gegner = k
        gegen = GEGEN[seite]
        h = self._hoehe_zeile()
        return [(10, 10 + j * h, b, gegen, n)
                for j, (b, n) in enumerate(gegner)]

    def _ring(self, x, y, b, gegen):
        """-> [(px, py, kachel, ist_mitte)] fuer die neun Felder."""
        g = 32 * ZK
        haupt = self.f.kante_jetzt()[0]
        aus = [(x + g, y + g, b, True)]
        for richtung, (cx, cy) in self.RINGE.items():
            # An der Nahtstelle steht die Hauptkachel selbst
            kachel = haupt if richtung == gegen \
                else self.f.haeufigster_nachbar(b, richtung)
            if kachel is not None:
                aus.append((x + cx * g, y + cy * g, kachel,
                            richtung == gegen))
        return aus

    def _band(self, x, y, gegen, i):
        """Das Rechteck des Abschnitts i -- auf der Naht zwischen den beiden."""
        g = 32 * ZK
        n = self.f.abschnitte
        mx, my = x + g, y + g          # Ecke der Mittelkachel
        if gegen in ("N", "S"):
            breit = g // n
            yy = my - BAND // 2 if gegen == "N" else my + g - BAND // 2
            return QRect(mx + i * breit, yy, breit, BAND // 2)
        tief = g // n
        xx = mx - BAND // 2 if gegen == "W" else mx + g - BAND // 2
        return QRect(xx, my + i * tief, BAND // 2, tief)

    def sizeHint(self):                                  # noqa: N802
        from PySide6.QtCore import QSize
        z = self._zeilen()
        return QSize(640, max(200, 20 + len(z) * self._hoehe_zeile()))

    def paintEvent(self, e):                             # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e22"))
        k = self.f.kante_jetzt()
        if not k:
            p.end()
            return
        kachel, seite, _v, _g = k
        g = 32 * ZK
        for x, y, b, gegen, anzahl in self._zeilen():
            for px, py, t, hervor in self._ring(x, y, b, gegen):
                p.drawPixmap(px, py, self.f.pixmap(t).scaled(g, g))
                if not hervor:
                    p.fillRect(px, py, g, g, QColor(20, 20, 24, 110))
            # Gegenkachel und Hauptkachel hell umranden
            p.setPen(QPen(QColor("#e8e8ee"), 2))
            p.drawRect(x + g, y + g, g, g)
            cx, cy = self.RINGE[gegen]
            p.drawRect(x + cx * g, y + cy * g, g, g)
            for i in range(self.f.abschnitte):
                wert = self.f.muster[b][gegen][i]
                streit = not _passt(self.f.muster[kachel][seite][i], wert)
                rect = self._band(x, y, gegen, i)
                p.fillRect(rect, STREIT if streit else TON[wert])
                p.setPen(QPen(QColor("#1e1e22"), 1))
                p.drawRect(rect)
                p.setPen(QPen(QColor("#fff"), 1))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "BF?"[wert])
            tx = x + 3 * g + 14
            p.setPen(QPen(QColor("#ddd"), 1))
            p.drawText(tx, y + 20,
                       f"{b} {SEITENNAME[gegen]}   {anzahl} mal in den Karten")
            ges, gut = self.f.wirkung(b, gegen)
            p.setPen(QPen(QColor("#999"), 1))
            p.drawText(tx, y + 40,
                       f"diese Kante: {ges} Vorkommen, stimmig {gut} "
                       f"({100*gut/ges if ges else 0:.0f} %)")
            p.setPen(QPen(QColor("#777"), 1))
            p.drawText(tx, y + 60, "hell umrandet: die beiden, um die es geht")
        p.end()

    def mousePressEvent(self, e: QMouseEvent):           # noqa: N802
        for x, y, b, gegen, _anzahl in self._zeilen():
            for i in range(self.f.abschnitte):
                if self._band(x, y, gegen, i).contains(
                        e.position().toPoint()):
                    self.f.umschalten(b, gegen, i)
                    return


class Fenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kante gegen alle")

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
        self.festgelegt = set(roh.get("festgelegt", []))

        self.rueckgaengig = []
        self.stelle = 0
        self.gehalten = None      # sauber gewordene Kante, weiter angezeigt
        self.mindest_abweichung = MINDEST_ABWEICHUNG
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
        self.links = Links(self)
        mitte.addWidget(self.links, 0, Qt.AlignmentFlag.AlignTop)
        self.rechts = Rechts(self)
        rolle = QScrollArea()
        rolle.setWidget(self.rechts)
        rolle.setWidgetResizable(True)
        mitte.addWidget(rolle, 1)

        fuss = QHBoxLayout()
        aussen.addLayout(fuss)
        for text, schritt in (("<< vorherige", -1), ("naechste >>", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=schritt: self._blaettern(s))
            fuss.addWidget(b)
        for text, n in (("nur grobe (3+)", 3), ("ab 2", 2), ("alle", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, n=n: self._schwere(n))
            fuss.addWidget(b)
        for text, alle in (("zerrissene -> egal (Z)", False),
                           ("ueberall (Umschalt+Z)", True)):
            b = QPushButton(text)
            b.clicked.connect(
                lambda _=False, a=alle: self.zerrissene_auf_egal(a))
            fuss.addWidget(b)
        self.stand = QLabel()
        self.stand.setStyleSheet("color: #bbb;")
        fuss.addWidget(self.stand)
        fuss.addStretch(1)
        b = QPushButton("speichern")
        b.clicked.connect(self._speichern)
        fuss.addWidget(b)

        for taste, schritt in (("Left", -1), ("Right", 1),
                               ("PgUp", -10), ("PgDown", 10)):
            QShortcut(QKeySequence(taste), self,
                      lambda s=schritt: self._blaettern(s))
        for taste, n in (("1", 1), ("2", 2), ("3", 3)):
            QShortcut(QKeySequence(taste), self,
                      lambda n=n: self._schwere(n))
        QShortcut(QKeySequence("Z"), self, self.zerrissene_auf_egal)
        QShortcut(QKeySequence("Shift+Z"), self,
                  lambda: self.zerrissene_auf_egal(True))
        QShortcut(QKeySequence("Ctrl+Z"), self, self._zurueck)
        QShortcut(QKeySequence("Ctrl+S"), self, self._speichern)

        self.resize(1180, 900)
        self._zeigen()

    # -- Daten ----------------------------------------------------------
    def _sammeln(self):
        """Alle Kanten mit Widerspruch, folgenreichste zuerst."""
        aus = []
        for kachel in sorted(self.muster):
            if not self.ct.ist_klippe(kachel) or kachel not in self.bearbeitet:
                continue
            for seite in SEITEN:
                gegner = []
                schlecht = 0
                for b, n in self.ct.nachbarn(kachel, seite).items():
                    if b not in self.muster or b not in self.bearbeitet:
                        continue
                    if n < MINDEST_VORKOMMEN:
                        continue
                    k = sum(1 for x, y in
                            zip(self.muster[kachel][seite],
                                self.muster[b][GEGEN[seite]])
                            if not _passt(x, y))
                    if k >= self.mindest_abweichung:
                        gegner.append((b, n))
                        schlecht += n
                if gegner:
                    gegner.sort(key=lambda t: -t[1])
                    aus.append((kachel, seite, schlecht, gegner))
        aus.sort(key=lambda t: -t[2])
        self.kanten = aus
        self.stelle = min(self.stelle, max(0, len(aus) - 1))

    def kante_jetzt(self):
        """Die gezeigte Kante -- auch wenn sie gerade sauber geworden ist.

        Eine saubere Kante steht nicht mehr in `self.kanten`. Sie trotzdem
        weiter zu zeigen ist der Punkt: man will sehen, was die eigene
        Aenderung bewirkt hat, statt wortlos woanders zu landen.
        """
        if self.gehalten:
            kachel, seite = self.gehalten
            return (kachel, seite, 0, [])
        return self.kanten[self.stelle] if self.kanten else None

    def wirkung(self, kachel, seite):
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

    def zerrissen(self, kachel, seite, i):
        """Was verlangen die Partner an dieser Stelle? -> (biom, fels).

        Beide Werte ueber der Schwelle heisst: die Originalkarten benutzen
        diesen Abschnitt in beide Richtungen, und dann ist keine Festlegung
        richtig.
        """
        b = f = 0
        for p, n in self.ct.nachbarn(kachel, seite).items():
            if p not in self.muster or p not in self.bearbeitet:
                continue
            w = self.muster[p][GEGEN[seite]][i]
            if w == BIOM:
                b += n
            elif w == FELS:
                f += n
        return b, f

    def ist_zerrissen(self, kachel, seite, i):
        return min(self.zerrissen(kachel, seite, i)) >= ZERRISS_SCHWELLE

    def haeufigster_nachbar(self, kachel, richtung):
        """Welche Kachel liegt in den Originalen dort am haeufigsten?

        Nur als Zusammenhang zum Ansehen -- damit aus einer Kachel ein Stueck
        Wand wird und man sieht, worin die Kante steckt.
        """
        z = self.ct.nachbarn(kachel, richtung)
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
        alt = self.muster[kachel][seite][i]
        self.rueckgaengig.append([(kachel, seite, i, alt)])
        self._setzen(kachel, seite, i,
                     {FELS: BIOM, BIOM: EGAL, EGAL: FELS}[alt])
        self.spar_uhr.start()
        self._auffrischen()

    def _setzen(self, kachel, seite, i, wert):
        self.muster[kachel][seite][i] = wert
        self.bearbeitet.add(kachel)
        self.festgelegt.add("%d:%s" % (kachel, seite))

    def zerrissene_auf_egal(self, alle=False):
        """Wo kein Wert richtig sein kann, keinen festlegen.

        Ohne `alle` nur an der gezeigten Kante -- man sieht sofort, was es
        bewirkt. Mit `alle` ueber die ganze Zuordnung; das ist eine Gruppe im
        Rueckgaengig, also mit einem Strg+Z wieder weg.
        """
        if alle:
            ziele = [(t, sei) for t in sorted(self.muster)
                     if self.ct.ist_klippe(t) and t in self.bearbeitet
                     for sei in SEITEN]
        else:
            k = self.kante_jetzt()
            if not k:
                return
            ziele = [(k[0], k[1])]
        gruppe = []
        for kachel, seite in ziele:
            for i in range(self.abschnitte):
                if self.muster[kachel][seite][i] == EGAL:
                    continue
                if self.ist_zerrissen(kachel, seite, i):
                    gruppe.append((kachel, seite, i,
                                   self.muster[kachel][seite][i]))
        for kachel, seite, i, _alt in gruppe:
            self._setzen(kachel, seite, i, EGAL)
        if gruppe:
            self.rueckgaengig.append(gruppe)
            self.spar_uhr.start()
        self._auffrischen()

    def _zurueck(self):
        if not self.rueckgaengig:
            return
        for kachel, seite, i, wert in reversed(self.rueckgaengig.pop()):
            self.muster[kachel][seite][i] = wert
        self.spar_uhr.start()
        self._auffrischen()

    def _auffrischen(self):
        """Neu sammeln, aber NIE von selbst weiterspringen.

        Die Liste sortiert sich nach jeder Aenderung neu, und wer dabei
        mitwandert, verliert die Stelle, an der er gerade arbeitet. Gewechselt
        wird nur mit den Pfeiltasten.

        Ist die Kante sauber geworden, faellt sie aus der Liste; die Ansicht
        bleibt trotzdem auf ihr stehen, bis von Hand geblaettert wird -- sonst
        sieht man das Ergebnis der eigenen Aenderung nie.

        Never advance on its own: the list re-sorts after every change, and
        following it loses the place one is working on.
        """
        k = self.kante_jetzt()
        merk = (k[0], k[1]) if k else None
        self._sammeln()
        if merk is None:
            self._zeigen()
            return
        for i, e in enumerate(self.kanten):
            if (e[0], e[1]) == merk:
                self.stelle = i
                self.gehalten = None
                self._zeigen()
                return
        # Sauber geworden: nicht mehr in der Liste, aber weiter anzeigen.
        self.gehalten = merk
        self._zeigen()

    def _schwere(self, n):
        """Ab wievielen abweichenden Abschnitten gezeigt wird."""
        self.mindest_abweichung = n
        self.gehalten = None
        self.stelle = 0
        self._sammeln()
        self._zeigen()

    def _blaettern(self, schritt):
        if self.spar_uhr.isActive():
            self._speichern()
        self.gehalten = None
        if self.kanten:
            self.stelle = (self.stelle + schritt) % len(self.kanten)
        self._zeigen()

    # -- Anzeige --------------------------------------------------------
    def _offen(self):
        """Offene Vorkommen, jede Naht EINMAL gezaehlt.

        Jeder Widerspruch steht zweimal in der Liste -- einmal als `a Sued an
        b`, einmal als `b Nord an a`. Die Kanten beide zu zeigen ist richtig,
        sie beide zu zaehlen nicht: gemessen ergab das 31700 statt der
        tatsaechlichen 15850.
        Each disagreement appears twice, once from either side; showing both
        edges is right, counting both is not.
        """
        gesehen = set()
        summe = 0
        for kachel, seite, _s, gegner in self.kanten:
            for b, n in gegner:
                schl = tuple(sorted(((kachel, seite), (b, GEGEN[seite]))))
                if schl in gesehen:
                    continue
                gesehen.add(schl)
                summe += n
        return summe

    def _kopf(self):
        k = self.kante_jetzt()
        offen = self._offen()
        if not k:
            self.kopf.setText("kein Widerspruch mehr")
            self.stand.setText("")
            return
        kachel, seite, schlecht, gegner = k
        if self.gehalten:
            ges, gut = self.wirkung(kachel, seite)
            self.kopf.setText(
                f"{kachel} {SEITENNAME[seite]}   —   SAUBER, keine "
                f"Gegenkachel widerspricht mehr   |   Kante {ges} Vorkommen, "
                f"stimmig {gut}   |   Pfeiltaste fuer die naechste")
            self.stand.setText(
                f"noch {len(self.kanten)} Kanten   |   {self._offen()} "
                f"Vorkommen   |   ab {self.mindest_abweichung} Abschnitten")
            return
        ges, gut = self.wirkung(kachel, seite)
        fest = "  (festgelegt)" if f"{kachel}:{seite}" in self.festgelegt \
            else ""
        zer = sum(1 for i in range(self.abschnitte)
                  if self.ist_zerrissen(kachel, seite, i))
        hinweis = (f"   |   {zer} von {self.abschnitte} Abschnitten ZERRISSEN "
                   f"(dort ist kein Wert richtig, Z setzt sie auf egal)"
                   if zer else "")
        self.kopf.setText(
            f"{kachel} {SEITENNAME[seite]}{fest}   —   {len(gegner)} "
            f"Gegenkacheln passen nicht, zusammen {schlecht} Vorkommen   |   "
            f"Kante {ges} Vorkommen, stimmig {gut} "
            f"({100*gut/ges if ges else 0:.0f} %){hinweis}")
        self.stand.setText(
            f"Kante {self.stelle + 1} von {len(self.kanten)}   |   offen: "
            f"{offen} Vorkommen   |   gezeigt ab {self.mindest_abweichung} "
            f"abweichenden Abschnitten")

    def _zeigen(self):
        self.links.update()
        self.rechts.updateGeometry()
        self.rechts.update()
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
