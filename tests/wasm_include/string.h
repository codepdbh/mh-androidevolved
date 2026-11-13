#ifndef MH_TEST_STRING_H
#define MH_TEST_STRING_H
#include <stddef.h>
void *memmove(void *destination, const void *source, size_t size);
void *memcpy(void *destination, const void *source, size_t size);
void *memset(void *destination, int value, size_t size);
#endif
