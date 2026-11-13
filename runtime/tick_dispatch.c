#include "tick_dispatch.h"
#include <stdint.h>
static int tick_dispatch_overlaps(const void *a,size_t asize,const void *b,size_t bsize){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    if(!asize||!bsize)return 0;
    return x<=y?y-x<asize:x-y<bsize;
}
int mh_tick_dispatch_call(const mh_tick_dispatch *d,uint32_t *eax,uint32_t *esp){
    if(!d||!d->memory||!d->memory->bytes||!d->clock||!d->return_allowed||!eax||!esp||
       tick_dispatch_overlaps(eax,sizeof *eax,esp,sizeof *esp)||
       tick_dispatch_overlaps(eax,sizeof *eax,d->memory->bytes,d->memory->size)||
       tick_dispatch_overlaps(esp,sizeof *esp,d->memory->bytes,d->memory->size)||
       tick_dispatch_overlaps(eax,sizeof *eax,d,sizeof *d)||tick_dispatch_overlaps(esp,sizeof *esp,d,sizeof *d)||
       tick_dispatch_overlaps(eax,sizeof *eax,d->memory,sizeof *d->memory)||
       tick_dispatch_overlaps(esp,sizeof *esp,d->memory,sizeof *d->memory))return 0;
    mh_tick_x86_state state={*eax,*esp};uint32_t ret;
    if(!mh_tick_x86_invoke(d->memory,&state,d->clock,d->clock_context,&ret)||
       !d->return_allowed(d->return_context,ret))return 0;
    *eax=state.eax;*esp=state.esp;return 1;
}
