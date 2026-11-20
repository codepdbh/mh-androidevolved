/* The game's boot as translated code over the port's API layer, shared by the comparison
 * harness (tests/winmain_native.c) and the Android app, so that what the comparison with x86
 * validates is exactly what runs on the device.
 *
 * Maps the user's manhunt.exe, resolves its imports to the port (runtime/port_api.c), replaces
 * the protection's redirections (runtime/protection_redirect.c), runs boot phase 2 (CRT start-up
 * and the 98 static initialisers) and then WinMain(0x400000, 0, command line, SW_SHOWDEFAULT)
 * as the CRT entry does, until `frame_limit` frames have been presented.
 *
 * Compile as one unit with the translated code on the include path (private/analysis/winmain).
 * Private: it includes code derived from the user's executable. */
#define RECOMP_GENERATED_CODE
#include <setjmp.h>
/* The runtime first: recomp_types.h defines the guest registers as macros (eax = g_eax, ...),
 * which must never rewrite host code. */
#include "guest_memory.c"
#include "pe32_image.c"
#include "win32_memory.c"
#include "win32_thread.c"
#include "win32_process.c"
#include "protection_redirect.c"
#include "port_api.c"
#include "game_runner.h"
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "virtual_cpu.h"
#include "x87_semantics.h"
#include "x86_semantics.h"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
double g_st[8];int g_fp_top;uint16_t g_fpu_cw=0x027f;   /* a Windows process starts with 53-bit precision, exceptions masked */
uint32_t g_mxcsr=0x1f80;                               /* SSE control: the processor default (all exceptions masked, round to nearest) */
#define GUEST_SIZE 0x20000000u      /* the whole Direct3D resource range (0x10000000-0x20000000); pages are committed on use */
#define STACK_TOP 0x1800000u
#define RETURN_SENTINEL 0x1f00000u
#define API_BASE 0x1e00000u
#define RUN_GLOBAL_BASE 0x2000000u
#define RUN_PROCESS_DATA 0x1f10000u
static uint8_t *guest;
static mh_port *port;
static uint32_t prus_target,pending_va;
static unsigned redirects[3];
static jmp_buf frames_done;
static mh_game_config cfg;
/* Unrecoverable guest state: the embedder's handler (it must not return), else the process ends. */
static void game_exit(int code){if(cfg.fatal)cfg.fatal(cfg.user,code);exit(code);}

static void game_log(const char *fmt,...){
    char text[600];va_list ap;va_start(ap,fmt);vsnprintf(text,sizeof text,fmt,ap);va_end(ap);
    if(cfg.log)cfg.log(text);else fprintf(stderr,"%s\n",text);
}
#if defined(_WIN32) && defined(MH_HOST_BACKTRACE)
#include <windows.h>
#include <dbghelp.h>
#pragma comment(lib,"dbghelp.lib")
static void host_backtrace(void){
    void *frames[24];USHORT n=CaptureStackBackTrace(1,24,frames,NULL);HANDLE p=GetCurrentProcess();
    SymInitialize(p,NULL,TRUE);
    for(USHORT i=0;i<n;i++){char buf[sizeof(SYMBOL_INFO)+256];SYMBOL_INFO *s=(SYMBOL_INFO*)buf;s->SizeOfStruct=sizeof(SYMBOL_INFO);s->MaxNameLen=255;
        DWORD64 d=0;if(SymFromAddr(p,(DWORD64)frames[i],&d,s))fprintf(stderr,"  %s+0x%llx\n",s->Name,(unsigned long long)d);else fprintf(stderr,"  %p\n",frames[i]);}
}
#else
static void host_backtrace(void){}
#endif
void mh_guest_fault(uint32_t a,size_t n){
    game_log("guest fault at 0x%08x width %u in 0x%08x (eax %08x ebx %08x ecx %08x edx %08x esi %08x edi %08x ebp %08x esp %08x)",
             a,(unsigned)n,g_cur_func,g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp);
    host_backtrace();
    game_exit(70);
}
void mh_dispatch_fault(uint32_t a,uint32_t c){game_log("dispatch fault to 0x%08x from 0x%08x",a,c);game_exit(74);}
static void unsupported(const char *what){game_log("%s (return 0x%08x, in 0x%08x)",what,MEM32(g_esp),g_cur_func);game_exit(81);}
uint64_t mh_guest_rdtsc(void){return mh_port_rdtsc(port);}
#include "winmain_unit.c"
#include "winmain_list.h"
#include "winmain_dispatch.h"
#include "winmain_unresolved.h"
#include "winmain_imports.h"
#include "../private/analysis/protection/redirect_sites.h"
#include "../private/analysis/boot_phase2/boot_phase2_list.h"
#define CONTINUE_VA (API_BASE+0x10u*(WINMAIN_IMPORTS+3u))
static int import_api[WINMAIN_IMPORTS];

/* ---- counters, as the reference's state['counts'] (WinMain stage only) and call log */
static struct { char name[96]; unsigned count; } counts[512];
static unsigned ncounts,ncalls;
static int counting;
static void count(const char *name,uint32_t ret){
    if(cfg.trace_all)game_log("call %s from 0x%x",name,ret);
    if(!counting)return;
    unsigned i=0;for(;i<ncounts&&strcmp(counts[i].name,name);i++){}
    if(i==ncounts){if(ncounts==512)unsupported("too many distinct calls");snprintf(counts[ncounts++].name,96,"%s",name);}
    counts[i].count++;ncalls++;
    if(cfg.calllog)fprintf(cfg.calllog,"%s %x\n",name,ret);
    if(cfg.dump_at&&ncalls==cfg.dump_at&&cfg.dump_path){   /* bisecting a divergence: .data/.bss at the n-th call */
        FILE *d=fopen(cfg.dump_path,"wb");if(d){fwrite(guest+0x67d000,1,0x8296d4-0x67d000,d);fclose(d);}
        exit(0);
    }
}

/* ---- port host: guest calls, faults, frame limit */
static uint32_t host_call_guest(void *user,uint32_t api_esp,uint32_t fn,const uint32_t *args,unsigned n){
    (void)user;uint32_t sp=api_esp-0x40u-4u*n;
    MEM32(sp)=CONTINUE_VA;for(unsigned i=0;i<n;i++)MEM32(sp+4+4*i)=args[i];
    g_esp=sp;recomp_func_t f=recomp_lookup(fn);
    if(!f)mh_dispatch_fault(fn,g_cur_func);
    uint32_t caller=g_cur_func;f();g_cur_func=caller;
    if(g_esp!=sp+4+4*n)unsupported("callback did not pop its arguments (not stdcall)");
    return g_eax;
}
static void port_fault(void *user,const char *message){(void)user;game_log("port: %s",message);game_exit(82);}
static void port_frames(void *user,unsigned frames){(void)user;(void)frames;longjmp(frames_done,1);}

/* ---- imports, COM, the protection's redirections, the HLE replacement */
static void api_thunk(void){
    /* no locals named like registers: recomp_types.h makes `esp` mean g_esp */
    uint32_t va=pending_va,sp=g_esp;unsigned i=(va-API_BASE)/0x10u-1u;
    count(winmain_imports[i].name,MEM32(sp));
    if(import_api[i]<0){char t[160];snprintf(t,sizeof t,"unsupported API %s",winmain_imports[i].name);unsupported(t);}
    uint32_t result=0;int has=0;
    mh_port_call_api(port,import_api[i],sp,&result,&has);
    if(has)g_eax=result;
    g_esp=sp+4u+4u*mh_port_api_args(import_api[i]);
}
static void com_thunk(void){
    uint32_t va=pending_va,sp=g_esp,ret=MEM32(sp),result=0,pop=0;int has=0;const char *label="?";
    mh_port_call_com(port,va,sp,&result,&has,&pop,&label);
    count(label,ret);
    if(has)g_eax=result;
    g_esp=sp+pop;
}
static void prus_slot(void){
    uint32_t ret=MEM32(g_esp);
    const mh_redirect_site *site=mh_redirect_find(mh_redirect_sites,sizeof mh_redirect_sites/sizeof mh_redirect_sites[0],ret);
    if(!site)unsupported("call through the protection slot from an unclassified site");
    switch(site->kind){
    case MH_REDIRECT_GET_LAST_ERROR:redirects[0]++;g_eax=*mh_port_last_error(port);g_esp+=4;break;
    case MH_REDIRECT_VALIDATE_POINTER:redirects[1]++;g_eax=mh_redirect_validate_pointer(&mh_recomp_region,MEM32(g_esp+4),MEM32(g_esp+8));g_esp+=12;break;
    case MH_REDIRECT_INTEGRITY:redirects[2]++;g_eax=site->value;g_esp+=4+4u*site->args;break;   /* the answer of an intact copy */
    case MH_REDIRECT_MIRROR:{unsigned h=site->args&0x7fu;redirects[2]++;
        if(site->args&0x80u)MEM32(MEM32(g_esp+4+4*h+4))=site->value;   /* stack: ret, header, A, M, B */
        g_eax=site->value;g_esp+=4+4*h;break;}
    case MH_REDIRECT_STORE:redirects[2]++;MEM32(g_ebx)=g_ecx;g_eax=g_ecx;g_esp+=4;break;
    /* MH_REDIRECT_RESUME sites are rewritten by the lifter (a jump within the caller) and never get here */
    default:unsupported("protection trigger site reached");
    }
}
void sub_00400080(void){
    uint32_t slot=0,e=g_esp;
    if(!mh_header_redirect_slot(&mh_recomp_region,MEM32(e),&slot))unsupported("header stub called from an unknown site");
    uint32_t target=MEM32(slot);
    MEM32(e-4)=target;MEM32(e-8)=g_eax;MEM32(e-12)=g_ecx;MEM32(e-16)=g_edx;MEM32(e-20)=g_ebx;
    MEM32(e-24)=e-4;MEM32(e-28)=g_ebp;MEM32(e-32)=g_esi;MEM32(e-36)=g_edi;
    recomp_func_t fn=recomp_lookup(target);
    if(!fn)mh_dispatch_fault(target,g_cur_func);
    fn();
}
/* 0x4becc0 (GetDXVersion) is replaced by the port: DirectX 8.1. */
void sub_004BECC0(void){count("GetDXVersion (HLE)",MEM32(g_esp));g_eax=0x801;g_esp+=4;}
recomp_func_t recomp_lookup(uint32_t va){
    if(va>=API_BASE+0x10u&&va<API_BASE+0x10u*(WINMAIN_IMPORTS+1u)&&!(va&0xfu)){pending_va=va;return api_thunk;}
    if(mh_port_is_com(va)){pending_va=va;return com_thunk;}
    if(va==prus_target)return prus_slot;
    if(va==0x4becc0u)return sub_004BECC0;
    return winmain_dispatch(va);
}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}

static uint32_t run_crc_table[256];
uint32_t mh_game_crc32(const uint8_t *p,size_t n){
    if(!run_crc_table[1])for(uint32_t i=0;i<256;i++){uint32_t c=i;for(int k=0;k<8;k++)c=c&1?0xedb88320u^(c>>1):c>>1;run_crc_table[i]=c;}
    uint32_t c=0xffffffffu;
    for(size_t i=0;i<n;i++)c=run_crc_table[(c^p[i])&255]^(c>>8);
    return c^0xffffffffu;
}
int mh_game_run(const mh_game_config *config){
    cfg=*config;
    FILE *f=fopen(cfg.exe_path,"rb");if(!f){game_log("cannot open %s",cfg.exe_path);return 77;}
    uint8_t *file=malloc(EXE_SIZE+1);size_t n=file?fread(file,1,EXE_SIZE+1,f):0;fclose(f);
    if(n!=EXE_SIZE||mh_game_crc32(file,n)!=EXE_CRC32){game_log("unexpected executable");free(file);return 78;}
    guest=calloc(1,GUEST_SIZE);if(!guest){free(file);return 71;}
    mh_guest_memory image;mh_pe32_info info;
    if(!mh_mem_init(&image,guest+0x400000,0xa18000-0x400000,0x400000)||!mh_pe32_map_image(file,n,&image,&info)){free(file);return 79;}
    free(file);
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,GUEST_SIZE-0x10000,0x10000))return 72;
    for(unsigned k=0;k<WINMAIN_IMPORTS;k++){MEM32(winmain_imports[k].slot)=API_BASE+0x10u*(k+1u);import_api[k]=mh_port_find_api(winmain_imports[k].name);}
    prus_target=MEM32(0x850000);
    const mh_port_host host={NULL,host_call_guest,port_fault,port_frames};
    port=mh_port_create(&mh_recomp_region,&host,cfg.game_dir,cfg.frame_limit);if(!port)return 75;
    if(cfg.renderer)mh_port_set_renderer(port,cfg.renderer);
    if(cfg.langid)mh_port_set_language(port,cfg.langid);
    if(cfg.key_script){mh_port_key_span spans[64];unsigned n=mh_port_parse_key_script(cfg.key_script,spans,64);mh_port_set_key_script(port,spans,n);}
    if(cfg.on_ready)cfg.on_ready(cfg.user,port,&mh_recomp_region);
    /* boot phase 2 */
    for(unsigned i=0;i<BOOT_RUNS;i++){
        g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x33333333;g_edx=0x44444444;g_esi=0x55555555;g_edi=0x66666666;g_ebp=0x77777777;
        g_esp=STACK_TOP;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;MEM32(STACK_TOP)=RETURN_SENTINEL;
        for(unsigned a=0;a<boot_runs[i].argc;a++)MEM32(STACK_TOP+4+4*a)=boot_runs[i].args[a];
        if(cfg.trace_all)game_log("boot run %u: 0x%08x",i,boot_runs[i].va);
        boot_runs[i].fn();
        if(g_esp!=STACK_TOP+4){game_log("run 0x%08x left esp 0x%08x",boot_runs[i].va,g_esp);return 73;}
    }
    /* WinMain, as the CRT entry calls it */
    mh_port_begin_winmain(port);counting=1;
    g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x33333333;g_edx=0x44444444;g_esi=0x55555555;g_edi=0x66666666;g_ebp=0x77777777;
    g_esp=STACK_TOP;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
    const uint32_t frame[5]={RETURN_SENTINEL,0x400000u,0,RUN_PROCESS_DATA+MEM32(0x82926c),10};
    for(unsigned i=0;i<5;i++)MEM32(STACK_TOP+4*i)=frame[i];
    if(!setjmp(frames_done)){sub_004C1080();game_log("WinMain returned (eax %08x)",g_eax);return 80;}
    return 0;
}

/* ---- results, for the comparison harness */
mh_port *mh_game_port(void){return port;}
uint8_t *mh_game_guest(void){return guest;}
unsigned mh_game_calls(void){return ncalls;}
static int by_name(const void *a,const void *b){return strcmp(((const char*)a),((const char*)b));}
void mh_game_print_result(FILE *out){
    qsort(counts,ncounts,sizeof counts[0],by_name);
    fprintf(out,"{\"calls\":%u,\"api_counts\":{",ncalls);
    for(unsigned i=0;i<ncounts;i++)fprintf(out,"%s\"%s\":%u",i?",":"",counts[i].name,counts[i].count);
    uint32_t com_next=mh_port_com_next(port),res_next=mh_port_res_next(port);
    fprintf(out,"},\"clock\":%llu,\"frames\":%u,\"last_error\":%u,\"global_next\":%u,\"com_next\":%u,\"res_next\":%u,",
            (unsigned long long)mh_port_clock(port),mh_port_frames(port),*mh_port_last_error(port),mh_port_global(port)->next,com_next,res_next);
    fprintf(out,"\"data_crc\":%u,\"bss_crc\":%u,\"image_crc\":[%u,%u],\"stack_crc\":%u,\"global_crc\":%u,\"com_crc\":%u,\"res_crc\":%u,\"fpu_cw\":%u}\n",
            mh_game_crc32(guest+0x67d000,0x7ed4a0-0x67d000),mh_game_crc32(guest+0x81e000,0x8296d4-0x81e000),
            mh_game_crc32(guest+0x400000,0x81b000-0x400000),mh_game_crc32(guest+0x81c2a0,0xa16000-0x81c2a0),
            mh_game_crc32(guest+STACK_TOP-0x10000,0x10014),mh_game_crc32(guest+RUN_GLOBAL_BASE,mh_port_global(port)->next-RUN_GLOBAL_BASE),
            mh_game_crc32(guest+0x1e40000,com_next-0x1e40000),mh_game_crc32(guest+0x10000000u,res_next-0x10000000u),g_fpu_cw);
}
