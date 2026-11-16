/* Tiny private translation harness: synthetic stack, registers and callee. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
static _Alignas(8) uint8_t guest[256];
static uint32_t argument,calls;
void mh_guest_fault(uint32_t a,size_t n){(void)a;(void)n;exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){(void)a;(void)c;exit(74);}
recomp_func_t recomp_lookup(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
void sub_00401B00(void){
    if(MEM32(g_esp)!=0x40103e || MEM32(g_esp+4)!=argument || g_ecx!=0x67d000)exit(80);
    calls++;g_esp+=8; /* Synthetic callee, no allocator or game behaviour. */
}
#include "free_wrapper_unit.c"
int main(void){
    const uint32_t values[]={0,1,0x12345678u,0xffffffffu};
    if(!mh_mem_init(&mh_recomp_region,guest,sizeof guest,0x10000))return 71;
    for(unsigned k=0;k<16;k++){
        uint32_t sp=0x10080+k%4;argument=values[k/4];calls=0;memset(guest,0xa5,sizeof guest);
        g_eax=9;g_ecx=10;g_edx=11;g_ebx=12;g_esi=13;g_edi=14;g_ebp=15;g_esp=sp;g_mem_base=0;
        g_flag_k=FK_CMP;g_flag_a=3;g_flag_b=5;g_flag_cf=1;
        uint32_t flags=recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1);
        MEM32(sp)=0x220000;MEM32(sp+4)=argument;
        sub_00401030();
        if(calls!=1||g_esp!=sp+4||g_ecx!=0x67d000||g_eax!=9||g_edx!=11||g_ebx!=12||g_esi!=13||g_edi!=14||g_ebp!=15)return 1;
        if(MEM32(sp-8)!=0x40103e||MEM32(sp-4)!=argument||MEM32(sp)!=0x220000||MEM32(sp+4)!=argument)return 2;
        if((flags&0x8d5)!=(recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1)&0x8d5))return 3;
    }
    puts("16 isolated wrapper cases passed; callee remains synthetic");return 0;
}
