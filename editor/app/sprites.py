"""Echte Spielgrafik fuer Fahrzeuge und Gebaeude (op2_art.prt + OP2_ART.BMP).

- op2_art.prt: Paletten, Bild-Metadaten und Animationen (Format wie in
  OP2Utility/ArtFile). OPU legt sie unter OPU/base/sprites/ ab.
- OP2_ART.BMP: alle Bilder als 8-Bit-Pixel in einer grossen Datei.
- resources/unit_anims.json: welcher Animations-Index zu welchem Typ gehoert,
  getrennt nach Eden und Plymouth (aus den Tabellen in Outpost2.exe gelesen).
- color.bmp: die sechs Spielerfarben (je 24 Paletteneintraege), mit denen
  die Bereiche 1..23 der Einheiten-Palette ersetzt werden.

Fehlt etwas davon, liefert `SpriteSatz.bild()` None und der Editor zeichnet
wie bisher farbige Rechtecke.

Real game graphics for vehicles and buildings. Missing files -> None, the
editor then falls back to coloured rectangles.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

HERE = Path(__file__).resolve().parent

# Index 5 = Normalansicht bei Gebaeuden; Fahrzeuge: Richtung (0 = Osten,
# im Uhrzeigersinn in 22,5-Grad-Schritten). 2 = Suedost wirkt am natuerlichsten.
GEBAEUDE_NORMAL = 5
FAHRZEUG_RICHTUNG = 2
_SPIELERFARBEN_STANDARD = [          # Fallback, falls color.bmp fehlt
    (7, 7, 147), (147, 8, 7), (8, 147, 7), (147, 147, 7), (7, 145, 147), (145, 7, 147),
]


def _finde(wurzeln, namen) -> Path | None:
    """Datei case-insensitiv in mehreren Ordnern suchen."""
    for w in wurzeln:
        w = Path(w)
        if not w.is_dir():
            continue
        klein = {p.name.lower(): p for p in w.iterdir() if p.is_file()}
        for n in namen:
            if n.lower() in klein:
                return klein[n.lower()]
    return None


class SpriteSatz:
    def __init__(self, spielordner):
        g = Path(spielordner)
        self._prt = _finde([g / "OPU" / "base" / "sprites", g, g / "sprites"], ["op2_art.prt"])
        self._bmp = _finde([g, g / "OPU" / "base" / "sprites", g / "OPU"], ["OP2_ART.BMP"])
        self._farben = _finde([g / "OPU" / "base" / "sprites", g], ["color.bmp"])
        self._geladen = False
        self._ok = False
        self._cache: dict = {}
        try:
            self._tabelle = json.loads((HERE / "resources" / "unit_anims.json").read_text("utf-8"))
        except Exception:
            self._tabelle = {}

    @property
    def verfuegbar(self) -> bool:
        self._laden()
        return self._ok

    # ------------------------------------------------------------------
    def _laden(self):
        if self._geladen:
            return
        self._geladen = True
        if not (self._prt and self._bmp and self._tabelle):
            return
        try:
            self._prt_lesen(self._prt.read_bytes())
            self._pixel = self._bmp.read_bytes()
            self._spielerfarben = self._farben_lesen()
            self._ok = True
        except Exception as e:                  # kaputte/fremde Datei: Rechtecke
            import sys
            print(f"Sprites nicht geladen: {e}", file=sys.stderr)
            self._ok = False

    def _prt_lesen(self, d: bytes):
        p = 0
        tag, n = struct.unpack_from("<4sI", d, p)
        if tag != b"CPAL":
            raise ValueError("op2_art.prt: kein CPAL-Kopf")
        p += 8
        self._paletten = []
        for _ in range(n):
            p += 28                                     # PPAL/head/data-Kopf
            self._paletten.append([tuple(d[p + 4 * k:p + 4 * k + 3]) for k in range(256)])
            p += 1024
        nb = struct.unpack_from("<I", d, p)[0]
        p += 4
        self._bilder = [struct.unpack_from("<IIIIHH", d, p + 20 * k) for k in range(nb)]
        p += 20 * nb
        na = struct.unpack_from("<I", d, p)[0]
        p += 16
        self._anims = []
        for _ in range(na):
            p += 4 + 16                                 # unknown + selectionRect
            dx, dy = struct.unpack_from("<2i", d, p)
            p += 8 + 4
            fc = struct.unpack_from("<I", d, p)[0]
            p += 4
            erstes = None
            for f in range(fc):
                lm, ub = d[p], d[p + 1]
                p += 2
                if lm & 0x80:
                    p += 2
                if ub & 0x80:
                    p += 2
                ebenen = []
                for _l in range(lm & 0x7F):
                    bi, _u, _fi, ox, oy = struct.unpack_from("<HBBhh", d, p)
                    p += 8
                    ebenen.append((bi, ox, oy))
                if f == 0:
                    erstes = ebenen
            nuc = struct.unpack_from("<I", d, p)[0]
            p += 4 + 16 * nuc
            self._anims.append(((dx, dy), erstes or []))

    def _farben_lesen(self):
        if self._farben is None:
            return None
        d = self._farben.read_bytes()
        pal = d[54:54 + 1024]
        gruppen = []
        for g in range(6):
            gruppen.append([(pal[(g * 24 + i) * 4 + 2], pal[(g * 24 + i) * 4 + 1],
                             pal[(g * 24 + i) * 4]) for i in range(24)])
        return gruppen

    # ------------------------------------------------------------------
    def _palette(self, nr: int, spieler: int):
        pal = list(self._paletten[nr])
        # Spielerfarbe: Paletten mit dem blauen Standardbereich 1..23 umfaerben.
        gruppen = self._spielerfarben
        if gruppen and pal[1:24] == gruppen[0][1:24] and spieler > 0:
            pal[1:24] = gruppen[spieler % 6][1:24]
        return pal

    def _bild(self, index: int, spieler: int) -> QImage | None:
        sl, off, h, w, typ, palnr = self._bilder[index]
        start = off + 14 + 40 + 1024
        daten = bytes(self._pixel[start:start + sl * h])
        if len(daten) < sl * h:
            return None
        if typ & 4:                                     # Schatten, 1 Bit
            img = QImage(daten, w, h, sl, QImage.Format_Mono)
            img.setColorTable([0, QColor(0, 0, 0, 110).rgba()])
        else:
            img = QImage(daten, w, h, sl, QImage.Format_Indexed8)
            pal = self._palette(palnr, spieler)
            img.setColorTable([0] + [QColor(*pal[i]).rgba() for i in range(1, 256)])
        # Kopie: QImage teilt sonst den Python-Puffer.
        return img.convertToFormat(QImage.Format_ARGB32_Premultiplied)

    def _anim_index(self, map_id: str, plymouth: bool) -> int | None:
        if not self._tabelle:
            return None
        volk = "plymouth" if plymouth else "eden"
        andere = "eden" if plymouth else "plymouth"
        for v in (volk, andere):
            liste = self._tabelle.get(v, {}).get(map_id)
            if not liste:
                continue
            if len(liste) == 16:                         # Fahrzeug
                i = liste[FAHRZEUG_RICHTUNG] if liste[FAHRZEUG_RICHTUNG] is not None else liste[0]
            else:
                i = liste[GEBAEUDE_NORMAL] if len(liste) > GEBAEUDE_NORMAL else None
            if i is not None and i >= 0:
                return i
        return None

    def bild(self, map_id: str, plymouth: bool, spieler: int = 0):
        """(QPixmap, QPoint) -- Bild und Versatz zur Mitte der Bezugskachel,
        oder None, wenn es fuer diesen Typ keine Grafik gibt."""
        schl = (map_id, plymouth, spieler)
        if schl in self._cache:
            return self._cache[schl]
        self._laden()
        erg = None
        if self._ok:
            a = self._anim_index(map_id, plymouth)
            if a is not None and 0 <= a < len(self._anims):
                (dx, dy), ebenen = self._anims[a]
                erg = self._zusammensetzen(ebenen, dx, dy, spieler)
        self._cache[schl] = erg
        return erg

    def _zusammensetzen(self, ebenen, dx, dy, spieler):
        if not ebenen:
            return None
        teile = []
        for bi, ox, oy in ebenen:
            if 0 <= bi < len(self._bilder):
                im = self._bild(bi, spieler)
                if im is not None:
                    teile.append((im, ox, oy))
        if not teile:
            return None
        x0 = min(ox for _i, ox, _oy in teile)
        y0 = min(oy for _i, _ox, oy in teile)
        x1 = max(ox + i.width() for i, ox, _oy in teile)
        y1 = max(oy + i.height() for i, _ox, oy in teile)
        ges = QImage(x1 - x0, y1 - y0, QImage.Format_ARGB32_Premultiplied)
        ges.fill(0)
        p = QPainter(ges)
        # Schatten zuerst, dann die Farbbilder darueber.
        for im, ox, oy in teile:
            p.drawImage(ox - x0, oy - y0, im)
        p.end()
        return QPixmap.fromImage(ges), QPoint(x0 - dx, y0 - dy)
