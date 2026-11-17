/* Synthetic checks for runtime/d3d8.c (IDirect3D8 subset); no game code. */
#include <stdio.h>
#include <string.h>
#include "guest_memory.h"
#include "d3d8.h"
#define CHECK(c) do { if (!(c)) { printf("failed: %s (line %d)\n", #c, __LINE__); return 1; } checks++; } while (0)
static uint8_t bytes[0x10000];
static mh_guest_memory m;
static mh_d3d8 d3d;
/* Builds a stdcall frame at esp (return address, then arguments) and invokes method `index`. */
static int call(uint32_t object, unsigned index, const uint32_t *args, unsigned n, uint32_t *eax, uint32_t *pop) {
    const uint32_t esp = 0x1f000;
    const char *name = 0;
    mh_mem_write_u32(&m, esp, 0x1234);
    mh_mem_write_u32(&m, esp + 4, object);
    for (unsigned i = 0; i < n; i++) mh_mem_write_u32(&m, esp + 8 + 4 * i, args[i]);
    uint32_t vtable = 0, va = 0;
    mh_mem_read_u32(&m, object, &vtable);
    mh_mem_read_u32(&m, vtable + 4 * index, &va);
    return mh_d3d8_call(&d3d, va, esp, eax, pop, &name);
}
int main(void) {
    unsigned checks = 0;
    uint32_t eax = 0, pop = 0, v = 0;
    CHECK(mh_mem_init(&m, bytes, sizeof bytes, 0x10000));
    CHECK(mh_d3d8_init(&d3d, &m, 0x18000, 0x1000));
    CHECK(mh_d3d8_create(&d3d, 120) == 0);                                   /* SDK version mismatch */
    uint32_t object = mh_d3d8_create(&d3d, MH_D3D_SDK_VERSION);
    CHECK(object != 0);
    CHECK(call(object, 4, 0, 0, &eax, &pop) == MH_D3D8_DONE && eax == 1 && pop == 8);           /* GetAdapterCount */
    uint32_t a0[] = {0}, a1[] = {1};
    CHECK(call(object, 6, a0, 1, &eax, &pop) == MH_D3D8_DONE && eax == mh_d3d8_mode_count() && pop == 12);
    CHECK(call(object, 6, a1, 1, &eax, &pop) == MH_D3D8_DONE && eax == 0);                       /* no second adapter */
    uint32_t e0[] = {0, 0, 0x19000}, e_last[] = {0, 11, 0x19000}, e_bad[] = {0, 12, 0x19000}, e_null[] = {0, 0, 0};
    CHECK(call(object, 7, e0, 3, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3D_OK && pop == 20); /* ret 0x10 + return address */
    CHECK(mh_mem_read_u32(&m, 0x19000, &v) && v == 640 && mh_mem_read_u32(&m, 0x19008, &v) && v == 60 &&
          mh_mem_read_u32(&m, 0x1900c, &v) && v == MH_D3DFMT_X8R8G8B8);
    CHECK(call(object, 7, e_last, 3, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3D_OK);
    CHECK(mh_mem_read_u32(&m, 0x19000, &v) && v == 1920 && mh_mem_read_u32(&m, 0x1900c, &v) && v == MH_D3DFMT_R5G6B5);
    CHECK(call(object, 7, e_bad, 3, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3DERR_INVALIDCALL);
    CHECK(call(object, 7, e_null, 3, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3DERR_INVALIDCALL);
    uint32_t dm[] = {0, 0x19010};
    CHECK(call(object, 8, dm, 2, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3D_OK && mh_mem_read_u32(&m, 0x19010, &v) && v == 1280);
    uint32_t ok[] = {0, MH_D3DDEVTYPE_HAL, MH_D3DFMT_X8R8G8B8, MH_D3DFMT_X8R8G8B8, 0},
             ref[] = {0, 2, MH_D3DFMT_X8R8G8B8, MH_D3DFMT_X8R8G8B8, 0},
             r8g8b8[] = {0, MH_D3DDEVTYPE_HAL, MH_D3DFMT_R8G8B8, MH_D3DFMT_R8G8B8, 0};
    CHECK(call(object, 9, ok, 5, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3D_OK && pop == 28);
    CHECK(call(object, 9, ref, 5, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3DERR_NOTAVAILABLE);
    CHECK(call(object, 9, r8g8b8, 5, &eax, &pop) == MH_D3D8_DONE && eax == MH_D3DERR_NOTAVAILABLE);
    CHECK(call(object, 1, 0, 0, &eax, &pop) == MH_D3D8_DONE && eax == 2);                        /* AddRef */
    CHECK(call(object, 2, 0, 0, &eax, &pop) == MH_D3D8_DONE && eax == 1);                        /* Release */
    CHECK(call(object, 2, 0, 0, &eax, &pop) == MH_D3D8_DONE && eax == 0);
    uint32_t caps[] = {0, 1, 0x19100};
    CHECK(call(object, 13, caps, 3, &eax, &pop) == MH_D3D8_UNIMPLEMENTED);                       /* GetDeviceCaps: not yet */
    CHECK(mh_d3d8_call(&d3d, MH_D3D8_VA + 0x400, 0x1f000, &eax, &pop, 0) == MH_D3D8_BAD_CALL);   /* unknown interface */
    mh_mem_write_u32(&m, 0x1f004, 0x19000);                                                      /* `this` is not an object */
    CHECK(mh_d3d8_call(&d3d, MH_D3D8_VA + 4 * 4, 0x1f000, &eax, &pop, 0) == MH_D3D8_BAD_CALL);
    printf("%u Direct3D 8 shim checks passed\n", checks);
    return 0;
}
