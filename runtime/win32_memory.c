#include "win32_memory.h"
#include <string.h>

int mh_win32_global_init(mh_win32_global_heap *heap, uint32_t base, uint32_t size) {
    if (!heap || (base & 7u) || !size || (uint64_t)base + size > UINT32_MAX) return 0;
    heap->base = base; heap->limit = base + size; heap->next = base;
    return 1;
}

uint32_t mh_win32_global_alloc(mh_win32_global_heap *heap, mh_guest_memory *memory, uint32_t flags, uint32_t bytes) {
    if (!heap || !memory || (flags & ~MH_GMEM_ZEROINIT)) return 0;
    uint64_t start = ((uint64_t)heap->next + 7u) & ~(uint64_t)7u;
    uint64_t size = bytes ? bytes : 1u;           /* Windows returns a valid block for 0 bytes */
    if (start + size > heap->limit) return 0;
    uint8_t *span = mh_mem_span(memory, (uint32_t)start, (size_t)size);
    if (!span) return 0;
    memset(span, 0, (size_t)size);
    heap->next = (uint32_t)(start + size);
    return (uint32_t)start;
}

void mh_win32_init_critical_section(mh_guest_memory *memory, uint32_t section) {
    for (uint32_t i = 0; i < 24; i += 4) mh_mem_write_u32(memory, section + i, 0);
    mh_mem_write_u32(memory, section + 4, 0xffffffffu);
}

int mh_win32_enter_critical_section(mh_guest_memory *memory, uint32_t section, uint32_t thread) {
    uint32_t lock, recursion, owner;
    if (!mh_mem_read_u32(memory, section + 4, &lock) || !mh_mem_read_u32(memory, section + 8, &recursion) ||
        !mh_mem_read_u32(memory, section + 12, &owner)) return 0;
    if (recursion && owner != thread) return 0;   /* would block: impossible with one thread */
    return mh_mem_write_u32(memory, section + 4, lock + 1) && mh_mem_write_u32(memory, section + 8, recursion + 1) &&
           mh_mem_write_u32(memory, section + 12, thread);
}

int mh_win32_leave_critical_section(mh_guest_memory *memory, uint32_t section, uint32_t thread) {
    uint32_t lock, recursion, owner;
    if (!mh_mem_read_u32(memory, section + 4, &lock) || !mh_mem_read_u32(memory, section + 8, &recursion) ||
        !mh_mem_read_u32(memory, section + 12, &owner)) return 0;
    if (!recursion || owner != thread) return 0;
    return mh_mem_write_u32(memory, section + 4, lock - 1) && mh_mem_write_u32(memory, section + 8, recursion - 1) &&
           mh_mem_write_u32(memory, section + 12, recursion == 1 ? 0 : thread);
}
