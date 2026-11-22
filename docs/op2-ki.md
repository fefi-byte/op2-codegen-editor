# op2-ki als Gegner / op2-ki as opponent

*English below.*

[op2-ki](https://github.com/fefi-byte/op2-ki) ist eine eigene KI für Outpost 2 (Rust, eigenes Projekt). Sie baut ihre
Kolonie selbst auf, forscht, erschließt Erz, baut Armeen und greift an – als Mehrspieler-Gegner oder in einer Mission
mit einer Rolle. Der Editor enthält **keinen KI-Code**: Er bindet die KI nur ein.

## Einrichten

1. op2-ki herunterladen: `git clone https://github.com/fefi-byte/op2-ki` oder das ZIP von GitHub entpacken.
2. In `config.ini` unter `[paths]` den Ordner eintragen:

   ```ini
   [paths]
   op2ki_path = D:\op2-ki
   ```

   Der Editor braucht daraus nur drei Dateien: `missionen/gemeinsam/op2ki.hpp`, `missionen/gemeinsam/op2ki_bruecke.hpp`
   (zum Bauen) und `fertig/op2ki.dll` (zum Spielen). Liegen sie flach in einem Ordner, geht das auch.

## Benutzen

Im Spielerdialog einen **KI-Spieler** wählen und *Von der op2-ki gesteuert* anhaken:

| Feld | Bedeutung |
|---|---|
| Rolle | *Mehrspieler-Gegner* (wie in den Duellen) oder Missionsmodus: *aggressiv*, *defensiv* (greift nicht selbst an, schlägt zurück), *Kolonie* (baut aus, greift nicht an) |
| Basis X/Y | Startplatz in Editor-Kacheln, sonst Kartenmitte |
| Startbasis selbst anlegen | an: die KI legt ihre Startbasis an; aus: sie übernimmt, was du für den Spieler auf die Karte gesetzt hast |
| Stellschrauben | weitere Einstellungen `name=wert` je Zeile, z. B. `zbWache=6`, `testPosten=60000`, `testPostenX=10`, `testPostenY=20`, `testPostenGroesse=4` (zweite Basis) – Liste in `EINBINDEN.md` der op2-ki |

Die Schwierigkeit kommt aus dem Spiel (leicht/normal/schwer, ohne Boni). Erz-Baken für die KI setzt du wie gewohnt auf
die Karte.

Beim **Bauen** kopiert der Editor die zwei Header in den Missionsordner; die Mission ruft in `InitProc`
`op2ki::start(...)` und in `AIProc` `op2ki::schritt(...)` auf. Nach dem Bauen (und bei *In OP2 testen*) liegt
`op2ki.dll` neben der Missions-DLL. Weitergeben musst du beide DLLs; ohne `op2ki.dll` läuft die Mission, der
KI-Spieler tut dann aber nichts (Meldung im Spiel). Die KI schreibt jede Entscheidung mit Grund nach
`OPU\logs\<Mission>-KI.jsonl`.

## English

[op2-ki](https://github.com/fefi-byte/op2-ki) is a separate Outpost 2 AI project. The editor contains no AI code, it
only links it in: set `[paths] op2ki_path` in `config.ini` to an op2-ki checkout or extracted ZIP, then tick
*Controlled by op2-ki* for an AI player in the players dialog (role, base position, start base, extra settings
`name=value`). Building copies `op2ki.hpp` and `op2ki_bruecke.hpp` into the mission folder; after a build (and on
*Test in OP2*) `op2ki.dll` is copied next to the mission DLL. Ship both DLLs. Difficulty comes from the game.
