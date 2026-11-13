#include "pe32_imports.h"

static int u16(const uint8_t *b,size_t n,uint32_t p,uint16_t *v){
    if((size_t)p>n || n-(size_t)p<2)return 0;
    *v=(uint16_t)(b[p]|((uint16_t)b[p+1]<<8));return 1;
}
static int u32(const uint8_t *b,size_t n,uint32_t p,uint32_t *v){
    if((size_t)p>n || n-(size_t)p<4)return 0;
    *v=(uint32_t)b[p]|((uint32_t)b[p+1]<<8)|((uint32_t)b[p+2]<<16)|((uint32_t)b[p+3]<<24);return 1;
}
static const char *text_at(const uint8_t *b,size_t n,uint32_t p){
    if((size_t)p>=n)return NULL;
    size_t max=n-(size_t)p;if(max>512)max=512;
    for(size_t i=0;i<max;i++)if(!b[p+i])return i?(const char *)(b+p):NULL;
    return NULL;
}
static int imports_overlap(const void *a,size_t asize,const void *b,size_t bsize){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    if(!asize||!bsize)return 0;
    return x<=y ? y-x<asize : x-y<bsize;
}
static int visit(const uint8_t *b,uint32_t n,uint32_t base,uint32_t dir,uint32_t size,
                 mh_pe32_import_visitor visitor,void *ctx,size_t *total){
    uint32_t pos=dir,end=dir+size;size_t number=0;
    while(pos<=end && end-pos>=20){
        uint32_t lookup,timestamp,chain,dll_rva,iat;
        if(!u32(b,n,pos,&lookup)||!u32(b,n,pos+4,&timestamp)||!u32(b,n,pos+8,&chain)||
           !u32(b,n,pos+12,&dll_rva)||!u32(b,n,pos+16,&iat))return 0;
        pos+=20;
        if(!(lookup|timestamp|chain|dll_rva|iat)){*total=number;return 1;}
        const char *dll=text_at(b,n,dll_rva);
        if(!dll || !iat)return 0;
        if(!lookup)lookup=iat;
        for(uint32_t i=0;i<65536;i++){
            uint64_t source=(uint64_t)lookup+(uint64_t)i*4,slot=(uint64_t)iat+(uint64_t)i*4;
            if(source+4>n || slot+4>n)return 0;
            uint32_t value;if(!u32(b,n,(uint32_t)source,&value))return 0;
            if(!value)break;
            mh_pe32_import item={0};item.dll=dll;item.iat_address=base+(uint32_t)slot;
            if(value&0x80000000u){
                if(value&0x7fff0000u)return 0; /* Reserved ordinal bits must be zero. */
                item.by_ordinal=1;item.ordinal=(uint16_t)value;
            }
            else {
                uint16_t hint;
                if(value>UINT32_MAX-2 || !u16(b,n,value,&hint))return 0;
                item.name=text_at(b,n,value+2);if(!item.name)return 0;
            }
            if(++number>65536)return 0;
            if(visitor && !visitor(&item,ctx))return 0;
            if(i==65535)return 0;
        }
    }
    return 0; /* A zero descriptor must fit inside the directory. */
}
int mh_pe32_visit_imports(const mh_guest_memory *region,const mh_pe32_info *info,
                          mh_pe32_import_visitor visitor,void *context,size_t *count){
    if(!region||!region->bytes||!info||!count||region->guest_base!=info->image_base||
       !info->image_size||region->size<info->image_size ||
       (uint64_t)info->image_base+info->image_size>UINT64_C(0x100000000))return 0;
    if(imports_overlap(count,sizeof *count,region->bytes,info->image_size) ||
       imports_overlap(count,sizeof *count,region,sizeof *region) || imports_overlap(count,sizeof *count,info,sizeof *info))return 0;
    const uint8_t *b=region->bytes;uint32_t n=info->image_size,pe,signature,base,image_size,dirs,dir,size;
    uint16_t mz,machine,magic,opt_size;
    if(!u16(b,n,0,&mz)||mz!=0x5a4d||!u32(b,n,0x3c,&pe)||pe>n || n-pe<24 ||
       !u32(b,n,pe,&signature)||signature!=0x4550||!u16(b,n,pe+4,&machine)||machine!=0x14c||
       !u16(b,n,pe+20,&opt_size)||opt_size<96 || (uint64_t)pe+24+opt_size>n)return 0;
    uint32_t opt=pe+24;
    if(!u16(b,n,opt,&magic)||magic!=0x10b||!u32(b,n,opt+28,&base)||base!=info->image_base||
       !u32(b,n,opt+56,&image_size)||image_size!=n||!u32(b,n,opt+92,&dirs))return 0;
    if(dirs<2){*count=0;return 1;}
    if(opt_size<112 || !u32(b,n,opt+104,&dir)||!u32(b,n,opt+108,&size))return 0;
    if(!dir && !size){*count=0;return 1;}
    if(!dir || size<20 || dir>n || size>n-dir)return 0;
    size_t validated=0,emitted=0;
    if(!visit(b,n,base,dir,size,NULL,NULL,&validated))return 0;
    if(visitor && !visit(b,n,base,dir,size,visitor,context,&emitted))return 0;
    *count=validated;return 1;
}
