/* Test doubles only: no Direct3D device, window, graphics or game launch. */
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
void mh_guest_fault(uint32_t address,size_t width){exit(address==0 && width==4 ? 70 : 79);}
void mh_dispatch_fault(uint32_t target,uint32_t caller){(void)target;(void)caller;exit(74);}

#ifdef MH_PRECISE_RETURN
#define CREATE_RET 0x4c0845u
#define COUNT_RET 0x4c0884u
#define RELEASE_RET 0x4c08f0u
#define RELEASE_EARLY_RET 0x4c08ccu
#define ENUM_RET 0x4c08a1u
#else
#define CREATE_RET RECOMP_RETADDR
#define COUNT_RET RECOMP_RETADDR
#define RELEASE_RET RECOMP_RETADDR
#define RELEASE_EARLY_RET RECOMP_RETADDR
#define ENUM_RET RECOMP_RETADDR
#endif
static uint32_t mock_modes,mock_refresh,mock_refresh2,mock_null;
static void mock_create(void){if(MEM32(g_esp)!=CREATE_RET || MEM32(g_esp+4)!=0xdc)exit(80);g_eax=mock_null?0:0x200000;g_esp+=8;}
static void mock_count(void){if(MEM32(g_esp)!=COUNT_RET || MEM32(g_esp+4)!=0x200000)exit(81);g_eax=mock_modes;g_flag_k=FK_TEST;g_flag_a=g_flag_b=g_flag_cf=0;g_esp+=12;}
static void mock_release(void){uint32_t ret=MEM32(g_esp);if((ret!=RELEASE_RET && ret!=RELEASE_EARLY_RET) || MEM32(g_esp+4)!=0x200000)exit(82);g_eax=0;g_esp+=8;}
static void mock_enum(void){
    uint32_t index=MEM32(g_esp+12);
    if(MEM32(g_esp)!=ENUM_RET || MEM32(g_esp+4)!=0x200000 || index>=mock_modes)exit(83);
    uint32_t refresh=index?mock_refresh2:mock_refresh;
    if(mock_modes==2)g_ecx=refresh; /* The synthetic x86 stub uses ECX for its table load. */
    uint32_t out=MEM32(g_esp+16);MEM32(out)=640;MEM32(out+4)=480;MEM32(out+8)=refresh;MEM32(out+12)=0x16;
    g_eax=0;g_flag_k=FK_TEST;g_flag_a=g_flag_b=g_flag_cf=0;g_esp+=20;
}
recomp_func_t recomp_lookup(uint32_t va){return va==0x300000?mock_create:va==0x300010?mock_count:va==0x300020?mock_release:va==0x300030?mock_enum:NULL;}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#ifdef MH_PRECISE_RETURN
#include "graphics_precise_unit.c"
#else
#include "graphics_checked_unit.c"
#endif

static void hex_bytes(const uint8_t *p,unsigned size){for(unsigned i=0;i<size;i++)printf("%02x",p[i]);}
int main(int argc,char **argv){
    int modes=argc==2 && strcmp(argv[1],"--modes")==0;
    int multi=argc==2 && strcmp(argv[1],"--multi")==0;
    int null_case=argc==2 && strcmp(argv[1],"--null")==0;
    if(argc!=1 && !modes && !multi && !null_case)return 76;
    /* The synthetic test maps addresses from 64 KiB; page zero is absent. */
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000))return 71;
    mock_null=(uint32_t)null_case;
    const uint32_t first[]={30,60,0,30},second[]={60,30,60,0};
    for(unsigned depth=16;depth<=32;depth+=8){
      for(unsigned scenario=0;scenario<(multi?4u:(modes?3u:1u));++scenario){
        uint32_t refresh=multi?first[scenario]:(modes?scenario*30:0);
        uint32_t refresh2=multi?second[scenario]:0;
        mock_modes=multi?2u:(uint32_t)modes;mock_refresh=refresh;mock_refresh2=refresh2;
        memset(guest+0x107f80,0,256);memset(guest+0x200000,0,256);memset(guest+0x210000,0,256);
        g_mem_base=0;g_esp=0x108000;g_eax=0;g_ebx=0x11111111;g_ecx=g_edx=0;
        g_esi=0x22222222;g_edi=0x33333333;g_ebp=0x44444444;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
        MEM32(g_esp)=0x320000;MEM32(g_esp+4)=640;MEM32(g_esp+8)=480;MEM32(g_esp+12)=depth;
        MEM32(0x81b52c)=0x300000;MEM32(0x200000)=0x210000;MEM32(0x210018)=0x300010;MEM32(0x210008)=0x300020;MEM32(0x21001c)=0x300030;
        MEM32(0x735eb0)=0;sub_004C0830();
        printf("{\"depth\":%u,\"refresh\":%u,\"refresh2\":%u,\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},\"stack_hex\":\"",depth,refresh,refresh2,g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        hex_bytes(guest+0x107fb0,96);puts("\"}");
      }
    }
    return 0;
}
