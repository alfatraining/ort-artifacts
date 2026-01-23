#!/usr/bin/env python3

"""Windows Visual Studio environment utilities."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


class VSEnvironmentError(Exception):
    """Visual Studio environment setup failure."""

    pass


def get_short_path_name(long_path: str) -> str:
    """Convert a path to its 8.3 short form using Windows API.

    Args:
        long_path: The long file path to convert

    Returns:
        The short path, or original path if conversion fails
    """
    from ctypes import c_wchar_p, create_unicode_buffer, windll

    # First call to get required buffer size
    length = windll.kernel32.GetShortPathNameW(c_wchar_p(long_path), None, 0)
    if length == 0:
        return long_path  # Fallback to original path

    # Second call to get the actual short path
    buffer = create_unicode_buffer(length)
    result = windll.kernel32.GetShortPathNameW(c_wchar_p(long_path), buffer, length)
    if result == 0:
        return long_path  # Fallback to original path

    return buffer.value


def find_vswhere() -> Path:
    """Locate vswhere.exe.

    Returns:
        Path to vswhere.exe

    Raises:
        VSEnvironmentError: If vswhere.exe cannot be found
    """
    # Try default VS installer path
    prog_files_x86 = os.environ.get("ProgramFiles(x86)")
    if prog_files_x86:
        vswhere_path = (
            Path(prog_files_x86)
            / "Microsoft Visual Studio"
            / "Installer"
            / "vswhere.exe"
        )
        if vswhere_path.exists():
            return vswhere_path

    # Try common paths
    common_paths = [
        Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"),
        Path(
            "/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
        ),  # MSYS2
    ]

    for path in common_paths:
        if path.exists():
            return path

    # Try PATH
    try:
        result = subprocess.run(
            ["where", "vswhere"], capture_output=True, text=True, check=True
        )
        return Path(result.stdout.strip().split("\n")[0])
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    raise VSEnvironmentError(
        "vswhere.exe not found. Please ensure Visual Studio 2022 or later is installed."
    )


def find_vs_path(version_range: str = "[17,18)") -> Path:
    """Find VS installation using vswhere.

    Args:
        version_range: VS version range (default: "[17,18)" for VS 2022)

    Returns:
        Path to VS installation directory

    Raises:
        VSEnvironmentError: If VS installation cannot be found
    """
    vswhere_path = find_vswhere()

    # Try to find specified version first (VS 2022)
    try:
        result = subprocess.run(
            [
                str(vswhere_path),
                "-products",
                "*",
                "-version",
                version_range,
                "-property",
                "installationPath",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        vs_path = result.stdout.strip()
        if vs_path:
            print(f"Found Visual Studio at: {vs_path}")
            return Path(vs_path)

    except subprocess.CalledProcessError:
        pass

    # Fall back to latest version
    try:
        result = subprocess.run(
            [str(vswhere_path), "-latest", "-property", "installationPath"],
            capture_output=True,
            text=True,
            check=True,
        )
        vs_path = result.stdout.strip()
        if vs_path:
            print(f"Found Visual Studio (latest) at: {vs_path}")
            return Path(vs_path)

    except subprocess.CalledProcessError:
        pass

    raise VSEnvironmentError(
        f"Visual Studio installation not found. Tried version {version_range} and latest."
    )


def get_vsdevcmd_path(vs_path: Path) -> Path:
    """Get path to VsDevCmd.bat.

    Args:
        vs_path: VS installation directory

    Returns:
        Path to VsDevCmd.bat

    Raises:
        VSEnvironmentError: If VsDevCmd.bat cannot be found
    """
    vsdevcmd_path = vs_path / "Common7" / "Tools" / "VsDevCmd.bat"

    if not vsdevcmd_path.exists():
        raise VSEnvironmentError(f"VsDevCmd.bat not found at: {vsdevcmd_path}")

    return vsdevcmd_path


def run_with_vs_env(commands: list[str], arch: str = "amd64") -> int:
    """Execute commands within VS developer environment.

    Constructs: cmd /c "call VsDevCmd.bat && <commands>"

    Args:
        commands: List of commands to execute
        arch: Target architecture (default: "amd64")

    Returns:
        Exit code from command execution

    Raises:
        VSEnvironmentError: If VS environment cannot be set up
    """
    vs_path = find_vs_path()
    vsdevcmd_path = get_vsdevcmd_path(vs_path)

    # Get short path to avoid issues with spaces
    vsdevcmd_short = get_short_path_name(str(vsdevcmd_path))

    # Build the command (no quotes needed - short path has no spaces)
    vsdevcmd_call = f"{vsdevcmd_short} -no_logo -arch={arch} -host_arch={arch}"
    full_command = f'{vsdevcmd_call} && {" && ".join(commands)}'

    comspec = os.environ.get("COMSPEC", "cmd.exe")

    print("Running commands in VS developer environment...")
    print(f'Command: {comspec} /c "{full_command}"')

    # Execute
    result = subprocess.run([comspec, "/c", full_command], shell=False)

    return result.returncode
