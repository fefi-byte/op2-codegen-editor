// mission.cpp -- generated from the editor model for: Editor Mission
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
    BuildingGroup _grp_2_ReinforceGroup1;
    FightGroup _grp_3_def;
    MiningGroup _grp_4_MiningGroup1;
    UnitEx _unit_struck;
    UnitEx _unit_veh;
    UnitEx _unit_Smelter1;
    UnitEx _unit_spider;
    UnitEx _unit_Mine1;
};
static MissionSave g_save;

static bool& _mining_armed_0 = g_save._mining_armed_0;
static int (&_mining_ids_0)[2] = g_save._mining_ids_0;
static bool& _repair_armed_0 = g_save._repair_armed_0;
static BuildingGroup& _grp_0_BuildingGroup1 = g_save._grp_0_BuildingGroup1;
static BuildingGroup& _grp_1_RebuildMines = g_save._grp_1_RebuildMines;
static BuildingGroup& _grp_2_ReinforceGroup1 = g_save._grp_2_ReinforceGroup1;
static FightGroup& _grp_3_def = g_save._grp_3_def;
static MiningGroup& _grp_4_MiningGroup1 = g_save._grp_4_MiningGroup1;
static UnitEx& _unit_struck = g_save._unit_struck;
static UnitEx& _unit_veh = g_save._unit_veh;
static UnitEx& _unit_Smelter1 = g_save._unit_Smelter1;
static UnitEx& _unit_spider = g_save._unit_spider;
static UnitEx& _unit_Mine1 = g_save._unit_Mine1;

static UnitEx _boot_0;
static UnitEx _boot_1;
static UnitEx _boot_2;

Export void NoResponseToTrigger() {}

static void _trigger_0_Disaster();
static void _trigger_1_base_rep();
static void _trigger_2_buildings();
static void _trigger_3_Trigger5();

ExportLevelDetailsFull("Editor Mission", "cm02.map", "MULTITEK.TXT", Colony, 2, 12, 0)
Export const AIModDescEx DescBlockEx = { 0 };

static void initProc() {
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
        TethysGame::CreateBeacon(mapMiningBeacon, XYPos(49, 16), OreTypeCommon, BarRandom, VariantRandom);
        TethysGame::CreateBeacon(mapMiningBeacon, XYPos(49, 21), OreTypeCommon, Bar3, VariantRandom);
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
    }
    op2::log::linef("InitProc: BuildingGroup 'BuildingGroup1' -> %d Einheiten", _grp_0_BuildingGroup1.TotalUnitCount());
    _grp_1_RebuildMines = CreateBuildingGroup(Player[1]);
    { MAP_RECT _r = MkRect(50, 5, 52, 7); _grp_1_RebuildMines.SetRect(_r); }
    op2::log::linef("InitProc: BuildingGroup 'RebuildMines' -> %d Einheiten", _grp_1_RebuildMines.TotalUnitCount());
    _grp_2_ReinforceGroup1 = CreateBuildingGroup(Player[1]);
    // Einheiten der ReinforceGroup 'ReinforceGroup1' zuweisen
    if (_unit_veh.unitID != 0) _grp_2_ReinforceGroup1.TakeUnit(_unit_veh);
    if (_boot_2.unitID != 0) _grp_2_ReinforceGroup1.TakeUnit(_boot_2);
    _grp_2_ReinforceGroup1.RecordVehReinforceGroup(_grp_0_BuildingGroup1, 1500);
    _grp_3_def = CreateFightGroup(Player[1]);
    { MAP_RECT _r = MkRect(23, 2, 59, 27); _grp_3_def.SetRect(_r); }
    _grp_4_MiningGroup1 = CreateMiningGroup(Player[1]);

    // --- Gruppen-Reparatur: zerstoerte, von der Engine an derselben
    // Stelle wieder errichtete Gebaeude automatisch neu zuweisen/
    // verknuepfen (ein einziger wiederkehrender Timer). ---
    CreateTimeTrigger(1, 0, kTicksPerMark, "_repairGroups_cb");

    AddGameMessage("Created with the OP2 Mission Editor.");

    // --- Victory conditions ---
    Trigger _v_16580 = CreateCountTrigger(1, 1, 0, mapEvacuationModule, mapAny, 1, cmpGreaterEqual, "NoResponseToTrigger");
    CreateVictoryCondition(1, 0, _v_16580, "Complete the mission.");

    // --- Defeat conditions ---
    Trigger _v_22266 = CreateResourceTrigger(1, 1, resCommonOre, 10000, 0, cmpGreaterEqual, "NoResponseToTrigger");
    CreateFailureCondition(1, 0, _v_22266, "");

    // --- Custom triggers (enabled at start) ---
    _trigger_0_Disaster();
    _trigger_1_base_rep();
    _trigger_2_buildings();
    _trigger_3_Trigger5();

    TethysGame::ForceMoraleGood(PlayerNum::PlayerAll);
    op2::log::line("InitProc: done");
}

// Trigger 'Disaster' (condition=time)
Export void _trigger_0_Disaster_cb() {
    GameMap::SetLavaPossible(MkXY(158, 160), 1);
    GameMap::SetLavaPossible(MkXY(158, 161), 1);
    GameMap::SetLavaPossible(MkXY(158, 162), 1);
    GameMap::SetLavaPossible(MkXY(158, 163), 1);
    GameMap::SetLavaPossible(MkXY(158, 164), 1);
    GameMap::SetLavaPossible(MkXY(159, 159), 1);
    GameMap::SetLavaPossible(MkXY(159, 160), 1);
    GameMap::SetLavaPossible(MkXY(159, 161), 1);
    GameMap::SetLavaPossible(MkXY(159, 162), 1);
    GameMap::SetLavaPossible(MkXY(159, 163), 1);
    GameMap::SetLavaPossible(MkXY(159, 164), 1);
    GameMap::SetLavaPossible(MkXY(160, 159), 1);
    GameMap::SetLavaPossible(MkXY(160, 160), 1);
    GameMap::SetLavaPossible(MkXY(160, 161), 1);
    GameMap::SetLavaPossible(MkXY(160, 162), 1);
    GameMap::SetLavaPossible(MkXY(160, 163), 1);
    GameMap::SetLavaPossible(MkXY(160, 164), 1);
    GameMap::SetLavaPossible(MkXY(160, 165), 1);
    GameMap::SetLavaPossible(MkXY(161, 158), 1);
    GameMap::SetLavaPossible(MkXY(161, 159), 1);
    GameMap::SetLavaPossible(MkXY(161, 160), 1);
    GameMap::SetLavaPossible(MkXY(161, 161), 1);
    GameMap::SetLavaPossible(MkXY(161, 162), 1);
    GameMap::SetLavaPossible(MkXY(161, 163), 1);
    GameMap::SetLavaPossible(MkXY(161, 164), 1);
    GameMap::SetLavaPossible(MkXY(161, 165), 1);
    GameMap::SetLavaPossible(MkXY(162, 158), 1);
    GameMap::SetLavaPossible(MkXY(162, 159), 1);
    GameMap::SetLavaPossible(MkXY(162, 160), 1);
    GameMap::SetLavaPossible(MkXY(162, 161), 1);
    GameMap::SetLavaPossible(MkXY(162, 162), 1);
    GameMap::SetLavaPossible(MkXY(162, 163), 1);
    GameMap::SetLavaPossible(MkXY(162, 164), 1);
    GameMap::SetLavaPossible(MkXY(162, 165), 1);
    GameMap::SetLavaPossible(MkXY(163, 157), 1);
    GameMap::SetLavaPossible(MkXY(163, 158), 1);
    GameMap::SetLavaPossible(MkXY(163, 159), 1);
    GameMap::SetLavaPossible(MkXY(163, 160), 1);
    GameMap::SetLavaPossible(MkXY(163, 161), 1);
    GameMap::SetLavaPossible(MkXY(163, 162), 1);
    GameMap::SetLavaPossible(MkXY(163, 163), 1);
    GameMap::SetLavaPossible(MkXY(163, 164), 1);
    GameMap::SetLavaPossible(MkXY(163, 165), 1);
    GameMap::SetLavaPossible(MkXY(164, 156), 1);
    GameMap::SetLavaPossible(MkXY(164, 157), 1);
    GameMap::SetLavaPossible(MkXY(164, 158), 1);
    GameMap::SetLavaPossible(MkXY(164, 159), 1);
    GameMap::SetLavaPossible(MkXY(164, 160), 1);
    GameMap::SetLavaPossible(MkXY(164, 161), 1);
    GameMap::SetLavaPossible(MkXY(164, 162), 1);
    GameMap::SetLavaPossible(MkXY(164, 163), 1);
    GameMap::SetLavaPossible(MkXY(164, 164), 1);
    GameMap::SetLavaPossible(MkXY(164, 165), 1);
    GameMap::SetLavaPossible(MkXY(165, 155), 1);
    GameMap::SetLavaPossible(MkXY(165, 156), 1);
    GameMap::SetLavaPossible(MkXY(165, 157), 1);
    GameMap::SetLavaPossible(MkXY(165, 158), 1);
    GameMap::SetLavaPossible(MkXY(165, 159), 1);
    GameMap::SetLavaPossible(MkXY(165, 160), 1);
    GameMap::SetLavaPossible(MkXY(165, 161), 1);
    GameMap::SetLavaPossible(MkXY(165, 162), 1);
    GameMap::SetLavaPossible(MkXY(165, 163), 1);
    GameMap::SetLavaPossible(MkXY(165, 164), 1);
    GameMap::SetLavaPossible(MkXY(165, 165), 1);
    GameMap::SetLavaPossible(MkXY(166, 155), 1);
    GameMap::SetLavaPossible(MkXY(166, 156), 1);
    GameMap::SetLavaPossible(MkXY(166, 157), 1);
    GameMap::SetLavaPossible(MkXY(166, 158), 1);
    GameMap::SetLavaPossible(MkXY(166, 159), 1);
    GameMap::SetLavaPossible(MkXY(166, 160), 1);
    GameMap::SetLavaPossible(MkXY(166, 161), 1);
    GameMap::SetLavaPossible(MkXY(166, 162), 1);
    GameMap::SetLavaPossible(MkXY(166, 163), 1);
    GameMap::SetLavaPossible(MkXY(166, 164), 1);
    GameMap::SetLavaPossible(MkXY(166, 165), 1);
    GameMap::SetLavaPossible(MkXY(167, 156), 1);
    GameMap::SetLavaPossible(MkXY(167, 157), 1);
    GameMap::SetLavaPossible(MkXY(167, 158), 1);
    GameMap::SetLavaPossible(MkXY(167, 159), 1);
    GameMap::SetLavaPossible(MkXY(167, 160), 1);
    GameMap::SetLavaPossible(MkXY(167, 161), 1);
    GameMap::SetLavaPossible(MkXY(167, 162), 1);
    GameMap::SetLavaPossible(MkXY(167, 163), 1);
    GameMap::SetLavaPossible(MkXY(167, 164), 1);
    GameMap::SetLavaPossible(MkXY(168, 157), 1);
    GameMap::SetLavaPossible(MkXY(168, 158), 1);
    GameMap::SetLavaPossible(MkXY(168, 159), 1);
    GameMap::SetLavaPossible(MkXY(168, 160), 1);
    GameMap::SetLavaPossible(MkXY(168, 161), 1);
    GameMap::SetLavaPossible(MkXY(168, 162), 1);
    GameMap::SetLavaPossible(MkXY(168, 163), 1);
    GameMap::SetLavaPossible(MkXY(168, 164), 1);
    GameMap::SetLavaPossible(MkXY(169, 157), 1);
    GameMap::SetLavaPossible(MkXY(169, 158), 1);
    GameMap::SetLavaPossible(MkXY(169, 159), 1);
    GameMap::SetLavaPossible(MkXY(169, 160), 1);
    GameMap::SetLavaPossible(MkXY(169, 161), 1);
    GameMap::SetLavaPossible(MkXY(169, 162), 1);
    GameMap::SetLavaPossible(MkXY(169, 163), 1);
    GameMap::SetLavaPossible(MkXY(169, 164), 1);
    GameMap::SetLavaPossible(MkXY(170, 156), 1);
    GameMap::SetLavaPossible(MkXY(170, 157), 1);
    GameMap::SetLavaPossible(MkXY(170, 158), 1);
    GameMap::SetLavaPossible(MkXY(170, 159), 1);
    GameMap::SetLavaPossible(MkXY(170, 160), 1);
    GameMap::SetLavaPossible(MkXY(170, 161), 1);
    GameMap::SetLavaPossible(MkXY(170, 162), 1);
    GameMap::SetLavaPossible(MkXY(170, 163), 1);
    GameMap::SetLavaPossible(MkXY(171, 156), 1);
    GameMap::SetLavaPossible(MkXY(171, 157), 1);
    GameMap::SetLavaPossible(MkXY(171, 158), 1);
    GameMap::SetLavaPossible(MkXY(171, 159), 1);
    GameMap::SetLavaPossible(MkXY(171, 160), 1);
    GameMap::SetLavaPossible(MkXY(171, 161), 1);
    GameMap::SetLavaPossible(MkXY(171, 162), 1);
    GameMap::SetLavaPossible(MkXY(172, 155), 1);
    GameMap::SetLavaPossible(MkXY(172, 156), 1);
    GameMap::SetLavaPossible(MkXY(172, 157), 1);
    GameMap::SetLavaPossible(MkXY(172, 158), 1);
    GameMap::SetLavaPossible(MkXY(173, 155), 1);
    GameMap::SetLavaPossible(MkXY(173, 156), 1);
    GameMap::SetLavaPossible(MkXY(173, 157), 1);
    GameMap::SetLavaPossible(MkXY(174, 154), 1);
    GameMap::SetLavaPossible(MkXY(174, 155), 1);
    GameMap::SetLavaPossible(MkXY(174, 156), 1);
    GameMap::SetLavaPossible(MkXY(174, 157), 1);
    GameMap::SetLavaPossible(MkXY(175, 153), 1);
    GameMap::SetLavaPossible(MkXY(175, 154), 1);
    GameMap::SetLavaPossible(MkXY(175, 155), 1);
    GameMap::SetLavaPossible(MkXY(175, 156), 1);
    GameMap::SetLavaPossible(MkXY(175, 157), 1);
    GameMap::SetLavaPossible(MkXY(176, 153), 1);
    GameMap::SetLavaPossible(MkXY(176, 154), 1);
    GameMap::SetLavaPossible(MkXY(176, 155), 1);
    GameMap::SetLavaPossible(MkXY(176, 156), 1);
    GameMap::SetLavaPossible(MkXY(176, 157), 1);
    GameMap::SetLavaPossible(MkXY(177, 153), 1);
    GameMap::SetLavaPossible(MkXY(177, 154), 1);
    GameMap::SetLavaPossible(MkXY(177, 155), 1);
    GameMap::SetLavaPossible(MkXY(177, 156), 1);
    GameMap::SetLavaPossible(MkXY(178, 153), 1);
    GameMap::SetLavaPossible(MkXY(178, 154), 1);
    GameMap::SetLavaPossible(MkXY(178, 155), 1);
    TethysGame::SetEruption(XYPos(166, 155), 15);
    TethysGame::SetLavaSpeed(15);
    AddGameMessage("Nachricht…");
    FreezeFlowS(MkXY(166, 153));
}
static void _trigger_0_Disaster() {
    CreateTimeTrigger(1, 1, (2) * kTicksPerMark, "_trigger_0_Disaster_cb");
}

// Trigger 'base rep' (condition=time)
Export void _trigger_1_base_rep_cb() {
    // Für Base im Norden
    _repair_armed_0 = true;
}
static void _trigger_1_base_rep() {
    CreateTimeTrigger(1, 1, (1) * kTicksPerMark, "_trigger_1_base_rep_cb");
}

// Trigger 'buildings' (condition=time)
Export void _trigger_2_buildings_cb() {
    {
        LOCATION _l;
        _l = MkXY(25, 12);
        _grp_0_BuildingGroup1.RecordBuilding(_l, mapAgridome, mapNone);
        op2::log::linef("RecordBuilding: mapAgridome @ (24,11) -> Gruppe mit %d Einheiten", _grp_0_BuildingGroup1.TotalUnitCount());
    }
    AddGameMessage("bildings");
}
static void _trigger_2_buildings() {
    CreateTimeTrigger(1, 1, (1) * kTicksPerMark, "_trigger_2_buildings_cb");
}

// Trigger 'Trigger5' (condition=time)
Export void _trigger_3_Trigger5_cb() {
    {
        LOCATION _l;
        _l = MkXY(49, 16);
        _grp_1_RebuildMines.RecordBuilding(_l, mapCommonOreMine, mapNone);
        op2::log::linef("RecordBuilding: mapCommonOreMine @ (48,15) -> Gruppe mit %d Einheiten", _grp_1_RebuildMines.TotalUnitCount());
    }
    _mining_armed_0 = true;
    _grp_1_RebuildMines.SetTargCount(mapRoboMiner, mapNone, 1);
    _grp_2_ReinforceGroup1.RecordVehReinforceGroup(_grp_1_RebuildMines, 1000);
}
static void _trigger_3_Trigger5() {
    CreateTimeTrigger(1, 1, (5) * kTicksPerMark, "_trigger_3_Trigger5_cb");
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
        PlayerBuildingEnum _e(1, mapCommonOreMine);
        UnitEx _u;
        LOCATION _a = MkXY(49, 16);
        static int _seen_anchor_3 = 0;
        while (_e.GetNext(_u)) {
            if (!(_u.Location() == _a)) continue;
            if (!isCompleted(_u)) { _seen_anchor_3 = 0; break; }
            if (_seen_anchor_3 != _u.unitID) { _seen_anchor_3 = _u.unitID; break; }
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
            GroupEnumerator _ge(_grp_2_ReinforceGroup1);
            UnitEx _m;
            while (_ge.GetNext(_m)) {
                if (_m.unitID == _u.unitID) { _member = true; break; }
            }
            if (!_member) {
                _grp_2_ReinforceGroup1.TakeUnit(_u);
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
            GroupEnumerator _ge(_grp_2_ReinforceGroup1);
            UnitEx _m;
            while (_ge.GetNext(_m)) {
                if (_m.unitID == _u.unitID) { _member = true; break; }
            }
            if (!_member) {
                _grp_2_ReinforceGroup1.TakeUnit(_u);
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
            _grp_4_MiningGroup1.Setup(_mine, _smelter, _area);
            _grp_4_MiningGroup1.SetTargCount(mapCargoTruck, mapNone, 2);
            _mining_ids_0[0] = _mine.unitID;
            _mining_ids_0[1] = _smelter.unitID;
            _grp_2_ReinforceGroup1.RecordVehReinforceGroup(_grp_4_MiningGroup1, 1000);
            op2::log::linef("MiningGroup [MiningGroup1] aktiviert (Mine %d, Smelter %d)", _mine.unitID, _smelter.unitID);
        }
    }
    if (_repair_armed_0) {
        int _issued[8]; int _nIssued = 0;
        {
        MAP_RECT _z = MkRect(24, 3, 45, 22);
        InRectEnumerator _e(_z);
        UnitEx _b;
        while (_e.GetNext(_b)) {
            if (!_b.IsBuilding() || !_b.IsLive() || _b.OwnerID() != 1) continue;
            map_id _bt = _b.GetType();
            int _thr = 1;
            if (_bt == mapTokamak) _thr = 200;
            if (_b.GetDamage() < _thr) continue;
            // freies Fahrzeug der Gruppe suchen (Praeferenz-Rangfolge)
            UnitEx _best; int _bestRank = 99;
            GroupEnumerator _ge(_grp_0_BuildingGroup1);
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
        {
        MAP_RECT _z = MkRect(46, 3, 57, 22);
        InRectEnumerator _e(_z);
        UnitEx _b;
        while (_e.GetNext(_b)) {
            if (!_b.IsBuilding() || !_b.IsLive() || _b.OwnerID() != 1) continue;
            map_id _bt = _b.GetType();
            int _thr = 1;
            if (_bt == mapTokamak) _thr = 200;
            if (_b.GetDamage() < _thr) continue;
            // freies Fahrzeug der Gruppe suchen (Praeferenz-Rangfolge)
            UnitEx _best; int _bestRank = 99;
            GroupEnumerator _ge(_grp_0_BuildingGroup1);
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

extern "C" int __stdcall DllMain(void*, unsigned long reason, void*) {
    if (reason == 1 /* DLL_PROCESS_ATTACH */) {
        op2::crash::installHandler();
        op2::log::setTickSource([] { return TethysGame::Tick(); });
    }
    return 1;
}
