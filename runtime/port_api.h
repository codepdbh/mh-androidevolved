#ifndef MH_PORT_API_H
#define MH_PORT_API_H
/* The port's Win32 / COM / Miles / Bink layer for WinMain and beyond.
 *
 * Same semantics as the x86 reference (tools/winmain_apis.py, documented in
 * docs/WINMAIN_PORT_MODEL.md): every handle value, guest allocation, string and
 * structure written to guest memory is the same, so translated code can be compared
 * with the reference exactly. Deterministic: a virtual millisecond clock (1 ms per
 * query) unless the host replaces it.
 *
 * The host (harness or app) provides guest calls (window/dialog procedures called
 * from inside an API, as Windows does), faults and the frame limit. Single guest
 * thread. Game data is read-only; directories the game creates go to an overlay. */
#include <stddef.h>
#include <stdint.h>
#include "guest_memory.h"

#define MH_PORT_GAME_DIR      "C:\\Manhunt\\"
#define MH_PORT_IMAGE_BASE    0x400000u
#define MH_PORT_SCRATCH       0x1f11000u   /* user32 structures (CREATESTRUCTA) */
#define MH_PORT_MSS_SCRATCH   0x1f12000u   /* Miles strings */
#define MH_PORT_COM_VA        0x1e10000u   /* COM method addresses: + 0x400*interface + 4*method */
#define MH_PORT_COM_HEAP      0x1e40000u
#define MH_PORT_COM_LIMIT     0x1e80000u
#define MH_PORT_RES_BASE      0x10000000u  /* Direct3D resource memory */
#define MH_PORT_RES_LIMIT     0x20000000u

typedef struct mh_port mh_port;
typedef struct {
    void *user;
    /* Calls guest function `fn` (stdcall) with `n` arguments, as the reference does: frame
     * placed at api_esp - 0x40 - 4n with return address `continue_va`; returns its eax. */
    uint32_t (*call_guest)(void *user, uint32_t api_esp, uint32_t fn, const uint32_t *args, unsigned n);
    void (*fault)(void *user, const char *message);          /* must not return */
    void (*frames_reached)(void *user, unsigned frames);     /* must not return */
} mh_port_host;

/* game_dir: host folder of the game; frame_limit: Present raises frames_reached at this count. */
mh_port *mh_port_create(mh_guest_memory *memory, const mh_port_host *host, const char *game_dir, unsigned frame_limit);
void mh_port_destroy(mh_port *port);
/* Shared process state with the phase-2 shims. */
uint32_t *mh_port_last_error(mh_port *port);
uint32_t mh_port_cwd(mh_port *port, char *out, size_t size);

/* Imports: handler index for an import name, or -1 if the port does not provide it. */
int mh_port_find_api(const char *name);
unsigned mh_port_api_args(int api);
const char *mh_port_api_name(int api);
/* Runs import `api` with the guest stack at `esp` (pointing at the return address).
 * Returns 1 and sets *eax (unless the API returns nothing, *has_eax = 0). */
void mh_port_call_api(mh_port *port, int api, uint32_t esp, uint32_t *eax, int *has_eax);
/* COM method at fake address `va`: *pop = bytes the callee pops (return address included). */
void mh_port_call_com(mh_port *port, uint32_t va, uint32_t esp, uint32_t *eax, int *has_eax, uint32_t *pop, const char **label);
int mh_port_is_com(uint32_t va);

/* Counters for the comparison with the reference. */
uint64_t mh_port_clock(const mh_port *port);
uint64_t mh_port_rdtsc(mh_port *port);   /* the guest's time-stamp counter */
unsigned mh_port_frames(const mh_port *port);
uint32_t mh_port_com_next(const mh_port *port);
uint32_t mh_port_res_next(const mh_port *port);
#endif
