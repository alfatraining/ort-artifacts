#!/usr/bin/env bash
# Android build: NNAPI enabled, XNNPACK disabled by default, architecture required
export USE_NNAPI="${USE_NNAPI:-ON}"
export USE_XNNPACK="${USE_XNNPACK:-OFF}"

# Architecture parsing with ABI mapping (required)
if [[ $# -gt 0 && "$1" =~ ^(arm64-v8a|aarch64|armeabi-v7a|armeabi|x86_64)$ ]]; then
    case $1 in
        arm64-v8a | aarch64)
            BUILD_ARCH=aarch64
            ANDROID_ABI=arm64-v8a
            ;;
        armeabi-v7a | armeabi)
            BUILD_ARCH=armeabi
            ANDROID_ABI=armeabi-v7a
            ;;
        x86_64)
            BUILD_ARCH=x86_64
            ANDROID_ABI=x86_64
            ;;
    esac
    shift
fi

if [[ -z "${BUILD_ARCH:-}" ]]; then
    echo "Error: Architecture required. Set BUILD_ARCH/ANDROID_ABI or pass architecture as first argument."
    echo "Usage: $0 [arm64-v8a|armeabi-v7a|x86_64] [options...]"
    exit 1
fi

export BUILD_ARCH ANDROID_ABI
exec "$(dirname "${BASH_SOURCE[0]}")/build.sh" android "$@"
