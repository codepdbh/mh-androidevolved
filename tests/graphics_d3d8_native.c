/* The game's refresh-rate selector 0x4c0830 (translated) over the port's
 * Direct3D 8 shim (runtime/d3d8.c). Portable; compared with
 * tools/probe_graphics_d3d8_x86.py, which emulates the same shim. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
#include "../runtime/d3d8.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
double g_st[8];int g_fp_top;uint16_t g_fpu_cw=0x037f;
static _Alignas(8) uint8_t guest[0x2000000];
static mh_d3d8 d3d;
static unsigned com_calls;
void mh_guest_fault(uint32_t a,size_t n){fprintf(stderr,"guest fault at 0x%08x width %u in 0x%08x\n",a,(unsigned)n,g_cur_func);exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){fprintf(stderr,"dispatch fault to 0x%08x from 0x%08x\n",a,c);exit(74);}
/* Import thunk 0x64408c = jmp [Direct3DCreate8]: stdcall(SDKVersion). */
void sub_0064408C(void){if(MEM32(g_esp)!=0x4c0845)exit(80);g_eax=mh_d3d8_create(&d3d,MEM32(g_esp+4));g_esp+=8;}
static void com_dispatch(uint32_t va){
    /* Not `eax`: recomp_types.h defines eax as g_eax, so a local of that name would shadow the global. */
    uint32_t result=0,pop=0;const char *name="?";
    int r=mh_d3d8_call(&d3d,va,g_esp,&result,&pop,&name);
    if(r!=MH_D3D8_DONE){fprintf(stderr,"Direct3D 8 method %s %s\n",name,r==MH_D3D8_UNIMPLEMENTED?"not implemented":"called badly");exit(75);}
    com_calls++;g_eax=result;g_esp+=pop;
    if(getenv("MH_TRACE_COM"))fprintf(stderr,"%s -> eax %08x pop %u calls %u\n",name,result,pop,com_calls);
}
#define M(i) static void d3d_method_##i(void){com_dispatch(MH_D3D8_VA+4u*(i));}
M(0) M(1) M(2) M(3) M(4) M(5) M(6) M(7) M(8) M(9) M(10) M(11) M(12) M(13) M(14) M(15)
static void (*const d3d_methods[MH_D3D8_METHODS])(void)={d3d_method_0,d3d_method_1,d3d_method_2,d3d_method_3,d3d_method_4,d3d_method_5,
    d3d_method_6,d3d_method_7,d3d_method_8,d3d_method_9,d3d_method_10,d3d_method_11,d3d_method_12,d3d_method_13,d3d_method_14,d3d_method_15};
recomp_func_t recomp_lookup(uint32_t va){
    if(va>=MH_D3D8_VA&&va<MH_D3D8_VA+4*MH_D3D8_METHODS&&!(va&3))return d3d_methods[(va-MH_D3D8_VA)/4];
    return NULL;
}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "graphics_d3d8_unit.c"

static const uint32_t widths[]={640,1280,1920,1000},heights[]={480,720,1080,700},depths[]={16,24,32};
int main(void){
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000))return 71;
    for(unsigned k=0;k<48;k++){
        unsigned size=k%4,depth=(k/4)%3,adapter=(k/12)%2,alignment=k/24;
        memset(guest+0x1d00000,0,0x10000);memset(guest+0x17fe00,0,0x300);
        if(!mh_d3d8_init(&d3d,&mh_recomp_region,0x1d00000,0x10000))return 72;
        MEM32(0x735eb0)=adapter;com_calls=0;
        uint32_t sp=0x180000+alignment*4;
        g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x33333333;g_edx=0x44444444;g_esi=0x55555555;g_edi=0x66666666;g_ebp=0x77777777;
        g_esp=sp;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
        MEM32(sp)=0x8f0000;MEM32(sp+4)=widths[size];MEM32(sp+8)=heights[size];MEM32(sp+12)=depths[depth];
        sub_004C0830();
        if(g_esp!=sp+4)return 73;
        printf("{\"case\":%u,\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},",
               k,g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        printf("\"com_calls\":%u,\"stack_hex\":\"",com_calls);for(unsigned i=0;i<0x300;i++)printf("%02x",guest[0x17fe00+i]);
        printf("\",\"heap_hex\":\"");for(unsigned i=0;i<0x60;i++)printf("%02x",guest[0x1d00000+i]);
        printf("\"}\n");
    }
    return 0;
}
