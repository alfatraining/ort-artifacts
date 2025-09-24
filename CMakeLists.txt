cmake_minimum_required(VERSION 3.26)
project(ort_artifacts)

include(ExternalProject)

# Cache variables with defaults matching

# message(FATAL_ERROR "USING GENERATOR: ${CMAKE_GENERATOR} for ${CMAKE_CONFIGURATION_TYPES}")

# Core options
set(REFERENCE "main" CACHE STRING "Exact branch or tag")
option(STATIC_BUILD "Build static library" OFF)
set(TARGET_ARCH "x86_64" CACHE STRING "Target architecture")
set_property(CACHE TARGET_ARCH PROPERTY STRINGS x86_64 aarch64)

# Platform options
option(IPHONEOS "Target iOS/iPadOS" OFF)
option(IPHONESIMULATOR "Target iOS/iPadOS simulator" OFF)
option(ANDROID "Target Android" OFF)
set(ANDROID_API "35" CACHE STRING "Android API level")
set(ANDROID_ABI "arm64-v8a" CACHE STRING "Android ABI")
set_property(CACHE ANDROID_ABI PROPERTY STRINGS armeabi-v7a arm64-v8a x86_64 x86)
option(WASM "Compile for WebAssembly" OFF)
set(EMSDK_VERSION "4.0.3" CACHE STRING "Emscripten SDK version")

# Runtime options
option(MSVC_STATIC_RUNTIME "Link with static MSVC runtime" OFF)

# Execution Provider options
option(USE_DIRECTML "Enable DirectML EP" OFF)
option(USE_COREML "Enable CoreML EP" OFF)
option(USE_XNNPACK "Enable XNNPACK EP" OFF)
option(USE_WEBGPU "Enable WebGPU EP" OFF)
option(USE_OPENVINO "Enable OpenVINO EP" OFF)
option(USE_NNAPI "Enable NNAPI EP" OFF)

# Build optimization options
option(FORCE_UPDATE "Force update of ONNX Runtime repository (re-clone)" OFF)

# Constants from build.ts
set(MACOS_DEPLOYMENT_TARGET "12.0")
set(IPHONE_DEPLOYMENT_TARGET "16.0")

# Platform detection
if(CMAKE_SYSTEM_NAME STREQUAL "Windows")
    set(PLATFORM_WIN32 ON)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
    set(PLATFORM_DARWIN ON)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(PLATFORM_LINUX ON)
endif()

# Environment variable validation for cross-compilation
if(ANDROID)
    if(NOT DEFINED ENV{ANDROID_NDK_HOME})
        message(FATAL_ERROR "ANDROID_NDK_HOME environment variable must be set for Android builds")
    endif()
    if(NOT DEFINED ENV{ANDROID_SDK_ROOT})
        message(FATAL_ERROR "ANDROID_SDK_ROOT environment variable must be set for Android builds")
    endif()
endif()

# Execution provider platform compatibility checks
if(USE_DIRECTML AND NOT PLATFORM_WIN32)
    message(FATAL_ERROR "DirectML EP is only available on Windows")
endif()

if(USE_COREML AND NOT PLATFORM_DARWIN)
    message(FATAL_ERROR "CoreML EP is only available on macOS/iOS")
endif()

if(USE_NNAPI AND NOT ANDROID)
    message(FATAL_ERROR "NNAPI EP is only available on Android")
endif()

if(USE_OPENVINO AND PLATFORM_DARWIN)
    message(FATAL_ERROR "OpenVINO EP is not available on macOS")
endif()

# Prepare patch command
file(GLOB PATCH_FILES ${CMAKE_CURRENT_SOURCE_DIR}/src/patches/all/*.patch)
list(SORT PATCH_FILES)
set(PATCH_COMMAND "")
foreach(PATCH_FILE ${PATCH_FILES})
    list(APPEND PATCH_COMMAND COMMAND git apply ${PATCH_FILE} --ignore-whitespace --recount || true)
endforeach()


# Prepare static build configuration command
if(STATIC_BUILD)
    set(STATIC_BUILD_COMMAND
        COMMAND ${CMAKE_COMMAND} -E make_directory <SOURCE_DIR>/static-build
        COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_CURRENT_SOURCE_DIR}/src/static-build/CMakeLists.txt <SOURCE_DIR>/static-build/CMakeLists.txt
    )
else()
    set(STATIC_BUILD_COMMAND "")
endif()

# Build CMAKE_ARGS based on options - basic flags across all targets
string(REPLACE ";" "<|>" BUILD_CONFIGS "${CMAKE_CONFIGURATION_TYPES}")
set(CMAKE_ARGS
    -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}
    -DCMAKE_CONFIGURATION_TYPES=${BUILD_CONFIGS}
    -DCMAKE_INSTALL_PREFIX=${CMAKE_CURRENT_BINARY_DIR}/artifact/onnxruntime
    -DCMAKE_DEBUG_POSTFIX=d
    -Donnxruntime_CLIENT_PACKAGE_BUILD=ON
    -Donnxruntime_USE_TELEMETRY=OFF
    -Donnxruntime_BUILD_UNIT_TESTS=OFF
    -Donnxruntime_USE_KLEIDIAI=ON
    -Donnxruntime_ENABLE_PYTHON=OFF
)

# Determine source directory based on static build option
if(STATIC_BUILD)
    set(SOURCE_SUBDIR static-build)
    list(APPEND CMAKE_ARGS -DONNXRUNTIME_SOURCE_DIR=<SOURCE_DIR>)
    list(APPEND CMAKE_ARGS -Donnxruntime_BUILD_SHARED_LIB=OFF)
    list(APPEND CMAKE_ARGS -DBUILD_SHARED_LIBS=OFF)
    set(BUILD_SHARED_LIBS OFF)
else()
    set(SOURCE_SUBDIR cmake)
    list(APPEND CMAKE_ARGS -Donnxruntime_BUILD_SHARED_LIB=ON)
    list(APPEND CMAKE_ARGS -Donnxruntime_ENABLE_LTO=ON)
endif()

# Platform-specific configuration
if(PLATFORM_DARWIN)
    list(APPEND CMAKE_ARGS -Dprotobuf_BUILD_PROTOC_BINARIES=OFF)
    
    # iOS vs macOS deployment target
    if(IPHONEOS OR IPHONESIMULATOR)
        list(APPEND CMAKE_ARGS -DCMAKE_OSX_DEPLOYMENT_TARGET=${IPHONE_DEPLOYMENT_TARGET} -DCMAKE_POLICY_VERSION_MINIMUM=3.5)
        list(APPEND CMAKE_ARGS -DCMAKE_TOOLCHAIN_FILE=<SOURCE_DIR>/cmake/onnxruntime_ios.toolchain.cmake)
        if(IPHONEOS)
            list(APPEND CMAKE_ARGS -DCMAKE_OSX_SYSROOT=iphoneos)
        elseif(IPHONESIMULATOR)
            list(APPEND CMAKE_ARGS -DCMAKE_OSX_SYSROOT=iphonesimulator)
        endif()
    else()
        list(APPEND CMAKE_ARGS -DCMAKE_OSX_DEPLOYMENT_TARGET=${MACOS_DEPLOYMENT_TARGET})
    endif()
    
    # Architecture selection for Darwin
    if(TARGET_ARCH STREQUAL "aarch64")
        list(APPEND CMAKE_ARGS -DCMAKE_OSX_ARCHITECTURES=arm64)
    else()
        list(APPEND CMAKE_ARGS -DCMAKE_OSX_ARCHITECTURES=x86_64)
    endif()
endif()

# Cross-compilation for Android
if(ANDROID)
    list(APPEND CMAKE_ARGS
        -DANDROID_PLATFORM=android-${ANDROID_API}
        -DANDROID_ABI=${ANDROID_ABI}
        -DANDROID_USE_LEGACY_TOOLCHAIN_FILE=false
        -DCMAKE_TOOLCHAIN_FILE=$ENV{ANDROID_NDK_HOME}/build/cmake/android.toolchain.cmake
    )
endif()

# Linux ARM64 cross-compilation
if(PLATFORM_LINUX AND NOT ANDROID AND TARGET_ARCH STREQUAL "aarch64")
    list(APPEND CMAKE_ARGS
        -Donnxruntime_CROSS_COMPILING=ON
        # -DCMAKE_TOOLCHAIN_FILE=${CMAKE_CURRENT_SOURCE_DIR}/toolchains/aarch64-unknown-linux-gnu.cmake
        -DCMAKE_TOOLCHAIN_FILE=<SOURCE_DIR>/cmake/linux_arm64_crosscompile_toolchain.cmake
    )
endif()

# Windows configuration
if(PLATFORM_WIN32)
    # Windows-specific compiler flags
    set(COMPILER_FLAGS "_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR")
    
    # ARM64 cross-compilation on Windows
    if(TARGET_ARCH STREQUAL "aarch64")
        list(APPEND CMAKE_ARGS -Donnxruntime_CROSS_COMPILING=ON -A ARM64)
        list(APPEND COMPILER_FLAGS "_SILENCE_ALL_CXX23_DEPRECATION_WARNINGS")
    endif()
    
    # MSVC static runtime configuration
    if(MSVC_STATIC_RUNTIME)
        list(APPEND CMAKE_ARGS
            -DONNX_USE_MSVC_STATIC_RUNTIME=ON
            -Dprotobuf_MSVC_STATIC_RUNTIME=ON
            -Dgtest_force_shared_crt=OFF
            -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded$<$<CONFIG:Debug>:Debug>
            -DABSL_MSVC_STATIC_RUNTIME=ON
        )
    else()
        list(APPEND CMAKE_ARGS
            -DONNX_USE_MSVC_STATIC_RUNTIME=OFF
            -Dprotobuf_MSVC_STATIC_RUNTIME=OFF
            -Dgtest_force_shared_crt=ON
            -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded$<$<CONFIG:Debug>:Debug>DLL
            -DABSL_MSVC_STATIC_RUNTIME=OFF
        )
    endif()
    
    # Add compiler flags if any
    if(COMPILER_FLAGS)
        string(REPLACE ";" " -D" COMPILER_FLAGS_STR "-D${COMPILER_FLAGS}")
        list(APPEND CMAKE_ARGS -DCMAKE_C_FLAGS=${COMPILER_FLAGS_STR})
        list(APPEND CMAKE_ARGS -DCMAKE_CXX_FLAGS=${COMPILER_FLAGS_STR})
    endif()
endif()

# Execution Provider configuration
if(USE_DIRECTML AND PLATFORM_WIN32)
    list(APPEND CMAKE_ARGS -Donnxruntime_USE_DML=ON)
endif()

if(USE_COREML AND PLATFORM_DARWIN)
    list(APPEND CMAKE_ARGS -Donnxruntime_USE_COREML=ON)
endif()

if(USE_XNNPACK)
    list(APPEND CMAKE_ARGS -Donnxruntime_USE_XNNPACK=ON)
endif()

if(USE_WEBGPU)
    list(APPEND CMAKE_ARGS
        -Donnxruntime_USE_WEBGPU=ON
        -Donnxruntime_ENABLE_DELAY_LOADING_WIN_DLLS=OFF
    )
endif()

if(USE_OPENVINO AND (PLATFORM_WIN32 OR PLATFORM_LINUX))
    list(APPEND CMAKE_ARGS
        -Donnxruntime_USE_OPENVINO=ON
        -Donnxruntime_USE_OPENVINO_GPU=ON
        -Donnxruntime_USE_OPENVINO_CPU=ON
        -Donnxruntime_USE_OPENVINO_NPU=ON
        -Donnxruntime_DISABLE_RTTI=OFF
    )
endif()

if(USE_NNAPI AND ANDROID)
    list(APPEND CMAKE_ARGS -Donnxruntime_USE_NNAPI_BUILTIN=ON)
endif()

# WebAssembly special case handling
if(WASM)
    set(WEBGPU_ARG "")
    if(USE_WEBGPU)
        set(WEBGPU_ARG "--use_webgpu")
    endif()
    
    ExternalProject_Add(onnxruntime
        GIT_REPOSITORY https://github.com/microsoft/onnxruntime
        GIT_TAG ${REFERENCE}
        GIT_SUBMODULES_RECURSE ON
        GIT_SHALLOW ON
        PATCH_COMMAND ${PATCH_COMMAND}
        CONFIGURE_COMMAND ""
        BUILD_COMMAND bash ./build.sh --config ${CMAKE_BUILD_TYPE} --build_wasm_static_lib --enable_wasm_simd --enable_wasm_threads --skip_tests --disable_wasm_exception_catching --disable_rtti --parallel ${WEBGPU_ARG} --emsdk_version ${EMSDK_VERSION}
        BUILD_IN_SOURCE ON
        INSTALL_COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/artifact/onnxruntime/lib
                     && ${CMAKE_COMMAND} -E copy <SOURCE_DIR>/build/Linux/${CMAKE_BUILD_TYPE}/libonnxruntime_webassembly.a ${CMAKE_CURRENT_BINARY_DIR}/artifact/onnxruntime/lib/libonnxruntime.a
        INSTALL_DIR ${CMAKE_CURRENT_BINARY_DIR}/artifact/onnxruntime
    )
else()
    ExternalProject_Add(onnxruntime
        GIT_REPOSITORY https://github.com/microsoft/onnxruntime
        GIT_TAG ${REFERENCE}
        GIT_SUBMODULES_RECURSE ON
        GIT_SHALLOW ON
        PATCH_COMMAND ${PATCH_COMMAND} ${STATIC_BUILD_COMMAND}
        SOURCE_SUBDIR ${SOURCE_SUBDIR}
        LIST_SEPARATOR "<|>"
        CMAKE_ARGS ${CMAKE_ARGS}
        # ${ORT_CMAKE_GENERATOR}
        INSTALL_DIR ${CMAKE_CURRENT_BINARY_DIR}/artifact/onnxruntime
        CMAKE_CACHE_ARGS -DCMAKE_INSTALL_PREFIX:PATH=<INSTALL_DIR>
    )
endif()

message(STATUS "ONNX Runtime ExternalProject configured successfully")


