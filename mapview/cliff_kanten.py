"""Die Kantenzuordnung von Hand -- welche Klippenkacheln aneinander duerfen.

Die Paartabelle aus `cliff_tiles` sagt nur, was in den 54 Originalkarten
NEBENEINANDER VORKAM. Was dort nie vorkam, kann trotzdem passen -- die Karten
sind eine Stichprobe, kein Regelwerk. Genau das ist die Luecke, die diese
Tabelle schliesst.

Jede Klippenkachel hat fuer jede ihrer vier Seiten vier Abschnitte, und jeder
Abschnitt sagt: hier grenzt Fels an (`FELS`), hier Biom (`BIOM`), oder es ist
`EGAL`. Zwei Kacheln duerfen nebeneinander, wenn ihre zugewandten Abschnitte
paarweise zusammenpassen -- gleich, oder einer davon `EGAL`.

Zugeordnet ist von Hand mit `editor/tools/kanten_zuordnen.py`, geprueft gegen
die Originalkarten mit `editor/tools/kante_gegen_alle.py`. Stand fuer mud: 156
Kacheln, 218 von 143791 Nachbarschaften widersprechen noch (0,15 %). Fuer san
und sno ist noch nichts zugeordnet -- `kennt` sagt das, und wer nichts weiss,
darf nichts verbieten.

Warum `EGAL` kein Schlupfloch ist: an vielen Abschnitten benutzen die
Originalkarten dieselbe Kante in beide Richtungen. Dort ist keine Festlegung
richtig, und `EGAL` ist die einzige zutreffende Aussage. Siehe
`docs/klippen-stand.md` Abschnitt 12.

The hand-made edge assignment: which cliff tiles may touch. The pair table only
knows what the stock maps happened to show; this one states the rule, so tiles
that never met can still be judged.
"""
from __future__ import annotations

import json
from pathlib import Path

HIER = Path(__file__).resolve().parent
MODELL_PFAD = HIER / "cliff_kanten.json"
AUTO_PFAD = HIER / "cliff_kanten_auto.json"

SEITEN = ("N", "O", "S", "W")
GEGEN = {"N": "S", "O": "W", "S": "N", "W": "O"}
BIOM, FELS, EGAL = 0, 1, 2

# Wieviele Abschnitte eine Kante hat. Muss zu `cliff_pixels.ABSCHNITTE`
# passen -- beide teilen die 32 Randpixel in vier mal acht.
ABSCHNITTE = 4


class CliffEdgeModel:
    """Die Zuordnung, mit der einzigen Frage, die zaehlt: darf a an b?"""

    def __init__(self, pfad: Path | str = MODELL_PFAD,
                 auto: Path | str | None = None):
        roh = json.loads(Path(pfad).read_text(encoding="utf-8"))
        bearbeitet = set(int(t) for t in roh.get("bearbeitet", []))
        self.kanten: dict[int, dict[str, tuple[int, ...]]] = {}
        for k, e in roh["kanten"].items():
            t = int(k)
            if t not in bearbeitet:
                continue                 # nur, was von Hand angesehen wurde
            self.kanten[t] = {s: tuple(int(x) for x in v)
                              for s, v in e.items()}
        # Die automatische Zuordnung (`cliff_kanten_auto.py`) fuellt, was
        # niemand von Hand angesehen hat -- san und sno. Die Hand hat immer
        # Vorrang.
        self.automatisch: set[int] = set()
        if auto is not None and Path(auto).exists():
            roh_a = json.loads(Path(auto).read_text(encoding="utf-8"))
            for k, e in roh_a.get("kanten", {}).items():
                t = int(k)
                if t in self.kanten:
                    continue
                self.kanten[t] = {s: tuple(int(x) for x in v)
                                  for s, v in e.items()}
                self.automatisch.add(t)
        self.abschnitte = ABSCHNITTE

    def __len__(self) -> int:
        return len(self.kanten)

    def kennt(self, kachel: int) -> bool:
        """Ist diese Kachel von Hand zugeordnet?

        Ohne Zuordnung darf die Tabelle nichts sagen -- weder ja noch nein.
        Fuer san und sno ist das derzeit alles.
        """
        return int(kachel) in self.kanten

    def seite(self, kachel: int, richtung: str) -> tuple[int, ...] | None:
        e = self.kanten.get(int(kachel))
        return e.get(richtung) if e else None

    def passt(self, a: int, b: int, richtung: str) -> bool:
        """Darf b in `richtung` an a liegen?

        Kennt die Tabelle eine der beiden nicht, ist die Antwort `True`: sie
        hat dann keine Meinung, und Unwissen darf nicht als Verbot gelten.
        """
        sa = self.seite(a, richtung)
        sb = self.seite(b, GEGEN[richtung])
        if sa is None or sb is None:
            return True
        return all(x == y or x == EGAL or y == EGAL for x, y in zip(sa, sb))

    def erlaubte(self, kachel: int, richtung: str,
                 kandidaten) -> list[int]:
        """Aus `kandidaten` die, die in `richtung` an `kachel` duerfen."""
        return [int(t) for t in kandidaten
                if self.passt(kachel, int(t), richtung)]

    def loch(self, a: int, b: int, richtung: str,
             mindestens: int = 3) -> bool:
        """Zeigen BEIDE Kacheln an dieser Naht Boden? Dann ist da ein Loch.

        Zwischen einer Klippen- und einer Bodenzelle ist Boden richtig.
        Zwischen ZWEI Klippenzellen heisst es: die Wand hoert hier auf und
        faengt daneben neu an -- ein Schnitt quer durch die Wand. Genau das
        passiert, wo zwei Blockstuecke ueberlappen, und dort stehen die
        Uebergangskacheln dann mitten in der Klippe.

        `passt` sagt dazu nichts, denn BIOM gleich BIOM gilt als passend.

        Gemessen an 176524 Naehten zwischen Klippenzellen der 54 Karten:
        ein Abschnitt Biom an Biom 10,03 %, zwei 6,11 %, drei 0,01 %, vier
        0,46 %. Ein oder zwei sind eine schraege Kante, die durch die Naht
        laeuft; ab drei ist es praktisch ausgeschlossen -- daher die
        Vorgabe 3.

        Both tiles showing ground at their shared seam means the wall stops
        here and starts again next door: a cut across the wall.
        """
        sa = self.seite(a, richtung)
        sb = self.seite(b, GEGEN[richtung])
        if sa is None or sb is None:
            return False
        n = sum(1 for x, y in zip(sa, sb) if x == BIOM and y == BIOM)
        return n >= mindestens

    def boden_an_boden(self, a: int, b: int, richtung: str) -> int:
        """Wieviele Abschnitte der Naht zeigen BEIDSEITS Boden?

        `loch` fragt dasselbe mit einer festen Schwelle. Die Zahl selbst wird
        gebraucht, wo die Schwelle nicht fest ist, sondern von der Beleglage
        des Paares abhaengt.
        """
        sa = self.seite(a, richtung)
        sb = self.seite(b, GEGEN[richtung])
        if sa is None or sb is None:
            return 0
        return sum(1 for x, y in zip(sa, sb) if x == BIOM and y == BIOM)

    def streit(self, a: int, b: int, richtung: str) -> list[int]:
        """Welche Abschnitte widersprechen sich? Leer heisst: keiner."""
        sa = self.seite(a, richtung)
        sb = self.seite(b, GEGEN[richtung])
        if sa is None or sb is None:
            return []
        return [i for i, (x, y) in enumerate(zip(sa, sb))
                if not (x == y or x == EGAL or y == EGAL)]


_zwischen: dict[str, CliffEdgeModel] = {}


def modell(pfad: Path | str = MODELL_PFAD, auto: bool = False) -> CliffEdgeModel:
    """Das Modell, einmal geladen und dann gemerkt.

    `auto` nimmt die automatische Zuordnung (`cliff_kanten_auto.json`) fuer
    alle nicht von Hand bearbeiteten Kacheln dazu. Nur der Gelaende-Loeser
    (`klippe_algo`) fragt danach; der Blockweg in `mapgen` bleibt bei der
    Hand -- mit der automatischen fielen dort fuenf san-Pruefungen
    (Fortsetzung, Eckblock, T-Stoss).
    """
    s = (str(pfad), bool(auto))
    if s not in _zwischen:
        _zwischen[s] = CliffEdgeModel(pfad, AUTO_PFAD if auto else None)
    return _zwischen[s]
