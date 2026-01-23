#!/usr/bin/env bash
# Linux build: OpenVINO and clang enabled by default
export USE_OPENVINO="${USE_OPENVINO:-ON}"
export USE_CLANG="${USE_CLANG:-true}"
exec "$(dirname "${BASH_SOURCE[0]}")/build.sh" linux "$@"
