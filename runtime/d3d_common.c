/* Shared Direct3D 8 renderer logic; see d3d_common.h. */
#include "d3d_common.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static float d3d_rf(const uint8_t *p) { float f; memcpy(&f, p, 4); return f; }
static uint32_t d3d_ru(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static float d3d_asf(uint32_t b) { float f; memcpy(&f, &b, 4); return f; }

/* ------------------------------------------------------------------ textures */
static void d3d_px(uint8_t *o, uint32_t r8, uint32_t g8, uint32_t b8, uint32_t a8) { o[0] = (uint8_t)r8; o[1] = (uint8_t)g8; o[2] = (uint8_t)b8; o[3] = (uint8_t)a8; }
static void d3d_565(uint16_t c, uint32_t *r8, uint32_t *g8, uint32_t *b8) {
    uint32_t r5 = c >> 11, g6 = (c >> 5) & 63, b5 = c & 31;
    *r8 = (r5 << 3) | (r5 >> 2); *g8 = (g6 << 2) | (g6 >> 4); *b8 = (b5 << 3) | (b5 >> 2);
}
static void d3d_dxt_block(const uint8_t *b, int format, uint8_t out[16][4]) {
    const uint8_t *cb = format == 1 ? b : b + 8;
    uint16_t c0 = (uint16_t)(cb[0] | cb[1] << 8), c1 = (uint16_t)(cb[2] | cb[3] << 8);
    uint32_t pal[4][4], r0, g0, b0, r1, g1, b1;
    d3d_565(c0, &r0, &g0, &b0); d3d_565(c1, &r1, &g1, &b1);
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
    for (int i = 0; i < 16; i++) { uint32_t *c = pal[(idx >> (2 * i)) & 3]; d3d_px(out[i], c[0], c[1], c[2], c[3]); }
    if (format == 2 || format == 3) {
        for (int i = 0; i < 16; i++) { uint32_t a = (b[i / 2] >> ((i & 1) * 4)) & 15; out[i][3] = (uint8_t)(a * 17); }
    } else if (format == 4 || format == 5) {
        uint32_t a[8]; a[0] = b[0]; a[1] = b[1];
        if (a[0] > a[1]) for (int k = 1; k < 7; k++) a[k + 1] = ((7 - k) * a[0] + k * a[1]) / 7;
        else { for (int k = 1; k < 5; k++) a[k + 1] = ((5 - k) * a[0] + k * a[1]) / 5; a[6] = 0; a[7] = 255; }
        uint64_t bits = 0; for (int k = 0; k < 6; k++) bits |= (uint64_t)b[2 + k] << (8 * k);
        for (int i = 0; i < 16; i++) out[i][3] = (uint8_t)a[(bits >> (3 * i)) & 7];
    }
}
uint8_t *mh_d3d_decode_texture(mh_guest_memory *memory, const mh_port_texture_info *t) {
    uint32_t w = t->level_width[0], h = t->level_height[0], mem = t->memory[0], pitch = t->pitch[0], f = t->format;
    uint8_t *out = calloc((size_t)w * h, 4);
    if (!out) return NULL;
    if (f >= 0x31545844u && f <= 0x35545844u) {
        int fmt = (int)((f >> 24) - '0'); uint32_t bw = (w + 3) / 4, bh = (h + 3) / 4, bs = fmt == 1 ? 8 : 16;
        for (uint32_t by = 0; by < bh; by++) for (uint32_t bx = 0; bx < bw; bx++) {
            const uint8_t *b = mh_mem_span(memory, mem + by * pitch + bx * bs, bs); uint8_t px[16][4];
            if (!b) continue;
            d3d_dxt_block(b, fmt, px);
            for (int i = 0; i < 16; i++) { uint32_t x = bx * 4 + (uint32_t)(i & 3), y = by * 4 + (uint32_t)(i >> 2); if (x < w && y < h) memcpy(out + 4 * ((size_t)y * w + x), px[i], 4); }
        }
        return out;
    }
    for (uint32_t y = 0; y < h; y++) {
        const uint8_t *row = mh_mem_span(memory, mem + y * pitch, pitch); if (!row) continue;
        for (uint32_t x = 0; x < w; x++) {
            uint8_t *o = out + 4 * ((size_t)y * w + x); uint32_t r8, g8, b8;
            switch (f) {
            case 21: d3d_px(o, row[4 * x + 2], row[4 * x + 1], row[4 * x], row[4 * x + 3]); break;
            case 22: d3d_px(o, row[4 * x + 2], row[4 * x + 1], row[4 * x], 255); break;
            case 23: d3d_565((uint16_t)(row[2 * x] | row[2 * x + 1] << 8), &r8, &g8, &b8); d3d_px(o, r8, g8, b8, 255); break;
            case 24: case 25: { uint16_t c = (uint16_t)(row[2 * x] | row[2 * x + 1] << 8); uint32_t r5 = (c >> 10) & 31, g5 = (c >> 5) & 31, b5 = c & 31;
                d3d_px(o, (r5 << 3) | (r5 >> 2), (g5 << 3) | (g5 >> 2), (b5 << 3) | (b5 >> 2), f == 25 ? ((c >> 15) ? 255 : 0) : 255); break; }
            case 26: { uint16_t c = (uint16_t)(row[2 * x] | row[2 * x + 1] << 8); d3d_px(o, ((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, (c >> 12) * 17); break; }
            case 28: d3d_px(o, 255, 255, 255, row[x]); break;
            case 50: d3d_px(o, row[x], row[x], row[x], 255); break;
            case 51: d3d_px(o, row[2 * x], row[2 * x], row[2 * x], row[2 * x + 1]); break;
            default: d3d_px(o, 255, 0, 255, 255); break;
            }
        }
    }
    return out;
}

/* ------------------------------------------------------------------ vertices */
typedef struct { uint32_t stride, off_normal, off_diffuse, off_specular, off_tex0; int transformed, has_normal, has_diffuse, has_specular, ntex; } d3d_layout;
/* Fixed-function lighting (D3DRS_LIGHTING), evaluated in world space per vertex. */
typedef struct { int on; unsigned n; float light[8][26]; float mat[17]; float ambient[4]; uint32_t diffuse_src, ambient_src, emissive_src; int color_vertex; float world[16]; } d3d_lighting;
static d3d_layout d3d_fvf_layout(uint32_t fvf, uint32_t stride) {
    d3d_layout L; memset(&L, 0, sizeof L); L.stride = stride;
    uint32_t pos = fvf & 0x00e, off;
    L.transformed = pos == 0x004;
    off = pos == 0x002 ? 12 : pos == 0x004 ? 16 : pos >= 0x006 ? 12 + 4 * ((pos - 0x004) / 2) : 0;
    if (fvf & 0x010) { L.has_normal = 1; L.off_normal = off; off += 12; }
    if (fvf & 0x020) off += 4;
    if (fvf & 0x040) { L.has_diffuse = 1; L.off_diffuse = off; off += 4; }
    if (fvf & 0x080) { L.has_specular = 1; L.off_specular = off; off += 4; }
    L.ntex = (int)((fvf >> 8) & 15); L.off_tex0 = off;
    return L;
}
static void d3d_color4(uint32_t c, float o[4]) { o[0] = ((c >> 16) & 255) / 255.0f; o[1] = ((c >> 8) & 255) / 255.0f; o[2] = (c & 255) / 255.0f; o[3] = (c >> 24) / 255.0f; }
static void d3d_mul(const float *v, const float *m, float *o) { for (int j = 0; j < 4; j++) o[j] = v[0] * m[j] + v[1] * m[4 + j] + v[2] * m[8 + j] + v[3] * m[12 + j]; }
static void d3d_light_vertex(const d3d_lighting *lt, const float *pos, const float *normal, const float vcol[4], const float vspec[4], int has_vcol, float out[4]) {
    /* material colours, or the vertex's colour (D3DMCS_COLOR1 = 1) with D3DRS_COLORVERTEX */
    const float *md = lt->mat, *ma = lt->mat + 4, *me = lt->mat + 12;
    float cd[4], ca[4], ce[4];
    for (int i = 0; i < 4; i++) {
        cd[i] = lt->color_vertex && has_vcol && lt->diffuse_src == 1 ? vcol[i] : lt->color_vertex && lt->diffuse_src == 2 ? vspec[i] : md[i];
        ca[i] = lt->color_vertex && has_vcol && lt->ambient_src == 1 ? vcol[i] : lt->color_vertex && lt->ambient_src == 2 ? vspec[i] : ma[i];
        ce[i] = lt->color_vertex && has_vcol && lt->emissive_src == 1 ? vcol[i] : lt->color_vertex && lt->emissive_src == 2 ? vspec[i] : me[i];
    }
    float p[4] = {pos[0], pos[1], pos[2], 1}, wp[4], n[4] = {normal[0], normal[1], normal[2], 0}, wn[4];
    d3d_mul(p, lt->world, wp); d3d_mul(n, lt->world, wn);
    float nl = sqrtf(wn[0] * wn[0] + wn[1] * wn[1] + wn[2] * wn[2]); if (nl > 0) { wn[0] /= nl; wn[1] /= nl; wn[2] /= nl; }
    float r = ce[0] + lt->ambient[0] * ca[0], g = ce[1] + lt->ambient[1] * ca[1], b = ce[2] + lt->ambient[2] * ca[2];
    for (unsigned i = 0; i < lt->n; i++) {
        const float *l = lt->light[i]; int type = (int)d3d_ru((const uint8_t *)&l[0]);
        float dir[3], att = 1;
        if (type == 3) { dir[0] = -l[16]; dir[1] = -l[17]; dir[2] = -l[18]; }   /* directional: towards the light */
        else {
            dir[0] = l[13] - wp[0]; dir[1] = l[14] - wp[1]; dir[2] = l[15] - wp[2];
            float d = sqrtf(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
            if (l[19] > 0 && d > l[19]) continue;   /* out of range */
            float den = l[21] + l[22] * d + l[23] * d * d; att = den > 0 ? 1 / den : 1;
            if (d > 0) { dir[0] /= d; dir[1] /= d; dir[2] /= d; }
        }
        float dl = sqrtf(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]); if (dl > 0) { dir[0] /= dl; dir[1] /= dl; dir[2] /= dl; }
        float k = wn[0] * dir[0] + wn[1] * dir[1] + wn[2] * dir[2]; if (k < 0) k = 0;
        r += att * (l[9] * ca[0] + l[1] * cd[0] * k); g += att * (l[10] * ca[1] + l[2] * cd[1] * k); b += att * (l[11] * ca[2] + l[3] * cd[2] * k);
    }
    out[0] = r > 1 ? 1 : r; out[1] = g > 1 ? 1 : g; out[2] = b > 1 ? 1 : b; out[3] = cd[3] > 1 ? 1 : cd[3] < 0 ? 0 : cd[3];
}
static const d3d_lighting *d3d_current_lighting;
static int d3d_fetch(mh_guest_memory *mem, const d3d_layout *L, uint32_t base, uint32_t index, const float *wvp, const uint32_t *vp, mh_d3d_vertex *o) {
    memset(o, 0, sizeof *o);
    const uint8_t *p = mh_mem_span(mem, base + index * L->stride, L->stride ? L->stride : 16);
    if (!p) return 0;
    if (L->transformed) { o->x = d3d_rf(p); o->y = d3d_rf(p + 4); o->z = d3d_rf(p + 8); o->rhw = d3d_rf(p + 12); }
    else {
        float v[4] = {d3d_rf(p), d3d_rf(p + 4), d3d_rf(p + 8), 1.0f}, c[4]; d3d_mul(v, wvp, c);
        if (c[3] <= 1e-6f) return 0;
        float vw = (float)vp[2], vh = (float)vp[3], minz = d3d_asf(vp[4]), maxz = d3d_asf(vp[5]);   /* X, Y, Width, Height are integers */
        o->x = (float)vp[0] + (1.0f + c[0] / c[3]) * vw * 0.5f; o->y = (float)vp[1] + (1.0f - c[1] / c[3]) * vh * 0.5f;
        o->z = minz + c[2] / c[3] * (maxz - minz); o->rhw = 1.0f / c[3];
    }
    if (L->has_diffuse) d3d_color4(d3d_ru(p + L->off_diffuse), o->diffuse); else o->diffuse[0] = o->diffuse[1] = o->diffuse[2] = o->diffuse[3] = 1.0f;
    if (L->has_specular) d3d_color4(d3d_ru(p + L->off_specular), o->specular);
    if (L->ntex) { o->u = d3d_rf(p + L->off_tex0); o->v = d3d_rf(p + L->off_tex0 + 4); }
    const d3d_lighting *lt = d3d_current_lighting;
    if (lt && lt->on && !L->transformed) {
        float pos[3] = {d3d_rf(p), d3d_rf(p + 4), d3d_rf(p + 8)}, nrm[3] = {0, 0, 0}, vcol[4];
        if (L->has_normal) { nrm[0] = d3d_rf(p + L->off_normal); nrm[1] = d3d_rf(p + L->off_normal + 4); nrm[2] = d3d_rf(p + L->off_normal + 8); }
        memcpy(vcol, o->diffuse, sizeof vcol);
        d3d_light_vertex(lt, pos, nrm, vcol, o->specular, L->has_diffuse, o->diffuse);
    }
    return 1;
}
size_t mh_d3d_assemble(mh_guest_memory *mem, mh_port *port, const mh_port_draw_call *call, mh_d3d_vertex **out) {
    uint32_t base = 0, stride = 0, length = 0, imem = 0, ilen = 0, ifmt = 101, basev = 0, count, first = 0;
    int indexed = call->kind == MH_DRAW_INDEXED || call->kind == MH_DRAW_INDEXED_UP;
    switch (call->kind) {
    case MH_DRAW_PRIMITIVE: first = call->args[0]; count = call->args[1]; mh_port_stream(port, 0, &base, &length, &stride); break;
    case MH_DRAW_INDEXED: count = call->args[3]; first = call->args[2]; mh_port_stream(port, 0, &base, &length, &stride); mh_port_indices(port, &imem, &ilen, &ifmt, &basev); break;
    case MH_DRAW_PRIMITIVE_UP: count = call->args[0]; base = call->args[1]; stride = call->args[2]; break;
    default: count = call->args[2]; imem = call->args[3]; ifmt = call->args[4]; base = call->args[5]; stride = call->args[6]; break;
    }
    *out = NULL;
    if (call->primitive < 4 || call->primitive > 6 || !count) return 0;   /* points and lines: not drawn yet */
    d3d_layout L = d3d_fvf_layout(mh_port_fvf(port), stride);
    float world[16], view[16], proj[16], wv[16], wvp[16]; uint32_t vp[6];
    mh_port_transform(port, 256, world); mh_port_transform(port, 2, view); mh_port_transform(port, 3, proj); mh_port_viewport(port, vp);
    for (int i = 0; i < 4; i++) d3d_mul(world + 4 * i, view, wv + 4 * i);
    for (int i = 0; i < 4; i++) d3d_mul(wv + 4 * i, proj, wvp + 4 * i);
    d3d_lighting lt; memset(&lt, 0, sizeof lt);
    lt.on = mh_port_render_state(port, 137) != 0 && !L.transformed;   /* D3DRS_LIGHTING */
    if (lt.on) {
        uint32_t raw[8][26], m[17]; lt.n = mh_port_lights(port, raw, 8); mh_port_material(port, m);
        memcpy(lt.light, raw, sizeof raw); memcpy(lt.mat, m, sizeof m); memcpy(lt.world, world, sizeof world);
        d3d_color4(mh_port_render_state(port, 139), lt.ambient);   /* D3DRS_AMBIENT */
        lt.color_vertex = mh_port_render_state(port, 141) != 0;
        lt.diffuse_src = mh_port_render_state(port, 145); lt.ambient_src = mh_port_render_state(port, 147); lt.emissive_src = mh_port_render_state(port, 148);
    }
    d3d_current_lighting = &lt;
    mh_d3d_vertex *v = malloc(sizeof *v * 3 * (size_t)count);
    if (!v) return 0;
    size_t n = 0;
    for (uint32_t t = 0; t < count; t++) {
        uint32_t k[3];
        if (call->primitive == 4) { k[0] = 3 * t; k[1] = 3 * t + 1; k[2] = 3 * t + 2; }
        else if (call->primitive == 5) { k[0] = t; k[1] = t + 1; k[2] = t + 2; if (t & 1) { uint32_t s = k[0]; k[0] = k[1]; k[1] = s; } }
        else { k[0] = 0; k[1] = t + 1; k[2] = t + 2; }
        int ok = 1;
        for (int j = 0; j < 3; j++) {
            uint32_t index = first + k[j];
            if (indexed) {
                uint32_t isz = ifmt == 102 ? 4 : 2; const uint8_t *ip = mh_mem_span(mem, imem + index * isz, isz);
                index = ip ? (isz == 4 ? d3d_ru(ip) : (uint32_t)(ip[0] | ip[1] << 8)) : 0;
                if (call->kind == MH_DRAW_INDEXED) index += basev;
            }
            ok &= d3d_fetch(mem, &L, base, index, wvp, vp, &v[n + (size_t)j]);
        }
        if (ok) n += 3;
    }
    (void)length; (void)ilen; d3d_current_lighting = NULL;
    *out = v; return n;
}

/* ------------------------------------------------------------------ pixel state */
void mh_d3d_pixel_state_get(mh_port *port, mh_d3d_pixel_state *s) {
    memset(s, 0, sizeof *s);
    s->has_texture = mh_port_texture(port, 0, &s->texture);
    s->address_u = mh_port_stage_state(port, 0, 13); s->address_v = mh_port_stage_state(port, 0, 14);
    s->mag_filter = mh_port_stage_state(port, 0, 16); s->min_filter = mh_port_stage_state(port, 0, 17);
    s->colorop = mh_port_stage_state(port, 0, 1); s->colorarg1 = mh_port_stage_state(port, 0, 2); s->colorarg2 = mh_port_stage_state(port, 0, 3);
    s->alphaop = mh_port_stage_state(port, 0, 4); s->alphaarg1 = mh_port_stage_state(port, 0, 5); s->alphaarg2 = mh_port_stage_state(port, 0, 6);
    s->tfactor = mh_port_render_state(port, 60);
    s->alpha_test = mh_port_render_state(port, 15) != 0; s->alpha_ref = mh_port_render_state(port, 24); s->alpha_func = mh_port_render_state(port, 25);
    s->blend = mh_port_render_state(port, 27) != 0; s->src_blend = mh_port_render_state(port, 19); s->dst_blend = mh_port_render_state(port, 20); s->blend_op = mh_port_render_state(port, 171);
    s->z_test = mh_port_render_state(port, 7) != 0; s->z_write = mh_port_render_state(port, 14) != 0; s->z_func = mh_port_render_state(port, 23);
    s->cull = mh_port_render_state(port, 22); s->color_write = mh_port_render_state(port, 168);
}
