# Das Kartenmodell / The map model

*English summary at the end.*

Die Vorlage „Wie die Originale (gelernt)" in *Neue Karte* (`mapview/mapgen_netz.py`,
`mapgen_netz_waende.py`). Stand 25.11.2026.

## Womit gelernt wurde

126 lesbare Karten lagen vor (`maps.vol` und OPU); nach dem Aussortieren von Kopien
und verschobenen Kopien blieben 73. Davon 61 zum Lernen und 12 zum Prüfen; die
Prüfkarten teilen mit keiner anderen Karte mehr als 15 % ihrer 8×8-Wandfenster. Die
Karten selbst sind nicht Teil des Repos, nur die Gewichte der Netze und die Liste der
Kachelpaare, die vorkommen.

## Zwei Netze

1. **Skizze** (`netz_skizze.onnx`, 0,72 Mio. Gewichte). Raster: ein Feld je 2×2
   Kacheln mit Wand und Fallrichtung, Boden je 4×4. Vorgabe sind Zonen: eng (Berg,
   Schlucht), Bauland (Tal, Hochebene) oder offen. Gelernt wird durch Lückenfüllen.
   Fehler auf den Prüfkarten (Wand): 0,39; vier Nachbarn auszählen: 0,50.
2. **Kacheln** (`netz_kacheln.onnx`, 1,26 Mio. Gewichte, 1442 Kacheln). Malt die Karte
   nach der Skizze, wieder durch Lückenfüllen gelernt. Fehler auf den Prüfkarten 2,93,
   ohne Skizze 3,27. Nachbau der 12 Prüfkarten aus ihrer Skizze: 91 % der gesetzten
   Wände am richtigen Ort, 93 % der Originalwände wiedergefunden; 0,1 % der
   8×8-Wandfenster stehen so auch in einer Lernkarte.

Beide sind kleine Faltungsnetze mit drei Auflösungen, gelernt mit PyTorch auf der CPU
(50 Minuten und 3 Stunden), gerechnet mit ONNX Runtime; die Abweichung zu PyTorch ist
höchstens 0,0002.

## Ablauf

Zonen (`berg_plan`) → Skizze ziehen → Wände verbinden, verlängern, doppelte
Nordkanten ausdünnen, ein Boden je Wand → Kacheln malen → unbekannte Paare und
Wandreste neu malen → Bergstufen → Sprenkel, Objekte, Notfelsen → Startpunkte.

Was sich dabei gezeigt hat:

- **Skizze in zufälliger Reihenfolge ziehen.** „Das Sicherste zuerst" ergibt fast leere
  Karten, denn am sichersten ist überall „keine Wand".
- **Nordkanten nicht erzwingen.** Sie sind eine Kachel dick, das Skizzenfeld zwei; der
  Zwang machte Doppelstriche (22 % statt 12 % der Wände).
- **Boden unter Bergen vorgeben.** In den Originalen liegen 94 % der bergartigen Gebiete
  auf Erde, 6 % auf Sand; Wände auf Fels gibt es kaum.
- **Freie Fläche als Bauland vorgeben,** sonst füllt das Netz alles mit Wänden
  (Klippenregler).
- **Die Karte ist ein Ausschnitt.** Zonen und Skizze entstehen auf einer Fläche, die
  ringsum 32 Kacheln weiter reicht, und werden dann ausgeschnitten. Vorher kreuzten 0,7
  Wände den Rand einer 128×128-Karte, jetzt 8 bis 12, in den Originalen etwa 12.
- **Nur offene Felder und nur ihren Ausschnitt rechnen:** 128×128 in 2–6 s statt 60–100 s.

## Großform

Das Skizzennetz sieht nur seine Umgebung; die Karten wirkten lose. Deshalb
entsteht zuerst ein Höhenplan der ganzen Karte (`mapgen_netz_gross.py`): große
Hochflächen und Kessel aus weichem Rauschen, grob gerastert, damit die Klippen in
geraden Stufen laufen. Ihre Ränder gehen als feste Wandfelder ins Skizzennetz. Ein
erster Entwurf liefert die Böden, die beim Beruhigen nicht über Wände hinweg
verlaufen; danach zieht das Netz die Wände passend zu diesen Böden noch einmal.
Gemessen an 81 Ausschnitten der Originale und 52 erzeugten Karten:

| | Original | vorher | jetzt |
|---|---|---|---|
| Biomgrenze an einer Klippe | 31 % | 7 % | 26 % |
| Klippe an einer Biomgrenze | 26 % | 6 % | 19 % |
| umschlossene Flächen je Karte | 3,1 | 0,8 | 3,7 |
| Gelände ohne Klippe in 14 Kacheln | 30 % | 45 % | 23 % |
| typische Klippenlänge (Kacheln) | 175 | 140 | 282 |
| Wandstücke unter 30 Kacheln je Karte | 3,6 | 10,2 | 3,9 |

In Bergzonen liegen ineinander geschachtelte Höhenlinien statt einzelner Stufen,
dazu kommen kleine ringsum geschlossene Kuppen. Das Kachelnetz lässt dünne
Nordkanten gern aus (ein Drittel der Skizzenfelder blieb ohne Wandkachel);
`luecken_zu` malt solche Löcher neu, `reste_weg` entfernt Inseln unter 24 Kacheln.

Mit Großform verteilt `mapgen_berge._ketten_verteilt` die Berge über die ganze
Welt samt Rand, verschieden groß und gerichtet; vorher lag fast immer eine lange
Kette mittig. Der Regler *Gelände ruhiger* (`gelaende_ruhe`) macht den Höhenplan
großflächiger, nimmt Terrassen und Kuppen weg und erklärt abseits der großen
Linien, auch im Berg, mehr Fläche zu Bauland, damit das Netz dort keine eigenen
kurzen Klippen zeichnet.

Merkmale kennt diese Vorlage nicht (sie wurden ausprobiert und verworfen).

Vulkane in drei Größen (`vulkanplaetze`, `vulkane` in `mapgen_netz_fels.py`):
die Skizze reserviert für jeden einen Platz, Lavafels für mittel und groß, Fels
für klein; beim Stempeln ersetzen bis zu 15 % fremde Kacheln im Rahmen die
häufigste Grundkachel. Krater, Risse und Trümmer (`mapgen_netz_deko.py`) sind die
Kachelgruppen des Spiels, nur auf ihrem Boden und mit passender Naht; Trümmer als
Absturzstellen in Gruppen.

Verlauf (`verlauf_feld`, `verlauf_gelaende` in `mapgen_basis.py`): ein Feld 0..1
über die Karte. Boden: Skizzennetz und Beruhigen bekommen je Ort einen Zuschlag
für den Boden an diesem Ende. Gelände: Berge, Hochflächen und Kessel rutschen auf
die bergige Seite, auf der flachen fallen Linien der Großform weg und das Netz
bekommt mehr Bauland.

Threads: 8 sind am schnellsten (128x128: 2 Threads 6,4 s, 4: 3,7 s, 8: 3,1 s,
16: 4,9 s, 30: 6,3 s), das ist die Vorgabe auf Rechnern mit 16 und mehr Threads.

## Böden beruhigen, Lavafels und Vulkane

Das Skizzennetz wechselt den Boden zu oft und kennt nur „Fels". Dafür gibt es eigene
Schritte (`_biome_beruhigen`, `mapgen_netz_fels.py`), gemessen an 65 Ausschnitten
128×128 aus 54 Originalkarten mit Fels und 52 erzeugten Karten (Regler 50):

| | Original | vorher | jetzt |
|---|---|---|---|
| Biomgrenze je Karte (4×4-Raster) | 212 | 163 | 186 |
| Umfang der Felsgebiete / √Fläche | 8,0 | 5,7 | 6,7 |
| Lavafels-Flecken je Karte | 3,3 | 18,4 | 1,9 |
| Größe eines Lavaflecks (Mittel der Karten-Mediane) | 463 | 4 | 325 |
| Fels stößt ohne Übergang an Lavafels, je Lava-Paar | 0,02 | 0,97 | 0,01 |
| Wechsel der Felsmuster je Paar | 0,04 | 0,11 | 0,03 |

„Vorher" ist mit dem Ruheregler auf 50, aber ohne Verbiegen und Lavaplan; ohne
Ruheregler lag die Biomgrenze bei 304. Fels besteht aus zwei Böden: Fels (`rocbas1/2`)
und dunkler Lavafels (`rocbas3-5`), dazwischen `roctola`. Geplant wird zuerst, wo die
Lava liegt; direkte Nachbarn Fels|Lavafels sind verboten, also muss das Netz Übergänge
legen. Vulkane werden in die Lavakerne gestempelt.

## Grenzen

- Wände sind im Mittel kürzer als in den Originalen.
- Ein eigens gelerntes Prüfernetz unterscheidet erzeugte von echten Ausschnitten
  weiterhin meist (0,95–0,98; 0,5 wäre Raten). Geprüft an früheren Fassungen.
- Schnee kommt nicht vor. Hochebenen sind nicht sicher erhöht.
- Berge sind befahrbar; je nach Regler bleibt ein Teil bebaubar, auf Sand mehr.
- Bei 256×256 etwa 16 s (gut: 34 s), gemessen mit 8 Threads.

Im Originalspiel (Harness): 4 Karten, darunter eine 256×256 und eine gespiegelte, 59
Panzer zu Hochebenen, Tälern, Schluchten, Bergen und Startplätzen; alle kamen an.

## English summary

Two small convolutional networks trained by in-filling on 61 maps (12 more held out,
each sharing less than 15 % of its 8×8 wall windows with any other map). The first
sketches walls and grounds from zones, the second paints tiles after the sketch and may
only use tile pairs seen in the training maps. The maps themselves are not part of this
repository. Rebuilding the 12 held-out maps from their sketches puts 91 % of the walls
in the right place; 0.1 % of the 8×8 wall windows are copies. Limits: walls are shorter
than in the originals, no snow, plateaus are not necessarily raised,
mountains are passable, and a critic network can still tell generated from original
crops (0.95–0.98 on earlier versions, 0.5 would be guessing).
