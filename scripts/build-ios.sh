#!/usr/bin/env bash
# iOS build: aarch64 default, CoreML and iphoneos enabled by default
export BUILD_ARCH="${BUILD_ARCH:-aarch64}"
export USE_COREML="${USE_COREML:-ON}"
export IPHONEOS="${IPHONEOS:-ON}"
exec "$(dirname "${BASH_SOURCE[0]}")/build.sh" ios "$@"
