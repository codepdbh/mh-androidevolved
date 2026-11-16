/* Isolated candidate test harness; all dependencies are test doubles. */
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
void mh_guest_fault(uint32_t a,size_t n){exit(a==0x11a8 && n==4?70:(a==0xc && n==4?71:79));}
void mh_dispatch_fault(uint32_t a,uint32_t b){exit(a==0 && b==0x6081a0?74:(a==0 && b==0x604dc0?75:79));}
#ifndef MH_REAL_SMALL_DEPS
void sub_00648540(void){if(MEM32(g_esp)!=0x6081ad)exit(80);g_edx=MEM32(g_esp);g_esp+=4;g_esp-=0x12ac;}
#endif
static uint32_t mock_result;
void sub_00605750(void){if(MEM32(g_esp)!=0x608211)exit(81);g_eax=mock_result;g_esp+=64;}
#ifndef MH_REAL_SMALL_DEPS
void sub_00426EF0(void){if(MEM32(g_esp)!=0x608226)exit(82);g_esp+=4;}
void sub_00481330(void){if(MEM32(g_esp)!=0x6082a5)exit(83);g_esp+=4;}
void sub_00608410(void){if(MEM32(g_esp)!=0x608261)exit(83);g_esp+=8;}
void sub_00481340(void){if(MEM32(g_esp)!=0x6082ad)exit(83);g_esp+=4;}
#endif
#ifdef MH_REAL_SMALL_DEPS
/* Callees of the translated dispatcher 0x5daa20: counters only, no game behaviour. */
void sub_00476A80(void){if(MEM32(g_esp)!=0x5daa2e)exit(87);MEM32(0x8a0000)+=1;g_esp+=4;}
void sub_00476AA0(void){if(MEM32(g_esp)!=0x5daa3e)exit(87);MEM32(0x8a0000)+=0x100;g_esp+=4;}
/* Callees of the translated x87 dependency 0x5daa50; the first mirrors the x86
 * double's push/pop, which leaves its argument just below the stack pointer. */
void sub_005DB0D0(void){if(MEM32(g_esp)!=0x5daa98)exit(88);MEM32(g_esp-4)=MEM32(g_esp+4);MEM32(0x8a0004)=MEM32(g_esp+4);MEM32(0x8a0008)+=1;g_esp+=4;}
void sub_00482F20(void){if(MEM32(g_esp)!=0x5daaa8)exit(88);MEM32(0x8a000c)+=1;g_esp+=4;}
#else
void sub_005DAA20(void){if(MEM32(g_esp)!=0x6083a9)exit(83);g_esp+=4;}
void sub_005DAA50(void){if(MEM32(g_esp)!=0x6083ae)exit(83);g_esp+=4;}
#endif
/* Synthetic callee of the translated wrapper; no allocation or freeing. */
void sub_00401B00(void){uint32_t arg=MEM32(g_esp+4);if(MEM32(g_esp)!=0x40103e||g_ecx!=0x67d000||(arg!=0x860000&&arg!=0x860100))exit(85);g_esp+=8;}
void sub_004932F0(void){if(MEM32(g_esp)!=0x604e24)exit(85);g_esp+=4;}
void sub_00493230(void){if(MEM32(g_esp)!=0x604e2e)exit(85);g_esp+=4;}
static void fake_tick(void){uint32_t ret=MEM32(g_esp);if(ret!=0x6081b5 && ret!=0x608219)exit(84);g_eax=MEM32(0x810000);g_edx=g_eax+40;MEM32(0x810000)=g_edx;g_esp+=4;}
static void fake_virtual(void){uint32_t ret=MEM32(g_esp);if(ret!=0x604dd6 && ret!=0x604e40)exit(86);g_esp+=4;}
recomp_func_t recomp_lookup(uint32_t va){return va==0x800100?fake_tick:((va==0x800200||va==0x800210)?fake_virtual:NULL);}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "time_checked_unit.c"
#ifdef MH_REAL_SMALL_DEPS
#include "dependencies/dep_00426ef0.c"
#include "dependencies/dep_00481330.c"
#include "dependencies/dep_00608410.c"
void sub_00604DC0(void);void sub_00604F30(void);
#include "dependencies/dep_00604d20_precise.c"
#include "dependencies/dep_00604f30.c"
void sub_00401030(void);void sub_004932F0(void);void sub_00493230(void);
#include "dependencies/dep_00604dc0_precise.c"
#include "dependencies/dep_005daa20_precise.c"
#include "dependencies/dep_00611640_precise.c"
#include "dependencies/dep_00481340_precise.c"
#include "dependencies/dep_00648540.c"
#include "dependencies/dep_005ea2b0_precise.c"
#include "dependencies/dep_005daa50_precise.c"
#include "dependencies/dep_00401030_precise.c"
#endif
/* x87 inputs per mode as exact float bit patterns: plain values, zero divisor in
 * the second division, negative/inexact values, zero divisors in both. The last
 * field is the getter value; 2 selects the call to 0x482f20. */
static const struct {uint32_t mul,div,ref_int,sub,getter;} x87_inputs[4]={
    {0x3fc00000u,0x40400000u,640,0x3f000000u,2},{0x3fc00000u,0x40400000u,0,0x00000000u,1},
    {0xbe800000u,0x40e00000u,0xfffffffdu,0x3dcccccdu,2},{0x7f800000u,0x7f800000u,1,0x3f800000u,0}};
static void setup_x87(unsigned m){
    MEM32(0x7c8a78)=x87_inputs[m].mul;MEM32(0x7c95a0)=x87_inputs[m].div;MEM32(0x7c8a74)=x87_inputs[m].ref_int;
    MEM32(0x7c908c)=x87_inputs[m].sub;MEM32(0x7d34f8)=x87_inputs[m].getter;
    MEM32(0x7d3510)=0;MEM32(0x7c8fec)=0;MEM32(0x8a0004)=0;MEM32(0x8a0008)=0;MEM32(0x8a000c)=0;
    memset(g_st,0,sizeof g_st);g_fp_top=0;g_fpu_cw=0x037f;
}
/* Mode selector for 0x5daa20 per alignment: first call, second call, neither, pattern value. */
static const uint32_t dispatch_modes[4]={0,1,2,0xe2df6fd3u};
/* Synthetic objects read by 0x481340, per tick index: none, A only, B only, both.
 * Sizes and destinations cover the byte-only, aligned and misaligned copy paths. */
static const struct {uint32_t a_dst,a_size,b_dst,b_size;int a,b;} copy_objects[4]={
    {0,0,0,0,0,0},{0x8a2001,7,0,0,1,0},{0,0,0x8a2402,0x23,0,1},{0x8a2000,0x40,0x8a2403,0x31,1,1}};
static void setup_copy_objects(unsigned t){
    memset(guest+0x8a1000,0,0x1600);
    for(unsigned i=0;i<0x100;i++)guest[0x71a860+i]=(uint8_t)(i*3+1);
    MEM32(0x71c87c)=copy_objects[t].a?0x8a1000:0;MEM32(0x71c880)=copy_objects[t].b?0x8a1400:0;
    MEM32(0x8a1170)=copy_objects[t].a_dst;MEM32(0x8a11b8)=copy_objects[t].a_size;
    MEM32(0x8a1570)=copy_objects[t].b_dst;MEM32(0x8a15b8)=copy_objects[t].b_size;
}
static void hex_bytes(const uint8_t *p,unsigned n){for(unsigned i=0;i<n;i++)printf("%02x",p[i]);}
static int run_virtual_zero(void){
    const uint32_t args[]={0,0x12345678u,0xffffffffu};
    for(unsigned k=0;k<12;k++){
        uint32_t argument=args[k/4],alignment=k%4;
        memset(guest+0x87ffe0,0,0x30);memset(guest+0x870000,0,0x20);
        g_mem_base=0;g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x870000;g_edx=0x33333333;
        g_esi=0x44444444;g_edi=0x55555555;g_ebp=0x66666666;g_esp=0x880000+alignment;
        g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
        MEM32(g_esp)=0x8f0000;MEM32(g_esp+4)=argument;MEM32(g_esp+8)=0;
        MEM32(0x736db8)=0x820000;MEM32(0x82000c)=0x821000;MEM32(0x821000)=0x822000;MEM32(0x822028)=0x800200;MEM32(0x822024)=0x800210;
        MEM32(0x725a54)=0x860000;MEM32(0x725a4c)=0x860100;
        sub_00604DC0();
        printf("{\"argument\":%u,\"alignment\":%u,\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},\"stack_hex\":\"",argument,alignment,g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        hex_bytes(guest+0x87ffe0,0x30);printf("\",\"object_hex\":\"");hex_bytes(guest+0x870000,0x20);
        printf("\",\"global_a\":%u,\"global_b\":%u}\n",MEM32(0x725a54),MEM32(0x725a4c));
    }
    return 0;
}
#define MH_X87_CHECKS_NO_MAIN
#include "test_x87_semantics.c"
int main(int argc,char **argv){
    if(argc==2&&!strcmp(argv[1],"--x87-semantics"))return mh_x87_semantic_checks();
    int null_object=argc==2&&!strcmp(argv[1],"--null-object"),missing_timer=argc==2&&!strcmp(argv[1],"--missing-timer"),missing_virtual=argc==2&&!strcmp(argv[1],"--missing-virtual"),null_virtual=argc==2&&!strcmp(argv[1],"--null-virtual-object"),virtual_zero=argc==2&&!strcmp(argv[1],"--virtual-zero");
    if(argc!=1&&!null_object&&!missing_timer&&!missing_virtual&&!null_virtual&&!virtual_zero)return 76;
    const uint32_t ticks[]={0,1234,0xffffffd0u,0xffffffffu};
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000))return 71;
    if(virtual_zero)return run_virtual_zero();
    for(unsigned k=0;k<64*sizeof(ticks)/sizeof(ticks[0]);k++){
        uint32_t tick=ticks[k/64],scenario=(k/16)%4,alignment=(k/4)%4,mode=k%4,guard=scenario==2?1:0;mock_result=scenario==0?0:(scenario==1?2:1);
        if(missing_virtual||null_virtual)mock_result=1;
        memset(guest+0x87ed00,0,0x1308);memset(guest+0x870000,0,0x1200);
        memset(guest+0x71a460,0,0x400);memset(guest+0x7d6ae4,0,0x10ec);MEM32(0x7d7bdc)=0;MEM32(0x7e8fa0)=0;MEM32(0x71c860)=0;
        for(unsigned i=0;i<0x400;i++)guest[0x7e6ba0+i]=(uint8_t)(i*7+3);
        for(unsigned i=0;i<0x60;i++)guest[0x7d6af0+i]=(uint8_t)(i*5+11);
        MEM32(0x7d6b18)=dispatch_modes[alignment];MEM32(0x8a0000)=0;setup_copy_objects(k/64);setup_x87(mode);
        g_mem_base=0;g_eax=0x11111111;g_ebx=0x22222222;g_ecx=null_object?0:0x870000;g_edx=0x33333333;
        g_esi=0x44444444;g_edi=0x55555555;g_ebp=0x66666666;g_esp=0x880000+alignment;
        g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
        MEM32(0x81b4fc)=missing_timer?0:0x800100;MEM32(0x810000)=tick;MEM32(g_esp)=0x8f0000;MEM32(0x8711c4)=guard;
        MEM32(0x736db8)=null_virtual?0:0x820000;MEM32(0x82000c)=0x821000;MEM32(0x821000)=0x822000;MEM32(0x822028)=missing_virtual?0:0x800200;MEM32(0x822024)=0x800210;
        MEM32(0x725a54)=mode&1?0x860000:0;MEM32(0x725a4c)=mode&2?0x860100:0;
        sub_006081A0();
        printf("{\"tick\":%u,\"result\":%u,\"guard\":%u,\"alignment\":%u,\"mode\":%u,\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},\"stack_hex\":\"",tick,mock_result,guard,alignment,mode,g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        hex_bytes(guest+0x87ed00,0x1308);printf("\",\"object_hex\":\"");hex_bytes(guest+0x870000,16);
        printf("\",\"copy_hex\":\"");hex_bytes(guest+0x71a460,0x400);
        printf("\",\"structure_hex\":\"");hex_bytes(guest+0x7d6ae4,0x10ec);
        printf("\",\"global_value\":%u,\"small_dep_value\":%u,\"inner_dep_value\":%u,\"global_a_after\":%u,\"global_b_after\":%u,\"tick_after\":%u,\"branch_calls\":%u,\"copy_out_hex\":\"",MEM32(0x7e8fa0),MEM32(0x71c860),MEM32(0x7d7bdc),MEM32(0x725a54),MEM32(0x725a4c),MEM32(0x810000),MEM32(0x8a0000));
        hex_bytes(guest+0x8a2000,0x500);
        printf("\",\"float_a\":%u,\"float_b\":%u,\"x87_arg\":%u,\"x87_calls\":%u,\"x87_tail_calls\":%u,\"fp_top\":%d}\n",
               MEM32(0x7d3510),MEM32(0x7c8fec),MEM32(0x8a0004),MEM32(0x8a0008),MEM32(0x8a000c),g_fp_top);
    }
    return 0;
}
