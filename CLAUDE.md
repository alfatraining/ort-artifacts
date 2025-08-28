# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains build configurations for creating static builds of ONNX Runtime for various platforms. The project is currently transitioning from Deno/TypeScript-based build scripts to pure CMake.

## Architecture

### Core Components

- **Static Build System**: Custom CMake configuration in `src/static-build/CMakeLists.txt` that bundles ONNX Runtime into a single static library
- **Patch System**: Platform-specific patches in `src/patches/all/` applied to the ONNX Runtime source before building
- **Cross-Platform Support**: Supports Windows, macOS, Linux, iOS, Android, and WebAssembly targets

### Key Files

- `src/static-build/CMakeLists.txt`: Main CMake configuration for static library bundling
- `src/build.ts`: Current Deno-based build script (to be replaced with CMake)
- `src/patches/all/*.patch`: Git patches applied to ONNX Runtime source

## Build System

### Current Build Process (Deno-based)

The current build system uses `deno run --allow-all src/build.ts` with various options:

**Core Options:**
- `-r, --reference <string>`: Exact branch or tag of ONNX Runtime
- `-s, --static`: Build static library 
- `-N, --ninja`: Build with Ninja generator
- `-A, --arch <arch>`: Target architecture (x86_64, aarch64)

**Platform Options:**
- `--iphoneos`: Target iOS/iPadOS
- `--iphonesimulator`: Target iOS/iPadOS simulator  
- `--android`: Target Android
- `--android_api <number>`: Android API level (default: 29)
- `--android_abi <abi>`: Android ABI (armeabi-v7a, arm64-v8a, x86_64, x86)
- `-W, --wasm`: Compile for WebAssembly
- `--emsdk <version>`: Emscripten SDK version (default: 4.0.3)

**Execution Provider Options:**
- `--directml`: Enable DirectML EP (Windows)
- `--coreml`: Enable CoreML EP (macOS/iOS)
- `--xnnpack`: Enable XNNPACK EP
- `--webgpu`: Enable WebGPU EP
- `--openvino`: Enable OpenVINO EP
- `--nnapi`: Enable NNAPI EP (Android)

**Runtime Options:**
- `--mt`: Link with static MSVC runtime (Windows)

### CMake Build Process

The static build system uses a custom CMake function `bundle_static_library()` that:

1. Recursively collects all static library dependencies
2. Filters out shared libraries (.dll, .so, .dylib, .tbd)
3. Bundles everything into a single static library using platform-specific tools:
   - **Windows**: `lib.exe` with `/NOLOGO /OUT:`
   - **macOS**: `libtool -static`
   - **Linux**: `ar` with MRI script

### Build Artifacts

Builds output to `artifact/onnxruntime/` with:
- Static libraries in `lib/` directory
- Headers preserved from original ONNX Runtime build
- Platform-specific DLLs for certain execution providers

## Development Workflow

### Environment Requirements

- **Android builds**: Requires `ANDROID_NDK_HOME` and `ANDROID_SDK_ROOT` environment variables
- **Cross-compilation**: Platform-specific toolchains (e.g., `toolchains/aarch64-unknown-linux-gnu.cmake` for Linux ARM64)

### Key Constants

- `MACOS_DEPLOYMENT_TARGET`: 12.0 (should be 13.3 per ONNX Runtime 1.21.0, but constrained to 12.0)
- `IPHONE_DEPLOYMENT_TARGET`: 16.0

### Patch Management

All patches in `src/patches/all/` are applied in alphabetical order:
1. `0001-no-soname.patch`
2. `0002-ignore-cpuinfo-arm64-patch.patch`
3. `0003-leak-logger-mutex.patch`
4. `0004-change-dylib-output_name.patch`
5. `0005-install-directml-dlls.patch`

## Migration Goals

The project is transitioning away from the Deno-based build script to pure CMake. When working on this migration:

1. Preserve all existing platform and execution provider support
2. Maintain the patch application system
3. Keep the static library bundling functionality
4. Ensure cross-compilation capabilities remain intact
5. Port all command-line options to CMake equivalents

## Known Issues

- Minimal builds are currently disabled (blocked by ONNX Runtime issue #25796)
- WebGPU EP with Vulkan backend on Windows needs investigation
- OpenVINO EP not available on macOS