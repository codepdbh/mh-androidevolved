/* Real POSIX reads through the private translated ReadFile wrapper. */
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include "checked_memory_adapter.h"
#include "checked_dispatch_adapter.h"
#include "../runtime/guest_memory.c"
#include "../runtime/readonly_stream.c"
#include <stdio.h>
uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp,g_cur_func;
ptrdiff_t g_mem_base;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
mh_guest_memory mh_recomp_region;
static _Alignas(8) uint8_t guest[0x900000];
static mh_readonly_stream stream=MH_READONLY_STREAM_INIT;
static int io_status;
#define CHECK(x) do{if(!(x)){printf("failed line %d\n",__LINE__);return 1;}}while(0)
void mh_guest_fault(uint32_t a,size_t n){(void)a;(void)n;exit(70);}
void mh_dispatch_fault(uint32_t a,uint32_t c){(void)a;(void)c;exit(74);}
static void real_read_file(void){
    if(MEM32(g_esp)!=0x60ff76||MEM32(g_esp+4)!=0x1234)exit(80);
    io_status=mh_ro_read_guest(&stream,&mh_recomp_region,MEM32(g_esp+8),MEM32(g_esp+12),MEM32(g_esp+16),MEM32(g_esp+20));
    g_eax=io_status==MH_RO_OK;g_esp+=24;
}
recomp_func_t recomp_lookup(uint32_t va){return va==0x800300?real_read_file:NULL;}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
#include "loader_helpers_unit.c"
static uint32_t read_wrapper(uint32_t count,unsigned alignment){
    uint32_t sp=0x880000+alignment;
    g_eax=9;g_esp=sp;g_ecx=0x820001;g_mem_base=0;
    MEM32(g_ecx)=0x1234;MEM32(0x81b374)=0x800300;
    MEM32(sp)=0x220000;MEM32(sp+4)=0x830001;MEM32(sp+8)=count;MEM32(sp+12)=0x840003;
    MEM32(0x840003)=0xeeeeeeeeu;
    sub_0060FF60();
    if(g_esp!=sp+16||MEM32(sp)!=0x220000)exit(81);
    return MEM32(0x840003);
}
int main(int argc,char **argv){
    if(argc!=2)return 76;
    CHECK(mh_mem_init(&mh_recomp_region,guest+0x10000,sizeof guest-0x10000,0x10000));
    int fd=open(argv[1],O_RDONLY|O_CLOEXEC|O_NOFOLLOW);CHECK(fd>=0);
    CHECK(lseek(fd,7,SEEK_SET)==7);
    CHECK(mh_ro_open_descriptor(&stream,fd)==MH_RO_OK);
    for(unsigned a=0;a<4;a++){
        CHECK(mh_ro_seek(&stream,0)==MH_RO_OK);
        CHECK(read_wrapper(3,a)==3&&g_eax==1&&io_status==MH_RO_OK);
        CHECK(!memcmp(guest+0x830001,"012",3));
        CHECK(read_wrapper(7,a)==7&&!memcmp(guest+0x830001,"3456789",7));
        CHECK(lseek(fd,0,SEEK_CUR)==7);
    }
    CHECK(mh_ro_seek(&stream,30)==MH_RO_OK);
    CHECK(read_wrapper(7,0)==2&&!memcmp(guest+0x830001,"uv",2));
    CHECK(read_wrapper(7,0)==0&&g_eax==1);
    CHECK(read_wrapper(0,0)==0&&g_eax==1);
    CHECK(mh_ro_seek(&stream,UINT64_MAX)==MH_RO_INVALID);
    uint64_t pos=stream.position;
    CHECK(mh_ro_read_guest(&stream,&mh_recomp_region,0,4,0x840003,0)==MH_RO_INVALID&&stream.position==pos);
    CHECK(mh_ro_read_guest(&stream,&mh_recomp_region,0x830001,4,0,0)==MH_RO_INVALID);
    CHECK(mh_ro_read_guest(&stream,&mh_recomp_region,0x830001,4,0x830002,0)==MH_RO_INVALID);
    CHECK(mh_ro_read_guest(&stream,&mh_recomp_region,0x830001,4,0x840003,1)==MH_RO_UNSUPPORTED&&MEM32(0x840003)==0);
    CHECK(mh_ro_read_guest(&stream,&mh_recomp_region,0x830001,1024u*1024u+1,0x800003,0)==MH_RO_UNSUPPORTED);
    mh_readonly_stream invalid={0x7fffffff,5};
    MEM8(0x830001)=0xa5;MEM32(0x840003)=99;
    CHECK(mh_ro_read_guest(&invalid,&mh_recomp_region,0x830001,1,0x840003,0)==MH_RO_IO);
    CHECK(invalid.position==5&&MEM8(0x830001)==0xa5&&MEM32(0x840003)==0);
    CHECK(close(fd)==0);CHECK(mh_ro_seek(&stream,0)==MH_RO_OK);
    CHECK(read_wrapper(1,0)==1&&MEM8(0x830001)=='0'); /* Owned duplicate still valid. */
    mh_ro_close(&stream);mh_ro_close(&stream);
    CHECK(read_wrapper(1,0)==0&&g_eax==0&&io_status==MH_RO_INVALID);
    int pipes[2];CHECK(pipe(pipes)==0);
    CHECK(mh_ro_open_descriptor(&stream,pipes[0])==MH_RO_UNSUPPORTED);close(pipes[0]);close(pipes[1]);
    int writable=open(argv[1],O_RDWR|O_CLOEXEC|O_NOFOLLOW);CHECK(writable>=0);
    CHECK(mh_ro_open_descriptor(&stream,writable)==MH_RO_UNSUPPORTED);close(writable);

    /* Only read the copied game on the phone; no original binary is executed. */
    fd=open("/sdcard/mh-androidevolved/manhunt.exe",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);CHECK(fd>=0);
    struct stat st;CHECK(fstat(fd,&st)==0&&st.st_size==6304256);
    CHECK(mh_ro_open_descriptor(&stream,fd)==MH_RO_OK);close(fd);
    CHECK(read_wrapper(64,1)==64&&MEM8(0x830001)=='M'&&MEM8(0x830002)=='Z');
    uint32_t pe=MEM32(0x830001+0x3c);CHECK(pe<6304252&&mh_ro_seek(&stream,pe)==MH_RO_OK);
    CHECK(read_wrapper(4,2)==4&&!memcmp(guest+0x830001,"PE\0\0",4));
    CHECK(mh_ro_seek(&stream,6304256)==MH_RO_OK&&read_wrapper(4,3)==0&&g_eax==1);
    mh_ro_close(&stream);
    puts("real read-only fixture and copied PE reads passed through translated wrapper");return 0;
}
