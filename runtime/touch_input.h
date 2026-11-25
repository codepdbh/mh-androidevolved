#ifndef MH_TOUCH_INPUT_H
#define MH_TOUCH_INPUT_H
#include <limits.h>
#include <stdint.h>
#include <string.h>

/* UI-thread input mailbox. The caller holds its mutex for every operation. The game thread
 * takes a snapshot once per frame; even a press/release between frames stays down for one frame. */
#define MH_TOUCH_KEYS 264u
typedef struct {
    uint8_t held[MH_TOUCH_KEYS], pressed[MH_TOUCH_KEYS];
    int32_t dx, dy;
} mh_touch_input;
static inline void mh_touch_key(mh_touch_input *input, unsigned key, int down) {
    if (key >= MH_TOUCH_KEYS) return;
    if (down && !input->held[key]) input->pressed[key] = 1;
    input->held[key] = down != 0;
}
static inline int32_t mh_touch_sum(int32_t old, int32_t delta) {
    int64_t sum = (int64_t)old + delta;
    return sum > INT32_MAX ? INT32_MAX : sum < INT32_MIN ? INT32_MIN : (int32_t)sum;
}
static inline void mh_touch_move(mh_touch_input *input, int32_t dx, int32_t dy) {
    input->dx = mh_touch_sum(input->dx, dx); input->dy = mh_touch_sum(input->dy, dy);
}
static inline void mh_touch_take(mh_touch_input *input, uint8_t keys[MH_TOUCH_KEYS], int32_t *dx, int32_t *dy) {
    for (unsigned i = 0; i < MH_TOUCH_KEYS; i++) keys[i] = input->held[i] || input->pressed[i];
    memset(input->pressed, 0, sizeof input->pressed);
    *dx = input->dx; *dy = input->dy; input->dx = input->dy = 0;
}
#endif
