#include "readonly_path.h"
#include <string.h>
int mh_ro_normalize_relative(const char *name,char *output,size_t capacity){
    if(!name||!output)return 0;
    char path[MH_RO_PATH_CAPACITY];size_t length=0;
    for(;length<sizeof path;length++){
        unsigned char c=(unsigned char)name[length];
        if(!c)break;
        if(c==':'||c<32)return 0;
        path[length]=c=='\\'?'/':(char)c;
    }
    if(!length||length==sizeof path||capacity<=length)return 0;
    path[length]=0;
    for(size_t start=0,i=0;i<=length;i++)if(!path[i]||path[i]=='/'){
        size_t n=i-start;
        if(!n||n>255||(n==1&&path[start]=='.')||(n==2&&path[start]=='.'&&path[start+1]=='.'))return 0;
        start=i+1;
    }
    memmove(output,path,length+1);return 1;
}
