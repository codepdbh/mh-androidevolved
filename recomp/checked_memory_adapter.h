#ifndef MH_CHECKED_MEMORY_ADAPTER_H
#define MH_CHECKED_MEMORY_ADAPTER_H

/* Experimental adapter for a restricted subset of generated functions.
 * Include after recomp_types.h. It does not cover ADDR, inline helpers defined
 * before this header, atomics, or concurrent use. */
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include "guest_memory.h"

extern mh_guest_memory mh_recomp_region;
void mh_guest_fault(uint32_t address, size_t width);

/* The same check as mh_mem_span (runtime/guest_memory.c), inline: every guest load and store
 * goes through here, and an out-of-line call per access was most of the translated code's time. */
static inline void *mh_recomp_access(uint32_t address, size_t width) {
    const mh_guest_memory *m = &mh_recomp_region;
    size_t start = (size_t)((uint64_t)address - m->guest_base);
    if (!width || !m->bytes || address < m->guest_base || start > m->size || width > m->size - start) {
        mh_guest_fault(address, width);
        abort(); /* A fault handler must not return. */
    }
    return m->bytes + start;
}

/* Guest x86 allows unaligned loads. Packed members make that property visible
 * to the host compiler; this adapter targets little-endian Windows/Android. */
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error checked_memory_adapter requires a little-endian host
#endif
#if defined(__clang__) || defined(__GNUC__)
#define MH_ALIAS __attribute__((__may_alias__))
#else
#define MH_ALIAS
#endif
#pragma pack(push, 1)
typedef struct MH_ALIAS { uint16_t value; } mh_packed_u16;
typedef struct MH_ALIAS { uint32_t value; } mh_packed_u32;
typedef struct MH_ALIAS { uint64_t value; } mh_packed_u64;
typedef struct MH_ALIAS { float value; } mh_packed_float;
typedef struct MH_ALIAS { double value; } mh_packed_double;
#pragma pack(pop)
#undef MH_ALIAS

#undef MEM8
#undef MEM16
#undef MEM32
#undef MEM64
#undef MEMF
#undef MEMD
#undef POP32_VAL
/* Guest memory is not volatile: the guest runs on one host thread and every host call (imports,
 * dispatch) is an opaque call the compiler must reload around, so it may keep values in registers
 * between accesses. Define MH_RECOMP_VOLATILE_MEMORY to get the upstream volatile accesses back. */
#ifdef MH_RECOMP_VOLATILE_MEMORY
#define MH_RECOMP_V volatile
#else
#define MH_RECOMP_V
#endif
#define MEM8(a) (*(MH_RECOMP_V uint8_t *)mh_recomp_access((uint32_t)(a),1))
#define MEM16(a) (((MH_RECOMP_V mh_packed_u16 *)mh_recomp_access((uint32_t)(a),2))->value)
#define MEM32(a) (((MH_RECOMP_V mh_packed_u32 *)mh_recomp_access((uint32_t)(a),4))->value)
#define MEM64(a) (((MH_RECOMP_V mh_packed_u64 *)mh_recomp_access((uint32_t)(a),8))->value)
#define MEMF(a) (((MH_RECOMP_V mh_packed_float *)mh_recomp_access((uint32_t)(a),4))->value)
#define MEMD(a) (((MH_RECOMP_V mh_packed_double *)mh_recomp_access((uint32_t)(a),8))->value)
static inline uint32_t mh_recomp_pop32(uint32_t *sp) {
    uint32_t value=MEM32(*sp); *sp+=4; return value;
}
#define POP32_VAL(sp) mh_recomp_pop32(&(sp))

/* Checked replacement for recomp_rep_movs. Both whole ranges are validated
 * before any byte is written, so an out-of-range copy faults without the
 * partial progress real x86 would make. Overlap keeps x86 element order. */
static inline void mh_recomp_rep_movs(uint32_t edi, uint32_t esi, uint32_t n, uint32_t esz, int df) {
    uint64_t total = (uint64_t)n * esz;
    uint32_t b, dst_start, src_start;
    uint8_t *dst, *src;
    if (!n) return;
    if ((esz != 1 && esz != 2 && esz != 4) || total > UINT32_MAX) {
        mh_guest_fault(edi, (size_t)esz);
        abort();
    }
    b = (uint32_t)total;
    dst_start = df > 0 ? edi : edi - b + esz;
    src_start = df > 0 ? esi : esi - b + esz;
    if (df <= 0 && (edi + esz < b || esi + esz < b)) {
        mh_guest_fault(edi, (size_t)esz);
        abort();
    }
    dst = (uint8_t *)mh_recomp_access(dst_start, b);
    src = (uint8_t *)mh_recomp_access(src_start, b);
    if (df > 0 ? (uint32_t)(edi - esi) >= b : (uint32_t)(esi - edi) >= b) {
        memmove(dst, src, b);
        return;
    }
    for (uint32_t i = 0; i < n; i++) {
        uint32_t k = df > 0 ? i * esz : b - (i + 1) * esz;
        memcpy(dst + k, src + k, esz);
    }
}

/* Checked replacement for PCRecomp's inline `rep stos` (memset on ADDR). Stores
 * the low esz bytes of value n times; the whole range is validated first, so
 * an invalid range faults without partial progress. Does not update EDI/ECX. */
static inline void mh_recomp_rep_stos(uint32_t edi, uint32_t value, uint32_t n, uint32_t esz, int df) {
    uint64_t total = (uint64_t)n * esz;
    uint32_t b, start;
    uint8_t *dst, pattern[4];
    if (!n) return;
    if ((esz != 1 && esz != 2 && esz != 4) || total > UINT32_MAX || (df <= 0 && edi + esz < (uint32_t)total)) {
        mh_guest_fault(edi, (size_t)esz);
        abort();
    }
    b = (uint32_t)total;
    start = df > 0 ? edi : edi - b + esz;
    dst = (uint8_t *)mh_recomp_access(start, b);
    pattern[0] = (uint8_t)value; pattern[1] = (uint8_t)(value >> 8);
    pattern[2] = (uint8_t)(value >> 16); pattern[3] = (uint8_t)(value >> 24);
    if (esz == 1) { memset(dst, pattern[0], b); return; }
    for (uint32_t k = 0; k < b; k += esz) memcpy(dst + k, pattern, esz);
}
#endif
