#ifndef MANHUNT_IMPORT_REGISTRY_H
#define MANHUNT_IMPORT_REGISTRY_H
#include "pe32_import_plan.h"

/* Registry owns neither names nor entries. Targets are 32-bit guest addresses,
 * never native function pointers. DLL names are ASCII case-insensitive; export
 * names are case-sensitive. The owner keeps the table immutable during use. */
typedef struct {
    const char *dll;
    const char *name; /* NULL for ordinal exports */
    uint16_t ordinal;
    uint32_t guest_target;
} mh_import_binding;
typedef struct { const mh_import_binding *entries; size_t count; } mh_import_registry;

/* Returns MH_IMPORT_ERROR for invalid or ambiguous bindings, MH_IMPORT_MISSING
 * when no binding matches, or MH_IMPORT_FOUND and writes a nonzero target. */
int mh_import_registry_resolve(const mh_pe32_import *item, void *context, uint32_t *target);
#endif
