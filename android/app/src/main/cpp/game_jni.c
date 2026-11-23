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
#include "../../../../../runtime/d3d_common.c"
#include "../../../../../runtime/gles_renderer.c"
#include "../../../../../runtime/audio_mixer.c"
#include <aaudio/AAudio.h>
#include <unistd.h>
#include <jni.h>
#include <pthread.h>
#include <time.h>
#include <limits.h>
#include <EGL/egl.h>
#include <android/native_window_jni.h>
#include <android/log.h>

#define TAG "mh_game"
typedef struct {
    ANativeWindow *window; char exe[512], dir[512], saves[512]; unsigned frames, langid; int realtime, stretch; float scale;
    EGLDisplay display; EGLSurface surface; EGLContext context;
} game_thread;
static pthread_mutex_t started_lock = PTHREAD_MUTEX_INITIALIZER;
static int started;

static void log_line(const char *line) { __android_log_print(ANDROID_LOG_INFO, TAG, "%s", line); }
static uint64_t now_ms(void *user) {
    (void)user; struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000u + (uint64_t)t.tv_nsec / 1000000u;
}
/* Pacing: the game runs on its virtual clock (the translated path is the traced one); real time
 * is held to it at every presented frame, so the picture and the sound (played in real time) agree. */
static uint64_t pace_real0, pace_virtual0;
static void pace(void) {
    mh_port *port = mh_game_port(); if (!port) return;
    uint64_t now = now_ms(NULL), virt = mh_port_clock(port);
    if (!pace_real0) { pace_real0 = now; pace_virtual0 = virt; return; }
    int64_t ahead = (int64_t)(virt - pace_virtual0) - (int64_t)(now - pace_real0);
    if (ahead > 0) usleep((useconds_t)(ahead > 200 ? 200 : ahead) * 1000);
    else if (ahead < -250) { pace_real0 = now; pace_virtual0 = virt; }   /* far behind (loading): do not rush to catch up */
}
static void swap(void *user) { game_thread *g = user; eglSwapBuffers(g->display, g->surface); pace(); }

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
    if (g->realtime) mh_port_set_clock(port, now_ms, NULL);
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
    mh_port_renderer pr; mh_gles_renderer_bind(r, &pr);
    mh_game_config c; memset(&c, 0, sizeof c);
    c.exe_path = g->exe; c.game_dir = g->dir; c.frame_limit = g->frames ? g->frames : UINT_MAX;
    c.renderer = &pr; c.user = g; c.on_ready = on_ready; c.log = log_line; c.fatal = fatal; c.langid = g->langid; c.save_dir = g->saves;
    c.key_script = "100:30:34";   /* the reference's: a click at frame 30 skips the intro movie */
    int rc = mh_game_run(&c);
    __android_log_print(ANDROID_LOG_INFO, TAG, "game run ended: %d after %u calls, %u frames", rc, mh_game_calls(),
                        mh_game_port() ? mh_port_frames(mh_game_port()) : 0);
    return NULL;   /* the last frame stays on screen */
}

JNIEXPORT jboolean JNICALL Java_com_manhuntae_android_GameActivity_nativeStart(JNIEnv *env, jclass cls, jobject surface,
                                                                                jstring exe, jstring dir, jint frames, jboolean realtime, jint langid,
                                                                                jfloat scale, jboolean stretch, jstring saves) {
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
    g->frames = (unsigned)frames; g->realtime = realtime == JNI_TRUE; g->langid = (unsigned)langid; g->scale = scale; g->stretch = stretch == JNI_TRUE;
    pthread_attr_t attr; pthread_attr_init(&attr); pthread_attr_setstacksize(&attr, 256u << 20);
    pthread_t thread; int ok = pthread_create(&thread, &attr, run, g) == 0;
    pthread_attr_destroy(&attr);
    if (ok) pthread_detach(thread);
    return ok ? JNI_TRUE : JNI_FALSE;
}

/* Input from the activity (UI thread): DirectInput scan codes, 0x100 + n for mouse buttons.
 * Single bytes read by the game thread at GetDeviceState. */
JNIEXPORT void JNICALL Java_com_manhuntae_android_GameActivity_nativeKey(JNIEnv *env, jclass cls, jint key, jboolean down) {
    (void)env; (void)cls;
    mh_port *port = mh_game_port();
    if (port) mh_port_set_key(port, (unsigned)key, down == JNI_TRUE);
}
JNIEXPORT void JNICALL Java_com_manhuntae_android_GameActivity_nativeMouseMove(JNIEnv *env, jclass cls, jint dx, jint dy) {
    (void)env; (void)cls;
    mh_port *port = mh_game_port();
    if (port) mh_port_mouse_move(port, dx, dy);
}
