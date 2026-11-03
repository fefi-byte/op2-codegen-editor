#pragma once
// op2_ki.hpp - eine KI, die eine Kolonie von null aufbaut (Editor-Geruest, erster Baustein).
//
// Laeuft in AIProc der Missions-DLL. Sie liest den Spielstand (Gebaeude, Fahrzeuge, Rohstoffe, Nahrung,
// Strom), entscheidet nach Bedarf, was als Naechstes gebaut wird, laesst die Strukturfabrik die Bausaetze
// herstellen, holt sie mit ConVecs ab und baut sie so um die Kommandozentrale, dass die Roehrenstuecke,
// die jedes Gebaeude rechts und unten mitbringt, sie verbinden (am Anfang gibt es kein Metall fuer
// weitere Roehren). Robo-Surveyor und Robo-Miner erschliessen Erz, Lastwagen
// fahren es per MiningGroup zur Schmelze. Labore forschen selbststaendig.
//
// Jede Entscheidung landet mit Begruendung in <Mission>-KI.jsonl (eine JSON-Zeile je Ereignis, dazu
// regelmaessig eine Momentaufnahme). Der Editor liest die Datei in der Ansicht "KI-Spur" und zeigt sie
// auf der Karte, mit Zeitleiste -- so sieht man, warum die KI etwas tut oder haengen bleibt.
//
// Der ganze Zustand steckt in `ki::Zustand` mit fester Groesse, ohne Zeiger -- er gehoert in die
// SaveRegion der Mission, sonst hat die KI nach dem Laden eines Spielstands alles vergessen.
// Nur Einzelspieler: Entscheidungen haengen nur vom Spielstand ab (Zufall ueber TethysGame::GetRand),
// fuer Mehrspieler ist das aber noch nicht geprueft.
//
// An AI that builds a colony from scratch (editor scaffolding, first building block). Runs in AIProc,
// decides by need what to build next, has the Structure Factory produce kits, fetches them with ConVecs
// and places them so the tube stubs every building brings (right and bottom) connect them. Every decision
// is written with its reason to <Mission>-KI.jsonl, read by the editor's "AI trace" view. All state lives
// in the fixed-size `ki::Zustand` (no pointers) -- it belongs in the mission's SaveRegion.
//
// Benoetigt / needs: Outpost2DLL, HFL (UnitEx, PlayerEx, Research), op2_log.hpp (kiRaw).

#include <cstdarg>
#include <cstdlib>
#include <cstdio>
#include <cstring>

namespace ki {

// ---------------------------------------------------------------------------------------------------
// Groessen und Takt / sizes and timing

constexpr int TAKT          = 20;    // alle 20 Ticks ein Entscheidungsschritt
constexpr int SPUR_TAKT     = 200;   // alle 200 Ticks eine Momentaufnahme in die Spur
constexpr int MAX_PLAETZE   = 48;    // geplante/gebaute Bauplaetze
constexpr int MAX_ROEHREN   = 48;    // offene Roehrenstuecke
constexpr int MAX_MINEN     = 4;     // Minen mit eigener MiningGroup
constexpr int GEDULD_BAU    = 1500;  // so lange darf ein ConVec fuer einen Bau brauchen
constexpr int GEDULD_KIT    = 2500;  // so lange darf ein Bausatz in der Fabrik dauern

// Zustaende eines Bauplatzes / states of a building site
enum PlatzZustand : short { P_FREI = 0, P_FAHRT = 1, P_BAUT = 2, P_STEHT = 3, P_GESPERRT = 9 };

struct Platz {
  short x0, y0;      // Grundflaeche oben links (Editor-Kacheln)
  short typ;         // map_id
  short zustand;     // PlatzZustand
  int   convec;      // unitID des ConVecs, der hier baut (0 = keiner)
  int   seit;        // Tick der letzten Aenderung
  short versuche;
  short raster;      // frei (frueher Rasterplatz), immer -1
};

struct Roehre {      // ein gerades Roehrenstueck (Editor-Kacheln, inklusive)
  short x1, y1, x2, y2;
  short zustand;     // 0 offen, 1 beauftragt, 2 fertig
  short versuche;
  int   seit;
};

struct Zustand {
  int aktiv;
  int spieler;
  int ux, uy;                 // Engine-Koordinate der Editor-Kachel (0,0)
  int breite, hoehe;          // Kartengroesse in Kacheln
  int bx, by;                 // Basismitte (Editor-Kacheln)
  int naechsterSchritt;
  int naechsteSpur;
  int forschungModus;         // 0: DoResearch mit techID, 1: mit Tabellenindex (kalibriert sich selbst)
  int forschungLab;           // unitID des Labors, dessen Start geprueft wird
  int forschungWert;          // angefragtes Thema
  int forschungSeit;
  int kitTyp;                 // Bausatz, der gerade in der Fabrik entsteht (0 = keiner)
  int kitSeit;
  int kitGesperrtTyp[8];      // Bausaetze, die die Fabrik (noch) nicht herstellt
  int kitGesperrtBis[8];
  int kitPauseBis;            // Fabrik hat den letzten Auftrag nicht angenommen -> kurz warten
  int fzTyp;                  // Fahrzeug, das gerade in der Fahrzeugfabrik entsteht
  int fzSeit;
  int fzPauseBis;
  int meldungenSeit[16];      // Entprellung wiederkehrender Meldungen
  Platz plaetze[MAX_PLAETZE];
  int anzahlPlaetze;
  Roehre roehren[MAX_ROEHREN];
  int anzahlRoehren;
  int minenId[MAX_MINEN];     // unitID der Mine je MiningGroup (0 = frei)
  int schmelzeId[MAX_MINEN];
  MiningGroup minenGruppe[MAX_MINEN];
  int bakeZiel;               // unitID der Bake, die als Naechstes erschlossen wird
  int bakeMiner;              // unitID des Miners, der gerade eine Mine baut
  int bakeSeit;               // seit wann diese Bake das Ziel ist
  int minerSeit;              // wann der Miner den Auftrag bekam
  int bakenX[4], bakenY[4];   // selbst angelegte Baken (Editor-Kacheln)
  int anzahlBaken;
};

// ---------------------------------------------------------------------------------------------------
// Kleinkram / helpers

struct Groesse { int w, h; };

inline Groesse grundflaeche(int typ) {
  switch (typ) {
    case mapCommandCenter:       return { 3, 2 };
    case mapStructureFactory:    return { 4, 3 };
    case mapVehicleFactory:      return { 4, 3 };
    case mapTokamak:             return { 2, 2 };
    case mapMHDGenerator:        return { 2, 2 };
    case mapSolarPowerArray:     return { 3, 2 };
    case mapCommonOreSmelter:    return { 4, 3 };
    case mapRareOreSmelter:      return { 4, 3 };
    case mapCommonOreMine:       return { 2, 1 };
    case mapRareOreMine:         return { 2, 1 };
    case mapCommonStorage:       return { 1, 2 };
    case mapRareStorage:         return { 1, 2 };
    case mapAgridome:            return { 3, 2 };
    case mapResidence:           return { 2, 2 };
    case mapReinforcedResidence: return { 3, 2 };
    case mapAdvancedResidence:   return { 3, 3 };
    case mapBasicLab:            return { 2, 2 };
    case mapStandardLab:         return { 3, 2 };
    case mapAdvancedLab:         return { 3, 3 };
    case mapMedicalCenter:       return { 2, 2 };
    case mapNursery:             return { 2, 2 };
    case mapUniversity:          return { 2, 2 };
    case mapRecreationFacility:  return { 2, 2 };
    case mapForum:               return { 2, 2 };
    case mapDIRT:                return { 3, 2 };
    case mapGarage:              return { 3, 2 };
    case mapConsumerFactory:     return { 3, 3 };
    case mapGuardPost:           return { 1, 1 };
    case mapLightTower:          return { 1, 1 };
    case mapGORF:                return { 3, 2 };
    case mapRobotCommand:        return { 2, 2 };
    case mapObservatory:         return { 2, 2 };
    case mapMeteorDefense:       return { 2, 2 };
    case mapTradeCenter:         return { 2, 2 };
    default:                     return { 2, 2 };
  }
}

inline const char* name(int typ) {
  switch (typ) {
    case mapCommandCenter: return "CommandCenter";        case mapStructureFactory: return "StructureFactory";
    case mapVehicleFactory: return "VehicleFactory";      case mapTokamak: return "Tokamak";
    case mapMHDGenerator: return "MHDGenerator";          case mapSolarPowerArray: return "SolarPowerArray";
    case mapCommonOreSmelter: return "CommonOreSmelter";  case mapRareOreSmelter: return "RareOreSmelter";
    case mapCommonOreMine: return "CommonOreMine";        case mapRareOreMine: return "RareOreMine";
    case mapCommonStorage: return "CommonStorage";        case mapRareStorage: return "RareStorage";
    case mapAgridome: return "Agridome";                  case mapResidence: return "Residence";
    case mapReinforcedResidence: return "ReinforcedResidence"; case mapAdvancedResidence: return "AdvancedResidence";
    case mapBasicLab: return "BasicLab";                  case mapStandardLab: return "StandardLab";
    case mapAdvancedLab: return "AdvancedLab";            case mapMedicalCenter: return "MedicalCenter";
    case mapNursery: return "Nursery";                    case mapUniversity: return "University";
    case mapRecreationFacility: return "RecreationFacility"; case mapForum: return "Forum";
    case mapDIRT: return "DIRT";                          case mapGarage: return "Garage";
    case mapConsumerFactory: return "ConsumerFactory";    case mapGuardPost: return "GuardPost";
    case mapLightTower: return "LightTower";              case mapGORF: return "GORF";
    case mapRobotCommand: return "RobotCommand";          case mapObservatory: return "Observatory";
    case mapMeteorDefense: return "MeteorDefense";        case mapTradeCenter: return "TradeCenter";
    case mapConVec: return "ConVec";                      case mapCargoTruck: return "CargoTruck";
    case mapRoboMiner: return "RoboMiner";                case mapRoboSurveyor: return "RoboSurveyor";
    case mapRoboDozer: return "RoboDozer";                case mapEarthworker: return "Earthworker";
    case mapScout: return "Scout";                        case mapRepairVehicle: return "RepairVehicle";
    case mapEvacuationTransport: return "EvacuationTransport";
    case mapLynx: return "Lynx";                          case mapPanther: return "Panther";
    case mapTiger: return "Tiger";                        case mapMiningBeacon: return "MiningBeacon";
    case mapNone: return "-";
    default: return "?";
  }
}

// Zelltypen (siehe mapview/celltypes.py)
inline bool zelleBebaubar(int c)  { return c == 0 || c == 2 || c == 3 || c == 4 || c == 5 || c == 7 || c == 21; }
inline bool zelleRoehre(int c)    { return c >= 26 && c <= 31; }
inline bool zelleBefahrbar(int c) { return zelleBebaubar(c) || c == 22 || zelleRoehre(c); }

inline LOCATION engine(const Zustand& z, int x, int y) { return LOCATION(x + z.ux, y + z.uy); }
inline int edX(const Zustand& z, const LOCATION& l) { return l.x - z.ux; }
inline int edY(const Zustand& z, const LOCATION& l) { return l.y - z.uy; }
inline bool aufKarte(const Zustand& z, int x, int y, int rand = 2) {
  return x >= rand && y >= rand && x < z.breite - rand && y < z.hoehe - rand;
}
inline int zelle(const Zustand& z, int x, int y) { return GameMap::GetCellType(engine(z, x, y)); }
inline int abstand2(int ax, int ay, int bx, int by) { return (ax - bx) * (ax - bx) + (ay - by) * (ay - by); }

// ---------------------------------------------------------------------------------------------------
// Spur / trace  (JSON-Zeilen in <Mission>-KI.jsonl)

struct Puffer {
  char b[12288];
  int n = 0;
  void roh(const char* s) { while (*s && n < (int)sizeof(b) - 2) b[n++] = *s++; }
  void f(const char* fmt, ...) {
    if (n >= (int)sizeof(b) - 2) return;
    va_list ap; va_start(ap, fmt);
    int k = std::vsnprintf(b + n, sizeof(b) - n - 1, fmt, ap);
    va_end(ap);
    if (k > 0) n += (k < (int)sizeof(b) - n - 1) ? k : (int)sizeof(b) - n - 2;
  }
  // Text als JSON-String (Anfuehrungszeichen und Backslash maskiert)
  void str(const char* s) {
    roh("\"");
    for (; *s && n < (int)sizeof(b) - 4; ++s) {
      if (*s == '"' || *s == '\\') b[n++] = '\\';
      b[n++] = *s;
    }
    roh("\"");
  }
  void schreiben() { op2::log::kiRaw(b, n); n = 0; }
};

// Eine Entscheidung mit Begruendung. `was`: bau, kit, fahrzeug, forschung, mine, roehre, warte, fehler, info
inline void melde(const Zustand& z, const char* was, int typ, int x, int y, const char* fmt, ...) {
  char warum[400];
  va_list ap; va_start(ap, fmt);
  std::vsnprintf(warum, sizeof(warum), fmt, ap);
  va_end(ap);
  Puffer p;
  p.f("{\"t\":%d,\"art\":\"entscheid\",\"p\":%d,\"was\":", TethysGame::Tick(), z.spieler);
  p.str(was);
  p.f(",\"typ\":"); p.str(name(typ));
  p.f(",\"x\":%d,\"y\":%d,\"warum\":", x, y);
  p.str(warum);
  p.roh("}");
  p.schreiben();
}

// Wiederkehrende Meldung hoechstens alle `abstand` Ticks (z.B. "warte auf Erz")
inline bool selten(Zustand& z, int kanal, int abstand) {
  const int t = TethysGame::Tick();
  if (kanal < 0 || kanal >= 16) return true;
  if (z.meldungenSeit[kanal] != 0 && t - z.meldungenSeit[kanal] < abstand) return false;
  z.meldungenSeit[kanal] = t;
  return true;
}

// Alle Gebaeudetypen, die die KI zaehlt (PlayerBuildingEnum braucht einen Typ).
// All building types the AI counts (PlayerBuildingEnum needs a type).
static const int GEBAEUDE[] = {
  mapCommandCenter, mapStructureFactory, mapVehicleFactory, mapTokamak, mapMHDGenerator, mapSolarPowerArray,
  mapCommonOreSmelter, mapRareOreSmelter, mapCommonOreMine, mapRareOreMine, mapCommonStorage, mapRareStorage,
  mapAgridome, mapResidence, mapReinforcedResidence, mapAdvancedResidence, mapBasicLab, mapStandardLab,
  mapAdvancedLab, mapMedicalCenter, mapNursery, mapUniversity, mapRecreationFacility, mapForum, mapDIRT,
  mapGarage, mapConsumerFactory, mapGuardPost, mapLightTower, mapGORF, mapRobotCommand, mapObservatory,
  mapMeteorDefense, mapTradeCenter, mapArachnidFactory, mapSpaceport, mapGeothermalPlant, mapMagmaWell,
};

// ---------------------------------------------------------------------------------------------------
// Lagebild / situation  (wird jeden Schritt neu erhoben, nicht gespeichert)

struct Lage {
  int geb[128];          // Anzahl fertiger Gebaeude je map_id (map_id < 128)
  int fz[128];           // Anzahl Fahrzeuge je map_id
  int kitsImSpiel[128];  // Bausaetze in Fabrikbuchten und auf ConVecs
  UnitEx cc, sf, vf;     // erste Kommandozentrale / Strukturfabrik / Fahrzeugfabrik
  int erz, erzMax, nahrung, nahrungNetto, stromFrei, menschen, wohnraum, wiss;
};

inline void erhebe(const Zustand& z, Lage& l) {
  std::memset(l.geb, 0, sizeof(l.geb));
  std::memset(l.fz, 0, sizeof(l.fz));
  std::memset(l.kitsImSpiel, 0, sizeof(l.kitsImSpiel));
  l.cc = UnitEx(); l.sf = UnitEx(); l.vf = UnitEx();
  const int p = z.spieler;
  for (int t : GEBAEUDE) {
    PlayerBuildingEnum e(p, (map_id)t);
    UnitEx u;
    while (e.GetNext(u)) {
      if (t >= 0 && t < 128) l.geb[t]++;
      if (t == mapCommandCenter && !l.cc.unitID) l.cc = u;
      if (t == mapStructureFactory) {
        if (!l.sf.unitID) l.sf = u;
        for (int bay = 0; bay < 6; ++bay) {
          const int k = u.GetFactoryCargo(bay);
          if (k > 0 && k < 128) l.kitsImSpiel[k]++;
        }
      }
      if (t == mapVehicleFactory && !l.vf.unitID) l.vf = u;
    }
  }
  {
    PlayerVehicleEnum e(p);
    UnitEx u;
    while (e.GetNext(u)) {
      const int t = u.GetType();
      if (t >= 0 && t < 128) l.fz[t]++;
      if (t == mapConVec) {
        const int k = u.GetCargo();
        if (k > 0 && k < 128) l.kitsImSpiel[k]++;
      }
    }
  }
  l.erz = Player[p].Ore();
  l.erzMax = ExtPlayer[p].GetMaxOre();
  l.nahrung = Player[p].FoodStored();
  l.nahrungNetto = ExtPlayer[p].GetNetFoodProduction();
  l.stromFrei = ExtPlayer[p].GetAmountPowerAvailable();
  l.menschen = Player[p].Kids() + Player[p].Workers() + Player[p].Scientists();
  l.wohnraum = ExtPlayer[p].GetTotalResidenceCapacity();
  l.wiss = ExtPlayer[p].GetNumAvailableScientists();
}

// Gebaeude eines Typs: fertig + geplant/im Bau
inline int geplant(const Zustand& z, int typ) {
  int n = 0;
  for (int i = 0; i < z.anzahlPlaetze; ++i)
    if (z.plaetze[i].typ == typ && (z.plaetze[i].zustand == P_FAHRT || z.plaetze[i].zustand == P_BAUT)) n++;
  return n;
}

// ---------------------------------------------------------------------------------------------------
// Bauplatz / site selection
//
// Jedes Gebaeude bringt zwei Roehrenstuecke mit: eins rechts, eins unten, jeweils in der Mitte der
// Seite und im 1 Kachel breiten Rand (ausser Kraftwerken und Minen). Am Anfang gibt es kein Metall
// fuer weitere Roehren -- also muessen die Gebaeude so stehen, dass diese Stuecke sie verbinden:
// genau 1 Kachel Abstand, und das Stueck des einen trifft die Seite des anderen. Kraftwerke und
// Minen brauchen keinen Anschluss.
//
// Every building comes with two tube stubs (right and bottom, centred in the 1-tile border; not power
// plants or mines). At the start there is no metal for more tubes, so buildings must stand exactly
// one tile apart with a stub of one touching the side of the other.

struct Rechteck { int x0, y0, w, h; bool stutzen; };

inline bool hatStutzen(int typ) {
  switch (typ) {
    case mapTokamak: case mapMHDGenerator: case mapSolarPowerArray: case mapGeothermalPlant:
    case mapCommonOreMine: case mapRareOreMine: case mapMagmaWell:
    case mapGuardPost: case mapLightTower:
      return false;
    default:
      return true;
  }
}

inline Rechteck rechteckUm(int typ, int cx, int cy) {        // aus der Mitte (Location)
  const Groesse g = grundflaeche(typ);
  return { cx - g.w / 2, cy - g.h / 2, g.w, g.h, hatStutzen(typ) };
}

// Alle eigenen Gebaeude und geplanten Plaetze (gesperrte Plaetze als Hindernis ohne Stutzen).
inline int hindernisse(const Zustand& z, Rechteck* out, int max) {
  int n = 0;
  for (int t : GEBAEUDE) {
    PlayerBuildingEnum e(z.spieler, (map_id)t);
    UnitEx u;
    while (e.GetNext(u) && n < max) {
      const LOCATION l = u.Location();
      out[n++] = rechteckUm(t, edX(z, l), edY(z, l));
    }
  }
  for (int i = 0; i < z.anzahlPlaetze && n < max; ++i) {
    const Platz& q = z.plaetze[i];
    if (q.zustand == P_FREI) continue;
    const Groesse g = grundflaeche(q.typ);
    out[n++] = { q.x0, q.y0, g.w, g.h, q.zustand != P_GESPERRT && hatStutzen(q.typ) };
  }
  return n;
}

inline bool ueberlappt(int ax, int ay, int aw, int ah, int bx, int by, int bw, int bh) {
  return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah;
}

// Grundflaeche bebaubar, Rand befahrbar, keine Bake/kein Wrack, nichts Geplantes im Weg,
// kein Roehrenstutzen unter der Grundflaeche.
inline bool platzFrei(const Zustand& z, int x0, int y0, int w, int h, const Rechteck* hin, int nh,
                      const char** grund) {
  if (!aufKarte(z, x0 - 1, y0 - 1, 2) || !aufKarte(z, x0 + w, y0 + h, 2)) { *grund = "Kartenrand"; return false; }
  for (int i = 0; i < nh; ++i) {
    const Rechteck& r = hin[i];
    // Abstand mindestens 1 Kachel: der Rand des einen darf die Grundflaeche des anderen nicht beruehren
    if (ueberlappt(x0 - 1, y0 - 1, w + 2, h + 2, r.x0, r.y0, r.w, r.h)) { *grund = "Gebaeude/Plan"; return false; }
    if (r.stutzen) {
      const int sx = r.x0 + r.w, sy = r.y0 + r.h / 2;        // rechter Stutzen
      const int ux = r.x0 + r.w / 2, uy = r.y0 + r.h;        // unterer Stutzen
      if (ueberlappt(x0, y0, w, h, sx, sy, 1, 1) || ueberlappt(x0, y0, w, h, ux, uy, 1, 1)) {
        *grund = "Roehrenstutzen"; return false;
      }
    }
  }
  for (int y = y0 - 1; y <= y0 + h; ++y)
    for (int x = x0 - 1; x <= x0 + w; ++x) {
      const int c = zelle(z, x, y);
      const bool innen = x >= x0 && x < x0 + w && y >= y0 && y < y0 + h;
      if (innen ? !zelleBebaubar(c) : !zelleBefahrbar(c)) { *grund = innen ? "Untergrund" : "Rand"; return false; }
    }
  MAP_RECT rr(engine(z, x0 - 1, y0 - 1), engine(z, x0 + w, y0 + h));
  InRectEnumerator e(rr);
  UnitEx u2;
  while (e.GetNext(u2)) {
    if (u2.IsVehicle()) {
      // Fahrende Fahrzeuge sind gleich weg; ein stehendes in der Grundflaeche blockiert den Bau.
      const LOCATION l = u2.Location();
      const int vx = edX(z, l), vy = edY(z, l);
      if (vx >= x0 && vx < x0 + w && vy >= y0 && vy < y0 + h && u2.GetCurAction() == moDone && u2.GetType() != mapConVec) {
        *grund = "Fahrzeug steht im Weg"; return false;
      }
      continue;
    }
    *grund = u2.IsBuilding() ? "Gebaeude" : "Bake/Wrack";
    return false;
  }
  return true;
}

// Neuen Eintrag in z.plaetze anlegen (freigewordene wiederverwenden). -1 = voll.
inline int platzEintrag(Zustand& z, int typ, int x0, int y0) {
  int k = -1;
  for (int i = 0; i < z.anzahlPlaetze; ++i) if (z.plaetze[i].zustand == P_FREI && !z.plaetze[i].convec) { k = i; break; }
  if (k < 0) {
    if (z.anzahlPlaetze >= MAX_PLAETZE) return -1;
    k = z.anzahlPlaetze++;
  }
  Platz& p = z.plaetze[k];
  p.x0 = (short)x0; p.y0 = (short)y0; p.typ = (short)typ; p.zustand = P_FREI;
  p.convec = 0; p.seit = TethysGame::Tick(); p.versuche = 0; p.raster = -1;
  return k;
}

// Platz fuer `typ` suchen. Liefert Index in z.plaetze oder -1.
inline int platzWaehlen(Zustand& z, int typ) {
  static Rechteck hin[160];
  const int nh = hindernisse(z, hin, 160);
  const Groesse g = grundflaeche(typ);
  const char* grund = "";
  int verworfen = 0;
  int bestX = 0, bestY = 0;
  int besteWertung = 1 << 30;
  bool gefunden = false;
  auto pruefen = [&](int x0, int y0, int wertung) {
    if (wertung >= besteWertung) return;
    if (!platzFrei(z, x0, y0, g.w, g.h, hin, nh, &grund)) { verworfen++; return; }
    besteWertung = wertung; bestX = x0; bestY = y0; gefunden = true;
  };
  const int mx = z.bx, my = z.by;
  if (!hatStutzen(typ) || typ == mapCommandCenter) {
    // Kommandozentrale: so nah wie moeglich an die Basismitte. Kraftwerke: etwas abseits (Ring um
    // die Mitte), damit sie keine Anschlussplaetze belegen.
    for (int dy = -12; dy <= 12; ++dy)
      for (int dx = -12; dx <= 12; ++dx) {
        const int x0 = mx + dx - g.w / 2, y0 = my + dy - g.h / 2;
        const int d2 = dx * dx + dy * dy;
        int w;
        if (typ == mapCommandCenter) w = d2;
        else { const int d = (int)(d2 > 0 ? d2 : 0); w = (d - 49) * (d - 49) / 8 + d / 4; }  // Ring um ~7
        pruefen(x0, y0, w);
      }
  } else {
    // Gebaeude mit Anschluss: an einen Stutzen eines vorhandenen/geplanten Gebaeudes, oder mit dem
    // eigenen Stutzen an dessen Seite -- immer genau 1 Kachel Abstand.
    for (int i = 0; i < nh; ++i) {
      const Rechteck& a = hin[i];
      if (!a.stutzen) continue;
      const int acx = a.x0 + a.w / 2, acy = a.y0 + a.h / 2;
      auto wert = [&](int x0, int y0, int ausrichtung) {
        const int cx = x0 + g.w / 2, cy = y0 + g.h / 2;
        return abstand2(cx, cy, mx, my) * 4 + ausrichtung;
      };
      // rechts von A (A's rechter Stutzen trifft unsere linke Seite)
      for (int y0 = acy - g.h + 1; y0 <= acy; ++y0) pruefen(a.x0 + a.w + 1, y0, wert(a.x0 + a.w + 1, y0, std::abs(y0 - a.y0)));
      // unter A (A's unterer Stutzen trifft unsere Oberseite)
      for (int x0 = acx - g.w + 1; x0 <= acx; ++x0) pruefen(x0, a.y0 + a.h + 1, wert(x0, a.y0 + a.h + 1, std::abs(x0 - a.x0)));
      // links von A (unser rechter Stutzen trifft A's linke Seite)
      for (int y0 = a.y0 - g.h / 2; y0 <= a.y0 + a.h - 1 - g.h / 2; ++y0) pruefen(a.x0 - 1 - g.w, y0, wert(a.x0 - 1 - g.w, y0, std::abs(y0 - a.y0)));
      // ueber A (unser unterer Stutzen trifft A's Oberseite)
      for (int x0 = a.x0 - g.w / 2; x0 <= a.x0 + a.w - 1 - g.w / 2; ++x0) pruefen(x0, a.y0 - 1 - g.h, wert(x0, a.y0 - 1 - g.h, std::abs(x0 - a.x0)));
    }
  }
  if (!gefunden) {
    if (selten(z, 6, 1000))
      melde(z, "fehler", typ, z.bx, z.by, "kein Bauplatz mit Anschluss (%d verworfen, zuletzt: %s)", verworfen, grund);
    return -1;
  }
  return platzEintrag(z, typ, bestX, bestY);
}

// ---------------------------------------------------------------------------------------------------
// Bedarf / needs: was soll als Naechstes gebaut werden?  Liefert map_id oder mapNone, dazu die Begruendung.

inline int bedarf(const Zustand& z, const Lage& l, char* warum, int n) {
  auto hat = [&](int t) { return l.geb[t] + geplant(z, t) + l.kitsImSpiel[t]; };
  const int bewohner = l.menschen;
  if (!hat(mapCommandCenter)) { std::snprintf(warum, n, "keine Kommandozentrale"); return mapCommandCenter; }
  if (!hat(mapStructureFactory)) { std::snprintf(warum, n, "ohne Strukturfabrik keine Bausaetze"); return mapStructureFactory; }
  if (!hat(mapTokamak)) { std::snprintf(warum, n, "kein Kraftwerk"); return mapTokamak; }
  if (!hat(mapCommonOreSmelter)) { std::snprintf(warum, n, "keine Erzschmelze"); return mapCommonOreSmelter; }
  if (!hat(mapAgridome)) { std::snprintf(warum, n, "keine Nahrung"); return mapAgridome; }
  if (l.stromFrei < 25 && geplant(z, mapTokamak) + l.kitsImSpiel[mapTokamak] == 0) {
    std::snprintf(warum, n, "nur %d Strom frei", l.stromFrei); return mapTokamak;
  }
  if ((l.nahrungNetto < 0 || l.nahrung < 300) && geplant(z, mapAgridome) + l.kitsImSpiel[mapAgridome] == 0) {
    std::snprintf(warum, n, "Nahrung %d, netto %+d", l.nahrung, l.nahrungNetto); return mapAgridome;
  }
  // KI-Spieler bekommen vom Spiel 4096 Arbeiter, 4096 Wissenschaftler, 256 Kinder, wenn die Mission
  // nichts setzt -- dann zaehlt Wohnraum nicht.
  // AI players get engine default population if the mission sets none -- housing does not count then.
  const bool standardVolk = bewohner >= 8000;
  if (!standardVolk && bewohner > l.wohnraum && geplant(z, mapResidence) + l.kitsImSpiel[mapResidence] == 0) {
    std::snprintf(warum, n, "%d Bewohner, Wohnraum %d", bewohner, l.wohnraum); return mapResidence;
  }
  if (!hat(mapVehicleFactory)) { std::snprintf(warum, n, "Fahrzeuge nachbauen"); return mapVehicleFactory; }
  if (!hat(mapBasicLab)) { std::snprintf(warum, n, "Forschung beginnen"); return mapBasicLab; }
  if (l.erzMax > 0 && l.erz > l.erzMax * 9 / 10 && geplant(z, mapCommonStorage) + l.kitsImSpiel[mapCommonStorage] == 0) {
    std::snprintf(warum, n, "Erzlager zu %d %% voll", l.erz * 100 / l.erzMax); return mapCommonStorage;
  }
  if (!hat(mapNursery)) { std::snprintf(warum, n, "Nachwuchs"); return mapNursery; }
  if (!hat(mapUniversity)) { std::snprintf(warum, n, "Wissenschaftler ausbilden"); return mapUniversity; }
  if (!hat(mapMedicalCenter)) { std::snprintf(warum, n, "Gesundheit"); return mapMedicalCenter; }
  if (!hat(mapStandardLab)) { std::snprintf(warum, n, "weiter forschen"); return mapStandardLab; }
  if (!hat(mapRecreationFacility)) { std::snprintf(warum, n, "Moral"); return mapRecreationFacility; }
  if (!standardVolk && hat(mapResidence) < 3 && bewohner + 10 > l.wohnraum) {
    std::snprintf(warum, n, "Wohnraum wird knapp (%d/%d)", bewohner, l.wohnraum); return mapResidence;
  }
  warum[0] = 0;
  return mapNone;
}

inline bool kitGesperrt(const Zustand& z, int typ) {
  const int t = TethysGame::Tick();
  for (int i = 0; i < 8; ++i) if (z.kitGesperrtTyp[i] == typ && z.kitGesperrtBis[i] > t) return true;
  return false;
}
inline void kitSperren(Zustand& z, int typ, int dauer) {
  int frei = 0;
  for (int i = 0; i < 8; ++i) if (z.kitGesperrtBis[i] < z.kitGesperrtBis[frei]) frei = i;
  z.kitGesperrtTyp[frei] = typ;
  z.kitGesperrtBis[frei] = TethysGame::Tick() + dauer;
}

// ---------------------------------------------------------------------------------------------------
// Strukturfabrik / structure factory: Bausatz herstellen

inline void fabrik(Zustand& z, const Lage& l) {
  if (!l.sf.unitID) return;
  UnitEx sf = l.sf;
  const int t = TethysGame::Tick();
  if (z.kitTyp) {                                        // laeuft schon etwas?
    for (int bay = 0; bay < 6; ++bay)
      if (sf.GetFactoryCargo(bay) == z.kitTyp) {
        melde(z, "kit", z.kitTyp, edX(z, sf.Location()), edY(z, sf.Location()), "fertig in Bucht %d", bay);
        z.kitTyp = 0;
        return;
      }
    if (t - z.kitSeit > 100 && t - z.kitSeit < 100 + TAKT + 1 && sf.GetCurAction() != moDevelop) {
      // Auftrag nicht angenommen: Fabrik im Bau, ohne Strom oder ohne Arbeiter? Spaeter erneut.
      melde(z, "warte", z.kitTyp, edX(z, sf.Location()), edY(z, sf.Location()),
            "Strukturfabrik nimmt den Auftrag nicht an (Strom %d, Arbeiter %d) -- in 500 Ticks erneut",
            sf.HasPower(), sf.HasWorkers());
      z.kitTyp = 0; z.kitPauseBis = t + 500;
      return;
    }
    if (t - z.kitSeit > GEDULD_KIT) {
      melde(z, "fehler", z.kitTyp, edX(z, sf.Location()), edY(z, sf.Location()),
            "Bausatz nach %d Ticks nicht fertig -- gesperrt (Technik fehlt? Arbeiter? Strom?)", t - z.kitSeit);
      kitSperren(z, z.kitTyp, 6000);
      z.kitTyp = 0;
    }
    return;
  }
  if (sf.GetCurAction() == moDevelop) return;            // produziert (vielleicht von Hand)
  if (t < z.kitPauseBis) return;
  int freieBucht = -1, kitsInBuchten = 0;
  for (int bay = 0; bay < 6; ++bay) {
    const int k = sf.GetFactoryCargo(bay);
    if (k == mapNone || k == 0) { if (freieBucht < 0) freieBucht = bay; }
    else kitsInBuchten++;
  }
  if (freieBucht < 0) return;
  // Nicht mehr Bausaetze vorproduzieren, als ConVecs sie abholen koennen.
  if (kitsInBuchten >= (l.fz[mapConVec] > 1 ? l.fz[mapConVec] : 1)) return;
  char warum[200];
  const int typ = bedarf(z, l, warum, sizeof(warum));
  if (typ == mapNone || typ == mapCommandCenter || kitGesperrt(z, typ)) return;
  UnitInfo info((map_id)typ);
  const int kosten = info.GetOreCost(z.spieler);
  if (kosten > l.erz) {
    if (selten(z, 0, 1500))
      melde(z, "warte", typ, edX(z, sf.Location()), edY(z, sf.Location()), "Erz %d, Bausatz kostet %d (%s)", l.erz, kosten, warum);
    return;
  }
  sf.DoProduce((map_id)typ, mapNone);
  z.kitTyp = typ; z.kitSeit = t;
  melde(z, "kit", typ, edX(z, sf.Location()), edY(z, sf.Location()), "%s (Erz %d, kostet %d)", warum, l.erz, kosten);
}

// ---------------------------------------------------------------------------------------------------
// ConVecs: Bausatz holen und bauen / fetch kits and build

inline int platzVon(const Zustand& z, int convecId) {
  for (int i = 0; i < z.anzahlPlaetze; ++i)
    if (z.plaetze[i].convec == convecId && z.plaetze[i].zustand != P_FREI && z.plaetze[i].zustand != P_GESPERRT) return i;
  return -1;
}

// Wohin DoBuild zielen muss, damit die Grundflaeche bei (x0, y0) liegt. Im Spiel gemessen (erster
// Lauf, Spur vom 3.11.): DoBuild(L) legt die Grundflaeche auf [L.x - w, L.x - 1] x [L.y - h, L.y - 1] --
// L ist die Ecke unten rechts des Rechtecks MIT dem 1-Kachel-Rand. Location() des fertigen Gebaeudes
// ist dagegen die Mitte (x0 + w/2, y0 + h/2), wie im Editor.
// Where DoBuild must aim so the footprint lands at (x0, y0): measured in game, L is the bottom-right
// corner of the footprint rectangle INCLUDING its 1-tile border.
inline LOCATION bauOrt(const Zustand& z, int x0, int y0, Groesse g) { return engine(z, x0 + g.w, y0 + g.h); }

inline bool stehtDa(const Zustand& z, const Platz& p) {
  const Groesse g = grundflaeche(p.typ);
  MAP_RECT r(engine(z, p.x0, p.y0), engine(z, p.x0 + g.w - 1, p.y0 + g.h - 1));
  InRectEnumerator e(r);
  Unit u;
  while (e.GetNext(u)) if (u.IsBuilding() && u.GetType() == p.typ && u.OwnerID() == z.spieler) return true;
  return false;
}

// Eigene stehende Fahrzeuge von Grundflaeche und Rand wegschicken (sie blockieren den Bau).
inline void platzRaeumen(Zustand& z, const Platz& p, int convecId) {
  const Groesse g = grundflaeche(p.typ);
  MAP_RECT r(engine(z, p.x0 - 1, p.y0 - 1), engine(z, p.x0 + g.w, p.y0 + g.h));
  InRectEnumerator e(r);
  UnitEx u;
  int n = 0;
  while (e.GetNext(u)) {
    if (!u.IsVehicle() || u.OwnerID() != z.spieler || u.unitID == convecId || u.IsBusy()) continue;
    u.DoMove(engine(z, p.x0 + g.w / 2, p.y0 + g.h + 4));
    n++;
  }
  if (n) melde(z, "info", p.typ, p.x0, p.y0, "%d Fahrzeug(e) vom Bauplatz geschickt", n);
}

inline void bauen(Zustand& z, UnitEx c, int kit) {
  const int t = TethysGame::Tick();
  int i = platzVon(z, c.unitID);
  if (i < 0) {
    i = platzWaehlen(z, kit);
    if (i < 0) return;
    Platz& p = z.plaetze[i];
    const Groesse g = grundflaeche(kit);
    p.zustand = P_FAHRT; p.convec = c.unitID; p.seit = t;
    c.DoBuild((map_id)kit, bauOrt(z, p.x0, p.y0, g));
    melde(z, "bau", kit, p.x0, p.y0, "ConVec %d bringt den Bausatz (Platz %dx%d)", c.unitID, g.w, g.h);
    return;
  }
  Platz& p = z.plaetze[i];
  const Groesse g = grundflaeche(p.typ);
  if (p.zustand == P_STEHT) return;              // Gebaeude waechst schon, Bausatz wird gerade verbaut
  if (c.GetCurAction() == moBuild) { if (p.zustand != P_BAUT) { p.zustand = P_BAUT; p.seit = t; } return; }
  if (c.IsBusy() || c.GetCurAction() != moDone) return;    // faehrt oder baut (Aktion 10 waehrend des Baus)
  if (t - p.seit > GEDULD_BAU || (p.zustand == P_FAHRT && t - p.seit > 200)) {
    platzRaeumen(z, p, c.unitID);
    p.versuche++;
    if (p.versuche >= 3) {
      melde(z, "fehler", p.typ, p.x0, p.y0, "Bau klappt hier nicht (%d Versuche) -- Platz gesperrt", p.versuche);
      p.zustand = P_GESPERRT; p.convec = 0;
      return;
    }
    p.seit = t;
    c.DoBuild((map_id)p.typ, bauOrt(z, p.x0, p.y0, g));
    melde(z, "bau", p.typ, p.x0, p.y0, "erneut beauftragt (Versuch %d)", p.versuche + 1);
  }
}

inline void convecs(Zustand& z, const Lage& l) {
  const int t = TethysGame::Tick();
  // Erst die Plaetze nachfuehren: ConVec leer und Gebaeude steht -> fertig
  for (int i = 0; i < z.anzahlPlaetze; ++i) {
    Platz& p = z.plaetze[i];
    UnitEx c; c.unitID = p.convec;
    const bool lebt = p.convec && c.IsLive() && c.GetType() == mapConVec && c.OwnerID() == z.spieler;
    if (p.zustand == P_STEHT) {                  // ConVec freigeben, sobald der Bausatz verbaut ist
      if (p.convec && (!lebt || c.GetCargo() == mapNone)) p.convec = 0;
      continue;
    }
    if (p.zustand != P_FAHRT && p.zustand != P_BAUT) continue;
    if (stehtDa(z, p)) {
      p.zustand = P_STEHT; p.seit = t;
      melde(z, "fertig", p.typ, p.x0, p.y0, "Gebaeude steht (im Bau oder fertig)");
    } else if (!lebt || c.GetCargo() != p.typ) {
      if (!lebt || c.GetCargo() == mapNone) {
        melde(z, "fehler", p.typ, p.x0, p.y0, lebt ? "ConVec ohne Bausatz, Gebaeude fehlt" : "ConVec verloren");
        p.zustand = P_FREI; p.convec = 0;
      }
    }
  }
  // Der ConVec mit der Kommandozentrale zuerst: an ihr haengt die ganze Basis.
  // The ConVec carrying the Command Center first: the grid hangs on it.
  {
    PlayerVehicleEnum e(z.spieler);
    UnitEx c;
    while (e.GetNext(c)) if (c.GetType() == mapConVec && c.GetCargo() == mapCommandCenter) bauen(z, c, mapCommandCenter);
  }
  int abholer = 0;  // ConVecs, die gerade zur Fabrik fahren
  PlayerVehicleEnum e(z.spieler);
  UnitEx c;
  while (e.GetNext(c)) {
    if (c.GetType() != mapConVec) continue;
    const int kit = c.GetCargo();
    if (kit == mapCommandCenter) continue;
    if (kit != mapNone && kit > 0) { bauen(z, c, kit); continue; }
    // Leer: Bausatz in der Fabrik abholen
    if (!l.sf.unitID) continue;
    UnitEx sf = l.sf;
    int bucht = -1;
    for (int bay = 0; bay < 6; ++bay) {
      const int k = sf.GetFactoryCargo(bay);
      if (k != mapNone && k > 0) { bucht = bay; break; }
    }
    if (bucht < 0) continue;
    const LOCATION dock = sf.GetDockLocation();
    const LOCATION wo = c.Location();
    if (wo.x == dock.x && wo.y == dock.y) {
      sf.DoTransferCargo(bucht);
      if (selten(z, 5, 200))
        melde(z, "laden", sf.GetFactoryCargo(bucht), edX(z, wo), edY(z, wo), "ConVec %d laedt aus Bucht %d", c.unitID, bucht);
    } else if (abholer == 0 && (!c.IsBusy() || c.GetLastCommand() != ctMoDock)) {
      c.DoDock(dock);
      abholer++;
      melde(z, "holen", sf.GetFactoryCargo(bucht), edX(z, dock), edY(z, dock), "ConVec %d faehrt zur Strukturfabrik", c.unitID);
    } else if (c.GetLastCommand() == ctMoDock) {
      abholer++;
    }
  }
}

// ---------------------------------------------------------------------------------------------------
// Roehren / tubes: der Earthworker arbeitet die Auftragsliste ab

inline bool roehreFertig(const Zustand& z, const Roehre& r) {
  for (int y = r.y1; y <= r.y2; ++y)
    for (int x = r.x1; x <= r.x2; ++x) if (!zelleRoehre(zelle(z, x, y))) return false;
  return true;
}

inline void roehren(Zustand& z) {
  const int t = TethysGame::Tick();
  UnitEx ew;
  {
    PlayerVehicleEnum e(z.spieler);
    UnitEx u;
    while (e.GetNext(u)) if (u.GetType() == mapEarthworker) { ew = u; break; }
  }
  bool beschaeftigt = false;
  for (int i = 0; i < z.anzahlRoehren; ++i) {
    Roehre& r = z.roehren[i];
    if (r.zustand == 2) continue;
    if (roehreFertig(z, r)) { r.zustand = 2; continue; }
    if (r.zustand == 1) {
      if (ew.unitID && (ew.IsBusy() || t - r.seit < 150)) { beschaeftigt = true; continue; }
      r.versuche++;
      if (r.versuche >= 3) {
        melde(z, "fehler", mapNone, r.x1, r.y1, "Roehre bis %d,%d nicht gebaut -- aufgegeben", r.x2, r.y2);
        r.zustand = 2;
        continue;
      }
      r.zustand = 0;
    }
    if (beschaeftigt || !ew.unitID || ew.IsBusy()) continue;
    // Nur die Einzelkacheln bauen, die noch keine Roehre sind? Ein Auftrag fuer das ganze Stueck ist
    // einfacher; der Earthworker ueberspringt fertige Kacheln.
    MAP_RECT rect(engine(z, r.x1, r.y1), engine(z, r.x2, r.y2));
    ew.DoBuildWall(mapTube, rect);
    r.zustand = 1; r.seit = t;
    beschaeftigt = true;
    melde(z, "roehre", mapNone, r.x1, r.y1, "Earthworker %d legt Roehre bis %d,%d", ew.unitID, r.x2, r.y2);
  }
  if (!ew.unitID) {
    for (int i = 0; i < z.anzahlRoehren; ++i)
      if (z.roehren[i].zustand != 2) {
        if (selten(z, 1, 3000)) melde(z, "warte", mapEarthworker, z.bx, z.by, "Roehren offen, aber kein Earthworker");
        break;
      }
  }
}

// ---------------------------------------------------------------------------------------------------
// Erz / ore: Bake finden, vermessen, Mine bauen, Lastwagen zuteilen

struct BakenFund { UnitEx beste; int gesehen, gewoehnlich, frei; };

inline bool mineAuf(const LOCATION& l) {
  LocationEnumerator e(l);
  Unit v;
  while (e.GetNext(v)) if (v.GetType() == mapCommonOreMine || v.GetType() == mapRareOreMine) return true;
  return false;
}

// Naechste freie gewoehnliche Erz-Bake. Drei Wege, weil nicht sicher ist, welcher Aufzaehler Baken
// liefert: Rechteck ueber die Karte, Umkreis um die Basis, selbst angelegte Baken per Kachel.
// Nearest free common ore beacon, found three ways (map rect, radius around the base, own beacons).
inline BakenFund bakeSuchen(const Zustand& z) {
  BakenFund f; f.gesehen = f.gewoehnlich = f.frei = 0;
  int ids[64]; int nids = 0;
  int besterD = 1 << 30;
  auto pruefe = [&](UnitEx& u) {
    if (u.GetType() != mapMiningBeacon) return;
    for (int i = 0; i < nids; ++i) if (ids[i] == u.unitID) return;
    if (nids < 64) ids[nids++] = u.unitID;
    f.gesehen++;
    if (u.GetOreType() != 0) return;                                   // nur gewoehnliches Erz
    f.gewoehnlich++;
    const LOCATION l = u.Location();
    if (mineAuf(l)) return;
    f.frei++;
    // vermessene Baken bevorzugen (Abzug), sonst die naechste
    const bool vermessen = (u.GetSurveyedBy() & (1 << z.spieler)) != 0;
    const int d = abstand2(edX(z, l), edY(z, l), z.bx, z.by) - (vermessen ? 200 : 0);
    if (d < besterD) { besterD = d; f.beste = u; }
  };
  {
    MAP_RECT alles(engine(z, 1, 1), engine(z, z.breite - 2, z.hoehe - 2));
    InRectEnumerator e(alles);
    UnitEx u;
    while (e.GetNext(u)) pruefe(u);
  }
  {
    InRangeEnumerator e(engine(z, z.bx, z.by), 60);
    UnitEx u;
    while (e.GetNext(u)) pruefe(u);
  }
  for (int i = 0; i < z.anzahlBaken; ++i) {
    LocationEnumerator e(engine(z, z.bakenX[i], z.bakenY[i]));
    UnitEx u;
    while (e.GetNext(u)) pruefe(u);
  }
  return f;
}

inline void erz(Zustand& z, const Lage& l) {
  const int p = z.spieler;
  const int t = TethysGame::Tick();
  // Ziel: naechste freie Bake. Der Surveyor faehrt hin und vermisst (wie ein Spieler es tun wuerde);
  // der Miner baut, sobald sie vermessen ist -- oder ohne, wenn es keinen Surveyor gibt oder er zu
  // lange braucht.
  // Target: nearest free beacon. The surveyor goes there first (human-like); the miner builds once it
  // is surveyed -- or without, if there is no surveyor or it takes too long.
  if (l.geb[mapCommonOreMine] < MAX_MINEN) {
    BakenFund f = bakeSuchen(z);
    if (!f.beste.unitID) {
      if (selten(z, 8, 5000))
        melde(z, "warte", mapMiningBeacon, z.bx, z.by, "keine freie Erz-Bake (gesehen %d, gewoehnlich %d, frei %d)",
              f.gesehen, f.gewoehnlich, f.frei);
    } else {
      UnitEx b = f.beste;
      const LOCATION bl = b.Location();
      if (z.bakeZiel != b.unitID) {
        z.bakeZiel = b.unitID; z.bakeSeit = t;
        melde(z, "info", mapMiningBeacon, edX(z, bl), edY(z, bl), "naechste Bake (gesehen %d, gewoehnlich %d, frei %d)",
              f.gesehen, f.gewoehnlich, f.frei);
      }
      const bool vermessen = (b.GetSurveyedBy() & (1 << p)) != 0;
      // Surveyor
      UnitEx s;
      bool surveyor = false;
      { PlayerVehicleEnum e(p); UnitEx u; while (e.GetNext(u)) if (u.GetType() == mapRoboSurveyor) { s = u; surveyor = true; break; } }
      if (!vermessen && surveyor && !s.IsBusy() && s.GetCurAction() == moDone && selten(z, 9, 400)) {
        const LOCATION sl = s.Location();
        const bool dort = abstand2(sl.x, sl.y, bl.x, bl.y) <= 2;
        LOCATION ziel = bl;
        if (!dort) ziel.x += 1;
        s.DoMove(ziel);
        melde(z, "vermessen", mapMiningBeacon, edX(z, bl), edY(z, bl),
              dort ? "Surveyor %d steht an der Bake, noch nicht vermessen -- faehrt drauf" : "Surveyor %d faehrt zur Bake", s.unitID);
      }
      // Miner
      UnitEx m; m.unitID = z.bakeMiner;
      const bool minerAmWerk = z.bakeMiner && m.IsLive() && m.GetType() == mapRoboMiner && (m.IsBusy() || m.GetCurAction() != moDone);
      const bool darf = vermessen || !surveyor || t - z.bakeSeit > 1200;
      if (darf && !minerAmWerk) {
        if (z.bakeMiner && m.IsLive() && m.GetType() == mapRoboMiner && t - z.minerSeit > 300 && selten(z, 10, 1500))
          melde(z, "fehler", mapCommonOreMine, edX(z, bl), edY(z, bl), "Robo-Miner %d steht, Mine nicht gebaut (vermessen: %s)",
                m.unitID, vermessen ? "ja" : "nein");
        PlayerVehicleEnum e(p);
        UnitEx u;
        while (e.GetNext(u)) {
          if (u.GetType() != mapRoboMiner || u.IsBusy()) continue;
          if (u.unitID == z.bakeMiner && t - z.minerSeit < 600) break;      // gleicher Auftrag, kurz warten
          u.DoDeployMiner(bl);
          z.bakeMiner = u.unitID; z.minerSeit = t;
          melde(z, "mine", mapCommonOreMine, edX(z, bl), edY(z, bl), "Robo-Miner %d baut Mine (%s)", u.unitID,
                vermessen ? "Bake vermessen" : surveyor ? "Surveyor braucht zu lange" : "ohne Surveyor");
          break;
        }
      }
    }
  }
  // 3) Jede Mine mit einer Schmelze verbinden und Lastwagen zuteilen
  UnitEx schmelze;
  { PlayerBuildingEnum e(p, mapCommonOreSmelter); e.GetNext(schmelze); }
  if (!schmelze.unitID) return;
  PlayerBuildingEnum em(p, mapCommonOreMine);
  UnitEx mine;
  while (em.GetNext(mine)) {
    int g = -1;
    for (int i = 0; i < MAX_MINEN; ++i) if (z.minenId[i] == mine.unitID) g = i;
    if (g < 0) {
      for (int i = 0; i < MAX_MINEN; ++i) if (!z.minenId[i]) { g = i; break; }
      if (g < 0) break;
      z.minenGruppe[g] = CreateMiningGroup(Player[p]);
      z.minenId[g] = mine.unitID;
      z.schmelzeId[g] = 0;
    }
    if (z.schmelzeId[g] != schmelze.unitID) {
      LOCATION ml = mine.Location(), sl = schmelze.Location();
      MAP_RECT bereich(LOCATION(sl.x - 3, sl.y - 3), LOCATION(sl.x + 3, sl.y + 3));
      z.minenGruppe[g].Setup(ml, sl, bereich);
      z.schmelzeId[g] = schmelze.unitID;
      melde(z, "mine", mapCommonOreMine, edX(z, ml), edY(z, ml), "Erzroute Mine -> Schmelze %d,%d", edX(z, sl), edY(z, sl));
    }
    // Zwei Lastwagen je Mine
    if (z.minenGruppe[g].TotalUnitCount() < 2) {
      PlayerVehicleEnum e(p);
      UnitEx u;
      while (e.GetNext(u)) {
        if (u.GetType() != mapCargoTruck || u.IsBusy()) continue;
        bool vergeben = false;
        for (int i = 0; i < MAX_MINEN && !vergeben; ++i) {
          if (!z.minenId[i]) continue;
          GroupEnumerator ge(z.minenGruppe[i]);
          Unit v;
          while (ge.GetNext(v)) if (v.unitID == u.unitID) { vergeben = true; break; }
        }
        if (vergeben) continue;
        z.minenGruppe[g].TakeUnit(u);
        melde(z, "mine", mapCargoTruck, edX(z, u.Location()), edY(z, u.Location()), "Lastwagen %d faehrt Erz", u.unitID);
        break;
      }
    }
  }
}

// ---------------------------------------------------------------------------------------------------
// Fahrzeugfabrik / vehicle factory

inline void fahrzeuge(Zustand& z, const Lage& l) {
  if (!l.vf.unitID) return;
  UnitEx vf = l.vf;
  const int t = TethysGame::Tick();
  if (z.fzTyp) {
    if (t - z.fzSeit > 100 && t - z.fzSeit < 100 + TAKT + 1 && vf.GetCurAction() != moDevelop && !vf.IsBusy()) {
      melde(z, "warte", z.fzTyp, edX(z, vf.Location()), edY(z, vf.Location()),
            "Fahrzeugfabrik nimmt den Auftrag nicht an (Strom %d, Arbeiter %d) -- in 500 Ticks erneut",
            vf.HasPower(), vf.HasWorkers());
      z.fzTyp = 0; z.fzPauseBis = t + 500;
      return;
    }
    if (vf.GetCurAction() == moDevelop || vf.IsBusy()) {
      if (t - z.fzSeit > GEDULD_KIT) { melde(z, "fehler", z.fzTyp, edX(z, vf.Location()), edY(z, vf.Location()), "Fahrzeug dauert zu lange"); z.fzTyp = 0; }
      return;
    }
    z.fzTyp = 0;
  }
  if (vf.IsBusy() || t < z.fzPauseBis) return;
  int typ = mapNone; const char* warum = "";
  int minen = l.geb[mapCommonOreMine];
  if (l.fz[mapConVec] < 2) { typ = mapConVec; warum = "weniger als 2 ConVecs"; }
  else if (l.fz[mapEarthworker] < 1) { typ = mapEarthworker; warum = "Roehren brauchen einen Earthworker"; }
  else if (l.fz[mapCargoTruck] < 2 * (minen > 0 ? minen : 1) && l.fz[mapCargoTruck] < 2 * MAX_MINEN) { typ = mapCargoTruck; warum = "zwei Lastwagen je Mine"; }
  else if (l.fz[mapRoboSurveyor] < 1) { typ = mapRoboSurveyor; warum = "Baken vermessen"; }
  else if (l.fz[mapRoboMiner] < 1 && minen < 2) { typ = mapRoboMiner; warum = "zweite Mine"; }
  else if (l.fz[mapConVec] < 3 && l.erz > 3000) { typ = mapConVec; warum = "Erz uebrig, schneller bauen"; }
  if (typ == mapNone) return;
  UnitInfo info((map_id)typ);
  const int kosten = info.GetOreCost(z.spieler);
  if (kosten > l.erz) {
    if (selten(z, 2, 1500)) melde(z, "warte", typ, edX(z, vf.Location()), edY(z, vf.Location()), "Erz %d, Fahrzeug kostet %d", l.erz, kosten);
    return;
  }
  vf.DoProduce((map_id)typ, mapNone);
  z.fzTyp = typ; z.fzSeit = t;
  melde(z, "fahrzeug", typ, edX(z, vf.Location()), edY(z, vf.Location()), "%s", warum);
}

// ---------------------------------------------------------------------------------------------------
// Forschung / research: freie Labore suchen sich ein Thema
// Ob DoResearch die techID oder den Tabellenindex will, ist nicht sicher dokumentiert -- die KI prueft
// nach dem ersten Auftrag, ob das Labor arbeitet, und wechselt sonst die Lesart (steht in der Spur).

inline int laborTyp(int unitTyp) {
  return unitTyp == mapBasicLab ? ltBasic : unitTyp == mapStandardLab ? ltStandard : unitTyp == mapAdvancedLab ? ltAdvanced : 0;
}

inline int themaWaehlen(const Zustand& z, int lab, char* name, int n) {
  static const int vorrang[] = { tcFood, tcMetals, tcPower, tcPopulation, tcMorale, tcBasic, tcVehicles, tcDefense, tcDisaster, tcWeapons, tcSpace };
  const int anzahl = Research::GetTechCount();
  int besteIdx = -1, besterRang = 99, besteKosten = 1 << 30;
  for (int i = 0; i < anzahl; ++i) {
    TechInfo ti = Research::GetTechInfo(i);
    if (!ti.IsValid()) continue;
    if (ti.GetPlayerHasTech() & (1 << z.spieler)) continue;
    if ((int)ti.GetLab() != lab) continue;
    const int kosten = Player[z.spieler].IsEden() ? ti.GetEdenCost() : ti.GetPlymouthCost();
    if (kosten <= 0) continue;                                     // 0 = frei, -1 = nicht erforschbar
    bool voraussetzungen = true;
    for (int r = 0; r < ti.GetNumRequiredTechs() && voraussetzungen; ++r) {
      TechInfo req = Research::GetTechInfo(ti.GetRequiredTechIndex(r));
      if (!req.IsValid() || !(req.GetPlayerHasTech() & (1 << z.spieler))) voraussetzungen = false;
    }
    if (!voraussetzungen) continue;
    int rang = 50;
    for (int k = 0; k < (int)(sizeof(vorrang) / sizeof(vorrang[0])); ++k) if (vorrang[k] == (int)ti.GetCategory()) { rang = k; break; }
    if (rang < besterRang || (rang == besterRang && kosten < besteKosten)) { besteIdx = i; besterRang = rang; besteKosten = kosten; }
  }
  if (besteIdx >= 0) {
    const char* nm = Research::GetTechInfo(besteIdx).GetTechName();
    std::snprintf(name, n, "%s", nm ? nm : "?");
  }
  return besteIdx;
}

inline void forschung(Zustand& z) {
  const int t = TethysGame::Tick();
  // Kalibrierung: hat der letzte Auftrag ein Thema gestartet?
  if (z.forschungLab && t - z.forschungSeit > 60) {
    UnitEx lab; lab.unitID = z.forschungLab;
    if (lab.IsLive() && !lab.HasPower()) {
      melde(z, "info", lab.GetType(), z.bx, z.by, "Labor ohne Strom -- Lesart von DoResearch noch offen");
    } else if (lab.IsLive()) {
      const int thema = lab.GetLabCurrentTopic();
      if (thema <= 0 && lab.GetCurAction() != moDoResearch) {
        z.forschungModus = 1 - z.forschungModus;
        melde(z, "info", lab.GetType(), z.bx, z.by,
              "Labor hat nicht angefangen -- DoResearch nimmt jetzt den %s", z.forschungModus ? "Tabellenindex" : "techID");
      } else {
        melde(z, "info", lab.GetType(), z.bx, z.by, "Forschung laeuft (Thema %d, Lesart %s)", thema, z.forschungModus ? "Index" : "techID");
      }
    }
    z.forschungLab = 0;
  }
  const int typen[] = { mapBasicLab, mapStandardLab, mapAdvancedLab };
  for (int typ : typen) {
    PlayerBuildingEnum e(z.spieler, (map_id)typ);
    UnitEx lab;
    while (e.GetNext(lab)) {
      if (lab.IsBusy() || lab.GetCurAction() == moDoResearch || lab.GetLabCurrentTopic() > 0) continue;
      if (!lab.HasPower()) {
        if (selten(z, 7, 3000)) melde(z, "warte", typ, edX(z, lab.Location()), edY(z, lab.Location()), "Labor ohne Strom");
        continue;
      }
      char nm[96];
      const int idx = themaWaehlen(z, laborTyp(typ), nm, sizeof(nm));
      if (idx < 0) {
        if (selten(z, 3, 6000)) melde(z, "warte", typ, edX(z, lab.Location()), edY(z, lab.Location()), "kein erforschbares Thema fuer dieses Labor");
        continue;
      }
      TechInfo ti = Research::GetTechInfo(idx);
      int wiss = ExtPlayer[z.spieler].GetNumAvailableScientists();
      if (wiss > ti.GetMaxScientists()) wiss = ti.GetMaxScientists();
      if (wiss <= 0) {
        if (selten(z, 4, 3000)) melde(z, "warte", typ, edX(z, lab.Location()), edY(z, lab.Location()), "keine freien Wissenschaftler fuer %s", nm);
        continue;
      }
      const int wert = z.forschungModus ? idx : ti.GetTechID();
      lab.DoResearch(wert, wiss);
      z.forschungLab = lab.unitID; z.forschungWert = wert; z.forschungSeit = t;
      melde(z, "forschung", typ, edX(z, lab.Location()), edY(z, lab.Location()), "%s (Tech %d, %d Wissenschaftler)", nm, ti.GetTechID(), wiss);
      return;                                                         // ein Auftrag je Schritt
    }
  }
}

// ---------------------------------------------------------------------------------------------------
// Momentaufnahme / snapshot

inline void spur(const Zustand& z, const Lage& l) {
  Puffer p;
  const int pl = z.spieler;
  p.f("{\"t\":%d,\"art\":\"stand\",\"p\":%d,\"erz\":%d,\"erzMax\":%d,\"selten\":%d,\"nahrung\":%d,\"nahrungNetto\":%d,"
      "\"strom\":[%d,%d],\"kinder\":%d,\"arbeiter\":%d,\"wiss\":%d,\"wohnraum\":%d,\"moral\":%d",
      TethysGame::Tick(), pl, l.erz, l.erzMax, Player[pl].RareOre(), l.nahrung, l.nahrungNetto,
      ExtPlayer[pl].GetAmountPowerGenerated(), ExtPlayer[pl].GetAmountPowerConsumed(),
      Player[pl].Kids(), Player[pl].Workers(), Player[pl].Scientists(), l.wohnraum, (int)Player[pl].MoraleLevel());
  p.roh(",\"geb\":[");
  {
    bool erst = true; int k = 0;
    for (int t : GEBAEUDE) {
      PlayerBuildingEnum e(pl, (map_id)t);
      UnitEx u;
      while (e.GetNext(u) && k++ < 120) {
        const LOCATION lo = u.Location();
        p.f("%s[\"%s\",%d,%d,%d]", erst ? "" : ",", name(t), edX(z, lo), edY(z, lo), u.IsBusy() ? 1 : 0);
        erst = false;
      }
    }
  }
  p.roh("],\"fz\":[");
  {
    PlayerVehicleEnum e(pl);
    UnitEx u; bool erst = true; int k = 0;
    while (e.GetNext(u) && k++ < 120) {
      const LOCATION lo = u.Location();
      p.f("%s[\"%s\",%d,%d,\"%s\",%d,%d]", erst ? "" : ",", name(u.GetType()), edX(z, lo), edY(z, lo),
          name(u.GetCargo()), (int)u.GetCurAction(), u.unitID);
      erst = false;
    }
  }
  p.roh("],\"plaetze\":[");
  for (int i = 0; i < z.anzahlPlaetze; ++i) {
    const Platz& q = z.plaetze[i];
    const Groesse g = grundflaeche(q.typ);
    p.f("%s[\"%s\",%d,%d,%d,%d,%d]", i ? "," : "", name(q.typ), q.x0, q.y0, g.w, g.h, (int)q.zustand);
  }
  p.roh("],\"roehren\":[");
  for (int i = 0; i < z.anzahlRoehren; ++i) {
    const Roehre& r = z.roehren[i];
    p.f("%s[%d,%d,%d,%d,%d]", i ? "," : "", r.x1, r.y1, r.x2, r.y2, (int)r.zustand);
  }
  p.roh("]}");
  p.schreiben();
}

// ---------------------------------------------------------------------------------------------------
// Oeffentliche Schnittstelle / public interface

// Startausruestung "von null": ConVecs mit Bausaetzen, Bergbau- und Hilfsfahrzeuge um (x, y).
inline void startausruestung(const Zustand& z, int x, int y) {
  struct Teil { int typ, fracht, dx, dy; };
  static const Teil teile[] = {
    { mapConVec, mapCommandCenter, 0, 0 },      { mapConVec, mapStructureFactory, 1, 0 },
    { mapConVec, mapTokamak, 2, 0 },            { mapConVec, mapCommonOreSmelter, -1, 0 },
    { mapConVec, mapAgridome, 0, 1 },           { mapRoboMiner, mapNone, 1, 1 },
    { mapRoboSurveyor, mapNone, 2, 1 },         { mapCargoTruck, mapNone, -1, 1 },
    { mapCargoTruck, mapNone, -2, 1 },          { mapEarthworker, mapNone, -2, 0 },
  };
  Unit u;
  for (const Teil& t : teile)
    // Abseits der Basis parken: stehende Fahrzeuge blockieren Bauplaetze.
    TethysGame::CreateUnit(u, (map_id)t.typ, engine(z, x + 2 * t.dx, y + 9 + t.dy), z.spieler, (map_id)t.fracht, 0);
}

// Ohne gewoehnliche Erz-Bake in Reichweite der Basis zwei anlegen (Teil der Startausruestung --
// Baken kommen sonst aus dem Missionsskript, die Karte selbst hat keine).
// Without a common ore beacon near the base, create two (part of the start equipment).
inline void bakenSichern(Zustand& z) {
  BakenFund f = bakeSuchen(z);
  UnitEx b = f.beste;
  if (b.unitID && abstand2(edX(z, b.Location()), edY(z, b.Location()), z.bx, z.by) < 40 * 40) return;
  int gesetzt = 0;
  for (int r = 12; r <= 30 && gesetzt < 2; r += 3)
    for (int k = 0; k < 16 && gesetzt < 2; ++k) {
      static const int RX[16] = { 1, 1, 0, -1, -1, -1, 0, 1, 1, 0, -1, 0, 1, -1, 1, -1 };
      static const int RY[16] = { 0, 1, 1, 1, 0, -1, -1, -1, 0, 1, 0, -1, 1, 1, -1, -1 };
      const int x = z.bx + RX[k] * r, y = z.by + RY[k] * r + 2;
      if (!aufKarte(z, x - 2, y - 2, 3) || !aufKarte(z, x + 2, y + 2, 3)) continue;
      bool frei = true;
      for (int yy = y - 1; yy <= y + 1 && frei; ++yy)
        for (int xx = x - 2; xx <= x + 2 && frei; ++xx) if (!zelleBebaubar(zelle(z, xx, yy))) frei = false;
      if (!frei) continue;
      const LOCATION l = engine(z, x, y);
      TethysGame::CreateBeacon(mapMiningBeacon, l.x, l.y, OreTypeCommon, gesetzt == 0 ? Bar2 : Bar3, VariantRandom);
      if (z.anzahlBaken < 4) { z.bakenX[z.anzahlBaken] = x; z.bakenY[z.anzahlBaken] = y; z.anzahlBaken++; }
      melde(z, "info", mapMiningBeacon, x, y, "keine Erz-Bake nahe der Basis -- Bake angelegt (Startausruestung)");
      gesetzt++;
      k += 7;                                                   // zweite Bake in eine andere Richtung
    }
}

// Einmal in InitProc. `ursprung` = Engine-Koordinate der Editor-Kachel (0,0), z.B. MkXY(1, 1).
inline void start(Zustand& z, int spieler, LOCATION ursprung, int breite, int hoehe, int x, int y, bool ausruestung) {
  std::memset(&z.plaetze, 0, sizeof(z.plaetze));
  std::memset(&z.roehren, 0, sizeof(z.roehren));
  z.aktiv = 1; z.spieler = spieler;
  z.ux = ursprung.x; z.uy = ursprung.y;
  z.breite = breite; z.hoehe = hoehe;
  z.bx = x; z.by = y;
  z.naechsterSchritt = 0; z.naechsteSpur = 0;
  z.forschungModus = 0; z.forschungLab = 0;
  z.kitTyp = 0; z.fzTyp = 0; z.anzahlPlaetze = 0; z.anzahlRoehren = 0;
  z.kitPauseBis = 0; z.fzPauseBis = 0;
  for (int i = 0; i < 8; ++i) { z.kitGesperrtTyp[i] = 0; z.kitGesperrtBis[i] = 0; }
  for (int i = 0; i < 16; ++i) z.meldungenSeit[i] = 0;
  for (int i = 0; i < MAX_MINEN; ++i) { z.minenId[i] = 0; z.schmelzeId[i] = 0; }
  z.bakeZiel = 0; z.bakeMiner = 0; z.bakeSeit = 0; z.minerSeit = 0; z.anzahlBaken = 0;
  Puffer p;
  p.f("{\"t\":%d,\"art\":\"start\",\"p\":%d,\"breite\":%d,\"hoehe\":%d,\"bx\":%d,\"by\":%d,\"ux\":%d,\"uy\":%d,\"eden\":%d}",
      TethysGame::Tick(), spieler, breite, hoehe, x, y, z.ux, z.uy, Player[spieler].IsEden() ? 1 : 0);
  p.schreiben();
  if (ausruestung) {
    startausruestung(z, x, y);
    bakenSichern(z);
  }
}

// Jeden AIProc-Aufruf; arbeitet intern im Takt.
inline void schritt(Zustand& z) {
  if (!z.aktiv) return;
  const int t = TethysGame::Tick();
  if (t < z.naechsterSchritt) return;
  z.naechsterSchritt = t + TAKT;
  Lage l;
  erhebe(z, l);
  // Ohne Kommandozentrale: der ConVec mit dem CC-Bausatz baut auf dem Mittelplatz.
  convecs(z, l);
  fabrik(z, l);
  fahrzeuge(z, l);
  erz(z, l);
  roehren(z);
  forschung(z);
  if (t >= z.naechsteSpur) {
    z.naechsteSpur = t + SPUR_TAKT;
    spur(z, l);
  }
}

} // namespace ki
