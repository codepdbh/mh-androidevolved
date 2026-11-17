#ifndef MH_X87_SEMANTICS_H
#define MH_X87_SEMANTICS_H

/* x87 arithmetic helpers for translated code running on non-x86 hosts.
 *
 * With invalid-operation exceptions masked (the default control word), x87
 * answers an invalid operation (0/0, inf/inf, inf-inf, 0*inf) with the
 * "real indefinite" QNaN: sign set, payload zero (0xFFF8000000000000 as a
 * double, 0xFFC00000 once stored as a float). AArch64 generates its default
 * NaN with the sign clear instead, so a plain C operator gives different bits
 * on Android than on x86. These helpers return the x87 value whenever a NaN is
 * produced from non-NaN operands. A NaN operand is left to the host's
 * propagation rules, which quiet it like x87 but may choose a different
 * operand when both are NaN.
 *
 * Arithmetic is still done in host double precision, not 80-bit extended, and
 * the precision-control field is not modelled. */
#include <math.h>
#include <stdint.h>
#include <string.h>

static inline double mh_x87_indefinite(void) {
    const uint64_t bits = 0xFFF8000000000000ull;
    double value;
    memcpy(&value, &bits, sizeof value);
    return value;
}
static inline double mh_x87_result(double result, double a, double b) {
    return (result != result && a == a && b == b) ? mh_x87_indefinite() : result;
}
static inline double mh_x87_add(double a, double b) { return mh_x87_result(a + b, a, b); }
static inline double mh_x87_sub(double a, double b) { return mh_x87_result(a - b, a, b); }
static inline double mh_x87_mul(double a, double b) { return mh_x87_result(a * b, a, b); }
static inline double mh_x87_div(double a, double b) { return mh_x87_result(a / b, a, b); }
/* fsqrt: a negative operand (not -0) is invalid and yields the indefinite. */
static inline double mh_x87_sqrt(double a) { return a < 0.0 ? mh_x87_indefinite() : sqrt(a); }
/* fistp qword: round by the control word's RC field (bits 10-11). NaN, infinities
 * and results outside int64 give the x87 "integer indefinite" 0x8000000000000000
 * (C's conversion would be undefined behaviour). */
static inline int64_t mh_x87_to_i64(double v, uint16_t cw) {
    double r;
    switch ((cw >> 10) & 3) {
    case 0: r = nearbyint(v); break;
    case 1: r = floor(v); break;
    case 2: r = ceil(v); break;
    default: r = trunc(v); break;
    }
    if (!(r >= -9223372036854775808.0 && r < 9223372036854775808.0)) return INT64_MIN;
    return (int64_t)r;
}
/* As PCRecomp's fp_st0_to_i64: while st(0) still holds the exact value an fild
 * loaded, store that integer (doubles cannot represent every int64). */
static inline int64_t mh_x87_st0_to_i64(double v0, int64_t shadow, uint16_t cw) {
    return v0 == (double)shadow ? shadow : mh_x87_to_i64(v0, cw);
}
#endif
