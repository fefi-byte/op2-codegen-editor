"""Sidebar-Tab "Gelaende": Absicht malen statt Kacheln stempeln.

Vorher liess dieser Tab einzelne Kacheln setzen. Das ist die falsche Ebene:
welche Kachel an einer Klippenkante richtig ist, haengt vom Umfeld ab, und wer
das von Hand macht, kaempft gegen die Kachelgrammatik statt zu gestalten.

Jetzt malt man, WAS an einer Stelle sein soll -- Hochland, Fels, Sand, ein
Vulkan -- und der Editor leitet die Kacheln daraus ab: Zelltyp aus der Form,
Kachel aus dem gelernten Umfeld der Originalkarten. Klippen entstehen von
selbst an der Grenze zwischen Hoch- und Tiefland.

Sidebar tab "Terrain": paint intent instead of stamping tiles. Previously this
tab placed individual tiles, which is the wrong level -- which tile is right on
a cliff edge depends on the surroundings. Now you paint WHAT should be at a
spot and the editor derives the tiles from it; cliffs appear by themselves on
the border between highland and lowland.
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPixmap, QIcon
from PySide6.QtWidgets import QButtonGroup, QGridLayout

from ..common import *
from ..style import apply_role
from ..paint_layers import (
    B_TIEF, B_ERDE, B_FELS, B_SAND, B_BEWUCHS, B_SCHNEE,
    B_VULKAN, B_LAVA, B_BAU, B_KLIPPE,
)

# Pinsel in Anzeigereihenfolge: erst der Radierer, dann die Boeden, dann die
# Sonderflaechen. Die Farbe ist nur die Knopfmarkierung.
# Brushes in display order: the eraser first, then grounds, then special areas.
# The colour is just the button marker.
BRUSH_ORDER: list[tuple[str, str]] = [
    (B_TIEF,    "#6e7a86"),
    (B_ERDE,    "#9a8358"),
    (B_FELS,    "#6f7a72"),
    (B_SAND,    "#c8862f"),
    (B_BEWUCHS, "#6f8f4a"),
    (B_SCHNEE,  "#cfd8e0"),
    (B_VULKAN,  "#b4462a"),
    (B_LAVA,    "#d4622a"),
    (B_BAU,     "#4f86c6"),
    (B_KLIPPE,  "#a08050"),
]

# Pinsel, die punktuell wirken statt flaechig -- dafuer ist eine Pinselgroesse
# sinnlos.
# Brushes that act on a point rather than an area -- a brush size makes no
# sense for those.
PUNKT_PINSEL = (B_VULKAN, B_KLIPPE)

# Pinsel, die einen Boden malen -- ihr Knopf zeigt eine echte Kachel, und in
# der Kachel-Palette filtern sie auf diesen Boden.
# Brushes that paint a ground: their button shows a real tile, and in the
# tile palette they filter for that ground.
BODEN_PINSEL = (B_ERDE, B_FELS, B_SAND, B_BEWUCHS, B_SCHNEE)

MODUS_MALEN = "malen"
MODUS_KACHELN = "kacheln"


class TerrainPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self._window = window
        # Vorausgewaehlt ist ein Bodenpinsel, nicht der Radierer: der erste
        # Klick soll nichts wegnehmen.
        # A ground brush is preselected, not the eraser -- the first click
        # should not take anything away.
        self._brush = B_ERDE
        self._modus = MODUS_MALEN
        self._buttons: dict[str, QPushButton] = {}

        aussen = QVBoxLayout(self)

        # Umschalter: Absicht malen oder Kacheln/Gruppen einzeln setzen.
        # Switch: paint intent, or place tiles/groups one by one.
        umschalter = QHBoxLayout()
        umschalter.setSpacing(0)
        self._modus_knoepfe: dict[str, QPushButton] = {}
        self._modus_gruppe = QButtonGroup(self)
        for i, (modus, schl) in enumerate(((MODUS_MALEN, "terrain.mode_paint"),
                                           (MODUS_KACHELN, "terrain.mode_tiles"))):
            b = QPushButton(tr(schl))
            b.setCheckable(True)
            b.setToolTip(tr(schl + "_hint"))
            b.setMinimumHeight(30)
            rund = ("border-top-left-radius:6px;border-bottom-left-radius:6px;"
                    "border-top-right-radius:0;border-bottom-right-radius:0;" if i == 0 else
                    "border-top-right-radius:6px;border-bottom-right-radius:6px;"
                    "border-top-left-radius:0;border-bottom-left-radius:0;")
            b.setStyleSheet(
                "QPushButton{font-weight:600;" + rund + "}"
                "QPushButton:checked{background:#f9e2af;color:#1e1e2e;border-color:#f9e2af;}")
            b.clicked.connect(lambda _=False, m=modus: self.set_modus(m))
            self._modus_gruppe.addButton(b)
            umschalter.addWidget(b, 1)
            self._modus_knoepfe[modus] = b
        aussen.addLayout(umschalter)

        # --- Malen ---
        self.mal_box = QWidget()
        lay = QVBoxLayout(self.mal_box)
        lay.setContentsMargins(0, 0, 0, 0)
        aussen.addWidget(self.mal_box)

        lbl = QLabel(tr("terrain.lbl_brushes"))
        lbl.setProperty("role", "section")
        lay.addWidget(lbl)

        raster = QGridLayout()
        raster.setSpacing(3)
        for i, (brush, farbe) in enumerate(BRUSH_ORDER):
            btn = QPushButton(tr(f"terrain.brush_{brush}"))
            btn.setCheckable(True)
            btn.setIcon(self._farbmarke(farbe))
            btn.setIconSize(QSize(18, 18))
            btn.setMinimumHeight(28)
            btn.setStyleSheet("QPushButton:checked{background:#45475a;border:2px solid #f9e2af;"
                              "font-weight:600;}")
            btn.setToolTip(tr(f"terrain.brush_{brush}_hint"))
            btn.clicked.connect(lambda _=False, b=brush: self.set_brush(b))
            raster.addWidget(btn, i // 2, i % 2)
            self._buttons[brush] = btn
        lay.addLayout(raster)

        form = QFormLayout()
        self.brush_size = QSpinBox()
        # Grossflaechig malen koennen: bis 61 Kacheln Durchmesser. Der Strich
        # wird gesammelt und erst beim Loslassen berechnet, deshalb kostet
        # ein grosser Pinsel keine Bildrate.
        # Paint large areas: up to 61 tiles across. The stroke is collected and
        # only computed on release, so a large brush costs no frame rate.
        self.brush_size.setRange(1, 61)
        self.brush_size.setValue(5)
        self.brush_size.valueChanged.connect(self._update_info)
        form.addRow(tr("terrain.lbl_brush"), self.brush_size)
        lay.addLayout(form)

        # Bedienfeld der Klippenlinie. Nur sichtbar, wenn der Klippenpinsel
        # gewaehlt ist -- sonst steht es nutzlos im Weg.
        # Cliff line controls. Only visible with the cliff brush selected.
        self.klippen_box = QWidget()
        kl = QVBoxLayout(self.klippen_box)
        kl.setContentsMargins(0, 4, 0, 4)
        kform = QFormLayout()
        self.klippen_seite_wahl = QComboBox()
        for wert in ("links", "rechts", "oben", "unten"):
            self.klippen_seite_wahl.addItem(tr(f"terrain.klippe_{wert}"), wert)
        self.klippen_seite_wahl.setToolTip(tr("terrain.klippe_seite_hint"))
        kform.addRow(tr("terrain.klippe_seite"), self.klippen_seite_wahl)
        # Wandhoehe: "wie Karte" misst die vorhandenen Klippen.
        # Wall height: "like map" measures the cliffs already there.
        self.klippen_hoehe_wahl = QComboBox()
        self.klippen_hoehe_wahl.addItem(tr("terrain.klippe_hoehe_karte"), None)
        for n in (3, 4, 5, 6):
            self.klippen_hoehe_wahl.addItem(tr("terrain.klippe_hoehe_n", n=n), n)
        self.klippen_hoehe_wahl.setToolTip(tr("terrain.klippe_hoehe_hint"))
        kform.addRow(tr("terrain.klippe_hoehe"), self.klippen_hoehe_wahl)
        kl.addLayout(kform)
        knopfreihe = QHBoxLayout()
        self.btn_klippe_setzen = QPushButton(tr("terrain.klippe_setzen"))
        self.btn_klippe_setzen.setToolTip(tr("terrain.klippe_setzen_hint"))
        self.btn_klippe_setzen.clicked.connect(self._window._klippe_setzen)
        # Seite oder Hoehe gewechselt: die Live-Vorschau neu rechnen.
        for wahl in (self.klippen_seite_wahl, self.klippen_hoehe_wahl):
            wahl.currentIndexChanged.connect(
                lambda *_: self._window._klippen_live_planen(
                    self._window._klippen_live_ziel, neu=True))
        apply_role(self.btn_klippe_setzen, "primary")
        knopfreihe.addWidget(self.btn_klippe_setzen, 1)
        self.btn_klippe_weg = QPushButton(tr("terrain.klippe_verwerfen"))
        self.btn_klippe_weg.clicked.connect(self._window._klippen_verwerfen)
        knopfreihe.addWidget(self.btn_klippe_weg, 1)
        kl.addLayout(knopfreihe)
        self.klippen_info = QLabel(tr("terrain.klippe_punkte", n=0))
        self.klippen_info.setWordWrap(True)
        self.klippen_info.setProperty("secondary", "true")
        kl.addWidget(self.klippen_info)
        lay.addWidget(self.klippen_box)
        self.klippen_box.setVisible(False)
        self.klippen_punkte_geaendert(0)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setProperty("secondary", "true")
        lay.addWidget(self.info)

        # --- Kacheln & Gruppen ---
        from .kachel_palette import KachelPalette
        self.palette = KachelPalette(window)
        self.palette.auswahl_geaendert.connect(self._kachel_gewaehlt)
        self.palette.setVisible(False)
        aussen.addWidget(self.palette, 1)
        lay = aussen

        # Overlay-Schalter: das Einfaerben hilft beim Malen, verdeckt aber die
        # Kachelgrafik -- deshalb abschaltbar, ohne den Tab verlassen zu muessen.
        # Overlay toggle: the tint helps while painting but hides the tile
        # graphics -- so it can be switched off without leaving the tab.
        legend_lbl = QLabel(tr("terrain.lbl_legend"))
        legend_lbl.setProperty("role", "section")
        lay.addWidget(legend_lbl)

        overlay_row = QHBoxLayout()
        self.overlay_toggle = QPushButton(tr("terrain.btn_overlay"))
        self.overlay_toggle.setCheckable(True)
        # Standardmaessig aus: das Einfaerben verdeckt die Kacheln, und wer es
        # braucht, schaltet es mit einem Klick ein.
        # Off by default: the tint hides the tiles; one click turns it on.
        self.overlay_toggle.setChecked(False)
        self.overlay_toggle.toggled.connect(self._on_overlay_changed)
        self.overlay_toggle.setStyleSheet(
            "QPushButton:checked{background:#a6e3a1;color:#1e1e2e;border-color:#a6e3a1;}")
        overlay_row.addWidget(self.overlay_toggle, 1)
        self.overlay_mode = QComboBox()
        self.overlay_mode.addItem(tr("terrain.mode_speed"), "speed")
        self.overlay_mode.addItem(tr("terrain.mode_blocked"), "blocked")
        self.overlay_mode.addItem(tr("terrain.mode_height"), "height")
        self.overlay_mode.currentIndexChanged.connect(self._on_overlay_changed)
        overlay_row.addWidget(self.overlay_mode, 1)
        lay.addLayout(overlay_row)

        # Uebergaenge der ganzen Karte neu bestimmen. Nuetzlich nach dem
        # Laden einer fremden Karte oder nach vielen Einzelstrichen.
        # Recompute the transitions of the whole map. Useful after loading a
        # foreign map or after many individual strokes.
        self.btn_aufraeumen = QPushButton(tr("terrain.btn_aufraeumen"))
        self.btn_aufraeumen.setToolTip(tr("terrain.btn_aufraeumen_hint"))
        self.btn_aufraeumen.clicked.connect(self._window._uebergaenge_aufraeumen)
        lay.addWidget(self.btn_aufraeumen)

        self.legende = self._build_legend()
        lay.addWidget(self.legende)
        self.legende.setVisible(False)
        self.overlay_mode.setEnabled(False)
        self._dehnung = QWidget()
        lay.addWidget(self._dehnung, 1)

        self.hint = QLabel(tr("terrain.hint"))
        self.hint.setWordWrap(True)
        self.hint.setProperty("secondary", "true")
        lay.addWidget(self.hint)

        self._modus_knoepfe[MODUS_MALEN].setChecked(True)
        self.set_brush(B_ERDE)

    # ------------------------------------------------------------------
    @staticmethod
    def _farbmarke(farbe: str) -> QIcon:
        pix = QPixmap(14, 14)
        pix.fill(QColor(farbe))
        return QIcon(pix)

    def _build_legend(self) -> QWidget:
        from ..window_terrain import SPEED_COLORS
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        for i, (klasse, farbe) in enumerate(SPEED_COLORS.items()):
            marke = QLabel()
            marke.setFixedSize(14, 14)
            marke.setStyleSheet(f"background:{QColor(*farbe).name()};border:1px solid #333;")
            grid.addWidget(marke, i // 2, (i % 2) * 2)
            grid.addWidget(QLabel(tr(f"terrain.speed_{klasse}")), i // 2, (i % 2) * 2 + 1)
        return box

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Modus / mode

    def modus(self) -> str:
        return self._modus

    def set_modus(self, modus: str) -> None:
        self._modus = modus
        self._modus_knoepfe[modus].setChecked(True)
        kacheln = modus == MODUS_KACHELN
        self.mal_box.setVisible(not kacheln)
        self.palette.setVisible(kacheln)
        self._dehnung.setVisible(not kacheln)
        self.hint.setVisible(not kacheln)
        if kacheln:
            self.palette.laden()
            # Der gewaehlte Boden filtert die Palette: Erde -> alles mit Erde.
            # The chosen ground filters the palette: mud -> everything with mud.
            if self._brush in BODEN_PINSEL:
                self.palette.set_familie(self._brush)
        w = self._window
        if hasattr(w, "_klippen_verwerfen") and kacheln and getattr(w, "_klippen_punkte", None):
            w._klippen_verwerfen()
        if hasattr(w, "_terrain_modus_gewechselt"):
            w._terrain_modus_gewechselt()

    def kachel_stempel(self):
        """Gewaehlter Stempel der Palette (nur im Kachelmodus)."""
        return self.palette.stempel() if self._modus == MODUS_KACHELN else None

    def _kachel_gewaehlt(self, _stempel):
        if hasattr(self._window, "_gelaende_banner_aktualisieren"):
            self._window._gelaende_banner_aktualisieren()

    def _kachel_symbole(self):
        """Bodenpinsel mit echter Kachel statt Farbfleck."""
        if getattr(self._window, "map", None) is None:
            return
        self.palette.laden()
        for brush in BODEN_PINSEL:
            pm = self.palette.repraesentant(brush)
            if pm is not None and brush in self._buttons:
                self._buttons[brush].setIcon(QIcon(pm))

    def set_brush(self, brush: str) -> None:
        self._brush = brush
        for key, btn in self._buttons.items():
            btn.setChecked(key == brush)
        self.brush_size.setEnabled(brush not in PUNKT_PINSEL)
        self.klippen_box.setVisible(brush == B_KLIPPE)
        if brush == B_KLIPPE and hasattr(self._window, "_klippen_vorwaermen"):
            self._window._klippen_vorwaermen()
        if hasattr(self._window, "_gelaende_banner_aktualisieren"):
            self._window._gelaende_banner_aktualisieren()
        self._update_info()

    def selected_brush(self) -> str:
        return self._brush

    def klippen_seite(self) -> str:
        """Auf welcher Seite der gezeichneten Linie liegt das Hochland?"""
        return self.klippen_seite_wahl.currentData() or "links"

    def klippen_hoehe(self):
        """Gewaehlte Wandhoehe in Zellen, oder None fuer "wie Karte"."""
        return self.klippen_hoehe_wahl.currentData()

    def klippen_hoehe_gemessen(self, zellen) -> None:
        """Den gemessenen Wert hinter "wie Karte" zeigen."""
        text = (tr("terrain.klippe_hoehe_karte") if zellen is None else
                tr("terrain.klippe_hoehe_karte_wert",
                   n=f"{zellen:.1f}".replace(".", ",")))
        self.klippen_hoehe_wahl.setItemText(0, text)

    def klippen_punkte_geaendert(self, n: int) -> None:
        """Anzahl gesetzter Stuetzpunkte anzeigen."""
        self.klippen_info.setText(tr("terrain.klippe_punkte", n=n))
        self.btn_klippe_setzen.setEnabled(n >= 2)

    def brush_radius(self) -> int:
        return max(1, self.brush_size.value())

    def set_brush_size(self, size: int) -> None:
        self.brush_size.setValue(max(1, min(61, size)))

    def load(self) -> None:
        self.palette._karten_marke = None
        self._kachel_symbole()
        self._update_info()

    def refresh(self, *_args) -> None:
        self._update_info()

    # ------------------------------------------------------------------
    def _on_overlay_changed(self, *_args):
        # Modusauswahl folgt dem Schalter -- eine Auswahl ohne Wirkung
        # verwirrt nur.
        # The mode box follows the toggle -- a choice without effect only
        # confuses.
        self.overlay_mode.setEnabled(self.overlay_toggle.isChecked())
        self.legende.setVisible(self.overlay_toggle.isChecked())
        self._window._set_overlay_options(
            self.overlay_toggle.isChecked(), self.overlay_mode.currentData())

    def _update_info(self):
        name = tr(f"terrain.brush_{self._brush}")
        if self._brush in PUNKT_PINSEL:
            self.info.setText(tr("terrain.info_point", brush=name))
        else:
            self.info.setText(tr("terrain.info_area", brush=name,
                                 size=self.brush_size.value()))
