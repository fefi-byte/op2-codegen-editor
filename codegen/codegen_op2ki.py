"""op2-ki-Befehle: aus den Daten einer Aktion "op2-ki-Befehl" den Befehlstext fuer op2ki::befehl bauen.

Die KI (eigenes Projekt op2-ki, Submodul op2-ki/) versteht Text, "name=wert" je Zeile (siehe op2-ki/EINBINDEN.md und
kern/src/cpp/befehl.rs). Der Editor haelt die Daten als dict in TriggerAction.op2ki:

  spieler   int
  art       "phase" | "angriff" | "verteidigung" | "drehbuchAus" | "befehl"
  phase:        id, bauen [{typ, n, x, y, r}] (x < 0 = ohne Ort), forschen [tech_id], fahrzeuge [{typ, waffe, n}],
                grund (bool), reihe (bool)
  angriff:      ziel ("basis" | "spieler" | "punkt" | "schwaechste"), zielspieler, x, y, angriffsart ("basis" | "ziel" |
                "ueberfall" | "halten"), parallel, emp ("" | "an" | "aus"), truppe ("auto" | "beste" | "liste" |
                "vorhanden"), anzahl, einheiten [{typ, waffe, n}], rueckzug, frist
  verteidigung: truppe ("auto" | "beste" | "liste"), anzahl, einheiten, bereich {x, y, width, height} oder leer,
                turm (Waffe, "" = selbst), patrouille ("" | "an" | "aus")
  befehl:       text (frei)

op2-ki commands: build the command text for op2ki::befehl from an "op2-ki command" action.
"""
from __future__ import annotations


def _name(m: str) -> str:
    """mapTokamak -> Tokamak"""
    m = (m or "").strip()
    return m[3:] if m.startswith("map") else m


def _einheiten(liste) -> str:
    teile = []
    for e in liste or []:
        typ = _name(e.get("typ", ""))
        if not typ:
            continue
        w = _name(e.get("waffe", "") or "")
        n = int(e.get("n", 1) or 1)
        teile.append(f"{typ}/{w}:{n}" if w and w != "None" else f"{typ}:{n}")
    return ",".join(teile)


def befehl_text(d: dict) -> str:
    """Befehlstext (Zeilen "name=wert") aus den Aktionsdaten."""
    d = d or {}
    art = d.get("art", "phase")
    z: list[str] = []
    if art == "phase":
        z.append(f"phase={int(d.get('id', 1) or 1)}")
        bauen = []
        for b in d.get("bauen") or []:
            typ = _name(b.get("typ", ""))
            if not typ:
                continue
            s = f"{typ}:{int(b.get('n', 1) or 1)}"
            if int(b.get("x", -1)) >= 0 and int(b.get("y", -1)) >= 0:
                s += f"@{int(b['x'])},{int(b['y'])},{int(b.get('r', 6) or 6)}"
            bauen.append(s)
        if bauen:
            z.append("bauen=" + ",".join(bauen))
        forschen = [str(int(t)) for t in (d.get("forschen") or []) if int(t) > 0]
        if forschen:
            z.append("forschen=" + ",".join(forschen))
        fz = _einheiten(d.get("fahrzeuge"))
        if fz:
            z.append("fahrzeuge=" + fz)
        z.append(f"grundversorgung={1 if d.get('grund', True) else 0}")
        z.append(f"reihenfolge={1 if d.get('reihe', False) else 0}")
    elif art == "drehbuchAus":
        z.append("drehbuch=0")
    elif art == "angriff":
        z.append("angriff=1")
        ziel = d.get("ziel", "basis")
        if ziel == "spieler":
            z.append(f"ziel=basis:{int(d.get('zielspieler', 0) or 0)}")
        elif ziel == "punkt":
            z.append(f"ziel=punkt:{int(d.get('x', 0) or 0)},{int(d.get('y', 0) or 0)}")
        elif ziel == "schwaechste":
            z.append("ziel=schwaechste")
        else:
            z.append("ziel=basis")
        z.append(f"art={d.get('angriffsart', 'basis') or 'basis'}")
        if d.get("parallel"):
            z.append("parallel=1")
        emp = d.get("emp", "")
        if emp in ("an", "aus"):
            z.append(f"emp={1 if emp == 'an' else 0}")
        truppe = d.get("truppe", "auto")
        if truppe == "beste":
            z.append(f"einheiten=beste:{int(d.get('anzahl', 6) or 6)}")
        elif truppe == "vorhanden":
            z.append("einheiten=vorhanden")
        elif truppe == "liste" and _einheiten(d.get("einheiten")):
            z.append("einheiten=" + _einheiten(d.get("einheiten")))
        if int(d.get("rueckzug", 0) or 0) > 0:
            z.append(f"rueckzug={int(d['rueckzug'])}")
        if int(d.get("frist", 0) or 0) > 0:
            z.append(f"frist={int(d['frist'])}")
    elif art == "verteidigung":
        z.append("verteidigung=1")
        truppe = d.get("truppe", "auto")
        if truppe == "beste":
            z.append(f"wache={int(d.get('anzahl', 6) or 6)}")
        elif truppe == "liste" and _einheiten(d.get("einheiten")):
            z.append("einheiten=" + _einheiten(d.get("einheiten")))
        b = d.get("bereich") or {}
        if int(b.get("width", 0) or 0) > 0 and int(b.get("height", 0) or 0) > 0:
            x, y = int(b.get("x", 0)), int(b.get("y", 0))
            z.append(f"bereich={x},{y},{x + int(b['width']) - 1},{y + int(b['height']) - 1}")
        if _name(d.get("turm", "") or ""):
            z.append(f"turm={_name(d['turm'])}")
        if d.get("patrouille", "") in ("an", "aus"):
            z.append(f"patrouille={1 if d['patrouille'] == 'an' else 0}")
    else:
        for zeile in (d.get("text", "") or "").replace(";", "\n").splitlines():
            zeile = zeile.strip()
            if zeile and "=" in zeile and not zeile.startswith("#"):
                z.append(zeile)
    return "\n".join(z) + "\n"


def kurz(d: dict) -> str:
    """Kurzbeschreibung fuer die Aktionskarte."""
    d = d or {}
    p = int(d.get("spieler", 1) or 0)
    art = d.get("art", "phase")
    if art == "phase":
        n = len(d.get("bauen") or []); f = len(d.get("forschen") or []); v = len(d.get("fahrzeuge") or [])
        return f"P{p}: Phase {int(d.get('id', 1) or 1)} -- {n} Bauten, {f} Forschungen, {v} Fahrzeuge"
    if art == "drehbuchAus":
        return f"P{p}: Drehbuch aus"
    if art == "angriff":
        return f"P{p}: Angriff ({d.get('ziel', 'basis')}, {d.get('angriffsart', 'basis')}{', zwei Wege' if d.get('parallel') else ''})"
    if art == "verteidigung":
        return f"P{p}: Verteidigung"
    t = (d.get("text", "") or "").replace("\n", "; ")
    return f"P{p}: {t[:44]}{'…' if len(t) > 44 else ''}"
