/* Software mixer for the port's Miles 3D samples; see audio_mixer.h. */
#include "audio_mixer.h"
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

#define VOICES 64
typedef struct {
    int active, playing; mh_port_sound s;
    double pos;              /* in source frames */
    int64_t loops_left;      /* 0 = forever; -1 = last pass, playing to the end */
    int16_t *decoded; uint32_t ndecoded;   /* IMA ADPCM, decoded at start */
} voice;
struct mh_mixer {
    mh_guest_memory *mem; unsigned rate; float gain;
    pthread_mutex_t lock; voice v[VOICES];
    int16_t *movie; unsigned movie_cap, movie_head, movie_len, movie_rate; double movie_pos;   /* ring of stereo frames */
};

static const int8_t MIX_IMA_INDEX[16] = {-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8};
static const int16_t MIX_IMA_STEP[89] = {7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,
    337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,
    4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767};
/* Mono IMA ADPCM (Microsoft block layout, as runtime/port_api.c decodes for AIL_process_digital_audio). */
static void mix_decode_adpcm(voice *v, const uint8_t *src) {
    uint32_t block = v->s.block, length = v->s.length;
    if (block < 5 || v->s.channels != 1) return;
    uint32_t per = (block - 4) * 2 + 1, nblocks = (length + block - 1) / block;
    v->decoded = malloc((size_t)nblocks * per * 2); if (!v->decoded) return;
    uint32_t n = 0;
    for (uint32_t b = 0; b + 4 <= length; b += block) {
        uint32_t end = b + block < length ? b + block : length;
        int pred = (int16_t)(src[b] | src[b + 1] << 8), index = src[b + 2] > 88 ? 88 : src[b + 2];
        v->decoded[n++] = (int16_t)pred;
        for (uint32_t i = b + 4; i < end; i++)
            for (int half = 0; half < 2; half++) {
                int nib = half ? src[i] >> 4 : src[i] & 15, step = MIX_IMA_STEP[index], diff = step >> 3;
                if (nib & 4) diff += step;
                if (nib & 2) diff += step >> 1;
                if (nib & 1) diff += step >> 2;
                pred = nib & 8 ? pred - diff : pred + diff; pred = pred < -32768 ? -32768 : pred > 32767 ? 32767 : pred;
                index += MIX_IMA_INDEX[nib]; index = index < 0 ? 0 : index > 88 ? 88 : index;
                v->decoded[n++] = (int16_t)pred;
            }
    }
    v->ndecoded = n;
}
static uint32_t mix_frame_bytes(const mh_port_sound *s) { uint32_t b = (s->bits / 8) * s->channels; return b ? b : 1; }
static uint32_t mix_total_frames(const voice *v) { return v->s.format == 0x11 ? v->ndecoded : v->s.length / mix_frame_bytes(&v->s); }
static uint32_t mix_to_frames(const voice *v, uint32_t bytes) {
    if (v->s.format == 0x11) return v->s.length ? (uint32_t)((uint64_t)bytes * v->ndecoded / v->s.length) : 0;
    return bytes / mix_frame_bytes(&v->s);
}
static voice *voice_find(mh_mixer *m, uint32_t handle, int create) {
    voice *free_slot = NULL;
    for (int i = 0; i < VOICES; i++) {
        if (m->v[i].active && m->v[i].s.handle == handle) return &m->v[i];
        if (!m->v[i].active && !free_slot) free_slot = &m->v[i];
    }
    return create ? free_slot : NULL;
}
static void voice_release(voice *v) { free(v->decoded); memset(v, 0, sizeof *v); }

void mh_mixer_sound(mh_mixer *m, const mh_port_sound *s, int event) {
    pthread_mutex_lock(&m->lock);
    voice *v = voice_find(m, s->handle, event == MH_SOUND_START);
    if (v) switch (event) {
    case MH_SOUND_START:
        voice_release(v); v->active = 1; v->s = *s; v->pos = 0; v->loops_left = s->loops;
        if (s->format == 0x11) {
            const uint8_t *src = s->length ? mh_mem_span(m->mem, s->data, s->length) : NULL;
            if (src) mix_decode_adpcm(v, src);
            if (!v->decoded) { voice_release(v); break; }
        } else if (s->format != 1 || (s->bits != 8 && s->bits != 16)) { voice_release(v); break; }
        v->playing = 1; break;
    case MH_SOUND_STOP: v->playing = 0; break;
    case MH_SOUND_RESUME: v->playing = 1; break;
    case MH_SOUND_END: case MH_SOUND_RELEASE: voice_release(v); break;
    case MH_SOUND_CHANGE:
        v->s.volume = s->volume; v->s.playback_rate = s->playback_rate; v->s.loop_start = s->loop_start; v->s.loop_end = s->loop_end;
        if (v->loops_left >= 0) v->loops_left = s->loops;
        break;
    }
    pthread_mutex_unlock(&m->lock);
}

void mh_mixer_render(mh_mixer *m, int16_t *out, unsigned frames) {
    int32_t *acc = calloc((size_t)frames * 2, sizeof *acc);
    if (!acc) { memset(out, 0, (size_t)frames * 4); return; }
    pthread_mutex_lock(&m->lock);
    for (int i = 0; i < VOICES; i++) {
        voice *v = &m->v[i];
        if (!v->active || !v->playing) continue;
        uint32_t total = mix_total_frames(v); if (!total) continue;
        const uint8_t *pcm = NULL;
        if (v->s.format != 0x11 && !(pcm = mh_mem_span(m->mem, v->s.data, v->s.length))) continue;   /* read in place: streams are refilled */
        uint32_t loop_start = mix_to_frames(v, v->s.loop_start), loop_end = v->s.loop_end == 0xffffffffu || !v->s.loop_end ? total : mix_to_frames(v, v->s.loop_end);
        if (loop_end > total || loop_end <= loop_start) loop_end = total;
        float vol = v->s.volume > 1.5f ? v->s.volume / 127.0f : v->s.volume; vol = vol < 0 ? 0 : vol > 1 ? 1 : vol; vol *= m->gain;
        int32_t g = (int32_t)(vol * 256);
        double step = (double)(v->s.playback_rate ? v->s.playback_rate : v->s.rate) / m->rate;
        int stereo = v->s.channels == 2 && v->s.format != 0x11;
        for (unsigned f = 0; f < frames; f++) {
            uint32_t end = v->loops_left == -1 || v->loops_left == 1 ? total : loop_end;
            if (v->pos >= end) {
                if (v->loops_left == -1 || v->loops_left == 1) { v->playing = 0; break; }
                if (v->loops_left > 1) v->loops_left--;
                v->pos = loop_start + (v->pos - end);
                if (v->loops_left == 1 && loop_end < total) v->loops_left = -1;
                if (v->pos >= total) v->pos = loop_start;
            }
            uint32_t k = (uint32_t)v->pos; int32_t l, r;
            if (v->s.format == 0x11) l = r = v->decoded[k];
            else if (v->s.bits == 16) { const uint8_t *p = pcm + (size_t)k * mix_frame_bytes(&v->s); l = (int16_t)(p[0] | p[1] << 8); r = stereo ? (int16_t)(p[2] | p[3] << 8) : l; }
            else { const uint8_t *p = pcm + (size_t)k * mix_frame_bytes(&v->s); l = (p[0] - 128) << 8; r = stereo ? (p[1] - 128) << 8 : l; }
            acc[2 * f] += l * g >> 8; acc[2 * f + 1] += r * g >> 8;
            v->pos += step;
        }
    }
    if (m->movie_len && m->movie_rate) {   /* the movie sound, resampled (linear) to the output rate */
        double step = (double)m->movie_rate / m->rate; int32_t g = (int32_t)(m->gain * 256);
        for (unsigned f = 0; f < frames && m->movie_pos + 1 < m->movie_len; f++) {
            unsigned k = (unsigned)m->movie_pos; double t = m->movie_pos - k;
            const int16_t *a = m->movie + 2 * ((m->movie_head + k) % m->movie_cap), *b = m->movie + 2 * ((m->movie_head + k + 1) % m->movie_cap);
            acc[2 * f] += (int32_t)((a[0] + (b[0] - a[0]) * t) * g) >> 8; acc[2 * f + 1] += (int32_t)((a[1] + (b[1] - a[1]) * t) * g) >> 8;
            m->movie_pos += step;
        }
        unsigned used = (unsigned)m->movie_pos; if (used > m->movie_len) used = m->movie_len;
        m->movie_head = (m->movie_head + used) % m->movie_cap; m->movie_len -= used; m->movie_pos -= used;
    }
    pthread_mutex_unlock(&m->lock);
    for (unsigned i = 0; i < frames * 2; i++) out[i] = (int16_t)(acc[i] < -32768 ? -32768 : acc[i] > 32767 ? 32767 : acc[i]);
    free(acc);
}

static void mix_on_sound(void *user, mh_port *port, const mh_port_sound *s, int event) { (void)port; mh_mixer_sound(user, s, event); }
void mh_mixer_movie(mh_mixer *m, const int16_t *pcm, unsigned frames, unsigned rate) {
    pthread_mutex_lock(&m->lock);
    if (!pcm) { m->movie_len = 0; m->movie_pos = 0; pthread_mutex_unlock(&m->lock); return; }
    if (!m->movie) { m->movie_cap = 48000 * 8; m->movie = malloc((size_t)m->movie_cap * 4); if (!m->movie) { m->movie_cap = 0; pthread_mutex_unlock(&m->lock); return; } }
    if (rate != m->movie_rate) { m->movie_rate = rate; m->movie_len = 0; m->movie_pos = 0; }
    for (unsigned i = 0; i < frames && m->movie_len < m->movie_cap; i++, m->movie_len++) {
        unsigned at = (m->movie_head + m->movie_len) % m->movie_cap; m->movie[2 * at] = pcm[2 * i]; m->movie[2 * at + 1] = pcm[2 * i + 1];
    }
    pthread_mutex_unlock(&m->lock);
}
static void mix_on_movie(void *user, mh_port *port, const int16_t *pcm, unsigned frames, unsigned rate) { (void)port; mh_mixer_movie(user, pcm, frames, rate); }
mh_mixer *mh_mixer_create(mh_guest_memory *memory, unsigned rate) {
    mh_mixer *m = calloc(1, sizeof *m); if (!m) return NULL;
    m->mem = memory; m->rate = rate ? rate : 48000; m->gain = 0.8f; pthread_mutex_init(&m->lock, NULL);
    return m;
}
void mh_mixer_destroy(mh_mixer *m) { if (!m) return; for (int i = 0; i < VOICES; i++) voice_release(&m->v[i]); pthread_mutex_destroy(&m->lock); free(m->movie); free(m); }
void mh_mixer_bind(mh_mixer *m, mh_port_audio *out) { out->user = m; out->sound = mix_on_sound; out->movie = mix_on_movie; }
void mh_mixer_set_gain(mh_mixer *m, float gain) { pthread_mutex_lock(&m->lock); m->gain = gain; pthread_mutex_unlock(&m->lock); }
