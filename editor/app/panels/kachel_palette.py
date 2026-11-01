"""Kachel-Palette des Map Editors: einzelne Kacheln und Kachelgruppen setzen.

Der Malpinsel leitet die Kacheln aus der Absicht ab ("hier Erde"). Manchmal
will man aber genau DIESEN Felsbrocken, DIESEN Krater oder eine bestimmte
Kante setzen. Dafuer zeigt die Palette alles, was die Karte mitbringt:

- Gruppen: die benannten Stempel aus der Karte (die Pinsel des
  Originaleditors, z.B. `mudrock1`, `sancrat3`), am Stueck gesetzt.
- Einzelkacheln: jede Kachel der Tilesets.

Gefiltert wird nach Boden ("Erde" zeigt alles, in dem Erde vorkommt -- auch
Uebergaenge zu Fels oder Sand) und nach Art (Felsen, Krater, Klippen ...).

Tile palette of the map editor: place single tiles and tile groups. The paint
brush derives tiles from intent; sometimes you want exactly THIS boulder or
crater. The palette shows everything the map provides -- the named groups
(the original editor's brushes) and every single tile -- filtered by ground
("Mud" shows everything containing mud, transitions included) and by kind.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QListView

from ..common import *

# Boeden in Anzeigereihenfolge; "sonst" sammelt Lava, Platzhalter usw.
# Grounds in display order; "sonst" collects lava, placeholders etc.
FAMILIEN = ("mud", "roc", "san", "veg", "sno", "sonst")

# Arten in Anzeigereihenfolge / kinds in display order
ARTEN = ("boden", "felsen", "krater", "risse", "klippe", "schutt",
         "bauwerk", "vulkan", "uebergang")

# Namensteil hinter dem Bodenpraefix -> Art. Die Gruppennamen der
# Originalkarten folgen einem festen Schema (mudrock1, sancratx3, rocwall2).
# Name part after the ground prefix -> kind; the stock names follow a scheme.
_ART_MUSTER = (
    (r"^(bas|pln)", "boden"),
    (r"^(crk|crac)", "risse"),
    (r"^mes", "klippe"),
    (r"^(rock|roc|rok)", "felsen"),
    (r"^crat", "krater"),
    (r"^(rub|wrk)", "schutt"),
    (r"^(wall|tube|doz|lavw|micw)", "bauwerk"),
    (r"^(volc|vent|zlav|burn)", "vulkan"),
    (r"^(to|tran)", "uebergang"),
)
_PRAEFIX = (("snow", "sno"), ("snw", "sno"), ("sno", "sno"),
            ("mud", "mud"), ("roc", "roc"), ("san", "san"))

SYMBOL = 56          # Kantenlaenge der Vorschaubilder / thumbnail size


@dataclass
class Stempel:
    """Was gesetzt wird: w x h Kacheln, zeilenweise. / What gets placed."""
    name: str
    breite: int
    hoehe: int
    kacheln: list[int]
    familien: set = field(default_factory=set)
    art: str = "boden"
    gruppe: bool = False
    haeufigkeit: float = 0.0

    def kachel(self, x: int, y: int) -> int:
        return self.kacheln[y * self.breite + x]


def _gruppe_einordnen(name: str) -> tuple[str, str]:
    """(Boden, Art) aus dem Gruppennamen. / (ground, kind) from the name."""
    klein = name.lower()
    fam, rest = "sonst", klein
    for praefix, f in _PRAEFIX:
        if klein.startswith(praefix):
            fam, rest = f, klein[len(praefix):]
            break
    if "lava" in klein:
        return fam, "vulkan"
    for muster, art in _ART_MUSTER:
        if re.match(muster, rest):
            return fam, art
    return fam, "boden"


def katalog(karte, tm) -> list[Stempel]:
    """Alle Gruppen und Einzelkacheln der Karte, eingeordnet.

    All groups and single tiles of the map, classified."""
    import celltypes as ct
    if karte is None:
        return []
    n = len(karte.tile_mappings)
    namen = tm.families if tm is not None else []
    # Uebergangskachel -> beide Boeden / transition tile -> both grounds
    paar_von: dict[int, tuple[str, str]] = {}
    if tm is not None:
        for (a, b), eintraege in tm.trans.items():
            for kachel, _mix in eintraege:
                paar_von[int(kachel)] = (a, b)
    leer = set()
    for i, m in enumerate(karte.tile_mappings):
        try:
            datei = karte.tileset_sources[m.tileset_index].filename.lower()
        except IndexError:
            datei = ""
        # well0000/blue: Platzhalter ohne Grafik / placeholder, no graphic
        if datei in ("well0000", "blue", ""):
            leer.add(i)

    def familien_von(kachel: int) -> set:
        out = set()
        if tm is not None and 0 <= kachel < len(tm.family_of):
            f = int(tm.family_of[kachel])
            if 0 <= f < len(namen) and namen[f] in FAMILIEN:
                out.add(namen[f])
        if kachel in paar_von:
            out.update(f for f in paar_von[kachel] if f in FAMILIEN)
        return out

    nutzung = tm.usage if tm is not None else {}
    stempel: list[Stempel] = []
    for g in karte.tile_groups:
        if g.width <= 0 or g.height <= 0 or len(g.mapping_indices) != g.width * g.height:
            continue
        if any(not (0 <= k < n) for k in g.mapping_indices):
            continue
        if all(k in leer for k in g.mapping_indices):
            continue
        fam, art = _gruppe_einordnen(g.name)
        fams = {fam}
        for k in g.mapping_indices:
            fams |= familien_von(int(k))
        if len(fams) > 1:
            fams.discard("sonst")
        stempel.append(Stempel(g.name, g.width, g.height, list(g.mapping_indices),
                               fams, art, gruppe=True))

    for i in range(n):
        if i in leer:
            continue
        fams = familien_von(i) or {"sonst"}
        zt = ct.default_cell_type(i, fallback=-1)
        if i in paar_von:
            art = "uebergang"
        elif zt is not None and zt >= 0 and ct.speed_class(zt) == ct.CLIFF:
            art = "klippe"
        elif tm is not None and i < len(tm.lava) and tm.lava[i]:
            art = "vulkan"
        elif zt in (ct.NORMAL_WALL, ct.MICROBE_WALL, ct.LAVA_WALL, ct.DOZED_AREA) \
                or (zt is not None and zt >= ct.TUBE_0):
            art = "bauwerk"
        elif zt == ct.RUBBLE:
            art = "schutt"
        elif zt == ct.IMPASSIBLE_2:
            art = "krater"
        elif zt == ct.IMPASSIBLE_1:
            art = "felsen"
        else:
            art = "boden"
        stempel.append(Stempel(f"#{i}", 1, 1, [i], fams, art,
                               haeufigkeit=float(nutzung.get(i, 0))))
    return stempel


class KachelPalette(QWidget):
    """Filter + Bildraster + Infokasten. Meldet die Auswahl per Signal.

    Filters + thumbnail grid + info box; reports the selection via signal."""
    auswahl_geaendert = Signal(object)          # Stempel oder None

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._katalog: list[Stempel] = []
        self._symbole: dict = {}
        self._familie = "mud"
        self._auswahl: Stempel | None = None
        self._karten_marke = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # Boden-Chips mit echter Kachel als Symbol / ground chips with a real tile
        kopf = QLabel(tr("tiles.lbl_ground"))
        kopf.setProperty("role", "section")
        lay.addWidget(kopf)
        chips = QGridLayout()
        chips.setSpacing(3)
        self._chips: dict[str, QPushButton] = {}
        self._chip_gruppe = QButtonGroup(self)
        self._chip_gruppe.setExclusive(True)
        for i, fam in enumerate(("alle",) + FAMILIEN):
            b = QPushButton(tr(f"tiles.fam_{fam}"))
            b.setCheckable(True)
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _=False, f=fam: self.set_familie(f))
            self._chip_gruppe.addButton(b)
            chips.addWidget(b, i // 4, i % 4)
            self._chips[fam] = b
        lay.addLayout(chips)

        zeile = QHBoxLayout()
        self.art = QComboBox()
        self.art.addItem(tr("tiles.art_alle"), "alle")
        for art in ARTEN:
            self.art.addItem(tr(f"tiles.art_{art}"), art)
        self.art.currentIndexChanged.connect(self._fuellen)
        zeile.addWidget(self.art, 1)
        self.sorte = QComboBox()
        self.sorte.addItem(tr("tiles.sorte_alle"), "alle")
        self.sorte.addItem(tr("tiles.sorte_gruppen"), "gruppen")
        self.sorte.addItem(tr("tiles.sorte_einzeln"), "einzeln")
        self.sorte.currentIndexChanged.connect(self._fuellen)
        zeile.addWidget(self.sorte, 1)
        lay.addLayout(zeile)

        self.suche = QLineEdit()
        self.suche.setPlaceholderText(tr("tiles.search"))
        self.suche.setClearButtonEnabled(True)
        self.suche.textChanged.connect(self._fuellen)
        lay.addWidget(self.suche)

        self.raster = QListWidget()
        self.raster.setViewMode(QListView.IconMode)
        self.raster.setResizeMode(QListView.Adjust)
        self.raster.setMovement(QListView.Static)
        self.raster.setUniformItemSizes(True)
        self.raster.setIconSize(QSize(SYMBOL, SYMBOL))
        self.raster.setGridSize(QSize(SYMBOL + 8, SYMBOL + 8))
        self.raster.setSpacing(2)
        self.raster.setMinimumHeight(260)
        self.raster.setStyleSheet(
            "QListWidget { background: #11111b; border: 1px solid #313244; border-radius: 6px; }"
            "QListWidget::item { border-radius: 4px; }"
            "QListWidget::item:selected { background: #45475a; border: 2px solid #f9e2af; }"
            "QListWidget::item:hover { background: #313244; }")
        self.raster.currentItemChanged.connect(self._gewaehlt)
        lay.addWidget(self.raster, 1)

        self.anzahl = QLabel("")
        self.anzahl.setProperty("secondary", "true")
        lay.addWidget(self.anzahl)

        # Infokasten der Auswahl / info box of the selection
        self.info_box = QFrame()
        self.info_box.setObjectName("kachelinfo")
        self.info_box.setStyleSheet(
            "QFrame#kachelinfo { background: #181825; border: 1px solid #313244;"
            " border-radius: 6px; }")
        il = QHBoxLayout(self.info_box)
        il.setContentsMargins(8, 6, 8, 6)
        self.info_bild = QLabel()
        self.info_bild.setFixedSize(96, 96)
        self.info_bild.setAlignment(Qt.AlignCenter)
        il.addWidget(self.info_bild)
        self.info_text = QLabel(tr("tiles.none"))
        self.info_text.setWordWrap(True)
        self.info_text.setTextFormat(Qt.RichText)
        il.addWidget(self.info_text, 1)
        lay.addWidget(self.info_box)

        hint = QLabel(tr("tiles.hint"))
        hint.setWordWrap(True)
        hint.setProperty("secondary", "true")
        lay.addWidget(hint)

        self._chips[self._familie].setChecked(True)

    # ------------------------------------------------------------------
    def laden(self) -> None:
        """Katalog zur aktuellen Karte aufbauen (Kacheln haengen an ihr)."""
        w = self._window
        karte = getattr(w, "map", None)
        marke = (id(karte), len(karte.tile_groups) if karte is not None else 0,
                 len(karte.tile_mappings) if karte is not None else 0)
        if marke == self._karten_marke and self._katalog:
            return
        self._karten_marke = marke
        self._symbole = {}
        try:
            import mapgen
            tm = mapgen.model()
        except Exception:                    # ohne Modell nur nach Namen
            tm = None
        self._katalog = katalog(karte, tm)
        self._chip_symbole()
        self._fuellen()

    def stempel(self) -> Stempel | None:
        return self._auswahl

    def set_familie(self, fam: str) -> None:
        if fam not in self._chips:
            fam = "alle"
        self._familie = fam
        self._chips[fam].setChecked(True)
        self._fuellen()

    def kachel_waehlen(self, kachel: int) -> None:
        """Pipette: genau diese Einzelkachel zeigen und auswaehlen."""
        ziel = next((s for s in self._katalog if not s.gruppe and s.kacheln[0] == kachel), None)
        if ziel is None:
            return
        fam = next(iter(sorted(ziel.familien)), "alle")
        self._familie = fam if fam in self._chips else "alle"
        self._chips[self._familie].setChecked(True)
        for combo in (self.art, self.sorte):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.suche.blockSignals(True)
        self.suche.clear()
        self.suche.blockSignals(False)
        self._fuellen()
        for i in range(self.raster.count()):
            if self.raster.item(i).data(Qt.UserRole) is ziel:
                self.raster.setCurrentRow(i)
                self.raster.scrollToItem(self.raster.item(i))
                break

    # ------------------------------------------------------------------
    def _passt(self, s: Stempel) -> bool:
        if self._familie != "alle" and self._familie not in s.familien:
            return False
        art = self.art.currentData()
        if art != "alle" and s.art != art:
            return False
        sorte = self.sorte.currentData()
        if sorte == "gruppen" and not s.gruppe:
            return False
        if sorte == "einzeln" and s.gruppe:
            return False
        text = self.suche.text().strip().lower()
        if text and text not in s.name.lower() and text != tr(f"tiles.art_{s.art}").lower():
            return False
        return True

    def _fuellen(self, *_):
        alt = self._auswahl
        self.raster.blockSignals(True)
        self.raster.clear()
        treffer = [s for s in self._katalog if self._passt(s)]
        # Gruppen zuerst nach Art und Name, dann Einzelkacheln nach Haeufigkeit.
        # Groups first by kind and name, then single tiles by frequency.
        reihe = {a: i for i, a in enumerate(ARTEN)}
        treffer.sort(key=lambda s: (not s.gruppe, reihe.get(s.art, 99),
                                    -s.haeufigkeit, s.name))
        neu_index = -1
        for s in treffer:
            it = QListWidgetItem(self._symbol(s), "")
            it.setData(Qt.UserRole, s)
            it.setToolTip(self._tooltip(s))
            self.raster.addItem(it)
            if s is alt:
                neu_index = self.raster.count() - 1
        self.raster.blockSignals(False)
        gruppen = sum(1 for s in treffer if s.gruppe)
        self.anzahl.setText(tr("tiles.count", g=gruppen, k=len(treffer) - gruppen))
        if neu_index >= 0:
            self.raster.setCurrentRow(neu_index)
        elif alt is not None:
            # Auswahl bleibt bestehen, auch wenn der Filter sie ausblendet.
            pass

    def _tooltip(self, s: Stempel) -> str:
        groesse = f"{s.breite}×{s.hoehe}"
        return f"{s.name}  ·  {groesse}  ·  {tr('tiles.art_' + s.art)}"

    def _gewaehlt(self, it, _alt=None):
        s = it.data(Qt.UserRole) if it is not None else None
        self._auswahl = s
        self._info_zeigen(s)
        self.auswahl_geaendert.emit(s)

    # ------------------------------------------------------------------
    def bild(self, s: Stempel) -> QPixmap | None:
        """Volles Bild des Stempels (32 px je Kachel). / Full stamp image."""
        w = self._window
        pm = QPixmap(s.breite * TILE, s.hoehe * TILE)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        for y in range(s.hoehe):
            for x in range(s.breite):
                k = w._tile_pixmap(s.kachel(x, y)) if hasattr(w, "_tile_pixmap") else None
                if k is not None:
                    p.drawPixmap(x * TILE, y * TILE, k)
        p.end()
        return pm

    def _symbol(self, s: Stempel) -> QIcon:
        icon = self._symbole.get(id(s))
        if icon is not None:
            return icon
        voll = self.bild(s)
        kasten = QPixmap(SYMBOL, SYMBOL)
        kasten.fill(QColor(0, 0, 0, 0))
        klein = voll.scaled(SYMBOL, SYMBOL, Qt.KeepAspectRatio,
                            Qt.FastTransformation if s.breite * s.hoehe == 1
                            else Qt.SmoothTransformation)
        p = QPainter(kasten)
        p.drawPixmap((SYMBOL - klein.width()) // 2, (SYMBOL - klein.height()) // 2, klein)
        if s.gruppe:
            # Kleine Ecke: Gruppe statt Einzelkachel / corner mark for groups
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(249, 226, 175, 220))
            p.drawPolygon(QPolygonF([QPointF(SYMBOL - 12, 0), QPointF(SYMBOL, 0),
                                     QPointF(SYMBOL, 12)]))
        p.end()
        icon = QIcon(kasten)
        self._symbole[id(s)] = icon
        return icon

    def _chip_symbole(self):
        """Jeder Boden-Chip zeigt seine haeufigste Kachel."""
        for fam, b in self._chips.items():
            kandidaten = [s for s in self._katalog
                          if not s.gruppe and s.art == "boden" and fam in s.familien]
            if fam == "alle" or not kandidaten:
                b.setIcon(QIcon())
                continue
            beste = max(kandidaten, key=lambda s: s.haeufigkeit)
            pm = self._window._tile_pixmap(beste.kacheln[0])
            b.setIcon(QIcon(pm) if pm is not None else QIcon())

    def repraesentant(self, fam: str) -> QPixmap | None:
        """Haeufigste reine Kachel eines Bodens (fuer Pinselknoepfe)."""
        kandidaten = [s for s in self._katalog
                      if not s.gruppe and s.art == "boden" and fam in s.familien]
        if not kandidaten:
            return None
        beste = max(kandidaten, key=lambda s: s.haeufigkeit)
        return self._window._tile_pixmap(beste.kacheln[0])

    def _info_zeigen(self, s: Stempel | None):
        if s is None:
            self.info_bild.clear()
            self.info_text.setText(tr("tiles.none"))
            return
        import celltypes as ct
        voll = self.bild(s)
        self.info_bild.setPixmap(voll.scaled(96, 96, Qt.KeepAspectRatio,
                                             Qt.FastTransformation if voll.width() <= 96
                                             else Qt.SmoothTransformation))
        klassen = []
        for k in dict.fromkeys(s.kacheln):
            zt = ct.default_cell_type(int(k), fallback=-1)
            if zt is not None and zt >= 0:
                name = tr("terrain.speed_" + ct.speed_class(zt))
                if name not in klassen:
                    klassen.append(name)
        boeden = ", ".join(tr(f"tiles.fam_{f}") for f in FAMILIEN if f in s.familien)
        titel = s.name if s.gruppe else tr("tiles.single", n=s.kacheln[0])
        zeilen = [f"<b>{titel}</b>",
                  tr("tiles.info_size", w=s.breite, h=s.hoehe, art=tr(f"tiles.art_{s.art}")),
                  tr("tiles.info_ground", boeden=boeden or "–")]
        if klassen:
            zeilen.append(tr("tiles.info_pass", klassen=", ".join(klassen)))
        self.info_text.setText("<br>".join(zeilen))
