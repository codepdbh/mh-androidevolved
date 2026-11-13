#include "pe32_image.h"
#include <string.h>

static int read16(const uint8_t *p,size_t n,size_t off,uint16_t *v) {
    if(off>n || n-off<2)return 0;
    *v=(uint16_t)((uint16_t)p[off]|((uint16_t)p[off+1]<<8));return 1;
}
static int read32(const uint8_t *p,size_t n,size_t off,uint32_t *v) {
    if(off>n || n-off<4)return 0;
    *v=(uint32_t)p[off]|((uint32_t)p[off+1]<<8)|((uint32_t)p[off+2]<<16)|((uint32_t)p[off+3]<<24);return 1;
}
static int overlaps(const void *a,size_t asize,const void *b,size_t bsize) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    if(!asize || !bsize)return 0;
    return x<=y ? y-x<asize : x-y<bsize;
}

int mh_pe32_map_image(const uint8_t *file,size_t file_size,mh_guest_memory *region,mh_pe32_info *out) {
    uint16_t mz,machine,sections,opt_size,magic;uint32_t pe,signature,base,image_size,header_size,entry;
    if(!file || !region || !region->bytes || !out ||
       !read16(file,file_size,0,&mz) || mz!=0x5a4d || !read32(file,file_size,0x3c,&pe))return 0;
    if((size_t)pe>file_size || file_size-(size_t)pe<24)return 0;
    if(!read32(file,file_size,pe,&signature) || signature!=0x00004550 ||
       !read16(file,file_size,(size_t)pe+4,&machine) || machine!=0x14c ||
       !read16(file,file_size,(size_t)pe+6,&sections) || !sections || sections>96 ||
       !read16(file,file_size,(size_t)pe+20,&opt_size) || opt_size<96) return 0;
    size_t opt=(size_t)pe+24;
    if(opt>file_size || opt_size>file_size-opt ||
       !read16(file,file_size,opt,&magic) || magic!=0x10b ||
       !read32(file,file_size,opt+16,&entry) || !read32(file,file_size,opt+28,&base) ||
       !read32(file,file_size,opt+56,&image_size) || !read32(file,file_size,opt+60,&header_size) ||
       !image_size || !header_size || header_size>file_size || header_size>image_size ||
       entry>=image_size || region->guest_base!=base || region->size<image_size ||
       (uint64_t)base+image_size>UINT64_C(0x100000000)) return 0;
    if(overlaps(file,file_size,region->bytes,image_size) ||
       overlaps(out,sizeof *out,file,file_size) || overlaps(out,sizeof *out,region->bytes,image_size) ||
       overlaps(region,sizeof *region,region->bytes,image_size))return 0;
    size_t table=opt+opt_size;
    if(table>file_size || (size_t)sections>(file_size-table)/40 ||
       table+(size_t)sections*40>header_size) return 0;
    /* Validate all sections and pairwise virtual overlap before writing. */
    for(uint16_t i=0;i<sections;i++) {
        size_t s=table+(size_t)i*40;uint32_t vsize,rva,raw,raw_offset;
        if(!read32(file,file_size,s+8,&vsize) || !read32(file,file_size,s+12,&rva) ||
           !read32(file,file_size,s+16,&raw) || !read32(file,file_size,s+20,&raw_offset))return 0;
        uint32_t span=vsize>raw?vsize:raw;
        if(span && (rva<header_size || rva>image_size || span>image_size-rva))return 0;
        if(raw && ((size_t)raw_offset>file_size || (size_t)raw>file_size-raw_offset))return 0;
        for(uint16_t j=0;j<i && span;j++) {
            size_t t=table+(size_t)j*40;uint32_t pv,pr,ps;
            if(!read32(file,file_size,t+8,&pv) || !read32(file,file_size,t+12,&pr) || !read32(file,file_size,t+16,&ps))return 0;
            uint32_t previous=pv>ps?pv:ps;
            if(previous && (uint64_t)rva<(uint64_t)pr+previous && (uint64_t)pr<(uint64_t)rva+span)return 0;
        }
    }
    memset(region->bytes,0,image_size);
    memcpy(region->bytes,file,header_size);
    for(uint16_t i=0;i<sections;i++) {
        size_t s=table+(size_t)i*40;uint32_t rva,raw,raw_offset;
        read32(file,file_size,s+12,&rva);read32(file,file_size,s+16,&raw);read32(file,file_size,s+20,&raw_offset);
        if(raw)memcpy(region->bytes+rva,file+raw_offset,raw);
    }
    out->image_base=base;out->image_size=image_size;out->entry_rva=entry;out->section_count=sections;
    return 1;
}
