#ifndef MANHUNT_PE32_IMPORT_PLAN_H
#define MANHUNT_PE32_IMPORT_PLAN_H
#include "pe32_imports.h"

enum { MH_IMPORT_ERROR=-1, MH_IMPORT_MISSING=0, MH_IMPORT_FOUND=1 };
typedef int (*mh_import_resolver)(const mh_pe32_import *item,void *context,uint32_t *guest_target);
typedef struct { uint32_t iat_address,original_value,target; int resolved; } mh_import_plan_entry;

/* Builds a plan without changing the image. NULL resolver means all missing.
 * A FOUND target must be a nonzero guest address, not a host pointer. The
 * caller owns a non-overlapping scratch array; on failure its contents are
 * unspecified, while count/missing and the image remain unchanged. The resolver
 * must not mutate the image, metadata, scratch array or output counters. */
int mh_pe32_plan_imports(const mh_guest_memory *region,const mh_pe32_info *info,
                         mh_import_resolver resolver,void *context,
                         mh_import_plan_entry *entries,size_t capacity,
                         size_t *count,size_t *missing);

/* Applies only a complete plan whose IAT values still equal their snapshots.
 * Validates every entry before writing. Caller must exclude concurrent writes. */
int mh_pe32_apply_import_plan(mh_guest_memory *region,const mh_import_plan_entry *entries,size_t count);
#endif
