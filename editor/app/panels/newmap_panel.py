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

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSlider, QScrollArea

from ..common import *
from ..style import apply_role
from .feature_list import FeatureList

import mapgen

# Auswaehlbare Kartengroessen -- die Breite steckt als Zweierpotenz im
# Dateikopf, deshalb keine freien Werte.
# Selectable map sizes -- the width is stored as a power of two in the file
# header, hence no free values.
SIZES = [(64, 64), (128, 64), (128, 128), (256, 128), (256, 256), (512, 256)]

TEMPLATE_KEYS = ["plains", "canyon", "desert", "islands", "ice", "newterra"]
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

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        form = QFormLayout(inner)

        self.size_combo = QComboBox()
        for w, h in SIZES:
            self.size_combo.addItem(f"{w} × {h}", (w, h))
        self.size_combo.setCurrentIndex(2)
        form.addRow(tr("newmap.lbl_size"), self.size_combo)

        self.template = QComboBox()
        for key in TEMPLATE_KEYS:
            self.template.addItem(tr(f"newmap.tpl_{key}"), key)
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
        form.addRow(tr("newmap.lbl_min_biome"), min_box)

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
        form.addRow(tr("newmap.lbl_cliffs"), self.cliffs)

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
        for widget in (self.size_combo, self.symmetry):
            widget.currentIndexChanged.connect(self._schedule)
        for widget in (self.seed, self.spawns, self.volcanoes):
            widget.valueChanged.connect(self._schedule)
        self.roughness.valueChanged.connect(self._schedule)
        self.cliffs.valueChanged.connect(self._schedule)
        self.details.valueChanged.connect(self._schedule)
        self.min_biome.valueChanged.connect(self._on_min_biome)
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
        if self._result is None:
            self._regenerate()
        self._window.close_newmap_panel(keep=True)

    def discard(self):
        """Vorherige Karte wiederherstellen und das Panel schliessen."""
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
        self._update_mix_labels()
        self._schedule()

    def _on_min_biome(self):
        self.min_biome_value.setText(f"{self.min_biome.value() / 10:.1f} %")
        self._schedule()

    def _on_mix_changed(self):
        self._update_mix_labels()
        self._schedule()

    def _update_mix_labels(self):
        total = sum(s.value() for s in self.mix_sliders.values()) or 1
        for key, slider in self.mix_sliders.items():
            self.mix_values[key].setText(f"{100 * slider.value() // total} %")

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
            details=self.details.value() / 100.0,
            features=self.features.features(),
            volcanoes=self.volcanoes.value(),
            landschaft=bool(tpl.get("landschaft", False)),
        )

    def generated(self) -> mapgen.GeneratedMap | None:
        if self._result is None:
            self._regenerate()
        return self._result

    def _regenerate(self):
        """Karte erzeugen und SOFORT in die grosse Ansicht uebernehmen."""
        if self._busy:
            return
        self._busy = True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            params = self.params()
            self._result = mapgen.generate(params)
            self._window.apply_generated_map(self._result, params)
            self.stats.setText(self._summary(self._result))
        except Exception as e:
            self.stats.setText(f"{type(e).__name__}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self._busy = False

    def _summary(self, gen: mapgen.GeneratedMap) -> str:
        mix = ", ".join(f"{k} {100 * v:.0f} %" for k, v in sorted(gen.family_share.items())
                        if v >= 0.01)
        parts = [tr("newmap.stat_passable", pct=round(100 * gen.passable_share)), mix]
        if gen.plateau_share > 0.005:
            parts.append(tr("newmap.stat_plateaus", pct=round(100 * gen.plateau_share),
                            n=len(gen.mesas)))
        if gen.volcanoes:
            parts.append(tr("newmap.stat_volcanoes", n=len(gen.volcanoes),
                            t=sum(len(z) for z in gen.lava_zones)))
        if gen.spawns:
            parts.append(tr("newmap.stat_spawns", n=len(gen.spawns),
                            ok=tr("newmap.connected_yes") if gen.connected
                            else tr("newmap.connected_no")))
        return " · ".join(p for p in parts if p)
