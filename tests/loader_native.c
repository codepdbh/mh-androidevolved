/* Isolated test of the translated slot loader 0x605750 over the real read-only
 * file layer (Android/POSIX only). Synthetic slot files are created under the
 * directory given as argv[1] and removed before exit. Only the CRT malloc of the arena is
 * a test double; CreateFileA/ReadFile/CloseHandle are the observed read-only
 * subset implemented by runtime/readonly_handles; the pool allocator is the translated one. Output is compared on the PC
 * against tools/probe_loader_x86.py (Unicorn). */
#define _GNU_SOURCE
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
#include "../runtime/readonly_stream.c"
#include "../runtime/readonly_path.c"
#include "../runtime/readonly_handles.c"
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
double g_st[8];int g_fp_top;uint16_t g_fpu_cw=0x037f;
static _Alignas(8) uint8_t guest[0x900000];
static mh_ro_handles files=MH_RO_HANDLES_INIT;
static unsigned api_opens,api_reads,api_closes;
void mh_guest_fault(uint32_t a,size_t n){(void)a;(void)n;exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){(void)a;(void)c;exit(74);}

/* The game's own pool allocator (translated, ../allocator/allocator_unit.c) serves
 * every string allocation. Only the CRT malloc that provides its arena is a double. */
#define POOL 0x67d000u
#define ARENA 0x8c0000u
#define ARENA_SIZE 0x8000u
void sub_00610BE0(void){if(MEM32(g_esp)!=0x40112b)exit(86);g_eax=ARENA;g_esp+=4;}
/* Read-only API subset, as observed at these exact call sites. */
static void api_read_file(void){
    if(MEM32(g_esp)!=0x60ff76)exit(80);
    api_reads++;
    g_eax=mh_ro_handle_read(&files,MEM32(g_esp+4),&mh_recomp_region,MEM32(g_esp+8),MEM32(g_esp+12),MEM32(g_esp+16),MEM32(g_esp+20))==MH_RO_OK;
    g_esp+=24;
}
static void api_create_file(void){
    if(MEM32(g_esp)!=0x60fee2)exit(82);
    uint32_t name_address=MEM32(g_esp+4),handle=0xffffffffu;char name[MH_RO_PATH_CAPACITY];int complete=0;
    for(unsigned i=0;i<sizeof name;i++){
        if(!mh_mem_read(&mh_recomp_region,name_address+i,&name[i],1))break;
        if(!name[i]){complete=1;break;}
    }
    api_opens++;
    if(complete&&MEM32(g_esp+8)==0x80000000u&&MEM32(g_esp+12)==0&&MEM32(g_esp+16)==0&&MEM32(g_esp+20)==3&&MEM32(g_esp+24)==0&&MEM32(g_esp+28)==0)
        if(mh_ro_open_relative(&files,name,&handle)!=MH_RO_OK)handle=0xffffffffu;
    g_eax=handle;g_esp+=32;
}
static void api_close_handle(void){
    if(MEM32(g_esp)!=0x60ff51)exit(83);
    api_closes++;g_eax=mh_ro_close_handle(&files,MEM32(g_esp+4))==MH_RO_OK;g_esp+=8;
}
recomp_func_t recomp_lookup(uint32_t va){return va==0x800300?api_read_file:(va==0x800400?api_create_file:(va==0x800500?api_close_handle:NULL));}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "dependencies/loader_helpers_unit.c"
#include "dependencies/file_lifecycle_unit.c"
#include "dependencies/dep_00611640_precise.c"
#include "dependencies/dep_00401030_precise.c"
#include "dependencies/loader_strings_unit.c"
#include "dependencies/dep_00605750_precise.c"
#include "../allocator/allocator_unit.c"

static const uint32_t block_sizes[7]={4,16,1,64,3,128,8};
static const unsigned file_sizes[4]={224,225,100,0}; /* exact, one extra byte, short, missing */
static char root_path[512];
static int root_created,dirs_created;
static void cleanup(void){
    char path[600];
    for(unsigned i=0;i<4;i++){snprintf(path,sizeof path,"%s/data/save/slot%u.bin",root_path,i);unlink(path);}
    if(dirs_created>=3){snprintf(path,sizeof path,"%s/data/save",root_path);rmdir(path);}
    if(dirs_created>=2){snprintf(path,sizeof path,"%s/data",root_path);rmdir(path);}
    if(root_created)rmdir(root_path);
}
static int make_fixtures(const char *base){
    char path[600];
    if(snprintf(root_path,sizeof root_path,"%s/root",base)>=(int)sizeof root_path)return 0;
    if(mkdir(root_path,0700))return 0;root_created=1;dirs_created=1;
    snprintf(path,sizeof path,"%s/data",root_path);if(mkdir(path,0700))return 0;dirs_created=2;
    snprintf(path,sizeof path,"%s/data/save",root_path);if(mkdir(path,0700))return 0;dirs_created=3;
    for(unsigned s=0;s<3;s++){
        uint8_t bytes[256];for(unsigned i=0;i<file_sizes[s];i++)bytes[i]=(uint8_t)(i*13+7+s);
        snprintf(path,sizeof path,"%s/data/save/slot%u.bin",root_path,s);
        int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
        if(fd<0||write(fd,bytes,file_sizes[s])!=(ssize_t)file_sizes[s]||close(fd))return 0;
    }
    return 1;
}
static void hex(uint32_t address,unsigned n){for(unsigned i=0;i<n;i++)printf("%02x",guest[address+i]);}
static void put_string(uint32_t address,const char *s){memcpy(guest+address,s,strlen(s)+1);}
int main(int argc,char **argv){
    if(argc!=2)return 76;
    atexit(cleanup);
    if(!mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000))return 71;
    if(!make_fixtures(argv[1]))return 72;
    for(unsigned k=0;k<16;k++){
        unsigned scenario=k%4,alignment=k/4;
        int fd=open(root_path,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
        mh_ro_handles fresh=MH_RO_HANDLES_INIT;files=fresh;
        if(fd<0||mh_ro_bind_root(&files,fd)!=MH_RO_OK)return 73;
        close(fd);api_opens=api_reads=api_closes=0;
        memset(guest+0x830000,0,0x2000);memset(guest+0x840000,0,0x800);memset(guest+0x87fe00,0,0x300);
        memset(guest+POOL,0,0x1300);memset(guest+ARENA,0,ARENA_SIZE);memset(guest+0x7d7c10,0,0x200);
        /* pool constructor (0x4010b0) over the 32 KiB arena, as the game's static initialiser does */
        g_eax=g_ebx=g_edx=g_esi=g_edi=g_ebp=0;g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
        g_ecx=POOL;g_esp=0x880000;MEM32(g_esp)=0x8f0000;MEM32(g_esp+4)=ARENA_SIZE;sub_004010B0();
        if(g_esp!=0x880008)return 74;
        MEM32(0x81b37c)=0x800400;MEM32(0x81b374)=0x800300;MEM32(0x81b370)=0x800500;
        put_string(0x831000,"data\\");MEM32(0x8302ac)=0x831000;MEM16(0x8302b0)=5;MEM16(0x8302b2)=0;
        put_string(0x7d7d88,"save\\");
        for(unsigned i=0;i<4;i++){char name[32];snprintf(name,sizeof name,"slot%u.bin",i);put_string(0x7d7c10+32*i,name);}
        for(unsigned i=0;i<4;i++)MEM32(0x830000+i*84+0xc)=0x1000+i;
        g_mem_base=0;g_eax=0x11111111;g_ebx=0x22222222;g_ecx=0x830000;g_edx=0x33333333;
        g_esi=0x44444444;g_edi=0x55555555;g_ebp=0x66666666;g_esp=0x880000+alignment;
        g_flag_k=g_flag_a=g_flag_b=g_flag_cf=0;
        MEM32(g_esp)=0x8f0000;MEM32(g_esp+4)=scenario;
        for(unsigned j=0;j<7;j++){MEM32(g_esp+8+8*j)=0x840000+0x100*j;MEM32(g_esp+12+8*j)=block_sizes[j];}
        sub_00605750();
        printf("{\"scenario\":%u,\"alignment\":%u,\"registers\":{\"eax\":%u,\"ebx\":%u,\"ecx\":%u,\"edx\":%u,\"esi\":%u,\"edi\":%u,\"ebp\":%u,\"esp\":%u,\"eflags\":%u},",
               scenario,alignment,g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1));
        printf("\"api\":[%u,%u,%u],\"stack_hex\":\"",api_opens,api_reads,api_closes);hex(0x87fe00,0x300);
        printf("\",\"object_hex\":\"");hex(0x830000,0x180);
        printf("\",\"buffers_hex\":\"");hex(0x840000,0x700);
        printf("\",\"heap_hex\":\"");hex(POOL,0x1268);hex(ARENA,ARENA_SIZE);
        printf("\"}\n");
        mh_ro_unbind(&files);
    }
    return 0;
}
