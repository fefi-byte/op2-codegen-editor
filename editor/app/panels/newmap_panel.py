"""Panel "Neue Karte": Gelaende aus einem Seed erzeugen -- in der Seitenleiste.

Bewusst kein Dialog: die erzeugte Karte wird direkt in der grossen Kartenansicht
aufgebaut, damit man sie in voller Groesse begutachten kann statt in einem
Briefmarkenfeld. Das Panel taucht nur auf, solange man es ueber das Menue
geoeffnet hat, und verschwindet mit "Uebernehmen" oder "Verwerfen".

"New map" panel: generate terrain from a seed -- in the sidebar. Deliberately
not a dialog: the generated map is built directly in the main map view so it
can be inspected at full size. The panel only exists while opened from the
menu and disappears on "keep" or "discard".
"""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QProgressBar, QSlider, QScrollArea

from ..common import *
from ..netz_worker import NetzWorker
from ..style import apply_role
from .feature_list import FeatureList
from .. import maplib

import mapgen
import mapgen_netz

# Auswaehlbare Kartengroessen -- die Breite steckt als Zweierpotenz im
# Dateikopf, deshalb keine freien Werte.
# Selectable map sizes -- the width is stored as a power of two in the file
# header, hence no free values.
SIZES = [(64, 64), (128, 64), (128, 128), (256, 128), (256, 256), (512, 256)]

TEMPLATE_KEYS = ["plains", "canyon", "desert", "islands", "ice", "newterra", "netz"]
# "veg" = bewachsener Fels -- OP2 kennt kein Grasland, aber diese Kacheln
# bilden im Original zusammenhaengende bewachsene Flaechen.
# "veg" = overgrown rock -- OP2 has no grassland, but these tiles form
# coherent overgrown areas in the original maps.
FAMILY_KEYS = ["mud", "veg", "roc", "san", "sno"]


class NewMapPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self._window = window
        self._result: mapgen.GeneratedMap | None = None
        self._busy = False
        self._backup = None
        # Gelernter Generator: laufende Rechnung, letzte Skizze und ob nach dem
        # Abbruch gleich neu begonnen werden soll.
        # Learned generator: running computation, last sketch, and whether to
        # restart right after cancelling.
        self._worker: NetzWorker | None = None
        self._skizze = None                     # (Parameter, Skizze)
        self._nochmal: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        form = QFormLayout(inner)

        self.size_combo = QComboBox()
        self._form = form
        for w, h in SIZES:
            self.size_combo.addItem(f"{w} × {h}", (w, h))
        self.size_combo.setCurrentIndex(2)
        form.addRow(tr("newmap.lbl_size"), self.size_combo)

        self.template = QComboBox()
        for key in TEMPLATE_KEYS:
            self.template.addItem(tr(f"newmap.tpl_{key}"), key)
        # Standard ist das gelernte Modell, wenn es laufen kann.
        # The learned model is the default when it can run.
        if mapgen_netz.verfuegbar():
            self.template.setCurrentIndex(TEMPLATE_KEYS.index("netz"))
        self.template.currentIndexChanged.connect(self._apply_template)
        form.addRow(tr("newmap.lbl_template"), self.template)

        seed_row = QHBoxLayout()
        seed_row.setContentsMargins(0, 0, 0, 0)
        self.seed = QSpinBox()
        self.seed.setRange(0, 999999)
        self.seed.setValue(1234)
        seed_row.addWidget(self.seed, 1)
        dice = QPushButton(tr("newmap.btn_dice"))
        dice.clicked.connect(self._roll_seed)
        seed_row.addWidget(dice)
        holder = QWidget()
        holder.setLayout(seed_row)
        form.addRow(tr("newmap.lbl_seed"), holder)

        mix_label = QLabel(tr("newmap.lbl_mix"))
        mix_label.setProperty("role", "section")
        form.addRow(mix_label)
        self.mix_sliders: dict[str, QSlider] = {}
        self.mix_values: dict[str, QLabel] = {}
        for key in FAMILY_KEYS:
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            value = QLabel("0 %")
            value.setMinimumWidth(42)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(slider, 1)
            row.addWidget(value)
            box = QWidget()
            box.setLayout(row)
            form.addRow(tr(f"newmap.fam_{key}"), box)
            self.mix_sliders[key] = slider
            if key == "sno":
                self._sno_box = box
            self.mix_values[key] = value

        self.roughness = QSlider(Qt.Horizontal)
        self.roughness.setRange(0, 100)
        # Vorgabe 0: gemessen verdoppelt eine zerkluefte Biomgrenze die
        # Kachelfehler, ohne dass die Karte dadurch interessanter wird.
        # Default 0: measured, a rugged biome border doubles the tile errors
        # without making the map more interesting.
        self.roughness.setValue(0)
        form.addRow(tr("newmap.lbl_roughness"), self.roughness)

        # Mindestgroesse eines Bioms: kleinere Flecken gehen im Nachbarbiom
        # auf, statt als Sprenkel stehen zu bleiben.
        # Minimum biome size: smaller patches dissolve into the neighbouring
        # biome instead of remaining as speckles.
        self.min_biome = QSlider(Qt.Horizontal)
        self.min_biome.setRange(0, 40)          # Zehntelprozent der Kartenflaeche
        self.min_biome.setValue(6)
        self.min_biome_value = QLabel("")
        min_row = QHBoxLayout()
        min_row.setContentsMargins(0, 0, 0, 0)
        min_row.addWidget(self.min_biome, 1)
        min_row.addWidget(self.min_biome_value)
        min_box = QWidget()
        min_box.setLayout(min_row)
        self._min_box = min_box
        form.addRow(tr("newmap.lbl_min_biome"), min_box)

        # Gelernter Generator: wie oft die Biome wechseln.
        # Learned generator: how often the biomes change.
        self.biom_ruhe = QSlider(Qt.Horizontal)
        self.biom_ruhe.setRange(0, 100)
        self.biom_ruhe.setToolTip(tr("newmap.biom_ruhe_hint"))
        self.biom_ruhe_value = QLabel("0 %")
        self.biom_ruhe_value.setMinimumWidth(42)
        ruhe_row = QHBoxLayout()
        ruhe_row.setContentsMargins(0, 0, 0, 0)
        ruhe_row.addWidget(self.biom_ruhe, 1)
        ruhe_row.addWidget(self.biom_ruhe_value)
        ruhe_box = QWidget()
        ruhe_box.setLayout(ruhe_row)
        self._ruhe_box = ruhe_box
        form.addRow(tr("newmap.lbl_biom_ruhe"), ruhe_box)

        # Gelernter Generator: grosse Hochflaechen und Kessel, an deren Klippen
        # die Boeden wechseln. Large uplands and basins, grounds change at cliffs.
        self.grossform = QSlider(Qt.Horizontal)
        self.grossform.setRange(0, 100)
        self.grossform.setToolTip(tr("newmap.grossform_hint"))
        form.addRow(tr("newmap.lbl_grossform"), self.grossform)
        # Gelernter Generator: Verlauf ueber die Karte -- Boden und Gelaende
        # wandern von einem Ende zum anderen. Learned: a gradient across the map.
        self.verlauf = QComboBox()
        self.verlauf.addItem(tr("newmap.verlauf_aus"), "")
        for key in mapgen.VERLAEUFE:
            self.verlauf.addItem(tr(f"newmap.verlauf_{key.replace('-', '_')}"), key)
        self.verlauf.setToolTip(tr("newmap.verlauf_hint"))
        form.addRow(tr("newmap.lbl_verlauf"), self.verlauf)
        self.verlauf_enden = []
        for ende in ("anfang", "ende"):
            zeile = QHBoxLayout()
            zeile.setContentsMargins(0, 0, 0, 0)
            boden = QComboBox()
            boden.addItem(tr("newmap.verlauf_mischung"), "")
            for key in ("mud", "roc", "san"):
                boden.addItem(tr(f"newmap.verlauf_{key}"), key)
            gelaende = QSlider(Qt.Horizontal)
            gelaende.setRange(0, 100)
            gelaende.setValue(50)
            gelaende.setToolTip(tr("newmap.verlauf_gelaende_hint"))
            zeile.addWidget(boden)
            zeile.addWidget(QLabel(tr("newmap.verlauf_flach")))
            zeile.addWidget(gelaende, 1)
            zeile.addWidget(QLabel(tr("newmap.verlauf_bergig")))
            box = QWidget()
            box.setLayout(zeile)
            form.addRow(tr(f"newmap.lbl_verlauf_{ende}"), box)
            self.verlauf_enden.append((box, boden, gelaende))

        # Gelernter Generator: Krater, Risse, Truemmer. Learned: decorations.
        self.deko = {}
        for key in ("krater", "risse", "truemmer"):
            regler = QSlider(Qt.Horizontal)
            regler.setRange(0, 100)
            regler.setToolTip(tr(f"newmap.{key}_hint"))
            form.addRow(tr(f"newmap.lbl_{key}"), regler)
            self.deko[key] = regler
        self.gelaende_ruhe = QSlider(Qt.Horizontal)
        self.gelaende_ruhe.setRange(0, 100)
        self.gelaende_ruhe.setToolTip(tr("newmap.gelaende_ruhe_hint"))
        form.addRow(tr("newmap.lbl_gelaende_ruhe"), self.gelaende_ruhe)

        # Gelernter Generator: dunkle Lavakerne in den Felsgebieten.
        # Learned generator: dark lava cores in the rock areas.
        self.lavafels = QSlider(Qt.Horizontal)
        self.lavafels.setRange(0, 100)
        self.lavafels.setValue(50)
        self.lavafels.setToolTip(tr("newmap.lavafels_hint"))
        form.addRow(tr("newmap.lbl_lavafels"), self.lavafels)

        self.symmetry = QComboBox()
        for mode in mapgen.SYMMETRIES:
            self.symmetry.addItem(tr(f"newmap.sym_{mode}"), mode)
        form.addRow(tr("newmap.lbl_symmetry"), self.symmetry)

        # Klippen: Hochflaechen mit Kantenstempeln. Nur Erde/Sand haben
        # passende Stempel, deshalb entstehen Plateaus bevorzugt dort.
        # Cliffs: plateaus with edge stamps. Only dirt/sand have matching
        # stamps, so plateaus prefer those areas.
        self.cliffs = QSlider(Qt.Horizontal)
        self.cliffs.setRange(0, 40)
        self.cliffs.setToolTip(tr("newmap.cliffs_hint"))
        form.addRow(tr("newmap.lbl_cliffs"), self.cliffs)

        # Berge und Bauland: Flaechenanteil der Bergketten, wie eng die Stufen
        # stehen, und wie viele Schluchten (kein Bauplatz), Taeler und
        # Hochebenen (Bauplatz) es gibt.
        # Mountains and building ground: area share, how tight the terraces
        # are, and the number of gorges (no building), valleys and plateaus
        # (building).
        self.berge = QSlider(Qt.Horizontal)
        self.berge.setRange(0, 40)
        self.berge_value = QLabel("0 %")
        self.berge_value.setMinimumWidth(42)
        berge_row = QHBoxLayout()
        berge_row.setContentsMargins(0, 0, 0, 0)
        berge_row.addWidget(self.berge, 1)
        berge_row.addWidget(self.berge_value)
        berge_box = QWidget()
        berge_box.setLayout(berge_row)
        berge_box.setToolTip(tr("newmap.berge_hint"))
        form.addRow(tr("newmap.lbl_berge"), berge_box)
        self.berg_dichte = QSlider(Qt.Horizontal)
        self.berg_dichte.setRange(0, 100)
        self.berg_dichte.setValue(80)
        self.berg_dichte.setToolTip(tr("newmap.berg_dichte_hint"))
        form.addRow(tr("newmap.lbl_berg_dichte"), self.berg_dichte)
        self.zonen: dict[str, QSpinBox] = {}
        for key, vorgabe in (("schluchten", 1), ("taeler", 1), ("hochebenen", 0)):
            feld = QSpinBox()
            feld.setRange(0, 6)
            feld.setValue(vorgabe)
            feld.setToolTip(tr(f"newmap.{key}_hint"))
            form.addRow(tr(f"newmap.lbl_{key}"), feld)
            self.zonen[key] = feld
        self.berg_felsen = QCheckBox(tr("newmap.berg_felsen"))
        self.berg_felsen.setChecked(True)
        self.berg_felsen.setToolTip(tr("newmap.berg_felsen_hint"))
        form.addRow("", self.berg_felsen)

        # Streugut: Steine, Risse und Krater im passenden Biom. Die Mitte des
        # Reglers entspricht der Dichte der Originalkarten (rund 3 %).
        # Scatter: stones, cracks and craters in the matching biome. The middle
        # of the slider matches the density of the original maps (about 3 %).
        self.details = QSlider(Qt.Horizontal)
        self.details.setRange(0, 100)
        self.details.setValue(50)
        form.addRow(tr("newmap.lbl_details"), self.details)

        self.spawns = QSpinBox()
        self.spawns.setRange(0, 8)
        self.spawns.setValue(2)
        form.addRow(tr("newmap.lbl_spawns"), self.spawns)

        self.volcanoes = QSpinBox()
        self.volcanoes.setRange(0, 4)
        form.addRow(tr("newmap.lbl_volcanoes"), self.volcanoes)
        # Gelernter Generator: Vulkane je Groesse. Learned: volcanoes per size.
        vulkan_row = QHBoxLayout()
        vulkan_row.setContentsMargins(0, 0, 0, 0)
        self.vulkan_groessen = []
        for key in ("klein", "mittel", "gross"):
            feld = QSpinBox()
            feld.setRange(0, 6)
            feld.setPrefix(tr(f"newmap.vulkan_{key}") + " ")
            feld.setToolTip(tr("newmap.vulkan_hint"))
            vulkan_row.addWidget(feld, 1)
            self.vulkan_groessen.append(feld)
        self._vulkan_box = QWidget()
        self._vulkan_box.setLayout(vulkan_row)
        form.addRow(tr("newmap.lbl_volcanoes"), self._vulkan_box)

        # Gelaendemerkmale: der Gegenpol zum Seed. Statt alles zu wuerfeln
        # beschreibt man grob, was vorkommen soll -- ein Tal, ein Berg -- und
        # der Zufall arbeitet drumherum.
        # Terrain features: the counterweight to the seed. Instead of rolling
        # everything you roughly describe what should be there -- a valley, a
        # mountain -- and the randomness works around it.
        self.features = FeatureList(self)
        self.features.changed.connect(self._schedule)
        form.addRow(tr("newmap.lbl_features"), self.features)

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # Gelernter Generator: Sofortvorschau, Fortschritt, gute Stufe.
        # Learned generator: instant preview, progress, good quality.
        self.netz_box = QWidget()
        netz = QVBoxLayout(self.netz_box)
        netz.setContentsMargins(0, 0, 0, 0)
        self.netz_bild = QLabel()
        self.netz_bild.setAlignment(Qt.AlignCenter)
        netz.addWidget(self.netz_bild)
        self.netz_balken = QProgressBar()
        self.netz_balken.setRange(0, 100)
        netz.addWidget(self.netz_balken)
        netz_row = QHBoxLayout()
        self.netz_gut = QPushButton(tr("newmap.netz_gut"))
        self.netz_gut.setToolTip(tr("newmap.netz_gut_hint"))
        self.netz_gut.clicked.connect(lambda: self._netz_start("gut"))
        netz_row.addWidget(self.netz_gut, 1)
        self.netz_stop = QPushButton(tr("newmap.netz_stop"))
        self.netz_stop.clicked.connect(self._netz_abbrechen)
        netz_row.addWidget(self.netz_stop)
        netz.addLayout(netz_row)
        thread_row = QHBoxLayout()
        thread_row.addWidget(QLabel(tr("newmap.lbl_netz_threads")))
        self.netz_threads = QSpinBox()
        self.netz_threads.setRange(0, os.cpu_count() or 4)
        self.netz_threads.setSpecialValueText(
            tr("newmap.netz_threads_auto", n=mapgen_netz.threads_vorgabe()))
        self.netz_threads.setToolTip(tr("newmap.netz_threads_hint"))
        self.netz_threads.setValue(appconfig.netz_threads())
        self.netz_threads.valueChanged.connect(appconfig.set_netz_threads)
        thread_row.addWidget(self.netz_threads, 1)
        netz.addLayout(thread_row)
        self.netz_box.setVisible(False)
        root.addWidget(self.netz_box)

        self.stats = QLabel("")
        self.stats.setWordWrap(True)
        self.stats.setProperty("secondary", "true")
        root.addWidget(self.stats)

        hint = QLabel(tr("newmap.panel_hint"))
        hint.setWordWrap(True)
        hint.setProperty("secondary", "true")
        root.addWidget(hint)

        buttons = QHBoxLayout()
        self.keep_btn = QPushButton(tr("newmap.btn_keep"))
        self.keep_btn.clicked.connect(self.keep)
        apply_role(self.keep_btn, "primary")
        buttons.addWidget(self.keep_btn)
        self.cancel_btn = QPushButton(tr("newmap.btn_discard"))
        self.cancel_btn.clicked.connect(self.discard)
        apply_role(self.cancel_btn, "danger")
        buttons.addWidget(self.cancel_btn)
        root.addLayout(buttons)

        # Neu erzeugen erst kurz nach der letzten Aenderung -- die Karte wird
        # ja komplett neu aufgebaut.
        # Regenerate shortly after the last change -- the whole map is rebuilt.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._regenerate)
        # Ein laufender Thread darf das Programmende nicht ueberleben.
        # A running thread must not outlive the program.
        QApplication.instance().aboutToQuit.connect(self.beenden)
        for widget in (self.size_combo, self.symmetry):
            widget.currentIndexChanged.connect(self._schedule)
        for widget in (self.seed, self.spawns, self.volcanoes):
            widget.valueChanged.connect(self._schedule)
        self.roughness.valueChanged.connect(self._schedule)
        self.cliffs.valueChanged.connect(self._schedule)
        self.berge.valueChanged.connect(self._on_berge)
        self.berg_dichte.valueChanged.connect(self._schedule)
        self.berg_felsen.toggled.connect(self._schedule)
        for feld in self.zonen.values():
            feld.valueChanged.connect(self._schedule)
        self.details.valueChanged.connect(self._schedule)
        self.min_biome.valueChanged.connect(self._on_min_biome)
        self.biom_ruhe.valueChanged.connect(self._on_biom_ruhe)
        self.lavafels.valueChanged.connect(self._schedule)
        self.grossform.valueChanged.connect(self._schedule)
        self.gelaende_ruhe.valueChanged.connect(self._schedule)
        for regler in self.deko.values():
            regler.valueChanged.connect(self._schedule)
        self.verlauf.currentIndexChanged.connect(self._on_verlauf)
        for _box, boden, gelaende in self.verlauf_enden:
            boden.currentIndexChanged.connect(self._schedule)
            gelaende.valueChanged.connect(self._schedule)
        for feld in self.vulkan_groessen:
            feld.valueChanged.connect(self._schedule)
        for slider in self.mix_sliders.values():
            slider.valueChanged.connect(self._on_mix_changed)

    # ------------------------------------------------------------------
    def start(self):
        """Zustand der aktuellen Karte sichern und erste Fassung erzeugen."""
        win = self._window
        self._backup = {
            "map_name": win.map_name,
            "bytes": win.map.to_bytes() if win.map is not None else None,
            "mapgen": getattr(win, "mapgen_params", None),
            "spawns": [list(p) for p in getattr(win, "spawn_points", [])],
            "volcanoes": [list(p) for p in getattr(win, "volcano_points", [])],
            "lava": [list(p) for p in getattr(win, "lava_fields", [])],
            "edited": getattr(win, "map_edited", False),
        }
        self._apply_template()

    def keep(self):
        """Erzeugte Karte behalten und das Panel schliessen."""
        if self._ist_netz() and (self._worker is not None or self._result is None):
            return                              # rechnet noch / still computing
        if self._result is None:
            self._regenerate()
        self._window.close_newmap_panel(keep=True)

    def discard(self):
        """Vorherige Karte wiederherstellen und das Panel schliessen."""
        self.beenden()
        self._window.close_newmap_panel(keep=False)

    def restore_backup(self):
        """Zustand von vor dem ersten Erzeugen zuruecksetzen."""
        win = self._window
        backup = self._backup
        if not backup:
            return
        if backup["bytes"] is not None:
            from op2map import Op2Map
            win.map = Op2Map(backup["bytes"])
            win.map_name = backup["map_name"]
            win.mapgen_params = backup["mapgen"]
            win.spawn_points = backup["spawns"]
            win.volcano_points = backup["volcanoes"]
            win.lava_fields = backup["lava"]
            win._rebuild_scene_from_map()
            win.map_edited = backup["edited"]

    # ------------------------------------------------------------------
    def _roll_seed(self):
        self.seed.setValue(int(np.random.default_rng().integers(0, 999999)))

    def _apply_template(self):
        tpl = mapgen.TEMPLATES[self.template.currentData()]
        for key, slider in self.mix_sliders.items():
            slider.blockSignals(True)
            slider.setValue(int(round(100 * tpl["mix"].get(key, 0.0))))
            slider.blockSignals(False)
        self.roughness.setValue(int(round(100 * tpl["roughness"])))
        # Vorlagen duerfen Vulkane vorschlagen (Landschaft: leicht vulkanisch);
        # der Drehknopf bleibt danach frei veraenderbar.
        # Templates may suggest volcanoes (landscape: slightly volcanic); the
        # spinner stays freely adjustable afterwards.
        if "volcanoes" in tpl:
            self.volcanoes.setValue(int(tpl["volcanoes"]))
        for key, regler in self.deko.items():
            regler.setValue(int(round(100 * tpl.get(key, 0.0))))
        for feld, n in zip(self.vulkan_groessen, tpl.get("vulkane", (0, 0, 0))):
            feld.setValue(int(n))
        # Ebenso Berge und Hochebenen. / Likewise mountains and plateaus.
        self.berge.setValue(int(round(100 * tpl.get("berge", 0.0))))
        self.berg_dichte.setValue(int(round(100 * tpl.get("berg_dichte", 0.8))))
        self.cliffs.setValue(int(round(100 * tpl.get("cliffs", 0.0))))
        self.details.setValue(int(round(100 * tpl.get("details", 0.5))))
        self.biom_ruhe.setValue(int(round(100 * tpl.get("biom_ruhe", 0.0))))
        self.grossform.setValue(int(round(100 * tpl.get("grossform", 0.0))))
        self.gelaende_ruhe.setValue(int(round(100 * tpl.get("gelaende_ruhe", 0.0))))
        self.lavafels.setValue(int(round(100 * tpl.get("lavafels", 0.5))))
        # Was der gelernte Generator nicht kann, verschwindet (Schnee,
        # Zerklueftung), was nur er kann, erscheint.
        # What the learned generator cannot do disappears and vice versa.
        netz = self._ist_netz()
        for feld in (self.roughness, self._min_box, self._sno_box):
            self._form.setRowVisible(feld, not netz)
        self._form.setRowVisible(self.features, not netz)
        self._form.setRowVisible(self.volcanoes, not netz)
        self._form.setRowVisible(self._vulkan_box, netz)
        for regler in self.deko.values():
            self._form.setRowVisible(regler, netz)
        self._form.setRowVisible(self.verlauf, netz)
        self._verlauf_zeigen()
        self._form.setRowVisible(self.berg_felsen, netz)
        self._form.setRowVisible(self._ruhe_box, netz)
        self._form.setRowVisible(self.grossform, netz)
        self._form.setRowVisible(self.gelaende_ruhe, netz)
        self._form.setRowVisible(self.lavafels, netz)
        self.netz_box.setVisible(netz)
        self.zonen["hochebenen"].setValue(int(tpl.get("hochebenen", 0)))
        self._update_mix_labels()
        self._schedule()

    def _on_min_biome(self):
        self.min_biome_value.setText(f"{self.min_biome.value() / 10:.1f} %")
        self._schedule()

    def _verlauf_zeigen(self):
        an = self._ist_netz() and bool(self.verlauf.currentData())
        for box, _b, _g in self.verlauf_enden:
            self._form.setRowVisible(box, an)

    def _on_verlauf(self):
        self._verlauf_zeigen()
        self._schedule()

    def _on_biom_ruhe(self):
        self.biom_ruhe_value.setText(f"{self.biom_ruhe.value()} %")
        self._schedule()

    def _on_berge(self):
        self.berge_value.setText(f"{self.berge.value()} %")
        self._schedule()

    def _on_mix_changed(self):
        self._update_mix_labels()
        self._schedule()

    def _update_mix_labels(self):
        total = sum(s.value() for s in self.mix_sliders.values()) or 1
        for key, slider in self.mix_sliders.items():
            self.mix_values[key].setText(f"{100 * slider.value() // total} %")

    def _ist_netz(self) -> bool:
        return bool(mapgen.TEMPLATES.get(self.template.currentData(), {}).get("netz"))

    def _schedule(self):
        self.stats.setText(tr("newmap.status_working"))
        self._timer.start()

    # ------------------------------------------------------------------
    def params(self) -> mapgen.MapGenParams:
        width, height = self.size_combo.currentData()
        mix = {k: s.value() / 100.0 for k, s in self.mix_sliders.items() if s.value() > 0}
        if not mix:
            mix = {"mud": 1.0}
        # Der Landschaftsmodus haengt an der Vorlage, nicht an einem eigenen
        # Regler: er ist eine andere Bauart, kein Parameter.
        # Landscape mode is tied to the template, not to a slider of its own:
        # it is a different construction, not a parameter.
        tpl = mapgen.TEMPLATES.get(self.template.currentData(), {})
        return mapgen.MapGenParams(
            width=width, height=height, seed=self.seed.value(), mix=mix,
            roughness=self.roughness.value() / 100.0,
            symmetry=self.symmetry.currentData() or mapgen.SYM_NONE,
            spawns=self.spawns.value(),
            cliffs=self.cliffs.value() / 100.0,
            min_biome=self.min_biome.value() / 1000.0,
            biom_ruhe=self.biom_ruhe.value() / 100.0,
            grossform=self.grossform.value() / 100.0,
            gelaende_ruhe=self.gelaende_ruhe.value() / 100.0,
            lavafels=self.lavafels.value() / 100.0,
            details=self.details.value() / 100.0,
            features=[] if self._ist_netz() else self.features.features(),
            volcanoes=self.volcanoes.value(),
            vulkane=tuple(f.value() for f in self.vulkan_groessen),
            **{k: r.value() / 100.0 for k, r in self.deko.items()},
            verlauf=self.verlauf.currentData() if self._ist_netz() else "",
            verlauf_boden=tuple(b.currentData() for _x, b, _g in self.verlauf_enden),
            verlauf_gelaende=tuple(g.value() / 100.0 for _x, _b, g in self.verlauf_enden),
            berge=self.berge.value() / 100.0,
            berg_dichte=self.berg_dichte.value() / 100.0,
            schluchten=self.zonen["schluchten"].value(),
            taeler=self.zonen["taeler"].value(),
            hochebenen=self.zonen["hochebenen"].value(),
            berg_felsen=self.berg_felsen.isChecked(),
            landschaft=bool(tpl.get("landschaft", False)),
        )

    def generated(self) -> mapgen.GeneratedMap | None:
        if self._result is None:
            self._regenerate()
        return self._result

    def _regenerate(self):
        """Karte erzeugen und SOFORT in die grosse Ansicht uebernehmen."""
        if self._ist_netz():
            self._netz_start("schnell")
            return
        self.beenden()
        if self._busy:
            return
        self._busy = True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            params = self.params()
            # Der Generator von OP2MappingLib, wenn vorhanden, sonst der Python-Weg.
            # OP2MappingLib's generator when available, else the Python one.
            self._result = maplib.generieren(params) or mapgen.generate(params)
            self._window.apply_generated_map(self._result, params)
            self.stats.setText(self._summary(self._result))
        except Exception as e:
            self.stats.setText(f"{type(e).__name__}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self._busy = False

    # ------------------------------------------------------------------
    # Gelernter Generator: in einem eigenen Thread, mit Sofortvorschau
    # Learned generator: in its own thread, with an instant preview

    def _netz_start(self, stufe: str):
        """Skizze und Karte rechnen. Laeuft schon eine Rechnung, wird sie
        abgebrochen und danach neu begonnen.

        Compute sketch and map; a running computation is cancelled first."""
        self._timer.stop()
        if not mapgen_netz.verfuegbar():
            self.stats.setText(tr("newmap.netz_fehlt"))
            self._netz_knoepfe(False)
            return
        if self._worker is not None:
            self._nochmal = stufe
            self._worker.abbrechen()
            return
        params = self.params()
        sk = self._skizze[1] if self._skizze and self._skizze[0] == params else None
        mapgen_netz.setze_threads(self.netz_threads.value())
        worker = NetzWorker(params, stufe, sk)
        worker.skizze_fertig.connect(self._netz_skizze)
        worker.fortschritt.connect(self.netz_balken.setValue)
        worker.ok.connect(self._netz_fertig)
        worker.err.connect(self.stats.setText)
        worker.finished.connect(self._netz_ende)
        self._worker = worker
        self.netz_balken.setValue(0)
        self.stats.setText(tr("newmap.status_working"))
        self._netz_knoepfe(True)
        worker.start()

    def _netz_knoepfe(self, rechnet: bool):
        self.keep_btn.setEnabled(not rechnet)
        self.netz_gut.setEnabled(not rechnet)
        self.netz_stop.setEnabled(rechnet)

    def _netz_abbrechen(self):
        self._nochmal = None
        if self._worker is not None:
            self._worker.abbrechen()

    def _netz_skizze(self, sk):
        worker = self.sender()
        if worker is not self._worker:
            return
        self._skizze = (worker.params, sk)
        bild = np.ascontiguousarray(mapgen_netz.skizzenbild(sk))
        h, w = bild.shape[:2]
        pix = QPixmap.fromImage(QImage(bild.data, w, h, w * 3,
                                       QImage.Format_RGB888).copy())
        self.netz_bild.setPixmap(pix.scaled(
            max(120, self.width() - 24), 150, Qt.KeepAspectRatio, Qt.FastTransformation))

    def _netz_fertig(self, gen):
        worker = self.sender()
        if worker is not self._worker or self._nochmal is not None:
            return
        self._result = gen
        self._window.apply_generated_map(gen, worker.params)
        self.stats.setText(self._summary(gen))

    def _netz_ende(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._netz_knoepfe(False)
        stufe, self._nochmal = self._nochmal, None
        if stufe is not None and self._ist_netz():
            self._netz_start(stufe)
        elif worker is not None and worker.abgebrochen:
            self.stats.setText(tr("newmap.netz_abgebrochen"))

    def beenden(self):
        """Laufende Rechnung abbrechen und auf ihr Ende warten.
        Cancel a running computation and wait for it."""
        self._nochmal = None
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.blockSignals(True)
            worker.abbrechen()
            worker.wait()
            worker.deleteLater()
            self._netz_knoepfe(False)

    def _summary(self, gen: mapgen.GeneratedMap) -> str:
        mix = ", ".join(f"{k} {100 * v:.0f} %" for k, v in sorted(gen.family_share.items())
                        if v >= 0.01)
        parts = [tr("newmap.stat_passable", pct=round(100 * gen.passable_share)), mix]
        if gen.plateau_share > 0.005:
            parts.append(tr("newmap.stat_plateaus", pct=round(100 * gen.plateau_share),
                            n=len(gen.mesas)))
        z = gen.zonen
        if z.get("berge") or z.get("hochebenen"):
            parts.append(tr("newmap.stat_berge", n=z["berge"], h=z["hochebenen"],
                            s=z["schluchten"], pct=round(100 * z["bauplatz"])))
            if z["undicht"] or z["unerreichbar"] or z["durchfahrbar"] < z["schluchten"]:
                parts.append(tr("newmap.stat_berge_warnung", u=z["undicht"],
                                h=z["unerreichbar"],
                                s=z["schluchten"] - z["durchfahrbar"]))
        if gen.volcanoes:
            parts.append(tr("newmap.stat_volcanoes", n=len(gen.volcanoes),
                            t=sum(len(z) for z in gen.lava_zones)))
        if gen.spawns:
            parts.append(tr("newmap.stat_spawns", n=len(gen.spawns),
                            ok=tr("newmap.connected_yes") if gen.connected
                            else tr("newmap.connected_no")))
        return " · ".join(p for p in parts if p)
