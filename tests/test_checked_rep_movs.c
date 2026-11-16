/* Synthetic checks for mh_recomp_rep_movs against an element-by-element model. */
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "checked_memory_adapter.h"

mh_guest_memory mh_recomp_region;
static jmp_buf fault_jump;
static uint32_t fault_address;
void mh_guest_fault(uint32_t address, size_t width) { (void)width; fault_address = address; longjmp(fault_jump, 1); }

#define BASE 0x1000u
#define SIZE 256u
static uint8_t guest[SIZE], model[SIZE];

/* x86 semantics: one element at a time, reading after earlier writes. */
static void model_movs(uint32_t edi, uint32_t esi, uint32_t n, uint32_t esz, int df) {
    for (uint32_t i = 0; i < n; i++) {
        memcpy(model + (edi - BASE), model + (esi - BASE), esz);
        edi += (uint32_t)(df * (int)esz); esi += (uint32_t)(df * (int)esz);
    }
}
static void fill(void) { for (unsigned i = 0; i < SIZE; i++) guest[i] = model[i] = (uint8_t)(i * 37 + 5); }

int main(void) {
    const uint32_t sizes[] = {1, 2, 4};
    unsigned cases = 0, faults = 0;
    if (!mh_mem_init(&mh_recomp_region, guest, SIZE, BASE)) return 10;
    for (unsigned s = 0; s < 3; s++) for (int df = -1; df <= 1; df += 2)
    for (uint32_t n = 0; n <= 20; n++) for (uint32_t d = 0; d < 48; d += 3) for (uint32_t r = 0; r < 48; r += 5) {
        uint32_t esz = sizes[s], b = n * esz;
        uint32_t edi = df > 0 ? BASE + 64 + d : BASE + 64 + d + b - esz;
        uint32_t esi = df > 0 ? BASE + 64 + r : BASE + 64 + r + b - esz;
        if (!n) { edi = BASE + 64 + d; esi = BASE + 64 + r; }
        fill();
        mh_recomp_rep_movs(edi, esi, n, esz, df);
        model_movs(edi, esi, n, esz, df);
        if (memcmp(guest, model, SIZE)) { printf("mismatch esz=%u df=%d n=%u d=%u r=%u\n", esz, df, n, d, r); return 11; }
        cases++;
    }
    /* Out-of-range destination, source and backward underflow must fault before writing. */
    const struct { uint32_t edi, esi, n, esz; int df; uint32_t at; } bad[] = {
        {BASE + SIZE - 4, BASE, 8, 1, 1, BASE + SIZE - 4},
        {BASE, BASE + SIZE - 2, 1, 4, 1, BASE + SIZE - 2},
        {BASE + 2, BASE + 100, 4, 1, -1, BASE + 2},
        {0x10, BASE, 4, 4, 1, 0x10},
    };
    for (unsigned i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        fill();
        if (setjmp(fault_jump) == 0) { mh_recomp_rep_movs(bad[i].edi, bad[i].esi, bad[i].n, bad[i].esz, bad[i].df); return 12; }
        if (memcmp(guest, model, SIZE)) return 13;
        if (bad[i].df > 0 && fault_address != bad[i].at && i != 1) return 14;
        faults++;
    }
    /* rep stos against an element-by-element model, both directions and widths. */
    unsigned stos = 0;
    for (unsigned s = 0; s < 3; s++) for (int df = -1; df <= 1; df += 2)
    for (uint32_t n = 0; n <= 20; n++) for (uint32_t d = 0; d < 48; d += 3) {
        uint32_t esz = sizes[s], value = 0xA1B2C3D4u ^ (n * 0x01010101u);
        uint32_t edi = BASE + 64 + d + (df < 0 && n ? n * esz - esz : 0), at = edi;
        fill();
        mh_recomp_rep_stos(edi, value, n, esz, df);
        for (uint32_t i = 0; i < n; i++) {
            for (uint32_t j = 0; j < esz; j++) model[at - BASE + j] = (uint8_t)(value >> (8 * j));
            at += (uint32_t)(df * (int)esz);
        }
        if (memcmp(guest, model, SIZE)) { printf("stos mismatch esz=%u df=%d n=%u d=%u\n", esz, df, n, d); return 15; }
        stos++;
    }
    fill();
    if (setjmp(fault_jump) == 0) { mh_recomp_rep_stos(BASE + SIZE - 3, 0, 1, 4, 1); return 16; }
    if (memcmp(guest, model, SIZE) || fault_address != BASE + SIZE - 3) return 17;
    printf("%u rep movs cases match; %u out-of-range copies rejected without writes; %u rep stos cases match\n", cases, faults, stos);
    return 0;
}
