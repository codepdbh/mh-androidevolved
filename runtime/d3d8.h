#ifndef MH_D3D8_H
#define MH_D3D8_H
/* Direct3D 8 for translated code: COM objects in guest memory.
 *
 * Each object is a guest structure whose first dword points to a guest vtable;
 * every vtable entry is a fake guest address (MH_D3D8_VA + 0x400*interface +
 * 4*method) that the harness/runtime dispatch maps to mh_d3d8_call(). Methods
 * follow the stdcall COM convention: arguments are read from the guest stack
 * (this pointer first) and the callee pops them.
 *
 * The adapter is a virtual "Android OpenGL ES" display with a fixed list of
 * modes; rendering is not implemented yet. Unimplemented methods return
 * MH_D3D8_UNIMPLEMENTED so the caller can stop with the method's name instead
 * of continuing with an invented result. */
#include <stdint.h>
#include "guest_memory.h"

#define MH_D3D8_VA            0x1e10000u
#define MH_D3D8_IFACE_D3D8    0u
#define MH_D3D8_METHODS       16u
#define MH_COM_IFACE_STRIDE   0x400u  /* up to 256 methods per interface (IDirect3DDevice8 has 97) */
#define MH_D3D_SDK_VERSION    220u

#define MH_D3D_OK             0x00000000u
#define MH_E_NOINTERFACE      0x80004002u
#define MH_D3DERR_INVALIDCALL 0x8876086cu
#define MH_D3DERR_NOTAVAILABLE 0x8876086au
#define MH_D3DFMT_R8G8B8      20u
#define MH_D3DFMT_X8R8G8B8    22u
#define MH_D3DFMT_R5G6B5      23u
#define MH_D3DDEVTYPE_HAL     1u

typedef struct {
    mh_guest_memory *memory;
    uint32_t heap_next, heap_limit;   /* guest region for COM objects */
    uint32_t vtable;                  /* guest address of the IDirect3D8 vtable */
} mh_d3d8;

enum { MH_D3D8_DONE = 0, MH_D3D8_UNIMPLEMENTED = 1, MH_D3D8_BAD_CALL = 2 };

/* Prepares the context and writes the IDirect3D8 vtable into [heap_base, heap_base+heap_size). */
int mh_d3d8_init(mh_d3d8 *d3d, mh_guest_memory *memory, uint32_t heap_base, uint32_t heap_size);
/* Direct3DCreate8(SDKVersion): returns the guest object, or 0 (version mismatch / no memory). */
uint32_t mh_d3d8_create(mh_d3d8 *d3d, uint32_t sdk_version);
/* Executes the method behind fake address `va` with the guest stack at `esp` (pointing at the
 * return address). On MH_D3D8_DONE stores the result in *eax and the bytes the callee pops
 * (return address included) in *pop. `name` receives the method name for diagnostics. */
int mh_d3d8_call(mh_d3d8 *d3d, uint32_t va, uint32_t esp, uint32_t *eax, uint32_t *pop, const char **name);
/* Fixed mode list of the virtual adapter (for tests and documentation). */
unsigned mh_d3d8_mode_count(void);
#endif
