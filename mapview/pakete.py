"""Detail-Pakete: fertige Bausaetze aus Detailkacheln (Wrackteile, Steine,
Krater, Risse, Schutt) mit fester Anordnung.

Ein Paket speichert nur die Details, nicht den Boden darunter -- gesetzt wird
es auf vorhandenen Boden derselben Art (Erde, Fels oder Sand). Drehen und
Spiegeln geht nicht: die Kacheln haben Licht und Schatten von einer festen
Seite.

Quellen:
- `pakete.json`: aus den Originalkarten ausgeschnittene Gruppen (Absturz-
  stellen, Steinfelder, Kraterfelder ...), erzeugt mit
  `python pakete.py <Spielordner>`.
- `pakete_eigene.json` neben der config.ini: selbst gebaute Pakete aus dem
  Editor ("Bereich als Paket speichern").

Detail packages: ready-made assemblies of detail tiles with a fixed layout.
A package stores only the details, never the ground; it is placed on
existing ground of the same kind. No rotation or mirroring -- the tiles are
lit from one side.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import kachelgruppen as kg

PFAD = Path(__file__).with_name("pakete.json")

WRACK, STEIN, KRATER, RISS, RUINE = "wrack", "stein", "krater", "riss", "ruine"
ARTEN = (WRACK, STEIN, KRATER, RISS, RUINE)
BOEDEN = ("mud", "roc", "san")


@dataclass
class Paket:
    name: str
    art: str
    boden: str
    breite: int
    hoehe: int
    teile: list = field(default_factory=list)      # [(dx, dy, kachel)]
    quelle: str = ""
    eigen: bool = False

    def als_dict(self) -> dict:
        return {"name": self.name, "art": self.art, "boden": self.boden,
                "breite": self.breite, "hoehe": self.hoehe,
                "teile": [list(t) for t in self.teile], "quelle": self.quelle}

    @classmethod
    def aus_dict(cls, d: dict, eigen: bool = False) -> "Paket":
        return cls(str(d["name"]), str(d.get("art", STEIN)), str(d.get("boden", "mud")),
                   int(d["breite"]), int(d["hoehe"]),
                   [tuple(int(v) for v in t) for t in d.get("teile", [])],
                   str(d.get("quelle", "")), eigen)

    def raster(self) -> np.ndarray:
        """(hoehe, breite) mit Kachelnummern, -1 = Boden bleibt."""
        r = np.full((self.hoehe, self.breite), -1, dtype=np.int32)
        for dx, dy, k in self.teile:
            r[dy, dx] = k
        return r


# ---------------------------------------------------------------------------
# Welche Kachel ist ein Detail, und welcher Art? / which tile is a detail

_THEMA: dict[int, str] | None = None


def _art_aus_name(name: str) -> str | None:
    rest = name.lower()
    for praefix in ("snow", "snw", "mud", "roc", "san"):
        if rest.startswith(praefix):
            rest = rest[len(praefix):]
            break
    else:
        return None
    if rest.startswith("wrk"):
        return WRACK
    if rest.startswith(("crk", "crac")):
        return RISS
    if rest.startswith("crat"):
        return KRATER
    if rest.startswith(("rock", "roc", "rok")):
        return STEIN
    if rest.startswith(("rub", "burn", "doz")):
        return RUINE
    return None


def themen() -> dict[int, str]:
    """Kachelnummer -> Art, fuer alle Detailkacheln."""
    global _THEMA
    if _THEMA is None:
        _THEMA = {}
        for name, block in kg.alle().items():
            art = _art_aus_name(name)
            if art is None or name.lower().startswith(("snow", "snw")):
                continue
            for k in np.asarray(block).ravel():
                _THEMA.setdefault(int(k), art)
    return _THEMA


def ist_detail(kachel: int) -> bool:
    return int(kachel) in themen()


def _hauptart(arten: list[str]) -> str:
    from collections import Counter
    c = Counter(arten)
    if c.get(WRACK, 0) >= max(2, len(arten) // 4):
        return WRACK                  # Wrackteile praegen eine Stelle sofort
    return c.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Bibliothek / library

def _eigene_pfad() -> Path:
    try:
        import appconfig
        return appconfig.base_dir() / "pakete_eigene.json"
    except Exception:
        return Path(__file__).resolve().parent.parent / "pakete_eigene.json"


def laden() -> list[Paket]:
    """Eingebaute und eigene Pakete."""
    out = []
    for pfad, eigen in ((PFAD, False), (_eigene_pfad(), True)):
        try:
            for d in json.loads(pfad.read_text("utf-8")):
                out.append(Paket.aus_dict(d, eigen))
        except (OSError, ValueError, KeyError):
            pass
    return out


def eigene_speichern(paket: Paket) -> Path:
    pfad = _eigene_pfad()
    try:
        daten = json.loads(pfad.read_text("utf-8"))
    except (OSError, ValueError):
        daten = []
    daten = [d for d in daten if d.get("name") != paket.name]
    daten.append(paket.als_dict())
    pfad.write_text(json.dumps(daten, indent=1, ensure_ascii=False), "utf-8")
    return pfad


def eigenes_loeschen(name: str) -> bool:
    pfad = _eigene_pfad()
    try:
        daten = json.loads(pfad.read_text("utf-8"))
    except (OSError, ValueError):
        return False
    rest = [d for d in daten if d.get("name") != name]
    if len(rest) == len(daten):
        return False
    pfad.write_text(json.dumps(rest, indent=1, ensure_ascii=False), "utf-8")
    return True


# ---------------------------------------------------------------------------
# Aus einem Kartenausschnitt / from a map area

def aus_bereich(kacheln: np.ndarray, familie_von, name: str = "",
                quelle: str = "") -> Paket | None:
    """Detailkacheln eines Ausschnitts als Paket. `familie_von(kachel)` liefert
    den Boden ("mud"/"roc"/"san"/...) einer Kachel; der Boden des Pakets ist
    die Mehrheit der NICHT-Details im Ausschnitt.

    Detail tiles of a map area as a package; its ground is the majority of
    the non-detail tiles in the area."""
    from collections import Counter
    th = themen()
    ys, xs = np.nonzero(np.vectorize(lambda k: int(k) in th)(kacheln))
    if len(xs) == 0:
        return None
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()
    rest = [familie_von(int(k)) for k in kacheln.ravel() if int(k) not in th]
    boden = Counter(f for f in rest if f in BOEDEN).most_common(1)
    if not boden:
        # Nur Details im Ausschnitt: der Boden der Detailkacheln selbst
        boden = Counter(familie_von(int(kacheln[y, x])) for y, x in zip(ys, xs)
                        if familie_von(int(kacheln[y, x])) in BOEDEN).most_common(1)
    boden = boden[0][0] if boden else "mud"
    teile = [(int(x - x0), int(y - y0), int(kacheln[y, x])) for y, x in zip(ys, xs)]
    art = _hauptart([th[k] for _, _, k in teile])
    return Paket(name or art, art, boden, int(x1 - x0 + 1), int(y1 - y0 + 1), teile, quelle, True)


# ---------------------------------------------------------------------------
# Aus den Originalkarten / from the stock maps

def auslesen(spielordner, tm, max_je_art: int = 10) -> list[Paket]:
    """Zusammenhaengende Detailgruppen der Originale als Pakete."""
    from collections import Counter, defaultdict
    from scipy import ndimage as ndi
    from op2map import Op2Map
    th = themen()
    namen = tm.families

    def familie_von(k):
        f = int(tm.family_of[k]) if 0 <= k < len(tm.family_of) else -1
        return namen[f] if 0 <= f < len(namen) else ""

    gesehen = set()
    kandidaten = defaultdict(list)
    for pfad in sorted(Path(spielordner).rglob("*.map")):
        if "backups" in str(pfad).lower() or pfad.stem.lower().startswith("klippentest"):
            continue
        m = Op2Map(pfad.read_bytes())
        g = np.array([[m.tile_mapping_index(x, y) for x in range(m.width)]
                      for y in range(m.height)], dtype=np.int32)
        detail = np.isin(g, list(th))
        lab, n = ndi.label(ndi.binary_dilation(detail, iterations=2))
        for i in range(1, n + 1):
            teil = (lab == i) & detail
            anzahl = int(teil.sum())
            if anzahl < 4:
                continue
            ys, xs = np.nonzero(teil)
            x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()
            if x1 - x0 > 26 or y1 - y0 > 26 or x0 < 2 or y0 < 2 \
                    or x1 > m.width - 3 or y1 > m.height - 3:
                continue
            ausschnitt = g[y0:y1 + 1, x0:x1 + 1]
            maske = teil[y0:y1 + 1, x0:x1 + 1]
            boden = Counter(familie_von(int(k)) for k in ausschnitt[~maske].ravel())
            boden_name, boden_n = (boden.most_common(1) or [("", 0)])[0]
            if boden_name not in BOEDEN or boden_n < 0.8 * max(1, (~maske).sum()):
                continue                       # gemischter Boden: kein sauberes Paket
            teile = [(int(x - x0), int(y - y0), int(g[y, x])) for y, x in zip(ys, xs)]
            schl = frozenset(teile)
            if schl in gesehen:
                continue                       # Eden/Plymouth teilen Karten
            gesehen.add(schl)
            if anzahl < 10 and anzahl / float((x1 - x0 + 1) * (y1 - y0 + 1)) < 0.05:
                continue                       # zu duenn: das ist Streugut, kein Bausatz
            gruppen = len({k for _, _, k in teile})
            art = _hauptart([th[k] for _, _, k in teile])
            kandidaten[(boden_name, art)].append(
                (anzahl * min(gruppen, 6), Paket(
                    "", art, boden_name, int(x1 - x0 + 1), int(y1 - y0 + 1), teile,
                    f"{pfad.stem} ({x0},{y0})")))
    def aehnlich(a: Paket, b: Paket) -> bool:
        """Fast dieselbe Gruppe, nur verschoben ausgeschnitten?"""
        ka = Counter(k for _, _, k in a.teile)
        kb = Counter(k for _, _, k in b.teile)
        gemeinsam = sum((ka & kb).values())
        return gemeinsam >= 0.7 * min(sum(ka.values()), sum(kb.values()))

    pakete = []
    for (boden_name, art), liste in sorted(kandidaten.items()):
        liste.sort(key=lambda t: -t[0])
        gewaehlt: list[Paket] = []
        for _, p in liste:
            if any(aehnlich(p, q) for q in gewaehlt):
                continue
            gewaehlt.append(p)
            if len(gewaehlt) >= max_je_art:
                break
        for nr, p in enumerate(gewaehlt, 1):
            p.name = f"{boden_name}-{art}-{nr:02d}"
            pakete.append(p)
    return pakete


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mapgen
    pakete = auslesen(sys.argv[1], mapgen.model())
    PFAD.write_text(json.dumps([p.als_dict() for p in pakete], indent=1), "utf-8")
    from collections import Counter
    print(len(pakete), "Pakete:", dict(Counter((p.boden, p.art) for p in pakete)))
