#!/usr/bin/env python3

"""ONNXRuntime build orchestration script.

This script orchestrates CMake-based builds for ONNXRuntime across multiple platforms.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from pprint import pprint
from typing import Dict, Literal, Optional
from typing import get_args as get_type_args

from generate_manifest import generate_manifest as generate_manifest_json
from internal.archive_artifacts import create_archive_with_symlinks
from internal.platform_utils import (
    is_linux,
    is_windows,
    normalize_arch,
    resolve_install_dir,
    to_native_path,
)
from internal.build_vs import VSEnvironmentError, run_with_vs_env

SupportedPlatform = Literal["win", "linux", "macos", "android", "ios", "wasm"]
SupportedBuildMode = Literal["Debug", "Release", "Both"]

# ORT target version configuration
ORT_TARGET_REFERENCE = "v1.23.2"

# OpenVINO target version/ABI configuration
OPENVINO_SDK_VERSION = "2025.2"
OPENVINO_OS_NAME: Dict[SupportedPlatform, str] = {
    "win": "windows",
    "linux": "linux",
    "macos": "macos",
}
OPENVINO_RELEASE_NAME: Dict[SupportedPlatform, str] = {
    "win": "windows",
    "linux": "ubuntu22",
    "macos": "12_6",
}


# ANSI color codes
class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"  # No Color


# Expectable error exceptions
class BuildError(Exception):
    """Base exception for build errors."""

    def __init__(self, message: str, exit_code: int = 1):
        self.message = message
        self.exit_code = exit_code
        super().__init__(self.message)


class ConfigurationError(BuildError):
    """Invalid configuration or arguments."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=2)


class CMakeError(BuildError):
    """CMake configuration or build failure."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


@dataclass
class ORTBuildConfig:
    """ONNXRuntime build configuration."""

    platform: SupportedPlatform
    arch: str = "x86_64"
    build_mode: SupportedBuildMode = "Release"
    build_dir: Optional[Path] = None
    reference: str = ORT_TARGET_REFERENCE
    static: bool = False

    # Execution providers
    directml: bool = False
    coreml: bool = False
    xnnpack: bool = False
    openvino: bool = False
    nnapi: bool = False
    webgpu: bool = False

    # Platform-specific
    msvc_static_runtime: bool = False
    android_api: int = 35
    android_abi: str = "arm64-v8a"
    iphoneos: bool = False
    iphonesimulator: bool = False
    android: bool = False
    wasm: bool = False
    emsdk_version: str = "4.0.3"

    # Build control
    nuke: bool = False
    nuke_only: bool = False
    clean: bool = False
    clean_only: bool = False
    dry_run: bool = False
    create_archive: bool = True
    local_manifest: bool = False
    archive_name: str = "onnxruntime_artifacts"
    artifact_dir: Optional[Path] = None

    # Toolchain
    use_clang: bool = False
    use_ninja: bool = True

    # Build variant (for auto-generated build dir names)
    variant: str = "dylib"  # or "static"

    def __post_init__(self):
        """Post-initialization processing."""
        # Normalize architecture
        self.arch = normalize_arch(self.arch)

        # Set variant based on static flag
        if self.static:
            self.variant = "static"

        # Auto-generate build_dir if not provided
        if self.build_dir is None:
            self.build_dir = self._generate_build_dir()

    def _generate_build_dir(self) -> Path:
        """Generate build directory name based on platform, arch, and variant."""
        return Path(
            f"build-{self.platform}-{self.arch.replace('aarch64', 'arm64')}-{self.variant}"
        )


def parse_args() -> ORTBuildConfig:
    """Parse command-line arguments and return ORTBuildConfig."""
    parser = argparse.ArgumentParser(
        description="Build ONNXRuntime for various platforms and configurations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    parser.add_argument(
        "--platform",
        required=True,
        choices=["win", "linux", "macos", "android", "ios", "wasm"],
        help="Target platform",
    )

    # Build options
    parser.add_argument(
        "--arch", "-A", default="x86_64", help="Target architecture (default: x86_64)"
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        help="Build directory (auto-generated if not specified)",
    )
    parser.add_argument(
        "--reference",
        "-r",
        default=ORT_TARGET_REFERENCE,
        help=f"ONNXRuntime version/reference (default: {ORT_TARGET_REFERENCE})",
    )
    parser.add_argument(
        "--static", "-s", action="store_true", help="Build static library"
    )

    # Build mode
    bm_group = parser.add_argument_group("Build Modes").add_mutually_exclusive_group()
    bm_group.add_argument(
        "--build-mode",
        "-b",
        default="Both",
        choices=get_type_args(SupportedBuildMode),
        help="Build configuration: Debug, Release, or Both (default: Both)",
    )
    bm_group.add_argument(
        "--debug",
        action="store_const",
        const="Debug",
        dest="build_mode_shortcut",
        help="Set build mode to Debug (same as: -b Debug)",
    )
    bm_group.add_argument(
        "--release",
        action="store_const",
        const="Release",
        dest="build_mode_shortcut",
        help="Set build mode to Release (same as: -b Release)",
    )
    bm_group.add_argument(
        "--debug-and-release",
        action="store_const",
        const="Both",
        dest="build_mode_shortcut",
        help="Build both Debug and Release (same as: -b Both)",
    )
    bm_group.add_argument(
        "--release-and-debug",
        action="store_const",
        const="Both",
        dest="build_mode_shortcut",
        help="Alias for --debug-and-release",
    )
    bm_group.add_argument(
        "--debrel",
        action="store_const",
        const="Both",
        dest="build_mode_shortcut",
        help="Alias for --debug-and-release",
    )
    bm_group.add_argument(
        "--reldeb",
        action="store_const",
        const="Both",
        dest="build_mode_shortcut",
        help="Alias for --debug-and-release",
    )

    # Execution providers
    ep_group = parser.add_argument_group("Execution providers")
    ep_group.add_argument("--directml", action="store_true", help="Enable DirectML EP")
    ep_group.add_argument("--coreml", action="store_true", help="Enable CoreML EP")
    ep_group.add_argument("--xnnpack", action="store_true", help="Enable XNNPACK EP")
    ep_group.add_argument("--openvino", action="store_true", help="Enable OpenVINO EP")
    ep_group.add_argument("--nnapi", action="store_true", help="Enable NNAPI EP")
    ep_group.add_argument("--webgpu", action="store_true", help="Enable WebGPU EP")

    # Platform-specific
    platform_group = parser.add_argument_group("Platform-specific options")
    platform_group.add_argument(
        "--mt", action="store_true", help="Use static MSVC runtime (Windows)"
    )
    platform_group.add_argument(
        "--android-api", type=int, default=35, help="Android API level (default: 35)"
    )
    platform_group.add_argument(
        "--android-abi", default="arm64-v8a", help="Android ABI (default: arm64-v8a)"
    )
    platform_group.add_argument(
        "--iphoneos", action="store_true", help="Target iOS / iPadOS"
    )
    platform_group.add_argument(
        "--iphonesimulator", action="store_true", help="Target iOS / iPadOS simulator"
    )
    platform_group.add_argument("--android", action="store_true", help="Target Android")
    platform_group.add_argument(
        "--wasm", "-W", action="store_true", help="Compile for WebAssembly"
    )
    platform_group.add_argument(
        "--emsdk",
        default="4.0.3",
        help="Emsdk version for WebAssembly (default: 4.0.3)",
    )

    # Build control
    control_group = parser.add_argument_group("Build control")
    control_group.add_argument(
        "--nuke",
        action="store_true",
        help="Remove entire build directory before proceeding",
    )
    control_group.add_argument(
        "--nuke-only",
        action="store_true",
        help="Only remove entire build directory and exit",
    )
    control_group.add_argument(
        "--clean", action="store_true", help="Remove CMakeCache.txt before proceeding"
    )
    control_group.add_argument(
        "--clean-only", action="store_true", help="Only remove CMakeCache.txt and exit"
    )
    control_group.add_argument(
        "--dry-run", action="store_true", help="Print commands without executing"
    )
    control_group.add_argument(
        "--create-archive", action="store_true", help="Create artifact archive"
    )
    control_group.add_argument(
        "--local-manifest", action="store_true", help="Generate local artifact manifest"
    )
    control_group.add_argument(
        "--archive-name",
        default="onnxruntime_artifacts",
        help="Archive name (default: onnxruntime_artifacts)",
    )
    control_group.add_argument(
        "--artifact-dir", type=Path, help="Artifact installation directory"
    )

    # Toolchain
    toolchain_group = parser.add_argument_group("Toolchain options")
    toolchain_group.add_argument(
        "--clang", action="store_true", help="Use clang (set CC=clang CXX=clang++)"
    )
    toolchain_group.add_argument(
        "--ninja",
        "-N",
        action="store_true",
        default=True,
        help="Build with Ninja (default: ON)",
    )

    args = parser.parse_args()

    # Handle build mode shortcut
    if args.build_mode_shortcut:
        args.build_mode = args.build_mode_shortcut

    # Set platform-specific flags
    if args.platform == "android":
        args.android = True
    elif args.platform == "ios":
        args.iphoneos = True
    elif args.platform == "wasm":
        args.wasm = True

    # Handle nuke-only
    if args.nuke_only:
        args.nuke = True

    # Handle clean-only
    if args.clean_only:
        args.clean = True

    # Create ORTBuildConfig
    config = ORTBuildConfig(
        platform=args.platform,
        arch=args.arch,
        build_mode=args.build_mode,
        build_dir=args.build_dir,
        reference=args.reference,
        static=args.static,
        directml=args.directml,
        coreml=args.coreml,
        xnnpack=args.xnnpack,
        openvino=args.openvino,
        nnapi=args.nnapi,
        webgpu=args.webgpu,
        msvc_static_runtime=args.mt,
        android_api=args.android_api,
        android_abi=args.android_abi,
        iphoneos=args.iphoneos,
        iphonesimulator=args.iphonesimulator,
        android=args.android,
        wasm=args.wasm,
        emsdk_version=args.emsdk,
        nuke=args.nuke,
        nuke_only=args.nuke_only,
        clean=args.clean,
        clean_only=args.clean_only,
        dry_run=args.dry_run,
        create_archive=args.create_archive,
        local_manifest=args.local_manifest,
        archive_name=args.archive_name,
        artifact_dir=args.artifact_dir,
        use_clang=args.clang,
        use_ninja=args.ninja,
    )

    return config


def install_openvino_sdk(config: ORTBuildConfig) -> None:
    """Download and install OpenVINO SDK and apply required environment variables.

    Keeps the downloaded archive cached 🤓.
    """
    from internal.install_openvino import (
        OpenVINOInstallError,
        install_and_initialize_sdk,
    )

    script_dir = Path(__file__).parent
    install_dir = script_dir.parent / "openvino_install"

    print(f"{Colors.CYAN}Installing OpenVINO SDK...{Colors.NC}")

    # Determine OpenVINO platform parameters
    if config.platform == "win":
        ov_arch = "x86_64"
    elif config.platform == "linux":
        ov_arch = "x86_64"
    elif config.platform == "macos":
        ov_arch = "x86_64" if config.arch == "x86_64" else "arm64"
    else:
        raise ConfigurationError(
            f"OpenVINO not supported for platform: {config.platform}"
        )

    try:
        applied_env_vars = install_and_initialize_sdk(
            version=OPENVINO_SDK_VERSION,
            os_name=OPENVINO_OS_NAME[config.platform],
            arch=ov_arch,
            release=OPENVINO_RELEASE_NAME[config.platform],
            install_dir=install_dir,
            keep_archive=True,
            verbose=True,
        )
    except OpenVINOInstallError as e:
        raise BuildError(f"OpenVINO installation failed: {e}")

    print("Applied OpenVINO environment variables:")
    pprint(applied_env_vars)
    print("-" * 80)

    # On Linux, patch rpath
    if is_linux():
        print("Patching OpenVINO library rpath...")
        try:
            openvino_libs = list(install_dir.rglob("libopenvino.so.*"))
            for lib in openvino_libs:
                if lib.is_file():
                    subprocess.run(
                        ["patchelf", "--set-rpath", "$ORIGIN", str(lib)], check=True
                    )
                    print(f"\tPatched: {lib}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"{Colors.YELLOW}Warning: Failed to patch rpath: {e}{Colors.NC}")

    print(f"{Colors.GREEN}OpenVINO SDK installed successfully{Colors.NC}")


def nuke_build_dirs(config: ORTBuildConfig) -> None:
    """Remove entire build directory."""
    print(f"{Colors.YELLOW}Performing complete nuke...{Colors.NC}")

    def rmtree_error_handler(func, path, _):
        """Error handler for shutil.rmtree to handle read-only files on Windows."""
        import stat

        # Clear the read-only attribute and retry
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def remove_dir_recursive(dir_path: Path):
        if dir_path.exists():
            # Use error handler to deal with read-only files on Windows
            # Note: onexc is Python 3.12+, onerror works on older versions
            if sys.version_info >= (3, 12):
                shutil.rmtree(
                    dir_path,
                    onexc=lambda f, p, e: rmtree_error_handler(f, p, e),
                )
            else:
                shutil.rmtree(dir_path, onerror=rmtree_error_handler)

            print(f"{Colors.GREEN}{str(dir_path)} was completely removed.{Colors.NC}")
        else:
            print(
                f"{Colors.YELLOW}{str(dir_path)} does not exist - nothing to nuke.{Colors.NC}"
            )

    if config.build_dir:
        remove_dir_recursive(config.build_dir)

    if config.artifact_dir:
        remove_dir_recursive(config.artifact_dir)


def clean_cmake_cache(build_dir: Path) -> None:
    """Remove CMakeCache.txt from build directory."""
    cache_file = build_dir / "CMakeCache.txt"
    if cache_file.exists():
        print(f"{Colors.YELLOW}Cleaning CMakeCache.txt...{Colors.NC}")
        cache_file.unlink()
        print(f"{Colors.GREEN}CMakeCache.txt removed.{Colors.NC}")
    else:
        print(
            f"{Colors.YELLOW}CMakeCache.txt does not exist - nothing to clean.{Colors.NC}"
        )


def setup_android_environment() -> None:
    """Set up Android environment variables."""
    if "ANDROID_HOME" not in os.environ:
        if "ANDROID_SDK_ROOT" in os.environ:
            os.environ["ANDROID_HOME"] = os.environ["ANDROID_SDK_ROOT"]
        else:
            home = Path.home()
            os.environ["ANDROID_HOME"] = str(home / "Android" / "Sdk")

    if "ANDROID_NDK_HOME" not in os.environ:
        android_home = Path(os.environ["ANDROID_HOME"])
        os.environ["ANDROID_NDK_HOME"] = str(android_home / "ndk" / "27.2.12479018")

    # Set ANDROID_NDK (legacy)
    if "ANDROID_NDK" not in os.environ:
        os.environ["ANDROID_NDK"] = os.environ["ANDROID_NDK_HOME"]

    os.environ["ANDROID_STL"] = "c++_shared"

    if "CMAKE_TOOLCHAIN_FILE" not in os.environ:
        android_ndk = Path(os.environ["ANDROID_NDK_HOME"])
        toolchain_file = android_ndk / "build" / "cmake" / "android.toolchain.cmake"
        os.environ["CMAKE_TOOLCHAIN_FILE"] = str(toolchain_file)


def setup_build_environment(config: ORTBuildConfig) -> None:
    """Set up build environment variables.

    Must be called once before execute_build() runs.
    Sets up OpenVINO, Android NDK, and clang environment as needed.

    Note: Environment variables are process-global, so this should
    be called from the main thread before any parallel execution.
    """
    if config.openvino:
        install_openvino_sdk(config)

    if config.android:
        setup_android_environment()

    if config.use_clang:
        os.environ["CC"] = "clang"
        os.environ["CXX"] = "clang++"

        # prebuilt OpenVINO SDK libs link dynamically against libgcc,
        # so we need to do the same to avoid incompatibilities with our
        # statically linked one
        if config.openvino:
            cflags = "-Wno-everything -Wno-all -static-libstdc++"
        else:
            cflags = "-Wno-everything -Wno-all -static-libstdc++ -static-libgcc"

        os.environ["CFLAGS"] = cflags
        os.environ["CXXFLAGS"] = cflags

    print("Build environment has been set up.")


def cmake_configure_args(config: ORTBuildConfig, lower_build_mode: str) -> list[str]:
    """CMake configure step arguments from internal build configuration.

    Args:
        config: Build configuration
        lower_build_mode: Lowercase build mode (for subdirectory)

    Returns:
        List of CMake arguments for the configure step (incl. 'cmake' itself as first argument)
    """
    # this should be guaranteed but the linter doesn't get it
    assert config.build_dir is not None, "BUG: config.build_dir is None"

    # Determine actual build directory (with mode subdirectory)
    actual_build_dir = config.build_dir / lower_build_mode

    # Convert to native path on Windows
    if is_windows():
        build_dir_str = to_native_path(actual_build_dir)
    else:
        build_dir_str = str(actual_build_dir)

    # Resolve install directory
    resolved_install_dir = resolve_install_dir(
        str(config.artifact_dir) if config.artifact_dir else None, config.build_dir
    )
    resolved_install_dir = resolved_install_dir / lower_build_mode

    if is_windows():
        install_dir_str = to_native_path(resolved_install_dir / "onnxruntime")
    else:
        install_dir_str = str(resolved_install_dir / "onnxruntime")

    # Base CMake args
    cmake_args = [
        "cmake",
        "-S",
        ".",
        "-B",
        build_dir_str,
        "--compile-no-warning-as-error",
        f"-DREFERENCE={config.reference}",
        f"-DSTATIC_BUILD={'ON' if config.static else 'OFF'}",
        f"-DCMAKE_BUILD_TYPE={config.build_mode}",
        f"-DTARGET_ARCH={config.arch}",
        f"-DIPHONEOS={'ON' if config.iphoneos else 'OFF'}",
        f"-DIPHONESIMULATOR={'ON' if config.iphonesimulator else 'OFF'}",
        f"-DANDROID={'ON' if config.android else 'OFF'}",
        f"-DANDROID_API={config.android_api}",
        f"-DANDROID_ABI={config.android_abi}",
        f"-DANDROID_STL={os.environ.get('ANDROID_STL', 'c++_shared')}",
        f"-DANDROID_SDK_ROOT={os.environ.get('ANDROID_HOME', '')}",
        f"-DWASM={'ON' if config.wasm else 'OFF'}",
        f"-DEMSDK_VERSION={config.emsdk_version}",
        f"-DMSVC_STATIC_RUNTIME={'ON' if config.msvc_static_runtime else 'OFF'}",
        f"-DUSE_DIRECTML={'ON' if config.directml else 'OFF'}",
        f"-DUSE_COREML={'ON' if config.coreml else 'OFF'}",
        f"-DUSE_XNNPACK={'ON' if config.xnnpack else 'OFF'}",
        f"-DUSE_WEBGPU={'ON' if config.webgpu else 'OFF'}",
        f"-DUSE_OPENVINO={'ON' if config.openvino else 'OFF'}",
        f"-DUSE_NNAPI={'ON' if config.nnapi else 'OFF'}",
        f"-DARTIFACT_DIR={install_dir_str}",
    ]

    # Generator args
    if config.use_ninja:
        cmake_args.extend(["-G", "Ninja"])
    else:
        if is_windows() and not config.android:
            cmake_args.extend(["-G", "Visual Studio 17 2022", "-A", "x64"])

    # Clang configuration (env vars set in setup_build_environment)
    if config.use_clang:
        cmake_args.extend(["-DCMAKE_CXX_COMPILER=clang++", "-DCMAKE_C_COMPILER=clang"])

    return cmake_args


def run_cmake_build(
    cmake_args: list[str],
    build_dir_str: str,
    dry_run: bool = False,
) -> int:
    """Run CMake configuration, build, and install.

    Args:
        cmake_args: CMake arguments
        build_dir_str: Build directory path
        dry_run: If True, only print commands without executing

    Returns:
        Exit code
    """
    build_command = ["cmake", "--build", build_dir_str, "--parallel"]
    install_command = ["cmake", "--install", build_dir_str]

    if dry_run:
        print(
            f"{Colors.YELLOW}DRY RUN MODE - Commands that would be executed:{Colors.NC}"
        )
        print()
        print(f"{Colors.CYAN}{' '.join(cmake_args)}{Colors.NC}")
        print(f"{Colors.CYAN}{' '.join(build_command)}{Colors.NC}")
        print(f"{Colors.CYAN}{' '.join(install_command)}{Colors.NC}")
        return 0

    # Configure
    print(f"{Colors.GREEN}Configuring ONNXRuntime build with CMake...{Colors.NC}")
    result = subprocess.run(cmake_args)
    if result.returncode != 0:
        raise CMakeError("CMake configuration failed")

    # Build
    print(f"{Colors.GREEN}Building ONNXRuntime...{Colors.NC}")
    result = subprocess.run(build_command)
    if result.returncode != 0:
        raise CMakeError("CMake build failed")

    # Install
    print(f"{Colors.GREEN}Installing...{Colors.NC}")
    result = subprocess.run(install_command)
    if result.returncode != 0:
        raise CMakeError("CMake install failed")

    return 0


def execute_build_config(config: ORTBuildConfig) -> int:
    """Execute a single build for the given configuration.

    Assumes setup_build_environment() was already called.
    Handles CMake configuration, build, install, and post-build steps.

    Args:
        config: Build configuration (should have single build_mode, not "Both")

    Returns:
        Exit code (0 = success)
    """
    # this should be guaranteed but the linter doesn't get it
    assert config.build_dir is not None, "BUG: config.build_dir is None"

    lower_build_mode = config.build_mode.lower()
    if lower_build_mode not in ["debug", "release", "relwithdebinfo", "minsizerel"]:
        raise BuildError(
            f"Build mode must be one of 'Release', 'Debug', 'RelWithDebInfo', 'MinSizeRel'"
            " (got: '{config.build_mode}')"
        )

    actual_build_dir = config.build_dir / lower_build_mode

    # Build CMake argument list
    configure_args = cmake_configure_args(config, lower_build_mode)

    if is_windows():
        build_dir_str = to_native_path(actual_build_dir)
    else:
        build_dir_str = str(actual_build_dir)

    # Execute build
    if is_windows() and config.use_ninja and (not config.android):
        # Windows ninja builds need to be explicitly executed in a VS developer environment

        configure_cmd = " ".join(configure_args)
        build_cmd = f"cmake --build {build_dir_str} --parallel"
        install_cmd = f"cmake --install {build_dir_str}"

        if config.dry_run:
            print(
                f"{Colors.YELLOW}DRY RUN MODE - Commands that would be executed:{Colors.NC}"
            )
            print()
            full_cmd = f"{configure_cmd} && {build_cmd} && {install_cmd}"
            print(f'{Colors.CYAN}cmd /c "VsDevCmd.bat ... && {full_cmd}"{Colors.NC}')
            return 0

        print(
            f"{Colors.CYAN}Running cmake via Visual Studio Developer Command Prompt...{Colors.NC}"
        )

        try:
            result = run_with_vs_env([configure_cmd, build_cmd, install_cmd])
            if result != 0:
                return result

        except VSEnvironmentError as e:
            raise BuildError(str(e))
    else:
        result = run_cmake_build(configure_args, build_dir_str, config.dry_run)
        if result != 0:
            return result

    if config.dry_run:
        return 0

    print(f"{Colors.GREEN}Build completed successfully!{Colors.NC}")

    # Post-build operations
    resolved_install_dir = resolve_install_dir(
        str(config.artifact_dir) if config.artifact_dir else None, config.build_dir
    )
    resolved_install_dir = resolved_install_dir / lower_build_mode

    if config.local_manifest:
        generate_manifest(resolved_install_dir, config.dry_run)

    if config.create_archive:
        archive_artifacts(resolved_install_dir, config.archive_name, config.dry_run)

    return 0


def run_parallel_builds(config: ORTBuildConfig) -> int:
    """Run Debug and Release builds in parallel.

    Creates copies of the configuration with Debug and Release build modes,
    then executes them concurrently using thread pool.

    Args:
        config: Base build configuration

    Returns:
        Exit code (0 = success, non-zero = failure)
    """
    import concurrent.futures
    from dataclasses import replace

    # this should be guaranteed but the linter doesn't get it
    assert config.build_dir is not None, "BUG: config.build_dir is None"

    print(f"{Colors.CYAN}Launching parallel Debug + Release builds...{Colors.NC}")

    # Set up environment once before parallel execution
    setup_build_environment(config)

    # Create configs for each build mode
    debug_config = replace(config, build_mode="Debug")
    release_config = replace(config, build_mode="Release")

    # Run builds in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_debug = executor.submit(execute_build_config, debug_config)
        future_release = executor.submit(execute_build_config, release_config)

        debug_result = future_debug.result()
        release_result = future_release.result()

    print(f"{Colors.CYAN}Both builds finished.{Colors.NC}")

    if debug_result != 0 or release_result != 0:
        return max(debug_result, release_result)

    return 0


def generate_manifest(resolved_install_dir: Path, dry_run: bool = False) -> None:
    """Generate local artifact manifest.

    Args:
        resolved_install_dir: Installation directory
        dry_run: If True, only print what would be done without executing
    """
    output_file = resolved_install_dir / "manifest.json"

    if dry_run:
        print(
            f"{Colors.CYAN}generate_manifest({resolved_install_dir}, {output_file}, local_mode=True){Colors.NC}"
        )
        return

    print(f"{Colors.GREEN}Generating local artifact manifest...{Colors.NC}")
    result = generate_manifest_json(resolved_install_dir, output_file, local_mode=True)
    if result == 0:
        print(f"{Colors.GREEN}Complete local manifest generation!{Colors.NC}")
    else:
        print(f"{Colors.YELLOW}Warning: Manifest generation failed{Colors.NC}")


def archive_artifacts(
    resolved_install_dir: Path,
    archive_name: str,
    dry_run: bool = False,
) -> None:
    """Archive build artifacts.

    Args:
        resolved_install_dir: Installation directory
        archive_name: Archive name (without extension)
        dry_run: If True, only print what would be done without executing
    """
    # Determine archive path
    archive_dir = Path(archive_name).parent
    archive_base = Path(archive_name).name.lower()

    if archive_dir == Path("."):
        archive_file_path = Path(".") / f"{archive_base}.zip"
    else:
        archive_file_path = archive_dir / f"{archive_base}.zip"

    if dry_run:
        print(
            f"{Colors.CYAN}create_archive_with_symlinks({resolved_install_dir}, {archive_file_path}){Colors.NC}"
        )
        return

    print(f"{Colors.GREEN}Archiving artifacts...{Colors.NC}")
    try:
        create_archive_with_symlinks(resolved_install_dir, archive_file_path)
        print(f"{Colors.GREEN}Completed archiving to '{archive_file_path}'!{Colors.NC}")
    except (FileNotFoundError, NotADirectoryError, OSError) as e:
        print(f"{Colors.YELLOW}Warning: Archiving failed - {e}{Colors.NC}")


def main() -> int:
    try:
        config = parse_args()

        # this should be guaranteed but the linter doesn't get it
        assert config.build_dir is not None, "BUG: config.build_dir is None"

        # Handle nuke operation
        if config.nuke or config.nuke_only:
            nuke_build_dirs(config)
            if config.nuke_only:
                print("Finished nuking. All done.")
                return 0

            print("Finished nuking. Proceeding.")
            print("----")

        lower_build_mode = config.build_mode.lower()

        # Handle clean operation
        both_build_mode_aliases = (
            "both",
            "debrel",
            "reldeb",
            "dar",
            "rad",
            "brad",
            "debug_and_release",
        )
        if config.clean or config.clean_only:
            if lower_build_mode in both_build_mode_aliases:
                clean_cmake_cache(config.build_dir / "debug")
                clean_cmake_cache(config.build_dir / "release")
            else:
                clean_cmake_cache(config.build_dir / lower_build_mode)

            if config.clean_only:
                print("Finished cleaning. All done.")
                return 0

            print("Finished cleaning. Proceeding.")
            print("----")

        # Handle parallel builds
        if lower_build_mode in both_build_mode_aliases:
            return run_parallel_builds(config)

        # Single build: setup environment and execute
        setup_build_environment(config)
        return execute_build_config(config)

    except BuildError as e:
        print(f"{Colors.RED}Error: {e.message}{Colors.NC}", file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Build cancelled by user{Colors.NC}", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"{Colors.RED}Unexpected error: {e}{Colors.NC}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
