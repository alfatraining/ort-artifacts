#!/bin/bash
set -euo pipefail

# Default values matching build.ts
REFERENCE="main"
STATIC_BUILD="OFF"
USE_NINJA="OFF"
TARGET_ARCH="x86_64"
IPHONEOS="OFF"
IPHONESIMULATOR="OFF"
ANDROID="OFF"
ANDROID_API="35"
ANDROID_ABI="arm64-v8a"
WASM="OFF"
EMSDK_VERSION="4.0.3"
MSVC_STATIC_RUNTIME="OFF"
USE_DIRECTML="OFF"
USE_COREML="OFF"
USE_XNNPACK="OFF"
USE_WEBGPU="OFF"
USE_OPENVINO="OFF"
USE_NNAPI="OFF"
DRY_RUN="OFF"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -r|--reference)
            REFERENCE="$2"
            shift 2
            ;;
        -s|--static)
            STATIC_BUILD="ON"
            shift
            ;;
        -N|--ninja)
            USE_NINJA="ON"
            shift
            ;;
        -A|--arch)
            TARGET_ARCH="$2"
            shift 2
            ;;
        --iphoneos)
            IPHONEOS="ON"
            shift
            ;;
        --iphonesimulator)
            IPHONESIMULATOR="ON"
            shift
            ;;
        --android)
            ANDROID="ON"
            shift
            ;;
        --android_api)
            ANDROID_API="$2"
            shift 2
            ;;
        --android_abi)
            ANDROID_ABI="$2"
            shift 2
            ;;
        -W|--wasm)
            WASM="ON"
            shift
            ;;
        --emsdk)
            EMSDK_VERSION="$2"
            shift 2
            ;;
        --mt)
            MSVC_STATIC_RUNTIME="ON"
            shift
            ;;
        --directml)
            USE_DIRECTML="ON"
            shift
            ;;
        --coreml)
            USE_COREML="ON"
            shift
            ;;
        --xnnpack)
            USE_XNNPACK="ON"
            shift
            ;;
        --webgpu)
            USE_WEBGPU="ON"
            shift
            ;;
        --openvino)
            USE_OPENVINO="ON"
            shift
            ;;
        --nnapi)
            USE_NNAPI="ON"
            shift
            ;;
        --dry-run)
            DRY_RUN="ON"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  -r, --reference <string>     Exact branch or tag"
            echo "  -s, --static                 Build static library"
            echo "  -N, --ninja                  Build with Ninja"
            echo "  -A, --arch <arch>            Configure target architecture (x86_64, aarch64)"
            echo "      --iphoneos               Target iOS / iPadOS"
            echo "      --iphonesimulator        Target iOS / iPadOS simulator"
            echo "      --android                Target Android"
            echo "      --android_api <number>   Android API (default: 35)"
            echo "      --android_abi <abi>      Android ABI (default: arm64-v8a)"
            echo "  -W, --wasm                   Compile for WebAssembly"
            echo "      --emsdk <version>        Emsdk version for WebAssembly (default: 4.0.3)"
            echo "      --mt                     Link with static MSVC runtime"
            echo "      --directml               Enable DirectML EP"
            echo "      --coreml                 Enable CoreML EP"
            echo "      --xnnpack                Enable XNNPACK EP"
            echo "      --webgpu                 Enable WebGPU EP"
            echo "      --openvino               Enable OpenVINO EP"
            echo "      --nnapi                  Enable NNAPI EP"
            echo "      --dry-run                Print CMake command without executing"
            echo "  -h, --help                   Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Use -h or --help for usage information" >&2
            exit 1
            ;;
    esac
done

# Select generator
if [[ "$USE_NINJA" == "ON" ]]; then
    GENERATOR="-G Ninja"
else
    GENERATOR=""
fi

if [[ "$DRY_RUN" == "ON" ]]; then
    echo "DRY RUN MODE - Commands that would be executed:"
    echo ""
    echo "cmake -S . -B build -DREFERENCE=\"$REFERENCE\" -DSTATIC_BUILD=\"$STATIC_BUILD\" -DUSE_NINJA=\"$USE_NINJA\" -DTARGET_ARCH=\"$TARGET_ARCH\" -DIPHONEOS=\"$IPHONEOS\" -DIPHONESIMULATOR=\"$IPHONESIMULATOR\" -DANDROID=\"$ANDROID\" -DANDROID_API=\"$ANDROID_API\" -DANDROID_ABI=\"$ANDROID_ABI\" -DWASM=\"$WASM\" -DEMSDK_VERSION=\"$EMSDK_VERSION\" -DMSVC_STATIC_RUNTIME=\"$MSVC_STATIC_RUNTIME\" -DUSE_DIRECTML=\"$USE_DIRECTML\" -DUSE_COREML=\"$USE_COREML\" -DUSE_XNNPACK=\"$USE_XNNPACK\" -DUSE_WEBGPU=\"$USE_WEBGPU\" -DUSE_OPENVINO=\"$USE_OPENVINO\" -DUSE_NNAPI=\"$USE_NNAPI\" $GENERATOR"
    echo ""
    echo "cmake --build build --config Release --parallel"
    exit 0
fi

echo "Configuring ONNX Runtime build with CMake..."

# Execute CMake configuration
cmake -S . -B build \
    -DREFERENCE="$REFERENCE" \
    -DSTATIC_BUILD="$STATIC_BUILD" \
    -DUSE_NINJA="$USE_NINJA" \
    -DTARGET_ARCH="$TARGET_ARCH" \
    -DIPHONEOS="$IPHONEOS" \
    -DIPHONESIMULATOR="$IPHONESIMULATOR" \
    -DANDROID="$ANDROID" \
    -DANDROID_API="$ANDROID_API" \
    -DANDROID_ABI="$ANDROID_ABI" \
    -DWASM="$WASM" \
    -DEMSDK_VERSION="$EMSDK_VERSION" \
    -DMSVC_STATIC_RUNTIME="$MSVC_STATIC_RUNTIME" \
    -DUSE_DIRECTML="$USE_DIRECTML" \
    -DUSE_COREML="$USE_COREML" \
    -DUSE_XNNPACK="$USE_XNNPACK" \
    -DUSE_WEBGPU="$USE_WEBGPU" \
    -DUSE_OPENVINO="$USE_OPENVINO" \
    -DUSE_NNAPI="$USE_NNAPI" \
    $GENERATOR

echo "Building ONNX Runtime..."

# Build the project
cmake --build build --config Release --parallel

echo "Build completed successfully!"