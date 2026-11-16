cmake_minimum_required(VERSION 3.22)
project(manhunt_android_runtime LANGUAGES C)

set(MH_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../../../..")
# Public runtime only; translated game code is never compiled into this library.
add_library(mh_runtime SHARED native_diagnostics.c native_selftest.c
    "${MH_ROOT}/runtime/guest_memory.c" "${MH_ROOT}/runtime/pe32_image.c" "${MH_ROOT}/runtime/pe32_imports.c"
    "${MH_ROOT}/runtime/pe32_import_plan.c" "${MH_ROOT}/runtime/readonly_stream.c")
target_include_directories(mh_runtime PRIVATE "${MH_ROOT}/runtime" "${MH_ROOT}/recomp" "${MH_ROOT}/tests")
target_compile_features(mh_runtime PRIVATE c_std_11)
target_compile_options(mh_runtime PRIVATE -Wall -Wextra)
