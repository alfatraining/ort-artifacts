#!/bin/bash
set -euo pipefail

# windows needs special handling (e.g. VS dev environment)
if [[ "${RUNNER_OS:-}" == "Windows" || "${OS:-}" == "Windows_NT" ]]; then
	IS_WINDOWS=true
else
	IS_WINDOWS=false
fi

# default values
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
CLEAN="OFF"
CLEAN_ALL="OFF"

# argument parsing
while [[ $# -gt 0 ]]; do
	case $1 in
	-r | --reference)
		REFERENCE="$2"
		shift 2
		;;
	-s | --static)
		STATIC_BUILD="ON"
		shift
		;;
	-N | --ninja)
		USE_NINJA="ON"
		shift
		;;
	-A | --arch)
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
	-W | --wasm)
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
	--clean)
		CLEAN="ON"
		shift
		;;
	--clean-all)
		CLEAN_ALL="ON"
		shift
		;;
	-h | --help)
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
		echo "      --force-update           Force update of ONNXRuntime repository (re-clone)"
		echo "      --clean                  Clean build directory but preserve ONNXRuntime repository"
		echo "      --clean-all              Clean everything including ONNXRuntime repository"
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

# output colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# convenience for local builds: handle cleaning without triggering re-cloning
if [[ "$CLEAN" == "ON" || "$CLEAN_ALL" == "ON" ]]; then
	BUILD_DIR="build"

	if [[ "$CLEAN_ALL" == "ON" ]]; then
		echo -e "${YELLOW}Performing complete clean (including ONNXRuntime repository)...${NC}"
		if [[ -d "$BUILD_DIR" ]]; then
			rm -rf "$BUILD_DIR"
			echo -e "${GREEN}Build directory completely removed.${NC}"
		else
			echo -e "${YELLOW}Build directory does not exist - nothing to clean.${NC}"
		fi
	elif [[ "$CLEAN" == "ON" ]]; then
		echo -e "${YELLOW}Performing selective clean (preserving ONNXRuntime repository)...${NC}"

		if [[ -d "$BUILD_DIR" ]]; then
			ONNX_RUNTIME_DIR="$BUILD_DIR/onnxruntime"
			STAMP_DIR="$BUILD_DIR/onnxruntime-prefix/src/onnxruntime-stamp"
			TEMP_DIR=""
			TEMP_STAMP_DIR=""

			# if ONNXRuntime repository exists, preserve it
			if [[ -d "$ONNX_RUNTIME_DIR" ]]; then
				TEMP_DIR="/tmp/onnxruntime-preserve-$(date +%Y%m%d-%H%M%S)"
				echo -e "${CYAN}Temporarily preserving ONNXRuntime repository...${NC}"
				mv "$ONNX_RUNTIME_DIR" "$TEMP_DIR"
			fi

			# if stamp directory exists, preserve it to prevent re-cloning
			if [[ -d "$STAMP_DIR" ]]; then
				TEMP_STAMP_DIR="/tmp/onnxruntime-stamps-$(date +%Y%m%d-%H%M%S)"
				echo -e "${CYAN}Temporarily preserving ExternalProject stamp files...${NC}"
				mv "$STAMP_DIR" "$TEMP_STAMP_DIR"
			fi

			# remove build directory
			rm -rf "$BUILD_DIR"
			echo -e "${GREEN}Build artifacts removed.${NC}"

			# restore ONNXRuntime repository if it was preserved
			if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
				mkdir -p "$BUILD_DIR"
				mv "$TEMP_DIR" "$ONNX_RUNTIME_DIR"
				echo -e "${GREEN}ONNXRuntime repository restored.${NC}"
			fi

			# restore stamp files if they were preserved
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

# configure generator arguments
if [[ "$USE_NINJA" == "ON" ]]; then
	GENERATOR_ARGS=("-G" "Ninja")
else
	if [[ "$IS_WINDOWS" == "true" ]]; then
		GENERATOR_ARGS=("-G" "Visual Studio 17 2022" "-A" "x64")
	else
		GENERATOR_ARGS=()
	fi
fi

# if [[ "$IS_WINDOWS" == "true" ]]; then
# 	if [[ "$USE_NINJA" == "ON" ]]; then
# 		GENERATOR_ARGS=("-G" "Ninja")
# 	else
# 		GENERATOR_ARGS=("-G" "Visual Studio 17 2022" "-A" "x64")
# 	fi
# else
# 	if [[ "$USE_NINJA" == "ON" ]]; then
# 		GENERATOR_ARGS=("-G" "Ninja")
# 	else
# 		GENERATOR_ARGS=()
# 	fi
# fi

# prepare CMake arguments
CMAKE_ARGS=(
	"-S" "."
	"-B" "build"
	"-DREFERENCE=$REFERENCE"
	"-DSTATIC_BUILD=$STATIC_BUILD"
	"-DUSE_NINJA=$USE_NINJA"
	"-DTARGET_ARCH=$TARGET_ARCH"
	"-DIPHONEOS=$IPHONEOS"
	"-DIPHONESIMULATOR=$IPHONESIMULATOR"
	"-DANDROID=$ANDROID"
	"-DANDROID_API=$ANDROID_API"
	"-DANDROID_ABI=$ANDROID_ABI"
	"-DWASM=$WASM"
	"-DEMSDK_VERSION=$EMSDK_VERSION"
	"-DMSVC_STATIC_RUNTIME=$MSVC_STATIC_RUNTIME"
	"-DUSE_DIRECTML=$USE_DIRECTML"
	"-DUSE_COREML=$USE_COREML"
	"-DUSE_XNNPACK=$USE_XNNPACK"
	"-DUSE_WEBGPU=$USE_WEBGPU"
	"-DUSE_OPENVINO=$USE_OPENVINO"
	"-DUSE_NNAPI=$USE_NNAPI"
	"${GENERATOR_ARGS[@]}"
)

# assemble the final command line -  Windows/ninja builds need a VS environment
if [[ "$IS_WINDOWS" == "true" && "$USE_NINJA" == "ON" ]]; then
	# find default VS installer path to obtain the `vswhere.exe` path
	PROGFILES_X86=$(printenv "ProgramFiles(x86)" 2>/dev/null || echo "")
	[[ -z "$PROGFILES_X86" ]] && PROGFILES_X86="/c/Program Files (x86)"
	VSWHERE_PATH="$PROGFILES_X86/Microsoft Visual Studio/Installer/vswhere.exe"

	# determine VS path
	VS_PATH=$("$VSWHERE_PATH" -latest -property installationPath 2>/dev/null || echo "")
	if [[ -z "$VS_PATH" ]]; then
		echo -e "${RED}Error: Visual Studio installation not found${NC}" >&2
		exit 1
	fi

	# build command for cmd.exe execution
	VSDEVCMD="$(cygpath -d "${VS_PATH}")/Common7/Tools/vsdevcmd.bat"
	CMAKE_CMD="cmake ${CMAKE_ARGS[*]}"
	BUILD_CMD="cmake --build build --config Release --parallel"
	INSTALL_CMD="cmake --install build"

	FULL_COMMAND=("$COMSPEC" "//c" "${VSDEVCMD} -no_logo -arch=amd64 -host_arch=amd64 && ${CMAKE_CMD} && ${BUILD_CMD} && ${INSTALL_CMD}")
else
	# it's simpler without VS environment
	CONFIGURE_COMMAND=("cmake" "${CMAKE_ARGS[@]}")
	BUILD_COMMAND=("cmake" "--build" "build" "--config" "Release" "--parallel")
	INSTALL_COMMAND=("cmake" "--install" "build")
fi

if [[ "$DRY_RUN" == "ON" ]]; then
	echo -e "${YELLOW}DRY RUN MODE - Commands that would be executed:${NC}"
	echo ""

	if [[ "$IS_WINDOWS" == "true" && "$USE_NINJA" == "ON" ]]; then
		echo -e "${CYAN}${FULL_COMMAND[*]}${NC}"
	else
		echo -e "${CYAN}${CONFIGURE_COMMAND[*]}${NC}"
		echo -e "${CYAN}${BUILD_COMMAND[*]}${NC}"
		echo -e "${CYAN}${INSTALL_COMMAND[*]}${NC}"
	fi
	exit 0
fi

echo -e "${GREEN}Configuring ONNXRuntime build with CMake...${NC}"

# execute the assembled command line
if [[ "$IS_WINDOWS" == "true" && "$USE_NINJA" == "ON" ]]; then
	echo -e "${CYAN}Running cmake via Visual Studio Developer Command Prompt...${NC}"

	# execute
	"${FULL_COMMAND[@]}"
else
	"${CONFIGURE_COMMAND[@]}"

	if [[ $? -ne 0 ]]; then
		echo -e "${RED}CMake configuration failed${NC}" >&2
		exit 1
	fi

	echo -e "${GREEN}Building ONNXRuntime...${NC}"
	"${BUILD_COMMAND[@]}"

	if [[ $? -ne 0 ]]; then
		echo -e "${RED}CMake build failed${NC}" >&2
		exit 1
	fi

	echo -e "${GREEN}Installing...${NC}"
	"${INSTALL_COMMAND[@]}"

	if [[ $? -ne 0 ]]; then
		echo -e "${RED}CMake install failed${NC}" >&2
		exit 1
	fi
fi

echo -e "${GREEN}Completed successfully!${NC}"
