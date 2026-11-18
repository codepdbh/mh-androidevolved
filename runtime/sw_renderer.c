/* Reference software renderer for the port's Direct3D 8 device; see sw_renderer.h.
 * Vertex assembly, texture decoding and the pixel state come from d3d_common.c, shared with the
 * GLES backend; this file rasterises and shades. */
#include "sw_renderer.h"
#include "d3d_common.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t memory, version, format, width, height; uint8_t *rgba; } tex_entry;
struct mh_sw_renderer {
    mh_guest_memory *mem; FILE *log; char png[512];
    uint32_t width, height; uint8_t *color; float *depth;
    tex_entry cache[256]; unsigned ncache;
};

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
static const uint8_t *texture(mh_sw_renderer *r, const mh_port_texture_info *t) {
    tex_entry *e = NULL;
    for (unsigned i = 0; i < r->ncache; i++)
        if (r->cache[i].memory == t->memory[0] && r->cache[i].format == t->format && r->cache[i].width == t->level_width[0] && r->cache[i].height == t->level_height[0]) e = &r->cache[i];
    if (e && e->version == t->version[0] && e->rgba) return e->rgba;
    if (!e) {
        if (r->ncache == 256) { for (unsigned i = 0; i < 256; i++) free(r->cache[i].rgba); r->ncache = 0; }
        e = &r->cache[r->ncache++]; e->rgba = NULL;
    }
    free(e->rgba);
    e->memory = t->memory[0]; e->version = t->version[0]; e->format = t->format; e->width = t->level_width[0]; e->height = t->level_height[0];
    e->rgba = mh_d3d_decode_texture(r->mem, t);
    return e->rgba;
}

/* ------------------------------------------------------------------ pixel pipeline */
typedef struct { const mh_d3d_pixel_state *s; const uint8_t *tex; uint32_t tw, th; } pipeline;
static int compare(uint32_t func, float a, float b) {
    switch (func) { case 1: return 0; case 2: return a < b; case 3: return a == b; case 4: return a <= b; case 5: return a > b; case 6: return a != b; case 7: return a >= b; default: return 1; }
}
static void color4(uint32_t c, float o[4]) { o[0] = ((c >> 16) & 255) / 255.0f; o[1] = ((c >> 8) & 255) / 255.0f; o[2] = (c & 255) / 255.0f; o[3] = (c >> 24) / 255.0f; }
static void sample_texture(const pipeline *pl, float u, float v, float out[4]) {
    uint32_t w = pl->tw, h = pl->th;
    float fu = u * (float)w, fv = v * (float)h; long x = (long)floorf(fu), y = (long)floorf(fv);
    if (pl->s->address_u == 3) x = x < 0 ? 0 : x >= (long)w ? (long)w - 1 : x; else { x %= (long)w; if (x < 0) x += w; }
    if (pl->s->address_v == 3) y = y < 0 ? 0 : y >= (long)h ? (long)h - 1 : y; else { y %= (long)h; if (y < 0) y += h; }
    const uint8_t *p = pl->tex + 4 * ((size_t)y * w + (size_t)x);
    for (int k = 0; k < 4; k++) out[k] = p[k] / 255.0f;
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
    const mh_d3d_pixel_state *s = pl->s; size_t at = (size_t)y * r->width + (size_t)x;
    if (s->z_test && !compare(s->z_func, z, r->depth[at])) return;
    float tex[4] = {1, 1, 1, 1}, a1[4], a2[4], out[4], tf[4];
    color4(s->tfactor, tf);
    if (pl->tex) sample_texture(pl, u, v, tex);
    uint32_t colorop = s->colorop;
    if (!pl->tex && colorop != 1 && (s->colorarg1 & 15) == 2) colorop = 3;   /* no texture bound: the other argument */
    arg(s->colorarg1, diffuse, tex, tf, specular, a1); arg(s->colorarg2, diffuse, tex, tf, specular, a2);
    for (int k = 0; k < 3; k++) out[k] = combine(colorop, a1[k], a2[k], diffuse[k]);
    arg(s->alphaarg1, diffuse, tex, tf, specular, a1); arg(s->alphaarg2, diffuse, tex, tf, specular, a2);
    out[3] = combine(s->alphaop, a1[3], a2[3], diffuse[3]);
    if (s->alpha_test && !compare(s->alpha_func, out[3] * 255.0f, (float)s->alpha_ref)) return;
    uint8_t *px = r->color + 4 * at;
    if (s->blend) {
        float dst[4] = {px[0] / 255.0f, px[1] / 255.0f, px[2] / 255.0f, px[3] / 255.0f}, src[4] = {out[0], out[1], out[2], out[3]};
        for (int k = 0; k < 4; k++) out[k] = fminf(1.0f, src[k] * factor(s->src_blend, src, dst, k) + dst[k] * factor(s->dst_blend, src, dst, k));
    }
    for (int k = 0; k < 4; k++) px[k] = (uint8_t)(fmaxf(0.0f, fminf(1.0f, out[k])) * 255.0f + 0.5f);
    if (s->z_write) r->depth[at] = z;
}
static float edge(float ax, float ay, float bx, float by, float px, float py) { return (bx - ax) * (py - ay) - (by - ay) * (px - ax); }
static void triangle(mh_sw_renderer *r, const pipeline *pl, const mh_d3d_vertex *a, const mh_d3d_vertex *b, const mh_d3d_vertex *c) {
    float area = edge(a->x, a->y, b->x, b->y, c->x, c->y);
    if (area == 0) return;
    if ((pl->s->cull == 2 && area > 0) || (pl->s->cull == 3 && area < 0)) return;   /* screen y grows down: area > 0 is clockwise */
    int x0 = (int)floorf(fminf(a->x, fminf(b->x, c->x))), x1 = (int)ceilf(fmaxf(a->x, fmaxf(b->x, c->x)));
    int y0 = (int)floorf(fminf(a->y, fminf(b->y, c->y))), y1 = (int)ceilf(fmaxf(a->y, fmaxf(b->y, c->y)));
    if (x0 < 0) x0 = 0; if (y0 < 0) y0 = 0; if (x1 > (int)r->width - 1) x1 = (int)r->width - 1; if (y1 > (int)r->height - 1) y1 = (int)r->height - 1;
    for (int y = y0; y <= y1; y++) for (int x = x0; x <= x1; x++) {
        float px = (float)x, py = (float)y;   /* Direct3D samples pixel centres at integer coordinates */
        float w0 = edge(b->x, b->y, c->x, c->y, px, py) / area, w1 = edge(c->x, c->y, a->x, a->y, px, py) / area, w2 = 1 - w0 - w1;
        if (w0 < 0 || w1 < 0 || w2 < 0) continue;
        float z = w0 * a->z + w1 * b->z + w2 * c->z, q = w0 * a->rhw + w1 * b->rhw + w2 * c->rhw; if (q == 0) q = 1;
        float pa = w0 * a->rhw / q, pb = w1 * b->rhw / q, pc = w2 * c->rhw / q, d[4], s[4];
        for (int k = 0; k < 4; k++) { d[k] = pa * a->diffuse[k] + pb * b->diffuse[k] + pc * c->diffuse[k]; s[k] = pa * a->specular[k] + pb * b->specular[k] + pc * c->specular[k]; }
        shade(r, pl, x, y, z, d, s, pa * a->u + pb * b->u + pc * c->u, pa * a->v + pb * b->v + pc * c->v);
    }
}

/* ------------------------------------------------------------------ device notifications */
static void on_clear(void *user, mh_port *port, uint32_t count, uint32_t rects, uint32_t flags, uint32_t color, float z, uint32_t stencil) {
    mh_sw_renderer *r = user; (void)stencil;
    if (!ensure(r, port)) return;
    if (r->log) fprintf(r->log, "clear count=%u flags=%x color=%08x z=%g\n", count, flags, color, z);
    for (uint32_t i = 0; i < (count ? count : 1); i++) {
        int32_t x0 = 0, y0 = 0, x1 = (int32_t)r->width, y1 = (int32_t)r->height;
        if (count) {
            uint32_t q[4]; if (!mh_mem_read(r->mem, rects + 16 * i, q, 16)) continue;
            x0 = (int32_t)q[0]; y0 = (int32_t)q[1]; x1 = (int32_t)q[2]; y1 = (int32_t)q[3];
        }
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
    mh_d3d_pixel_state s; mh_d3d_pixel_state_get(port, &s);
    pipeline pl = {&s, NULL, 0, 0};
    if (s.has_texture) { pl.tex = texture(r, &s.texture); pl.tw = s.texture.level_width[0]; pl.th = s.texture.level_height[0]; }
    mh_d3d_vertex *v = NULL; size_t n = mh_d3d_assemble(r->mem, port, call, &v);
    if (r->log) fprintf(r->log, "draw kind=%d prim=%u tris=%u fvf=%03x tex=%s%ux%u fmt=%08x colorop=%u(%x,%x) alphaop=%u blend=%d(%u,%u) atest=%d z=%d/%d cull=%u\n",
                        call->kind, call->primitive, (unsigned)(n / 3), mh_port_fvf(port), s.has_texture ? "" : "none ", pl.tw, pl.th, s.has_texture ? s.texture.format : 0,
                        s.colorop, s.colorarg1, s.colorarg2, s.alphaop, s.blend, s.src_blend, s.dst_blend, s.alpha_test, s.z_test, s.z_write, s.cull);
    for (size_t i = 0; i + 2 < n; i += 3) triangle(r, &pl, &v[i], &v[i + 1], &v[i + 2]);
    free(v);
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
static uint32_t png_crc_table[256];
static uint32_t png_crc(uint32_t c, const uint8_t *p, size_t n) {
    if (!png_crc_table[1]) for (uint32_t i = 0; i < 256; i++) { uint32_t v = i; for (int k = 0; k < 8; k++) v = v & 1 ? 0xedb88320u ^ (v >> 1) : v >> 1; png_crc_table[i] = v; }
    c ^= 0xffffffffu; for (size_t i = 0; i < n; i++) c = png_crc_table[(c ^ p[i]) & 255] ^ (c >> 8); return c ^ 0xffffffffu;
}
static void be32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v; }
static void chunk(FILE *f, const char *type, const uint8_t *data, uint32_t n) {
    uint8_t h[8]; be32(h, n); memcpy(h + 4, type, 4); fwrite(h, 1, 8, f); if (n) fwrite(data, 1, n, f);
    uint32_t c = png_crc(0, (const uint8_t *)type, 4); c = n ? png_crc(c, data, n) : c; uint8_t t[4]; be32(t, c); fwrite(t, 1, 4, f);
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
    for (size_t pos = 0; ; ) {
        size_t n = raw_n - pos > 65535 ? 65535 : raw_n - pos; int last = pos + n >= raw_n;
        z[o++] = (uint8_t)last; z[o++] = (uint8_t)n; z[o++] = (uint8_t)(n >> 8); z[o++] = (uint8_t)~n; z[o++] = (uint8_t)(~n >> 8);
        memcpy(z + o, raw + pos, n); o += n; pos += n; if (last) break;
    }
    be32(z + o, (b << 16) | a); o += 4;
    chunk(f, "IDAT", z, (uint32_t)o); chunk(f, "IEND", NULL, 0);
    free(raw); free(z); return fclose(f) == 0;
}
