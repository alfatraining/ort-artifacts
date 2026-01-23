#!/usr/bin/env python3

"""
OpenVINO Installation Script

This script downloads, extracts, and configures OpenVINO installations.
It serves as a command-line replacement for the install-openvino-action GitHub Action.

Usage:
    python install_openvino.py --version 2025.1.0
    eval $(python install_openvino.py --version 2025.1.0 --env)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, urlretrieve

from .platform_utils import (
    convert_windows_path_for_msys2,
    detect_arch,
    detect_os,
    detect_shell,
    is_msys2,
    is_windows,
    to_native_path,
)

try:
    import psutil
except ImportError:
    psutil = None  # Optional dependency for Windows shell detection

# Constants
BASE_URL = "https://storage.openvinotoolkit.org"
FILETREE_URL = f"{BASE_URL}/filetree.json"

OPENVINO_PREFIXES = [
    "OPENVINO",
    "OpenVINO",
    "INTEL_OPENVINO",
    "InferenceEngine",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "PKG_CONFIG_PATH",
    "PYTHONPATH",
    "TBB",
    "ngraph",
]


# Custom Exceptions
class OpenVINOInstallError(Exception):
    """Base exception for OpenVINO installation errors."""

    pass


class DownloadError(OpenVINOInstallError):
    """Error during download."""

    pass


class ExtractionError(OpenVINOInstallError):
    """Error during archive extraction."""

    pass


class EnvironmentError(OpenVINOInstallError):
    """Error setting up environment."""

    pass


def log_info(message: str, env_mode: bool, verbose: bool, **kwargs) -> None:
    """Print informational message only if appropriate."""
    if env_mode and not verbose:
        return  # Silent in env mode unless verbose
    print(message, file=sys.stderr if env_mode else None, **kwargs)


def _detect_linux_release() -> str:
    """
    Parse /etc/os-release to determine Linux distribution.
    Returns a string like 'ubuntu22', 'ubuntu24', etc.
    """
    os_release_path = Path("/etc/os-release")

    if not os_release_path.exists():
        raise OpenVINOInstallError(
            "Cannot detect Linux distribution: /etc/os-release not found"
        )

    result: Dict[str, str] = {}
    id_pattern = re.compile(r'^ID="?([a-z]+)"?$')
    version_pattern = re.compile(r'^VERSION_ID="?([0-9]+)\.?.*"?$')

    with open(os_release_path) as f:
        for line in f:
            line = line.strip()

            id_match = id_pattern.match(line)
            if id_match:
                result["id"] = id_match.group(1)

            version_match = version_pattern.match(line)
            if version_match:
                result["version"] = version_match.group(1)

    if "id" not in result or "version" not in result:
        raise OpenVINOInstallError(
            "Could not parse ID and VERSION_ID from /etc/os-release"
        )

    # Return format like "ubuntu22"
    return f"{result['id']}{result['version']}"


def _detect_macos_release(version: str) -> str:
    """
    Determine which macOS release string to use based on OpenVINO version.
    OpenVINO 2024.1.0+ uses 12_6, older versions use 10_15.
    """
    # Parse version string for comparison
    try:
        version_parts = version.split(".")
        year = int(version_parts[0])
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0

        # 2024.1.0 and newer use macOS 12_6
        if year > 2024 or (year == 2024 and minor >= 1):
            return "12_6"
        else:
            return "10_15"

    except (ValueError, IndexError):
        raise OpenVINOInstallError(f"Invalid version format: {version}")


def _apply_version_quirks(os_name: str, release: str, version: str) -> str:
    """
    Apply version-specific compatibility quirks.
    Main quirk: Ubuntu 22 doesn't have packages for 2022.x, so downgrade to Ubuntu 20.
    """
    if os_name == "linux" and release == "ubuntu22" and version.startswith("2022"):
        print(
            "WARNING: Downgrading ubuntu22 to ubuntu20 for OpenVINO 2022.x compatibility",
            file=sys.stderr,
        )
        print(
            "         OpenVINO lacks jammy (22.04) packages for this version, but focal (20.04) should work",
            file=sys.stderr,
        )
        return "ubuntu20"

    return release


def _download_filetree(env_mode: bool, verbose: bool) -> Dict[str, Any]:
    """Download and parse the filetree.json index."""
    log_info(f"Fetching filetree index from {FILETREE_URL}...", env_mode, verbose)

    try:
        with urlopen(FILETREE_URL) as response:
            return json.loads(response.read())
    except (URLError, HTTPError) as e:
        raise DownloadError(f"Failed to download filetree.json: {e}")
    except json.JSONDecodeError as e:
        raise DownloadError(f"Failed to parse filetree.json: {e}")


def _navigate_filetree(
    filetree: Dict[str, Any],
    path_segments: List[str],
) -> List[Dict[str, Any]]:
    """
    Navigate through filetree JSON structure following path segments.
    Returns the children array at the final path.
    """
    current = filetree

    for segment in path_segments:
        if "children" not in current:
            raise DownloadError(
                f"No 'children' found at path segment before '{segment}'"
            )

        # Find the child with matching name
        matched: Optional[Dict[str, Any]] = None
        for child in current["children"]:
            if child.get("name") == segment:
                matched = child
                break

        if not matched:
            raise DownloadError(f"Path segment '{segment}' not found in filetree")

        current = matched

    return current.get("children", [])


def _build_download_url(
    filetree: Dict[str, Any],
    version: str,
    os_name: str,
    release: str,
    arch: str,
) -> Tuple[str, str]:
    """
    Navigate the filetree JSON structure to build download URL.
    Returns tuple of (url, filename).
    """
    # Strip trailing .0 from version for filetree navigation
    version_stripped = re.sub(r"\.0$", "", version)

    if os_name == "windows":
        release = "windows"

    # Navigate filetree: repositories → openvino → packages → version → os
    try:
        packages = _navigate_filetree(
            filetree,
            ["repositories", "openvino", "packages", version_stripped, os_name],
        )
    except DownloadError as e:
        raise DownloadError(
            f"Failed to navigate filetree for version {version}, OS {os_name}: {e}"
        )

    # Find matching file
    # Pattern: {release}_{version}...{arch}.{ext}
    # For Windows: skip files starting with 'pdb_'
    file_extension = "zip" if os_name == "windows" else "tgz"
    file_match = f"{release}_{version_stripped}"
    file_end = f"{arch}.{file_extension}"

    matched_file: Optional[str] = None
    for package in packages:
        if package.get("type") != "file":
            continue

        name = package.get("name", "")

        # Skip PDB files on Windows
        if os_name == "windows" and name.startswith("pdb_"):
            continue

        # Check if file matches our criteria
        if file_match in name and name.endswith(file_end):
            matched_file = name
            break

    if not matched_file:
        raise DownloadError(
            f"No matching package found for:\n"
            f"  OS: {os_name}\n"
            f"  Release: {release}\n"
            f"  Version: {version_stripped}\n"
            f"  Architecture: {arch}\n"
            f"  Expected pattern: *{file_match}*{file_end}"
        )

    url = f"{BASE_URL}/repositories/openvino/packages/{version_stripped}/{os_name}/{matched_file}"
    return url, matched_file


def _download_with_progress(
    url: str,
    dest_path: Path,
    env_mode: bool,
    verbose: bool,
) -> str:
    """
    Download a file with a progress indicator.
    """
    log_info(f"Downloading: {url}", env_mode, verbose)
    log_info(f"Destination: {dest_path}", env_mode, verbose)

    def reporthook(block_num: int, block_size: int, total_size: int) -> None:
        """Simple progress callback."""
        if env_mode and not verbose:
            return  # Silent in env mode

        downloaded = block_num * block_size

        if total_size > 0:
            percent = min(100, downloaded * 100 / total_size)
            bar_length = 50
            filled = int(bar_length * percent / 100)
            bar = "=" * filled + "-" * (bar_length - filled)

            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)

            print(
                f"\r[{bar}] {percent:.1f}% ({downloaded_mb:.1f} MB / {total_mb:.1f} MB)",
                end="",
                flush=True,
                file=sys.stderr if env_mode else None,
            )
        else:
            # Total size unknown
            downloaded_mb = downloaded / (1024 * 1024)
            print(
                f"\rDownloaded: {downloaded_mb:.1f} MB",
                end="",
                flush=True,
                file=sys.stderr if env_mode else None,
            )

    try:
        filename, _ = urlretrieve(url, dest_path, reporthook)
        log_info("", env_mode, verbose)  # New line after progress bar

        file_size = Path(filename).stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        log_info(f"Download complete: {file_size_mb:.1f} MB", env_mode, verbose)

        return filename
    except (URLError, HTTPError) as e:
        raise DownloadError(f"Download failed: {e}")
    except OSError as e:
        raise DownloadError(f"Failed to save file: {e}")


def _extract_archive(
    archive_path: Path,
    dest_dir: Path,
    env_mode: bool,
    verbose: bool,
) -> Path:
    """
    Extract .tgz or .zip archive to destination directory.
    Returns the path to the extracted directory.
    """
    archive_path = Path(archive_path)
    dest_dir = Path(dest_dir)

    log_info(f"Extracting: {archive_path.name}", env_mode, verbose)

    try:
        root_dirs: set[str] = set()

        # Windows uses ZIP
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                namelist = zip_ref.namelist()
                if not namelist:
                    raise ExtractionError("Archive is empty")

                # Extract all files
                zip_ref.extractall(dest_dir)

                # Get the root directory name (first path component)
                for name in namelist:
                    parts = name.split("/")
                    if parts[0]:  # Not empty
                        root_dirs.add(parts[0])

                if not root_dirs:
                    raise ExtractionError("Could not determine extracted directory")

                # Use the first root directory (should only be one)
                extracted_dir = dest_dir / sorted(root_dirs)[0]

        # Linux/macOS use TGZ
        elif archive_path.suffix == ".tgz" or archive_path.name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tar_ref:
                # Get members
                members = tar_ref.getmembers()
                if not members:
                    raise ExtractionError("Archive is empty")

                # Extract all files
                tar_ref.extractall(dest_dir)

                # Get the root directory name
                for member in members:
                    parts = member.name.split("/")
                    if parts[0]:
                        root_dirs.add(parts[0])

                if not root_dirs:
                    raise ExtractionError("Could not determine extracted directory")

                extracted_dir = dest_dir / sorted(root_dirs)[0]

        else:
            raise ExtractionError(f"Unsupported archive format: {archive_path.suffix}")

        if not extracted_dir.exists():
            raise ExtractionError(f"Extracted directory not found: {extracted_dir}")

        log_info(f"Extracted to: {extracted_dir}", env_mode, verbose)
        return extracted_dir

    except (tarfile.TarError, zipfile.BadZipFile) as e:
        raise ExtractionError(f"Failed to extract archive: {e}")
    except OSError as e:
        raise ExtractionError(f"File system error during extraction: {e}")


#
# OpenVINO environment extraction functions
#


def _extract_openvino_env_vars(env_assignment_lines: List[str]) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    for line in env_assignment_lines:
        if "=" in line:
            key, value = line.split("=", 1)
            env_vars[key] = value

    # Filter to only OpenVINO-related variables
    openvino_vars = {
        k: v
        for k, v in env_vars.items()
        if any(prefix in k for prefix in OPENVINO_PREFIXES)
    }

    return openvino_vars


def _source_setupvars_unix(setupvars_script: Path) -> Dict[str, str]:
    """
    Source setupvars.sh and capture environment changes for Unix (Linux/macOS).
    Returns a dictionary of OpenVINO-related environment variables.
    """
    if not setupvars_script.exists():
        raise EnvironmentError(f"Setup script not found: {setupvars_script}")

    # Create a shell command that sources setupvars and prints all env vars
    cmd = f'source "{setupvars_script}" && env'

    try:
        result = subprocess.run(
            ["bash", "-c", cmd], capture_output=True, text=True, check=True
        )

        # Parse environment variables and filter OpenVINO-specific ones
        env_assignments = result.stdout.splitlines()
        openvino_vars = _extract_openvino_env_vars(env_assignments)
        return openvino_vars

    except subprocess.CalledProcessError as e:
        raise EnvironmentError(f"Failed to source setupvars.sh:\n{e.stderr}")
    except FileNotFoundError:
        raise EnvironmentError("bash not found. Is it installed?")


def _source_setupvars_windows(setupvars_script: Path) -> Dict[str, str]:
    """
    Execute setupvars.bat and capture environment changes on Windows.
    Returns a dictionary of OpenVINO-related environment variables.
    """
    if not setupvars_script.exists():
        raise EnvironmentError(f"Setup script not found: {setupvars_script}")

    # OpenVINO's setupvars script needs to find python in its `PATH` which is not always ensured,
    # so we add the current python executable's parent directory
    cmd_env = os.environ.copy()
    cmd_env["PATH"] = f"{str(Path(sys.executable).parent)};{cmd_env['PATH']}"

    try:
        result = subprocess.run(
            ["cmd", "/c", f"call {setupvars_script.name} && set"],
            capture_output=True,
            text=True,
            check=True,
            cwd=setupvars_script.parent,
            env=cmd_env,
        )

        # Parse environment variables and filter OpenVINO-specific ones
        env_assignments = result.stdout.splitlines()
        openvino_vars = _extract_openvino_env_vars(env_assignments)
        return openvino_vars

    except subprocess.CalledProcessError as e:
        raise EnvironmentError(f"Failed to execute setupvars.bat:\n{e.stderr}")
    except FileNotFoundError:
        raise EnvironmentError("cmd.exe not found")


def _source_setupvars_bat_from_bash(setupvars_script: Path) -> Dict[str, str]:
    """
    Execute setupvars.bat from bash (MSYS2, Git Bash) and capture environment.
    Returns a dictionary of OpenVINO-related environment variables.
    """
    if not setupvars_script.exists():
        raise EnvironmentError(f"Setup script not found: {setupvars_script}")

    # OpenVINO's setupvars script needs to find python in its `PATH` which is not always ensured,
    # so we add the current python executable's parent directory
    cmd_env = os.environ.copy()
    cmd_env["PATH"] = f"{str(Path(sys.executable).parent)};{cmd_env['PATH']}"

    try:
        result = subprocess.run(
            ["cmd", "/c", f"call {setupvars_script.name} && set"],
            capture_output=True,
            text=True,
            check=True,
            cwd=setupvars_script.parent,
            env=cmd_env,
        )

        # Parse environment variables from output and extract OpenVino-specific ones
        env_assignments = result.stdout.splitlines()
        openvino_vars = _extract_openvino_env_vars(env_assignments)

        # Convert Windows paths to MSYS2 paths for PATH-like variables
        for key in [
            k for k in openvino_vars if ("path" in k.lower()) or ("dir" in k.lower())
        ]:
            openvino_vars[key] = convert_windows_path_for_msys2(openvino_vars[key])

        return openvino_vars

    except subprocess.CalledProcessError as e:
        raise EnvironmentError(
            f"Failed to execute setupvars.bat (windows bash):\n{e.stderr}"
        )
    except FileNotFoundError:
        raise EnvironmentError("bash not found. Is it installed?")


def _source_setupvars(install_dir: Path) -> Dict[str, str]:
    """
    Source the setupvars script and capture environment variables.
    Returns a dictionary of environment variables set by setupvars.

    Note: Even if os_name is 'windows' (for package download), we may be running
    in bash on Windows (Git Bash, WSL, MSYS2), so we check the actual shell first.
    """
    install_dir = Path(install_dir).absolute().resolve()

    # Check if we're running in a Unix-like shell (even on Windows)
    # This handles cases like Git Bash, WSL, or MSYS2 on Windows
    current_shell = detect_shell()

    if current_shell in ("bash", "fish", "csh"):
        # Try setupvars.sh first (Linux/macOS style)
        setupvars_sh = install_dir / "setupvars.sh"
        if setupvars_sh.exists():
            return _source_setupvars_unix(setupvars_sh)

        # If on Windows and no .sh file, use batch file from bash
        if os.name == "nt":
            setupvars_bat = install_dir / "setupvars.bat"
            if setupvars_bat.exists():
                return _source_setupvars_bat_from_bash(setupvars_bat)

        raise EnvironmentError(
            f"No setupvars script found in {install_dir}. "
            f"Expected setupvars.sh or setupvars.bat"
        )

    elif current_shell == "powershell":
        # PowerShell on Windows - try .ps1 first, fallback to .bat
        setupvars_ps1 = install_dir / "setupvars.ps1"
        if setupvars_ps1.exists():
            # For now, fallback to .bat as we don't have PS1 executor yet
            # TODO: Implement PowerShell script execution
            pass
        setupvars_bat = install_dir / "setupvars.bat"
        return _source_setupvars_windows(setupvars_bat)
    else:
        # cmd on Windows
        setupvars_bat = install_dir / "setupvars.bat"
        return _source_setupvars_windows(setupvars_bat)


def _print_env_exports(env_vars: Dict[str, str], shell: Optional[str] = None) -> None:
    """
    Print shell commands to export environment variables.
    If shell is None, auto-detect.
    """
    if shell is None:
        shell = detect_shell()

    # Print appropriate export commands based on shell
    for key, value in sorted(env_vars.items()):
        if shell == "fish":
            print(f'set -gx {key} "{value}";')
        elif shell == "csh":
            print(f'setenv {key} "{value}";')
        elif shell == "cmd":
            print(f"set {key}={value}")
        elif shell == "powershell":
            print(f'$env:{key}="{value}";')
        else:  # bash/zsh
            print(f'export {key}="{value}";')


def _parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Install OpenVINO binaries and configure environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic installation with auto-detection
  python install_openvino.py --version 2025.1.0

  # Install and print environment setup commands
  eval $(python install_openvino.py --version 2025.1.0 --env)

  # Override auto-detection
  python install_openvino.py --version 2024.2.0 --os linux --release ubuntu20 --arch x86_64

  # Install to specific directory
  python install_openvino.py --version 2025.1.0 --install-dir /opt/intel
        """,
    )

    parser.add_argument(
        "--version", required=True, help="OpenVINO release version (e.g., 2025.1.0)"
    )

    parser.add_argument(
        "--os",
        choices=["linux", "macos", "windows"],
        help="Operating system (auto-detected if not specified)",
    )

    parser.add_argument(
        "--release",
        help="Distribution release (e.g., ubuntu24, ubuntu22, ubuntu20, 12_6, 10_15). "
        "Auto-detected for Linux/macOS",
    )

    parser.add_argument(
        "--arch",
        choices=["x86_64", "arm64"],
        help="CPU architecture (auto-detected if not specified)",
    )

    parser.add_argument(
        "--env",
        action="store_true",
        default=False,
        help="Print shell commands to set up environment variables (for use with eval)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show progress messages on stderr (only effective with --env)",
    )

    parser.add_argument(
        "--install-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to install OpenVINO (default: current directory)",
    )

    parser.add_argument(
        "--keep-archive",
        action="store_true",
        default=True,
        help="Keep downloaded archive after extraction (caching)",
    )

    return parser.parse_args()


def _download_and_install_sdk(
    version: str,
    os_name: str,
    arch: str,
    release: str,
    install_dir: Path,
    keep_archive: bool,
    env_mode: bool,
    verbose: bool,
) -> Path:
    """Internal: download and extract OpenVINO.

    This is the shared core logic used by both the programmatic API
    and the CLI entry point.

    Args:
        version: OpenVINO version (e.g., "2025.2")
        os_name: Target OS ("linux", "macos", "windows")
        arch: Target architecture ("x86_64", "arm64")
        release: OS release identifier (e.g., "ubuntu22", "windows", "12_6")
        install_dir: Directory to install OpenVINO
        keep_archive: Whether to keep the downloaded archive
        env_mode: If True, suppress stdout (for eval usage)
        verbose: If True, show progress on stderr (only effective with env_mode)

    Returns:
        Path to the extracted OpenVINO directory

    Raises:
        DownloadError: If download fails
        ExtractionError: If archive extraction fails
    """
    # Apply version quirks
    release = _apply_version_quirks(os_name, release, version)

    # Ensure install directory exists
    install_dir = Path(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    # Download filetree and build URL
    filetree = _download_filetree(env_mode=env_mode, verbose=verbose)
    url, filename = _build_download_url(filetree, version, os_name, release, arch)

    # Download archive (if not already cached)
    archive_path = install_dir / filename
    if archive_path.exists() and archive_path.is_file():
        log_info(f"Archive already exists: {archive_path}", env_mode, verbose)
    else:
        _download_with_progress(url, archive_path, env_mode=env_mode, verbose=verbose)

    # Extract archive
    extracted_dir = _extract_archive(
        archive_path, install_dir, env_mode=env_mode, verbose=verbose
    )

    # Clean up archive if requested
    if not keep_archive:
        log_info(f"Removing archive: {archive_path.name}", env_mode, verbose)
        archive_path.unlink()

    return extracted_dir


def install_and_get_env_vars(
    version: str,
    os_name: str,
    arch: str,
    release: str,
    install_dir: Path,
    keep_archive: bool = True,
    verbose: bool = False,
) -> Dict[str, str]:
    """Install OpenVINO and return environment variables as a dict.

    This is the programmatic API for use by other Python modules.
    Unlike the CLI, this function:
    - Does NOT print shell-formatted export commands
    - Does NOT require psutil for shell detection
    - Returns environment variables directly as a Python dict

    Args:
        version: OpenVINO version (e.g., "2025.2")
        os_name: Target OS ("linux", "macos", "windows")
        arch: Target architecture ("x86_64", "arm64")
        release: OS release identifier (e.g., "ubuntu22", "windows", "12_6")
        install_dir: Directory to install OpenVINO
        keep_archive: Whether to keep the downloaded archive (default: True)
        verbose: Whether to print progress messages to stderr (default: False)

    Returns:
        Dict[str, str]: Environment variables set by OpenVINO setupvars script

    Raises:
        OpenVINOInstallError: If installation fails
        DownloadError: If download fails
        ExtractionError: If archive extraction fails
        EnvironmentError: If environment setup fails
    """
    extracted_dir = _download_and_install_sdk(
        version=version,
        os_name=os_name,
        arch=arch,
        release=release,
        install_dir=install_dir,
        keep_archive=keep_archive,
        env_mode=True,
        verbose=verbose,
    )

    if verbose:
        print(f"OpenVINO installed to: {extracted_dir}", file=sys.stderr)

    return _source_setupvars(extracted_dir)


def install_and_initialize_sdk(
    version: str,
    os_name: str,
    arch: str,
    release: str,
    install_dir: Path,
    keep_archive: bool = True,
    verbose: bool = False,
) -> Dict[str, str]:

    # Install and get environment variables directly
    env_vars = install_and_get_env_vars(
        version=version,
        os_name=os_name,
        arch=arch,
        release=release,
        install_dir=install_dir,
        keep_archive=keep_archive,
        verbose=verbose,
    )

    # Apply environment variables
    applied_env_vars: Dict[str, str] = {}
    for key, value in env_vars.items():
        # On Windows in MSYS bash, convert posix-style paths to native Windows paths
        if is_windows() and is_msys2():
            lower_key = key.lower()
            if ("dir" in lower_key) or ("path" in lower_key):
                value_paths = value.split(";") if ";" in value else value.split(":")
                value = ";".join([to_native_path(p) for p in value_paths])

        os.environ[key] = value
        applied_env_vars[key] = value

    return applied_env_vars


def main() -> int:
    """Main entry point."""
    args = _parse_arguments()

    try:
        # 1. Determine platform parameters
        os_name = args.os or detect_os()
        arch = args.arch or detect_arch()

        if os_name == "linux":
            release = args.release or _detect_linux_release()
        elif os_name == "macos":
            release = args.release or _detect_macos_release(args.version)
        else:  # windows
            release = args.release or "windows"

        # Apply version quirks
        release = _apply_version_quirks(os_name, release, args.version)

        # Print configuration
        log_info("=" * 70, args.env, args.verbose)
        log_info("OpenVINO Installation Configuration", args.env, args.verbose)
        log_info("=" * 70, args.env, args.verbose)
        log_info(f"  Version:      {args.version}", args.env, args.verbose)
        log_info(f"  OS:           {os_name}", args.env, args.verbose)
        log_info(f"  Release:      {release}", args.env, args.verbose)
        log_info(f"  Architecture: {arch}", args.env, args.verbose)
        log_info(f"  Install Dir:  {args.install_dir}", args.env, args.verbose)
        log_info("=" * 70, args.env, args.verbose)
        log_info("", args.env, args.verbose)

        # 2. Download and extract using shared core logic
        extracted_dir = _download_and_install_sdk(
            version=args.version,
            os_name=os_name,
            arch=arch,
            release=release,
            install_dir=args.install_dir,
            keep_archive=args.keep_archive,
            env_mode=args.env,
            verbose=args.verbose,
        )

        log_info("", args.env, args.verbose)
        log_info("=" * 70, args.env, args.verbose)
        log_info(
            f"✓ OpenVINO installed successfully to: {extracted_dir}",
            args.env,
            args.verbose,
        )
        log_info("=" * 70, args.env, args.verbose)

        # 6. Set up environment if requested
        if args.env:
            env_vars = _source_setupvars(extracted_dir)
            _print_env_exports(env_vars)
        else:
            log_info("", args.env, args.verbose)
            log_info("To set up your environment, run:", args.env, args.verbose)

            # Detect current shell to provide appropriate instructions
            current_shell = detect_shell()
            if current_shell in ("bash", "fish", "csh"):
                log_info(
                    f'  source "{extracted_dir}/setupvars.sh"', args.env, args.verbose
                )
            elif current_shell == "powershell":
                log_info(
                    f'  & "{extracted_dir}\\setupvars.bat"', args.env, args.verbose
                )
            else:
                log_info(
                    f'  call "{extracted_dir}\\setupvars.bat"', args.env, args.verbose
                )

            log_info("", args.env, args.verbose)
            log_info("Or use the --env flag with eval:", args.env, args.verbose)
            if current_shell in ("bash", "fish", "csh"):
                log_info(
                    f"  eval $(python {sys.argv[0]} --version {args.version} --env)",
                    args.env,
                    args.verbose,
                )
            elif current_shell == "powershell":
                log_info(
                    f"  python {sys.argv[0]} --version {args.version} --env | Invoke-Expression",
                    args.env,
                    args.verbose,
                )
            else:
                log_info(
                    f"  REM (eval equivalent not available in cmd)",
                    args.env,
                    args.verbose,
                )

        return 0

    except KeyboardInterrupt:
        print("\n\nInstallation cancelled by user", file=sys.stderr)
        return 130

    except OpenVINOInstallError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
