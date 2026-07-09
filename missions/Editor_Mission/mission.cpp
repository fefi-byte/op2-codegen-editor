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
#include <functional>
#include <type_traits>

using namespace op2;

static const int kDiff[] = {5, 10, 13};
static const int diff = kDiff[(int)Player(0).difficulty()];

static int randBetween(int minValue, int maxValue) {
    if (maxValue < minValue) std::swap(minValue, maxValue);
    return minValue + Game::getRand(maxValue - minValue + 1);
}

struct MissionSave {
    int cbCount = 0;                 // belegte Callback-Slots / used callback slots
    unsigned char cbSlot[64] = {};   // Slot -> Index in g_cbTable (0xFF = nicht wiederherstellbar)
    bool var2 = false;
    Group _grp_0_BuildingGroup1{};
    Group _grp_1_ReinforceGroup1{};
    Group _grp_2_def{};
    Unit _unit_struck{};
    Unit _unit_veh{};
    Unit _unit_spider{};
};
static_assert(std::is_trivially_copyable_v<MissionSave>, "SaveRegion braucht POD-Daten");
static MissionSave g_save;

static bool& var2 = g_save.var2;
static Group& _grp_0_BuildingGroup1 = g_save._grp_0_BuildingGroup1;
static Group& _grp_1_ReinforceGroup1 = g_save._grp_1_ReinforceGroup1;
static Group& _grp_2_def = g_save._grp_2_def;
static Unit& _unit_struck = g_save._unit_struck;
static Unit& _unit_veh = g_save._unit_veh;
static Unit& _unit_spider = g_save._unit_spider;

static std::function<void()> trackCb(void (*fn)(), int tableIdx) {
    if (g_save.cbCount < 64) g_save.cbSlot[g_save.cbCount++] = (unsigned char)tableIdx;
    return fn;
}
static std::function<void()> trackLost(std::function<void()> cb) {
    if (g_save.cbCount < 64) g_save.cbSlot[g_save.cbCount++] = 0xFF;
    return cb;
}

static void _trigger_0_Disaster();
static void _trigger_1_base_rep();
static void _trigger_2_reinforce();
static void _trigger_3_Trigger4();

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
    Game::player(1).setTechLevel(12);
    Game::player(1).setCommonOre(8000);
    Game::player(1).setRareOre(8000);
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
            { { 47, 13 }, MapID::LightTower },
            { { 30, 9 }, MapID::MedicalCenter },
            { { 44, 20 }, MapID::GuardPost, MapID::RPG },
            { { 54, 19 }, MapID::GuardPost, MapID::RPG },
            { { 54, 13 }, MapID::GuardPost, MapID::RPG },
            { { 54, 8 }, MapID::GuardPost, MapID::RPG },
            { { 42, 20 }, MapID::GuardPost, MapID::RPG },
            { { 46, 20 }, MapID::GuardPost, MapID::EMP },
            { { 52, 19 }, MapID::GuardPost, MapID::EMP },
            { { 54, 16 }, MapID::GuardPost, MapID::EMP },
            { { 54, 10 }, MapID::GuardPost, MapID::EMP },
            { { 33, 16 }, MapID::Tokamak },
            { { 29, 15 }, MapID::RareOreSmelter },
            { { 39, 5 }, MapID::ArachnidFactory },
            { { 47, 6 }, MapID::MHDGenerator },
        };
        base.vehicles = {
            { { 46, 9 }, MapID::CargoTruck, MapID::None, UnitDirection::East },
            { { 47, 9 }, MapID::CargoTruck, MapID::None, UnitDirection::East },
            { { 42, 10 }, MapID::ConVec, MapID::None, UnitDirection::East },
            { { 43, 13 }, MapID::Spider, MapID::None, UnitDirection::East },
        };
        createBase(Game::player(1), base);
    }

    // --- Named units ---
    _unit_struck = GameMap::unitOnTile({ 38, 15 });
    _unit_veh = GameMap::unitOnTile({ 34, 11 });
    for (Unit _u : Game::unitsInRect({ 43, 13 }, { 43, 13 })) {
        if (_u.type() == MapID::Spider && _u.ownerId() == 1) { _unit_spider = _u; break; }
    }

    // --- Groups (building / reinforce / fight) ---
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
            if ((_loc.x == 34 && _loc.y == 11) || (_loc.x == 39 && _loc.y == 5)) _grp_1_ReinforceGroup1.takeUnit(_u);
        }
    }
    _grp_1_ReinforceGroup1.recordVehReinforceGroup(_grp_0_BuildingGroup1, 1500);
    _grp_2_def = createFightGroup(Game::player(1));
    _grp_2_def.setIdleRect({ 23, 2 }, { 59, 27 });

    Game::addMessage("Mit dem OP2 Mission Editor erstellt.");

    // --- Custom triggers (enabled at start) ---
    _trigger_0_Disaster();
    _trigger_1_base_rep();
    _trigger_2_reinforce();
    _trigger_3_Trigger4();

    op2::ignore(Game::forceMoraleGood());
    log::line("InitProc: done");
}

// Trigger 'Disaster' (condition=time)
static void _trigger_0_Disaster_cb() {
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
    op2::ignore(Game::createEruption(Location{ 166, 155 }, 15, true));
    Game::addMessage("Nachricht…");
}
static void _trigger_0_Disaster() {
    onMark(500, trackCb(&_trigger_0_Disaster_cb, 0), /*oneShot=*/false);
}

// Trigger 'base rep' (condition=time)
static void _trigger_1_base_rep_cb() {
    for (Unit unit : Game::unitsOf(1)) {
        const Location _l1 = unit.location();
        if (!(unit.isBuilding() && _l1.x >= 25 && _l1.x <= 57 && _l1.y >= 2 && _l1.y <= 24)) continue;
        if ((unit.damage() >= 10)) {
            for (Unit unit2 : Game::unitsOf(1)) {
                const Location _l2 = unit2.location();
                if (!(unit2.isVehicle() && unit2.type() == MapID::Spider && _l2.x >= 28 && _l2.x <= 58 && _l2.y >= 3 && _l2.y <= 25)) continue;
                if ((unit2.command() == int(abi::CommandType::Nop))) {
                }
            }
        }
    }
}
static void _trigger_1_base_rep() {
    onMark(1, trackCb(&_trigger_1_base_rep_cb, 1), /*oneShot=*/false);
}

// Trigger 'reinforce' (condition=time)
static void _trigger_2_reinforce_cb() {
    Game::addMessage("FAHRZEUGE");
}
static void _trigger_2_reinforce() {
    onMark(1, trackCb(&_trigger_2_reinforce_cb, 2), /*oneShot=*/true);
}

// Trigger 'Trigger4' (condition=time)
static void _trigger_3_Trigger4_cb() {
    _grp_2_def.setTargCount(MapID::Lynx, MapID::Microwave, 5);
    _grp_2_def.setTargCount(MapID::Lynx, MapID::EMP, 2);
    _grp_1_ReinforceGroup1.recordVehReinforceGroup(_grp_2_def, 1200);
}
static void _trigger_3_Trigger4() {
    onMark(1, trackCb(&_trigger_3_Trigger4_cb, 3), /*oneShot=*/true);
}

// Alle statisch bekannten Trigger-Callbacks (Index = cbSlot-Wert in g_save).
// All statically known trigger callbacks (index = cbSlot value in g_save).
static void (* const g_cbTable[])() = {
    &_trigger_0_Disaster_cb,
    &_trigger_1_base_rep_cb,
    &_trigger_2_reinforce_cb,
    &_trigger_3_Trigger4_cb,
};
static constexpr int kNumKnownCbs = int(sizeof(g_cbTable) / sizeof(g_cbTable[0]));

// Beim Laden eines Spielstands ruft OP2 InitProc NICHT erneut auf. Die
// Engine stellt ihre Trigger (inkl. TitanTriggerN-Stubnamen) aus dem
// Spielstand wieder her -- aber die Callback-Registry der DLL ist leer.
// g_save (SaveRegion) enthaelt die Slot->Callback-Zuordnung; hier wird
// die Registry daraus wiederaufgebaut. Slots mit 0xFF (Laufzeit-Lambdas
// mit Captures) sind nicht wiederherstellbar und bleiben leer.
//
// On savegame load OP2 does NOT call InitProc again. The engine restores
// its triggers (incl. TitanTriggerN stub names) from the save -- but the
// DLL's callback registry is empty. g_save (SaveRegion) holds the
// slot->callback mapping; rebuild the registry from it here.
static void restoreCallbacksAfterLoad() {
    using namespace op2::trigger_detail;
    if (g_count != 0 || g_save.cbCount <= 0) return;  // frische Session / nichts zu tun
    int lost = 0;
    for (int i = 0; i < g_save.cbCount && i < kMaxCallbacks; ++i) {
        const int idx = g_save.cbSlot[i];
        if (idx >= 0 && idx < kNumKnownCbs) g_callbacks[i] = g_cbTable[idx];
        else ++lost;
    }
    g_count = g_save.cbCount;
    log::linef("Savegame-Load: %d Trigger-Callbacks wiederhergestellt, %d nicht wiederherstellbar",
               g_save.cbCount - lost, lost);
}

static void aiProc() {
    // Fallback: falls OnLoadSavedGame von dieser OPU-Version nicht gerufen
    // wird, stellt der erste AIProc-Tick nach einem Load die Registry her.
    restoreCallbacksAfterLoad();
}

extern "C" __declspec(dllexport) int  InitProc() { crash::guard("InitProc", &initProc); return 1; }
extern "C" __declspec(dllexport) void AIProc()   { crash::guard("AIProc",   &aiProc); }

// SaveRegion: g_save wird von der Engine mit dem Spielstand gespeichert
// und beim Laden byte-genau restauriert (Variablen, Gruppen, Einheiten,
// Callback-Slots).
extern "C" __declspec(dllexport) void GetSaveRegions(mission::SaveRegion* p) {
    if (p) { p->pData = &g_save; p->size = sizeof(g_save); }
}

extern "C" __declspec(dllexport) int OnLoadSavedGame(mission::OnLoadSavedGameArgs*) {
    crash::guard("OnLoadSavedGame", &restoreCallbacksAfterLoad);
    return 1;
}

extern "C" int __stdcall DllMain(void*, unsigned long reason, void*) {
    if (reason == 1 /* DLL_PROCESS_ATTACH */) {
        crash::installHandler();
        log::setTickSource([] { return Game::tick(); });
    }
    return 1;
}
