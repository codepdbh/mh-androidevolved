#include "pe32_image.h"
#include "pe32_imports.h"
#include "pe32_import_plan.h"
#ifdef MH_TEST_IMPORT_REGISTRY
#include "import_registry.h"
#endif
#include <stdint.h>
#include <string.h>
#define CHECK(x) do { if(!(x)) return __LINE__; } while(0)
_Alignas(8) static uint8_t file[0x400], mapped[0x2100];
static void put16(size_t p,uint16_t v){file[p]=(uint8_t)v;file[p+1]=(uint8_t)(v>>8);}
static void put32(size_t p,uint32_t v){for(unsigned i=0;i<4;i++)file[p+i]=(uint8_t)(v>>(i*8));}
static void fixture(void){
    memset(file,0,sizeof file);memset(mapped,0xa5,sizeof mapped);
    put16(0,0x5a4d);put32(0x3c,0x80);put32(0x80,0x4550);put16(0x84,0x14c);put16(0x86,1);put16(0x94,0xe0);
    put16(0x98,0x10b);put32(0xa8,0x1000);put32(0xb4,0x400000);put32(0xd0,0x2000);put32(0xd4,0x200);
    put32(0x180,0x180);put32(0x184,0x1000);put32(0x188,0x100);put32(0x18c,0x200);
    for(unsigned i=0;i<0x100;i++)file[0x200+i]=(uint8_t)i;
}
static int equals(const char *a,const char *b){while(*a && *a==*b){a++;b++;}return *a==*b;}
static int inspect_import(const mh_pe32_import *item,void *context){
    unsigned *visited=context;
    if(!equals(item->dll,"foo.dll"))return 0;
    if(*visited==0){if(item->by_ordinal || !item->name || !equals(item->name,"Bar") || item->iat_address!=0x401050)return 0;}
    else if(*visited==1){if(!item->by_ordinal || item->name || item->ordinal!=7 || item->iat_address!=0x401054)return 0;}
    else return 0;
    (*visited)++;return 1;
}
static int reject_import(const mh_pe32_import *item,void *context){(void)item;(void)context;return 0;}
static int resolve_import(const mh_pe32_import *item,void *context,uint32_t *target){
    int mode=*(int *)context;
    if(mode==2){*target=0;return MH_IMPORT_FOUND;}
    if(mode==1 && item->by_ordinal)return MH_IMPORT_MISSING;
    *target=item->by_ordinal?0x70000002u:0x70000001u;return MH_IMPORT_FOUND;
}
static void imports_fixture(void){
    fixture();put32(0xf4,16);put32(0x100,0x1000);put32(0x104,40);
    memset(file+0x200,0,0x100);
    put32(0x200,0x1040);put32(0x20c,0x1060);put32(0x210,0x1050);
    put32(0x240,0x1070);put32(0x244,0x80000007);
    memcpy(file+0x260,"foo.dll",8);memcpy(file+0x272,"Bar",4);
}
int mh_pe_tests(void){
    mh_guest_memory mem;mh_pe32_info info;
    fixture();CHECK(mh_mem_init(&mem,mapped,sizeof mapped,0x400000));
    CHECK(mh_pe32_map_image(file,sizeof file,&mem,&info));
    size_t no_imports=99;CHECK(mh_pe32_visit_imports(&mem,&info,NULL,NULL,&no_imports) && no_imports==0);
    CHECK(info.image_base==0x400000 && info.image_size==0x2000 && info.entry_rva==0x1000 && info.section_count==1);
    CHECK(mapped[0]=='M' && mapped[0x1001]==1 && mapped[0x10ff]==0xff);
    CHECK(mapped[0x1100]==0 && mapped[0x117f]==0 && mapped[0x2000]==0xa5);
    fixture();info.image_base=0xabcdef;put32(0x18c,0x380);
    CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));CHECK(mapped[0]==0xa5 && info.image_base==0xabcdef);
    fixture();put16(0x86,2);put32(0x1a8,0x100);put32(0x1ac,0x1100);put32(0x1b0,0x80);put32(0x1b4,0x300);
    CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));CHECK(mapped[0]==0xa5);
    fixture();CHECK(!mh_pe32_map_image(file,0x100,&mem,&info));CHECK(mapped[0]==0xa5);
    fixture();put16(0x84,0x8664);CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();put32(0x3c,0xfffffff0);CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();put32(0x184,0xfffffff0);CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();put32(0x18c,0xfffffff0);CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();put32(0xd4,0x180);CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();put16(0x86,97);CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();put32(0xa8,0x2000);CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();CHECK(!mh_pe32_map_image(file,sizeof file,&mem,(mh_pe32_info *)(mapped+0x100)));
    CHECK(mapped[0]==0xa5 && mapped[0x100]==0xa5);
    fixture();CHECK(!mh_pe32_map_image(file,sizeof file,&mem,(mh_pe32_info *)(file+0x100)));
    CHECK(file[0]=='M');
    fixture();mem.guest_base=0x500000;CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();put32(0xb4,0xfffff000);mem.guest_base=0xfffff000;
    CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));
    fixture();mem.bytes=file;mem.size=0x2000;mem.guest_base=0x400000;
    CHECK(!mh_pe32_map_image(file,sizeof file,&mem,&info));CHECK(file[0]=='M');
    imports_fixture();CHECK(mh_mem_init(&mem,mapped,sizeof mapped,0x400000));
    CHECK(mh_pe32_map_image(file,sizeof file,&mem,&info));
    size_t count=99;unsigned visited=0;
    CHECK(mh_pe32_visit_imports(&mem,&info,inspect_import,&visited,&count));CHECK(count==2 && visited==2);
    count=99;CHECK(mh_pe32_visit_imports(&mem,&info,NULL,NULL,&count) && count==2);
    count=99;CHECK(!mh_pe32_visit_imports(&mem,&info,reject_import,NULL,&count) && count==99);
    mapped[0x1044]=0x01;mapped[0x1045]=0x20;mapped[0x1046]=0;mapped[0x1047]=0;
    count=99;visited=0;CHECK(!mh_pe32_visit_imports(&mem,&info,inspect_import,&visited,&count));
    CHECK(count==99 && visited==0); /* Bad second entry must not emit the first. */
    imports_fixture();CHECK(mh_pe32_map_image(file,sizeof file,&mem,&info));
    mapped[0x1046]=1; /* Reserved ordinal bit, after a valid first entry. */
    count=99;visited=0;CHECK(!mh_pe32_visit_imports(&mem,&info,inspect_import,&visited,&count));
    CHECK(count==99 && visited==0);
    imports_fixture();CHECK(mh_pe32_map_image(file,sizeof file,&mem,&info));
    CHECK(!mh_pe32_visit_imports(&mem,&info,NULL,NULL,(size_t *)(mapped+0x100)));
    imports_fixture();CHECK(mh_pe32_map_image(file,sizeof file,&mem,&info));
    mh_import_plan_entry plan[2];size_t planned=99,missing=99;uint32_t value=9;
#ifdef MH_TEST_IMPORT_REGISTRY
    mh_import_binding bindings[]={{"FOO.DLL","Bar",0,0x70000001u},{"foo.dll",0,7,0x70000002u}};
    mh_import_registry registry={bindings,1};
    CHECK(mh_pe32_plan_imports(&mem,&info,mh_import_registry_resolve,&registry,plan,2,&planned,&missing));
    CHECK(planned==2 && missing==1 && !mh_pe32_apply_import_plan(&mem,plan,planned));
    CHECK(mh_mem_read_u32(&mem,0x401050,&value) && value==0);
    registry.count=2;
    CHECK(mh_pe32_plan_imports(&mem,&info,mh_import_registry_resolve,&registry,plan,2,&planned,&missing));
    CHECK(planned==2 && missing==0 && mh_pe32_apply_import_plan(&mem,plan,planned));
    CHECK(mh_mem_read_u32(&mem,0x401050,&value) && value==0x70000001u);
    CHECK(mh_mem_read_u32(&mem,0x401054,&value) && value==0x70000002u);
    imports_fixture();CHECK(mh_pe32_map_image(file,sizeof file,&mem,&info));
#endif
    CHECK(mh_pe32_plan_imports(&mem,&info,NULL,NULL,plan,2,&planned,&missing));
    CHECK(planned==2 && missing==2 && !plan[0].resolved && !plan[1].resolved);
    CHECK(!mh_pe32_apply_import_plan(&mem,plan,planned));
    CHECK(mh_mem_read_u32(&mem,0x401050,&value) && value==0);
    int mode=1;planned=missing=99;
    CHECK(mh_pe32_plan_imports(&mem,&info,resolve_import,&mode,plan,2,&planned,&missing));
    CHECK(planned==2 && missing==1 && !mh_pe32_apply_import_plan(&mem,plan,planned));
    mode=2;planned=missing=99;
    CHECK(!mh_pe32_plan_imports(&mem,&info,resolve_import,&mode,plan,2,&planned,&missing));
    CHECK(planned==99 && missing==99);
    mode=0;planned=missing=99;
    CHECK(!mh_pe32_plan_imports(&mem,&info,resolve_import,&mode,plan,1,&planned,&missing));
    CHECK(planned==99 && missing==99 && mh_mem_read_u32(&mem,0x401050,&value) && value==0);
    mode=0;CHECK(mh_pe32_plan_imports(&mem,&info,resolve_import,&mode,plan,2,&planned,&missing));
    CHECK(planned==2 && missing==0);
    CHECK(mh_mem_write_u32(&mem,0x401050,3));CHECK(!mh_pe32_apply_import_plan(&mem,plan,planned));
    CHECK(mh_mem_read_u32(&mem,0x401054,&value) && value==0);
    CHECK(mh_mem_write_u32(&mem,0x401050,0));
    CHECK(mh_mem_write_u32(&mem,0x401054,3));CHECK(!mh_pe32_apply_import_plan(&mem,plan,planned));
    CHECK(mh_mem_read_u32(&mem,0x401050,&value) && value==0);
    CHECK(mh_mem_write_u32(&mem,0x401054,0));
    uint32_t saved=plan[1].iat_address;plan[1].iat_address=plan[0].iat_address;
    CHECK(!mh_pe32_apply_import_plan(&mem,plan,planned));plan[1].iat_address=saved;
    plan[1].iat_address=plan[0].iat_address+1;
    CHECK(!mh_pe32_apply_import_plan(&mem,plan,planned));plan[1].iat_address=saved;
    CHECK(mh_pe32_apply_import_plan(&mem,plan,planned));
    CHECK(mh_mem_read_u32(&mem,0x401050,&value) && value==0x70000001u);
    CHECK(mh_mem_read_u32(&mem,0x401054,&value) && value==0x70000002u);
    CHECK(!mh_pe32_apply_import_plan(&mem,plan,planned)); /* snapshots no longer match */
    return 0;
}
#ifndef MH_NO_MAIN
int main(void){return mh_pe_tests();}
#endif
