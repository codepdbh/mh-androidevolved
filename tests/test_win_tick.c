#include "win_tick.h"
#define CHECK(x) do { if(!(x)) return __LINE__; } while(0)
static int fake_clock(void *context,uint32_t *tick){
    if(!context)return 0;
    *tick=*(const uint32_t *)context;return 1;
}
int mh_tick_tests(void){
    uint32_t out=99;
    CHECK(mh_tick_from_elapsed(0,999999,&out)&&out==0);
    CHECK(mh_tick_from_elapsed(1,999999999,&out)&&out==1999);
    CHECK(mh_tick_from_elapsed(4294967,296000000,&out)&&out==0);
    CHECK(mh_tick_from_elapsed(UINT64_MAX,999000000,&out)&&out==UINT32_MAX);
    out=99;CHECK(!mh_tick_from_elapsed(0,1000000000,&out)&&out==99);
    CHECK(!mh_tick_from_elapsed(0,0,0));
    uint8_t stack[8]={0x78,0x56,0x34,0x12,0,0,0,0};mh_guest_memory mem;
    mh_tick_x86_state state={17,0x1000};uint32_t ret=88;
    CHECK(mh_mem_init(&mem,stack,sizeof stack,0x1000));
    CHECK(mh_tick_x86_return(&mem,&state,0xdeadbeefu,&ret));
    CHECK(state.eax==0xdeadbeefu&&state.esp==0x1004&&ret==0x12345678u);
    state.eax=17;state.esp=0x1006;ret=88;
    CHECK(!mh_tick_x86_return(&mem,&state,4,&ret));
    CHECK(state.eax==17&&state.esp==0x1006&&ret==88);
    state.esp=UINT32_MAX-2u;
    CHECK(!mh_tick_x86_return(&mem,&state,4,&ret));
    CHECK(state.eax==17&&state.esp==UINT32_MAX-2u&&ret==88);
    state.esp=0x1000;
    CHECK(!mh_tick_x86_return(&mem,&state,4,&state.eax));
    CHECK(state.eax==17&&state.esp==0x1000);
    uint32_t sample=1234;
    CHECK(!mh_tick_x86_invoke(&mem,&state,fake_clock,0,&ret));
    CHECK(state.eax==17&&state.esp==0x1000&&ret==88);
    CHECK(mh_tick_x86_invoke(&mem,&state,fake_clock,&sample,&ret));
    CHECK(state.eax==1234&&state.esp==0x1004&&ret==0x12345678u);
#ifdef MH_TEST_ANDROID_BOOT_CLOCK
    uint32_t first=0,last=0;
    CHECK(mh_android_boot_tick_count(&first));
    CHECK(mh_android_boot_tick_count(&last));
    CHECK((uint32_t)(last-first)<10000u);
    CHECK(!mh_android_boot_tick_count(0));
    state.eax=17;state.esp=0x1000;ret=0;
    CHECK(mh_tick_x86_invoke(&mem,&state,mh_android_boot_tick_provider,0,&ret));
    CHECK(state.esp==0x1004&&ret==0x12345678u&&(uint32_t)(state.eax-last)<10000u);
#endif
    return 0;
}
