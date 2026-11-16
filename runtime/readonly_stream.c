#define _POSIX_C_SOURCE 200809L
#include "readonly_stream.h"
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
_Static_assert(sizeof(off_t)>=8,"readonly streams require 64-bit file offsets");

static int ro_overlap(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return n&&m&&(x<=y?y-x<n:x-y<m);
}
int mh_ro_open_descriptor(mh_readonly_stream *s,int fd){
    struct stat st;
    if(!s||s->fd!=-1||fd<0)return MH_RO_INVALID;
    int flags=fcntl(fd,F_GETFL);
    if(flags<0||fstat(fd,&st)!=0)return MH_RO_IO;
    if((flags&O_ACCMODE)!=O_RDONLY||!S_ISREG(st.st_mode))return MH_RO_UNSUPPORTED;
    int owned=fcntl(fd,F_DUPFD_CLOEXEC,0);
    if(owned<0)return MH_RO_IO;
    s->fd=owned;s->position=0;return MH_RO_OK;
}
void mh_ro_close(mh_readonly_stream *s){
    if(!s)return;
    if(s->fd>=0)close(s->fd);
    s->fd=-1;s->position=0;
}
int mh_ro_seek(mh_readonly_stream *s,uint64_t position){
    if(!s||s->fd<0||position>INT64_MAX)return MH_RO_INVALID;
    s->position=position;return MH_RO_OK;
}
int mh_ro_read_guest(mh_readonly_stream *s,mh_guest_memory *m,uint32_t buffer,
                     uint32_t requested,uint32_t out,uint32_t overlapped){
    if(!s||!m||!m->bytes||!out||
       ro_overlap(s,sizeof *s,m->bytes,m->size)||ro_overlap(m,sizeof *m,m->bytes,m->size)||
       ro_overlap(s,sizeof *s,m,sizeof *m))return MH_RO_INVALID;
    uint8_t *count=mh_mem_span(m,out,4);
    if(!count)return MH_RO_INVALID;
    if(requested && (uint64_t)buffer<(uint64_t)out+4 && (uint64_t)out<(uint64_t)buffer+requested)return MH_RO_INVALID;
    mh_mem_write_u32(m,out,0);
    if(overlapped||requested>1024u*1024u)return MH_RO_UNSUPPORTED;
    if(s->fd<0||s->position>INT64_MAX||requested>(uint64_t)INT64_MAX-s->position)return MH_RO_INVALID;
    uint8_t *dest=requested?mh_mem_span(m,buffer,requested):NULL;
    if(requested&&!dest)return MH_RO_INVALID;
    if(!requested)return MH_RO_OK;
    uint8_t *scratch=malloc(requested);
    if(!scratch)return MH_RO_NOMEM;
    ssize_t n;
    do{n=pread(s->fd,scratch,requested,(off_t)s->position);}while(n<0&&errno==EINTR);
    if(n<0){free(scratch);return MH_RO_IO;}
    if((uint64_t)n>requested){free(scratch);return MH_RO_IO;}
    if(n)memcpy(dest,scratch,(size_t)n);
    free(scratch);s->position+=(uint64_t)n;
    mh_mem_write_u32(m,out,(uint32_t)n);return MH_RO_OK;
}
