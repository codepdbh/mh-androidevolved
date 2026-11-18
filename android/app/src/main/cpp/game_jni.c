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
#include <jni.h>
#include <pthread.h>
#include <time.h>
#include <limits.h>
#include <EGL/egl.h>
#include <android/native_window_jni.h>
#include <android/log.h>

#define TAG "mh_game"
typedef struct {
    ANativeWindow *window; char exe[512], dir[512]; unsigned frames, langid; int realtime;
    EGLDisplay display; EGLSurface surface; EGLContext context;
} game_thread;
static pthread_mutex_t started_lock = PTHREAD_MUTEX_INITIALIZER;
static int started;

static void log_line(const char *line) { __android_log_print(ANDROID_LOG_INFO, TAG, "%s", line); }
static uint64_t now_ms(void *user) {
    (void)user; struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000u + (uint64_t)t.tv_nsec / 1000000u;
}
static void swap(void *user) { game_thread *g = user; eglSwapBuffers(g->display, g->surface); }
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
    mh_port_renderer pr; mh_gles_renderer_bind(r, &pr);
    mh_game_config c; memset(&c, 0, sizeof c);
    c.exe_path = g->exe; c.game_dir = g->dir; c.frame_limit = g->frames ? g->frames : UINT_MAX;
    c.renderer = &pr; c.user = g; c.on_ready = on_ready; c.log = log_line; c.fatal = fatal; c.langid = g->langid;
    c.key_script = "100:30:34";   /* the reference's: a click at frame 30 skips the intro movie */
    int rc = mh_game_run(&c);
    __android_log_print(ANDROID_LOG_INFO, TAG, "game run ended: %d after %u calls, %u frames", rc, mh_game_calls(),
                        mh_game_port() ? mh_port_frames(mh_game_port()) : 0);
    return NULL;   /* the last frame stays on screen */
}

JNIEXPORT jboolean JNICALL Java_com_manhuntae_android_GameActivity_nativeStart(JNIEnv *env, jclass cls, jobject surface,
                                                                                jstring exe, jstring dir, jint frames, jboolean realtime, jint langid) {
    (void)cls;
    pthread_mutex_lock(&started_lock);
    if (started) { pthread_mutex_unlock(&started_lock); return JNI_FALSE; }   /* the guest state cannot be restarted */
    started = 1; pthread_mutex_unlock(&started_lock);
    game_thread *g = calloc(1, sizeof *g); if (!g) return JNI_FALSE;
    g->window = ANativeWindow_fromSurface(env, surface);
    const char *e = (*env)->GetStringUTFChars(env, exe, NULL), *d = (*env)->GetStringUTFChars(env, dir, NULL);
    snprintf(g->exe, sizeof g->exe, "%s", e); snprintf(g->dir, sizeof g->dir, "%s", d);
    (*env)->ReleaseStringUTFChars(env, exe, e); (*env)->ReleaseStringUTFChars(env, dir, d);
    g->frames = (unsigned)frames; g->realtime = realtime == JNI_TRUE; g->langid = (unsigned)langid;
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
