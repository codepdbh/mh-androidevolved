#ifndef MH_X86_SEMANTICS_H
#define MH_X86_SEMANTICS_H
/* Integer instructions PCRecomp leaves unimplemented, for the audited rewrites of
 * tools/recomp_lift.py. Pure functions of their arguments. */
#include <stdint.h>

/* daa, as QEMU implements it (the reference emulator): CF/AF in from the current flags;
 * AF and CF out from the two adjustment steps, ZF/PF/SF from the result, OF cleared.
 * Returns the new EFLAGS word (the bits above the arithmetic flags kept from `eflags`). */
static inline uint32_t mh_x86_daa(uint32_t *eax, uint32_t eflags) {
    uint32_t al = *eax & 0xffu, old_al = al, cf = eflags & 1u, af = eflags & 0x10u, out = 0;
    if ((al & 0x0f) > 9 || af) { al = (al + 6) & 0xffu; out |= 0x10u; }
    if (old_al > 0x99 || cf) { al = (al + 0x60) & 0xffu; out |= 1u; }
    *eax = (*eax & ~0xffu) | al;
    uint32_t p = al; p ^= p >> 4; p ^= p >> 2; p ^= p >> 1;
    out |= (al == 0 ? 0x40u : 0) | ((~p & 1u) << 2) | (al & 0x80u);
    return (eflags & ~0x8d5u) | out;
}

/* fbld: 80-bit packed BCD (bytes 0-8: 18 digits, two per byte, least significant first;
 * byte 9 bit 7: sign) to the double stack. */
static inline double mh_x87_bld(const uint8_t *p) {
    double v = 0.0;
    for (int i = 8; i >= 0; i--) v = v * 100.0 + (double)((p[i] >> 4) * 10 + (p[i] & 0x0f));
    return (p[9] & 0x80) ? -v : v;
}
#endif
