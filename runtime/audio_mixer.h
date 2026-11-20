#ifndef MH_AUDIO_MIXER_H
#define MH_AUDIO_MIXER_H
/* Software mixer for the port's Miles 3D samples (mh_port_set_audio): output only.
 *
 * Each voice plays its sample from guest memory: 16/8-bit PCM is read where the game keeps it
 * (streamed music is refilled in place while it loops), IMA ADPCM is decoded when the sample
 * starts. Rate (the sample's or its playback rate), volume, loop count and loop block as Miles
 * defines them. Output: interleaved stereo 16-bit at the mixer's rate. mh_mixer_sound may be
 * called from the game thread while mh_mixer_render runs on the audio thread (a mutex). */
#include <stdint.h>
#include "guest_memory.h"
#include "port_api.h"

typedef struct mh_mixer mh_mixer;
mh_mixer *mh_mixer_create(mh_guest_memory *memory, unsigned rate);
void mh_mixer_destroy(mh_mixer *m);
/* An mh_port_audio that feeds this mixer. */
void mh_mixer_bind(mh_mixer *m, mh_port_audio *out);
void mh_mixer_sound(mh_mixer *m, const mh_port_sound *sound, int event);
void mh_mixer_render(mh_mixer *m, int16_t *out, unsigned frames);
void mh_mixer_set_gain(mh_mixer *m, float gain);
#endif
