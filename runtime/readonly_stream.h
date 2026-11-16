#ifndef MH_READONLY_STREAM_H
#define MH_READONLY_STREAM_H
#include "guest_memory.h"
#include <stdint.h>
typedef struct { int fd; uint64_t position; } mh_readonly_stream;
#define MH_READONLY_STREAM_INIT { -1, 0 }
enum { MH_RO_OK=0, MH_RO_INVALID=1, MH_RO_IO=2, MH_RO_NOMEM=3, MH_RO_UNSUPPORTED=4 };

/* POSIX/Android backend for regular read-only descriptors, including seekable
 * descriptors supplied by an Android content provider. Duplicates fd and owns
 * the duplicate. Its independent cursor starts at zero; never changes the
 * borrowed descriptor's offset. Caller serializes access and keeps metadata
 * outside guest memory. No path opening, writes or Win32 handle table here. */
int mh_ro_open_descriptor(mh_readonly_stream *stream,int fd);
void mh_ro_close(mh_readonly_stream *stream);
int mh_ro_seek(mh_readonly_stream *stream,uint64_t position);

/* Synchronous subset only: nonzero count output, no OVERLAPPED, <=1 MiB per
 * call, disjoint guest outputs. Invalid ranges cause no I/O. A valid count
 * output is zeroed on handle/I/O failure. Buffer/cursor commit only on success.
 * EOF succeeds with zero bytes. Does not implement all ReadFile semantics. */
int mh_ro_read_guest(mh_readonly_stream *stream,mh_guest_memory *memory,
                     uint32_t buffer,uint32_t requested,uint32_t bytes_read,uint32_t overlapped);
#endif
