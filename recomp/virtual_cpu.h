#ifndef MH_VIRTUAL_CPU_H
#define MH_VIRTUAL_CPU_H
/* Fixed virtual x86 CPU reported to translated code by CPUID.
 *
 * PCRecomp's CPUID asks the host CPU under MSVC (results differ per PC) and
 * does nothing elsewhere (on Android the registers keep stale values). The
 * port instead answers every CPUID with one documented, deterministic CPU,
 * identical on Windows, Android and in the Unicorn x86 references:
 *   leaf 0:          max basic leaf 1, vendor "GenuineIntel";
 *   leaf 1:          family 6 / model 7 / stepping 3 (0x673), features FPU only;
 *   leaf 0x80000000: no extended leaves;
 *   any other leaf:  all zero.
 * Announcing no MMX, CMOV, SSE, SSE2 or 3DNow! makes the game pick its plain
 * x87/integer paths, which the auditable translation supports.
 * Include after recomp_types.h (uses the global guest registers). */
#include <stdint.h>

#define MH_VCPU_VENDOR_EBX 0x756e6547u /* "Genu" */
#define MH_VCPU_VENDOR_EDX 0x49656e69u /* "ineI" */
#define MH_VCPU_VENDOR_ECX 0x6c65746eu /* "ntel" */
#define MH_VCPU_SIGNATURE  0x00000673u
#define MH_VCPU_FEATURES   0x00000001u /* FPU */

static inline void mh_virtual_cpuid(void) {
    uint32_t leaf = g_eax;
    g_eax = g_ebx = g_ecx = g_edx = 0;
    if (leaf == 0) { g_eax = 1; g_ebx = MH_VCPU_VENDOR_EBX; g_edx = MH_VCPU_VENDOR_EDX; g_ecx = MH_VCPU_VENDOR_ECX; }
    else if (leaf == 1) { g_eax = MH_VCPU_SIGNATURE; g_edx = MH_VCPU_FEATURES; }
    else if (leaf == 0x80000000u) { g_eax = 0x80000000u; }
}
#define MH_VIRTUAL_CPUID() do { RECOMP_REGS_OUT(); mh_virtual_cpuid(); RECOMP_REGS_IN(); } while (0)
#endif
