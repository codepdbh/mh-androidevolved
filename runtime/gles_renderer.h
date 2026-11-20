#ifndef MH_GLES_RENDERER_H
#define MH_GLES_RENDERER_H
/* OpenGL ES 3 backend for the port's Direct3D 8 device (runtime/port_api.c).
 *
 * Uses the same vertex assembly, texture decoding and pixel state as the reference software
 * renderer (runtime/d3d_common.c): vertices arrive in Direct3D screen space and are only mapped
 * to clip space here (with w for perspective-correct interpolation and Direct3D's integer pixel
 * centres); culling is decided on the CPU exactly as in the reference; stage-0 combine and the
 * alpha test run in the fragment shader; blending, depth and filtering use GL's fixed functions.
 * The device's back buffer is an off-screen framebuffer, scaled to the window with its aspect
 * ratio kept at Present. Requires a current GLES 3 context on the calling thread. */
#include <stdint.h>
#include "guest_memory.h"
#include "port_api.h"

typedef struct mh_gles_renderer mh_gles_renderer;
/* `swap` is called after each presented frame has been drawn to the window (e.g. eglSwapBuffers);
 * `window_size` reports the current window size in pixels. */
mh_gles_renderer *mh_gles_renderer_create(mh_guest_memory *memory, void *user,
                                          void (*swap)(void *user), void (*window_size)(void *user, int *width, int *height));
void mh_gles_renderer_destroy(mh_gles_renderer *r);
/* Internal resolution: `scale` times the back buffer (1 = the game's own resolution), or 0 for the
 * window's resolution; `stretch` fills the whole window instead of keeping the 4:3 picture with bars.
 * Presentation only: the game and its Direct3D state are unchanged. */
void mh_gles_renderer_set_options(mh_gles_renderer *r, float scale, int stretch);
void mh_gles_renderer_bind(mh_gles_renderer *r, mh_port_renderer *out);
#endif
