#include "import_registry.h"

#define MH_REGISTRY_LIMIT 4096u
static unsigned char fold(unsigned char c){return c>='A'&&c<='Z'?(unsigned char)(c+('a'-'A')):c;}
static int equal(const char *a,const char *b,int insensitive){
    if(!a||!b)return 0;
    while(*a&&*b){
        unsigned char x=(unsigned char)*a++,y=(unsigned char)*b++;
        if(insensitive){x=fold(x);y=fold(y);}
        if(x!=y)return 0;
    }
    return *a==*b;
}
static int same_export(const mh_import_binding *a,const mh_import_binding *b){
    if(!equal(a->dll,b->dll,1))return 0;
    if(!a->name||!b->name)return !a->name&&!b->name&&a->ordinal==b->ordinal;
    return equal(a->name,b->name,0);
}
int mh_import_registry_resolve(const mh_pe32_import *item,void *context,uint32_t *target){
    const mh_import_registry *r=context;
    if(!item||!target||!r||(!r->entries&&r->count)||r->count>MH_REGISTRY_LIMIT||
       !item->dll||!*item->dll||(item->by_ordinal!=0&&item->by_ordinal!=1)||
       (!item->by_ordinal&&(!item->name||!*item->name)))return MH_IMPORT_ERROR;
    for(size_t i=0;i<r->count;i++){
        const mh_import_binding *e=&r->entries[i];
        if(!e->dll||!*e->dll||!e->guest_target||(e->name&&!*e->name))return MH_IMPORT_ERROR;
        for(size_t j=0;j<i;j++)if(same_export(e,&r->entries[j]))return MH_IMPORT_ERROR;
    }
    for(size_t i=0;i<r->count;i++){
        const mh_import_binding *e=&r->entries[i];
        if(!equal(e->dll,item->dll,1))continue;
        if(item->by_ordinal?(!e->name&&e->ordinal==item->ordinal):(e->name&&equal(e->name,item->name,0))){
            *target=e->guest_target;return MH_IMPORT_FOUND;
        }
    }
    return MH_IMPORT_MISSING;
}
