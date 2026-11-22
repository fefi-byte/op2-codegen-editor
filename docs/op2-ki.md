# op2-ki als Gegner / op2-ki as opponent

*English below.*

[op2-ki](https://github.com/fefi-byte/op2-ki) ist eine eigene KI für Outpost 2 (Rust, eigenes Projekt). Sie baut ihre
Kolonie selbst auf, forscht, erschließt Erz, baut Armeen und greift an – als Mehrspieler-Gegner oder in einer Mission
mit einer Rolle. Der Editor enthält **keinen KI-Code**: Er bindet die KI nur ein.

## Einrichten

op2-ki steckt als **Git-Submodul** in `op2-ki/` (im Windows-Release: die mitgelieferte Kopie). Das Release des Editors
enthält immer das **neueste op2-ki-Release** (Tag `v*`); im Checkout holt man es mit

```
git submodule update --init op2-ki
git -C op2-ki fetch --tags && git -C op2-ki checkout $(git -C op2-ki tag -l "v*" --sort=-v:refname | head -n 1)
```

**op2ki.dll baut der Editor auf deinem PC** aus diesen Quellen (Rust, 32 Bit). Einmalig einrichten:

1. Rust installieren: https://rustup.rs
2. `rustup target add i686-pc-windows-msvc`

Unter Windows reicht dafür die Visual-Studio-Installation, die der Editor ohnehin für die Missionen braucht. Der erste
Bau dauert ein paar Minuten, danach baut cargo nur neu, was sich geändert hat. Die DLL landet in `build/op2ki/` neben
dem Editor und wird nach jedem Bau neben die Missions-DLL kopiert.

Für einen eigenen op2-ki-Checkout kannst du in `config.ini` unter `[paths]` `op2ki_path = D:\op2-ki` setzen.

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

Beim **Bauen** kopiert der Editor die zwei Header in den Missionsordner und baut `op2ki.dll`; die Mission ruft in
`InitProc` `op2ki::start(...)` und in `AIProc` `op2ki::schritt(...)` auf. Nach dem Bauen (und bei *In OP2 testen*)
liegt `op2ki.dll` neben der Missions-DLL. Weitergeben musst du beide DLLs; ohne `op2ki.dll` läuft die Mission, der
KI-Spieler tut dann aber nichts (Meldung im Spiel). Die KI schreibt jede Entscheidung mit Grund nach
`OPU\logs\<Mission>-KI.jsonl`.

## English

[op2-ki](https://github.com/fefi-byte/op2-ki) is a separate Outpost 2 AI project, included as the git submodule
`op2-ki/`; an editor release always ships the latest op2-ki release (tag `v*`). The editor builds `op2ki.dll` on your
PC from it: install Rust (https://rustup.rs) and run `rustup target add i686-pc-windows-msvc` once. Tick
*Controlled by op2-ki* for an AI player in the players dialog (role, base position, start base, extra settings
`name=value`). Building copies `op2ki.hpp` and `op2ki_bruecke.hpp` into the mission folder and builds the DLL; after a
build (and on *Test in OP2*) `op2ki.dll` is copied next to the mission DLL. Ship both DLLs. `[paths] op2ki_path`
overrides the submodule with your own checkout.
