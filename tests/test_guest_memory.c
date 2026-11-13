#include "guest_memory.h"
#include <stdint.h>
#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

int mh_memory_tests(void) {
    uint8_t bytes[8] = {0}; mh_guest_memory mem; uint32_t value = 123;
    mh_guest_memory unchanged = {bytes, sizeof bytes, 0x2000};
    CHECK(!mh_mem_init(&mem, bytes, 8, UINT32_MAX - 3));
    CHECK(!mh_mem_init(&unchanged, bytes, 0, 0));
    CHECK(unchanged.bytes == bytes && unchanged.size == sizeof bytes && unchanged.guest_base == 0x2000);
    CHECK(mh_mem_init(&mem, bytes, sizeof bytes, 0x1000));
    CHECK(mh_mem_span(&mem, 0x1001, 4) == bytes+1);
    CHECK(mh_mem_span(&mem, 0x1005, 4) == 0);
    CHECK(mh_mem_span(&mem, 0x1008, 0) == 0);
    CHECK(mh_mem_write_u32(&mem, 0x1001, UINT32_C(0x12345678)));
    CHECK(bytes[1] == 0x78 && bytes[2] == 0x56 && bytes[3] == 0x34 && bytes[4] == 0x12);
    CHECK(mh_mem_read_u32(&mem, 0x1001, &value) && value == UINT32_C(0x12345678));
    value = 123;
    CHECK(!mh_mem_read_u32(&mem, 0x1005, &value) && value == 123);
    CHECK(!mh_mem_write_u32(&mem, 0x0fff, 0));
    CHECK(!mh_mem_write_u32(&mem, UINT32_MAX, 0));
    CHECK(!mh_mem_write_u32(&mem, 0x1005, 0));
    CHECK(bytes[1] == 0x78 && bytes[2] == 0x56 && bytes[3] == 0x34 && bytes[4] == 0x12);
    CHECK(!mh_mem_read_u32(&mem, 0x1000, 0));
    CHECK(mh_mem_read(&mem, 0x1008, 0, 0));
    CHECK(mh_mem_write(&mem, 0x1002, bytes+1, 4));
    CHECK(bytes[2] == 0x78 && bytes[3] == 0x56 && bytes[4] == 0x34 && bytes[5] == 0x12);
    CHECK(mh_mem_write(&mem, 0x1001, bytes+2, 4));
    CHECK(bytes[1] == 0x78 && bytes[2] == 0x56 && bytes[3] == 0x34 && bytes[4] == 0x12);
    CHECK(mh_mem_init(&mem, bytes, 4, UINT32_MAX - 3));
    CHECK(mh_mem_write_u32(&mem, UINT32_MAX - 3, UINT32_C(0x89abcdef)));
    CHECK(mh_mem_read_u32(&mem, UINT32_MAX - 3, &value) && value == UINT32_C(0x89abcdef));
    return 0;
}

#ifndef MH_NO_MAIN
int main(void) { return mh_memory_tests(); }
#endif
