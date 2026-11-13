#include "guest_memory.h"
#include <string.h>

int mh_mem_init(mh_guest_memory *mem, uint8_t *bytes, size_t size, uint32_t base) {
    if (!mem || !bytes || size == 0 || (uint64_t)size > UINT64_C(0x100000000) - base) return 0;
    mem->bytes = bytes; mem->size = size; mem->guest_base = base;
    return 1;
}

static int offset_for(const mh_guest_memory *mem, uint32_t address, size_t size, size_t *offset) {
    if (!mem || !mem->bytes || address < mem->guest_base) return 0;
    size_t start = (size_t)((uint64_t)address - mem->guest_base);
    if (start > mem->size || size > mem->size - start) return 0;
    *offset = start;
    return 1;
}

uint8_t *mh_mem_span(mh_guest_memory *mem, uint32_t address, size_t size) {
    size_t offset;
    if (!size || !offset_for(mem, address, size, &offset)) return NULL;
    return mem->bytes + offset;
}

int mh_mem_read(const mh_guest_memory *mem, uint32_t address, void *out, size_t size) {
    size_t offset;
    if ((!out && size) || !offset_for(mem, address, size, &offset)) return 0;
    if (size) memmove(out, mem->bytes + offset, size);
    return 1;
}

int mh_mem_write(mh_guest_memory *mem, uint32_t address, const void *data, size_t size) {
    size_t offset;
    if ((!data && size) || !offset_for(mem, address, size, &offset)) return 0;
    if (size) memmove(mem->bytes + offset, data, size);
    return 1;
}

int mh_mem_read_u32(const mh_guest_memory *mem, uint32_t address, uint32_t *out) {
    uint8_t b[4];
    if (!out || !mh_mem_read(mem, address, b, sizeof b)) return 0;
    *out = (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
    return 1;
}

int mh_mem_write_u32(mh_guest_memory *mem, uint32_t address, uint32_t value) {
    uint8_t b[4] = {(uint8_t)value, (uint8_t)(value >> 8), (uint8_t)(value >> 16), (uint8_t)(value >> 24)};
    return mh_mem_write(mem, address, b, sizeof b);
}
