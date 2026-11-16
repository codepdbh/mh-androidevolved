/* Bounded real opens/reads beneath authorized directory descriptors. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
#include "../runtime/readonly_stream.c"
#include "../runtime/readonly_path.c"
#include "../runtime/readonly_handles.c"
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
static _Alignas(8) uint8_t guest[0x900000];
static mh_ro_handles files=MH_RO_HANDLES_INIT;
static unsigned api_opens,api_closes;
#define CHECK(x) do{if(!(x)){printf("failed line %d\n",__LINE__);return 1;}}while(0)
void mh_guest_fault(uint32_t a,size_t n){(void)a;(void)n;exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){(void)a;(void)c;exit(74);}
static void real_read_file(void){
    if(MEM32(g_esp)!=0x60ff76)exit(80);
    g_eax=mh_ro_handle_read(&files,MEM32(g_esp+4),&mh_recomp_region,MEM32(g_esp+8),MEM32(g_esp+12),MEM32(g_esp+16),MEM32(g_esp+20))==MH_RO_OK;
    g_esp+=24;
}
/* Test adapters accept only the observed read-only API subset; no Win32
 * sharing/error/encoding emulation is claimed beyond these assertions. */
static void readonly_create_file(void){
    if(MEM32(g_esp)!=0x60fee2)exit(82);
    uint32_t name_address=MEM32(g_esp+4),handle=0xffffffffu;char name[MH_RO_PATH_CAPACITY];int complete=0;
    for(unsigned i=0;i<sizeof name;i++){
        if((uint64_t)name_address+i>UINT32_MAX||!mh_mem_read(&mh_recomp_region,name_address+i,&name[i],1))break;
        if(!name[i]){complete=1;break;}
    }
    api_opens++;
    if(complete&&MEM32(g_esp+8)==0x80000000u&&MEM32(g_esp+12)==0&&MEM32(g_esp+16)==0&&MEM32(g_esp+20)==3&&MEM32(g_esp+24)==0&&MEM32(g_esp+28)==0){
        if(mh_ro_open_relative(&files,name,&handle)!=MH_RO_OK)handle=0xffffffffu;
    }
    g_eax=handle;g_esp+=32;
}
static void readonly_close_handle(void){
    if(MEM32(g_esp)!=0x60ff51)exit(83);
    api_closes++;g_eax=mh_ro_close_handle(&files,MEM32(g_esp+4))==MH_RO_OK;g_esp+=8;
}
recomp_func_t recomp_lookup(uint32_t va){return va==0x800300?real_read_file:(va==0x800400?readonly_create_file:(va==0x800500?readonly_close_handle:NULL));}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "loader_helpers_unit.c"
#include "file_lifecycle_unit.c"
static uint32_t open_wrapper(const char *name,uint32_t access){
    strcpy((char *)guest+0x850001,name);g_esp=0x880001;g_ecx=0x820001;g_ebx=123;
    MEM32(g_esp)=0x220000;MEM32(g_esp+4)=0x850001;MEM32(g_esp+8)=access;MEM32(g_esp+12)=0;
    sub_0060FEC0();if(g_esp!=0x880011||g_ebx!=123)exit(84);return g_eax;
}
static void close_wrapper(int destroy){
    g_esp=0x880002;g_ecx=0x820001;g_ebx=124;MEM32(g_esp)=0x220000;
    if(destroy)sub_0060FEB0();else sub_0060FF40();
    if(g_esp!=0x880006||g_ebx!=124||(destroy&&g_eax!=0x820001))exit(85);
}
static uint32_t read_handle(uint32_t h,uint32_t n,unsigned alignment){
    uint32_t sp=0x880000+alignment;g_eax=9;g_esp=sp;g_ecx=0x820001;g_mem_base=0;
    MEM32(g_ecx)=h;MEM32(0x81b374)=0x800300;MEM32(sp)=0x220000;
    MEM32(sp+4)=0x830001;MEM32(sp+8)=n;MEM32(sp+12)=0x840003;MEM32(0x840003)=99;
    sub_0060FF60();if(g_esp!=sp+16||MEM32(sp)!=0x220000)exit(81);return MEM32(0x840003);
}
int main(int argc,char **argv){
    if(argc!=2)return 76;
    CHECK(mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000));
    int fd=open(argv[1],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);CHECK(fd>=0);
    CHECK(mh_ro_bind_root(&files,fd)==MH_RO_OK);close(fd);
    uint32_t a=0,b=0,reused=0,out=99;
    CHECK(mh_ro_open_relative(&files,"fixture",&a)==MH_RO_OK);
    CHECK(mh_ro_open_relative(&files,"nested\\data",&b)==MH_RO_OK&&a!=b);
    CHECK(read_handle(a,3,0)==3&&g_eax==1&&!memcmp(guest+0x830001,"012",3));
    CHECK(read_handle(b,2,1)==2&&g_eax==1&&!memcmp(guest+0x830001,"01",2));
    CHECK(read_handle(a,3,2)==3&&!memcmp(guest+0x830001,"345",3));
    CHECK(read_handle(b,2,3)==2&&!memcmp(guest+0x830001,"23",2));
    CHECK(mh_ro_close_handle(&files,a)==MH_RO_OK);
    CHECK(mh_ro_open_relative(&files,"fixture",&reused)==MH_RO_OK&&reused!=a);
    CHECK(read_handle(a,1,0)==0&&g_eax==0);
    CHECK(mh_ro_close_handle(&files,a)==MH_RO_INVALID);
    CHECK(read_handle(reused,1,0)==1&&MEM8(0x830001)=='0');
    const char *invalid[]={"","/fixture","\\fixture","C:\\fixture","../fixture","nested/../fixture","./fixture","nested//data","nested/","fixture:stream"};
    for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];i++){out=99;CHECK(mh_ro_open_relative(&files,invalid[i],&out)==MH_RO_INVALID&&out==99);}
    CHECK(mh_ro_open_relative(&files,"link",&out)!=MH_RO_OK);
    CHECK(mh_ro_open_relative(&files,"linked/data",&out)!=MH_RO_OK);
    struct stat fifo;
    if(fstatat(files.root_fd,"pipe",&fifo,AT_SYMLINK_NOFOLLOW)==0){
        CHECK(S_ISFIFO(fifo.st_mode)&&mh_ro_open_relative(&files,"pipe",&out)==MH_RO_UNSUPPORTED);
    }else{CHECK(errno==ENOENT);puts("SKIP: FIFO fixture unavailable on device");}
    CHECK(mh_ro_open_relative(&files,"nested",&out)==MH_RO_UNSUPPORTED);
    uint32_t held[MH_RO_HANDLE_SLOTS];unsigned used=0;
    while(used<MH_RO_HANDLE_SLOTS&&mh_ro_open_relative(&files,"fixture",&held[used])==MH_RO_OK)used++;
    CHECK(used==MH_RO_HANDLE_SLOTS-2);out=99;
    CHECK(mh_ro_open_relative(&files,"fixture",&out)==MH_RO_NOMEM&&out==99);
    for(unsigned i=0;i<used;i++)CHECK(mh_ro_close_handle(&files,held[i])==MH_RO_OK);
    mh_ro_unbind(&files);mh_ro_unbind(&files);
    CHECK(read_handle(b,1,0)==0&&g_eax==0);
    fd=open(argv[1],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);CHECK(fd>=0);
    CHECK(mh_ro_bind_root(&files,fd)==MH_RO_OK);close(fd);
    CHECK(mh_ro_open_relative(&files,"fixture",&out)==MH_RO_OK&&out!=reused);
    CHECK(read_handle(reused,1,0)==0&&g_eax==0);
    mh_ro_unbind(&files);
    fd=open("/sdcard/mh-androidevolved",O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);CHECK(fd>=0);
    CHECK(mh_ro_bind_root(&files,fd)==MH_RO_OK);close(fd);
    CHECK(mh_ro_open_relative(&files,"manhunt.exe",&out)==MH_RO_OK);
    CHECK(read_handle(out,64,1)==64&&MEM8(0x830001)=='M'&&MEM8(0x830002)=='Z');
    uint32_t pe=MEM32(0x830001+0x3c);CHECK(pe<6304252&&mh_ro_handle_seek(&files,out,pe)==MH_RO_OK);
    CHECK(read_handle(out,4,2)==4&&!memcmp(guest+0x830001,"PE\0\0",4));
    CHECK(mh_ro_close_handle(&files,out)==MH_RO_OK);
    unsigned retired=out&15u;files.slots[retired].generation=0x03ffffffu;
    CHECK(mh_ro_open_relative(&files,"manhunt.exe",&out)==MH_RO_OK&&(out&15u)==retired);
    CHECK(mh_ro_close_handle(&files,out)==MH_RO_OK);
    CHECK(mh_ro_open_relative(&files,"manhunt.exe",&out)==MH_RO_OK&&(out&15u)!=retired);
    CHECK(mh_ro_close_handle(&files,out)==MH_RO_OK);mh_ro_unbind(&files);
    /* Full translated lifecycle with the controlled, read-only API adapters. */
    fd=open(argv[1],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);CHECK(fd>=0);
    CHECK(mh_ro_bind_root(&files,fd)==MH_RO_OK);close(fd);
    MEM32(0x81b37c)=0x800400;MEM32(0x81b370)=0x800500;
    g_ecx=0x820001;g_esp=0x880000;sub_0060FEA0();CHECK(MEM32(0x820001)==0xffffffffu);
    CHECK(open_wrapper("fixture",0x80000000u)==1);a=MEM32(0x820001);
    CHECK(read_handle(a,2,0)==2&&!memcmp(guest+0x830001,"01",2));
    CHECK(open_wrapper("nested\\data",0x80000000u)==1);b=MEM32(0x820001);
    CHECK(a!=b&&api_closes==1&&mh_ro_handle_seek(&files,a,0)==MH_RO_INVALID);
    CHECK(read_handle(b,3,1)==3&&!memcmp(guest+0x830001,"012",3));
    close_wrapper(0);CHECK(MEM32(0x820001)==0xffffffffu&&api_closes==2);
    close_wrapper(0);CHECK(api_closes==2);
    CHECK(open_wrapper("../fixture",0x80000000u)==0&&MEM32(0x820001)==0xffffffffu);
    CHECK(open_wrapper("fixture",0x40000000u)==0&&MEM32(0x820001)==0xffffffffu);
    CHECK(open_wrapper("missing",0x80000000u)==0&&MEM32(0x820001)==0xffffffffu);
    CHECK(open_wrapper("fixture",0x80000000u)==1);close_wrapper(1);
    CHECK(api_opens==6&&api_closes==3&&MEM32(0x820001)==0xffffffffu);mh_ro_unbind(&files);
    fd=open("/sdcard/mh-androidevolved",O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);CHECK(fd>=0);
    CHECK(mh_ro_bind_root(&files,fd)==MH_RO_OK);close(fd);
    CHECK(open_wrapper("manhunt.exe",0x80000000u)==1);out=MEM32(0x820001);
    CHECK(read_handle(out,64,2)==64&&MEM8(0x830001)=='M'&&MEM8(0x830002)=='Z');
    close_wrapper(1);CHECK(api_opens==7&&api_closes==4&&MEM32(0x820001)==0xffffffffu);mh_ro_unbind(&files);
    puts("real relative opens, handles, copied PE reads and translated open/read/close lifecycle passed");return 0;
}
