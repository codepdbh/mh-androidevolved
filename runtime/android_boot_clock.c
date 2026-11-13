#define _POSIX_C_SOURCE 200809L
#include "win_tick.h"
#include <time.h>

int mh_android_boot_tick_count(uint32_t *out){
    struct timespec now;
    if(!out||clock_gettime(CLOCK_BOOTTIME,&now)!=0||now.tv_sec<0||now.tv_nsec<0||now.tv_nsec>=1000000000L)return 0;
    return mh_tick_from_elapsed((uint64_t)now.tv_sec,(uint32_t)now.tv_nsec,out);
}
int mh_android_boot_tick_provider(void *context,uint32_t *out){
    (void)context;
    return mh_android_boot_tick_count(out);
}
