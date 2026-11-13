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
#endif
