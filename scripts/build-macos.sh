#!/usr/bin/env bash
# macOS build: CoreML enabled by default, architecture required
export USE_COREML="${USE_COREML:-ON}"

# Architecture parsing (arm64/x86_64 required)
if [[ $# -gt 0 && "$1" =~ ^(arm64|aarch64|x86_64)$ ]]; then
    case $1 in
        arm64 | aarch64) BUILD_ARCH=aarch64 ;;
        x86_64) BUILD_ARCH=x86_64 ;;
    esac
    shift
fi

if [[ -z "${BUILD_ARCH:-}" ]]; then
    echo "Error: Architecture required. Set BUILD_ARCH or pass 'arm64' or 'x86_64' as first argument."
    echo "Usage: $0 [arm64|x86_64] [options...]"
    exit 1
fi

export BUILD_ARCH
exec "$(dirname "${BASH_SOURCE[0]}")/build.sh" macos "$@"
