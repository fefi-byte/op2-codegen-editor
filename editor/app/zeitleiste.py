"""Zeitleiste der Zeit-Trigger, schwebend oben auf der Karte.

Zeigt alle Trigger mit Ausloeser "Zeit (Marks)" auf einer Achse. Gefuellte
Punkte: beim Missionsstart aktiv (absolute Zeit). Hohle Punkte: werden erst
von einem anderen Trigger gestartet -- ihre Zeit zaehlt ab diesem Moment,
die Position ist also nur ein Anhalt. Wiederholende Trigger zeigen ihre
weiteren Ausloesungen als feine Striche. Liegen Punkte dicht beieinander,
werden sie in Reihen gestapelt -- so fallen Haeufungen sofort auf.

Klick waehlt den Trigger, Doppelklick oeffnet ihn.

Timeline of time triggers, floating at the top of the map. Filled dots:
active at mission start (absolute time). Hollow dots: started by another
trigger, so their time counts from then. Repeating triggers show further
firings as faint ticks; close dots stack into rows.
"""
from __future__ import annotations

from PySide6.QtWidgets import QToolTip

from .common import *
from .style import TRIGGER_FARBEN

SEK_JE_MARK = 25            # wie der Marks-Hinweis im Bedingungsformular
_RAND = 14
_REIHE = 11
_STANDARD = QColor(137, 180, 250)
_SPAETER = QColor(250, 179, 135)


def _zeit_text(marks: int) -> str:
    s = int(marks) * SEK_JE_MARK
    h, rest = divmod(s, 3600)
    m, _s = divmod(rest, 60)
    return f"{h}h {m:02d}min" if h else f"{m}min"


class Zeitleiste(QWidget):
    gewaehlt = Signal(int)
    geoeffnet = Signal(int)

    def __init__(self, parent, window):
        super().__init__(parent)
        self._w = window
        self._punkte: list[tuple[QPointF, int, str]] = []   # Position, Index, Tooltip
        self._ende = 100
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("zeitleiste")
        self.setStyleSheet("QWidget#zeitleiste { background: rgba(17,17,27,225);"
                           " border: 1px solid #313244; border-radius: 6px; }")
        self.setFixedHeight(58)

    # ------------------------------------------------------------------
    @staticmethod
    def _marks(t) -> int | None:
        try:
            return int(t.marks)
        except (TypeError, ValueError):
            return None        # Ausdruck (z.B. abhaengig vom Schwierigkeitsgrad)

    def eintraege(self):
        """[(index, trigger, marks)] aller Zeit-Trigger mit festem Wert."""
        out = []
        for i, t in enumerate(self._w.triggers):
            if t.condition != "time":
                continue
            m = self._marks(t)
            if m is not None:
                out.append((i, t, m))
        return out

    def auffrischen(self):
        e = self.eintraege()
        self.setVisible(bool(e) and getattr(self, "_an", True))
        hoechst = max([m for _i, _t, m in e] or [100])
        # Etwas Luft rechts und eine runde Endmarke.
        roh = hoechst * 1.15
        schritt = 10 ** max(1, len(str(int(roh))) - 1)
        self._ende = max(100, int((roh + schritt - 1) // schritt * schritt))
        self.update()

    def setze_an(self, an: bool):
        self._an = an
        self.auffrischen()

    def _x(self, marks: float) -> float:
        breite = self.width() - 2 * _RAND
        return _RAND + breite * min(1.0, marks / max(1, self._ende))

    # ------------------------------------------------------------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        achse_y = self.height() - 16
        p.setPen(QPen(QColor(88, 91, 112), 1))
        p.drawLine(QPointF(_RAND, achse_y), QPointF(self.width() - _RAND, achse_y))
        # Skala: 5 Abschnitte / scale
        f = p.font()
        f.setPointSizeF(7.5)
        p.setFont(f)
        for k in range(6):
            m = self._ende * k / 5
            x = self._x(m)
            p.setPen(QPen(QColor(88, 91, 112), 1))
            p.drawLine(QPointF(x, achse_y), QPointF(x, achse_y + 3))
            p.setPen(QColor(127, 132, 156))
            text = f"M {int(m)}"
            p.drawText(QRectF(x - 30, achse_y + 3, 60, 12), Qt.AlignHCenter, text)

        # Punkte in Reihen stapeln, wenn sie sich ueberdecken.
        belegt: list[list[float]] = [[], [], []]
        self._punkte = []
        for i, t, m in sorted(self.eintraege(), key=lambda e: e[2]):
            x = self._x(m)
            reihe = 0
            while reihe < len(belegt) - 1 and any(abs(x - bx) < 9 for bx in belegt[reihe]):
                reihe += 1
            belegt[reihe].append(x)
            y = achse_y - 8 - reihe * _REIHE
            farbe = QColor(TRIGGER_FARBEN.get(getattr(t, "color", "") or "", "")) \
                if getattr(t, "color", "") else (_STANDARD if t.enabled_at_start else _SPAETER)
            # Wiederholungen als feine Striche / repeats as faint ticks
            if not t.one_shot and m > 0:
                p.setPen(QPen(QColor(farbe.red(), farbe.green(), farbe.blue(), 110), 1))
                n = m * 2
                while n <= self._ende:
                    xx = self._x(n)
                    p.drawLine(QPointF(xx, achse_y - 3), QPointF(xx, achse_y + 1))
                    n += m
            p.setPen(QPen(farbe, 2))
            p.setBrush(QBrush(farbe) if t.enabled_at_start else Qt.NoBrush)
            p.drawEllipse(QPointF(x, y), 4, 4)
            tipp = f"{t.name}\nM {m}  (≈ {_zeit_text(m)})"
            if not t.enabled_at_start:
                tipp += "\n" + tr("timeline.relative")
            if not t.one_shot:
                tipp += "\n" + tr("timeline.repeats", m=m)
            self._punkte.append((QPointF(x, y), i, tipp))
        if self._w.triggers and not self._punkte:
            p.setPen(QColor(127, 132, 156))
            p.drawText(self.rect(), Qt.AlignCenter, tr("timeline.empty"))
        p.end()

    def _treffer(self, pos) -> list[tuple[QPointF, int, str]]:
        return [e for e in self._punkte
                if abs(e[0].x() - pos.x()) <= 6 and abs(e[0].y() - pos.y()) <= 6]

    def mouseMoveEvent(self, e):
        t = self._treffer(e.position())
        if t:
            QToolTip.showText(e.globalPosition().toPoint(), "\n\n".join(x[2] for x in t), self)
            self.setCursor(Qt.PointingHandCursor)
        else:
            QToolTip.hideText()
            self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, e):
        t = self._treffer(e.position())
        if t:
            self.gewaehlt.emit(t[0][1])

    def mouseDoubleClickEvent(self, e):
        t = self._treffer(e.position())
        if t:
            self.geoeffnet.emit(t[0][1])
