#ifndef MH_PROTECTION_REDIRECT_H
#define MH_PROTECTION_REDIRECT_H
/* Replacement for the two call redirections of the executable's protection
 * wrapper (user's own copy; see docs/BOOT_PROTECTION_BLOCKER.md). The wrapper
 * itself is never executed.
 *
 * Header stub (call 0x400080): the stub walks a table of (IAT slot, return
 * address) pairs downwards from 0x40087c until a zero return address and
 * jumps to the import in the matching slot. mh_header_redirect_slot() does the
 * same lookup over the mapped image; the caller then calls the import with the
 * caller's return address still on the stack (a tail jump).
 *
 * .prus slot (call [0x850000]): each call site was classified statically by
 * tools/resolve_protection_redirects.py into a table sorted by return address.
 * mh_redirect_find() looks a return address up in it. */
#include <stddef.h>
#include <stdint.h>
#include "guest_memory.h"

#define MH_HEADER_STUB_VA   0x400080u
#define MH_HEADER_TABLE_END 0x40087cu
#define MH_HEADER_TABLE_MIN 0x400100u   /* table never reaches into the stub */
#define MH_PRUS_SLOT_VA     0x850000u

/* INTEGRITY: an anti-tamper check that requires eax == value (tools/resolve_protection_redirects.py). */
/* RESUME: the intact wrapper removes `args` stdcall arguments and continues at `value`. */
/* MIRROR: returns value, removes `args & 0x7f` header arguments and, with 0x80, stores value at the
 * triple's pointer; STORE: [ebx] = ecx (tools/resolve_protection_redirects.py). */
enum { MH_REDIRECT_GET_LAST_ERROR = 1, MH_REDIRECT_VALIDATE_POINTER = 2, MH_REDIRECT_TRIGGER = 3, MH_REDIRECT_INTEGRITY = 4, MH_REDIRECT_RESUME = 5,
       MH_REDIRECT_MIRROR = 6, MH_REDIRECT_STORE = 7 };
typedef struct { uint32_t return_address; uint8_t kind; uint32_t value; uint8_t args; } mh_redirect_site;

/* Nonzero and *slot set when `return_address` is in the header table. */
int mh_header_redirect_slot(const mh_guest_memory *image, uint32_t return_address, uint32_t *slot);
/* Site for `return_address` in a table sorted by return address, or NULL. */
const mh_redirect_site *mh_redirect_find(const mh_redirect_site *sites, size_t count, uint32_t return_address);
/* IsBadReadPtr/IsBadWritePtr over guest memory: 0 when [pointer, pointer+size) is
 * mapped (or size is 0), 1 otherwise. */
uint32_t mh_redirect_validate_pointer(mh_guest_memory *memory, uint32_t pointer, uint32_t size);
#endif
