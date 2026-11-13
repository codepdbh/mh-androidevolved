#include <stddef.h>
#include <stdint.h>

/* Test-only freestanding implementation. The Android build uses libc memmove. */
void *memmove(void *destination, const void *source, size_t size) {
    unsigned char *d = destination;
    const unsigned char *s = source;
    if ((uintptr_t)d <= (uintptr_t)s) {
        for (size_t i = 0; i < size; ++i) d[i] = s[i];
    } else {
        for (size_t i = size; i > 0; --i) d[i-1] = s[i-1];
    }
    return destination;
}
void *memcpy(void *destination, const void *source, size_t size) {
    unsigned char *d=destination;const unsigned char *s=source;
    for(size_t i=0;i<size;++i)d[i]=s[i];return destination;
}
void *memset(void *destination,int value,size_t size) {
    unsigned char *d=destination;
    for(size_t i=0;i<size;++i)d[i]=(unsigned char)value;return destination;
}
