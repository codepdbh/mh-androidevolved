/* Reference software renderer for the port's Direct3D 8 device; see sw_renderer.h. */
#include "sw_renderer.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t memory, version, format, width, height; uint8_t *rgba; } tex_entry;
struct mh_sw_renderer {
    mh_guest_memory *mem; FILE *log; char png[512];
    uint32_t width, height; uint8_t *color; float *depth;
    tex_entry cache[256]; unsigned ncache;
};

/* ------------------------------------------------------------------ guest reads */
static const uint8_t *span(mh_sw_renderer *r, uint32_t a, size_t n) { return n ? mh_mem_span(r->mem, a, n) : NULL; }
static float rf(const uint8_t *p) { float f; memcpy(&f, p, 4); return f; }
static uint32_t ru(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static uint32_t bitsf(uint32_t b) { return b; }
static float asf(uint32_t b) { float f; memcpy(&f, &b, 4); return f; }

/* ------------------------------------------------------------------ framebuffer */
static int ensure(mh_sw_renderer *r, mh_port *port) {
    uint32_t w, h;
    if (!mh_port_device_size(port, &w, &h) || !w || !h) return 0;
    if (w != r->width || h != r->height) {
        free(r->color); free(r->depth);
        r->color = calloc((size_t)w * h, 4); r->depth = malloc((size_t)w * h * sizeof(float));
        if (!r->color || !r->depth) return 0;
        for (size_t i = 0; i < (size_t)w * h; i++) { r->depth[i] = 1.0f; r->color[4 * i + 3] = 255; }
        r->width = w; r->height = h;
    }
    return 1;
}

/* ------------------------------------------------------------------ textures */
static void rgba(uint8_t *o, uint32_t r8, uint32_t g8, uint32_t b8, uint32_t a8) { o[0] = (uint8_t)r8; o[1] = (uint8_t)g8; o[2] = (uint8_t)b8; o[3] = (uint8_t)a8; }
static void c565(uint16_t c, uint32_t *r8, uint32_t *g8, uint32_t *b8) {
    uint32_t r5 = c >> 11, g6 = (c >> 5) & 63, b5 = c & 31;
    *r8 = (r5 << 3) | (r5 >> 2); *g8 = (g6 << 2) | (g6 >> 4); *b8 = (b5 << 3) | (b5 >> 2);
}
static void dxt_block(const uint8_t *b, int format, uint8_t out[16][4]) {
    const uint8_t *cb = format == 1 ? b : b + 8;
    uint16_t c0 = (uint16_t)(cb[0] | cb[1] << 8), c1 = (uint16_t)(cb[2] | cb[3] << 8);
    uint32_t pal[4][4]; uint32_t r0, g0, b0, r1, g1, b1;
    c565(c0, &r0, &g0, &b0); c565(c1, &r1, &g1, &b1);
    pal[0][0] = r0; pal[0][1] = g0; pal[0][2] = b0; pal[0][3] = 255;
    pal[1][0] = r1; pal[1][1] = g1; pal[1][2] = b1; pal[1][3] = 255;
    if (c0 > c1 || format != 1) {
        for (int k = 0; k < 3; k++) { uint32_t a = pal[0][k], c = pal[1][k]; pal[2][k] = (2 * a + c) / 3; pal[3][k] = (a + 2 * c) / 3; }
        pal[2][3] = pal[3][3] = 255;
    } else {
        for (int k = 0; k < 3; k++) { pal[2][k] = (pal[0][k] + pal[1][k]) / 2; pal[3][k] = 0; }
        pal[2][3] = 255; pal[3][3] = 0;
    }
    uint32_t idx = (uint32_t)cb[4] | (uint32_t)cb[5] << 8 | (uint32_t)cb[6] << 16 | (uint32_t)cb[7] << 24;
    for (int i = 0; i < 16; i++) { uint32_t *c = pal[(idx >> (2 * i)) & 3]; rgba(out[i], c[0], c[1], c[2], c[3]); }
    if (format == 2 || format == 3) {        /* explicit 4-bit alpha */
        for (int i = 0; i < 16; i++) { uint32_t a = (b[i / 2] >> ((i & 1) * 4)) & 15; out[i][3] = (uint8_t)(a * 17); }
    } else if (format == 4 || format == 5) { /* interpolated alpha */
        uint32_t a[8]; a[0] = b[0]; a[1] = b[1];
        if (a[0] > a[1]) for (int k = 1; k < 7; k++) a[k + 1] = ((7 - k) * a[0] + k * a[1]) / 7;
        else { for (int k = 1; k < 5; k++) a[k + 1] = ((5 - k) * a[0] + k * a[1]) / 5; a[6] = 0; a[7] = 255; }
        uint64_t bits = 0; for (int k = 0; k < 6; k++) bits |= (uint64_t)b[2 + k] << (8 * k);
        for (int i = 0; i < 16; i++) out[i][3] = (uint8_t)a[(bits >> (3 * i)) & 7];
    }
}
static const uint8_t *texture_rgba(mh_sw_renderer *r, const mh_port_texture_info *t, uint32_t *w, uint32_t *h) {
    uint32_t mem = t->memory[0], ver = t->version[0];
    *w = t->level_width[0]; *h = t->level_height[0];
    for (unsigned i = 0; i < r->ncache; i++) {
        tex_entry *e = &r->cache[i];
        if (e->memory == mem && e->format == t->format && e->width == *w && e->height == *h) {
            if (e->version == ver) return e->rgba;
            free(e->rgba); e->rgba = NULL; e->version = ver; goto decode_into;
        }
    }
    if (r->ncache == 256) { for (unsigned i = 0; i < 256; i++) free(r->cache[i].rgba); r->ncache = 0; }
    {
        tex_entry *e = &r->cache[r->ncache++]; e->memory = mem; e->version = ver; e->format = t->format; e->width = *w; e->height = *h; e->rgba = NULL;
    }
decode_into:;
    tex_entry *e = NULL;
    for (unsigned i = 0; i < r->ncache; i++) if (r->cache[i].memory == mem && r->cache[i].format == t->format && r->cache[i].width == *w && r->cache[i].height == *h) e = &r->cache[i];
    uint8_t *out = calloc((size_t)*w * *h, 4); if (!out) return NULL;
    uint32_t f = t->format, pitch = t->pitch[0];
    if (f >= 0x31545844u && f <= 0x35545844u) {       /* DXT1..DXT5 */
        int fmt = (int)((f >> 24) - '0'); uint32_t bw = (*w + 3) / 4, bh = (*h + 3) / 4, bs = fmt == 1 ? 8 : 16;
        for (uint32_t by = 0; by < bh; by++) for (uint32_t bx = 0; bx < bw; bx++) {
            const uint8_t *b = span(r, mem + by * pitch + bx * bs, bs); uint8_t px[16][4];
            if (!b) continue;
            dxt_block(b, fmt, px);
            for (int i = 0; i < 16; i++) { uint32_t x = bx * 4 + (uint32_t)(i & 3), y = by * 4 + (uint32_t)(i >> 2); if (x < *w && y < *h) memcpy(out + 4 * ((size_t)y * *w + x), px[i], 4); }
        }
    } else {
        for (uint32_t y = 0; y < *h; y++) {
            const uint8_t *row = span(r, mem + y * pitch, pitch); if (!row) continue;
            for (uint32_t x = 0; x < *w; x++) {
                uint8_t *o = out + 4 * ((size_t)y * *w + x); uint32_t r8, g8, b8;
                switch (f) {
                case 21: rgba(o, row[4 * x + 2], row[4 * x + 1], row[4 * x], row[4 * x + 3]); break;
                case 22: rgba(o, row[4 * x + 2], row[4 * x + 1], row[4 * x], 255); break;
                case 23: c565((uint16_t)(row[2 * x] | row[2 * x + 1] << 8), &r8, &g8, &b8); rgba(o, r8, g8, b8, 255); break;
                case 24: case 25: { uint16_t c = (uint16_t)(row[2 * x] | row[2 * x + 1] << 8); uint32_t r5 = (c >> 10) & 31, g5 = (c >> 5) & 31, b5 = c & 31;
                    rgba(o, (r5 << 3) | (r5 >> 2), (g5 << 3) | (g5 >> 2), (b5 << 3) | (b5 >> 2), f == 25 ? ((c >> 15) ? 255 : 0) : 255); break; }
                case 26: { uint16_t c = (uint16_t)(row[2 * x] | row[2 * x + 1] << 8); rgba(o, ((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, (c >> 12) * 17); break; }
                case 28: rgba(o, 255, 255, 255, row[x]); break;
                case 50: rgba(o, row[x], row[x], row[x], 255); break;
                case 51: rgba(o, row[2 * x], row[2 * x], row[2 * x], row[2 * x + 1]); break;
                default: rgba(o, 255, 0, 255, 255); break;   /* unknown format: magenta */
                }
            }
        }
    }
    e->rgba = out; return out;
}
static void sample_texture(const uint8_t *tex, uint32_t w, uint32_t h, float u, float v, uint32_t au, uint32_t av, float out[4]) {
    float fu = u * (float)w, fv = v * (float)h; long x = (long)floorf(fu), y = (long)floorf(fv);
    if (au == 3) x = x < 0 ? 0 : x >= (long)w ? (long)w - 1 : x; else { x %= (long)w; if (x < 0) x += w; }
    if (av == 3) y = y < 0 ? 0 : y >= (long)h ? (long)h - 1 : y; else { y %= (long)h; if (y < 0) y += h; }
    const uint8_t *p = tex + 4 * ((size_t)y * w + (size_t)x);
    for (int k = 0; k < 4; k++) out[k] = p[k] / 255.0f;
}

/* ------------------------------------------------------------------ vertices */
typedef struct { float x, y, z, rhw; float diffuse[4], specular[4]; float u, v; int ok; } vtx;
typedef struct { uint32_t fvf, stride, pos_size, off_diffuse, off_specular, off_tex0; int transformed, has_diffuse, has_specular, ntex; } layout;
static layout fvf_layout(uint32_t fvf, uint32_t stride) {
    layout L; memset(&L, 0, sizeof L); L.fvf = fvf; L.stride = stride;
    uint32_t pos = fvf & 0x00e, off;
    L.transformed = pos == 0x004;
    off = pos == 0x002 ? 12 : pos == 0x004 ? 16 : pos >= 0x006 ? 12 + 4 * ((pos - 0x004) / 2) : 0;
    if (fvf & 0x010) off += 12;
    if (fvf & 0x020) off += 4;
    if (fvf & 0x040) { L.has_diffuse = 1; L.off_diffuse = off; off += 4; }
    if (fvf & 0x080) { L.has_specular = 1; L.off_specular = off; off += 4; }
    L.ntex = (int)((fvf >> 8) & 15); L.off_tex0 = off; L.pos_size = pos;
    return L;
}
static void color4(uint32_t c, float o[4]) { o[0] = ((c >> 16) & 255) / 255.0f; o[1] = ((c >> 8) & 255) / 255.0f; o[2] = (c & 255) / 255.0f; o[3] = (c >> 24) / 255.0f; }
static void mul(const float *v, const float *m, float *o) { for (int j = 0; j < 4; j++) o[j] = v[0] * m[j] + v[1] * m[4 + j] + v[2] * m[8 + j] + v[3] * m[12 + j]; }
static vtx fetch(mh_sw_renderer *r, mh_port *port, const layout *L, uint32_t base, uint32_t index, const float *wvp, const uint32_t *vp) {
    vtx o; memset(&o, 0, sizeof o);
    const uint8_t *p = span(r, base + index * L->stride, L->stride ? L->stride : 16);
    (void)port;
    if (!p) return o;
    if (L->transformed) { o.x = rf(p); o.y = rf(p + 4); o.z = rf(p + 8); o.rhw = rf(p + 12); }
    else {
        float v[4] = {rf(p), rf(p + 4), rf(p + 8), 1.0f}, c[4]; mul(v, wvp, c);
        if (c[3] <= 1e-6f) return o;
        float vw = (float)vp[2], vh = (float)vp[3], minz = asf(vp[4]), maxz = asf(vp[5]);   /* X, Y, Width, Height are integers */
        o.x = (float)vp[0] + (1.0f + c[0] / c[3]) * vw * 0.5f; o.y = (float)vp[1] + (1.0f - c[1] / c[3]) * vh * 0.5f;
        o.z = minz + c[2] / c[3] * (maxz - minz); o.rhw = 1.0f / c[3];
    }
    if (L->has_diffuse) color4(ru(p + L->off_diffuse), o.diffuse); else { o.diffuse[0] = o.diffuse[1] = o.diffuse[2] = o.diffuse[3] = 1.0f; }
    if (L->has_specular) color4(ru(p + L->off_specular), o.specular);
    if (L->ntex) { o.u = rf(p + L->off_tex0); o.v = rf(p + L->off_tex0 + 4); }
    o.ok = 1; return o;
}

/* ------------------------------------------------------------------ pixel pipeline */
typedef struct {
    int has_tex; const uint8_t *tex; uint32_t tw, th, addr_u, addr_v;
    uint32_t colorop, carg1, carg2, alphaop, aarg1, aarg2, tfactor;
    int alpha_test; uint32_t alpha_ref, alpha_func; int blend; uint32_t src, dst;
    int ztest, zwrite; uint32_t zfunc;
} pipeline;
static int compare(uint32_t func, float a, float b) {
    switch (func) { case 1: return 0; case 2: return a < b; case 3: return a == b; case 4: return a <= b; case 5: return a > b; case 6: return a != b; case 7: return a >= b; default: return 1; }
}
static void arg(uint32_t a, const float *diffuse, const float *tex, const float *tfactor, const float *specular, float o[4]) {
    const float *s = (a & 15) == 2 ? tex : (a & 15) == 3 ? tfactor : (a & 15) == 4 ? specular : diffuse;
    for (int k = 0; k < 4; k++) o[k] = s[k];
    if (a & 0x20) o[0] = o[1] = o[2] = s[3];
    if (a & 0x10) for (int k = 0; k < 4; k++) o[k] = 1.0f - o[k];
}
static float combine(uint32_t op, float a, float b, float diffuse) {
    switch (op) {
    case 1: return diffuse; case 2: return a; case 3: return b; case 4: return a * b; case 5: return fminf(1.0f, 2 * a * b); case 6: return fminf(1.0f, 4 * a * b);
    case 7: return fminf(1.0f, a + b); case 8: return fmaxf(0.0f, fminf(1.0f, a + b - 0.5f)); default: return a * b;
    }
}
static float factor(uint32_t f, const float *src, const float *dst, int k) {
    switch (f) {
    case 1: return 0; case 2: return 1; case 3: return src[k]; case 4: return 1 - src[k]; case 5: return src[3]; case 6: return 1 - src[3];
    case 7: return dst[3]; case 8: return 1 - dst[3]; case 9: return dst[k]; case 10: return 1 - dst[k]; default: return 1;
    }
}
static void shade(mh_sw_renderer *r, const pipeline *pl, int x, int y, float z, const float *diffuse, const float *specular, float u, float v) {
    size_t at = (size_t)y * r->width + (size_t)x;
    if (pl->ztest && !compare(pl->zfunc, z, r->depth[at])) return;
    float tex[4] = {1, 1, 1, 1}, a1[4], a2[4], out[4], tf[4];
    color4(pl->tfactor, tf);
    if (pl->has_tex && pl->tex) sample_texture(pl->tex, pl->tw, pl->th, u, v, pl->addr_u, pl->addr_v, tex);
    arg(pl->carg1, diffuse, tex, tf, specular, a1); arg(pl->carg2, diffuse, tex, tf, specular, a2);
    for (int k = 0; k < 3; k++) out[k] = combine(pl->colorop, a1[k], a2[k], diffuse[k]);
    arg(pl->aarg1, diffuse, tex, tf, specular, a1); arg(pl->aarg2, diffuse, tex, tf, specular, a2);
    out[3] = combine(pl->alphaop, a1[3], a2[3], diffuse[3]);
    if (pl->alpha_test && !compare(pl->alpha_func, out[3] * 255.0f, (float)pl->alpha_ref)) return;
    uint8_t *px = r->color + 4 * at;
    if (pl->blend) {
        float dst[4] = {px[0] / 255.0f, px[1] / 255.0f, px[2] / 255.0f, px[3] / 255.0f}, src[4] = {out[0], out[1], out[2], out[3]};
        for (int k = 0; k < 4; k++) out[k] = fminf(1.0f, src[k] * factor(pl->src, src, dst, k) + dst[k] * factor(pl->dst, src, dst, k));
    }
    for (int k = 0; k < 4; k++) px[k] = (uint8_t)(fmaxf(0.0f, fminf(1.0f, out[k])) * 255.0f + 0.5f);
    if (pl->zwrite) r->depth[at] = z;
}
static float edge(float ax, float ay, float bx, float by, float px, float py) { return (bx - ax) * (py - ay) - (by - ay) * (px - ax); }
static void triangle(mh_sw_renderer *r, const pipeline *pl, uint32_t cull, vtx a, vtx b, vtx c) {
    if (!a.ok || !b.ok || !c.ok) return;
    float area = edge(a.x, a.y, b.x, b.y, c.x, c.y);
    if (area == 0) return;
    if ((cull == 2 && area > 0) || (cull == 3 && area < 0)) return;   /* screen y grows down: area > 0 is clockwise */
    int x0 = (int)floorf(fminf(a.x, fminf(b.x, c.x))), x1 = (int)ceilf(fmaxf(a.x, fmaxf(b.x, c.x)));
    int y0 = (int)floorf(fminf(a.y, fminf(b.y, c.y))), y1 = (int)ceilf(fmaxf(a.y, fmaxf(b.y, c.y)));
    if (x0 < 0) x0 = 0; if (y0 < 0) y0 = 0; if (x1 > (int)r->width - 1) x1 = (int)r->width - 1; if (y1 > (int)r->height - 1) y1 = (int)r->height - 1;
    for (int y = y0; y <= y1; y++) for (int x = x0; x <= x1; x++) {
        float px = (float)x, py = (float)y;   /* Direct3D samples pixel centres at integer coordinates */
        float w0 = edge(b.x, b.y, c.x, c.y, px, py) / area, w1 = edge(c.x, c.y, a.x, a.y, px, py) / area, w2 = 1 - w0 - w1;
        if (w0 < 0 || w1 < 0 || w2 < 0) continue;
        float z = w0 * a.z + w1 * b.z + w2 * c.z, q = w0 * a.rhw + w1 * b.rhw + w2 * c.rhw; if (q == 0) q = 1;
        float pa = w0 * a.rhw / q, pb = w1 * b.rhw / q, pc = w2 * c.rhw / q, d[4], s[4];
        for (int k = 0; k < 4; k++) { d[k] = pa * a.diffuse[k] + pb * b.diffuse[k] + pc * c.diffuse[k]; s[k] = pa * a.specular[k] + pb * b.specular[k] + pc * c.specular[k]; }
        shade(r, pl, x, y, z, d, s, pa * a.u + pb * b.u + pc * c.u, pa * a.v + pb * b.v + pc * c.v);
    }
}

/* ------------------------------------------------------------------ device notifications */
static void on_clear(void *user, mh_port *port, uint32_t count, uint32_t rects, uint32_t flags, uint32_t color, float z, uint32_t stencil) {
    mh_sw_renderer *r = user; (void)stencil;
    if (!ensure(r, port)) return;
    if (r->log) fprintf(r->log, "clear count=%u flags=%x color=%08x z=%g\n", count, flags, color, z);
    for (uint32_t i = 0; i < (count ? count : 1); i++) {
        int32_t x0 = 0, y0 = 0, x1 = (int32_t)r->width, y1 = (int32_t)r->height;
        if (count) { const uint8_t *p = span(r, rects + 16 * i, 16); if (!p) continue; x0 = (int32_t)ru(p); y0 = (int32_t)ru(p + 4); x1 = (int32_t)ru(p + 8); y1 = (int32_t)ru(p + 12); }
        if (x0 < 0) x0 = 0; if (y0 < 0) y0 = 0; if (x1 > (int32_t)r->width) x1 = (int32_t)r->width; if (y1 > (int32_t)r->height) y1 = (int32_t)r->height;
        for (int32_t y = y0; y < y1; y++) for (int32_t x = x0; x < x1; x++) {
            size_t at = (size_t)y * r->width + (size_t)x;
            if (flags & 1) { uint8_t *px = r->color + 4 * at; px[0] = (uint8_t)(color >> 16); px[1] = (uint8_t)(color >> 8); px[2] = (uint8_t)color; px[3] = (uint8_t)(color >> 24); }
            if (flags & 2) r->depth[at] = z;
        }
    }
}
static void on_draw(void *user, mh_port *port, const mh_port_draw_call *call) {
    mh_sw_renderer *r = user;
    if (!ensure(r, port)) return;
    uint32_t fvf = mh_port_fvf(port), base = 0, stride = 0, length = 0, imem = 0, ilen = 0, ifmt = 101, basev = 0, count, first = 0, nverts = 0;
    int indexed = call->kind == MH_DRAW_INDEXED || call->kind == MH_DRAW_INDEXED_UP;
    switch (call->kind) {
    case MH_DRAW_PRIMITIVE: first = call->args[0]; count = call->args[1]; mh_port_stream(port, 0, &base, &length, &stride); break;
    case MH_DRAW_INDEXED: count = call->args[3]; first = call->args[2]; nverts = call->args[1];
        mh_port_stream(port, 0, &base, &length, &stride); mh_port_indices(port, &imem, &ilen, &ifmt, &basev); break;
    case MH_DRAW_PRIMITIVE_UP: count = call->args[0]; base = call->args[1]; stride = call->args[2]; break;
    default: count = call->args[2]; imem = call->args[3]; ifmt = call->args[4]; base = call->args[5]; stride = call->args[6]; nverts = call->args[1]; break;
    }
    layout L = fvf_layout(fvf, stride);
    pipeline pl; memset(&pl, 0, sizeof pl);
    mh_port_texture_info ti;
    if (mh_port_texture(port, 0, &ti)) { pl.has_tex = 1; pl.tex = texture_rgba(r, &ti, &pl.tw, &pl.th); }
    pl.addr_u = mh_port_stage_state(port, 0, 13); pl.addr_v = mh_port_stage_state(port, 0, 14);
    pl.colorop = mh_port_stage_state(port, 0, 1); pl.carg1 = mh_port_stage_state(port, 0, 2); pl.carg2 = mh_port_stage_state(port, 0, 3);
    pl.alphaop = mh_port_stage_state(port, 0, 4); pl.aarg1 = mh_port_stage_state(port, 0, 5); pl.aarg2 = mh_port_stage_state(port, 0, 6);
    if (!pl.has_tex) { if (pl.colorop != 1) pl.colorop = (pl.carg1 & 15) == 2 ? 3 : pl.colorop; }
    pl.tfactor = mh_port_render_state(port, 60);
    pl.alpha_test = mh_port_render_state(port, 15) != 0; pl.alpha_ref = mh_port_render_state(port, 24); pl.alpha_func = mh_port_render_state(port, 25);
    pl.blend = mh_port_render_state(port, 27) != 0; pl.src = mh_port_render_state(port, 19); pl.dst = mh_port_render_state(port, 20);
    pl.ztest = mh_port_render_state(port, 7) != 0; pl.zwrite = mh_port_render_state(port, 14) != 0; pl.zfunc = mh_port_render_state(port, 23);
    uint32_t cull = mh_port_render_state(port, 22);
    float world[16], view[16], proj[16], wv[16], wvp[16]; uint32_t vp[6];
    mh_port_transform(port, 256, world); mh_port_transform(port, 2, view); mh_port_transform(port, 3, proj); mh_port_viewport(port, vp);
    for (int i = 0; i < 4; i++) { mul(world + 4 * i, view, wv + 4 * i); }
    for (int i = 0; i < 4; i++) { mul(wv + 4 * i, proj, wvp + 4 * i); }
    if (r->log) fprintf(r->log, "draw kind=%d prim=%u count=%u first=%u verts=%u fvf=%03x stride=%u tex=%s%ux%u fmt=%08x colorop=%u(%x,%x) alphaop=%u blend=%d(%u,%u) atest=%d z=%d/%d cull=%u\n",
                        call->kind, call->primitive, count, first, nverts, fvf, stride, pl.has_tex ? "" : "none ", pl.tw, pl.th, pl.has_tex ? ti.format : 0,
                        pl.colorop, pl.carg1, pl.carg2, pl.alphaop, pl.blend, pl.src, pl.dst, pl.alpha_test, pl.ztest, pl.zwrite, cull);
    uint32_t ntri = call->primitive >= 4 && call->primitive <= 6 ? count : 0;
    for (uint32_t t = 0; t < ntri; t++) {
        uint32_t k[3];
        if (call->primitive == 4) { k[0] = 3 * t; k[1] = 3 * t + 1; k[2] = 3 * t + 2; }
        else if (call->primitive == 5) { k[0] = t; k[1] = t + 1; k[2] = t + 2; if (t & 1) { uint32_t s = k[0]; k[0] = k[1]; k[1] = s; } }
        else { k[0] = 0; k[1] = t + 1; k[2] = t + 2; }
        vtx v[3];
        for (int j = 0; j < 3; j++) {
            uint32_t index = first + k[j];
            if (indexed) {
                uint32_t isz = ifmt == 102 ? 4 : 2; const uint8_t *ip = span(r, imem + index * isz, isz);
                index = ip ? (isz == 4 ? ru(ip) : (uint32_t)(ip[0] | ip[1] << 8)) : 0;
                if (call->kind == MH_DRAW_INDEXED) index += basev;
            }
            v[j] = fetch(r, port, &L, base, index, wvp, vp);
        }
        triangle(r, &pl, cull, v[0], v[1], v[2]);
    }
    (void)bitsf; (void)length; (void)ilen;
}
static void on_present(void *user, mh_port *port, unsigned frame) {
    mh_sw_renderer *r = user;
    if (!ensure(r, port)) return;
    if (r->log) fprintf(r->log, "present %u (%ux%u)\n", frame, r->width, r->height);
    if (r->png[0]) { char path[600]; snprintf(path, sizeof path, r->png, frame); mh_write_png(path, r->color, r->width, r->height); }
}

/* ------------------------------------------------------------------ lifetime */
mh_sw_renderer *mh_sw_renderer_create(mh_guest_memory *memory, FILE *log, const char *png_pattern) {
    mh_sw_renderer *r = calloc(1, sizeof *r); if (!r) return NULL;
    r->mem = memory; r->log = log; if (png_pattern) snprintf(r->png, sizeof r->png, "%s", png_pattern);
    return r;
}
void mh_sw_renderer_destroy(mh_sw_renderer *r) { if (!r) return; for (unsigned i = 0; i < r->ncache; i++) free(r->cache[i].rgba); free(r->color); free(r->depth); free(r); }
void mh_sw_renderer_bind(mh_sw_renderer *r, mh_port_renderer *out) { memset(out, 0, sizeof *out); out->user = r; out->clear = on_clear; out->draw = on_draw; out->present = on_present; }
const uint8_t *mh_sw_renderer_frame(const mh_sw_renderer *r, uint32_t *w, uint32_t *h) { *w = r->width; *h = r->height; return r->color; }

/* ------------------------------------------------------------------ PNG */
static uint32_t crc_table[256];
static uint32_t crc(uint32_t c, const uint8_t *p, size_t n) {
    if (!crc_table[1]) for (uint32_t i = 0; i < 256; i++) { uint32_t v = i; for (int k = 0; k < 8; k++) v = v & 1 ? 0xedb88320u ^ (v >> 1) : v >> 1; crc_table[i] = v; }
    c ^= 0xffffffffu; for (size_t i = 0; i < n; i++) c = crc_table[(c ^ p[i]) & 255] ^ (c >> 8); return c ^ 0xffffffffu;
}
static void be32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v; }
static void chunk(FILE *f, const char *type, const uint8_t *data, uint32_t n) {
    uint8_t h[8]; be32(h, n); memcpy(h + 4, type, 4); fwrite(h, 1, 8, f); if (n) fwrite(data, 1, n, f);
    uint32_t c = crc(0, (const uint8_t *)type, 4); c = n ? crc(c, data, n) : c; uint8_t t[4]; be32(t, c); fwrite(t, 1, 4, f);
}
int mh_write_png(const char *path, const uint8_t *rgba, uint32_t w, uint32_t h) {
    FILE *f = fopen(path, "wb"); if (!f) return 0;
    static const uint8_t sig[8] = {137, 80, 78, 71, 13, 10, 26, 10}; fwrite(sig, 1, 8, f);
    uint8_t ihdr[13]; be32(ihdr, w); be32(ihdr + 4, h); ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = ihdr[11] = ihdr[12] = 0; chunk(f, "IHDR", ihdr, 13);
    size_t raw_n = (size_t)h * (1 + 4 * (size_t)w), blocks = raw_n / 65535 + 1;
    uint8_t *raw = malloc(raw_n), *z = malloc(raw_n + 5 * blocks + 6); if (!raw || !z) { fclose(f); free(raw); free(z); return 0; }
    for (uint32_t y = 0; y < h; y++) { raw[y * (1 + 4 * (size_t)w)] = 0; memcpy(raw + y * (1 + 4 * (size_t)w) + 1, rgba + (size_t)y * w * 4, 4 * (size_t)w); }
    size_t o = 0; z[o++] = 0x78; z[o++] = 0x01;
    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < raw_n; i++) { a = (a + raw[i]) % 65521; b = (b + a) % 65521; }
    for (size_t pos = 0; pos < raw_n || pos == 0; ) {
        size_t n = raw_n - pos > 65535 ? 65535 : raw_n - pos; int last = pos + n >= raw_n;
        z[o++] = (uint8_t)last; z[o++] = (uint8_t)n; z[o++] = (uint8_t)(n >> 8); z[o++] = (uint8_t)~n; z[o++] = (uint8_t)(~n >> 8);
        memcpy(z + o, raw + pos, n); o += n; pos += n; if (last) break;
    }
    be32(z + o, (b << 16) | a); o += 4;
    chunk(f, "IDAT", z, (uint32_t)o); chunk(f, "IEND", NULL, 0);
    free(raw); free(z); return fclose(f) == 0;
}
