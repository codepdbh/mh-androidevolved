#include "pe32_import_plan.h"

#define MH_MAX_PLAN 4096u
typedef struct {
    const mh_guest_memory *region;mh_import_resolver resolver;void *user;
    mh_import_plan_entry *entries;size_t capacity,used,missing;
} builder;
static int overlaps(const void *a,size_t asize,const void *b,size_t bsize){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    if(!asize||!bsize)return 0;
    return x<=y ? y-x<asize : x-y<bsize;
}
static int slots_overlap(uint32_t a,uint32_t b){
    return (uint64_t)a<(uint64_t)b+4 && (uint64_t)b<(uint64_t)a+4;
}
static int append_import(const mh_pe32_import *item,void *context){
    builder *b=context;
    if(b->used>=b->capacity)return 0;
    for(size_t i=0;i<b->used;i++)if(slots_overlap(b->entries[i].iat_address,item->iat_address))return 0;
    uint32_t old,target=0;
    if(!mh_mem_read_u32(b->region,item->iat_address,&old))return 0;
    int status=b->resolver?b->resolver(item,b->user,&target):MH_IMPORT_MISSING;
    if(status!=MH_IMPORT_MISSING && status!=MH_IMPORT_FOUND)return 0;
    if(status==MH_IMPORT_FOUND && !target)return 0;
    mh_import_plan_entry *e=&b->entries[b->used++];
    e->iat_address=item->iat_address;e->original_value=old;
    e->target=status==MH_IMPORT_FOUND?target:0;e->resolved=status==MH_IMPORT_FOUND;
    if(!e->resolved)b->missing++;
    return 1;
}
int mh_pe32_plan_imports(const mh_guest_memory *region,const mh_pe32_info *info,
                         mh_import_resolver resolver,void *context,mh_import_plan_entry *entries,
                         size_t capacity,size_t *count,size_t *missing){
    if(!region||!region->bytes||!info||!count||!missing||capacity>MH_MAX_PLAN||(!entries && capacity))return 0;
    size_t bytes=capacity*sizeof *entries;
    if(overlaps(entries,bytes,region->bytes,region->size)||overlaps(count,sizeof *count,region->bytes,region->size)||
       overlaps(missing,sizeof *missing,region->bytes,region->size)||overlaps(count,sizeof *count,missing,sizeof *missing)||
       overlaps(entries,bytes,count,sizeof *count)||overlaps(entries,bytes,missing,sizeof *missing)||
       overlaps(entries,bytes,region,sizeof *region)||overlaps(entries,bytes,info,sizeof *info)||
       overlaps(count,sizeof *count,region,sizeof *region)||overlaps(count,sizeof *count,info,sizeof *info)||
       overlaps(missing,sizeof *missing,region,sizeof *region)||overlaps(missing,sizeof *missing,info,sizeof *info))return 0;
    builder b={region,resolver,context,entries,capacity,0,0};size_t total=0;
    if(!mh_pe32_visit_imports(region,info,append_import,&b,&total) || total!=b.used)return 0;
    *count=b.used;*missing=b.missing;return 1;
}
int mh_pe32_apply_import_plan(mh_guest_memory *region,const mh_import_plan_entry *entries,size_t count){
    if(!region||!region->bytes||count>MH_MAX_PLAN||(!entries && count))return 0;
    if(overlaps(entries,count*sizeof *entries,region->bytes,region->size)||
       overlaps(entries,count*sizeof *entries,region,sizeof *region))return 0;
    for(size_t i=0;i<count;i++){
        uint32_t current;
        if(entries[i].resolved!=1 || !entries[i].target ||
           !mh_mem_read_u32(region,entries[i].iat_address,&current) || current!=entries[i].original_value)return 0;
        for(size_t j=0;j<i;j++)if(slots_overlap(entries[j].iat_address,entries[i].iat_address))return 0;
    }
    for(size_t i=0;i<count;i++)
        if(!mh_mem_write_u32(region,entries[i].iat_address,entries[i].target))return 0;
    return 1;
}
