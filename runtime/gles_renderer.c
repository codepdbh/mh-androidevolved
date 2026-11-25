/* OpenGL ES 3 backend for the port's Direct3D 8 device; see gles_renderer.h. */
#include "gles_renderer.h"
#include "d3d_common.h"
#include <GLES3/gl3.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t memory, format, width, height, version; GLuint id; } gl_texture;
/* A render target other than the back buffer (a texture level or a surface): its own framebuffer
 * with a colour texture, used directly when the game samples that texture. */
typedef struct { uint32_t memory, width, height; int fw, fh; GLuint tex, fbo, depth; } gl_target;
struct mh_gles_renderer {
    mh_guest_memory *mem; void *user; void (*swap)(void *); void (*window_size)(void *, int *, int *);
    uint32_t width, height;                 /* the device's back buffer (Direct3D units) */
    int fw, fh;                             /* the framebuffer: the back buffer at the internal resolution */
    float scale; int stretch;               /* options (mh_gles_renderer_set_options): 0 bars, 1 stretched, 2 widescreen */
    float kx;                               /* the current target's horizontal scale (widescreen back buffer: < 1) */
    int ww, wh;                             /* the window size, refreshed at every Present */
    GLuint fbo, color, depth;
    GLuint program, vbo, vao;
    GLint u_tex, u_has_tex, u_color, u_alpha, u_tfactor, u_atest, u_afunc, u_aref;
    gl_texture textures[512]; unsigned ntextures;
    gl_target targets[32]; unsigned ntargets;
    uint32_t cw, ch; int cfw, cfh;          /* the current target: Direct3D size and framebuffer size */
    GLint u_flip;
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
    "uniform int u_atest; uniform int u_afunc; uniform float u_aref; uniform int u_flip;\n"
    "out vec4 o;\n"
    "vec4 sel(int a, vec4 tex){ int s=a&15; vec4 r = s==2?tex : s==3?u_tfactor : s==4?v_specular : v_diffuse;\n"
    "  if((a&0x20)!=0) r=vec4(r.a); if((a&0x10)!=0) r=vec4(1.0)-r; return r; }\n"
    "float comb(int op,float a,float b,float d){ if(op==1) return d; if(op==2) return a; if(op==3) return b; if(op==4) return a*b;\n"
    "  if(op==5) return min(1.0,2.0*a*b); if(op==6) return min(1.0,4.0*a*b); if(op==7) return min(1.0,a+b); if(op==8) return clamp(a+b-0.5,0.0,1.0); return a*b; }\n"
    "bool cmpf(int f,float a,float b){ if(f==1) return false; if(f==2) return a<b; if(f==3) return a==b; if(f==4) return a<=b;\n"
    "  if(f==5) return a>b; if(f==6) return a!=b; if(f==7) return a>=b; return true; }\n"
    "void main(){\n"
    "  vec4 tex = u_has_tex!=0 ? texture(u_tex, u_flip!=0 ? vec2(v_uv.x, 1.0-v_uv.y) : v_uv) : vec4(1.0);\n"
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
    r->u_flip = glGetUniformLocation(r->program, "u_flip");
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
    /* Internal resolution: the back buffer scaled by `scale`, or (scale 0) to the window: its
     * height with the aspect kept, or the whole window when stretched. Geometry arrives in Direct3D
     * screen units and is mapped to clip space, so only the framebuffer size changes. */
    int fw, fh;
    if (r->ww < 1 || r->wh < 1) r->window_size(r->user, &r->ww, &r->wh);
    int ww = r->ww, wh = r->wh; if (ww < 1 || wh < 1) { ww = (int)w; wh = (int)h; }
    if (r->scale > 0) { fh = (int)(h * r->scale + 0.5f); fw = r->stretch == 2 ? (int)((float)fh * ww / wh + 0.5f) : (int)(w * r->scale + 0.5f); }
    else {
        if (r->stretch) { fw = ww; fh = wh; }
        else { float s = (float)ww / w < (float)wh / h ? (float)ww / w : (float)wh / h; fw = (int)(w * s + 0.5f); fh = (int)(h * s + 0.5f); }
    }
    if (fw > 4096) fw = 4096; if (fh > 4096) fh = 4096; if (fw < 1) fw = 1; if (fh < 1) fh = 1;
    if (w != r->width || h != r->height || fw != r->fw || fh != r->fh) {
        if (r->fbo) { glDeleteFramebuffers(1, &r->fbo); glDeleteRenderbuffers(1, &r->color); glDeleteRenderbuffers(1, &r->depth); }
        glGenFramebuffers(1, &r->fbo); glGenRenderbuffers(1, &r->color); glGenRenderbuffers(1, &r->depth);
        glBindRenderbuffer(GL_RENDERBUFFER, r->color); glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, fw, fh);
        glBindRenderbuffer(GL_RENDERBUFFER, r->depth); glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, fw, fh);
        glBindFramebuffer(GL_FRAMEBUFFER, r->fbo);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, r->color);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, r->depth);
        r->width = w; r->height = h; r->fw = fw; r->fh = fh;
        glClearColor(0, 0, 0, 1); glClearDepthf(1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
    /* the current render target: the back buffer, or a texture/surface with its own framebuffer
     * (rendered at the same internal scale; rows bottom-up, so it is sampled flipped) */
    uint32_t mem = 0, tw = 0, th = 0, tf = 0;
    if (mh_port_render_target(port, &mem, &tw, &th, &tf) && tw && th) {
        gl_target *t = NULL;
        for (unsigned i = 0; i < r->ntargets; i++) if (r->targets[i].memory == mem && r->targets[i].width == tw && r->targets[i].height == th) t = &r->targets[i];
        if (!t) {
            if (r->ntargets == 32) { glDeleteTextures(1, &r->targets[0].tex); glDeleteFramebuffers(1, &r->targets[0].fbo); glDeleteRenderbuffers(1, &r->targets[0].depth);
                                     memmove(r->targets, r->targets + 1, 31 * sizeof *r->targets); r->ntargets--; }
            t = &r->targets[r->ntargets++]; memset(t, 0, sizeof *t);
            t->memory = mem; t->width = tw; t->height = th;
            t->fw = (int)(tw * (float)r->fh / h + 0.5f); t->fh = (int)(th * (float)r->fh / h + 0.5f);
            if (t->fw < 1) t->fw = 1; if (t->fh < 1) t->fh = 1; if (t->fw > 4096) t->fw = 4096; if (t->fh > 4096) t->fh = 4096;
            glGenTextures(1, &t->tex); glBindTexture(GL_TEXTURE_2D, t->tex);
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, t->fw, t->fh, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
            glGenRenderbuffers(1, &t->depth); glBindRenderbuffer(GL_RENDERBUFFER, t->depth); glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, t->fw, t->fh);
            glGenFramebuffers(1, &t->fbo); glBindFramebuffer(GL_FRAMEBUFFER, t->fbo);
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t->tex, 0);
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, t->depth);
            glClearColor(0, 0, 0, 0); glClearDepthf(1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        }
        glBindFramebuffer(GL_FRAMEBUFFER, t->fbo); glViewport(0, 0, t->fw, t->fh);
        r->cw = tw; r->ch = th; r->cfw = t->fw; r->cfh = t->fh; r->kx = 1;
        return 1;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, r->fbo); glViewport(0, 0, r->fw, r->fh);
    r->cw = w; r->ch = h; r->cfw = r->fw; r->cfh = r->fh;
    r->kx = r->stretch == 2 ? ((float)w / h) / ((float)r->fw / r->fh) : 1;
    return 1;
}
static const gl_target *target_for(const mh_gles_renderer *r, uint32_t memory) {
    if (!memory) return NULL;
    for (unsigned i = 0; i < r->ntargets; i++) if (r->targets[i].memory == memory) return &r->targets[i];
    return NULL;
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
        float sx = (float)r->cfw / r->cw, sy = (float)r->cfh / r->ch, mid = r->cfw * 0.5f;
        GLint left = (GLint)(mid + (x0 * sx - mid) * r->kx + 0.5f), right = (GLint)(mid + (x1 * sx - mid) * r->kx + 0.5f), top = (GLint)(y0 * sy + 0.5f), bottom = (GLint)(y1 * sy + 0.5f);
        glScissor(left, r->cfh - bottom, right - left, bottom - top); glClear(mask);
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
    /* clip space -> Direct3D viewport -> GL clip space (linear in the clip coordinates) */
    uint32_t vp[6]; mh_port_viewport(port, vp); float minz, maxz; memcpy(&minz, &vp[4], 4); memcpy(&maxz, &vp[5], 4);
    const float ax = ((float)vp[0] + vp[2] * 0.5f + 0.5f) / (float)r->cw * 2.0f - 1.0f, bx = (float)vp[2] / (float)r->cw;
    const float ay = 1.0f - ((float)vp[1] + vp[3] * 0.5f + 0.5f) / (float)r->ch * 2.0f, by = (float)vp[3] / (float)r->ch;
    for (size_t i = 0; i + 2 < n; i += 3) {
        const mh_d3d_vertex *a = &v[i], *b = &v[i + 1], *c = &v[i + 2];
        float area = (b->x - a->x) * (c->y - a->y) - (b->y - a->y) * (c->x - a->x);
        if (a->has_clip) {   /* the screen-space orientation (y down) is -det[x y w] */
            const float *p = a->clip, *q = b->clip, *t = c->clip;
            area = -(p[0] * (q[1] * t[3] - q[3] * t[1]) - p[1] * (q[0] * t[3] - q[3] * t[0]) + p[3] * (q[0] * t[1] - q[1] * t[0]));
        }
        if (area == 0 || (s.cull == 2 && area > 0) || (s.cull == 3 && area < 0)) continue;   /* as the reference renderer */
        for (int k = 0; k < 3; k++) {
            const mh_d3d_vertex *p = &v[i + (size_t)k]; float w = p->rhw != 0 ? 1.0f / p->rhw : 1.0f, *o = buf + 14 * out++;
            if (p->has_clip) {
                w = p->clip[3];
                o[0] = (ax * w + bx * p->clip[0]) * r->kx; o[1] = ay * w + by * p->clip[1];
                o[2] = (2.0f * minz - 1.0f) * w + 2.0f * (maxz - minz) * p->clip[2]; o[3] = w;
            } else {
                o[0] = ((p->x + 0.5f) / (float)r->cw * 2.0f - 1.0f) * w * r->kx;    /* Direct3D pixel centres are at integers */
                o[1] = (1.0f - (p->y + 0.5f) / (float)r->ch * 2.0f) * w;
                o[2] = (p->z * 2.0f - 1.0f) * w; o[3] = w;
            }
            memcpy(o + 4, p->diffuse, 16); memcpy(o + 8, p->specular, 16); o[12] = p->u; o[13] = p->v;
        }
    }
    free(v);
    if (!out) { free(buf); return; }
    glUseProgram(r->program); glBindVertexArray(r->vao); glBindBuffer(GL_ARRAY_BUFFER, r->vbo);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(out * 14 * sizeof(float)), buf, GL_STREAM_DRAW);
    free(buf);
    glActiveTexture(GL_TEXTURE0);
    const gl_target *rt = s.has_texture ? target_for(r, s.texture.memory[0]) : NULL;
    glUniform1i(r->u_flip, rt != NULL);
    if (s.has_texture) {
        glBindTexture(GL_TEXTURE_2D, rt ? rt->tex : texture(r, &s.texture));
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
    int ww = 0, wh = 0; r->window_size(r->user, &ww, &wh); r->ww = ww; r->wh = wh;
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0); glBindFramebuffer(GL_READ_FRAMEBUFFER, r->fbo);
    glViewport(0, 0, ww, wh); glDisable(GL_SCISSOR_TEST); glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    /* fit the back buffer to the window: aspect ratio kept (bars), or stretched over the whole window */
    int dw = ww, dh = wh;
    if (r->stretch == 2) { dh = (int)((long)ww * r->fh / r->fw); if (dh > wh) { dh = wh; dw = (int)((long)wh * r->fw / r->fh); } }
    else if (!r->stretch) { dh = (int)((long)ww * r->height / r->width); if (dh > wh) { dh = wh; dw = (int)((long)wh * r->width / r->height); } }
    int dx = (ww - dw) / 2, dy = (wh - dh) / 2;
    glBlitFramebuffer(0, 0, r->fw, r->fh, dx, dy, dx + dw, dy + dh, GL_COLOR_BUFFER_BIT, r->fw == dw && r->fh == dh ? GL_NEAREST : GL_LINEAR);
    r->swap(r->user);
    glBindFramebuffer(GL_FRAMEBUFFER, r->fbo);
}

mh_gles_renderer *mh_gles_renderer_create(mh_guest_memory *memory, void *user, void (*swap)(void *), void (*window_size)(void *, int *, int *)) {
    mh_gles_renderer *r = calloc(1, sizeof *r); if (!r) return NULL;
    r->mem = memory; r->user = user; r->swap = swap; r->window_size = window_size; r->scale = 1; r->kx = 1; mh_d3d_keep_clip = 1;
    return r;
}
void mh_gles_renderer_destroy(mh_gles_renderer *r) {
    if (!r) return;
    for (unsigned i = 0; i < r->ntextures; i++) glDeleteTextures(1, &r->textures[i].id);
    if (r->fbo) { glDeleteFramebuffers(1, &r->fbo); glDeleteRenderbuffers(1, &r->color); glDeleteRenderbuffers(1, &r->depth); }
    if (r->program) { glDeleteProgram(r->program); glDeleteBuffers(1, &r->vbo); glDeleteVertexArrays(1, &r->vao); }
    free(r);
}
void mh_gles_renderer_set_options(mh_gles_renderer *r, float scale, int stretch) { r->scale = scale < 0 ? 0 : scale > 6 ? 6 : scale; r->stretch = stretch < 0 || stretch > 2 ? 0 : stretch; mh_d3d_keep_clip = 1; }
void mh_gles_renderer_bind(mh_gles_renderer *r, mh_port_renderer *out) { memset(out, 0, sizeof *out); out->user = r; out->clear = on_clear; out->draw = on_draw; out->present = on_present; }
