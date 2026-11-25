#ifndef MH_D3D_COMMON_H
#define MH_D3D_COMMON_H
/* What every renderer of the port's Direct3D 8 device needs, computed once from the recorded
 * state: textures decoded to RGBA, draw calls assembled into screen-space triangles, and the
 * fixed-function pixel state. Shared by the reference software renderer and the GLES backend so
 * both see exactly the same data. Portable C. */
#include <stddef.h>
#include <stdint.h>
#include "guest_memory.h"
#include "port_api.h"

/* A vertex after the fixed-function vertex stage, in screen space (pixels; Direct3D samples
 * pixel centres at integer coordinates), with z in [MinZ, MaxZ] and rhw = 1/w. */
typedef struct { float x, y, z, rhw; float diffuse[4], specular[4]; float u, v; float clip[4]; int has_clip; } mh_d3d_vertex;
/* Set by a backend that clips on the GPU: untransformed vertices also carry their clip-space position
 * (`clip`, `has_clip`) and the ones behind the camera are kept (x, y, z, rhw are then not meaningful). */
extern int mh_d3d_keep_clip;

/* Assembles a draw call into a triangle list (3 vertices per triangle). Triangles with a vertex
 * behind the eye (w <= 0, no near-plane clipping yet) are dropped. Returns the number of
 * vertices written to *out (malloc'd, caller frees). */
size_t mh_d3d_assemble(mh_guest_memory *memory, mh_port *port, const mh_port_draw_call *call, mh_d3d_vertex **out);

/* Level 0 of a texture as RGBA8 (rows top to bottom), malloc'd; unknown formats are magenta. */
uint8_t *mh_d3d_decode_texture(mh_guest_memory *memory, const mh_port_texture_info *t);

/* The fixed-function pixel state of stage 0 and the output merger. */
typedef struct {
    int has_texture; mh_port_texture_info texture; uint32_t address_u, address_v, mag_filter, min_filter;
    uint32_t colorop, colorarg1, colorarg2, alphaop, alphaarg1, alphaarg2, tfactor;
    int alpha_test; uint32_t alpha_ref, alpha_func;
    int blend; uint32_t src_blend, dst_blend, blend_op;
    int z_test, z_write; uint32_t z_func;
    uint32_t cull;          /* D3DCULL: 1 none, 2 clockwise, 3 counter-clockwise */
    uint32_t color_write;
} mh_d3d_pixel_state;
void mh_d3d_pixel_state_get(mh_port *port, mh_d3d_pixel_state *s);
#endif
