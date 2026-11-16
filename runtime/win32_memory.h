#ifndef MH_WIN32_MEMORY_H
#define MH_WIN32_MEMORY_H
/* Minimal Win32 memory and synchronisation shims over guest memory.
 *
 * GlobalAlloc: only GMEM_FIXED (0) and GMEM_ZEROINIT (0x40) are accepted;
 * blocks come from a caller-provided guest region in address order, 8-byte
 * aligned like Windows, and are always zero-filled so results are
 * deterministic. Out of space or other flags -> 0. No GlobalFree yet.
 *
 * Critical sections: single-threaded model of the documented
 * RTL_CRITICAL_SECTION fields (+4 LockCount, +8 RecursionCount,
 * +0xc OwningThread), as left by InitializeCriticalSection (LockCount -1).
 * Enter/Leave never block; Leave by a non-owner is reported as an error.
 * Neither shim touches guest registers; callers model the stdcall frame. */
#include <stdint.h>
#include "guest_memory.h"

#define MH_GMEM_FIXED 0x0000u
#define MH_GMEM_ZEROINIT 0x0040u
typedef struct { uint32_t base, limit, next; } mh_win32_global_heap;

int mh_win32_global_init(mh_win32_global_heap *heap, uint32_t base, uint32_t size);
uint32_t mh_win32_global_alloc(mh_win32_global_heap *heap, mh_guest_memory *memory, uint32_t flags, uint32_t bytes);

void mh_win32_init_critical_section(mh_guest_memory *memory, uint32_t section);
int mh_win32_enter_critical_section(mh_guest_memory *memory, uint32_t section, uint32_t thread);
int mh_win32_leave_critical_section(mh_guest_memory *memory, uint32_t section, uint32_t thread);
#endif
