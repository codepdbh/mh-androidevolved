/* Synthetic checks for the x87 arithmetic helpers; no game code. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "x87_semantics.h"

static uint64_t bits64(double v) { uint64_t b; memcpy(&b, &v, sizeof b); return b; }
static uint32_t bits32(float v) { uint32_t b; memcpy(&b, &v, sizeof b); return b; }
static double from64(uint64_t b) { double v; memcpy(&v, &b, sizeof v); return v; }

int mh_x87_semantic_checks(void) {
    volatile double zero = 0.0, one = 1.0, inf = INFINITY;
    unsigned checks = 0;
#define CHECK(c) do { if (!(c)) { printf("failed: %s (line %d)\n", #c, __LINE__); return 1; } checks++; } while (0)
    /* Invalid operations yield the x87 real indefinite, also after a float store. */
    CHECK(bits64(mh_x87_div(zero, zero)) == 0xFFF8000000000000ull);
    CHECK(bits64(mh_x87_div(inf, inf)) == 0xFFF8000000000000ull);
    CHECK(bits64(mh_x87_sub(inf, inf)) == 0xFFF8000000000000ull);
    CHECK(bits64(mh_x87_add(inf, -inf)) == 0xFFF8000000000000ull);
    CHECK(bits64(mh_x87_mul(zero, inf)) == 0xFFF8000000000000ull);
    CHECK(bits32((float)mh_x87_div(zero, zero)) == 0xFFC00000u);
    /* Division by zero is not invalid: signed infinities, as x87 with masked exceptions. */
    CHECK(bits64(mh_x87_div(one, zero)) == 0x7FF0000000000000ull);
    CHECK(bits64(mh_x87_div(-one, zero)) == 0xFFF0000000000000ull);
    CHECK(bits64(mh_x87_div(one, -zero)) == 0xFFF0000000000000ull);
    /* Ordinary values are untouched. */
    CHECK(mh_x87_mul(1.5, 3.0) == 4.5 && mh_x87_sub(1.0, 0.25) == 0.75 && mh_x87_add(2.0, 3.0) == 5.0 && mh_x87_div(9.0, 3.0) == 3.0);
    /* A NaN operand is propagated, not replaced by the indefinite. */
    {
        double payload = from64(0x7FF8000000001234ull);
        CHECK((bits64(mh_x87_add(payload, one)) & 0x000FFFFFFFFFFFFFull) == 0x0008000000001234ull);
        CHECK((bits64(mh_x87_mul(one, payload)) & 0x000FFFFFFFFFFFFFull) == 0x0008000000001234ull);
    }
    /* fsqrt */
    CHECK(mh_x87_sqrt(9.0) == 3.0 && bits64(mh_x87_sqrt(-zero)) == 0x8000000000000000ull);
    CHECK(bits64(mh_x87_sqrt(-one)) == 0xFFF8000000000000ull);
    CHECK(bits64(mh_x87_sqrt(-inf)) == 0xFFF8000000000000ull && mh_x87_sqrt(inf) == inf);
    /* fistp qword: rounding control and the integer indefinite */
    CHECK(mh_x87_to_i64(2.5, 0x037f) == 2 && mh_x87_to_i64(3.5, 0x037f) == 4 && mh_x87_to_i64(-2.5, 0x037f) == -2);
    CHECK(mh_x87_to_i64(2.7, 0x077f) == 2 && mh_x87_to_i64(-2.2, 0x077f) == -3);   /* down */
    CHECK(mh_x87_to_i64(2.2, 0x0b7f) == 3 && mh_x87_to_i64(-2.7, 0x0b7f) == -2);   /* up */
    CHECK(mh_x87_to_i64(2.7, 0x0f7f) == 2 && mh_x87_to_i64(-2.7, 0x0f7f) == -2);   /* chop */
    CHECK(mh_x87_to_i64(zero / zero, 0x037f) == INT64_MIN && mh_x87_to_i64(inf, 0x037f) == INT64_MIN);
    CHECK(mh_x87_to_i64(9.3e18, 0x037f) == INT64_MIN && mh_x87_to_i64(-9223372036854775808.0, 0x037f) == INT64_MIN);
    CHECK(mh_x87_to_i64(-9.2e18, 0x037f) == -9200000000000000000ll);
    CHECK(mh_x87_st0_to_i64((double)9007199254740993ll, 9007199254740993ll, 0x037f) == 9007199254740993ll);  /* shadow kept */
    CHECK(mh_x87_st0_to_i64(1.5, 7, 0x037f) == 2);
    /* fist word/dword */
    CHECK(mh_x87_to_i32(2.5, 0x037f) == 2 && mh_x87_to_i32(3e9, 0x037f) == INT32_MIN && mh_x87_to_i32(-2147483648.0, 0x037f) == INT32_MIN);
    CHECK(mh_x87_to_i32(zero / zero, 0x037f) == INT32_MIN && mh_x87_to_i32(-2147483647.6, 0x0f7f) == -2147483647);
    CHECK(mh_x87_to_i16(40000.0, 0x037f) == INT16_MIN && mh_x87_to_i16(-12.5, 0x037f) == -12 && mh_x87_to_i16(32767.0, 0x037f) == 32767);
    /* fchs, trig */
    CHECK(bits64(mh_x87_chs(zero)) == 0x8000000000000000ull && mh_x87_chs(-1.5) == 1.5);
    CHECK(bits64(mh_x87_sin(inf)) == 0xFFF8000000000000ull && bits64(mh_x87_cos(-inf)) == 0xFFF8000000000000ull);
    CHECK(bits64(mh_x87_tan(inf)) == 0xFFF8000000000000ull && mh_x87_sin(0.0) == 0.0 && mh_x87_cos(0.0) == 1.0);
    CHECK(mh_x87_atan2(0.0, 0.0) == 0.0 && mh_x87_atan2(1.0, 0.0) > 1.57);
    /* fprem */
    CHECK(mh_x87_fmod(7.0, 2.0) == 1.0 && bits64(mh_x87_fmod(1.0, zero)) == 0xFFF8000000000000ull && bits64(mh_x87_fmod(inf, 2.0)) == 0xFFF8000000000000ull);
    /* fyl2x / fyl2xp1 */
    CHECK(mh_x87_yl2x(3.0, 8.0) == 9.0 && bits64(mh_x87_yl2x(1.0, -1.0)) == 0xFFF8000000000000ull);
    CHECK(mh_x87_yl2x(2.0, zero) == -INFINITY && mh_x87_yl2x(-2.0, zero) == INFINITY && bits64(mh_x87_yl2x(zero, zero)) == 0xFFF8000000000000ull);
    CHECK(mh_x87_yl2xp1(1.0, 0.0) == 0.0 && bits64(mh_x87_yl2xp1(1.0, -2.0)) == 0xFFF8000000000000ull);
    /* f2xm1 / fscale */
    CHECK(mh_x87_f2xm1(1.0) == 1.0 && mh_x87_f2xm1(0.0) == 0.0 && mh_x87_f2xm1(-1.0) == -0.5);
    CHECK(mh_x87_scale(3.0, 2.9) == 12.0 && mh_x87_scale(3.0, -1.5) == 1.5 && mh_x87_scale(1.0, 1e9) == INFINITY && mh_x87_scale(1.0, -1e9) == 0.0);
    CHECK(mh_x87_scale(2.0, inf) == INFINITY && bits64(mh_x87_scale(zero, inf)) == 0xFFF8000000000000ull);
    /* 80-bit load/store */
    {
        uint8_t t[10];
        const double values[] = {1.0, -2.5, 3.141592653589793, 1e300, -1e-300, 0.0};
        for (unsigned i = 0; i < sizeof values / sizeof values[0]; i++) { mh_x87_st80(t, values[i]); CHECK(mh_x87_ld80(t) == values[i]); }
        mh_x87_st80(t, -zero); CHECK(bits64(mh_x87_ld80(t)) == 0x8000000000000000ull);
        mh_x87_st80(t, -inf); CHECK(t[9] == 0xFF && t[8] == 0xFF && mh_x87_ld80(t) == -inf);
        mh_x87_st80(t, mh_x87_indefinite()); CHECK(bits64(mh_x87_ld80(t)) == 0xFFF8000000000000ull);
        mh_x87_st80(t, from64(0x7FF8000000001234ull)); CHECK(bits64(mh_x87_ld80(t)) == 0x7FF8000000001234ull);
        const uint8_t pi80[10] = {0x35, 0xC2, 0x68, 0x21, 0xA2, 0xDA, 0x0F, 0xC9, 0x00, 0x40};   /* x87 fldpi image */
        CHECK(mh_x87_ld80(pi80) == 3.141592653589793);
    }
    printf("%u x87 semantic checks passed\n", checks);
    return 0;
}
#ifndef MH_X87_CHECKS_NO_MAIN
int main(void) { return mh_x87_semantic_checks(); }
#endif
