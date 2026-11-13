#ifndef MANHUNT_TICK_DISPATCH_H
#define MANHUNT_TICK_DISPATCH_H
#include "win_tick.h"

typedef int (*mh_tick_return_allowed)(void *context,uint32_t return_address);
typedef struct {
    const mh_guest_memory *memory;
    mh_tick_clock clock;
    void *clock_context;
    mh_tick_return_allowed return_allowed;
    void *return_context;
} mh_tick_dispatch;

/* Callbacks and guest memory must remain stable and must not mutate registers.
 * Rejects invalid arguments, clock/stack failures and unapproved return VAs.
 * On failure both register outputs are unchanged; caller must stop dispatch. */
int mh_tick_dispatch_call(const mh_tick_dispatch *dispatch,uint32_t *eax,uint32_t *esp);
#endif
