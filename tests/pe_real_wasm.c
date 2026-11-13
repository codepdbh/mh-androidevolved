/* Read-only local PE mapping check. Input bytes and mapped image live in WASM memory only. */
#include <stdint.h>
#include "pe32_image.h"
#include "pe32_imports.h"
#include "pe32_import_plan.h"
#define LIMIT (8u*1024u*1024u)
static uint8_t source[LIMIT],image[LIMIT];
static mh_pe32_info info;
typedef struct {uint32_t dll,name,by_ordinal,ordinal,iat;} record;
static record records[2048];
static mh_import_plan_entry plan[2048];
static uint32_t used;
static int capture(const mh_pe32_import *item,void *context){
    (void)context;if(used>=2048)return 0;
    records[used].dll=(uint32_t)((const uint8_t *)item->dll-image);
    records[used].name=item->name?(uint32_t)((const uint8_t *)item->name-image):0;
    records[used].by_ordinal=(uint32_t)item->by_ordinal;records[used].ordinal=item->ordinal;
    records[used].iat=item->iat_address;used++;return 1;
}
uintptr_t pe_source(void){return (uintptr_t)source;}
uintptr_t pe_image(void){return (uintptr_t)image;}
uint32_t pe_capacity(void){return LIMIT;}
uint32_t pe_size(void){return info.image_size;}
uint32_t pe_entry(void){return info.entry_rva;}
uint32_t pe_map(uint32_t length){
    mh_guest_memory memory;
    if(length>LIMIT || !mh_mem_init(&memory,image,LIMIT,0x400000))return 0;
    return (uint32_t)mh_pe32_map_image(source,length,&memory,&info);
}
int32_t pe_collect_imports(void){
    mh_guest_memory memory;size_t count=0;used=0;
    if(!mh_mem_init(&memory,image,LIMIT,0x400000) || !mh_pe32_visit_imports(&memory,&info,capture,NULL,&count) || count!=used)return -1;
    return (int32_t)used;
}
uint32_t pe_import(uint32_t index,uint32_t field){
    if(index>=used)return UINT32_MAX;
    switch(field){case 0:return records[index].dll;case 1:return records[index].name;case 2:return records[index].by_ordinal;case 3:return records[index].ordinal;case 4:return records[index].iat;default:return UINT32_MAX;}
}
int32_t pe_plan_missing(void){
    mh_guest_memory memory;size_t count=0,missing=0;
    if(!mh_mem_init(&memory,image,LIMIT,0x400000) ||
       !mh_pe32_plan_imports(&memory,&info,NULL,NULL,plan,2048,&count,&missing) ||
       count!=missing || mh_pe32_apply_import_plan(&memory,plan,count))return -1;
    return (int32_t)missing;
}
