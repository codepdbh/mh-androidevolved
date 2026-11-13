#include <jni.h>
#include <stdint.h>
#include <stdlib.h>
#include "guest_memory.h"
#include "pe32_image.h"
#include "pe32_imports.h"

/* This diagnostic exercises only a local memory buffer, not the game. */
JNIEXPORT jstring JNICALL
Java_com_manhuntae_android_MainActivity_nativeGetRuntimeDiagnostic(JNIEnv *env, jclass type) {
    uint8_t bytes[8] = {0};
    mh_guest_memory region;
    uint32_t result = 0;
    (void)type;
    const int ok = mh_mem_init(&region, bytes, sizeof bytes, 0x1000) &&
                   mh_mem_write_u32(&region, 0x1001, UINT32_C(0x12345678)) &&
                   mh_mem_read_u32(&region, 0x1001, &result) &&
                   result == UINT32_C(0x12345678) &&
                   !mh_mem_write_u32(&region, 0x1005, 0);
    return (*env)->NewStringUTF(env, ok ? "Memoria nativa: comprobación básica correcta; juego no disponible."
                                        : "Memoria nativa: la comprobación básica falló; juego no disponible.");
}

/* The Java caller checks the hash twice. This maps bytes only; it executes none. */
JNIEXPORT jstring JNICALL
Java_com_manhuntae_android_MainActivity_nativeInspectKnownPe(JNIEnv *env, jclass type, jbyteArray executable) {
    (void)type;
    if (!executable || (*env)->GetArrayLength(env, executable) != 6304256)
        return (*env)->NewStringUTF(env, "No se pudo comprobar la estructura PE del ejecutable.");
    jbyte *bytes = (*env)->GetByteArrayElements(env, executable, NULL);
    if (!bytes) return NULL; /* A pending JNI allocation exception is propagated. */
    const size_t image_size = 0x618000;
    uint8_t *image = (uint8_t *)malloc(image_size);
    if (!image) {
        (*env)->ReleaseByteArrayElements(env, executable, bytes, JNI_ABORT);
        return (*env)->NewStringUTF(env, "No hay memoria suficiente para comprobar el PE.");
    }
    mh_guest_memory region;
    mh_pe32_info info;
    size_t imports = 0;
    int ok = mh_mem_init(&region, image, image_size, 0x400000) &&
             mh_pe32_map_image((const uint8_t *)bytes, 6304256, &region, &info) &&
             info.image_size == image_size && info.entry_rva == 0x451370 && info.section_count == 15 &&
             mh_pe32_visit_imports(&region, &info, NULL, NULL, &imports) && imports == 165;
    free(image);
    (*env)->ReleaseByteArrayElements(env, executable, bytes, JNI_ABORT);
    return (*env)->NewStringUTF(env, ok ? "Ejecutable identificado; estructura PE e importaciones comprobadas. Los demás datos no están verificados; el juego no está disponible."
                                        : "Ejecutable identificado, pero falló la comprobación PE. El juego no está disponible.");
}
