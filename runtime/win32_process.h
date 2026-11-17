#ifndef MH_WIN32_PROCESS_H
#define MH_WIN32_PROCESS_H
/* Process-level Win32 state for translated code, as the CRT start-up sees it.
 *
 * - Command line and environment live in a caller-provided guest block:
 *   the command line `"manhunt.exe"` at +0 and an empty environment block
 *   (two NULs) at +0x100. GetEnvironmentStrings returns that block and
 *   FreeEnvironmentStringsA accepts only it.
 * - The game is a GUI process without a console: GetStdHandle returns NULL
 *   for every standard handle.
 * - GetCurrentProcess returns the pseudo-handle -1. DuplicateHandle is only
 *   modelled for a NULL source handle, which fails with ERROR_INVALID_HANDLE
 *   like Windows; any other source is reported as unsupported.
 * - CreateEventA returns distinct handles 0x50000001, 0x50000002, ... The
 *   event objects themselves (signal/wait) are not modelled yet. */
#include <stdint.h>
#include "guest_memory.h"
#include "win32_thread.h"

#define MH_PROCESS_BLOCK_SIZE 0x200u
#define MH_ERROR_INVALID_HANDLE 6u
#define MH_EVENT_HANDLE_BASE 0x50000000u

typedef struct {
    uint32_t block;     /* guest address of the command line/environment block */
    uint32_t events;    /* events created so far */
} mh_win32_process;

int mh_win32_process_init(mh_win32_process *process, mh_guest_memory *memory, uint32_t block);
uint32_t mh_win32_get_command_line(const mh_win32_process *process);
uint32_t mh_win32_get_environment_strings(const mh_win32_process *process);
uint32_t mh_win32_free_environment_strings(const mh_win32_process *process, uint32_t block);
uint32_t mh_win32_get_std_handle(uint32_t which);
uint32_t mh_win32_get_current_process(void);
/* Returns 0 (failure, last error set) for a NULL source; -1 when the case is not modelled. */
int mh_win32_duplicate_handle(mh_win32_thread *thread, uint32_t source_handle);
uint32_t mh_win32_create_event(mh_win32_process *process);
#endif
