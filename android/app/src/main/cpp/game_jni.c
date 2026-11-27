/* libmh_game: the translated game in the app (private build: it contains translated game code,
 * compiled by scripts/worksafe.py build_game_library, never part of the public sources).
 *
 * GameActivity hands over its Surface; a dedicated thread with a large stack (translated calls
 * nest like the original's) creates an EGL / OpenGL ES 3 context on it and runs the shared boot
 * (runtime/game_runner.c) with the GLES backend: every Present is drawn to the window and swapped.
 * The intro is skipped with the same scripted click as the x86 reference (so the run follows the
 * translated path into the main menu). When the frame limit is reached, or the guest reaches code
 * not translated yet, the thread ends and the last frame stays on screen.
 * The activity runs in its own process (":game"): a fault in the guest ends only that process. */
#include "../../../../../runtime/game_runner.c"
#include <time.h>
static inline uint64_t mh_prof_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000u + (uint64_t)t.tv_nsec; }
#define MH_GLES_PROFILE mh_prof_ns
#include "../../../../../runtime/d3d_common.c"
#include "../../../../../runtime/gles_renderer.c"
#include "../../../../../runtime/audio_mixer.c"
#include "../../../../../runtime/touch_input.h"
#include <aaudio/AAudio.h>
#include <unistd.h>
#include <jni.h>
#include <pthread.h>
#include <time.h>
#include <limits.h>
#include <EGL/egl.h>
#include <android/native_window_jni.h>
#include <android/log.h>
#include <sys/system_properties.h>

#define TAG "mh_game"
typedef struct {
    ANativeWindow *window; char exe[512], dir[512], saves[512]; unsigned frames, langid; int realtime, stretch; float scale;
    EGLDisplay display; EGLSurface surface; EGLContext context;
} game_thread;
static pthread_mutex_t started_lock = PTHREAD_MUTEX_INITIALIZER;
static int started;
static pthread_mutex_t input_lock = PTHREAD_MUTEX_INITIALIZER;
static mh_touch_input input;
static void apply_input(mh_port *port) {
    uint8_t keys[MH_TOUCH_KEYS]; int32_t dx, dy;
    pthread_mutex_lock(&input_lock); mh_touch_take(&input, keys, &dx, &dy); pthread_mutex_unlock(&input_lock);
    for (unsigned i = 0; i < MH_TOUCH_KEYS; i++) mh_port_set_key(port, i, keys[i]);
    if (dx || dy) mh_port_mouse_move(port, dx, dy);
}

static void log_line(const char *line) { __android_log_print(ANDROID_LOG_INFO, TAG, "%s", line); }
static uint64_t now_ms(void *user) {
    (void)user; struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000u + (uint64_t)t.tv_nsec / 1000000u;
}
/* Pacing: the game runs on its virtual clock (the translated path is the traced one); real time
 * is held to it at every presented frame, so the picture and the sound (played in real time) agree. */
static uint64_t pace_real0, pace_virtual0;
/* With the real-time clock (EXTRA_REALTIME) the game's clock already is real time: there is
 * nothing to hold back, and a baseline taken from a stale clock sample would be slept on
 * every frame (measured: ~107 ms a frame, 9 fps on the S25). */
static int pace_realtime;
static void pace(void) {
    if (pace_realtime) return;
    mh_port *port = mh_game_port(); if (!port) return;
    uint64_t now = now_ms(NULL), virt = mh_port_clock(port);
    if (!pace_real0) { pace_real0 = now; pace_virtual0 = virt; return; }
    int64_t ahead = (int64_t)(virt - pace_virtual0) - (int64_t)(now - pace_real0);
    if (ahead > 0) usleep((useconds_t)(ahead > 200 ? 200 : ahead) * 1000);
    else if (ahead < -250) { pace_real0 = now; pace_virtual0 = virt; }   /* far behind (loading): do not rush to catch up */
}
static uint64_t now_us(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000u + (uint64_t)t.tv_nsec / 1000u; }
static struct { uint64_t frame0, draw, present, swap, sleep, draws, frames, virt0; } perf;
static mh_port_renderer inner;
/* Diagnostics (adb shell setprop): debug.mh.skip is a mask of draws to leave out (1 sampling a
 * render target, 2 into a render target, 4 with fog, 8 blended ZERO/INVSRCCOLOR, 16 pre-transformed);
 * a new value of debug.mh.log logs every draw of the next frame. Read once per 120 frames. */
static unsigned dbg_skip, dbg_log_frame; static char dbg_log_seen[PROP_VALUE_MAX];
static void dbg_poll(void) {
    char v[PROP_VALUE_MAX] = {0};
    __system_property_get("debug.mh.skip", v); dbg_skip = (unsigned)strtoul(v, NULL, 0);
    memset(v, 0, sizeof v); __system_property_get("debug.mh.log", v);
    if (v[0] && strcmp(v, dbg_log_seen)) { memcpy(dbg_log_seen, v, sizeof v); dbg_log_frame = 1; }
}
static void timed_draw(void *user, mh_port *port, const mh_port_draw_call *call) {
    if (dbg_skip || dbg_log_frame == 2) {
        mh_d3d_pixel_state s; mh_d3d_pixel_state_get(port, &s);
        uint32_t tm = 0, tw = 0, th = 0, tf = 0; int into = mh_port_render_target(port, &tm, &tw, &th, &tf) && tw && th;
        int sample = s.has_texture && target_for(user, s.texture.memory[0]) != NULL, pre = (mh_port_fvf(port) & 0x00e) == 0x004;
        unsigned cat = (sample ? 1u : 0) | (into ? 2u : 0) | (s.fog_mode ? 4u : 0) | (s.blend && s.src_blend == 1 && s.dst_blend == 4 ? 8u : 0) | (pre ? 16u : 0);
        if (dbg_log_frame == 2)
            __android_log_print(ANDROID_LOG_INFO, TAG, "draw kind=%d prim=%u n=%u fvf=%03x cat=%x rt=%08x tex=%08x %ux%u fmt=%08x op=%u(%x,%x) aop=%u blend=%d(%u,%u) atest=%d(%u,%u) z=%d/%d(%u) cull=%u fog=%u(%g,%g,%06x) addr=%u/%u",
                call->kind, call->primitive, call->args[1], mh_port_fvf(port), cat, tm, s.has_texture ? s.texture.memory[0] : 0, s.texture.level_width[0], s.texture.level_height[0], s.texture.format,
                s.colorop, s.colorarg1, s.colorarg2, s.alphaop, s.blend, s.src_blend, s.dst_blend, s.alpha_test, s.alpha_func, s.alpha_ref, s.z_test, s.z_write, s.z_func, s.cull,
                s.fog_mode, s.fog_start, s.fog_end, s.fog_color, s.address_u, s.address_v);
        if (dbg_skip & cat) return;
    }
    uint64_t t = now_us(); inner.draw(user, port, call); perf.draw += now_us() - t; perf.draws++;
}
/* debug.mh.dump: a new value writes every render target as PPM (rows top-down) to the saves folder. */
static char dbg_dump_dir[512], dbg_dump_seen[PROP_VALUE_MAX];
static void dbg_dump(mh_gles_renderer *r) {
    char v[PROP_VALUE_MAX] = {0}; __system_property_get("debug.mh.dump", v);
    if (!v[0] || !strcmp(v, dbg_dump_seen) || !dbg_dump_dir[0]) return;
    memcpy(dbg_dump_seen, v, sizeof v);
    for (unsigned i = 0; i < r->ntargets; i++) {
        const gl_target *t = &r->targets[i]; size_t n = (size_t)t->fw * t->fh * 4; uint8_t *px = malloc(n); if (!px) continue;
        glBindFramebuffer(GL_FRAMEBUFFER, t->fbo); glReadPixels(0, 0, t->fw, t->fh, GL_RGBA, GL_UNSIGNED_BYTE, px);
        char path[700]; snprintf(path, sizeof path, "%s/rt_%s_%08x.ppm", dbg_dump_dir, v, t->memory);
        FILE *f = fopen(path, "wb");
        if (f) { fprintf(f, "P6\n%d %d\n255\n", t->fw, t->fh);
                 for (int y = t->fh - 1; y >= 0; y--) for (int x = 0; x < t->fw; x++) fwrite(px + 4 * ((size_t)y * t->fw + x), 1, 3, f);
                 fclose(f); __android_log_print(ANDROID_LOG_INFO, TAG, "dumped %s", path); }
        free(px);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, r->fbo);
}
static void timed_present(void *user, mh_port *port, unsigned frame) {
    if (perf.frames % 30 == 15) dbg_dump(user);
    uint64_t t = now_us(); inner.present(user, port, frame); perf.present += now_us() - t;
    apply_input(port);
    if (dbg_log_frame == 2) dbg_log_frame = 0; else if (dbg_log_frame == 1) dbg_log_frame = 2;
    if (perf.frames % 30 == 0) dbg_poll();
    if (++perf.frames == 120) {
        uint64_t now = now_us(), all = now - perf.frame0, virt = mh_port_clock(port);
        uint64_t other = perf.present + perf.draw; uint64_t guest = all > other ? all - other : 0;
        __android_log_print(ANDROID_LOG_INFO, TAG, "perf 120 frames: %.1f fps real, %.1f fps virtual; per frame ms: guest %.2f, draw %.2f (%llu calls), present %.2f (swap %.2f, pace sleep %.2f); draw split ms: assemble %.2f, build %.2f, gl %.2f (%llu batches)",
                            perf.frame0 ? 120e6 / all : 0.0, perf.virt0 && virt > perf.virt0 ? 120e3 / (double)(virt - perf.virt0) : 0.0,
                            guest / 120e3, perf.draw / 120e3, (unsigned long long)(perf.draws / 120), perf.present / 120e3, perf.swap / 120e3, perf.sleep / 120e3,
                            mh_gles_prof[0] / 120e6, mh_gles_prof[1] / 120e6, mh_gles_prof[2] / 120e6, (unsigned long long)(mh_gles_prof[3] / 120));
        memset(mh_gles_prof, 0, sizeof mh_gles_prof);
        memset(&perf, 0, sizeof perf); perf.frame0 = now; perf.virt0 = virt;
    }
}
static void swap(void *user) {
    game_thread *g = user; uint64_t t = now_us(); eglSwapBuffers(g->display, g->surface); uint64_t t2 = now_us(); perf.swap += t2 - t;
    pace(); perf.sleep += now_us() - t2;
}

/* Sound: the Miles samples mixed in software (runtime/audio_mixer.c), played by AAudio. */
static mh_mixer *mixer;
static aaudio_data_callback_result_t audio_callback(AAudioStream *stream, void *user, void *data, int32_t frames) {
    (void)stream; (void)user; mh_mixer_render(mixer, data, (unsigned)frames); return AAUDIO_CALLBACK_RESULT_CONTINUE;
}
static void start_audio(void) {
    AAudioStreamBuilder *b = NULL; AAudioStream *stream = NULL;
    if (AAudio_createStreamBuilder(&b) != AAUDIO_OK) return;
    AAudioStreamBuilder_setFormat(b, AAUDIO_FORMAT_PCM_I16); AAudioStreamBuilder_setChannelCount(b, 2);
    AAudioStreamBuilder_setSampleRate(b, 48000); AAudioStreamBuilder_setPerformanceMode(b, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
    AAudioStreamBuilder_setUsage(b, AAUDIO_USAGE_GAME); AAudioStreamBuilder_setDataCallback(b, audio_callback, NULL);
    if (AAudioStreamBuilder_openStream(b, &stream) == AAUDIO_OK && AAudioStream_getSampleRate(stream) == 48000) AAudioStream_requestStart(stream);
    else log_line("audio output unavailable");
    AAudioStreamBuilder_delete(b);
}
static void window_size(void *user, int *w, int *h) {
    game_thread *g = user; EGLint x = 0, y = 0;
    eglQuerySurface(g->display, g->surface, EGL_WIDTH, &x); eglQuerySurface(g->display, g->surface, EGL_HEIGHT, &y);
    *w = x; *h = y;
}
static void fatal(void *user, int code) {
    (void)user; __android_log_print(ANDROID_LOG_WARN, TAG, "guest stopped (%d) after %u frames; the last frame stays on screen", code,
                                     mh_game_port() ? mh_port_frames(mh_game_port()) : 0);
    pthread_exit(NULL);
}
static void on_ready(void *user, mh_port *port, mh_guest_memory *memory) {
    game_thread *g = user; (void)memory;
    if (mixer) { static mh_port_audio audio; mh_mixer_bind(mixer, &audio); mh_port_set_audio(port, &audio); start_audio(); }
    if (g->realtime) { mh_port_set_clock(port, now_ms, NULL); pace_realtime = 1; }
    mh_port_set_video_decode(port, 1);   /* the movies are decoded in the app (they stay black in the compared runs) */
    memset(&perf, 0, sizeof perf); perf.frame0 = now_us(); perf.virt0 = mh_port_clock(port);
}
static int init_egl(game_thread *g) {
    g->display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (g->display == EGL_NO_DISPLAY || !eglInitialize(g->display, NULL, NULL)) return 0;
    const EGLint attrs[] = {EGL_RENDERABLE_TYPE, 0x40 /* EGL_OPENGL_ES3_BIT */, EGL_SURFACE_TYPE, EGL_WINDOW_BIT,
                            EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_NONE};
    EGLConfig config; EGLint n = 0;
    if (!eglChooseConfig(g->display, attrs, &config, 1, &n) || n < 1) return 0;
    g->surface = eglCreateWindowSurface(g->display, config, g->window, NULL);
    const EGLint context_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    g->context = eglCreateContext(g->display, config, EGL_NO_CONTEXT, context_attrs);
    if (g->surface == EGL_NO_SURFACE || g->context == EGL_NO_CONTEXT) return 0;
    return eglMakeCurrent(g->display, g->surface, g->surface, g->context) == EGL_TRUE;
}
static void *run(void *arg) {
    game_thread *g = arg;
    if (!init_egl(g)) { log_line("EGL / OpenGL ES 3 initialisation failed"); return NULL; }
    __android_log_print(ANDROID_LOG_INFO, TAG, "GL: %s / %s", (const char *)glGetString(GL_RENDERER), (const char *)glGetString(GL_VERSION));
    glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT); eglSwapBuffers(g->display, g->surface);
    mh_gles_renderer *r = mh_gles_renderer_create(&mh_recomp_region, g, swap, window_size);
    mh_gles_renderer_set_options(r, g->scale, g->stretch);
    mixer = mh_mixer_create(&mh_recomp_region, 48000);
    mh_port_renderer pr; mh_gles_renderer_bind(r, &inner); pr = inner; pr.draw = timed_draw; pr.present = timed_present;
    mh_game_config c; memset(&c, 0, sizeof c);
    c.exe_path = g->exe; c.game_dir = g->dir; c.frame_limit = g->frames ? g->frames : UINT_MAX;
    c.renderer = &pr; c.user = g; c.on_ready = on_ready; c.log = log_line; c.fatal = fatal; c.langid = g->langid; c.save_dir = g->saves; snprintf(dbg_dump_dir, sizeof dbg_dump_dir, "%s", g->saves);
    c.key_script = "100:30:34";   /* the reference's: a click at frame 30 skips the intro movie */
    int rc = mh_game_run(&c);
    __android_log_print(ANDROID_LOG_INFO, TAG, "game run ended: %d after %u calls, %u frames", rc, mh_game_calls(),
                        mh_game_port() ? mh_port_frames(mh_game_port()) : 0);
    return NULL;   /* the last frame stays on screen */
}

JNIEXPORT jboolean JNICALL Java_com_manhuntae_android_GameActivity_nativeStart(JNIEnv *env, jclass cls, jobject surface,
                                                                                jstring exe, jstring dir, jint frames, jboolean realtime, jint langid,
                                                                                jfloat scale, jint stretch, jstring saves) {
    (void)cls;
    pthread_mutex_lock(&started_lock);
    if (started) { pthread_mutex_unlock(&started_lock); return JNI_FALSE; }   /* the guest state cannot be restarted */
    started = 1; pthread_mutex_unlock(&started_lock);
    game_thread *g = calloc(1, sizeof *g); if (!g) return JNI_FALSE;
    g->window = ANativeWindow_fromSurface(env, surface);
    const char *e = (*env)->GetStringUTFChars(env, exe, NULL), *d = (*env)->GetStringUTFChars(env, dir, NULL);
    snprintf(g->exe, sizeof g->exe, "%s", e); snprintf(g->dir, sizeof g->dir, "%s", d);
    (*env)->ReleaseStringUTFChars(env, exe, e); (*env)->ReleaseStringUTFChars(env, dir, d);
    const char *sv = (*env)->GetStringUTFChars(env, saves, NULL); snprintf(g->saves, sizeof g->saves, "%s", sv); (*env)->ReleaseStringUTFChars(env, saves, sv);
    g->frames = (unsigned)frames; g->realtime = realtime == JNI_TRUE; g->langid = (unsigned)langid; g->scale = scale; g->stretch = (int)stretch;
    pthread_attr_t attr; pthread_attr_init(&attr); pthread_attr_setstacksize(&attr, 256u << 20);
    pthread_t thread; int ok = pthread_create(&thread, &attr, run, g) == 0;
    pthread_attr_destroy(&attr);
    if (ok) pthread_detach(thread);
    return ok ? JNI_TRUE : JNI_FALSE;
}

/* The UI only writes the protected mailbox. Guest state is accessed by the game thread. */
JNIEXPORT void JNICALL Java_com_manhuntae_android_GameActivity_nativeKey(JNIEnv *env, jclass cls, jint key, jboolean down) {
    (void)env; (void)cls;
    pthread_mutex_lock(&input_lock); mh_touch_key(&input, (unsigned)key, down == JNI_TRUE); pthread_mutex_unlock(&input_lock);
}
JNIEXPORT void JNICALL Java_com_manhuntae_android_GameActivity_nativeMouseMove(JNIEnv *env, jclass cls, jint dx, jint dy) {
    (void)env; (void)cls;
    pthread_mutex_lock(&input_lock); mh_touch_move(&input, dx, dy); pthread_mutex_unlock(&input_lock);
}
