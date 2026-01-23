#!/usr/bin/env python3

"""Cross-platform utilities for build system."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path, PurePath
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None  # Optional dependency for shell detection


def detect_os() -> str:
    """Detect the operating system.

    Returns:
        Normalized OS name: 'windows', 'linux', 'macos'
    """
    # Check environment variables first (for CI/build environments)
    if os.environ.get("RUNNER_OS") == "Windows" or os.environ.get("OS") == "Windows_NT":
        return "windows"

    system = platform.system().lower()

    if system == "linux":
        return "linux"
    elif system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    else:
        raise RuntimeError(f"Unsupported operating system: {system}")


def detect_arch() -> str:
    """Detect CPU architecture.

    Returns:
        Normalized architecture: 'x86_64', 'aarch64', 'arm64'
    """
    machine = platform.machine().lower()

    # Normalize architecture names
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    elif machine in ("arm64", "aarch64"):
        # Return arm64 for macOS, aarch64 for others
        if detect_os() == "macos":
            return "arm64"
        return "aarch64"
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")


def is_windows() -> bool:
    """Check if running on Windows."""
    return detect_os() == "windows"


def is_linux() -> bool:
    """Check if running on Linux."""
    return detect_os() == "linux"


def is_macos() -> bool:
    """Check if running on macOS."""
    return detect_os() == "macos"


def is_msys2() -> bool:
    """Check if running in MSYS2/Git Bash on Windows."""
    return bool(os.environ.get("MSYSTEM") or os.environ.get("MSYS"))


def detect_shell() -> str:
    """Detect the user's shell.

    This checks the current shell environment, which may differ from the OS.
    For example, on Windows we could be running in Git Bash, MSYS2, or WSL.

    Returns:
        Shell name: 'bash', 'fish', 'csh', 'powershell', 'cmd'
    """
    # Check for MSYS2 bash (Windows) - highest priority
    if is_msys2():
        return "bash"

    # Check SHELL env var (works for most Unix-like shells)
    shell_env = os.environ.get("SHELL", "")

    if shell_env:
        # We have a SHELL variable, so we're in a Unix-like shell
        if "fish" in shell_env:
            return "fish"
        elif "csh" in shell_env:
            return "csh"
        elif "bash" in shell_env or "sh" in shell_env:
            return "bash"

    # No SHELL variable, check Windows-specific indicators
    if os.name == "nt":
        if psutil:
            try:
                parent_name = psutil.Process(os.getppid()).name()
                if re.fullmatch(r"pwsh|pwsh\.exe|powershell\.exe", parent_name):
                    return "powershell"
            except Exception:
                pass
        return "cmd"

    # Default for Unix systems
    return "bash"


def to_native_path(path: PurePath | str) -> str:
    """Convert path to native format.

    On Windows with MSYS2/Git Bash, converts to Windows-style paths.
    Otherwise returns the path as-is.

    Args:
        path: Path to convert

    Returns:
        Native path string
    """
    path = str(path)

    if not (is_windows() and is_msys2()):
        return path

    try:
        # Convert to Windows path using cygpath
        result = subprocess.run(
            ["cygpath", "-w", path], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to manual conversion
        return convert_msys2_path_to_windows(path)


def to_posix_path(path: str) -> str:
    """Convert Windows path to POSIX format for MSYS2.

    Args:
        path: Path to convert

    Returns:
        POSIX path string
    """
    return convert_windows_path_for_msys2(path) if is_windows() else path


def convert_windows_path_for_msys2(path_string: str) -> str:
    """Convert Windows-style paths to MSYS2 paths.

    Handles semicolon-separated path lists.
    Examples:
        C:\\path -> /c/path
        D:\\folder;C:\\other -> /d/folder:/c/other

    Args:
        path_string: Windows path or list of paths (semicolon-separated)

    Returns:
        MSYS2-style path(s) (colon-separated if multiple)
    """
    paths = path_string.split(";")
    converted = []

    for path in paths:
        if not path:
            continue
        # Convert C:\path to /c/path
        if len(path) >= 3 and path[1] == ":" and path[2] == "\\":
            drive = path[0].lower()
            rest = path[3:].replace("\\", "/")
            converted.append(f"/{drive}/{rest}")
        else:
            # Already Unix-style or relative path
            converted.append(path.replace("\\", "/"))

    return ":".join(converted)


def convert_msys2_path_to_windows(msys2_path: str) -> str:
    """Convert MSYS2-style path to Windows-style path.

    Examples:
        /c/path/to/file -> C:\\path\\to\\file
        /d/folder -> D:\\folder
        C:\\already\\windows -> C:\\already\\windows (unchanged)

    Args:
        msys2_path: MSYS2 path

    Returns:
        Windows-style path
    """
    # If already a Windows path (has drive letter), return as-is
    if len(msys2_path) >= 3 and msys2_path[1] == ":":
        return msys2_path

    # Convert MSYS2 path /c/path to C:\path
    if msys2_path.startswith("/") and len(msys2_path) >= 3 and msys2_path[2] == "/":
        drive = msys2_path[1].upper()
        rest = msys2_path[3:].replace("/", "\\")
        return f"{drive}:\\{rest}"

    # If it's a relative path or doesn't match pattern, return as-is
    return msys2_path


def resolve_install_dir(cli_install_dir: Optional[str], build_dir: Path) -> Path:
    """Resolve install directory with precedence: CLI arg > env var > default.

    Args:
        cli_install_dir: Install directory from CLI (may be None)
        build_dir: Build directory (for computing default)

    Returns:
        Resolved install directory path
    """
    if cli_install_dir:
        return Path(cli_install_dir)
    elif os.environ.get("ORT_INSTALL_DIR"):
        return Path(os.environ["ORT_INSTALL_DIR"])
    else:
        return build_dir / "install"


def normalize_arch(arch: str) -> str:
    """Normalize architecture string to standard names which
        our CMake configuration expects.
        Modifications here aren't a matter of taste.

    Args:
        arch: Architecture string (e.g., 'arm64', 'aarch64', 'x86_64')

    Returns:
        Normalized architecture name ('x86_64', 'aarch64', 'armeabi' if recognized, otherwise lowercase input arch)
    """
    arch_lower = arch.lower()
    match arch_lower:
        case "x86_64" | "amd64" | "x64":
            return "x86_64"
        case "arm64" | "aarch64":
            return "aarch64"
        case "armeabi" | "armeabi-v7a":
            return "armeabi"
        case _:
            return arch_lower
