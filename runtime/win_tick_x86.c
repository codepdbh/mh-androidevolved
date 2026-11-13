#include "win_tick.h"
#include <stdint.h>

static int overlaps(const void *a,size_t asize,const void *b,size_t bsize){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    if(!asize||!bsize)return 0;
    return x<=y?y-x<asize:x-y<bsize;
}
int mh_tick_x86_return(const mh_guest_memory *memory,mh_tick_x86_state *state,
                       uint32_t tick,uint32_t *return_address){
    uint32_t ret;
    if(!memory||!memory->bytes||!state||!return_address||
       overlaps(state,sizeof *state,memory->bytes,memory->size)||
       overlaps(return_address,sizeof *return_address,memory->bytes,memory->size)||
       overlaps(state,sizeof *state,memory,sizeof *memory)||
       overlaps(return_address,sizeof *return_address,memory,sizeof *memory)||
       overlaps(state,sizeof *state,return_address,sizeof *return_address)||
       state->esp>UINT32_MAX-4u||
       !mh_mem_read_u32(memory,state->esp,&ret))return 0;
    state->eax=tick;
    state->esp+=4u;
    *return_address=ret;
    return 1;
}

int mh_tick_x86_invoke(const mh_guest_memory *memory,mh_tick_x86_state *state,
                       mh_tick_clock clock,void *context,uint32_t *return_address){
    uint32_t tick;
    if(!clock||!clock(context,&tick))return 0;
    return mh_tick_x86_return(memory,state,tick,return_address);
}
