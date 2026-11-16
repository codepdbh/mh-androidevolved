#define _POSIX_C_SOURCE 200809L
#include "readonly_handles.h"
#include "readonly_path.h"
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define RO_GENERATION_MAX 0x03ffffffu
static int handles_overlap(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return n&&m&&(x<=y?y-x<n:x-y<m);
}
static mh_ro_slot *find_slot(mh_ro_handles *t,uint32_t h){
    if(!t||t->root_fd<0||(h&0xc0000000u)!=0x40000000u)return NULL;
    mh_ro_slot *s=&t->slots[h&15u];uint32_t generation=(h>>4)&RO_GENERATION_MAX;
    return generation&&s->generation==generation&&s->stream.fd>=0?s:NULL;
}
int mh_ro_bind_root(mh_ro_handles *t,int fd){
    struct stat st;
    if(!t||t->root_fd!=-1||fd<0)return MH_RO_INVALID;
    int flags=fcntl(fd,F_GETFL);
    if(flags<0||fstat(fd,&st)!=0)return MH_RO_IO;
    if((flags&O_ACCMODE)!=O_RDONLY||!S_ISDIR(st.st_mode))return MH_RO_UNSUPPORTED;
    int owned=fcntl(fd,F_DUPFD_CLOEXEC,0);
    if(owned<0)return MH_RO_IO;
    for(unsigned i=0;i<MH_RO_HANDLE_SLOTS;i++){
        if(!t->slots[i].generation)t->slots[i].generation=1;
        t->slots[i].stream.fd=-1;t->slots[i].stream.position=0;
    }
    t->root_fd=owned;return MH_RO_OK;
}
int mh_ro_close_handle(mh_ro_handles *t,uint32_t handle){
    mh_ro_slot *s=find_slot(t,handle);
    if(!s)return MH_RO_INVALID;
    mh_ro_close(&s->stream);s->generation++; /* Retire instead of wrapping. */
    return MH_RO_OK;
}
void mh_ro_unbind(mh_ro_handles *t){
    if(!t||t->root_fd<0)return;
    for(unsigned i=0;i<MH_RO_HANDLE_SLOTS;i++)if(t->slots[i].stream.fd>=0){mh_ro_close(&t->slots[i].stream);t->slots[i].generation++;}
    close(t->root_fd);t->root_fd=-1;
}
int mh_ro_open_relative(mh_ro_handles *t,const char *name,uint32_t *out){
    if(!t||t->root_fd<0||!name||!out||handles_overlap(out,sizeof *out,t,sizeof *t))return MH_RO_INVALID;
    char path[MH_RO_PATH_CAPACITY];
    if(!mh_ro_normalize_relative(name,path,sizeof path))return MH_RO_INVALID;
    unsigned slot=0;
    while(slot<MH_RO_HANDLE_SLOTS && (t->slots[slot].stream.fd>=0||t->slots[slot].generation>RO_GENERATION_MAX))slot++;
    if(slot==MH_RO_HANDLE_SLOTS)return MH_RO_NOMEM;
    int directory=t->root_fd,owned_directory=-1;char *component=path;
    while(1){
        char *separator=strchr(component,'/');if(separator)*separator=0;
        int flags=O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK|(separator?O_DIRECTORY:0);
        int fd=openat(directory,component,flags);
        if(owned_directory>=0)close(owned_directory);
        if(fd<0)return MH_RO_IO;
        if(!separator){
            int status=mh_ro_open_descriptor(&t->slots[slot].stream,fd);close(fd);
            if(status!=MH_RO_OK)return status;
            *out=0x40000000u|(t->slots[slot].generation<<4)|slot;return MH_RO_OK;
        }
        directory=fd;owned_directory=fd;component=separator+1;
    }
}
int mh_ro_handle_seek(mh_ro_handles *t,uint32_t h,uint64_t p){
    mh_ro_slot *s=find_slot(t,h);return s?mh_ro_seek(&s->stream,p):MH_RO_INVALID;
}
int mh_ro_handle_read(mh_ro_handles *t,uint32_t h,mh_guest_memory *m,uint32_t b,uint32_t n,uint32_t out,uint32_t ov){
    if(!t||!m||!m->bytes||handles_overlap(t,sizeof *t,m->bytes,m->size)||handles_overlap(t,sizeof *t,m,sizeof *m))return MH_RO_INVALID;
    mh_ro_slot *s=find_slot(t,h);mh_readonly_stream invalid=MH_READONLY_STREAM_INIT;
    return mh_ro_read_guest(s?&s->stream:&invalid,m,b,n,out,ov);
}
