# Aufbau-KI: eine Kolonie von null

Stand: erster Baustein (November 2026). Noch nicht im Spiel erprobt — die Spur ist dafür da,
genau das zu tun.

## Einschalten

*Mission → Spieler*: Spieler auf **KI** stellen, **KI baut die Kolonie selbst auf** anhaken.
Basismitte (Editor-Kacheln, Standard: Kartenmitte) und **Startausrüstung erzeugen** wählen.
Mit Startausrüstung legt die KI in InitProc selbst an:

- 5 ConVecs mit Bausätzen: Kommandozentrale, Strukturfabrik, Tokamak, Erzschmelze, Agridome
- Robo-Miner, Robo-Surveyor, 2 Lastwagen, Earthworker

Die Startausrüstung parkt 9 Kacheln unter der Basismitte — stehende Fahrzeuge blockieren Bauplätze.
Ohne Startausrüstung arbeitet sie mit den Einheiten, die im Editor für diesen Spieler stehen.
Kolonisten, Erz und Tech-Level kommen wie gewohnt aus dem Spieler-Dialog. Setzt die Mission keine
Kolonisten, gibt das Spiel KI-Spielern 4096 Arbeiter, 4096 Wissenschaftler und 256 Kinder; dann
beachtet die KI den Wohnraum nicht.

## Was sie tut (Takt: alle 20 Ticks)

| Teil | Was | Wie |
|---|---|---|
| Lagebild | Gebäude, Fahrzeuge, Bausätze, Erz, Nahrung, Strom, Wohnraum | `PlayerBuildingEnum` je Typ, `PlayerVehicleEnum`, HFL `PlayerEx` |
| Bedarf | Was fehlt als Nächstes? | feste Reihenfolge (CC, Strukturfabrik, Tokamak, Schmelze, Agridome), dann nach Lage: Strom < 25, Nahrung netto < 0, Wohnraum, Fahrzeugfabrik, Labor, Lager, Nursery, University, Medical Center, Standard Lab, Recreation |
| Strukturfabrik | Bausatz herstellen | `UnitEx::DoProduce`; nicht mehr Bausätze als ConVecs; zu teuer → warten; nach 2500 Ticks ohne Ergebnis wird der Typ eine Weile gesperrt |
| ConVecs | Bausatz holen und bauen | `DoDock` an der Fabrik, `DoTransferCargo`, `DoBuild` auf dem gewählten Platz; drei Fehlversuche → Platz gesperrt, nächster Platz |
| Bauplatz | Wo gebaut wird | Jedes Gebäude außer Kraftwerken und Minen bringt zwei Röhrenstücke mit: rechts und unten, jeweils mittig im 1 Kachel breiten Rand. Am Anfang gibt es kein Metall für weitere Röhren, also steht jedes neue Gebäude genau 1 Kachel neben einem vorhandenen, so dass ein Stück des einen die Seite des anderen trifft. Kraftwerke kommen etwas abseits (Ring um die Mitte), die Kommandozentrale so nah an die Basismitte wie möglich |
| Röhren | (später) | Der Earthworker kann Röhrenaufträge abarbeiten; beim Start werden keine angelegt |
| Erz | Mine und Route | nächste freie gewöhnliche Bake (vermessene bevorzugt); der Surveyor fährt hin und vermisst, der Miner baut mit `DoDeployMiner`, sobald sie vermessen ist — oder ohne, wenn es keinen Surveyor gibt oder er länger als 1200 Ticks braucht. Je Mine eine `MiningGroup` zur Schmelze mit zwei Lastwagen. Baken sucht die KI auf drei Wegen (Rechteck über die Karte, Umkreis um die Basis, selbst angelegte per Kachel) und schreibt die Zahlen in die Spur |
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
- Basis kompakt um die Kommandozentrale; Schmelzen stehen nicht bei den Minen.
- Ohne Schmelze oder Lager kann die Kolonie kein Erz speichern: die Startressourcen verfallen, bis die Schmelze steht.
- Mehrspieler nicht geprüft (die KI läuft dort auf jedem Rechner und muss überall gleich entscheiden).
- Im Spiel gemessen (erster Lauf): `DoBuild(L)` legt die Grundfläche auf `[L.x−w, L.x−1] × [L.y−h, L.y−1]` —
  `L` ist die Ecke unten rechts des Rechtecks mit Rand. `Location()` eines Gebäudes ist die Mitte
  (`x0 + w/2`, `y0 + h/2`). Baken kommen aus dem Missionsskript; mit Startausrüstung legt die KI zwei
  an, wenn keine in 40 Kacheln Umkreis liegt.
- Annahmen über die Engine, die erst das Spiel bestätigt: Bauplatz-Regeln (Rand frei von Gebäuden),
  Anschluss über die Röhrenstücke der Gebäude, Andocken an der Strukturfabrik, Lesart von `DoResearch`.
  Wo es klemmt, steht es in der Spur.
