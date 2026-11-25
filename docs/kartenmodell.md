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

Zonen (`berg_plan`, Merkmale) → Skizze ziehen → Wände verbinden, verlängern, doppelte
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

## Grenzen

- Wände sind im Mittel kürzer als in den Originalen.
- Ein eigens gelerntes Prüfernetz unterscheidet erzeugte von echten Ausschnitten
  weiterhin meist (0,95–0,98; 0,5 wäre Raten). Geprüft an früheren Fassungen.
- Schnee, Lava und Vulkane kommen nicht vor. Hochebenen sind nicht sicher erhöht.
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
than in the originals, no snow, lava or volcanoes, plateaus are not necessarily raised,
mountains are passable, and a critic network can still tell generated from original
crops (0.95–0.98 on earlier versions, 0.5 would be guessing).
