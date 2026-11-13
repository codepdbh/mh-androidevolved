cmake_minimum_required(VERSION 3.22)
project(manhunt_android_runtime LANGUAGES C)

set(MH_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../../../..")
add_library(mh_runtime SHARED native_diagnostics.c "${MH_ROOT}/runtime/guest_memory.c" "${MH_ROOT}/runtime/pe32_image.c" "${MH_ROOT}/runtime/pe32_imports.c" "${MH_ROOT}/runtime/pe32_import_plan.c")
target_include_directories(mh_runtime PRIVATE "${MH_ROOT}/runtime")
target_compile_features(mh_runtime PRIVATE c_std_11)
