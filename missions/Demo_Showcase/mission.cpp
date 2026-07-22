// mission.cpp -- generated from the editor model for: Demo Showcase
// Built against OP2MissionSDK (Outpost2DLL + OP2Helper + HFL).
// https://github.com/OutpostUniverse/OP2MissionSDK

#include <Outpost2DLL/Outpost2DLL.h>
#include <OP2Helper/OP2Helper.h>
#include <HFL/Source/HFL.h>
#include "op2_log.hpp"
#include "op2_crash.hpp"

static const int kTicksPerMark = 100;

static const int kDiff[] = {5, 10, 13};
static int diff = 10;

static int randBetween(int minValue, int maxValue) {
    if (maxValue < minValue) { int _t = minValue; minValue = maxValue; maxValue = _t; }
    return minValue + TethysGame::GetRand(maxValue - minValue + 1);
}

// Erste Einheit auf einer Kachel (LOCATION in Engine-Koordinaten, MkXY).
// First unit on a tile (LOCATION in engine coordinates, MkXY).
static UnitEx unitOnTile(LOCATION where) {
    LocationEnumerator _e(where);
    UnitEx _u;
    if (_e.GetNext(_u)) return _u;
    return UnitEx();
}

// Einheit eines Typs/Spielers auf einer Kachel (fuer Fahrzeug-Capture).
// Unit of a type/player on a tile (for vehicle capture).
static UnitEx findUnitAt(LOCATION where, map_id type, int owner) {
    LocationEnumerator _e(where);
    UnitEx _u;
    while (_e.GetNext(_u)) {
        if (_u.GetType() == type && _u.OwnerID() == owner) return _u;
    }
    return UnitEx();
}

static int countUnitsOfType(int playerNum, map_id type) {
    int _n = 0;
    PlayerUnitEnum _e(playerNum);
    UnitEx _u;
    while (_e.GetNext(_u)) if (_u.GetType() == type) ++_n;
    return _n;
}

// Fertig UND ruhig? WHITELIST auf moDone: alles andere (moDevelop =
// im Bau, moOperationalWait = wartet auf Inbetriebnahme, HFL-Sentinels
// bei nicht initialisiertem HFL) zaehlt als NICHT bereit -- ein
// TakeUnit in diesen Zustaenden macht das Gebaeude kaputt.
// Finished AND quiet? WHITELIST on moDone: anything else (moDevelop =
// under construction, moOperationalWait = waiting to go operational,
// HFL sentinels when HFL is not initialized) counts as NOT ready --
// a TakeUnit in those states corrupts the building.
static bool isCompleted(UnitEx u) {
    if (u.unitID == 0 || !u.IsLive()) return false;
    return u.GetCurAction() == moDone;
}

struct MissionSave {
    bool _mining_armed_0 = false;
    int _mining_ids_0[2] = { 0, 0 };
    bool _repair_armed_0 = false;
    BuildingGroup _grp_0_BuildingGroup1;
    BuildingGroup _grp_1_RebuildMines;
    BuildingGroup _grp_2_Reparatur;
    BuildingGroup _grp_3_ReinforceGroup1;
    FightGroup _grp_4_def;
    MiningGroup _grp_5_MiningGroup1;
    UnitEx _unit_struck;
    UnitEx _unit_veh;
    UnitEx _unit_Smelter1;
    UnitEx _unit_spider;
    UnitEx _unit_space;
    UnitEx _unit_test;
    UnitEx _unit_Mine1;
};
static MissionSave g_save;

static bool& _mining_armed_0 = g_save._mining_armed_0;
static int (&_mining_ids_0)[2] = g_save._mining_ids_0;
static bool& _repair_armed_0 = g_save._repair_armed_0;
static BuildingGroup& _grp_0_BuildingGroup1 = g_save._grp_0_BuildingGroup1;
static BuildingGroup& _grp_1_RebuildMines = g_save._grp_1_RebuildMines;
static BuildingGroup& _grp_2_Reparatur = g_save._grp_2_Reparatur;
static BuildingGroup& _grp_3_ReinforceGroup1 = g_save._grp_3_ReinforceGroup1;
static FightGroup& _grp_4_def = g_save._grp_4_def;
static MiningGroup& _grp_5_MiningGroup1 = g_save._grp_5_MiningGroup1;
static UnitEx& _unit_struck = g_save._unit_struck;
static UnitEx& _unit_veh = g_save._unit_veh;
static UnitEx& _unit_Smelter1 = g_save._unit_Smelter1;
static UnitEx& _unit_spider = g_save._unit_spider;
static UnitEx& _unit_space = g_save._unit_space;
static UnitEx& _unit_test = g_save._unit_test;
static UnitEx& _unit_Mine1 = g_save._unit_Mine1;

static UnitEx _boot_0;
static UnitEx _boot_1;
static UnitEx _boot_2;

Export void NoResponseToTrigger() {}

static void _trigger_0_Intro();
static void _trigger_1_Bergbau();
static void _trigger_2_Reparatur();
static void _trigger_3_Meteor();
static void _trigger_4_Angriffswelle();
static void _trigger_5_EMP_Rakete();
static void _trigger_6_Uebergabe();

ExportLevelDetailsFull("Demo Showcase", "cm02.map", "MULTITEK.TXT", Colony, 2, 12, 0)
Export const AIModDescEx DescBlockEx = { 0 };

// Vor-Spielstart-Briefing (briefing_dialog.cpp + briefing.rc):
// modaler Dialog waehrend der Missions-Initialisierung.
// Pre-game briefing (briefing_dialog.cpp + briefing.rc):
// modal dialog during mission initialization.
extern void ShowBriefing();
extern void* g_briefing_hinst;

static void initProc() {
    // Briefing VOR dem Spielstart anzeigen (blockiert bis CONTINUE).
    // Show the briefing BEFORE game start (blocks until CONTINUE).
    ShowBriefing();
    op2::log::line("InitProc: starting");
    if (HFLInit() != HFLLOADED) {
        op2::log::line("InitProc: HFLInit FAILED");
    }
    diff = kDiff[Player[0].Difficulty()];

    // --- Player 0 ---
    Player[0].GoEden();
    Player[0].GoHuman();
    Player[0].SetTechLevel(12);

    // --- Player 1 ---
    Player[1].GoPlymouth();
    Player[1].GoAI();
    Player[1].SetTechLevel(12);
    Player[1].SetOre(8000);
    Player[1].SetRareOre(8000);
    Player[1].SetFoodStored(99999);


    // --- Base layout for player 0 ---
    {
        Unit _u;
        TethysGame::CreateBeacon(mapMiningBeacon, XYPos(49, 16), OreTypeRandom, BarRandom, VariantRandom);
        TethysGame::CreateBeacon(mapMiningBeacon, XYPos(49, 21), OreTypeRandom, BarRandom, VariantRandom);
        TethysGame::CreateUnit(_u, mapLynx, MkXY(20, 2), 0, mapStarflare, East);
        TethysGame::CreateUnit(_u, mapLynx, MkXY(19, 2), 0, mapStarflare, East);
        TethysGame::CreateUnit(_u, mapLynx, MkXY(17, 2), 0, mapStarflare, East);
        TethysGame::CreateUnit(_u, mapLynx, MkXY(18, 2), 0, mapStarflare, East);
        TethysGame::CreateUnit(_u, mapLynx, MkXY(16, 2), 0, mapStarflare, East);
        TethysGame::CreateUnit(_u, mapLynx, MkXY(15, 2), 0, mapStarflare, East);
        TethysGame::CreateUnit(_u, mapLynx, MkXY(14, 2), 0, mapStarflare, East);
    }

    // --- Base layout for player 1 ---
    {
        Unit _u;
        TethysGame::CreateUnit(_u, mapCommandCenter, MkXY(38, 12), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapTokamak, MkXY(44, 6), 1, mapNone, 0);
        TethysGame::CreateUnit(_unit_struck, mapStructureFactory, MkXY(38, 15), 1, mapNone, 0);
        TethysGame::CreateUnit(_unit_veh, mapVehicleFactory, MkXY(34, 11), 1, mapNone, 0);
        TethysGame::CreateUnit(_unit_Smelter1, mapCommonOreSmelter, MkXY(39, 8), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapGORF, MkXY(29, 12), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapLightTower, MkXY(47, 13), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapMedicalCenter, MkXY(30, 9), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(44, 20), 1, mapRPG, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(54, 19), 1, mapRPG, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(54, 13), 1, mapRPG, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(54, 8), 1, mapRPG, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(42, 20), 1, mapRPG, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(46, 20), 1, mapEMP, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(52, 19), 1, mapEMP, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(54, 16), 1, mapEMP, 0);
        TethysGame::CreateUnit(_u, mapGuardPost, MkXY(54, 10), 1, mapEMP, 0);
        TethysGame::CreateUnit(_u, mapTokamak, MkXY(33, 16), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapRareOreSmelter, MkXY(29, 15), 1, mapNone, 0);
        TethysGame::CreateUnit(_boot_2, mapArachnidFactory, MkXY(39, 5), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapMHDGenerator, MkXY(47, 6), 1, mapNone, 0);
        TethysGame::CreateUnit(_unit_space, mapSpaceport, MkXY(28, 20), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapCommandCenter, MkXY(85, 11), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapAgridome, MkXY(81, 11), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapResidence, MkXY(81, 14), 1, mapNone, 0);
        TethysGame::CreateUnit(_unit_test, mapStructureFactory, MkXY(85, 14), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapTokamak, MkXY(90, 8), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapUniversity, MkXY(81, 8), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapNursery, MkXY(84, 8), 1, mapNone, 0);
        TethysGame::CreateUnit(_u, mapCargoTruck, MkXY(46, 9), 1, mapNone, East);
        TethysGame::CreateUnit(_u, mapCargoTruck, MkXY(47, 9), 1, mapNone, East);
        TethysGame::CreateUnit(_boot_0, mapConVec, MkXY(42, 10), 1, mapNone, East);
        TethysGame::CreateUnit(_unit_spider, mapSpider, MkXY(43, 13), 1, mapNone, East);
        TethysGame::CreateUnit(_boot_1, mapEarthworker, MkXY(43, 10), 1, mapNone, East);
        TethysGame::CreateUnit(_u, mapSpider3Pack, MkXY(44, 16), 1, mapNone, East);
    }

    // --- Groups (building / reinforce / fight / mining) ---
    _grp_0_BuildingGroup1 = CreateBuildingGroup(Player[1]);
    { MAP_RECT _r = MkRect(46, 5, 49, 7); _grp_0_BuildingGroup1.SetRect(_r); }
    // Einheiten der BuildingGroup 'BuildingGroup1' zuweisen
    if (_unit_struck.unitID != 0) _grp_0_BuildingGroup1.TakeUnit(_unit_struck);
    if (_boot_0.unitID != 0) _grp_0_BuildingGroup1.TakeUnit(_boot_0);
    if (_boot_1.unitID != 0) _grp_0_BuildingGroup1.TakeUnit(_boot_1);
    _grp_0_BuildingGroup1.SetTargCount(mapConVec, mapNone, 1);
    _grp_0_BuildingGroup1.SetTargCount(mapEarthworker, mapNone, 1);
    {
        LOCATION _l;
        _l = MkXY(38, 15);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapStructureFactory, mapNone);
        _l = MkXY(38, 12);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapCommandCenter, mapNone);
        _l = MkXY(44, 6);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapTokamak, mapNone);
        _l = MkXY(34, 11);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapVehicleFactory, mapNone);
        _l = MkXY(39, 8);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapCommonOreSmelter, mapNone);
        _l = MkXY(29, 12);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGORF, mapNone);
        _l = MkXY(47, 13);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapLightTower, mapNone);
        _l = MkXY(30, 9);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapMedicalCenter, mapNone);
        _l = MkXY(44, 20);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapRPG);
        _l = MkXY(54, 19);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapRPG);
        _l = MkXY(54, 13);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapRPG);
        _l = MkXY(54, 8);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapRPG);
        _l = MkXY(42, 20);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapRPG);
        _l = MkXY(46, 20);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapEMP);
        _l = MkXY(52, 19);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapEMP);
        _l = MkXY(54, 16);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapEMP);
        _l = MkXY(54, 10);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapGuardPost, mapEMP);
        _l = MkXY(33, 16);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapTokamak, mapNone);
        _l = MkXY(29, 15);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapRareOreSmelter, mapNone);
        _l = MkXY(39, 5);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapArachnidFactory, mapNone);
        _l = MkXY(47, 6);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapMHDGenerator, mapNone);
        _l = MkXY(28, 20);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapSpaceport, mapNone);
        _l = MkXY(85, 11);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapCommandCenter, mapNone);
        _l = MkXY(81, 11);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapAgridome, mapNone);
        _l = MkXY(81, 14);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapResidence, mapNone);
        _l = MkXY(85, 14);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapStructureFactory, mapNone);
        _l = MkXY(90, 8);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapTokamak, mapNone);
        _l = MkXY(81, 8);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapUniversity, mapNone);
        _l = MkXY(84, 8);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapNursery, mapNone);
    }
    op2::log::linef("InitProc: BuildingGroup 'BuildingGroup1' -> %d Einheiten", _grp_0_BuildingGroup1.TotalUnitCount());
    _grp_1_RebuildMines = CreateBuildingGroup(Player[1]);
    { MAP_RECT _r = MkRect(50, 5, 52, 7); _grp_1_RebuildMines.SetRect(_r); }
    op2::log::linef("InitProc: BuildingGroup 'RebuildMines' -> %d Einheiten", _grp_1_RebuildMines.TotalUnitCount());
    _grp_2_Reparatur = CreateBuildingGroup(Player[1]);
    { MAP_RECT _r = MkRect(42, 12, 45, 15); _grp_2_Reparatur.SetRect(_r); }
    // Einheiten der BuildingGroup 'Reparatur' zuweisen
    if (_unit_spider.unitID != 0) _grp_2_Reparatur.TakeUnit(_unit_spider);
    _grp_2_Reparatur.SetTargCount(mapSpider, mapNone, 1);
    op2::log::linef("InitProc: BuildingGroup 'Reparatur' -> %d Einheiten", _grp_2_Reparatur.TotalUnitCount());
    _grp_3_ReinforceGroup1 = CreateBuildingGroup(Player[1]);
    // Einheiten der ReinforceGroup 'ReinforceGroup1' zuweisen
    if (_unit_veh.unitID != 0) _grp_3_ReinforceGroup1.TakeUnit(_unit_veh);
    if (_boot_2.unitID != 0) _grp_3_ReinforceGroup1.TakeUnit(_boot_2);
    _grp_3_ReinforceGroup1.RecordVehReinforceGroup(_grp_0_BuildingGroup1, 1500);
    _grp_4_def = CreateFightGroup(Player[1]);
    { MAP_RECT _r = MkRect(23, 2, 59, 27); _grp_4_def.SetRect(_r); }
    _grp_5_MiningGroup1 = CreateMiningGroup(Player[1]);

    // --- Gruppen-Reparatur: zerstoerte, von der Engine an derselben
    // Stelle wieder errichtete Gebaeude automatisch neu zuweisen/
    // verknuepfen (ein einziger wiederkehrender Timer). ---
    CreateTimeTrigger(1, 0, kTicksPerMark, "_repairGroups_cb");

    AddGameMessage("Demo Showcase - der OP2 Mission Editor stellt sich vor.");

    // --- Victory conditions ---
    Trigger _v_27973 = CreateBuildingCountTrigger(1, 1, 0, 5, cmpGreaterEqual, "NoResponseToTrigger");
    CreateVictoryCondition(1, 0, _v_27973, "Uebernehmt die Ost-Kolonie (Marke 20 abwarten).");

    // --- Defeat conditions ---
    Trigger _v_59529 = CreateVehicleCountTrigger(1, 1, 0, 0, cmpLowerEqual, "NoResponseToTrigger");
    CreateFailureCondition(1, 0, _v_59529, "");

    // --- Custom triggers (enabled at start) ---
    _trigger_0_Intro();
    _trigger_1_Bergbau();
    _trigger_2_Reparatur();
    _trigger_3_Meteor();
    _trigger_4_Angriffswelle();
    _trigger_5_EMP_Rakete();
    _trigger_6_Uebergabe();

    TethysGame::ForceMoraleGood(PlayerNum::PlayerAll);
    op2::log::line("InitProc: done");
}

// Trigger 'Intro' (condition=time)
// Begruessung als Dialogbox + eigene Musik-Playlist
Export void _trigger_0_Intro_cb() {
    // In-Game-Dialogbox (TethysGameEx::MsgBox)
    TethysGameEx::MsgBox(NULL, "Willkommen in der Demo-Mission!\n\nBeobachtet die Plymouth-Kolonie im Zentrum - sie verwaltet sich ab jetzt selbst. Alle Ereignisse werden per Dialog und Nachricht angekuendigt.", "Leitstand", MB_OK | MB_ICONINFORMATION);
    // Playlist: 2x Plymouth, dann EP41 im Loop
    {
        static SongIds _songs[] = { songPlymth11, songPlymth21, songEP41 };
        TethysGame::SetMusicPlayList(3, 0, _songs);
    }
}
static void _trigger_0_Intro() {
    CreateTimeTrigger(1, 1, (2) * kTicksPerMark, "_trigger_0_Intro_cb");
}

// Trigger 'Bergbau' (condition=time)
// Mine als geplantes Gebaeude (Anker Mine1) + Makro: Gruppe wird scharf und startet, sobald Mine+Smelter stehen
Export void _trigger_1_Bergbau_cb() {
    AddGameMessage("Die Kolonie errichtet ihre Erzmine...");
    // Benannter Anker Mine1 - findet die Mine auch nach Zerstoerung und Wiederaufbau
    {
        LOCATION _l;
        _l = MkXY(49, 16);
        _grp_1_RebuildMines.RecordBuilding(_l, mapCommonOreMine, mapNone);
        op2::log::linef("RecordBuilding: mapCommonOreMine @ (48,15) -> Gruppe mit %d Einheiten", _grp_1_RebuildMines.TotalUnitCount());
    }
    // Robo-Miner-Sollstaerke; Fabrik liefert nach
    _grp_1_RebuildMines.SetTargCount(mapRoboMiner, mapNone, 1);
    _grp_3_ReinforceGroup1.RecordVehReinforceGroup(_grp_1_RebuildMines, 1000);
    // 2 Trucks; Mine/Smelter kommen als Anker von der Gruppe
    _mining_armed_0 = true;
}
static void _trigger_1_Bergbau() {
    CreateTimeTrigger(1, 1, (3) * kTicksPerMark, "_trigger_1_Bergbau_cb");
}

// Trigger 'Reparatur' (condition=time)
// Reparatur-Makro: Zone = ganze Basis, Tokamak erst ab 150 Schaden
Export void _trigger_2_Reparatur_cb() {
    // Plymouth-Spezialist Spider repariert, ConVec hilft aus
    _repair_armed_0 = true;
}
static void _trigger_2_Reparatur() {
    CreateTimeTrigger(1, 1, (4) * kTicksPerMark, "_trigger_2_Reparatur_cb");
}

// Trigger 'Meteor' (condition=time)
// Katastrophe + anschliessender Wiederaufbau durch record_all
Export void _trigger_3_Meteor_cb() {
    TethysGameEx::MsgBox(NULL, "Meteoreinschlag im Anflug auf die Kolonie!\n\nBeobachtet, wie zerstoerte Gebaeude exakt an derselben Stelle wieder aufgebaut werden.", "Warnung", MB_OK | MB_ICONINFORMATION);
    // Grosser Meteor mitten in die Basis
    TethysGame::SetMeteor(XYPos((int((40) + 1)), (int((10) + 1))), 2);
}
static void _trigger_3_Meteor() {
    CreateTimeTrigger(1, 1, (8) * kTicksPerMark, "_trigger_3_Meteor_cb");
}

// Trigger 'Angriffswelle' (condition=time)
// Spawn-Welle: 3 Microwave-Lynx sammeln sich und greifen an
Export void _trigger_4_Angriffswelle_cb() {
    TethysGameEx::MsgBox(NULL, "Feindliche Fahrzeuge naehern sich eurer Position von Osten!", "Warnung", MB_OK | MB_ICONINFORMATION);
    // Spawn bei (24,2), Angriffsbereich = Spielertruppe
    {
        MAP_RECT _r = MkRect(25, 3, 27, 4);
        _grp_4_def.SetRect(_r);
        for (int _i = 0; _i < 3; ++_i) {
            Unit _u;
            if (TethysGame::CreateUnit(_u, mapLynx, MkXY(25 + (_i % 3), 3 + (_i / 3)), 1, mapMicrowave, 0)) _grp_4_def.TakeUnit(_u);
        }
        MAP_RECT _ar = MkRect(13, 1, 21, 5);
        _grp_4_def.SetAttackType(mapAny);
        _grp_4_def.ClearGuarderdRects();
        _grp_4_def.AddGuardedRect(_ar);
        _grp_4_def.DoGuardRect();
    }
}
static void _trigger_4_Angriffswelle() {
    CreateTimeTrigger(1, 1, (12) * kTicksPerMark, "_trigger_4_Angriffswelle_cb");
}

// Trigger 'EMP-Rakete' (condition=time)
// SetEMPMissile: Start off-screen, Ziel Spielertruppe (nur Plymouth)
Export void _trigger_5_EMP_Rakete_cb() {
    TethysGameEx::MsgBox(NULL, "EMP-Raketenstart geortet! Eure Fahrzeuge werden kurz lahmgelegt.", "Warnung", MB_OK | MB_ICONINFORMATION);
    TethysGame::SetEMPMissile(XYPos(1, 25), 1, XYPos(17, 3));
}
static void _trigger_5_EMP_Rakete() {
    CreateTimeTrigger(1, 1, (16) * kTicksPerMark, "_trigger_5_EMP_Rakete_cb");
}

// Trigger 'Uebergabe' (condition=time)
// forEach-Schleife ueber alle Gebaeude der KI im Ost-Rechteck -> Uebergabe an Spieler 0 (Sieg folgt via Gebaeudezahl)
Export void _trigger_6_Uebergabe_cb() {
    TethysGameEx::MsgBox(NULL, "Die Ost-Kolonie schliesst sich euch an!\n\nAlle Gebaeude im Osten gehoeren jetzt euch - damit ist das Missionsziel erfuellt.", "Leitstand", MB_OK | MB_ICONINFORMATION);
    // Schleife: Gebaeude von Spieler 1 im Ost-Bereich
    {
        for (int _bt1 = (int)mapCommonOreMine; _bt1 <= (int)mapTokamak; ++_bt1) {
            PlayerBuildingEnum _e1b(1, (map_id)_bt1);
            UnitEx unit;
            while (_e1b.GetNext(unit)) {
                MAP_RECT _fr1 = MkRect(77, 4, 96, 21);
                LOCATION _l1 = unit.Location();
                if (!(_fr1.Check(_l1))) continue;
                if (true) {
                    unit.DoTransfer(0);
                }
            }
        }
    }
    AddGameMessage("Die Ost-Kolonie gehoert jetzt euch!");
}
static void _trigger_6_Uebergabe() {
    CreateTimeTrigger(1, 1, (20) * kTicksPerMark, "_trigger_6_Uebergabe_cb");
}

Export void _repairGroups_cb() {
    {
        PlayerBuildingEnum _e(1, mapStructureFactory);
        UnitEx _u;
        LOCATION _a = MkXY(38, 15);
        static int _seen_anchor_0 = 0;
        while (_e.GetNext(_u)) {
            if (!(_u.Location() == _a)) continue;
            if (!isCompleted(_u)) { _seen_anchor_0 = 0; break; }
            if (_seen_anchor_0 != _u.unitID) { _seen_anchor_0 = _u.unitID; break; }
            if (_unit_struck.unitID != _u.unitID) {
                _unit_struck = _u;
                op2::log::linef("Anker [struck] -> Einheit %d gebunden", _u.unitID);
            }
            break;
        }
    }
    {
        PlayerBuildingEnum _e(1, mapVehicleFactory);
        UnitEx _u;
        LOCATION _a = MkXY(34, 11);
        static int _seen_anchor_1 = 0;
        while (_e.GetNext(_u)) {
            if (!(_u.Location() == _a)) continue;
            if (!isCompleted(_u)) { _seen_anchor_1 = 0; break; }
            if (_seen_anchor_1 != _u.unitID) { _seen_anchor_1 = _u.unitID; break; }
            if (_unit_veh.unitID != _u.unitID) {
                _unit_veh = _u;
                op2::log::linef("Anker [veh] -> Einheit %d gebunden", _u.unitID);
            }
            break;
        }
    }
    {
        PlayerBuildingEnum _e(1, mapCommonOreSmelter);
        UnitEx _u;
        LOCATION _a = MkXY(39, 8);
        static int _seen_anchor_2 = 0;
        while (_e.GetNext(_u)) {
            if (!(_u.Location() == _a)) continue;
            if (!isCompleted(_u)) { _seen_anchor_2 = 0; break; }
            if (_seen_anchor_2 != _u.unitID) { _seen_anchor_2 = _u.unitID; break; }
            if (_unit_Smelter1.unitID != _u.unitID) {
                _unit_Smelter1 = _u;
                op2::log::linef("Anker [Smelter1] -> Einheit %d gebunden", _u.unitID);
            }
            break;
        }
    }
    {
        PlayerBuildingEnum _e(1, mapSpaceport);
        UnitEx _u;
        LOCATION _a = MkXY(28, 20);
        static int _seen_anchor_3 = 0;
        while (_e.GetNext(_u)) {
            if (!(_u.Location() == _a)) continue;
            if (!isCompleted(_u)) { _seen_anchor_3 = 0; break; }
            if (_seen_anchor_3 != _u.unitID) { _seen_anchor_3 = _u.unitID; break; }
            if (_unit_space.unitID != _u.unitID) {
                _unit_space = _u;
                op2::log::linef("Anker [space] -> Einheit %d gebunden", _u.unitID);
            }
            break;
        }
    }
    {
        PlayerBuildingEnum _e(1, mapStructureFactory);
        UnitEx _u;
        LOCATION _a = MkXY(85, 14);
        static int _seen_anchor_4 = 0;
        while (_e.GetNext(_u)) {
            if (!(_u.Location() == _a)) continue;
            if (!isCompleted(_u)) { _seen_anchor_4 = 0; break; }
            if (_seen_anchor_4 != _u.unitID) { _seen_anchor_4 = _u.unitID; break; }
            if (_unit_test.unitID != _u.unitID) {
                _unit_test = _u;
                op2::log::linef("Anker [test] -> Einheit %d gebunden", _u.unitID);
            }
            break;
        }
    }
    {
        PlayerBuildingEnum _e(1, mapCommonOreMine);
        UnitEx _u;
        LOCATION _a = MkXY(49, 16);
        static int _seen_anchor_5 = 0;
        while (_e.GetNext(_u)) {
            if (!(_u.Location() == _a)) continue;
            if (!isCompleted(_u)) { _seen_anchor_5 = 0; break; }
            if (_seen_anchor_5 != _u.unitID) { _seen_anchor_5 = _u.unitID; break; }
            if (_unit_Mine1.unitID != _u.unitID) {
                _unit_Mine1 = _u;
                op2::log::linef("Anker [Mine1] -> Einheit %d gebunden", _u.unitID);
            }
            break;
        }
    }
    {
        PlayerBuildingEnum _e(1, mapStructureFactory);
        UnitEx _u;
        LOCATION _a = MkXY(38, 15);
        while (_e.GetNext(_u)) {
            LOCATION _loc = _u.Location();
            if (!(_loc == _a)) continue;
            static int _seen_BuildingGroup1_0 = 0;
            if (!isCompleted(_u)) { _seen_BuildingGroup1_0 = 0; continue; }
            if (_seen_BuildingGroup1_0 != _u.unitID) {
                _seen_BuildingGroup1_0 = _u.unitID;
                continue;  // erst 1 Mark stabil fertig, dann uebernehmen
            }
            bool _member = false;
            GroupEnumerator _ge(_grp_0_BuildingGroup1);
            UnitEx _m;
            while (_ge.GetNext(_m)) {
                if (_m.unitID == _u.unitID) { _member = true; break; }
            }
            if (!_member) {
                _grp_0_BuildingGroup1.TakeUnit(_u);
                op2::log::linef("Repair: mapStructureFactory (Einheit %d) -> Gruppe wieder aufgenommen", _u.unitID);
            }
        }
    }
    {
        PlayerBuildingEnum _e(1, mapVehicleFactory);
        UnitEx _u;
        LOCATION _a = MkXY(34, 11);
        while (_e.GetNext(_u)) {
            LOCATION _loc = _u.Location();
            if (!(_loc == _a)) continue;
            static int _seen_ReinforceGroup1_0 = 0;
            if (!isCompleted(_u)) { _seen_ReinforceGroup1_0 = 0; continue; }
            if (_seen_ReinforceGroup1_0 != _u.unitID) {
                _seen_ReinforceGroup1_0 = _u.unitID;
                continue;  // erst 1 Mark stabil fertig, dann uebernehmen
            }
            bool _member = false;
            GroupEnumerator _ge(_grp_3_ReinforceGroup1);
            UnitEx _m;
            while (_ge.GetNext(_m)) {
                if (_m.unitID == _u.unitID) { _member = true; break; }
            }
            if (!_member) {
                _grp_3_ReinforceGroup1.TakeUnit(_u);
                op2::log::linef("Repair: mapVehicleFactory (Einheit %d) -> Gruppe wieder aufgenommen", _u.unitID);
            }
        }
    }
    {
        PlayerBuildingEnum _e(1, mapArachnidFactory);
        UnitEx _u;
        LOCATION _a = MkXY(39, 5);
        while (_e.GetNext(_u)) {
            LOCATION _loc = _u.Location();
            if (!(_loc == _a)) continue;
            static int _seen_ReinforceGroup1_1 = 0;
            if (!isCompleted(_u)) { _seen_ReinforceGroup1_1 = 0; continue; }
            if (_seen_ReinforceGroup1_1 != _u.unitID) {
                _seen_ReinforceGroup1_1 = _u.unitID;
                continue;  // erst 1 Mark stabil fertig, dann uebernehmen
            }
            bool _member = false;
            GroupEnumerator _ge(_grp_3_ReinforceGroup1);
            UnitEx _m;
            while (_ge.GetNext(_m)) {
                if (_m.unitID == _u.unitID) { _member = true; break; }
            }
            if (!_member) {
                _grp_3_ReinforceGroup1.TakeUnit(_u);
                op2::log::linef("Repair: mapArachnidFactory (Einheit %d) -> Gruppe wieder aufgenommen", _u.unitID);
            }
        }
    }
    if (_mining_armed_0) {
        UnitEx _mine = _unit_Mine1;
        UnitEx _smelter = _unit_Smelter1;
        if (isCompleted(_mine) && isCompleted(_smelter) &&
            (_mine.unitID != _mining_ids_0[0] || _smelter.unitID != _mining_ids_0[1])) {
            MAP_RECT _area = MkRect(35, 5, 44, 12);
            _grp_5_MiningGroup1.Setup(_mine, _smelter, _area);
            _grp_5_MiningGroup1.SetTargCount(mapCargoTruck, mapNone, 2);
            _mining_ids_0[0] = _mine.unitID;
            _mining_ids_0[1] = _smelter.unitID;
            _grp_3_ReinforceGroup1.RecordVehReinforceGroup(_grp_5_MiningGroup1, 1000);
            op2::log::linef("MiningGroup [MiningGroup1] aktiviert (Mine %d, Smelter %d)", _mine.unitID, _smelter.unitID);
        }
    }
    if (_repair_armed_0) {
        int _issued[8]; int _nIssued = 0;
        {
        MAP_RECT _z = MkRect(27, 4, 56, 22);
        InRectEnumerator _e(_z);
        UnitEx _b;
        while (_e.GetNext(_b)) {
            if (!_b.IsBuilding() || !_b.IsLive() || _b.OwnerID() != 1) continue;
            map_id _bt = _b.GetType();
            int _thr = 1;
            if (_bt == mapTokamak) _thr = 150;
            if (_b.GetDamage() < _thr) continue;
            // freies Fahrzeug der Gruppe suchen (Praeferenz-Rangfolge)
            UnitEx _best; int _bestRank = 99;
            GroupEnumerator _ge(_grp_2_Reparatur);
            UnitEx _v;
            while (_ge.GetNext(_v)) {
                if (!_v.IsVehicle() || !_v.IsLive()) continue;
                if (_v.GetLastCommand() != ctNop) continue;
                bool _busy = false;
                for (int _i = 0; _i < _nIssued; ++_i) if (_issued[_i] == _v.unitID) _busy = true;
                if (_busy) continue;
                int _rank = 99;
                map_id _vt = _v.GetType();
                if (_vt == mapSpider) _rank = 0;
                else if (_vt == mapConVec) _rank = 1;
                if (_rank < _bestRank) { _bestRank = _rank; _best = _v; }
            }
            if (_bestRank < 99 && _nIssued < 8) {
                _best.DoRepair(_b);
                _issued[_nIssued++] = _best.unitID;
                op2::log::linef("Repair-Auftrag: Fahrzeug %d -> Gebaeude %d (Schaden %d)", _best.unitID, _b.unitID, _b.GetDamage());
            }
        }
        }
    }
}

static void aiProc() {
    // Nach einem Spielstand-Load laeuft InitProc NICHT erneut -- HFL
    // muss hier nachinitialisiert werden (intern idempotent), sonst
    // liefern UnitEx-Abfragen wie GetCurAction nur Sentinel-Werte.
    // After a savegame load InitProc does NOT run again -- HFL must
    // be (re)initialized here (internally idempotent), otherwise
    // UnitEx queries like GetCurAction only return sentinel values.
    HFLInit();
    diff = kDiff[Player[0].Difficulty()];
}

Export int InitProc() { op2::crash::guard("InitProc", &initProc); return 1; }
Export void AIProc()  { op2::crash::guard("AIProc",   &aiProc); }

// SaveRegion: g_save wird von der Engine mit dem Spielstand gespeichert
// und beim Laden byte-genau restauriert (Variablen, Gruppen-/Unit-/
// Trigger-Stubs, armed-Flags).
ExportSaveLoadData(g_save)

extern "C" int __stdcall DllMain(void* inst, unsigned long reason, void*) {
    if (reason == 1 /* DLL_PROCESS_ATTACH */) {
        g_briefing_hinst = inst;
        op2::crash::installHandler();
        op2::log::setTickSource([] { return TethysGame::Tick(); });
    }
    return 1;
}
