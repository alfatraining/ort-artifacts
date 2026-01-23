#!/usr/bin/env bash
# Windows build: DirectML and static MSVC runtime enabled by default
export USE_DIRECTML="${USE_DIRECTML:-ON}"
export MSVC_STATIC_RUNTIME="${MSVC_STATIC_RUNTIME:-ON}"
exec "$(dirname "${BASH_SOURCE[0]}")/build.sh" win "$@"
