/* Isolated test of the translated pool allocator (ctor 0x4010b0, allocate
 * 0x401350, free 0x401b00). Portable: no POSIX or Windows APIs. The CRT
 * malloc 0x610be0 that provides the arena is a test double returning a fixed
 * guest address. Output is compared with tools/probe_allocator_x86.py. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
double g_st[8];int g_fp_top;uint16_t g_fpu_cw=0x037f;
static _Alignas(8) uint8_t guest[0x900000];
void mh_guest_fault(uint32_t a,size_t n){(void)a;(void)n;exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){(void)a;(void)c;exit(74);}
recomp_func_t recomp_lookup(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}

#define POOL 0x67d000u
#define ARENA 0x890000u
#define ARENA_SIZE 0x30000u
/* CRT malloc double (cdecl): returns the fixed arena; records the request. */
void sub_00610BE0(void){
    if(MEM32(g_esp)!=0x40112b)exit(80);
    MEM32(0x8c0100)=MEM32(g_esp+4);g_eax=ARENA;g_esp+=4;
}
#include "allocator_unit.c"

static const uint32_t sizes[16]={1,8,15,16,17,31,48,100,255,256,1000,2032,2048,3000,5000,0x3000};
static uint32_t call_pool(void (*fn)(void),uint32_t argument,uint32_t sp){
    g_eax=0x11111111;g_ebx=0x22222222;g_ecx=POOL;g_edx=0x33333333;g_esi=0x44444444;g_edi=0x55555555;g_ebp=0x66666666;
    g_esp=sp;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
    MEM32(sp)=0x8f0000;MEM32(sp+4)=argument;
    fn();
    if(g_esp!=sp+8)exit(81);
    return g_eax;
}
static uint64_t fnv(uint32_t address,uint32_t n){
    uint64_t h=1469598103934665603ull;
    for(uint32_t i=0;i<n;i++){h^=guest[address+i];h*=1099511628211ull;}
    return h;
}
int main(void){
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000))return 71;
    for(unsigned k=0;k<16;k++){
        unsigned alignment=k%4,zero_fill=(k/4)%2,seed_variant=k/8;
        uint32_t sp=0x880000+alignment,x=0x1234567u+k*0x9e3779b9u+seed_variant,live[64],count=0,results[60];
        memset(guest+POOL,0,0x1300);memset(guest+ARENA,0xcd,ARENA_SIZE);memset(guest+0x8c0100,0,0x10);
        memset(guest+0x87fe00,0,0x300);
        call_pool(sub_004010B0,ARENA_SIZE,sp);
        guest[0x67e264]=(uint8_t)zero_fill;
        for(unsigned op=0;op<60;op++){
            x=x*1103515245u+12345u;
            if(count==0||((x>>16)%3)!=0){
                uint32_t p=call_pool(sub_00401350,sizes[(x>>8)%16],sp);results[op]=p;
                if(p&&count<64){live[count++]=p;for(uint32_t i=0;i<sizes[(x>>8)%16]&&i<64;i++)MEM8(p+i)=(uint8_t)(op+i);}
            }else{
                uint32_t i=(x>>4)%count,p=live[i];live[i]=live[--count];
                call_pool(sub_00401B00,p,sp);results[op]=0xF0000000u|(p&0x0fffffffu);
            }
        }
        printf("{\"case\":%u,\"results\":[",k);
        for(unsigned op=0;op<60;op++)printf("%s%u",op?",":"",results[op]);
        printf("],\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},",
               g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        printf("\"pool_hex\":\"");for(unsigned i=0;i<0x1268;i++)printf("%02x",guest[POOL+i]);
        printf("\",\"stack_hex\":\"");for(unsigned i=0;i<0x300;i++)printf("%02x",guest[0x87fe00+i]);
        printf("\",\"arena_fnv\":\"%016llx\",\"malloc_request\":%u}\n",(unsigned long long)fnv(ARENA,ARENA_SIZE),MEM32(0x8c0100));
    }
    return 0;
}
