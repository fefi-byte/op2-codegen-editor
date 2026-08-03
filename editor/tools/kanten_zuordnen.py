"""Kantenabschnitte von Hand zuordnen: Fels oder Biom.

Aufruf:  python editor/tools/kanten_zuordnen.py

Jede der 307 Klippenkacheln hat vier Kanten, jede Kante zerfaellt in vier
Abschnitte zu acht Pixeln. Fuer jeden Abschnitt wird gesagt, was dort liegt:

    Fels   die Klippe selbst
    Biom   das Gelaende der eigenen Familie

Mehr gibt es nicht zu waehlen. Es geht um den UEBERGANG in der Kachel, nicht
darum, was danebensteht -- und eine Klippenkachel kann nur das Biom tragen, in
dem sie steht. Zwei Kacheln passen aneinander, wenn ihre beruehrenden Muster
zusammengehen.

Warum von Hand: alles andere im Projekt zaehlt die 54 Originalkarten aus, und
die decken nur 3,17 % der moeglichen Kachelpaare ab. Ueber die uebrigen 97 %
kann keine Zaehlung etwas sagen -- ein Kantenmuster schon.

Bedienung:
    Klick auf einen Abschnitt      umschalten
    F / B                          alle Abschnitte der Kachel auf Fels / Biom
    Pfeil links/rechts             blaettern, Bild auf/ab zehnerweise
    Strg+Z                         letzte Aenderung zurueck
    Strg+S                         speichern (auch beim Schliessen)

Vorbelegt ist aus den Pixeln: der Abstand eines Abschnitts zur Grundkachel der
eigenen Familie trennt Fels von Biom zu 90,1 % (Fels im Median 15,6, Biom 0,0).
Die Vorbelegung ist ein Vorschlag, kein Befund -- deshalb dieses Werkzeug.

Manual edge-section assignment: each of the 307 cliff tiles has four edges of
four eight-pixel sections; each section is rock or biome. It is about the
transition inside the tile, not about what borders it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import (QColor, QImage, QKeySequence, QMouseEvent, QPainter,
                           QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox,
                               QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
if str(ROOT / "mapview") not in sys.path:
    sys.path.insert(0, str(ROOT / "mapview"))

ZIEL = ROOT / "mapview" / "cliff_kanten.json"
SEITEN = ("N", "O", "S", "W")
SEITENNAME = {"N": "Nord", "O": "Ost", "S": "Sued", "W": "West"}
# 0 = Biom, 1 = Fels, 2 = egal. "egal" passt zu beidem -- gebraucht, wo die
# Fels-Boden-Grenze mitten in einen Abschnitt faellt und zwei Kacheln sie
# verschieden runden. Gemessen weichen 963 von 1300 Widerspruechen in genau
# einem Abschnitt ab, meist aus genau diesem Grund.
# 0 = biome, 1 = rock, 2 = either; "either" matches both, needed where the
# boundary falls inside a section and two tiles round it differently.
BIOM, FELS, EGAL = 0, 1, 2
NAME = {BIOM: "Biom", FELS: "Fels", EGAL: "egal"}
TON = {BIOM: QColor("#3a8ac9"), FELS: QColor("#c98a3a"),
       EGAL: QColor("#6f7a55")}
Z = 12          # Zoom: ein Kachelpixel in Bildschirmpixeln
RAND = 26       # Breite des Abschnittsbandes


class Tafel(QWidget):
    """Die Kachel gross, mit den 16 Abschnitten als Baender aussen herum."""

    def __init__(self, fenster):
        super().__init__()
        self.f = fenster
        self.setFixedSize(32 * Z + 2 * RAND, 32 * Z + 2 * RAND)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _felder(self):
        """-> [(QRect, seite, abschnitt)] fuer alle 16 Baender."""
        n = self.f.abschnitte
        laenge = 32 * Z // n
        aus = []
        for a in range(n):
            aus.append((QRect(RAND + a * laenge, 0, laenge, RAND), "N", a))
            aus.append((QRect(RAND + 32 * Z, RAND + a * laenge, RAND, laenge),
                        "O", a))
            aus.append((QRect(RAND + a * laenge, RAND + 32 * Z, laenge, RAND),
                        "S", a))
            aus.append((QRect(0, RAND + a * laenge, RAND, laenge), "W", a))
        return aus

    def paintEvent(self, e):                             # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e22"))
        bild = self.f.bild_jetzt()
        if bild is not None:
            p.drawPixmap(RAND, RAND, bild.scaled(
                32 * Z, 32 * Z, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation))
        eintrag = self.f.eintrag_jetzt()
        for rect, seite, a in self._felder():
            wert = eintrag[seite][a]
            p.fillRect(rect, TON[wert])
            p.setPen(QPen(QColor("#1e1e22"), 1))
            p.drawRect(rect)
            if wert == EGAL:
                p.setPen(QPen(QColor("#e8e8ee"), 1))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
        p.setPen(QPen(QColor("#888"), 1))
        p.drawRect(RAND, RAND, 32 * Z, 32 * Z)
        p.end()

    def mousePressEvent(self, e: QMouseEvent):           # noqa: N802
        for rect, seite, a in self._felder():
            if rect.contains(e.position().toPoint()):
                self.f.umschalten(seite, a)
                return


class Fenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Klippenkanten: Fels oder Biom")

        d = np.load(ROOT / "mapview" / "cliff_pixels_model.npz")
        self.kacheln = [int(t) for t in d["kacheln"]]
        self.bilder = d["bilder"]
        self.vorbelegung = d["vorbelegung"]
        self.abschnitte = int(d["abschnitte"])
        try:
            import mapgen
            tm = mapgen.model()
            self.familie = {t: (tm.families[tm.family_of[t]]
                                if t < len(tm.family_of)
                                and tm.family_of[t] >= 0 else "?")
                            for t in self.kacheln}
        except Exception:                                # noqa: BLE001
            self.familie = {t: "?" for t in self.kacheln}

        # Nur was wirklich Klippe IST. Die 307 kamen daher, dass sie in den
        # Originalkarten mit einem Klippen-Zelltyp vorkommen -- darunter sind
        # aber reine Bodenkacheln, bei denen irgendwo eine Zelle falsch
        # ausgezeichnet ist. Gemessen haben genau 5 der 307 keinen einzigen
        # Fels-Abschnitt, und jede davon kommt in allen 54 Karten nur ein- bis
        # zweimal vor. Sie werden weggelassen.
        #
        # Only tiles that actually ARE cliff: five of the 307 have no rock
        # section at all and occur once or twice in all 54 maps -- plain ground
        # cells that carry a cliff cell type somewhere by mistake.
        echt = [i for i in range(len(self.kacheln))
                if bool(self.vorbelegung[i].any())]
        self.kacheln = [self.kacheln[i] for i in echt]
        self.bilder = self.bilder[echt]
        self.vorbelegung = self.vorbelegung[echt]

        # Die Klippenkacheln verteilen sich auf drei Familien. Beurteilt wird
        # je Familie, denn "Biom" heisst in jeder etwas anderes.
        self.alle_kacheln = list(self.kacheln)
        self.alle_bilder = self.bilder
        self.alle_vorbelegung = self.vorbelegung
        self.familien = sorted({self.familie[t] for t in self.alle_kacheln})
        self.familie_jetzt = self.familien[0] if self.familien else None

        self.daten = self._laden()
        # Gespeichert wird IMMER alles (auch die unberuehrte Vorbelegung),
        # damit die Datei fuer sich steht. Was von Hand angefasst wurde, steht
        # getrennt daneben -- sonst gaelte nach dem ersten Speichern alles als
        # bearbeitet und das Springen auf Unberuehrtes waere wertlos.
        self.geaendert = set(self._bearbeitet_gelesen)
        self.rueckgaengig = []
        self.stelle = 0

        # Nach jeder Aenderung selbst speichern. Von Hand zu speichern ist eine
        # Bedienung, die man vergisst, und bei 302 Kacheln waere ein Absturz
        # teuer. Kurz verzoegert, damit nicht jeder Klick die Datei schreibt.
        # Autosave shortly after each change: 302 tiles are too much work to
        # lose to a crash, and remembering to save is a chore.
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

        leiste = QHBoxLayout()
        aussen.addLayout(leiste)
        leiste.addWidget(QLabel("Familie:"))
        gruppe = QButtonGroup(self)
        for fam in self.familien:
            n = sum(1 for t in self.alle_kacheln if self.familie[t] == fam)
            b = QRadioButton(f"{fam} ({n})")
            b.setChecked(fam == self.familie_jetzt)
            b.toggled.connect(
                lambda an, fam=fam: an and self._familie_waehlen(fam))
            gruppe.addButton(b)
            leiste.addWidget(b)
        leiste.addStretch(1)

        mitte = QHBoxLayout()
        aussen.addLayout(mitte, 1)
        self.tafel = Tafel(self)
        mitte.addWidget(self.tafel, 0, Qt.AlignmentFlag.AlignTop)

        rechts = QVBoxLayout()
        mitte.addLayout(rechts, 1)
        self.hinweis = QLabel(
            "Klick auf ein Band schaltet um.\n"
            "Klick geht im Kreis: Fels -> Biom -> egal\n"
            "F / B / E setzt alles auf Fels / Biom / egal\n"
            "Pfeiltasten blaettern, Strg+Z nimmt zurueck.\n\n"
            "Orange = Fels, Blau = Biom, Gruen = egal.\n"
            "egal passt zu beidem.\n\n"
            "Wird von selbst gespeichert.")
        self.hinweis.setStyleSheet("color: #bbb;")
        rechts.addWidget(self.hinweis)
        self.muster = QLabel()
        self.muster.setStyleSheet("font-family: monospace; color: #ddd;")
        rechts.addWidget(self.muster)
        rechts.addStretch(1)

        fuss = QHBoxLayout()
        aussen.addLayout(fuss)
        for text, schritt in (("<< zurueck", -1), ("weiter >>", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=schritt: self._blaettern(s))
            fuss.addWidget(b)
        self.nur_unberuehrt = QCheckBox("nur unbearbeitete anspringen")
        fuss.addWidget(self.nur_unberuehrt)
        fuss.addStretch(1)
        b = QPushButton("speichern (Strg+S)")
        b.clicked.connect(self._speichern)
        fuss.addWidget(b)

        for taste, schritt in (("Left", -1), ("Right", 1),
                               ("PgUp", -10), ("PgDown", 10)):
            QShortcut(QKeySequence(taste), self,
                      lambda s=schritt: self._blaettern(s))
        QShortcut(QKeySequence("F"), self, lambda: self._alle(FELS))
        QShortcut(QKeySequence("B"), self, lambda: self._alle(BIOM))
        QShortcut(QKeySequence("E"), self, lambda: self._alle(EGAL))
        QShortcut(QKeySequence("Ctrl+Z"), self, self._zurueck)
        QShortcut(QKeySequence("Ctrl+S"), self, self._speichern)

        self.resize(900, 560)
        self._familie_waehlen(self.familie_jetzt)

    # -- Daten ----------------------------------------------------------
    def _laden(self) -> dict:
        """Gespeicherte Zuordnung lesen, Fremdformate stillschweigend fallen
        lassen.

        Eine aeltere Fassung dieses Werkzeugs schrieb je Seite ein WORT
        ("klippe", "biom") statt einer Liste. `list(map(bool, "klippe"))` ergibt
        sechs Wahrheitswerte -- die Kachel bekam dann sechs Abschnitte statt
        vier, und niemand sah, woher. Darum wird die Laenge geprueft.
        """
        self._bearbeitet_gelesen = []
        if not ZIEL.exists():
            return {}
        try:
            roh = json.loads(ZIEL.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            return {}
        self._bearbeitet_gelesen = [int(t) for t in roh.get("bearbeitet", [])]
        aus = {}
        for k, e in roh.get("kanten", {}).items():
            if not isinstance(e, dict) or set(e) != set(SEITEN):
                continue
            if any(not isinstance(v, list) or len(v) != self.abschnitte
                   for v in e.values()):
                continue
            aus[int(k)] = {s: [int(x) for x in e[s]] for s in SEITEN}
        return aus

    def eintrag_jetzt(self) -> dict:
        kachel = self.kacheln[self.stelle]
        if kachel not in self.daten:
            v = self.vorbelegung[self.stelle]
            self.daten[kachel] = {s: [FELS if x else BIOM for x in v[i]]
                                  for i, s in enumerate(SEITEN)}
        return self.daten[kachel]

    def bild_jetzt(self):
        b = self.bilder[self.stelle]
        h, w, _ = b.shape
        return QPixmap.fromImage(
            QImage(b.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888))

    def _speichern(self):
        for i, t in enumerate(self.alle_kacheln):
            if t not in self.daten:
                v = self.alle_vorbelegung[i]
                self.daten[t] = {s: [bool(x) for x in v[j]]
                                 for j, s in enumerate(SEITEN)}
        ZIEL.write_text(json.dumps({
            "hinweis": ("Von Hand: je Kante vier Abschnitte, true = Fels, "
                        "false = Biom der eigenen Familie."),
            "seiten": list(SEITEN),
            "abschnitte": self.abschnitte,
            "bearbeitet": sorted(self.geaendert),
            "kanten": {str(k): v for k, v in sorted(self.daten.items())},
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        self.spar_uhr.stop()
        self._kopf()

    def closeEvent(self, e):                             # noqa: N802
        self._speichern()
        super().closeEvent(e)

    # -- Bedienung ------------------------------------------------------
    def umschalten(self, seite: str, a: int):
        """Klick geht im Kreis: Fels -> Biom -> egal -> Fels."""
        e = self.eintrag_jetzt()
        self.rueckgaengig.append((self.stelle, seite, a, e[seite][a]))
        e[seite][a] = {FELS: BIOM, BIOM: EGAL, EGAL: FELS}[e[seite][a]]
        self.geaendert.add(self.kacheln[self.stelle])
        self._zeigen()
        self.spar_uhr.start()

    def _alle(self, wert: int):
        e = self.eintrag_jetzt()
        for s in SEITEN:
            for a in range(self.abschnitte):
                if e[s][a] != wert:
                    self.rueckgaengig.append((self.stelle, s, a, e[s][a]))
                    e[s][a] = wert
        self.geaendert.add(self.kacheln[self.stelle])
        self._zeigen()
        self.spar_uhr.start()

    def _zurueck(self):
        if not self.rueckgaengig:
            return
        stelle, seite, a, wert = self.rueckgaengig.pop()
        self.stelle = stelle
        self.eintrag_jetzt()[seite][a] = wert
        self._zeigen()
        self.spar_uhr.start()

    def _blaettern(self, schritt: int):
        if self.spar_uhr.isActive():
            self._speichern()
        n = len(self.kacheln)
        if abs(schritt) > 1 or not self.nur_unberuehrt.isChecked():
            self.stelle = (self.stelle + schritt) % n
        else:
            stelle = self.stelle
            for _ in range(n):
                stelle = (stelle + schritt) % n
                if self.kacheln[stelle] not in self.geaendert:
                    break
            self.stelle = stelle
        self._zeigen()

    def _familie_waehlen(self, fam):
        """Nur die Kacheln dieser Familie anzeigen."""
        self.familie_jetzt = fam
        stellen = [i for i, t in enumerate(self.alle_kacheln)
                   if fam is None or self.familie[t] == fam]
        if not stellen:
            return
        self.kacheln = [self.alle_kacheln[i] for i in stellen]
        self.bilder = self.alle_bilder[stellen]
        self.vorbelegung = self.alle_vorbelegung[stellen]
        self.stelle = 0
        self.rueckgaengig.clear()
        self._zeigen()

    # -- Anzeige --------------------------------------------------------
    def _kopf(self):
        kachel = self.kacheln[self.stelle]
        fertig = len(self.geaendert)
        in_fam = sum(1 for t in self.kacheln if t in self.geaendert)
        self.kopf.setText(
            f"Kachel {kachel}  ({self.familie.get(kachel, '?')})   "
            f"{self.stelle + 1} von {len(self.kacheln)}   |   "
            f"in dieser Familie bearbeitet: {in_fam}   "
            f"(insgesamt {fertig} von {len(self.alle_kacheln)})"
            + ("   -  ungespeichert" if self.spar_uhr.isActive()
               else "   -  gespeichert"))

    def _zeigen(self):
        e = self.eintrag_jetzt()
        self.muster.setText("\n".join(
            f"{SEITENNAME[s]:5s}  " + " ".join(NAME[v] for v in e[s])
            for s in SEITEN))
        self.tafel.update()
        self._kopf()


def main():
    app = QApplication(sys.argv)
    f = Fenster()
    f.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
