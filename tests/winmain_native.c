/* Comparison harness: the boot up to WinMain's first frames, as translated code over the port
 * (runtime/game_runner.c, the same code the Android app runs), until the third presented frame;
 * prints the record compared with tools/trace_static_init_x86.py --winmain.
 * argv[1] = the user's manhunt.exe; argv[2] = the game folder (read only). Portable.
 * Environment (debugging): MH_CALLLOG=<file> every API/COM call; MH_TRACE_ALL=1 log every call;
 * MH_DUMP_AT=<n> MH_DUMP=<file> .data/.bss at the n-th call; MH_DUMP=<file> / MH_DUMP_GLOBAL=<file>
 * memory images at the end; MH_RENDER=<dir> frames as PNG through the reference software renderer. */
#include "../runtime/game_runner.c"
#include "../runtime/d3d_common.c"
#include "../runtime/sw_renderer.c"
#define FRAMES 3u   /* MH_FRAMES overrides, as --frames of the reference */
int main(int argc,char **argv){
    if(argc!=3)return 76;
    mh_game_config c;memset(&c,0,sizeof c);
    c.exe_path=argv[1];c.game_dir=argv[2];c.frame_limit=getenv("MH_FRAMES")?(unsigned)strtoul(getenv("MH_FRAMES"),NULL,10):FRAMES;c.key_script=getenv("MH_KEYS");if(getenv("MH_LANG"))c.langid=(unsigned)strtoul(getenv("MH_LANG"),NULL,16);
    if(getenv("MH_CALLLOG"))c.calllog=fopen(getenv("MH_CALLLOG"),"w");
    c.trace_all=getenv("MH_TRACE_ALL")!=NULL;
    if(getenv("MH_DUMP_AT")){c.dump_at=(unsigned)strtoul(getenv("MH_DUMP_AT"),NULL,10);c.dump_path=getenv("MH_DUMP");}
    mh_port_renderer pr;
    if(getenv("MH_RENDER")){
        static char pattern[600],logpath[600];
        snprintf(pattern,sizeof pattern,"%s/frame%%03u.png",getenv("MH_RENDER"));snprintf(logpath,sizeof logpath,"%s/draws.txt",getenv("MH_RENDER"));
        mh_sw_renderer *sw=mh_sw_renderer_create(&mh_recomp_region,fopen(logpath,"w"),pattern);mh_sw_renderer_bind(sw,&pr);c.renderer=&pr;
        if(getenv("MH_RENDER_FROM"))mh_sw_renderer_set_first_frame(sw,(unsigned)strtoul(getenv("MH_RENDER_FROM"),NULL,10));
    }
    int rc=mh_game_run(&c);
    if(rc)return rc;
    if(c.calllog)fclose(c.calllog);
    mh_game_print_result(stdout);
    uint8_t *g=mh_game_guest();mh_port *p=mh_game_port();
    if(getenv("MH_DUMP_GLOBAL")){FILE *d=fopen(getenv("MH_DUMP_GLOBAL"),"wb");if(d){fwrite(g+RUN_GLOBAL_BASE,1,mh_port_global(p)->next-RUN_GLOBAL_BASE,d);fclose(d);}}
    if(getenv("MH_DUMP")){FILE *d=fopen(getenv("MH_DUMP"),"wb");if(d){fwrite(g+0x67d000,1,0x8296d4-0x67d000,d);fclose(d);}}
    if(getenv("MH_DUMP_STACK")){FILE *d=fopen(getenv("MH_DUMP_STACK"),"wb");if(d){fwrite(g+0x1800000u-0x10000,1,0x10014,d);fclose(d);}}   /* the stack_crc range */
    return 0;
}
