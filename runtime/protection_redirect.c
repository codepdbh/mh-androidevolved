#include "protection_redirect.h"

int mh_header_redirect_slot(const mh_guest_memory *image, uint32_t return_address, uint32_t *slot) {
    if (!image || !slot || !return_address) return 0;
    for (uint32_t at = MH_HEADER_TABLE_END; at >= MH_HEADER_TABLE_MIN; at -= 8) {
        uint32_t ret = 0, entry = 0;
        if (!mh_mem_read_u32(image, at, &ret) || !ret) return 0;
        if (ret == return_address) {
            if (!mh_mem_read_u32(image, at - 4, &entry)) return 0;
            *slot = entry;
            return 1;
        }
    }
    return 0;
}

const mh_redirect_site *mh_redirect_find(const mh_redirect_site *sites, size_t count, uint32_t return_address) {
    size_t lo = 0, hi = count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (sites[mid].return_address == return_address) return &sites[mid];
        if (sites[mid].return_address < return_address) lo = mid + 1; else hi = mid;
    }
    return NULL;
}

uint32_t mh_redirect_validate_pointer(mh_guest_memory *memory, uint32_t pointer, uint32_t size) {
    if (!size) return 0;
    return mh_mem_span(memory, pointer, size) ? 0u : 1u;
}
