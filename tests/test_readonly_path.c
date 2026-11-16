#include "readonly_path.h"
#include <stdio.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){printf("failed line %d\n",__LINE__);return 1;}}while(0)
int main(void){
    char output[1024],before[1024];
    const char *bad[]={"","/a","\\a","C:\\a","../a","a/../b","./a","a/./b","a//b","a\\\\b","a/","a:","\\\\server\\a","a\x01"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++){
        memset(output,0xa5,sizeof output);memcpy(before,output,sizeof output);
        CHECK(!mh_ro_normalize_relative(bad[i],output,sizeof output));CHECK(!memcmp(before,output,sizeof output));
    }
    const char *good[]={"a","a/b","level.1","..archive","folder name/file","a\\b\\c"};
    const char *wanted[]={"a","a/b","level.1","..archive","folder name/file","a/b/c"};
    for(unsigned i=0;i<sizeof good/sizeof good[0];i++){CHECK(mh_ro_normalize_relative(good[i],output,sizeof output));CHECK(!strcmp(output,wanted[i]));}
    char component[257];memset(component,'a',256);component[256]=0;
    CHECK(!mh_ro_normalize_relative(component,output,sizeof output));component[255]=0;
    CHECK(mh_ro_normalize_relative(component,output,sizeof output));
    char longest[1025];
    for(unsigned i=0;i<1023;i++){longest[i]=(i==255||i==511||i==767)?'/':'a';}
    longest[1023]=0;
    CHECK(mh_ro_normalize_relative(longest,output,sizeof output));
    longest[1023]='a';longest[1024]=0;CHECK(!mh_ro_normalize_relative(longest,output,sizeof output));
    CHECK(!mh_ro_normalize_relative("abc",output,3));CHECK(mh_ro_normalize_relative("abc",output,4));
    char same[16]="a\\b";CHECK(mh_ro_normalize_relative(same,same,sizeof same)&&!strcmp(same,"a/b"));
    CHECK(!mh_ro_normalize_relative(NULL,output,sizeof output));CHECK(!mh_ro_normalize_relative("a",NULL,1));
    puts("relative path validation, unchanged failures, bounds and alias checks passed");return 0;
}
