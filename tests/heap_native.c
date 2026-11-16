/* Isolated test of the game's own heap (malloc 0x610be0 and its 18 callees)
 * over the Win32 shims in runtime/win32_memory.c: GlobalAlloc and
 * Enter/LeaveCriticalSection. Portable; compared with tools/probe_heap_x86.py. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
#include "../runtime/win32_memory.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
double g_st[8];int g_fp_top;uint16_t g_fpu_cw=0x037f;
#define GUEST_SIZE 0x2000000u
#define GLOBAL_BASE 0x1000000u
#define GLOBAL_SIZE 0x1000000u
#define CS 0x828120u
#define THREAD 0x1234u
static uint8_t *guest;
static mh_win32_global_heap global_heap;
static unsigned api_calls[3];
void mh_guest_fault(uint32_t a,size_t n){fprintf(stderr,"guest fault at 0x%08x width %u in 0x%08x\n",a,(unsigned)n,g_cur_func);exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){(void)a;(void)c;exit(74);}
/* stdcall adapters at the exact call sites; registers other than ESP/EAX untouched. */
static void api_enter(void){
    if(MEM32(g_esp)!=0x610beeu)exit(80);
    api_calls[0]++;if(!mh_win32_enter_critical_section(&mh_recomp_region,MEM32(g_esp+4),THREAD))exit(81);g_esp+=8;
}
static void api_leave(void){
    if(MEM32(g_esp)!=0x610c08u)exit(82);
    api_calls[1]++;if(!mh_win32_leave_critical_section(&mh_recomp_region,MEM32(g_esp+4),THREAD))exit(83);g_esp+=8;
}
static void api_global_alloc(void){
    if(MEM32(g_esp)!=0x64a490u)exit(84);
    api_calls[2]++;g_eax=mh_win32_global_alloc(&global_heap,&mh_recomp_region,MEM32(g_esp+4),MEM32(g_esp+8));g_esp+=12;
}
recomp_func_t recomp_lookup(uint32_t va){return va==0x800600?api_enter:(va==0x800700?api_leave:(va==0x800800?api_global_alloc:NULL));}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "heap_unit.c"
#include "heap_data.h"

static uint32_t crc_table[256];
static uint32_t crc32_of(uint32_t address,uint32_t n){
    uint32_t c=0xffffffffu;
    for(uint32_t i=0;i<n;i++)c=crc_table[(c^guest[address+i])&255]^(c>>8);
    return c^0xffffffffu;
}
static const uint32_t sizes[16]={1,7,16,24,100,200,512,1000,1024,4000,4096,8000,16384,30000,65536,100000};
int main(void){
    for(uint32_t i=0;i<256;i++){uint32_t c=i;for(int k=0;k<8;k++)c=c&1?0xedb88320u^(c>>1):c>>1;crc_table[i]=c;}
    guest=calloc(1,GUEST_SIZE);
    if(!guest||!mh_mem_init(&mh_recomp_region,guest+0x10000,GUEST_SIZE-0x10000,0x10000))return 71;
    for(unsigned k=0;k<16;k++){
        uint32_t sp=0x880000+k%4,x=0x2468aceu+k*0x9e3779b9u,results[40];
        memset(guest+0x81e000,0,0x8296d4-0x81e000);memset(guest+GLOBAL_BASE,0,GLOBAL_SIZE);memset(guest+0x87fe00,0,0x300);
        for(unsigned i=0;i<sizeof heap_table/sizeof heap_table[0];i++)MEM32(HEAP_TABLE+4*i)=heap_table[i]; /* real .data values */
        mh_win32_init_critical_section(&mh_recomp_region,CS);
        if(!mh_win32_global_init(&global_heap,GLOBAL_BASE,GLOBAL_SIZE))return 72;
        MEM32(0x81b3e4)=0x800600;MEM32(0x81b3e8)=0x800700;MEM32(0x81b40c)=0x800800;
        api_calls[0]=api_calls[1]=api_calls[2]=0;
        for(unsigned op=0;op<40;op++){
            x=x*1103515245u+12345u;uint32_t size=sizes[(x>>8)%16];
            g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x33333333;g_edx=0x44444444;g_esi=0x55555555;g_edi=0x66666666;g_ebp=0x77777777;
            g_esp=sp;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;MEM32(sp)=0x8f0000;MEM32(sp+4)=size;
            sub_00610BE0();
            if(g_esp!=sp+4)return 73;
            results[op]=g_eax;
            if(g_eax)for(uint32_t i=0;i<size&&i<32;i++)MEM8(g_eax+i)=(uint8_t)(op*7+i);
        }
        printf("{\"case\":%u,\"results\":[",k);
        for(unsigned op=0;op<40;op++)printf("%s%u",op?",":"",results[op]);
        printf("],\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},",
               g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        printf("\"api\":[%u,%u,%u],\"global_next\":%u,\"stack_hex\":\"",api_calls[0],api_calls[1],api_calls[2],global_heap.next);
        for(unsigned i=0;i<0x300;i++)printf("%02x",guest[0x87fe00+i]);
        printf("\",\"cs_hex\":\"");for(unsigned i=0;i<24;i++)printf("%02x",guest[CS+i]);
        printf("\",\"bss_crc\":%u,\"global_crc\":%u}\n",crc32_of(0x81e000,0x8296d4-0x81e000),crc32_of(GLOBAL_BASE,global_heap.next-GLOBAL_BASE));
    }
    free(guest);return 0;
}
