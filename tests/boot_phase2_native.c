/* Boot phase 2: map the user's manhunt.exe and run, as translated code, what the
 * real CRT entry (0x64a380) runs before WinMain: 0x653460(0x7eba68), the CRT
 * initialisation 0x655490 and all 98 C++ static initialisers in .CRT order.
 *
 * The protection wrapper is never executed: the header stub 0x400080 and the
 * .prus slot [0x850000] are replaced by runtime/protection_redirect.c (call
 * sites classified by tools/resolve_protection_redirects.py). Win32 APIs come
 * from the port's shims (memory, thread state, process state). Portable.
 * argv[1] = path to the user's manhunt.exe (read only).
 * Output is compared with the reference of tools/trace_static_init_x86.py. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "virtual_cpu.h"
#include "x87_semantics.h"
#include "../runtime/guest_memory.c"
#include "../runtime/pe32_image.c"
#include "../runtime/win32_memory.c"
#include "../runtime/win32_thread.c"
#include "../runtime/win32_process.c"
#include "../runtime/protection_redirect.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
double g_st[8];int g_fp_top;uint16_t g_fpu_cw=0x027f;   /* a Windows process starts with 53-bit precision, exceptions masked */
#define GUEST_SIZE 0x6200000u
#define STACK_TOP 0x1800000u
#define RETURN_SENTINEL 0x1f00000u
#define API_BASE 0x1e00000u          /* fake import addresses, outside the image */
#define PROCESS_BLOCK 0x1f10000u     /* command line and environment */
#define GLOBAL_BASE 0x2000000u
#define GLOBAL_SIZE 0x4100000u
#define THREAD 0x1234u
static uint8_t *guest;
static mh_win32_global_heap global_heap;
static mh_win32_thread thread;
static mh_win32_process process;
static uint32_t prus_target;
static unsigned redirects[2];
void mh_guest_fault(uint32_t a,size_t n){fprintf(stderr,"guest fault at 0x%08x width %u in 0x%08x\n",a,(unsigned)n,g_cur_func);exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){fprintf(stderr,"dispatch fault to 0x%08x from 0x%08x\n",a,c);exit(74);}
static void unsupported(const char *what){fprintf(stderr,"%s (return 0x%08x, in 0x%08x)\n",what,MEM32(g_esp),g_cur_func);exit(81);}

#include "boot_phase2_unit.c"
#include "boot_phase2_list.h"
#include "boot_phase2_dispatch.h"
#include "boot_phase2_unresolved.h"
#include "../private/analysis/protection/redirect_sites.h"
/* Import shims: stdcall, arguments at g_esp+4..., the callee pops them and the return address. */
enum {
#define X(name,slot) API_##name,
    BOOT_SLOTS
#undef X
    API_COUNT
};
static unsigned api_calls[API_COUNT];
#define ARG(i) MEM32(g_esp+4+4*(i))
#define RET(value,args) do{g_eax=(value);g_esp+=4+4*(args);}while(0)
#define RET_VOID(args) do{g_esp+=4+4*(args);}while(0)
static void api_EnterCriticalSection(void){api_calls[API_EnterCriticalSection]++;if(!mh_win32_enter_critical_section(&mh_recomp_region,ARG(0),THREAD))unsupported("EnterCriticalSection would block");RET_VOID(1);}
static void api_LeaveCriticalSection(void){api_calls[API_LeaveCriticalSection]++;if(!mh_win32_leave_critical_section(&mh_recomp_region,ARG(0),THREAD))unsupported("LeaveCriticalSection by a non-owner");RET_VOID(1);}
static void api_InitializeCriticalSection(void){api_calls[API_InitializeCriticalSection]++;mh_win32_init_critical_section(&mh_recomp_region,ARG(0));RET_VOID(1);}
static void api_DeleteCriticalSection(void){unsupported("DeleteCriticalSection is not modelled");}
static void api_GlobalAlloc(void){api_calls[API_GlobalAlloc]++;RET(mh_win32_global_alloc(&global_heap,&mh_recomp_region,ARG(0),ARG(1)),2);}
static void api_GlobalFree(void){unsupported("GlobalFree is not modelled");}
static void api_TlsAlloc(void){api_calls[API_TlsAlloc]++;RET(mh_win32_tls_alloc(&thread),0);}
static void api_TlsFree(void){api_calls[API_TlsFree]++;RET((uint32_t)mh_win32_tls_free(&thread,ARG(0)),1);}
static void api_TlsGetValue(void){api_calls[API_TlsGetValue]++;RET(mh_win32_tls_get_value(&thread,ARG(0)),1);}
static void api_TlsSetValue(void){api_calls[API_TlsSetValue]++;RET((uint32_t)mh_win32_tls_set_value(&thread,ARG(0),ARG(1)),2);}
static void api_GetStdHandle(void){api_calls[API_GetStdHandle]++;RET(mh_win32_get_std_handle(ARG(0)),1);}
static void api_GetCurrentProcess(void){api_calls[API_GetCurrentProcess]++;RET(mh_win32_get_current_process(),0);}
static void api_DuplicateHandle(void){
    api_calls[API_DuplicateHandle]++;
    int r=mh_win32_duplicate_handle(&thread,ARG(1));
    if(r<0)unsupported("DuplicateHandle of a real handle is not modelled");
    RET((uint32_t)r,7);
}
static void api_GetCommandLineA(void){api_calls[API_GetCommandLineA]++;RET(mh_win32_get_command_line(&process),0);}
static void api_GetEnvironmentStrings(void){api_calls[API_GetEnvironmentStrings]++;RET(mh_win32_get_environment_strings(&process),0);}
static void api_FreeEnvironmentStringsA(void){api_calls[API_FreeEnvironmentStringsA]++;RET(mh_win32_free_environment_strings(&process,ARG(0)),1);}
static void api_CreateEventA(void){api_calls[API_CreateEventA]++;RET(mh_win32_create_event(&process),4);}
static void api_GetTickCount(void){unsupported("GetTickCount is not expected during boot phase 2");}
static void api_ExitProcess(void){unsupported("ExitProcess");}
static void api_MessageBoxA(void){unsupported("MessageBoxA");}
static void (*const api_fns[API_COUNT])(void)={
#define X(name,slot) api_##name,
    BOOT_SLOTS
#undef X
};
static const uint32_t api_slots[API_COUNT]={
#define X(name,slot) slot,
    BOOT_SLOTS
#undef X
};
/* The .prus slot: what each classified call site needs. Trigger sites are not handled yet. */
static void prus_slot(void){
    uint32_t ret=MEM32(g_esp);
    const mh_redirect_site *site=mh_redirect_find(mh_redirect_sites,sizeof mh_redirect_sites/sizeof mh_redirect_sites[0],ret);
    if(!site)unsupported("call through the protection slot from an unclassified site");
    switch(site->kind){
    case MH_REDIRECT_GET_LAST_ERROR:redirects[0]++;RET(mh_win32_get_last_error(&thread),0);break;
    case MH_REDIRECT_VALIDATE_POINTER:redirects[1]++;RET(mh_redirect_validate_pointer(&mh_recomp_region,ARG(0),ARG(1)),2);break;
    default:unsupported("protection trigger site reached");
    }
}
/* The header stub 0x400080: a tail jump to the import that its table names for this return address. */
void sub_00400080(void){
    uint32_t slot=0,e=g_esp;
    if(!mh_header_redirect_slot(&mh_recomp_region,MEM32(e),&slot))unsupported("header stub called from an unknown site");
    uint32_t target=MEM32(slot);
    /* The stub's own stack writes (sub esp,4; push eax; ...; pushad; the resolved address
     * replaces the copied return address), so the stack below esp matches x86 exactly. */
    MEM32(e-4)=target;MEM32(e-8)=g_eax;MEM32(e-12)=g_ecx;MEM32(e-16)=g_edx;MEM32(e-20)=g_ebx;
    MEM32(e-24)=e-4;MEM32(e-28)=g_ebp;MEM32(e-32)=g_esi;MEM32(e-36)=g_edi;
    recomp_func_t fn=recomp_lookup(target);
    if(!fn)mh_dispatch_fault(target,g_cur_func);
    fn();
}
recomp_func_t recomp_lookup(uint32_t va){
    if(va>=API_BASE+0x10&&va<API_BASE+0x10*(API_COUNT+1)&&!(va&0xf))return api_fns[(va-API_BASE)/0x10-1];
    if(va==prus_target)return prus_slot;
    return boot_phase2_dispatch(va);
}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}

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
    /* What the Windows loader provides: resolved import slots (fake addresses served by the shims). */
    for(unsigned k=0;k<API_COUNT;k++)MEM32(api_slots[k])=API_BASE+0x10*(k+1);
    prus_target=MEM32(0x850000);
    mh_win32_thread_init(&thread);
    if(!mh_win32_process_init(&process,&mh_recomp_region,PROCESS_BLOCK))return 75;
    if(!mh_win32_global_init(&global_heap,GLOBAL_BASE,GLOBAL_SIZE))return 75;
    printf("{\"image\":[%u,%u,%u],\"results\":[",info.image_base,info.image_size,info.entry_rva);
    for(unsigned i=0;i<BOOT_RUNS;i++){
        g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x33333333;g_edx=0x44444444;g_esi=0x55555555;g_edi=0x66666666;g_ebp=0x77777777;
        g_esp=STACK_TOP;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;MEM32(STACK_TOP)=RETURN_SENTINEL;
        for(unsigned a=0;a<boot_runs[i].argc;a++)MEM32(STACK_TOP+4+4*a)=boot_runs[i].args[a];
        boot_runs[i].fn();
        if(g_esp!=STACK_TOP+4){fprintf(stderr,"run 0x%08x left esp 0x%08x\n",boot_runs[i].va,g_esp);return 73;}
        printf("%s[%u,%u,%u,%u,%u,%u,%u]",i?",":"",boot_runs[i].va,g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi);
    }
    printf("],\"api_calls\":[");
    for(unsigned k=0;k<API_COUNT;k++)printf("%s%u",k?",":"",api_calls[k]);
    printf("],\"redirects\":[%u,%u],\"last_error\":%u,\"tls\":[",redirects[0],redirects[1],thread.last_error);
    for(unsigned k=0,first=1;k<MH_TLS_SLOTS;k++)if(thread.tls_used>>k&1){printf("%s[%u,%u]",first?"":",",k,thread.tls[k]);first=0;}
    printf("],\"events\":%u,\"global_next\":%u,\"data_crc\":%u,\"bss_crc\":%u,\"image_crc\":[%u,%u],\"stack_crc\":%u,\"global_crc\":%u,\"fpu_cw\":%u}\n",
           process.events,global_heap.next,
           crc32_bytes(guest+0x67d000,0x7ed4a0-0x67d000),crc32_bytes(guest+0x81e000,0x8296d4-0x81e000),
           crc32_bytes(guest+0x400000,0x81b000-0x400000),crc32_bytes(guest+0x81c2a0,0xa16000-0x81c2a0),  /* without the two import tables */
           crc32_bytes(guest+STACK_TOP-0x4000,0x4004),
           crc32_bytes(guest+GLOBAL_BASE,global_heap.next-GLOBAL_BASE),g_fpu_cw);
    free(guest);return 0;
}
