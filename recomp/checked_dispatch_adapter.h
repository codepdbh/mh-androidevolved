#ifndef MH_CHECKED_DISPATCH_ADAPTER_H
#define MH_CHECKED_DISPATCH_ADAPTER_H

/* Include after recomp_types.h and checked_memory_adapter.h. A missing target
 * is a runtime fault: never invent a return value or continue execution. */
#include <stdint.h>
#include <stdlib.h>
void mh_dispatch_fault(uint32_t target, uint32_t caller);

/* For audited call sites whose original next instruction is known. */
#define MH_RECOMP_CALL_AT(func, return_va) do { \
    uint32_t mh_caller_ = g_cur_func; \
    PUSH32(esp, (uint32_t)(return_va)); \
    RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT(); \
    (func)(); \
    RECOMP_REGS_IN(); g_cur_func = mh_caller_; \
} while (0)

#define MH_RECOMP_ICALL_AT(target_va, return_va) do { \
    uint32_t mh_target_ = (uint32_t)(target_va); \
    RECOMP_ICALL_TRACE(mh_target_); \
    recomp_func_t mh_fn_ = RECOMP_RESOLVE_SITE(mh_target_); \
    if (!mh_fn_) { mh_dispatch_fault(mh_target_, g_cur_func); abort(); } \
    uint32_t mh_caller_ = g_cur_func; \
    PUSH32(esp, (uint32_t)(return_va)); \
    RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT(); \
    mh_fn_(); \
    RECOMP_REGS_IN(); g_cur_func = mh_caller_; \
} while (0)

/* Audited `jmp dword ptr [slot]` (an import thunk): a tail jump with the caller's
 * return address still on the stack; the callee returns for this function. */
#define MH_RECOMP_IJMP_AT(target_va) do { \
    uint32_t mh_target_ = (uint32_t)(target_va); \
    RECOMP_ICALL_TRACE(mh_target_); \
    recomp_func_t mh_fn_ = RECOMP_RESOLVE_SITE(mh_target_); \
    if (!mh_fn_) { mh_dispatch_fault(mh_target_, g_cur_func); abort(); } \
    RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT(); \
    mh_fn_(); \
} while (0)

#undef RECOMP_ICALL
#define RECOMP_ICALL(target_va) do { \
    uint32_t mh_target_ = (uint32_t)(target_va); \
    RECOMP_ICALL_TRACE(mh_target_); \
    recomp_func_t mh_fn_ = RECOMP_RESOLVE_SITE(mh_target_); \
    if (!mh_fn_) { mh_dispatch_fault(mh_target_, g_cur_func); abort(); } \
    uint32_t mh_caller_ = g_cur_func; \
    PUSH32(esp, RECOMP_RETADDR); \
    RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT(); \
    mh_fn_(); \
    RECOMP_REGS_IN(); g_cur_func = mh_caller_; \
} while (0)

#undef RECOMP_ITAIL
#define RECOMP_ITAIL(target_va) do { \
    uint32_t mh_target_ = (uint32_t)(target_va); \
    RECOMP_ICALL_TRACE(mh_target_); \
    recomp_func_t mh_fn_ = RECOMP_RESOLVE_SITE(mh_target_); \
    if (mh_fn_) { RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT(); RECOMP_TAIL_CALL(mh_fn_); } \
    else if (mh_target_ != RECOMP_RETADDR) { mh_dispatch_fault(mh_target_, g_cur_func); abort(); } \
} while (0)
#endif
