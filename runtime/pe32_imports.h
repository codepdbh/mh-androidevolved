#ifndef MANHUNT_PE32_IMPORTS_H
#define MANHUNT_PE32_IMPORTS_H
#include "pe32_image.h"

typedef struct {
    const char *dll;       /* Borrowed NUL-terminated strings in the mapped image. */
    const char *name;      /* NULL for an ordinal import. */
    uint32_t iat_address;  /* Guest address, never a host pointer. */
    uint16_t ordinal;
    int by_ordinal;
} mh_pe32_import;
typedef int (*mh_pe32_import_visitor)(const mh_pe32_import *item, void *context);

/* Validates the entire import table before the first callback. No IAT writes.
 * A visitor returning zero aborts enumeration. `count` changes only on success.
 * Image and metadata must remain unchanged until the call completes. The
 * output count must not overlap the image or metadata. */
int mh_pe32_visit_imports(const mh_guest_memory *region, const mh_pe32_info *info,
                          mh_pe32_import_visitor visitor, void *context, size_t *count);
#endif
