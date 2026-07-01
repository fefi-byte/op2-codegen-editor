#pragma once
// op2_mission.hpp - the Outpost 2 mission-DLL contract (the Layer-1 "be a mission" ABI).
//
// These types/layouts are facts about how Outpost 2 / the OPU loader interface with a mission DLL
// (reference: TethysAPI API/Mission.h). A mission DLL must export, with exactly these names & layouts:
//     char      LevelDesc[]      // shown in the mission list
//     char      MapName[]        // .map file to load
//     char      TechtreeName[]   // tech tree file
//     ModDesc   DescBlock        // mission type / players / tech
//     ModDescEx DescBlockEx      // multiplayer-AI slots (0 for single-player)
// and may optionally export the entry points:
//     int  InitProc()                      // set up the world; return nonzero on success
//     void AIProc()                        // called every 4 ticks
//     void GetSaveRegions(SaveRegion*)     // declare save-game state
// All entry points are __cdecl (the project default) with C linkage.

#include <cstddef>
#include "op2/abi/memory.hpp"

namespace op2::mission {

/// DescBlock.missionType. Positive = campaign mission; negative = colony / demo / tutorial / multiplayer.
enum class MissionType : int {
  Campaign1 = 1, Campaign2, Campaign3, Campaign4,  Campaign5,  Campaign6,
  Campaign7,     Campaign8, Campaign9, Campaign10, Campaign11, Campaign12,

  Colony          = -1,
  AutoDemo        = -2,
  Tutorial        = -3,
  LandRush        = -4,
  SpaceRace       = -5,
  ResourceRace    = -6,
  Midas           = -7,
  LastOneStanding = -8,
};

/// Exported as `DescBlock` (16 bytes). Tells Outpost 2 the mission's type / player count / tech.
struct ModDesc {
  MissionType missionType;
  int         numPlayers;    ///< 1-6; includes AIs on single-player maps, excludes them on multiplayer maps.
  int         maxTechLevel;  ///< 12 enables all techs for standard tech trees.
  int         unitMission;   ///< ibool; set to 1 to disable most reports (unit-only missions).
};

/// Exported as `DescBlockEx` (32 bytes). THIS is the "AI players in multiplayer" descriptor - numMultiplayerAIs
/// is the count of extra AI player slots to initialize besides Gaia (OP2MissionSDK calls the equivalent
/// `AIModDescEx`). 0 for single-player / colony maps. Set it to exactly the number of computer players a
/// multiplayer script runs - getting it wrong causes alliance / color / colony bugs.
struct ModDescEx {
  int numMultiplayerAIs;
  int field_04, field_08, field_0C, field_10, field_14, field_18, field_1C;
};

/// Passed to GetSaveRegions(): point pData/size at a PERSISTENT (global/static) block of mission state to save &
/// restore across save/load. On loading a saved game OP2 restores these bytes and resumes AIProc WITHOUT calling
/// InitProc - so a save region is how a mission carries its own state (phase, counters, flags) through a reload.
struct SaveRegion {
  void*       pData;
  std::size_t size;
};

// ---- typed save/load over the engine's StreamIO (the OnSaveGame / OnLoadSavedGame callbacks, OPU 1.4.0+) ----
// For variable-length data that doesn't fit a fixed SaveRegion. OP2 hands the callback a StreamIO* positioned at
// the end of normal save data; write your data in OnSaveGame and read it back (same order) in OnLoadSavedGame.

/// Args for the OnSaveGame(args) / OnLoadSavedGame(args) mission exports. pSavedGame is an engine StreamIO*.
struct OnSaveGameArgs      { std::size_t structSize; void* pSavedGame; };
struct OnLoadSavedGameArgs { std::size_t structSize; void* pSavedGame; };

// ---- the rest of the optional mission lifecycle callbacks (OPU 1.4.0+ extended API) ----
// Export any of these (C linkage, undecorated) and the OPU loader calls them. The two *Mission load/unload hooks
// return ibool (1 = ok); the event hooks return void.
//   ibool OnLoadMission(OnLoadMissionArgs*)      // DLL loaded
//   ibool OnUnloadMission(OnUnloadMissionArgs*)  // DLL unloading
//   void  OnEndMission(OnEndMissionArgs*)        // mission won / lost / aborted
//   void  OnChat(OnChatArgs*)                    // any player sent a chat message (pText is writable)
//   void  OnGameCommand(OnGameCommandArgs*)      // a game command packet is being processed (1.4.2)
struct OnLoadMissionArgs   { std::size_t structSize; };
struct OnUnloadMissionArgs { std::size_t structSize; };
struct OnEndMissionArgs    { std::size_t structSize; void* pMissionResults; };           ///< MissionResults*
struct OnChatArgs          { std::size_t structSize; char* pText; std::size_t bufferSize; int playerNum; };
struct OnGameCommandArgs   { std::size_t structSize; void* pPacket; int playerNum; };     ///< pPacket = CommandPacket*

/// A thin wrapper over an engine StreamIO* for typed mission save/load.
class Stream {
public:
  constexpr explicit Stream(void* streamIO) : s_{ streamIO } {}
  [[nodiscard]] bool valid() const { return s_ != nullptr; }

  /// Length-prefixed string I/O - the engine's NON-virtual entry points (fixed addresses, always safe to call).
  bool        writeString(const char* str) { return s_ && abi::callFast<0x49DB40, int, void*, const char*>(s_, str) != 0; }
  const char* readString()                 { return s_ ? abi::member<0x49DBC0, const char*>(s_) : nullptr; }

  /// Raw / typed value I/O via StreamIO's VIRTUAL Write/Read. Slots 6 (Write) and 7 (Read) in the engine's
  /// declared vtable order [GetStatus, Destroy, Tell, Seek, F1, Flush, Write, Read, Close]. Call these inside an
  /// SEH-guarded export the first time, in case the slot index needs confirming against a live save stream.
  bool writeBytes(const void* p, std::size_t n) {
    if (!s_) return false;
    using Fn = int(__thiscall*)(void*, std::size_t, const void*);
    return reinterpret_cast<Fn>((*reinterpret_cast<void***>(s_))[6])(s_, n, p) != 0;
  }
  bool readBytes(void* p, std::size_t n) {
    if (!s_) return false;
    using Fn = int(__thiscall*)(void*, std::size_t, void*);
    return reinterpret_cast<Fn>((*reinterpret_cast<void***>(s_))[7])(s_, n, p) != 0;
  }
  template <typename T> bool writeValue(const T& v) { return writeBytes(&v, sizeof(T)); }
  template <typename T> bool readValue(T&        v) { return readBytes(&v,  sizeof(T)); }

private:
  void* s_ = nullptr;
};

} // namespace op2::mission
