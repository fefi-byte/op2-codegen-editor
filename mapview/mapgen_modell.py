"""Das gelernte Kachelmodell (`tiles_model.npz`) und seine Abfragen.

Teil des Kartengenerators, aus `mapgen.py` herausgeloest; `mapgen`
reicht alles weiter, Aufrufer bleiben unveraendert.

The learned tile model and its queries. Part of the map generator,
split out of `mapgen.py`, which re-exports everything.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

import celltypes  # noqa: E402
import shapegen  # noqa: E402
from mapgen_basis import (  # noqa: E402
    FAMILY_VEGETATION,
    MODEL_PATH,
    _korridor_von_stempel,
    _sperr_maske,
)


class TileModel:
    """Gelernte Nachbarschaft + Familienzuordnung der Kacheln."""

    def __init__(self, path: Path | None = None):
        data = np.load(path or MODEL_PATH, allow_pickle=False)
        self.families = [str(f) for f in data["families"]]
        # Formtabellen: Klippen entstehen daraus, statt kopiert zu werden.
        # Shape tables: cliffs are generated from these instead of copied.
        self.shapes = shapegen.ShapeTables(data)
        # Uebergangskacheln: je Bodenpaar die Kacheln samt gelerntem
        # Mischgrad (0 = fast nur A, 1 = fast nur B).
        # Transition tiles: per ground pair the tiles with their learned blend
        # level (0 = almost only A, 1 = almost only B).
        self.mix_quantile = (np.asarray(data["trans_quantile"], dtype=np.float32)
                             if "trans_quantile" in data else None)
        # Randkacheln je (Bodenpaar, Richtung) -- das ist die eigentliche
        # Auswahl. Nach Mischgrad allein blieben hunderte Kacheln je Paar und
        # die Grenze wurde zu Rauschen; mit der Richtung sind es 16.
        # Border tiles per (ground pair, direction) -- this is the actual
        # choice. By blend level alone hundreds of tiles remained per pair and
        # the border turned into noise; with the direction there are 16.
        self.rand: dict[tuple[str, str], dict[int, tuple]] = {}
        if "border_keys" in data and len(data["border_keys"]) > 1:
            paare = [tuple(str(p).split("|")) for p in data["border_pairs"]]
            keys = data["border_keys"]
            offs = data["border_offsets"]
            for i, schl in enumerate(keys.tolist()):
                paar, richtung = paare[schl // 8], schl % 8
                lo, hi = int(offs[i]), int(offs[i + 1])
                if hi > lo and len(paar) == 2:
                    self.rand.setdefault(paar, {})[richtung] = (
                        data["border_tiles"][lo:hi],
                        data["border_counts"][lo:hi].astype(float))

        self.trans: dict[tuple[str, str], list[tuple[int, float]]] = {}
        if "trans_tiles" in data and len(data["trans_tiles"]) > 1:
            for tile, a, b, mix in zip(data["trans_tiles"], data["trans_a"],
                                       data["trans_b"], data["trans_mix"]):
                self.trans.setdefault((str(a), str(b)), []).append(
                    (int(tile), float(mix)))
            for eintraege in self.trans.values():
                eintraege.sort(key=lambda t: t[1])
        # Mischgrad je Kachel: 0 = fast nur Boden A, 1 = fast nur B.
        # Blend level per tile: 0 = almost only ground A, 1 = almost only B.
        self.mix_of = {t: m for e in self.trans.values() for t, m in e}
        self.right = self._index(data["right"])
        self.down = self._index(data["down"])
        # Umkehrtabellen: zu einer Kachel alle, die links bzw. darueber
        # stehen duerfen. Die Vorausschau auf feste Nachbarn fragt genau das
        # und war ohne diese Tabellen mit 66 % der Rechenzeit der Flaschenhals
        # beim Malen.
        # Reverse tables: for a tile, everything allowed to its left or above.
        # The look-ahead at fixed neighbours asks exactly that and, without
        # these tables, was the bottleneck while painting at 66 % of the time.
        self.right_rev = self._umkehren(self.right)
        self.down_rev = self._umkehren(self.down)
        self._nachbar_cache: dict = {}
        self._abstand_cache: dict = {}
        self._daten = data
        self.gruppe = (np.asarray(data["gruppen"], dtype=np.int32)
                       if "gruppen" in data else None)
        usage = data["usage"]
        self.usage = dict(zip(usage[:, 0].tolist(), usage[:, 1].tolist()))
        self._usage_summe = float(sum(self.usage.values())) or 1.0
        fam = data["family"]
        self.family_of = np.full(2048, -1, dtype=np.int16)
        self.family_of[fam[:, 0]] = fam[:, 1].astype(np.int16)
        # Bewuchs ist in OP2 keine eigene Gelaendesorte, sondern bewachsener
        # Fels (Zelltyp cellFastPassible1). Die 27 Kacheln liegen in den
        # Gruppen von Erde und Fels, bilden aber Flaechen (zu 80 % folgt
        # rechts wieder Bewuchs) -- deshalb hier als eigene Familie fuehren,
        # damit sie steuerbar wird.
        # Vegetation is not its own terrain type in OP2 but overgrown rock
        # (cell type cellFastPassible1). Those 27 tiles sit in the dirt and
        # rock groups yet form patches (80 % continue to the right), so they
        # are treated as their own family here to make them steerable.
        self.veg_family = len(self.families)
        self.families.append(FAMILY_VEGETATION)
        for tile in range(2048):
            if celltypes.default_cell_type(tile, fallback=-1) == celltypes.FAST_PASSIBLE_1:
                self.family_of[tile] = self.veg_family

        # Bauteile (Vulkan, Lava, Klippen, Brandspuren, planiert): duerfen NIE
        # zufaellig gestreut werden -- im Original werden sie gesetzt.
        # Building blocks (volcano, lava, cliffs, burn marks, bulldozed): must
        # never be scattered randomly -- the originals place them.
        self.structure = np.zeros(2048, dtype=bool)
        self.structure[data["structure"]] = True
        # Lavakacheln werden NIE gesetzt: fliessende Lava entsteht im Spiel
        # durch den Vulkanausbruch. Die Karte liefert nur den Vulkan und das
        # Gebiet, in dem Lava fliessen darf (lavaPossible, zur Laufzeit).
        # Lava tiles are NEVER placed: flowing lava is created in-game by the
        # eruption. The map only provides the volcano and the area where lava
        # may flow (lavaPossible, set at runtime).
        self.lava = np.zeros(2048, dtype=bool)
        self.lava[data["lava"]] = True
        self.placeable = ~self.structure
        # Nur was die Originalkarten oft genug benutzen, darf frei gesetzt
        # werden. Mauern, Tubes, Wracks und Schutt stehen dort als fertige
        # Bauteile in Missionen, nicht als Landschaft -- `sanwrk17` etwa kommt
        # in 33 Karten neunmal vor.
        #
        # Frueher hat die gelernte Paartabelle sie nebenbei ausgesperrt: sie
        # standen nie neben normalem Boden, also kam die Kombination nie vor.
        # Die Kantenregel prueft aber nur den Rand, und der Rand eines
        # Wrackteils auf Sand sieht aus wie Sand. Schlimmer noch: die rechte
        # Kante eines Wrackteils passt fast nur zum naechsten Wrackteil, also
        # blieb der Sampler nach einer einzigen Fehlplatzierung mit 93,9 % in
        # derselben Gruppe -- eine Kachel zog einen ganzen Zug nach sich. So
        # kamen 384 statt 34 solcher Kacheln auf eine Karte.
        #
        # Gemessen ueber drei Seeds: ab 20 fallen sie von 384 auf 1, waehrend
        # noch 386 Kacheln frei bleiben. Hoehere Grenzen bringen nichts mehr
        # und nehmen nur Vielfalt weg.
        #
        # Only what the original maps use often enough may be placed freely.
        # Walls, tubes, wrecks and rubble appear there as finished building
        # blocks in missions, not as landscape -- `sanwrk17` for instance
        # occurs nine times across 33 maps.
        #
        # The learned pair table used to lock them out as a side effect: they
        # never stood next to ordinary ground, so the combination never
        # occurred. The edge rule however only checks the border, and the
        # border of a wreck piece on sand looks like sand. Worse, a wreck
        # piece's right edge fits almost only the next wreck piece, so after a
        # single misplacement the sampler stayed in the same group with 93.9 %
        # -- one tile dragged in a whole run. That produced 384 instead of 34
        # such tiles per map.
        #
        # Measured over three seeds: from 20 upwards they drop from 384 to 1
        # while 386 tiles remain free. Higher limits gain nothing and only
        # remove variety.
        for _t in range(len(self.placeable)):
            if int(self.usage.get(int(_t), 0)) < self.MINDEST_NUTZUNG:
                self.placeable[_t] = False

        # Fertige Klippenformationen aus den Originalkarten -- am Stueck
        # gesetzt sehen sie aus wie handgebaut, weil sie es sind.
        # Ready-made cliff formations from the original maps -- placed in one
        # piece they look hand-built, because they are.
        self.details: list = []             # (tiles, familie)
        if "detail_sizes" in data:
            d_sizes = data["detail_sizes"]
            d_tiles = data["detail_tiles"]
            d_off = data["detail_offsets"]
            d_fams = [str(f) for f in data["detail_families"]]
            for i in range(len(d_sizes)):
                dw, dh = int(d_sizes[i][0]), int(d_sizes[i][1])
                block = d_tiles[d_off[i]:d_off[i + 1]]
                # 1x1-Stempel weglassen: eine einzelne Kachel im Nichts sieht
                # nach Rauschen aus, nicht nach einem Steinfeld.
                # Skip 1x1 stamps: a single tile in the middle of nowhere looks
                # like noise, not like a rock field.
                if dw * dh > 1 and len(block) == dw * dh:
                    self.details.append((block.reshape(dh, dw),
                                         d_fams[i] if i < len(d_fams) else ""))

        # Grosse Massive und fertige Taeler -- fuer die Gelaendemerkmale.
        # Large massifs and finished valleys -- for the terrain features.
        self.massifs: list = []             # (tiles, familie)
        self.valleys: list = []             # (tiles, familie, achse, korridor)
        for name, ziel in (("massif", self.massifs), ("valley", self.valleys)):
            if f"{name}_sizes" not in data:
                continue
            sizes = data[f"{name}_sizes"]
            flat = data[f"{name}_tiles"]
            off = data[f"{name}_offsets"]
            fams = [str(f) for f in data[f"{name}_families"]]
            achsen = ([str(a) for a in data["valley_axis"]]
                      if name == "valley" else [""] * len(sizes))
            for i in range(len(sizes)):
                bw, bh = int(sizes[i][0]), int(sizes[i][1])
                block = flat[off[i]:off[i + 1]]
                if bw * bh <= 1 or len(block) != bw * bh:
                    continue
                tiles = block.reshape(bh, bw)
                fam = fams[i] if i < len(fams) else ""
                # Fremdes Biom aussortieren. Der Filter beim Anlernen greift zu
                # frueh: dort waechst die Familienzuordnung noch Karte fuer
                # Karte, hier ist sie vollstaendig. Ohne das stand ein weisser
                # Schneebalken mitten in der Wueste.
                # Sort out foreign biomes. The filter during training runs too
                # early -- there the family assignment still grows map by map,
                # here it is complete. Without this a white snow bar stood in
                # the middle of the desert.
                if not self._familienrein(tiles, fam):
                    continue
                if name == "valley":
                    ziel.append((tiles, fam, achsen[i] if i < len(achsen) else "h",
                                 _korridor_von_stempel(tiles)))
                else:
                    ziel.append((tiles, fam))

        # Uebergangskacheln gehoeren ausschliesslich ins Band. Ueber die
        # Nachbarschaftstabellen konnte der Bodensampler sie trotzdem waehlen
        # (342 von 486 galten als frei setzbar) -- dann malt man Sand und
        # bekommt Mischkacheln mitten hinein.
        # Transition tiles belong to the band only. Through the adjacency
        # tables the ground sampler could still pick them (342 of 486 counted
        # as freely placeable) -- then you paint sand and get blend tiles right
        # in the middle of it.
        for _paar in self.trans.values():
            for _t, _ in _paar:
                self.placeable[int(_t)] = False

        self._saeubere_formtabellen()
        self.formation_class: list[str] = []   # grat / massiv / plateau
        self.formation_dir: list[str] = []     # Gefaellerichtung n/o/s/w
        if "formation_class" in data:
            self.formation_class = [str(v) for v in data["formation_class"]]
        if "formation_dir" in data:
            self.formation_dir = [str(v) for v in data["formation_dir"]]

        self.formations: list = []          # (tiles, familie)
        f_sizes = data["formation_sizes"]
        f_tiles = data["formation_tiles"]
        f_off = data["formation_offsets"]
        f_fams = ([str(f) for f in data["formation_families"]]
                  if "formation_families" in data else [""] * len(f_sizes))
        for i in range(len(f_sizes)):
            fw, fh = int(f_sizes[i][0]), int(f_sizes[i][1])
            block = f_tiles[f_off[i]:f_off[i + 1]]
            if fw * fh and len(block) == fw * fh:
                self.formations.append((block.reshape(fh, fw),
                                        f_fams[i] if i < len(f_fams) else ""))
        self.volcanoes: list[tuple[str, int, int, np.ndarray]] = []
        names = [str(n) for n in data["volcano_names"]]
        sizes = data["volcano_sizes"]
        flat = data["volcano_tiles"]
        offsets = data["volcano_offsets"]
        for i, name in enumerate(names):
            if not name:
                continue
            w, h = int(sizes[i][0]), int(sizes[i][1])
            block = flat[offsets[i]:offsets[i + 1]]
            if w * h and len(block) == w * h:
                self.volcanoes.append((name, w, h, block.reshape(h, w)))
        # Deko gehoert ins Streugut, nicht in die freie Auswahl. Krater,
        # Felsbrocken und Risse haben einen eigenen Durchgang, der sie in
        # Gruppen und passend zum Untergrund verteilt. Konnte der Sampler sie
        # zusaetzlich einzeln setzen, standen je Karte 71-96 solcher Kacheln
        # zusammenhanglos im Gelaende -- ein Krater mitten im Sand, der zu
        # nichts gehoert.
        # Decoration belongs to the scatter pass, not to the free choice.
        # Craters, boulders and cracks have their own pass that distributes them
        # in groups and to matching ground. When the sampler could place them
        # individually on top, 71-96 such tiles per map stood in the terrain
        # without context -- a crater in the middle of the sand belonging to
        # nothing.
        for _kacheln, _fam in self.details:
            for _t in np.asarray(_kacheln).ravel():
                if 0 <= int(_t) < len(self.placeable):
                    self.placeable[int(_t)] = False
        # Dazu jede Kachel aus einer Verzierungsgruppe, auch wenn sie es nicht
        # in den Stempelvorrat geschafft hat.
        # Plus every tile from a decoration group, even one that did not make it
        # into the stamp pool.
        for _t in data.get("deko", np.array([], dtype=np.int32)):
            if 0 <= int(_t) < len(self.placeable):
                self.placeable[int(_t)] = False
        self._build_family_pools()
        # Zuletzt: die Kantenregel braucht Familien, Uebergaenge und
        # Haeufigkeiten, die weiter oben erst entstehen.
        # Last: the edge rule needs families, transitions and usage
        # counts, which only come into existence further up.
        self._lade_kanten(data)


    # Ab welchem ANTEIL der Nachbarschaften eines Blocks eine seiner Seiten als
    # "hier darf eine Klippe anschliessen" gilt.
    #
    # Bewusst ein Anteil und keine feste Zahl: eine feste haengt daran, wie
    # viele Karten zufaellig im Training liegen. Gemessen an 13 unabhaengig
    # belegten Regeln -- `sanmes00/01/02` ohne Nord/Sued, `07` und `14` ohne
    # Ost/West, `07` stapelbar, `05` ueber `07` -- haelt eine feste 3 bei 33
    # Karten alle 13, bei 107 nur noch 8: drei von 25 Faellen sind ein Signal,
    # drei von 629 sind Rauschen. Mit 10 % bleiben es in beiden Faellen 13.
    #
    # From what SHARE of a block's adjacencies one of its sides counts as "a
    # cliff may adjoin here". Deliberately a share and not a fixed count: a
    # fixed one depends on how many maps happen to be in the training set.
    # Measured against 13 independently established rules, a fixed 3 holds all
    # 13 at 33 maps but only 8 at 107 -- three out of 25 cases is a signal,
    # three out of 629 is noise. At 10 % it stays 13 either way.
    KLIPPEN_ANTEIL = 0.10

    # Grundgewicht fuer eine nie beobachtete Paarung auf einer erlaubten Seite.
    # Die Messung sagt, was die Entwickler taten, nicht was moeglich ist -- Sand
    # bringt nur 7 bis 20 Vorkommen je Block mit. Ein Filter daraus wuerde die
    # Auswahl auf die paar gesehenen Faelle einkochen; als Gewicht bleibt das
    # Seltene selten statt unmoeglich.
    # Base weight for a never-observed pairing on a permitted side. The
    # measurement says what the developers did, not what is possible -- sand
    # brings only 7 to 20 occurrences per block. Turning that into a filter
    # would boil the choice down to the handful of seen cases; as a weight the
    # rare stays rare instead of impossible.
    KLIPPEN_GRUNDRATE = 0.5


    def _build_family_pools(self):
        """Kacheln je Familie, nach Haeufigkeit -- Startpunkt des Samplings.

        Bauteile bleiben draussen; nur das Lavagebiet zieht aus Lavakacheln.

        Tiles per family, by frequency. Building blocks stay out; only the
        lava area draws from lava tiles."""
        self.by_family: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        for fi in range(len(self.families)):
            tiles = np.array([t for t, n in self.usage.items()
                              if self.family_of[t] == fi and self.placeable[t]],
                             dtype=np.int32)
            if len(tiles):
                weights = np.array([self.usage[int(t)] for t in tiles], dtype=float)
                self.by_family[fi] = (tiles, weights / weights.sum())

    # Ab welchem Farbunterschied zwei Kacheln an ihrer gemeinsamen Kante als
    # unvereinbar gelten. Gemessen an den Originalkarten: bei 30 sind 98,6 %
    # aller dort tatsaechlich benachbarten Paare erlaubt, und je Kachel
    # kommen 542 statt 21 Nachbarn in Frage.
    # From what colour difference two tiles count as incompatible along their
    # shared edge. Measured against the original maps: at 30, 98.6 % of all
    # pairs actually adjacent there are allowed, and 542 instead of 21 tiles
    # qualify as neighbours per tile.
    KANTEN_SCHWELLE = 30.0

    # Zusaetzlich der groesste Unterschied EINES Abschnitts. Der Mittelwert
    # allein verduennt eine einzelne verrutschte Ecke: passen sieben von acht
    # Abschnitten, faellt der achte nicht mehr auf, und im Bild endet dann eine
    # dunkle Struktur mitten an der Kachelkante. Gemessen an den Originalen
    # liegt dieser Groesstwert bei echten Nachbarn im Mittel bei 26; mit 55
    # bleiben 95 % der echten Paare erlaubt und noch 472 statt 542 Nachbarn je
    # Kachel -- es fallen also nur die Faelle mit einer stark abweichenden
    # Ecke weg.
    # Additionally the largest difference of a SINGLE segment. The mean alone
    # dilutes one misaligned corner: if seven of eight segments match, the
    # eighth no longer registers, and in the picture a dark structure then ends
    # in the middle of a tile border. Measured against the originals this
    # maximum averages 26 for real neighbours; at 55, 95 % of real pairs stay
    # allowed and 472 instead of 542 neighbours per tile remain -- so only the
    # cases with one strongly deviating corner drop out.
    KANTEN_SPITZE = 55.0

    # In wie viele Abschnitte eine Seite fuer den Musterabgleich zerlegt wird.
    # Jeder Abschnitt bekommt eine Bodenfamilie, und zwei Kacheln duerfen nur
    # aneinander, wenn die gemeinsame Seite dieselbe Folge hat -- Abschnitt fuer
    # Abschnitt, in derselben Leserichtung. Deckt eine Suedseite links bis zur
    # Mitte ab, muss die Nordseite darunter genau dort ebenfalls abdecken.
    #
    # Das ist keine Frage von "nah genug", sondern eine Ja/Nein-Regel, und
    # gemessen halten sich die Originalkarten daran: bei 4 Abschnitten stimmen
    # 95,3 % (waagerecht) und 95,9 % (senkrecht) aller echten Nachbarschaften
    # exakt, und es bleiben 429 erlaubte Nachbarn je Kachel. Feiner (8) faellt
    # auf 93 %, groeber (2) laesst mit 479 Nachbarn zu viel durch.
    #
    # Into how many segments a side is split for the pattern match. Each segment
    # gets a ground family, and two tiles may only join when the shared side has
    # the same sequence -- segment by segment, in the same reading direction. If
    # a south side is covered from the left to the middle, the north side below
    # must be covered exactly there too.
    #
    # This is not a question of "close enough" but a yes/no rule, and measured,
    # the original maps obey it: at 4 segments, 95.3 % (horizontal) and 95.9 %
    # (vertical) of all real adjacencies match exactly, leaving 429 allowed
    # neighbours per tile. Finer (8) drops to 93 %, coarser (2) lets too much
    # through at 479 neighbours.
    MUSTER_ABSCHNITTE = 4

    # Aufschlag auf den Kantenabstand, wenn das Muster nicht passt. Nur fuer die
    # Notwahl gedacht, wo keine Kachel die Bedingung haelt -- dann soll immer
    # noch die mit passendem Muster vorgehen.
    # Surcharge on the edge distance when the pattern does not match. Only for
    # the last-resort choice where no tile satisfies the constraint -- there the
    # one with a matching pattern should still win.
    MUSTER_STRAFE = 100.0

    # Gewicht fuer ein Paar, das die Kantenregel erlaubt, das aber in keiner
    # Originalkarte vorkam. Klein genug, dass Beobachtetes vorgeht, gross
    # genug, dass der Loeser nicht in Sackgassen laeuft.
    # Weight for a pair the edge rule allows but which occurs in no original
    # map: small enough that observed combinations win, large enough that the
    # solver does not run into dead ends.
    # Wie stark die Grundhaeufigkeit einer Kachel gegen die beobachteten
    # Paare zaehlt. Beide auf EINE Skala zu bringen ist der Kern: ein Paar, das
    # in 33 Karten neunmal vorkam, darf nicht so schwer wiegen wie die
    # haeufigste Bodenkachel ueberhaupt, nur weil deren Kombination zufaellig
    # nie beobachtet wurde. Vorher standen hier zwei getrennte Werte, und genau
    # dazwischen entstand die Kettenreaktion: lag erst eine seltene Kachel,
    # zog sie die naechste nach, und die Karte fuellte sich mit Mauern, Tubes
    # und Schrott.
    # How strongly a tile's base frequency counts against the observed pairs.
    # Putting both on ONE scale is the crux: a pair seen nine times across 33
    # maps must not weigh as much as the single most common ground tile merely
    # because that combination happened never to be observed. Two separate
    # values used to live here, and the chain reaction arose exactly in
    # between: once one rare tile was placed it pulled in the next, and the map
    # filled up with walls, tubes and debris.
    GRUNDRATE = 2000.0

    # Wie oft eine Kachel in den 33 Originalkarten vorkommen muss, damit der
    # Generator sie frei setzen darf.
    # How often a tile must occur across the 33 original maps for the generator
    # to place it freely.
    MINDEST_NUTZUNG = 20

    # Obergrenze fuer den Zwischenspeicher der Kantenabstaende. Ein Eintrag ist
    # ein Wert je Kachel, also rund 16 KB; ohne Grenze standen nach vier Karten
    # 3276 Eintraege und 54 MB darin. Bei Ueberlauf ganz leeren statt einzeln zu
    # verdraengen -- eine Karte braucht ihr Arbeitsgebiet ohnehin am Stueck.
    # Upper bound for the edge-distance cache. One entry is one value per tile,
    # about 16 KB; without a limit four maps left 3276 entries and 54 MB in it.
    # On overflow clear it wholesale instead of evicting one by one -- a map
    # needs its working set in one piece anyway.
    ABSTAND_CACHE_MAX = 2048


    def _lade_kanten(self, data) -> None:
        """Kantensignaturen laden und daraus die erlaubten Nachbarn bilden.

        Das ersetzt die gelernte Paartabelle als BEDINGUNG. Sie kannte nur,
        was in 33 Karten zufaellig vorkam -- im Schnitt 21 von 2012 moeglichen
        Nachbarn. Daher die Sackgassen: was links gesetzt wurde, machte rechts
        jede gueltige Wahl unmoeglich. Die Kantenregel ist dagegen berechenbar
        und gilt fuer alle Kacheln.

        This replaces the learned pair table as the CONSTRAINT. That table only
        knew what happened to occur in 33 maps -- 21 of 2012 possible
        neighbours on average, which is where the dead ends came from: what was
        placed on the left made every valid choice on the right impossible. The
        edge rule, by contrast, is computable and holds for every tile.
        """
        self.kanten = np.asarray(data["kanten"], dtype=np.float32) \
            if "kanten" in data else None
        self.kante_rechts: dict[int, np.ndarray] = {}
        self.kante_unten: dict[int, np.ndarray] = {}
        if self.kanten is None or len(self.kanten) < 2:
            return
        n = len(self.kanten)
        gueltig = self.kanten.reshape(n, -1).any(axis=1)
        self._baue_muster(gueltig)
        ost = self.kanten[:, 0]
        west = self.kanten[:, 1]
        sued = self.kanten[:, 2]
        nord = self.kanten[:, 3]
        idx = np.nonzero(gueltig)[0].astype(np.int32)
        # In Bloecken rechnen -- die volle Matrix waere sonst hunderte MB.
        # Compute in blocks; the full matrix would otherwise be hundreds of MB.
        for quelle, ziel, ablage, muster_q, muster_z in (
                (ost, west, self.kante_rechts, 0, 1),
                (sued, nord, self.kante_unten, 2, 3)):
            b = ziel[idx]
            for anfang in range(0, len(idx), 128):
                teil = idx[anfang:anfang + 128]
                d = np.abs(quelle[teil][:, None, :, :]
                           - b[None, :, :, :]).mean(axis=3)
                erlaubt = ((d.mean(axis=2) <= self.KANTEN_SCHWELLE)
                           & (d.max(axis=2) <= self.KANTEN_SPITZE))
                if self.muster is not None:
                    ma = self.muster[teil, muster_q][:, None, :]
                    mb = self.muster[idx, muster_z][None, :, :]
                    gleich = (ma == mb).all(axis=2)
                    betrifft = (self.ist_uebergang[teil][:, None]
                                | self.ist_uebergang[idx][None, :])
                    erlaubt &= gleich | ~betrifft
                for i, t in enumerate(teil):
                    ablage[int(t)] = idx[erlaubt[i]]
        self._baue_nachfolger()

    def _baue_muster(self, gueltig: np.ndarray) -> None:
        """Je Seite eine Folge von Bodenfamilien, ein Eintrag je Abschnitt.

        Reine Kacheln bekommen durchgehend ihre eigene Familie. Bei
        Uebergangskacheln wird je Abschnitt nur zwischen deren BEIDEN Boeden
        entschieden -- eine Zuordnung zur naechsten von allen Familien war zu
        wackelig, weil Fels und Erde farblich nah liegen und reine Kacheln dann
        zufaellig kippten (die Trefferquote fiel damit von 95 auf 60 %).

        One sequence of ground families per side, one entry per segment. Pure
        tiles get their own family throughout. For transition tiles each segment
        is decided between their TWO grounds only -- assigning to the nearest of
        all families was too shaky, because rock and dirt are close in colour
        and pure tiles then flipped at random (the match rate fell from 95 % to
        60 % that way).
        """
        n = len(self.kanten)
        abschnitte = self.MUSTER_ABSCHNITTE
        # Beim Lernen aus den echten Kachelpixeln bestimmt -- zwei Pixelreihen
        # tief, jeder Pixel einzeln eingeordnet und auf hoechstens einen
        # Wechsel je Kante zurechtgerueckt. Aus den gespeicherten Kantenmitteln
        # abzuleiten war ungenauer: eine einzige Pixelreihe kippt an
        # gesprenkelten Grenzen, und ein Mittelwert landet immer zwischen
        # beiden Boeden.
        # Determined during training from the real tile pixels -- two pixel rows
        # deep, every pixel classified individually and snapped to at most one
        # change per edge. Deriving it from the stored edge means was less
        # accurate: a single pixel row flips on dithered borders, and a mean
        # always lands between the two grounds.
        gelernt = self._daten.get("muster") if hasattr(self, "_daten") else None
        if gelernt is not None and len(gelernt) >= n:
            self.muster = np.asarray(gelernt[:n], dtype=np.int16)
            self.ist_uebergang = np.zeros(n, dtype=bool)
            for (na, nb), liste in self.trans.items():
                if na in self.families and nb in self.families:
                    for t, _ in liste:
                        if 0 <= int(t) < n:
                            self.ist_uebergang[int(t)] = True
            return
        segmente = self.kanten.shape[2]
        if segmente % abschnitte:
            self.muster = None
            return
        grob = self.kanten.reshape(n, 4, abschnitte,
                                   segmente // abschnitte, 3).mean(axis=3)

        # Kachel -> Bodenpaar aus der Uebergangstabelle
        paar_von: dict[int, tuple[int, int]] = {}
        for (na, nb), liste in self.trans.items():
            if na in self.families and nb in self.families:
                a = self.families.index(na)
                b = self.families.index(nb)
                for t, _ in liste:
                    paar_von[int(t)] = (a, b)

        farbe: dict[int, np.ndarray] = {}
        for fi in range(len(self.families)):
            rein = [t for t in range(n)
                    if gueltig[t] and self.family_of[t] == fi
                    and self.usage.get(int(t), 0) >= 100 and t not in paar_von]
            if len(rein) >= 3:
                farbe[fi] = grob[rein].reshape(-1, 3).mean(axis=0)

        # Nur Uebergangskacheln tragen ueberhaupt ein Muster, das etwas
        # aussagt. Bei einer reinen Kachel sind alle Abschnitte dieselbe
        # Familie -- verlangt man dann Gleichheit, duerfen zwei reine Kacheln
        # verschiedener Familien NIE aneinander, und die Biomgrenze kann nur
        # noch durch Uebergangskacheln laufen. Wo die fehlen, rastet sie auf
        # ganze Kacheln: im Bild wurde aus einem organischen Bewuchsrand eine
        # gerade Rastertreppe.
        # Only transition tiles carry a pattern that says anything. On a pure
        # tile all segments are the same family -- demanding equality then means
        # two pure tiles of different families may NEVER touch, and the biome
        # border can only run through transition tiles. Where those are missing
        # it snaps to whole tiles: in the picture an organic vegetation border
        # turned into a straight staircase.
        self.ist_uebergang = np.zeros(n, dtype=bool)
        for t in paar_von:
            if 0 <= t < n:
                self.ist_uebergang[t] = True
        muster = np.full((n, 4, abschnitte), -1, dtype=np.int16)
        schluessel = np.array(sorted(farbe)) if farbe else np.array([], int)
        farben = (np.stack([farbe[k] for k in schluessel]) if len(schluessel)
                  else None)
        for t in range(n):
            if not gueltig[t]:
                continue
            paar = paar_von.get(t)
            if paar and paar[0] in farbe and paar[1] in farbe:
                a, b = paar
                da = np.linalg.norm(grob[t] - farbe[a], axis=2)
                db = np.linalg.norm(grob[t] - farbe[b], axis=2)
                muster[t] = np.where(da <= db, a, b)
                continue
            f = int(self.family_of[t])
            if f >= 0:
                muster[t] = f
            elif farben is not None:
                d = np.linalg.norm(grob[t][:, :, None, :] - farben[None, None],
                                   axis=3)
                muster[t] = schluessel[d.argmin(axis=2)]
        self.muster = muster

    def muster_passt(self, a: int, b: int, richtung: str) -> bool:
        """Haben die beiden an ihrer gemeinsamen Seite dasselbe Muster?"""
        if self.muster is None:
            return True
        if not (self.ist_uebergang[int(a)] or self.ist_uebergang[int(b)]):
            return True
        q, z = (0, 1) if richtung == "rechts" else (2, 3)
        return bool((self.muster[int(a), q] == self.muster[int(b), z]).all())

    def _kanten_teile(self, kachel: int, richtung: str,
                      rueck: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Mittelwert und groesster Einzelabschnitt, getrennt."""
        q, z = (0, 1) if richtung == "rechts" else (2, 3)
        if rueck:
            q, z = z, q
        je_abschnitt = np.abs(self.kanten[:, z]
                              - self.kanten[int(kachel), q]).mean(axis=2)
        return je_abschnitt.mean(axis=1), je_abschnitt.max(axis=1)

    def kanten_abstand(self, kachel: int, richtung: str,
                       rueck: bool = False,
                       mit_muster: bool = True) -> np.ndarray:
        """Wie schlecht diese Kachel an jede andere anschliesst.

        Beide Kriterien auf eine Skala gebracht: der Wert ist so normiert, dass
        `<= KANTEN_SCHWELLE` genau dann gilt, wenn Mittelwert UND groesster
        Einzelabschnitt innerhalb ihrer Grenzen liegen.

        `mit_muster=False` laesst die Musterstrafe weg und liefert den reinen
        Farbsprung. Das braucht, wer Muster und Farbe getrennt verrechnet --
        sonst zaehlt die Musterabweichung zweimal.

        How badly this tile joins every other one. Both criteria on one scale:
        the value is normalised so that `<= KANTEN_SCHWELLE` holds exactly when
        the mean AND the largest single segment are within their limits.
        `mit_muster=False` drops the pattern penalty and yields the pure colour
        jump -- needed by callers that score pattern and colour separately,
        otherwise the pattern deviation would count twice.

        Das Ergebnis liegt im Zwischenspeicher -- nicht veraendern.
        The result is cached -- do not modify it.
        """
        schluessel = (int(kachel), richtung, bool(rueck), bool(mit_muster))
        treffer = self._abstand_cache.get(schluessel)
        if treffer is not None:
            return treffer
        q, z = (0, 1) if richtung == "rechts" else (2, 3)
        if rueck:
            q, z = z, q
        eigen = self.kanten[int(kachel), q]                 # (segmente, 3)
        andere = self.kanten[:, z]                          # (n, segmente, 3)
        je_abschnitt = np.abs(andere - eigen).mean(axis=2)   # (n, segmente)
        mittel = je_abschnitt.mean(axis=1)
        spitze = je_abschnitt.max(axis=1)
        wert = np.maximum(mittel,
                          spitze * self.KANTEN_SCHWELLE / self.KANTEN_SPITZE)
        if self.muster is not None and mit_muster:
            mq, mz = (0, 1) if richtung == "rechts" else (2, 3)
            if rueck:
                mq, mz = mz, mq
            passt = (self.muster[:, mz] == self.muster[int(kachel), mq]).all(axis=1)
            betrifft = self.ist_uebergang | self.ist_uebergang[int(kachel)]
            wert = wert + np.where(passt | ~betrifft, 0.0, self.MUSTER_STRAFE)
        if len(self._abstand_cache) >= self.ABSTAND_CACHE_MAX:
            self._abstand_cache.clear()
        self._abstand_cache[schluessel] = wert
        return wert

    def nachbarn_schwelle(self, kachel: int, richtung: str, schwelle: float,
                          rueck: bool = False, mit_muster: bool = True):
        """Erlaubte Nachbarn bei gelockerter Schwelle.

        Fuer die Rueckfallstufen: eine Nachbarin ganz zu ignorieren hiesse, an
        dieser Naht alles zuzulassen. Eine groessere Schwelle laesst die Naht
        sichtbarer werden, aber nicht beliebig.

        Allowed neighbours at a relaxed threshold. For the fallback levels:
        ignoring a neighbour entirely would allow anything at that seam; a
        larger threshold lets the seam become more visible, but not arbitrary.
        """
        schluessel = (int(kachel), richtung, float(schwelle), bool(rueck),
                      bool(mit_muster))
        treffer = self._nachbar_cache.get(schluessel)
        if treffer is not None:
            return treffer
        if self.kanten is None or len(self.kanten) < 2:
            return None, None
        # Nur der Mittelwert wird gelockert. Spitze und Muster bleiben hart:
        # ein normiertes Gesamtmass hat beim Lockern auch die Spitze mitgezogen
        # (bei Schwelle 60 waere ein Einzelabschnitt bis 110 durchgegangen), und
        # gemessen stiegen die sichtbaren Brueche dadurch von 0,24 auf 1,78 % --
        # die Stufen feuerten in 7,1 % der Zellen statt in 0,2 %.
        # Only the mean is relaxed. Peak and pattern stay hard: a single
        # normalised measure dragged the peak along when relaxing (at threshold
        # 60 a single segment up to 110 would have passed), and measured, visible
        # breaks rose from 0.24 to 1.78 % because the levels fired in 7.1 % of
        # cells instead of 0.2 %.
        mittel, spitze = self._kanten_teile(kachel, richtung, rueck)
        gueltig = self.kanten.reshape(len(self.kanten), -1).any(axis=1)
        erlaubt = (mittel <= schwelle) & (spitze <= self.KANTEN_SPITZE) & gueltig
        if self.muster is not None and mit_muster:
            mq, mz = (0, 1) if richtung == "rechts" else (2, 3)
            if rueck:
                mq, mz = mz, mq
            gleich = (self.muster[:, mz]
                      == self.muster[int(kachel), mq]).all(axis=1)
            betrifft = self.ist_uebergang | self.ist_uebergang[int(kachel)]
            erlaubt &= gleich | ~betrifft
        keys = np.nonzero(erlaubt)[0].astype(np.int32)
        treffer = (keys, self._gewichte(kachel, richtung, keys, rueck))
        self._nachbar_cache[schluessel] = treffer
        return treffer

    def _gewichte(self, kachel: int, richtung: str, keys: np.ndarray,
                  rueck: bool = False) -> np.ndarray:
        """Beobachtete Paare plus Grundrate der Kachel.

        Entspricht der ueblichen Glaettung: P(b|a) ~ Zaehler(a,b) + a * P(b).
        Ein nie beobachtetes Paar erbt damit die Haeufigkeit, die die Kachel
        ueberhaupt hat -- haeufiger Boden bleibt haeufig, Seltenes selten.

        Observed pairs plus the tile's base rate, i.e. the usual smoothing
        P(b|a) ~ count(a,b) + a * P(b). A never-observed pair thus inherits the
        frequency the tile has at all: common ground stays common, rare stays
        rare.
        """
        grund = self.GRUNDRATE * np.array(
            [self.usage.get(int(k), 0) for k in keys], dtype=float)
        grund /= max(1.0, self._usage_summe)
        # KEINE Untergrenze: eine feste Untergrenze macht alle unbeobachteten
        # Kandidaten gleich wahrscheinlich, und seltene Kacheln gibt es viel
        # mehr als haeufige -- gemessen setzte der Sampler dann 471 Kacheln
        # einer Gruppe, die in 33 Originalkarten neunmal vorkommt.
        # NO floor: a fixed floor makes all unobserved candidates equally
        # likely, and rare tiles far outnumber common ones -- measured, the
        # sampler then placed 471 tiles of a group occurring nine times across
        # 33 original maps.
        gew = np.maximum(grund, 1e-9)
        if rueck:
            tabelle = self.right_rev if richtung == "rechts" else self.down_rev
            erlaubt = tabelle.get(int(kachel))
            if erlaubt is not None:
                gew = gew + np.isin(keys, erlaubt).astype(float)
            return gew
        tabelle = self.right if richtung == "rechts" else self.down
        gelernt = tabelle.get(int(kachel))
        if gelernt is not None:
            zuordnung = {int(k): float(v) for k, v in zip(*gelernt)}
            for i, k in enumerate(keys):
                gew[i] += zuordnung.get(int(k), 0.0)
        return gew

    def nachbarn_rev(self, kachel: int, richtung: str):
        """Welche Kacheln duerfen LINKS bzw. UEBER dieser stehen."""
        schluessel = (int(kachel), richtung, "rev")
        treffer = self._nachbar_cache.get(schluessel)
        if treffer is None:
            treffer = self.nachbarn_schwelle(kachel, richtung,
                                             self.KANTEN_SCHWELLE, rueck=True)
            self._nachbar_cache[schluessel] = treffer
        return treffer

    def _baue_nachfolger(self) -> None:
        """Gibt es hinter Kachel t ueberhaupt eine Kachel der Familie f?

        Mit der Musterregel wird die Bedingung so streng, dass linke und obere
        Nachbarin gemeinsam eine Kachel fordern koennen, die es nicht gibt --
        gemessen in 3,87 % der Zellen, und genau dort entstanden die sichtbaren
        Brueche. Diese Tabelle erlaubt es, solche Sackgassen VOR dem Setzen zu
        meiden, statt sie hinterher zu bemerken.

        Is there any tile of family f behind tile t at all? With the pattern rule
        the constraint becomes strict enough that the left and top neighbour can
        jointly demand a tile that does not exist -- measured in 3.87 % of cells,
        and that is exactly where the visible breaks arose. This table allows
        avoiding such dead ends BEFORE placing instead of noticing them after.
        """
        anzahl = len(self.families)
        self.nachfolger_rechts = np.zeros((2048, anzahl + 1), dtype=bool)
        self.nachfolger_unten = np.zeros((2048, anzahl + 1), dtype=bool)
        for ablage, tabelle in ((self.nachfolger_rechts, self.kante_rechts),
                                (self.nachfolger_unten, self.kante_unten)):
            for t, erlaubt in tabelle.items():
                if not len(erlaubt):
                    continue
                frei = erlaubt[self.placeable[erlaubt]]
                if not len(frei):
                    continue
                fams = self.family_of[frei]
                ablage[int(t), anzahl] = True          # irgendeine Familie
                for f in np.unique(fams):
                    if 0 <= int(f) < anzahl:
                        ablage[int(t), int(f)] = True

    def hat_nachfolger(self, kacheln: np.ndarray, richtung: str,
                       familie: int) -> np.ndarray:
        """Maske: welche dieser Kacheln lassen die Familie noch zu?"""
        ablage = (self.nachfolger_rechts if richtung == "rechts"
                  else self.nachfolger_unten)
        spalte = familie if 0 <= familie < len(self.families) else len(self.families)
        return ablage[kacheln, spalte]

    def familie_nutzbar(self, familie: int) -> bool:
        """Hat dieser Boden ueberhaupt setzbare Kacheln?

        Schnee zum Beispiel hat keine: von 222 Kacheln sind 210 unpassierbar
        und keine erreicht die Mindesthaeufigkeit. Was der Generator nicht als
        Boden setzen kann, soll auch nicht ueber die Formtabelle hereinkommen.

        Does this ground have any placeable tiles at all? Snow for instance has
        none: of 222 tiles 210 are impassable and none reaches the minimum
        frequency. What the generator cannot place as ground should not enter
        through the shape table either.
        """
        if not hasattr(self, "_nutzbar"):
            self._nutzbar = {
                f: bool((self.placeable & (self.family_of == f)).any())
                for f in range(len(self.families))}
        return self._nutzbar.get(int(familie), True)

    def nachbarn(self, kachel: int, richtung: str):
        schluessel = (int(kachel), richtung)
        treffer = self._nachbar_cache.get(schluessel)
        if treffer is None:
            treffer = self._nachbarn_bauen(kachel, richtung)
            self._nachbar_cache[schluessel] = treffer
        return treffer

    def _nachbarn_bauen(self, kachel: int, richtung: str):
        """Erlaubte Nachbarn samt Gewicht -- Kantenregel plus Vorliebe.

        Allowed neighbours with weights: the edge rule decides what is
        possible, the learned frequency what is preferred.
        """
        tabelle = self.right if richtung == "rechts" else self.down
        kante = self.kante_rechts if richtung == "rechts" else self.kante_unten
        erlaubt = kante.get(int(kachel))
        gelernt = tabelle.get(int(kachel))
        if erlaubt is None or not len(erlaubt):
            return gelernt if gelernt is not None else (None, None)
        # Dieselbe Gewichtung wie bei gelockerter Schwelle -- vorher stand
        # hier eine zweite, flache Fassung, und weil der Sampler ueber genau
        # diesen Weg laeuft, blieb jede Verbesserung an `_gewichte` wirkungslos.
        # The same weighting as for a relaxed threshold -- a second, flat
        # version used to live here, and since the sampler runs through exactly
        # this path, every improvement to `_gewichte` had no effect.
        return erlaubt, self._gewichte(kachel, richtung, erlaubt)

    @staticmethod
    def _umkehren(tabelle: dict) -> dict:
        """a -> [b...] wird zu b -> [a...] (als sortierte Felder)."""
        sammler: dict[int, list[int]] = {}
        for a, (keys, _) in tabelle.items():
            for b in keys.tolist():
                sammler.setdefault(int(b), []).append(int(a))
        return {b: np.array(sorted(v), dtype=np.int32) for b, v in sammler.items()}

    @staticmethod
    def _index(pairs: np.ndarray) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        order = np.argsort(pairs[:, 0], kind="stable")
        pairs = pairs[order]
        starts = np.searchsorted(pairs[:, 0], np.arange(pairs[:, 0].max() + 2))
        table = {}
        for a in range(len(starts) - 1):
            lo, hi = starts[a], starts[a + 1]
            if hi > lo:
                table[a] = (pairs[lo:hi, 1].copy(), pairs[lo:hi, 2].astype(float))
        return table

    def _saeubere_formtabellen(self) -> None:
        """Lava, Fumarolen und Geroell aus den Klippen-Tabellen werfen.

        Die Tabellen lernen alles, was im Original in dieser Situation stand --
        rund um vulkanische Klippen also auch Lavakacheln und Schlote. Beim
        Nachschlagen landeten die dann mitten in der Wueste. Der Boden-Sampler
        filtert Bauteile laengst heraus, die Klippen-Tabelle muss es auch.
        Klippenkacheln selbst bleiben natuerlich drin.

        Throw lava, fumaroles and rubble out of the cliff tables. The tables
        learn everything that stood in that situation in the original, so around
        volcanic cliffs that includes lava tiles and vents, which then ended up
        in the middle of the desert on lookup. The ground sampler has always
        filtered structure tiles; the cliff table has to as well. Cliff tiles
        themselves of course stay.
        """
        verboten = {celltypes.VENTS_AND_FUMAROLES}
        erlaubt = np.ones(2048, dtype=bool)
        for tile in range(2048):
            zt = celltypes.default_cell_type(tile, fallback=-1)
            if zt in (celltypes.NORTH_CLIFFS, celltypes.CLIFFS_HIGH_SIDE,
                      celltypes.CLIFFS_LOW_SIDE):
                continue                      # Klippen sind das Ziel
            if zt in verboten or celltypes.speed_class(zt) in ("slow", "impassable"):
                erlaubt[tile] = False
        erlaubt[np.nonzero(self.lava)[0]] = False

        for keys, offs, tiles, counts in (
                ("ctx_keys", "ctx_offsets", "ctx_tiles", "ctx_counts"),
                ("ctx5_keys", "ctx5_offsets", "ctx5_tiles", "ctx5_counts"),
                ("grob_keys", "grob_offsets", "grob_tiles", "grob_counts")):
            k = getattr(self.shapes, keys)
            o = getattr(self.shapes, offs)
            t = getattr(self.shapes, tiles)
            c = getattr(self.shapes, counts)
            neu_k, neu_o, neu_t, neu_c = [], [0], [], []
            for i in range(len(k)):
                lo, hi = int(o[i]), int(o[i + 1])
                behalten = [(int(t[j]), int(c[j])) for j in range(lo, hi)
                            if erlaubt[int(t[j])]]
                if not behalten:
                    continue
                neu_k.append(int(k[i]))
                for kachel, n in behalten:
                    neu_t.append(kachel)
                    neu_c.append(n)
                neu_o.append(len(neu_t))
            setattr(self.shapes, keys, np.array(neu_k or [0], dtype=np.int64))
            setattr(self.shapes, offs, np.array(neu_o, dtype=np.int32))
            setattr(self.shapes, tiles, np.array(neu_t or [0], dtype=np.int32))
            setattr(self.shapes, counts, np.array(neu_c or [0], dtype=np.int32))

    @property
    def paar_hat_satz(self) -> np.ndarray:
        """Matrix: gibt es fuer diese beiden Boeden einen Uebergangssatz?

        Erde neben Bewuchs ist normal -- dafuer gibt es keine Uebergangskacheln,
        der Bewuchs sitzt einfach auf der Erde. Erde neben Fels dagegen kommt in
        den 33 Originalkarten KEIN einziges Mal ohne `mudtoroc` dazwischen vor.
        Die Matrix trennt beide Faelle.

        Matrix: is there a transition set for these two grounds? Dirt beside
        vegetation is normal -- there are no transition tiles for it, the growth
        simply sits on the dirt. Dirt beside rock on the other hand does not
        occur even once without `mudtoroc` in between across the 33 original
        maps. The matrix separates the two cases.
        """
        if getattr(self, "_paar_satz", None) is None:
            n = len(self.families)
            m = np.zeros((n, n), dtype=bool)
            for na, nb in self.trans:
                if na in self.families and nb in self.families:
                    a, b = self.families.index(na), self.families.index(nb)
                    m[a, b] = m[b, a] = True
            self._paar_satz = m
        return self._paar_satz


    def _familienrein(self, tiles, fam: str, grenze: float = 0.85) -> bool:
        """Bringt der Stempel ueberwiegend den eigenen Untergrund mit?"""
        if fam not in self.families:
            return True
        koerper = _sperr_maske(tiles)
        for _ in range(4):
            gewachsen = koerper.copy()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    gewachsen |= np.roll(np.roll(koerper, dy, 0), dx, 1)
            koerper = gewachsen
        fams = self.family_of[tiles[koerper]]
        klass = fams[(fams >= 0) & (fams < len(self.families))]
        if not len(klass):
            return False
        return float((klass == self.families.index(fam)).mean()) >= grenze


_model: TileModel | None = None


def model() -> TileModel:
    global _model
    if _model is None:
        _model = TileModel()
    return _model
