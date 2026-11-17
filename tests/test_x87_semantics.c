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
    printf("%u x87 semantic checks passed\n", checks);
    return 0;
}
#ifndef MH_X87_CHECKS_NO_MAIN
int main(void) { return mh_x87_semantic_checks(); }
#endif
