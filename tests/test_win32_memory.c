/* Synthetic checks for runtime/win32_memory.c; no game code. */
#include <stdio.h>
#include <string.h>
#include "guest_memory.h"
#include "win32_memory.h"
#define CHECK(c) do { if (!(c)) { printf("failed: %s (line %d)\n", #c, __LINE__); return 1; } checks++; } while (0)
static uint8_t bytes[0x4000];
int main(void) {
    unsigned checks = 0;
    mh_guest_memory m;
    mh_win32_global_heap h;
    uint32_t v = 0;
    CHECK(mh_mem_init(&m, bytes, sizeof bytes, 0x10000));
    memset(bytes, 0xAB, sizeof bytes);
    /* GlobalAlloc: 8-byte alignment, zero fill, address order, limits and flags. */
    CHECK(!mh_win32_global_init(&h, 0x11004, 0x100));                  /* unaligned base rejected */
    CHECK(mh_win32_global_init(&h, 0x11000, 0x100));
    uint32_t a = mh_win32_global_alloc(&h, &m, MH_GMEM_FIXED, 3);
    uint32_t b = mh_win32_global_alloc(&h, &m, MH_GMEM_ZEROINIT, 9);
    uint32_t c = mh_win32_global_alloc(&h, &m, MH_GMEM_FIXED, 0);       /* zero bytes still yields a block */
    CHECK(a == 0x11000 && b == 0x11008 && c == 0x11018 && h.next == 0x11019);
    CHECK(bytes[0x1000] == 0 && bytes[0x1002] == 0 && bytes[0x1010] == 0 && bytes[0x1003] == 0xAB);
    CHECK(mh_win32_global_alloc(&h, &m, 0x2, 4) == 0 && h.next == 0x11019);   /* GMEM_MOVEABLE unsupported */
    CHECK(mh_win32_global_alloc(&h, &m, 0, 0x100) == 0 && h.next == 0x11019); /* out of space */
    CHECK(mh_win32_global_alloc(&h, &m, 0, 0xE0) == 0x11020 && h.next == 0x11100);
    /* Critical sections: initial state, recursion, owner checks. */
    const uint32_t cs = 0x12000;
    mh_win32_init_critical_section(&m, cs);
    CHECK(mh_mem_read_u32(&m, cs + 4, &v) && v == 0xffffffffu);
    CHECK(mh_win32_enter_critical_section(&m, cs, 7) && mh_win32_enter_critical_section(&m, cs, 7));
    CHECK(mh_mem_read_u32(&m, cs + 4, &v) && v == 1 && mh_mem_read_u32(&m, cs + 8, &v) && v == 2);
    CHECK(!mh_win32_enter_critical_section(&m, cs, 8));                 /* another thread would block */
    CHECK(!mh_win32_leave_critical_section(&m, cs, 8));                 /* non-owner leave rejected */
    CHECK(mh_win32_leave_critical_section(&m, cs, 7) && mh_mem_read_u32(&m, cs + 12, &v) && v == 7);
    CHECK(mh_win32_leave_critical_section(&m, cs, 7) && mh_mem_read_u32(&m, cs + 12, &v) && v == 0);
    CHECK(mh_mem_read_u32(&m, cs + 4, &v) && v == 0xffffffffu && mh_mem_read_u32(&m, cs + 8, &v) && v == 0);
    CHECK(!mh_win32_leave_critical_section(&m, cs, 7));                 /* unbalanced leave rejected */
    CHECK(!mh_win32_enter_critical_section(&m, 0x13ffc, 7));            /* section outside guest memory */
    printf("%u win32 memory shim checks passed\n", checks);
    return 0;
}
