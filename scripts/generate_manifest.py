#!/usr/bin/env python3

"""Generate a manifest JSON for ONNXRuntime artifacts."""

import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

LIBRARY_DIRECTORIES: Tuple[PurePosixPath, ...] = (
    PurePosixPath("onnxruntime/bin"),
    PurePosixPath("onnxruntime/lib"),
)

ONNXRUNTIME_LIBRARY_NAMES = {
    "onnxruntime_sx.dll",
    "onnxruntime_sxd.dll",
    "libonnxruntime_sx.so",
    "libonnxruntime_sxd.so",
    "libonnxruntime_sx.dylib",
    "libonnxruntime_sxd.dylib",
    "onnxruntime.lib",
    "onnxruntimed.lib",
    "libonnxruntime.a",
    "libonnxruntimed.a",
}

EXTRA_FILE_EXTENSIONS = (".dll", ".so", ".dylib", ".pdb")


def _calculate_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    return sha256_hash.hexdigest()


def _get_archive_files(archive_path: Path) -> List[PurePosixPath]:
    """Get list of files in an archive as PurePosixPath objects."""
    with zipfile.ZipFile(archive_path, "r") as zf:
        return [PurePosixPath(name) for name in zf.namelist()]


def _find_lib_directories(files: List[PurePosixPath]) -> List[PurePosixPath]:
    """Find all library (sub-)directories present in a list of files (directory listing).

    Identifies all directories from `LIBRARY_DIRECTORIES` which are found
    as path prefixes in any entry of `files`.
    """
    return [
        lib_dir
        for lib_dir in LIBRARY_DIRECTORIES
        if any(f.is_relative_to(lib_dir) for f in files)
    ]


def _get_files_in_directories(
    files: List[PurePosixPath],
    search_directories: List[PurePosixPath],
) -> Set[PurePosixPath]:
    """Get all files from specified directories with full relative paths.

    Only includes files directly in the directories (not their subdirectories).
    """
    return {f for f in files if f.parent in search_directories}


def _find_onnxruntime_library(files: Set[PurePosixPath]) -> Optional[PurePosixPath]:
    """Find the main ONNXRuntime library by checking file basenames.

    Returns the first file matching a known ORT library name (shared or static).
    (An archive or installation directory is expected to have only one main ORT library.)
    """

    for f in files:
        if f.name in ONNXRUNTIME_LIBRARY_NAMES:
            return f

    return None


def _is_library_file(path: PurePosixPath) -> bool:
    """Check if a path is a runtime library file (shared library or PDB).

    Handles versioned shared libraries like libfoo.so.1.2.3.
    """
    return path.suffix in EXTRA_FILE_EXTENSIONS or ".so" in path.suffixes


def _get_extra_files(
    files: Set[PurePosixPath],
    ort_library: PurePosixPath,
) -> List[PurePosixPath]:
    """Get all extra library files (shared libraries and PDBs).

    The returned file list is *excluding* the main ORT library.
    """
    return sorted(f for f in files if (f != ort_library) and _is_library_file(f))


def _process_artifact(archive_path: Path) -> Optional[Dict]:
    """Process a single artifact archive and extract relevant metadata."""

    sha256 = _calculate_sha256(archive_path)

    try:
        files = _get_archive_files(archive_path)
    except (zipfile.BadZipFile, OSError) as e:
        print(f"Error reading archive {archive_path}: {e}")
        return None

    lib_dirs = _find_lib_directories(files)
    if not lib_dirs:
        print(f"Warning: No library directories found in {archive_path}")
        return None

    lib_files = _get_files_in_directories(files, lib_dirs)
    if not lib_files:
        print(f"Warning: No library files found in {archive_path}")
        return None

    ort_library = _find_onnxruntime_library(lib_files)
    if not ort_library:
        print(f"Warning: No ONNXRuntime library found in {archive_path}")
        return None

    extra_files = _get_extra_files(lib_files, ort_library)

    return {
        "archive": f"{archive_path.stem}.zip",
        "sha256": sha256,
        "ort_lib": ort_library.as_posix(),
        "extra_files": [f.as_posix() for f in extra_files],
    }


def _strip_version_prefix(artifact_name: str) -> str:
    """Strip 'ort-<version>-' prefix from artifact name.

    Artifact names follow pattern: ort-<version>-<target>-<buildtype>
    Returns: <target>-<buildtype>
    """
    parts = artifact_name.split("-", 2)
    if len(parts) >= 3 and parts[0] == "ort":
        if re.fullmatch(r"v?\d+(\.\d+)*", parts[1]):
            return parts[2]
        else:
            return "-".join(parts[1:])

    return artifact_name


def _find_archives(artifacts_dir: Path) -> List[Path]:
    """Find all ZIP files in `artifacts_dir` (recursively)."""
    return sorted([f for f in artifacts_dir.rglob("*.zip") if f.is_file()])


def _get_local_files(root_dir: Path) -> List[PurePosixPath]:
    """Recursively get all regular files in the given directory, returning relative paths.

    Returns PurePosixPath objects for consistency with archive mode.
    """
    return [
        PurePosixPath(path.relative_to(root_dir).as_posix())
        for path in root_dir.rglob("*")
        if path.is_file()
    ]


def _process_local_artifact(root_dir: Path) -> Optional[Dict]:
    """Process a local (installation) directory and extract relevant metadata
        about contained files.

    Args:
        root_dir: Path to the parent directory containing 'onnxruntime/' subdirectory.

    Returns:
        Dictionary with metadata or None if no valid artifacts found.
    """

    onnxruntime_dir = root_dir / "onnxruntime"
    if not onnxruntime_dir.is_dir():
        print(f"Error: 'onnxruntime' subdirectory not found in {root_dir}")
        return None

    files = _get_local_files(onnxruntime_dir)

    # Prefix all paths with "onnxruntime/" to match archive structure
    files = [PurePosixPath("onnxruntime") / f for f in files]

    lib_dirs = _find_lib_directories(files)
    if not lib_dirs:
        print(f"Warning: No library directories found in {root_dir}")
        return None

    lib_files = _get_files_in_directories(files, lib_dirs)
    if not lib_files:
        print(f"Warning: No library files found in {root_dir}")
        return None

    ort_library = _find_onnxruntime_library(lib_files)
    if not ort_library:
        print(f"Warning: No ONNXRuntime library found in {root_dir}")
        return None

    extra_files = _get_extra_files(lib_files, ort_library)

    return {
        "ort_lib": ort_library.as_posix(),
        "extra_files": [f.as_posix() for f in extra_files],
    }


def generate_manifest(
    root_dir: Path,
    output_file: Path,
    local_mode: bool = False,
) -> int:
    """Generate manifest JSON for artifacts.

    Args:
        root_dir: Root directory containing artifacts
        output_file: Path to write the manifest JSON
        local_mode: If True, scan local directory; if False, scan ZIP archives

    Returns:
        0 on success, non-zero on error
    """

    if not (root_dir.exists() and root_dir.is_dir()):
        print(
            f"Error: Input root directory '{str(root_dir)}' is not an existing directory!"
        )
        return 1

    if output_file.exists() and (not output_file.is_file()):
        print(f"Error: Output file path '{str(output_file)}' exists but is not a file!")
        return 1

    if not output_file.exists():
        output_file.parent.mkdir(parents=True, exist_ok=True)

    if local_mode:
        # Local mode: scan a local build directory
        print(f"Processing local artifacts in {root_dir}...")
        manifest = _process_local_artifact(root_dir)
        if manifest is None:
            return 1

        with output_file.open(mode="w") as f:
            json.dump(manifest, f, indent=2)

        print(f"\nManifest generated: {output_file}")
        print(f"Library: {manifest['ort_lib']}")
        return 0

    # Archive mode: scan zip files
    archives = _find_archives(root_dir)
    if not archives:
        print(f"Warning: No archives found in '{str(root_dir)}'")
        return 1

    manifest = {}
    for archive in archives:
        print(f"Processing {archive}...")
        metadata = _process_artifact(archive)
        if metadata:
            artifact_name = _strip_version_prefix(archive.stem).lower()
            manifest[artifact_name] = metadata

    with output_file.open(mode="w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest generated: {output_file}")
    print(f"Total artifacts: {len(manifest)}")

    return 0


def main() -> int:
    """Generate manifest JSON for all artifacts (CLI entry point)."""

    parser = argparse.ArgumentParser(
        description="Generate a JSON manifest for all zip files in a directory"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Local mode: scan a local build directory instead of zip archives",
    )
    default_root_dir = os.environ.get("ORT_INSTALL_DIR", "artifacts")
    parser.add_argument(
        "-r",
        "--root-dir",
        type=Path,
        default=default_root_dir,
        help=f"Root directory path (default: ORT_INSTALL_DIR or 'artifacts')",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default="manifest.json",
        help="Output file path to write the JSON manifest to",
    )
    args = parser.parse_args()

    return generate_manifest(args.root_dir, args.output_file, args.local)


if __name__ == "__main__":
    try:
        exit(main())
    except Exception as e:
        print(f'Failed with exception:\n"{e}"')
        exit(1)
