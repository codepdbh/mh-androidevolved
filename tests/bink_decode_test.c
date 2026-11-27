/* Decodes frames of a .bik file with runtime/bink_decoder.c and writes them as PPM images
 * (diagnostics: bink_decode_test file.bik out_prefix first count [step]). Prints a checksum per frame. */
#include "../runtime/bink_decoder.c"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "usage: %s file.bik out_prefix first count [step]\n", argv[0]); return 2; }
    mh_bink *b = mh_bink_open(argv[1]);
    if (!b) { fprintf(stderr, "cannot open %s\n", argv[1]); return 1; }
    uint32_t w, h, n; mh_bink_info(b, &w, &h, &n);
    printf("%ux%u, %u frames\n", w, h, n);
    unsigned first = (unsigned)atoi(argv[3]), count = (unsigned)atoi(argv[4]), step = argc > 5 ? (unsigned)atoi(argv[5]) : 1;
    uint8_t *rgb = malloc((size_t)w * h * 4);
    for (unsigned k = 0; k < count && first + k * step < n; k++) {
        unsigned i = first + k * step;
        if (!mh_bink_decode(b, i)) { printf("frame %u: decode failed\n", i); continue; }
        mh_bink_copy(b, rgb, w * 4, 0, 0, w, h, 1);
        uint32_t sum = 0; for (size_t p = 0; p < (size_t)w * h * 4; p++) sum = sum * 31 + rgb[p];
        printf("frame %u: checksum %08x\n", i, sum);
        char path[512]; snprintf(path, sizeof path, "%s%05u.ppm", argv[2], i);
        FILE *f = fopen(path, "wb");
        if (f) { fprintf(f, "P6\n%u %u\n255\n", w, h); for (size_t p = 0; p < (size_t)w * h; p++) fwrite(rgb + 4 * p, 1, 3, f); fclose(f); }
    }
    free(rgb); mh_bink_close(b);
    return 0;
}
