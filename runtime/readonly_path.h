#ifndef MH_READONLY_PATH_H
#define MH_READONLY_PATH_H
#include <stddef.h>
#define MH_RO_PATH_CAPACITY 1024u
/* Host string validation, independent of the filesystem. Failure leaves the
 * output untouched. Slash and backslash normalize to slash; output may alias
 * input. Names are byte-exact, no case folding or character-set conversion. */
int mh_ro_normalize_relative(const char *name,char *output,size_t capacity);
#endif
