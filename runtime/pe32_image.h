#ifndef MANHUNT_PE32_IMAGE_H
#define MANHUNT_PE32_IMAGE_H
#include <stddef.h>
#include <stdint.h>
#include "guest_memory.h"

typedef struct {
    uint32_t image_base, image_size, entry_rva;
    uint16_t section_count;
} mh_pe32_info;

/* Maps headers and sections at their preferred base. Input and output buffers
 * must not overlap; metadata must not overlap either buffer. Overlap is rejected.
 * Does not execute code, relocate, resolve imports or TLS.
 * On validation failure, region and info are not modified. */
int mh_pe32_map_image(const uint8_t *file, size_t file_size,
                      mh_guest_memory *region, mh_pe32_info *info);
#endif
