#ifndef MH_SW_RENDERER_H
#define MH_SW_RENDERER_H
/* Reference software renderer for the port's Direct3D 8 device (runtime/port_api.c).
 *
 * Portable C, no GPU: draws the recorded device state (FVF vertices, index/vertex buffers
 * and *UP data, transforms and viewport, stage-0 texture combine, alpha test/blend,
 * z-buffer, culling; textures in the common RGB formats and DXT1-5) into an RGBA image.
 * It is the ground truth the GLES backend is checked against, and a way to look at frames
 * on any machine. Fixed-function lighting is not modelled yet (vertex colours are used). */
#include <stdint.h>
#include <stdio.h>
#include "guest_memory.h"
#include "port_api.h"

typedef struct mh_sw_renderer mh_sw_renderer;
/* `log` (may be NULL) receives one line per clear/draw/present; `png_pattern` (may be NULL)
 * is a printf pattern with one %u for the frame number, e.g. "frame%03u.png". */
mh_sw_renderer *mh_sw_renderer_create(mh_guest_memory *memory, FILE *log, const char *png_pattern);
void mh_sw_renderer_destroy(mh_sw_renderer *r);
/* Fills a mh_port_renderer that routes the device's notifications to `r`. */
void mh_sw_renderer_bind(mh_sw_renderer *r, mh_port_renderer *out);
/* The last presented frame (RGBA, rows top to bottom). */
const uint8_t *mh_sw_renderer_frame(const mh_sw_renderer *r, uint32_t *width, uint32_t *height);
/* PNG (8-bit RGBA, stored deflate blocks) of an RGBA image; returns 1 on success. */
int mh_write_png(const char *path, const uint8_t *rgba, uint32_t width, uint32_t height);
#endif
