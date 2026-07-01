// mission.cpp -- generated from the editor model for: Editor Mission
// Built against TitanAPI (https://github.com/leviathan400/TitanAPI).

#include "op2.hpp"
#include "op2/trigger.hpp"
#include "op2/base.hpp"
#include "op2/groups.hpp"
#include "op2_mission.hpp"
#include "op2_log.hpp"
#include "op2_crash.hpp"
#include <algorithm>
#include <ranges>

using namespace op2;

static const int kDiff[] = {5, 10, 13};
static const int diff = kDiff[(int)Player(0).difficulty()];

static int randBetween(int minValue, int maxValue) {
    if (maxValue < minValue) std::swap(minValue, maxValue);
    return minValue + Game::getRand(maxValue - minValue + 1);
}

static int var1 = 0;
static bool var2 = false;

static void _trigger_0_Trigger1();

static Group _grp_0_BuildingGroup1;
static Group _grp_1_ReinforceGroup1;

extern "C" __declspec(dllexport) char LevelDesc[]    = "Editor Mission";
extern "C" __declspec(dllexport) char MapName[]      = "cm02.map";
extern "C" __declspec(dllexport) char TechtreeName[] = "MULTITEK.TXT";
extern "C" __declspec(dllexport) mission::ModDesc   DescBlock   = { mission::MissionType::Colony, 2, 12, 0 };
extern "C" __declspec(dllexport) mission::ModDescEx DescBlockEx = { 0, 0, 0, 0, 0, 0, 0, 0 };

static void initProc() {
    log::line("InitProc: starting");

    // --- Player 0 ---
    Game::player(0).goEden().goHuman();
    Game::player(0).setTechLevel(12);

    // --- Player 1 ---
    Game::player(1).goPlymouth().goAI();
    Game::player(1).setTechLevel(4);
    Game::player(1).setCommonOre(8000);
    Game::player(1).setRareOre(0);
    Game::player(1).setFood(99999);


    // --- Base layout for player 0 ---
    {
        BaseLayout base;
        base.beacons = {
            { { 49, 16 }, abi::MineType::CommonOre, abi::OreYield::Bar2 },
            { { 49, 21 }, abi::MineType::CommonOre, abi::OreYield::Bar3 },
        };
        createBase(Game::player(0), base);
    }

    // --- Base layout for player 1 ---
    {
        BaseLayout base;
        base.buildings = {
            { { 38, 12 }, MapID::CommandCenter },
            { { 44, 6 }, MapID::Tokamak },
            { { 38, 15 }, MapID::StructureFactory },
            { { 34, 11 }, MapID::VehicleFactory },
            { { 39, 8 }, MapID::CommonOreSmelter },
            { { 49, 16 }, MapID::CommonOreMine },
            { { 29, 12 }, MapID::GORF },
            { { 30, 9 }, MapID::MedicalCenter },
        };
        base.vehicles = {
            { { 46, 9 }, MapID::CargoTruck, MapID::None, UnitDirection::East },
            { { 47, 9 }, MapID::CargoTruck, MapID::None, UnitDirection::East },
            { { 42, 10 }, MapID::ConVec, MapID::None, UnitDirection::East },
            { { 47, 13 }, MapID::LightTower, MapID::None, UnitDirection::East },
        };
        createBase(Game::player(1), base);
    }

    // --- Groups (building / reinforce) ---
    _grp_0_BuildingGroup1 = createBuildingGroup(Game::player(1));
    _grp_0_BuildingGroup1.setBuildRect({ 46, 5 }, { 49, 7 });
    {
        // Einheiten der BuildingGroup 'BuildingGroup1' zuweisen
        for (Unit _u : Game::unitsOf(1)) {
            Location _loc = _u.location();
            if ((_loc.x == 38 && _loc.y == 15) || (_loc.x == 42 && _loc.y == 10)) _grp_0_BuildingGroup1.takeUnit(_u);
        }
    }
    _grp_1_ReinforceGroup1 = createBuildingGroup(Game::player(1));
    {
        // Einheiten der ReinforceGroup 'ReinforceGroup1' zuweisen
        for (Unit _u : Game::unitsOf(1)) {
            Location _loc = _u.location();
            if ((_loc.x == 34 && _loc.y == 11)) _grp_1_ReinforceGroup1.takeUnit(_u);
        }
    }
    _grp_1_ReinforceGroup1.recordVehReinforceGroup(_grp_0_BuildingGroup1, 1500);

    Game::addMessage("Mit dem OP2 Mission Editor erstellt.");

    op2::ignore(Game::forceMoraleGood());
    log::line("InitProc: done");
}

// Trigger 'Trigger1' (condition=time)
static void _trigger_0_Trigger1() {
    onMark(100,
    [] {
        GameMap::setLavaPossible(Location{ 158, 160 }, true);
        GameMap::setLavaPossible(Location{ 158, 161 }, true);
        GameMap::setLavaPossible(Location{ 158, 162 }, true);
        GameMap::setLavaPossible(Location{ 158, 163 }, true);
        GameMap::setLavaPossible(Location{ 158, 164 }, true);
        GameMap::setLavaPossible(Location{ 159, 159 }, true);
        GameMap::setLavaPossible(Location{ 159, 160 }, true);
        GameMap::setLavaPossible(Location{ 159, 161 }, true);
        GameMap::setLavaPossible(Location{ 159, 162 }, true);
        GameMap::setLavaPossible(Location{ 159, 163 }, true);
        GameMap::setLavaPossible(Location{ 159, 164 }, true);
        GameMap::setLavaPossible(Location{ 160, 159 }, true);
        GameMap::setLavaPossible(Location{ 160, 160 }, true);
        GameMap::setLavaPossible(Location{ 160, 161 }, true);
        GameMap::setLavaPossible(Location{ 160, 162 }, true);
        GameMap::setLavaPossible(Location{ 160, 163 }, true);
        GameMap::setLavaPossible(Location{ 160, 164 }, true);
        GameMap::setLavaPossible(Location{ 160, 165 }, true);
        GameMap::setLavaPossible(Location{ 161, 158 }, true);
        GameMap::setLavaPossible(Location{ 161, 159 }, true);
        GameMap::setLavaPossible(Location{ 161, 160 }, true);
        GameMap::setLavaPossible(Location{ 161, 161 }, true);
        GameMap::setLavaPossible(Location{ 161, 162 }, true);
        GameMap::setLavaPossible(Location{ 161, 163 }, true);
        GameMap::setLavaPossible(Location{ 161, 164 }, true);
        GameMap::setLavaPossible(Location{ 161, 165 }, true);
        GameMap::setLavaPossible(Location{ 162, 158 }, true);
        GameMap::setLavaPossible(Location{ 162, 159 }, true);
        GameMap::setLavaPossible(Location{ 162, 160 }, true);
        GameMap::setLavaPossible(Location{ 162, 161 }, true);
        GameMap::setLavaPossible(Location{ 162, 162 }, true);
        GameMap::setLavaPossible(Location{ 162, 163 }, true);
        GameMap::setLavaPossible(Location{ 162, 164 }, true);
        GameMap::setLavaPossible(Location{ 162, 165 }, true);
        GameMap::setLavaPossible(Location{ 163, 157 }, true);
        GameMap::setLavaPossible(Location{ 163, 158 }, true);
        GameMap::setLavaPossible(Location{ 163, 159 }, true);
        GameMap::setLavaPossible(Location{ 163, 160 }, true);
        GameMap::setLavaPossible(Location{ 163, 161 }, true);
        GameMap::setLavaPossible(Location{ 163, 162 }, true);
        GameMap::setLavaPossible(Location{ 163, 163 }, true);
        GameMap::setLavaPossible(Location{ 163, 164 }, true);
        GameMap::setLavaPossible(Location{ 163, 165 }, true);
        GameMap::setLavaPossible(Location{ 164, 156 }, true);
        GameMap::setLavaPossible(Location{ 164, 157 }, true);
        GameMap::setLavaPossible(Location{ 164, 158 }, true);
        GameMap::setLavaPossible(Location{ 164, 159 }, true);
        GameMap::setLavaPossible(Location{ 164, 160 }, true);
        GameMap::setLavaPossible(Location{ 164, 161 }, true);
        GameMap::setLavaPossible(Location{ 164, 162 }, true);
        GameMap::setLavaPossible(Location{ 164, 163 }, true);
        GameMap::setLavaPossible(Location{ 164, 164 }, true);
        GameMap::setLavaPossible(Location{ 164, 165 }, true);
        GameMap::setLavaPossible(Location{ 165, 155 }, true);
        GameMap::setLavaPossible(Location{ 165, 156 }, true);
        GameMap::setLavaPossible(Location{ 165, 157 }, true);
        GameMap::setLavaPossible(Location{ 165, 158 }, true);
        GameMap::setLavaPossible(Location{ 165, 159 }, true);
        GameMap::setLavaPossible(Location{ 165, 160 }, true);
        GameMap::setLavaPossible(Location{ 165, 161 }, true);
        GameMap::setLavaPossible(Location{ 165, 162 }, true);
        GameMap::setLavaPossible(Location{ 165, 163 }, true);
        GameMap::setLavaPossible(Location{ 165, 164 }, true);
        GameMap::setLavaPossible(Location{ 165, 165 }, true);
        GameMap::setLavaPossible(Location{ 166, 155 }, true);
        GameMap::setLavaPossible(Location{ 166, 156 }, true);
        GameMap::setLavaPossible(Location{ 166, 157 }, true);
        GameMap::setLavaPossible(Location{ 166, 158 }, true);
        GameMap::setLavaPossible(Location{ 166, 159 }, true);
        GameMap::setLavaPossible(Location{ 166, 160 }, true);
        GameMap::setLavaPossible(Location{ 166, 161 }, true);
        GameMap::setLavaPossible(Location{ 166, 162 }, true);
        GameMap::setLavaPossible(Location{ 166, 163 }, true);
        GameMap::setLavaPossible(Location{ 166, 164 }, true);
        GameMap::setLavaPossible(Location{ 166, 165 }, true);
        GameMap::setLavaPossible(Location{ 167, 156 }, true);
        GameMap::setLavaPossible(Location{ 167, 157 }, true);
        GameMap::setLavaPossible(Location{ 167, 158 }, true);
        GameMap::setLavaPossible(Location{ 167, 159 }, true);
        GameMap::setLavaPossible(Location{ 167, 160 }, true);
        GameMap::setLavaPossible(Location{ 167, 161 }, true);
        GameMap::setLavaPossible(Location{ 167, 162 }, true);
        GameMap::setLavaPossible(Location{ 167, 163 }, true);
        GameMap::setLavaPossible(Location{ 167, 164 }, true);
        GameMap::setLavaPossible(Location{ 168, 157 }, true);
        GameMap::setLavaPossible(Location{ 168, 158 }, true);
        GameMap::setLavaPossible(Location{ 168, 159 }, true);
        GameMap::setLavaPossible(Location{ 168, 160 }, true);
        GameMap::setLavaPossible(Location{ 168, 161 }, true);
        GameMap::setLavaPossible(Location{ 168, 162 }, true);
        GameMap::setLavaPossible(Location{ 168, 163 }, true);
        GameMap::setLavaPossible(Location{ 168, 164 }, true);
        GameMap::setLavaPossible(Location{ 169, 157 }, true);
        GameMap::setLavaPossible(Location{ 169, 158 }, true);
        GameMap::setLavaPossible(Location{ 169, 159 }, true);
        GameMap::setLavaPossible(Location{ 169, 160 }, true);
        GameMap::setLavaPossible(Location{ 169, 161 }, true);
        GameMap::setLavaPossible(Location{ 169, 162 }, true);
        GameMap::setLavaPossible(Location{ 169, 163 }, true);
        GameMap::setLavaPossible(Location{ 169, 164 }, true);
        GameMap::setLavaPossible(Location{ 170, 156 }, true);
        GameMap::setLavaPossible(Location{ 170, 157 }, true);
        GameMap::setLavaPossible(Location{ 170, 158 }, true);
        GameMap::setLavaPossible(Location{ 170, 159 }, true);
        GameMap::setLavaPossible(Location{ 170, 160 }, true);
        GameMap::setLavaPossible(Location{ 170, 161 }, true);
        GameMap::setLavaPossible(Location{ 170, 162 }, true);
        GameMap::setLavaPossible(Location{ 170, 163 }, true);
        GameMap::setLavaPossible(Location{ 171, 156 }, true);
        GameMap::setLavaPossible(Location{ 171, 157 }, true);
        GameMap::setLavaPossible(Location{ 171, 158 }, true);
        GameMap::setLavaPossible(Location{ 171, 159 }, true);
        GameMap::setLavaPossible(Location{ 171, 160 }, true);
        GameMap::setLavaPossible(Location{ 171, 161 }, true);
        GameMap::setLavaPossible(Location{ 171, 162 }, true);
        GameMap::setLavaPossible(Location{ 172, 155 }, true);
        GameMap::setLavaPossible(Location{ 172, 156 }, true);
        GameMap::setLavaPossible(Location{ 172, 157 }, true);
        GameMap::setLavaPossible(Location{ 172, 158 }, true);
        GameMap::setLavaPossible(Location{ 173, 155 }, true);
        GameMap::setLavaPossible(Location{ 173, 156 }, true);
        GameMap::setLavaPossible(Location{ 173, 157 }, true);
        GameMap::setLavaPossible(Location{ 174, 154 }, true);
        GameMap::setLavaPossible(Location{ 174, 155 }, true);
        GameMap::setLavaPossible(Location{ 174, 156 }, true);
        GameMap::setLavaPossible(Location{ 174, 157 }, true);
        GameMap::setLavaPossible(Location{ 175, 153 }, true);
        GameMap::setLavaPossible(Location{ 175, 154 }, true);
        GameMap::setLavaPossible(Location{ 175, 155 }, true);
        GameMap::setLavaPossible(Location{ 175, 156 }, true);
        GameMap::setLavaPossible(Location{ 175, 157 }, true);
        GameMap::setLavaPossible(Location{ 176, 153 }, true);
        GameMap::setLavaPossible(Location{ 176, 154 }, true);
        GameMap::setLavaPossible(Location{ 176, 155 }, true);
        GameMap::setLavaPossible(Location{ 176, 156 }, true);
        GameMap::setLavaPossible(Location{ 176, 157 }, true);
        GameMap::setLavaPossible(Location{ 177, 153 }, true);
        GameMap::setLavaPossible(Location{ 177, 154 }, true);
        GameMap::setLavaPossible(Location{ 177, 155 }, true);
        GameMap::setLavaPossible(Location{ 177, 156 }, true);
        GameMap::setLavaPossible(Location{ 178, 153 }, true);
        GameMap::setLavaPossible(Location{ 178, 154 }, true);
        GameMap::setLavaPossible(Location{ 178, 155 }, true);
        op2::ignore(Game::createEruption(Location{ 166, 154 }, 15, true));
        Game::addMessage("Nachricht…");
    },
    /*oneShot=*/false);
}

static void aiProc() {}

extern "C" __declspec(dllexport) int  InitProc() { crash::guard("InitProc", &initProc); return 1; }
extern "C" __declspec(dllexport) void AIProc()   { crash::guard("AIProc",   &aiProc); }

extern "C" __declspec(dllexport) void GetSaveRegions(mission::SaveRegion* p) {
    if (p) { p->pData = nullptr; p->size = 0; }
}

extern "C" int __stdcall DllMain(void*, unsigned long reason, void*) {
    if (reason == 1 /* DLL_PROCESS_ATTACH */) {
        crash::installHandler();
        log::setTickSource([] { return Game::tick(); });
    }
    return 1;
}
