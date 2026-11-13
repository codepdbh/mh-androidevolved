/* Tests JNI entry points with a minimal fake JNI table and a read-only PE file. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <jni.h>
#include "../runtime/guest_memory.c"
#include "../runtime/pe32_image.c"
#include "../runtime/pe32_imports.c"
#include "../android/app/src/main/cpp/native_diagnostics.c"

typedef struct { jbyte *bytes; jsize size; } fake_array;
static int gets,releases,last_mode;
static jstring fake_string(JNIEnv *env,const char *text){(void)env;return (jstring)text;}
static jsize fake_length(JNIEnv *env,jarray array){(void)env;return ((fake_array *)array)->size;}
static jbyte *fake_get(JNIEnv *env,jbyteArray array,jboolean *copy){(void)env;(void)copy;gets++;return ((fake_array *)array)->bytes;}
static void fake_release(JNIEnv *env,jbyteArray array,jbyte *bytes,jint mode){
    (void)env;if(bytes!=((fake_array *)array)->bytes)exit(21);releases++;last_mode=mode;
}
int main(int argc,char **argv){
    if(argc!=2)return 2;
    struct JNINativeInterface table={0};
    table.NewStringUTF=fake_string;table.GetArrayLength=fake_length;
    table.GetByteArrayElements=fake_get;table.ReleaseByteArrayElements=fake_release;
    JNIEnv env=&table;
    const char *message=(const char *)Java_com_manhuntae_android_MainActivity_nativeGetRuntimeDiagnostic(&env,NULL);
    if(!message || !strstr(message,"correcta"))return 3;
    fake_array data={NULL,1};
    message=(const char *)Java_com_manhuntae_android_MainActivity_nativeInspectKnownPe(&env,NULL,(jbyteArray)&data);
    if(!message || !strstr(message,"No se pudo") || gets || releases)return 4;
    FILE *input=NULL;if(fopen_s(&input,argv[1],"rb")!=0 || !input)return 5;
    data.size=6304256;data.bytes=(jbyte *)malloc((size_t)data.size);
    if(!data.bytes){fclose(input);return 6;}
    size_t read=fread(data.bytes,1,(size_t)data.size,input);int extra=fgetc(input);fclose(input);
    if(read!=(size_t)data.size || extra!=EOF){free(data.bytes);return 7;}
    message=(const char *)Java_com_manhuntae_android_MainActivity_nativeInspectKnownPe(&env,NULL,(jbyteArray)&data);
    if(!message || !strstr(message,"importaciones comprobadas") || gets!=1 || releases!=1 || last_mode!=JNI_ABORT){free(data.bytes);return 8;}
    data.bytes[0]=0;
    message=(const char *)Java_com_manhuntae_android_MainActivity_nativeInspectKnownPe(&env,NULL,(jbyteArray)&data);
    if(!message || !strstr(message,"fall") || gets!=2 || releases!=2 || last_mode!=JNI_ABORT){free(data.bytes);return 9;}
    free(data.bytes);puts("fake JNI: diagnostic, size rejection, valid PE and invalid PE passed");return 0;
}
