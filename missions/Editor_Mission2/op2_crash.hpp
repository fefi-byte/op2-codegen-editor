#pragma once
// op2_crash.hpp - crash diagnostics for the mission DLL.
//
// Two layers, both writing the fault to the log so a crash leaves a breadcrumb instead of a silent death:
//   1) SEH guards (op2::crash::guard) wrap the engine entry points (InitProc / AIProc). A structured exception
//      (access violation, etc.) is logged with its code + faulting address, then SWALLOWED so the game keeps
//      running (the entry point just returns) instead of taking the whole process down.
//   2) A process-wide unhandled-exception filter (SetUnhandledExceptionFilter) catches faults outside those
//      guards - e.g. inside an engine-invoked trigger callback - and logs them as a last resort.
//
// KERNEL32-only; no <windows.h> (keeps the DLL's import table to KERNEL32, like the rest of TitanAPI). The
// minimal EXCEPTION_RECORD/POINTERS layouts below match the x86 ABI so we can read the code + address without
// pulling in the Windows headers.
//
// SEH (__try/__except) is MSVC-only. MinGW cross-builds get no-op stubs that simply call fn() directly.

#include "op2_log.hpp"

namespace op2::crash {

#ifdef _MSC_VER

#include <excpt.h>            // __try/__except + GetExceptionInformation

// Head of the x86 EXCEPTION_RECORD - enough for the exception code + faulting instruction address.
struct ExceptionRecord  { unsigned long code; unsigned long flags; void* pNext; void* address; };
struct ExceptionPointers { ExceptionRecord* record; void* context; };

extern "C" __declspec(dllimport) void* __stdcall SetUnhandledExceptionFilter(void* filter);

/// Log a fault (exception code + faulting address). Returns EXCEPTION_EXECUTE_HANDLER (1) so it can double as
/// an SEH filter expression.
inline long report(const char* where, ExceptionPointers* ep) {
  const unsigned long code = (ep && ep->record) ? ep->record->code    : 0UL;
  void* const         addr = (ep && ep->record) ? ep->record->address : nullptr;
  op2::log::linef("!!!!!!!! CRASH in %s : exception 0x%08lX at %p !!!!!!!!", where, code, addr);
  return 1;  // EXCEPTION_EXECUTE_HANDLER
}

/// Process-wide last-chance filter (catches faults outside the SEH guards, e.g. in trigger callbacks).
inline long __stdcall unhandledFilter(void* exceptionPointers) {
  return report("unhandled exception", reinterpret_cast<ExceptionPointers*>(exceptionPointers));
}

/// Install the unhandled-exception filter. Call once at DLL attach.
inline void installHandler() {
  SetUnhandledExceptionFilter(reinterpret_cast<void*>(&unhandledFilter));
}

/// Run fn() under an SEH guard: a structured exception is logged, then swallowed so the game keeps running.
/// The wrapper holds no C++ objects needing unwinding, so __try is permitted here (the C++ work lives in fn).
inline void guard(const char* where, void (*fn)()) {
  __try {
    fn();
  } __except (report(where, reinterpret_cast<ExceptionPointers*>(GetExceptionInformation()))) {
    // already logged in the filter expression; swallow and let the game continue
  }
}

#else // MinGW cross-compile: SEH not available, use no-op stubs

inline void installHandler() {}

inline void guard(const char* /*where*/, void (*fn)()) {
  fn();
}

#endif // _MSC_VER

} // namespace op2::crash
