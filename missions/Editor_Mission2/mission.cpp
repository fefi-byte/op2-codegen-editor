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
    Group _grp_0_ReinforceGroup1{};
    Group _grp_1_FightGroup1{};
};
static_assert(std::is_trivially_copyable_v<MissionSave>, "SaveRegion braucht POD-Daten");
static MissionSave g_save;

static Group& _grp_0_ReinforceGroup1 = g_save._grp_0_ReinforceGroup1;
static Group& _grp_1_FightGroup1 = g_save._grp_1_FightGroup1;

static std::function<void()> trackCb(void (*fn)(), int tableIdx) {
    if (g_save.cbCount < 64) g_save.cbSlot[g_save.cbCount++] = (unsigned char)tableIdx;
    return fn;
}
static std::function<void()> trackLost(std::function<void()> cb) {
    if (g_save.cbCount < 64) g_save.cbSlot[g_save.cbCount++] = 0xFF;
    return cb;
}

static void _trigger_0_Trigger1();

extern "C" __declspec(dllexport) char LevelDesc[]    = "Editor Mission";
extern "C" __declspec(dllexport) char MapName[]      = "cm01.map";
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
    Game::player(1).setCommonOre(10000);
    Game::player(1).setRareOre(10000);
    Game::player(1).setFood(0);


    // --- Base layout for player 1 ---
    {
        BaseLayout base;
        base.buildings = {
            { { 72, 64 }, MapID::Tokamak },
            { { 71, 71 }, MapID::CommandCenter },
            { { 67, 71 }, MapID::CommonOreSmelter },
            { { 62, 71 }, MapID::RareOreSmelter },
            { { 69, 64 }, MapID::Tokamak },
            { { 67, 75 }, MapID::VehicleFactory },
            { { 62, 75 }, MapID::VehicleFactory },
            { { 62, 67 }, MapID::StructureFactory },
        };
        createBase(Game::player(1), base);
    }

    // --- Groups (building / reinforce / fight) ---
    _grp_0_ReinforceGroup1 = createBuildingGroup(Game::player(1));
    {
        // Einheiten der ReinforceGroup 'ReinforceGroup1' zuweisen
        for (Unit _u : Game::unitsOf(1)) {
            Location _loc = _u.location();
            if ((_loc.x == 67 && _loc.y == 75) || (_loc.x == 62 && _loc.y == 75)) _grp_0_ReinforceGroup1.takeUnit(_u);
        }
    }
    _grp_1_FightGroup1 = createFightGroup(Game::player(1));
    _grp_1_FightGroup1.setIdleRect({ 58, 61 }, { 78, 82 });

    Game::addMessage("Mit dem OP2 Mission Editor erstellt.");

    // --- Custom triggers (enabled at start) ---
    _trigger_0_Trigger1();

    op2::ignore(Game::forceMoraleGood());
    log::line("InitProc: done");
}

// Trigger 'Trigger1' (condition=time)
static void _trigger_0_Trigger1_cb() {
    _grp_1_FightGroup1.setTargCount(MapID::Lynx, MapID::Microwave, 1);
    _grp_0_ReinforceGroup1.recordVehReinforceGroup(_grp_1_FightGroup1, 1200);
}
static void _trigger_0_Trigger1() {
    onMark(1, trackCb(&_trigger_0_Trigger1_cb, 0), /*oneShot=*/true);
}

// Alle statisch bekannten Trigger-Callbacks (Index = cbSlot-Wert in g_save).
// All statically known trigger callbacks (index = cbSlot value in g_save).
static void (* const g_cbTable[])() = {
    &_trigger_0_Trigger1_cb,
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
