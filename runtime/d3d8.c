#include "d3d8.h"
#include <string.h>

/* Virtual adapter: common 4:3 and 16:9 sizes, two back-buffer formats, 60 Hz. */
static const struct { uint32_t width, height; } sizes[] = {
    {640, 480}, {800, 600}, {1024, 768}, {1280, 720}, {1280, 960}, {1920, 1080}};
static const uint32_t formats[] = {MH_D3DFMT_X8R8G8B8, MH_D3DFMT_R5G6B5};
#define SIZE_COUNT (sizeof sizes / sizeof sizes[0])
#define FORMAT_COUNT (sizeof formats / sizeof formats[0])
#define DESKTOP_SIZE 3u /* 1280x720 */

static const char *const d3d8_names[MH_D3D8_METHODS] = {
    "IDirect3D8::QueryInterface", "IDirect3D8::AddRef", "IDirect3D8::Release", "IDirect3D8::RegisterSoftwareDevice",
    "IDirect3D8::GetAdapterCount", "IDirect3D8::GetAdapterIdentifier", "IDirect3D8::GetAdapterModeCount",
    "IDirect3D8::EnumAdapterModes", "IDirect3D8::GetAdapterDisplayMode", "IDirect3D8::CheckDeviceType",
    "IDirect3D8::CheckDeviceFormat", "IDirect3D8::CheckDeviceMultiSampleType", "IDirect3D8::CheckDepthStencilMatch",
    "IDirect3D8::GetDeviceCaps", "IDirect3D8::GetAdapterMonitor", "IDirect3D8::CreateDevice"};
/* Arguments of each method, including `this` (callee pops 4*n + 4 bytes). */
/* QueryInterface(this,riid,ppv) AddRef(this) Release(this) RegisterSoftwareDevice(this,p) GetAdapterCount(this)
 * GetAdapterIdentifier(this,Adapter,Flags,p) GetAdapterModeCount(this,Adapter) EnumAdapterModes(this,Adapter,Mode,p)
 * GetAdapterDisplayMode(this,Adapter,p) CheckDeviceType(this,Adapter,DevType,DispFmt,BackFmt,Windowed)
 * CheckDeviceFormat(this,Adapter,DevType,AdapterFmt,Usage,RType,CheckFmt)
 * CheckDeviceMultiSampleType(this,Adapter,DevType,SurfFmt,Windowed,MSType)
 * CheckDepthStencilMatch(this,Adapter,DevType,AdapterFmt,RTFmt,DSFmt) GetDeviceCaps(this,Adapter,DevType,p)
 * GetAdapterMonitor(this,Adapter) CreateDevice(this,Adapter,DevType,hFocus,Flags,pParams,ppDevice) */
static const uint8_t d3d8_args[MH_D3D8_METHODS] = {3, 1, 1, 2, 1, 4, 2, 4, 3, 6, 7, 6, 6, 4, 2, 7};

unsigned mh_d3d8_mode_count(void) { return (unsigned)(SIZE_COUNT * FORMAT_COUNT); }

static uint32_t alloc(mh_d3d8 *d3d, uint32_t size) {
    uint32_t start = (d3d->heap_next + 15u) & ~15u;
    if (start < d3d->heap_next || size > d3d->heap_limit - start || start > d3d->heap_limit) return 0;
    uint8_t *span = mh_mem_span(d3d->memory, start, size);
    if (!span) return 0;
    memset(span, 0, size);
    d3d->heap_next = start + size;
    return start;
}

int mh_d3d8_init(mh_d3d8 *d3d, mh_guest_memory *memory, uint32_t heap_base, uint32_t heap_size) {
    if (!d3d || !memory || (uint64_t)heap_base + heap_size > UINT32_MAX) return 0;
    d3d->memory = memory; d3d->heap_next = heap_base; d3d->heap_limit = heap_base + heap_size;
    d3d->vtable = alloc(d3d, 4 * MH_D3D8_METHODS);
    if (!d3d->vtable) return 0;
    for (uint32_t i = 0; i < MH_D3D8_METHODS; i++)
        mh_mem_write_u32(memory, d3d->vtable + 4 * i, MH_D3D8_VA + MH_COM_IFACE_STRIDE * MH_D3D8_IFACE_D3D8 + 4 * i);
    return 1;
}

/* Object layout: +0 vtable, +4 reference count. */
uint32_t mh_d3d8_create(mh_d3d8 *d3d, uint32_t sdk_version) {
    if (!d3d || sdk_version != MH_D3D_SDK_VERSION) return 0;
    uint32_t object = alloc(d3d, 16);
    if (!object) return 0;
    mh_mem_write_u32(d3d->memory, object, d3d->vtable);
    mh_mem_write_u32(d3d->memory, object + 4, 1);
    return object;
}

static void write_mode(mh_guest_memory *m, uint32_t at, unsigned index) {
    unsigned size = index / FORMAT_COUNT, format = index % FORMAT_COUNT;
    mh_mem_write_u32(m, at, sizes[size].width);
    mh_mem_write_u32(m, at + 4, sizes[size].height);
    mh_mem_write_u32(m, at + 8, 60);
    mh_mem_write_u32(m, at + 12, formats[format]);
}

static int valid_object(mh_d3d8 *d3d, uint32_t self) {
    uint32_t vtable = 0;
    return self && mh_mem_read_u32(d3d->memory, self, &vtable) && vtable == d3d->vtable;
}

int mh_d3d8_call(mh_d3d8 *d3d, uint32_t va, uint32_t esp, uint32_t *eax, uint32_t *pop, const char **name) {
    uint32_t a[8] = {0};
    if (!d3d || !eax || !pop || va < MH_D3D8_VA || ((va - MH_D3D8_VA) & 3u)) return MH_D3D8_BAD_CALL;
    uint32_t iface = (va - MH_D3D8_VA) / MH_COM_IFACE_STRIDE, method = ((va - MH_D3D8_VA) % MH_COM_IFACE_STRIDE) / 4u;
    if (iface != MH_D3D8_IFACE_D3D8 || method >= MH_D3D8_METHODS) return MH_D3D8_BAD_CALL;
    if (name) *name = d3d8_names[method];
    for (unsigned i = 0; i < d3d8_args[method]; i++)
        if (!mh_mem_read_u32(d3d->memory, esp + 4 + 4 * i, &a[i])) return MH_D3D8_BAD_CALL;
    if (!valid_object(d3d, a[0])) return MH_D3D8_BAD_CALL;
    *pop = 4u + 4u * d3d8_args[method];
    mh_guest_memory *m = d3d->memory;
    uint32_t refs = 0;
    switch (method) {
    case 0: /* QueryInterface(this, riid, ppv): only the object itself would qualify; report none. */
        if (a[2]) mh_mem_write_u32(m, a[2], 0);
        *eax = MH_E_NOINTERFACE; return MH_D3D8_DONE;
    case 1: case 2: /* AddRef / Release */
        if (!mh_mem_read_u32(m, a[0] + 4, &refs)) return MH_D3D8_BAD_CALL;
        refs = method == 1 ? refs + 1 : (refs ? refs - 1 : 0);
        mh_mem_write_u32(m, a[0] + 4, refs);
        *eax = refs; return MH_D3D8_DONE;
    case 4: /* GetAdapterCount */
        *eax = 1; return MH_D3D8_DONE;
    case 6: /* GetAdapterModeCount(this, Adapter) */
        *eax = a[1] == 0 ? mh_d3d8_mode_count() : 0; return MH_D3D8_DONE;
    case 7: /* EnumAdapterModes(this, Adapter, Mode, pMode) */
        if (a[1] != 0 || a[2] >= mh_d3d8_mode_count() || !a[3] || !mh_mem_span(m, a[3], 16)) { *eax = MH_D3DERR_INVALIDCALL; return MH_D3D8_DONE; }
        write_mode(m, a[3], a[2]); *eax = MH_D3D_OK; return MH_D3D8_DONE;
    case 8: /* GetAdapterDisplayMode(this, Adapter, pMode) */
        if (a[1] != 0 || !a[2] || !mh_mem_span(m, a[2], 16)) { *eax = MH_D3DERR_INVALIDCALL; return MH_D3D8_DONE; }
        write_mode(m, a[2], DESKTOP_SIZE * FORMAT_COUNT); *eax = MH_D3D_OK; return MH_D3D8_DONE;
    case 9: { /* CheckDeviceType(this, Adapter, DevType, DisplayFormat, BackBufferFormat, Windowed) */
        int display_ok = a[3] == MH_D3DFMT_X8R8G8B8 || a[3] == MH_D3DFMT_R5G6B5;
        int back_ok = a[4] == a[3] || (a[5] && (a[4] == MH_D3DFMT_X8R8G8B8 || a[4] == MH_D3DFMT_R5G6B5));
        *eax = a[1] == 0 && a[2] == MH_D3DDEVTYPE_HAL && display_ok && back_ok ? MH_D3D_OK : MH_D3DERR_NOTAVAILABLE;
        return MH_D3D8_DONE; }
    default:
        return MH_D3D8_UNIMPLEMENTED;
    }
}
