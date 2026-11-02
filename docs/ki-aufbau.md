# Aufbau-KI: eine Kolonie von null

Stand: erster Baustein (November 2026). Noch nicht im Spiel erprobt — die Spur ist dafür da,
genau das zu tun.

## Einschalten

*Mission → Spieler*: Spieler auf **KI** stellen, **KI baut die Kolonie selbst auf** anhaken.
Basismitte (Editor-Kacheln, Standard: Kartenmitte) und **Startausrüstung erzeugen** wählen.
Mit Startausrüstung legt die KI in InitProc selbst an:

- 5 ConVecs mit Bausätzen: Kommandozentrale, Strukturfabrik, Tokamak, Erzschmelze, Agridome
- Robo-Miner, Robo-Surveyor, 2 Lastwagen, Earthworker

Ohne Startausrüstung arbeitet sie mit den Einheiten, die im Editor für diesen Spieler stehen.
Kolonisten, Erz und Tech-Level kommen wie gewohnt aus dem Spieler-Dialog.

## Was sie tut (Takt: alle 20 Ticks)

| Teil | Was | Wie |
|---|---|---|
| Lagebild | Gebäude, Fahrzeuge, Bausätze, Erz, Nahrung, Strom, Wohnraum | `PlayerBuildingEnum` je Typ, `PlayerVehicleEnum`, HFL `PlayerEx` |
| Bedarf | Was fehlt als Nächstes? | feste Reihenfolge (CC, Strukturfabrik, Tokamak, Schmelze, Agridome), dann nach Lage: Strom < 25, Nahrung netto < 0, Wohnraum, Fahrzeugfabrik, Labor, Lager, Nursery, University, Medical Center, Standard Lab, Recreation |
| Strukturfabrik | Bausatz herstellen | `UnitEx::DoProduce`; nicht mehr Bausätze als ConVecs; zu teuer → warten; nach 2500 Ticks ohne Ergebnis wird der Typ eine Weile gesperrt |
| ConVecs | Bausatz holen und bauen | `DoDock` an der Fabrik, `DoTransferCargo`, `DoBuild` auf dem Raster; drei Fehlversuche → Platz gesperrt, nächster Platz |
| Raster | Wo gebaut wird | Plätze 4×3 mit 1 Kachel Gasse (Abstand 5×4), Platz (0,0) = Kommandozentrale; Grundfläche bebaubar, Rand befahrbar und ohne Gebäude |
| Röhren | Anschluss an die CC | je Platz zwei gerade Stücke durch die Gassen; der Earthworker baut sie mit `DoBuildWall(mapTube)` |
| Erz | Mine und Route | Surveyor zur nächsten Bake, Miner `DoDeployMiner` auf die vermessene, je Mine eine `MiningGroup` zur Schmelze mit zwei Lastwagen |
| Fahrzeugfabrik | Nachschub | 2 ConVecs, 1 Earthworker, 2 Lastwagen je Mine, 1 Surveyor, 1 Miner, 3. ConVec bei Erzüberschuss |
| Forschung | freie Labore | Thema aus der Tech-Tabelle: passendes Labor, Voraussetzungen erfüllt, Vorrang Nahrung → Metalle → Strom → Bevölkerung → Moral → Rest, billigstes zuerst |

Ob `DoResearch` die techID oder den Tabellenindex will, ist nicht sicher dokumentiert. Die KI
prüft nach dem ersten Auftrag, ob das Labor arbeitet, wechselt sonst die Lesart und schreibt das
in die Spur.

## Die Spur

`<Spiel>/OPU/logs/<Mission>-KI.jsonl`, eine JSON-Zeile je Ereignis:

- `start`: Spieler, Kartengröße, Basismitte, Engine-Ursprung
- `entscheid`: `was` (bau, kit, laden, holen, fertig, fahrzeug, forschung, mine, vermessen, roehre,
  warte, fehler, info), `typ`, `x`/`y` in Editor-Kacheln, `warum`
- `stand` (alle 200 Ticks): Rohstoffe, Strom, Bevölkerung, alle Gebäude und Fahrzeuge,
  geplante Plätze mit Zustand, Röhrenaufträge

Im Editor: *Ansicht → KI-Spur*. Spur öffnen, Regler über die Momentaufnahmen, die Karte zeigt
Gebäude (grün), Fahrzeuge (blau, ConVec mit Bausatz als „CV→Tokamak“), geplante Plätze
(gestrichelt: gelb unterwegs, orange im Bau, rot gesperrt), Röhren und die Basismitte. Die Liste
zeigt die Entscheidungen bis zum gewählten Zeitpunkt; ein Klick springt auf der Karte hin.
**Live** liest die Datei jede Sekunde nach, während das Spiel läuft.

## Spielstand

Der ganze Zustand steckt in `ki::Zustand` (feste Größe, keine Zeiger) und liegt in der
SaveRegion der Mission (`g_save.ki_<Spieler>`). Nach dem Laden macht die KI dort weiter.

## Bekannte Grenzen

- Nur Wirtschaft und Forschung, noch kein Militär.
- Nur gewöhnliches Erz, kein Rare Ore, keine Raumfahrt.
- Raster kompakt um die Mitte; Schmelzen stehen nicht bei den Minen.
- Mehrspieler nicht geprüft (die KI läuft dort auf jedem Rechner und muss überall gleich entscheiden).
- Annahmen über die Engine, die erst das Spiel bestätigt: Bauplatz-Regeln (Rand frei von Gebäuden),
  Anschluss über Röhren in den Gassen, Andocken an der Strukturfabrik, Lesart von `DoResearch`.
  Wo es klemmt, steht es in der Spur.
