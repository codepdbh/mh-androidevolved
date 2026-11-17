#ifndef MH_WIN32_THREAD_H
#define MH_WIN32_THREAD_H
/* Per-thread Win32 state for translated code: the last-error value and
 * thread-local storage (TlsAlloc/TlsGetValue/TlsSetValue/TlsFree).
 *
 * Single guest thread. Semantics follow the documented behaviour:
 * TLS indexes are handed out lowest-free first (0..63), new and freed slots
 * read as 0, TlsGetValue sets the last error to ERROR_SUCCESS when it
 * succeeds (callers use GetLastError to tell a stored 0 from a failure), and
 * an invalid index fails with ERROR_INVALID_PARAMETER. */
#include <stdint.h>

#define MH_TLS_SLOTS 64u
#define MH_TLS_OUT_OF_INDEXES 0xffffffffu
#define MH_ERROR_SUCCESS 0u
#define MH_ERROR_INVALID_PARAMETER 87u

typedef struct {
    uint32_t last_error;
    uint64_t tls_used;               /* bit i: index i allocated */
    uint32_t tls[MH_TLS_SLOTS];
} mh_win32_thread;

void mh_win32_thread_init(mh_win32_thread *thread);
uint32_t mh_win32_get_last_error(const mh_win32_thread *thread);
void mh_win32_set_last_error(mh_win32_thread *thread, uint32_t error);
uint32_t mh_win32_tls_alloc(mh_win32_thread *thread);
uint32_t mh_win32_tls_get_value(mh_win32_thread *thread, uint32_t index);
int mh_win32_tls_set_value(mh_win32_thread *thread, uint32_t index, uint32_t value);
int mh_win32_tls_free(mh_win32_thread *thread, uint32_t index);
#endif
