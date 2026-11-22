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

**op2ki.dll** kommt fertig aus dem op2-ki-Release (`op2-ki/fertig/op2ki.dll`, passend zum ausgecheckten Tag) und wird
nach jedem Bau neben die Missions-DLL kopiert. Wer sie selbst aus den Quellen bauen will: Rust installieren
(https://rustup.rs), `rustup target add i686-pc-windows-msvc` und in `config.ini` unter `[build]`
`op2ki_selbst_bauen = true` setzen; die DLL landet dann in `build/op2ki/`.

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

Beim **Bauen** kopiert der Editor die zwei Header in den Missionsordner; die Mission ruft in
`InitProc` `op2ki::start(...)` und in `AIProc` `op2ki::schritt(...)` auf. Nach dem Bauen (und bei *In OP2 testen*)
liegt `op2ki.dll` neben der Missions-DLL. Weitergeben musst du beide DLLs; ohne `op2ki.dll` läuft die Mission, der
KI-Spieler tut dann aber nichts (Meldung im Spiel). Die KI schreibt jede Entscheidung mit Grund nach
`OPU\logs\<Mission>-KI.jsonl`.

## Befehle aus Triggern (Drehbuch, Angriff, Verteidigung)

Die Aktion **op2-ki-Befehl** (Gruppe *op2-ki*) sagt der KI im laufenden Spiel, was sie tun soll:

| Befehl | Wirkung |
|---|---|
| *Phase* | Drehbuch: Bauliste (Gebäude, Anzahl, optional Ort auf der Karte mit Umkreis), Forschungen, Fahrzeuge. Ist ein Drehbuch aktiv, baut die KI **nichts selbstständig**. *Grundversorgung automatisch* (Standard an) lässt sie trotzdem Notfälle, Wohnraum, Kindergarten, Uni, Krankenhaus und die Kolonie-Forschung erledigen, damit die Bevölkerung lebt. *Der Reihe nach*: erst wenn ein Eintrag steht, kommt der nächste. |
| *Angriff* | Ziel (Gegnerbasis, Basis eines Spielers, Punkt auf der Karte, schwächstes Ziel), Art (Basis angreifen, Ziel zerstören und heim, Überfall, Ort besetzen und halten), auf zwei Wegen gleichzeitig, EMP-Rakete ja/nein, Einheiten (KI wählt, die besten N, genaue Liste, alles was da ist), Rückzug bei Verlust, Wartefrist |
| *Verteidigung* | Wache (Anzahl oder genaue Liste), Bereich auf der Karte, Waffe neuer Türme, Patrouille |
| *Drehbuch beenden* | die KI entscheidet wieder selbst |
| *Freier Befehl* | jede Stellschraube `name=wert`, z. B. `rolle=1`, `aussenposten=10,20,4` |

Die Bedingung **op2-ki meldet** (in *Wenn/Dann* und als Zusatzbedingung) fragt den Stand ab: Phase N fertig, laufende
Phase, Angriff (unterwegs, gewonnen, abgebrochen), Zahl der Angriffe, letzter Angriff auf die Basis, Satelliten,
Gebäude, Kampffahrzeuge, Kampfwert. Damit baut man Phasen: Trigger „Phase 1 fertig“ → Aktion „Phase 2“ usw.

Befehle überleben Speichern/Laden: der Editor legt sie in den Spielstand der Mission, nach dem Laden startet die KI neu
und bekommt alle Befehle noch einmal.

## English

[op2-ki](https://github.com/fefi-byte/op2-ki) is a separate Outpost 2 AI project, included as the git submodule
`op2-ki/`; an editor release always ships the latest op2-ki release (tag `v*`) including its ready-built `op2ki.dll`.
Tick *Controlled by op2-ki* for an AI player in the players dialog (role, base position, start base, extra settings
`name=value`). Building copies `op2ki.hpp` and `op2ki_bruecke.hpp` into the mission folder; after a build (and on
*Test in OP2*) `op2ki.dll` is copied next to the mission DLL. Ship both DLLs. To build the DLL yourself install Rust,
add the `i686-pc-windows-msvc` target and set `[build] op2ki_selbst_bauen = true`. `[paths] op2ki_path` overrides the
submodule with your own checkout.

The action **op2-ki command** gives orders during the game: script *phases* (build list with optional map spots,
research, vehicles; while a script is active the AI builds nothing on its own, *basic supply* keeps the colony alive),
*attacks* (target, kind, two routes, EMP, which units, retreat, wait limit) and *defence* (guard size or units, area,
tower weapon, patrol). The condition **op2-ki reports** reads back phase/attack state and counts. Orders survive
save/load.
