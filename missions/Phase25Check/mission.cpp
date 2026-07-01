// mission.cpp -- generated from the editor model for: Find Unit Test
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

static void _trigger_0_both_ready();

extern "C" __declspec(dllexport) char LevelDesc[]    = "Find Unit Test";
extern "C" __declspec(dllexport) char MapName[]      = "cm02.map";
extern "C" __declspec(dllexport) char TechtreeName[] = "MULTITEK.TXT";
extern "C" __declspec(dllexport) mission::ModDesc   DescBlock   = { mission::MissionType::Colony, 1, 12, 0 };
extern "C" __declspec(dllexport) mission::ModDescEx DescBlockEx = { 0, 0, 0, 0, 0, 0, 0, 0 };

static void initProc() {
    log::line("InitProc: starting");

    // --- Player 0 ---
    Game::player(0).goEden().goHuman();
    Game::player(0).setTechLevel(12);


    // --- Custom triggers (enabled at start) ---
    _trigger_0_both_ready();

    op2::ignore(Game::forceMoraleGood());
    log::line("InitProc: done");
}

// Trigger 'both_ready' (condition=findUnit)
static void _trigger_0_both_ready() {
    static Trigger _self;
    _self = onTick(10, [] {
        Unit _u0 = GameMap::unitOnTile({ 64, 72 });
        bool _ready0 = _u0.isLive() && _u0.type() == MapID::CommandCenter && _u0.enabled();
        Unit _u1 = GameMap::unitOnTile({ 67, 72 });
        bool _ready1 = _u1.isLive() && _u1.type() == MapID::Tokamak && _u1.enabled();
        if (!(_ready0 && _ready1)) return;
        Game::addMessage("Both buildings online!");
        _self.disable();
    }, /*oneShot=*/false);
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
