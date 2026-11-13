#ifndef MANHUNT_WIN_TICK_H
#define MANHUNT_WIN_TICK_H
#include <stdint.h>
#include "guest_memory.h"

/* Convert elapsed boot time to a wrapping 32-bit millisecond count. On failure
 * the output is unchanged. This is a helper, not an x86 ABI thunk. */
int mh_tick_from_elapsed(uint64_t seconds, uint32_t nanoseconds, uint32_t *out);

/* Android CLOCK_BOOTTIME includes suspend. Returns zero if the clock fails. */
int mh_android_boot_tick_count(uint32_t *out);
int mh_android_boot_tick_provider(void *context, uint32_t *out);

typedef struct { uint32_t eax, esp; } mh_tick_x86_state;
/* Model the no-argument x86 return after obtaining a tick: read the guest
 * return address from the stack, place the tick in EAX, and pop four bytes.
 * State and return address must not overlap the guest region, metadata or each
 * other. The caller handles dispatch to the returned address. */
int mh_tick_x86_return(const mh_guest_memory *memory, mh_tick_x86_state *state,
                       uint32_t tick, uint32_t *return_address);
/* Clock must write tick on success and must not mutate the state or guest
 * memory. Its failure leaves the state and return-address output unchanged. */
typedef int (*mh_tick_clock)(void *context, uint32_t *tick);
int mh_tick_x86_invoke(const mh_guest_memory *memory, mh_tick_x86_state *state,
                       mh_tick_clock clock, void *context, uint32_t *return_address);
#endif
