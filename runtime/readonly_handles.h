#ifndef MH_READONLY_HANDLES_H
#define MH_READONLY_HANDLES_H
#include "readonly_stream.h"
#define MH_RO_HANDLE_SLOTS 16u
typedef struct { mh_readonly_stream stream; uint32_t generation; } mh_ro_slot;
typedef struct { int root_fd; mh_ro_slot slots[MH_RO_HANDLE_SLOTS]; } mh_ro_handles;
#define MH_RO_HANDLES_INIT { .root_fd=-1 }

/* Initialized table owns a duplicate read-only directory descriptor. Names are
 * bounded relative paths with slash/backslash separators. Absolute paths,
 * empty components, dot/dot-dot, colon and all symlink components are rejected.
 * Exact filename case only. Callers serialize all operations; host outputs and
 * metadata must not alias the table or guest memory. Not a full Win32 API. */
int mh_ro_bind_root(mh_ro_handles *table,int directory_fd);
void mh_ro_unbind(mh_ro_handles *table);
int mh_ro_open_relative(mh_ro_handles *table,const char *name,uint32_t *handle);
int mh_ro_close_handle(mh_ro_handles *table,uint32_t handle);
int mh_ro_handle_seek(mh_ro_handles *table,uint32_t handle,uint64_t position);
int mh_ro_handle_read(mh_ro_handles *table,uint32_t handle,mh_guest_memory *memory,
                      uint32_t buffer,uint32_t requested,uint32_t bytes_read,uint32_t overlapped);
#endif
