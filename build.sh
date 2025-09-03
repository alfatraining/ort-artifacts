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
FORCE_UPDATE="OFF"
CLEAN="OFF"
CLEAN_ALL="OFF"

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
        --force-update)
            FORCE_UPDATE="ON"
            shift
            ;;
        --clean)
            CLEAN="ON"
            shift
            ;;
        --clean-all)
            CLEAN_ALL="ON"
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
            echo "      --force-update           Force update of ONNX Runtime repository (re-clone)"
            echo "      --clean                  Clean build artifacts but preserve ONNX Runtime repository"
            echo "      --clean-all              Clean everything including ONNX Runtime repository"
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

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Handle cleaning operations
if [[ "$CLEAN" == "ON" || "$CLEAN_ALL" == "ON" ]]; then
    BUILD_DIR="build"
    
    if [[ "$CLEAN_ALL" == "ON" ]]; then
        echo -e "${YELLOW}Performing complete clean (including ONNX Runtime repository)...${NC}"
        if [[ -d "$BUILD_DIR" ]]; then
            rm -rf "$BUILD_DIR"
            echo -e "${GREEN}Build directory completely removed.${NC}"
        else
            echo -e "${YELLOW}Build directory does not exist - nothing to clean.${NC}"
        fi
    elif [[ "$CLEAN" == "ON" ]]; then
        echo -e "${YELLOW}Performing selective clean (preserving ONNX Runtime repository)...${NC}"
        
        if [[ -d "$BUILD_DIR" ]]; then
            ONNX_RUNTIME_DIR="$BUILD_DIR/onnxruntime"
            STAMP_DIR="$BUILD_DIR/onnxruntime-prefix/src/onnxruntime-stamp"
            TEMP_DIR=""
            TEMP_STAMP_DIR=""
            
            # If ONNX Runtime repository exists, preserve it
            if [[ -d "$ONNX_RUNTIME_DIR" ]]; then
                TEMP_DIR="/tmp/onnxruntime-preserve-$(date +%Y%m%d-%H%M%S)"
                echo -e "${CYAN}Temporarily preserving ONNX Runtime repository...${NC}"
                mv "$ONNX_RUNTIME_DIR" "$TEMP_DIR"
            fi
            
            # If stamp directory exists, preserve it to prevent re-cloning
            if [[ -d "$STAMP_DIR" ]]; then
                TEMP_STAMP_DIR="/tmp/onnxruntime-stamps-$(date +%Y%m%d-%H%M%S)"
                echo -e "${CYAN}Temporarily preserving ExternalProject stamp files...${NC}"
                mv "$STAMP_DIR" "$TEMP_STAMP_DIR"
            fi
            
            # Remove build directory
            rm -rf "$BUILD_DIR"
            echo -e "${GREEN}Build artifacts removed.${NC}"
            
            # Restore ONNX Runtime repository if it was preserved
            if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
                mkdir -p "$BUILD_DIR"
                mv "$TEMP_DIR" "$ONNX_RUNTIME_DIR"
                echo -e "${GREEN}ONNX Runtime repository restored.${NC}"
            fi
            
            # Restore stamp files if they were preserved
            if [[ -n "$TEMP_STAMP_DIR" && -d "$TEMP_STAMP_DIR" ]]; then
                STAMP_PARENT_DIR="$BUILD_DIR/onnxruntime-prefix/src"
                mkdir -p "$STAMP_PARENT_DIR"
                mv "$TEMP_STAMP_DIR" "$STAMP_DIR"
                echo -e "${GREEN}ExternalProject stamp files restored.${NC}"
            fi
        else
            echo -e "${YELLOW}Build directory does not exist - nothing to clean.${NC}"
        fi
    fi

    echo "Finished cleaning up."
    exit 0
fi

# Select generator
if [[ "$USE_NINJA" == "ON" ]]; then
    GENERATOR="-G Ninja"
else
    GENERATOR=""
fi

if [[ "$DRY_RUN" == "ON" ]]; then
    echo -e "${YELLOW}DRY RUN MODE - Commands that would be executed:${NC}"
    echo ""
    echo -e "${CYAN}cmake -S . -B build -DREFERENCE=$REFERENCE -DSTATIC_BUILD=$STATIC_BUILD -DUSE_NINJA=$USE_NINJA -DTARGET_ARCH=$TARGET_ARCH -DIPHONEOS=$IPHONEOS -DIPHONESIMULATOR=$IPHONESIMULATOR -DANDROID=$ANDROID -DANDROID_API=$ANDROID_API -DANDROID_ABI=$ANDROID_ABI -DWASM=$WASM -DEMSDK_VERSION=$EMSDK_VERSION -DMSVC_STATIC_RUNTIME=$MSVC_STATIC_RUNTIME -DUSE_DIRECTML=$USE_DIRECTML -DUSE_COREML=$USE_COREML -DUSE_XNNPACK=$USE_XNNPACK -DUSE_WEBGPU=$USE_WEBGPU -DUSE_OPENVINO=$USE_OPENVINO -DUSE_NNAPI=$USE_NNAPI -DFORCE_UPDATE=$FORCE_UPDATE$([[ -n "$GENERATOR" ]] && echo " $GENERATOR")${NC}"
    echo ""
    echo -e "${CYAN}cmake --build build --config Release --parallel 9${NC}"
    exit 0
fi

echo -e "${GREEN}Configuring ONNX Runtime build with CMake...${NC}"

# Execute CMake configuration
echo -e "${CYAN}Running: cmake -S . -B build -DREFERENCE=\"$REFERENCE\" -DSTATIC_BUILD=\"$STATIC_BUILD\" -DUSE_NINJA=\"$USE_NINJA\" -DTARGET_ARCH=\"$TARGET_ARCH\" -DIPHONEOS=\"$IPHONEOS\" -DIPHONESIMULATOR=\"$IPHONESIMULATOR\" -DANDROID=\"$ANDROID\" -DANDROID_API=\"$ANDROID_API\" -DANDROID_ABI=\"$ANDROID_ABI\" -DWASM=\"$WASM\" -DEMSDK_VERSION=\"$EMSDK_VERSION\" -DMSVC_STATIC_RUNTIME=\"$MSVC_STATIC_RUNTIME\" -DUSE_DIRECTML=\"$USE_DIRECTML\" -DUSE_COREML=\"$USE_COREML\" -DUSE_XNNPACK=\"$USE_XNNPACK\" -DUSE_WEBGPU=\"$USE_WEBGPU\" -DUSE_OPENVINO=\"$USE_OPENVINO\" -DUSE_NNAPI=\"$USE_NNAPI\" -DFORCE_UPDATE=\"$FORCE_UPDATE\" $GENERATOR${NC}"

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
    -DFORCE_UPDATE="$FORCE_UPDATE" \
    $GENERATOR

if [[ $? -ne 0 ]]; then
    echo -e "${RED}CMake configuration failed with exit code $?${NC}" >&2
    exit 1
fi

echo -e "${GREEN}Building ONNX Runtime...${NC}"

# Build the project
cmake --build build --config Release --parallel

if [[ $? -ne 0 ]]; then
    echo -e "${RED}CMake build failed with exit code $?${NC}" >&2
    exit 1
fi

echo -e "${GREEN}Installing...${NC}"

# Install the project
cmake --install build

if [[ $? -ne 0 ]]; then
    echo -e "${RED}CMake install failed with exit code $?${NC}" >&2
    exit 1
fi

echo -e "${GREEN}Completed successfully!${NC}"