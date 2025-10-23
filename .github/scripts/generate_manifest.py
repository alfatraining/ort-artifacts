#!/usr/bin/env python3
"""Generate a manifest JSON for all ONNX Runtime artifacts."""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set

# Constants
LIBRARY_DIRECTORIES = ["onnxruntime/bin", "onnxruntime/lib"]

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


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_archive_files(archive_path: Path) -> List[str]:
    """Get list of files in an archive."""
    with zipfile.ZipFile(archive_path, "r") as zf:
        return zf.namelist()


def find_lib_directories(files: List[str]) -> List[str]:
    """Find all library directories present in the archive."""
    return [
        lib_dir
        for lib_dir in LIBRARY_DIRECTORIES
        if any(f.startswith(f"{lib_dir}/") for f in files)
    ]


def get_files_in_directories(files: List[str], directories: List[str]) -> Set[str]:
    """Get all files from specified directories with full relative paths.

    Only includes files directly in the directories (not subdirectories).
    """
    result = set()
    for directory in directories:
        dir_prefix = f"{directory}/"
        for f in files:
            if f.startswith(dir_prefix):
                relative = f[len(dir_prefix):]
                if relative and "/" not in relative:
                    result.add(f)
    return result


def find_onnxruntime_library(files: Set[str]) -> Optional[str]:
    """Find the main ONNX Runtime library by checking file basenames."""
    for f in files:
        basename = Path(f).name
        if basename in ONNXRUNTIME_LIBRARY_NAMES:
            return f
    return None


def get_extra_files(files: Set[str], ort_library: str) -> List[str]:
    """Get all extra library files (DLLs, shared libraries, PDBs) except main library."""
    extra = []
    for f in files:
        if f == ort_library:
            continue
        # Include files with library extensions or .so version symlinks
        if f.endswith(EXTRA_FILE_EXTENSIONS) or ".so." in f:
            extra.append(f)
    return sorted(extra)


def process_artifact(archive_path: Path) -> Optional[Dict]:
    """Process a single artifact archive and extract metadata."""
    sha256 = calculate_sha256(archive_path)

    try:
        files = get_archive_files(archive_path)
    except (zipfile.BadZipFile, OSError) as e:
        print(f"Error reading archive {archive_path}: {e}")
        return None

    lib_dirs = find_lib_directories(files)
    if not lib_dirs:
        print(f"Warning: No library directories found in {archive_path}")
        return None

    lib_files = get_files_in_directories(files, lib_dirs)
    if not lib_files:
        print(f"Warning: No library files found in {archive_path}")
        return None

    ort_library = find_onnxruntime_library(lib_files)
    if not ort_library:
        print(f"Warning: No ONNX Runtime library found in {archive_path}")
        return None

    extra_files = get_extra_files(lib_files, ort_library)

    return {
        "archive": f"{archive_path.stem}.zip",
        "sha256": sha256,
        "ort_lib": ort_library,
        "extra_files": extra_files,
    }


def strip_version_prefix(artifact_name: str) -> str:
    """Strip 'ort-<version>-' prefix from artifact name.

    Artifact names follow pattern: ort-<version>-<target>-<buildtype>
    Returns: <target>-<buildtype>
    """
    parts = artifact_name.split("-", 2)
    if len(parts) >= 3 and parts[0] == "ort":
        return parts[2]
    return artifact_name


def find_archives(artifacts_dir: Path) -> List[Path]:
    """Find all ZIP archives in artifacts directory and subdirectories."""
    return sorted(artifacts_dir.glob("**/*.zip"))


def main():
    """Generate manifest JSON for all artifacts."""
    artifacts_dir = Path("artifacts")

    if not artifacts_dir.exists():
        print("Error: artifacts/ directory not found")
        return

    archives = find_archives(artifacts_dir)
    if not archives:
        print("Warning: No archives found in artifacts/")
        return

    manifest = {}
    for archive in archives:
        print(f"Processing {archive}...")
        metadata = process_artifact(archive)
        if metadata:
            artifact_name = strip_version_prefix(archive.stem).lower()
            manifest[artifact_name] = metadata

    manifest_path = Path("manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest generated: {manifest_path}")
    print(f"Total artifacts: {len(manifest)}")


if __name__ == "__main__":
    main()
