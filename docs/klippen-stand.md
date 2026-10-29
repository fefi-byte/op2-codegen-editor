# Klippen: Stand, Modell, offene Punkte

Uebergabe nach der Sitzung vom 30.07.2026. Alles hier ist gemessen, nicht
geschaetzt; wo eine Zahl steht, steht dabei, woran sie gemessen wurde.

Alle drei Suiten sind gruen:

```bash
python mapview/tests/mapgen_test.py && python mapview/tests/map_roundtrip.py && python editor/tests/ui_smoke.py
```

---

## 1. Die Grundidee

Klippen entstehen **nicht** mehr aus einer gemalten Flaeche. Der alte Weg war
Flaeche → Hoehenfeld → dreizeiliges Zelltypband → Kachel je Zelle; nach drei
Ableitungen war nicht mehr bekannt, wo die Wand gemeint war.

Stattdessen wird die **Kante direkt gezeichnet**: eine Punktfolge plus die
Seite, auf der es hoch geht. Damit steht alles fest, was die Bloecke brauchen.
Zustaendig ist `mapgen.klippe_aus_linie(grid, punkte, hoch_seite, tm, rng, familie)`
→ `(maske, zellenfeld)`.

Gearbeitet wird ausschliesslich mit **ganzen Gruppen** (`*mes*` — die Pinsel,
mit denen die Entwickler gemalt haben), nie mit Einzelkacheln. Einzeln gezogen
ergeben sie Flickwerk.

---

## 2. Das Klippenmodell (`cliffs_model.npz`)

Eigene Datei, eigener Trainer: `mapview/learn_cliffs.py`.

```bash
python mapview/learn_cliffs.py
```

**Getrennt vom Kachelmodell**, weil `tiles_model.npz` die durchgemessene
Statistik des Bodensamplers traegt und von den Klippen nicht angefasst werden
darf. Fehlt `cliffs_model.npz`, laeuft der Generator weiter und faellt auf die
Pixelregel zurueck.

Inhalt: 35 Gruppen (18 mud, 17 san), 107 Karten, 12938 Vorkommen,
**13058 beruehrende Blockpaare mit Versatz**.

### Warum abgezaehlt und nicht geschaetzt

Die Gruppen stehen **woertlich** in den Karten — die Entwickler haben mit genau
diesen Pinseln gemalt. Alle 35 kommen vor. Die Nachbarschaft ist damit eine
Zaehlung.

Die vorher benutzte Pixelregel (`block_kante_ist_wand` ueber Farbabstand)
beurteilt nur **75 %** der Blockkanten so wie die Karten, und sie irrt
einseitig: sie uebersieht Waende. `sanmes01` etwa gilt ihr als "nirgends Wand",
obwohl der Block ost und west an Klippen grenzt. Die Messung hat Vorrang; die
Pixelregel bleibt nur fuer Bloecke zustaendig, zu denen die Messung schweigt.

### Die API auf dem `TileModel`

| Aufruf | liefert |
|---|---|
| `tm.klippen_gruppe(block)` | Gruppenname zu einem Kachelmuster |
| `tm.klippen_seite_frei(block, seite)` | darf dort eine Klippe anschliessen? |
| `tm.klippen_gewicht(a, b, seite)` | wie oft lag b auf dieser Seite von a |
| `tm.klippen_bester_versatz(a, b, seite)` | haeufigster Versatz entlang der Naht |
| `tm.klippen_belegt(a, b, seite)` | die nackte Zaehlung, **ohne** Grundrate |
| `mapgen.klippen_hochseite(block)` | wohin das **Hochland** zeigt: `"SW"`, `"N"`, … |
| `mapgen.klippen_hoch_passt(block, soll)` | widerspricht die Hochseite nicht? |
| `mapgen.klippe_achse_an(grid, x, y, tm, fam)` | `("v"\|"h", Seite)` der Klippe dort |
| `mapgen.klippe_wand_an(grid, x, y, tm, fam)` | dasselbe **plus Block und Lage** |
| `mapgen.klippen_treffer(grid, x, y, tm, fam)` | alle ganzen Bloecke dort, nach Abstand |

`klippen_belegt` und `klippen_gewicht` beantworten zwei verschiedene Fragen.
Das Gewicht traegt die Grundrate und waehlt **unter** Kandidaten; die nackte
Zaehlung entscheidet, ob ueberhaupt einer hingehoert. Fuer die zweite Frage
waere die Grundrate eine Erfindung.

`klippe_wand_an` gibt zusaetzlich den Block und seine Lage zurueck. Die Achse
allein beantwortet „braucht es hier eine Ecke?", nicht „wo genau" — dafuer
braucht die Ecke die Flucht der vorhandenen Wand.

`klippen_treffer` liefert bewusst die ganze Liste. Die Suche haengt nicht
davon ab, wonach gefragt wird -- nur ihre Auswertung tut das, und die braucht
verschiedene Bloecke: der Anker einen, der in Laufrichtung durchgeht, die
Achsenfrage einen mit zwei gegenueberliegenden Wandseiten. Wer nur den ersten
Treffer ansieht, gibt am Wandende auf (siehe 7.1).

`seite`: 0 = Ost, 1 = West, 2 = Sued, 3 = Nord — wie in den Kantensignaturen,
gelesen als "b liegt dort von a".

### Zwei Konstanten, die Entscheidungen sind

`TileModel.KLIPPEN_ANTEIL = 0.10` — ab welchem **Anteil** der Nachbarschaften
eines Blocks eine Seite als Wandkante gilt. Bewusst ein Anteil: eine feste Zahl
haengt daran, wie viele Karten zufaellig im Training liegen. Gemessen an 13
unabhaengig belegten Regeln haelt eine feste 3 bei 33 Karten alle 13, bei 107
nur noch 8 — drei von 25 Faellen sind ein Signal, drei von 629 sind Rauschen.

`TileModel.KLIPPEN_GRUNDRATE = 0.5` — Grundgewicht fuer eine nie beobachtete
Paarung auf einer erlaubten Seite. Die Messung sagt, was die Entwickler taten,
nicht was moeglich ist.

---

## 3. Die 13 belegten Regeln

Vom Nutzer von Hand benannt, **bevor** gemessen wurde — also keine
Zirkelpruefung. Sie stehen als Liste in `check_klippen_nachbarn`
(`mapview/tests/mapgen_test.py`) und laufen bei jedem Testlauf mit:

- `sanmes00/01/02` haben nord und sued **keine** Klippenkante
- `sanmes07` und `sanmes14` haben ost und west **keine** (reine Sanduebergaenge)
- `sanmes07` ist nord/sued stapelbar
- `sanmes05` gehoert ueber `sanmes07`

Jede Aenderung an Datenmenge oder Schwelle muss diese 13 weiter erfuellen.

---

## 4. Was der Kachelsatz hergibt (gemessen)

**Blocklaengen — je Richtung gibt es genau EINE:**

| Topf | Laenge |
|---|---|
| san senkrecht (O/W) | 4 |
| san waagerecht (S/N) | 3 |
| mud senkrecht | 5 |
| mud waagerecht | 3 |

Eine gezeichnete Strecke geht deshalb fast nie glatt auf. Deshalb laufen die
Laeufe **durch** und die Ecke deckt den Ueberstand (siehe 5.).

**Abschlussstuecke** (Wand auf genau einer Seite):

| Ende | san | mud |
|---|---|---|
| links (nur Ost) | `sanmes12` | `mudmes05` |
| rechts (nur West) | `sanmes08` | `mudmes08` |
| oben (nur Sued) | **keiner** | **keiner** |
| unten (nur Nord) | **keiner** | **keiner** |

Fuer **senkrechte** Waende gibt es in keiner Familie einen Abschluss. Die
Entwickler haben senkrechte Waende nie abgeschlossen. Dort bleibt die Stelle
frei — das ist ehrlicher als ein verdrehter Eckblock.

**Schraege Waende sind Treppen, keine Geraden.** Gemessen an `cm03`, 919
Kantenschritte: wie weit sich die linke Klippenkante von einer Zeile zur
naechsten waagerecht versetzt.

| Versatz je Zeile | Anteil | entspricht |
|---|---|---|
| 0 Spalten | **55,2 %** | senkrecht |
| ±1 Spalte | 24,5 % | 45° |
| ±2 Spalten | 8,0 % | 26,6° |
| ±3 Spalten | 6,6 % | 18,4° |
| ±4 Spalten | 3,6 % | 14,0° |

Ueber die Haelfte aller Schritte ist **senkrecht**, und mehr als vier Spalten
kommt nicht vor. Eine schraege Klippe entsteht also nicht aus einem festen
Neigungsverhaeltnis, sondern indem senkrechte Stuecke mit Versaetzen gemischt
werden. Die Schraege bei `cm03` (82,39) etwa wechselt zwischen −1 und −2 und
kommt so auf 1,6:1, also 32° — ein Winkel, den kein einzelnes
Kachelverhaeltnis hergibt.

Daraus die neun **Baurichtungen** des Pinsels (`KLIPPEN_NEIGUNGEN`, in alle
vier Quadranten gespiegelt gibt das 32 Richtungen): 0°, 14,0°, 18,4°, 26,6°,
45°, 63,4°, 71,6°, 76,0°, 90°. Ein Klick rastet auf die naechstgelegene, die
Streckenlaenge bleibt dabei erhalten — die Strecke dreht sich nur.

**Nordkanten sind haarfein.** `sanmes00/01/02` sind 1x3 und tragen nur
`NORTH_CLIFFS`. Liegt das Hochland suedlich einer Strecke, ist sie deren
Nordkante und wird eine duenne Linie. Das ist echt — in `newworld` sehen die
Hochflaechen genauso aus. Kein Fehler.

---

## 5. Der Ablauf in `klippe_aus_linie`

1. **Hand bestimmen** (`_klippen_hand`): die Hochseite bezieht sich auf die
   **Zeichenrichtung**, nicht auf den Bildschirm. Nach Sueden laufend liegt
   links im Osten; nach Osten laufend liegt links im Norden — beides derselbe
   Quadrant. `oben`/`unten` werden auf das erste Stueck bezogen.
2. **Topf waehlen** (`_klippen_richtung`): der Schluessel benennt die
   **Tief**seite. `"O"` heisst Tiefe im Osten, also Hochland **West**.
3. **Laeufe** — durchgehend bis zum gezeichneten Punkt; der letzte Block wird
   auf diesen Punkt **zurueckgezogen** und ueberlappt dabei seinen Vorgaenger.
   Nur Bloecke, deren Wand in Laufrichtung weitergeht (senkrecht: Nord **und**
   Sued; waagerecht: Ost **und** West). Der erste Block legt die Flucht fest,
   jeder weitere haengt sich mit dem **gemessenen Versatz** an.
4. **Ecken zuletzt** — sie decken den Ueberstand zu. Zwei harte Bedingungen:
   Wand auf den gebrauchten Seiten **und** eine Hochseite, die der gewuenschten
   nicht widerspricht (siehe „Wandseite ist nicht Hochseite"). Die Auswahl
   darunter ist **gewichtet** nach der gemessenen Nachbarschaft zu den
   tatsaechlich angrenzenden Laufbloecken.
5. **Abschluesse** an offenen Enden, nur wo es einen echten gibt, und nicht
   dort, wo schon eine Ecke steht oder wo die Linie eine vorhandene Wand
   gerade fortsetzt.
6. **T-Stoesse zuallerletzt** — trifft der Zug mitten auf eine vorhandene Wand,
   kommen deren Bloecke wieder obenauf. Es gibt kein T-Stueck (siehe 7.5), also
   bleibt die Querwand, wie sie war, und der Abzweig stoesst an sie.

### Wandseite ist nicht Hochseite

Die beiden sind unabhaengig, und das Uebersehen dieser Trennung war der
groesste der gefundenen Fehler.

`block_kante_ist_wand(b, seite)` beantwortet: **laeuft die Wand ueber diese
Blockkante weiter?** Das steuert die Laeufe richtig. Es sagt aber nichts
darueber, **welche Seite oben ist** — und genau das entscheidet, ob eine
Hochflaeche innen oder aussen liegt.

`mudmes01` und `mudmes07` haben beide Wand nach West und Sued. Bei `mudmes01`
liegt das Hochland suedwestlich, bei `mudmes07` nordoestlich. Wer nur die
Wandseiten prueft, greift die um 180 Grad verdrehte Ecke.

`mapgen.klippen_hochseite(block)` liest die Richtung aus den **Zelltypen**:
Schwerpunkt der Hochseitenzellen gegen den der Tiefseitenzellen, wobei eine
Nordkante als Hochland suedlich davon zaehlt. Gemessen ueber alle Bloecke:

| Ecke einer Hochflaeche | Wand quert | Hochland | mud | san |
|---|---|---|---|---|
| Nordost | W + S | SW | `mudmes01` | `sanmes15` |
| Nordwest | O + S | SO | `mudmes02` | `sanmes05` |
| Suedost | W + N | NW | `mudmes11`, `mudmes12` | `sanmes11` |
| Suedwest | O + N | NO | `mudmes00`, `mudmes15` | `sanmes09` |

**Zu jeder der vier Ecken gibt es in beiden Familien einen Block.** Die
Wandbedingung allein laesst aber 2 bis 3 zu, darunter den verdrehten. Ohne die
Hochseitenfrage traf es bei mud **jeden** Seed: `mudmes07` war der einzige
Kandidat mit Wand West+Sued in den Toepfen „Ecke" und „Motiv" — und der
falsche. Bei san 2 von 12.

**Der Kandidatenkreis war zu eng.** `mudmes01` liegt im *Richtungstopf* `O`,
nicht in „Ecke"/„Motiv" — er konnte gar nicht gewaehlt werden. Fuer Ecken kommt
deshalb jetzt der ganze Kachelsatz der Familie in Frage; aussortiert wird ueber
Wandseiten und Hochseite, nicht ueber den Topf, aus dem ein Block stammt.

Die Hochseitenpruefung ist **kein Gleichheitstest**: ein Block, dessen
Hochland nur nach Sueden zeigt, taugt auch fuer eine Ecke mit Hochland
suedwestlich. Ausgeschlossen wird nur der echte Widerspruch — Hochland nach
Norden, wo es nach Sueden gehoert.

### Eine Naht ist kein Ende

Setzt eine Linie an einer vorhandenen Klippe an, ist ihr Startpunkt keine
Wandkante, sondern eine Naht — die Wand laeuft auf beiden Seiten weiter. Daran
haengen drei Dinge, und sie hingen alle drei falsch:

- **Anker.** Flucht und Paarung kommen von einem Block, der in Laufrichtung
  *durchgeht*. Am dichtesten beim Klick liegt aber das Abschlussstueck des
  alten Zuges, und das hat nur eine Wandseite — als Partner gewaehlt richtet es
  die Fortsetzung an einem Wandende aus statt an der Wand. Das verschiebt die
  ganze Wand: gemessen an `v->h`, mud, Arm 9, Seed 1 lag die waagerechte
  Fortsetzung **vier Reihen ueber** der gezeichneten Linie und hing frei in der
  Landschaft; mit dem durchgehenden Block als Anker sitzt sie auf der Linie und
  trifft das Ende der senkrechten Wand.
- **Die alte Kappe muss weg.** Der Lauf faengt deshalb auf ihr an statt am
  Klick und ueberschreibt sie; ueberstehen duerfen die Laeufe ohnehin.
- **Der neue Zug darf dort keine setzen.** Sonst steht sofort die naechste da.
- **Die Ecke muss die alte Wand kennen.** Sie stammt aus einem frueheren Zug
  und steht deshalb weder in `flucht_spalte` noch in `anschluss` — die Ecke
  zentrierte sich auf den Klick. Bei einer 2 Kacheln breiten Wand (`mudmes16`)
  und einem 3 Kacheln breiten Eckstueck (`mudmes14`) ragte sie damit genau eine
  Spalte nach Osten hinaus. Jetzt wird die vorhandene Wand als Nachbar
  eingetragen; die Ecke richtet sich mit dem gemessenen Versatz an ihr aus und
  wird ausserdem nach der Nachbarschaft zu ihr gewichtet. Bei `san` faellt es
  nicht auf — dort ist die Wand selbst 3 breit und das Eckstueck passte
  zufaellig.

Beide Kappen zusammen ergaben den hellen, flachen Fleck mitten in einer
fortgesetzten Wand. Gemessen wird das ueber „traegt die Wand im Inneren einen
Block mit Wand auf genau einer Seite?" — vor der Korrektur `sanmes12` bzw.
`mudmes05`, danach keinen.

### Ueberlappen ist erlaubt

Nur die Ecken sind unantastbar; die Laeufe duerfen einander ueberdecken.

**Wichtig, weil ich mich hier geirrt habe:** Eine Zaehlung ueberlappender
Blockpaare ergab null in 107 Karten — das war ein **Fehler der Methode**. Ein
ueberlappter Block ist teilweise ueberschrieben und wird von der Mustersuche
gar nicht mehr gefunden; die Zaehlung *kann* ihn nicht sehen. Der Gegentest
entscheidet: nur **42 %** der Klippenzellen der Originalkarten sind von
vollstaendigen Bloecken gedeckt, bei `on6_01` nur **15 %**. Die Entwickler
haben sehr wohl ueberlappt.

**Derselbe blinde Fleck trifft den Generator, nicht nur die Zaehlung.** Alles,
was ueber `klippen_treffer` laeuft — Anker, Achse, Nahterkennung — sucht ganze
Bloecke wieder und findet einen ueberlappten nicht. Je mehr ueberlappt wird,
desto oefter greift das ins Leere. Wer Ueberlappung hinzufuegt, muss pruefen,
was danach noch gefunden wird (siehe 7.3).

---

## 6. Der Editor

**Pinsel „Klippe zeichnen"** im Gelaende-Tab. Kein Flaechenpinsel: jeder Klick
setzt einen Stuetzpunkt, die Punkte erscheinen als gelbe Linie. Darunter die
Hochseite waehlen, dann „Klippe setzen". Derselbe Punkt am Schluss schliesst
die Figur.

**Baurichtungen.** Ab dem zweiten Punkt rastet der Klick auf eine der neun
gemessenen Neigungen (siehe 4.). Sobald ein Punkt steht, folgt eine
gestrichelte Linie dem Zeiger und zeigt die gerastete Richtung, bevor man sie
setzt. Frei gezogene Schraegen gibt es nicht -- sie kommen in den
Originalkarten nicht vor.

Beim Ziehen ruft der Editor `_terrain_stamp` bei **jeder Mausbewegung** auf —
deshalb zaehlt nur der erste Aufruf eines Strichs als Klick (`_klick_neu`).

**Fortsetzen:** neue Linie am Ende der alten beginnen — oder auf ihr enden.
Blaue Ringe zeigen offene Enden; **jeder** Klick rastet im Umkreis von 5
Kacheln darauf ein, nicht nur der erste, und ein gemerktes Ende gewinnt gegen
einen abgeleiteten Ring (siehe 7.4). Auch **mitten auf eine Wand** laesst sich
zielen: dort zeigt ein gestrichelter Ring unter dem Zeiger, wohin der Klick
faellt (Umkreis 3, siehe 7.6). Die Laufrichtung der vorhandenen Klippe
wird **aus dem Modell** ermittelt (`klippe_achse_an`), nicht gespeichert — das
gilt auch fuer geladene Karten.

**Einen Hochland-Pinsel gibt es nicht mehr** (geloescht 30.07.2026). Hochland
aus einer gemalten Flaeche abzuleiten war der alte Weg, an dem die Klippen
gescheitert sind (siehe 1.). Hochland entsteht jetzt nur noch dort, wo eine
gezeichnete Klippe es setzt.

**Achtung, der zweite Klippenweg lebt weiter.** `klippen_laeufer` und
`_male_klippen` haengen nicht am geloeschten Pinsel, sondern an
`synth_region` — und das laeuft nach *jedem* Gelaendestrich. Sobald ein
Bodenpinsel ueber eine Flaeche mit Hochland geht, leitet dieser Weg dort wieder
ein Klippenband ab. Er kennt keine der Korrekturen aus 7.; ihn zu pruefen steht
noch aus.

**Entfernen:** der Pinsel **„Tiefland"** ist der Radierer. Er setzt die
Hoehenebene auf 0, `synth_region` leitet daraus wieder normalen Boden ab.
Gemessen: 60 gezeichnete Klippenzellen, danach null davon uebrig.

Beteiligte Stellen: `editor/app/paint_layers.py` (`klippe_zeichnen`,
`offene_enden`, `klippen_anker`), `editor/app/window_terrain.py`
(`_klippe_punkt`, `_klippe_setzen`, `_klippen_vorschau`),
`editor/app/panels/terrain_panel.py`, `lang.de.ini` / `lang.en.ini`.

Achtung bei Sprachschluesseln: `tr()` ersetzt `{name}`, **nicht** `%(name)s`.

---

## 7. Die Punkte, die offen waren

**Alle sieben sind zu.** Der Abschnitt bleibt stehen, weil in mehreren Faellen
nicht der beschriebene Fehler der wirkliche war — das ist die nuetzlichere
Information als die Loesung. Zweimal reproduzierte sich die gemeldete Stoerung
gar nicht (die Ein-Spalten-Luecke in 7.1, die Ringe mitten in der Wand in 7.4),
und dahinter lag jeweils etwas anderes.

Offen ist nur noch, was sich nicht messen laesst: ob der mitlaufende Zielring
aus 7.6 sich beim Zeichnen gut anfuehlt. Die Stellschraube dafuer ist der
Umkreis 3 in `klippen_wand_punkt`.

### 7.1 Fortsetzungs-Ecke greift nur in einer Richtung — ERLEDIGT (30.07.2026)

Der Zweig `if alt is not None and (alt[0] == "v") != neu_senk:` wurde **nicht
betreten**, also lag es an `klippe_achse_an` — die zweite der beiden in der
Doku genannten Moeglichkeiten.

**Ursache.** Die Achsenfrage sah nur den *naechstliegenden* Block an und gab
auf, wenn der keine Achse hat. Am Ende eines waagerechten Laufs liegt dort das
Abschlussstueck (`sanmes08`/`mudmes08`, Wand nur nach West) — eine Wandseite,
keine Achse, Rueckgabe `None`. Senkrechte Laeufe haben gar kein
Abschlussstueck (siehe 4.), dort traf die Frage sofort einen Laufblock. Genau
daher die Einseitigkeit; mit der Ecke selbst hatte es nie etwas zu tun.

**Behoben** durch `klippen_treffer`: die Suche liefert alle Bloecke nach
Abstand, und `klippe_achse_an` geht weiter, bis einer die Frage beantworten
kann. Der zweitnaechste ist der Laufblock (`mudmes04`, Wand Ost+West) → `h`.

Gemessen, beide Familien, beide Reihenfolgen — `mudmes12` (Wand West+Nord)
sitzt jetzt bei (37,29). In der Suite steht das als
`<fam>/<achse>: Laufrichtung am Ende aus dem Modell` und
`<fam>/<achse>: Fortsetzung um die Ecke bekommt einen Eckblock`, jeweils
`v` **und** `h`.

**Die Luecke von einer Spalte gab es nicht (mehr).** Das Bild oben in der
alten Fassung dieser Doku ist veraltet; im heutigen Code reproduziert es sich
nicht. Nachgemessen ueber 144 Kombinationen (2 Familien x 2 Reihenfolgen x 4
Knickspalten x 3 Armlaengen x 3 Seeds): die Klippenzellen am Knick hingen
**immer** in einem Stueck zusammen, vor der Korrektur wie danach. Auch
eingeschlossene Bodenkacheln gibt es in keiner Variante — null.

Was tatsaechlich fehlte, war der Eckblock selbst: die beiden Laeufe
ueberlappten sich nur. Sichtbar aufgebrochen war die Ecke nie. Wer hier eine
Luecke sucht, sucht vergebens; die Korrektur ist eine der Bauart, nicht des
Anblicks.

**Achtung bei der Metrik.** Ein erster Zaehler nahm den Grundboden in einem
5x5-Kasten um den Knick und nannte den neuen Stand in 12 von 144 Faellen
schlechter. Das war der Zaehler, nicht der Code: ein Eckstueck laesst in einem
Quadrat immer Boden uebrig, und wo die Wand danach richtig auf der gezeichneten
Zeile sitzt statt vier Reihen darueber, steigt die Zahl sogar. Angesehen hat
den Fall erst das Bild.

### 7.2 Wandenden sehen abgeschnitten aus — ERLEDIGT (30.07.2026)

**Gemessen:** die waagerechten Abschluesse werden gesetzt, an beiden Enden,
in beiden Familien. Die offene Frage von vorher ist damit erledigt.

**Was daran wirklich stoerte,** war ein anderer Fall: nicht das Ende einer
Wand, sondern die *Naht* einer fortgesetzten. Dort standen zwei
Abschlussstuecke mitten in der Wand und ergaben einen hellen, flachen Fleck.
Das ist behoben (siehe 5., „Eine Naht ist kein Ende").

**Inzwischen gemessen — der Abschluss haengt am Laufblock, nicht an der
Richtung.** Gefragt wurde, was in den Originalen auf der Wandseite eines
Abschlussstueckes lag:

| Abschluss | gemessene Nachbarn auf der Wandseite |
|---|---|
| `mudmes05` (Wand Ost) | `mudmes07` 78x, `mudmes04` 28x, `mudmes03` 23x, `mudmes11` 22x … |
| `mudmes08` (Wand West) | `mudmes04` 45x, `mudmes15` 44x, `mudmes00` 37x, `mudmes06` 36x … |
| `sanmes08` (Wand West) | `sanmes09` 36x, `sanmes13` 10x, `sanmes04` 7x … |
| `sanmes12` (Wand Ost) | `sanmes11` 30x, `sanmes10` 19x, `sanmes04` 9x … |

**Ausnahmslos dreireihige Bloecke.** Die einreihigen Nordkanten
(`mudmes09/10`, `sanmes00/01/02`) stehen in keiner dieser Listen. Umgekehrt
gefragt sind deren gemessene Nachbarn nach Ost und West wiederum Laufbloecke,
die die Wand fortsetzen — **nie** ein Abschluss.

Also: an einer haarfeinen Nordkante endet die Wand in den Originalen ohne
Abschluss. Der 3x3-Klotz, der dort stand, war ein Fremdkoerper. Die Auswahl
fragt jetzt `klippen_belegt` gegen den Block, an den der Abschluss stoesst,
und setzt keinen, wenn die Zaehlung schweigt — dieselbe Ehrlichkeit wie bei
den senkrechten Waenden. Wo die Zaehlung ihn stuetzt, bleibt er (Gegenprobe in
der Suite: `<fam>: dicke Wand behaelt ihren Abschluss`).

Zusaetzlich haengt der Abschluss jetzt mit dem gemessenen Versatz am Lauf,
statt auf den Klickpunkt zentriert zu werden — genau wie die Ecke.

### 7.3 Der Ueberstand am Ende eines Laufs bleibt stehen — ERLEDIGT (30.07.2026)

**Belegt an der U-Figur** `[(6,2), (19,2), (19,14), (4,14)]`, mud: der
senkrechte Lauf setzte 5 Reihen hohe Bloecke bei y=2, 7, 12 — der letzte reichte
bis y=16, die Ecke deckte y=13..15. Die Reihe y=16 blieb als Stummel unter der
Ecke stehen. Dasselbe oben rechts eine Kachel nach Osten. In allen 6 gepruefte
Seeds, beide Stellen.

**Gemessen, Laufblock gegen Eckblock (in Laufrichtung):**

| | Laufblock | Eckbloecke |
|---|---|---|
| mud senkrecht | 3, 5 | 3, 6 |
| mud waagerecht | 3 | 3, 4 |
| san senkrecht | 4 | 3, 4 |
| san waagerecht | 3 | 3 |

Ein *langer genug* Eckblock existiert also durchaus — meine erste Notiz hier
(„die Ecke kann den Ueberstand gar nicht decken") war zu schnell. Gewaehlt wird
er aber nach Wandseiten, Hochseite und Gewicht, nicht nach Laenge, und er sitzt
am **Knickpunkt**, nicht am Ende des Ueberstands. Auf „die Ecke deckt es schon"
ist kein Verlass.

**Behoben** ueber das, was 5. ohnehin erlaubt: Ueberlappen. Der letzte Block
wird auf den gezeichneten Punkt zurueckgezogen und schiebt sich ueber seinen
Vorgaenger, statt ins Leere zu ragen. Eine Luecke entsteht nicht — genau die war
der Grund, den Lauf durchlaufen zu lassen. Ausnahme: ein Stueck, das kuerzer ist
als ein einziger Block, behaelt seinen Ueberstand, sonst laege der Block vor dem
Anfang.

**Der Preis, und er hat sofort zugebissen:** die Laeufe ueberlappen dadurch
haeufiger, und ein ueberlappter Block ist von der Mustersuche nicht mehr
auffindbar (siehe 5.). Am Nahtpunkt einer geraden Fortsetzung blieb daher nur
noch das Abschlussstueck uebrig, `klippe_wand_an` fand keine Achse, die Naht
wurde nicht erkannt — und der Fleck aus 7.2 war zurueck. Die Suite hat es
gefangen.

Gegenmittel: ein Abschlussstueck verraet die Achse sehr wohl. Wand allein nach
West heisst, die Wand laeuft ost-west und liegt westlich. `klippe_wand_an`
fragt das als **zweite** Quelle, erst nachdem kein durchgehender Block gefunden
wurde — so aendert sich nichts an den Stellen, wo einer da ist.

### 7.4 Ankerringe und zulaufende Linien — ERLEDIGT (30.07.2026)

**Mitten in der Wand sitzt kein Ring.** Nachgemessen auf sechs Originalkarten
(`cm01`–`cm04`, `eden01`, `eden02`): von 3 bis 51 gemeldeten Ringen je Karte
liegt **keiner** an einer Stelle, an der die Klippe in zwei gegenueberliegende
Richtungen weiterlaeuft. Die Sorge aus der alten Fassung dieser Doku
reproduziert sich nicht; die 3x3-Rasterung haelt.

**Was stattdessen falsch war: der behauptete Vorrang gab es nicht.** Im
Kommentar stand „deshalb haben beim Einrasten die gemerkten Vorrang" — gebaut
war es nicht so. Die Quellen wurden aneinandergehaengt und mit `min` nach
Abstand sortiert; die Reihenfolge half nichts. Gemessen an einer Wand mit Ende
bei (26,16): ein Klick auf (29,16) rastete auf den abgeleiteten Ring (28,16)
ein — zwei Kacheln **hinter** dem Wandende, und die Fortsetzung setzte am
falschen Block an. Jetzt gewinnt ein gemerktes Ende, sobald ueberhaupt eines in
Reichweite ist.

**Zulaufende Linien schliessen jetzt an.** Zwei Stellen:

- *Editor:* eingerastet wird an **jedem** Punkt, nicht nur am ersten. Schon
  gesetzte Punkte sind ausgenommen, sonst zoege ein kurzer zweiter Klick auf den
  ersten zurueck.
- *`klippe_aus_linie`:* auch der **letzte** Punkt fragt die vorhandene Klippe
  (`ende_wand`). Weicht deren Achse ab, ist er ein Knick und bekommt eine Ecke;
  liegt sie auf derselben Achse, ist er eine Naht und bekommt kein Wandende.
  Eine dort vorhandene Kappe wird verschluckt, indem der Lauf ueber sie hinaus
  verlaengert wird — spiegelbildlich zum Anfang.

Vorher stand an der Naht `mudmes08` bzw. `sanmes12` — ein Wandende genau dort,
wo die beiden Waende sich treffen. Jetzt `mudmes15` bzw. `sanmes09`, die
Suedwest-Ecke aus der Tabelle in „Wandseite ist nicht Hochseite".

### 7.5 T-Stoss mitten auf eine Wand — ERLEDIGT (30.07.2026)

**Erst gemessen, ob es so etwas ueberhaupt gibt** — zwei unabhaengige Wege,
beide mit demselben Ergebnis:

- *Bloecke mit drei Wandseiten:* `mud` hat **keinen einzigen**. `san` hat drei
  (`sanmes05`, `sanmes09`, `sanmes10`); sie kommen in zehn Karten 16 mal vor,
  davon **einmal** mit Klippe hinter allen drei Kanten.
- *Verzweigt sich die Linie?* Die Nordkantenzellen der Originalkarten
  (`cm01`–`cm04`, `eden01`–`eden04`) haben in **sechs von acht** Karten null
  Zellen mit drei oder mehr Nachbarn derselben Art; cm02 hat 14 von 401,
  eden03 eine von 116.

Das passt zur Sache: eine Klippe trennt hoch von tief, und eine Grenze
zwischen zwei Gebieten verzweigt sich nicht. **Es gibt kein T-Stueck, also wird
keines erfunden.**

**Was stattdessen falsch lief.** Ein T sah fuer den Code aus wie ein Knick —
beide sind „vorhandene Wand mit anderer Achse" — und bekam die
Eckenbehandlung. Der Eckblock schnitt sich quer durch die Wand, die er treffen
sollte: gemessen 9 gekippte Zellen bei san, 1 bis 2 bei mud, in jeder der drei
Klickvarianten.

**Unterschieden wird jetzt an der Frage, ob die Wand ueber den Nahtpunkt hinaus
auf beiden Seiten weiterlaeuft** (`durchgehende_wand`). Laeuft sie durch, ist es
ein T: kein Eckblock, kein Wandende, und die Bloecke der Querwand kommen nach
dem Zug wieder obenauf. Der Abzweig laeuft ausserdem bis an die nahe Kante der
Querwand — auch wenn zu kurz geklickt wurde, denn eingerastet wird nur an
Enden.

Gemessen wird ab dem **Nahtpunkt**, nicht ab dem gefundenen Block: der liegt am
Wandende oft noch mitten in der Wand, und dann meldete die Frage dort
faelschlich ein T — die Ecke aus 7.4 fiel damit weg. Die Suite hat es gefangen.

Ergebnis: 0 gekippte Zellen, keine Luecke, beide Familien, alle drei
Klickvarianten. Ohne die T-Erkennung fallen alle sechs durch.

### 7.6 Einrasten mitten auf einer Wand — ERLEDIGT (30.07.2026)

Die offene Frage war, ob ein Ring entlang der ganzen Wand mehr stoert als er
hilft. **Gemessen: ja, deutlich.** Ein Ring je 3x3-Feld mit Klippe waere

| Karte | Ringe heute | entlang der Wand |
|---|---|---|
| `cm01` 128x128 | 15 | 245 |
| `cm02` 256x256 | 34 | 804 |
| `cm03` 256x256 | 44 | 941 |
| `cm04` 256x256 | 51 | 1017 |
| `eden01` 64x64 | 6 | 88 |

Faktor 16 bis 24, und jeder Ring ist ein Element in der Szene, das bei jeder
Kartenaenderung neu gezeichnet wird. Die Karte verschwindet darunter.

**Gewaehlt wurde deshalb keins von beidem, sondern EIN Ring, der dem Zeiger
folgt** (`_klippen_zielring`, gestrichelt statt durchgezogen, damit er sich von
den dauerhaften Ringen der offenen Enden unterscheidet). Er erscheint nur dort,
wo wirklich eingerastet wird, und nicht auf einem offenen Ende — dort steht
schon ein eigener.

Die Reihenfolge in `klippen_anker` ist damit: gemerktes Ende, dann abgeleiteter
Ring, dann **die Wand selbst** (`klippen_wand_punkt`, Umkreis 3). Gefragt werden
die Zelltypen in einem kleinen Fenster, nicht das Kachelgitter — billig genug
fuer jede Mausbewegung. Die Vorrangregel aus 7.4 bleibt: nahe an einem Ende
gewinnt weiter das Ende.

### 7.7 Mehrere Hoehenstufen — ERLEDIGT (30.07.2026)

**Es gibt keine Ebenen.** Vom Nutzer festgestellt; Outpost 2 kennt genau eine
Stufe, hoch gegen tief. Damit ist die Frage keine Messfrage, und es gibt nichts
zu bauen.

Nachgesehen, ob der Code das schon so haelt: ja, ausnahmslos. `hoehe` bekommt
nur 0 oder 1 zugewiesen (`paint_layers.py`: `_hoehe_aus_klippe`, der Pinsel,
die Radierer), der Generator setzt `H` ebenso, und gelesen wird ueberall
`H > 0`. Kein Vergleich im ganzen Baum erwartet einen groesseren Wert. Der
Kommentar in `paint_layers.py` („hoehe 0 = Tiefland, 1 = Hochland") beschreibt
also keine Vereinfachung, sondern die Sache selbst.

---

## 8. Das Saeulenmodell (`cliff_columns_model.npz`) — im Bau

Ein zweiter, unabhaengiger Ansatz neben dem Gruppenmodell aus 2.: nicht die
Kachel und nicht der Block ist die Einheit, sondern das **senkrechte Band** —
der Querschnitt einer Wand. Gezaehlt wird, welches Band rechts neben welchem
steht und mit welchem senkrechten Versatz. **Dieser Versatz ist die Neigung.**
Eine Schraege entsteht also nicht aus einer gewuerfelten Stufenfolge
(`klippe_treppe`), sondern daraus, dass man Baender aneinanderreiht, die
zueinander passen.

`mapview/learn_cliff_columns.py` misst, `mapview/cliff_columns.py` fragt.
Der Modulkopf des Trainers traegt alle Zahlen.

### Drei Messfehler auf dem Weg, jeder mit demselben Muster

Alle drei sahen wie ein Befund ueber die Karten aus und waren einer ueber die
Auswahl.

**±4 war die andere Wand.** Mit `VERSATZ_GRENZE = 4` zaehlte die Messung 216
Uebergaenge mit Versatz ±4 und wies sie als zweithaeufigsten Wert aus. Zwei drei
Kacheln hohe Baender im Abstand 4 ueberlappen sich aber nicht — dazwischen liegt
Boden. Es waren die beiden parallel laufenden Waende derselben Karte. Beim
Setzen zerfiel die Kette genau dort in unverbundene Stuecke. Das Anzeichen stand
schon in der Verteilung: ±2 und ±3 kamen fast nicht vor, ±4 stand als Spitze da.

**„Band genau 3 hoch" misst nur waagerechte Waende.** Ein senkrechter Schnitt
durch eine schraege Wand ist laenger als durch eine waagerechte. Nur 27 % aller
Baender sind genau 3 hoch, und deren Nachbarn haben zu 94,8 % Versatz null —
das las sich wie „Klippen laufen fast immer waagerecht" und hiess in Wahrheit
„ich habe nur die waagerechten genommen". Trifft ein Dreierband auf ein
Viererband, ist der Versatz zu **70,1 %** ungleich null: dort sitzen die Stufen.

**Ein Ausschnitt aus einem hohen Band ist keine Wand.** Der naechste Versuch nahm
je Band ein oberes und ein unteres randbuendiges Dreierfenster. Die Statistik sah
gut aus (54,8 % Versatz ungleich null, saettigt genauso), das Rendering war
Schutt. Grund: das obere Fenster eines 7 Kacheln hohen Bandes hat unten eine
*Mittel*kachel — allein hingestellt steht darunter Boden statt Fels.

### Wo die Grenze liegt und warum

Sehr hohe Baender sind ueberhaupt keine Querschnitte: eine Spalte, die 11
Klippenkacheln durchlaeuft, folgt einer Nord-Sued-Wand der **Laenge** nach.
Gemessen ueber alle 54 Stockkarten, ganze Baender als Einheit:

| Bandhoehe | Baender | je Band | einmalig | Versatz ≠ 0 | Wachstum 20→54 |
|-----------|---------|---------|----------|-------------|----------------|
| 3         | 788     | 11,77   | 46,3 %   | 5,1 %       | ×2,10          |
| **3–4**   | **1297**| **10,07**| **49,6 %**| **23,6 %** | **×2,16**      |
| 3–5       | 1756    | 9,21    | 51,2 %   | 30,3 %      | ×2,19          |
| 3–8       | 2951    | 6,78    | 56,0 %   | 37,4 %      | ×2,36          |

Ab 5 steigt der Anteil der Baender, die in 54 Karten genau einmal vorkommen,
und die Belege je Band fallen — das waere Auswendiglernen statt einer Regel.
Das **ganze** Band als Einheit ohne Hoehengrenze ist erst recht nichts: 4309
Baender, 57 % davon einmalig, Median 1 Nachfolger.

Bei 3–4 sind die Versaetze fast nur ±1 — eine Treppe aus einzelnen Stufen:

    -2  0,9 %     -1  14,2 %     0  76,4 %     +1  7,7 %     +2  0,4 %

### Das Band weiss, wohin die Wand laeuft

Ueber echte Dreierfolgen a → b → c gemessen, Ungewissheit ueber den naechsten
Versatz:

| bekannt              | Bit   | davon weg |
|----------------------|-------|-----------|
| nichts               | 2,047 | —         |
| der vorige Versatz   | 1,949 | 4,8 %     |
| **das Band**         | **0,727** | **64,5 %** |

Eine Wand ist also **nicht** einfach autokorreliert — nach −2 ist der haeufigste
naechste Wert 0 oder +1. Ein Setzer braucht deshalb kein Gedaechtnis fuer die
Neigung; er muss nur das Band kennen.

### Stand (31.07.2026)

Getestet bisher nur fuer **mud**: 1084 Baender, 299 im Kern (90 %).
300 Ketten gesetzt, ganze Baender gelegt, **keine Loecher**. Sanfte Neigungen
(|n| ≲ 0,4) sehen wie Originalwaende aus, auch ueber 32 Spalten. Offen:

- Ketten sterben frueh — Laenge Median 5, Mittel 9,7, nur 50 von 300 laufen
  ueber die volle Breite. Ursache sind Baender ohne Nachfolger derselben
  Familie.
- Der Setzer nutzt Versatz 0 zu oft (84,2 % statt 76,4 %) — der Kernfilter
  bevorzugt die haeufigen, flachen Baender.
- Steile Ketten (|n| > 0,8) zerfallen in Klumpen: bei ±2 und ±3 beruehren sich
  zwei Baender nur noch in einer Zeile.
- Fuer **san** ungetestet (114 Baender im alten Zaehlstand), keine Pruefungen in
  den Suiten, nichts davon haengt am Editor.

## 9. Die Nachbarschaftstabelle (`cliff_tiles_model.npz`) — im Bau

Keine Gruppen, keine Baender, keine Statistik ueber Formen: die rohe Liste.
Fuer **jede** Klippenkachel und **jede** der vier Richtungen ist ausgezaehlt,
welche Kachel dort in den Originalkarten tatsaechlich steht.

    an Kachel 88 darf nach Osten die 89 (94 %), die 122 (1 %), +18 seltene
                     nach Sueden die 90 (64 %), die 187 (26 %), +10 seltene
                     und oestlich lag NIE Gelaende, suedlich zu 24 %

`mapview/learn_cliff_tiles.py` zaehlt aus, `mapview/cliff_tiles.py` fragt.

### Der Vorrat ist klein und die Liste ist satt

Ueber alle 54 Stockkarten kommen genau **307** verschiedene Kacheln als Klippe
vor, bei 121603 Vorkommen. Das laesst sich vollstaendig auszaehlen — und es ist
ausgezaehlt: von 20 auf 54 Karten waechst die Paarliste nur um den Faktor 1,60,
und die letzten **vier** Karten brachten noch **68 neue Paare von 11934** (0,6 %).

Scharf ist sie auch. Erlaubte Klippennachbarn je Kachel und Richtung:

| Richtung | Median | fuer 95 % der Faelle | nie eine Klippe | nie Gelaende |
|----------|--------|----------------------|-----------------|--------------|
| N        | 7      | 4                    | 27              | 186          |
| O        | 9      | 5                    | 20              | 148          |
| S        | 8      | 4                    | 37              | 62           |
| W        | 9      | 5                    | 23              | 160          |

### Gelaende ist eine Aussage, keine Luecke

Zaehlt man Bodenkacheln als Nachbarn mit, sieht dieselbe Tabelle unscharf aus
(Median 11 bis 16). Das ist kein Widerspruch: wo eine Klippe an offenes Gelaende
grenzt, darf dort jede Bodenkachel stehen. Klippennachbar und „Boden erlaubt"
sind zwei verschiedene Fragen und werden getrennt gefuehrt.

Aber „hier liegt Gelaende" ist selbst eine **harte Bedingung** — 186 der 307
Kacheln haben nach Norden nie Boden. Das war der teuerste Fehler in diesem
Abschnitt: der erste Nachbau liess die Bodenrichtungen einfach weg, weil dort
keine Klippe stand, und traf **0 von 216** Kacheln. Mit `BODEN` als Eintrag
statt als Auslassung wurde daraus 6,6 bis 29 %, und aus Schutt wurden
wiedererkennbare Waende.

### Umkreis 1 oder 2? Gemessen auf ungesehenen Karten

Tabelle aus 40 Karten, geprueft auf den 14 uebrigen (32237 Klippenzellen):

| | nur 4 Nachbarn | 8, alle hart | **4 hart + 4 Gewicht** |
|---|---|---|---|
| Kandidaten (Median) | 5 | 3 | 5 |
| richtige auf Platz 1 | 87,0 % | 90,6 % | **88,8 %** |
| richtige unter den ersten 3 | 97,3 % | 98,5 % | **97,8 %** |
| Widerspruch, gar nichts passt | 0,70 % | 2,37 % | **0,70 %** |

Von 32237 Kacheln waren nur **4** im Training unbekannt (0,01 %).

Die Diagonalen schaerfen also, verbauen sich hart gerechnet aber dreimal so oft
selbst — und vor einer Zelle zu stehen, in die nichts passt, kostet mehr als ein
zweitbester Treffer. Als Gewicht bringen sie die Haelfte des Gewinns umsonst.
Das ist noch einmal dieselbe Regel wie in 10.: **Vorlieben gehoeren in Gewichte,
nicht in Filter.**

### Stand (31.07.2026)

Modell gebaut und geprueft, haengt an nichts. Der Nachbau ganzer Ausschnitte
laeuft; lange Diagonalen kommen gut heraus, **waagerechte Laeufe zerfallen noch
in Stuecke**. Der strenge Massstab „identische Kachel" untertreibt dabei stark —
`mp4_04` trifft 29 % und sieht aus wie das Original.

Offen: die Zerfallsstellen, Zelltypen werden noch nicht mitgesetzt (54 Kacheln
kommen mit mehr als einem Typ vor), keine Pruefungen in den Suiten.

## 10. Eigene Gruppen (`cliff_patches_model.npz`) und der Setzer in zwei Durchgaengen

Die 35 mitgelieferten `*mes*`-TileGroups kennen den **diagonalen Lauf** nicht —
ein schraeg durchlaufendes Wandstueck mit seinen Uebergaengen gibt es dort als
Ganzes nicht. In den Karten gibt es ihn sehr wohl: als 6x4-Block kommt so ein
Lauf bis zu **272 mal** vor. Also holt man sich die Gruppen aus den Karten statt
aus dem Kachelsatz.

`mapview/learn_cliff_patches.py` schuerft, `mapview/cliff_patches.py` fragt.
Jedes NxM-Fenster ueber einer Klippe ist ein Kandidat, der Boden ist WILDCARD.

### Warum mehrere Groessen

Streng gemessen — ueberlappungsfrei gekachelt, nur Gruppen ab 10 Vorkommen:

| Groesse | Gruppen ab 10x | deckt streng | davon gebraucht |
|---------|----------------|--------------|-----------------|
| 2x2     | 2187           | 71,0 %       | 1164            |
| 3x3     | 3542           | 49,5 %       | 1343            |
| 4x3     | 4015           | 43,0 %       | 1411            |
| 6x4     | 4348           | 27,8 %       | 1098            |
| 6x6     | 4210           | 20,4 %       | 947             |

Grosse Gruppen tragen den Lauf, decken aber wenig; kleine decken viel, tragen
aber keine Richtung. Geschuerft werden 6x4, 4x6, 4x3, 3x4, 3x3 und 2x2 —
zusammen **23038 Gruppen**, davon 17643 mud und 5395 san. **Keine einzige
Gruppe mischt Familien**, ueber alle Groessen hinweg.

Hoch UND breit ist noetig: eine Nord-Sued-Wand braucht ein hohes Fenster, eine
Ost-West-Wand ein breites.

### Die Form ist die Bedingung, die Kacheln kommen mit

Eine Gruppe darf nur dort liegen, wo genau die Zellen Klippe sind, die in ihr
Klippe sind. Darum sind die Gruppen nach ihrer Form abgelegt und nicht nach
ihren Kacheln — gesucht wird immer mit einer Form in der Hand.

### Der Setzer

**Durchgang 1, Gruppen.** Von der groessten Groesse abwaerts wird jede Stelle
geprueft, deren Form eine bekannte Gruppe hat. Gelegt wird eine haeufige Gruppe,
die den schon gesetzten Kacheln nicht widerspricht.

**Durchgang 2, Tabelle.** Was keine Gruppe abgedeckt hat, faellt an
`cliff_tiles.py`: vier Nachbarn hart, Diagonalen als Gewicht, Gelaende als
Aussage.

Probe — alle Klippenkacheln eines Ausschnitts geloescht, nur die Form blieb
stehen, dann neu gesetzt:

| Karte | nur Tabelle | Gruppen + Tabelle | von Gruppen gedeckt | Notloesungen |
|-------|-------------|-------------------|---------------------|--------------|
| eden09 | 15,7 % | **40,7 %** | 99 % | 12 → **0** |
| cm01   |  4,6 % | **23,9 %** | 98 % | 18 → **3** |
| mp4_04 | 22,6 % | **25,8 %** | 100 % |  1 → **0** |

Der Massstab „identische Kachel" untertreibt stark; im Bild ist der Nachbau vom
Original kaum zu unterscheiden, waehrend die Tabelle allein die Laeufe zerreisst.

### Zwei Fehler, beide vom selben Typ: Boden ist kein leeres Feld

**Die Vertraeglichkeitspruefung.** Beim Pruefen, ob eine Gruppe den schon
gesetzten Kacheln widerspricht, zaehlten die BODENzellen des Fensters als
„gesetzt" — sie tragen ja noch ihre alte Kachel. Verglichen wurden sie gegen die
Wildcard der Gruppe, und die passt dort nie. Der Trefferwert fiel von 13,9 auf
4,2 %. Richtig ist, nur die Klippenzellen zu binden.

**Die Familie steht im Gelaende.** Ohne Familienbedingung legte der Setzer
san- und Lavagruppen in eine mud-Karte: die Form passte, die Familie nicht.
Die Familie muss aus dem umliegenden GELAENDE gelesen werden — das bleibt beim
Malen ja stehen. Mit dieser einen Bedingung stieg eden09 von 31,5 auf 40,7 %.

### Eine Kachel weiss nicht, ob sie zum Berg oder zum Abhang zeigt

`CLIFFS_HIGH_SIDE` sitzt auf der Hochseite der Wand, `CLIFFS_LOW_SIDE` auf der
Tiefseite. Ob eine Kachel das eine oder das andere ist, steht **nicht in der
Kachel**:

| | |
|---|---|
| Kacheln mit genau einem Zelltyp | 118 von 307 (59 Tief, 39 Hoch, 20 Nord) |
| Kacheln, die Hoch UND Tief sind | **171** |
| Vorkommen auf solchen Kacheln | **73,9 %** |
| Zellen, deren Kachel den Typ festlegt | **20,2 %** |
| Zellen, die Kachel + vier Nachbarn festlegen | 90,6 % |

Auf 14 ungesehenen Karten den Zelltyp raten:

| Weg | richtig |
|-----|---------|
| `celltypes.default_cell_type` (heute im Projekt) | 94,1 % |
| haeufigster Typ je Kachel | 94,5 % |
| **je Kachel + vier Nachbarn** | **98,6 %** |

Die Fehler sind Hoch → Tief (2,8 %) und Tief → Hoch (1,1 %) — die Wand zeigt zur
falschen Seite.

**Die Bergseite ist eine Eingabe, keine Folge der Form.** Die Zelltypen in den
Gruppen mitzufuehren allein half nichts (68,8 % gegen 69,3 % aus der Kachel):
dieselbe Kontur gibt es mit dem Hochland oben und mit dem Hochland unten, und
wer nur die Form vorgibt, waehlt die Seite blind. Gibt man sie mit vor:

| Setzer bekommt | Kachel identisch | Zelltyp richtig | Hoch↔Tief | von Gruppen |
|----------------|------------------|-----------------|-----------|-------------|
| nur die Form   | 32,5 % | 68,8 % | **16,8 %** | 99 % |
| Form + Bergseite | **40,6 %** | **99,0 %** | **0,7 %** | 98 % |

Die zusaetzliche Bedingung kostet fast keine Deckung (99 → 98 %) und raeumt die
vertauschten Waende ab. Der Klippenpinsel muss die Hochseite also mitliefern —
`klippen_hochseite` und die `hoehe`-Ebene in `PaintLayers` gibt es dafuer schon.

### Eingebaut ist die Hochseite, nicht der Kachelersatz

`klippe_zelltypen(maske, punkte, hand)` leitet die Zelltypen aus der Hochseite
ab, die der Pinsel ohnehin kennt, und `klippe_aus_linie` benutzt es am Ende
statt `celltypes.default_cell_type`. Die gemessene Regel:

    Laenge 1   N     94 %        Laenge 4   HHLL  45 %
    Laenge 2   HL    52 %        Laenge 5   HHHLL 26 %
    Laenge 3   HLL   82 %

Es sind also nicht "eine Hochzelle, Rest tief", sondern immer ZWEI Tiefzellen am
unteren Ende — bei Dicke 2 nur eine. Geprueft in `mapgen_test` als „Zelltyp
folgt der Hochseite"; auf dem Stand davor ist die Pruefung rot (3 Spalten je
Familie falsch).

**Der Kachelersatz aus den Gruppen (`klippe_feinsetzen`) ist gebaut, aber
ausgeschaltet.** Er wirft 20 Pruefungen aus Abschnitt 7 um, und zwar aus einem
strukturellen Grund: die Fortsetzung eines Zuges sucht die gesetzten BLOECKE im
Gitter wieder — daran haengen Flucht, Eckwahl, Wandende und T-Stoss. Werden die
Kacheln durch Gruppenkacheln ersetzt, ist kein Block mehr auffindbar. Die
Messung dazu:

| | Prueflauf |
|---|---|
| nur Zelltypen aus der Hochseite | alle gruen |
| zusaetzlich Kacheln aus Gruppen | 20 rot (Fortsetzung, Ecke, Wandende, T-Stoss) |

Der Umbau wurde begonnen und dann **abgeblasen**, weil die Messung die Annahme
umgeworfen hat, auf der er stand.

Die Messung, die zum Gruppenmodell fuehrte, verglich zwei Verfahren, die VON
NULL bauen: Nachbarschaftstabelle gegen Gruppen. Der Pinsel baut aber drittens —
er legt ganze ORIGINALBLOECKE, und die sind von Haus aus zusammenhaengend. Am
Pinselergebnis selbst gemessen, Anteil der Kachelpaare, die in **keiner** der 54
Originalkarten vorkommen:

| Zug | Bloecke | + Gruppen |
|-----|---------|-----------|
| senkrecht (mud/san) | **0,00 % / 0,00 %** | 12,8 % / 15,8 % |
| waagerecht | 2,3 % / 3,4 % | 1,5 % / 11,1 % |
| Ecke | 1,5 % / 1,2 % | 7,3 % / 12,1 % |
| **Schraege** | **32,2 % / 31,4 %** | 32,2 % / 41,8 % |
| **Zickzack** | **32,5 % / 37,4 %** | 26,9 % / 45,1 % |

Auf geraden Zuegen und Ecken ist der Blockweg praktisch fehlerfrei, und das
Feinsetzen macht ihn schlechter. Zwanzig gruene Pruefungen dafuer aufzugeben
waere ein schlechtes Geschaeft.

Ein Fehler von mir steckte auch darin und ist behoben: die Vertraeglichkeit
einer Gruppe wurde nur INNERHALB ihres Fensters geprueft, die Naht zum Nachbarn
sah niemand. Beim senkrechten Zug waren das 22 % unbekannte Paare; mit
Nahtpruefung 12,8 %. Immer noch schlechter als 0,00 %.

**Wo der echte Fehler sitzt.** Auf der Schraegen und im Zickzack liegen in
BEIDEN Verfahren 27 bis 45 % der Kachelpaare so nebeneinander, wie es in keiner
Originalkarte vorkommt. Das ist keine Frage der Kachelwahl, sondern der
Treppenkonstruktion. Dort lohnt die Arbeit, nicht am Kachelersatz.

`kacheln_feinsetzen` bleibt darum auf `False` — gebaut, gemessen, nicht benutzt.

**Nachtrag (01.08.2026): auf der Schraegen hat sich das gedreht.** Nach der
Treppenumstellung, den festen Mustern und der Hochkanten-Ausrichtung neu
gemessen:

| Zug | mud Bloecke | mud + Gruppen | san Bloecke | san + Gruppen |
|-----|-------------|---------------|-------------|---------------|
| waagerecht | 2,3 % | 1,5 % | 3,4 % | 11,1 % |
| senkrecht | **0,0 %** | 12,8 % | **0,0 %** | 17,5 % |
| Ecke | 1,6 % | 7,0 % | 1,3 % | 12,2 % |
| Schraege | 26,1 % | **15,3 %** | 28,4 % | 46,9 % |
| Zickzack | 28,3 % | **12,3 %** | 30,7 % | 44,4 % |

Bei **mud** halbieren die Gruppen den Fehler auf der Schraegen, bei **san**
verdoppeln sie ihn. Die naheliegende Erklaerung ist es nicht: die Deckung durch
Gruppen ist mit 91 % (mud) gegen 88 % (san) praktisch gleich. Auch die
Zelltypbedingung erklaert es nicht allein -- sie kostet BEIDE Familien rund 25
Punkte Anwendbarkeit (mud 82,9 → 57,5 %, san 73,3 → 49,7 %), ist also teuer,
aber nicht der Unterschied.

Der san-Rueckschritt ist damit ungeklaert, und solange er das ist, wird nichts
umgeschaltet. Die Zelltypbedingung als GEWICHT statt als Filter waere der
naechste Griff -- dieselbe Regel wie schon dreimal.

### Womit geprueft wird, und was das Mass wert ist

Die Pruefung „gehoert das nebeneinander?" ist eine einzige Frage an die
gezaehlte Tabelle: **stand b in dieser Richtung je neben a?** Anzahl > 0 heisst
erlaubt. Kein Pixelvergleich, kein Kantenabgleich — nur ein Beleg aus den 54
Karten. Das Mass kann also sagen „so hat es nie jemand gebaut", niemals „das ist
falsch".

Damit die Prozentzahlen ueberhaupt lesbar sind, muss das Mass geeicht sein:

| | |
|---|---|
| moegliche gerade Paare (307 Kacheln x 4 Richtungen) | 376996 |
| davon je belegt | 11934 — **3,17 %** |
| davon genau einmal belegt | 3248 (27 %) |

Unbekannt ist also der Normalfall: 97 % aller denkbaren Paare kommen nie vor.
Die Latte ist deshalb nicht 0 %, sondern das, was eine ECHTE Karte erreicht.
Jede der 51 Klippenkarten gegen die Tabelle aus den uebrigen geprueft:

| | unbekannte Paare |
|---|---|
| Median | **1,01 %** |
| Mittel | 1,24 % |
| schlechteste (`ply05`) | 5,17 % |
| Karten ueber 5 % | 1 von 51 |

Eine echte Karte liegt also bei rund einem Prozent. Damit sind die Werte des
Pinsels einzuordnen: gerade Zuege und Ecken (0 bis 3,4 %) liegen im natuerlichen
Bereich, die Schraege mit 28 % liegt beim **25fachen**, und das Feinsetzen mit
12 bis 47 % ist erst recht daneben.

Das zweite, unabhaengige Mass ist die Wiederholungsrate (0,85 % gerade, 1,31 %
ueber Eck): sie faengt einen anderen Fehler, das sichtbare Kacheln.

### Die Treppe: Mittelwert und Streuung legen keine Verteilung fest

`_stufenfolge` erzeugte die Trittfolge aus dem Mittel und der gemessenen
Streuung 1,31. Das lieferte **17 % Schritte <= 0** (224 Nullen und 93 negative
von 1860). Ein Tritt der Laenge 0 ist kein Tritt, sondern zwei Absaetze
uebereinander — die Wand faellt in EINER Spalte um zwei Zeilen, was das
Saeulenmodell mit 0,9 % ausweist. Ein negativer Schritt ist eine Wand, die
zurueckspringt. **79 % der unbekannten Kachelpaare sassen an genau diesen
Stellen.**

Eine Untergrenze allein machte es nicht besser, sondern anders schlecht: die
geforderte Streuung war dann nur noch ueber Extreme zu erreichen (914 Einsen und
720 Vieren von 2340), und ueber Eck stand **20 %** lang dieselbe Kachel statt
der gemessenen 1,31 %.

Also die Verteilung selbst messen. 206 Schraegen aus den 54 Karten, 974 Tritte:

| Trittlaenge | 1 | 2 | 3 | 4 | 5 | | Sprunghoehe | 1 | 2 | 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| gemessen | 41,1 % | 23,4 % | 12,1 % | 7,8 % | 6,1 % | | gemessen | 75,5 % | 24,5 % | **nie** |

Die Trittlaengen sind fast genau geometrisch (q = 1 − 1/2,62 sagt
38,2 / 23,6 / 14,6 / 9,0 / 5,6 %), und nur **1 von 206** Schraegen hat
gleichmaessige Tritte. Der Sprung ist zu einem Viertel ZWEI Zeilen — der alte
Erzeuger kannte nur eine.

`_tritte` und `_spruenge` erzeugen jetzt daraus. Wirkung auf dem Blockweg:

| | vorher | nachher |
|---|--------|---------|
| unbekannte Paare, Schraege | 32,2 % | **28,1 %** |
| unbekannte Paare, Zickzack | 32,5 % | **27,6 %** |
| gleiche Kachel ueber Eck | 19,8 % | **5,0 %** |

### Die Naht gewichten: gebaut, gemessen, wieder entfernt

Der naheliegende Schritt nach der Treppe war, die Blockwahl an der Stufe nach
Nahtbelegen zu gewichten — der Blockvorrat bliebe unangetastet, die 20
Pruefungen aus Abschnitt 7 also gruen. Gebaut, und der Faktor gemessen wie
ueblich:

| Faktor | Schraege, unbekannte Paare | Zickzack |
|--------|---------------------------|----------|
| 0      | 26,81 % | 31,07 % |
| 2      | 26,81 % | 31,07 % |
| 8      | 26,81 % | 31,07 % |
| 30     | 26,81 % | 31,07 % |
| 200    | 26,81 % | 31,07 % |

**Kein einziges Ergebnis aendert sich.** Der Grund steht im Vorrat:

| | |
|---|---|
| Bloecke je Familie insgesamt | mud **18**, san **17** |
| Bloecke je Laufrichtung | **1 bis 3** |
| Blockpaare mit mehr als einem gezaehlten Versatz | 38 von 482 (**8 %**) |

`waehle` hat meist genau einen Kandidaten, und der Versatz ist in 92 % der
Faelle ebenfalls festgelegt. **Die Wand, die der Blockweg baut, ist bestimmt** —
es gibt nichts zu steuern. Der Code wurde wieder entfernt; die Messung steht
hier.

Damit ist die Lage klar: die 28 % auf der Schraegen sind nicht durch bessere
Wahl INNERHALB des Blockvorrats zu beheben, weil es keine Wahl gibt. Es braucht
einen groesseren Kachelvorrat — also die geschuerften Gruppen — und die
vertragen sich nicht mit der blocksuchenden Fortsetzung.

### Feste Treppenmuster je Winkel

Bei 18 Bloecken je Familie ist die Abwechslung, die ein Zufallsgenerator
hineinbringt, keine -- sondern Streuung um einen festen Vorrat. Gemessen, wieviel
Zufall ueberhaupt noch wirkt (40 Seeds, dieselbe Linie):

| Zug | verschiedene Kachelbilder | Spanne der Qualitaet |
|-----|---------------------------|----------------------|
| senkrecht | **1** | — |
| waagerecht | 39 | 0,4 Punkte |
| Ecke | 35 | 0,4 Punkte |
| Schraege | 40 | **11 bis 13 Punkte** |
| Schraege, Treppe fest | 40 | **1 bis 3 Punkte** |

Bei geraden Zuegen ist die Blockwahl gleichgueltig, und der senkrechte Zug ist
ohnehin festgelegt (ein Laufblock). Auf der Schraegen kommt die ganze Streuung
aus der TREPPE, nicht aus der Kachelwahl.

Also je Winkel einmal die beste Treppe suchen (400 Zufallstreppen, gewertet auf
beiden Familien zugleich) und fest hinterlegen. Die Muster kommen fuer mud und
san **gleich** heraus — die gute Treppe haengt an der Geometrie, nicht am
Kachelsatz. Am fertigen Pinsel gemessen, 12 Seeds, beide Familien:

| Winkel | Grad | gewuerfelt | festes Muster | gewonnen |
|--------|------|------------|---------------|----------|
| 4:1 | 14,0° | 10,1 % | **7,3 %** | 2,8 |
| 3:1 | 18,4° | 13,5 % | **10,0 %** | 3,5 |
| 2:1 | 26,6° | 19,1 % | **13,2 %** | 5,9 |
| 1:1 | 45,0° | 30,5 % | **26,4 %** | 4,1 |
| 1:2 | 63,4° | 27,3 % | 28,1 % | −0,8 |
| 1:3 | 71,6° | 22,6 % | 22,1 % | 0,5 |
| 1:4 | 76,0° | 19,8 % | 19,0 % | 0,8 |

Der Gewinn liegt bei den FLACHEN Winkeln. Steile bringen nichts, und auch das
passt zum Vorrat: senkrechte Waende haben nur einen Laufblock, dort ist die Wand
festgelegt.

**Ein Fehler dabei, der 5 Punkte kostete:** blieb nach dem letzten ganzen
Musterdurchlauf ein Rest, habe ich ihn dem Endpunkt ueberlassen. Damit haengt an
der Treppe eine UNZERLEGTE Schraege, und genau die laesst `klippe_aus_linie` auf
eine Achse fallen — die andere Komponente verschwindet ersatzlos. Bei 26,6°
waren das 16,2 % statt 13,2 %. Der Rest wird jetzt selbst zerlegt.

Der Preis ist Gleichfoermigkeit: jede Schraege desselben Winkels sieht gleich
aus. Bei diesem Vorrat ist das ehrlicher als Zufall, der nur zwischen schlechten
Varianten waehlt.

### Die Kante entlanglaufen — der aussichtsreichste Ansatz

Der Hinweis kam vom Nutzer, mit einer Stelle: **cm04 bei (167,175)**. Dort
zeigt die Klippe ein Gebirge, und entlang der Oberkante wiederholt sich eine
Kachelfolge:

    x=163  94    x=170  94    x=177  94
    x=164  95    x=171  95    x=178  95
    x=165  94    x=172  94    x=179  94
    x=166  95    x=173  95    x=180  95
    x=167 160    x=174 160    x=181 160
    x=168 161    x=175 161
    x=169 162    x=176 162

`94, 95` ist der Schritt, `160, 161, 162` das flache Stueck.

**Der Winkel allein reicht nicht, die FOLGE schon.** Gemessen ueber 712
Kantenlaeufe aus allen 54 Karten (6162 Zellen, 195 verschiedene Kantenkacheln):

| bekannt | Kachel auf Platz 1 | erste zwei | eindeutig |
|---------|--------------------|------------|-----------|
| nichts | 6,3 % | 11,9 % | 0 % |
| nur der Sprung (Winkel) | 10,9 % | 18,8 % | 0 % |
| Trittlaenge + Stelle + Sprung | 25,9 % | — | 21 % |
| **vorige Kachel** | **58,4 %** | 71,5 % | 44 % |
| vorige Kachel + deren Sprung | 65,4 % | 79,0 % | 49 % |
| vorige Kachel + beide Spruenge | 69,2 % | 82,5 % | 59 % |
| **zwei vorige Kacheln + Sprung** | **72,9 %** | 85,9 % | **72 %** |

Die Geometrie allein ist also schwach (25,9 %), die Folge stark (72,9 %), und
in **72 %** der Faelle steht die Kachel sogar fest -- dort kam ueber alle 54
Karten nie eine andere vor. Das deckt sich mit der zweiten Haelfte des
Hinweises: was uebrig bleibt, sind die "vollen" Kacheln, die austauschbar sind.

Damit ist ein Weg gefunden, der weder am Blockvorrat (18 Stueck) noch an der
Belegdichte der Paartabelle (3,17 %) haengt: die Wand wird ENTLANG ihrer Kante
erzeugt, nicht aus Bloecken zusammengesetzt.

### Nicht ersetzen, sondern reparieren

Die Gruppen ANSTELLE der Bloecke zu setzen macht alles schlechter -- gemessen
ueber alle sechs Faelle:

| Zug | mud Bloecke | mud Gruppen | san Bloecke | san Gruppen |
|-----|-------------|-------------|-------------|-------------|
| waagerecht | 2 % | 5 % | 3 % | 15 % |
| **senkrecht** | **0 %** | 11 % | **0 %** | 12 % |
| schraeg | 13 % | 22 % | 13 % | 37 % |

Wo der Blockweg 0 % erreicht, kann kein Ersatz gewinnen: der senkrechte Lauf hat
genau einen Block, der lueckenlos an sich selbst anschliesst.

Gebraucht werden die Gruppen dort, wo die Bloecke NICHTS haben -- an den Stufen.
`klippe_naehte_bessern` ersetzt darum nichts, sondern gibt nur die Zellen frei,
die an einem unbelegten Kachelpaar haengen, und setzt sie aus Gruppen und
Tabelle neu; der Rest bleibt stehen und bindet als Bedingung. Eine Runde, die
nichts bringt, wird verworfen.

**Der Preis, die Bloecke auffindbar zu halten, ist genau beziffert.** Jede
angefasste Zelle macht den Block, in dem sie liegt, fuer die Fortsetzung
unsichtbar:

| Reparatur | mud schraeg | Pruefungen |
|-----------|-------------|------------|
| uneingeschraenkt | **9 %** | 3 rot |
| nur an Stufen | 9 % | 1 rot |
| nur an Stufen, Ecken ausgenommen | 12 % | **alle gruen** |
| gar nicht | 13 % | alle gruen |

Drei Prozentpunkte kostet es, Abschnitt 7 heil zu lassen. `naehte_bessern`
steht auf `True`, weil es nur bessern kann -- bei san aendert es nichts, weil
dort jede Runde verworfen wird.

### Kacheln zu Klassen buendeln: gemessen, verschlechtert die Pruefung

Nur 3,17 % der moeglichen Paare sind belegt. Die Idee: Kacheln, die sich gleich
verhalten, in Klassen buendeln und auf Klassenebene pruefen -- aus einem Beleg
werden dann viele.

Der Haken liegt auf der Hand, und deshalb braucht es ZWEI Masse: steckt man
alles in eine Klasse, ist nichts mehr unbekannt und die Pruefung wertlos. Also
gemessen, wieviel echte Karten sie annimmt UND wieviel Unsinn sie durchlaesst.
Tabelle aus 40 Karten, geprueft auf 11 ungesehenen (66068 Paare) gegen 40000
gewuerfelte Paare:

| Schwelle | Klassen | Probe unbekannt | Zufall angenommen | Trennschaerfe |
|----------|---------|-----------------|-------------------|---------------|
| **keine** | 302 | 2,18 % | **2,78 %** | **35,2x** |
| 0,80 | 299 | 2,16 % | 2,80 % | 34,9x |
| 0,70 | 253 | 1,79 % | 4,30 % | 22,8x |
| 0,60 | 194 | 1,43 % | 9,12 % | 10,8x |
| 0,50 | 136 | 0,92 % | 19,18 % | 5,2x |
| 0,30 | 48 | 0,26 % | 39,49 % | 2,5x |

Trennschaerfe ist angenommene echte Paare geteilt durch angenommene
Zufallspaare. **Jede Buendelung kostet mehr, als sie bringt**: von 302 auf 253
Klassen faellt die Unbekannt-Quote um 0,39 Punkte, waehrend die Zufallsannahme
um 1,52 Punkte steigt. Die ungebuendelte Kacheltabelle ist die schaerfste, die
zu haben ist.

Damit ist auch gesagt, warum die Tabelle so duenn ist: **nicht weil Belege
fehlen, sondern weil die Kacheln sich wirklich unterscheiden.** Mehr Daten
helfen, Zusammenfassen nicht.

### Keilfoermige Gruppen: gemessen, bringt nichts

Ein Rechteck ueber einer Schraegen ist zum groessten Teil Boden, also lag die
Frage nahe, ob ein KEIL (Parallelogramm) die Schraege besser fasst. Gemessen auf
denselben Stellen — nur Fenster, deren Oberkante ueber die Fensterbreite
wandert:

| Fenster | Rechteck | Keil 0,5 | Keil 1,0 | folgt der Wand |
|---------|----------|----------|----------|----------------|
| 4x4, Vorkommen je Muster | **1,84** | 1,75 | 1,82 | 1,48 |
| 6x4 | **1,53** | 1,50 | 1,47 | 1,23 |
| 8x4 | **1,40** | 1,31 | 1,31 | 1,16 |

Nichts schlaegt das Rechteck, und das Fenster, das der Wand selbst folgt, ist am
schlechtesten. Der Grund liegt tiefer als die Fensterform: **in den
Originalkarten gibt es kaum Schraegen.** Ueber alle 54 Karten nur 206 Stueck mit
zusammen 974 Tritten, und jedes Schraegenfenster kommt nur 1,2 bis 1,8 mal vor,
gleich welche Form es hat. Zum Vergleich decken die waagerecht-senkrechten
6x4-Gruppen 159700 Vorkommen auf 4348 Muster — 36,7 je Gruppe.

Fuer Schraegen ist also nichts zu lernen, was sich wiederholt. Sie muessen
erzeugt werden: Treppe aus der gemessenen Verteilung, Kacheln aus der
Nachbarschaftstabelle.

### Die Nordkante ist duenn — jeder Dichtefilter wirft sie weg

Von den 307 Klippenkacheln sind **41 Nordkacheln** (`NORTH_CLIFFS`), mit 14478
Vorkommen; die anderen sind 158 `CLIFFS_LOW_SIDE` und 108 `CLIFFS_HIGH_SIDE`.

Die Nordkante ist ein bis zwei Kacheln hoch und fuellt ein 6x4-Fenster damit nur
zu einem Viertel. Die erste Gruppentafel hatte alles unter einem Drittel
Klippenzellen weggefiltert — und damit allein bei 6x4 **807 Gruppen mit
Nordkachel** unsichtbar gemacht. Im Modell waren sie die ganze Zeit: 1387 der
4348 6x4-Gruppen enthalten eine Nordkachel, 223 bestehen nur daraus.

Gebaut werden sie auch. Nachbau nach Zelltyp aufgeschluesselt:

| Zelltyp | Zellen | identisch |
|---------|--------|-----------|
| Nord    |  66    | **40,9 %** |
| Hoch    | 177    | 27,7 % |
| Tief    | 225    | 40,4 % |

Die Nordkante ist also die am besten getroffene der drei — sie war nur nicht zu
sehen. Wer nach Flaechenanteil filtert, filtert nach Wandstaerke.

### Wiederholung ist praktisch verboten

Wie oft steht dieselbe Kachel neben sich selbst? Ueber alle 54 Karten:

| Richtung | Anteil der Klippenpaare |
|----------|-------------------------|
| N / S    | 0,64 % |
| O / W    | 1,07 % |
| NO / SW  | 0,98 % |
| SO / NW  | **1,65 %** |
| **gerade gesamt** | **0,85 %** |
| **ueber Eck gesamt** | **1,31 %** |

Ueber Eck ist es also **haeufiger** als gerade, und dabei ist die Diagonale
SO/NW deutlich staerker als NO/SW — die Richtung, in die die isometrische
Darstellung faellt.

Der laengste Lauf derselben Kachel in allen 54 Karten ist **3**; 99,2 % der
waagerechten Laeufe haben Laenge 1. **176 der 307 Kacheln** stehen nie neben
sich selbst.

Das ist ein Pruefmass fuer jeden Setzer: wer darueber liegt, kachelt sichtbar.
Der Fuell-Durchgang tat das (2,4 bis 8,6 % gerade), weil er rohe
Vorkommenszahlen multiplizierte und damit global haeufige Kacheln bevorzugte.
Mit Anteilen je Richtung statt roher Zahlen steigen die Treffer leicht (87,8 →
88,1 %) und die Wiederholung faellt (1,64 → 1,29 %). Im Setzer mit Gruppen
liegt eden09 bei 0,34 % gerade — genau auf dem Wert des Originals.

**Der Weg ohne Gruppen bleibt unstabil.** Von Null weg Zelle fuer Zelle zu
fuellen baut auf den eigenen Fehlern auf; dort schwankt die Wiederholung mit
jeder Gewichtsaenderung stark in beide Richtungen. Das ist genau der Weg, den
die Gruppen ersetzen — im Zweiwege-Setzer fuellt die Tabelle nur noch eine
Handvoll Zellen.

### Stand (31.07.2026)

Modell gebaut, Setzer laeuft in zwei Durchgaengen, haengt noch an nichts. Offen:
keine Pruefungen in den Suiten (die Wiederholungsrate waere die erste), Zelltypen
werden nicht mitgesetzt, der Setzer liegt noch im Scratchpad und nicht in
`mapgen`.

## 11. Arbeitsweise, die sich bewaehrt hat

**Erst messen, dann bauen.** Jede Vermutung in dieser Sitzung, die nicht
gemessen wurde, war falsch — teils zweimal hintereinander an derselben Stelle.

**Manches ist keine Messfrage.** „Es gibt keine Ebenen" (7.7) kam vom Nutzer
und beendete den Punkt in einem Satz. Bevor eine Messung aufgesetzt wird, lohnt
die Frage, ob jemand die Antwort einfach weiss — die 13 Regeln in 3. kamen
genauso zustande.

**Ein Rueckfall, der die Bedingung fallen laesst, ist der Fehler.** Drei Mal
aufgetreten: `bloecke("Ecke") or bloecke("Motiv")` (das `or` erreichte drei von
vier Eckdrehungen nie), `if not passend: passend = ecken` (setzte die um 180
Grad verdrehte Ecke), `gelockert()` mit Rueckfall auf alle Kacheln.

**Vorlieben gehoeren in Gewichte, nicht in Filter.** Die Regel „Wand auf genau
diesen Seiten" hat den richtigen Eckblock aussortiert, weil die Messung ihm
eine dritte Wandkante zuschreibt. Harte Bedingung: „hat Wand auf den
gebrauchten Seiten". Alles Weitere: Gewicht.

**Pruefen, ob die Messmethode das ueberhaupt sehen kann.** Die
Ueberlappungszaehlung konnte prinzipiell nur null liefern. Dieselbe Falle noch
einmal in 7.1: die Achsenfrage sah nur den naechstliegenden Block und konnte
am Wandende gar nichts anderes als „keine Achse" antworten. Wer den Fehler
bei der Ecke sucht, sucht dann lange.

**Was der Kachelsatz nicht hergibt, wird nicht erfunden.** Fuer senkrechte
Wandenden gibt es keinen Abschluss, fuer einen T-Stoss kein Stueck, fuer eine
haarfeine Nordkante keine Kappe. Jedes Mal war die richtige Antwort, die Stelle
frei zu lassen oder das Vorhandene stehen zu lassen — und jedes Mal stand
vorher etwas Verdrehtes dort, weil eine Regel unbedingt etwas setzen wollte.

**Ein Kommentar ist keine Zusicherung.** Der Vorrang der gemerkten Enden stand
seit jeher als Begruendung im Code und war nie gebaut (7.4). Wo ein Kommentar
ein Verhalten behauptet, gehoert eine Pruefung daneben — sonst beschreibt er
eine Absicht, die niemand einloest.

**Zwei Fragen, die gleich klingen, sind selten dieselbe.** „Laeuft die Wand
ueber diese Kante weiter?" und „welche Seite ist oben?" sahen wie eine aus, und
solange nur die erste gestellt wurde, stand die Haelfte der Ecken verdreht.
Genauso `klippen_gewicht` gegen `klippen_belegt`: „welcher Kandidat" und „ob
ueberhaupt einer".

**Ein Zaehler, der nicht misst, was stoert, ist schlimmer als keiner.** Der
5x5-Kasten um den Knick nannte die Korrektur in 12 Faellen schlechter; angesehen
war sie dort besser. Umgekehrt fand der Zaehler „eingeschlossene Bodenkacheln"
ueberall null — der blasse Fleck war nie ein Loch im Gitter, sondern eine
Klippenkachel mit dem falschen Gesicht. Bei Klippen entscheidet am Ende das
Bild; die Zahl taugt nur, wenn vorher geprueft ist, dass sie den Mangel
ueberhaupt beruehrt.

**Eine Pruefung, die auch vorher gehalten haette, belegt nichts.** Fuer beide
Korrekturen wurden die Aenderungen im Quelltext gezielt zurueckgedreht und die
neuen Pruefungen dagegen laufen gelassen: `Achse am waagerechten Ende: None`
und `Wandenden mitten in der Wand: [sanmes12/mudmes05]` — beide fallen durch,
danach halten sie. Ohne diesen Gegenlauf waeren es Zeilen ohne Aussage.

## 12. Die Kantenzuordnung von Hand — und warum sie nicht fehlerfrei wird

Jede Klippenkachel bekommt fuer jede ihrer vier Seiten vier Abschnitte, und
jeder Abschnitt sagt: hier grenzt **Fels** an, hier **Biom**, oder **egal**.
Zugeordnet wird von Hand mit `editor/tools/kanten_zuordnen.py`, geprueft mit
`editor/tools/kante_gegen_alle.py`. Das Ergebnis steht in
`mapview/cliff_kanten.json`.

Geprueft wird gegen die 54 Originalkarten: liegen zwei Kacheln dort
nebeneinander, muessen ihre zugewandten Abschnitte zusammenpassen. Fuer mud
(156 zugeordnete Kacheln, 2496 Abschnitte) blieben nach mehreren Durchgaengen
11347 Vorkommen an Widerspruechen.

### Warum Nachbessern den Fehler nur verschiebt

Beim Korrigieren wurden die Fehler nicht weniger, sondern wanderten. Der Grund
ist gemessen und eindeutig:

> **Alle 11347 Widersprueche — 100 %, nicht 90 oder 95 — sitzen an Abschnitten,
> an denen die Partner aus den Originalkarten beides verlangen.** Kein einziger
> ist durch einen anderen Wert loesbar.

Eine Kachelseite trifft in den Karten viele Partner. Verlangt Partner A an
Abschnitt 2 Fels und Partner B dort Biom, dann heilt jede Festlegung das eine
Paar und reisst das andere auf. Solche Abschnitte heissen hier **zerrissen**.

Damit ist die Frage „welcher Wert ist richtig?" an diesen Stellen falsch
gestellt. `egal` ist dort keine Ausweichloesung, sondern die einzige Aussage,
die stimmt.

### Was drei andere Wege gebracht haben (alle gemessen, alle verworfen)

**Ausgleichen mit Suchverfahren** (iterated conditional modes, Treuestrafe
gegen Abweichung von der Handarbeit). Ohne `egal` wird es bei jeder Einstellung
**schlechter** als von Hand — 133 %, 124 %, 111 %, 96 %. Mit `egal` sinkt es
stark, aber die Suche setzt `egal` willkuerlich: 50/67/58 % ihrer
egal-Vorschlaege liegen an Abschnitten mit unklarer Fels-Boden-Grenze,
erwartbar waeren 56 %. Reiner Zufall, also keine Begruendung.

**Die Pixel als Schiedsrichter.** Aus `cliff_pixels_model.npz` laesst sich je
Abschnitt sagen, welcher Anteil der acht Randpixel Fels ist. Die Handzuordnung
deckt sich damit zu 90,2 %. Von den 59 groben Faellen (drei oder vier
abweichende Abschnitte) entscheiden die Pixel aber nur **3**; und zwingt man
die 155 abweichenden Abschnitte aufs Bild, steigen die Widersprueche auf
**394 %**. Die Handzuordnung ist in sich stimmiger als das Pixelkriterium.

**Die Vermutung, es liege an schraegen Grenzen.** Laeuft die Fels-Boden-Grenze
mitten durch die acht Pixel eines Abschnitts, runden zwei Kacheln sie
verschieden — das erklaert die 787 Faelle mit einer einzigen Abweichung. Die
groben Faelle erklaert es nicht: dort sind 33 bis 42 % der strittigen
Abschnitte unklar, bei einer Grundrate von 36 %.

### Der Weg, der bleibt: zerrissene Abschnitte auf `egal`

Keine Suche, keine Willkuer, eine Regel. Was sie kostet (mud):

| Regel | Widersprueche | erlaubte Paare | egal-Abschnitte |
|---|---|---|---|
| von Hand | 11347 (100 %) | 24,2 % | 30 |
| zerrissen ab 50 Vorkommen | 1134 (10,0 %) | 29,8 % | 165 |
| zerrissen ab 20 Vorkommen | 454 (4,0 %) | 34,8 % | 262 |
| **zerrissen ab 10 Vorkommen** | **218 (1,9 %)** | **39,4 %** | **348** |
| zerrissen ab 1 Vorkommen | 0 | 63,0 % | 873 |
| alles auf `egal` | 0 | 100,0 % | 2496 |

Die Spalte „erlaubte Paare" ist der Preis: jedes `egal` macht die Zuordnung
nachgiebiger. Alles auf `egal` zu setzen erreicht null Widersprueche, indem es
jede Aussage aufgibt — genau darum ist es keine Loesung. Bei Schwelle 10
widerspricht fast nichts mehr, und die Zuordnung lehnt immer noch drei von
fuenf Paaren ab.

`ZERRISS_SCHWELLE` in `editor/tools/kante_gegen_alle.py` haelt diesen Wert.
Zerrissene Abschnitte sind dort violett umrandet, der Kopf sagt, wieviele der
strittigen Abschnitte ueberhaupt loesbar sind, `Z` setzt sie fuer die gezeigte
Kante auf `egal`, `Umschalt+Z` fuer die ganze Zuordnung — als eine Gruppe, die
ein `Strg+Z` wieder zuruecknimmt.

### Stand (02.08.2026) — angewandt

Die Regel ist angewandt: `cliff_kanten.json` steht bei **341 `egal`** (14 % der
Abschnitte) und **218 Vorkommen** an Widerspruechen.

| | Vorkommen | Anteil aller mud-Nachbarschaften |
|---|---|---|
| vorher | 11347 | 7,89 % |
| jetzt | 218 | **0,15 %** |
| bestenfalls ohne neues `egal` | 162 | 0,11 % |

Bei 143791 mud-Nachbarschaften insgesamt. Von den groben Faellen sind drei
Paare mit vier abweichenden Abschnitten uebrig (4 Vorkommen) und acht mit drei
(17 Vorkommen).

**Der Charakter der Restfehler hat sich umgekehrt.** Bei `ZERRISS_SCHWELLE`
sitzt keiner mehr an einer zerrissenen Stelle — jede Korrektur wirkt jetzt,
statt den Fehler weiterzuschieben. Streng gemessen (jede Minderheit zaehlt,
nicht erst ab 10) sind allerdings nur 20 der 278 strittigen Abschnitte
*eindeutig*, also mit einigen Partnern; beim Rest steht eine grosse Mehrheit
gegen eine kleine Minderheit, etwa `187 West` Abschnitt 3 mit 8 mal Biom gegen
486 mal Fels.

Der Mehrheit ueberall zu folgen bringt 218 → 162 Vorkommen fuer 19 Klicks und
kein einziges neues `egal`. Die restlichen 162 (112 Paare) sind ohne weiteres
`egal` nicht aufloesbar. Ob sich die 19 Klicks fuer 0,04 Prozentpunkte lohnen,
ist eine Ermessensfrage — die Zuordnung ist an dieser Stelle fertig.

### Im Loeser (`cliff_kanten.py`, `klippe_loesen(kanten=True)`)

Die Paartabelle kennt nur, was in den 54 Karten NEBENEINANDER VORKAM. Das ist
eine Stichprobe, kein Regelwerk — und der Grund, warum der Loeser bei Schraegen
in die Zeitgrenze lief. Von 48672 mud-Paarungen:

| | Paarungen | |
|---|---|---|
| in den Karten belegt | 4484 | 9,2 % |
| von der Kantenzuordnung neu erlaubt | 14804 | 30,4 % |
| verboten | 29384 | 60,4 % |

Belegt bleibt vor erlaubt — aber als **Rang**, nicht als Gewicht. Als Gewicht
abgetastet (mittlere Naht ueber die drei mud-Waende, Original 24):

    Abschlag   1,00   0,50   0,25   0,10   0,00
    Naht       26,9   26,5   25,9   25,8   24,4

Am besten ist der Grenzfall, und der ist genau der Rang. Innerhalb des zweiten
Rangs entscheidet die **Naht allein**: bei einer bloss erlaubten Paarung sagt
die Haeufigkeit nichts ueber diese Stelle — die Kachel ist ja gerade deshalb im
Vorrat, weil ihre Kanten passen, nicht weil sie hier je gelegen haette.

| mud | nur Paartabelle | + Kanten, Rang nach Haeufigkeit | + Kanten, Rang nach Naht |
|---|---|---|---|
| waagerecht | 25,2 | 25,3 | 25,5 |
| schraeg 2:1 | 26,6 / **8,1 s** | 26,3 | **24,2** / 0,2 s |
| schraeg 1:1 | 26,4 | 26,2 | **23,8** / 0,2 s |

Die 8,1 Sekunden bei 2:1 waren die Zeitgrenze: der Loeser gab die Pixelordnung
auf und fiel auf die Haeufigkeit zurueck. Mit dem groesseren Vorrat loest er in
0,2 Sekunden und behaelt die Naht.

**Das Mass hat sich mitgeaendert.** „Unbelegte Paare" taugt nicht mehr als
Urteil, sobald der Loeser unbelegte Paare nutzen DARF — es steigt
zwangslaeufig. Der Fehler ist jetzt „weder belegt noch erlaubt", und der ist
auf allen Waenden **null**. Dass die Zahl etwas misst, ist gegengeprueft:
dieselben Waende mit Bloecken haben 88 (2:1) und 136 (1:1) regelwidrige Paare.

### Durchgesetzt statt nur gemessen (`klippe_regeln_durchsetzen`)

Der Loeser setzt von sich aus nichts Regelwidriges — aber er laeuft nicht
ueberall. An Ecken, Enden, wiederhergestellten Querwaenden und ueberall dort,
wo gar nicht gesucht wird, bleiben Bloecke stehen, und der reine Blockweg hat
auf den Schraegen 88 (2:1) und 136 (1:1) regelwidrige Paare.

`klippe_naehte_bessern` bringt die nur auf 80. Sie sucht in der falschen Menge:
sie zielt auf UNBELEGTE Paare, und davon gibt es hundertfach mehr als
regelwidrige. Deshalb eine eigene Runde am Ende von `klippe_aus_linie`, die
allein auf das zielt, was wirklich falsch ist. Weil das wenige sind, kann sie
Kachel fuer Kachel vorgehen und jede Ersetzung einzeln pruefen: ersetzt wird
nur bei strikter Verbesserung, unter gleichguten Kandidaten gewinnt der
belegte, dann der mit der besseren Naht.

| mud | vorher | nachher |
|---|---|---|
| waagerecht | 0 regelwidrig, Naht 17,3 | 0, Naht 17,3 |
| schraeg 2:1 | 88, Naht 22,1 | **0**, Naht 22,0 |
| schraeg 1:1 | 136, Naht 25,8 | **0**, Naht **23,6** |

**Der Eckenschutz gilt hier nicht** (`REGELN_ECKENSCHUTZ = 0`). `ECKENSCHUTZ`
haelt Loeser und Nahtreparatur von den gezeichneten Ecken fern, weil beide
GANZE Bereiche neu belegen und der Block danach nicht mehr auffindbar ist. Die
Durchsetzung tauscht dagegen einzelne Kacheln. Abgetastet:

    Radius      7    5    3    2    1    0
    2:1        16   10    6    2    0    0
    1:1        28   21   14   10    3    0

Bei Radius 7 lagen ALLE verbleibenden schlechten Zellen im Schutz und keine
einzige ausserhalb — der Schutz war die ganze Restmenge. Was dagegen sehr wohl
ausgenommen bleiben muss, sind `quer_heil` und `schon_da`: ohne die erste fiel
die Pruefung „T-Stoss laesst die Querwand heil" um.

Fuer san und sno aendert das nichts: `kennt()` sagt Nein, und wer nichts weiss,
darf nichts verbieten.

In der Suite stehen dafuer sechs Pruefungen (`check_kantenzuordnung`,
`check_regeltreu`), darunter der Gegenlauf mit `regeln_durchsetzen=False`, der
zeigt, dass die Kennzahl ueberhaupt anschlagen kann (80 Paare).

### Die Wandhoehe (`klippe_hoehe_begrenzen`, `klippe_aus_linie(hoehe=…)`)

Die Uebergangskacheln standen mitten in der Wand statt an ihrem Rand. Aus der
Kantenzuordnung laesst sich die Rolle jeder Kachel ablesen — Nordseite zeigt
Boden heisst Oberkante, Suedseite zeigt Boden heisst Unterkante — und damit der
Fehler zaehlen: eine Bodenkante, hinter der eine Klippenzelle steht.

| | Bodenkante mit Klippe dahinter |
|---|---|
| Originalkarten, gerade Stellen | 0,89 % |
| Originalkarten, schraege Stellen | 0,72 % |
| erzeugt, waagerecht | 0,7 % |
| erzeugt, schraeg 2:1 | **8,5 %** |
| erzeugt, schraeg 1:1 | **11,3 %** |

Die Ursache ist die Banddicke. Aus den Bloecken ergibt sie sich von selbst und
kommt waagerecht sauber auf 3; auf Schraegen ueberlappen die Bloecke an den
Stufen und das Band wird 3 bis 7 Kacheln dick. In einem zu dicken Band landen
Ober- und Unterkanten zwangslaeufig in der Mitte.

Die Originalkarten benutzen alle Hoehen: 1 Kachel 23,9 %, 2 Kacheln 12,6 %,
3 Kacheln 27,0 %. `hoehe` gibt sie jetzt vor, gezaehlt von der gezeichneten
Kante aus; gestutzte Zellen bekommen wieder Boden aus `tm.by_family`.

| Wand | Banddicken ohne | mit 3 | mit 2 |
|---|---|---|---|
| waagerecht | 3 → 0,7 % | 3 → 0,7 % | 2 → 1,0 % |
| schraeg 2:1 | 3–6 → 8,5 % | 3–4 → **1,4 %** | 2–3 → **1,0 %** |
| schraeg 1:1 | 3–7 → 11,3 % | 3–5 → 5,3 % | 2–3 → **0,7 %** |

**Gezaehlt wird die Banddistanz, nicht die Achse.** Entlang einer Achse zu
zaehlen war der erste Versuch und falsch: auf einer 45-Grad-Wand zeigt die
Hochrichtung mal nach Norden, mal nach Westen, und eine senkrechte Zeile durch
das schraege Band ist laenger als seine Dicke. Damit blieben bei `hoehe=3`
Baender von 4 stehen und 7,9 % statt 5,3 %.

**Offen bleibt `hoehe=3` auf der 45-Grad-Schraegen: 5,3 %.** Das ist kein
geometrischer Zwang — die Originalkarten liegen auf schraegen Stellen bei
0,72 %, also genauso gut wie auf geraden. `hoehe=2` erreicht diesen Wert
(0,7 %), `hoehe=3` nicht.

### Das Loch: Biom gegen Biom zwischen zwei Klippenzellen

Vorbild ist cm02 64,164 bis 70,161 — eine 2:1 nach rechts oben, Band
durchgehend 3 Kacheln, je Spalte Oberkante / voll / Unterkante. Der Setzer
baute dort stattdessen zwei Blockstuecke uebereinander, und an ihrer
Beruehrung stand eine Unterkante direkt ueber einer Oberkante: die eine zeigt
nach unten Boden, die andere nach oben. Zusammen ist das ein Schnitt quer durch
die Wand — genau die Uebergangskacheln mitten in der Klippe.

`passt` liess das durch, weil `BIOM == BIOM` als passend gilt. Zwischen einer
Klippen- und einer Bodenzelle ist das richtig, zwischen ZWEI Klippenzellen
nicht. Gemessen an 176524 Naehten zwischen Klippenzellen der 54 Karten:

| | Anteil |
|---|---|
| gemischt | 41,94 % |
| ganz Fels an Fels | 22,90 % |
| unbekannt | 18,54 % |
| 1 Abschnitt Biom an Biom | 10,03 % |
| 2 Abschnitte Biom an Biom | 6,11 % |
| **ganz Biom an Biom** | **0,46 %** |
| 3 Abschnitte Biom an Biom | 0,01 % |

Ein oder zwei Abschnitte sind haeufig — das ist eine schraege Kante, die durch
die Naht laeuft. Ab drei ist es praktisch ausgeschlossen; daher
`CliffEdgeModel.loch(..., mindestens=3)`.

**Es ist unerwuenscht, nicht verboten.** Als harte Bedingung fiel die Pruefung
„Fortsetzung um die Ecke bekommt einen Eckblock" um, und die Ursache war nicht
der Schutzradius: **2 bis 3 der 35 Klippenbloecke aus den Originalkarten
enthalten selbst so eine Naht.** Wer das verbietet, verbietet Originalmaterial.
Also getrennt gefuehrt — `regelwidrig` (weder belegt noch erlaubt, davon darf
nichts stehenbleiben) und `Loch` (selten, aber es kommt vor). Die Reparatur
raeumt Loecher erst NACH den regelwidrigen weg, der Loeser meidet sie mit
Rueckfall.

Alle vier Schraegrichtungen, `hoehe=3`, Bodenkante mit Klippe dahinter
(Originalkarten 0,72 bis 0,89 %):

| Richtung | vorher | mit der Loch-Regel |
|---|---|---|
| rechts unten | 1,4 % | **1,0 %** |
| rechts oben (wie cm02) | 0,8 % | **0,8 %** |
| links unten | 2,2 % | **0,7 %** |
| links oben | 3,1 % | 2,3 % |

Ohne `hoehe` sinkt „rechts unten" von 7,3 auf 4,6 %, „links unten" von 3,3 auf
1,0 %.

**Offen bleibt die Form selbst.** cm02 schiebt ein 3 Kacheln dickes Band um
eine Zeile je zwei Spalten weiter; der Setzer stapelt 3 Kacheln hohe Bloecke,
die sich ueberlappen, und laesst dabei Baender von 5 stehen. Die Loch-Regel
raeumt die Folge auf, nicht die Ursache. Dazu kommt: bei einem Zug von nur
sechs Kacheln liegt die ganze Wand im `ECKENSCHUTZ` der beiden Endpunkte, der
Loeser kommt dort also gar nicht zum Zug.

### Die Gruppen, neu beurteilt

Die geschuerften Gruppen (Abschnitt 10) galten als gescheitert. Der Satz dazu
im Quelltext lautete: „ein senkrechter Lauf steht als Block bei 0 % unbekannten
Paaren und mit Gruppen bei 11 bis 12 %." Das ist **richtig gemessen und falsch
verallgemeinert** — es gilt fuer gerade Laeufe, an Schraegen ist es umgekehrt.

Dazu kommt, dass das damalige Mass unbrauchbar war: „unbelegt" heisst nur, dass
die 54 Karten dieses Paar nicht zeigen, und sie sind eine Stichprobe. Mit der
Kantenzuordnung laesst sich fairer urteilen. Gemessen, alles bei 0 regelwidrig;
„falsch mitten" = Bodenkante mit Klippe dahinter, Originalkarten 0,72–0,89 %:

| Zug | Bloecke | Gruppen ueberall |
|---|---|---|
| senkrecht | **0,0 %**, Naht 9,1 | 3,4 %, Naht 15,4 |
| waagerecht | 0,7 %, Naht 17,3 | 0,7 %, Naht 21,6 |
| 2:1 runter | 5,2 % | **1,7 %** |
| 2:1 hoch | 1,3 % | **0,4 %** |
| 1:1 runter | 6,5 % | **2,9 %** |

Die Bloecke stammen aus dem Kachelsatz und kennen den geraden Lauf; den
diagonalen kennen sie nicht, den gibt es nur in den Karten — und dafuer sind
die Gruppen da. Also jedes Werkzeug dort, wo es herkommt:
`gruppen_auf_stufen=True` setzt die Stufen aus Gruppen und laesst die geraden
Stuecke als Bloecke stehen. `klippe_stufen` ist dafuer aus
`klippe_naehte_bessern` herausgeloest.

| Zug | nur Bloecke | Gruppen auf Stufen | dito + `hoehe=3` |
|---|---|---|---|
| senkrecht | 0,0 % | 0,0 % | 0,0 % |
| waagerecht | 0,7 % | 0,7 % | 0,7 % |
| 2:1 runter | 5,2 % | 4,2 % | **2,2 %** |
| 2:1 hoch | 1,3 % | 0,7 % | 0,9 % |
| 1:1 runter | 6,5 % | 6,0 % | **4,4 %** |

**Auf die Stufen beschraenkt bleibt die Haelfte des Gewinns liegen** (1:1: 6,0 %
statt 2,9 %). Der Grund ist der `ECKENSCHUTZ`: `klippe_stufen` nimmt 15x15
Zellen um jeden gezeichneten Punkt aus, und auf einer 45-Grad-Wand ist das ein
grosser Teil der Wand. Gruppen ueberall zu setzen ist keine Loesung — dann ist
der Block nicht mehr auffindbar und die 20 Pruefungen aus Abschnitt 7 fallen um.

### Harte Uebergaenge: nackter Fels gegen offenen Boden

Die Suite kennt den Begriff fuer den Boden — zwei Boeden duerfen nie ohne
Uebergangskachel aneinanderstossen. An der Klippe gibt es das Gegenstueck, und
die Kantenzuordnung kann es benennen: **eine Kachelseite zeigt FELS, aber
daneben liegt offener Boden.** Die Wand hoert einfach auf. Originalkarten:
**0,47 %** von 61907 Kachelseiten.

Das `hoehe`-Stutzen aus dem vorigen Abschnitt hat genau das erzeugt — es
schneidet das Band ab und legt nackten Fels frei:

| Zug | ohne | `hoehe=3` | `hoehe=2` |
|---|---|---|---|
| waagerecht | 0,0 % | 0,0 % | **17,0 %** |
| 2:1 hoch | 2,2 % | 8,0 % | **21,9 %** |
| 1:1 runter | 5,0 % | 9,5 % | **28,4 %** |

`hoehe=2` war als die saubere Einstellung empfohlen — gemessen war nur die eine
Seite (Uebergaenge mitten in der Wand), die andere nicht. Nach der Reparatur:

| Zug | ohne | `hoehe=3` | `hoehe=2` |
|---|---|---|---|
| waagerecht | 0,0 % | 0,0 % | 2,7 % |
| senkrecht | 1,4 % | 1,4 % | 1,4 % |
| 2:1 runter | 0,0 % | 0,5 % | 2,7 % |
| 2:1 hoch | 0,0 % | 0,3 % | 4,3 % |
| 1:1 runter | 0,9 % | 1,5 % | 3,1 % |

**Zwei Reparaturen, zwei Schutzmasken.** Regelwidriges liegt INNEN in der Wand
und braucht `REGELN_ECKENSCHUTZ = 0`; harte Uebergaenge liegen am RAND, also
genau dort, wo die Bloecke ihre Kanten haben. Mit einem gemeinsamen Radius geht
beides nicht auf:

    Radius   Suite                      hart    regelwidrig
      0      5 rot (Fortsetzung/Ecke)   0,0 %        0
      2      3 rot (regeltreu)          1,6 %       21
      7      3 rot (regeltreu)          3,5 %      104

Getrennt gefuehrt (`HART_ECKENSCHUTZ`) geht es; 1 ist der kleinste Radius, bei
dem die Bloecke auffindbar bleiben.

**Das Loch darf kein Ausgangspunkt der Reparatur sein.** Als solcher
aufgenommen fiel „Fortsetzung um die Ecke bekommt einen Eckblock" um — jede
angefasste Zelle macht ihren Block unauffindbar, und das Loch ist unerwuenscht,
nicht unmoeglich. Es zaehlt nur dort mit, wo die Reparatur ohnehin arbeitet.

### Erst die Raender (`klippe_raender_setzen`)

Der Rand ist das Einzige, was man von einer Klippe sieht, und er ist staerker
eingeschraenkt als das Innere: liegt hinter einer Kachelseite offener Boden,
MUSS diese Seite Boden zeigen. Wer den Rand zuletzt behandelt, hat dort keine
Wahl mehr — das Innere hat ihn schon festgelegt. Also laeuft der Durchgang vor
`klippe_regeln_durchsetzen` und fasst nur Randzellen an.

**Die Fuellkachel faellt damit von selbst weg.** 19 der 156 zugeordneten
mud-Kacheln zeigen auf allen vier Seiten Fels; sie gehoeren ins Innere und
koennen an keinem Rand stehen. Bei `hoehe=2` ist JEDE Zelle eine Randzelle —
die Wand hat kein Inneres, also kann dort keine Fuellkachel vorkommen. Die
zweite Forderung folgt aus der ersten. Zum Vergleich: die Originalkarten haben
1,13 % Fuellkacheln auf ihren Randzellen.

**Bei vorgegebener Hoehe gilt der Eckenschutz hier nicht.** Er soll die Bloecke
auffindbar halten — aber das Stutzen hat sie ohnehin zerschnitten, an den
Zugenden ist nichts mehr zu bewahren. Mit Schutz blieben Reste stehen, und
gemessen sassen sie **ausnahmslos** an einem Zugende (15 von 15 Faellen).

| Zug | | Fuellkachel am Rand | Fels zum Boden |
|---|---|---|---|
| waagerecht | `hoehe=2` vorher | 1,8 % | 5,5 % |
| | nachher | **0** | **0** |
| 2:1 hoch | `hoehe=2` vorher | 1,0 % | 4,1 % |
| | nachher | **0** | **0** |
| 1:1 runter | `hoehe=2` vorher | 0 | 3,9 % |
| | nachher | 0 | **0** |

Ohne `hoehe` bleibt der Schutz und damit ein Rest an den Zugenden — dort ist
die Wand nicht fertig, sondern wartet auf die Fortsetzung.

Stand bei `hoehe=2` ueber alle fuenf Zuege: 461 Zellen, 0 regelwidrig, 0 hart,
0 Fuellkacheln, 5 Loecher.

### Was im Editorbild zu sehen war, und was davon gemessen ist

Ein Bild aus dem Editor zeigte harte Kanten und Luecken. Nachgestellt wurde
systematisch; **nicht reproduzieren** liessen sich die Luecken:

| Vermutung | gemessen |
|---|---|
| Streckenzug mit Knicken (3 bis 6 Punkte) | haengt zusammen, 0 bis 4 harte Kanten |
| zweiter Zug ans Ende des ersten | haengt zusammen |
| kurze Abschnitte (3 bis 12 Kacheln) | haengt zusammen |
| steile Neigungen bis 1:8 | haengt zusammen |
| Winkelrasten verschiebt den Klick | hoechstens 2 Kacheln, nie 3 |

Zwei Befunde dagegen sind hart:

**1. Fuer san ist nichts zugeordnet — 0 von 138 Kacheln** (mud: 156 von 160).
Damit ist auf san alles untaetig, was in diesem Abschnitt steht: die
Randsetzung, die Regeldurchsetzung, die Loch- und die Hart-Regel. `kennt()`
sagt Nein, und wer nichts weiss, darf nichts verbieten. Der Anteil unbelegter
Paare ist dort entsprechend rund doppelt so hoch wie bei mud (35,4 % gegen
17,7 % auf der 2:1, 39,0 % gegen 29,6 % auf der 1:1).

**2. Eine Wand ueber eine Biomgrenze erzeugt 118 harte Bodenkanten.** Die
Familie wird nur am ERSTEN Punkt bestimmt (`paint_layers.py`, `familie` aus
`punkte[0]`) und fuer den ganzen Zug beibehalten. Laeuft die Wand ins
Nachbarbiom, stehen ihre Kacheln dort gegen fremden Boden: gemessen an einem
einzigen 2:1-Zug ueber eine mud/san-Grenze 74 Kachelseiten an fremdem Biom und
118 harte Bodenkanten nach der Regel, die die Suite fuer den Boden anlegt.
Nicht behoben.

**Neu in der Suite: `check_wand_haengt_zusammen`.** Bis hierher sah jede
Kennzahl auf Nahtstellen, keine auf die Form als Ganzes — eine Wand mit Luecken
faellt aber mehr ins Auge als jede falsche Kachel. Geprueft werden gerade,
schraege und geknickte Zuege sowie ein zweiter Zug am Ende des ersten, fuer mud
und san.

## 13. Die Gruppen, neu geschuerft und nach FORM indiziert

Das aeltere `cliff_patches` haelt dieselben Gruppen ueber ihre FUELLUNG
indiziert. Beim Setzen lautet die Frage aber nicht „kenne ich diese
Kachelfolge", sondern **„hier steht diese Stufe — welche Kacheln gehoeren da
hin?"**. Nach Fuellung indiziert ist das eine Suche, nach Form ein
Nachschlagen. `learn_cliff_gruppen.py` und `cliff_gruppen.py`.

### Was die Karten hergeben

Anteil der 121603 Klippenzellen, die in einer Gruppe ab 10 Vorkommen liegen:

| Groesse | ab 3× | ab 10× | ab 30× | ab 100× |
|---|---|---|---|---|
| 2x2 | 99,3 % | 97,4 % | 92,8 % | 81,8 % |
| 3x3 | 98,2 % | 93,6 % | 85,2 % | 70,6 % |
| 4x3 | 97,1 % | 90,3 % | 78,6 % | 62,0 % |
| 6x4 | 92,4 % | **80,2 %** | 66,3 % | 47,9 % |

Die aeltere Notiz nannte fuer 6x4 „deckt streng 27,8 %". Das war eine andere
Frage — dort ueberlappungsfrei gekachelt, hier „liegt in mindestens einer
haeufigen Gruppe". Der Wortschatz ist da, er laesst sich nur nicht lueckenlos
parkettieren; genau darum die Leiter mehrerer Groessen.

### Warum die Form der Schluessel ist

Nach Art getrennt, 4x3, Bestimmtheit = Vorkommen je Fuellung:

| Art | Formen | Vorkommen | Fuellungen | Bestimmtheit |
|---|---|---|---|---|
| gerade | 354 | 204860 | 34133 | 6,0 |
| Stufe | 749 | 64003 | 18911 | 3,4 |

Im Mittel sagt das wenig, im Einzelnen sehr viel. Die haeufigsten GERADEN
Formen haben 700 bis 3000 Fuellungen — die sagen nur „hier ist Wand". Einzelne
STUFENformen dagegen sind Vorlagen:

    6x4  ......|....##|...##.|...##.    175 Vorkommen,  4 Fuellungen
    6x4  ......|....##|..###.|..##..     87 Vorkommen,  2 Fuellungen
    4x3  ...#|..##|...#                 330 Vorkommen, 13 Fuellungen

Und es sind die Stufen — also gerade das, was die Bloecke aus dem Kachelsatz
nicht kennen: die kennen den geraden Lauf, den diagonalen gibt es nur in den
Karten.

### Was das Modell leistet

**Bei 6x4 haben 56,8 % der Formen genau EINE Fuellung, 82,6 % hoechstens
drei.** Die Form gibt die Kacheln also meist vor. Bei 2x2 dagegen kennt das
Modell jedes Fenster, schlaegt aber im Mittel 268 Fuellungen vor: es weiss
alles und sagt nichts.

Nachgeschlagen auf cm02 (Fenster fuer Fenster, Fuellung nicht vorgegeben):

| Groesse | Form bekannt | richtige Fuellung dabei | Vorschlaege im Mittel |
|---|---|---|---|
| 6x4 | 78 % | 64 % | 14,8 |
| 4x3 | 98 % | 69 % | 35,1 |
| 3x3 | 99 % | 74 % | 53,8 |
| 2x2 | 100 % | 86 % | 267,7 |

Das ist die Leiter: gross traegt die Richtung, klein stopft die Reste.

### Am Setzer (`klippe_gruppen_setzen`)

Die Leiter: groesste Form zuerst nachschlagen und setzen, dann die
naechstkleinere ueber das, was uebrig bleibt. Was eine grosse Gruppe gesetzt
hat, bindet die kleineren. Eingehaengt dort, wo bisher `klippe_feinsetzen` mit
dem Fuellungsmodell lief — auf den Stufen.

Dieselben Waende, beide Modelle, „falsch mitten" = Bodenkante mit Klippe
dahinter (Originalkarten 0,72 bis 0,89 %):

| Zug | `hoehe` | Fuellungsmodell | **Formmodell** |
|---|---|---|---|
| waagerecht | — | 0,9 % | 0,9 % |
| senkrecht | — | 0,0 % | 0,0 % |
| 2:1 runter | — | 12,9 % | **4,8 %** |
| 2:1 runter | 3 | 5,6 % | **1,2 %** |
| 2:1 hoch | — | 18,1 % | **3,3 %** |
| 2:1 hoch | 3 | 15,7 % | **8,0 %** |
| 1:1 runter | — | 21,6 % | **14,9 %** |
| 1:1 runter | 3 | 6,2 % | **3,0 %** |

Auf jeder Schraegen mindestens halbiert, auf geraden Laeufen unveraendert —
dort setzen die Bloecke, und die Gruppen fassen sie nicht an.

**Der Preis ist die Naht**, sie steigt um etwa eins bis zwei (2:1 runter 22,0 →
23,1, 1:1 runter 22,9 → 24,8). Die Originalkarten liegen bei 24, 24,8 ist also
kein Ausreisser. Regelwidrig bleibt ueberall 0.

### Die Bruecke beim Stutzen — und drei Fehldiagnosen davor

`2:1 hoch` war mit `hoehe=3` schlechter (8,0 %) als ohne (3,3 %). Drei
Vermutungen dazu, alle falsch:

1. **„Die Reihenfolge stimmt nicht, erst stutzen dann Gruppen."** Falsch —
   gestutzt wird bereits vor dem Setzen der Gruppen.
2. **„Das Stutzen reisst Loecher."** Auch falsch. Die vermeintlichen Loecher
   (`....|....|..#.`) sind die Ecke des Bandes, die ins Fenster ragt — gueltige
   Ansichten, die das Modell nur nicht hat, weil ihre Fuellungen seltener als
   zehnmal vorkommen. Das ist die Deckungsgrenze, kein Fehler.
3. **„Unerreichbare Zellen stehenzulassen ist das Problem."** Aenderte keine
   einzige Kennzahl.

Gefunden hat den echten Fehler erst die auf `hoehe` erweiterte
Zusammenhangspruefung: **bei `hoehe=2` auf der 45-Grad-Schraegen zerfaellt die
Wand in zwei Stuecke.** Die verbliebenen Teile beruehren sich nur noch ueber
Eck, und ueber Eck ist keine Wand, sondern eine Luecke. Der Fehler stand seit
dem Bau von `hoehe` drin; die Pruefung lief nur ohne Hoehenangabe und sah ihn
nie.

`klippe_hoehe_begrenzen` holt jetzt gestutzte Zellen zurueck, die zwei Teile
verbinden. Das macht das Band an diesen Stellen um eine Zelle dicker, und die
Bruecken-Zellen sitzen naturgemaess im Inneren: „Uebergaenge mitten in der
Wand" stieg bei `hoehe=2` von 0,7 auf 3,1 %.

**Das ist ein Tausch, kein Versehen.** Eine Wand mit Luecke faellt sofort ins
Auge, eine Uebergangskachel eine Zelle zu weit innen nicht. Ein Versuch, auch
das zu reparieren — „Bodenkante mit Klippe dahinter" als vierter Mangel —
fasste jede Innennaht an und warf sechs Pruefungen zu Ecke und Fortsetzung um;
zurueckgenommen. Die Schwelle der Pruefung steht jetzt bei 4 % mit dieser
Begruendung im Quelltext.

### Stand (03.08.2026)

Modell gebaut, Lader mit Formindex, am Setzer angeschlossen. Die
Zusammenhangspruefung deckt jetzt auch `hoehe` ab — 30 Faelle ueber mud und
san. `cliff_patches` und `klippe_feinsetzen` stehen noch da und werden von
`kacheln_feinsetzen=True` benutzt.

### Offen

### Der `ECKENSCHUTZ` war NICHT der Engpass

Ueber mehrere Abschnitte stand hier, er sei „an drei Stellen der Engpass".
Das war eine Vermutung, die nie geprueft wurde. Nachgemessen ist sie falsch.

Der Grund fuer den Schutz: `klippen_treffer` sucht VOLLSTAENDIG
wiedergefundene Bloecke. Eine geaenderte Kachel, und der Block ist weg, also
darf an den gezeichneten Ecken nichts angefasst werden.

Gebraucht wird aber kein Block. Achse, Seite und Hochkante stehen im Feld, und
`klippe_wand_aus_feld` liest sie dort — die Funktion stand seit langem da und
wurde von nichts benutzt. Sie ist jetzt als **Rueckfall** eingehaengt: findet
`klippen_treffer` keinen Anker, wird die Hochkante aus dem Feld gelesen und die
Flucht daran ausgerichtet. Nur bei gleicher Achse — eine Querwand ist keine
Fortsetzung, und an ihr auszurichten verdrehte prompt zwei Eckpruefungen.

Damit haelt die Fortsetzung bis Radius 3 statt 7. **Die Qualitaet wird dabei
aber nicht besser** („Uebergaenge mitten in der Wand", Originalkarten 0,72 bis
0,89 %):

| Zug | `hoehe` | Radius 7 | Radius 3 |
|---|---|---|---|
| 2:1 runter | — | 4,8 % | 9,1 % |
| 2:1 runter | 3 | **1,2 %** | 3,9 % |
| 2:1 hoch | — | 3,3 % | 2,8 % |
| 2:1 hoch | 3 | 8,0 % | 7,4 % |
| 1:1 runter | — | 14,9 % | 13,0 % |
| 1:1 runter | 3 | 3,0 % | 3,1 % |

An zwei von drei Zuegen wird es schlechter. Der Schutz haelt an den Ecken
Blockkacheln fest, die dort zufaellig richtig sind; wer ihn verkleinert, laesst
die Reparaturen ran, und die koennen „Bodenkante mit Klippe dahinter" nicht
beheben — der einzige Mangel, der bis heute nur gemessen und nie repariert
wird.

Der Schutz bleibt also bei 7, jetzt mit der Messung im Quelltext statt mit
einer Vermutung. Der Rueckfall bleibt ebenfalls: er macht die Fortsetzung
unabhaengig davon, ob ein Block ueberlebt hat, und das ist unabhaengig vom
Radius ein Gewinn.

### Die Reparatur fuer „Bodenkante mit Klippe dahinter"

Der Spiegelfall zu `klippe_raender_setzen`: dort darf eine Seite, hinter der
offener Boden liegt, keinen Fels zeigen; hier darf eine Seite, hinter der
KLIPPE steht, keinen Boden zeigen. Sonst steht eine Uebergangskachel mitten in
der Wand statt an ihrem Rand. Das ist die Zahl, an der diese ganze Reihe misst
— und sie wurde bis hierher nur gemessen, nie behoben.

**Ein eigener Durchgang, nicht ein vierter Begriff.** Der erste Versuch haengte
das Mass in `klippe_regeln_durchsetzen` ein; damit aenderte es die Rangfolge
fuer JEDE besuchte Zelle statt nur fuer die schadhaften, und sechs Pruefungen
zu Ecke, Abschluss und Fortsetzung fielen um. `klippe_innenkanten_bessern`
besucht nur die Zellen, die den Mangel tragen — auf einer Wand von 154 Zellen
sind das etwa 12 — und ersetzt nur bei strikter Verbesserung, nie um den Preis
eines regelwidrigen Paares, eines harten Uebergangs oder eines Lochs.

| Zug | `hoehe` | vorher | nachher |
|---|---|---|---|
| waagerecht | — | 0,9 % | 0,9 % |
| senkrecht | — | 0,0 % | 0,0 % |
| 2:1 runter | — | 4,8 % | **2,0 %** |
| 2:1 runter | 3 | 1,2 % | **0,6 %** |
| 2:1 hoch | — | 3,3 % | **1,9 %** |
| 2:1 hoch | 3 | **8,0 %** | **2,6 %** |
| 1:1 runter | — | **14,9 %** | **3,5 %** |
| 1:1 runter | 3 | 3,0 % | **2,2 %** |

Originalkarten: 0,72 bis 0,89 %. Vorher lag der Setzer beim 4- bis 17-fachen,
jetzt beim 2- bis 4-fachen.

`INNEN_ECKENSCHUTZ = 3` ist der kleinste Radius, bei dem die Suite haelt: bei 0
fallen sechs Pruefungen, bei 2 noch zwei. Die Reparatur fasst Zellen mitten in
der Wand an, also dort, wo die Bloecke ihren Kern haben.

san und sno sind noch nicht von Hand zugeordnet — dort aendert der Einbau
nichts, `kennt()` sagt Nein und wer nichts weiss, darf nichts verbieten. `san
schraeg 1:1` findet der Loeser weiterhin nicht (16 s Zeitgrenze, faellt auf die
Bloecke mit 35 % zurueck); das ist der naechste echte Fehler. Ausserdem: der
zweite Klippenweg (`klippen_laeufer`) hat nichts davon, und `loesen=False` in
`klippe_aus_linie` steht weiterhin auf aus — der Loeser laeuft also nur, wo er
ausdruecklich gerufen wird.

## 14. Zehn cm02-Klippen exakt nachbauen — und eigene entwerfen

Die Messlatte: gegeben ist die Klippenmaske, gesucht sind die Kacheln. Wer das
kann, hat die Gruppen beisammen.

### Was den Nachbau getragen hat

| Schritt | cm02 genau | ganz |
|---|---|---|
| Ausgangsmodell (6x4 bis 2x2, ab 10x) | 27,8 % | 1/10 |
| **Bestfit statt zeilenweise** | 41,1 % | 1/10 |
| grosse Formen dazu (10x8, 14x10) | 99,4 % | 8/10 |
| **echte Fenstermaske statt Bauteil** | 99,4 % | 8/10 |
| 20x14 und 14x20 dazu | **100 %** | **10/10** |

Ueberbleibsel: **0** in allen Faellen ab Bestfit.

Drei Erkenntnisse, jede gegen eine Vermutung von mir:

**Bestfit statt zeilenweise.** Zeilenweise legt der erste Treffer oben links
alles Folgende fest. Wer zuerst dort setzt, wo am meisten Unbelegtes haengt,
gewinnt 13 Prozentpunkte — ohne eine einzige neue Gruppe.

**Nicht wuerfeln half NICHT.** Die haeufigste Fuellung statt einer gewuerfelten
zu nehmen brachte 27,8 auf 28,3 % — nichts. Die Wahl war nie das Problem.

**Abstimmen machte es schlechter.** Jede Zelle von allen passenden Gruppen
waehlen zu lassen fiel von 99,5 auf 87,1 %: die Mehrheit ueberschreibt richtige,
aber seltenere Kacheln.

**Und ein Fehler in meiner Messung**, nicht im Modell: der Ausschnitt enthielt
nur die eine Zusammenhangskomponente. In der Karte stehen im selben Fenster
weitere Klippenzellen, und genau die haben die Gruppen beim Lernen gesehen.

### Die ehrliche Zahl

| | cm02 genau | ganz |
|---|---|---|
| mit cm02 gelernt | 100 % | 10/10 |
| **OHNE cm02 gelernt** | **70,5 %** | **0/10** |

Das 10/10 ist zum Teil Auswendiglernen — bei Schwelle 1 und 20x14-Fenstern
steht cm02 selbst im Vorrat. Bewiesen ist damit die Maschinerie (Formindex,
Bestfit, Groessenleiter, null Ueberbleibsel), nicht die Verallgemeinerung.

### Eigene Entwuerfe

Sieben Formen, die in keiner Originalkarte stehen: Bogen, S-Kurve, Halbinsel,
zwei Treppen, Zacken, langer Lauf.

**Hier ist der kleinere Vorrat besser.** Schwelle 3 (248556 Gruppen) schlaegt
Schwelle 1 (2294222) fast ueberall — beim langen Lauf 0/0/0/0 gegen 2/9/4/0.
Die seltenen Gruppen sind ueberangepasst: sie helfen beim Nachbauen der Karte,
aus der sie stammen, und schaden bei allem anderen.

Nach den Reparaturen (Raender, Innenkanten, Regeln):

| | roh | fertig | Originalkarten |
|---|---|---|---|
| hart | 2,01 % | **0,00 %** | 0,47 % |
| innen | 1,54 % | **0,20 %** | 0,72–0,89 % |
| Loch | 2 | **0** | 0,46 % |
| regelwidrig | 32 | **0** | — |

Sechs der sieben Entwuerfe sind vollstaendig mangelfrei; nur „Zacken" behaelt
3 Innenkanten (2,3 %). **Auf jeder Kennzahl besser als die Originalkarten.**

## 15. Die Flaeche einer Kachel, und was daran Regel ist

Aus den Kachelbildern laesst sich die Fels-Boden-Flaeche berechnen: je Pixel der
Abstand zur Grundkachel der Familie, dann geglaettet. Das ist dieselbe Aussage
wie die Kantenzuordnung, nur in 32x32 statt in vier Seiten mal vier
Abschnitten.

**Stand: 95,2 % Deckung mit der Handzuordnung, 10,6 % Streit an den Naehten.**
Die Handzuordnung liegt bei 0,15 % — die Flaeche ersetzt sie nicht, aber sie
zeigt, wo man hinsehen muss.

### Was gemessen wurde und nicht half

**Der Farbabstand liess sich nicht nach unten anpassen.** Zwischen 1 und 8 hat
er keine Wirkung: 62 % der Pixel liegen bei Abstand genau 0, der Rest bei 6 oder
mehr. Dazwischen liegt kein einziges Pixel.

**Die Durchschnittshelligkeit taugt nicht als Gegenprobe.** Sie sagt den
Felsanteil einer Kachel mit Korrelation -0,99 voraus — und genau deshalb kann
sie nichts bestaetigen: beide kommen aus denselben Pixeln. Der erste Anlauf
mass sogar verkehrt herum (auffaellige Kacheln hatten die BESSERE Deckung),
weil die Gerade an der rohen Karte angepasst und daran die geglaettete Flaeche
gemessen wurde.

**Die Sprungmessung an zusammengelegten Kacheln ist gestrichen.** Viermal
nachgebessert, viermal fand sie dieselben Faelle, in denen die Frage nicht
gilt: volle Felskacheln haben keine Fels-Boden-Grenze, und wer dort eine sucht,
findet Textur. 30 der 38 beteiligten Kachelplaetze waren „voll", ihre Flaechen
durchweg richtig.

### Was half

**Der Mehrheitsfilter statt des Farbabstands.** 5x5 ab 6 von 25 (nicht ab 13 —
an einer Kante ist ein Pixel nur halb von Fels umgeben, wer die Mehrheit
verlangt, frisst die Kontur).

**Das Scannen** (Idee des Nutzers): Linien durch die Kachel ziehen und die
Wechsel zaehlen. Es trennt die Rollen — bei „oben+unten" haben 53 % der
senkrechten Linien zwei Wechsel, bei den Kanten 7 %. Damit stieg diese Gruppe
von 84,6 auf 93,4 %.

**Die LAGE der Uebergaenge statt ihrer Zahl.** Die Spanne — von wo bis wo die
Linien mit Wechsel reichen — trennt Kante von Ecke sauber (Median 100 % gegen
75 %), wo die Wechselzahl ueberlappte.

**Die Nahtprobe gegen die Originalkarten.** Die einzige Gegenprobe, die wirklich
trennt: Kacheln mit wenig Nahtstreit haben 98,3 % Deckung, die mit viel 88,7 %.
Sie funktioniert, weil die Karten etwas wissen, das in keinem Pixel steht —
welche Kacheln tatsaechlich aneinanderliegen.

### Die Regeln, und wo sie gelten

    Fels    genau EIN Bereich, und er beruehrt den Rand
    Boden   JEDER Bereich beruehrt den Rand

Erst hiess die zweite „hoechstens ZWEI Bodenbereiche". Auf einer einzelnen
Kachel stimmt das; im 2x2-Verbund aus den Originalkarten faellt es durch —
`130` mit fuenf und `199` mit sieben Bodenbereichen stehen 386 und 308 mal in
den Karten. Neu gefasst besteht der Verbund vollstaendig: 24 von 24 statt 18.

**Auf der KARTE gilt die Bodenregel nicht.** cm02 hat fuenf eingeschlossene
Bodenbereiche, der groesste mit 83 Zellen — ein Hochplateau. Die Regel gehoert
in die Kachel, nicht in den Setzer.

### Was daraus in den Setzer ging

Nur eines, und es kam aus der Messung nebenbei: **ein V-foermiger Zug zerfiel
bei `hoehe=2` in zwei Stuecke** (84 und 10 Zellen). Die Bruecke in
`klippe_hoehe_begrenzen` schloss nur Luecken von genau einer Zelle; bei
breiteren setzt sie jetzt schrittweise eine Zelle in Richtung des anderen
Teils. Alle 27 geprueften Zuege haengen danach zusammen, und der V-Fall steht
in der Suite.

### Stand (03.08.2026)

Die Flaechenberechnung liegt vollstaendig im Scratchpad und haengt an nichts.
Was sie fuer san leisten koennte: eine Vorbelegung, die bei drei von vier
Kacheln stimmt, plus eine Liste von 15 Kacheln zum Nachsehen — statt 138 von
Hand durchzugehen. Die Ecken sind dabei die schwache Gruppe: acht der zwoelf
auffaelligsten Kacheln sind welche.

## 16. Der algorithmische Setzer im Editor

Der Blockweg legt fertige Bloecke an die Kante und bessert hinterher nach.
`mapview/klippe_algo.py` dreht das um: er fragt nicht, welche Kachel auf welche
folgen darf, sondern was das GELAENDE an dieser Stelle verlangt.

    1. Das Gelaende wird viermal feiner beschrieben als das Kachelraster --
       eine Kachel hat vier Abschnitte je Seite, also 4x4 Teilfelder.
    2. Je Kachel wird an ihren vier Raendern abgelesen, was dort stehen muss:
       16 Abschnitte, jeder Fels oder Biom.
    3. Gesetzt wird die Kachel, deren Handzuordnung genau das zeigt.

Damit ist ein harter Uebergang nicht mehr zu reparieren, sondern ausgeschlossen:
eine Kachel, die Fels ins Biom zeigt, erfuellt die Abfrage nicht.

### Was der Kachelsatz nicht hergibt

Auf Seitenebene (jede Seite ganz Fels oder ganz Biom) haben **4 der 16 Faelle
keine einzige Kachel**: 5 und 10 (eine Zelle breite Wand), 8, und **11 --
Klippe oben, Boden unten**, also die Unterkante. Und das Seitenraster wirft 100
der 156 mud-Kacheln weg, weil ihre Seiten halb Fels und halb Biom sind. Darum
laeuft der Setzer auf ABSCHNITTS-Ebene, nicht auf Seitenebene.

### Vier Gelaenderegeln, jede aus einer Messung

**Beim Zusammenstoss gehoert die Randlinie dem Biom.** Ohne sie: hart 114. Der
Uebergang braucht Platz INNERHALB der Kachel. Auf einer Schraege wandert die
Grenze durch alle Zwischenlagen und trifft die Kachelkante regelmaessig --
dort sassen die letzten 13 harten Stellen, alle auf N- und S-Seiten.

**Zwei benachbarte Klippenzellen teilen an ihrer Naht Fels.** Das Loch galt mir
als unmoeglich -- zu Unrecht. Eine Naht hat zwei Seiten, und das sind
verschiedene Teilfelder; beide koennen Biom sein, waehrend beide Zellen
anderswo Fels tragen. Gemessen: auf einer senkrechten Wand genau eine Stelle.

**Gelaende an den Kachelsatz angleichen.** Wo keine Kachel den verlangten Rand
zeigt, wird nicht die Regel gelockert, sondern das Gelaende berichtigt.

**Die drei muessen ABWECHSELND laufen.** Die Berichtigung kann eine duenne
Randzelle ganz leeren; danach steht die Nachbarzelle mit Fels an einer Naht,
hinter der nun Biom liegt. Ohne den Wechsel blieb auf einer 2:1-Schraege genau
eine harte Stelle.

### Gegen die Treppe

"Es sind Treppen" wurde erst messbar, als klar war, was das heisst: die
Originalkarten setzen **zu 99 % keine zwei gleichen Kacheln nebeneinander**
(Lauflaenge 1,01, laengster Lauf 3). Die gerade Wand hatte einen Lauf ueber
**51 Zellen** und 48 % Fuellkacheln gegen 16,4 % in den Originalen.

    Hoehe schwankt    Ober- und Unterkante haben je einen eigenen langsamen
                      Verlauf (2,5 bis 4,5), damit sie nicht gemeinsam springen
    Fuellregel        bei Hoehe 2 null bis eine Fuellkachel, bei Hoehe 3 eine
                      bis zwei, ab Hoehe 4 weiter eins bis zwei. Ueberzaehlige
                      Vollzellen bekommen eine Ecke Boden gekerbt und fragen
                      damit nach den 36 Kacheln mit winziger Eckschraege
    keine Wiederholung bei praktisch gleicher Naht (Spielraum 3) gewinnt die
                      Kachel, die sich vom Nachbarn unterscheidet

Der Deckel bei zwei ist gemessen: "h-2 bis h-1" weitergeschrieben erlaubte bei
Hoehe 4 schon zwei bis drei und trieb den Fuellanteil auf 28,6 %.

### Stand gegen die Originale

                          eigene Waende        Originalkarten
    hart                  0                    --
    Loch                  0                    --
    Lauflaenge            1,00 bis 1,04        1,01
    Wandhoehe             3,54 bis 3,63        3,54
    Fuellanteil           21 bis 33 %          16,4 %
    kleine Eckschraege    10 bis 22 %          22,8 %
    regelwidrige Paare    0,9 bis 5,1 %        0,0 %
    Naht                  20,8 bis 22,0        18,4

Die Naht war zuvor bei 27 bis 31. Sie wurde zum Auswahlkriterium unter den
Kacheln, die das Gelaende ohnehin erlauben -- **regelwidrig fiel dabei um zwei
Drittel**, und das ist die eigentliche Bestaetigung: der Setzer kennt die
Paartabelle nicht, sie ist also eine unabhaengige Auskunft.

Die frueher genannten 24 als Zielwert waren falsch. Mit demselben Code
nachgemessen liegen die Originale bei 18,4 (Median 17,3); aufgeteilt: voll/voll
23,9, gemischt 20,1, Uebergang/Uebergang 17,1.

### Grenzen

Der laengste Lauf von 8 auf einer geraden Wand bleibt: dort hat **jede Zelle
genau eine passende Kachel**. Das ist eine Grenze des Kachelsatzes.

`verfuegbar()` traegt vorerst nur `mud` -- san und sno haben keine
Handzuordnung. Der Editor faellt dort still auf den Blockweg zurueck; der
Schalter "Gelaende statt Bloecke" im Gelaendefeld stellt beides um.

### Falle bei der Hochseite

"oben" und "unten" sind bildschirmfest, "links" und "rechts" beziehen sich auf
die ZEICHENRICHTUNG. Nach unten gezeichnet liegt links im Osten. Wer das
gleichsetzt, baut die Wand auf der falschen Seite -- genau das tat der erste
Einbau, und es fiel erst am Einrasttest der Oberflaeche auf, nicht an den
Klippenpruefungen.

### Stand (05.08.2026)

`mapview/klippe_algo.py`, angeschlossen in `paint_layers._klippe_belegen`,
Schalter in `terrain_panel`. `check_klippe_algo` in der mapgen-Suite prueft
hart und Loch auf vier Zuegen, dass die Pruefung ohne die Randregel durchfaellt,
und dass san und sno sich sauber verweigern. Alle drei Suiten gruen.

## 17. san und sno: was messbar war, und was nicht

Der algorithmische Setzer braucht die Handzuordnung der Kachelraender. mud hat
sie (156 Kacheln), san und sno nicht. Der Versuch, sie fuer beide aus der
gemessenen Felsflaeche ABZULEITEN, ist an einer klaren Zahl gescheitert -- und
das Scheitern ist das Ergebnis dieses Abschnitts.

### sno kann gar nicht

    222 sno-Kacheln, davon platzierbar          0
    sno-Zellen in allen 54 Karten          11 225
    davon "Huegel/Eis/Vulkan (unpassierbar)" 11 161  (99,4 %)
    davon Klippenzellen                        63
    sno-Klippenkacheln im Pixelmodell           9

**sno ist kein Biom, sondern unpassierbares Eis.** Es gibt keinen sno-Boden,
in dem eine Klippe stehen koennte, und darum auch keine Bodenkachel als
Vergleich -- die mitgelieferte Vorbelegung setzt fuer sno mangels Vergleich
schlicht alles auf Fels. Mit neun Kacheln laege sno ausserdem weit unter den
40, die `klippe_algo.MINDEST_KACHELN` verlangt; die Abfrage nach einem genauen
16-Abschnitte-Rand fande fast nie einen Treffer. Fuer sno bleibt der Blockweg
zustaendig, und das ist kein Provisorium.

### san: abgeleitet reicht nicht

Gemessen an mud, wo die Handzuordnung als Wahrheit danebenliegt, streng
gezaehlt (EGAL gilt NICHT als Treffer):

                                       Abschnitte  Kacheln ganz richtig
    Vorbelegung im Pixelmodell            92,9 %          38,5 %
    Ableitung ueber die ganze Flaeche     95,9 %          67,3 %

Die Ableitung ist also deutlich besser als die mitgelieferte Vorbelegung --
89 statt 153 falsche Abschnitte. Aber sie ist keine Handqualitaet. Die
unabhaengige Probe an den Originalkarten, die keine der Einstellungen je
gesehen hat: zwei Kacheln, die dort aneinanderstossen, muessen sich an ihrer
gemeinsamen Naht einig sein.

                          Nahtstreit    hart      Loch
    mud, Handzuordnung        0,08 %   1,58 %    0,56 %
    mud, abgeleitet           8,77 %   7,99 %    1,29 %
    san, abgeleitet           7,80 %  20,01 %    0,37 %

Rund einer von zwoelf Nahtabschnitten widerspricht sich selbst -- was zu den
4 % falschen Abschnitten passt, denn an einer Naht treffen zwei davon
aufeinander. Die Handzuordnung ist deshalb so einig, weil sie MIT der
Nahtprobe gebaut wurde.

### Drei Versuche, es besser zu machen -- alle gemessen gescheitert

**Breitere Bodenpalette** (bis zu 24 Bodenkacheln statt einer): schlechter,
64,7 % gegen 67,3 % ganz richtige Kacheln. Mehr Bodenfarben fressen die
Felsflaeche an.

**Nachbarn abstimmen lassen** -- wer von seinen Nachbarn geschlossen
ueberstimmt wird, dreht sich um. Sah zunaechst nach einem Sprung auf 82 % aus;
streng nachgemessen war das die EGAL-Aufblaehung: 470 Abschnitte wurden auf
EGAL gesetzt, und meine Auswertung liess das als Treffer durchgehen. Wirklich
gemessen sinken die falschen Abschnitte von 89 auf 52, dafuer werden 181
aufgegeben -- fehlerfreie Kacheln fallen von 67,3 % auf 25,0 %.

**Verdachtsrangliste**, damit man nur die zweifelhaften Kacheln nachsieht:
1,38x gegen Zufall bei den ersten zwanzig, danach praktisch 1,0x. Auch die
Liste der Kacheln mit Nahtstreit taugt nicht als Auswahl -- sie trifft bei mud
94 % der Kacheln, wo die Zuordnung nachweislich stimmt.

**Damit gibt es keinen belastbaren Weg, die falschen san-Kacheln zu benennen.**
Wer sie sucht, muss alle 138 ansehen.

### Was eingebaut wurde

In `cliff_kanten.json` steht fuer san (138) und sno (9) jetzt die abgeleitete
Vorbelegung statt der schwaecheren aus dem Pixelmodell -- 91 Eintraege haben
sich geaendert, mud ist unberuehrt. `bearbeitet` bleibt bei 156: der Lader gibt
die ungeprueften Werte NICHT heraus, `verfuegbar()` sagt fuer san und sno
weiter nein, und der Editor bleibt dort beim Blockweg.

Der Nutzen ist der Startpunkt des Handwerkzeugs: es liest `kanten` und beginnt
damit bei rund 96 % statt bei 93 %. Freigegeben wird eine Kachel dort, wo sie
angesehen wurde -- das Werkzeug traegt sie beim Durchsehen selbst in
`bearbeitet` ein.

Sicherung der vorherigen Datei: `cliff_kanten.json.vor_vorbelegung`.

### Stand (05.08.2026)

san wartet auf einen Handdurchgang ueber 138 Kacheln. sno ist erledigt: dort
gibt es nichts zuzuordnen.

## 18. Der Landschaftsmodus des Generators (11.08.2026)

Der Generator hat einen dritten Klippenaufrufer: `_klippen_aus_linien`
(mapgen.py) laeuft die Konturen des Hoehenfelds ab und zeichnet sie mit
`klippe_aus_linie` -- derselbe Blockweg wie der Pinsel, mit allen Reparaturen.
Nur im Landschaftsmodus (`MapGenParams.landschaft`, Vorlage "newterra");
die uebrigen Vorlagen benutzen weiter `_male_klippen`.

Was dabei gemessen wurde:

- **Konturen muessen rechtwinklig sein.** Das Hoehenfeld wird auf ein
  FUENFERraster begradigt (senkrechter mud-Laufblock = 5 hoch) und die
  Vereinfachung (`_kontur_vereinfachen`, eps 1,0) behaelt jede Ecke. Freie
  Schraegen (eps 2,9) zerfielen als haarfeine Nordkanten-Treppen sichtbar in
  Stummel; Viererraster ohne Glaettung zerfiel in Haken (8 Segmente der
  Laengen 3-7 auf einem 37-Zellen-Bogen).
- **Ein Biom je Wand** (`_landschaft_familien`): jede Hochlandkomponente samt
  4er-Saum bekommt die Mehrheitsfamilie ihres Umfelds, BEVOR die Uebergaenge
  gemischt werden -- der bekannte Fehler "Wand ueber Biomgrenze = 118 harte
  Kanten" (Abschnitt 12) wird so umgangen statt repariert. Ergebnis ueber
  sechs Seeds: null harte Bodenkanten, null isolierte Klippenzellen.
- **Rampen als Luecken im Zug** (`_kontur_boegen`): bevorzugt auf waagerechten
  Laeufen, weil nur dort Abschlussstuecke existieren. Am Kartenrand wird keine
  Wand gezeichnet -- das Hochland laeuft dort aus dem Bild.
- **san-Mesas bleiben die schwache Stelle**: ohne Kantenzuordnung keine
  Reparaturen (Abschnitt 17), die Ringe wirken offener als mud-Waende.

Pruefungen: `check_landschaft` in `mapview/tests/mapgen_test.py`
(Determinismus, Klippenanteil als ANTEIL, Isolation, harte Kanten,
Kachelflut-Deckel 10 %, Flussbett, Verbundenheit).

## 19. Der Gelaende-Loeser: suchen statt setzen

Der Setzer aus Abschnitt 16 waehlt je Zelle eine Kachel, die das Gelaende
erfuellt -- ob zwei Nachbarn zueinander passen, ist dort keine Bedingung. Der
Blockloeser `mapgen.klippe_loesen` wiederum sucht passende Paare, kennt aber
das Gelaende nicht. `klippe_algo.loesen` verbindet beides.

### Was der gierige Setzer wirklich liefert

Auf 45 Waenden (neun Zuege, fuenf Saaten) ueber `klippe_aus_linie` gemessen:

    regelwidrig (weder belegt noch erlaubt)    6,5 %
    unbelegt (in keiner der 54 Karten)          41,9 %
    Loch                                        3

Das sind die Kacheln, die "nicht zueinander passen". Die 0,9 bis 5,1 % aus
Abschnitt 16 waren zu optimistisch.

### Warum der erste Loeser NICHTS fand

Mit dem Gelaende als harter Bedingung war jede der neun Waende unloesbar --
erschoepfend durchsucht in Millisekunden. Der Grund: `verlangt` liest den Rand
einer Kachel aus ihrem EIGENEN aeussersten Teilfeld. Links und rechts einer
Naht sind das zwei verschiedene Spalten, und an **23 bis 29 % der Naehte**
weichen sie ab. Das Gelaende verlangt dann von zwei Nachbarn Raender, die
nicht zusammenpassen.

### Was half (alles gemessen)

| Schritt | geloest | unbelegt |
|---|---|---|
| Gelaende hart, wie es ist | 0/27 | -- |
| `naht_teilen` (Fels, wo eine Seite Fels hat) | 12/27 | 8,5 % |
| dasselbe mit Boden statt Fels | 0/9 | -- |
| Berichtigung schreibt beide Nahtseiten | schlechter (4/9) | -- |
| **Abweichung vom Gelaende 0 bis 4 Abschnitte, stufenweise** | **27/27** | 15 % |
| **zuerst nur belegte Paare, Abweichung 4** | 23/27 | **0 %** |

Hart bleiben dabei drei Dinge: **kein Fels zum offenen Boden** (hart = 0),
**kein Loch** (`ke.loch` als Paarverbot -- ohne das stiegen die Loecher mit
der Abweichung auf 12 bis 29), und **jedes Paar belegt oder erlaubt**. Das
Gelaende ist nur noch Vorlage: Abweichungen kosten, verbieten aber nichts.

### Stand gegen vorher (45 Waende, `klippe_aus_linie`)

                    bisher    Loeser    Originalkarten
    regelwidrig     6,5 %     0 %       0 %
    unbelegt        41,9 %    1,6 %     --
    hart            0         0         --
    Loch            3         0         --
    gleiche Nachbarn 2,0 %    2,2 %     ~1 %
    Naht            22,9      23,9      18,4
    Zeit je Wand    0,13 s    0,25 s (max 1,7 s)

Die Naht ist leicht schlechter: der Loeser ordnet erst nach Gelaende und
Beleg, dann nach Naht. Das ist der naechste Hebel.

### Wo es steht

`klippe_algo.loesen`, `loesen_stufenweise`, `naht_teilen`,
`gelaende_angleichen`; Schalter `LOESER` (an), Stufen in `LOESER_STUFEN`.
Findet keine Stufe etwas, faellt `klippe_aus_linie` auf `setzen` mit dem
ungeteilten Gelaende zurueck. In der mapgen-Suite: "Loeser ohne regelwidrige
Paare" auf vier Zuegen, mit Gegenprobe ohne Loeser (14 Paare).

### Offen

- **Im Spiel ansehen.** Alle Zahlen sind gegen die Tabellen gemessen, kein
  Bild ist angesehen.
- Naht als Teil der Ordnung frueher gewichten.
- san und sno: weiterhin ohne Handzuordnung, also ohne `vorrat`.

### Nachtrag: das Innere der Kachel (28.10.2026)

Im Bild fiel am Knick eine Treppe auf, obwohl jede Kachel am Rand stimmte.
Grund: die Handzuordnung beschreibt nur die RAENDER. Eine Kachel mit
waagerechtem Felsband erfuellt dieselben Raender wie eine mit schraegem --
erst recht mit `egal`-Abschnitten und der Abweichung 4 aus der ersten Stufe,
die bei 22 von 27 Waenden greift.

`innenbilder()` liest je Kachel ihr Inneres als 4x4 aus den Pixeln
(Helligkeit unter 80 = Fels; gegen die Handzuordnung der Raender 93 %
Uebereinstimmung). Der Loeser ordnet danach: erst Abweichung am Rand, dann
Abweichung innen, dann Beleg.

    Innenabweichung je Kachel (von 16)    gierig 1,68   Loeser 1,71   + innen 0,98
    regelwidrig                            6,5 %         0 %           0 %
    unbelegt                               41,7 %        2,6 %         2,5 %
    Naht                                   22,8          23,8          25,0

Die Naht wird dabei etwas schlechter; im Bild ist der Knick dafuer glatt.

### Nachtrag: Wiederholung und Wanddicke (28.10.2026)

**Wiederholung.** Der Loeser prueft jetzt auch die Kachel ZWEI Zellen weiter
(A-B-A-B) und stellt Wiederholung direkt hinter die Randabweichung
(`wdh_stufe=1`). Gleiche Kachel im Abstand 2: 8,8 % -> 1,2 % (cm02 0,8 %),
direkter Nachbar 5,5 % -> 1,5 % (cm02 3,9 %). Innenabweichung 0,97 -> 1,07.

**Wanddicke.** Gegen cm02 nachgerendert: die Originale sind ein duennes
Felsband, das sich diagonal durch die Kacheln schlaengelt. Vollfels-Kacheln:
cm02 6,7 %, bisher 43 %. Das dicke Band war die eigentliche Quelle der
Treppen. `HOEHE_MIN/MAX` jetzt 1,5/2,5 (Tabelle am Wert). Zellen je Spalte
3,0 -- wie cm02 in jeder Richtung (gemessen nach Wandwinkel, 2 bis 4).

### Offen (nach Ansicht im Bild)

- Restliche Treppenabsaetze auf 2:1-Schraegen.
- Wandenden: oft ein dicker Klumpen.
- Waagerecht wiederholt sich ein "Buckel"-Motiv, obwohl die Kacheln
  verschieden sind -- vermutlich optisch aehnliche Kacheln.
- Vollfels noch 21 % gegen 6,7 %.

### Nachtrag: Klippen, die nach Norden fallen (28.10.2026)

In cm02 ist eine nordwaerts fallende Klippe keine Wand, sondern eine
Abbruchkante von EINER Zelle (Zelltyp N; Spaltenmuster "N" 162x, "NN" 77x,
gegen "HLL" 184x und "HHLL" 77x bei der Suedwand). Die N-Kacheln (19 im
mud-Vorrat, 389 Vorkommen in cm02) tragen innen eine einzige Felslinie in
der zweiten Teilfeldzeile. Bisher wurde die Nordwand genauso dick gebaut
wie die Suedwand.

- `band_aus_linie`: faellt die Wand nach Norden (`art == "v"`, `ri < 0`),
  ist das Felsband `NORD_MIN`..`NORD_MAX` = 0,25..0,5 Kacheln dick.
- `_nordlinie_durchziehen`: die Linie wird je Teilfeldspalte von der
  Zellgrenze ins Zellinnere geschoben und bei Reihenwechsel senkrecht
  verbunden. Auf der Grenze hatte `rand_dem_biom` sie halb geloescht (274 ->
  134 Teilfelder), und es gab keine Kacheln fuer "Fels nur am Rand".
- `LOESER_STUFEN` um Abweichung 5 und 6 erweitert: die waagerechte Nordkante
  loest erst ab 4 bis 5.

Neue Testzuege im Bildvergleich: 2:1 schraeg/fallend, Knick und 1:1 jeweils
mit `hoch_seite="unten"`. Alle 13 ohne unpassende Paare, ohne Loch.
Die Pruefung im Spiel steht weiter aus -- insbesondere, ob die Zelltypen
der Nordkante als N gesetzt werden (`celltypes.default_cell_type`).

### Nachtrag: Wandenden (28.10.2026)

In cm02 laufen Waende ueber zwei bis drei Kacheln spitz oder rund zu; bei
uns waren sie bis zum letzten Punkt voll dick (Klumpen). `band_aus_linie`
verjuengt die Dicke jetzt zu beiden Enden des Zuges (`ENDE_LAENGE` 3,5
Kacheln, `ENDE_REST` 0, Wurzelverlauf). Abschaltbar mit `enden=False`.
Die Nordkante bleibt unverjuengt -- verjuengt zerfiel sie, und 2:1 Nord war
bis Abweichung 8 unloesbar. Alle 39 Pruefwaende sauber.

### Nachtrag: Fels laut Bild zum offenen Boden (28.10.2026)

Am Ende einer waagerechten Wand stand eine Kachel mit Fels unten rechts,
darunter nichts -- im Bild fehlte sichtbar eine Kachel. Die Handzuordnung
hatte die Seite `egal`, die harte Regel ("kein FELS zum Boden") griff darum
nicht. Jetzt zaehlt der Loeser zusaetzlich, an wie vielen offenen Seiten das
Bild (`innenbilder`, ab `OFFEN_FELS_MAX` = 2 von 4 Teilfeldern) Fels zeigt,
und stellt das als ERSTE Vorliebe vor alles andere.

    als Verbot     17 von 39 Pruefwaenden unloesbar -> verworfen
    als Vorliebe   offene Seiten mit Bild-Fels 364 -> 102 (39 Waende, 3 Saaten)
                   je Saat 2,8 % der offenen Seiten; cm02 hat 16,0 %
    weiterhin      0 unpassende Paare, 0 Loch, 0 hart

## 20. san ohne Handzuordnung: die automatische Kantenzuordnung (28.10.2026)

**Vorweg: Abschnitt 17 kam zum selben Schluss.** Die abgeleitete Zuordnung
erreicht keine Handqualitaet (dort 8,8 % Selbstwiderspruch an den Naehten,
hier 6,2 % Widersprueche gegen die Karten). Neu ist nur, dass der
Gelaende-Loeser damit trotzdem saubere Waende baut: er nimmt zuerst Paare, die
in den Karten belegt sind, und die Zuordnung entscheidet nur den Rest. Die
Schwaeche der Zuordnung bleibt -- wer san auf Handqualitaet will, braucht
weiter das Handwerkzeug.

`mapview/cliff_kanten_auto.py` leitet fuer jede nicht von Hand bearbeitete
Kachel die vier Abschnitte je Seite ab -- aus den Kachelbildern und der
Paartabelle, beide im Repo. Ergebnis: `cliff_kanten_auto.json`, neu erzeugt
mit `python mapview/cliff_kanten_auto.py`.

    Pixel       Fels/Boden je Pixel (zwei Farbzentren je Familie, k-means
                auf geglaetteten Pixeln; Boden = heller), je Abschnitt die
                Mehrheit der aeussersten zwei Pixelreihen
    Mehrheit    Abschnitt uebernimmt, was die Partner in den Karten zu
                >= 80 % verlangen
    zerrissen   verlangen die Partner beides (je >= 10 Vorkommen) -> EGAL

### An mud gegen die Handzuordnung gemessen

    Abschnitte wie von Hand            96,8 % (Helligkeit), 96,1 % (k-means)
    Widersprueche gegen die Karten      0,0 %
    nicht belegte Paare: erlaubt, wo die Hand verbietet   16,5 %
                         verbietet, wo die Hand erlaubt   12,7 %

Die automatische Zuordnung ist also nachgiebiger als die Hand: sie setzt
514 Abschnitte auf EGAL, die Hand 341. Versucht, das einzuschraenken (alle
gemessen, alle verworfen):

- strengere Zerriss-Schwelle (20, 40): der Loeser findet seltener eine
  Belegung, faellt auf `setzen` zurueck -- schlechter.
- EGAL nur, wo die Pixel selbst unklar sind: 8 % falsch erlaubt, aber
  33-40 % falsch verboten; 20 von 39 Waenden ohne Loesung.
- Pixelnaht als Schiedsrichter: nimmt falsche Erlaubnisse nur gegen ein
  Vielfaches an richtigen weg.
- laengeres Bleiben bei "nur belegt" (Abweichung bis 8): loest nicht mehr.

Im Bild (mud, Hand gegen automatisch nebeneinander) sind die Suedwaende
praktisch gleich; strittig waren die Treppenuebergaenge der Nordkante.

### san

Helligkeit trennt dort nicht: orangefarbener Sand und rotbrauner Fels sind
fast gleich hell (Mediane 76 gegen 54) -- daher die Farbzentren. Auch
`klippe_algo.innenbilder` nimmt fuer alles ausser mud die Farbzentren.

    san: 138 Kacheln, Widersprueche gegen die Karten 6,2 %
    39 Pruefwaende (13 Zuege, 3 Saaten): kein Rueckfall, 0 Loch, 0 hart,
    unbelegte Paare 47,5 % (mud mit Hand 26,2 %)

sno ist NICHT dabei: 9 Kacheln, 63 Vorkommen in allen Karten, 63,8 %
Widersprueche -- und `MINDEST_KACHELN` = 40 ohnehin unerreichbar.

### Wo sie gilt

Nur im Gelaende-Loeser: `cliff_kanten.modell(auto=True)`. Der Blockweg in
`mapgen` bleibt bei der Hand -- mit der automatischen fielen dort fuenf
san-Pruefungen (Fortsetzung, Eckblock, T-Stoss) und "laesst die belegten
Paare durch" (98,7 %). Der Editor schaltet san ueber `verfuegbar()` von
selbst auf den Gelaende-Weg.

### Offen

- Im Spiel ansehen -- besonders san.
- Wer san doch von Hand nachsehen will: die automatische Zuordnung ist ein
  guter Startwert fuer `kanten_zuordnen.py`.

## 21. Flache Schraegen: Plateau und 45 Grad statt gleichmaessig (28.10.2026)

Mit `maps.vol` vom Nutzer-PC lassen sich jetzt alle 54 Originalkarten mit
echtem Boden rendern. Gesucht: abfallende Suedwaende mit 4 bis 9 Zellen
Hoehenunterschied auf 14 Spalten -- 20 Fundstellen (cm03, cm04, eden03,
mp4_03, mp4_06, mp4_12, mp6_01, ply05, ...).

**Keine einzige laeuft gleichmaessig.** Jede ist eine Folge aus waagerechtem
Plateau und kurzem 45-Grad-Abstieg von zwei bis drei Zellen, dazwischen ein
schmales Band H ueber L. Unser Gelaende legte die Linie gleichmaessig 2:1 --
die Kacheln machten daraus eine Treppe aus Ein-Zellen-Versaetzen.

`_schraege_profil` zerlegt jetzt jedes flache Stueck einer Suedwand
(`art == "v"`, `ri > 0`, Neigung unter 0,9) in Plateaus und 45-Grad-Stuecke:
Stueckzahl = Hoehenunterschied / Zufall(2..3), die Plateaulaengen aus einer
Dirichlet-Verteilung, die Gesamtneigung bleibt genau. Abschaltbar mit
`SCHRAEGE_ZERLEGEN = False`. Nordkanten bleiben unberuehrt.

78 Pruefwaende (mud und san, 13 Zuege, 3 Saaten): kein Rueckfall, 0
unpassend, 0 Loch, 0 hart. Bildvergleich gegen sechs Originale im Chat.

## 22. Zusammengefuehrt: lokaler August-Stand und Gelaende-Loeser (29.10.2026)

Der lokale Stand (Branch `kanten-san`: Commit vom 06.08. plus nicht
committeter Landschaftsmodus vom 08.-11.08.) und der Branch `klippen-loeser`
sind zusammengefuehrt. Uebernommen:

- **Landschaftsmodus** (Abschnitt 18) vollstaendig, samt `check_landschaft`.
- **Befund zu san/sno** (Abschnitt 17) vollstaendig; Abschnitt 20 verweist
  darauf.
- **Die Pruefung "Randkacheln mitten in der Wand"** -- sie zeigte eine echte
  Schwaeche des Loesers (einzelne Waende bis 10,8 %). Behoben durch die neue
  Vorliebe `INNENKANTE` (Tabelle am Wert): mud 1,54 -> 0,30 %, san 1,63 ->
  0,20 %; Originale 1,22 bzw. 0,95 %.

`klippe_algo.py` kommt vom Loeser-Branch. Die lokalen Aenderungen daran
(berechnete Zuordnung `_gerechnet`, `naht_haelt(mindestens)`, Eckenfilter)
sind NICHT uebernommen -- gemessen auf dem zusammengefuehrten Stand:

    mud, 39 Waende            unpassend   unbelegt   innen
    Loeser-Branch              0 Waende    25,9 %     1,54 %
    zusammengefuehrt           12          34,7 %       --
    ohne Eckenfilter            2          29,1 %       --
    Loeser + nur Eckenfilter   10          36,4 %     2,25 %

`cliff_kanten_gerechnet.json` lag lokal nur als unversionierte Datei vor; die
automatische Zuordnung (`cliff_kanten_auto.json`, Abschnitt 20) ersetzt sie.

## 23. Nordkante: Zeile, Enden, Abwechslung (29.10.2026)

Im Editor fiel auf: die Nordkante endete mit einem Haken (Kachel 164) und
bestand durchgehend aus Kachel 211. Gegen alle 54 Karten gezaehlt:

- **Zeile.** Die haeufigsten N-Kacheln in der Mitte einer Kante (157, 158,
  161, 160, 95, 162, 96, 159; je 500-700 Vorkommen) tragen die Linie im
  zweiten Abschnitt der Ostseite und sind EINEN Abschnitt dick. Unsere Linie
  lag in Zeile 1-2 -- dazu passte nur 211. Jetzt: genau ein Teilfeld, Zeile
  `NORD_ZEILE` = 1.
- **Enden.** Im Original hoert die Nordkante an der Kachelkante auf, mit Fels
  bis an die offene Seite (Westende 94, 212, 160, 211, 157, 159). Unsere Regel
  "kein Fels zum offenen Boden" liess nur Hakenkacheln zu. Jetzt laeuft die
  Linie an jedem Ende bis an die Kachelkante, und der Loeser erlaubt dort
  genau an dieser Seite Fels (`offen_ok`).
- **Abwechslung.** Die Vorliebe `INNENKANTE` zaehlte eine Seite mit drei
  Abschnitten Boden und einem Fels als "Randkachel mitten in der Wand" --
  bei einer Nordkante ist das ihre Linie. Jetzt nur Seiten ganz ohne Fels.
  Dazu prueft die Wiederholung auch den Abstand 3 (sonst Dreierrhythmus
  158-162-159).

78 Pruefwaende: 0 unpassend, 0 Loch, 0 hart; gleiche Nachbarn mud 1,8 %
(Originale 3,9 %), Abstand 2/3 1,9 %; unbelegt mud 25,3 -> 28,1 %.

## 24. Nur noch der Gelaende-Loeser, und eine Live-Vorschau (29.10.2026)

**Blockweg entfernt.** Editorpinsel, Flaechenpinsel, Landschaftsmodus und
alle Generatorvorlagen setzen Klippen nur noch ueber
`klippe_algo.klippe_aus_linie`. Geloescht: der Umschalter "Gelaende statt
Bloecke", 46 Funktionen und die Block-Methoden des `TileModel` in `mapgen.py`
(8905 -> 4369 Zeilen), die Module `cliff_walk`, `cliff_columns`,
`cliff_patches`, `cliff_gruppen` samt Modellen und Trainern, und die fuenf
Pruefungen, die nur den Blockweg betrafen. Der Flaechenpinsel laesst
bestehende Klippenzellen stehen, statt sie neu zu bauen. sno hat weiterhin
keine Kantenzuordnung -- dort wird keine Klippe gesetzt, und der Editor sagt
das.

**Schneller.** Der Loeser rechnete jede Stufe von vorn und fragte die
Kantentabelle Kachel fuer Kachel. Jetzt:

- je Familie einmal numpy-Tabellen (`_Tabelle`): Kantenabschnitte, erlaubte
  Nachbarn je Richtung, Innenbild, Fels zum offenen Boden
- die Kandidatenwerte (`_vorbereiten`) einmal fuer alle acht Stufen
- `rand_dem_biom`, `naht_teilen`, `naht_haelt`, `angleichen` vektorisiert
- gerechnet wird nur im Rechteck um die Linie, nicht auf der ganzen Karte
- Stufenzeit 0,15 s statt 1 s

Median je Wand 196 -> 24 ms, Mittel 65 ms; auf allen 78 Pruefwaenden
kachelgleich zum Stand davor.

**Live-Vorschau.** Steht beim Klippenpinsel mindestens ein Punkt, rechnet der
Editor die Wand fuer die gesetzten Punkte plus den Zeiger (gerastet wie der
Klick) und legt sie halbdeckend ueber die Karte. Geschrieben wird dabei
nichts: `PaintLayers.klippe_berechnen` arbeitet auf einer Kopie. Damit die
Vorschau genau das zeigt, was "Setzen" schreibt, kommt der Zufall aus den
Punkten und der Seite (crc32) statt aus dem fortlaufenden Generator --
geprueft: gesetzte Wand kachelgleich zur Vorschau.

- Gerechnet wird, wenn die Maus 60 ms stillsteht; dieselbe Linie wird nicht
  zweimal gerechnet.
- Ein Durchlauf im Editor: 33-50 ms, davon 11 ms fuer das Kachelgitter.
- Beim Waehlen des Klippenpinsels laedt ein Hintergrundfaden die Modelle
  (rund 2 s), damit die erste Mausbewegung nicht einfriert.
- Seitenwechsel rechnet neu; Setzen, Verwerfen, anderer Pinsel und das
  Verlassen des Gelaende-Reiters nehmen die Vorschau weg.

**Gerade Stuecke gerade (29.10.2026).** Im Editor war die Wand zwischen zwei
Punkten auf derselben Hoehe wellig: Oberkante und Dicke wanderten frei, und
die Unterkante sprang von Zelle zu Zelle um eine Reihe. Auf waagerecht oder
senkrecht gezeichneten Abschnitten wandert die Kante jetzt nicht mehr
(`GERADE_UNRUHE` = 0) und die Dicke streut nur noch zu 15 %
(`GERADE_DICKE`); an Knicks zu schraegen Stuecken wird ueber zwei Kacheln
uebergeblendet. Schraegen bleiben unveraendert. Nebenbei sinken die
Randkacheln mitten in der Wand (san senkrecht im Mittel 2,4 -> 0,6 %). Die
Suite-Pruefung dazu mittelt jetzt ueber drei Saaten, weil eine einzelne Wand
je Saat zwischen 0,4 und 3,9 % streute.

## 25. Wandhoehe aus der Karte (29.10.2026)

Die Wand war fest etwa 3 Zellen hoch. Jetzt richtet sie sich nach der Karte,
oder nach der Wahl im Editor ("Wandhoehe": wie Karte, 2 bis 6 Zellen).

**Gemessen wie in den Originalen** (`wandhoehe_messen`): je Spalte die Laeufe
von H/L-Zellen, nur wo links und rechts auch Klippe steht -- also quer durch
eine waagerecht laufende Wand. 54 Karten: Median ueberall 3, Mittel je Karte
2,5 bis 3,8 (mp2_05: 5,1). Hohe Waende sind in den Originalen selten (Hoehe 4
und mehr: 8 % der Laeufe) und sehen in der Mitte nach zwei gestapelten
Felsbaendern aus (Felsanteil 0,81 -> 0,56 -> 0,70) -- das waere der naechste
Schritt (Terrassen), ist aber noch nicht gebaut.

**Wo gemessen wird** (`wandhoehe_vor_ort`): erst 24 Zellen um die Linie --
wer an eine Klippe ansetzt, will deren Hoehe --, sonst die ganze Karte, sonst
3. Mindestens 12 Laeufe, damit eine einzelne Ecke nicht entscheidet.

**Umrechnung** (`dicke_aus_hoehe`): Felsdicke d +- 0,5 ergibt d + 1 Zellen
(2,0 -> 2,96; 3,0 -> 3,96; 4,0 -> 4,99; 5,0 -> 6,00 bei mud; san gleich). Auf
jeder Hoehe 0 hart, 0 Loch. 3 Zellen ergibt genau die bisherigen 1,5 bis 2,5.
Die Suite prueft, dass gebaut wird, was gemessen wird (2, 3, 5 Zellen).

Nebenbei liest der Editor das Kachelgitter ueber eine Indextabelle statt
Zelle fuer Zelle (11 -> 3 ms auf 256x256).
