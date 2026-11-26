/* The port's Win32 / COM / Miles / Bink layer. Mirrors tools/winmain_apis.py (and the phase-2
 * handlers of tools/trace_static_init_x86.py) section by section; see port_api.h. */
#include "port_api.h"
#include "win32_memory.h"
#include "win32_thread.h"
#include "win32_process.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <io.h>
#else
#include <dirent.h>
#include <unistd.h>
#endif

#define GLOBAL_BASE 0x2000000u
#define GLOBAL_SIZE 0x4100000u
#define PROCESS_DATA 0x1f10000u
#define THREAD_ID 0x1234u
#define MAXPATH 1024

/* ---------------------------------------------------------------- state */
typedef struct { char key[96], name[96]; uint32_t atom, wndproc, style, extra0, extra1, hinst; } wclass;
typedef struct { uint32_t k, v; } kv;
typedef struct {
    uint32_t hwnd; char cls[96]; uint32_t wndproc, style, exstyle; int64_t rect[4];
    char title[1024]; int visible; kv longs[16]; unsigned nlongs;
} window;
typedef struct { uint32_t hdlg, template_, proc; int ended_set; uint32_t ended; } dialog;
typedef struct { uint32_t h, dialog, id, sel, check; unsigned n; char items[64][256]; uint32_t data[64]; } control;
typedef struct { uint32_t hwnd, id, interval; uint64_t due; } timer;
typedef struct { uint32_t hwnd, msg, wp, lp; } qmsg;
typedef struct { char key[64], name[64], value[1024]; } envvar;
typedef struct { uint32_t h; char path[MAXPATH], guest[MAXPATH]; uint64_t pos, size; int open, overlapped, ov, written; } gfile;   /* ov: overlay file index + 1 */
typedef struct { char key[MAXPATH * 2]; uint8_t *data; uint64_t size, cap, created, written; int deleted; } ovfile;   /* times: virtual clock (ms) */   /* writable overlay file (saves) */
typedef struct { uint32_t h; char path[600]; } hkey;
typedef struct { char key[64]; uint32_t type, size; uint8_t *data; } regvalue;
typedef struct { char key[600], name[600]; regvalue *values; unsigned nvalues; } regkey;

enum { K_DIDEVICE, K_DINPUT, K_D3D8, K_DEVICE, K_SURFACE, K_VBUF, K_IBUF, K_TEXTURE, K_KINDS };
typedef struct { uint32_t width, height, pitch, size, memory, locked, version, surface; } level;
typedef struct {
    uint32_t width, height, format, windowed, depth, swap, window, refresh, interval, flags;
} present_params;
typedef struct com_obj {
    uint32_t addr; int iface, kind;
    /* DirectInput device */
    int keyboard, has_format, acquired; uint32_t format, coop_hwnd, coop_flags;
    /* Direct3D device */
    present_params params; uint32_t rs[256]; uint8_t rs_set[256]; uint32_t tss[8][32]; uint8_t tss_set[8][32];
    struct { uint32_t index, m[16]; } transforms[64]; unsigned ntransforms;
    uint32_t textures[8]; uint32_t viewport[6]; int has_viewport; uint32_t material[17];
    struct { uint32_t index, l[26]; } lights[16]; unsigned nlights; kv light_enable[16]; unsigned nlight_enable;
    struct { uint32_t stream, buffer, stride; } streams[16]; unsigned nstreams;
    uint32_t indices[2]; uint32_t vertex_shader; int scene; unsigned frames, resets, clears, draws[4];
    uint32_t back_buffer, render_target, depth_stencil, cursor_shown;
    /* surface */
    uint32_t device, width, height, usage, pool, size, memory, pitch, locked, version; int has_memory;
    struct com_obj *level_owner; int level_index;
    /* buffers */
    uint32_t length, fvf, locks;
    /* texture */
    level levels[16]; unsigned nlevels;
    int destroyed;
} com_obj;

typedef struct {
    int released; uint32_t status, loops, info[9], offset, loop_block[2]; int has_info; uint64_t started;
    float volume; uint32_t playback_rate;   /* for the audio output only */
} sample;
typedef struct { uint32_t h, frames, rate, div; uint64_t start; char name[MAXPATH]; } bink;

struct mh_port {
    mh_guest_memory *mem; mh_port_host host; char game_dir[MAXPATH]; unsigned frame_limit;
    uint32_t api_esp;
    /* phase 2 */
    mh_win32_global_heap global; mh_win32_thread thread; mh_win32_process process;
    /* WinMain */
    uint64_t clock; uint32_t error_mode; char cwd[MAXPATH];
    envvar env[16]; unsigned nenv;
    wclass classes[8]; unsigned nclasses;
    window windows[16]; unsigned nwindows;
    struct { int32_t x, y; int32_t count; uint32_t handle; int clip; uint32_t cliprect[4]; } cursor;
    gfile *files; unsigned nfiles, capfiles;
    char overlay[16][MAXPATH]; unsigned noverlay;
    ovfile *ovfiles; unsigned novfiles, capovfiles; char save_dir[MAXPATH]; int save_readonly;   /* overlay files; save_dir: optional host copy */
    regkey *reg; unsigned nreg; hkey hkeys[64]; unsigned nhkeys;
    dialog dialogs[8]; unsigned ndialogs; control *controls; unsigned ncontrols;
    uint32_t active, focus;
    timer timers[16]; unsigned ntimers;
    qmsg queue[256]; unsigned nqueue;
    /* COM */
    uint32_t com_next; struct { int kind; uint32_t vtable; } ifaces[16]; unsigned nifaces; int iface_of_kind[K_KINDS];
    com_obj **objects; unsigned nobjects, capobjects;
    uint32_t res_next;
    struct { uint32_t start, end; } *res_free; unsigned nres_free, capres_free;
    uint32_t serial;                           /* resource contents versions, unique across reuse */
    unsigned frames;
    uint64_t tsc_reads;
    uint64_t (*now_ms)(void *); void *now_user; uint64_t now_base;
    uint32_t langid;                           /* GetUserDefaultLangID and friends */
    uint8_t keys[256], mouse_buttons[8];       /* live input (DIK scan codes; mouse buttons) */
    uint8_t keys_delivered[256];               /* keyboard state already posted as messages */
    volatile int32_t mouse_dx, mouse_dy;       /* live mouse motion not yet read by the game */
    mh_port_key_span script[64]; unsigned nscript;
    mh_port_renderer renderer; int has_renderer; struct com_obj *device;
    mh_port_audio audio; int has_audio;
    /* Miles */
    uint32_t mss_redist, mss_scratch, mss_driver; int mss_provider_open, mss_started;
    struct { uint32_t k, v; } prefs[32]; unsigned nprefs;
    struct { char name[128]; uint32_t v; } prefs3d[32]; unsigned nprefs3d; uint32_t room;
    sample samples[64]; unsigned nsamples;
    bink binks[8]; unsigned nbinks;
};

/* ---------------------------------------------------------------- helpers */
static void fail(mh_port *P, const char *fmt, ...) {
    char text[512]; va_list ap; va_start(ap, fmt); vsnprintf(text, sizeof text, fmt, ap); va_end(ap);
    P->host.fault(P->host.user, text); abort();
}
static uint32_t r32(mh_port *P, uint32_t a) { uint32_t v = 0; if (!mh_mem_read_u32(P->mem, a, &v)) fail(P, "guest read at 0x%08x", a); return v; }
static void w32(mh_port *P, uint32_t a, uint32_t v) { if (!mh_mem_write_u32(P->mem, a, v)) fail(P, "guest write at 0x%08x", a); }
static void wbytes(mh_port *P, uint32_t a, const void *d, size_t n) { if (n && !mh_mem_write(P->mem, a, d, n)) fail(P, "guest write of %u bytes at 0x%08x", (unsigned)n, a); }
static void zero(mh_port *P, uint32_t a, size_t n) { uint8_t *s = n ? mh_mem_span(P->mem, a, n) : NULL; if (n && !s) fail(P, "guest zero at 0x%08x", a); if (n) memset(s, 0, n); }
/* As the reference's cstr(a, limit): up to `limit` bytes, stopping at NUL. */
static void cstr(mh_port *P, uint32_t a, char *out, size_t limit) {
    size_t i = 0;
    for (; a && i < limit; i++) { uint8_t c = 0; if (!mh_mem_read(P->mem, a + (uint32_t)i, &c, 1)) fail(P, "guest string at 0x%08x", a); if (!c) break; out[i] = (char)c; }
    out[i] = 0;
}
static void upper(char *s) { for (; *s; s++) if (*s >= 'a' && *s <= 'z') *s -= 32; }
static void lower(char *s) { for (; *s; s++) if (*s >= 'A' && *s <= 'Z') *s += 32; }
static int ieq(const char *a, const char *b) { for (; *a && *b; a++, b++) { char x = *a, y = *b; if (x >= 'A' && x <= 'Z') x += 32; if (y >= 'A' && y <= 'Z') y += 32; if (x != y) return 0; } return *a == *b; }
static int istarts(const char *s, const char *p) { for (; *p; s++, p++) { char x = *s, y = *p; if (!x) return 0; if (x >= 'A' && x <= 'Z') x += 32; if (y >= 'A' && y <= 'Z') y += 32; if (x != y) return 0; } return 1; }
static void slashes(char *s) { for (; *s; s++) if (*s == '/') *s = '\\'; }
static void rstrip_bs(char *s) { size_t n = strlen(s); while (n && s[n - 1] == '\\') s[--n] = 0; }
static int32_t s32(uint32_t v) { return (int32_t)v; }
static uint32_t lparam(int64_t lo, int64_t hi) { return (uint32_t)((lo & 0xffff) | ((hi & 0xffff) << 16)); }
static int64_t floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b) && ((a < 0) != (b < 0))) q--; return q; }
/* Virtual clock: 1 ms per query (deterministic, as the reference). With a host clock
 * (mh_port_set_clock) it follows real time instead, never going backwards. */
static uint64_t tick(mh_port *P) {
    if (!P->now_ms) return ++P->clock;
    uint64_t real = 0x10000 + (P->now_ms(P->now_user) - P->now_base);
    if (real > P->clock) P->clock = real;
    return P->clock;
}
static uint32_t call_guest(mh_port *P, uint32_t fn, const uint32_t *args, unsigned n) {
    return P->host.call_guest(P->host.user, P->api_esp, fn, args, n);
}

/* ---------------------------------------------------------------- host file system */
static int host_isdir(const char *p) { struct stat st; return stat(p, &st) == 0 && (st.st_mode & S_IFMT) == S_IFDIR; }
static int host_isfile(const char *p) { struct stat st; return stat(p, &st) == 0 && (st.st_mode & S_IFMT) == S_IFREG; }
static uint64_t host_size(const char *p) { struct stat st; return stat(p, &st) == 0 ? (uint64_t)st.st_size : 0; }
/* First entry of `dir` equal to `name` ignoring ASCII case (directory order, as os.listdir). */
static int host_match(const char *dir, const char *name, char *out, size_t size) {
#ifdef _WIN32
    char pattern[MAXPATH + 4]; struct _finddata_t fd; intptr_t h;
    snprintf(pattern, sizeof pattern, "%s\\*", dir);
    if ((h = _findfirst(pattern, &fd)) == -1) return -1;
    int found = 0;
    do { if (strcmp(fd.name, ".") && strcmp(fd.name, "..") && ieq(fd.name, name)) { snprintf(out, size, "%s", fd.name); found = 1; break; } } while (_findnext(h, &fd) == 0);
    _findclose(h); return found;
#else
    DIR *d = opendir(dir); struct dirent *e; int found = 0;
    if (!d) return -1;
    while ((e = readdir(d))) if (strcmp(e->d_name, ".") && strcmp(e->d_name, "..") && ieq(e->d_name, name)) { snprintf(out, size, "%s", e->d_name); found = 1; break; }
    closedir(d); return found;
#endif
}
#ifdef _WIN32
#define SEP "\\"
#else
#define SEP "/"
#endif
/* resolve(): guest path -> host path; *err = 0, 2 (file not found) or 3 (path not found). */
static int resolve(mh_port *P, const char *guest, char *host, size_t size, uint32_t *err) {
    char p[MAXPATH * 2], comp[MAXPATH], match[MAXPATH];
    snprintf(p, sizeof p, "%s", guest); slashes(p);
    if (!(strlen(p) > 1 && p[1] == ':') && p[0] != '\\') { char t[MAXPATH * 2]; snprintf(t, sizeof t, "%s\\%s", P->cwd, p); snprintf(p, sizeof p, "%s", t); }
    if (!istarts(p, MH_PORT_GAME_DIR)) { *err = 3; return 0; }
    snprintf(host, size, "%s", P->game_dir);
    const char *s = p + strlen(MH_PORT_GAME_DIR);
    /* components, skipping '' and '.' */
    char *parts[256]; unsigned n = 0; static char buf[MAXPATH * 2];
    snprintf(buf, sizeof buf, "%s", s);
    for (char *t = buf, *q; t; t = q) { q = strchr(t, '\\'); if (q) *q++ = 0; if (*t && strcmp(t, ".")) { if (n < 256) parts[n++] = t; } }
    for (unsigned i = 0; i < n; i++) {
        snprintf(comp, sizeof comp, "%s", parts[i]);
        if (!strcmp(comp, "..")) { *err = 3; return 0; }
        int r = host_match(host, comp, match, sizeof match);
        if (r < 0) { *err = 3; return 0; }
        if (!r) { *err = i == n - 1 ? 2 : 3; return 0; }
        size_t l = strlen(host); snprintf(host + l, size - l, SEP "%s", match);
    }
    *err = 0; return 1;
}

/* ---------------------------------------------------------------- COM core */
static uint32_t com_alloc(mh_port *P, uint32_t size) {
    uint32_t start = (P->com_next + 15u) & ~15u;
    if (start + size > MH_PORT_COM_LIMIT) fail(P, "COM heap exhausted");
    zero(P, start, size); P->com_next = start + size; return start;
}
typedef uint32_t (*com_handler)(mh_port *, com_obj *, const uint32_t *, int *);
typedef struct { const char *name; unsigned nargs; com_handler fn; } com_method;
typedef struct { const char *name; const com_method *methods; unsigned count; } com_iface_desc;
static const com_iface_desc *iface_desc(int kind);
static int interface(mh_port *P, int kind) {
    const com_iface_desc *d = iface_desc(kind);
    unsigned index = P->nifaces; uint32_t vtable = com_alloc(P, 4 * d->count);
    for (unsigned i = 0; i < d->count; i++) w32(P, vtable + 4 * i, MH_PORT_COM_VA + 0x400u * index + 4 * i);
    P->ifaces[index].kind = kind; P->ifaces[index].vtable = vtable; P->nifaces++; P->iface_of_kind[kind] = (int)index;
    return (int)index;
}
static int iface_for(mh_port *P, int kind) { return P->iface_of_kind[kind] >= 0 ? P->iface_of_kind[kind] : interface(P, kind); }
static com_obj *object(mh_port *P, uint32_t addr) {
    for (unsigned i = 0; i < P->nobjects; i++) if (P->objects[i]->addr == addr) return P->objects[i];
    return NULL;
}
static com_obj *new_object(mh_port *P, int index) {
    uint32_t obj = com_alloc(P, 16); w32(P, obj, P->ifaces[index].vtable); w32(P, obj + 4, 1);
    com_obj *o = calloc(1, sizeof *o); if (!o) fail(P, "out of host memory");
    o->addr = obj; o->iface = index; o->kind = P->ifaces[index].kind;
    if (P->nobjects == P->capobjects) { P->capobjects = P->capobjects ? 2 * P->capobjects : 256; P->objects = realloc(P->objects, P->capobjects * sizeof *P->objects); }
    P->objects[P->nobjects++] = o; return o;
}
static uint32_t give(mh_port *P, uint32_t obj) { w32(P, obj + 4, r32(P, obj + 4) + 1); return obj; }
static uint32_t addref(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; uint32_t r = r32(P, a[0] + 4) + 1; w32(P, a[0] + 4, r); return r; }
/* Resource memory: sizes rounded to 16; first fit in address order over the released blocks,
 * else the top; reused memory is zeroed (the reference, tools/winmain_apis.py, does the same). */
static uint32_t res_alloc(mh_port *P, uint32_t size) {
    size = (size + 15u) & ~15u;
    for (unsigned i = 0; i < P->nres_free; i++) {
        uint32_t s = P->res_free[i].start, e = P->res_free[i].end;
        if (e - s < size) continue;
        if (e - s == size) { memmove(&P->res_free[i], &P->res_free[i + 1], (P->nres_free - i - 1) * sizeof *P->res_free); P->nres_free--; }
        else P->res_free[i].start = s + size;
        zero(P, s, size); return s;
    }
    uint32_t start = P->res_next;
    if (start + size > MH_PORT_RES_LIMIT || start + size < start) fail(P, "Direct3D resource memory exhausted");
    P->res_next = start + size; return start;
}
static void res_release(mh_port *P, uint32_t start, uint32_t size) {
    size = (size + 15u) & ~15u;
    if (P->nres_free == P->capres_free) {
        P->capres_free = P->capres_free ? 2 * P->capres_free : 256;
        P->res_free = realloc(P->res_free, P->capres_free * sizeof *P->res_free); if (!P->res_free) fail(P, "out of host memory");
    }
    unsigned i = 0; while (i < P->nres_free && P->res_free[i].start < start) i++;
    memmove(&P->res_free[i + 1], &P->res_free[i], (P->nres_free - i) * sizeof *P->res_free); P->nres_free++;
    P->res_free[i].start = start; P->res_free[i].end = start + size;
    if (i + 1 < P->nres_free && P->res_free[i].end == P->res_free[i + 1].start) {
        P->res_free[i].end = P->res_free[i + 1].end;
        memmove(&P->res_free[i + 1], &P->res_free[i + 2], (P->nres_free - i - 2) * sizeof *P->res_free); P->nres_free--;
    }
    if (i > 0 && P->res_free[i - 1].end == P->res_free[i].start) {
        P->res_free[i - 1].end = P->res_free[i].end;
        memmove(&P->res_free[i], &P->res_free[i + 1], (P->nres_free - i - 1) * sizeof *P->res_free); P->nres_free--;
    }
    if (P->nres_free && P->res_free[P->nres_free - 1].end == P->res_next) P->res_next = P->res_free[--P->nres_free].start;
}
static void level_layout(mh_port *P, uint32_t fmt, uint32_t w, uint32_t h, uint32_t *pitch, uint32_t *size);
static void key_messages(mh_port *P);
/* Last reference released: the object's own resource memory returns (a texture level's surface
 * belongs to its texture; device surfaces keep the device's reference). */
static void destroy(mh_port *P, com_obj *o) {
    if (o->destroyed) return;
    if (o->kind == K_TEXTURE) for (unsigned i = 0; i < o->nlevels; i++) res_release(P, o->levels[i].memory, o->levels[i].size);
    else if (o->kind == K_VBUF || o->kind == K_IBUF) res_release(P, o->memory, o->length);
    else if (o->kind == K_SURFACE && o->has_memory && !o->level_owner) { uint32_t pitch, size; level_layout(P, o->format, o->width, o->height, &pitch, &size); res_release(P, o->memory, size); }
    else return;
    o->destroyed = 1;
}
static uint32_t release(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; uint32_t r = r32(P, a[0] + 4); r = r ? r - 1 : 0; w32(P, a[0] + 4, r);
    if (!r && o) destroy(P, o);
    return r;
}

/* ---------------------------------------------------------------- DirectInput 8 */
static const uint8_t GUID_KEYBOARD[16] = {0x61,0x2b,0x1d,0x6f,0xa0,0xd5,0xcf,0x11,0xbf,0xc7,0x44,0x45,0x53,0x54,0x00,0x00};
static const uint8_t GUID_MOUSE[16]    = {0x60,0x2b,0x1d,0x6f,0xa0,0xd5,0xcf,0x11,0xbf,0xc7,0x44,0x45,0x53,0x54,0x00,0x00};
static const uint8_t IID_DI8A[16]      = {0x30,0x80,0x79,0xbf,0x3a,0x48,0xa2,0x4d,0xaa,0x99,0x5d,0x64,0xed,0x36,0x97,0x00};
static int guid_is(mh_port *P, uint32_t a, const uint8_t *g) { uint8_t b[16]; if (!mh_mem_read(P->mem, a, b, 16)) fail(P, "GUID read"); return !memcmp(b, g, 16); }
#define DIERR_INVALIDPARAM 0x80070057u
#define DIERR_DEVICENOTREG 0x80040154u
#define DIERR_NOTACQUIRED 0x8007000cu
#define DIERR_NOINTERFACE 0x80004002u
static uint32_t dev_get_caps(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; if (r32(P, a[1]) != 0x2c) return DIERR_INVALIDPARAM;
    const uint32_t mouse[6] = {0x2c, 1, 0x212, 3, 3, 0}, kb[6] = {0x2c, 1, 0x413, 0, 128, 0};
    zero(P, a[1], 0x2c); for (int i = 0; i < 6; i++) w32(P, a[1] + 4 * i, o->keyboard ? kb[i] : mouse[i]);
    return 0;
}
static uint32_t dev_acquire(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)a; (void)h; if (!o->has_format) return DIERR_INVALIDPARAM; o->acquired = 1; return 0; }
static uint32_t dev_unacquire(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)a; (void)h; int was = o->acquired; o->acquired = 0; return was ? 0 : 1; }
static uint32_t dev_get_state(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; if (!o->acquired) return DIERR_NOTACQUIRED;
    if (!o->has_format || a[1] != o->format) return DIERR_INVALIDPARAM;
    zero(P, a[2], a[1]);
    if (!o->keyboard && (a[1] == 16 || a[1] == 20)) {   /* DIMOUSESTATE(2): lX, lY (live motion), buttons at +12 (script codes 0x100 + n) */
        int32_t dx = P->mouse_dx, dy = P->mouse_dy, sx = 0, sy = 0;
        P->mouse_dx -= dx; P->mouse_dy -= dy;
        for (unsigned i = 0; i < P->nscript; i++) {   /* scripted motion: 0x200 +X, 0x201 -X, 0x202 +Y, 0x203 -Y */
            unsigned k = P->script[i].key;
            if (k < 0x200 || k > 0x203 || P->frames < P->script[i].from || P->frames >= P->script[i].to) continue;
            int32_t s = (k == 0x200 || k == 0x202) ? MH_PORT_MOUSE_STEP : -MH_PORT_MOUSE_STEP;
            if (k < 0x202) sx += s; else sy += s;
        }
        dx += sx; dy += sy;
        if (dx || dy) { w32(P, a[2], (uint32_t)dx); w32(P, a[2] + 4, (uint32_t)dy); }
        for (unsigned b = 0; b < a[1] - 12; b++) {
            int down = P->mouse_buttons[b & 7] != 0;
            for (unsigned i = 0; i < P->nscript && !down; i++)
                down = P->script[i].key == 0x100 + b && P->frames >= P->script[i].from && P->frames < P->script[i].to;
            if (down) { const uint8_t v = 0x80; wbytes(P, a[2] + 12 + b, &v, 1); }
        }
    }
    if (o->keyboard && a[1] == 256) {   /* DIK scan codes: 0x80 when down (live state or the input script) */
        for (unsigned k = 0; k < 256; k++) {
            int down = P->keys[k] != 0;
            for (unsigned i = 0; i < P->nscript && !down; i++)
                down = P->script[i].key == k && P->frames >= P->script[i].from && P->frames < P->script[i].to;
            if (down) { const uint8_t v = 0x80; wbytes(P, a[2] + k, &v, 1); }
        }
    }
    return 0;
}
static uint32_t dev_set_format(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; uint32_t f[4]; for (int i = 0; i < 4; i++) f[i] = r32(P, a[1] + 4 * i);
    if (f[0] != 0x18 || f[1] != 0x10) return DIERR_INVALIDPARAM;
    o->format = f[3]; o->has_format = 1; return 0;
}
static uint32_t dev_set_coop(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)h; o->coop_hwnd = a[1]; o->coop_flags = a[2]; return 0; }
static const com_method DIDEVICE_METHODS[] = {
    {"QueryInterface",3,0},{"AddRef",1,addref},{"Release",1,release},{"GetCapabilities",2,dev_get_caps},{"EnumObjects",4,0},{"GetProperty",3,0},
    {"SetProperty",3,0},{"Acquire",1,dev_acquire},{"Unacquire",1,dev_unacquire},{"GetDeviceState",3,dev_get_state},{"GetDeviceData",5,0},
    {"SetDataFormat",2,dev_set_format},{"SetEventNotification",2,0},{"SetCooperativeLevel",3,dev_set_coop},{"GetObjectInfo",4,0},{"GetDeviceInfo",2,0},
    {"RunControlPanel",3,0},{"Initialize",4,0},{"CreateEffect",5,0},{"EnumEffects",4,0},{"GetEffectInfo",3,0},{"GetForceFeedbackState",2,0},
    {"SendForceFeedbackCommand",2,0},{"EnumCreatedEffectObjects",4,0},{"Escape",2,0},{"Poll",1,0},{"SendDeviceData",5,0},{"EnumEffectsInFile",5,0},
    {"WriteEffectToFile",5,0},{"BuildActionMap",4,0},{"SetActionMap",4,0},{"GetImageInfo",2,0}};
static uint32_t di_create_device(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; int kb = guid_is(P, a[1], GUID_KEYBOARD), mouse = guid_is(P, a[1], GUID_MOUSE);
    if (!kb && !mouse) { w32(P, a[2], 0); return DIERR_DEVICENOTREG; }
    if (a[3]) return 0x80040110u;
    com_obj *d = new_object(P, P->iface_of_kind[K_DIDEVICE]); d->keyboard = kb; w32(P, a[2], d->addr); return 0;
}
static uint32_t di_enum_devices(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; uint32_t t = a[1];
    if (t == 4 || (t >= 0x14 && t <= 0x18)) return 0;
    fail(P, "IDirectInput8A::EnumDevices for device type 0x%x", t); return 0;
}
static const com_method DINPUT_METHODS[] = {
    {"QueryInterface",3,0},{"AddRef",1,addref},{"Release",1,release},{"CreateDevice",4,di_create_device},{"EnumDevices",5,di_enum_devices},
    {"GetDeviceStatus",2,0},{"RunControlPanel",3,0},{"Initialize",3,0},{"FindDevice",4,0},{"EnumDevicesBySemantics",6,0},{"ConfigureDevices",5,0}};

/* ---------------------------------------------------------------- Direct3D 8 */
#define D3D_OK 0u
#define D3DERR_INVALIDCALL 0x8876086cu
#define D3DERR_NOTAVAILABLE 0x8876086au
#define X8R8G8B8 22u
#define R5G6B5 23u
#define FOURCC(a,b,c,d) ((uint32_t)(a) | (uint32_t)(b) << 8 | (uint32_t)(c) << 16 | (uint32_t)(d) << 24)
#define DXT1 FOURCC('D','X','T','1')
static const uint32_t SIZES[6][2] = {{640,480},{800,600},{1024,768},{1280,720},{1280,960},{1920,1080}};
static const uint32_t FORMATS[2] = {X8R8G8B8, R5G6B5};
static void mode(unsigned i, uint32_t *m) { m[0] = SIZES[i / 2][0]; m[1] = SIZES[i / 2][1]; m[2] = 60; m[3] = FORMATS[i % 2]; }
static void write_mode(mh_port *P, uint32_t at, const uint32_t *m) { for (int i = 0; i < 4; i++) w32(P, at + 4 * i, m[i]); }
static int is_format(uint32_t f) { return f == X8R8G8B8 || f == R5G6B5; }
static int is_texture_format(uint32_t f) { return (f >= 21 && f <= 26) || f == 28 || f == 50 || f == 51 || (f >= FOURCC('D','X','T','1') && f <= FOURCC('D','X','T','5') && (f & 0x00ffffffu) == (FOURCC('D','X','T','1') & 0x00ffffffu)); }
static int is_depth_format(uint32_t f) { return f == 80 || f == 75 || f == 77; }
static int is_target_format(uint32_t f) { return f == 21 || f == 22 || f == 23; }
static uint32_t F(float v) { uint32_t b; memcpy(&b, &v, 4); return b; }
static uint32_t d3d_qi(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; if (a[2]) w32(P, a[2], 0); return 0x80004002u; }
static uint32_t d3d_count(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; (void)h; return 1; }
static uint32_t d3d_mode_count(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)h; return a[1] == 0 ? 12 : 0; }
static uint32_t d3d_enum_modes(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; uint32_t m[4]; if (a[1] != 0 || a[2] >= 12 || !a[3]) return D3DERR_INVALIDCALL;
    mode(a[2], m); write_mode(P, a[3], m); return D3D_OK;
}
static uint32_t d3d_display_mode(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; uint32_t m[4]; if (a[1] != 0 || !a[2]) return D3DERR_INVALIDCALL;
    mode(6, m); write_mode(P, a[2], m); return D3D_OK;
}
static uint32_t d3d_check_type(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)P; (void)o; (void)h; int display = is_format(a[3]), back = a[4] == a[3] || (a[5] && is_format(a[4]));
    return a[1] == 0 && a[2] == 1 && display && back ? D3D_OK : D3DERR_NOTAVAILABLE;
}
static uint32_t caps8[53];
static void init_caps(void) {
    const uint32_t c[53] = {1,0, 0,0x200A0000,0,0x80000001,0, 0x0009BAF0, 0x000008F2,0x00332191, 0xFF,0x1FFF,0x1FFF,0xFF,
        0x00084208,0x00014C05, 0x03030700,0x03030700,0, 0x1F,0,0x1F, 2048,2048,0,8192,2048,4,
        F(1e10f),F(0.0f),F(0.0f),F(0.0f),F(0.0f),F(0.0f), 0xFF,0x00080008,0x03FFFFFF, 8,4,0x3B,8,6,4,0,
        F(64.0f),0xFFFFF,0xFFFFF,16,255, 0xFFFE0000,0,0xFFFF0000,F(0.0f)};
    memcpy(caps8, c, sizeof c);
}
static uint32_t d3d_get_caps_at(mh_port *P, uint32_t adapter, uint32_t type, uint32_t out) {
    if (adapter != 0 || type != 1 || !out) return D3DERR_INVALIDCALL;
    for (int i = 0; i < 53; i++) w32(P, out + 4 * i, caps8[i]);
    return D3D_OK;
}
static uint32_t d3d_get_caps(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; return d3d_get_caps_at(P, a[1], a[2], a[3]); }
static uint32_t d3d_check_format(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)P; (void)o; (void)h; uint32_t usage = a[4], rtype = a[5], fmt = a[6]; int ok;
    if (a[1] != 0 || a[2] != 1 || !is_format(a[3])) return D3DERR_INVALIDCALL;
    if (usage & 2) ok = is_depth_format(fmt) && rtype == 1;
    else if (usage & 1) ok = is_target_format(fmt) && (rtype == 1 || rtype == 3);
    else if (rtype == 1 || rtype == 3 || rtype == 5) ok = is_texture_format(fmt) || is_target_format(fmt);
    else ok = 0;
    return ok ? D3D_OK : D3DERR_NOTAVAILABLE;
}
static uint32_t d3d_check_ms(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)h; if (a[1] != 0 || a[2] != 1) return D3DERR_INVALIDCALL; return a[5] == 0 ? D3D_OK : D3DERR_NOTAVAILABLE; }
static uint32_t d3d_check_depth(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)P; (void)o; (void)h; if (a[1] != 0 || a[2] != 1) return D3DERR_INVALIDCALL;
    return is_target_format(a[4]) && is_depth_format(a[5]) ? D3D_OK : D3DERR_NOTAVAILABLE;
}
static uint32_t d3d_identifier(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; if (a[1] != 0 || !a[3]) return D3DERR_INVALIDCALL;
    zero(P, a[3], 0x42c);
    wbytes(P, a[3], "mh-androidevolved", 18); wbytes(P, a[3] + 512, "Android OpenGL ES (Manhunt port)", 33);
    w32(P, a[3] + 1024, 0); w32(P, a[3] + 1028, 0x00080001); w32(P, a[3] + 0x428, 1); return D3D_OK;
}
static uint32_t bytes_per_pixel(uint32_t f) {
    switch (f) { case 21: case 22: case 75: case 77: return 4; case 23: case 24: case 25: case 26: case 51: case 80: return 2; case 28: case 50: return 1; default: return 0; }
}
static void level_layout(mh_port *P, uint32_t fmt, uint32_t w, uint32_t h, uint32_t *pitch, uint32_t *size) {
    if (is_texture_format(fmt) && fmt > 0xffff) {
        uint32_t bw = (w + 3) / 4 ? (w + 3) / 4 : 1, bh = (h + 3) / 4 ? (h + 3) / 4 : 1, block = fmt == DXT1 ? 8 : 16;
        *pitch = bw * block; *size = bw * block * bh; return;
    }
    uint32_t bpp = bytes_per_pixel(fmt);
    if (!bpp) fail(P, "texture format 0x%x", fmt);
    *pitch = w * bpp; *size = w * bpp * h;
}
/* surfaces */
static com_obj *new_surface(mh_port *P, uint32_t device, uint32_t w, uint32_t h, uint32_t fmt, uint32_t usage, uint32_t pool) {
    com_obj *s = new_object(P, iface_for(P, K_SURFACE));
    s->device = device; s->width = w; s->height = h; s->format = fmt; s->usage = usage; s->pool = pool; s->size = w * h * bytes_per_pixel(fmt);
    return s;
}
static uint32_t surf_desc(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; const uint32_t v[8] = {o->format, 1, o->usage, o->pool, o->size, 0, o->width, o->height};
    for (int i = 0; i < 8; i++) w32(P, a[1] + 4 * i, v[i]);
    return D3D_OK;
}
static uint32_t block_offset(com_obj *t, uint32_t fmt, uint32_t pitch, uint32_t left, uint32_t top) {
    (void)t; return fmt > 0xffff ? (top / 4) * pitch + (left / 4) * (fmt == DXT1 ? 8 : 16) : top * pitch + left * bytes_per_pixel(fmt);
}
static uint32_t surf_lock(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; if (o->locked) return D3DERR_INVALIDCALL;
    if (!o->has_memory) { uint32_t pitch, size; level_layout(P, o->format, o->width, o->height, &pitch, &size); o->pitch = pitch; o->memory = res_alloc(P, size); o->has_memory = 1; }
    uint32_t offset = a[2] ? block_offset(o, o->format, o->pitch, r32(P, a[2]), r32(P, a[2] + 4)) : 0;
    o->locked = 1; w32(P, a[1], o->pitch); w32(P, a[1] + 4, o->memory + offset); return D3D_OK;
}
static uint32_t surf_unlock(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)a; (void)h; if (!o->locked) return D3DERR_INVALIDCALL;
    o->locked = 0; o->version = ++P->serial;
    if (o->level_owner) o->level_owner->levels[o->level_index].version = P->serial;
    return D3D_OK;
}
static const com_method SURFACE_METHODS[] = {
    {"QueryInterface",3,0},{"AddRef",1,addref},{"Release",1,release},{"GetDevice",2,0},{"SetPrivateData",5,0},{"GetPrivateData",4,0},
    {"FreePrivateData",2,0},{"GetContainer",3,0},{"GetDesc",2,surf_desc},{"LockRect",4,surf_lock},{"UnlockRect",1,surf_unlock}};
/* buffers */
static uint32_t buf_lock(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; uint32_t offset = a[1], size = a[2], out = a[3];
    if (offset > o->length || (size && (uint64_t)offset + size > o->length)) return D3DERR_INVALIDCALL;
    o->locks++; w32(P, out, o->memory + offset); return D3D_OK;
}
static uint32_t buf_unlock(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)a; (void)h; if (!o->locks) return D3DERR_INVALIDCALL; o->locks--; o->version = ++P->serial; return D3D_OK; }
static uint32_t buf_desc(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; int vertex = o->kind == K_VBUF; const uint32_t v[6] = {o->format, vertex ? 6u : 7u, o->usage, o->pool, o->length, o->fvf};
    for (int i = 0; i < (vertex ? 6 : 5); i++) w32(P, a[1] + 4 * i, v[i]);
    return D3D_OK;
}
static uint32_t buf_preload(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; *h = 0; return 0; }
static uint32_t buf_type(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)a; (void)h; return o->kind == K_VBUF ? 6 : 7; }
static const com_method BUFFER_METHODS[] = {
    {"QueryInterface",3,0},{"AddRef",1,addref},{"Release",1,release},{"GetDevice",2,0},{"SetPrivateData",5,0},{"GetPrivateData",4,0},
    {"FreePrivateData",2,0},{"SetPriority",2,0},{"GetPriority",1,0},{"PreLoad",1,buf_preload},{"GetType",1,buf_type},{"Lock",5,buf_lock},
    {"Unlock",1,buf_unlock},{"GetDesc",2,buf_desc}};
static uint32_t create_buffer(mh_port *P, uint32_t device, int kind, uint32_t length, uint32_t usage, uint32_t fmt, uint32_t fvf, uint32_t pool, uint32_t out) {
    if (!length || !out || pool > 3) return D3DERR_INVALIDCALL;
    if (kind == K_IBUF && fmt != 101 && fmt != 102) return D3DERR_INVALIDCALL;
    int index = iface_for(P, kind);
    uint32_t memory = res_alloc(P, length);
    com_obj *b = new_object(P, index);
    b->device = device; b->length = length; b->usage = usage; b->format = fmt; b->fvf = fvf; b->pool = pool; b->memory = memory;
    w32(P, out, b->addr); return D3D_OK;
}
/* textures */
static level *tex_level(com_obj *o, uint32_t i) { return i < o->nlevels ? &o->levels[i] : NULL; }
static uint32_t tex_lock(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; level *lv = tex_level(o, a[1]);
    if (!lv || lv->locked) return D3DERR_INVALIDCALL;
    uint32_t offset = a[3] ? block_offset(o, o->format, lv->pitch, r32(P, a[3]), r32(P, a[3] + 4)) : 0;
    lv->locked = 1; w32(P, a[2], lv->pitch); w32(P, a[2] + 4, lv->memory + offset); return D3D_OK;
}
static uint32_t tex_unlock(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; level *lv = tex_level(o, a[1]); if (!lv || !lv->locked) return D3DERR_INVALIDCALL; lv->locked = 0; lv->version = ++P->serial; return D3D_OK; }
static uint32_t tex_level_desc(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; level *lv = tex_level(o, a[1]); if (!lv) return D3DERR_INVALIDCALL;
    const uint32_t v[8] = {o->format, 1, o->usage, o->pool, lv->size, 0, lv->width, lv->height};
    for (int i = 0; i < 8; i++) w32(P, a[2] + 4 * i, v[i]);
    return D3D_OK;
}
static uint32_t tex_surface_level(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; level *lv = tex_level(o, a[1]); if (!lv) return D3DERR_INVALIDCALL;
    if (!lv->surface) {
        com_obj *s = new_surface(P, o->device, lv->width, lv->height, o->format, o->usage, o->pool);
        s->memory = lv->memory; s->pitch = lv->pitch; s->has_memory = 1; s->level_owner = o; s->level_index = (int)a[1]; lv->surface = s->addr;
    }
    w32(P, a[2], give(P, lv->surface)); return D3D_OK;
}
static uint32_t tex_preload(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; *h = 0; return 0; }
static uint32_t tex_type(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; (void)h; return 3; }
static uint32_t tex_count(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)a; (void)h; return o->nlevels; }
static uint32_t tex_dirty(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; (void)h; return D3D_OK; }
static const com_method TEXTURE_METHODS[] = {
    {"QueryInterface",3,0},{"AddRef",1,addref},{"Release",1,release},{"GetDevice",2,0},{"SetPrivateData",5,0},{"GetPrivateData",4,0},
    {"FreePrivateData",2,0},{"SetPriority",2,0},{"GetPriority",1,0},{"PreLoad",1,tex_preload},{"GetType",1,tex_type},{"SetLOD",2,0},
    {"GetLOD",1,0},{"GetLevelCount",1,tex_count},{"GetLevelDesc",3,tex_level_desc},{"GetSurfaceLevel",3,tex_surface_level},
    {"LockRect",5,tex_lock},{"UnlockRect",2,tex_unlock},{"AddDirtyRect",2,tex_dirty}};

/* device */
static uint32_t rs_default(mh_port *P, uint32_t s, int *known) {
    static const uint32_t keys[] = {7,8,9,10,14,15,16,19,20,22,23,24,25,26,27,28,29,30,34,35,36,37,38,40,47,48,52,53,54,55,56,57,58,59,60,
        128,129,130,131,132,133,134,135,136,137,139,140,141,142,143,145,146,147,148,151,152,153,154,155,156,157,158,159,160,161,162,163,164,166,167,168,170,171};
    const uint32_t vals[] = {1,3,2,0,1,0,1,2,1,3,4,0,8,0,0,0,0,0,0,0,F(0.0f),F(1.0f),F(1.0f),0,0,0,0,1,1,1,8,0,0xffffffffu,0xffffffffu,0xffffffffu,
        0,0,0,0,0,0,0,0,1,1,0,0,1,1,0,1,2,0,0,0,0,0,F(1.0f),F(1.0f),0,0,F(1.0f),F(0.0f),F(0.0f),1,0xffffffffu,0,F(1.0f),F(64.0f),0,0xf,F(0.0f),1};
    (void)P;
    for (unsigned i = 0; i < sizeof keys / sizeof keys[0]; i++) if (keys[i] == s) { *known = 1; return vals[i]; }
    *known = 0; return 0;
}
static uint32_t tss_default(mh_port *P, uint32_t stage, uint32_t t) {
    switch (t) {
    case 1: return stage == 0 ? 4 : 1; case 2: return 2; case 3: return 1; case 4: return stage == 0 ? 2 : 1; case 5: return 2; case 6: return 1;
    case 7: case 8: case 9: case 10: return 0; case 11: return stage; case 13: case 14: return 1; case 15: return 0; case 16: case 17: return 1;
    case 18: case 19: case 20: return 0; case 21: return 1; case 22: case 23: case 24: return 0; case 25: case 26: case 27: case 28: return 1;
    default: fail(P, "texture stage state %u has no known default", t); return 0;
    }
}
static uint32_t dv_set_rs(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)h; if (a[1] >= 256) fail(P, "render state %u", a[1]); o->rs[a[1]] = a[2]; o->rs_set[a[1]] = 1; return D3D_OK; }
static uint32_t dv_get_rs(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; int known; uint32_t d = rs_default(P, a[1], &known);
    int set = a[1] < 256 && o->rs_set[a[1]];
    if (!set && !known) fail(P, "render state %u has no known default", a[1]);
    w32(P, a[2], set ? o->rs[a[1]] : d); return D3D_OK;
}
static uint32_t dv_set_tss(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; if (a[1] >= 8) return D3DERR_INVALIDCALL;
    if (a[2] >= 32) fail(P, "texture stage state %u", a[2]);
    o->tss[a[1]][a[2]] = a[3]; o->tss_set[a[1]][a[2]] = 1; return D3D_OK;
}
static uint32_t dv_get_tss(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; if (a[1] >= 8) return D3DERR_INVALIDCALL;
    uint32_t d = tss_default(P, a[1], a[2]);   /* evaluated first, as the reference */
    w32(P, a[3], a[2] < 32 && o->tss_set[a[1]][a[2]] ? o->tss[a[1]][a[2]] : d); return D3D_OK;
}
static uint32_t dv_set_texture(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)h; if (a[1] >= 8) return D3DERR_INVALIDCALL; o->textures[a[1]] = a[2]; return D3D_OK; }
static uint32_t dv_get_texture(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; uint32_t t = a[1] < 8 ? o->textures[a[1]] : 0; w32(P, a[2], t ? give(P, t) : 0); return D3D_OK; }
static uint32_t dv_set_transform(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; unsigned i = 0;
    for (; i < o->ntransforms && o->transforms[i].index != a[1]; i++) {}
    if (i == o->ntransforms) { if (i == 64) fail(P, "too many transforms"); o->transforms[o->ntransforms++].index = a[1]; }
    for (int k = 0; k < 16; k++) o->transforms[i].m[k] = r32(P, a[2] + 4 * k);
    return D3D_OK;
}
static uint32_t dv_get_transform(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; const uint32_t identity[16] = {F(1.0f),0,0,0, 0,F(1.0f),0,0, 0,0,F(1.0f),0, 0,0,0,F(1.0f)}; const uint32_t *m = identity;
    for (unsigned i = 0; i < o->ntransforms; i++) if (o->transforms[i].index == a[1]) m = o->transforms[i].m;
    for (int k = 0; k < 16; k++) w32(P, a[2] + 4 * k, m[k]);
    return D3D_OK;
}
static uint32_t dv_set_viewport(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; for (int k = 0; k < 6; k++) o->viewport[k] = r32(P, a[1] + 4 * k); o->has_viewport = 1; return D3D_OK; }
static uint32_t dv_get_viewport(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; const uint32_t d[6] = {0, 0, o->params.width, o->params.height, F(0.0f), F(1.0f)};
    for (int k = 0; k < 6; k++) w32(P, a[1] + 4 * k, o->has_viewport ? o->viewport[k] : d[k]);
    return D3D_OK;
}
static uint32_t dv_set_material(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; for (int k = 0; k < 17; k++) o->material[k] = r32(P, a[1] + 4 * k); return D3D_OK; }
static uint32_t dv_set_light(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; unsigned i = 0; for (; i < o->nlights && o->lights[i].index != a[1]; i++) {}
    if (i == o->nlights) { if (i == 16) fail(P, "too many lights"); o->lights[o->nlights++].index = a[1]; }
    for (int k = 0; k < 26; k++) o->lights[i].l[k] = r32(P, a[2] + 4 * k);
    return D3D_OK;
}
static uint32_t dv_light_enable(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; unsigned i = 0; for (; i < o->nlight_enable && o->light_enable[i].k != a[1]; i++) {}
    if (i == o->nlight_enable) { if (i == 16) fail(P, "too many lights"); o->light_enable[o->nlight_enable++].k = a[1]; }
    o->light_enable[i].v = a[2]; return D3D_OK;
}
static uint32_t dv_set_stream(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; unsigned i = 0; for (; i < o->nstreams && o->streams[i].stream != a[1]; i++) {}
    if (i == o->nstreams) { if (i == 16) fail(P, "too many streams"); o->streams[o->nstreams++].stream = a[1]; }
    o->streams[i].buffer = a[2]; o->streams[i].stride = a[3]; return D3D_OK;
}
static uint32_t dv_set_indices(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)h; o->indices[0] = a[1]; o->indices[1] = a[2]; return D3D_OK; }
static uint32_t dv_set_vs(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)h; o->vertex_shader = a[1]; return D3D_OK; }
static uint32_t dv_set_ps(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; if (a[1]) fail(P, "SetPixelShader with a shader (the port reports no pixel shaders)"); return D3D_OK; }
static uint32_t dv_begin(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)a; (void)h; if (o->scene) return D3DERR_INVALIDCALL; o->scene = 1; return D3D_OK; }
static uint32_t dv_end(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)a; (void)h; if (!o->scene) return D3DERR_INVALIDCALL; o->scene = 0; return D3D_OK; }
static uint32_t dv_clear(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; o->clears++;
    if (P->has_renderer && P->renderer.clear) { float z; memcpy(&z, &a[5], 4); P->renderer.clear(P->renderer.user, P, a[1], a[2], a[3], a[4], z, a[6]); }
    return D3D_OK;
}
static uint32_t dv_present(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)a; (void)h; o->frames++; P->frames = o->frames;
    key_messages(P);
    if (P->has_renderer && P->renderer.present) P->renderer.present(P->renderer.user, P, P->frames);
    if (P->frames >= P->frame_limit) P->host.frames_reached(P->host.user, P->frames);
    return D3D_OK;
}
static void notify_draw(mh_port *P, int kind, const uint32_t *a, unsigned nargs) {
    if (!P->has_renderer || !P->renderer.draw) return;
    mh_port_draw_call c; memset(&c, 0, sizeof c); c.kind = kind; c.primitive = a[1];
    for (unsigned i = 2; i < nargs && i - 2 < 8; i++) c.args[i - 2] = a[i];
    P->renderer.draw(P->renderer.user, P, &c);
}
#define DRAW(n, i, nargs) static uint32_t n(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; if (!o->scene) return D3DERR_INVALIDCALL; o->draws[i]++; notify_draw(P, i, a, nargs); return D3D_OK; }
DRAW(dv_draw0, 0, 4) DRAW(dv_draw1, 1, 6) DRAW(dv_draw2, 2, 5) DRAW(dv_draw3, 3, 9)
static uint32_t dv_ok(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; (void)h; return D3D_OK; }
static uint32_t dv_texmem(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; (void)h; return 256u << 20; }
static uint32_t dv_validate(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; w32(P, a[1], 1); return D3D_OK; }
static uint32_t dv_caps(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; return d3d_get_caps_at(P, 0, 1, a[1]); }
static uint32_t dv_display_mode(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; uint32_t m[4]; if (o->params.windowed) mode(6, m); else { m[0] = o->params.width; m[1] = o->params.height; m[2] = 60; m[3] = o->params.format; }
    write_mode(P, a[1], m); return D3D_OK;
}
static uint32_t dv_creation(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; const uint32_t v[4] = {0, 1, o->params.window, o->params.flags}; for (int k = 0; k < 4; k++) w32(P, a[1] + 4 * k, v[k]); return D3D_OK; }
static uint32_t dv_gamma(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; uint8_t g[0x600]; if (!mh_mem_read(P->mem, a[2], g, sizeof g)) fail(P, "gamma ramp"); *h = 0; return 0; }
static uint32_t dv_show_cursor(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)h; uint32_t old = o->cursor_shown; o->cursor_shown = a[1]; return old; }
static uint32_t dv_cursor_pos(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)o; (void)a; *h = 0; return 0; }
static uint32_t dv_render_target(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; w32(P, a[1], give(P, o->render_target)); return D3D_OK; }
static uint32_t dv_depth_surface(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; if (!o->depth_stencil) { w32(P, a[1], 0); return 0x88760827u; }
    w32(P, a[1], give(P, o->depth_stencil)); return D3D_OK;
}
static uint32_t dv_back_buffer(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)h; if (a[1] != 0 || a[2] != 0) return D3DERR_INVALIDCALL; w32(P, a[3], give(P, o->back_buffer)); return D3D_OK; }
static uint32_t dv_create_texture(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; uint32_t width = a[1], height = a[2], levels = a[3], usage = a[4], fmt = a[5], pool = a[6], out = a[7];
    if (!width || !height || width > 2048 || height > 2048 || !out) return D3DERR_INVALIDCALL;
    int ok = usage & 1 ? is_target_format(fmt) : (is_texture_format(fmt) || is_target_format(fmt));
    if (!ok) return D3DERR_INVALIDCALL;
    level chain[16]; unsigned n = 0; uint32_t w = width, hh = height;
    for (;;) {
        uint32_t pitch, size; level_layout(P, fmt, w, hh, &pitch, &size);
        if (n == 16) fail(P, "too many texture levels");
        chain[n] = (level){w, hh, pitch, size, res_alloc(P, size), 0, ++P->serial, 0}; n++;
        if ((levels && n >= levels) || (w == 1 && hh == 1)) break;
        w = w / 2 ? w / 2 : 1; hh = hh / 2 ? hh / 2 : 1;
    }
    com_obj *t = new_object(P, iface_for(P, K_TEXTURE));
    t->device = a[0]; t->format = fmt; t->usage = usage; t->pool = pool; t->nlevels = n; memcpy(t->levels, chain, n * sizeof *chain);
    w32(P, out, t->addr); return D3D_OK;
}
static com_obj *surface_memory(mh_port *P, uint32_t s) {
    com_obj *d = object(P, s);
    if (!d->has_memory) { uint32_t pitch, size; level_layout(P, d->format, d->width, d->height, &pitch, &size); d->pitch = pitch; d->memory = res_alloc(P, size); d->has_memory = 1; }
    return d;
}
static uint32_t dv_copy_rects(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; uint32_t src = a[1], rects = a[2], count = a[3], dst = a[4], points = a[5];
    if (!object(P, src) || !object(P, dst)) return D3DERR_INVALIDCALL;
    com_obj *s = surface_memory(P, src), *d = surface_memory(P, dst);
    if (s->format != d->format) return D3DERR_INVALIDCALL;
    int dxt = s->format > 0xffff; uint32_t unit = dxt ? 4 : 1, bpp = dxt ? (s->format == DXT1 ? 8 : 16) : bytes_per_pixel(s->format);
    for (uint32_t i = 0; i < (count ? count : 1); i++) {
        uint32_t l, t, r, b;
        if (count) { l = r32(P, rects + 16 * i); t = r32(P, rects + 16 * i + 4); r = r32(P, rects + 16 * i + 8); b = r32(P, rects + 16 * i + 12); }
        else { l = 0; t = 0; r = s->width; b = s->height; }
        uint32_t px = points ? r32(P, points + 8 * i) : l, py = points ? r32(P, points + 8 * i + 4) : t;
        if (r > s->width || b > s->height || (int64_t)px + (int64_t)r - l > d->width || (int64_t)py + (int64_t)b - t > d->height) return D3DERR_INVALIDCALL;
        uint32_t row = ((r - l + unit - 1) / unit) * bpp;
        for (uint32_t y = t / unit; y < (b + unit - 1) / unit; y++) {
            uint8_t *from = mh_mem_span(P->mem, s->memory + y * s->pitch + (l / unit) * bpp, row);
            uint8_t *to = mh_mem_span(P->mem, d->memory + (py / unit + y - t / unit) * d->pitch + (px / unit) * bpp, row);
            if (row && (!from || !to)) fail(P, "CopyRects outside guest memory");
            if (row) memmove(to, from, row);
        }
    }
    d->version = ++P->serial;
    if (d->level_owner) d->level_owner->levels[d->level_index].version = P->serial;
    return D3D_OK;
}
static uint32_t dv_create_ds(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; if (!a[1] || !a[2] || !is_depth_format(a[3]) || a[4] != 0 || !a[5]) return D3DERR_INVALIDCALL;
    w32(P, a[5], new_surface(P, a[0], a[1], a[2], a[3], 2, 0)->addr); return D3D_OK;
}
static uint32_t dv_create_rt(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; if (!a[1] || !a[2] || !is_target_format(a[3]) || a[4] != 0 || !a[6]) return D3DERR_INVALIDCALL;
    w32(P, a[6], new_surface(P, a[0], a[1], a[2], a[3], 1, 0)->addr); return D3D_OK;
}
static uint32_t dv_create_image(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; if (!a[1] || !a[2] || !a[4] || !(is_texture_format(a[3]) || is_target_format(a[3]))) return D3DERR_INVALIDCALL;
    w32(P, a[4], new_surface(P, a[0], a[1], a[2], a[3], 0, 2)->addr); return D3D_OK;
}
static uint32_t dv_set_rt(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)P; (void)h; if (a[1]) o->render_target = a[1]; o->depth_stencil = a[2]; return D3D_OK; }
static uint32_t dv_create_vb(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; return create_buffer(P, a[0], K_VBUF, a[1], a[2], 100, a[3], a[4], a[5]); }
static uint32_t dv_create_ib(mh_port *P, com_obj *o, const uint32_t *a, int *h) { (void)o; (void)h; return create_buffer(P, a[0], K_IBUF, a[1], a[2], a[3], 0, a[4], a[5]); }
static window *find_window(mh_port *P, uint32_t h);
static int presentation(mh_port *P, uint32_t ppp, uint32_t hwnd, present_params *out, uint32_t *hr) {
    uint32_t pp[13]; for (int i = 0; i < 13; i++) pp[i] = r32(P, ppp + 4 * i);
    uint32_t width = pp[0], height = pp[1], fmt = pp[2], count = pp[3], ms = pp[4], swap = pp[5], devwin = pp[6], windowed = pp[7], autodepth = pp[8], depthfmt = pp[9];
    uint32_t win = devwin ? devwin : hwnd; window *w = find_window(P, win);
    if (!w || ms != 0 || count > 1 || (autodepth && !is_depth_format(depthfmt))) { *hr = D3DERR_INVALIDCALL; return 0; }
    if (windowed) {
        if (!width) width = (uint32_t)(w->rect[2] - w->rect[0]);
        if (!height) height = (uint32_t)(w->rect[3] - w->rect[1]);
        if (fmt == 0) fmt = X8R8G8B8;
    } else {
        uint32_t refresh = (pp[11] == 0 || pp[11] == 60) ? 60 : pp[11]; int found = 0;
        for (unsigned i = 0; i < 12; i++) { uint32_t m[4]; mode(i, m); if (m[0] == width && m[1] == height && m[2] == refresh && m[3] == fmt) found = 1; }
        if (!found) { *hr = D3DERR_INVALIDCALL; return 0; }
    }
    if (!is_target_format(fmt)) { *hr = D3DERR_NOTAVAILABLE; return 0; }
    w32(P, ppp, width); w32(P, ppp + 4, height); w32(P, ppp + 8, fmt); w32(P, ppp + 12, count > 1 ? count : 1);
    *out = (present_params){width, height, fmt, windowed, autodepth ? depthfmt : 0, swap, win, pp[11], pp[12], 0};
    return 1;
}
static void attach_buffers(mh_port *P, com_obj *dev) {
    present_params *p = &dev->params;
    dev->back_buffer = new_surface(P, dev->addr, p->width, p->height, p->format, 1, 0)->addr;
    dev->render_target = dev->back_buffer;
    dev->depth_stencil = p->depth ? new_surface(P, dev->addr, p->width, p->height, p->depth, 2, 0)->addr : 0;
}
static uint32_t dv_reset(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)h; present_params p; uint32_t hr;
    if (!presentation(P, a[1], o->params.window, &p, &hr)) return hr;
    p.flags = o->params.flags; o->params = p;
    memset(o->rs_set, 0, sizeof o->rs_set); memset(o->tss_set, 0, sizeof o->tss_set); o->ntransforms = 0;
    memset(o->textures, 0, sizeof o->textures); o->nstreams = 0; o->has_viewport = 0; o->resets++;
    attach_buffers(P, o); return D3D_OK;
}
static const com_method DEVICE_METHODS[] = {
    {"QueryInterface",3,0},{"AddRef",1,addref},{"Release",1,release},{"TestCooperativeLevel",1,dv_ok},{"GetAvailableTextureMem",1,dv_texmem},
    {"ResourceManagerDiscardBytes",2,dv_ok},{"GetDirect3D",2,0},{"GetDeviceCaps",2,dv_caps},{"GetDisplayMode",2,dv_display_mode},{"GetCreationParameters",2,dv_creation},
    {"SetCursorProperties",4,0},{"SetCursorPosition",4,dv_cursor_pos},{"ShowCursor",2,dv_show_cursor},{"CreateAdditionalSwapChain",3,0},{"Reset",2,dv_reset},{"Present",5,dv_present},
    {"GetBackBuffer",4,dv_back_buffer},{"GetRasterStatus",2,0},{"SetGammaRamp",3,dv_gamma},{"GetGammaRamp",2,0},{"CreateTexture",8,dv_create_texture},{"CreateVolumeTexture",9,0},
    {"CreateCubeTexture",7,0},{"CreateVertexBuffer",6,dv_create_vb},{"CreateIndexBuffer",6,dv_create_ib},{"CreateRenderTarget",7,dv_create_rt},{"CreateDepthStencilSurface",6,dv_create_ds},
    {"CreateImageSurface",5,dv_create_image},{"CopyRects",6,dv_copy_rects},{"UpdateTexture",3,0},{"GetFrontBuffer",2,0},{"SetRenderTarget",3,dv_set_rt},{"GetRenderTarget",2,dv_render_target},
    {"GetDepthStencilSurface",2,dv_depth_surface},{"BeginScene",1,dv_begin},{"EndScene",1,dv_end},{"Clear",7,dv_clear},{"SetTransform",3,dv_set_transform},{"GetTransform",3,dv_get_transform},{"MultiplyTransform",3,0},
    {"SetViewport",2,dv_set_viewport},{"GetViewport",2,dv_get_viewport},{"SetMaterial",2,dv_set_material},{"GetMaterial",2,0},{"SetLight",3,dv_set_light},{"GetLight",3,0},{"LightEnable",3,dv_light_enable},
    {"GetLightEnable",3,0},{"SetClipPlane",3,0},{"GetClipPlane",3,0},{"SetRenderState",3,dv_set_rs},{"GetRenderState",3,dv_get_rs},{"BeginStateBlock",1,0},
    {"EndStateBlock",2,0},{"ApplyStateBlock",2,0},{"CaptureStateBlock",2,0},{"DeleteStateBlock",2,0},{"CreateStateBlock",3,0},{"SetClipStatus",2,0},
    {"GetClipStatus",2,0},{"GetTexture",3,dv_get_texture},{"SetTexture",3,dv_set_texture},{"GetTextureStageState",4,dv_get_tss},{"SetTextureStageState",4,dv_set_tss},{"ValidateDevice",2,dv_validate},
    {"GetInfo",4,0},{"SetPaletteEntries",3,0},{"GetPaletteEntries",3,0},{"SetCurrentTexturePalette",2,0},{"GetCurrentTexturePalette",2,0},
    {"DrawPrimitive",4,dv_draw0},{"DrawIndexedPrimitive",6,dv_draw1},{"DrawPrimitiveUP",5,dv_draw2},{"DrawIndexedPrimitiveUP",9,dv_draw3},{"ProcessVertices",6,0},
    {"CreateVertexShader",5,0},{"SetVertexShader",2,dv_set_vs},{"GetVertexShader",2,0},{"DeleteVertexShader",2,0},{"SetVertexShaderConstant",4,0},
    {"GetVertexShaderConstant",4,0},{"GetVertexShaderDeclaration",4,0},{"GetVertexShaderFunction",4,0},{"SetStreamSource",4,dv_set_stream},
    {"GetStreamSource",4,0},{"SetIndices",3,dv_set_indices},{"GetIndices",3,0},{"CreatePixelShader",3,0},{"SetPixelShader",2,dv_set_ps},{"GetPixelShader",2,0},
    {"DeletePixelShader",2,0},{"SetPixelShaderConstant",4,0},{"GetPixelShaderConstant",4,0},{"GetPixelShaderFunction",4,0},
    {"DrawRectPatch",4,0},{"DrawTriPatch",4,0},{"DeletePatch",2,0}};
static uint32_t d3d_create_device(mh_port *P, com_obj *o, const uint32_t *a, int *h) {
    (void)o; (void)h; uint32_t adapter = a[1], type = a[2], hwnd = a[3], flags = a[4], ppp = a[5], out = a[6];
    if (adapter != 0 || type != 1 || !out || !(flags & 0x70)) return D3DERR_INVALIDCALL;
    present_params p; uint32_t hr;
    if (!presentation(P, ppp, hwnd, &p, &hr)) return hr;
    p.flags = flags;
    com_obj *dev = new_object(P, iface_for(P, K_DEVICE));
    dev->params = p; attach_buffers(P, dev); P->device = dev; w32(P, out, dev->addr); return D3D_OK;
}
static const com_method D3D8_METHODS[] = {
    {"QueryInterface",3,d3d_qi},{"AddRef",1,addref},{"Release",1,release},{"RegisterSoftwareDevice",2,0},{"GetAdapterCount",1,d3d_count},
    {"GetAdapterIdentifier",4,d3d_identifier},{"GetAdapterModeCount",2,d3d_mode_count},{"EnumAdapterModes",4,d3d_enum_modes},
    {"GetAdapterDisplayMode",3,d3d_display_mode},{"CheckDeviceType",6,d3d_check_type},{"CheckDeviceFormat",7,d3d_check_format},
    {"CheckDeviceMultiSampleType",6,d3d_check_ms},{"CheckDepthStencilMatch",6,d3d_check_depth},{"GetDeviceCaps",4,d3d_get_caps},
    {"GetAdapterMonitor",2,0},{"CreateDevice",7,d3d_create_device}};

#define DESC(n, m) {n, m, sizeof m / sizeof m[0]}
static const com_iface_desc DESCS[K_KINDS] = {
    DESC("IDirectInputDevice8A", DIDEVICE_METHODS), DESC("IDirectInput8A", DINPUT_METHODS), DESC("IDirect3D8", D3D8_METHODS),
    DESC("IDirect3DDevice8", DEVICE_METHODS), DESC("IDirect3DSurface8", SURFACE_METHODS), DESC("IDirect3DVertexBuffer8", BUFFER_METHODS),
    DESC("IDirect3DIndexBuffer8", BUFFER_METHODS), DESC("IDirect3DTexture8", TEXTURE_METHODS)};
static const com_iface_desc *iface_desc(int kind) { return &DESCS[kind]; }

int mh_port_is_com(uint32_t va) { return va >= MH_PORT_COM_VA && va < MH_PORT_COM_VA + 0x400u * 16; }
void mh_port_call_com(mh_port *P, uint32_t va, uint32_t esp, uint32_t *eax, int *has_eax, uint32_t *pop, const char **label) {
    static char text[96];
    uint32_t index = (va - MH_PORT_COM_VA) / 0x400u, method = ((va - MH_PORT_COM_VA) % 0x400u) / 4u;
    if (index >= P->nifaces || (va & 3)) fail(P, "unknown COM address 0x%08x", va);
    const com_iface_desc *d = iface_desc(P->ifaces[index].kind);
    if (method >= d->count) fail(P, "%s method %u", d->name, method);
    const com_method *m = &d->methods[method]; uint32_t a[12];
    for (unsigned i = 0; i < m->nargs; i++) a[i] = r32(P, esp + 4 + 4 * i);
    com_obj *o = object(P, a[0]);
    if (!o || o->iface != (int)index) fail(P, "%s::%s on a bad object 0x%08x", d->name, m->name, a[0]);
    if (!m->fn) fail(P, "%s::%s not implemented", d->name, m->name);
    snprintf(text, sizeof text, "%s::%s", d->name, m->name);
    if (label) *label = text;
    *has_eax = 1; *eax = m->fn(P, o, a, has_eax); *pop = 4 + 4 * m->nargs;
}

/* ---------------------------------------------------------------- Win32 APIs */
typedef uint32_t (*api_handler)(mh_port *, const uint32_t *, int *);
#define API(n) static uint32_t n(mh_port *P, const uint32_t *a, int *h)
#define UNUSED (void)P; (void)a; (void)h
/* phase 2 (the handlers of tools/trace_static_init_x86.py) */
API(enter_cs) { (void)h; if (!mh_win32_enter_critical_section(P->mem, a[0], THREAD_ID)) fail(P, "EnterCriticalSection would block"); *h = 0; return 0; }
API(leave_cs) { (void)h; if (!mh_win32_leave_critical_section(P->mem, a[0], THREAD_ID)) fail(P, "LeaveCriticalSection by a non-owner"); *h = 0; return 0; }
API(init_cs) { mh_win32_init_critical_section(P->mem, a[0]); *h = 0; return 0; }
API(delete_cs) { (void)P; (void)a; *h = 0; return 0; }
API(global_alloc) { (void)h; return mh_win32_global_alloc(&P->global, P->mem, a[0], a[1]); }
API(global_free) { UNUSED; return 0; }
API(tls_alloc) { (void)a; (void)h; return mh_win32_tls_alloc(&P->thread); }
API(tls_free) { (void)h; return (uint32_t)mh_win32_tls_free(&P->thread, a[0]); }
API(tls_get) { (void)h; return mh_win32_tls_get_value(&P->thread, a[0]); }
API(tls_set) { (void)h; return (uint32_t)mh_win32_tls_set_value(&P->thread, a[0], a[1]); }
API(get_std_handle) { (void)P; (void)h; return mh_win32_get_std_handle(a[0]); }
API(get_current_process) { UNUSED; return mh_win32_get_current_process(); }
API(duplicate_handle) { (void)h; int r = mh_win32_duplicate_handle(&P->thread, a[1]); if (r < 0) fail(P, "DuplicateHandle of a real handle is not modelled"); return (uint32_t)r; }
API(get_command_line) { (void)a; (void)h; return mh_win32_get_command_line(&P->process); }
API(get_environment) { (void)a; (void)h; return mh_win32_get_environment_strings(&P->process); }
API(free_environment) { (void)h; return mh_win32_free_environment_strings(&P->process, a[0]); }
API(create_event) { (void)a; (void)h; return mh_win32_create_event(&P->process); }
API(get_tick_count) { UNUSED; return 0x10000; }
/* WinMain */
API(system_parameters) { UNUSED; return 1; }
API(time_get_time) { (void)a; (void)h; return (uint32_t)tick(P); }
API(time_period) { UNUSED; return 0; }
API(qpf) { (void)h; w32(P, a[0], 1000000); w32(P, a[0] + 4, 0); return 1; }
API(qpc) { (void)h; uint64_t us = tick(P) * 1000; w32(P, a[0], (uint32_t)us); w32(P, a[0] + 4, (uint32_t)(us >> 32)); return 1; }
API(lang) { UNUSED; return P->langid; }
API(set_error_mode) { (void)h; uint32_t old = P->error_mode; P->error_mode = a[0]; return old; }
API(get_module_file_name) {
    (void)h; static const char path[] = MH_PORT_GAME_DIR "manhunt.exe"; uint32_t len = sizeof path - 1;
    if (a[0] != 0 && a[0] != MH_PORT_IMAGE_BASE) fail(P, "GetModuleFileNameA for module 0x%x", a[0]);
    if (a[2] > len) { wbytes(P, a[1], path, len + 1); return len; }
    if (a[2]) { wbytes(P, a[1], path, a[2]); *mh_port_last_error(P) = 122; }
    return a[2];
}
static int inside_game(const char *path) {
    char p[MAXPATH]; snprintf(p, sizeof p, "%s", path); slashes(p); rstrip_bs(p);
    char root[64]; snprintf(root, sizeof root, "%s", MH_PORT_GAME_DIR); rstrip_bs(root);
    return ieq(p, root) || istarts(p, MH_PORT_GAME_DIR);
}
API(set_current_directory) {
    (void)h; char path[MAXPATH]; cstr(P, a[0], path, 260);
    if (!inside_game(path)) {
        if (strchr(path, ':') || path[0] == '\\') { *mh_port_last_error(P) = 3; return 0; }
        fail(P, "SetCurrentDirectoryA with relative path '%s'", path);
    }
    snprintf(P->cwd, sizeof P->cwd, "%s", path); slashes(P->cwd); rstrip_bs(P->cwd); return 1;
}
API(get_current_directory) {
    (void)h; uint32_t len = (uint32_t)strlen(P->cwd);
    if (a[0] > len) { wbytes(P, a[1], P->cwd, len + 1); return len; }
    return len + 1;
}
API(set_env) {
    (void)h; char name[300], key[300]; cstr(P, a[0], name, 260);
    if (!name[0] || strchr(name + 1, '=')) { *mh_port_last_error(P) = 87; return 0; }
    snprintf(key, sizeof key, "%s", name); upper(key);
    unsigned i = 0; for (; i < P->nenv && strcmp(P->env[i].key, key); i++) {}
    if (a[1]) {
        if (i == P->nenv) { if (i == 16) fail(P, "too many environment variables"); P->nenv++; }
        snprintf(P->env[i].key, sizeof P->env[i].key, "%s", key); snprintf(P->env[i].name, sizeof P->env[i].name, "%s", name);
        cstr(P, a[1], P->env[i].value, sizeof P->env[i].value - 1);
    } else if (i < P->nenv) { memmove(&P->env[i], &P->env[i + 1], (P->nenv - i - 1) * sizeof *P->env); P->nenv--; }
    return 1;
}
API(get_env) {
    (void)h; char key[300]; cstr(P, a[0], key, 260); upper(key);
    for (unsigned i = 0; i < P->nenv; i++) if (!strcmp(P->env[i].key, key)) {
        uint32_t len = (uint32_t)strlen(P->env[i].value);
        if (a[2] > len) { wbytes(P, a[1], P->env[i].value, len + 1); return len; }
        return len + 1;
    }
    *mh_port_last_error(P) = 203; return 0;
}
API(load_cursor) { (void)h; if (a[0] != 0 || a[1] > 0xffff) fail(P, "LoadCursorA(0x%x, 0x%x): only system cursors", a[0], a[1]); return 0x60000000u | a[1]; }
API(register_class) {
    (void)h; uint32_t w[10]; for (int i = 0; i < 10; i++) w[i] = r32(P, a[0] + 4 * i);
    char name[300], key[300];
    if (w[9] > 0xffff) cstr(P, w[9], name, 260); else snprintf(name, sizeof name, "#%u", w[9]);
    snprintf(key, sizeof key, "%s", name); upper(key);
    for (unsigned i = 0; i < P->nclasses; i++) if (!strcmp(P->classes[i].key, key)) { *mh_port_last_error(P) = 1410; return 0; }
    if (P->nclasses == 8) fail(P, "too many window classes");
    wclass *c = &P->classes[P->nclasses]; uint32_t atom = 0xC000 + P->nclasses++;
    snprintf(c->key, sizeof c->key, "%s", key); snprintf(c->name, sizeof c->name, "%s", name);
    c->atom = atom; c->wndproc = w[1]; c->style = w[0]; c->extra0 = w[2]; c->extra1 = w[3]; c->hinst = w[4];
    return atom;
}
API(get_system_metrics) {
    (void)h; static const int32_t m[][2] = {{0,1280},{1,720},{4,0},{5,0},{6,0},{7,0},{8,0},{15,0},{32,0},{33,0},{16,1280},{17,720},{61,1280},{62,720},{78,1280},{79,720},{80,1}};
    for (unsigned i = 0; i < sizeof m / sizeof m[0]; i++) if ((uint32_t)m[i][0] == a[0]) return (uint32_t)m[i][1];
    fail(P, "GetSystemMetrics(%u)", a[0]); return 0;
}
static int32_t clamp(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : v > hi ? hi : v; }
API(set_cursor_pos) { (void)h; P->cursor.x = clamp(s32(a[0]), 0, 1279); P->cursor.y = clamp(s32(a[1]), 0, 719); return 1; }
API(get_cursor_pos) { (void)h; w32(P, a[0], (uint32_t)P->cursor.x); w32(P, a[0] + 4, (uint32_t)P->cursor.y); return 1; }
API(show_cursor) { (void)h; P->cursor.count += a[0] ? 1 : -1; return (uint32_t)P->cursor.count; }
API(set_cursor) { (void)h; uint32_t old = P->cursor.handle; P->cursor.handle = a[0]; return old; }
API(clip_cursor) { (void)h; P->cursor.clip = a[0] != 0; if (a[0]) for (int i = 0; i < 4; i++) P->cursor.cliprect[i] = r32(P, a[0] + 4 * i); return 1; }
API(adjust_window_rect) { UNUSED; return 1; }
static window *find_window(mh_port *P, uint32_t h) { for (unsigned i = 0; i < P->nwindows; i++) if (P->windows[i].hwnd == h) return &P->windows[i]; return NULL; }
static window *need_window(mh_port *P, uint32_t h) { window *w = find_window(P, h); if (!w) fail(P, "unknown window 0x%x", h); return w; }
static window *add_window(mh_port *P, uint32_t hwnd) {
    window *w = find_window(P, hwnd);   /* a dict assignment: an existing key is overwritten */
    if (!w) { if (P->nwindows == 16) fail(P, "too many windows"); w = &P->windows[P->nwindows++]; }
    memset(w, 0, sizeof *w); w->hwnd = hwnd; return w;
}
static void remove_window(mh_port *P, uint32_t hwnd) {
    for (unsigned i = 0; i < P->nwindows; i++) if (P->windows[i].hwnd == hwnd) { memmove(&P->windows[i], &P->windows[i + 1], (P->nwindows - i - 1) * sizeof *P->windows); P->nwindows--; return; }
}
#define WM_CREATE 1u
#define WM_MOVE 3u
#define WM_SIZE 5u
#define WM_ACTIVATE 6u
#define WM_SETFOCUS 7u
#define WM_ACTIVATEAPP 0x1cu
#define WM_TIMER 0x113u
#define WM_QUIT 0x12u
#define WM_INITDIALOG 0x110u
#define WM_COMMAND 0x111u
static uint32_t cb4(mh_port *P, uint32_t fn, uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3) { const uint32_t args[4] = {a0, a1, a2, a3}; return call_guest(P, fn, args, 4); }
API(create_window) {
    (void)h; uint32_t exstyle = a[0], cls = a[1], title = a[2], style = a[3], x = a[4], y = a[5], w = a[6], hh = a[7], parent = a[8], menu = a[9], hinst = a[10], param = a[11];
    char name[300] = ""; wclass *klass = NULL;
    if (cls > 0xffff) cstr(P, cls, name, 260);
    else for (unsigned i = 0; i < P->nclasses; i++) if (P->classes[i].atom == cls) snprintf(name, sizeof name, "%s", P->classes[i].name);
    char key[300]; snprintf(key, sizeof key, "%s", name); upper(key);
    for (unsigned i = 0; i < P->nclasses; i++) if (!strcmp(P->classes[i].key, key)) klass = &P->classes[i];
    if (!klass) { *mh_port_last_error(P) = 1407; return 0; }
    if (parent || menu) fail(P, "CreateWindowExA with a parent or menu");
    if (x == 0x80000000u) x = y = 0;
    if (w == 0x80000000u) fail(P, "CreateWindowExA with CW_USEDEFAULT size");
    uint32_t hwnd = 0x00020000u + 4 * P->nwindows; window *win = add_window(P, hwnd);
    snprintf(win->cls, sizeof win->cls, "%s", klass->name); win->wndproc = klass->wndproc; win->style = style; win->exstyle = exstyle;
    win->rect[0] = x; win->rect[1] = y; win->rect[2] = (int64_t)x + w; win->rect[3] = (int64_t)y + hh;
    if (title) cstr(P, title, win->title, 260);
    win->visible = (style & 0x10000000u) != 0;
    const uint32_t cs[12] = {param, hinst, menu, parent, hh, w, y, x, style, title, cls, exstyle};
    for (int i = 0; i < 12; i++) w32(P, MH_PORT_SCRATCH + 4 * i, cs[i]);
    uint32_t wndproc = klass->wndproc;
    uint32_t r0 = cb4(P, wndproc, hwnd, WM_CREATE, 0, MH_PORT_SCRATCH);
    cb4(P, wndproc, hwnd, WM_SIZE, 0, lparam(w, hh));
    cb4(P, wndproc, hwnd, WM_MOVE, 0, lparam(x, y));
    if (r0 == 0xffffffffu) { remove_window(P, hwnd); return 0; }
    return hwnd;
}
API(def_window_proc) { (void)h; if (a[1] == 0x10) fail(P, "DefWindowProcA for message 0x%x", a[1]); return 0; }
#define KERNEL32 0x7ff00000u
API(get_module_handle) {
    (void)h; if (a[0] == 0) return MH_PORT_IMAGE_BASE;
    char name[300]; cstr(P, a[0], name, 260); lower(name); slashes(name);
    const char *last = strrchr(name, '\\'); last = last ? last + 1 : name;
    if (!strcmp(last, "manhunt.exe") || !strcmp(last, "manhunt")) return MH_PORT_IMAGE_BASE;
    if (!strcmp(last, "kernel32.dll") || !strcmp(last, "kernel32")) return KERNEL32;
    fail(P, "GetModuleHandleA('%s')", last); return 0;
}
/* kernel32 is a pseudo module: GetProcAddress resolves only functions the executable also imports
 * (the result is that import's address), as the reference does. */
API(get_proc_address) {
    (void)h; char name[300] = "";
    if (a[1] > 0xffff) cstr(P, a[1], name, 260);
    if (a[0] == KERNEL32 && !strcmp(name, "GetDiskFreeSpaceExA")) return r32(P, 0x81b3c8);
    fail(P, "GetProcAddress(0x%x, '%s')", a[0], name); return 0;
}
/* Save space: 8 GiB free of 16 GiB, for any directory. */
API(get_disk_free_space) {
    (void)h; const uint64_t v[3] = {8ull << 30, 16ull << 30, 8ull << 30};
    for (int i = 0; i < 3; i++) if (a[1 + i]) { w32(P, a[1 + i], (uint32_t)v[i]); w32(P, a[1 + i] + 4, (uint32_t)(v[i] >> 32)); }
    return 1;
}
/* files */
#define INVALID_HANDLE 0xffffffffu
/* Writable overlay files (saves), as the reference: in memory, keyed by the case-folded full guest
 * path; the original data is never written. With a save directory (the app's private storage) each
 * file is also kept there: loaded when first looked up, rewritten when its handle is closed. */
static void guest_key(mh_port *P, const char *name, char *key, size_t size) {
    char p[MAXPATH * 2]; snprintf(p, sizeof p, "%s", name); slashes(p);
    if (!(strlen(p) > 1 && p[1] == ':') && p[0] != '\\') snprintf(key, size, "%s\\%s", P->cwd, p); else snprintf(key, size, "%s", p);
    lower(key);
}
static int save_path(mh_port *P, const char *key, char *out, size_t size) {   /* save_dir/<path below the game folder, '\\' -> '_'> */
    if (!istarts(key, MH_PORT_GAME_DIR) || !key[strlen(MH_PORT_GAME_DIR)]) return 0;
    const char *rel = key + strlen(MH_PORT_GAME_DIR); while (*rel == '\\') rel++;
    int n = snprintf(out, size, "%s" SEP "%s", P->save_dir, rel);
    if (n < 0 || (size_t)n >= size) return 0;
    for (char *c = out + strlen(P->save_dir) + 1; *c; c++) if (*c == '\\') *c = '_';
    return 1;
}
static ovfile *ov_add(mh_port *P, const char *key) {
    if (P->novfiles == P->capovfiles) { P->capovfiles = P->capovfiles ? 2 * P->capovfiles : 8; P->ovfiles = realloc(P->ovfiles, P->capovfiles * sizeof *P->ovfiles); }
    ovfile *o = &P->ovfiles[P->novfiles++]; memset(o, 0, sizeof *o); snprintf(o->key, sizeof o->key, "%s", key); return o;
}
static int ov_find(mh_port *P, const char *key) {   /* index + 1, or 0 */
    for (unsigned i = P->novfiles; i-- > 0;)   /* the latest entry; a deleted one is a tombstone (not reloaded) */
        if (!strcmp(P->ovfiles[i].key, key)) return P->ovfiles[i].deleted ? 0 : (int)i + 1;
    if (!P->save_dir[0]) return 0;
    char path[MAXPATH * 3]; if (!save_path(P, key, path, sizeof path)) return 0;
    FILE *fp = fopen(path, "rb"); if (!fp) return 0;
    ovfile *o = ov_add(P, key); uint8_t chunk[4096]; size_t got;
    while ((got = fread(chunk, 1, sizeof chunk, fp)) > 0) {
        if (o->size + got > o->cap) { o->cap = (o->size + got) * 2; o->data = realloc(o->data, o->cap); }
        memcpy(o->data + o->size, chunk, got); o->size += got;
    }
    fclose(fp); return (int)P->novfiles;
}
static uint32_t save_error(int error) {
    return error == ENOSPC ? 112u : error == EACCES ? 5u : error == ENOENT ? 3u : 29u;
}
/* Write a sibling temporary file and replace only after a complete, flushed write. The previous
 * save remains intact on any failure before the replacement. The guest uses a single thread. */
static uint32_t ov_store(mh_port *P, int ov) {
    if (!P->save_dir[0] || !ov || P->save_readonly) return 0;
    ovfile *o = &P->ovfiles[ov - 1]; char path[MAXPATH * 3], temporary[MAXPATH * 3 + 8];
    if (!save_path(P, o->key, path, sizeof path)) return 123;
    snprintf(temporary, sizeof temporary, "%s.tmp", path);
    FILE *fp = fopen(temporary, "wb"); if (!fp) return save_error(errno);
    uint32_t error = 0;
    if (o->size > SIZE_MAX || (o->size && fwrite(o->data, 1, (size_t)o->size, fp) != o->size)) error = save_error(errno);
    if (!error && fflush(fp)) error = save_error(errno);
#ifdef _WIN32
    if (!error && _commit(_fileno(fp))) error = save_error(errno);
#else
    if (!error && fsync(fileno(fp))) error = save_error(errno);
#endif
    if (fclose(fp) && !error) error = save_error(errno);
    if (!error) {
#ifdef _WIN32
        if (!MoveFileExA(temporary, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) error = GetLastError();
#else
        if (rename(temporary, path)) error = save_error(errno);
#endif
    }
    if (error) remove(temporary);
    return error;
}
static int overlay_dir(mh_port *P, const char *key) { for (unsigned i = 0; i < P->noverlay; i++) if (!strcmp(P->overlay[i], key)) return 1; return 0; }
static gfile *new_file(mh_port *P, uint32_t *handle) {
    if (P->nfiles == P->capfiles) { P->capfiles = P->capfiles ? 2 * P->capfiles : 64; P->files = realloc(P->files, P->capfiles * sizeof *P->files); }
    gfile *f = &P->files[P->nfiles]; *handle = 0x00F00004u + 4 * P->nfiles++; memset(f, 0, sizeof *f); f->h = *handle; return f;
}
API(create_file) {
    (void)h; char name[MAXPATH + 1], host[MAXPATH * 2], key[MAXPATH * 2]; uint32_t err, handle, disp = a[4]; cstr(P, a[0], name, MAXPATH);
    guest_key(P, name, key, sizeof key);
    int ov = ov_find(P, key);
    if ((a[1] & 0x40000000u) || (disp != 3 && disp != 4) || ov) {
        char parent[MAXPATH * 2]; snprintf(parent, sizeof parent, "%s", key); char *cut = strrchr(parent, '\\'); if (cut) *cut = 0;
        int parent_ok = overlay_dir(P, parent) || (resolve(P, parent, host, sizeof host, &err) && host_isdir(host));
        if (!istarts(key, MH_PORT_GAME_DIR) || !parent_ok) { *mh_port_last_error(P) = 3; return INVALID_HANDLE; }
        if (resolve(P, name, host, sizeof host, &err) && (host_isfile(host) || host_isdir(host))) fail(P, "CreateFileA writing original data: '%s'", name);
        int exists = ov != 0;
        if (disp == 1 && exists) { *mh_port_last_error(P) = 80; return INVALID_HANDLE; }
        if ((disp == 3 || disp == 5) && !exists) { *mh_port_last_error(P) = 2; return INVALID_HANDLE; }
        if (disp < 1 || disp > 5) { *mh_port_last_error(P) = 87; return INVALID_HANDLE; }
        if (!exists) { ovfile *o = ov_add(P, key); o->created = o->written = P->clock; ov = (int)P->novfiles; }
        else if (disp == 1 || disp == 2 || disp == 5) P->ovfiles[ov - 1].size = 0;
        gfile *f = new_file(P, &handle); f->ov = ov; snprintf(f->guest, sizeof f->guest, "%s", name);
        f->open = 1; f->overlapped = (a[5] & 0x40000000u) != 0;
        f->written = !exists || disp == 2 || disp == 5;
        *mh_port_last_error(P) = exists && (disp == 2 || disp == 4) ? 183 : 0; return handle;
    }
    if (!resolve(P, name, host, sizeof host, &err) || !host_isfile(host)) { *mh_port_last_error(P) = err ? err : 2; return INVALID_HANDLE; }
    gfile *f = new_file(P, &handle);
    snprintf(f->path, sizeof f->path, "%s", host); snprintf(f->guest, sizeof f->guest, "%s", name);
    f->size = host_size(host); f->open = 1; f->overlapped = (a[5] & 0x40000000u) != 0;
    *mh_port_last_error(P) = 0; return handle;
}
static uint64_t file_size(mh_port *P, const gfile *f) { return f->ov ? P->ovfiles[f->ov - 1].size : f->size; }
static gfile *file(mh_port *P, uint32_t h) {
    if (h < 0x00F00004u || ((h - 0x00F00004u) & 3)) return NULL;
    uint32_t i = (h - 0x00F00004u) / 4; return i < P->nfiles && P->files[i].open ? &P->files[i] : NULL;
}
API(read_file) {
    (void)h; uint32_t buf = a[1], n = a[2], pread = a[3], pov = a[4]; gfile *f = file(P, a[0]);
    if (!f) { *mh_port_last_error(P) = 6; return 0; }
    uint64_t offset = pov ? ((uint64_t)r32(P, pov + 8) | (uint64_t)r32(P, pov + 12) << 32) : f->pos;
    size_t got = 0;
    if (f->ov) {
        const ovfile *o = &P->ovfiles[f->ov - 1];
        if (offset < o->size && n) {
            got = (size_t)(o->size - offset < n ? o->size - offset : n);
            uint8_t *dest = mh_mem_span(P->mem, buf, (uint32_t)got);
            if (!dest) fail(P, "ReadFile buffer outside guest memory");
            memcpy(dest, o->data + offset, got);
        }
        goto done;
    }
    FILE *fp = fopen(f->path, "rb");
    if (!fp) fail(P, "cannot reopen %s", f->path);
    if (offset < f->size && n) {
        uint8_t *dest = mh_mem_span(P->mem, buf, n);
        if (!dest) fail(P, "ReadFile buffer outside guest memory");
#ifdef _WIN32
        _fseeki64(fp, (long long)offset, SEEK_SET);
#else
        fseeko(fp, (off_t)offset, SEEK_SET);
#endif
        got = fread(dest, 1, n, fp);
    }
    fclose(fp);
done:
    if (pread) w32(P, pread, (uint32_t)got);
    if (pov) {
        w32(P, pov, 0); w32(P, pov + 4, (uint32_t)got);
        if (!got && n) { *mh_port_last_error(P) = 38; return 0; }
    } else f->pos = offset + got;
    return 1;
}
API(write_file) {
    (void)h; uint32_t buf = a[1], n = a[2], pwritten = a[3], pov = a[4]; gfile *f = file(P, a[0]);
    if (!f) { *mh_port_last_error(P) = 6; return 0; }
    if (!f->ov) fail(P, "WriteFile to original data: '%s'", f->guest);
    uint64_t offset = pov ? ((uint64_t)r32(P, pov + 8) | (uint64_t)r32(P, pov + 12) << 32) : f->pos;
    ovfile *o = &P->ovfiles[f->ov - 1];
    if (offset + n > o->cap) { o->cap = (offset + n) * 2; o->data = realloc(o->data, o->cap); }
    if (offset > o->size) memset(o->data + o->size, 0, offset - o->size);
    if (n) { const uint8_t *src = mh_mem_span(P->mem, buf, n); if (!src) fail(P, "WriteFile buffer outside guest memory"); memcpy(o->data + offset, src, n); }
    if (offset + n > o->size) o->size = offset + n;
    o->written = P->clock;
    f->written = 1;
    if (pwritten) w32(P, pwritten, n);
    if (pov) { w32(P, pov, 0); w32(P, pov + 4, n); }
    else f->pos = offset + n;
    return 1;
}
/* File times: FILE_EPOCH (2004-01-01 00:00 UTC as a FILETIME) plus the virtual clock (ms) when an
 * overlay file was created / last written; original data: FILE_EPOCH (as the reference). */
#define FILE_EPOCH ((1072915200ull + 11644473600ull) * 10000000ull)
API(get_file_information) {
    (void)h; gfile *f = file(P, a[0]);
    if (!f) { *mh_port_last_error(P) = 6; return 0; }
    uint64_t created = 0, written = 0, size = f->size; uint32_t attr = 0x01, index = 0;
    if (f->ov) { const ovfile *o = &P->ovfiles[f->ov - 1]; created = o->created; written = o->written; size = o->size; attr = 0x20; index = (uint32_t)f->ov; }
    uint32_t info[13] = {attr}; const uint64_t ms[3] = {created, written, written};
    for (int i = 0; i < 3; i++) { uint64_t t = FILE_EPOCH + ms[i] * 10000u; info[1 + 2 * i] = (uint32_t)t; info[2 + 2 * i] = (uint32_t)(t >> 32); }
    info[7] = 0x4d480001u; info[8] = (uint32_t)(size >> 32); info[9] = (uint32_t)size; info[10] = 1; info[11] = 0; info[12] = index;
    for (int i = 0; i < 13; i++) w32(P, a[1] + 4 * i, info[i]);
    return 1;
}
API(file_time_to_local) { (void)h; w32(P, a[1], r32(P, a[0])); w32(P, a[1] + 4, r32(P, a[0] + 4)); return 1; }   /* local time zone: UTC */
API(file_time_to_system) {
    (void)h; uint64_t t = (uint64_t)r32(P, a[0]) | (uint64_t)r32(P, a[0] + 4) << 32;
    if (t >> 63) { *mh_port_last_error(P) = 87; return 0; }
    int64_t ms_total = (int64_t)(t / 10000), days = ms_total / 86400000, ms = ms_total % 86400000;
    int64_t z = days - 134774 + 719468;   /* days since 1601-01-01 -> civil date (Howard Hinnant's algorithm) */
    int64_t era = z / 146097, doe = z - era * 146097, yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t y = yoe + era * 400, doy = doe - (365 * yoe + yoe / 4 - yoe / 100), mp = (5 * doy + 2) / 153;
    int64_t d = doy - (153 * mp + 2) / 5 + 1, m = mp < 10 ? mp + 3 : mp - 9; y += m <= 2;
    const int64_t st[8] = {y, m, (days + 1) % 7, d, ms / 3600000, ms / 60000 % 60, ms / 1000 % 60, ms % 1000};
    for (int i = 0; i < 8; i++) { uint8_t v[2] = {(uint8_t)st[i], (uint8_t)(st[i] >> 8)}; wbytes(P, a[1] + 2 * i, v, 2); }
    return 1;
}
API(get_overlapped_result) { (void)h; if (!file(P, a[0])) { *mh_port_last_error(P) = 6; return 0; } w32(P, a[2], r32(P, a[1] + 4)); return 1; }
API(set_file_pointer) {
    (void)h; gfile *f = file(P, a[0]); uint32_t lo = a[1], phi = a[2], method = a[3];
    if (!f) { *mh_port_last_error(P) = 6; return INVALID_HANDLE; }
    int64_t dist = phi ? (int64_t)(((uint64_t)r32(P, phi) << 32) | lo) : (int64_t)s32(lo);
    int64_t base;
    if (method == 0) base = 0; else if (method == 1) base = (int64_t)f->pos; else if (method == 2) base = (int64_t)file_size(P, f);
    else { *mh_port_last_error(P) = 131; return INVALID_HANDLE; }
    if (base + dist < 0) { *mh_port_last_error(P) = 131; return INVALID_HANDLE; }
    f->pos = (uint64_t)(base + dist);
    if (phi) w32(P, phi, (uint32_t)(f->pos >> 32));
    *mh_port_last_error(P) = 0; return (uint32_t)f->pos;
}
API(get_file_size) { (void)h; gfile *f = file(P, a[0]); if (!f) { *mh_port_last_error(P) = 6; return INVALID_HANDLE; } uint64_t s = file_size(P, f); if (a[1]) w32(P, a[1], (uint32_t)(s >> 32)); return (uint32_t)s; }
API(delete_file) {
    (void)h; char name[MAXPATH + 1], host[MAXPATH * 2], key[MAXPATH * 2]; uint32_t err; cstr(P, a[0], name, MAXPATH);
    guest_key(P, name, key, sizeof key);
    int ov = ov_find(P, key);
    if (ov) {
        for (unsigned i = 0; i < P->nfiles; i++) if (P->files[i].open && P->files[i].ov == ov) { *mh_port_last_error(P) = 32; return 0; }
        ovfile *o = &P->ovfiles[ov - 1];
        if (P->save_dir[0] && !P->save_readonly) {
            char path[MAXPATH * 3];
            if (save_path(P, key, path, sizeof path) && remove(path) && errno != ENOENT) { *mh_port_last_error(P) = save_error(errno); return 0; }
        }
        o->deleted = 1; free(o->data); o->data = NULL; o->size = o->cap = 0; return 1;
    }
    if (resolve(P, name, host, sizeof host, &err) && (host_isfile(host) || host_isdir(host))) fail(P, "DeleteFileA on original data: '%s'", name);
    char parent[MAXPATH * 2]; snprintf(parent, sizeof parent, "%s", key); char *cut = strrchr(parent, '\\'); if (cut) *cut = 0;
    int parent_ok = overlay_dir(P, parent) || (resolve(P, parent, host, sizeof host, &err) && host_isdir(host));
    *mh_port_last_error(P) = istarts(key, MH_PORT_GAME_DIR) && parent_ok ? 2 : 3; return 0;
}
API(close_handle) {
    (void)h; gfile *f = file(P, a[0]);
    if (f) {
        uint32_t error = f->written ? ov_store(P, f->ov) : 0;
        f->open = 0;
        if (error) { *mh_port_last_error(P) = error; return 0; }
        return 1;
    }
    if (a[0] > 0x50000000u && a[0] <= 0x50000000u + P->process.events) return 1;
    *mh_port_last_error(P) = 6; return 0;
}
API(create_directory) {
    (void)h; char name[MAXPATH + 1], full[MAXPATH * 2], host[MAXPATH * 2], key[MAXPATH * 2]; uint32_t err;
    cstr(P, a[0], name, MAXPATH); slashes(name); rstrip_bs(name);
    if (!(strlen(name) > 1 && name[1] == ':') && name[0] != '\\') snprintf(full, sizeof full, "%s\\%s", P->cwd, name); else snprintf(full, sizeof full, "%s", name);
    if (!istarts(full, MH_PORT_GAME_DIR)) { *mh_port_last_error(P) = 3; return 0; }
    snprintf(key, sizeof key, "%s", full); lower(key);
    int exists = resolve(P, full, host, sizeof host, &err) && host_isdir(host);
    for (unsigned i = 0; i < P->noverlay; i++) if (!strcmp(P->overlay[i], key)) exists = 1;
    if (exists) { *mh_port_last_error(P) = 183; return 0; }
    if (P->noverlay == 16) fail(P, "too many overlay directories");
    snprintf(P->overlay[P->noverlay++], MAXPATH, "%s", key); return 1;
}
API(get_file_attributes) {
    (void)h; char name[MAXPATH + 1], host[MAXPATH * 2], key[MAXPATH * 2]; uint32_t err; cstr(P, a[0], name, MAXPATH);
    guest_key(P, name, key, sizeof key); rstrip_bs(key);
    if (ov_find(P, key)) return 0x20;            /* FILE_ATTRIBUTE_ARCHIVE */
    if (overlay_dir(P, key)) return 0x10;
    if (!resolve(P, name, host, sizeof host, &err)) { *mh_port_last_error(P) = err; return INVALID_HANDLE; }
    return host_isdir(host) ? 0x10 : 0x01;
}
/* registry */
static const char *root_name(uint32_t h) { return h == 0x80000000u ? "HKCR" : h == 0x80000001u ? "HKCU" : h == 0x80000002u ? "HKLM" : h == 0x80000003u ? "HKU" : NULL; }
static int key_path(mh_port *P, uint32_t hk, uint32_t sub, char *keyu, char *path, size_t size) {
    const char *base = root_name(hk);
    if (!base) for (unsigned i = 0; i < P->nhkeys; i++) if (P->hkeys[i].h == hk) base = P->hkeys[i].path;
    if (!base) return 0;
    char s[600] = "";
    if (sub) { cstr(P, sub, s, 512); size_t b = 0, e = strlen(s); while (s[b] == '\\') b++; while (e > b && s[e - 1] == '\\') e--; memmove(s, s + b, e - b); s[e - b] = 0; }
    if (s[0]) snprintf(path, size, "%s\\%s", base, s); else snprintf(path, size, "%s", base);
    snprintf(keyu, size, "%s", path); upper(keyu); return 1;
}
static regkey *reg_find(mh_port *P, const char *keyu) { for (unsigned i = 0; i < P->nreg; i++) if (!strcmp(P->reg[i].key, keyu)) return &P->reg[i]; return NULL; }
static uint32_t new_hkey(mh_port *P, const char *path) {
    uint32_t h = 0x70000004u + 4 * P->nhkeys;
    for (unsigned i = 0; i < P->nhkeys; i++) if (P->hkeys[i].h == h) { snprintf(P->hkeys[i].path, sizeof P->hkeys[i].path, "%s", path); return h; }
    if (P->nhkeys == 64) fail(P, "too many registry handles");
    P->hkeys[P->nhkeys].h = h; snprintf(P->hkeys[P->nhkeys].path, sizeof P->hkeys[P->nhkeys].path, "%s", path); P->nhkeys++; return h;
}
API(reg_open) {
    (void)h; char keyu[600], path[600];
    if (!key_path(P, a[0], a[1], keyu, path, sizeof path)) return 6;
    if (!reg_find(P, keyu) && strcmp(keyu, "HKCR") && strcmp(keyu, "HKCU") && strcmp(keyu, "HKLM") && strcmp(keyu, "HKU")) return 2;
    w32(P, a[4], new_hkey(P, path)); return 0;
}
API(reg_create) {
    (void)h; char keyu[600], path[600];
    if (!key_path(P, a[0], a[1], keyu, path, sizeof path)) return 6;
    int created = !reg_find(P, keyu);
    for (char *p = strchr(path, '\\'); ; p = strchr(p + 1, '\\')) {   /* every prefix with at least two components */
        char prefix[600], up[600]; size_t n = p ? (size_t)(p - path) : strlen(path);
        memcpy(prefix, path, n); prefix[n] = 0;
        if (strchr(prefix, '\\')) {
            snprintf(up, sizeof up, "%s", prefix); upper(up);
            if (!reg_find(P, up)) {
                P->reg = realloc(P->reg, (P->nreg + 1) * sizeof *P->reg); regkey *k = &P->reg[P->nreg++]; memset(k, 0, sizeof *k);
                snprintf(k->key, sizeof k->key, "%s", up); snprintf(k->name, sizeof k->name, "%s", prefix);
            }
        }
        if (!p) break;
    }
    w32(P, a[7], new_hkey(P, path));
    if (a[8]) w32(P, a[8], created ? 1 : 2);
    return 0;
}
API(reg_close) {
    (void)h; if (root_name(a[0])) return 0;
    for (unsigned i = 0; i < P->nhkeys; i++) if (P->hkeys[i].h == a[0]) { memmove(&P->hkeys[i], &P->hkeys[i + 1], (P->nhkeys - i - 1) * sizeof *P->hkeys); P->nhkeys--; return 0; }
    return 6;
}
API(reg_set_value) {
    (void)h; char keyu[600], path[600], name[300] = "";
    if (!key_path(P, a[0], 0, keyu, path, sizeof path)) return 6;
    regkey *k = reg_find(P, keyu); if (!k) return 6;
    if (a[1]) cstr(P, a[1], name, 260);
    upper(name);
    regvalue *v = NULL; for (unsigned i = 0; i < k->nvalues; i++) if (!strcmp(k->values[i].key, name)) v = &k->values[i];
    if (!v) { k->values = realloc(k->values, (k->nvalues + 1) * sizeof *k->values); v = &k->values[k->nvalues++]; memset(v, 0, sizeof *v); snprintf(v->key, sizeof v->key, "%s", name); }
    free(v->data); v->type = a[3]; v->size = a[5]; v->data = a[5] ? malloc(a[5]) : NULL;
    if (a[5] && !mh_mem_read(P->mem, a[4], v->data, a[5])) fail(P, "RegSetValueExA data");
    return 0;
}
API(reg_query_value) {
    (void)h; char keyu[600], path[600], name[300] = "";
    if (!key_path(P, a[0], 0, keyu, path, sizeof path)) return 6;
    regkey *k = reg_find(P, keyu); if (!k) return 6;
    if (a[1]) cstr(P, a[1], name, 260);
    upper(name);
    regvalue *v = NULL; for (unsigned i = 0; i < k->nvalues; i++) if (!strcmp(k->values[i].key, name)) v = &k->values[i];
    if (!v) return 2;
    if (a[3]) w32(P, a[3], v->type);
    if (a[4]) { uint32_t size = r32(P, a[5]); if (size < v->size) { w32(P, a[5], v->size); return 234; } wbytes(P, a[4], v->data, v->size); }
    if (a[5]) w32(P, a[5], v->size);
    return 0;
}
/* dialogs */
static dialog *find_dialog(mh_port *P, uint32_t h) { for (unsigned i = 0; i < P->ndialogs; i++) if (P->dialogs[i].hdlg == h) return &P->dialogs[i]; return NULL; }
static control *find_control(mh_port *P, uint32_t h) { for (unsigned i = 0; i < P->ncontrols; i++) if (P->controls[i].h == h) return &P->controls[i]; return NULL; }
static uint32_t make_control(mh_port *P, uint32_t hdlg, uint32_t id) {
    uint32_t h = 0x00030000u + 4 * id;
    if (!find_control(P, h)) {
        P->controls = realloc(P->controls, (P->ncontrols + 1) * sizeof *P->controls); control *c = &P->controls[P->ncontrols++];
        memset(c, 0, sizeof *c); c->h = h; c->dialog = hdlg; c->id = id; c->sel = 0xffffffffu;
    }
    return h;
}
API(dialog_box) {
    (void)h; uint32_t proc = a[3], param = a[4];
    if (P->ndialogs == 8) fail(P, "too many dialogs");
    uint32_t hdlg = 0x00028000u + 4 * P->ndialogs; dialog *d = &P->dialogs[P->ndialogs++];
    d->hdlg = hdlg; d->template_ = a[1]; d->proc = proc; d->ended_set = 0;
    window *w = add_window(P, hdlg); snprintf(w->cls, sizeof w->cls, "#32770"); w->visible = 1;
    cb4(P, proc, hdlg, WM_INITDIALOG, 0, param);
    d = find_dialog(P, hdlg);
    if (d->ended_set) return d->ended;
    cb4(P, proc, hdlg, WM_COMMAND, 1, make_control(P, hdlg, 1));
    d = find_dialog(P, hdlg);
    if (!d->ended_set) fail(P, "dialog not ended after IDOK");
    return d->ended;
}
API(end_dialog) { (void)h; dialog *d = find_dialog(P, a[0]); if (!d) { *mh_port_last_error(P) = 1400; return 0; } d->ended = a[1]; d->ended_set = 1; return 1; }
API(get_dlg_item) { (void)h; if (!find_dialog(P, a[0])) { *mh_port_last_error(P) = 1400; return 0; } return make_control(P, a[0], a[1]); }
static uint32_t control_message(mh_port *P, control *c, uint32_t msg, uint32_t wp, uint32_t lp) {
    uint32_t n = c->n;
    switch (msg) {
    case 0x143: if (n == 64) fail(P, "too many combo items"); cstr(P, lp, c->items[n], 255); c->data[n] = 0; c->n++; return n;
    case 0x14b: c->n = 0; c->sel = 0xffffffffu; return 0;
    case 0x146: return n;
    case 0x14e: if (wp < n) { c->sel = wp; return wp; } c->sel = 0xffffffffu; return 0xffffffffu;
    case 0x147: return c->sel;
    case 0x151: if (wp >= n) return 0xffffffffu; c->data[wp] = lp; return 1;
    case 0x150: return wp < n ? c->data[wp] : 0xffffffffu;
    case 0x148: if (wp >= n) return 0xffffffffu; wbytes(P, lp, c->items[wp], strlen(c->items[wp]) + 1); return (uint32_t)strlen(c->items[wp]);
    default: fail(P, "message 0x%x to dialog control %u", msg, c->id); return 0;
    }
}
/* window management */
static void write_rect(mh_port *P, uint32_t at, const int64_t *r) { for (int i = 0; i < 4; i++) w32(P, at + 4 * i, (uint32_t)r[i]); }
API(get_window_rect) { (void)h; write_rect(P, a[1], need_window(P, a[0])->rect); return 1; }
API(get_client_rect) { (void)h; window *w = need_window(P, a[0]); int64_t r[4] = {0, 0, w->rect[2] - w->rect[0], w->rect[3] - w->rect[1]}; write_rect(P, a[1], r); return 1; }
API(client_to_screen) { (void)h; window *w = need_window(P, a[0]); w32(P, a[1], (uint32_t)(s32(r32(P, a[1])) + w->rect[0])); w32(P, a[1] + 4, (uint32_t)(s32(r32(P, a[1] + 4)) + w->rect[1])); return 1; }
API(screen_to_client) { (void)h; window *w = need_window(P, a[0]); w32(P, a[1], (uint32_t)(s32(r32(P, a[1])) - w->rect[0])); w32(P, a[1] + 4, (uint32_t)(s32(r32(P, a[1] + 4)) - w->rect[1])); return 1; }
static uint32_t reshape(mh_port *P, uint32_t hwnd, int64_t x, int64_t y, int64_t cx, int64_t cy, int move, int size) {
    window *w = need_window(P, hwnd); int64_t old[4]; memcpy(old, w->rect, sizeof old);
    if (move) { w->rect[2] += x - w->rect[0]; w->rect[3] += y - w->rect[1]; w->rect[0] = x; w->rect[1] = y; }
    if (size) { w->rect[2] = w->rect[0] + cx; w->rect[3] = w->rect[1] + cy; }
    int sized = size && (w->rect[2] - w->rect[0] != old[2] - old[0] || w->rect[3] - w->rect[1] != old[3] - old[1]);
    int moved = move && (w->rect[0] != old[0] || w->rect[1] != old[1]);
    uint32_t proc = w->wndproc; int64_t nw = w->rect[2] - w->rect[0], nh = w->rect[3] - w->rect[1], nx = w->rect[0], ny = w->rect[1];
    if (proc) {
        if (sized) cb4(P, proc, hwnd, WM_SIZE, 0, lparam(nw, nh));
        if (moved) cb4(P, proc, hwnd, WM_MOVE, 0, lparam(nx, ny));
    }
    return 1;
}
API(set_window_pos) { (void)h; return reshape(P, a[0], s32(a[2]), s32(a[3]), s32(a[4]), s32(a[5]), !(a[6] & 2), !(a[6] & 1)); }
API(move_window) { (void)h; return reshape(P, a[0], s32(a[1]), s32(a[2]), s32(a[3]), s32(a[4]), 1, 1); }
API(show_window) {
    (void)h; window *w = need_window(P, a[0]); int was = w->visible; w->visible = a[1] != 0;
    if (w->visible && !was && w->wndproc && !P->active) {
        uint32_t proc = w->wndproc, hwnd = a[0]; P->active = hwnd; P->focus = hwnd;
        cb4(P, proc, hwnd, WM_ACTIVATEAPP, 1, 0); cb4(P, proc, hwnd, WM_ACTIVATE, 1, 0); cb4(P, proc, hwnd, WM_SETFOCUS, 0, 0);
    }
    return (uint32_t)was;
}
API(set_timer) {
    (void)h; if (a[0]) need_window(P, a[0]);
    if (a[3]) fail(P, "SetTimer with a TIMERPROC");
    uint32_t id = a[0] ? a[1] : 0x7000u + P->ntimers, interval = a[2] > 10 ? a[2] : 10;
    unsigned i = 0; for (; i < P->ntimers && !(P->timers[i].hwnd == a[0] && P->timers[i].id == id); i++) {}
    if (i == P->ntimers) { if (i == 16) fail(P, "too many timers"); P->ntimers++; }
    P->timers[i] = (timer){a[0], id, interval, P->clock + interval}; return id;
}
API(kill_timer) {
    (void)h; for (unsigned i = 0; i < P->ntimers; i++) if (P->timers[i].hwnd == a[0] && P->timers[i].id == a[1]) { memmove(&P->timers[i], &P->timers[i + 1], (P->ntimers - i - 1) * sizeof *P->timers); P->ntimers--; return 1; }
    *mh_port_last_error(P) = 1402; return 0;
}
static int next_message(mh_port *P, uint32_t hwnd, uint32_t lo, uint32_t hi, int remove, qmsg *out) {
    for (unsigned i = 0; i < P->nqueue; i++) {
        qmsg m = P->queue[i];
        if ((!hwnd || m.hwnd == hwnd) && ((lo == 0 && hi == 0) || (lo <= m.msg && m.msg <= hi))) {
            if (remove) { memmove(&P->queue[i], &P->queue[i + 1], (P->nqueue - i - 1) * sizeof *P->queue); P->nqueue--; }
            *out = m; return 1;
        }
    }
    /* timers in (hwnd, id) order */
    int best = -1;
    for (unsigned i = 0; i < P->ntimers; i++) {
        timer *t = &P->timers[i];
        if (P->clock >= t->due && (!hwnd || t->hwnd == hwnd) && ((lo == 0 && hi == 0) || (lo <= WM_TIMER && WM_TIMER <= hi)))
            if (best < 0 || t->hwnd < P->timers[best].hwnd || (t->hwnd == P->timers[best].hwnd && t->id < P->timers[best].id)) best = (int)i;
    }
    if (best < 0) return 0;
    if (remove) P->timers[best].due = P->clock + P->timers[best].interval;
    *out = (qmsg){P->timers[best].hwnd, WM_TIMER, P->timers[best].id, 0}; return 1;
}
static void write_msg(mh_port *P, uint32_t at, const qmsg *m) {
    const uint32_t v[7] = {m->hwnd, m->msg, m->wp, m->lp, (uint32_t)P->clock, (uint32_t)P->cursor.x, (uint32_t)P->cursor.y};
    for (int i = 0; i < 7; i++) w32(P, at + 4 * i, v[i]);
}
/* MapVirtualKeyA on a US keyboard, as the reference: 0 VK->scan, 1 scan->VK, 2 VK->char, 3 scan->VK (left/right). */
static uint32_t map_virtual_key(mh_port *P, const uint32_t *a, int *h) {
    (void)P; (void)h;
    static const uint8_t vk_sc[][2] = {{0x1b,0x01},{0x08,0x0e},{0x09,0x0f},{0x0d,0x1c},{0x10,0x2a},{0x11,0x1d},{0x12,0x38},{0x20,0x39},{0x14,0x3a},{0x26,0x48},{0x28,0x50},{0x25,0x4b},{0x27,0x4d},{0x2d,0x52},{0x2e,0x53},{0x24,0x47},{0x23,0x4f},{0x21,0x49},{0x22,0x51},{0x90,0x45},{0x91,0x46},{0x6a,0x37},{0x6b,0x4e},{0x6d,0x4a},{0x6e,0x53},{0x6f,0x35},{0x60,0x52},{0x61,0x4f},{0x62,0x50},{0x63,0x51},{0x64,0x4b},{0x65,0x4c},{0x66,0x4d},{0x67,0x47},{0x68,0x48},{0x69,0x49},{0xa0,0x2a},{0xa1,0x36},{0xa2,0x1d},{0xa3,0x1d},{0xa4,0x38},{0xa5,0x38},{0xba,0x27},{0xbb,0x0d},{0xbc,0x33},{0xbd,0x0c},{0xbe,0x34},{0xbf,0x35},{0xc0,0x29},{0xdb,0x1a},{0xdc,0x2b},{0xdd,0x1b},{0xde,0x28},{0x51,0x10},{0x57,0x11},{0x45,0x12},{0x52,0x13},{0x54,0x14},{0x59,0x15},{0x55,0x16},{0x49,0x17},{0x4f,0x18},{0x50,0x19},{0x41,0x1e},{0x53,0x1f},{0x44,0x20},{0x46,0x21},{0x47,0x22},{0x48,0x23},{0x4a,0x24},{0x4b,0x25},{0x4c,0x26},{0x5a,0x2c},{0x58,0x2d},{0x43,0x2e},{0x56,0x2f},{0x42,0x30},{0x4e,0x31},{0x4d,0x32},{0x31,0x02},{0x32,0x03},{0x33,0x04},{0x34,0x05},{0x35,0x06},{0x36,0x07},{0x37,0x08},{0x38,0x09},{0x39,0x0a},{0x30,0x0b},{0x70,0x3b},{0x71,0x3c},{0x72,0x3d},{0x73,0x3e},{0x74,0x3f},{0x75,0x40},{0x76,0x41},{0x77,0x42},{0x78,0x43},{0x79,0x44},{0x7a,0x57},{0x7b,0x58}};
    static const uint8_t vk_ex[][2] = {{0x1d,0xa2},{0x2a,0xa0},{0x36,0xa1},{0x38,0xa4}};
    static const uint8_t vk_ch[][2] = {{0x08,0x08},{0x09,0x09},{0x0d,0x0d},{0x1b,0x1b},{0x20,0x20},{0x30,0x30},{0x31,0x31},{0x32,0x32},{0x33,0x33},{0x34,0x34},{0x35,0x35},{0x36,0x36},{0x37,0x37},{0x38,0x38},{0x39,0x39},{0x41,0x41},{0x42,0x42},{0x43,0x43},{0x44,0x44},{0x45,0x45},{0x46,0x46},{0x47,0x47},{0x48,0x48},{0x49,0x49},{0x4a,0x4a},{0x4b,0x4b},{0x4c,0x4c},{0x4d,0x4d},{0x4e,0x4e},{0x4f,0x4f},{0x50,0x50},{0x51,0x51},{0x52,0x52},{0x53,0x53},{0x54,0x54},{0x55,0x55},{0x56,0x56},{0x57,0x57},{0x58,0x58},{0x59,0x59},{0x5a,0x5a},{0x60,0x30},{0x61,0x31},{0x62,0x32},{0x63,0x33},{0x64,0x34},{0x65,0x35},{0x66,0x36},{0x67,0x37},{0x68,0x38},{0x69,0x39},{0x6a,0x2a},{0x6b,0x2b},{0x6d,0x2d},{0x6e,0x2e},{0x6f,0x2f},{0xba,0x3b},{0xbb,0x3d},{0xbc,0x2c},{0xbd,0x2d},{0xbe,0x2e},{0xbf,0x2f},{0xc0,0x60},{0xdb,0x5b},{0xdc,0x5c},{0xdd,0x5d},{0xde,0x27}};
    uint32_t code = a[0], kind = a[1];
    if (kind == 0) { for (unsigned i = 0; i < sizeof vk_sc / sizeof vk_sc[0]; i++) if (vk_sc[i][0] == code) return vk_sc[i][1]; return 0; }
    if (kind == 1 || kind == 3) {
        if (kind == 3) for (unsigned i = 0; i < sizeof vk_ex / sizeof vk_ex[0]; i++) if (vk_ex[i][0] == code) return vk_ex[i][1];
        for (unsigned i = 0; i < sizeof vk_sc / sizeof vk_sc[0]; i++) if (vk_sc[i][1] == code) return vk_sc[i][0];
        return 0;
    }
    if (kind == 2) { for (unsigned i = 0; i < sizeof vk_ch / sizeof vk_ch[0]; i++) if (vk_ch[i][0] == code) return vk_ch[i][1]; }
    return 0;
}
/* Keyboard messages (as the reference): the game's menus read WM_KEYDOWN/WM_CHAR, not DirectInput.
 * At each Present the keyboard state for the new frame count (script and live keys) is compared
 * with the one delivered; each change posts WM_KEYDOWN (+ WM_CHAR) or WM_KEYUP to the focus window. */
static int key_vk(unsigned k, uint32_t *vk, uint32_t *ch) {
    static const uint32_t map[][3] = {{0x01,0x1b,0x1b},{0x1c,0x0d,0x0d},{0x39,0x20,0x20},{0xc8,0x26,0},{0xd0,0x28,0},{0xcb,0x25,0},{0xcd,0x27,0},
        {0x0f,0x09,0x09},{0x2a,0x10,0},{0x1d,0x11,0},{0x11,0x57,0x77},{0x1e,0x41,0x61},{0x1f,0x53,0x73},{0x20,0x44,0x64},
        {0x21,0x46,0x66},{0x10,0x51,0x71},{0x12,0x45,0x65},{0x13,0x52,0x72},{0x2d,0x58,0x78},
        {0x02,0x31,0x31},{0x03,0x32,0x32},{0x04,0x33,0x33},{0x05,0x34,0x34}};   /* DIK, VK, WM_CHAR: as the reference */
    for (unsigned i = 0; i < sizeof map / sizeof map[0]; i++) if (map[i][0] == k) { *vk = map[i][1]; *ch = map[i][2]; return 1; }
    return 0;
}
static void post(mh_port *P, qmsg m) { if (P->nqueue == 256) fail(P, "message queue full"); P->queue[P->nqueue++] = m; }
static void key_messages(mh_port *P) {
    uint32_t target = P->focus ? P->focus : P->active;
    for (unsigned k = 0; k < 256; k++) {
        uint32_t vk, ch; if (!key_vk(k, &vk, &ch)) continue;
        int want = P->keys[k] != 0;
        for (unsigned i = 0; i < P->nscript && !want; i++) want = P->script[i].key == k && P->frames >= P->script[i].from && P->frames < P->script[i].to;
        if (want == (P->keys_delivered[k] != 0)) continue;
        uint32_t lp = 1u | ((k & 0x7fu) << 16) | (k & 0x80 ? 1u << 24 : 0);
        if (want) { post(P, (qmsg){target, 0x100, vk, lp}); if (ch) post(P, (qmsg){target, 0x102, ch, lp}); }
        else post(P, (qmsg){target, 0x101, vk, lp | 0xc0000000u});
        P->keys_delivered[k] = (uint8_t)want;
    }
}
API(peek_message) { (void)h; qmsg m; if (!next_message(P, a[1], a[2], a[3], a[4] & 1, &m)) return 0; write_msg(P, a[0], &m); return 1; }
API(get_message) { (void)h; qmsg m; if (!next_message(P, a[1], a[2], a[3], 1, &m)) fail(P, "GetMessageA would block with an empty queue"); write_msg(P, a[0], &m); return m.msg == WM_QUIT ? 0 : 1; }
API(post_message) { (void)h; if (a[0] && !find_window(P, a[0])) { *mh_port_last_error(P) = 1400; return 0; } if (P->nqueue == 256) fail(P, "message queue full"); P->queue[P->nqueue++] = (qmsg){a[0], a[1], a[2], a[3]}; return 1; }
API(post_quit) { if (P->nqueue == 256) fail(P, "message queue full"); P->queue[P->nqueue++] = (qmsg){0, WM_QUIT, a[0], 0}; *h = 0; return 0; }
API(translate_message) { UNUSED; return 0; }
API(dispatch_message) {
    (void)h; uint32_t hwnd = r32(P, a[0]), msg = r32(P, a[0] + 4), wp = r32(P, a[0] + 8), lp = r32(P, a[0] + 12);
    if (msg == WM_TIMER && lp) fail(P, "WM_TIMER with a TIMERPROC");
    window *w = find_window(P, hwnd);
    if (!w || !w->wndproc) return 0;
    return cb4(P, w->wndproc, hwnd, msg, wp, lp);
}
API(set_window_text) { (void)h; window *w = need_window(P, a[0]); if (a[1]) cstr(P, a[1], w->title, sizeof w->title - 1); else w->title[0] = 0; return 1; }
API(get_window_text) {
    (void)h; window *w = need_window(P, a[0]); uint32_t max = a[2] > 1 ? a[2] - 1 : 0, len = (uint32_t)strlen(w->title);
    if (len > max) len = max;
    if (a[2]) { uint8_t nul = 0; wbytes(P, a[1], w->title, len); wbytes(P, a[1] + len, &nul, 1); }
    return len;
}
API(update_window) { (void)h; need_window(P, a[0]); return 1; }
API(is_iconic) { (void)h; need_window(P, a[0]); return 0; }
API(is_window_visible) { (void)h; return (uint32_t)need_window(P, a[0])->visible; }
API(set_foreground_window) { (void)h; need_window(P, a[0]); P->active = a[0]; return 1; }
API(get_foreground_window) { (void)a; (void)h; return P->active; }
static uint32_t *window_long(window *w, uint32_t index) {
    if (index == 0xfffffffcu) return &w->wndproc; if (index == 0xfffffff0u) return &w->style; if (index == 0xffffffecu) return &w->exstyle;
    return NULL;
}
API(get_window_long) {
    (void)h; window *w = need_window(P, a[0]); uint32_t *v = window_long(w, a[1]); if (v) return *v;
    for (unsigned i = 0; i < w->nlongs; i++) if (w->longs[i].k == a[1]) return w->longs[i].v;
    return 0;
}
API(set_window_long) {
    (void)h; window *w = need_window(P, a[0]); uint32_t *v = window_long(w, a[1]), old;
    if (v) { old = *v; *v = a[2]; return old; }
    for (unsigned i = 0; i < w->nlongs; i++) if (w->longs[i].k == a[1]) { old = w->longs[i].v; w->longs[i].v = a[2]; return old; }
    if (w->nlongs == 16) fail(P, "too many window longs");
    w->longs[w->nlongs++] = (kv){a[1], a[2]}; return 0;
}
API(set_focus) { (void)h; if (a[0] && !find_control(P, a[0]) && !find_window(P, a[0])) { *mh_port_last_error(P) = 1400; return 0; } uint32_t old = P->focus; P->focus = a[0]; return old; }
API(get_focus) { (void)a; (void)h; return P->focus; }
API(send_message) {
    (void)h; control *c = find_control(P, a[0]);
    if (c) return control_message(P, c, a[1], a[2], a[3]);
    window *w = find_window(P, a[0]);
    if (w && w->wndproc) return cb4(P, w->wndproc, a[0], a[1], a[2], a[3]);
    fail(P, "SendMessageA to 0x%x message 0x%x", a[0], a[1]); return 0;
}
/* Miles */
static uint32_t mss_string(mh_port *P, const char *text) {
    uint32_t at = P->mss_scratch, n = (uint32_t)strlen(text) + 1; wbytes(P, at, text, n); P->mss_scratch = (at + n + 3) & ~3u; return at;
}
#define PROVIDER 0x6E000001u
#define SMP_DONE 2u
#define SMP_PLAYING 4u
#define SMP_STOPPED 8u
API(ail_redist) { (void)h; uint32_t old = P->mss_redist; char t[300]; if (a[0]) { cstr(P, a[0], t, 260); P->mss_redist = mss_string(P, t); } else P->mss_redist = MH_PORT_MSS_SCRATCH; return old; }
API(ail_startup) { (void)a; (void)h; P->mss_started = 1; return 1; }
API(ail_shutdown) { (void)a; P->mss_started = 0; *h = 0; return 0; }
API(ail_set_preference) {
    (void)h; for (unsigned i = 0; i < P->nprefs; i++) if (P->prefs[i].k == a[0]) { uint32_t old = P->prefs[i].v; P->prefs[i].v = a[1]; return old; }
    if (P->nprefs == 32) fail(P, "too many Miles preferences");
    P->prefs[P->nprefs].k = a[0]; P->prefs[P->nprefs].v = a[1]; P->nprefs++; return 0;
}
/* AIL_process_digital_audio: streamed IMA ADPCM (0x11, mono, 4 bits) to 16-bit PCM at the same
 * rate, block by block, as the reference (tools/winmain_apis.py); returns the bytes written. */
static const int8_t IMA_INDEX[16] = {-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8};
static const int16_t IMA_STEP[89] = {7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,
    337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,
    4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767};
API(ail_process_audio) {
    (void)h; uint32_t dest = a[0], size = a[1], rate = a[2], fmt = a[3], count = a[4], info = a[5], f[9];
    for (int i = 0; i < 9; i++) f[i] = r32(P, info + 4 * i);
    if (count != 1 || fmt != 1 || f[0] != 0x11 || f[4] != 4 || f[5] != 1 || f[3] != rate || f[7] < 5)
        fail(P, "AIL_process_digital_audio conversion format 0x%x bits %u channels %u rate %u to rate %u format %u", f[0], f[4], f[5], f[3], rate, fmt);
    uint32_t block = f[7], length = f[2], limit = size / 2, n = 0;
    const uint8_t *src = length ? mh_mem_span(P->mem, f[1], length) : NULL;
    if (length && !src) fail(P, "ADPCM source outside guest memory");
    int16_t *out = malloc((size_t)limit * 2 + 2); if (!out && limit) fail(P, "out of host memory");
    for (uint32_t b = 0; b + block <= length && n < limit; b += block) {
        int pred = (int16_t)(src[b] | src[b + 1] << 8), index = src[b + 2] > 88 ? 88 : src[b + 2];
        out[n++] = (int16_t)pred;
        for (uint32_t i = b + 4; i < b + block; i++)
            for (int half = 0; half < 2; half++) {
                int nib = half ? src[i] >> 4 : src[i] & 15, step = IMA_STEP[index], diff = step >> 3;
                if (nib & 4) diff += step; if (nib & 2) diff += step >> 1; if (nib & 1) diff += step >> 2;
                pred = nib & 8 ? pred - diff : pred + diff; pred = pred < -32768 ? -32768 : pred > 32767 ? 32767 : pred;
                index += IMA_INDEX[nib]; index = index < 0 ? 0 : index > 88 ? 88 : index;
                if (n < limit) out[n++] = (int16_t)pred;
            }
    }
    uint8_t *le = (uint8_t *)out;   /* in place: little-endian samples */
    for (uint32_t i = 0; i < n; i++) { uint16_t s = (uint16_t)out[i]; le[2 * i] = (uint8_t)s; le[2 * i + 1] = (uint8_t)(s >> 8); }
    wbytes(P, dest, le, 2 * (size_t)n);
    free(out); return 2 * n;
}
API(ail_ms_count) { (void)a; (void)h; return (uint32_t)tick(P); }
API(ail_open_driver) { (void)h; if ((a[1] != 8 && a[1] != 16) || (a[2] != 1 && a[2] != 2)) return 0; P->mss_driver = 0x6D000001u; return P->mss_driver; }
API(ail_close_driver) { (void)a; P->mss_driver = 0; *h = 0; return 0; }
API(ail_enum_providers) {
    (void)h; if (r32(P, a[0]) != 0) return 0;
    w32(P, a[0], 1); w32(P, a[1], PROVIDER); w32(P, a[2], mss_string(P, "Miles Fast 2D Positional Audio")); return 1;
}
API(ail_open_provider) { (void)h; if (a[0] != PROVIDER) return 1; P->mss_provider_open = 1; return 0; }
API(ail_close_provider) { (void)a; P->mss_provider_open = 0; *h = 0; return 0; }
static int pref3d(mh_port *P, const char *name) { for (unsigned i = 0; i < P->nprefs3d; i++) if (!strcmp(P->prefs3d[i].name, name)) return (int)i; return -1; }
API(ail_provider_pref) {
    (void)h; char name[128]; cstr(P, a[1], name, 127); int i = pref3d(P, name);
    if (i < 0) { if (P->nprefs3d == 32) fail(P, "too many 3D preferences"); i = (int)P->nprefs3d++; snprintf(P->prefs3d[i].name, sizeof P->prefs3d[i].name, "%s", name); }
    P->prefs3d[i].v = r32(P, a[2]); return 0;
}
API(ail_provider_attribute) {
    char name[128]; cstr(P, a[1], name, 127); int i = pref3d(P, name);
    if (i < 0) fail(P, "AIL_3D_provider_attribute('%s')", name);
    w32(P, a[2], P->prefs3d[i].v); *h = 0; return 0;
}
API(ail_set_room) { P->room = a[1]; *h = 0; return 0; }
API(ail_room) { (void)a; (void)h; return P->room; }
/* Audio output (mh_port_set_audio): every change of a sample is reported with its whole state.
 * Output only: what the game observes (status, offsets) stays on the virtual clock. */
static void sound_event(mh_port *P, uint32_t h, const sample *s, int event) {
    if (!P->has_audio || !P->audio.sound) return;
    mh_port_sound d; memset(&d, 0, sizeof d);
    d.handle = h; d.status = s->status; d.loops = s->loops; d.loop_start = s->loop_block[0]; d.loop_end = s->loop_block[1];
    d.volume = s->volume; d.playback_rate = s->playback_rate;
    if (s->has_info) { d.format = s->info[0]; d.data = s->info[1]; d.length = s->info[2]; d.rate = s->info[3]; d.bits = s->info[4];
                       d.channels = s->info[5]; d.samples = s->info[6]; d.block = s->info[7]; }
    P->audio.sound(P->audio.user, P, &d, event);
}
static sample *need_sample(mh_port *P, uint32_t h) {
    if (h < 0x6F000004u || ((h - 0x6F000004u) & 3) || (h - 0x6F000004u) / 4 >= P->nsamples) fail(P, "unknown 3D sample handle 0x%x", h);
    return &P->samples[(h - 0x6F000004u) / 4];
}
static uint64_t sample_ms(const sample *s) {
    if (!s->has_info) return 0;
    uint32_t fmt = s->info[0], length = s->info[2], rate = s->info[3], bits = s->info[4], channels = s->info[5], samples = s->info[6];
    uint64_t per = (bits / 8) * channels; uint64_t frames = fmt == 0x11 ? samples : length / (per ? per : 1);
    return frames * 1000 / (rate ? rate : 1);
}
static uint32_t update(mh_port *P, sample *s) {
    if (s->status == SMP_PLAYING && s->loops && P->clock - s->started >= sample_ms(s) * s->loops) s->status = SMP_DONE;
    return s->status;
}
API(ail_allocate) {
    (void)h; if (a[0] != PROVIDER || !P->mss_provider_open) return 0;
    unsigned live = 0; for (unsigned i = 0; i < P->nsamples; i++) live += !P->samples[i].released;
    if (live >= 32) return 0;
    if (P->nsamples == 64) fail(P, "too many 3D samples");
    sample *s = &P->samples[P->nsamples]; memset(s, 0, sizeof *s); s->status = SMP_DONE; s->loops = 1; s->volume = 1.0f;
    return 0x6F000004u + 4 * P->nsamples++;
}
API(ail_release) { sample *s = need_sample(P, a[0]); s->released = 1; sound_event(P, a[0], s, MH_SOUND_RELEASE); *h = 0; return 0; }
API(ail_set_info) {
    (void)h; sample *s = need_sample(P, a[0]); uint32_t info[9]; for (int i = 0; i < 9; i++) info[i] = r32(P, a[1] + 4 * i);
    if ((info[0] != 1 && info[0] != 0x11) || (info[5] != 1 && info[5] != 2)) return 0;
    memcpy(s->info, info, sizeof info); s->has_info = 1; s->status = SMP_DONE; s->offset = 0; sound_event(P, a[0], s, MH_SOUND_END); return 1;
}
API(ail_start) { sample *s = need_sample(P, a[0]); s->status = SMP_PLAYING; s->started = P->clock; s->offset = 0; sound_event(P, a[0], s, MH_SOUND_START); *h = 0; return 0; }
API(ail_stop) { sample *s = need_sample(P, a[0]); if (update(P, s) == SMP_PLAYING) { s->status = SMP_STOPPED; s->offset = (uint32_t)(P->clock - s->started); sound_event(P, a[0], s, MH_SOUND_STOP); } *h = 0; return 0; }
API(ail_resume) { sample *s = need_sample(P, a[0]); if (s->status == SMP_STOPPED) { s->status = SMP_PLAYING; s->started = P->clock - s->offset; sound_event(P, a[0], s, MH_SOUND_RESUME); } *h = 0; return 0; }
API(ail_end) { sample *s = need_sample(P, a[0]); s->status = SMP_DONE; sound_event(P, a[0], s, MH_SOUND_END); *h = 0; return 0; }
API(ail_status) { (void)h; return update(P, need_sample(P, a[0])); }
API(ail_length) { (void)h; sample *s = need_sample(P, a[0]); return s->has_info ? s->info[2] : 0; }
API(ail_offset) {
    (void)h; sample *s = need_sample(P, a[0]);
    if (!s->has_info || update(P, s) != SMP_PLAYING) return s->status != SMP_STOPPED ? 0 : (s->info[2] < s->offset ? s->info[2] : s->offset);
    uint64_t ms = sample_ms(s); if (ms < 1) ms = 1;
    return (uint32_t)((uint64_t)s->info[2] * ((P->clock - s->started) % ms) / ms);
}
API(ail_loop_count) { sample *s = need_sample(P, a[0]); s->loops = a[1]; sound_event(P, a[0], s, MH_SOUND_CHANGE); *h = 0; return 0; }
API(ail_loop_block) { sample *s = need_sample(P, a[0]); s->loop_block[0] = a[1]; s->loop_block[1] = a[2]; sound_event(P, a[0], s, MH_SOUND_CHANGE); *h = 0; return 0; }
API(ail_set_volume) { sample *s = need_sample(P, a[0]); memcpy(&s->volume, &a[1], 4); sound_event(P, a[0], s, MH_SOUND_CHANGE); *h = 0; return 0; }
API(ail_set_rate) { sample *s = need_sample(P, a[0]); s->playback_rate = a[1]; sound_event(P, a[0], s, MH_SOUND_CHANGE); *h = 0; return 0; }
API(ail_setter) { need_sample(P, a[0]); *h = 0; return 0; }
/* Bink */
static bink *need_bink(mh_port *P, uint32_t h) { for (unsigned i = 0; i < P->nbinks; i++) if (P->binks[i].h == h) return &P->binks[i]; fail(P, "unknown Bink handle 0x%x", h); return NULL; }
API(bink_sound) { UNUSED; return 1; }
API(bink_open) {
    (void)h; char name[MAXPATH + 1], host[MAXPATH * 2]; uint32_t err; uint8_t head[44];
    cstr(P, a[0], name, MAXPATH);
    if (!resolve(P, name, host, sizeof host, &err) || !host_isfile(host)) return 0;
    FILE *fp = fopen(host, "rb"); size_t got = fp ? fread(head, 1, sizeof head, fp) : 0; if (fp) fclose(fp);
    if (got < 44 || !(!memcmp(head, "BIK", 3) || !memcmp(head, "KB2", 3))) return 0;
    uint32_t v[5]; memcpy(&v[0], head + 8, 4); memcpy(&v[1], head + 20, 16);
    uint32_t handle = com_alloc(P, 0x400); const uint32_t fields[7] = {v[1], v[2], v[0], 1, 0, v[3], v[4]};
    for (int i = 0; i < 7; i++) w32(P, handle + 4 * i, fields[i]);
    if (P->nbinks == 8) fail(P, "too many Bink movies");
    bink *b = &P->binks[P->nbinks++]; b->h = handle; b->frames = v[0]; b->rate = v[3]; b->div = v[4] ? v[4] : 1; b->start = P->clock;
    snprintf(b->name, sizeof b->name, "%s", name); return handle;
}
API(bink_buffer_open) { (void)h; uint32_t buf = com_alloc(P, 0x100); const uint32_t v[4] = {a[1], a[2], a[1], a[2]}; for (int i = 0; i < 4; i++) w32(P, buf + 4 * i, v[i]); return buf; }
API(bink_volume) { need_bink(P, a[0]); *h = 0; return 0; }
API(bink_wait) {
    (void)h; bink *b = need_bink(P, a[0]); int64_t frame = r32(P, a[0] + 0xc);
    int64_t due = (int64_t)b->start + floordiv((frame - 1) * 1000 * (int64_t)b->div, b->rate ? (int64_t)b->rate : 1);
    return (int64_t)P->clock < due ? 1 : 0;
}
API(bink_do_frame) { (void)h; need_bink(P, a[0]); return 0; }
API(bink_copy) {
    (void)h; need_bink(P, a[0]); uint32_t dest = a[1], pitch = a[2], dest_h = a[3], dx = a[4], dy = a[5], sw = a[8], sh = a[9], flags = a[10], bpp;
    switch (flags & 0x1f) { case 3: case 4: bpp = 4; break; case 0xa: case 0xb: case 0xc: case 0xd: bpp = 2; break; default: fail(P, "BinkCopyToBufferRect surface type 0x%x", flags); return 0; }
    uint32_t rows = dest_h > dy ? (sh < dest_h - dy ? sh : dest_h - dy) : 0;
    for (uint32_t r = 0; r < rows; r++) zero(P, dest + (dy + r) * pitch + dx * bpp, (size_t)sw * bpp);
    return 0;
}
API(bink_next) {
    bink *b = need_bink(P, a[0]); uint32_t frame = r32(P, a[0] + 0xc); w32(P, a[0] + 0x10, frame);
    w32(P, a[0] + 0xc, frame < b->frames ? frame + 1 : 1); *h = 0; return 0;
}
API(bink_close) { need_bink(P, a[0]); for (unsigned i = 0; i < P->nbinks; i++) if (P->binks[i].h == a[0]) { memmove(&P->binks[i], &P->binks[i + 1], (P->nbinks - i - 1) * sizeof *P->binks); P->nbinks--; break; } *h = 0; return 0; }
/* DirectInput / Direct3D entry points */
API(direct_input_create) {
    (void)h; if (a[1] != 0x800 || !guid_is(P, a[2], IID_DI8A)) { w32(P, a[3], 0); return DIERR_NOINTERFACE; }
    if (a[4]) return 0x80040110u;
    w32(P, a[3], new_object(P, P->iface_of_kind[K_DINPUT])->addr); return 0;
}
API(direct3d_create) { (void)h; return a[0] == 220 ? new_object(P, P->iface_of_kind[K_D3D8])->addr : 0; }

static const struct { const char *name; unsigned nargs; api_handler fn; } APIS[] = {
    {"EnterCriticalSection",1,enter_cs},{"LeaveCriticalSection",1,leave_cs},{"InitializeCriticalSection",1,init_cs},{"DeleteCriticalSection",1,delete_cs},
    {"GlobalAlloc",2,global_alloc},{"GlobalFree",1,global_free},{"TlsAlloc",0,tls_alloc},{"TlsFree",1,tls_free},{"TlsGetValue",1,tls_get},{"TlsSetValue",2,tls_set},
    {"GetStdHandle",1,get_std_handle},{"GetCurrentProcess",0,get_current_process},{"DuplicateHandle",7,duplicate_handle},{"GetCommandLineA",0,get_command_line},
    {"GetEnvironmentStrings",0,get_environment},{"FreeEnvironmentStringsA",1,free_environment},{"CreateEventA",4,create_event},{"GetTickCount",0,get_tick_count},
    {"SystemParametersInfoA",4,system_parameters},{"timeGetTime",0,time_get_time},{"timeBeginPeriod",1,time_period},{"timeEndPeriod",1,time_period},
    {"QueryPerformanceFrequency",1,qpf},{"QueryPerformanceCounter",1,qpc},{"GetUserDefaultLangID",0,lang},{"GetSystemDefaultLangID",0,lang},
    {"GetUserDefaultLCID",0,lang},{"GetSystemDefaultLCID",0,lang},{"SetErrorMode",1,set_error_mode},{"GetModuleFileNameA",3,get_module_file_name},
    {"SetCurrentDirectoryA",1,set_current_directory},{"GetCurrentDirectoryA",2,get_current_directory},{"SetEnvironmentVariableA",2,set_env},
    {"GetEnvironmentVariableA",3,get_env},{"LoadCursorA",2,load_cursor},{"RegisterClassA",1,register_class},{"GetSystemMetrics",1,get_system_metrics},
    {"SetCursorPos",2,set_cursor_pos},{"GetCursorPos",1,get_cursor_pos},{"ShowCursor",1,show_cursor},{"SetCursor",1,set_cursor},{"ClipCursor",1,clip_cursor},
    {"AdjustWindowRect",3,adjust_window_rect},{"CreateWindowExA",12,create_window},{"DefWindowProcA",4,def_window_proc},{"GetModuleHandleA",1,get_module_handle},
    {"GetProcAddress",2,get_proc_address},{"GetDiskFreeSpaceExA",4,get_disk_free_space},{"CreateFileA",7,create_file},{"ReadFile",5,read_file},{"GetOverlappedResult",4,get_overlapped_result},{"SetFilePointer",4,set_file_pointer},
    {"GetFileSize",2,get_file_size},{"WriteFile",5,write_file},{"FileTimeToLocalFileTime",2,file_time_to_local},{"FileTimeToSystemTime",2,file_time_to_system},{"GetFileInformationByHandle",2,get_file_information},{"CloseHandle",1,close_handle},{"DeleteFileA",1,delete_file},{"CreateDirectoryA",2,create_directory},{"GetFileAttributesA",1,get_file_attributes},
    {"RegOpenKeyExA",5,reg_open},{"RegCreateKeyExA",9,reg_create},{"RegCloseKey",1,reg_close},{"RegSetValueExA",6,reg_set_value},{"RegQueryValueExA",6,reg_query_value},
    {"DialogBoxParamA",5,dialog_box},{"EndDialog",2,end_dialog},{"GetDlgItem",2,get_dlg_item},{"GetWindowRect",2,get_window_rect},{"GetClientRect",2,get_client_rect},
    {"ClientToScreen",2,client_to_screen},{"MapVirtualKeyA",2,map_virtual_key},{"ScreenToClient",2,screen_to_client},{"SetWindowPos",7,set_window_pos},{"MoveWindow",6,move_window},
    {"ShowWindow",2,show_window},{"SetTimer",4,set_timer},{"KillTimer",2,kill_timer},{"PeekMessageA",5,peek_message},{"GetMessageA",4,get_message},
    {"PostMessageA",4,post_message},{"PostQuitMessage",1,post_quit},{"TranslateMessage",1,translate_message},{"DispatchMessageA",1,dispatch_message},
    {"SetWindowTextA",2,set_window_text},{"GetWindowTextA",3,get_window_text},{"UpdateWindow",1,update_window},{"IsIconic",1,is_iconic},
    {"IsWindowVisible",1,is_window_visible},{"SetForegroundWindow",1,set_foreground_window},{"GetForegroundWindow",0,get_foreground_window},
    {"GetActiveWindow",0,get_foreground_window},{"GetWindowLongA",2,get_window_long},{"SetWindowLongA",3,set_window_long},{"SetFocus",1,set_focus},
    {"GetFocus",0,get_focus},{"SendMessageA",4,send_message},
    {"_AIL_set_redist_directory@4",1,ail_redist},{"_AIL_startup@0",0,ail_startup},{"_AIL_shutdown@0",0,ail_shutdown},{"_AIL_set_preference@8",2,ail_set_preference},
    {"_AIL_ms_count@0",0,ail_ms_count},{"_AIL_process_digital_audio@24",6,ail_process_audio},{"_AIL_open_digital_driver@16",4,ail_open_driver},{"_AIL_close_digital_driver@4",1,ail_close_driver},
    {"_AIL_enumerate_3D_providers@12",3,ail_enum_providers},{"_AIL_open_3D_provider@4",1,ail_open_provider},{"_AIL_close_3D_provider@4",1,ail_close_provider},
    {"_AIL_set_3D_provider_preference@12",3,ail_provider_pref},{"_AIL_3D_provider_attribute@12",3,ail_provider_attribute},{"_AIL_set_3D_room_type@8",2,ail_set_room},
    {"_AIL_3D_room_type@4",1,ail_room},{"_AIL_allocate_3D_sample_handle@4",1,ail_allocate},{"_AIL_release_3D_sample_handle@4",1,ail_release},
    {"_AIL_set_3D_sample_info@8",2,ail_set_info},{"_AIL_start_3D_sample@4",1,ail_start},{"_AIL_stop_3D_sample@4",1,ail_stop},{"_AIL_resume_3D_sample@4",1,ail_resume},
    {"_AIL_end_3D_sample@4",1,ail_end},{"_AIL_3D_sample_status@4",1,ail_status},{"_AIL_3D_sample_length@4",1,ail_length},{"_AIL_3D_sample_offset@4",1,ail_offset},
    {"_AIL_set_3D_sample_loop_count@8",2,ail_loop_count},{"_AIL_set_3D_sample_loop_block@12",3,ail_loop_block},{"_AIL_set_3D_position@16",4,ail_setter},
    {"_AIL_set_3D_sample_volume@8",2,ail_set_volume},{"_AIL_set_3D_sample_distances@12",3,ail_setter},{"_AIL_set_3D_sample_effects_level@8",2,ail_setter},
    {"_AIL_set_3D_sample_occlusion@8",2,ail_setter},{"_AIL_set_3D_sample_playback_rate@8",2,ail_set_rate},
    {"_BinkSetSoundSystem@8",2,bink_sound},{"_BinkOpen@8",2,bink_open},{"_BinkBufferOpen@16",4,bink_buffer_open},{"_BinkSetVolume@12",3,bink_volume},
    {"_BinkWait@4",1,bink_wait},{"_BinkDoFrame@4",1,bink_do_frame},{"_BinkCopyToBufferRect@44",11,bink_copy},{"_BinkNextFrame@4",1,bink_next},{"_BinkClose@4",1,bink_close},
    {"DirectInput8Create",5,direct_input_create},{"Direct3DCreate8",1,direct3d_create}};

int mh_port_find_api(const char *name) { for (unsigned i = 0; i < sizeof APIS / sizeof APIS[0]; i++) if (!strcmp(APIS[i].name, name)) return (int)i; return -1; }
unsigned mh_port_api_args(int api) { return APIS[api].nargs; }
const char *mh_port_api_name(int api) { return APIS[api].name; }
void mh_port_call_api(mh_port *P, int api, uint32_t esp, uint32_t *eax, int *has_eax) {
    uint32_t a[12] = {0}, saved = P->api_esp;
    for (unsigned i = 0; i < 12; i++) mh_mem_read_u32(P->mem, esp + 4 + 4 * i, &a[i]);   /* the reference reads 12 */
    P->api_esp = esp; *has_eax = 1;
    *eax = APIS[api].fn(P, a, has_eax);
    P->api_esp = saved;
}

/* ---------------------------------------------------------------- lifetime */
mh_port *mh_port_create(mh_guest_memory *memory, const mh_port_host *host, const char *game_dir, unsigned frame_limit) {
    mh_port *P = calloc(1, sizeof *P);
    if (!P) return NULL;
    init_caps();
    P->mem = memory; P->host = *host; P->frame_limit = frame_limit; snprintf(P->game_dir, sizeof P->game_dir, "%s", game_dir);
    for (int k = 0; k < K_KINDS; k++) P->iface_of_kind[k] = -1;
    mh_win32_thread_init(&P->thread);
    if (!mh_win32_process_init(&P->process, memory, PROCESS_DATA) || !mh_win32_global_init(&P->global, GLOBAL_BASE, GLOBAL_SIZE)) { free(P); return NULL; }
    P->clock = 0x10000; P->langid = 0x0409; snprintf(P->cwd, sizeof P->cwd, "C:\\Manhunt");
    P->cursor.x = 640; P->cursor.y = 360; P->cursor.handle = 0x60007f00u;
    P->com_next = MH_PORT_COM_HEAP; P->res_next = MH_PORT_RES_BASE;
    P->mss_redist = MH_PORT_MSS_SCRATCH; P->mss_scratch = MH_PORT_MSS_SCRATCH + 0x10;
    return P;
}
/* The WinMain stage starts: what tools/winmain_apis.make() does on creation. */
void mh_port_begin_winmain(mh_port *P);
void mh_port_begin_winmain(mh_port *P) {
    interface(P, K_DIDEVICE); interface(P, K_DINPUT); interface(P, K_D3D8);
    uint8_t z = 0; wbytes(P, MH_PORT_MSS_SCRATCH, &z, 1);
}
void mh_port_destroy(mh_port *P) {
    if (!P) return;
    for (unsigned i = 0; i < P->nobjects; i++) free(P->objects[i]);
    for (unsigned i = 0; i < P->nreg; i++) { for (unsigned j = 0; j < P->reg[i].nvalues; j++) free(P->reg[i].values[j].data); free(P->reg[i].values); }
    for (unsigned i = 0; i < P->novfiles; i++) free(P->ovfiles[i].data);
    free(P->ovfiles); free(P->objects); free(P->files); free(P->reg); free(P->controls); free(P->res_free); free(P);
}
uint32_t *mh_port_last_error(mh_port *P) { return &P->thread.last_error; }
uint32_t mh_port_cwd(mh_port *P, char *out, size_t size) { snprintf(out, size, "%s", P->cwd); return (uint32_t)strlen(P->cwd); }
uint64_t mh_port_clock(const mh_port *P) { return P->clock; }
void mh_port_set_clock(mh_port *P, uint64_t (*now_ms)(void *user), void *user) {
    P->now_ms = now_ms; P->now_user = user; if (now_ms) P->now_base = now_ms(user) - (P->clock - 0x10000);
}
/* rdtsc: a 1 GHz counter on the virtual clock, strictly increasing (each read adds one). */
uint64_t mh_port_rdtsc(mh_port *P) { return P->clock * 1000000u + ++P->tsc_reads; }
unsigned mh_port_frames(const mh_port *P) { return P->frames; }
void mh_port_mouse_move(mh_port *P, int dx, int dy) { P->mouse_dx += dx; P->mouse_dy += dy; }
void mh_port_set_save_readonly(mh_port *P, int readonly) { P->save_readonly = readonly != 0; }
void mh_port_set_save_dir(mh_port *P, const char *dir) { snprintf(P->save_dir, sizeof P->save_dir, "%s", dir ? dir : ""); }
void mh_port_set_language(mh_port *P, uint32_t langid) { P->langid = langid & 0xffff; }
void mh_port_set_key(mh_port *P, unsigned key, int down) {
    if (key < 256) P->keys[key] = down ? 1 : 0; else if (key - 0x100 < 8) P->mouse_buttons[key - 0x100] = down ? 1 : 0;
}
int mh_port_set_key_script(mh_port *P, const mh_port_key_span *spans, unsigned n) {
    if (n > 64) return 0;
    memcpy(P->script, spans, n * sizeof *spans); P->nscript = n; return 1;
}
unsigned mh_port_parse_key_script(const char *text, mh_port_key_span *out, unsigned max) {
    unsigned n = 0;
    while (text && *text && n < max) {
        unsigned k, f, t; int used = 0;
        if (sscanf(text, "%x:%u:%u%n", &k, &f, &t, &used) != 3 || (k > 0x107 && (k < 0x200 || k > 0x203))) break;
        out[n].key = k; out[n].from = f; out[n].to = t; n++; text += used; if (*text == ',') text++;
    }
    return n;
}
uint32_t mh_port_com_next(const mh_port *P) { return P->com_next; }
uint32_t mh_port_res_next(const mh_port *P) { return P->res_next; }
mh_win32_global_heap *mh_port_global(mh_port *P);
mh_win32_global_heap *mh_port_global(mh_port *P) { return &P->global; }

/* ---------------------------------------------------------------- renderer interface */
void mh_port_set_audio(mh_port *P, const mh_port_audio *a) { if (a) { P->audio = *a; P->has_audio = 1; } else P->has_audio = 0; }
void mh_port_set_renderer(mh_port *P, const mh_port_renderer *r) { if (r) { P->renderer = *r; P->has_renderer = 1; } else P->has_renderer = 0; }
int mh_port_device_size(mh_port *P, uint32_t *w, uint32_t *h) { if (!P->device) return 0; *w = P->device->params.width; *h = P->device->params.height; return 1; }
uint32_t mh_port_render_state(mh_port *P, uint32_t s) {
    int known; uint32_t d = rs_default(P, s, &known);
    return P->device && s < 256 && P->device->rs_set[s] ? P->device->rs[s] : d;
}
uint32_t mh_port_stage_state(mh_port *P, uint32_t stage, uint32_t t) {
    if (stage >= 8 || t >= 32) return 0;
    if (P->device && P->device->tss_set[stage][t]) return P->device->tss[stage][t];
    switch (t) { case 12: case 29: case 30: case 31: case 0: return 0; default: return tss_default(P, stage, t); }
}
int mh_port_transform(mh_port *P, uint32_t index, float m[16]) {
    static const float identity[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
    memcpy(m, identity, sizeof identity);
    if (!P->device) return 0;
    for (unsigned i = 0; i < P->device->ntransforms; i++) if (P->device->transforms[i].index == index) { memcpy(m, P->device->transforms[i].m, 64); return 1; }
    return 0;
}
void mh_port_viewport(mh_port *P, uint32_t v[6]) {
    com_obj *d = P->device;
    if (d && d->has_viewport) { memcpy(v, d->viewport, 24); return; }
    v[0] = 0; v[1] = 0; v[2] = d ? d->params.width : 0; v[3] = d ? d->params.height : 0; v[4] = F(0.0f); v[5] = F(1.0f);
}
uint32_t mh_port_fvf(mh_port *P) { return P->device ? P->device->vertex_shader : 0; }
int mh_port_texture(mh_port *P, uint32_t stage, mh_port_texture_info *info) {
    if (!P->device || stage >= 8 || !P->device->textures[stage]) return 0;
    com_obj *t = object(P, P->device->textures[stage]);
    if (!t || t->kind != K_TEXTURE) return 0;
    memset(info, 0, sizeof *info); info->format = t->format; info->width = t->levels[0].width; info->height = t->levels[0].height; info->levels = t->nlevels;
    for (unsigned i = 0; i < t->nlevels; i++) {
        info->memory[i] = t->levels[i].memory; info->pitch[i] = t->levels[i].pitch; info->level_width[i] = t->levels[i].width;
        info->level_height[i] = t->levels[i].height; info->version[i] = t->levels[i].version;
    }
    return 1;
}
int mh_port_stream(mh_port *P, uint32_t stream, uint32_t *memory, uint32_t *length, uint32_t *stride) {
    if (!P->device) return 0;
    for (unsigned i = 0; i < P->device->nstreams; i++) if (P->device->streams[i].stream == stream) {
        com_obj *b = object(P, P->device->streams[i].buffer);
        if (!b || b->kind != K_VBUF) return 0;
        *memory = b->memory; *length = b->length; *stride = P->device->streams[i].stride; return 1;
    }
    return 0;
}
uint32_t mh_port_stream_version(mh_port *P, uint32_t stream) {
    if (!P->device) return 0;
    for (unsigned i = 0; i < P->device->nstreams; i++) if (P->device->streams[i].stream == stream) {
        com_obj *b = object(P, P->device->streams[i].buffer);
        return b && b->kind == K_VBUF ? b->version : 0;
    }
    return 0;
}
uint32_t mh_port_indices_version(mh_port *P) {
    if (!P->device || !P->device->indices[0]) return 0;
    com_obj *b = object(P, P->device->indices[0]);
    return b && b->kind == K_IBUF ? b->version : 0;
}
int mh_port_indices(mh_port *P, uint32_t *memory, uint32_t *length, uint32_t *format, uint32_t *base_vertex) {
    if (!P->device || !P->device->indices[0]) return 0;
    com_obj *b = object(P, P->device->indices[0]);
    if (!b || b->kind != K_IBUF) return 0;
    *memory = b->memory; *length = b->length; *format = b->format; *base_vertex = P->device->indices[1]; return 1;
}

unsigned mh_port_lights(mh_port *P, uint32_t (*out)[26], unsigned max) {
    com_obj *d = P->device; unsigned n = 0; if (!d) return 0;
    for (unsigned i = 0; i < d->nlight_enable && n < max; i++) {
        if (!d->light_enable[i].v) continue;
        for (unsigned j = 0; j < d->nlights; j++)
            if (d->lights[j].index == d->light_enable[i].k) { memcpy(out[n++], d->lights[j].l, sizeof d->lights[j].l); break; }
    }
    return n;
}
void mh_port_material(mh_port *P, uint32_t out[17]) {
    if (P->device) memcpy(out, P->device->material, 17 * sizeof *out); else memset(out, 0, 17 * sizeof *out);
}
int mh_port_render_target(mh_port *P, uint32_t *memory, uint32_t *width, uint32_t *height, uint32_t *format) {
    com_obj *d = P->device; if (!d || !d->render_target || d->render_target == d->back_buffer) return 0;
    com_obj *s = object(P, d->render_target); if (!s) return 0;
    *memory = s->has_memory ? s->memory : 0;   /* read only: the guest's state is never changed here */ *width = s->width; *height = s->height; *format = s->format; return 1;
}
