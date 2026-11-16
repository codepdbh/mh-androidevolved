/* In-app self-test of the public runtime pieces; contains no game code.
 * - guest memory bounds, checked rep movs and x87 NaN semantics;
 * - real read-only reads of a user-selected file through the descriptor
 *   backend used by the translated ReadFile wrapper, compared with the bytes
 *   Java already verified by SHA-256. */
#include <jni.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "guest_memory.h"
#include "readonly_stream.h"
#include "checked_memory_adapter.h"
#define MH_X87_CHECKS_NO_MAIN
#include "test_x87_semantics.c"

/* Required by the checked adapter; only the self-test uses it in this library. */
mh_guest_memory mh_recomp_region;
static jmp_buf selftest_fault;
static uint32_t selftest_fault_address;
void mh_guest_fault(uint32_t address, size_t width) {
    (void)width;
    selftest_fault_address = address;
    longjmp(selftest_fault, 1);
}

static int check_guest_memory(void) {
    static uint8_t bytes[4096];
    mh_guest_memory m;
    uint32_t v = 0;
    if (!mh_mem_init(&m, bytes, sizeof bytes, 0x10000)) return 0;
    if (!mh_mem_write_u32(&m, 0x10ffc, 0x11223344u) || !mh_mem_read_u32(&m, 0x10ffc, &v) || v != 0x11223344u) return 0;
    if (bytes[4092] != 0x44 || bytes[4095] != 0x11) return 0;               /* little-endian guest layout */
    if (mh_mem_write_u32(&m, 0x10ffd, 1) || mh_mem_read_u32(&m, 0xfffc, &v)) return 0; /* both ends rejected */
    return 1;
}

/* x86 semantics: element by element, reads after earlier writes. */
static void model_movs(uint8_t *mem, uint32_t base, uint32_t edi, uint32_t esi, uint32_t n, uint32_t esz, int df) {
    for (uint32_t i = 0; i < n; i++) {
        memcpy(mem + (edi - base), mem + (esi - base), esz);
        edi += (uint32_t)(df * (int)esz); esi += (uint32_t)(df * (int)esz);
    }
}
static unsigned check_rep_movs(int *fault_ok) {
    static uint8_t guest[256], model[256];
    const uint32_t base = 0x1000u;
    unsigned cases = 0;
    if (!mh_mem_init(&mh_recomp_region, guest, sizeof guest, base)) return 0;
    for (uint32_t esz = 1; esz <= 4; esz *= 2) for (int df = -1; df <= 1; df += 2)
    for (uint32_t n = 1; n <= 12; n++) for (uint32_t d = 0; d < 24; d += 5) for (uint32_t r = 0; r < 24; r += 7) {
        uint32_t b = n * esz;
        uint32_t edi = base + 64 + d + (df < 0 ? b - esz : 0), esi = base + 64 + r + (df < 0 ? b - esz : 0);
        for (unsigned i = 0; i < sizeof guest; i++) guest[i] = model[i] = (uint8_t)(i * 37 + 5);
        if (setjmp(selftest_fault) != 0) return 0;
        mh_recomp_rep_movs(edi, esi, n, esz, df);
        model_movs(model, base, edi, esi, n, esz, df);
        if (memcmp(guest, model, sizeof guest)) return 0;
        cases++;
    }
    /* A copy past the end must fault before writing anything. */
    for (unsigned i = 0; i < sizeof guest; i++) guest[i] = model[i] = (uint8_t)i;
    *fault_ok = 0;
    if (setjmp(selftest_fault) == 0) mh_recomp_rep_movs(base + 250, base, 16, 1, 1);
    else *fault_ok = selftest_fault_address == base + 250 && !memcmp(guest, model, sizeof guest);
    return cases;
}

JNIEXPORT jstring JNICALL
Java_com_manhuntae_android_MainActivity_nativeRunSelfTest(JNIEnv *env, jclass type) {
    (void)type;
    char text[512];
    int fault_ok = 0;
    int memory_ok = check_guest_memory();
    unsigned movs = check_rep_movs(&fault_ok);
    int x87_ok = mh_x87_semantic_checks() == 0;
    snprintf(text, sizeof text,
             "Autodiagnóstico ARM64 del runtime:\n"
             "· Memoria invitada con límites: %s\n"
             "· rep movs comprobado: %s (%u casos frente al modelo x86; copia fuera de rango %s)\n"
             "· Semántica x87 (NaN indefinido, ±inf): %s",
             memory_ok ? "correcta" : "FALLO",
             movs && fault_ok ? "correcto" : "FALLO", movs, fault_ok ? "rechazada sin escribir" : "NO rechazada",
             x87_ok ? "correcta" : "FALLO");
    return (*env)->NewStringUTF(env, text);
}

JNIEXPORT jstring JNICALL
Java_com_manhuntae_android_MainActivity_nativeReadDescriptor(JNIEnv *env, jclass type, jint fd, jbyteArray expected) {
    (void)type;
    char text[512];
    const uint32_t base = 0x10000u, buffer = 0x20000u, count_at = 0x10000u;
    jsize size = expected ? (*env)->GetArrayLength(env, expected) : 0;
    if (size <= 0 || size > 32 * 1024 * 1024) return (*env)->NewStringUTF(env, "Lectura nativa: tamaño no admitido.");
    size_t region = (size_t)(buffer - base) + (size_t)size;
    uint8_t *bytes = calloc(1, region);
    jbyte *want = bytes ? (*env)->GetByteArrayElements(env, expected, NULL) : NULL;
    if (!bytes || !want) { free(bytes); return (*env)->NewStringUTF(env, "Lectura nativa: sin memoria."); }
    mh_guest_memory m;
    mh_readonly_stream s = MH_READONLY_STREAM_INIT;
    uint32_t got = 0, total = 0, calls = 0, eof = 1, lfanew = 0;
    int rc = mh_mem_init(&m, bytes, region, base) ? mh_ro_open_descriptor(&s, fd) : MH_RO_INVALID;
    /* Sequential reads of at most 1 MiB, as the translated ReadFile wrapper issues them. */
    while (rc == MH_RO_OK && total < (uint32_t)size) {
        uint32_t chunk = (uint32_t)size - total;
        if (chunk > 1024u * 1024u) chunk = 1024u * 1024u;
        rc = mh_ro_read_guest(&s, &m, buffer + total, chunk, count_at, 0);
        if (rc == MH_RO_OK && (!mh_mem_read_u32(&m, count_at, &got) || got == 0)) rc = MH_RO_IO;
        if (rc == MH_RO_OK) { total += got; calls++; }
    }
    /* At end of file a read succeeds with zero bytes. */
    if (rc == MH_RO_OK) rc = mh_ro_read_guest(&s, &m, buffer, 16, count_at, 0);
    if (rc == MH_RO_OK && mh_mem_read_u32(&m, count_at, &eof) != 1) rc = MH_RO_IO;
    /* Random access: e_lfanew from the DOS header, read through a seek. */
    if (rc == MH_RO_OK) rc = mh_ro_seek(&s, 0x3c);
    if (rc == MH_RO_OK) rc = mh_ro_read_guest(&s, &m, base + 4, 4, count_at, 0);
    if (rc == MH_RO_OK) mh_mem_read_u32(&m, base + 4, &lfanew);
    int overlapped_rejected = mh_ro_read_guest(&s, &m, buffer, 16, count_at, 1) == MH_RO_UNSUPPORTED;
    mh_ro_close(&s);
    int same = rc == MH_RO_OK && total == (uint32_t)size && !memcmp(bytes + (buffer - base), want, (size_t)size);
    uint32_t want_lfanew = size >= 0x40 ? (uint32_t)(uint8_t)want[0x3c] | (uint32_t)(uint8_t)want[0x3d] << 8 |
                                          (uint32_t)(uint8_t)want[0x3e] << 16 | (uint32_t)(uint8_t)want[0x3f] << 24 : 0;
    (*env)->ReleaseByteArrayElements(env, expected, want, JNI_ABORT);
    free(bytes);
    snprintf(text, sizeof text,
             "Lectura real por descriptor (capa de solo lectura del port):\n"
             "· %u bytes en %u lecturas de hasta 1 MiB a memoria invitada: %s\n"
             "· Fin de archivo devuelve 0 bytes: %s · desplazamiento a e_lfanew (0x%x): %s\n"
             "· Lectura OVERLAPPED rechazada: %s",
             total, calls, same ? "idénticos a los verificados por SHA-256" : "DIFERENTES o error",
             eof == 0 ? "sí" : "NO", lfanew, rc == MH_RO_OK && lfanew == want_lfanew ? "correcto" : "FALLO",
             overlapped_rejected ? "sí" : "NO");
    return (*env)->NewStringUTF(env, text);
}
