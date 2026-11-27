/* Bink 1 video decoder for the port's binkw32 emulation (runtime/port_api.c).
 * Derived from FFmpeg's Bink decoder: runtime/bink_decoder.c and runtime/bink_tables.h are under
 * the GNU LGPL 2.1 or later. Portable C, no dependencies. */
#ifndef MH_BINK_DECODER_H
#define MH_BINK_DECODER_H
#include <stdint.h>

typedef struct mh_bink mh_bink;

/* Opens a .bik file (revisions 'f'..'i' of Bink 1, no alpha). NULL if it cannot be decoded. */
mh_bink *mh_bink_open(const char *path);
void mh_bink_close(mh_bink *b);
void mh_bink_info(const mh_bink *b, uint32_t *width, uint32_t *height, uint32_t *frames);
/* Decodes frame `index` (0-based), stepping from the last decoded one or from the start.
 * Returns 1 on success; the frame stays available to mh_bink_copy until the next decode. */
int mh_bink_decode(mh_bink *b, uint32_t index);
/* The audio decoded with the frames stepped through by the last mh_bink_decode (track 0, DCT
 * variant): interleaved stereo 16-bit at *rate; valid until the next decode. Returns the frames. */
size_t mh_bink_take_audio(mh_bink *b, const int16_t **pcm, unsigned *rate);
/* Converts the rectangle (sx, sy, w, h) of the current frame to `dst` (rows of `pitch` bytes):
 * format 0 = 32-bit B G R X, 1 = 32-bit R G B X, 2 = RGB565. */
void mh_bink_copy(const mh_bink *b, uint8_t *dst, uint32_t pitch, uint32_t sx, uint32_t sy, uint32_t w, uint32_t h, int format);
#endif
