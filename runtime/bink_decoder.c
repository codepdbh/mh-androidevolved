/* Bink 1 video decoder; see bink_decoder.h.
 *
 * Derived from FFmpeg's libavcodec/bink.c and binkdsp.c (Copyright (c) 2009 Konstantin Shishkov,
 * Copyright (C) 2011 Peter Ross) and libavformat/bink.c, rewritten as a small standalone decoder
 * for the Bink files of this game (revision 'i', YUV 4:2:0).
 *
 * This file is free software; you can redistribute it and/or modify it under the terms of the GNU
 * Lesser General Public License as published by the Free Software Foundation; either version 2.1
 * of the License, or (at your option) any later version. It is distributed in the hope that it
 * will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more details. */
#include "bink_decoder.h"
#include "bink_tables.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ------------------------------------------------------------------ bit reader (little-endian) */
typedef struct { const uint8_t *buf; size_t bits, pos; } bits_t;   /* buf has 8 zero bytes of padding */
static uint32_t peek(const bits_t *g, int n) {
    size_t byte = g->pos >> 3; uint64_t w = 0;
    for (int i = 0; i < 8; i++) w |= (uint64_t)g->buf[byte + (size_t)i] << (8 * i);
    w >>= g->pos & 7;
    return n >= 32 ? (uint32_t)w : (uint32_t)(w & ((1ull << n) - 1));
}
static uint32_t get(bits_t *g, int n) {
    if (!n) return 0;
    uint32_t v = peek(g, n); g->pos += (size_t)n; if (g->pos > g->bits + 64) g->pos = g->bits + 64; return v;
}
static int get1(bits_t *g) { return (int)get(g, 1); }
static long left(const bits_t *g) { return (long)g->bits - (long)g->pos; }

/* ------------------------------------------------------------------ audio (Bink audio, DCT variant) */
/* Inverse transform: y[n] = sum_k a_k X[k] cos(pi k (2n+1) / (2N)), a_0 = 1/2, through a 2N-point
 * complex FFT: y[n] = Re(sum_k a_k X[k] e^{i pi k / (2N)} e^{2 pi i k n / (2N)}). */
typedef struct { float re, im; } cpx;
static void fft(cpx *a, int n, const cpx *tw) {   /* in place, forward sign +i (an inverse DFT without 1/n) */
    for (int i = 1, j = 0; i < n; i++) {
        int bit = n >> 1; for (; j & bit; bit >>= 1) j ^= bit; j ^= bit;
        if (i < j) { cpx t = a[i]; a[i] = a[j]; a[j] = t; }
    }
    for (int len = 2; len <= n; len <<= 1) {
        int step = n / len;
        for (int i = 0; i < n; i += len)
            for (int k = 0; k < len / 2; k++) {
                cpx w = tw[k * step], u = a[i + k], v = a[i + k + len / 2];
                cpx t = {v.re * w.re - v.im * w.im, v.re * w.im + v.im * w.re};
                a[i + k].re = u.re + t.re; a[i + k].im = u.im + t.im;
                a[i + k + len / 2].re = u.re - t.re; a[i + k + len / 2].im = u.im - t.im;
            }
    }
}
typedef struct {
    int channels, frame_len, overlap_len, num_bands, first;
    unsigned bands[26]; float quant_table[96], root;
    float previous[2][256];
    cpx *work, *tw, *pre;            /* 2N work buffer, 2N twiddles, N pre-rotations */
} bink_audio;
static const uint16_t wma_critical_freqs[25] = {100, 200, 300, 400, 510, 630, 770, 920, 1080, 1270, 1480, 1720, 2000, 2320, 2700, 3150, 3700, 4400, 5300, 6400, 7700, 9500, 12000, 15500, 24500};
static int audio_init(bink_audio *s, unsigned rate, int channels) {
    if (channels < 1 || channels > 2) return 0;
    int bits = rate < 22050 ? 9 : rate < 44100 ? 10 : 11;
    s->channels = channels; s->frame_len = 1 << bits; s->overlap_len = s->frame_len / 16;
    unsigned half = (rate + 1) / 2;
    s->root = (float)(s->frame_len / (sqrt((double)s->frame_len) * 32768.0));
    for (int i = 0; i < 96; i++) s->quant_table[i] = expf((float)i * 0.15289164787221953823f) * s->root;
    for (s->num_bands = 1; s->num_bands < 25; s->num_bands++) if (half <= wma_critical_freqs[s->num_bands - 1]) break;
    s->bands[0] = 2;
    for (int i = 1; i < s->num_bands; i++) s->bands[i] = (unsigned)((wma_critical_freqs[i - 1] * s->frame_len / half) & ~1u);
    s->bands[s->num_bands] = (unsigned)s->frame_len;
    s->first = 1;
    int n2 = 2 * s->frame_len;
    s->work = malloc(sizeof(cpx) * (size_t)n2); s->tw = malloc(sizeof(cpx) * (size_t)n2); s->pre = malloc(sizeof(cpx) * (size_t)s->frame_len);
    if (!s->work || !s->tw || !s->pre) return 0;
    for (int k = 0; k < n2; k++) { double a = 2.0 * M_PI * k / n2; s->tw[k].re = (float)cos(a); s->tw[k].im = (float)sin(a); }
    for (int k = 0; k < s->frame_len; k++) { double a = M_PI * k / n2; s->pre[k].re = (float)cos(a); s->pre[k].im = (float)sin(a); }
    return 1;
}
static void audio_free(bink_audio *s) { free(s->work); free(s->tw); free(s->pre); }
static void dct3(bink_audio *s, const float *x, float *y) {
    int n = s->frame_len, n2 = 2 * n;
    for (int k = 0; k < n; k++) { float v = k ? x[k] : 0.5f * x[0]; s->work[k].re = v * s->pre[k].re; s->work[k].im = v * s->pre[k].im; }
    for (int k = n; k < n2; k++) s->work[k].re = s->work[k].im = 0;
    fft(s->work, n2, s->tw);
    for (int i = 0; i < n; i++) y[i] = s->work[i].re;
}
static float get_float(bits_t *g) {
    int power = (int)get(g, 5); float f = ldexpf((float)get(g, 23), power - 23);
    return get1(g) ? -f : f;
}
static const uint8_t rle_length_tab[16] = {2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 32, 64};
/* One block: frame_len - overlap_len samples per channel into out[ch]. Returns 0 on bad data. */
static int audio_block(bink_audio *s, bits_t *g, float out[2][2048]) {
    float coeffs[2048 + 2], quant[25];
    get(g, 2);   /* the DCT variant */
    for (int ch = 0; ch < s->channels; ch++) {
        if (left(g) < 58) return 0;
        coeffs[0] = get_float(g) * s->root; coeffs[1] = get_float(g) * s->root;
        if (left(g) < s->num_bands * 8) return 0;
        for (int i = 0; i < s->num_bands; i++) { int v = (int)get(g, 8); quant[i] = s->quant_table[v > 95 ? 95 : v]; }
        int k = 0, i = 2; float q = quant[0];
        while (i < s->frame_len) {
            int j;
            if (get1(g)) j = i + rle_length_tab[get(g, 4)] * 8; else j = i + 8;
            if (j > s->frame_len) j = s->frame_len;
            int width = (int)get(g, 4);
            if (!width) { memset(coeffs + i, 0, sizeof(float) * (size_t)(j - i)); i = j; while (s->bands[k] < (unsigned)i) q = quant[k++]; }
            else while (i < j) {
                if (s->bands[k] == (unsigned)i) q = quant[k++];
                int coeff = (int)get(g, width);
                coeffs[i] = coeff ? (get1(g) ? -q * (float)coeff : q * (float)coeff) : 0.0f;
                i++;
            }
            if (left(g) < 0) return 0;
        }
        coeffs[0] /= 0.5f;
        dct3(s, coeffs, out[ch]);
        for (int n = 0; n < s->frame_len; n++) out[ch][n] *= 1.0f / 1024;   /* to [-1, 1] (measured: peaks ~0.6 on the game's movies) */
    }
    for (int ch = 0; ch < s->channels; ch++) {
        int count = s->overlap_len * s->channels;
        if (!s->first) for (int i = 0, j = ch; i < s->overlap_len; i++, j += s->channels)
            out[ch][i] = (s->previous[ch][i] * (float)(count - j) + out[ch][i] * (float)j) / (float)count;
        memcpy(s->previous[ch], &out[ch][s->frame_len - s->overlap_len], sizeof(float) * (size_t)s->overlap_len);
    }
    s->first = 0;
    return 1;
}


/* ------------------------------------------------------------------ Huffman trees */
typedef struct { uint8_t sym, len; } vlc_entry;
static vlc_entry vlc_table[16][1 << 7]; static int vlc_bits[16]; static int vlc_ready;
static void init_vlcs(void) {
    if (vlc_ready) return;
    for (int t = 0; t < 16; t++) {
        int maxbits = bink_tree_lens[t][15]; vlc_bits[t] = maxbits;
        for (int s = 0; s < 16; s++) {
            int len = bink_tree_lens[t][s];
            for (int fill = 0; fill < (1 << (maxbits - len)); fill++) {
                vlc_entry *e = &vlc_table[t][bink_tree_bits[t][s] | fill << len]; e->sym = (uint8_t)s; e->len = (uint8_t)len;
            }
        }
    }
    vlc_ready = 1;
}
typedef struct { int vlc_num; uint8_t syms[16]; } tree_t;
static int get_huff(bits_t *g, const tree_t *t) {
    const vlc_entry *e = &vlc_table[t->vlc_num][peek(g, vlc_bits[t->vlc_num])];
    g->pos += e->len; return t->syms[e->sym];
}
static void merge(bits_t *g, uint8_t *dst, const uint8_t *src, int size) {
    const uint8_t *src2 = src + size; int size2 = size;
    do { if (!get1(g)) { *dst++ = *src++; size--; } else { *dst++ = *src2++; size2--; } } while (size && size2);
    while (size--) *dst++ = *src++;
    while (size2--) *dst++ = *src2++;
}
static int read_tree(bits_t *g, tree_t *tree) {
    uint8_t tmp1[16] = {0}, tmp2[16], *in = tmp1, *out = tmp2;
    if (left(g) < 4) return -1;
    tree->vlc_num = (int)get(g, 4);
    if (!tree->vlc_num) { for (int i = 0; i < 16; i++) tree->syms[i] = (uint8_t)i; return 0; }
    if (get1(g)) {
        int len = (int)get(g, 3);
        for (int i = 0; i <= len; i++) { tree->syms[i] = (uint8_t)get(g, 4); tmp1[tree->syms[i]] = 1; }
        for (int i = 0; i < 16 && len < 16 - 1; i++) if (!tmp1[i]) tree->syms[++len] = (uint8_t)i;
    } else {
        int len = (int)get(g, 2);
        for (int i = 0; i < 16; i++) in[i] = (uint8_t)i;
        for (int i = 0; i <= len; i++) {
            int size = 1 << i;
            for (int t = 0; t < 16; t += size << 1) merge(g, out + t, in + t, size);
            uint8_t *s = in; in = out; out = s;
        }
        memcpy(tree->syms, in, 16);
    }
    return 0;
}

/* ------------------------------------------------------------------ bundles */
enum { SRC_BLOCK_TYPES, SRC_SUB_BLOCK_TYPES, SRC_COLORS, SRC_PATTERN, SRC_X_OFF, SRC_Y_OFF, SRC_INTRA_DC, SRC_INTER_DC, SRC_RUN, NB_SRC };
enum { SKIP_BLOCK, SCALED_BLOCK, MOTION_BLOCK, RUN_BLOCK, RESIDUE_BLOCK, INTRA_BLOCK, FILL_BLOCK, INTER_BLOCK, PATTERN_BLOCK, RAW_BLOCK };
typedef struct { int len; tree_t tree; uint8_t *data, *data_end, *cur_dec, *cur_ptr; } bundle_t;

typedef struct { uint8_t *p[4]; int stride[4], rows[4]; } frame_t;
struct mh_bink {
    FILE *f; uint32_t width, height, frames, flags, version, ntracks, file_size;
    uint32_t *index;                      /* frames + 1 offsets (bit 0 cleared) */
    uint8_t *packet; size_t packet_cap;
    bundle_t bundle[NB_SRC]; uint8_t *bundle_mem;
    tree_t col_high[16]; int col_lastval;
    frame_t fr[2]; int cur, have_last; int64_t decoded;   /* index of the frame in fr[cur], -1 none */
    /* audio track 0 (DCT variant only): its decoder, and the PCM of the last decoded frame (interleaved, 16-bit) */
    int has_audio; unsigned arate, achannels; bink_audio audio; int16_t *pcm; size_t pcm_frames, pcm_cap;
};

static int ilog2(unsigned v) { int r = 0; while (v >>= 1) r++; return r; }
static void init_lengths(mh_bink *c, int width, int bw) {
    width = (width + 7) & ~7;
    c->bundle[SRC_BLOCK_TYPES].len = ilog2((unsigned)(width >> 3) + 511) + 1;
    c->bundle[SRC_SUB_BLOCK_TYPES].len = ilog2((unsigned)(width >> 4) + 511) + 1;
    c->bundle[SRC_COLORS].len = ilog2((unsigned)bw * 64 + 511) + 1;
    c->bundle[SRC_INTRA_DC].len = c->bundle[SRC_INTER_DC].len = c->bundle[SRC_X_OFF].len = c->bundle[SRC_Y_OFF].len = ilog2((unsigned)(width >> 3) + 511) + 1;
    c->bundle[SRC_PATTERN].len = ilog2((unsigned)(bw << 3) + 511) + 1;
    c->bundle[SRC_RUN].len = ilog2((unsigned)bw * 48 + 511) + 1;
}
static int read_bundle(bits_t *g, mh_bink *c, int n) {
    if (n == SRC_COLORS) { for (int i = 0; i < 16; i++) if (read_tree(g, &c->col_high[i]) < 0) return -1; c->col_lastval = 0; }
    if (n != SRC_INTRA_DC && n != SRC_INTER_DC && read_tree(g, &c->bundle[n].tree) < 0) return -1;
    c->bundle[n].cur_dec = c->bundle[n].cur_ptr = c->bundle[n].data;
    return 0;
}
/* the number of values to decode next, or 0 when the bundle needs nothing now (or is done) */
static int check_read(bits_t *g, bundle_t *b) {
    if (!b->cur_dec || b->cur_dec > b->cur_ptr) return 0;
    int t = (int)get(g, b->len);
    if (!t) { b->cur_dec = NULL; return 0; }
    return t;
}
static int read_runs(bits_t *g, bundle_t *b) {
    int t = check_read(g, b); if (!t) return 0;
    if (b->cur_dec + t > b->data_end || left(g) < 1) return -1;
    if (get1(g)) { int v = (int)get(g, 4); memset(b->cur_dec, v, (size_t)t); b->cur_dec += t; }
    else { const uint8_t *end = b->cur_dec + t; while (b->cur_dec < end) *b->cur_dec++ = (uint8_t)get_huff(g, &b->tree); }
    return 0;
}
static int read_motion_values(bits_t *g, bundle_t *b) {
    int t = check_read(g, b); if (!t) return 0;
    if (b->cur_dec + t > b->data_end || left(g) < 1) return -1;
    if (get1(g)) {
        int v = (int)get(g, 4); if (v) { int sign = -get1(g); v = (v ^ sign) - sign; }
        memset(b->cur_dec, v, (size_t)t); b->cur_dec += t;
    } else {
        const uint8_t *end = b->cur_dec + t;
        while (b->cur_dec < end) { int v = get_huff(g, &b->tree); if (v) { int sign = -get1(g); v = (v ^ sign) - sign; } *b->cur_dec++ = (uint8_t)v; }
    }
    return 0;
}
static const uint8_t rlelens[4] = {4, 8, 12, 32};
static int read_block_types(bits_t *g, bundle_t *b, uint32_t version) {
    int t = check_read(g, b); if (!t) return 0;
    if (version == 'k') { t ^= 0xBB; if (!t) { b->cur_dec = NULL; return 0; } }
    const uint8_t *end = b->cur_dec + t;
    if (end > b->data_end || left(g) < 1) return -1;
    if (get1(g)) { int v = (int)get(g, 4); memset(b->cur_dec, v, (size_t)t); b->cur_dec += t; return 0; }
    int last = 0;
    while (b->cur_dec < end) {
        int v = get_huff(g, &b->tree);
        if (v < 12) { last = v; *b->cur_dec++ = (uint8_t)v; }
        else { int run = rlelens[v - 12]; if (end - b->cur_dec < run) return -1; memset(b->cur_dec, last, (size_t)run); b->cur_dec += run; }
    }
    return 0;
}
static int read_patterns(bits_t *g, bundle_t *b) {
    int t = check_read(g, b); if (!t) return 0;
    const uint8_t *end = b->cur_dec + t; if (end > b->data_end) return -1;
    while (b->cur_dec < end) { if (left(g) < 2) return -1; int v = get_huff(g, &b->tree); v |= get_huff(g, &b->tree) << 4; *b->cur_dec++ = (uint8_t)v; }
    return 0;
}
static int read_colors(bits_t *g, bundle_t *b, mh_bink *c) {
    int t = check_read(g, b); if (!t) return 0;
    const uint8_t *end = b->cur_dec + t; if (end > b->data_end || left(g) < 1) return -1;
    if (get1(g)) {
        c->col_lastval = get_huff(g, &c->col_high[c->col_lastval]);
        int v = c->col_lastval << 4 | get_huff(g, &b->tree);
        if (c->version < 'i') { int sign = ((int8_t)v) >> 7; v = ((v & 0x7F) ^ sign) - sign; v += 0x80; }
        memset(b->cur_dec, v, (size_t)t); b->cur_dec += t;
    } else {
        while (b->cur_dec < end) {
            if (left(g) < 2) return -1;
            c->col_lastval = get_huff(g, &c->col_high[c->col_lastval]);
            int v = c->col_lastval << 4 | get_huff(g, &b->tree);
            if (c->version < 'i') { int sign = ((int8_t)v) >> 7; v = ((v & 0x7F) ^ sign) - sign; v += 0x80; }
            *b->cur_dec++ = (uint8_t)v;
        }
    }
    return 0;
}
static int read_dcs(bits_t *g, bundle_t *b, int start_bits, int has_sign) {
    int16_t *dst = (int16_t *)b->cur_dec, *dst_end = (int16_t *)b->data_end;
    int len = check_read(g, b); if (!len) return 0;
    if (left(g) < start_bits - has_sign) return -1;
    int v = (int)get(g, start_bits - has_sign);
    if (v && has_sign) { int sign = -get1(g); v = (v ^ sign) - sign; }
    if (dst_end - dst < 1) return -1;
    *dst++ = (int16_t)v; len--;
    for (int i = 0; i < len; i += 8) {
        int len2 = len - i < 8 ? len - i : 8;
        if (dst_end - dst < len2) return -1;
        int bsize = (int)get(g, 4);
        if (bsize) {
            for (int j = 0; j < len2; j++) {
                int v2 = (int)get(g, bsize);
                if (v2) { int sign = -get1(g); v2 = (v2 ^ sign) - sign; }
                v += v2; *dst++ = (int16_t)v;
                if (v < -32768 || v > 32767) return -1;
            }
        } else for (int j = 0; j < len2; j++) *dst++ = (int16_t)v;
    }
    b->cur_dec = (uint8_t *)dst;
    return 0;
}
static int get_value(mh_bink *c, int n) {
    bundle_t *b = &c->bundle[n];
    if (n < SRC_X_OFF || n == SRC_RUN) return *b->cur_ptr++;
    if (n == SRC_X_OFF || n == SRC_Y_OFF) return (int8_t)*b->cur_ptr++;
    int16_t v; memcpy(&v, b->cur_ptr, 2); b->cur_ptr += 2; return v;
}

/* ------------------------------------------------------------------ DCT */
static int read_dct_coeffs(bits_t *g, int32_t block[64], const uint8_t *scan, int *coef_count_, int coef_idx[64], int q) {
    int coef_list[128], mode_list[128], list_start = 64, list_end = 64, coef_count = 0;
    if (left(g) < 4) return -1;
    coef_list[list_end] = 4;  mode_list[list_end++] = 0;
    coef_list[list_end] = 24; mode_list[list_end++] = 0;
    coef_list[list_end] = 44; mode_list[list_end++] = 0;
    coef_list[list_end] = 1;  mode_list[list_end++] = 3;
    coef_list[list_end] = 2;  mode_list[list_end++] = 3;
    coef_list[list_end] = 3;  mode_list[list_end++] = 3;
    for (int bits = (int)get(g, 4) - 1; bits >= 0; bits--) {
        int list_pos = list_start;
        while (list_pos < list_end) {
            if (!(mode_list[list_pos] | coef_list[list_pos]) || !get1(g)) { list_pos++; continue; }
            int ccoef = coef_list[list_pos], mode = mode_list[list_pos], t;
            switch (mode) {
            case 0: coef_list[list_pos] = ccoef + 4; mode_list[list_pos] = 1; /* fall through */
            case 2:
                if (mode == 2) { coef_list[list_pos] = 0; mode_list[list_pos++] = 0; }
                for (int i = 0; i < 4; i++, ccoef++) {
                    if (get1(g)) { coef_list[--list_start] = ccoef; mode_list[list_start] = 3; }
                    else {
                        if (!bits) t = 1 - (get1(g) << 1);
                        else { t = (int)get(g, bits) | 1 << bits; int sign = -get1(g); t = (t ^ sign) - sign; }
                        block[scan[ccoef]] = t; coef_idx[coef_count++] = ccoef;
                    }
                }
                break;
            case 1:
                mode_list[list_pos] = 2;
                for (int i = 0; i < 3; i++) { ccoef += 4; coef_list[list_end] = ccoef; mode_list[list_end++] = 2; }
                break;
            case 3:
                if (!bits) t = 1 - (get1(g) << 1);
                else { t = (int)get(g, bits) | 1 << bits; int sign = -get1(g); t = (t ^ sign) - sign; }
                block[scan[ccoef]] = t; coef_idx[coef_count++] = ccoef;
                coef_list[list_pos] = 0; mode_list[list_pos++] = 0;
                break;
            }
            if (list_start < 1 || list_end > 127) return -1;
        }
    }
    int quant_idx = q == -1 ? (int)get(g, 4) : q;
    if (quant_idx > 15) return -1;
    *coef_count_ = coef_count;
    return quant_idx;
}
static void unquantize(int32_t block[64], const int32_t quant[64], int coef_count, const int coef_idx[64], const uint8_t *scan) {
    block[0] = (int)((unsigned)block[0] * (unsigned)quant[0]) >> 11;
    for (int i = 0; i < coef_count; i++) { int idx = coef_idx[i]; block[scan[idx]] = (int)((unsigned)block[scan[idx]] * (unsigned)quant[idx]) >> 11; }
}
static int read_residue(bits_t *g, int16_t block[64], int masks_count) {
    int coef_list[128], mode_list[128], list_start = 64, list_end = 64, nz_coeff[64], nz_count = 0;
    coef_list[list_end] = 4;  mode_list[list_end++] = 0;
    coef_list[list_end] = 24; mode_list[list_end++] = 0;
    coef_list[list_end] = 44; mode_list[list_end++] = 0;
    coef_list[list_end] = 0;  mode_list[list_end++] = 2;
    for (int mask = 1 << get(g, 3); mask; mask >>= 1) {
        for (int i = 0; i < nz_count; i++) {
            if (!get1(g)) continue;
            if (block[nz_coeff[i]] < 0) block[nz_coeff[i]] = (int16_t)(block[nz_coeff[i]] - mask); else block[nz_coeff[i]] = (int16_t)(block[nz_coeff[i]] + mask);
            if (--masks_count < 0) return 0;
        }
        int list_pos = list_start;
        while (list_pos < list_end) {
            if (!(coef_list[list_pos] | mode_list[list_pos]) || !get1(g)) { list_pos++; continue; }
            int ccoef = coef_list[list_pos], mode = mode_list[list_pos], sign;
            switch (mode) {
            case 0: coef_list[list_pos] = ccoef + 4; mode_list[list_pos] = 1; /* fall through */
            case 2:
                if (mode == 2) { coef_list[list_pos] = 0; mode_list[list_pos++] = 0; }
                for (int i = 0; i < 4; i++, ccoef++) {
                    if (get1(g)) { coef_list[--list_start] = ccoef; mode_list[list_start] = 3; }
                    else {
                        if (nz_count >= 64) return -1;
                        nz_coeff[nz_count++] = bink_scan[ccoef]; sign = -get1(g); block[bink_scan[ccoef]] = (int16_t)((mask ^ sign) - sign);
                        if (--masks_count < 0) return 0;
                    }
                }
                break;
            case 1:
                mode_list[list_pos] = 2;
                for (int i = 0; i < 3; i++) { ccoef += 4; coef_list[list_end] = ccoef; mode_list[list_end++] = 2; }
                break;
            case 3:
                if (nz_count >= 64) return -1;
                nz_coeff[nz_count++] = bink_scan[ccoef]; sign = -get1(g); block[bink_scan[ccoef]] = (int16_t)((mask ^ sign) - sign);
                coef_list[list_pos] = 0; mode_list[list_pos++] = 0;
                if (--masks_count < 0) return 0;
                break;
            }
            if (list_start < 1 || list_end > 127) return -1;
        }
    }
    return 0;
}
#define A1 2896
#define A2 2217
#define A3 3784
#define A4 -5352
#define MUL(X, Y) ((int)((unsigned)(X) * (unsigned)(Y)) >> 11)
#define IDCT(dest, s0, s1, s2, s3, s4, s5, s6, s7, d0, d1, d2, d3, d4, d5, d6, d7, munge, src) { \
    const int a0 = (src)[s0] + (src)[s4], a1 = (src)[s0] - (src)[s4], a2 = (src)[s2] + (src)[s6], a3 = MUL(A1, (src)[s2] - (src)[s6]); \
    const int a4 = (src)[s5] + (src)[s3], a5 = (src)[s5] - (src)[s3], a6 = (src)[s1] + (src)[s7], a7 = (src)[s1] - (src)[s7]; \
    const int b0 = a4 + a6, b1 = MUL(A3, a5 + a7), b2 = MUL(A4, a5) - b0 + b1, b3 = MUL(A1, a6 - a4) - b2, b4 = MUL(A2, a7) + b3 - b1; \
    (dest)[d0] = munge(a0 + a2 + b0); (dest)[d1] = munge(a1 + a3 - a2 + b2); (dest)[d2] = munge(a1 - a3 + a2 + b3); (dest)[d3] = munge(a0 - a2 - b4); \
    (dest)[d4] = munge(a0 - a2 + b4); (dest)[d5] = munge(a1 - a3 + a2 - b3); (dest)[d6] = munge(a1 + a3 - a2 - b2); (dest)[d7] = munge(a0 + a2 - b0); }
#define M_NONE(x) (x)
#define M_ROW(x) (((x) + 0x7F) >> 8)
static void idct_col(int *dest, const int32_t *src) {
    if ((src[8] | src[16] | src[24] | src[32] | src[40] | src[48] | src[56]) == 0)
        dest[0] = dest[8] = dest[16] = dest[24] = dest[32] = dest[40] = dest[48] = dest[56] = src[0];
    else IDCT(dest, 0, 8, 16, 24, 32, 40, 48, 56, 0, 8, 16, 24, 32, 40, 48, 56, M_NONE, src)
}
/* As FFmpeg: values are stored to bytes without clamping (modulo 256). */
static void idct_put(uint8_t *dest, int stride, const int32_t *block) {
    int temp[64];
    for (int i = 0; i < 8; i++) idct_col(&temp[i], &block[i]);
    for (int i = 0; i < 8; i++) { uint8_t *d = dest + i * stride; const int *s = &temp[8 * i]; IDCT(d, 0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7, (uint8_t)M_ROW, s) }
}
static void idct_add(uint8_t *dest, int stride, int32_t *block) {
    int temp[64];
    for (int i = 0; i < 8; i++) idct_col(&temp[i], &block[i]);
    for (int i = 0; i < 8; i++) { int32_t *d = &block[8 * i]; const int *s = &temp[8 * i]; IDCT(d, 0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7, M_ROW, s) }
    for (int i = 0; i < 8; i++, dest += stride, block += 8) for (int j = 0; j < 8; j++) dest[j] = (uint8_t)(dest[j] + block[j]);
}
static void scale_block(const uint8_t src[64], uint8_t *dst, int stride) {
    for (int j = 0; j < 8; j++, src += 8) for (int i = 0; i < 8; i++) {
        uint8_t v = src[i]; dst[(2 * j) * stride + 2 * i] = dst[(2 * j) * stride + 2 * i + 1] = v; dst[(2 * j + 1) * stride + 2 * i] = dst[(2 * j + 1) * stride + 2 * i + 1] = v;
    }
}
static void copy8(uint8_t *dst, const uint8_t *src, int stride) { for (int i = 0; i < 8; i++) memmove(dst + i * stride, src + i * stride, 8); }
static void fill(uint8_t *dst, int v, int stride, int n) { for (int i = 0; i < n; i++) memset(dst + i * stride, v, (size_t)n); }

/* ------------------------------------------------------------------ planes */
static int put_motion(mh_bink *c, uint8_t *dst, const uint8_t *prev, int stride, const uint8_t *ref_start, const uint8_t *ref_end) {
    int xoff = get_value(c, SRC_X_OFF), yoff = get_value(c, SRC_Y_OFF);
    const uint8_t *ref = prev + xoff + yoff * stride;
    if (ref < ref_start || ref > ref_end) return -1;
    copy8(dst, ref, stride);
    return 0;
}
static int decode_plane(mh_bink *c, bits_t *g, int plane, int is_chroma) {
    uint8_t *dst, *prev; int16_t block[64]; uint8_t ublock[64]; int32_t dctblock[64]; int coordmap[64], coef_idx[64], coef_count, quant_idx, v, col[2];
    frame_t *cur = &c->fr[c->cur], *last = c->have_last ? &c->fr[c->cur ^ 1] : cur;
    const int stride = cur->stride[plane];
    const int bw = is_chroma ? (int)(c->width + 15) >> 4 : (int)(c->width + 7) >> 3, bh = is_chroma ? (int)(c->height + 15) >> 4 : (int)(c->height + 7) >> 3;
    const int width = (int)c->width >> is_chroma;
    if (c->version == 'k' && get1(g)) {
        int f = (int)get(g, 8); for (int i = 0; i < ((int)c->height >> is_chroma); i++) memset(cur->p[plane] + i * stride, f, (size_t)width);
        goto end;
    }
    init_lengths(c, width > 8 ? width : 8, bw);
    for (int i = 0; i < NB_SRC; i++) if (read_bundle(g, c, i) < 0) return -1;
    const uint8_t *ref_start = last->p[plane], *ref_end = ref_start + (bw - 1 + stride * (bh - 1)) * 8;
    for (int i = 0; i < 64; i++) coordmap[i] = (i & 7) + (i >> 3) * stride;
    for (int by = 0; by < bh; by++) {
        if (read_block_types(g, &c->bundle[SRC_BLOCK_TYPES], c->version) < 0 || read_block_types(g, &c->bundle[SRC_SUB_BLOCK_TYPES], c->version) < 0 ||
            read_colors(g, &c->bundle[SRC_COLORS], c) < 0 || read_patterns(g, &c->bundle[SRC_PATTERN]) < 0 ||
            read_motion_values(g, &c->bundle[SRC_X_OFF]) < 0 || read_motion_values(g, &c->bundle[SRC_Y_OFF]) < 0 ||
            read_dcs(g, &c->bundle[SRC_INTRA_DC], 11, 0) < 0 || read_dcs(g, &c->bundle[SRC_INTER_DC], 11, 1) < 0 || read_runs(g, &c->bundle[SRC_RUN]) < 0)
            return -1;
        dst = cur->p[plane] + 8 * by * stride; prev = last->p[plane] + 8 * by * stride;
        for (int bx = 0; bx < bw; bx++, dst += 8, prev += 8) {
            if (left(g) < 0) return -1;
            int blk = get_value(c, SRC_BLOCK_TYPES);
            if (((by & 1) || (bx & 1)) && blk == SCALED_BLOCK) { bx++; dst += 8; prev += 8; continue; }
            const uint8_t *scan;
            switch (blk) {
            case SKIP_BLOCK: copy8(dst, prev, stride); break;
            case SCALED_BLOCK:
                blk = get_value(c, SRC_SUB_BLOCK_TYPES);
                switch (blk) {
                case RUN_BLOCK: {
                    if (left(g) < 4) return -1;
                    scan = bink_patterns[get(g, 4)]; int i = 0;
                    do {
                        int run = get_value(c, SRC_RUN) + 1; i += run; if (i > 64) return -1;
                        if (get1(g)) { v = get_value(c, SRC_COLORS); for (int j = 0; j < run; j++) ublock[*scan++] = (uint8_t)v; }
                        else for (int j = 0; j < run; j++) ublock[*scan++] = (uint8_t)get_value(c, SRC_COLORS);
                    } while (i < 63);
                    if (i == 63) ublock[*scan++] = (uint8_t)get_value(c, SRC_COLORS);
                    break; }
                case INTRA_BLOCK:
                    memset(dctblock, 0, sizeof dctblock); dctblock[0] = get_value(c, SRC_INTRA_DC);
                    if ((quant_idx = read_dct_coeffs(g, dctblock, bink_scan, &coef_count, coef_idx, -1)) < 0) return -1;
                    unquantize(dctblock, bink_intra_quant[quant_idx], coef_count, coef_idx, bink_scan);
                    idct_put(ublock, 8, dctblock);
                    break;
                case FILL_BLOCK: v = get_value(c, SRC_COLORS); fill(dst, v, stride, 16); break;
                case PATTERN_BLOCK:
                    for (int i = 0; i < 2; i++) col[i] = get_value(c, SRC_COLORS);
                    for (int j = 0; j < 8; j++) { v = get_value(c, SRC_PATTERN); for (int i = 0; i < 8; i++, v >>= 1) ublock[i + j * 8] = (uint8_t)col[v & 1]; }
                    break;
                case RAW_BLOCK: for (int j = 0; j < 8; j++) for (int i = 0; i < 8; i++) ublock[i + j * 8] = (uint8_t)get_value(c, SRC_COLORS); break;
                default: return -1;
                }
                if (blk != FILL_BLOCK) scale_block(ublock, dst, stride);
                bx++; dst += 8; prev += 8;
                break;
            case MOTION_BLOCK: if (put_motion(c, dst, prev, stride, ref_start, ref_end) < 0) return -1; break;
            case RUN_BLOCK: {
                scan = bink_patterns[get(g, 4)]; int i = 0;
                do {
                    int run = get_value(c, SRC_RUN) + 1; i += run; if (i > 64) return -1;
                    if (get1(g)) { v = get_value(c, SRC_COLORS); for (int j = 0; j < run; j++) dst[coordmap[*scan++]] = (uint8_t)v; }
                    else for (int j = 0; j < run; j++) dst[coordmap[*scan++]] = (uint8_t)get_value(c, SRC_COLORS);
                } while (i < 63);
                if (i == 63) dst[coordmap[*scan++]] = (uint8_t)get_value(c, SRC_COLORS);
                break; }
            case RESIDUE_BLOCK:
                if (put_motion(c, dst, prev, stride, ref_start, ref_end) < 0) return -1;
                memset(block, 0, sizeof block); v = (int)get(g, 7);
                if (read_residue(g, block, v) < 0) return -1;
                for (int i = 0; i < 8; i++) for (int j = 0; j < 8; j++) dst[i * stride + j] = (uint8_t)(dst[i * stride + j] + block[i * 8 + j]);
                break;
            case INTRA_BLOCK:
                memset(dctblock, 0, sizeof dctblock); dctblock[0] = get_value(c, SRC_INTRA_DC);
                if ((quant_idx = read_dct_coeffs(g, dctblock, bink_scan, &coef_count, coef_idx, -1)) < 0) return -1;
                unquantize(dctblock, bink_intra_quant[quant_idx], coef_count, coef_idx, bink_scan);
                idct_put(dst, stride, dctblock);
                break;
            case FILL_BLOCK: v = get_value(c, SRC_COLORS); fill(dst, v, stride, 8); break;
            case INTER_BLOCK:
                if (put_motion(c, dst, prev, stride, ref_start, ref_end) < 0) return -1;
                memset(dctblock, 0, sizeof dctblock); dctblock[0] = get_value(c, SRC_INTER_DC);
                if ((quant_idx = read_dct_coeffs(g, dctblock, bink_scan, &coef_count, coef_idx, -1)) < 0) return -1;
                unquantize(dctblock, bink_inter_quant[quant_idx], coef_count, coef_idx, bink_scan);
                idct_add(dst, stride, dctblock);
                break;
            case PATTERN_BLOCK:
                for (int i = 0; i < 2; i++) col[i] = get_value(c, SRC_COLORS);
                for (int i = 0; i < 8; i++) { v = get_value(c, SRC_PATTERN); for (int j = 0; j < 8; j++, v >>= 1) dst[i * stride + j] = (uint8_t)col[v & 1]; }
                break;
            case RAW_BLOCK:
                if (c->bundle[SRC_COLORS].cur_ptr + 64 > c->bundle[SRC_COLORS].data_end) return -1;
                for (int i = 0; i < 8; i++) memcpy(dst + i * stride, c->bundle[SRC_COLORS].cur_ptr + i * 8, 8);
                c->bundle[SRC_COLORS].cur_ptr += 64;
                break;
            default: return -1;
            }
        }
    }
end:
    if (g->pos & 31) g->pos += 32 - (g->pos & 31);   /* the next plane starts at a 32-bit boundary */
    return 0;
}

/* ------------------------------------------------------------------ container */
static uint32_t rl32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
mh_bink *mh_bink_open(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    uint8_t h[44];
    if (fread(h, 1, 44, f) != 44 || memcmp(h, "BIK", 3)) { fclose(f); return NULL; }
    mh_bink *c = calloc(1, sizeof *c); if (!c) { fclose(f); return NULL; }
    c->f = f; c->version = h[3]; c->file_size = rl32(h + 4) + 8; c->frames = rl32(h + 8);
    c->width = rl32(h + 20); c->height = rl32(h + 24); c->flags = rl32(h + 36); c->ntracks = rl32(h + 40);
    if (c->version < 'f' || c->version > 'i' || (c->flags & 0x00100000) || !c->frames || c->frames > 1000000 ||
        !c->width || !c->height || c->width > 4096 || c->height > 4096 || c->ntracks > 256) { mh_bink_close(c); return NULL; }
    /* audio track headers: max decoded sizes, (rate, flags) pairs, ids; track 0 is played when it uses the DCT */
    if (c->ntracks) {
        uint8_t t[4];
        if (!fseek(f, 44 + 4 * (long)c->ntracks, SEEK_SET) && fread(t, 1, 4, f) == 4) {
            unsigned rate = (unsigned)(t[0] | t[1] << 8), flags = (unsigned)(t[2] | t[3] << 8);
            c->arate = rate; c->achannels = flags & 0x2000 ? 2 : 1;
            c->has_audio = (flags & 0x1000) && rate >= 8000 && rate <= 96000 && audio_init(&c->audio, rate, (int)c->achannels);
        }
    }
    if (fseek(f, 44 + 12 * (long)c->ntracks, SEEK_SET)) { mh_bink_close(c); return NULL; }
    c->index = malloc(sizeof *c->index * ((size_t)c->frames + 1));
    if (!c->index) { mh_bink_close(c); return NULL; }
    for (uint32_t i = 0; i < c->frames; i++) { uint8_t b[4]; if (fread(b, 1, 4, f) != 4) { mh_bink_close(c); return NULL; } c->index[i] = rl32(b) & ~1u; }
    c->index[c->frames] = c->file_size;
    for (uint32_t i = 0; i < c->frames; i++) if (c->index[i + 1] <= c->index[i]) { mh_bink_close(c); return NULL; }
    /* planes (with a 16-pixel margin for 16x16 blocks at the edges) and bundles */
    int bw = (int)(c->width + 7) >> 3, bh = (int)(c->height + 7) >> 3, cbw = (int)(c->width + 15) >> 4, cbh = (int)(c->height + 15) >> 4;
    for (int k = 0; k < 2; k++) {
        frame_t *fr = &c->fr[k];
        fr->stride[0] = bw * 8 + 16; fr->rows[0] = bh * 8 + 16;
        fr->stride[1] = fr->stride[2] = cbw * 8 + 16; fr->rows[1] = fr->rows[2] = cbh * 8 + 16;
        for (int p = 0; p < 3; p++) { fr->p[p] = calloc((size_t)fr->stride[p] * fr->rows[p], 1); if (!fr->p[p]) { mh_bink_close(c); return NULL; } }
        memset(fr->p[1], 128, (size_t)fr->stride[1] * fr->rows[1]); memset(fr->p[2], 128, (size_t)fr->stride[2] * fr->rows[2]);
    }
    size_t blocks = (size_t)bw * bh;
    c->bundle_mem = calloc(blocks, 64 * NB_SRC); if (!c->bundle_mem) { mh_bink_close(c); return NULL; }
    for (int i = 0; i < NB_SRC; i++) { c->bundle[i].data = c->bundle_mem + blocks * 64 * (size_t)i; c->bundle[i].data_end = c->bundle[i].data + blocks * 64; }
    c->decoded = -1;
    init_vlcs();
    return c;
}
void mh_bink_close(mh_bink *c) {
    if (!c) return;
    if (c->f) fclose(c->f);
    for (int k = 0; k < 2; k++) for (int p = 0; p < 4; p++) free(c->fr[k].p[p]);
    if (c->has_audio) audio_free(&c->audio);
    free(c->index); free(c->packet); free(c->bundle_mem); free(c->pcm); free(c);
}
size_t mh_bink_take_audio(mh_bink *c, const int16_t **pcm, unsigned *rate) {
    size_t n = c->pcm_frames; *pcm = c->pcm; *rate = c->arate; c->pcm_frames = 0; return n;
}
void mh_bink_info(const mh_bink *c, uint32_t *w, uint32_t *h, uint32_t *frames) { *w = c->width; *h = c->height; *frames = c->frames; }
/* The audio packet of one frame: a 32-bit decoded size, then blocks aligned to 32 bits. */
static void decode_audio(mh_bink *c, const uint8_t *data, uint32_t n) {
    static float out[2][2048];
    bits_t g = {data, (size_t)n * 8, 32};
    int per = c->audio.frame_len - c->audio.overlap_len;
    while (left(&g) > 0) {
        if (c->pcm_frames + (size_t)per > c->pcm_cap) {
            size_t cap = c->pcm_cap ? c->pcm_cap * 2 : 16384; while (cap < c->pcm_frames + (size_t)per) cap *= 2;
            int16_t *p = realloc(c->pcm, cap * 2 * sizeof *p); if (!p) return;
            c->pcm = p; c->pcm_cap = cap;
        }
        if (!audio_block(&c->audio, &g, out)) return;
        int16_t *o = c->pcm + 2 * c->pcm_frames;
        for (int t = 0; t < per; t++) for (int ch = 0; ch < 2; ch++) {
            float v = out[c->achannels == 2 ? ch : 0][t] * 32767.0f;
            o[2 * t + ch] = (int16_t)(v < -32768.0f ? -32768 : v > 32767.0f ? 32767 : (int)lrintf(v));
        }
        c->pcm_frames += (size_t)per;
        if (g.pos & 31) g.pos += 32 - (g.pos & 31);
    }
}
static int decode_next(mh_bink *c, uint32_t i) {
    uint32_t size = c->index[i + 1] - c->index[i];
    if (size > c->packet_cap) { uint8_t *p = realloc(c->packet, (size_t)size + 16); if (!p) return 0; c->packet = p; c->packet_cap = size; }
    if (fseek(c->f, (long)c->index[i], SEEK_SET) || fread(c->packet, 1, size, c->f) != size) return 0;
    memset(c->packet + size, 0, 16);
    /* skip the audio packets: per track, a 32-bit size and the data */
    uint32_t at = 0;
    for (uint32_t t = 0; t < c->ntracks; t++) {
        if (at + 4 > size) return 0;
        uint32_t n = rl32(c->packet + at); if (n > size - at - 4) return 0;
        if (t == 0 && c->has_audio && n >= 4) decode_audio(c, c->packet + at + 4, n);
        at += 4 + n;
    }
    bits_t g = {c->packet + at, (size_t)(size - at) * 8, 0};
    c->cur ^= 1;   /* decode into the older buffer; the newer one is the reference */
    if (c->version >= 'i') g.pos += 32;
    for (int plane = 0; plane < 3; plane++) {
        int idx = (!plane || c->version < 'h') ? plane : plane ^ 3;
        if (decode_plane(c, &g, idx, plane != 0) < 0) { c->have_last = 1; return 0; }
        if (g.pos >= g.bits) break;
    }
    c->have_last = 1;
    return 1;
}
int mh_bink_decode(mh_bink *c, uint32_t index) {
    if (!c || index >= c->frames) return 0;
    if ((int64_t)index == c->decoded) return 1;
    uint32_t from = (int64_t)index > c->decoded ? (uint32_t)(c->decoded + 1) : 0;
    if (!from) { c->have_last = 0; if (c->has_audio) c->audio.first = 1; }
    c->pcm_frames = 0;
    for (uint32_t i = from; i <= index; i++) { decode_next(c, i); c->decoded = i; }
    return 1;
}
static uint8_t clip(int v) { return (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v); }
void mh_bink_copy(const mh_bink *c, uint8_t *dst, uint32_t pitch, uint32_t sx, uint32_t sy, uint32_t w, uint32_t h, int format) {
    if (!c || c->decoded < 0) return;
    const frame_t *f = &c->fr[c->cur];
    for (uint32_t y = 0; y < h && sy + y < c->height; y++) {
        uint8_t *o = dst + (size_t)y * pitch; uint32_t yy = sy + y;
        const uint8_t *Y = f->p[0] + (size_t)yy * f->stride[0], *U = f->p[1] + (size_t)(yy >> 1) * f->stride[1], *V = f->p[2] + (size_t)(yy >> 1) * f->stride[2];
        for (uint32_t x = 0; x < w && sx + x < c->width; x++) {
            uint32_t xx = sx + x; int C = Y[xx] - 16, D = U[xx >> 1] - 128, E = V[xx >> 1] - 128;   /* BT.601, video range */
            uint8_t r = clip((298 * C + 409 * E + 128) >> 8), gg = clip((298 * C - 100 * D - 208 * E + 128) >> 8), b = clip((298 * C + 516 * D + 128) >> 8);
            if (format == 2) { uint16_t px = (uint16_t)((r >> 3) << 11 | (gg >> 2) << 5 | b >> 3); o[2 * x] = (uint8_t)px; o[2 * x + 1] = (uint8_t)(px >> 8); }
            else if (format == 1) { o[4 * x] = r; o[4 * x + 1] = gg; o[4 * x + 2] = b; o[4 * x + 3] = 255; }
            else { o[4 * x] = b; o[4 * x + 1] = gg; o[4 * x + 2] = r; o[4 * x + 3] = 255; }
        }
    }
}
