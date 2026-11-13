#ifndef MANHUNT_GUEST_MEMORY_H
#define MANHUNT_GUEST_MEMORY_H

#include <stddef.h>
#include <stdint.h>

/* A contiguous, explicitly mapped guest region. The caller owns the backing bytes. */
typedef struct {
    uint8_t *bytes;
    size_t size;
    uint32_t guest_base;
} mh_guest_memory;

/* Nonzero on success. All failed operations leave output and memory unchanged. */
int mh_mem_init(mh_guest_memory *mem, uint8_t *bytes, size_t size, uint32_t guest_base);
int mh_mem_read(const mh_guest_memory *mem, uint32_t address, void *out, size_t size);
int mh_mem_write(mh_guest_memory *mem, uint32_t address, const void *data, size_t size);
int mh_mem_read_u32(const mh_guest_memory *mem, uint32_t address, uint32_t *out);
int mh_mem_write_u32(mh_guest_memory *mem, uint32_t address, uint32_t value);
/* Resolve a nonempty in-range span; returns NULL on failure. The owner must
 * keep the region alive and must enforce any required host alignment. */
uint8_t *mh_mem_span(mh_guest_memory *mem, uint32_t address, size_t size);

#endif
