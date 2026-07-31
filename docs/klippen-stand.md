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

## 8. Arbeitsweise, die sich bewaehrt hat

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
