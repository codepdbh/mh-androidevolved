#include "import_registry.h"
#define CHECK(x) do{if(!(x))return __LINE__;}while(0)
int mh_registry_tests(void){
    mh_import_binding bindings[]={{"KERNEL32.DLL","GetTickCount",0,0x12340000u},{"x.dll",0,27,0x12340004u}};
    mh_import_registry r={bindings,2};uint32_t out=77;
    mh_pe32_import item={"kernel32.dll","GetTickCount",0,0,0};
    CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_FOUND&&out==0x12340000u);
    item.name="gettickcount";out=77;
    CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_MISSING&&out==77);
    item.dll="X.DLL";item.name=0;item.by_ordinal=1;item.ordinal=27;
    CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_FOUND&&out==0x12340004u);
    item.ordinal=28;out=77;CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_MISSING&&out==77);
    bindings[1]=bindings[0];bindings[1].dll="kernel32.dll";
    CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_ERROR&&out==77);
    bindings[1].name="Different";bindings[1].guest_target=0;
    CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_ERROR&&out==77);
    r.count=0;r.entries=0;CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_MISSING&&out==77);
    item.by_ordinal=2;CHECK(mh_import_registry_resolve(&item,&r,&out)==MH_IMPORT_ERROR);
    return 0;
}
