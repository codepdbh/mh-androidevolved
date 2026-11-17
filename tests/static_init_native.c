/* Boot phase 1: map the user's manhunt.exe into guest memory with the runtime's
 * PE mapper (as the Windows loader would place it) and run the C++ static
 * initialisers from .CRT that the port supports, in table order, as translated
 * code. Memory APIs come from runtime/win32_memory.c; indirect calls go through
 * the generated fail-closed dispatch table. Portable.
 * argv[1] = path to the user's manhunt.exe (read only).
 * Output is compared with tools/probe_static_init_x86.py. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "virtual_cpu.h"
#include "../runtime/guest_memory.c"
#include "../runtime/pe32_image.c"
#include "../runtime/win32_memory.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
double g_st[8];int g_fp_top;uint16_t g_fpu_cw=0x037f;
#define GUEST_SIZE 0x6200000u
#define STACK_TOP 0x1800000u
#define RETURN_SENTINEL 0x1f00000u
#define API_BASE 0x1e00000u          /* fake import addresses, outside the image */
#define GLOBAL_BASE 0x2000000u
#define GLOBAL_SIZE 0x4100000u
#define CS 0x828120u
#define THREAD 0x1234u
static uint8_t *guest;
static mh_win32_global_heap global_heap;
static unsigned mem_api[3];
void mh_guest_fault(uint32_t a,size_t n){fprintf(stderr,"guest fault at 0x%08x width %u in 0x%08x\n",a,(unsigned)n,g_cur_func);exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){fprintf(stderr,"dispatch fault to 0x%08x from 0x%08x\n",a,c);exit(74);}
static void api_enter(void){mem_api[0]++;if(!mh_win32_enter_critical_section(&mh_recomp_region,MEM32(g_esp+4),THREAD))exit(81);g_esp+=8;}
static void api_leave(void){mem_api[1]++;if(!mh_win32_leave_critical_section(&mh_recomp_region,MEM32(g_esp+4),THREAD))exit(82);g_esp+=8;}
static void api_global_alloc(void){mem_api[2]++;g_eax=mh_win32_global_alloc(&global_heap,&mh_recomp_region,MEM32(g_esp+4),MEM32(g_esp+8));g_esp+=12;}
#include "static_init_unit.c"
#include "static_init_dispatch.h"
#include "static_init_unresolved.h"
recomp_func_t recomp_lookup(uint32_t va){
    switch(va){case API_BASE+0x100:return api_enter;case API_BASE+0x200:return api_leave;case API_BASE+0x300:return api_global_alloc;default:break;}
    return static_init_dispatch(va);
}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "static_init_list.h"

static uint32_t crc_table[256];
static uint32_t crc32_bytes(const uint8_t *p,size_t n){
    uint32_t c=0xffffffffu;
    for(size_t i=0;i<n;i++)c=crc_table[(c^p[i])&255]^(c>>8);
    return c^0xffffffffu;
}
int main(int argc,char **argv){
    if(argc!=2)return 76;
    for(uint32_t i=0;i<256;i++){uint32_t c=i;for(int k=0;k<8;k++)c=c&1?0xedb88320u^(c>>1):c>>1;crc_table[i]=c;}
    FILE *f=fopen(argv[1],"rb");if(!f)return 77;
    uint8_t *file=malloc(EXE_SIZE+1);size_t n=file?fread(file,1,EXE_SIZE+1,f):0;fclose(f);
    if(n!=EXE_SIZE||crc32_bytes(file,n)!=EXE_CRC32){fprintf(stderr,"unexpected executable\n");return 78;}
    guest=calloc(1,GUEST_SIZE);if(!guest)return 71;
    mh_guest_memory image;mh_pe32_info info;
    if(!mh_mem_init(&image,guest+0x400000,0xa18000-0x400000,0x400000)||!mh_pe32_map_image(file,n,&image,&info))return 79;
    free(file);
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,GUEST_SIZE-0x10000,0x10000))return 72;
    /* Process state the Windows loader/CRT would provide before the initialisers:
     * resolved import slots for the memory APIs and the heap's critical section. */
    MEM32(0x81b3e4)=API_BASE+0x100;MEM32(0x81b3e8)=API_BASE+0x200;MEM32(0x81b40c)=API_BASE+0x300;
    mh_win32_init_critical_section(&mh_recomp_region,CS);
    if(!mh_win32_global_init(&global_heap,GLOBAL_BASE,GLOBAL_SIZE))return 75;
    unsigned count=sizeof static_inits/sizeof static_inits[0];
    printf("{\"image\":[%u,%u,%u],\"results\":[",info.image_base,info.image_size,info.entry_rva);
    for(unsigned i=0;i<count;i++){
        g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x33333333;g_edx=0x44444444;g_esi=0x55555555;g_edi=0x66666666;g_ebp=0x77777777;
        g_esp=STACK_TOP;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;MEM32(STACK_TOP)=RETURN_SENTINEL;
        static_init_fns[i]();
        if(g_esp!=STACK_TOP+4){fprintf(stderr,"initialiser 0x%08x left esp 0x%08x\n",static_inits[i],g_esp);return 73;}
        printf("%s[%u,%u,%u,%u,%u,%u,%u]",i?",":"",static_inits[i],g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi);
    }
    printf("],\"mem_api\":[%u,%u,%u],\"global_next\":%u,\"data_crc\":%u,\"bss_crc\":%u,\"image_crc\":%u,\"stack_crc\":%u,\"global_crc\":%u}\n",
           mem_api[0],mem_api[1],mem_api[2],global_heap.next,
           crc32_bytes(guest+0x67d000,0x7ed4a0-0x67d000),crc32_bytes(guest+0x81e000,0x8296d4-0x81e000),
           crc32_bytes(guest+0x400000,0xa18000-0x400000),crc32_bytes(guest+STACK_TOP-0x2000,0x2004),
           crc32_bytes(guest+GLOBAL_BASE,global_heap.next-GLOBAL_BASE));
    free(guest);return 0;
}
