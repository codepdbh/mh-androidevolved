#include "touch_input.h"
#include <stdio.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } checks++; } while (0)
int main(void) {
    mh_touch_input input = {0}; uint8_t keys[MH_TOUCH_KEYS]; int32_t dx, dy; unsigned checks = 0;
    mh_touch_key(&input, 0x1c, 1); mh_touch_key(&input, 0x1c, 0);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(keys[0x1c]); CHECK(!dx && !dy);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(!keys[0x1c]);
    mh_touch_key(&input, 0xc8, 1); mh_touch_key(&input, 0x2a, 1); mh_touch_key(&input, 0x100, 1);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(keys[0xc8] && keys[0x2a] && keys[0x100]);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(keys[0xc8] && keys[0x2a] && keys[0x100]);
    mh_touch_key(&input, 0xc8, 0); mh_touch_key(&input, 0x2a, 0); mh_touch_key(&input, 0x100, 0);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(!keys[0xc8] && !keys[0x2a] && !keys[0x100]);
    mh_touch_key(&input, MH_TOUCH_KEYS, 1); mh_touch_key(&input, UINT32_MAX, 1);
    mh_touch_move(&input, 12, -9); mh_touch_move(&input, -2, 4);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(dx == 10 && dy == -5);
    for (unsigned i = 0; i < MH_TOUCH_KEYS; i++) CHECK(!keys[i]);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(!dx && !dy);
    mh_touch_move(&input, INT32_MAX, INT32_MIN); mh_touch_move(&input, 1, -1);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(dx == INT32_MAX && dy == INT32_MIN);
    mh_touch_move(&input, INT32_MIN, INT32_MAX); mh_touch_move(&input, INT32_MAX, INT32_MIN);
    mh_touch_take(&input, keys, &dx, &dy); CHECK(dx == -1 && dy == -1);
    printf("touch input: %u checks passed; short taps, held keys, multitouch, accumulated motion, saturation\n", checks);
    return 0;
}
