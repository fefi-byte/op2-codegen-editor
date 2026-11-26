"""Forschungsbaum (Tech-Datei, z.B. multitek.txt) lesen, aendern, schreiben, pruefen.

Ohne Qt, damit Tests und Codegen es nutzen koennen.

Dateiaufbau je Thema:

    BEGIN_TECH "Name" 03401
        CATEGORY        4
        DESCRIPTION     "..."
        REQUIRES        03402          (mehrfach moeglich)
        EDEN_COST       800            (oder COST fuer beide Kolonien)
        PLYMOUTH_COST   1000
        MAX_SCIENTISTS  10
        LAB             2
        UNIT_PROP CON_TRUCK Hit_Points 375
    END_TECH

Rundreise: ein Thema, das nicht geaendert wurde, wird Byte fuer Byte so
geschrieben, wie es gelesen wurde (Kommentare, Leerzeichen, CRLF). Auch Text
zwischen den Themen (Kopfkommentar, Gruppenueberschriften, der Pruefsummen-
Anhang der OPU-Dateien) bleibt unveraendert. Nur geaenderte Themen werden neu
formatiert, im Stil der Originaldateien. Unbekannte Zeilen in einem Thema
(PLAYER_PROP, FUNCTION_RESULT, Kommentare) bleiben dabei erhalten.

Reads, edits, writes and checks Outpost 2 tech tree files. An unchanged topic
is written back byte for byte; only edited topics are reformatted, keeping
their unknown lines.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

# --- Grenzen des Spiels / the game's limits ---------------------------------
MAX_TECHS = 256
MAX_NAME = 100
MAX_TEXT = 800            # DESCRIPTION, TEASER, IMPROVE_DESC
MAX_REQUIRES = 32
MAX_UPGRADES = 32         # UNIT_PROP + PLAYER_PROP + FUNCTION_RESULT
SCIENTISTS_RANGE = (4, 18)  # 1 nur fuer Sonderthemen / 1 for special topics
LABS = (1, 2, 3)

# Kategorien = Symbol im Forschungsmenue des Spiels. Keys for tr("techtree.cat_N").
CATEGORIES = tuple(range(13))

# Die 19 Eigenschaften, die UNIT_PROP setzen kann, in der Reihenfolge der
# Tabelle im Spiel (Outpost2.exe 0x4D5C48). Je Eintrag: Name, Stelle im
# Wertesatz der Einheit, fuer welche Art sie gilt. Mehrere Namen teilen sich
# eine Stelle; was sie bedeutet, haengt von der Art ab (Fahrzeug, Gebaeude,
# Waffe). Quelle: op2-rs tools/crates/op2-sim/src/upgrades.rs.
# The 19 UNIT_PROP properties in the game's table order, with the offset in a
# unit type's per-player stats and the kind they are meant for.
PROPERTIES: tuple[tuple[str, int, str], ...] = (
    ("Hit_Points", 0x00, "all"),
    ("Armor", 0x08, "all"),
    ("Production_Capacity", 0x34, "building"),
    ("Move_Speed", 0x24, "vehicle"),
    ("Sight_Range", 0x18, "all"),
    ("Rate_Of_Fire", 0x30, "weapon"),
    ("Build_Time", 0x14, "all"),
    ("Power_Required", 0x24, "building"),
    ("Storage_Capacity", 0x30, "building"),
    ("Storage_Bays", 0x38, "building"),
    ("Production_Rate", 0x2C, "vehicle"),
    ("Concussion_Damage", 0x28, "weapon"),
    ("Penetration_Damage", 0x2C, "weapon"),
    ("Improved", 0x1D, "building"),
    ("Workers_Required", 0x28, "building"),
    ("Common_Required", 0x0C, "all"),
    ("Rare_Required", 0x10, "all"),
    ("Turn_Rate", 0x28, "vehicle"),
    ("Build_Points", 0x14, "all"),
)
PROPERTY_NAMES = tuple(p[0] for p in PROPERTIES)
ARMOR_RANGE = (0, 5)

# Welche Eigenschaften zu welcher Art Einheit passen, und wie sie dort heissen
# (Schluessel fuer tr("techtree.pl_<name>")). Die Art kommt aus der
# Regel-Tabelle, in der die Einheit steht. Grundlage: die Stelle im Wertesatz
# (op2-rs upgrades.rs apply_unit/apply_weapon) und die Nutzung in den
# OPU-Baeumen. Bei Waffen ist Sight_Range die Reichweite, Rate_Of_Fire die
# Nachladezeit und Move_Speed das Drehtempo des Turms.
# Which properties fit which kind of unit, and what they are called there.
KIND_PROPERTIES: dict[str, tuple[tuple[str, str], ...]] = {
    "vehicle": (
        ("Hit_Points", "hp"), ("Armor", "armor"), ("Move_Speed", "speed"),
        ("Turn_Rate", "turn"), ("Sight_Range", "sight"), ("Production_Rate", "workrate"),
        ("Common_Required", "common"), ("Rare_Required", "rare"), ("Build_Time", "buildtime"),
    ),
    "building": (
        ("Hit_Points", "hp"), ("Armor", "armor"), ("Sight_Range", "sight"),
        ("Production_Capacity", "output"), ("Power_Required", "power"),
        ("Workers_Required", "workers"), ("Storage_Capacity", "storage"),
        ("Storage_Bays", "bays"), ("Improved", "improved"),
        ("Common_Required", "common"), ("Rare_Required", "rare"), ("Build_Points", "buildtime"),
    ),
    "weapon": (
        ("Concussion_Damage", "concussion"), ("Penetration_Damage", "penetration"),
        ("Sight_Range", "range"), ("Rate_Of_Fire", "reload"), ("Move_Speed", "turret"),
        ("Common_Required", "common"), ("Rare_Required", "rare"),
    ),
    "space": (
        ("Common_Required", "common"), ("Rare_Required", "rare"), ("Build_Time", "buildtime"),
    ),
}
KINDS = tuple(KIND_PROPERTIES)


def unit_kind(sheets: dict, code: str) -> str | None:
    """'vehicle' | 'building' | 'weapon' | 'space' oder None (unbekannt)."""
    entry = sheets.get(code) if sheets else None
    return entry[0] if entry else None


def props_for(kind: str | None) -> tuple[tuple[str, str | None], ...]:
    """Passende Eigenschaften (Name, Bezeichnungs-Schluessel) einer Art;
    unbekannte Art: alle 19 ohne eigene Bezeichnung."""
    if kind in KIND_PROPERTIES:
        return KIND_PROPERTIES[kind]
    return tuple((name, None) for name in PROPERTY_NAMES)


def prop_fits(kind: str | None, prop: str) -> bool:
    return kind is None or any(p == prop for p, _ in props_for(kind))

# Spalte der Regel-Tabelle (OPU/base/sheets), aus der der Grundwert einer
# Eigenschaft kommt -- je Art. Die Kopfzeilen der Tabellen sind zweizeilig;
# hier steht beides mit Leerzeichen verbunden.
# Sheet column holding a property's base value, per kind of sheet.
SHEET_COLUMNS: dict[str, dict[str, str]] = {
    "vehicle": {
        "Hit_Points": "Hit Points", "Armor": "Armor Class", "Move_Speed": "Move Points",
        "Turn_Rate": "Turn Rate", "Common_Required": "Common Ore Cost",
        "Rare_Required": "Rare Ore Cost", "Build_Time": "Build Time",
        "Build_Points": "Build Time", "Sight_Range": "Sight range",
        "Production_Rate": "Production Rate", "Storage_Capacity": "Cargo Capacity",
    },
    "building": {
        "Hit_Points": "Hit Points", "Armor": "Armor Class", "Common_Required": "Common Ore Cost",
        "Rare_Required": "Rare Ore Cost", "Build_Points": "Building Points",
        "Build_Time": "Building Points", "Power_Required": "Power required",
        "Workers_Required": "Workers required", "Sight_Range": "Sight range",
        "Storage_Capacity": "Storage Capacity", "Production_Capacity": "Production Capacity",
        "Storage_Bays": "Storage Bays",
    },
    "weapon": {
        "Concussion_Damage": "Concussion Damage", "Penetration_Damage": "Penetration Damage",
        "Common_Required": "Common Ore Cost", "Rare_Required": "Rare Ore Cost",
        "Sight_Range": "Weapon Range in tiles", "Rate_Of_Fire": "Reload Time",
        "Build_Time": "Build Time", "Move_Speed": "Turret Turn Rate",
        "Power_Required": "Turret Turn Rate",
    },
    "space": {
        "Common_Required": "Common Ore Cost", "Rare_Required": "Rare Ore Cost",
        "Build_Time": "Build Time", "Build_Points": "Build Time",
    },
}
SHEET_FILES = {"vehicle": "vehicles.txt", "building": "building.txt", "weapon": "weapons.txt",
               "space": "space.txt"}

# Namen der Einheiten-Codes, wie das Spiel sie zeigt (nur zur Anzeige). Die
# Raumschiff-Teile SPACE_n sind ueber ihr Forschungsthema in space.txt
# zugeordnet; Codes ohne sicheren Namen bleiben ohne (dann steht der Code).
# Display names of the unit codes, as the game shows them.
UNIT_NAMES: dict[str, str] = {
    # Fahrzeuge / vehicles
    "LIGHT_TANK": "Lynx", "MED_TANK": "Panther", "BIG_TANK": "Tiger", "SCOUT": "Scout",
    "CON_TRUCK": "ConVec", "BIG_TRUCK": "Cargo Truck", "MOBILE_HOME": "Evacuation Transport",
    "MINER": "Robo-Miner", "SURVEYOR": "Robo-Surveyor", "BULL_DOZER": "Robo-Dozer",
    "WALL_TRUCK": "Earthworker", "REPAIR_TRUCK": "Repair Vehicle", "GEO_METRO": "GeoCon",
    "SPIDER": "Spider", "SCORPION": "Scorpion",
    # Gebaeude / buildings
    "COMMAND": "Command Center", "TOKAMAK": "Tokamak", "SOLAR": "Solar Power Array",
    "GEOTHERMAL": "Geothermal Plant", "ASE": "MHD Generator", "MINE": "Common Ore Mine",
    "MINE_ADV": "Rare Ore Mine", "MAGMA_WELL": "Magma Well", "SMELTER": "Common Ore Smelter",
    "SMELTER_ADV": "Rare Ore Smelter", "GORF": "GORF", "RESIDENCE": "Residence",
    "RESIDENCE_E": "Reinforced Residence", "RESIDENCE_P": "Advanced Residence",
    "AGRIDOME": "Agridome", "MED_CENTER": "Medical Center", "NURSERY": "Nursery",
    "UNIVERSITY": "University", "RECREATION": "Recreation Facility", "FORUM": "Forum",
    "DIRT": "DIRT", "LAB": "Basic Lab", "LAB_STANDARD": "Standard Lab",
    "LAB_ADV": "Advanced Lab", "OBSERVATORY": "Observatory", "METEOR_DEF": "Meteor Defense",
    "TRADE": "Trade Center", "FACT_STRUCTURE": "Structure Factory",
    "FACT_VEHICLE": "Vehicle Factory", "FACT_ANDROID": "Arachnid Factory",
    "FACT_LUXURY": "Consumer Factory", "GARAGE": "Garage", "SPACEPORT": "Spaceport",
    "ROBOT_COMMAND": "Robot Command Center", "TOWER_GUARD": "Guard Post",
    "TOWER_LIGHT": "Light Tower", "STORAGE_ORE": "Common Storage",
    "STORAGE_RARE": "Rare Storage", "TUBE": "Tube", "WALL": "Wall",
    "WALL_LAVA": "Lava Wall", "WALL_MICROBE": "Microbe Wall",
    # Waffen / weapons
    "LASER": "Laser", "MICROWAVE": "Microwave", "RAIL_GUN": "Rail Gun", "CANNON": "RPG",
    "ACID": "Acid Cloud", "EMP": "EMP", "FOAM": "Sticky Foam", "SPAM": "ESG",
    "THORS_HAMMER": "Thor's Hammer", "SCORPION_WEAPON": "Energy Cannon (Scorpion)",
    "TURRET_DESTRUCT": "Starflare", "TURRET_DESTRUCT_ADV": "Supernova",
    "SELF_DESTRUCT": "Self-Destruct", "SELF_DESTRUCT_ADV": "Self-Destruct (advanced)",
    "SCUTTLE_DESTRUCT": "Scuttle",
    # Effekte in der Waffen-Tabelle / effects in the weapons sheet
    "EMP_BIG": "EMP blast (large)", "AMBIENT_ANIM": "Ambient animation", "BEACON": "Beacon",
    "BLD_EXPL_SML": "Building explosion (small)", "BLD_EXPL_MED": "Building explosion (medium)",
    "BLD_EXPL_BIG": "Building explosion (large)", "EARTHQUAKE": "Earthquake",
    "ERUPTION": "Volcanic eruption", "FUMAROLE": "Fumarole", "LIGHTNING": "Electrical storm",
    "MAGMA_VENT": "Magma vent", "METEOR": "Meteor", "TORNADO": "Vortex", "SHUTTLE": "Shuttle",
    # Raumfahrt / space
    "EDWARD": "EDWARD Satellite", "EMP_MISSILE": "EMP Missile", "SULV": "SULV",
    "RLV": "RLV (Reusable Launch Vehicle)", "SOLAR_SAT": "Solar Power Satellite",
    "SPACE_1": "Ion Drive Module", "SPACE_2": "Fusion Drive Module",
    "SPACE_3": "Command Module", "SPACE_4": "Fueling Systems", "SPACE_5": "Habitat Ring",
    "SPACE_6": "Sensor Package", "SPACE_7": "Skydock", "SPACE_8": "Stasis Systems",
    "SPACE_9": "Orbital Package", "SPACE_10": "Phoenix Module",
    "SPACE_14": "Evacuation Module", "SPACE_15": "Children's Module",
}

# Eintraege der Waffen-Tabelle, die keine Waffe sind (Katastrophen, Explosionen,
# Anzeige). In der Auswahl stehen sie in einer eigenen Gruppe am Ende.
# Weapons-sheet entries that are not weapons.
EFFECT_CODES = frozenset({
    "EMP_BIG", "AMBIENT_ANIM", "BEACON", "BLD_EXPL_SML", "BLD_EXPL_MED", "BLD_EXPL_BIG",
    "EARTHQUAKE", "ERUPTION", "FUMAROLE", "LIGHTNING", "MAGMA_VENT", "METEOR", "TORNADO",
    "SHUTTLE", "SCUTTLE_DESTRUCT", "SELF_DESTRUCT", "SELF_DESTRUCT_ADV",
})


def unit_label(code: str) -> str:
    """Lesbarer Name, sonst der Code. Readable name, else the code."""
    return UNIT_NAMES.get(code, code)


# --- Datenmodell / data model ----------------------------------------------

@dataclass
class UnitProp:
    unit: str
    prop: str
    value: int


@dataclass
class Tech:
    id: int
    name: str
    category: int = 0
    description: str = ""
    teaser: str = ""
    improve_desc: str = ""
    requires: list[int] = field(default_factory=list)
    # None = Zeile fehlt. Mit `same_cost` wird COST statt EDEN_/PLYMOUTH_COST
    # geschrieben (nur wenn beide gleich sind).
    eden_cost: int | None = None
    plymouth_cost: int | None = None
    same_cost: bool = False
    max_scientists: int | None = None
    lab: int | None = None
    props: list[UnitProp] = field(default_factory=list)
    # Zeilen, die das Modell nicht kennt (Kommentare, PLAYER_PROP...), roh.
    extra_lines: list[str] = field(default_factory=list)
    # Originaltext des ganzen Blocks; None fuer neue Themen.
    raw: str | None = field(default=None, repr=False, compare=False)
    _snapshot: tuple | None = field(default=None, repr=False, compare=False)

    def key(self) -> tuple:
        return (self.id, self.name, self.category, self.description, self.teaser,
                self.improve_desc, tuple(self.requires), self.eden_cost, self.plymouth_cost,
                self.same_cost, self.max_scientists, self.lab,
                tuple((p.unit, p.prop, p.value) for p in self.props), tuple(self.extra_lines))

    def changed(self) -> bool:
        return self.raw is None or self._snapshot != self.key()

    def mark_clean(self) -> None:
        self._snapshot = self.key()

    def cost_for(self, faction: str) -> int | None:
        """'eden' | 'plymouth': Kosten (-1 gesperrt, 0 sofort erforscht)."""
        return self.eden_cost if faction == "eden" else self.plymouth_cost

    def is_free_marker(self) -> bool:
        """Starteintrag/Freischaltung: Kategorie 0 (keine eigentliche Forschung)."""
        return self.category == 0

    def upgrade_count(self) -> int:
        return len(self.props) + sum(
            1 for l in self.extra_lines if l.strip().split(" ")[0] in ("PLAYER_PROP", "FUNCTION_RESULT"))


@dataclass
class TechFile:
    """Eine Tech-Datei. `chunks` ist die Datei in Reihenfolge: Text oder Tech."""
    chunks: list = field(default_factory=list)
    newline: str = "\r\n"
    path: Path | None = None
    load_problems: list[str] = field(default_factory=list)

    @property
    def techs(self) -> list[Tech]:
        return [c for c in self.chunks if isinstance(c, Tech)]

    def by_id(self) -> dict[int, Tech]:
        return {t.id: t for t in self.techs}

    def get(self, tid: int) -> Tech | None:
        for t in self.techs:
            if t.id == tid:
                return t
        return None

    def changed(self) -> bool:
        return any(t.changed() for t in self.techs) or self._removed

    _removed: bool = False

    # -- Aendern / edit --

    def add(self, tech: Tech, after: Tech | None = None) -> None:
        """Neues Thema einfuegen, hinter `after` (sonst am Ende vor dem Anhang)."""
        if after is not None and after in self.chunks:
            i = self.chunks.index(after) + 1
        else:
            i = self._end_index()
        # Leerzeile davor, wie in den Originalen.
        self.chunks.insert(i, self.newline)
        self.chunks.insert(i + 1, tech)

    def _end_index(self) -> int:
        last = -1
        for i, c in enumerate(self.chunks):
            if isinstance(c, Tech):
                last = i
        return last + 1 if last >= 0 else len(self.chunks)

    def remove(self, tech: Tech) -> list[Tech]:
        """Thema loeschen und alle REQUIRES darauf entfernen. Gibt die
        Themen zurueck, deren Voraussetzungen sich dadurch aenderten."""
        i = self.chunks.index(tech)
        del self.chunks[i]
        # Die Leerzeile davor mit entfernen, wenn wir sie selbst eingefuegt haben.
        if i > 0 and self.chunks[i - 1] == self.newline:
            del self.chunks[i - 1]
        self._removed = True
        touched = []
        for t in self.techs:
            if tech.id in t.requires:
                t.requires = [r for r in t.requires if r != tech.id]
                touched.append(t)
        return touched

    def change_id(self, tech: Tech, new_id: int) -> list[Tech]:
        """Nummer aendern und jedes REQUIRES darauf mitziehen."""
        old = tech.id
        tech.id = new_id
        touched = []
        for t in self.techs:
            if old in t.requires:
                t.requires = [new_id if r == old else r for r in t.requires]
                touched.append(t)
        return touched

    def free_id(self, near: int) -> int:
        """Erste freie Nummer ab `near` (bleibt >= 1000: Tech-Level != 0)."""
        used = {t.id for t in self.techs}
        n = max(1000, near)
        while n in used:
            n += 1
        return n

    def followers(self, tid: int) -> list[Tech]:
        return [t for t in self.techs if tid in t.requires]

    def ancestors(self, tid: int) -> set[int]:
        by = self.by_id()
        out: set[int] = set()
        stack = list(by[tid].requires) if tid in by else []
        while stack:
            r = stack.pop()
            if r in out or r not in by:
                continue
            out.add(r)
            stack.extend(by[r].requires)
        return out

    def descendants(self, tid: int) -> set[int]:
        kids: dict[int, list[int]] = {}
        for t in self.techs:
            for r in t.requires:
                kids.setdefault(r, []).append(t.id)
        out: set[int] = set()
        stack = list(kids.get(tid, []))
        while stack:
            k = stack.pop()
            if k in out:
                continue
            out.add(k)
            stack.extend(kids.get(k, []))
        return out

    # -- Schreiben / write --

    def text(self) -> str:
        out = []
        for c in self.chunks:
            if isinstance(c, Tech):
                out.append(c.raw if not c.changed() else format_tech(c, self.newline))
            else:
                out.append(c)
        return "".join(out)

    def save(self, path: Path | str | None = None, backup: bool = True) -> Path:
        path = Path(path or self.path)
        data = self.text().encode("latin-1", errors="replace")
        if backup and path.exists():
            path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
        path.write_bytes(data)
        self.path = path
        for t in self.techs:
            if t.changed():
                t.raw = format_tech(t, self.newline)
            t.mark_clean()
        self._removed = False
        return path


# --- Lesen / read ------------------------------------------------------------

_BEGIN = re.compile(r'^[ \t]*BEGIN_TECH[ \t]+"([^"]*)"[ \t]+(-?\d+)', re.M)
_END = re.compile(r'^[ \t]*END_TECH[^\n]*(\n|$)', re.M)
_INT_TAGS = {"CATEGORY": "category", "MAX_SCIENTISTS": "max_scientists", "LAB": "lab"}
_STR_TAGS = {"DESCRIPTION": "description", "TEASER": "teaser", "IMPROVE_DESC": "improve_desc"}


def _strip_comment(s: str) -> str:
    """Kommentar ab ';' entfernen, aber nicht innerhalb von Anfuehrungszeichen."""
    inq = False
    for i, ch in enumerate(s):
        if ch == '"':
            inq = not inq
        elif ch == ";" and not inq:
            return s[:i]
    return s


def _logical_lines(body: str) -> list[str]:
    """Zeilen; eine Zeile mit offenem Anfuehrungszeichen laeuft weiter."""
    out, buf = [], None
    for line in body.splitlines(keepends=True):
        if buf is not None:
            buf += line
            if _strip_comment_count(buf) % 2 == 0:
                out.append(buf); buf = None
            continue
        if _strip_comment_count(line) % 2:
            buf = line
        else:
            out.append(line)
    if buf is not None:
        out.append(buf)
    return out


def _strip_comment_count(s: str) -> int:
    n, inq = 0, False
    for ch in s:
        if ch == '"':
            n += 1; inq = not inq
        elif ch == ";" and not inq:
            break
    return n


def parse_tech(name: str, tid: int, body: str, problems: list[str]) -> Tech:
    t = Tech(id=tid, name=name)
    has_cost = False
    for raw_line in _logical_lines(body):
        line = _strip_comment(raw_line).strip()
        if not line:
            if raw_line.strip():                    # reine Kommentarzeile
                t.extra_lines.append(raw_line.strip())
            continue
        tag, _, rest = line.partition(" ")
        if "\t" in tag:
            tag, _, rest2 = line.partition("\t"); rest = rest2
        rest = rest.strip()
        try:
            if tag in _STR_TAGS:
                m = re.match(r'"(.*)"', rest, re.S)
                val = m.group(1) if m else rest
                setattr(t, _STR_TAGS[tag], re.sub(r"[\r\n\t]", "", val))
            elif tag in _INT_TAGS:
                setattr(t, _INT_TAGS[tag], int(rest.split()[0]))
            elif tag == "REQUIRES":
                t.requires.append(int(rest.split()[0]))
            elif tag == "COST":
                v = int(rest.split()[0]); t.eden_cost = t.plymouth_cost = v; has_cost = True
            elif tag == "EDEN_COST":
                t.eden_cost = int(rest.split()[0])
            elif tag == "PLYMOUTH_COST":
                t.plymouth_cost = int(rest.split()[0])
            elif tag == "UNIT_PROP":
                p = rest.split()
                t.props.append(UnitProp(p[0], p[1], int(p[2])))
            else:
                t.extra_lines.append(raw_line.strip())
        except (ValueError, IndexError):
            problems.append(f"{tid:05d}: {line[:60]}")
            t.extra_lines.append(raw_line.strip())
    t.same_cost = has_cost
    return t


def parse(text: str, path: Path | None = None) -> TechFile:
    nl = "\r\n" if "\r\n" in text else "\n"
    tf = TechFile(newline=nl, path=path)
    pos = 0
    for m in _BEGIN.finditer(text):
        if m.start() < pos:
            continue
        end = _END.search(text, m.end())
        if not end:
            tf.load_problems.append(f"{m.group(2)}: END_TECH fehlt / missing")
            break
        start = text.rfind("\n", 0, m.start()) + 1    # Zeilenanfang samt Einrueckung
        if start < pos:
            start = m.start()
        if start > pos:
            tf.chunks.append(text[pos:start])
        body = text[m.end():end.start()]
        tech = parse_tech(m.group(1), int(m.group(2)), body, tf.load_problems)
        tech.raw = text[start:end.end()]
        tech.mark_clean()
        tf.chunks.append(tech)
        pos = end.end()
    if pos < len(text):
        tf.chunks.append(text[pos:])
    return tf


def load(path: Path | str) -> TechFile:
    path = Path(path)
    return parse(path.read_bytes().decode("latin-1"), path)


def new_file() -> TechFile:
    nl = "\r\n"
    tf = TechFile(newline=nl)
    tf.chunks.append(f"; Outpost 2: Divided Destiny{nl}; Research{nl}{nl}")
    return tf


# --- Formatieren / format ---------------------------------------------------

def _q(s: str) -> str:
    return '"' + s.replace('"', "'").replace("\r", " ").replace("\n", " ") + '"'


def format_tech(t: Tech, nl: str = "\r\n") -> str:
    def row(tag: str, val) -> str:
        return f"    {tag:<16}{val}{nl}"
    lines = [f'BEGIN_TECH {_q(t.name)} {t.id:05d}{nl}', row("CATEGORY", t.category)]
    if t.description:
        lines.append(row("DESCRIPTION", _q(t.description)))
    if t.teaser:
        lines.append(row("TEASER", _q(t.teaser)))
    if t.improve_desc:
        lines.append(row("IMPROVE_DESC", _q(t.improve_desc)))
    for r in t.requires:
        lines.append(row("REQUIRES", f"{r:05d}"))
    if t.same_cost and t.eden_cost == t.plymouth_cost and t.eden_cost is not None:
        lines.append(row("COST", t.eden_cost))
    else:
        if t.eden_cost is not None:
            lines.append(row("EDEN_COST", t.eden_cost))
        if t.plymouth_cost is not None:
            lines.append(row("PLYMOUTH_COST", t.plymouth_cost))
    if t.max_scientists is not None:
        lines.append(row("MAX_SCIENTISTS", t.max_scientists))
    if t.lab is not None:
        lines.append(row("LAB", t.lab))
    for p in t.props:
        lines.append(f"    UNIT_PROP {p.unit} {p.prop} {p.value}{nl}")
    for x in t.extra_lines:
        lines.append(f"    {x}{nl}")
    lines.append(f"END_TECH{nl}")
    return "".join(lines)


# --- Pruefen / validate -------------------------------------------------------

@dataclass
class Problem:
    level: str        # "error" | "warning"
    tech: int | None
    code: str         # Schluessel fuer tr("techtree.v_<code>")
    args: dict = field(default_factory=dict)


def validate_tech(tf: TechFile, t: Tech, units=None) -> list[Problem]:
    """`units`: bekannte Einheiten-Codes (Menge) oder {Code: Art} -- dann wird
    auch geprueft, ob die Eigenschaft zur Art passt."""
    P = []
    ids = {x.id for x in tf.techs}

    def add(level, code, **a):
        P.append(Problem(level, t.id, code, a))
    if t.id < 1000:
        add("error", "id_level")
    if sum(1 for x in tf.techs if x.id == t.id) > 1:
        add("error", "id_duplicate")
    if not t.name.strip():
        add("error", "name_empty")
    if len(t.name) > MAX_NAME:
        add("error", "name_long", n=len(t.name), max=MAX_NAME)
    for fld in ("description", "teaser", "improve_desc"):
        if len(getattr(t, fld)) > MAX_TEXT:
            add("error", "text_long", field=fld, n=len(getattr(t, fld)), max=MAX_TEXT)
    if '"' in t.name + t.description + t.teaser + t.improve_desc:
        add("error", "quote")
    if t.category not in CATEGORIES:
        add("error", "category", v=t.category)
    for r in t.requires:
        if r not in ids:
            add("error", "req_missing", req=r)
        if r == t.id:
            add("error", "req_self")
    if len(t.requires) != len(set(t.requires)):
        add("warning", "req_double")
    if len(t.requires) > MAX_REQUIRES:
        add("error", "req_many", n=len(t.requires), max=MAX_REQUIRES)
    if t.upgrade_count() > MAX_UPGRADES:
        add("error", "props_many", n=t.upgrade_count(), max=MAX_UPGRADES)
    for c in (t.eden_cost, t.plymouth_cost):
        if c is not None and c < -1:
            add("error", "cost_neg", v=c)
    if t.eden_cost is None and t.plymouth_cost is None:
        add("warning", "cost_none")
    researchable = any(c is not None and c > 0 for c in (t.eden_cost, t.plymouth_cost))
    if researchable:
        if t.lab not in LABS:
            add("error", "lab", v=t.lab)
        lo, hi = SCIENTISTS_RANGE
        if t.max_scientists is None or not (lo <= t.max_scientists <= hi or t.max_scientists == 1):
            add("error", "scientists", v=t.max_scientists, lo=lo, hi=hi)
    elif t.lab is not None and t.lab not in LABS:
        add("error", "lab", v=t.lab)
    for p in t.props:
        if p.prop not in PROPERTY_NAMES:
            add("error", "prop_unknown", prop=p.prop)
        if p.prop == "Armor" and not (ARMOR_RANGE[0] <= p.value <= ARMOR_RANGE[1]):
            add("error", "armor", v=p.value)
        if units and p.unit not in units:
            add("warning", "unit_unknown", unit=p.unit)
        elif isinstance(units, dict) and p.prop in PROPERTY_NAMES and not prop_fits(units.get(p.unit), p.prop):
            add("warning", "prop_kind", unit=p.unit, prop=p.prop, kind=units.get(p.unit))
    seen: dict[tuple[str, str], int] = {}
    for p in t.props:
        seen[(p.unit, p.prop)] = seen.get((p.unit, p.prop), 0) + 1
    for (u, pr), n in seen.items():
        if n > 1:
            add("warning", "prop_double", unit=u, prop=pr)
    return P


def find_cycles(tf: TechFile) -> list[list[int]]:
    by = tf.by_id()
    color: dict[int, int] = {}
    cycles = []

    def visit(n, stack):
        color[n] = 1
        stack.append(n)
        for r in by[n].requires:
            if r not in by:
                continue
            if color.get(r) == 1:
                cycles.append(stack[stack.index(r):] + [r])
            elif r not in color:
                visit(r, stack)
        stack.pop()
        color[n] = 2
    for t in tf.techs:
        if t.id not in color:
            visit(t.id, [])
    return cycles


def validate(tf: TechFile, units=None) -> list[Problem]:
    out: list[Problem] = []
    if len(tf.techs) > MAX_TECHS:
        out.append(Problem("error", None, "too_many", {"n": len(tf.techs), "max": MAX_TECHS}))
    for t in tf.techs:
        out += validate_tech(tf, t, units)
    for c in find_cycles(tf):
        out.append(Problem("error", c[0], "cycle", {"chain": " > ".join(f"{i:05d}" for i in c)}))
    # Welche Kolonie erreicht ein Thema nie, weil eine Voraussetzung fuer sie gesperrt ist?
    by = tf.by_id()
    for fac in ("eden", "plymouth"):
        for t in tf.techs:
            if (t.cost_for(fac) or 0) < 0:
                continue
            blocked = [r for r in tf.ancestors(t.id) if (by[r].cost_for(fac) or 0) < 0]
            if blocked:
                out.append(Problem("warning", t.id, "unreachable",
                                   {"faction": fac, "req": min(blocked)}))
    return out


# --- Anordnung / layout -----------------------------------------------------

def layout(techs: list[Tech]) -> dict[int, tuple[int, int]]:
    """Spalte = laengste Kette von Voraussetzungen (nur unter `techs`), Zeile
    so, dass Linien moeglichst wenig kreuzen (Schwerpunkt der Vorgaenger).
    Column = deepest prerequisite chain; row by barycentre of the predecessors."""
    by = {t.id: t for t in techs}
    depth: dict[int, int] = {}

    def d(tid, seen):
        if tid in depth:
            return depth[tid]
        if tid in seen:
            return 0
        seen.add(tid)
        reqs = [r for r in by[tid].requires if r in by]
        v = 1 + max(d(r, seen) for r in reqs) if reqs else 0
        depth[tid] = v
        return v
    for t in techs:
        d(t.id, set())
    cols: dict[int, list[Tech]] = {}
    for t in techs:
        cols.setdefault(depth[t.id], []).append(t)
    row: dict[int, float] = {}
    pos: dict[int, tuple[int, int]] = {}
    kids: dict[int, list[int]] = {}
    for t in techs:
        for r in t.requires:
            if r in by:
                kids.setdefault(r, []).append(t.id)
    order = {}
    for c in sorted(cols):
        lst = cols[c]
        if c == 0:
            lst.sort(key=lambda t: (t.category, t.name.lower(), t.id))
        else:
            def bary(t):
                rs = [row[r] for r in t.requires if r in row]
                return sum(rs) / len(rs) if rs else 0.0
            lst.sort(key=lambda t: (bary(t), t.category, t.name.lower()))
        for i, t in enumerate(lst):
            row[t.id] = i
        order[c] = lst
    # Zweiter Durchgang: Wurzeln nach dem Schwerpunkt ihrer Nachfolger.
    if 0 in order and len(order) > 1:
        def kbary(t):
            ks = [row[k] for k in kids.get(t.id, []) if k in row]
            return sum(ks) / len(ks) if ks else 1e9
        order[0].sort(key=lambda t: (kbary(t), t.category, t.name.lower()))
        for i, t in enumerate(order[0]):
            row[t.id] = i
    for c, lst in order.items():
        for i, t in enumerate(lst):
            pos[t.id] = (c, i)
    return pos


# --- Regel-Tabellen (Grundwerte) / rule sheets (base values) -----------------

def read_sheets(sheets_dir: Path | str) -> dict[str, tuple[str, dict[str, str]]]:
    """{CODE: (art, {Spaltenname: Wert})} aus vehicles/building/weapons/space.txt."""
    out: dict[str, tuple[str, dict[str, str]]] = {}
    for kind, fname in SHEET_FILES.items():
        p = Path(sheets_dir) / fname
        try:
            lines = p.read_bytes().decode("latin-1").splitlines()
        except OSError:
            continue
        if len(lines) < 3:
            continue
        h1, h2 = lines[0].split("\t"), lines[1].split("\t")
        heads = [" ".join(x for x in (a.strip(), (h2[i] if i < len(h2) else "").strip()) if x)
                 for i, a in enumerate(h1)]
        for line in lines[2:]:
            if not line.strip() or line.lstrip().startswith(";"):
                continue
            cells = line.split("\t")
            code = cells[0].strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
                continue
            out[code] = (kind, {heads[i]: cells[i].strip() for i in range(min(len(heads), len(cells)))})
    return out


def base_value(sheets: dict, unit: str, prop: str) -> str | None:
    entry = sheets.get(unit)
    if not entry:
        return None
    kind, row = entry
    col = SHEET_COLUMNS.get(kind, {}).get(prop)
    if not col:
        return None
    for k, v in row.items():
        if k.lower() == col.lower():
            return v or None
    return None
