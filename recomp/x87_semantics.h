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
/* Precision control (control word bits 8-9) for FADD/FSUB/FMUL/FDIV/FSQRT and their integer and
 * popping forms: 00 rounds the significand to 24 bits (keeping x87's wide exponent range, unlike a
 * float conversion), 10 to 53 bits (double, the model's own precision), 11 is extended (modelled
 * as double). Rounding is to nearest even, the x87 default (RC 00). Transcendental instructions
 * are not affected by precision control. */
static inline double mh_x87_round_pc(double r, uint16_t cw) {
    if (((cw >> 8) & 3) != 0 || r == 0.0 || r != r || isinf(r)) return r;
    int e; double m = frexp(r, &e);                 /* r = m * 2^e, 0.5 <= |m| < 1 */
    return ldexp(nearbyint(ldexp(m, 24)), e - 24);
}
static inline double mh_x87_add_pc(double a, double b, uint16_t cw) { return mh_x87_round_pc(mh_x87_add(a, b), cw); }
static inline double mh_x87_sub_pc(double a, double b, uint16_t cw) { return mh_x87_round_pc(mh_x87_sub(a, b), cw); }
static inline double mh_x87_mul_pc(double a, double b, uint16_t cw) { return mh_x87_round_pc(mh_x87_mul(a, b), cw); }
static inline double mh_x87_div_pc(double a, double b, uint16_t cw) { return mh_x87_round_pc(mh_x87_div(a, b), cw); }
/* fsqrt: a negative operand (not -0) is invalid and yields the indefinite. */
static inline double mh_x87_sqrt(double a) { return a < 0.0 ? mh_x87_indefinite() : sqrt(a); }
static inline double mh_x87_sqrt_pc(double a, uint16_t cw) { return mh_x87_round_pc(mh_x87_sqrt(a), cw); }
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
/* fist/fistp word and dword: as mh_x87_to_i64, with the 16/32-bit integer indefinite. */
static inline int32_t mh_x87_to_i32(double v, uint16_t cw) {
    int64_t r = mh_x87_to_i64(v, cw);
    return (r == INT64_MIN || r < INT32_MIN || r > INT32_MAX) ? INT32_MIN : (int32_t)r;
}
static inline int16_t mh_x87_to_i16(double v, uint16_t cw) {
    int64_t r = mh_x87_to_i64(v, cw);
    return (r == INT64_MIN || r < INT16_MIN || r > INT16_MAX) ? INT16_MIN : (int16_t)r;
}
/* fchs: exact sign flip (also of NaNs and zeros). */
static inline double mh_x87_chs(double a) { return -a; }
/* fsin/fcos/fptan: infinities are invalid (indefinite). The host reduces any finite argument,
 * so |x| >= 2^63 (which x87 leaves unchanged with C2 set) is the one case that differs. */
static inline double mh_x87_sin(double a) { return isinf(a) ? mh_x87_indefinite() : sin(a); }
static inline double mh_x87_cos(double a) { return isinf(a) ? mh_x87_indefinite() : cos(a); }
static inline double mh_x87_tan(double a) { return isinf(a) ? mh_x87_indefinite() : tan(a); }
/* fpatan: atan2 never produces a NaN from non-NaN operands, as x87. */
static inline double mh_x87_atan2(double y, double x) { return atan2(y, x); }
/* fprem/fprem1 (as one complete reduction): a zero divisor or infinite dividend is invalid. */
static inline double mh_x87_fmod(double a, double b) { return mh_x87_result(fmod(a, b), a, b); }
/* fyl2x: st(1) * log2(st(0)). Negative x or 0*log2(0) is invalid; y*log2(0) with y != 0 is
 * a signed infinity (division-by-zero, masked). */
static inline double mh_x87_yl2x(double y, double x) {
    if (x != x || y != y) return x + y;
    if (x < 0.0 || (x == 0.0 && y == 0.0)) return mh_x87_indefinite();
    return mh_x87_result(y * log2(x), y, x);
}
/* fyl2xp1: st(1) * log2(st(0) + 1), defined for |x| < 1 - sqrt(2)/2 on x87. */
static inline double mh_x87_yl2xp1(double y, double x) {
    if (x != x || y != y) return x + y;
    if (x <= -1.0) return mh_x87_indefinite();
    return mh_x87_result(y * (log1p(x) / 0.6931471805599453), y, x);
}
/* f2xm1: 2^x - 1 (x87 defines it for |x| <= 1; expm1 keeps the precision near 0). */
static inline double mh_x87_f2xm1(double a) { return mh_x87_result(expm1(a * 0.6931471805599453), a, a); }
/* fscale: st(0) * 2^trunc(st(1)), without C's undefined (int) conversion. */
static inline double mh_x87_scale(double a, double b) {
    if (a != a || b != b) return a + b;
    if (isinf(b)) return mh_x87_result(b > 0 ? a * INFINITY : a * 0.0, a, b);
    double t = trunc(b);
    if (t > 100000.0) t = 100000.0;
    if (t < -100000.0) t = -100000.0;
    return ldexp(a, (int)t);
}
/* fld/fstp tbyte (80-bit extended) on the double stack: a load rounds to double (to nearest),
 * a store widens exactly. NaNs keep their sign and the top fraction bits (x87 quiets them on
 * load, as here); infinities and zeros keep their sign. */
static inline double mh_x87_ld80(const uint8_t *p) {
    uint64_t m, bits; uint16_t se; double v;
    memcpy(&m, p, 8); memcpy(&se, p + 8, 2);
    int e = se & 0x7FFF, neg = se >> 15;
    if (e == 0x7FFF) {
        if ((m << 1) == 0) bits = 0x7FF0000000000000ull;                                  /* infinity */
        else bits = 0x7FF8000000000000ull | ((m << 1) >> 12);                               /* quiet NaN, payload kept */
        bits |= (uint64_t)neg << 63; memcpy(&v, &bits, 8); return v;
    }
    v = ldexp((double)m, (e ? e : 1) - 16383 - 63);
    return neg ? -v : v;
}
static inline void mh_x87_st80(uint8_t *p, double v) {
    uint64_t bits, m = 0; uint16_t se;
    memcpy(&bits, &v, 8);
    se = (uint16_t)((bits >> 63) << 15);
    uint64_t frac = bits & 0x000FFFFFFFFFFFFFull; int e = (int)((bits >> 52) & 0x7FF);
    if (e == 0x7FF) { se |= 0x7FFF; m = 0x8000000000000000ull | (frac << 11); }             /* inf / NaN with payload */
    else if (e != 0 || frac != 0) {
        int ex; double f = frexp(fabs(v), &ex);                                               /* f in [0.5, 1) */
        m = (uint64_t)ldexp(f, 64); se |= (uint16_t)(ex - 1 + 16383);
    }
    memcpy(p, &m, 8); memcpy(p + 8, &se, 2);
}
/* As PCRecomp's fp_st0_to_i64: while st(0) still holds the exact value an fild
 * loaded, store that integer (doubles cannot represent every int64). */
static inline int64_t mh_x87_st0_to_i64(double v0, int64_t shadow, uint16_t cw) {
    return v0 == (double)shadow ? shadow : mh_x87_to_i64(v0, cw);
}
#endif
