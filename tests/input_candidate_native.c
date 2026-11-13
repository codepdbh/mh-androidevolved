/* Synthetic input tests only: no keyboard, mouse, window or real Win32 APIs. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"

uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
__declspec(align(8)) static uint8_t guest[0x820000];
static unsigned scenario,module_calls,input_calls,error_calls;
void mh_guest_fault(uint32_t address,size_t width){(void)address;(void)width;exit(70);}
void mh_dispatch_fault(uint32_t target,uint32_t caller){(void)target;(void)caller;exit(74);}
static void mock_module(void){
    if(MEM32(g_esp)!=0x4c1bc8 || MEM32(g_esp+4)!=0)exit(80);
    module_calls++;g_eax=0x222000;g_esp+=8;
}
static void mock_input(void){
    if(MEM32(g_esp)!=0x4c1bce || MEM32(g_esp+4)!=0x222000 || MEM32(g_esp+8)!=0x800 ||
       MEM32(g_esp+12)!=0x67e7b4 || MEM32(g_esp+16)!=0x210020 || MEM32(g_esp+20)!=0)exit(81);
    input_calls++;
    if(scenario==1)g_eax=0x80004005u;
    else {MEM32(0x210020)=0x230000;g_eax=0;g_flag_k=FK_TEST;g_flag_a=g_flag_b=g_flag_cf=0;}
    g_esp+=24;
}
recomp_func_t recomp_lookup(uint32_t va){return va==0x300000?mock_module:va==0x300020?mock_input:NULL;}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "input_precise_unit.c"
void sub_0060F110(void){
    if(MEM32(g_esp)!=0x4c1be3 || MEM32(g_esp+4)!=0x7e9c94 || MEM32(g_esp+8)!=0x736880)exit(82);
    error_calls++;g_esp+=4;
}
static void hex_bytes(const uint8_t *p,unsigned size){for(unsigned i=0;i<size;i++)printf("%02x",p[i]);}
int main(void){
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000))return 71;
    const char *names[]={"success","failure","already"};
    for(scenario=0;scenario<3;scenario++){
        memset(guest+0x107f80,0,256);memset(guest+0x200000,0,256);memset(guest+0x210000,0,256);
        g_mem_base=0;g_esp=0x108000;g_eax=0;g_ebx=0x11111111;g_ecx=g_edx=0;
        g_esi=0x22222222;g_edi=0x33333333;g_ebp=0x44444444;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
        module_calls=input_calls=error_calls=0;
        MEM32(g_esp)=0x320000;MEM32(0x736db8)=0x200000;MEM32(0x20000c)=0x210000;
        MEM32(0x81b3ac)=0x300000;MEM32(0x81b35c)=0x300020;MEM32(0x210020)=scenario==2?0x230000:0;
        sub_004C1BA0();
        if(module_calls!=(scenario==2?0u:1u) || input_calls!=(scenario==2?0u:1u) || error_calls!=(scenario==1?1u:0u))return 83;
        printf("{\"scenario\":\"%s\",\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},\"stack_hex\":\"",names[scenario],g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        hex_bytes(guest+0x107fc0,80);printf("\",\"config_hex\":\"");hex_bytes(guest+0x210000,64);puts("\"}");
    }
    return 0;
}
