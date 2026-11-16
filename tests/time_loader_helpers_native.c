/* Private translated helpers, synthetic guest memory and ReadFile only. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
static _Alignas(8) uint8_t guest[0x900000];
static uint32_t buffer,count,read_out,result,calls;
void mh_guest_fault(uint32_t a,size_t n){exit(a==0&&n==4?70:79);}
void mh_dispatch_fault(uint32_t a,uint32_t c){exit(a==0&&c==0x60ff60?74:79);}
static void mock_read_file(void){
    if(MEM32(g_esp)!=0x60ff76||MEM32(g_esp+4)!=0x1234||MEM32(g_esp+8)!=buffer||MEM32(g_esp+12)!=count||MEM32(g_esp+16)!=read_out||MEM32(g_esp+20)!=0)exit(80);
    if(result)for(uint32_t i=0;i<count;i++)MEM8(buffer+i)=(uint8_t)(i+1);
    MEM32(read_out)=result?count:0;g_eax=result;g_esp+=24;calls++;
}
recomp_func_t recomp_lookup(uint32_t va){return va==0x800300?mock_read_file:NULL;}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "loader_helpers_unit.c"
static void seed(uint32_t sp){
    g_eax=9;g_ebx=10;g_ecx=11;g_edx=12;g_esi=13;g_edi=14;g_ebp=15;g_esp=sp;g_mem_base=0;
    g_flag_k=FK_CMP;g_flag_a=3;g_flag_b=5;g_flag_cf=1;
}
int main(int argc,char **argv){
    int missing=argc==2&&!strcmp(argv[1],"--missing-readfile"),bad=argc==2&&!strcmp(argv[1],"--bad-object");
    if(argc!=1&&!missing&&!bad)return 76;
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000))return 71;
    const uint32_t values[]={0,1,0xfffffd54u,0xffffffffu},sizes[]={0,1,7,31};
    for(unsigned k=0;k<16;k++){
        uint32_t sp=0x880000+k%4;seed(sp);g_ecx=values[k/4];sub_00605E40();
        if(g_eax!=values[k/4]+0x2acu||g_esp!=sp+4)return 1;
        seed(sp);g_ecx=0x820001+k%4;MEM32(g_ecx)=0;sub_0060FEA0();
        if(g_eax!=g_ecx||MEM32(g_ecx)!=0xffffffffu||g_esp!=sp+4)return 2;
    }
    for(unsigned k=0;k<32;k++){
        uint32_t sp=0x880000+k%4;seed(sp);buffer=0x830001+k%4;read_out=0x840003;count=sizes[(k/4)%4];result=k/16;calls=0;
        g_ecx=bad?0:0x820001;MEM32(0x820001)=0x1234;MEM32(0x81b374)=missing?0:0x800300;
        MEM32(sp)=0x220000;MEM32(sp+4)=buffer;MEM32(sp+8)=count;MEM32(sp+12)=read_out;
        memset(guest+buffer,0xa5,32);MEM32(read_out)=0xffffffffu;
        uint32_t flags=recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1);
        sub_0060FF60();
        if(calls!=1||g_esp!=sp+16||g_eax!=result||MEM32(read_out)!=(result?count:0))return 3;
        for(uint32_t i=0;i<32;i++)if(MEM8(buffer+i)!=(result&&i<count?(uint8_t)(i+1):0xa5))return 4;
        if(g_ebx!=10||g_ecx!=0x820001||g_edx!=12||g_esi!=13||g_edi!=14||g_ebp!=15)return 5;
        if((flags&0x8d5)!=(recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1)&0x8d5))return 6;
        if(MEM32(sp)!=0x220000||MEM32(sp+4)!=buffer||MEM32(sp+8)!=count||MEM32(sp+12)!=read_out)return 7;
    }
    puts("64 helper checks passed; ReadFile remains simulated");return 0;
}
