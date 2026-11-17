#include "win32_process.h"

static const char command_line[] = "\"manhunt.exe\"";

int mh_win32_process_init(mh_win32_process *process, mh_guest_memory *memory, uint32_t block) {
    uint8_t *span = mh_mem_span(memory, block, MH_PROCESS_BLOCK_SIZE);
    if (!process || !span) return 0;
    for (uint32_t i = 0; i < MH_PROCESS_BLOCK_SIZE; i++) span[i] = 0;
    for (uint32_t i = 0; i < sizeof command_line; i++) span[i] = (uint8_t)command_line[i];   /* includes the NUL */
    process->block = block;
    process->events = 0;
    return 1;
}

uint32_t mh_win32_get_command_line(const mh_win32_process *process) { return process->block; }
uint32_t mh_win32_get_environment_strings(const mh_win32_process *process) { return process->block + 0x100u; }
uint32_t mh_win32_free_environment_strings(const mh_win32_process *process, uint32_t block) {
    return block == process->block + 0x100u;
}
uint32_t mh_win32_get_std_handle(uint32_t which) { (void)which; return 0; }
uint32_t mh_win32_get_current_process(void) { return 0xffffffffu; }

int mh_win32_duplicate_handle(mh_win32_thread *thread, uint32_t source_handle) {
    if (source_handle != 0) return -1;
    mh_win32_set_last_error(thread, MH_ERROR_INVALID_HANDLE);
    return 0;
}

uint32_t mh_win32_create_event(mh_win32_process *process) {
    process->events++;
    return MH_EVENT_HANDLE_BASE | process->events;
}
