/* Differential harness only; these simplified macros are not the Android runtime. */
#include <stdint.h>
#include <stddef.h>
static uint8_t memory[0x230000];
static uint32_t eax,ebx,ecx,edx,esi,edi,ebp,esp;
static uint32_t captured_kind,captured_a,captured_b,captured_cf;
#define MEM8(a) (*(uint8_t *)&memory[(uint32_t)(a)])
#define MEM16(a) (*(uint16_t *)&memory[(uint32_t)(a)])
#define MEM32(a) (*(uint32_t *)&memory[(uint32_t)(a)])
#define PUSH32(sp,v) do { (sp)-=4; MEM32(sp)=(v); } while(0)
#define POP32_VAL(sp) ((sp)+=4,MEM32((sp)-4))
#define LO8(v) ((uint8_t)(v))
#define LO16(v) ((uint16_t)(v))
#define SET_LO8(r,v) ((r)=((r)&0xffffff00u)|(uint8_t)(v))
#define SET_LO16(r,v) ((r)=((r)&0xffff0000u)|(uint16_t)(v))
#define CMP_NE(a,b) ((uint32_t)(a)!=(uint32_t)(b))
#define CMP_B(a,b) ((uint32_t)(a)<(uint32_t)(b))
#define CMP_BE(a,b) ((uint32_t)(a)<=(uint32_t)(b))
#define CMP_A(a,b) ((uint32_t)(a)>(uint32_t)(b))
#define CMP_AE(a,b) ((uint32_t)(a)>=(uint32_t)(b))
#define TEST_Z(a,b) (((uint32_t)(a)&(uint32_t)(b))==0)
#define FK_NONE 0
#define FK_ADD 1
#define FK_CMP 2
#define FK_TEST 3
#define FK_NARROW(k,s) ((k)|((s)<<8))
#define RECOMP_ENTER(a) ((void)(a))
#define RECOMP_FLAGS_OUT() (captured_kind=_flag_k,captured_a=_flag_a,captured_b=_flag_b,captured_cf=_cf)
#include "candidate.c"

void run_case(uint32_t key, uint32_t start, uint32_t end, uint32_t mode, uint32_t skew) {
    for (size_t i=0; i<256; ++i) { memory[0x107f80+i]=0; memory[0x200000+i]=0; memory[0x210000+i]=0; memory[0x220000+i]=0; }
    esp=0x108000+skew; eax=0; ebx=0x11111111; ecx=0x200000+skew; edx=0;
    esi=0x22222222; edi=0x33333333; ebp=0x44444444;
    MEM32(esp)=0x300000; MEM32(esp+4)=key; MEM32(esp+8)=0x220000+skew;
    MEM32(esp+12)=start; MEM32(esp+16)=end;
    MEM32(0x200004+skew)=mode; MEM32(0x20000c+skew)=0x210000+skew; MEM16(0x200010+skew)=3;
    MEM8(0x210000+skew)=10; MEM8(0x210008+skew)=20; MEM8(0x210010+skew)=30; MEM16(0x220000+skew)=0xffff;
    sub_0040A020();
}
uint32_t get_result(uint32_t skew) { return MEM16(0x220000+skew); }
uint32_t get_flags(void) {
    uint32_t kind=captured_kind&255, shift=captured_kind>>8;
    uint32_t a=captured_a,b=captured_b,r,cf=captured_cf&1,of=0,af=0;
    if (kind==FK_CMP) { r=a-b; cf=a<b; of=((a^b)&(a^r))>>31; af=((a^b^r)>>(shift+4))&1; }
    else if (kind==FK_ADD) { r=a+b; cf=r<a; of=(~(a^b)&(a^r))>>31; af=((a^b^r)>>(shift+4))&1; }
    else if (kind==FK_TEST) r=a&b;
    else return 2|cf;
    uint32_t low=(r>>shift)&255, ones=0;
    for (unsigned i=0;i<8;++i) ones+=(low>>i)&1;
    return 2|cf|((ones%2==0)<<2)|(af<<4)|((r==0)<<6)|((r>>31)<<7)|(of<<11);
}
uint32_t get_reg(uint32_t n) {
    switch(n) {case 0:return eax;case 1:return ebx;case 2:return ecx;case 3:return edx;
        case 4:return esi;case 5:return edi;case 6:return ebp;case 7:return esp;default:return 0;}
}
uintptr_t get_guest_memory(void) { return (uintptr_t)memory; }
