#ifndef MH_GAME_RUNNER_H
#define MH_GAME_RUNNER_H
/* Runs the game's boot as translated code over the port (runtime/game_runner.c). */
#include <stdint.h>
#include <stdio.h>
#include "guest_memory.h"
#include "port_api.h"

typedef struct {
    const char *exe_path;                  /* the user's manhunt.exe (verified by size and CRC-32) */
    const char *game_dir;                  /* the game folder, read only */
    unsigned frame_limit;                  /* mh_game_run returns 0 after this many presented frames */
    const mh_port_renderer *renderer;      /* optional: receives the Direct3D device's notifications */
    void *user;
    /* optional: called once the port exists, before any guest code runs */
    void (*on_ready)(void *user, mh_port *port, mh_guest_memory *memory);
    void (*fatal)(void *user, int code);   /* optional: guest fault (must not return); default: exit */
    void (*log)(const char *line);         /* optional: diagnostics (default: stderr) */
    FILE *calllog;                         /* optional: every API/COM call of WinMain (name, return address) */
    int trace_all;                         /* log every call, also during boot phase 2 */
    unsigned langid;                       /* optional: Windows LANGID (0: English, 0x0409) */
    const char *key_script;                /* optional input script, as MH_KEYS of the reference */
    const char *save_dir;                  /* optional host directory that also keeps the saves (default: memory only) */
    int save_readonly;                     /* the save directory only seeds the saves (tests) */
    unsigned dump_at; const char *dump_path;   /* write .data/.bss at the n-th call and exit (bisection) */
} mh_game_config;

/* 0 when frame_limit frames were presented; otherwise an error code (the reason is logged).
 * Faults inside the guest call `fatal` (default: end the process) after logging. */
int mh_game_run(const mh_game_config *config);
mh_port *mh_game_port(void);
uint8_t *mh_game_guest(void);
unsigned mh_game_calls(void);
uint32_t mh_game_crc32(const uint8_t *p, size_t n);
/* The comparison record (the fields of private/analysis/winmain/x86_reference.json). */
void mh_game_print_result(FILE *out);
#endif
