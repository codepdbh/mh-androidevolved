#include "win32_thread.h"
#include <string.h>

void mh_win32_thread_init(mh_win32_thread *thread) { memset(thread, 0, sizeof *thread); }
uint32_t mh_win32_get_last_error(const mh_win32_thread *thread) { return thread->last_error; }
void mh_win32_set_last_error(mh_win32_thread *thread, uint32_t error) { thread->last_error = error; }

static int allocated(const mh_win32_thread *thread, uint32_t index) {
    return index < MH_TLS_SLOTS && (thread->tls_used >> index & 1u);
}

uint32_t mh_win32_tls_alloc(mh_win32_thread *thread) {
    for (uint32_t i = 0; i < MH_TLS_SLOTS; i++)
        if (!allocated(thread, i)) {
            thread->tls_used |= (uint64_t)1 << i;
            thread->tls[i] = 0;
            return i;
        }
    return MH_TLS_OUT_OF_INDEXES;
}

uint32_t mh_win32_tls_get_value(mh_win32_thread *thread, uint32_t index) {
    if (!allocated(thread, index)) { thread->last_error = MH_ERROR_INVALID_PARAMETER; return 0; }
    thread->last_error = MH_ERROR_SUCCESS;
    return thread->tls[index];
}

int mh_win32_tls_set_value(mh_win32_thread *thread, uint32_t index, uint32_t value) {
    if (!allocated(thread, index)) { thread->last_error = MH_ERROR_INVALID_PARAMETER; return 0; }
    thread->tls[index] = value;
    return 1;
}

int mh_win32_tls_free(mh_win32_thread *thread, uint32_t index) {
    if (!allocated(thread, index)) { thread->last_error = MH_ERROR_INVALID_PARAMETER; return 0; }
    thread->tls_used &= ~((uint64_t)1 << index);
    thread->tls[index] = 0;
    return 1;
}
