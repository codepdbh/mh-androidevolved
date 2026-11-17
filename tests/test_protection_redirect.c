/* Synthetic checks for runtime/win32_thread.c and runtime/protection_redirect.c; no game code. */
#include <stdio.h>
#include "guest_memory.h"
#include "win32_thread.h"
#include "protection_redirect.h"
#define CHECK(c) do { if (!(c)) { printf("failed: %s (line %d)\n", #c, __LINE__); return 1; } checks++; } while (0)
static uint8_t header[0x1000];
int main(void) {
    unsigned checks = 0;
    /* Thread state */
    mh_win32_thread t; mh_win32_thread_init(&t);
    CHECK(mh_win32_get_last_error(&t) == 0);
    CHECK(mh_win32_tls_get_value(&t, 0) == 0 && mh_win32_get_last_error(&t) == MH_ERROR_INVALID_PARAMETER);
    CHECK(mh_win32_tls_alloc(&t) == 0 && mh_win32_tls_alloc(&t) == 1);
    mh_win32_set_last_error(&t, 5);
    CHECK(mh_win32_tls_get_value(&t, 1) == 0 && mh_win32_get_last_error(&t) == MH_ERROR_SUCCESS); /* stored 0 vs failure */
    CHECK(mh_win32_tls_set_value(&t, 1, 0x1234) && mh_win32_tls_get_value(&t, 1) == 0x1234);
    CHECK(!mh_win32_tls_set_value(&t, 2, 1) && mh_win32_get_last_error(&t) == MH_ERROR_INVALID_PARAMETER);
    CHECK(mh_win32_tls_free(&t, 0) && !mh_win32_tls_free(&t, 0));
    CHECK(mh_win32_tls_alloc(&t) == 0 && mh_win32_tls_get_value(&t, 0) == 0);                    /* reused slot reads 0 */
    CHECK(!mh_win32_tls_set_value(&t, MH_TLS_SLOTS, 1) && !mh_win32_tls_free(&t, 0xffffffffu));
    for (unsigned i = 2; i < MH_TLS_SLOTS; i++) CHECK(mh_win32_tls_alloc(&t) == i);
    CHECK(mh_win32_tls_alloc(&t) == MH_TLS_OUT_OF_INDEXES);
    /* Header table, laid out like the stub expects: pairs below 0x40087c, zero terminator. */
    mh_guest_memory image;
    CHECK(mh_mem_init(&image, header, sizeof header, 0x400000));
    mh_mem_write_u32(&image, 0x40087c, 0x401234); mh_mem_write_u32(&image, 0x400878, 0x81b000);
    mh_mem_write_u32(&image, 0x400874, 0x405678); mh_mem_write_u32(&image, 0x400870, 0x81b004);
    mh_mem_write_u32(&image, 0x40086c, 0);
    mh_mem_write_u32(&image, 0x400864, 0x409999);                                                 /* beyond terminator */
    uint32_t slot = 0;
    CHECK(mh_header_redirect_slot(&image, 0x401234, &slot) && slot == 0x81b000);
    CHECK(mh_header_redirect_slot(&image, 0x405678, &slot) && slot == 0x81b004);
    CHECK(!mh_header_redirect_slot(&image, 0x409999, &slot));
    CHECK(!mh_header_redirect_slot(&image, 0, &slot));
    for (uint32_t a = 0x400100; a <= 0x40087c; a += 4) mh_mem_write_u32(&image, a, 0x11111111);  /* no terminator */
    CHECK(!mh_header_redirect_slot(&image, 0x22222222, &slot));                                  /* bounded walk */
    /* Site table */
    static const mh_redirect_site sites[] = {{0x401000, MH_REDIRECT_TRIGGER}, {0x500000, MH_REDIRECT_GET_LAST_ERROR},
                                             {0x600000, MH_REDIRECT_VALIDATE_POINTER}};
    CHECK(mh_redirect_find(sites, 3, 0x500000)->kind == MH_REDIRECT_GET_LAST_ERROR);
    CHECK(mh_redirect_find(sites, 3, 0x401000)->kind == MH_REDIRECT_TRIGGER);
    CHECK(mh_redirect_find(sites, 3, 0x600000)->kind == MH_REDIRECT_VALIDATE_POINTER);
    CHECK(!mh_redirect_find(sites, 3, 0x500001) && !mh_redirect_find(sites, 0, 0x500000));
    /* Pointer validation */
    CHECK(mh_redirect_validate_pointer(&image, 0x400ff8, 8) == 0);
    CHECK(mh_redirect_validate_pointer(&image, 0x400ffc, 8) == 1);
    CHECK(mh_redirect_validate_pointer(&image, 0x10, 1) == 1);
    CHECK(mh_redirect_validate_pointer(&image, 0x10, 0) == 0);
    printf("%u thread-state and protection-redirect checks passed\n", checks);
    return 0;
}
