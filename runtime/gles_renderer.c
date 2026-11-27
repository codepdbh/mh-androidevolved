/* OpenGL ES 3 backend for the port's Direct3D 8 device; see gles_renderer.h. */
#include "gles_renderer.h"
#include "d3d_common.h"
#include <GLES3/gl3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t memory, format, width, height, version; GLuint id; } gl_texture;
/* A render target other than the back buffer (a texture level or a surface): its own framebuffer
 * with a colour texture, used directly when the game samples that texture. */
typedef struct { uint32_t memory, width, height; int fw, fh; GLuint tex, fbo, depth; } gl_target;
/* A guest vertex or index buffer kept on the GPU until its contents version changes. */
typedef struct { uint32_t memory, length, version; GLuint id; } gl_buffer;
/* Uniform locations of the shared fragment stage. */
typedef struct { GLint tex, has_tex, color, alpha, tfactor, atest, afunc, aref, flip, fog, fogcolor, fogp, tex1, has_tex1, flip1, s1color, s1alpha; } frag_loc;
struct mh_gles_renderer {
    mh_guest_memory *mem; void *user; void (*swap)(void *); void (*window_size)(void *, int *, int *);
    uint32_t width, height;                 /* the device's back buffer (Direct3D units) */
    int fw, fh;                             /* the framebuffer: the back buffer at the internal resolution */
    float scale; int stretch;               /* options (mh_gles_renderer_set_options): 0 bars, 1 stretched, 2 widescreen */
    float kx;                               /* the current target's horizontal scale (widescreen back buffer: < 1) */
    int ww, wh;                             /* the window size, refreshed at every Present */
    GLuint fbo, color, depth;
    GLuint program, vbo, vao;
    /* Batch: consecutive draws with the same pixel state and target are sent as one glDrawArrays
     * (the camcorder scanlines are 240 one-line draws a frame; one GL draw each cost ~0.2 ms). */
    float *pend; size_t pend_n, pend_cap; mh_d3d_pixel_state pend_state; GLuint pend_fbo, cur_fbo; int pend_vw, pend_vh, cur_vw, cur_vh;
    frag_loc f2d, f3d;
    gl_texture textures[512]; unsigned ntextures;
    gl_target targets[32]; unsigned ntargets;
    uint32_t cw, ch; int cfw, cfh;          /* the current target: Direct3D size and framebuffer size */
    /* Untransformed triangles on the GPU: the game's vertex and index buffers as they are, with
     * the world-view-projection and the fixed-function lighting in the vertex shader. */
    GLuint program3d, vao3d, vbo_up, ibo_up; int gpu3d;
    GLint u_wvp, u_world, u_vp, u_zk, u_light, u_nlights, u_lights, u_mat, u_ambient, u_csel;
    GLint u_wv, u_tm0, u_tm1, u_tci, u_ttff;
    gl_buffer buffers[2048]; unsigned nbuffers;
};

static const char *VERTEX =
    "#version 300 es\n"
    "layout(location=0) in vec4 a_pos; layout(location=1) in vec4 a_diffuse; layout(location=2) in vec4 a_specular; layout(location=3) in vec2 a_uv;\n"
    "out vec4 v_diffuse; out vec4 v_specular; out vec2 v_uv; out vec2 v_uv1;\n"
    "void main(){ gl_Position=a_pos; v_diffuse=a_diffuse; v_specular=a_specular; v_uv=a_uv; v_uv1=a_uv; }\n";
/* Untransformed vertices: as mh_d3d_assemble (runtime/d3d_common.c) computes them on the CPU, with
 * the clip space mapped like the 2D path (u_vp: ax bx ay by; u_zk: MinZ MaxZ kx). Colours arrive as
 * D3DCOLOR bytes (B G R A). Lights: 6 vec4 each (type range att0 att1 | att2 | diffuse | ambient |
 * position | direction); u_csel: the colour source of diffuse/ambient/emissive (0 material, 1 vertex
 * diffuse, 2 vertex specular). */
static const char *VERTEX3D =
    "#version 300 es\n"
    "layout(location=0) in vec3 a_pos; layout(location=1) in vec3 a_normal; layout(location=2) in vec4 a_diffuse; layout(location=3) in vec4 a_specular; layout(location=4) in vec2 a_uv; layout(location=5) in vec2 a_uv1;\n"
    "uniform mat4 u_wv; uniform mat4 u_tm0; uniform mat4 u_tm1; uniform ivec2 u_tci; uniform ivec2 u_ttff;\n"
    "uniform mat4 u_wvp; uniform mat4 u_world; uniform vec4 u_vp; uniform vec3 u_zk;\n"
    "uniform int u_light; uniform int u_nlights; uniform vec4 u_lights[48]; uniform vec4 u_mat[4]; uniform vec4 u_ambient; uniform ivec3 u_csel;\n"
    "out vec4 v_diffuse; out vec4 v_specular; out vec2 v_uv; out vec2 v_uv1;\n"
    "vec2 tcoord(int mode, vec2 src, mat4 tm, int ttff, vec3 cp, vec3 cn){\n"
    "  vec4 i4 = mode==1 ? vec4(cn,1.0) : mode==2 ? vec4(cp,1.0) : mode==3 ? vec4(reflect(normalize(cp),cn),1.0) : vec4(src,1.0,0.0);\n"
    "  int cnt=ttff&255; if(cnt==0) return i4.xy;\n"
    "  vec4 t=tm*i4; if((ttff&256)!=0){ float d = cnt==2 ? t.y : cnt==3 ? t.z : t.w; return d!=0.0 ? t.xy/d : t.xy; } return t.xy; }\n"
    "vec4 pick(int s, vec4 m, vec4 vc, vec4 vs){ return s==1?vc : s==2?vs : m; }\n"
    "void main(){\n"
    "  vec4 c=u_wvp*vec4(a_pos,1.0); float w=c.w;\n"
    "  gl_Position=vec4((u_vp.x*w+u_vp.y*c.x)*u_zk.z, u_vp.z*w+u_vp.w*c.y, (2.0*u_zk.x-1.0)*w+2.0*(u_zk.y-u_zk.x)*c.z, w);\n"
    "  vec4 dif=a_diffuse.zyxw, spe=a_specular.zyxw; v_specular=spe;\n"
    "  if(u_tci.x!=0 || u_tci.y!=0 || u_ttff.x!=0 || u_ttff.y!=0){\n"
    "    vec3 cp=(u_wv*vec4(a_pos,1.0)).xyz, cn=normalize((u_wv*vec4(a_normal,0.0)).xyz+vec3(0.0,0.0,1e-20));\n"
    "    v_uv=tcoord(u_tci.x,a_uv,u_tm0,u_ttff.x,cp,cn); v_uv1=tcoord(u_tci.y,a_uv1,u_tm1,u_ttff.y,cp,cn);\n"
    "  } else { v_uv=a_uv; v_uv1=a_uv1; }\n"
    "  if(u_light==0){ v_diffuse=dif; return; }\n"
    "  vec4 cd=pick(u_csel.x,u_mat[0],dif,spe), ca=pick(u_csel.y,u_mat[1],dif,spe), ce=pick(u_csel.z,u_mat[3],dif,spe);\n"
    "  vec3 wp=(u_world*vec4(a_pos,1.0)).xyz, wn=(u_world*vec4(a_normal,0.0)).xyz; float nl=length(wn); if(nl>0.0) wn/=nl;\n"
    "  vec3 col=ce.rgb+u_ambient.rgb*ca.rgb;\n"
    "  for(int i=0;i<8;i++){ if(i>=u_nlights) break;\n"
    "    vec4 p0=u_lights[6*i]; vec3 dir; float att=1.0;\n"
    "    if(p0.x==3.0) dir=-u_lights[6*i+5].xyz;\n"
    "    else { dir=u_lights[6*i+4].xyz-wp; float d=length(dir); if(p0.y>0.0 && d>p0.y) continue;\n"
    "           float den=p0.z+p0.w*d+u_lights[6*i+1].x*d*d; att=den>0.0?1.0/den:1.0; if(d>0.0) dir/=d; }\n"
    "    float dl=length(dir); if(dl>0.0) dir/=dl;\n"
    "    float k=max(dot(wn,dir),0.0);\n"
    "    col+=att*(u_lights[6*i+3].rgb*ca.rgb+u_lights[6*i+2].rgb*cd.rgb*k); }\n"
    "  v_diffuse=vec4(min(col,vec3(1.0)), clamp(cd.a,0.0,1.0));\n"
    "}\n";
/* Stage-0 combine and alpha test: the same rules as runtime/sw_renderer.c. */
static const char *FRAGMENT =
    "#version 300 es\nprecision highp float; precision highp int;\n"
    "in vec4 v_diffuse; in vec4 v_specular; in vec2 v_uv; in vec2 v_uv1;\n"
    "uniform sampler2D u_tex; uniform int u_has_tex; uniform ivec3 u_color; uniform ivec3 u_alpha; uniform vec4 u_tfactor;\n"
    "uniform sampler2D u_tex1; uniform int u_has_tex1; uniform int u_flip1; uniform ivec3 u_s1color; uniform ivec3 u_s1alpha;\n"
    "uniform int u_atest; uniform int u_afunc; uniform float u_aref; uniform int u_flip;\n"
    "uniform int u_fog; uniform vec3 u_fogcolor; uniform vec3 u_fogp;\n"
    "out vec4 o;\n"
    "vec4 sel(int a, vec4 tex, vec4 cur){ int s=a&15; vec4 r = s==2?tex : s==3?u_tfactor : s==4?v_specular : s==1?cur : v_diffuse;\n"
    "  if((a&0x20)!=0) r=vec4(r.a); if((a&0x10)!=0) r=vec4(1.0)-r; return r; }\n"
    "vec4 comb(int op, vec4 a, vec4 b, vec4 pass, vec4 tex, vec4 cur){\n"
    "  if(op==1) return pass; if(op==2) return a; if(op==3) return b; if(op==4) return a*b;\n"
    "  if(op==5) return min(vec4(1.0),2.0*a*b); if(op==6) return min(vec4(1.0),4.0*a*b); if(op==7) return min(vec4(1.0),a+b);\n"
    "  if(op==8) return clamp(a+b-0.5,0.0,1.0); if(op==9) return clamp(2.0*(a+b-0.5),0.0,1.0); if(op==10) return clamp(a-b,0.0,1.0);\n"
    "  if(op==11) return clamp(a+b-a*b,0.0,1.0); if(op==12) return mix(b,a,v_diffuse.a); if(op==13) return mix(b,a,tex.a);\n"
    "  if(op==14) return mix(b,a,u_tfactor.a); if(op==15) return clamp(a+b*(1.0-tex.a),0.0,1.0); if(op==16) return mix(b,a,cur.a); return a*b; }\n"
    "bool cmpf(int f,float a,float b){ if(f==1) return false; if(f==2) return a<b; if(f==3) return a==b; if(f==4) return a<=b;\n"
    "  if(f==5) return a>b; if(f==6) return a!=b; if(f==7) return a>=b; return true; }\n"
    "void main(){\n"
    "  vec4 tex = u_has_tex!=0 ? texture(u_tex, u_flip!=0 ? vec2(v_uv.x, 1.0-v_uv.y) : v_uv) : vec4(1.0);\n"
    "  int cop = u_color.x; if(u_has_tex==0 && cop!=1 && (u_color.y&15)==2) cop=3;\n"
    "  vec3 rgb=comb(cop, sel(u_color.y,tex,v_diffuse), sel(u_color.z,tex,v_diffuse), v_diffuse, tex, v_diffuse).rgb;\n"
    "  float al=comb(u_alpha.x, sel(u_alpha.y,tex,v_diffuse), sel(u_alpha.z,tex,v_diffuse), v_diffuse, tex, v_diffuse).a;\n"
    "  if(u_s1color.x>1){ vec4 cur=vec4(rgb,al);\n"
    "    vec4 t1 = u_has_tex1!=0 ? texture(u_tex1, u_flip1!=0 ? vec2(v_uv1.x, 1.0-v_uv1.y) : v_uv1) : vec4(1.0);\n"
    "    rgb=comb(u_s1color.x, sel(u_s1color.y,t1,cur), sel(u_s1color.z,t1,cur), cur, t1, cur).rgb;\n"
    "    if(u_s1alpha.x>1) al=comb(u_s1alpha.x, sel(u_s1alpha.y,t1,cur), sel(u_s1alpha.z,t1,cur), cur, t1, cur).a; }\n"
    "  if(u_atest!=0 && !cmpf(u_afunc, al*255.0, u_aref)) discard;\n"
    /* fog (see mh_d3d_pixel_state): linear fog with an end <= 1 is on the device depth, the rest on the eye depth (w) */
    "  if(u_fog!=0){ float f;\n"
    "    if(u_fog==4) f=v_specular.a;\n"
    "    else { float d = (u_fog==3 && u_fogp.y<=1.0) ? gl_FragCoord.z : 1.0/gl_FragCoord.w;\n"
    "      f = u_fog==3 ? (u_fogp.y-d)/max(u_fogp.y-u_fogp.x,1e-6) : u_fog==1 ? exp(-u_fogp.z*d) : exp(-(u_fogp.z*d)*(u_fogp.z*d)); }\n"
    "    rgb=mix(u_fogcolor, rgb, clamp(f,0.0,1.0)); }\n"
    "  o=vec4(rgb, al);\n"
    "}\n";

static void frag_locs(GLuint p, frag_loc *L) {
    L->tex = glGetUniformLocation(p, "u_tex"); L->has_tex = glGetUniformLocation(p, "u_has_tex");
    L->color = glGetUniformLocation(p, "u_color"); L->alpha = glGetUniformLocation(p, "u_alpha");
    L->tfactor = glGetUniformLocation(p, "u_tfactor"); L->atest = glGetUniformLocation(p, "u_atest");
    L->afunc = glGetUniformLocation(p, "u_afunc"); L->aref = glGetUniformLocation(p, "u_aref"); L->flip = glGetUniformLocation(p, "u_flip");
    L->fog = glGetUniformLocation(p, "u_fog"); L->fogcolor = glGetUniformLocation(p, "u_fogcolor"); L->fogp = glGetUniformLocation(p, "u_fogp");
    L->tex1 = glGetUniformLocation(p, "u_tex1"); L->has_tex1 = glGetUniformLocation(p, "u_has_tex1"); L->flip1 = glGetUniformLocation(p, "u_flip1");
    L->s1color = glGetUniformLocation(p, "u_s1color"); L->s1alpha = glGetUniformLocation(p, "u_s1alpha");
}
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
    frag_locs(r->program, &r->f2d);
    /* the GPU path is optional: without it every draw takes the CPU path */
    GLuint vs3 = compile(GL_VERTEX_SHADER, VERTEX3D);
    if (vs3) {
        r->program3d = glCreateProgram(); glAttachShader(r->program3d, vs3); glAttachShader(r->program3d, fs); glLinkProgram(r->program3d);
        ok = 0; glGetProgramiv(r->program3d, GL_LINK_STATUS, &ok);
        if (ok) {
            frag_locs(r->program3d, &r->f3d);
            r->u_wvp = glGetUniformLocation(r->program3d, "u_wvp"); r->u_world = glGetUniformLocation(r->program3d, "u_world");
            r->u_vp = glGetUniformLocation(r->program3d, "u_vp"); r->u_zk = glGetUniformLocation(r->program3d, "u_zk");
            r->u_light = glGetUniformLocation(r->program3d, "u_light"); r->u_nlights = glGetUniformLocation(r->program3d, "u_nlights");
            r->u_lights = glGetUniformLocation(r->program3d, "u_lights"); r->u_mat = glGetUniformLocation(r->program3d, "u_mat");
            r->u_ambient = glGetUniformLocation(r->program3d, "u_ambient"); r->u_csel = glGetUniformLocation(r->program3d, "u_csel");
            r->u_wv = glGetUniformLocation(r->program3d, "u_wv"); r->u_tm0 = glGetUniformLocation(r->program3d, "u_tm0"); r->u_tm1 = glGetUniformLocation(r->program3d, "u_tm1");
            r->u_tci = glGetUniformLocation(r->program3d, "u_tci"); r->u_ttff = glGetUniformLocation(r->program3d, "u_ttff");
            glGenVertexArrays(1, &r->vao3d); glGenBuffers(1, &r->vbo_up); glGenBuffers(1, &r->ibo_up);
            r->gpu3d = 1;
        }
    }
    glGenVertexArrays(1, &r->vao); glGenBuffers(1, &r->vbo);
    glBindVertexArray(r->vao); glBindBuffer(GL_ARRAY_BUFFER, r->vbo);
    const GLsizei stride = 14 * sizeof(float);
    glEnableVertexAttribArray(0); glVertexAttribPointer(0, 4, GL_FLOAT, GL_FALSE, stride, (void *)0);
    glEnableVertexAttribArray(1); glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, (void *)(4 * sizeof(float)));
    glEnableVertexAttribArray(2); glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, stride, (void *)(8 * sizeof(float)));
    glEnableVertexAttribArray(3); glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, stride, (void *)(12 * sizeof(float)));
    return 1;
}
static void flush(mh_gles_renderer *r);
/* Optional timing (the app defines MH_GLES_PROFILE to a function returning nanoseconds):
 * [0] assembling vertices, [1] building GL vertices, [2] flushing batches, [3] batches flushed. */
uint64_t mh_gles_prof[4];
#ifdef MH_GLES_PROFILE
#define PROF_NOW() MH_GLES_PROFILE()
#else
#define PROF_NOW() 0
#endif
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
        flush(r);   /* the batch may target the framebuffer about to be replaced */
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
            if (r->ntargets == 32) { flush(r); glDeleteTextures(1, &r->targets[0].tex); glDeleteFramebuffers(1, &r->targets[0].fbo); glDeleteRenderbuffers(1, &r->targets[0].depth);
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
        glBindFramebuffer(GL_FRAMEBUFFER, t->fbo); glViewport(0, 0, t->fw, t->fh); r->cur_fbo = t->fbo; r->cur_vw = t->fw; r->cur_vh = t->fh;
        r->cw = tw; r->ch = th; r->cfw = t->fw; r->cfh = t->fh; r->kx = 1;
        return 1;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, r->fbo); glViewport(0, 0, r->fw, r->fh); r->cur_fbo = r->fbo; r->cur_vw = r->fw; r->cur_vh = r->fh;
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
    mh_gles_renderer *r = user; flush(r);
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
/* The fixed-function pixel state for the next draw: texture, combine, fog, alpha test, blending,
 * depth, culling (gl_cull: by GL, for the GPU path; the CPU path culls itself) and colour mask. */
static void apply_state(mh_gles_renderer *r, const frag_loc *L, const mh_d3d_pixel_state *s, int gl_cull) {
    glActiveTexture(GL_TEXTURE0);
    const gl_target *rt = s->has_texture ? target_for(r, s->texture.memory[0]) : NULL;
    glUniform1i(L->flip, rt != NULL);
    if (s->has_texture) {
        glBindTexture(GL_TEXTURE_2D, rt ? rt->tex : texture(r, &s->texture));
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, s->mag_filter == 1 ? GL_NEAREST : GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, s->min_filter == 1 ? GL_NEAREST : GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, gl_address(s->address_u)); glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, gl_address(s->address_v));
    }
    glUniform1i(L->tex, 0); glUniform1i(L->has_tex, s->has_texture);
    glUniform3i(L->color, (GLint)s->colorop, (GLint)s->colorarg1, (GLint)s->colorarg2);
    glUniform3i(L->alpha, (GLint)s->alphaop, (GLint)s->alphaarg1, (GLint)s->alphaarg2);
    glUniform4f(L->tfactor, ((s->tfactor >> 16) & 255) / 255.0f, ((s->tfactor >> 8) & 255) / 255.0f, (s->tfactor & 255) / 255.0f, (s->tfactor >> 24) / 255.0f);
    glUniform1i(L->fog, (GLint)s->fog_mode); glUniform3f(L->fogcolor, ((s->fog_color >> 16) & 255) / 255.0f, ((s->fog_color >> 8) & 255) / 255.0f, (s->fog_color & 255) / 255.0f);
    glUniform3f(L->fogp, s->fog_start, s->fog_end, s->fog_density);
    glUniform1i(L->atest, s->alpha_test); glUniform1i(L->afunc, (GLint)s->alpha_func); glUniform1f(L->aref, (float)s->alpha_ref);
    if (s->blend) {
        static const GLenum ops[6] = {GL_FUNC_ADD, GL_FUNC_ADD, GL_FUNC_SUBTRACT, GL_FUNC_REVERSE_SUBTRACT, GL_MIN, GL_MAX};
        glEnable(GL_BLEND); glBlendFunc(gl_blend(s->src_blend), gl_blend(s->dst_blend)); glBlendEquation(s->blend_op < 6 ? ops[s->blend_op] : GL_FUNC_ADD);
    } else glDisable(GL_BLEND);
    if (s->z_test) { glEnable(GL_DEPTH_TEST); glDepthFunc(gl_compare(s->z_func)); } else glDisable(GL_DEPTH_TEST);
    glDepthMask(s->z_write ? GL_TRUE : GL_FALSE);
    /* Direct3D culls in screen space with y down; GL clip space has y up, so its winding is reversed:
     * D3DCULL_CW (2) removes GL back faces and D3DCULL_CCW (3) GL front faces (glFrontFace CCW). */
    if (gl_cull && (s->cull == 2 || s->cull == 3)) { glEnable(GL_CULL_FACE); glFrontFace(GL_CCW); glCullFace(s->cull == 2 ? GL_BACK : GL_FRONT); }
    else glDisable(GL_CULL_FACE);
    glColorMask((s->color_write & 1) != 0, (s->color_write & 2) != 0, (s->color_write & 4) != 0, (s->color_write & 8) != 0);
}
/* Sends the pending batch to the framebuffer it was recorded for. */
static void flush(mh_gles_renderer *r) {
    if (!r->pend_n) return;
    uint64_t prof_t0 = PROF_NOW(); mh_gles_prof[3]++;
    const mh_d3d_pixel_state s = r->pend_state;
    glBindFramebuffer(GL_FRAMEBUFFER, r->pend_fbo); glViewport(0, 0, r->pend_vw, r->pend_vh);
    glUseProgram(r->program); glBindVertexArray(r->vao); glBindBuffer(GL_ARRAY_BUFFER, r->vbo);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(r->pend_n * 14 * sizeof(float)), r->pend, GL_STREAM_DRAW);
    apply_state(r, &r->f2d, &s, 0);
    glDrawArrays(GL_TRIANGLES, 0, (GLsizei)r->pend_n);
    r->pend_n = 0; mh_gles_prof[2] += PROF_NOW() - prof_t0;
    glBindFramebuffer(GL_FRAMEBUFFER, r->cur_fbo); glViewport(0, 0, r->cur_vw, r->cur_vh);
}
/* A guest buffer on the GPU, uploaded again when its contents version changes (0: unknown, always). */
static GLuint gpu_buffer(mh_gles_renderer *r, GLenum target, uint32_t memory, uint32_t length, uint32_t version) {
    gl_buffer *e = NULL;
    for (unsigned i = 0; i < r->nbuffers; i++) if (r->buffers[i].memory == memory && r->buffers[i].length == length) { e = &r->buffers[i]; break; }
    if (e && version && e->version == version) { glBindBuffer(target, e->id); return e->id; }
    const void *data = mh_mem_span(r->mem, memory, length);
    if (!data) return 0;
    if (!e) {
        if (r->nbuffers == 2048) { for (unsigned i = 0; i < r->nbuffers; i++) glDeleteBuffers(1, &r->buffers[i].id); r->nbuffers = 0; }
        e = &r->buffers[r->nbuffers++]; e->memory = memory; e->length = length; glGenBuffers(1, &e->id);
    }
    glBindBuffer(target, e->id); glBufferData(target, (GLsizeiptr)length, data, GL_STATIC_DRAW);
    e->version = version;
    return e->id;
}
static void mat_mul(const float *a, const float *b, float *o) {   /* row vectors: o = a * b */
    for (int i = 0; i < 4; i++) for (int j = 0; j < 4; j++) o[4 * i + j] = a[4 * i] * b[j] + a[4 * i + 1] * b[4 + j] + a[4 * i + 2] * b[8 + j] + a[4 * i + 3] * b[12 + j];
}
static float u2f(uint32_t u) { float f; memcpy(&f, &u, 4); return f; }
/* Texture stage 1 (the GPU path): its texture on unit 1 and its colour and alpha operations. */
static void apply_stage1(mh_gles_renderer *r, mh_port *port, const frag_loc *L) {
    uint32_t cop = mh_port_stage_state(port, 1, 1);
    glUniform3i(L->s1color, (GLint)cop, (GLint)mh_port_stage_state(port, 1, 2), (GLint)mh_port_stage_state(port, 1, 3));
    glUniform3i(L->s1alpha, (GLint)mh_port_stage_state(port, 1, 4), (GLint)mh_port_stage_state(port, 1, 5), (GLint)mh_port_stage_state(port, 1, 6));
    mh_port_texture_info t; int has = cop > 1 && mh_port_texture(port, 1, &t);
    glUniform1i(L->has_tex1, has); glUniform1i(L->tex1, 1);
    const gl_target *rt = has ? target_for(r, t.memory[0]) : NULL; glUniform1i(L->flip1, rt != NULL);
    if (has) {
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, rt ? rt->tex : texture(r, &t));
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, mh_port_stage_state(port, 1, 16) == 1 ? GL_NEAREST : GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, mh_port_stage_state(port, 1, 17) == 1 ? GL_NEAREST : GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, gl_address(mh_port_stage_state(port, 1, 13)));
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, gl_address(mh_port_stage_state(port, 1, 14)));
        glActiveTexture(GL_TEXTURE0);
    }
}
/* Untransformed triangles on the GPU. Returns 0 to leave the draw to the CPU path. */
static int draw3d(mh_gles_renderer *r, mh_port *port, const mh_port_draw_call *call, uint32_t fvf) {
    uint32_t pos = fvf & 0x00e;
    if (!r->gpu3d || pos == 0 || pos == 0x004 || call->primitive < 4 || call->primitive > 6) return 0;
    /* the FVF layout (as d3d_fvf_layout) */
    uint32_t off = pos == 0x002 ? 12 : 12 + 4 * ((pos - 0x004) / 2), off_n = 0, off_d = 0, off_s = 0;
    int has_n = 0, has_d = 0, has_s = 0, ntex = (int)((fvf >> 8) & 15);
    if (fvf & 0x010) { has_n = 1; off_n = off; off += 12; }
    if (fvf & 0x020) off += 4;
    if (fvf & 0x040) { has_d = 1; off_d = off; off += 4; }
    if (fvf & 0x080) { has_s = 1; off_s = off; off += 4; }
    const uint32_t off_t = off;
    uint32_t prims, nidx; GLenum mode = call->primitive == 4 ? GL_TRIANGLES : call->primitive == 5 ? GL_TRIANGLE_STRIP : GL_TRIANGLE_FAN;
    uint32_t base = 0, length = 0, stride = 0, imem = 0, ilen = 0, ifmt = 101, basev = 0, vfirst = 0, istart = 0;
    GLuint vb = 0, ib = 0;
    switch (call->kind) {
    case MH_DRAW_PRIMITIVE: case MH_DRAW_INDEXED:
        if (!mh_port_stream(port, 0, &base, &length, &stride) || !stride) return 0;
        prims = call->kind == MH_DRAW_PRIMITIVE ? call->args[1] : call->args[3];
        break;
    default:
        prims = call->kind == MH_DRAW_PRIMITIVE_UP ? call->args[0] : call->args[2];
        stride = call->kind == MH_DRAW_PRIMITIVE_UP ? call->args[2] : call->args[6];
        if (!stride) return 0;
        break;
    }
    if (!prims) return 1;
    nidx = call->primitive == 4 ? 3 * prims : prims + 2;
    if (nidx > (1u << 22) || off > stride) return 0;
    if (call->kind == MH_DRAW_PRIMITIVE) {
        vfirst = call->args[0];
        if ((uint64_t)(vfirst + nidx) * stride > length) return 0;
        if (!(vb = gpu_buffer(r, GL_ARRAY_BUFFER, base, length, mh_port_stream_version(port, 0)))) return 0;
    } else if (call->kind == MH_DRAW_INDEXED) {
        if (!mh_port_indices(port, &imem, &ilen, &ifmt, &basev)) return 0;
        uint32_t isz = ifmt == 102 ? 4 : 2; istart = call->args[2];
        if ((uint64_t)(istart + nidx) * isz > ilen || (uint64_t)(basev + call->args[0] + call->args[1]) * stride > length) return 0;
        if (!(vb = gpu_buffer(r, GL_ARRAY_BUFFER, base, length, mh_port_stream_version(port, 0)))) return 0;
        if (!(ib = gpu_buffer(r, GL_ELEMENT_ARRAY_BUFFER, imem, ilen, mh_port_indices_version(port)))) return 0;
        vfirst = basev;
    } else {
        /* user pointers: uploaded at every draw */
        uint32_t vbytes, vmem = call->kind == MH_DRAW_PRIMITIVE_UP ? call->args[1] : call->args[5];
        if (call->kind == MH_DRAW_PRIMITIVE_UP) vbytes = nidx * stride;
        else vbytes = (call->args[0] + call->args[1]) * stride;
        if (vbytes > (16u << 20)) return 0;
        const void *vdata = mh_mem_span(r->mem, vmem, vbytes); if (!vdata) return 0;
        if (call->kind == MH_DRAW_INDEXED_UP) {
            ifmt = call->args[4]; uint32_t isz = ifmt == 102 ? 4 : 2;
            const void *idata = mh_mem_span(r->mem, call->args[3], nidx * isz); if (!idata) return 0;
            glBindVertexArray(r->vao3d);
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, r->ibo_up); glBufferData(GL_ELEMENT_ARRAY_BUFFER, (GLsizeiptr)(nidx * isz), idata, GL_STREAM_DRAW); ib = r->ibo_up;
        }
        glBindBuffer(GL_ARRAY_BUFFER, r->vbo_up); glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)vbytes, vdata, GL_STREAM_DRAW); vb = r->vbo_up;
    }
    flush(r);   /* the CPU batch comes first */
    glUseProgram(r->program3d); glBindVertexArray(r->vao3d);
    glBindBuffer(GL_ARRAY_BUFFER, vb);
    const char *at = (const char *)(uintptr_t)((size_t)vfirst * stride);
    glEnableVertexAttribArray(0); glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, (GLsizei)stride, at);
    if (has_n) { glEnableVertexAttribArray(1); glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, (GLsizei)stride, at + off_n); } else { glDisableVertexAttribArray(1); glVertexAttrib4f(1, 0, 0, 0, 0); }
    if (has_d) { glEnableVertexAttribArray(2); glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, (GLsizei)stride, at + off_d); } else { glDisableVertexAttribArray(2); glVertexAttrib4f(2, 1, 1, 1, 1); }
    if (has_s) { glEnableVertexAttribArray(3); glVertexAttribPointer(3, 4, GL_UNSIGNED_BYTE, GL_TRUE, (GLsizei)stride, at + off_s); } else { glDisableVertexAttribArray(3); glVertexAttrib4f(3, 0, 0, 0, 0); }
    /* texture coordinate sets: D3DFVF_TEXCOORDSIZE gives each set's size (0: 2 floats, 1: 3, 2: 4, 3: 1);
     * each stage reads the set its D3DTSS_TEXCOORDINDEX names (low word) */
    uint32_t set_off[8], o2 = off_t;
    for (int k = 0; k < 8; k++) { set_off[k] = o2; uint32_t sz = (fvf >> (16 + 2 * k)) & 3; o2 += sz == 0 ? 8 : sz == 1 ? 12 : sz == 2 ? 16 : 4; }
    uint32_t tci0 = mh_port_stage_state(port, 0, 11), tci1 = mh_port_stage_state(port, 1, 11);
    for (int st = 0; st < 2; st++) {
        uint32_t idx = (st ? tci1 : tci0) & 0xffff; GLuint loc = st ? 5 : 4;
        if ((int)idx < ntex && set_off[idx] + 8 <= stride) { glEnableVertexAttribArray(loc); glVertexAttribPointer(loc, 2, GL_FLOAT, GL_FALSE, (GLsizei)stride, at + set_off[idx]); }
        else { glDisableVertexAttribArray(loc); glVertexAttrib4f(loc, 0, 0, 0, 1); }
    }
    if (ib) glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ib);
    /* transforms and viewport mapping, as the CPU path */
    float world[16], view[16], proj[16], wv[16], wvp[16]; uint32_t vp[6];
    mh_port_transform(port, 256, world); mh_port_transform(port, 2, view); mh_port_transform(port, 3, proj); mh_port_viewport(port, vp);
    mat_mul(world, view, wv); mat_mul(wv, proj, wvp);
    {   /* texture coordinate generation (camera space) and texture transforms of stages 0 and 1 */
        float tm0[16], tm1[16];
        uint32_t f0 = mh_port_stage_state(port, 0, 24), f1 = mh_port_stage_state(port, 1, 24);
        mh_port_transform(port, 16, tm0); mh_port_transform(port, 17, tm1);
        glUniformMatrix4fv(r->u_wv, 1, GL_FALSE, wv); glUniformMatrix4fv(r->u_tm0, 1, GL_FALSE, tm0); glUniformMatrix4fv(r->u_tm1, 1, GL_FALSE, tm1);
        glUniform2i(r->u_tci, (GLint)(tci0 >> 16 & 3), (GLint)(tci1 >> 16 & 3)); glUniform2i(r->u_ttff, (GLint)(f0 & 0x1ff), (GLint)(f1 & 0x1ff));
    }
    glUniformMatrix4fv(r->u_wvp, 1, GL_FALSE, wvp); glUniformMatrix4fv(r->u_world, 1, GL_FALSE, world);
    glUniform4f(r->u_vp, ((float)vp[0] + vp[2] * 0.5f + 0.5f) / (float)r->cw * 2.0f - 1.0f, (float)vp[2] / (float)r->cw,
                1.0f - ((float)vp[1] + vp[3] * 0.5f + 0.5f) / (float)r->ch * 2.0f, (float)vp[3] / (float)r->ch);
    glUniform3f(r->u_zk, u2f(vp[4]), u2f(vp[5]), r->kx);
    /* fixed-function lighting (D3DRS_LIGHTING), as d3d_light_vertex */
    int light = mh_port_render_state(port, 137) != 0;
    glUniform1i(r->u_light, light);
    if (light) {
        uint32_t raw[8][26], m[17]; unsigned n = mh_port_lights(port, raw, 8); mh_port_material(port, m);
        float L[48][4]; memset(L, 0, sizeof L);
        for (unsigned i = 0; i < n; i++) {
            float *q = L[6 * i];
            q[0] = (float)raw[i][0]; q[1] = u2f(raw[i][19]); q[2] = u2f(raw[i][21]); q[3] = u2f(raw[i][22]);
            L[6 * i + 1][0] = u2f(raw[i][23]);
            for (int k = 0; k < 3; k++) { L[6 * i + 2][k] = u2f(raw[i][1 + k]); L[6 * i + 3][k] = u2f(raw[i][9 + k]); L[6 * i + 4][k] = u2f(raw[i][13 + k]); L[6 * i + 5][k] = u2f(raw[i][16 + k]); }
        }
        float M[4][4]; for (int i = 0; i < 16; i++) M[i / 4][i % 4] = u2f(m[i]);
        uint32_t amb = mh_port_render_state(port, 139); int cv = mh_port_render_state(port, 141) != 0;
        uint32_t ds = mh_port_render_state(port, 145), as = mh_port_render_state(port, 147), es = mh_port_render_state(port, 148);
        int sel[3]; const uint32_t src[3] = {ds, as, es};
        for (int i = 0; i < 3; i++) sel[i] = cv && has_d && src[i] == 1 ? 1 : cv && src[i] == 2 ? 2 : 0;
        glUniform1i(r->u_nlights, (GLint)n); glUniform4fv(r->u_lights, 48, &L[0][0]); glUniform4fv(r->u_mat, 4, &M[0][0]);
        glUniform4f(r->u_ambient, ((amb >> 16) & 255) / 255.0f, ((amb >> 8) & 255) / 255.0f, (amb & 255) / 255.0f, (amb >> 24) / 255.0f);
        glUniform3i(r->u_csel, sel[0], sel[1], sel[2]);
    }
    mh_d3d_pixel_state s; mh_d3d_pixel_state_get(port, &s);
    apply_state(r, &r->f3d, &s, 1);
    apply_stage1(r, port, &r->f3d);
    if (ib) glDrawElements(mode, (GLsizei)nidx, ifmt == 102 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, (const void *)(uintptr_t)((size_t)istart * (ifmt == 102 ? 4 : 2)));
    else glDrawArrays(mode, 0, (GLsizei)nidx);
    glDisable(GL_CULL_FACE);
    return 1;
}
static void on_draw(void *user, mh_port *port, const mh_port_draw_call *call) {
    mh_gles_renderer *r = user;
    if (!ensure(r, port)) return;
    uint64_t prof_t0 = PROF_NOW();
    if (draw3d(r, port, call, mh_port_fvf(port))) { mh_gles_prof[1] += PROF_NOW() - prof_t0; return; }
    mh_d3d_vertex *v = NULL; size_t n = mh_d3d_assemble(r->mem, port, call, &v);
    uint64_t prof_t1 = PROF_NOW(); mh_gles_prof[0] += prof_t1 - prof_t0;
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
            const mh_d3d_vertex *p = &v[i + (size_t)k]; float w = p->rhw > 0 ? 1.0f / p->rhw : 1.0f, *o = buf + 14 * out++;
            if (p->has_clip) {
                w = p->clip[3];
                o[0] = (ax * w + bx * p->clip[0]) * r->kx; o[1] = ay * w + by * p->clip[1];
                o[2] = (2.0f * minz - 1.0f) * w + 2.0f * (maxz - minz) * p->clip[2]; o[3] = w;
            } else {
                /* Into a render target (drawn at the internal scale, then sampled): each coordinate is
                 * moved to the pixel boundary Direct3D's coverage gives at the target's own size (pixel
                 * i is drawn when its centre i is inside), so the same pixels are covered at any scale.
                 * Without it the shadow pass leaves the target's first row and column at the clear
                 * colour, and the clamped shadow projection then darkens the floor around the player. */
                float px = p->x, py = p->y;
                if (r->cur_fbo != r->fbo) { px = ceilf(px) - 0.5f; py = ceilf(py) - 0.5f; }
                o[0] = ((px + 0.5f) / (float)r->cw * 2.0f - 1.0f) * w * r->kx;    /* Direct3D pixel centres are at integers */
                o[1] = (1.0f - (py + 0.5f) / (float)r->ch * 2.0f) * w;
                /* Direct3D does not clip pre-transformed vertices against the depth range: the HUD, the
                 * camcorder overlay and the shadow pass draw at z = 3276. GL would clip them; z is clamped. */
                float z = p->z < 0 ? 0 : p->z > 1 ? 1 : p->z;
                o[2] = (z * 2.0f - 1.0f) * w; o[3] = w;
            }
            memcpy(o + 4, p->diffuse, 16); memcpy(o + 8, p->specular, 16); o[12] = p->u; o[13] = p->v;
        }
    }
    free(v);
    mh_gles_prof[1] += PROF_NOW() - prof_t1;
    if (!out) { free(buf); return; }
    /* a different state or target ends the batch; a very large one is sent as it is */
    if (r->pend_n && (r->pend_fbo != r->cur_fbo || memcmp(&r->pend_state, &s, sizeof s) || r->pend_n + out > (1u << 20))) flush(r);
    if (r->pend_n + out > r->pend_cap) {
        size_t cap = r->pend_cap ? r->pend_cap : 65536; while (cap < r->pend_n + out) cap *= 2;
        float *grown = realloc(r->pend, cap * 14 * sizeof(float)); if (!grown) { free(buf); return; }
        r->pend = grown; r->pend_cap = cap;
    }
    memcpy(r->pend + 14 * r->pend_n, buf, out * 14 * sizeof(float)); free(buf);
    if (!r->pend_n) { r->pend_state = s; r->pend_fbo = r->cur_fbo; r->pend_vw = r->cur_vw; r->pend_vh = r->cur_vh; }
    r->pend_n += out;
}
static void on_present(void *user, mh_port *port, unsigned frame) {
    mh_gles_renderer *r = user; (void)frame; flush(r);
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
    for (unsigned i = 0; i < r->nbuffers; i++) glDeleteBuffers(1, &r->buffers[i].id);
    if (r->program3d) { glDeleteProgram(r->program3d); glDeleteVertexArrays(1, &r->vao3d); glDeleteBuffers(1, &r->vbo_up); glDeleteBuffers(1, &r->ibo_up); }
    if (r->fbo) { glDeleteFramebuffers(1, &r->fbo); glDeleteRenderbuffers(1, &r->color); glDeleteRenderbuffers(1, &r->depth); }
    if (r->program) { glDeleteProgram(r->program); glDeleteBuffers(1, &r->vbo); glDeleteVertexArrays(1, &r->vao); }
    free(r->pend); r->pend = NULL; r->pend_n = r->pend_cap = 0;
    free(r);
}
void mh_gles_renderer_set_options(mh_gles_renderer *r, float scale, int stretch) { r->scale = scale < 0 ? 0 : scale > 6 ? 6 : scale; r->stretch = stretch < 0 || stretch > 2 ? 0 : stretch; mh_d3d_keep_clip = 1; }
void mh_gles_renderer_bind(mh_gles_renderer *r, mh_port_renderer *out) { memset(out, 0, sizeof *out); out->user = r; out->clear = on_clear; out->draw = on_draw; out->present = on_present; }
