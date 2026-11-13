#include "win_tick.h"

int mh_tick_from_elapsed(uint64_t seconds, uint32_t nanoseconds, uint32_t *out){
    if(!out||nanoseconds>=1000000000u)return 0;
    *out=(uint32_t)seconds*1000u+nanoseconds/1000000u;
    return 1;
}
