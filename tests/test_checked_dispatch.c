/* Synthetic dispatch tests only; no game code or graphics. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
#include "../runtime/win_tick_x86.c"
#include "../runtime/tick_dispatch.c"

uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
_Alignas(8) static uint8_t guest[256];
_Alignas(8) static uint8_t timer_guest[256];
static uint32_t tail_target_va;
static uint32_t expected_tick_return;
#ifdef __ANDROID__
static int use_real_clock;
#endif

void mh_guest_fault(uint32_t address,size_t width) { (void)address;(void)width;exit(70); }
void mh_dispatch_fault(uint32_t target,uint32_t caller) {
    exit(target==0x4444 && caller==0x1000 ? 74 : 77);
}
static void call_target(void) { g_eax=0x12345678;g_esp+=4; }
static void tail_target(void) { g_eax=0x87654321; }
static int fake_tick_clock(void *ctx,uint32_t *tick) { (void)ctx;*tick=0x12345678u;return 1; }
static int allowed_tick_return(void *ctx,uint32_t ret) { return ret==*(const uint32_t *)ctx; }
/* Synthetic adapter only. It admits an explicitly audited return address. */
static void tick_target(void) {
    mh_tick_clock clock=fake_tick_clock;
#ifdef __ANDROID__
    if(use_real_clock)clock=mh_android_boot_tick_provider;
#endif
    mh_tick_dispatch dispatch={&mh_recomp_region,clock,NULL,allowed_tick_return,&expected_tick_return};
    if (!mh_tick_dispatch_call(&dispatch,&g_eax,&g_esp)) exit(78);
}
recomp_func_t recomp_lookup(uint32_t va) { return va==0x2000?call_target:(va==0x3000?tail_target:(va==0x5000?tick_target:NULL)); }
recomp_func_t recomp_lookup_manual(uint32_t va) { (void)va;return NULL; }
recomp_func_t recomp_lookup_import(uint32_t va) { (void)va;return NULL; }

static void issue_call(uint32_t target) {
    uint32_t _cf=0,_flag_a=0,_flag_b=0,_flag_k=FK_NONE;
    RECOMP_ENTER(0x1000); RECOMP_ICALL(target); RECOMP_FLAGS_IN(); RECOMP_FLAGS_OUT();
}
static void issue_tail(void) {
    uint32_t _cf=0,_flag_a=0,_flag_b=0,_flag_k=FK_NONE;
    RECOMP_ENTER(0x1000); RECOMP_ITAIL(tail_target_va); return;
}
static void issue_precise(uint32_t target) {
    uint32_t _cf=0,_flag_a=0,_flag_b=0,_flag_k=FK_NONE;
    RECOMP_ENTER(0x1000); MH_RECOMP_ICALL_AT(target,0x1234abcd); RECOMP_FLAGS_IN(); RECOMP_FLAGS_OUT();
}
static void issue_direct_precise(void) {
    uint32_t _cf=0,_flag_a=0,_flag_b=0,_flag_k=FK_NONE;
    RECOMP_ENTER(0x1000); MH_RECOMP_CALL_AT(call_target,0x8765abcd); RECOMP_FLAGS_IN(); RECOMP_FLAGS_OUT();
}
static void issue_timer_iat(uint32_t return_va) {
    uint32_t _cf=0,_flag_a=0,_flag_b=0,_flag_k=FK_NONE;
    RECOMP_ENTER(0x6081a0); MH_RECOMP_ICALL_AT(MEM32(0x81b4fc),return_va); RECOMP_FLAGS_IN(); RECOMP_FLAGS_OUT();
}
int main(int argc,char **argv) {
    if (!mh_mem_init(&mh_recomp_region,guest,sizeof guest,0x10000)) return 71;
    g_esp=0x10080;g_mem_base=0;
    if (argc==2 && strcmp(argv[1],"--missing-call")==0) { issue_call(0x4444);return 75; }
    if (argc==2 && strcmp(argv[1],"--missing-tail")==0) { tail_target_va=0x4444;issue_tail();return 75; }
    if (argc==2 && strcmp(argv[1],"--missing-precise")==0) { issue_precise(0x4444);return 75; }
    if (argc==2 && strcmp(argv[1],"--tick-return-mismatch")==0) { expected_tick_return=1;issue_call(0x5000);return 75; }
    if (argc!=1) return 76;
    issue_call(0x2000);
    if (g_eax!=0x12345678 || g_esp!=0x10080 || g_cur_func!=0x1000) return 1;
    tail_target_va=0x3000;issue_tail();
    if (g_eax!=0x87654321 || g_esp!=0x10080) return 2;
    tail_target_va=RECOMP_RETADDR;issue_tail();
    if (g_esp!=0x10080) return 3;
    issue_precise(0x2000);
    if (g_eax!=0x12345678 || g_esp!=0x10080 || MEM32(0x1007c)!=0x1234abcd) return 4;
    issue_direct_precise();
    if (g_eax!=0x12345678 || g_esp!=0x10080 || MEM32(0x1007c)!=0x8765abcd) return 5;
    if (g_icall_count!=4 || g_icall_trace_idx!=4 || g_icall_trace[0]!=0x2000 ||
        g_icall_trace[1]!=0x3000 || g_icall_trace[2]!=RECOMP_RETADDR ||
        g_icall_trace[3]!=0x2000 || g_icall_from[0]!=0x1000 || g_icall_from[1]!=0x1000 ||
        g_icall_from[2]!=0x1000 || g_icall_from[3]!=0x1000) return 6;
    expected_tick_return=RECOMP_RETADDR;issue_call(0x5000);
    if(g_eax!=0x12345678u||g_esp!=0x10080||MEM32(0x1007c)!=RECOMP_RETADDR)return 7;
    expected_tick_return=0x1234abcdu;issue_precise(0x5000);
    if(g_eax!=0x12345678u||g_esp!=0x10080||MEM32(0x1007c)!=0x1234abcdu)return 8;
#ifdef __ANDROID__
    uint32_t before=0,after=0;
    if(!mh_android_boot_tick_count(&before))return 9;
    use_real_clock=1;expected_tick_return=RECOMP_RETADDR;issue_call(0x5000);
    if(!mh_android_boot_tick_count(&after)||g_esp!=0x10080 ||
       (uint32_t)(g_eax-before)>(uint32_t)(after-before) || (uint32_t)(after-before)>10000u)return 10;
#endif
    uint32_t sample_eax=9,sample_esp=0x1007c,denied=1;
    mh_tick_dispatch denied_dispatch={&mh_recomp_region,fake_tick_clock,NULL,allowed_tick_return,&denied};
    if(mh_tick_dispatch_call(&denied_dispatch,&sample_eax,&sample_esp)||sample_eax!=9||sample_esp!=0x1007c)return 11;
    if(mh_tick_dispatch_call(&denied_dispatch,&sample_eax,&sample_eax)||sample_eax!=9)return 12;
    if(!mh_mem_init(&mh_recomp_region,timer_guest,sizeof timer_guest,0x81b400))return 13;
    MEM32(0x81b4fc)=0x5000;g_esp=0x81b480;
#ifdef __ANDROID__
    use_real_clock=0;
#endif
    expected_tick_return=0x6081b5;issue_timer_iat(expected_tick_return);
    if(g_eax!=0x12345678u||g_esp!=0x81b480||MEM32(0x81b47c)!=0x6081b5)return 14;
    expected_tick_return=0x608219;issue_timer_iat(expected_tick_return);
    if(g_eax!=0x12345678u||g_esp!=0x81b480||MEM32(0x81b47c)!=0x608219)return 15;
    puts("checked calls, tail calls and return sentinel passed");return 0;
}
