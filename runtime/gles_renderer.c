/* OpenGL ES 3 backend for the port's Direct3D 8 device; see gles_renderer.h. */
#include "gles_renderer.h"
#include "d3d_common.h"
#include <GLES3/gl3.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t memory, format, width, height, version; GLuint id; } gl_texture;
struct mh_gles_renderer {
    mh_guest_memory *mem; void *user; void (*swap)(void *); void (*window_size)(void *, int *, int *);
    uint32_t width, height; GLuint fbo, color, depth;
    GLuint program, vbo, vao;
    GLint u_tex, u_has_tex, u_color, u_alpha, u_tfactor, u_atest, u_afunc, u_aref;
    gl_texture textures[512]; unsigned ntextures;
};

static const char *VERTEX =
    "#version 300 es\n"
    "layout(location=0) in vec4 a_pos; layout(location=1) in vec4 a_diffuse; layout(location=2) in vec4 a_specular; layout(location=3) in vec2 a_uv;\n"
    "out vec4 v_diffuse; out vec4 v_specular; out vec2 v_uv;\n"
    "void main(){ gl_Position=a_pos; v_diffuse=a_diffuse; v_specular=a_specular; v_uv=a_uv; }\n";
/* Stage-0 combine and alpha test: the same rules as runtime/sw_renderer.c. */
static const char *FRAGMENT =
    "#version 300 es\nprecision highp float; precision highp int;\n"
    "in vec4 v_diffuse; in vec4 v_specular; in vec2 v_uv;\n"
    "uniform sampler2D u_tex; uniform int u_has_tex; uniform ivec3 u_color; uniform ivec3 u_alpha; uniform vec4 u_tfactor;\n"
    "uniform int u_atest; uniform int u_afunc; uniform float u_aref;\n"
    "out vec4 o;\n"
    "vec4 sel(int a, vec4 tex){ int s=a&15; vec4 r = s==2?tex : s==3?u_tfactor : s==4?v_specular : v_diffuse;\n"
    "  if((a&0x20)!=0) r=vec4(r.a); if((a&0x10)!=0) r=vec4(1.0)-r; return r; }\n"
    "float comb(int op,float a,float b,float d){ if(op==1) return d; if(op==2) return a; if(op==3) return b; if(op==4) return a*b;\n"
    "  if(op==5) return min(1.0,2.0*a*b); if(op==6) return min(1.0,4.0*a*b); if(op==7) return min(1.0,a+b); if(op==8) return clamp(a+b-0.5,0.0,1.0); return a*b; }\n"
    "bool cmpf(int f,float a,float b){ if(f==1) return false; if(f==2) return a<b; if(f==3) return a==b; if(f==4) return a<=b;\n"
    "  if(f==5) return a>b; if(f==6) return a!=b; if(f==7) return a>=b; return true; }\n"
    "void main(){\n"
    "  vec4 tex = u_has_tex!=0 ? texture(u_tex, v_uv) : vec4(1.0);\n"
    "  int cop = u_color.x; if(u_has_tex==0 && cop!=1 && (u_color.y&15)==2) cop=3;\n"
    "  vec4 c1=sel(u_color.y,tex), c2=sel(u_color.z,tex);\n"
    "  vec3 rgb=vec3(comb(cop,c1.r,c2.r,v_diffuse.r), comb(cop,c1.g,c2.g,v_diffuse.g), comb(cop,c1.b,c2.b,v_diffuse.b));\n"
    "  vec4 a1=sel(u_alpha.y,tex), a2=sel(u_alpha.z,tex);\n"
    "  float al=comb(u_alpha.x,a1.a,a2.a,v_diffuse.a);\n"
    "  if(u_atest!=0 && !cmpf(u_afunc, al*255.0, u_aref)) discard;\n"
    "  o=vec4(rgb, al);\n"
    "}\n";

static GLuint compile(GLenum type, const char *src) {
    GLuint s = glCreateShader(type); glShaderSource(s, 1, &src, NULL); glCompileShader(s);
    GLint ok = 0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    return ok ? s : 0;
}
static int init_gl(mh_gles_renderer *r) {
    GLuint vs = compile(GL_VERTEX_SHADER, VERTEX), fs = compile(GL_FRAGMENT_SHADER, FRAGMENT);
    if (!vs || !fs) return 0;
    r->program = glCreateProgram(); glAttachShader(r->program, vs); glAttachShader(r->program, fs); glLinkProgram(r->program);
    GLint ok = 0; glGetProgramiv(r->program, GL_LINK_STATUS, &ok); if (!ok) return 0;
    r->u_tex = glGetUniformLocation(r->program, "u_tex"); r->u_has_tex = glGetUniformLocation(r->program, "u_has_tex");
    r->u_color = glGetUniformLocation(r->program, "u_color"); r->u_alpha = glGetUniformLocation(r->program, "u_alpha");
    r->u_tfactor = glGetUniformLocation(r->program, "u_tfactor"); r->u_atest = glGetUniformLocation(r->program, "u_atest");
    r->u_afunc = glGetUniformLocation(r->program, "u_afunc"); r->u_aref = glGetUniformLocation(r->program, "u_aref");
    glGenVertexArrays(1, &r->vao); glGenBuffers(1, &r->vbo);
    glBindVertexArray(r->vao); glBindBuffer(GL_ARRAY_BUFFER, r->vbo);
    const GLsizei stride = 14 * sizeof(float);
    glEnableVertexAttribArray(0); glVertexAttribPointer(0, 4, GL_FLOAT, GL_FALSE, stride, (void *)0);
    glEnableVertexAttribArray(1); glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, (void *)(4 * sizeof(float)));
    glEnableVertexAttribArray(2); glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, stride, (void *)(8 * sizeof(float)));
    glEnableVertexAttribArray(3); glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, stride, (void *)(12 * sizeof(float)));
    return 1;
}
static int ensure(mh_gles_renderer *r, mh_port *port) {
    uint32_t w, h;
    if (!mh_port_device_size(port, &w, &h) || !w || !h) return 0;
    if (!r->program && !init_gl(r)) return 0;
    if (w != r->width || h != r->height) {
        if (r->fbo) { glDeleteFramebuffers(1, &r->fbo); glDeleteRenderbuffers(1, &r->color); glDeleteRenderbuffers(1, &r->depth); }
        glGenFramebuffers(1, &r->fbo); glGenRenderbuffers(1, &r->color); glGenRenderbuffers(1, &r->depth);
        glBindRenderbuffer(GL_RENDERBUFFER, r->color); glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, (GLsizei)w, (GLsizei)h);
        glBindRenderbuffer(GL_RENDERBUFFER, r->depth); glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, (GLsizei)w, (GLsizei)h);
        glBindFramebuffer(GL_FRAMEBUFFER, r->fbo);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, r->color);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, r->depth);
        r->width = w; r->height = h;
        glClearColor(0, 0, 0, 1); glClearDepthf(1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, r->fbo); glViewport(0, 0, (GLsizei)w, (GLsizei)h);
    return 1;
}
static GLuint texture(mh_gles_renderer *r, const mh_port_texture_info *t) {
    gl_texture *e = NULL;
    for (unsigned i = 0; i < r->ntextures; i++)
        if (r->textures[i].memory == t->memory[0] && r->textures[i].format == t->format && r->textures[i].width == t->level_width[0] && r->textures[i].height == t->level_height[0]) e = &r->textures[i];
    if (e && e->version == t->version[0]) return e->id;
    if (!e) {
        if (r->ntextures == 512) { for (unsigned i = 0; i < 512; i++) glDeleteTextures(1, &r->textures[i].id); r->ntextures = 0; }
        e = &r->textures[r->ntextures++]; glGenTextures(1, &e->id);
        e->memory = t->memory[0]; e->format = t->format; e->width = t->level_width[0]; e->height = t->level_height[0];
    }
    uint8_t *rgba = mh_d3d_decode_texture(r->mem, t);
    glBindTexture(GL_TEXTURE_2D, e->id);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, (GLsizei)e->width, (GLsizei)e->height, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    free(rgba);
    e->version = t->version[0];
    return e->id;
}
static GLenum gl_compare(uint32_t f) {
    static const GLenum m[9] = {GL_ALWAYS, GL_NEVER, GL_LESS, GL_EQUAL, GL_LEQUAL, GL_GREATER, GL_NOTEQUAL, GL_GEQUAL, GL_ALWAYS};
    return f < 9 ? m[f] : GL_ALWAYS;
}
static GLenum gl_blend(uint32_t f) {
    switch (f) {
    case 1: return GL_ZERO; case 2: return GL_ONE; case 3: return GL_SRC_COLOR; case 4: return GL_ONE_MINUS_SRC_COLOR; case 5: return GL_SRC_ALPHA;
    case 6: return GL_ONE_MINUS_SRC_ALPHA; case 7: return GL_DST_ALPHA; case 8: return GL_ONE_MINUS_DST_ALPHA; case 9: return GL_DST_COLOR;
    case 10: return GL_ONE_MINUS_DST_COLOR; case 11: return GL_SRC_ALPHA_SATURATE; default: return GL_ONE;
    }
}
static GLint gl_address(uint32_t a) { return a == 2 ? GL_MIRRORED_REPEAT : a == 3 || a == 4 ? GL_CLAMP_TO_EDGE : GL_REPEAT; }

/* ------------------------------------------------------------------ device notifications */
static void on_clear(void *user, mh_port *port, uint32_t count, uint32_t rects, uint32_t flags, uint32_t color, float z, uint32_t stencil) {
    mh_gles_renderer *r = user;
    if (!ensure(r, port)) return;
    GLbitfield mask = 0;
    if (flags & 1) { glClearColor(((color >> 16) & 255) / 255.0f, ((color >> 8) & 255) / 255.0f, (color & 255) / 255.0f, (color >> 24) / 255.0f); mask |= GL_COLOR_BUFFER_BIT; }
    if (flags & 2) { glClearDepthf(z); glDepthMask(GL_TRUE); mask |= GL_DEPTH_BUFFER_BIT; }
    if (flags & 4) { glClearStencil((GLint)stencil); mask |= GL_STENCIL_BUFFER_BIT; }
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    if (!count) { glDisable(GL_SCISSOR_TEST); glClear(mask); return; }
    glEnable(GL_SCISSOR_TEST);
    for (uint32_t i = 0; i < count; i++) {
        uint32_t q[4]; if (!mh_mem_read(r->mem, rects + 16 * i, q, 16)) continue;
        int32_t x0 = (int32_t)q[0], y0 = (int32_t)q[1], x1 = (int32_t)q[2], y1 = (int32_t)q[3];
        /* Direct3D rectangles are top-down; the framebuffer rows are flipped (row 0 at the top in NDC). */
        glScissor(x0, (GLint)r->height - y1, x1 - x0, y1 - y0); glClear(mask);
    }
    glDisable(GL_SCISSOR_TEST);
}
static void on_draw(void *user, mh_port *port, const mh_port_draw_call *call) {
    mh_gles_renderer *r = user;
    if (!ensure(r, port)) return;
    mh_d3d_vertex *v = NULL; size_t n = mh_d3d_assemble(r->mem, port, call, &v);
    if (!n) { free(v); return; }
    mh_d3d_pixel_state s; mh_d3d_pixel_state_get(port, &s);
    float *buf = malloc(n * 14 * sizeof(float)); size_t out = 0;
    if (!buf) { free(v); return; }
    for (size_t i = 0; i + 2 < n; i += 3) {
        const mh_d3d_vertex *a = &v[i], *b = &v[i + 1], *c = &v[i + 2];
        float area = (b->x - a->x) * (c->y - a->y) - (b->y - a->y) * (c->x - a->x);
        if (area == 0 || (s.cull == 2 && area > 0) || (s.cull == 3 && area < 0)) continue;   /* as the reference renderer */
        for (int k = 0; k < 3; k++) {
            const mh_d3d_vertex *p = &v[i + (size_t)k]; float w = p->rhw != 0 ? 1.0f / p->rhw : 1.0f, *o = buf + 14 * out++;
            o[0] = ((p->x + 0.5f) / (float)r->width * 2.0f - 1.0f) * w;    /* Direct3D pixel centres are at integers */
            o[1] = (1.0f - (p->y + 0.5f) / (float)r->height * 2.0f) * w;
            o[2] = (p->z * 2.0f - 1.0f) * w; o[3] = w;
            memcpy(o + 4, p->diffuse, 16); memcpy(o + 8, p->specular, 16); o[12] = p->u; o[13] = p->v;
        }
    }
    free(v);
    if (!out) { free(buf); return; }
    glUseProgram(r->program); glBindVertexArray(r->vao); glBindBuffer(GL_ARRAY_BUFFER, r->vbo);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(out * 14 * sizeof(float)), buf, GL_STREAM_DRAW);
    free(buf);
    glActiveTexture(GL_TEXTURE0);
    if (s.has_texture) {
        glBindTexture(GL_TEXTURE_2D, texture(r, &s.texture));
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, s.mag_filter == 1 ? GL_NEAREST : GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, s.min_filter == 1 ? GL_NEAREST : GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, gl_address(s.address_u)); glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, gl_address(s.address_v));
    }
    glUniform1i(r->u_tex, 0); glUniform1i(r->u_has_tex, s.has_texture);
    glUniform3i(r->u_color, (GLint)s.colorop, (GLint)s.colorarg1, (GLint)s.colorarg2);
    glUniform3i(r->u_alpha, (GLint)s.alphaop, (GLint)s.alphaarg1, (GLint)s.alphaarg2);
    glUniform4f(r->u_tfactor, ((s.tfactor >> 16) & 255) / 255.0f, ((s.tfactor >> 8) & 255) / 255.0f, (s.tfactor & 255) / 255.0f, (s.tfactor >> 24) / 255.0f);
    glUniform1i(r->u_atest, s.alpha_test); glUniform1i(r->u_afunc, (GLint)s.alpha_func); glUniform1f(r->u_aref, (float)s.alpha_ref);
    if (s.blend) {
        static const GLenum ops[6] = {GL_FUNC_ADD, GL_FUNC_ADD, GL_FUNC_SUBTRACT, GL_FUNC_REVERSE_SUBTRACT, GL_MIN, GL_MAX};
        glEnable(GL_BLEND); glBlendFunc(gl_blend(s.src_blend), gl_blend(s.dst_blend)); glBlendEquation(s.blend_op < 6 ? ops[s.blend_op] : GL_FUNC_ADD);
    } else glDisable(GL_BLEND);
    if (s.z_test) { glEnable(GL_DEPTH_TEST); glDepthFunc(gl_compare(s.z_func)); } else glDisable(GL_DEPTH_TEST);
    glDepthMask(s.z_write ? GL_TRUE : GL_FALSE);
    glDisable(GL_CULL_FACE);
    glColorMask((s.color_write & 1) != 0, (s.color_write & 2) != 0, (s.color_write & 4) != 0, (s.color_write & 8) != 0);
    glDrawArrays(GL_TRIANGLES, 0, (GLsizei)out);
}
static void on_present(void *user, mh_port *port, unsigned frame) {
    mh_gles_renderer *r = user; (void)frame;
    if (!ensure(r, port)) return;
    int ww = 0, wh = 0; r->window_size(r->user, &ww, &wh);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0); glBindFramebuffer(GL_READ_FRAMEBUFFER, r->fbo);
    glViewport(0, 0, ww, wh); glDisable(GL_SCISSOR_TEST); glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    /* fit the back buffer to the window, aspect ratio kept */
    int dw = ww, dh = (int)((long)ww * r->height / r->width);
    if (dh > wh) { dh = wh; dw = (int)((long)wh * r->width / r->height); }
    int dx = (ww - dw) / 2, dy = (wh - dh) / 2;
    glBlitFramebuffer(0, 0, (GLint)r->width, (GLint)r->height, dx, dy, dx + dw, dy + dh, GL_COLOR_BUFFER_BIT, GL_LINEAR);
    r->swap(r->user);
    glBindFramebuffer(GL_FRAMEBUFFER, r->fbo);
}

mh_gles_renderer *mh_gles_renderer_create(mh_guest_memory *memory, void *user, void (*swap)(void *), void (*window_size)(void *, int *, int *)) {
    mh_gles_renderer *r = calloc(1, sizeof *r); if (!r) return NULL;
    r->mem = memory; r->user = user; r->swap = swap; r->window_size = window_size;
    return r;
}
void mh_gles_renderer_destroy(mh_gles_renderer *r) {
    if (!r) return;
    for (unsigned i = 0; i < r->ntextures; i++) glDeleteTextures(1, &r->textures[i].id);
    if (r->fbo) { glDeleteFramebuffers(1, &r->fbo); glDeleteRenderbuffers(1, &r->color); glDeleteRenderbuffers(1, &r->depth); }
    if (r->program) { glDeleteProgram(r->program); glDeleteBuffers(1, &r->vbo); glDeleteVertexArrays(1, &r->vao); }
    free(r);
}
void mh_gles_renderer_bind(mh_gles_renderer *r, mh_port_renderer *out) { memset(out, 0, sizeof *out); out->user = r; out->clear = on_clear; out->draw = on_draw; out->present = on_present; }
