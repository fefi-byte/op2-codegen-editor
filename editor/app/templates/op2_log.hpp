#pragma once
// op2_log.hpp - tiny append-only debug logger for the mission DLL (editor scaffolding, no SDK dependency).
//
// Writes to  <Outpost2.exe dir>\OPU\logs\<OP2LOG_NAME>.log  (or <dir>\logs if the exe already sits in an OPU
// folder). Each line is opened+written+closed via raw Win32 (KERNEL32 only - no <windows.h>, so it does
// not clash with memory.hpp's GetModuleHandleA declaration; keeps the DLL importing only KERNEL32). The
// open/close-per-line cost buys a crucial property for crash debugging: the last line is flushed to disk
// before the next call runs, so if an engine call crashes the game, its "about to call" line is preserved.

#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <cstring>

// Log file base name (no extension). The generated CMakeLists.txt sets it to the mission DLL name.
// The main log is <name>.log; the AI-action channel (op2::log::ai) is <name>-AI.log.
#ifndef OP2LOG_NAME
#define OP2LOG_NAME "cOP2Mission"
#endif

namespace op2::log {

// Minimal Win32 imports (all KERNEL32). extern "C" => global C linkage, so these resolve to the real
// imports despite living in this namespace.
extern "C" {
  __declspec(dllimport) unsigned long __stdcall GetModuleFileNameA(void* hModule, char* lpFilename, unsigned long nSize);
  __declspec(dllimport) void*         __stdcall CreateFileA(const char* name, unsigned long access, unsigned long share,
                                                            void* sa, unsigned long disp, unsigned long flags, void* tmpl);
  __declspec(dllimport) int           __stdcall WriteFile(void* h, const void* buf, unsigned long n,
                                                          unsigned long* written, void* ovl);
  __declspec(dllimport) int           __stdcall CloseHandle(void* h);
  __declspec(dllimport) int           __stdcall CreateDirectoryA(const char* path, void* sa);
  __declspec(dllimport) unsigned long __stdcall GetCurrentProcessId();
  __declspec(dllimport) unsigned long __stdcall GetTickCount();
  __declspec(dllimport) void          __stdcall GetLocalTime(void* lpSystemTime);  // fills a SYSTEMTIME
}

namespace detail {

inline char g_path[600]   = { 0 };   // <dir>\<OP2LOG_NAME>.log     - the main mission log
inline char g_aiPath[600] = { 0 };   // <dir>\<OP2LOG_NAME>-AI.log  - the scripted-AI action channel
inline bool g_ready       = false;

// Optional game-tick source: the mission sets this (to e.g. op2::Game::tick) so every log line carries the
// game time. Null until set (and pre-game), in which case the prefix shows tick=-1.
inline int (*g_tickSource)() = nullptr;

inline void* const kInvalidHandle = reinterpret_cast<void*>(static_cast<std::uintptr_t>(-1));

// Create every directory segment of an absolute path (e.g. D:\Outpost 2\OPU\logs). Drive-letter paths only.
inline void ensure_dirs(char* dir) {
  for (char* p = dir + 3; *p; ++p) {            // skip "X:\"
    if (*p == '\\') { *p = 0; CreateDirectoryA(dir, nullptr); *p = '\\'; }
  }
  CreateDirectoryA(dir, nullptr);
}

inline void resolve_path() {
  g_ready = true;
  char exe[600] = { 0 };
  const unsigned long n = GetModuleFileNameA(nullptr, exe, sizeof(exe));
  if (n == 0 || n >= sizeof(exe)) { std::strcpy(g_path, OP2LOG_NAME ".log"); std::strcpy(g_aiPath, OP2LOG_NAME "-AI.log"); return; }

  int slash = -1;                                // strip the exe filename -> directory
  for (int i = 0; exe[i]; ++i) if (exe[i] == '\\') slash = i;
  if (slash < 0) { std::strcpy(g_path, OP2LOG_NAME ".log"); std::strcpy(g_aiPath, OP2LOG_NAME "-AI.log"); return; }
  exe[slash] = 0;

  const int len = static_cast<int>(std::strlen(exe));
  const bool inOpu = (len >= 4) && (exe[len-4] == '\\') &&
                     (exe[len-3]=='O'||exe[len-3]=='o') && (exe[len-2]=='P'||exe[len-2]=='p') &&
                     (exe[len-1]=='U'||exe[len-1]=='u');
  char dir[600];
  std::snprintf(dir, sizeof(dir), inOpu ? "%s\\logs" : "%s\\OPU\\logs", exe);
  ensure_dirs(dir);
  std::snprintf(g_path,   sizeof(g_path),   "%s\\" OP2LOG_NAME ".log",    dir);
  std::snprintf(g_aiPath, sizeof(g_aiPath), "%s\\" OP2LOG_NAME "-AI.log", dir);
}

inline void write_raw(const char* path, const char* s, int len) {
  // FILE_APPEND_DATA=0x4, FILE_SHARE_READ|WRITE=0x3, OPEN_ALWAYS=4, FILE_ATTRIBUTE_NORMAL=0x80
  void* h = CreateFileA(path, 0x0004, 0x0003, nullptr, 4, 0x80, nullptr);
  if (h == kInvalidHandle || h == nullptr) return;
  unsigned long w = 0;
  WriteFile(h, s, static_cast<unsigned long>(len), &w, nullptr);
  CloseHandle(h);
}

// Format the standard "[tick=.. pid=..] msg" line into `buf` and write it to `path`.
inline void write_line(const char* path, const char* msg) {
  if (!g_ready) resolve_path();
  const int gameTick = g_tickSource ? g_tickSource() : -1;
  char buf[1024];
  int n = std::snprintf(buf, sizeof(buf), "[tick=%d pid=%lu] %s\r\n",
                        gameTick, static_cast<unsigned long>(GetCurrentProcessId()), msg);
  if (n < 0) return;
  if (n > static_cast<int>(sizeof(buf))) n = static_cast<int>(sizeof(buf));
  write_raw(path, buf, n);
}

} // namespace detail

/// Absolute path the log resolves to (also written into the log on the first line).
inline const char* path() { if (!detail::g_ready) detail::resolve_path(); return detail::g_path; }

/// Set the game-tick source so each log line is prefixed with the current game time. Pass a function such as
/// `[]{ return op2::Game::tick(); }`. Safe to call at DLL attach (the source is only invoked when logging).
inline void setTickSource(int (*fn)()) { detail::g_tickSource = fn; }

/// Append one line to the MAIN log (prefixed with the game tick + pid), flushed immediately.
inline void line(const char* msg) { detail::write_line(detail::g_path, msg); }

/// Append one line to the AI-action channel (<name>-AI.log) - a separate file for monitoring/debugging the
/// scripted computer player's decisions, like OP2Lua's AI log. Same tick+pid prefix, flushed per line.
inline void ai(const char* msg) { detail::write_line(detail::g_aiPath, msg); }

/// Log a human-readable local date/time line (call once at startup, so each run is timestamped).
inline void timestamp() {
  unsigned short st[8] = { 0 };   // SYSTEMTIME: [0]year [1]month [2]dayOfWeek [3]day [4]hour [5]min [6]sec [7]ms
  GetLocalTime(st);
  char buf[64];
  std::snprintf(buf, sizeof(buf), "started %04u-%02u-%02u %02u:%02u:%02u",
                st[0], st[1], st[3], st[4], st[5], st[6]);
  line(buf);
}

/// printf-style line to the MAIN log.
inline void linef(const char* fmt, ...) {
  char msg[768];
  va_list ap; va_start(ap, fmt);
  std::vsnprintf(msg, sizeof(msg), fmt, ap);
  va_end(ap);
  line(msg);
}

/// printf-style line to the AI-action channel.
inline void ailinef(const char* fmt, ...) {
  char msg[768];
  va_list ap; va_start(ap, fmt);
  std::vsnprintf(msg, sizeof(msg), fmt, ap);
  va_end(ap);
  ai(msg);
}

} // namespace op2::log
