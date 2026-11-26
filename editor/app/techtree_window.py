"""Forschungsbaum-Editor: Tech-Datei als Baum von links nach rechts.

Laeuft als dritter Modus im Hauptfenster (Mission | Map Editor | Tech Tree).
Links steht alles zum gewaehlten Thema und ist direkt editierbar (Nummer,
Name, Kategorie, Kosten je Kolonie, Labor, Wissenschaftler, Voraussetzungen,
Texte mit Restzeichen, Werteaenderungen als Tabelle). Rechts der Baum: jede
Spalte eine Stufe (laengste Kette von Voraussetzungen), Linien von der
Voraussetzung zum Thema. Das kleine + an einer Karte legt ein neues Thema an,
das diese Karte voraussetzt.

Datei lesen/schreiben/pruefen: editor/techtree_model.py (ohne Qt).

Tech tree editor: the tech file as a left-to-right tree; the left panel edits
the selected topic, the + on a card adds a topic that requires it.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QFileDialog, QFormLayout,
    QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QStyledItemDelegate, QTableWidget, QToolBar, QVBoxLayout, QWidget,
)

from . import common as _common  # noqa: F401  (Suchpfad fuer techtree_model / sys.path)
import techtree_model as tm
from . import i18n
from . import style as S

tr = i18n.tr

CARD_W, CARD_H = 236, 58
COL_GAP, ROW_GAP = 70, 14

CATEGORY_COLORS = {
    0: S.OVERLAY, 1: S.LAVENDER, 2: S.SUBTEXT, 3: S.YELLOW, 4: S.BLUE, 5: S.GREEN,
    6: S.PEACH, 7: S.RED, 8: S.SKY, 9: S.PINK, 10: S.TEAL, 11: S.MAUVE, 12: S.SKY,
}
AMBER = S.PEACH        # Voraussetzungen der Auswahl / prerequisites of the selection
FOLLOW = S.BLUE        # Folgethemen / followers


def cost_text(c: int | None) -> str:
    if c is None:
        return "–"
    if c < 0:
        return tr("techtree.cost_locked")
    if c == 0:
        return tr("techtree.cost_free")
    return str(c)


# --- Baum / tree ------------------------------------------------------------

class _PlusItem(QGraphicsRectItem):
    """Das kleine + rechts an einer Karte."""

    def __init__(self, card: "TechCard"):
        super().__init__(0, 0, 18, 18, card)
        self.card = card
        self.setPos(CARD_W - 9, CARD_H / 2 - 9)
        self.setBrush(QColor(S.SURFACE1))
        self.setPen(QPen(QColor(S.GREEN), 1.4))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("techtree.plus_tip"))
        self.setAcceptHoverEvents(True)
        self.setZValue(3)

    def paint(self, p, opt, w=None):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(self.pen()); p.setBrush(self.brush())
        p.drawRoundedRect(self.rect(), 9, 9)
        p.setPen(QPen(QColor(S.GREEN), 2))
        c = self.rect().center()
        p.drawLine(QPointF(c.x() - 4, c.y()), QPointF(c.x() + 4, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 4), QPointF(c.x(), c.y() + 4))

    def hoverEnterEvent(self, e):
        self.setBrush(QColor(S.SURFACE2)); self.update()

    def hoverLeaveEvent(self, e):
        self.setBrush(QColor(S.SURFACE1)); self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.card.view.plusClicked.emit(self.card.tech.id)
            e.accept()


class TechCard(QGraphicsRectItem):
    def __init__(self, tech: tm.Tech, view: "TreeView"):
        super().__init__(0, 0, CARD_W, CARD_H)
        self.tech = tech
        self.view = view
        self.state = "normal"      # normal | selected | ancestor | follower | dim
        self.problem = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(2)
        self.plus = _PlusItem(self)

    def paint(self, p, opt, w=None):
        t, v = self.tech, self.view
        p.setRenderHint(QPainter.Antialiasing)
        fac = v.faction
        locked = fac != "both" and (t.cost_for(fac) or 0) < 0
        bg = QColor(S.SURFACE0)
        border = QColor(S.BORDER)
        if self.state == "selected":
            border = QColor(S.YELLOW); bg = QColor(S.SURFACE1)
        elif self.state == "ancestor":
            border = QColor(AMBER)
        elif self.state == "follower":
            border = QColor(FOLLOW)
        if self.problem:
            border = QColor(S.RED) if self.state == "normal" else border
        if self.state == "dim" or locked:
            p.setOpacity(0.35)
        p.setPen(QPen(border, 2 if self.state != "normal" or self.problem else 1))
        p.setBrush(bg)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        # Kategorie-Streifen links / category stripe
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(CATEGORY_COLORS.get(t.category, S.OVERLAY)))
        p.drawRoundedRect(QRectF(2, 2, 5, CARD_H - 4), 2, 2)
        # Name
        f = QFont(p.font()); f.setPointSizeF(9.5); f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(S.TEXT))
        fm = QFontMetrics(f)
        p.drawText(QRectF(13, 5, CARD_W - 32, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(t.name, Qt.ElideRight, CARD_W - 32))
        # Zeile 2: Nummer, Kosten / line 2: id, costs
        f2 = QFont(p.font()); f2.setPointSizeF(8.2); f2.setBold(False)
        p.setFont(f2)
        p.setPen(QColor(S.SUBTEXT))
        p.drawText(QRectF(13, 23, 48, 15), Qt.AlignLeft | Qt.AlignVCenter, f"{t.id:05d}")
        x = 60
        for name, col in (("eden", S.SKY), ("plymouth", S.RED)):
            if fac not in ("both", name):
                continue
            c = t.cost_for(name)
            txt = ("E " if name == "eden" else "P ") + cost_text(c)
            p.setPen(QColor(S.GREEN if c == 0 else col if (c or 0) > 0 else S.OVERLAY))
            p.drawText(QRectF(x, 23, 70, 15), Qt.AlignLeft | Qt.AlignVCenter, txt)
            x += QFontMetrics(f2).horizontalAdvance(txt) + 10
        # Zeile 3: Kategorie, Labor, Upgrades
        p.setPen(QColor(S.OVERLAY))
        bits = [tr(f"techtree.cat_{t.category}") if t.category in tm.CATEGORIES else "?"]
        if t.lab:
            bits.append(tr("techtree.lab_short", n=t.lab))
        if t.props:
            bits.append(tr("techtree.upgrades_short", n=len(t.props)))
        line3 = " · ".join(bits)
        p.drawText(QRectF(13, 38, CARD_W - 32, 15), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f2).elidedText(line3, Qt.ElideRight, CARD_W - 32))
        p.setOpacity(1.0)

    def hoverEnterEvent(self, e):
        self.view.hover(self.tech.id)

    def hoverLeaveEvent(self, e):
        self.view.hover(None)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.view.techClicked.emit(self.tech.id)
            e.accept()
        else:
            super().mousePressEvent(e)


class TreeView(QGraphicsView):
    techClicked = Signal(int)
    plusClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QColor(S.CRUST))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.tf: tm.TechFile | None = None
        self.faction = "both"
        self.show_markers = False
        self.search = ""
        self.selected: int | None = None
        self._hover: int | None = None
        self.cards: dict[int, TechCard] = {}
        self.edges: list[tuple[int, int, QGraphicsPathItem]] = []
        self.problem_ids: set[int] = set()

    def visible_techs(self) -> list[tm.Tech]:
        if not self.tf:
            return []
        return [t for t in self.tf.techs
                if self.show_markers or not t.is_free_marker() or t.id == self.selected]

    def rebuild(self) -> None:
        sc = self.scene()
        sc.clear()
        self.cards.clear(); self.edges.clear()
        techs = self.visible_techs()
        pos = tm.layout(techs)
        for t in techs:
            c, r = pos[t.id]
            card = TechCard(t, self)
            card.setPos(c * (CARD_W + COL_GAP), r * (CARD_H + ROW_GAP))
            sc.addItem(card)
            self.cards[t.id] = card
        for t in techs:
            for r in t.requires:
                if r in self.cards:
                    item = QGraphicsPathItem()
                    item.setZValue(1)
                    sc.addItem(item)
                    self.edges.append((r, t.id, item))
        self._paths()
        self.restyle()
        sc.setSceneRect(sc.itemsBoundingRect().adjusted(-40, -40, 80, 80))

    def _paths(self) -> None:
        for a, b, item in self.edges:
            pa = self.cards[a].pos() + QPointF(CARD_W, CARD_H / 2)
            pb = self.cards[b].pos() + QPointF(0, CARD_H / 2)
            path = QPainterPath(pa)
            dx = max(30.0, (pb.x() - pa.x()) * 0.5)
            path.cubicTo(pa + QPointF(dx, 0), pb - QPointF(dx, 0), pb)
            item.setPath(path)

    def restyle(self) -> None:
        focus = self._hover if self._hover is not None else self.selected
        anc = self.tf.ancestors(focus) if (self.tf and focus is not None) else set()
        des = self.tf.descendants(focus) if (self.tf and focus is not None) else set()
        q = self.search.strip().lower()
        for tid, card in self.cards.items():
            t = card.tech
            match = (not q or q in t.name.lower() or q in f"{t.id:05d}"
                     or any(q in p.unit.lower() for p in t.props))
            if tid == self.selected:
                card.state = "selected"
            elif tid in anc:
                card.state = "ancestor"
            elif tid in des:
                card.state = "follower"
            elif not match:
                card.state = "dim"
            else:
                card.state = "normal"
            card.problem = tid in self.problem_ids
            card.update()
        for a, b, item in self.edges:
            if focus is not None and (b == focus or b in anc) and (a in anc or a == focus):
                pen = QPen(QColor(AMBER), 2.2)
            elif focus is not None and (a == focus or a in des) and b in des:
                pen = QPen(QColor(FOLLOW), 2.2)
            else:
                pen = QPen(QColor(S.SURFACE2), 1.2)
            item.setPen(pen)

    def refresh_card(self, tid: int) -> None:
        if tid in self.cards:
            self.cards[tid].update()

    def hover(self, tid: int | None) -> None:
        self._hover = tid
        self.restyle()

    def center_on(self, tid: int) -> None:
        if tid in self.cards:
            self.ensureVisible(self.cards[tid], 80, 60)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
        else:
            super().wheelEvent(e)


# --- Bearbeitungsfeld / editor panel ----------------------------------------

def prop_label(kind: str | None, prop: str) -> str:
    """Bezeichnung einer Eigenschaft fuer diese Art Einheit (Scout: Sichtweite,
    Waffe: Reichweite ...). Label of a property for this kind of unit."""
    for name, key in tm.props_for(kind):
        if name == prop and key:
            return tr(f"techtree.pl_{key}")
    return tr(f"techtree.prop_{prop}") if prop in tm.PROPERTY_NAMES else prop


def prop_hint(kind: str | None, prop: str) -> str:
    for name, key in tm.props_for(kind):
        if name == prop and key:
            return tr(f"techtree.ph_{key}")
    return tr(f"techtree.hint_{prop}") if prop in tm.PROPERTY_NAMES else ""


class _PropDelegate(QStyledItemDelegate):
    """Aufgeklappte Liste: Bezeichnung und Name in der Datei (Sight_Range ...).
    Dropdown shows the label and the file name of the property."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        code = index.data(Qt.UserRole)
        if code in tm.PROPERTY_NAMES:
            option.text = f"{option.text}  ·  {code}"


class _UnitDelegate(QStyledItemDelegate):
    """Aufgeklappte Einheitenliste: Name, dahinter klein der Code."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        code = index.data(Qt.UserRole)
        if code and tm.UNIT_NAMES.get(code):
            option.text = f"{option.text}   ·  {code}"


class _UpgradeTable(QTableWidget):
    """Werte-Tabelle: Wert, Grundwert und Loeschknopf fest rechts; Einheit und
    Eigenschaft teilen sich den Rest (je mit Mindestbreite, sonst waagerecht
    scrollen). Fixed columns on the right; unit and property share the rest."""
    UNIT_MIN, PROP_MIN = 130, 150

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_unit_column()

    def fit_unit_column(self) -> None:
        fest = sum(self.columnWidth(c) for c in range(2, self.columnCount()))
        frei = self.viewport().width() - fest
        prop = max(self.PROP_MIN, int(frei * 0.48))
        self.setColumnWidth(1, prop)
        self.setColumnWidth(0, max(self.UNIT_MIN, frei - prop))


class _LabPreview(QWidget):
    """Ungefaehre Vorschau des Labor-Textfelds: so breit, dass die Linie aus
    39 Unterstrichen es gerade fuellt, umgebrochen nur an Leerzeichen. Die
    Schrift des Spiels ist eine andere, darum ist der Umbruch nur annaehernd.
    Approximate preview of the lab's text box."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 4)
        lay.setSpacing(2)
        self.box = QLabel()
        self.box.setTextFormat(Qt.PlainText)
        self.box.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # Das globale Stylesheet setzt die Schriftgroesse fuer alle Widgets;
        # darum hier im eigenen Stylesheet, und mit derselben Groesse messen.
        # The global stylesheet sets the font size; set it here too and measure alike.
        f = QFont(self.box.font()); f.setPointSizeF(9)
        fm = QFontMetrics(f)
        self._fm = fm
        self._breite = fm.horizontalAdvance(tm.RULE) + 2
        # Breite + Innenabstand (2 x 6) + Rahmen (2 x 2) + etwas Luft
        self.box.setFixedWidth(self._breite + 2 * 6 + 2 * 2 + 4)
        self.box.setStyleSheet(
            f"background: {S.CRUST}; color: {S.GREEN}; border: 2px solid {S.SURFACE2};"
            " padding: 4px 6px; font-size: 9pt;")
        self.info = QLabel(""); self.info.setProperty("secondary", "true")
        lay.addWidget(self.box)
        lay.addWidget(self.info)

    def show_text(self, text: str) -> None:
        zeilen = tm.wrap_text(text, lambda z: self._fm.horizontalAdvance(z) <= self._breite)
        self.box.setText("\n".join(zeilen) if zeilen else " ")
        self.info.setText(tr("techtree.preview_lines", n=len(zeilen)))


class _Counter(QLabel):
    """'noch 712 von 800 Zeichen' unter einem Textfeld."""

    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.setProperty("secondary", "true")

    def show_len(self, n: int) -> None:
        left = self.limit - n
        self.setText(tr("techtree.chars_left", left=left, max=self.limit))
        self.setStyleSheet(f"color: {S.RED if left < 0 else S.YELLOW if left < self.limit * 0.05 else S.OVERLAY};")


class TechForm(QWidget):
    changed = Signal(int)          # Thema geaendert (Inhalt)
    structureChanged = Signal()    # Voraussetzungen/Nummer: Baum neu anordnen
    selectRequested = Signal(int)
    deleteRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tf: tm.TechFile | None = None
        self.tech: tm.Tech | None = None
        self.sheets: dict = {}
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self.head = QLabel(tr("techtree.nothing_selected"))
        f = self.head.font(); f.setPointSizeF(f.pointSizeF() + 3); f.setBold(True)
        self.head.setFont(f)
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.problems = QLabel("")
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet(f"color: {S.RED};")
        lay.addWidget(self.problems)

        self.body = QWidget()
        b = QVBoxLayout(self.body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(10)
        lay.addWidget(self.body, 1)

        # Grunddaten / basics
        g = QGroupBox(tr("techtree.grp_basics"))
        form = QFormLayout(g)
        self.id_spin = QSpinBox(); self.id_spin.setRange(1000, 99999)
        self.id_spin.setToolTip(tr("techtree.id_tip"))
        self.id_spin.editingFinished.connect(self._id_done)
        form.addRow(tr("techtree.lbl_id"), self.id_spin)
        self.name_edit = QLineEdit(); self.name_edit.setMaxLength(tm.MAX_NAME)
        self.name_edit.textChanged.connect(self._name_changed)
        self.name_count = _Counter(tm.MAX_NAME)
        nb = QVBoxLayout(); nb.setSpacing(1); nb.addWidget(self.name_edit); nb.addWidget(self.name_count)
        form.addRow(tr("techtree.lbl_name"), nb)
        self.cat_combo = QComboBox()
        for c in tm.CATEGORIES:
            self.cat_combo.addItem(f"{c} · {tr(f'techtree.cat_{c}')}", c)
        self.cat_combo.currentIndexChanged.connect(self._cat_changed)
        form.addRow(tr("techtree.lbl_category"), self.cat_combo)
        self.lab_combo = QComboBox()
        self.lab_combo.addItem(tr("techtree.lab_none"), None)
        for n in tm.LABS:
            self.lab_combo.addItem(tr(f"techtree.lab_{n}"), n)
        self.lab_combo.currentIndexChanged.connect(self._lab_changed)
        form.addRow(tr("techtree.lbl_lab"), self.lab_combo)
        self.sci_spin = QSpinBox(); self.sci_spin.setRange(0, tm.SCIENTISTS_RANGE[1])
        self.sci_spin.setSpecialValueText(tr("techtree.none"))
        self.sci_spin.setToolTip(tr("techtree.sci_tip"))
        self.sci_spin.valueChanged.connect(self._sci_changed)
        form.addRow(tr("techtree.lbl_scientists"), self.sci_spin)
        b.addWidget(g)

        # Fraktionen und Kosten / factions and costs
        g = QGroupBox(tr("techtree.grp_factions"))
        grid = QGridLayout(g)
        self.fac_check: dict[str, QCheckBox] = {}
        self.fac_cost: dict[str, QSpinBox] = {}
        for row, fac in enumerate(("eden", "plymouth")):
            cb = QCheckBox(tr(f"techtree.fac_{fac}"))
            cb.setToolTip(tr("techtree.fac_tip"))
            sp = QSpinBox(); sp.setRange(0, 999999); sp.setSingleStep(100)
            sp.setSpecialValueText(tr("techtree.cost_free_long"))
            sp.setToolTip(tr("techtree.cost_tip"))
            cb.toggled.connect(lambda on, f=fac: self._fac_changed(f))
            sp.valueChanged.connect(lambda _v, f=fac: self._fac_changed(f))
            grid.addWidget(cb, row, 0)
            grid.addWidget(sp, row, 1)
            self.fac_check[fac] = cb
            self.fac_cost[fac] = sp
        self.same_cost = QCheckBox(tr("techtree.same_cost"))
        self.same_cost.setToolTip(tr("techtree.same_cost_tip"))
        self.same_cost.toggled.connect(self._same_changed)
        grid.addWidget(self.same_cost, 2, 0, 1, 2)
        b.addWidget(g)

        # Voraussetzungen / prerequisites
        g = QGroupBox(tr("techtree.grp_requires"))
        v = QVBoxLayout(g)
        self.req_list = QListWidget()
        self.req_list.setMaximumHeight(120)
        self.req_list.itemDoubleClicked.connect(lambda it: self.selectRequested.emit(it.data(Qt.UserRole)))
        v.addWidget(self.req_list)
        row = QHBoxLayout()
        self.req_combo = QComboBox(); self.req_combo.setEditable(True)
        self.req_combo.setInsertPolicy(QComboBox.NoInsert)
        self.req_combo.lineEdit().setPlaceholderText(tr("techtree.req_placeholder"))
        comp = self.req_combo.completer()
        comp.setFilterMode(Qt.MatchContains); comp.setCompletionMode(QCompleter.PopupCompletion)
        self.req_add = QPushButton(tr("techtree.req_add")); self.req_add.clicked.connect(self._req_add)
        self.req_del = QPushButton(tr("techtree.req_remove")); self.req_del.clicked.connect(self._req_remove)
        row.addWidget(self.req_combo, 1); row.addWidget(self.req_add); row.addWidget(self.req_del)
        v.addLayout(row)
        self.follow_label = QLabel(""); self.follow_label.setWordWrap(True)
        self.follow_label.setProperty("secondary", "true")
        self.follow_label.setTextFormat(Qt.RichText)
        self.follow_label.linkActivated.connect(lambda s: self.selectRequested.emit(int(s)))
        v.addWidget(self.follow_label)
        b.addWidget(g)

        # Texte / texts
        g = QGroupBox(tr("techtree.grp_texts"))
        v = QVBoxLayout(g)
        self.texts: dict[str, tuple[QPlainTextEdit, _Counter]] = {}
        self.previews: dict[str, _LabPreview] = {}
        for fld, h in (("description", 110), ("teaser", 110), ("improve_desc", 44)):
            kopf = QHBoxLayout()
            kopf.addWidget(QLabel(tr(f"techtree.lbl_{fld}")), 1)
            ed = QPlainTextEdit(); ed.setFixedHeight(h)
            ed.setToolTip(tr(f"techtree.tip_{fld}"))
            cnt = _Counter(tm.MAX_TEXT)
            if fld != "improve_desc":
                # Nur Beschreibung und TEASER stehen im Labor-Feld mit Linie.
                linie = QPushButton(tr("techtree.rule_insert"))
                linie.setToolTip(tr("techtree.rule_tip"))
                linie.clicked.connect(lambda _=False, f=fld: self._insert_rule(f))
                vor = QPushButton(tr("techtree.preview"))
                vor.setCheckable(True)
                vor.setToolTip(tr("techtree.preview_tip"))
                kopf.addWidget(linie); kopf.addWidget(vor)
                pv = _LabPreview()
                pv.setVisible(False)
                vor.toggled.connect(pv.setVisible)
                self.previews[fld] = pv
            v.addLayout(kopf)
            ed.textChanged.connect(lambda f=fld: self._text_changed(f))
            v.addWidget(ed); v.addWidget(cnt)
            if fld in self.previews:
                v.addWidget(self.previews[fld])
            self.texts[fld] = (ed, cnt)
        b.addWidget(g)

        # Werteaenderungen / upgrades
        g = QGroupBox(tr("techtree.grp_upgrades"))
        v = QVBoxLayout(g)
        self.table = _UpgradeTable(0, 5)
        self.table.setHorizontalHeaderLabels([
            tr("techtree.col_unit"), tr("techtree.col_prop"), tr("techtree.col_value"),
            tr("techtree.col_base"), ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        fm = QFontMetrics(self.table.font())
        breite_wert = max(72, fm.horizontalAdvance(tr("techtree.col_value")) + 18)
        breite_grund = max(72, fm.horizontalAdvance(tr("techtree.col_base")) + 18)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        for c, w in ((2, breite_wert), (3, breite_grund), (4, 34)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed); self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(190)
        self.table.currentCellChanged.connect(lambda r, *_: self._prop_hint(r))
        v.addWidget(self.table)
        row = QHBoxLayout()
        self.prop_add = QPushButton(tr("techtree.prop_add")); self.prop_add.clicked.connect(self._prop_add)
        self.prop_count = QLabel(""); self.prop_count.setProperty("secondary", "true")
        row.addWidget(self.prop_add); row.addStretch(1); row.addWidget(self.prop_count)
        v.addLayout(row)
        self.prop_hint = QLabel(""); self.prop_hint.setWordWrap(True)
        self.prop_hint.setProperty("secondary", "true")
        v.addWidget(self.prop_hint)
        self.extra_label = QLabel(""); self.extra_label.setWordWrap(True)
        self.extra_label.setProperty("secondary", "true")
        v.addWidget(self.extra_label)
        b.addWidget(g)

        self.del_btn = QPushButton(tr("techtree.delete_tech"))
        self.del_btn.clicked.connect(lambda: self.tech and self.deleteRequested.emit(self.tech.id))
        b.addWidget(self.del_btn)
        b.addStretch(1)
        self.body.setEnabled(False)

    # -- Laden / load --

    def set_file(self, tf: tm.TechFile, sheets: dict) -> None:
        self.tf = tf
        self.sheets = sheets
        self.show_tech(None)

    def show_tech(self, tech: tm.Tech | None) -> None:
        self.tech = tech
        self._loading = True
        try:
            self.body.setEnabled(tech is not None)
            if tech is None:
                self.head.setText(tr("techtree.nothing_selected"))
                self.problems.setText("")
                self.req_list.clear(); self.table.setRowCount(0)
                return
            t = tech
            self._head()
            self.id_spin.setValue(t.id)
            self.name_edit.setText(t.name)
            self.name_count.show_len(len(t.name))
            self.cat_combo.setCurrentIndex(max(0, self.cat_combo.findData(t.category)))
            self.lab_combo.setCurrentIndex(max(0, self.lab_combo.findData(t.lab)))
            self.sci_spin.setValue(t.max_scientists or 0)
            for fac in ("eden", "plymouth"):
                c = t.cost_for(fac)
                self.fac_check[fac].setChecked(c is None or c >= 0)
                self.fac_cost[fac].setValue(max(0, c or 0))
                self.fac_cost[fac].setEnabled(c is None or c >= 0)
            self.same_cost.setChecked(t.same_cost)
            self._same_enable()
            for fld, (ed, cnt) in self.texts.items():
                ed.setPlainText(getattr(t, fld))
                cnt.show_len(len(getattr(t, fld)))
            self._fill_requires()
            self._fill_props()
            extra = [x for x in t.extra_lines]
            self.extra_label.setText(tr("techtree.extra_lines", lines="\n".join(extra)) if extra else "")
        finally:
            self._loading = False

    def _head(self) -> None:
        t = self.tech
        self.head.setText(f"{t.id:05d} · {t.name}")

    def show_problems(self, probs: list[str]) -> None:
        self.problems.setText("\n".join("• " + p for p in probs))

    def _fill_requires(self) -> None:
        t, tf = self.tech, self.tf
        by = tf.by_id()
        self.req_list.clear()
        for r in t.requires:
            o = by.get(r)
            it = QListWidgetItem(f"{r:05d}  {o.name if o else tr('techtree.missing')}")
            it.setData(Qt.UserRole, r)
            if o is None:
                it.setForeground(QColor(S.RED))
            self.req_list.addItem(it)
        # Auswahl fuer neue Voraussetzungen: nicht sich selbst, keine Nachfolger (Zyklus).
        bad = tf.descendants(t.id) | {t.id} | set(t.requires)
        self.req_combo.blockSignals(True)
        self.req_combo.clear()
        for o in sorted(tf.techs, key=lambda x: x.id):
            if o.id not in bad:
                self.req_combo.addItem(f"{o.id:05d}  {o.name}", o.id)
        self.req_combo.setCurrentIndex(-1)
        self.req_combo.blockSignals(False)
        fol = tf.followers(t.id)
        if fol:
            links = ", ".join(f'<a href="{o.id}" style="color:{S.BLUE}">{o.id:05d} {o.name}</a>' for o in fol)
            self.follow_label.setText(tr("techtree.followers", links=links))
        else:
            self.follow_label.setText(tr("techtree.no_followers"))

    def _fill_props(self) -> None:
        t = self.tech
        self.table.setRowCount(0)
        for p in t.props:
            self._add_row(p)
        self._prop_counts()
        self._prop_hint(self.table.currentRow())

    def _unit_codes(self) -> list[str]:
        codes = set(self.sheets) | {p.unit for x in self.tf.techs for p in x.props}
        return sorted(codes)

    def _fill_unit_combo(self, combo: QComboBox, current: str) -> None:
        """Auswahlliste der Einheiten, nach Art gruppiert (Ueberschriften nicht
        waehlbar). Ein Code aus der Datei, den keine Regel-Tabelle kennt, steht
        unter "Sonstige" mit Warnzeichen.
        Unit list grouped by kind; headers are not selectable."""
        model = combo.model()
        groups: dict[str | None, list[str]] = {}
        for code in self._unit_codes():
            kind = tm.unit_kind(self.sheets, code)
            if code in tm.EFFECT_CODES:
                kind = "effect"
            groups.setdefault(kind, []).append(code)
        if current and current not in self._unit_codes():
            groups.setdefault(None, []).append(current)
        for kind in (*tm.KINDS, "effect", None):
            codes = groups.get(kind)
            if not codes:
                continue
            combo.addItem(tr(f"techtree.kinds_{kind}" if kind else "techtree.kinds_other"))
            head = model.item(combo.count() - 1)
            head.setEnabled(False)
            f = head.font(); f.setBold(True); head.setFont(f)
            for code in sorted(codes, key=lambda c: (tm.unit_label(c).lower(), c)):
                text = tm.unit_label(code)
                if kind is None:
                    text = "⚠ " + text
                combo.addItem(text, code)
                combo.setItemData(combo.count() - 1, code, Qt.ToolTipRole)
        i = combo.findData(current)
        combo.setCurrentIndex(i if i >= 0 else 1)
        combo.setToolTip(current)

    def _add_row(self, p: tm.UnitProp) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        unit = QComboBox()
        unit.setMaxVisibleItems(20)
        unit.setItemDelegate(_UnitDelegate(unit))
        unit.view().setMinimumWidth(400)
        self._fill_unit_combo(unit, p.unit)
        prop = QComboBox()
        prop.setItemDelegate(_PropDelegate(prop))
        prop.view().setMinimumWidth(360)
        self._fill_prop_combo(prop, p.unit, p.prop)
        val = QSpinBox(); val.setRange(-1, 9999999); val.setValue(p.value)
        # Ohne Pfeile ueber das Stylesheet ("flach"), NICHT mit NoButtons:
        # das liess die Zahl unter dem Stylesheet verschwinden.
        val.setProperty("flach", "true")
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        base = QLabel(""); base.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        base.setContentsMargins(0, 0, 8, 0)
        base.setToolTip(tr("techtree.base_tip"))
        rm = QPushButton("✕"); rm.setFixedSize(28, 24); rm.setToolTip(tr("techtree.prop_remove"))
        rm.setStyleSheet("padding: 0px;")
        self.table.setCellWidget(r, 0, unit)
        self.table.setCellWidget(r, 1, prop)
        self.table.setCellWidget(r, 2, val)
        self.table.setCellWidget(r, 3, base)
        self.table.setCellWidget(r, 4, rm)
        unit.currentIndexChanged.connect(lambda *_, u=unit: self._unit_changed(u))
        prop.currentIndexChanged.connect(lambda *_: self._props_from_table())
        val.valueChanged.connect(lambda *_: self._props_from_table())
        rm.clicked.connect(lambda _=False, w=rm: self._prop_remove(w))
        self._row_extras(r)

    def _fill_prop_combo(self, combo: QComboBox, unit: str, current: str) -> None:
        """Nur die Eigenschaften, die zur Art der Einheit passen, mit deren
        Bezeichnung. Passt die bisherige nicht, bleibt sie mit Warnzeichen
        stehen (eine Datei kann das so enthalten).
        Only the properties fitting the unit's kind, under their label."""
        kind = tm.unit_kind(self.sheets, unit)
        combo.blockSignals(True)
        combo.clear()
        for k, (name, _key) in enumerate(tm.props_for(kind)):
            combo.addItem(prop_label(kind, name), name)
            combo.setItemData(k, prop_hint(kind, name), Qt.ToolTipRole)
        i = combo.findData(current)
        if i < 0 and current:
            combo.addItem(f"⚠ {current}", current)
            i = combo.count() - 1
            combo.setItemData(i, tr("techtree.prop_not_fitting"), Qt.ToolTipRole)
        combo.setCurrentIndex(max(0, i))
        combo.setToolTip(combo.itemData(combo.currentIndex(), Qt.ToolTipRole) or "")
        combo.blockSignals(False)

    def _unit_changed(self, unit_combo: QComboBox) -> None:
        unit_combo.setToolTip(unit_combo.currentData() or "")
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 0) is unit_combo:
                code, prop, _v = self._row_values(r)
                self._fill_prop_combo(self.table.cellWidget(r, 1), code, prop)
                break
        self._props_from_table()

    def _row_values(self, r: int) -> tuple[str, str, int]:
        code = self.table.cellWidget(r, 0).currentData() or ""
        prop = self.table.cellWidget(r, 1).currentData()
        val = self.table.cellWidget(r, 2).value()
        return code, prop, val

    def _row_extras(self, r: int) -> None:
        code, prop, _v = self._row_values(r)
        bv = tm.base_value(self.sheets, code, prop)
        self.table.cellWidget(r, 3).setText(bv if bv is not None else "–")
        spin = self.table.cellWidget(r, 2)
        spin.blockSignals(True)
        if prop == "Armor":
            spin.setRange(*tm.ARMOR_RANGE)
        elif prop == "Improved":
            spin.setRange(0, 1)
        else:
            spin.setRange(-1, 9999999)
        spin.blockSignals(False)

    def _props_from_table(self) -> None:
        if self._loading or not self.tech:
            return
        props = []
        for r in range(self.table.rowCount()):
            code, prop, val = self._row_values(r)
            self._row_extras(r)
            props.append(tm.UnitProp(code, prop, self.table.cellWidget(r, 2).value()))
        self.tech.props = props
        self._prop_counts()
        self._prop_hint(self.table.currentRow())
        self.changed.emit(self.tech.id)

    def _prop_counts(self) -> None:
        n = self.tech.upgrade_count() if self.tech else 0
        self.prop_count.setText(tr("techtree.prop_count", n=n, max=tm.MAX_UPGRADES))
        self.prop_add.setEnabled(n < tm.MAX_UPGRADES)

    def _prop_hint(self, r: int) -> None:
        if not self.tech or r < 0 or r >= self.table.rowCount():
            self.prop_hint.setText(tr("techtree.prop_hint_none"))
            return
        code, prop, _v = self._row_values(r)
        kind = tm.unit_kind(self.sheets, code)
        text = prop_hint(kind, prop)
        if not tm.prop_fits(kind, prop):
            text = tr("techtree.prop_not_fitting") + " " + text
        self.prop_hint.setText(text)

    def _prop_add(self) -> None:
        if not self.tech:
            return
        last = self.tech.props[-1] if self.tech.props else None
        unit = last.unit if last else "CON_TRUCK"
        first = tm.props_for(tm.unit_kind(self.sheets, unit))[0][0]
        p = tm.UnitProp(unit, first, 0)
        bv = tm.base_value(self.sheets, p.unit, p.prop)
        if bv and bv.lstrip("-").isdigit():
            p.value = int(bv)
        self.tech.props.append(p)
        self._loading = True
        self._add_row(p)
        self._loading = False
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self._prop_counts()
        self.changed.emit(self.tech.id)

    def _prop_remove(self, btn) -> None:
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 4) is btn:
                self.table.removeRow(r)
                break
        self._props_from_table()

    # -- Aenderungen / edits --

    def _name_changed(self, s: str) -> None:
        if '"' in s:
            self.name_edit.setText(s.replace('"', "'")); return
        self.name_count.show_len(len(s))
        if self._loading or not self.tech:
            return
        self.tech.name = s
        self._head()
        self.changed.emit(self.tech.id)

    def _cat_changed(self, _i) -> None:
        if self._loading or not self.tech:
            return
        self.tech.category = self.cat_combo.currentData()
        self.changed.emit(self.tech.id)

    def _lab_changed(self, _i) -> None:
        if self._loading or not self.tech:
            return
        self.tech.lab = self.lab_combo.currentData()
        self.changed.emit(self.tech.id)

    def _sci_changed(self, v) -> None:
        if self._loading or not self.tech:
            return
        self.tech.max_scientists = v or None
        self.changed.emit(self.tech.id)

    def _fac_changed(self, fac: str) -> None:
        on = self.fac_check[fac].isChecked()
        self.fac_cost[fac].setEnabled(on)
        if self._loading or not self.tech:
            return
        val = self.fac_cost[fac].value() if on else -1
        if self.same_cost.isChecked() and self.same_cost.isEnabled():
            # Gemeinsame Kosten: die andere Kolonie zieht mit.
            other = "plymouth" if fac == "eden" else "eden"
            self._loading = True
            self.fac_check[other].setChecked(on)
            self.fac_cost[other].setValue(self.fac_cost[fac].value())
            self.fac_cost[other].setEnabled(on)
            self._loading = False
            self.tech.eden_cost = self.tech.plymouth_cost = val
        elif fac == "eden":
            self.tech.eden_cost = val
        else:
            self.tech.plymouth_cost = val
        self._same_enable()
        self.changed.emit(self.tech.id)

    def _same_enable(self) -> None:
        t = self.tech
        equal = t is not None and t.eden_cost == t.plymouth_cost
        self.same_cost.setEnabled(equal or self.same_cost.isChecked())
        if not equal and t is not None:
            self._loading_guard(lambda: self.same_cost.setChecked(False))
            t.same_cost = False

    def _loading_guard(self, fn) -> None:
        old = self._loading
        self._loading = True
        try:
            fn()
        finally:
            self._loading = old

    def _same_changed(self, on: bool) -> None:
        if self._loading or not self.tech:
            return
        self.tech.same_cost = on
        if on:
            self.tech.plymouth_cost = self.tech.eden_cost
            self.show_tech(self.tech)
        self.changed.emit(self.tech.id)

    def _insert_rule(self, fld: str) -> None:
        ed, _cnt = self.texts[fld]
        neu, pos = tm.insert_rule(ed.toPlainText(), ed.textCursor().position())
        if len(neu) > tm.MAX_TEXT:
            QMessageBox.information(self, tr("techtree.title"), tr("techtree.rule_too_long"))
            return
        ed.setPlainText(neu)
        cur = ed.textCursor(); cur.setPosition(pos); ed.setTextCursor(cur)
        ed.setFocus()

    def _text_changed(self, fld: str) -> None:
        ed, cnt = self.texts[fld]
        s = ed.toPlainText()
        cnt.show_len(len(s))
        if fld in self.previews:
            self.previews[fld].show_text(s)
        if self._loading or not self.tech:
            return
        # Das Spiel kennt keine Zeilenumbrueche und keine " im Text.
        clean = s.replace("\r", " ").replace("\n", " ").replace('"', "'")
        setattr(self.tech, fld, clean)
        self.changed.emit(self.tech.id)

    def _id_done(self) -> None:
        if self._loading or not self.tech:
            return
        new = self.id_spin.value()
        if new == self.tech.id:
            return
        if self.tf.get(new) is not None:
            QMessageBox.warning(self, tr("techtree.title"), tr("techtree.id_taken", id=f"{new:05d}"))
            self._loading_guard(lambda: self.id_spin.setValue(self.tech.id))
            return
        self.tf.change_id(self.tech, new)
        self._head()
        self.structureChanged.emit()
        self.changed.emit(new)

    def _req_add(self) -> None:
        if not self.tech:
            return
        tid = self.req_combo.currentData()
        if tid is None:
            txt = self.req_combo.currentText().strip()[:5]
            tid = int(txt) if txt.isdigit() else None
        if tid is None or tid in self.tech.requires or tid == self.tech.id:
            return
        if tid in self.tf.descendants(self.tech.id):
            QMessageBox.warning(self, tr("techtree.title"), tr("techtree.req_cycle"))
            return
        self.tech.requires.append(tid)
        self._fill_requires()
        self.structureChanged.emit()
        self.changed.emit(self.tech.id)

    def _req_remove(self) -> None:
        it = self.req_list.currentItem()
        if not self.tech or it is None:
            return
        self.tech.requires.remove(it.data(Qt.UserRole))
        self._fill_requires()
        self.structureChanged.emit()
        self.changed.emit(self.tech.id)


# --- Seite im Hauptfenster / page in the main window -----------------------

class TechTreePage(QWidget):
    """Der Forschungsbaum als Seite im Hauptfenster (Modus "Tech Tree").

    `host` ist das Editorfenster (optional): Missionsordner, Techtree-Name,
    Statusleiste. The tech tree as a page in the main window."""

    def __init__(self, host=None, path: Path | None = None, techs_dir: Path | None = None,
                 sheets_dir: Path | None = None):
        super().__init__(host)
        self.host = host
        self.techs_dir = Path(techs_dir) if techs_dir else None
        self.sheets = tm.read_sheets(sheets_dir) if sheets_dir else {}
        self.tf: tm.TechFile = tm.new_file()

        self.form = TechForm()
        self.form.set_file(self.tf, self.sheets)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self.form)
        scroll.setMinimumWidth(470)
        self.tree = TreeView()
        self.problem_list = QListWidget()
        self.problem_list.itemClicked.connect(self._problem_clicked)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.tree); right.addWidget(self.problem_list)
        right.setSizes([760, 140])
        split = QSplitter(Qt.Horizontal)
        split.addWidget(scroll); split.addWidget(right)
        split.setSizes([580, 1020])
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._toolbar()
        self._lay.addWidget(split, 1)
        self.tree.techClicked.connect(self.select)
        self.tree.plusClicked.connect(self.add_after)
        self.form.changed.connect(self._changed)
        self.form.structureChanged.connect(self._structure)
        self.form.selectRequested.connect(self.select)
        self.form.deleteRequested.connect(self.delete_tech)
        self._check_timer = QTimer(self); self._check_timer.setSingleShot(True)
        self._check_timer.setInterval(250); self._check_timer.timeout.connect(self.check)
        if path:
            self.open_path(Path(path))
        else:
            self._set_file(self.tf)

    def _toolbar(self) -> None:
        tb = QToolBar(tr("techtree.title"), self); tb.setMovable(False)
        self._lay.addWidget(tb)
        self.file_label = QLabel("")
        f = self.file_label.font(); f.setBold(True); self.file_label.setFont(f)
        tb.addWidget(self.file_label)
        tb.addSeparator()

        def act(key, slot, shortcut=None):
            a = QAction(tr(f"techtree.{key}"), self); a.triggered.connect(slot)
            if shortcut:
                # Nur solange die Seite sichtbar ist (die Karte hat eigene Kuerzel).
                a.setShortcut(shortcut)
                a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
                self.addAction(a)
            tb.addAction(a); return a
        if self.host is not None:
            # Im Editor gehoert der Baum zum Projekt: Speichern = Projekt
            # speichern; eine andere Datei dient nur als Grundlage.
            # In the editor the tree belongs to the project.
            act("save_project", self.save, "Ctrl+S")
            act("import_file", self.import_dialog, "Ctrl+O")
        else:
            act("new_file", self.new_file)
            act("open", self.open_dialog, "Ctrl+O")
            act("save", self.save, "Ctrl+S")
            act("save_as", self.save_as, "Ctrl+Shift+S")
        tb.addSeparator()
        act("add_root", lambda: self.add_after(None), "Ctrl+N")
        tb.addSeparator()
        tb.addWidget(QLabel(" " + tr("techtree.view_faction") + " "))
        self.fac_combo = QComboBox()
        for k in ("both", "eden", "plymouth"):
            self.fac_combo.addItem(tr(f"techtree.view_{k}"), k)
        self.fac_combo.currentIndexChanged.connect(self._faction_view)
        tb.addWidget(self.fac_combo)
        self.marker_check = QCheckBox(tr("techtree.show_markers"))
        self.marker_check.setToolTip(tr("techtree.show_markers_tip"))
        self.marker_check.toggled.connect(self._markers)
        tb.addWidget(self.marker_check)
        self.search = QLineEdit(); self.search.setPlaceholderText(tr("techtree.search"))
        self.search.setClearButtonEnabled(True); self.search.setMaximumWidth(240)
        self.search.textChanged.connect(self._search)
        self.search.returnPressed.connect(self._search_jump)
        tb.addWidget(self.search)

    # -- Datei / file --

    def _set_file(self, tf: tm.TechFile) -> None:
        self.tf = tf
        self.tree.tf = tf
        self.tree.selected = None
        self.form.set_file(tf, self.sheets)
        self.tree.rebuild()
        self.check()
        self._title()
        if tf.load_problems:
            QMessageBox.warning(self, tr("techtree.title"),
                                tr("techtree.load_problems", n=len(tf.load_problems),
                                   lines="\n".join(tf.load_problems[:10])))

    def _title(self) -> None:
        name = self.tf.path.name if self.tf.path else tr("techtree.untitled")
        star = " *" if self.tf.changed() else ""
        self.file_label.setText(f" {name}{star} ")
        tip = str(self.tf.path) if self.tf.path else ""
        if self.host is not None and (self.tf.path is None or self._is_original(Path(self.tf.path))):
            tip = tr("techtree.from_original", path=tip)
        self.file_label.setToolTip(tip)

    def _status(self, msg: str) -> None:
        if self.host is not None and hasattr(self.host, "statusBar"):
            self.host.statusBar().showMessage(msg, 6000)

    def load_for_mission(self, path: Path | None) -> None:
        """Beim Wechsel in den Modus: die Tech-Datei der Mission laden, wenn
        eine andere offen ist und nichts ungespeichert ist."""
        if path is None or (self.tf.path and Path(self.tf.path) == Path(path)):
            return
        if self.tf.changed():
            return
        self.open_path(Path(path))

    def ask_discard(self) -> bool:
        return self._ask_discard()

    def write_to(self, path: Path) -> None:
        """Ohne Rueckfrage schreiben (das Projekt speichert hierueber).
        Write without asking; used by the project save."""
        self.tf.save(Path(path))
        self._title()

    def import_dialog(self) -> None:
        """Eine andere Tech-Datei als Grundlage uebernehmen; gespeichert wird
        sie mit dem Projekt unter dessen eigenem Namen.
        Take another tech file as the base; it is saved with the project."""
        if self.tf.changed() and QMessageBox.question(
                self, tr("techtree.title"), tr("techtree.import_confirm")) != QMessageBox.Yes:
            return
        start = str(self.techs_dir or "")
        fn, _ = QFileDialog.getOpenFileName(self, tr("techtree.import_file"), start,
                                            tr("techtree.file_filter"))
        if not fn:
            return
        try:
            tf = tm.load(Path(fn))
        except OSError as e:
            QMessageBox.warning(self, tr("techtree.title"), tr("techtree.open_failed", e=e))
            return
        ziel = self.tf.path if (self.tf.path and not self._is_original(Path(self.tf.path))) else None
        tf.path = ziel
        tf._removed = True        # gilt als geaendert, bis das Projekt gespeichert ist
        self._set_file(tf)
        self._status(tr("techtree.imported", name=Path(fn).name))

    def _ask_discard(self) -> bool:
        if not self.tf.changed():
            return True
        r = QMessageBox.question(self, tr("techtree.title"), tr("techtree.unsaved"),
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_file(self) -> None:
        if self._ask_discard():
            self._set_file(tm.new_file())

    def open_dialog(self) -> None:
        if not self._ask_discard():
            return
        start = str(self.tf.path.parent if self.tf.path else (self.techs_dir or ""))
        fn, _ = QFileDialog.getOpenFileName(self, tr("techtree.open"), start, tr("techtree.file_filter"))
        if fn:
            self.open_path(Path(fn))

    def open_path(self, path: Path) -> None:
        try:
            tf = tm.load(path)
        except OSError as e:
            QMessageBox.warning(self, tr("techtree.title"), tr("techtree.open_failed", e=e))
            return
        self._set_file(tf)

    def _is_original(self, path: Path) -> bool:
        if not self.techs_dir:
            return False
        try:
            return path.resolve().parent == self.techs_dir.resolve()
        except OSError:
            return False

    def save(self) -> bool:
        if self.host is not None and hasattr(self.host, "techtree_projekt_speichern"):
            return self.host.techtree_projekt_speichern()
        if not self.tf.path:
            return self.save_as()
        if self._is_original(self.tf.path):
            r = QMessageBox.warning(self, tr("techtree.title"),
                                    tr("techtree.overwrite_original", name=self.tf.path.name),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return self.save_as()
        return self._write(self.tf.path)

    def save_as(self) -> bool:
        start = self._mission_folder() or (self.tf.path.parent if self.tf.path else None)
        name = self.tf.path.name if self.tf.path else "MYTEK.TXT"
        fn, _ = QFileDialog.getSaveFileName(self, tr("techtree.save_as"),
                                            str((start or Path.cwd()) / name), tr("techtree.file_filter"))
        if not fn:
            return False
        return self._write(Path(fn))

    def _write(self, path: Path) -> bool:
        errors = [p for p in tm.validate(self.tf, {c: k for c, (k, _row) in self.sheets.items()} or None) if p.level == "error"]
        if errors:
            r = QMessageBox.warning(self, tr("techtree.title"), tr("techtree.save_with_errors", n=len(errors)),
                                    QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Save:
                return False
        try:
            self.tf.save(path)
        except OSError as e:
            QMessageBox.warning(self, tr("techtree.title"), tr("techtree.save_failed", e=e))
            return False
        self._title()
        self._status(tr("techtree.saved", path=path))
        return True

    def _mission_folder(self) -> Path | None:
        mf = getattr(self.host, "mission_folder", None) if self.host else None
        return Path(mf) if mf else None

    def use_for_mission(self) -> None:
        """Den Namen dieser Datei als TechtreeName der Mission eintragen."""
        if not self.host:
            return
        if not self.tf.path:
            if not self.save_as():
                return
        mf = self._mission_folder()
        if mf and self.tf.path.parent.resolve() != mf.resolve() and not self._is_original(self.tf.path):
            QMessageBox.information(self, tr("techtree.title"), tr("techtree.use_not_in_mission", folder=mf))
        self.host.tech_tree = self.tf.path.name
        if hasattr(self.host, "_refresh_overview"):
            self.host._refresh_overview()
        self._status(tr("techtree.used_for_mission", name=self.tf.path.name))

    # -- Auswahl und Bearbeiten / selection and editing --

    def select(self, tid: int | None) -> None:
        t = self.tf.get(tid) if tid is not None else None
        if t and t.is_free_marker() and not self.marker_check.isChecked() and t.id not in self.tree.cards:
            self.tree.selected = t.id
            self.tree.rebuild()
        self.tree.selected = t.id if t else None
        self.form.show_tech(t)
        self.tree.restyle()
        if t:
            self.tree.center_on(t.id)
        self._form_problems()

    def add_after(self, parent_id: int | None) -> None:
        parent = self.tf.get(parent_id) if parent_id is not None else None
        if len(self.tf.techs) >= tm.MAX_TECHS:
            QMessageBox.warning(self, tr("techtree.title"), tr("techtree.too_many", max=tm.MAX_TECHS))
            return
        near = (parent.id + 1) if parent else max([1000] + [t.id + 1 for t in self.tf.techs if t.id < 12000])
        t = tm.Tech(id=self.tf.free_id(near), name=tr("techtree.new_name"))
        if parent:
            t.requires = [parent.id]
            t.category = parent.category if parent.category else 4
            t.lab = parent.lab or 2
            t.max_scientists = parent.max_scientists or 10
            for fac in ("eden", "plymouth"):
                c = parent.cost_for(fac)
                setattr(t, f"{fac}_cost", (max(c or 0, 0) + 200) if (c is None or c >= 0) else -1)
            t.same_cost = t.eden_cost == t.plymouth_cost
        else:
            t.category, t.lab, t.max_scientists = 4, 2, 10
            t.eden_cost = t.plymouth_cost = 1000
            t.same_cost = True
        self.tf.add(t, after=parent)
        self.tree.rebuild()
        self.select(t.id)
        self.form.name_edit.setFocus(); self.form.name_edit.selectAll()
        self._changed(t.id)

    def delete_tech(self, tid: int) -> None:
        t = self.tf.get(tid)
        if not t:
            return
        fol = self.tf.followers(tid)
        msg = tr("techtree.delete_confirm", name=t.name, id=f"{t.id:05d}", n=len(fol))
        if QMessageBox.question(self, tr("techtree.title"), msg) != QMessageBox.Yes:
            return
        self.tf.remove(t)
        self.tree.rebuild()
        self.select(None)
        self._changed(None)

    def _changed(self, tid) -> None:
        if tid is not None:
            self.tree.refresh_card(tid)
        self._title()
        self._check_timer.start()

    def _structure(self) -> None:
        sel = self.tree.selected = self.form.tech.id if self.form.tech else None
        self.tree.rebuild()
        if sel is not None:
            self.tree.center_on(sel)

    # -- Ansicht / view --

    def _faction_view(self, _i) -> None:
        self.tree.faction = self.fac_combo.currentData()
        self.tree.restyle()

    def _markers(self, on: bool) -> None:
        self.tree.show_markers = on
        self.tree.rebuild()

    def _search(self, s: str) -> None:
        self.tree.search = s
        self.tree.restyle()

    def _search_jump(self) -> None:
        q = self.search.text().strip().lower()
        for t in self.tree.visible_techs():
            if q and (q in t.name.lower() or q in f"{t.id:05d}"):
                self.select(t.id)
                return

    # -- Pruefen / check --

    def problem_text(self, p: tm.Problem) -> str:
        args = dict(p.args)
        if "field" in args:
            args["field"] = tr(f"techtree.lbl_{args['field']}")
        if "faction" in args:
            args["faction"] = tr(f"techtree.fac_{args['faction']}")
        if "req" in args:
            args["req"] = f"{args['req']:05d}"
        if "unit" in args and tm.UNIT_NAMES.get(args["unit"]):
            args["unit"] = f"{tm.unit_label(args['unit'])} ({args['unit']})"
        if "kind" in args:
            args["kind"] = tr(f"techtree.kind_{args['kind']}") if args["kind"] else "?"
        return tr(f"techtree.v_{p.code}", **args)

    def check(self) -> None:
        probs = tm.validate(self.tf, {c: k for c, (k, _row) in self.sheets.items()} or None)
        self._probs = probs
        self.problem_list.clear()
        errs = sum(1 for p in probs if p.level == "error")
        head = QListWidgetItem(tr("techtree.check_summary", techs=len(self.tf.techs),
                                  errors=errs, warnings=len(probs) - errs))
        head.setForeground(QColor(S.RED if errs else S.GREEN))
        self.problem_list.addItem(head)
        by = self.tf.by_id()
        for p in probs:
            name = f"{p.tech:05d} {by[p.tech].name}" if p.tech in by else "–"
            it = QListWidgetItem(f"{'✖' if p.level == 'error' else '⚠'}  {name}: {self.problem_text(p)}")
            it.setForeground(QColor(S.RED if p.level == "error" else S.YELLOW))
            it.setData(Qt.UserRole, p.tech)
            self.problem_list.addItem(it)
        self.tree.problem_ids = {p.tech for p in probs if p.level == "error" and p.tech is not None}
        self.tree.restyle()
        self._form_problems()

    def _form_problems(self) -> None:
        t = self.form.tech
        probs = [self.problem_text(p) for p in getattr(self, "_probs", []) if t and p.tech == t.id]
        self.form.show_problems(probs)

    def _problem_clicked(self, it) -> None:
        tid = it.data(Qt.UserRole)
        if tid is not None:
            self.select(tid)
