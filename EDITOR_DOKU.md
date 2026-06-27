# OP2 Mission Editor — Funktionsdokumentation

Zuletzt aktualisiert: 2026-06-27

---

## Inhaltsverzeichnis

1. [Überblick](#überblick)
2. [Hauptfenster](#hauptfenster)
3. [Karten-Ansicht](#karten-ansicht)
4. [Dialog: Einstellungen (Setup)](#dialog-einstellungen-setup)
5. [Dialog: Spieler](#dialog-spieler)
6. [Dialog: Sieg & Niederlage](#dialog-sieg--niederlage)
7. [Dialog: Gruppen](#dialog-gruppen)
8. [Dialog: Trigger](#dialog-trigger)
9. [Dialog: Aktionseditor (IF/Dann/Sonst)](#dialog-aktionseditor-ifdannsonst)
10. [Ausdrucksfelder (ExprEdit)](#ausdrucksfelder-expresit)
11. [Codegenerierung](#codegenerierung)
12. [Projektformat (Save/Load)](#projektformat-saveload)

---

## Überblick

Der OP2 Mission Editor ist ein visueller Editor für Missionen des Spiels *Outpost 2: Divided Destiny*. Er erzeugt aus dem visuellen Modell direkt C++23-Quellcode (via TitanAPI) und kann diesen per Klick zu einer DLL kompilieren und die Mission in OP2 starten.

**Technologie:** Python 3 · PySide6 · TitanAPI (C++23, Header-only)

---

## Hauptfenster

### Toolbar (von links nach rechts)

| Schaltfläche | Funktion |
|---|---|
| **Einstellungen** | Missionsname, Typ, Techtree, Schwierigkeit, Variablen |
| **Spieler** | Kolonie, Mensch/KI, Tech-Level, Ressourcen, Forschungen |
| **Sieg & Niederlage** | Sieg- und Niederlage-Bedingungen |
| **Gruppen** | BuildingGroups und ReinforceGroups verwalten |
| **Trigger** | Trigger mit Bedingungen und Aktionen |
| **Code anzeigen** | Generierten C++-Code mit Syntax-Highlighting anzeigen |
| **Build → DLL** | C++ kompilieren und DLL in OP2-Ordner kopieren |
| **In OP2 testen** | Mission direkt in OP2 starten (über op2launcher.exe) |
| **Objekte leeren** | Alle platzierten Einheiten/Gebäude entfernen |

### Menü

- **Datei:** Projekt öffnen / speichern / speichern unter · Karte wählen · Ausgabeort · Beenden
- **Ansicht:** Gitter ein/aus · Zoom 1:1 · Zoom Karte einpassen
- **Sprache:** Automatisch (System) · Deutsch · English (wirkt beim nächsten Start)

### Linke Seitenleiste — Platzieren

- **Kategorie:** Gebäude · Fahrzeuge · Beacons & Mauern
- **Einheitenliste** mit Fußabdruck-Anzeige
- **Spieler-Auswahl** (0–5)
- **Unit-Name** (optional, für Scripting-Referenzen)
- Kontextabhängige Parameter:
  - Cargo-LKW: Frachttyp + Menge
  - ConVec: Bausatz (welches Gebäude wird gebaut)
  - Mining Beacon: Erz-Typ (Zufall/Common/Rare) + Ertrag (Bar1–3)
  - Kampffahrzeuge (Lynx/Panther/Tiger) + Guard Post: Waffe

### Rechte Seitenleiste — Mission-Übersicht

Dynamischer Baum mit folgenden Sektionen:

- **Ablauf / Trigger** — Hierarchie aller Trigger mit Ausführungsreihenfolge (⟶), Zykluserkennung
- **Spieler** — Zusammenfassung aller Spieler-Konfigurationen
- **Gruppen** — Liste aller BuildingGroups und ReinforceGroups
- **Sieg/Niederlage** — Sieg- und Niederlage-Bedingungen
- **Objekte** — Anzahl platzierter Einheiten, Gebäude, Beacons, Wände

Doppelklick auf Einträge öffnet den jeweiligen Bearbeiten-Dialog.

---

## Karten-Ansicht

### Mausbedienung

| Aktion | Funktion |
|---|---|
| Linksklick | Objekt platzieren (wenn Auswahl aktiv) oder Objekt-Eigenschaften bearbeiten |
| Rechtsklick | Objekt entfernen |
| Mitteltaste ziehen | Karte verschieben (Pan) |
| Mausrad | Zoom (1,25× / 0,8× pro Schritt) |
| Linksklick ziehen | Rechteck aufziehen (für SetRect / Tube-/Walllinien) |

### Visuelle Elemente

- **Platzierungsvorschau:** Gestricheltes Rechteck + Label zeigt wo das Objekt landen würde
- **Aktionslinie:** L-förmige Linie für Tube-/Wall-Recordaufnahmen
- **Aktionsbereich:** Transparentes Rechteck für flächige Aktionen
- **Spielerfarben:** 6 unterschiedliche Farben (Blau/Rot/Grün/Gelb/Lila/Cyan)
- **Beacon-Farbe:** Orange
- **Wand-/Tubefarbe:** Grau
- **Kachel-Gitter:** Optionales 1px-Linienraster (über Ansicht-Menü)

---

## Dialog: Einstellungen (Setup)

Öffnet sich über **Einstellungen** in der Toolbar.

### Basisdaten

| Feld | Beschreibung |
|---|---|
| Missionsname | Wird in OP2 in der Missionsliste angezeigt |
| Missionstyp | Colony, AutoDemo, Tutorial, Multi-Varianten (Land Rush, Space Race, …) |
| Techtree-Datei | Pfad zur Technologie-Datei (Standard: `MULTITEK.TXT`) |

### Schwierigkeit

Drei Zahlenwerte (Hard / Normal / Easy, Standard: 13 / 10 / 5).

Diese Werte stehen als `diff`-Variable in allen **Ausdrucksfeldern** zur Verfügung. Beispiel: Ein Triggerzeitpunkt von `ceil(600 * diff / 10)` ergibt 780 Marks auf Hard, 600 auf Normal, 300 auf Easy.

### Benutzerdefinierte Variablen

Tabelle mit Spalten **Name · Typ · Startwert**:

- **Typ:** `int` oder `bool`
- **Startwert:** Integer-Zahl (für `bool`: 0 = false, alles andere = true)
- Die Variablen werden als `static`-Variablen im generierten C++ deklariert
- Sie können in `modVar`-Aktionen geändert und mit `varCheck`-Bedingungen geprüft werden

---

## Dialog: Spieler

Öffnet sich über **Spieler** in der Toolbar.

### Spielerliste

Links: Liste aller Spieler mit Kurzinfo. Schaltflächen „Spieler hinzufügen" und „Entfernen".

### Spieler-Konfiguration

| Feld | Beschreibung |
|---|---|
| Kolonie | Eden oder Plymouth |
| Typ | Mensch oder KI |
| Tech-Level | 0–12 (12 = alle Techs aus Techtree automatisch verfügbar) |
| Startressourcen setzen | Schaltet das initResources-Flag ein |
| Kolonisten explizit setzen | Setzt Arbeiter / Wissenschaftler / Kinder auf genaue Zahlen |
| Ressourcen explizit setzen | Setzt Common Ore / Rare Ore / Nahrung auf genaue Werte (auch Ausdrücke möglich) |
| Vorab erforscht | Einzelne Technologien per Name auswählen und hinzufügen |

Ressourcenfelder (Common Ore, Rare Ore, Nahrung) unterstützen **Ausdrucksfelder** mit Schwierigkeitsvorschau.

---

## Dialog: Sieg & Niederlage

Öffnet sich über **Sieg & Niederlage** in der Toolbar.

### Bedingungstypen

| Typ | Felder |
|---|---|
| Zeit überstehen | Marks |
| Letzter Überlebender | Spieler |
| Raumschiff bauen | Spieler |
| Kein Command Center | Spieler |
| Gebäude-Anzahl | Spieler, Gebäudetyp, Vergleich, Anzahl |
| Fahrzeug-Anzahl | Spieler, Vergleich, Anzahl |
| Technologie erforscht | Spieler, Tech-ID |
| Ressource erreicht | Spieler, Ressource, Vergleich, Menge |
| Gebäude operativ | Spieler, Gebäudetyp, Vergleich, Anzahl |

Jede Bedingung hat ein Beschreibungsfeld für den Anzeigetext im Spiel.

Es können beliebig viele Sieg- und Niederlage-Bedingungen kombiniert werden.

---

## Dialog: Gruppen

Öffnet sich über **Gruppen** in der Toolbar.

Gruppen erscheinen als Baum (optional mit Ordner-Gruppierung).

### BuildingGroup

Eine BuildingGroup verwaltet einen Satz Gebäude, die automatisch wiedergebaut werden sollen.

| Feld | Beschreibung |
|---|---|
| Name | Eindeutiger Bezeichner |
| Ordner | Optionaler Ordnername zur Gliederung |
| Spieler | Welcher Spieler besitzt die Gruppe |
| Rect X/Y/Breite/Höhe | Bereich auf der Karte (0–1023), in dem Gebäude gesucht werden |
| Einheiten | Checkboxen für Gebäude- und Fahrzeugtypen der Gruppe |

**SetRect auf Karte ziehen:** Rechteck per Maus auf der Karte aufziehen anstatt Koordinaten eintippen.

### ReinforceGroup

Eine ReinforceGroup versorgt andere Gruppen mit Einheiten (Vehicle Factories).

| Feld | Beschreibung |
|---|---|
| Reinforce-Ziele | Textfeld: ein Zielgruppen-Name pro Zeile, Format `GruppenName=Priorität` |
| Einheiten | Checkboxen für Factory-Typen |

---

## Dialog: Trigger

Öffnet sich über **Trigger** in der Toolbar oder per „Trigger +"-Knopf in der Übersicht.

### Trigger-Liste

Baum mit Ordner-Gruppierung. Jeder Trigger zeigt Bedingungstyp und Aktionenanzahl.

### Trigger-Eigenschaften

| Feld | Beschreibung |
|---|---|
| Name | Eindeutiger Bezeichner |
| Ordner | Optionaler Ordnername zur Gliederung |
| Beim Start aktiv | Trigger wird sofort in initProc registriert |
| Nur einmal auslösen | Trigger wird nach dem ersten Auslösen deaktiviert (oneShot) |

### Trigger-Bedingungen

| Typ | Felder |
|---|---|
| Zeit (Marks) | Marks (Ausdrucksfeld mit Schwierigkeitsvorschau) |
| Punkt erreicht | Spieler, X, Y |
| Rechteck betreten | Spieler, X, Y, Breite, Höhe |
| Gebäude-Anzahl | Spieler, Gebäudetyp, Vergleich, Anzahl |
| Fahrzeug-Anzahl | Spieler, Vergleich, Anzahl |
| Technologie erforscht | Spieler, Tech-ID |
| Ressource erreicht | Spieler, Ressource, Vergleich, Menge |
| Gebäude operativ | Spieler, Gebäudetyp, Vergleich, Anzahl |
| Einheit finden | Liste von Einheits-Prüfungen (Typ, X, Y) |

### Aktionsliste

Unterhalb der Bedingung: Liste aller Aktionen des Triggers. Aktionen können per „+ Aktion hinzufügen" ergänzt, bearbeitet oder entfernt werden.

IF-Blöcke können beliebig tief verschachtelt werden.

---

## Dialog: Aktionseditor (IF/Dann/Sonst)

Erscheint beim Hinzufügen oder Bearbeiten einer Aktion.

### Aktionstypen

| Typ | Felder | Codegen-Ausgabe |
|---|---|---|
| Leere Aktion (noop) | — | `// (empty action)` |
| Nachricht anzeigen | Text | `Game::addMessage(...)` |
| Einheit erzeugen | Einheitstyp, Waffe, X, Y, Spieler | `Game::createUnit(...)` |
| Anderen Trigger erstellen | Ziel-Trigger | Ruft Trigger-Helper auf |
| RecordBuilding | Gruppe, Gebäudetyp, X, Y | `group.recordBuilding(...)` |
| RecordTube-Linie | Gruppe, X→X2, Y→Y2 | `Game::createTube(...)` |
| RecordWall-Linie | Gruppe, Wall-Typ, X→X2, Y→Y2 | `Game::createWall(...)` |
| SetTargCount | Gruppe, Einheit, Waffe, Zielanzahl (Expr) | `group.setTargCount(...)` |
| Gebäude einer Gruppe zuweisen | Gruppe, Gebäudetyp, X, Y, Spieler | `onTick(10, [...takeUnit])` |
| Variable ändern | Variable, Modus (inc/dec/expr), Ausdruck | `var++` / `var--` / `var = expr` |
| Wenn / Dann / Sonst | Bedingungen, Dann-Aktionen, Sonst-Aktionen | `if (cond) { ... } else { ... }` |

### IF-Bedingungen (für Aktions-Gating)

Jede Aktion kann durch eine oder mehrere Bedingungen gesichert werden (AND/OR):

| Typ | Felder |
|---|---|
| Gebäude an Position vorhanden | Spieler, Gebäudetyp, X, Y |
| Gebäude-Schaden | Spieler, Gebäudetyp, Vergleich, Wert (Expr) |
| Spieler-Ressource | Spieler, Ressource, Vergleich, Wert (Expr) |
| Gebäude-Anzahl | Spieler, Gebäudetyp, Vergleich, Wert (Expr) |
| Technologie erforscht | Spieler, Tech-ID |
| Variable prüfen | Variable (aus Variablenliste), Vergleich, Wert (Expr) |

Jede Bedingung kann mit **Negieren (NICHT)** invertiert werden.

---

## Ausdrucksfelder (ExprEdit)

Überall wo früher ein einfaches Zahlenfeld stand, gibt es jetzt **Ausdrucksfelder**, die entweder:

- eine **ganze Zahl** akzeptieren (`600`), oder
- einen **C++-Ausdruck** mit dem Bezeichner `diff` und eigenen Variablen (`ceil(600 * diff / 10)`)

### Schwierigkeits-Vorschau

Wenn `diff` im Ausdruck vorkommt, erscheint direkt unter dem Feld eine Live-Vorschau:

```
Hard: 780  ·  Normal: 600  ·  Easy: 300
```

(berechnet mit den Werten aus dem Setup-Dialog)

### Unterstützte Funktionen im Ausdruck

`ceil`, `floor`, `round`, `abs`, `max`, `min`

### Felder mit Ausdrucksunterstützung

- Trigger-Marks (Zeitbedingung)
- SetTargCount-Zielanzahl
- Spieler-Ressourcen (Common Ore, Rare Ore, Nahrung)
- ActionCondition-Wert (playerResource, buildingCount, unitDamage, varCheck)

---

## Codegenerierung

Der Editor generiert aus dem Modell eine einzelne C++23-Quelldatei (`mission.cpp`).

### Ausgabe-Struktur

```
// mission.cpp -- generated ...
#include "op2.hpp"
...
using namespace op2;

static const int kDiff[] = {13, 10, 5};
static const int diff = kDiff[(int)Game::difficulty()];

static int meinVar = 0;          // Benutzerdefinierte Variablen
static bool flagAktiv = false;

static void make_MeinTrigger();  // Forward-Deklarationen
static Group g_0;                // Gruppen-Variablen

extern "C" ... LevelDesc[]       // OP2-DLL-Exporte
extern "C" ... MapName[]
extern "C" ... TechtreeName[]
extern "C" ... DescBlock         // Missionstyp, Spieleranzahl
extern "C" ... DescBlockEx

static void initProc() {
    // Spieler-Setup
    // Base Layout (Gebäude, Fahrzeuge, Beacons, Wände)
    // Gruppen-Initialisierung
    // Start-Nachricht
    // Sieg-/Niederlage-Bedingungen
    // Trigger aktivieren
}

static void make_MeinTrigger() {
    onMark(ceil(600 * diff / 10), [] {
        if (meinVar >= 3) {
            Game::addMessage("Gewonnen!");
        }
    }, /*oneShot=*/true);
}

static void aiProc() {}

extern "C" InitProc() { crash::guard("InitProc", &initProc); }
extern "C" AIProc()   { crash::guard("AIProc",   &aiProc); }
```

### Koordinaten

Der Editor verwendet 0-basierte Koordinaten. Die Codegenerierung addiert automatisch +1 auf X und Y, da OP2 1-basierte Kachelkoordinaten erwartet.

---

## Projektformat (Save/Load)

Ein Projekt wird als **Ordner** gespeichert, der alle Dateien enthält:

```
MeinProjekt/
├── project.json      ← alle Editor-Daten
├── mission.cpp       ← generierter C++-Code
└── mission.dll       ← kompilierte DLL (nach Build)
```

### `project.json` — Felder

| Feld | Inhalt |
|---|---|
| `mission_name` | Missionsname |
| `mission_type` | Integer (MissionType-Enum) |
| `tech_tree` | Techtree-Dateiname |
| `difficulty` | `{hard, normal, easy}` |
| `variables` | Liste von `{name, var_type, initial_value}` |
| `map` | Kartendateiname |
| `players` | Liste aller Spieler-Konfigurationen |
| `objects` | Liste aller platzierten Einheiten/Gebäude |
| `building_groups` | BuildingGroup-Definitionen |
| `reinforce_groups` | ReinforceGroup-Definitionen |
| `triggers` | Trigger-Definitionen (inkl. verschachtelter Aktionen) |
| `victories` | Sieg-Bedingungen |
| `defeats` | Niederlage-Bedingungen |
| `node_positions` | Timeline-Knotenpositionen (visuelles Layout) |

Alle Felder sind abwärtskompatibel: Unbekannte Schlüssel werden beim Laden ignoriert, fehlende Schlüssel erhalten ihre Standardwerte.
