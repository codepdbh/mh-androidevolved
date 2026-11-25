/* Synthetic API-level save lifecycle. No original game code or data. */
#include "port_api.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#define mkdir_one(p) _mkdir(p)
#define rmdir_one(p) _rmdir(p)
#else
#include <unistd.h>
#define mkdir_one(p) mkdir(p, 0700)
#define rmdir_one(p) rmdir(p)
#endif
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } checks++; } while (0)
#define BASE 0x1f00000u
#define STACK (BASE + 0x20000u)
#define NAME (BASE + 0x21000u)
#define DATA (BASE + 0x22000u)
#define COUNT (BASE + 0x23000u)
static unsigned checks;
static mh_guest_memory mem;
static mh_port *port;
static const char guest_save[] = "User Files\\SaveGames\\MANHUNT0.SAV";
static void fault(void *user, const char *message) { (void)user; fprintf(stderr, "fault: %s\n", message); exit(2); }
static uint32_t api(const char *name, const uint32_t *args, unsigned n) {
    int index = mh_port_find_api(name), has = 0; uint32_t result = 0;
    if (index < 0 || mh_port_api_args(index) != n) exit(3);
    for (unsigned i = 0; i < 12; i++) mh_mem_write_u32(&mem, STACK + 4 + 4 * i, i < n ? args[i] : 0);
    mh_port_call_api(port, index, STACK, &result, &has); return result;
}
static uint32_t open_save(uint32_t access, uint32_t disposition) {
    mh_mem_write(&mem, NAME, guest_save, sizeof guest_save);
    const uint32_t a[] = {NAME, access, 0, 0, disposition, 0, 0}; return api("CreateFileA", a, 7);
}
static uint32_t close_save(uint32_t handle) { return api("CloseHandle", &handle, 1); }
static uint32_t write_save(uint32_t handle, const char *data) {
    size_t n = strlen(data); mh_mem_write(&mem, DATA, data, n);
    const uint32_t a[] = {handle, DATA, (uint32_t)n, COUNT, 0}; return api("WriteFile", a, 5);
}
static int read_save(uint32_t handle, const char *expected) {
    char got[128] = {0}; uint32_t count = 0;
    const uint32_t a[] = {handle, DATA, 100, COUNT, 0};
    if (!api("ReadFile", a, 5) || !mh_mem_read_u32(&mem, COUNT, &count) || count != strlen(expected)) return 0;
    return mh_mem_read(&mem, DATA, got, count) && !memcmp(got, expected, count);
}
static int start(const char *root, const char *save_dir, int readonly) {
    mh_port_host host = {0}; host.fault = fault;
    port = mh_port_create(&mem, &host, root, 0); if (!port) return 0;
    mh_port_set_save_dir(port, save_dir); mh_port_set_save_readonly(port, readonly);
    const char *dirs[] = {"User Files", "User Files\\SaveGames"};
    for (unsigned i = 0; i < 2; i++) {
        mh_mem_write(&mem, NAME, dirs[i], strlen(dirs[i]) + 1);
        const uint32_t a[] = {NAME, 0}; if (!api("CreateDirectoryA", a, 2)) return 0;
    }
    return 1;
}
int main(int argc, char **argv) {
    if (argc != 2) return 4;
    char game[1200], saves[1200], path[1400], temporary[1410], missing[1400];
    snprintf(game, sizeof game, "%s/game", argv[1]); snprintf(saves, sizeof saves, "%s/saves-test", argv[1]);
    snprintf(path, sizeof path, "%s/user files_savegames_manhunt0.sav", saves);
    snprintf(temporary, sizeof temporary, "%s.tmp", path); snprintf(missing, sizeof missing, "%s/missing/saves", argv[1]);
    CHECK(!mkdir_one(game)); CHECK(!mkdir_one(saves));
    uint8_t *bytes = calloc(1, 0x40000); CHECK(bytes && mh_mem_init(&mem, bytes, 0x40000, BASE));
    CHECK(start(game, saves, 0));
    uint32_t h = open_save(0x40000000u, 2); CHECK(h != 0xffffffffu);
    CHECK(write_save(h, "first save")); CHECK(close_save(h));
    mh_port_destroy(port); CHECK(start(game, saves, 0));
    h = open_save(0x80000000u, 3); CHECK(h != 0xffffffffu); CHECK(read_save(h, "first save")); CHECK(close_save(h));
    h = open_save(0x40000000u, 2); CHECK(h != 0xffffffffu); CHECK(write_save(h, "replacement")); CHECK(close_save(h));
    mh_port_destroy(port); CHECK(start(game, saves, 1));
    h = open_save(0x40000000u, 2); CHECK(h != 0xffffffffu); CHECK(write_save(h, "test changes only")); CHECK(close_save(h));
    mh_port_destroy(port); CHECK(start(game, saves, 0));
    h = open_save(0x80000000u, 3); CHECK(read_save(h, "replacement")); CHECK(close_save(h));
    /* Failed temporary open must report failure and preserve the previous save. */
    CHECK(!mkdir_one(temporary));
    h = open_save(0x40000000u, 2); CHECK(write_save(h, "must not replace")); CHECK(!close_save(h)); CHECK(*mh_port_last_error(port) != 0);
    CHECK(!rmdir_one(temporary)); mh_port_destroy(port); CHECK(start(game, saves, 0));
    h = open_save(0x80000000u, 3); CHECK(read_save(h, "replacement")); CHECK(close_save(h));
    /* Truncation with no WriteFile still persists, and survives a fresh port instance. */
    h = open_save(0x40000000u, 5); CHECK(h != 0xffffffffu); CHECK(close_save(h));
    mh_port_destroy(port); CHECK(start(game, saves, 0));
    h = open_save(0x80000000u, 3); CHECK(read_save(h, "")); CHECK(close_save(h));
    /* Failed final replacement also leaves no temporary file behind. */
    CHECK(!remove(path)); CHECK(!mkdir_one(path));
    h = open_save(0x40000000u, 2); CHECK(write_save(h, "rename must fail")); CHECK(!close_save(h));
    FILE *fp = fopen(temporary, "rb"); CHECK(!fp); CHECK(!rmdir_one(path));
    mh_port_destroy(port); CHECK(start(game, missing, 0));
    h = open_save(0x40000000u, 2); CHECK(write_save(h, "missing directory")); CHECK(!close_save(h)); CHECK(*mh_port_last_error(port) == 3);
    mh_port_destroy(port); CHECK(start(game, saves, 0));
    h = open_save(0x40000000u, 2); CHECK(h != 0xffffffffu); CHECK(close_save(h));
    mh_port_destroy(port); CHECK(start(game, saves, 0));
    h = open_save(0x80000000u, 3); CHECK(h != 0xffffffffu); CHECK(read_save(h, "")); CHECK(close_save(h));
    mh_port_destroy(port); free(bytes);
    CHECK(!remove(path)); CHECK(!rmdir_one(saves)); CHECK(!rmdir_one(game));
    printf("port saves: %u checks passed; persistent reopen, replacement, readonly seeds, empty saves, open/rename failures; cleanup OK\n", checks);
    return 0;
}
