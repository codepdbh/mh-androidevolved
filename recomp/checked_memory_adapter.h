#ifndef MH_CHECKED_MEMORY_ADAPTER_H
#define MH_CHECKED_MEMORY_ADAPTER_H

/* Experimental adapter for a restricted subset of generated functions.
 * Include after recomp_types.h. It does not cover ADDR, inline helpers defined
 * before this header, atomics, or concurrent use. */
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include "guest_memory.h"

extern mh_guest_memory mh_recomp_region;
void mh_guest_fault(uint32_t address, size_t width);

static inline void *mh_recomp_access(uint32_t address, size_t width) {
    uint8_t *p = mh_mem_span(&mh_recomp_region, address, width);
    if (!p) {
        mh_guest_fault(address, width);
        abort(); /* A fault handler must not return. */
    }
    return p;
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
#define MEM8(a) (*(volatile uint8_t *)mh_recomp_access((uint32_t)(a),1))
#define MEM16(a) (((volatile mh_packed_u16 *)mh_recomp_access((uint32_t)(a),2))->value)
#define MEM32(a) (((volatile mh_packed_u32 *)mh_recomp_access((uint32_t)(a),4))->value)
#define MEM64(a) (((volatile mh_packed_u64 *)mh_recomp_access((uint32_t)(a),8))->value)
#define MEMF(a) (((volatile mh_packed_float *)mh_recomp_access((uint32_t)(a),4))->value)
#define MEMD(a) (((volatile mh_packed_double *)mh_recomp_access((uint32_t)(a),8))->value)
static inline uint32_t mh_recomp_pop32(uint32_t *sp) {
    uint32_t value=MEM32(*sp); *sp+=4; return value;
}
#define POP32_VAL(sp) mh_recomp_pop32(&(sp))
#endif
