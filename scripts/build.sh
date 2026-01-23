#!/usr/bin/env bash
# Shared build script with universal defaults.
# Platform-specific scripts set their overrides, then call this script.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# PLATFORM="${1:?Usage: $0 <platform> [options...]}"
# shift

# ARGS=(--platform "$PLATFORM")
[[ -n "${PLATFORM:-}" ]] && ARGS+=(--platform "${PLATFORM}")

# Architecture (universal default: x86_64)
ARGS+=(--arch "${BUILD_ARCH:-x86_64}")

# Build options
[[ "${BUILD_VARIANT:-dylib}" == "static" ]] && ARGS+=(--static)
[[ -n "${BUILD_TYPE:-}" ]] && ARGS+=(--build-mode "$BUILD_TYPE")
[[ -n "${ONNXRUNTIME_REF:-}" ]] && ARGS+=(--reference "$ONNXRUNTIME_REF")
[[ -n "${BUILD_DIR:-}" ]] && ARGS+=(--build-dir "$BUILD_DIR")

# Execution providers (XNNPACK defaults ON, others OFF)
[[ "${USE_XNNPACK:-ON}" == "ON" ]] && ARGS+=(--xnnpack)
[[ "${USE_COREML:-OFF}" == "ON" ]] && ARGS+=(--coreml)
[[ "${USE_DIRECTML:-OFF}" == "ON" ]] && ARGS+=(--directml)
[[ "${USE_OPENVINO:-OFF}" == "ON" || "${WITH_OPENVINO:-OFF}" == "ON" ]] && ARGS+=(--openvino)
[[ "${USE_NNAPI:-OFF}" == "ON" ]] && ARGS+=(--nnapi)
[[ "${USE_WEBGPU:-OFF}" == "ON" ]] && ARGS+=(--webgpu)

# Platform-specific options (only added when relevant env vars set)
[[ -n "${ANDROID_ABI:-}" ]] && ARGS+=(--android-abi "$ANDROID_ABI")
[[ -n "${ANDROID_API:-}" ]] && ARGS+=(--android-api "$ANDROID_API")
[[ "${IPHONEOS:-OFF}" == "ON" ]] && ARGS+=(--iphoneos)
[[ "${IPHONESIMULATOR:-OFF}" == "ON" ]] && ARGS+=(--iphonesimulator)
[[ "${MSVC_STATIC_RUNTIME:-OFF}" == "ON" ]] && ARGS+=(--mt)

# Build control
[[ "${CREATE_ARCHIVE:-OFF}" == "ON" ]] && ARGS+=(--create-archive)
[[ "${CREATE_LOCAL_MANIFEST:-ON}" == "ON" ]] && ARGS+=(--local-manifest)
[[ "${NUKE_BUILD_DIR:-OFF}" == "ON" ]] && ARGS+=(--nuke)
[[ -n "${ARCHIVE_NAME:-}" ]] && ARGS+=(--archive-name "$ARCHIVE_NAME")
[[ -n "${ORT_INSTALL_DIR:-}" ]] && ARGS+=(--artifact-dir "$ORT_INSTALL_DIR")

# Toolchain
[[ "${USE_CLANG:-false}" == "true" ]] && ARGS+=(--clang)

# Pass through additional arguments and execute
exec python3 "${SCRIPT_DIR}/build.py" "${ARGS[@]}" "$@"
