/* Isolated comparison using PCRecomp's actual recomp32 header, never the game. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#ifdef MH_CHECKED_TEST
#include "checked_memory_adapter.h"
#include "../runtime/guest_memory.c"
mh_guest_memory mh_recomp_region;
void mh_guest_fault(uint32_t address, size_t width) { (void)address; (void)width; exit(70); }
#endif

uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
#ifdef MH_X87_TEST
double g_st[8];
int g_fp_top;
uint16_t g_fpu_cw;
#endif
__declspec(align(8)) static uint8_t guest[0x230000];
#ifdef MH_X87_TEST
#include "candidate_checked.c"
#else
#include "candidate.c"
#endif

static void hex_bytes(const uint8_t *bytes, unsigned count) {
    for (unsigned i=0;i<count;++i) printf("%02x",bytes[i]);
}
static void run_case(uint32_t key, uint32_t start, uint32_t end, uint32_t mode, uint32_t skew) {
    memset(guest+0x107f80,0,256); memset(guest+0x200000,0,256);
    memset(guest+0x210000,0,256); memset(guest+0x220000,0,256);
#ifdef MH_CHECKED_TEST
    if (!mh_mem_init(&mh_recomp_region,guest,sizeof guest,0)) exit(71);
    g_mem_base=0; /* The tested candidate must not use the unchecked base. */
#else
    g_mem_base=(ptrdiff_t)(uintptr_t)guest;
#endif
    g_esp=0x108000+skew;g_eax=0;g_ebx=0x11111111;g_ecx=0x200000+skew;g_edx=0;
    g_esi=0x22222222;g_edi=0x33333333;g_ebp=0x44444444;
    g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
#ifdef MH_X87_TEST
    memset(g_st,0,sizeof g_st); g_fp_top=0; g_fpu_cw=0x037f;
#endif
    MEM32(g_esp)=0x300000;MEM32(g_esp+4)=key;MEM32(g_esp+8)=0x220000+skew;
    MEM32(g_esp+12)=start;MEM32(g_esp+16)=end;
    MEM32(0x200004+skew)=mode;MEM32(0x20000c+skew)=0x210000+skew;MEM16(0x200010+skew)=3;
    MEM16(0x220000+skew)=0xffff;
#ifdef MH_X87_TEST
    MEMF(0x210000+skew)=10.0f;MEMF(0x210008+skew)=20.0f;MEMF(0x210010+skew)=30.0f;
    sub_00409960();
#else
    MEM8(0x210000+skew)=10;MEM8(0x210008+skew)=20;MEM8(0x210010+skew)=30;
    sub_0040A020();
#endif
    printf("{\"key\":%u,\"start\":%u,\"end\":%u,\"mode\":%u,\"skew\":%u,\"result\":%u,",key,start,end,mode,skew,(unsigned)MEM16(0x220000+skew));
    printf("\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},",g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
    printf("\"stack_hex\":\"");hex_bytes(guest+0x107ff0+skew,36);
    printf("\",\"object_hex\":\"");hex_bytes(guest+0x200000+skew,32);
    printf("\",\"array_hex\":\"");hex_bytes(guest+0x210000+skew,24);
#ifdef MH_X87_TEST
    printf("\",\"fp_top\":%d}\n",g_fp_top);
#else
    puts("\"}");
#endif
}
int main(int argc, char **argv) {
#ifdef MH_X87_TEST
    int special = argc==2 && strcmp(argv[1],"--special")==0;
    if (special) {
        const uint32_t keys[]={0x80000000,0x7f800000,0xff800000,0x7fc00000};
        for (unsigned skew=0;skew<4;++skew) for (unsigned mode=0;mode<2;++mode) for (unsigned k=0;k<4;++k)
            for (unsigned start=0;start<3;++start) for (unsigned end=0;end<3;++end)
                run_case(keys[k],start,end,mode,skew);
        return 0;
    }
#endif
#ifdef MH_CHECKED_TEST
    if (argc==2) {
        if (!mh_mem_init(&mh_recomp_region,guest,sizeof guest,0)) return 71;
        if (strcmp(argv[1],"--oob")==0) { (void)MEM32((uint32_t)sizeof guest-2); return 72; }
        if (strcmp(argv[1],"--oob64")==0) { (void)MEM64((uint32_t)sizeof guest-7); return 72; }
        if (strcmp(argv[1],"--unaligned")==0) {
            MEM32(0x1001)=0x12345678u;
            return MEM32(0x1001)==0x12345678u && guest[0x1001]==0x78 && guest[0x1004]==0x12 ? 0 : 72;
        }
        if (strcmp(argv[1],"--widths")==0) {
            MEM64(0x1001)=UINT64_C(0x123456789abcdef0);
            if (MEM64(0x1001)!=UINT64_C(0x123456789abcdef0) || guest[0x1001]!=0xf0 || guest[0x1008]!=0x12) return 72;
            MEMF(0x1011)=1.5f;
            if (MEMF(0x1011)!=1.5f || guest[0x1011]!=0 || guest[0x1012]!=0 || guest[0x1013]!=0xc0 || guest[0x1014]!=0x3f) return 72;
            MEMD(0x1021)=-2.5;
            if (MEMD(0x1021)!=-2.5 || guest[0x1027]!=0x04 || guest[0x1028]!=0xc0) return 72;
            return 0;
        }
        return 73;
    }
#else
    (void)argc; (void)argv;
#endif
#ifdef MH_X87_TEST
    const uint32_t fixed[][3]={{0x40a00000,0,2},{0x41a00000,0,2},{0x42200000,0,2},{0x41a00000,2,1},{0x41f00000,0,0}};
    const uint32_t keys[]={0,0x40a00000,0x41200000,0x41700000,0x41a00000,0x41c80000,0x41f00000,0x420c0000,0xbf800000};
#else
    const uint32_t fixed[][3]={{5,0,2},{20,0,2},{40,0,2},{20,2,1},{30,0,0}};
    const uint32_t keys[]={0,5,10,15,20,25,30,35,255};
#endif
    for (unsigned i=0;i<5;++i) run_case(fixed[i][0],fixed[i][1],fixed[i][2],0,0);
    for (unsigned skew=0;skew<4;++skew) for (unsigned mode=0;mode<2;++mode) for (unsigned k=0;k<9;++k)
        for (unsigned start=0;start<3;++start) for (unsigned end=0;end<3;++end)
            run_case(keys[k],start,end,mode,skew);
    return 0;
}
