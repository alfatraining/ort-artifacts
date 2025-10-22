#!/usr/bin/env python3
"""Generate a manifest JSON for all ONNX Runtime artifacts."""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set

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


def find_lib_directory(files: List[str]) -> Optional[str]:
    """Find the library directory in the archive (bin or lib)."""
    # Check for bin directory first.
    if any(f.startswith("onnxruntime/bin/") for f in files):
        return "onnxruntime/bin"
    # Fallback to lib directory.
    if any(f.startswith("onnxruntime/lib/") for f in files):
        return "onnxruntime/lib"
    return None


def get_files_in_directory(files: List[str], directory: str) -> Set[str]:
    """Get all files in a specific directory from the archive."""
    dir_prefix = directory + "/"
    result = set()
    for f in files:
        if f.startswith(dir_prefix):
            relative = f[len(dir_prefix):]
            # Only files directly in the directory (not subdirectories).
            if relative and "/" not in relative:
                result.add(relative)
    return result


def find_onnxruntime_library(files: Set[str]) -> Optional[str]:
    """Find the main ONNX Runtime library."""
    for f in files:
        if f in (
            "onnxruntime_sx.dll",
            "onnxruntime_sxd.dll",
            "libonnxruntime_sx.so",
            "libonnxruntime_sxd.so",
            "libonnxruntime_sx.dylib",
            "libonnxruntime_sxd.dylib",
            "onnxruntime.lib",
            "onnxruntimed.lib",
            "libonnxruntime.a",
            "libonnxruntimed.a"):
            return f
    return None


def get_extra_files(files: Set[str], ort_library: str) -> List[str]:
    """Get all extra library files except the main ONNX Runtime library."""
    extensions = (".dll", ".so", ".dylib", ".pdb")
    extra = []

    for f in files:
        # Skip the main onnxruntime library.
        if f == ort_library:
            continue

        # Include files with extensions or symlinks (files with .so. pattern).
        if f.endswith(extensions) or ".so." in f:
            extra.append(f)

    return sorted(extra)


def process_artifact(archive_path: Path) -> Optional[Dict]:
    """Process a single artifact archive and extract metadata."""
    # Calculate SHA256.
    sha256 = calculate_sha256(archive_path)

    # Get archive contents.
    try:
        files = get_archive_files(archive_path)
    except Exception as e:
        print(f"Error reading archive {archive_path}: {e}")
        return None

    # Find library directory.
    lib_dir = find_lib_directory(files)
    if not lib_dir:
        print(f"Warning: No onnxruntime/bin or onnxruntime/lib found in {archive_path}")
        return None

    # Get files in the library directory.
    lib_files = get_files_in_directory(files, lib_dir)

    # Find main ONNX Runtime library.
    ort_library = find_onnxruntime_library(lib_files)
    if not ort_library:
        print(f"Warning: No ONNX Runtime library found in {archive_path}")
        return None

    # Get extra files.
    extra_files = get_extra_files(lib_files, ort_library)

    return {
        "file": archive_path.stem + ".zip",
        "sha256": sha256,
        "dir": lib_dir,
        "ort_lib": ort_library,
        "extra_files": extra_files
    }


def strip_version_prefix(artifact_name: str) -> str:
    """Strip 'ort-<version>-' prefix from artifact name."""
    # Artifact names follow pattern: ort-<version>-<target>-<buildtype>.
    # Remove first two parts (ort and version).
    parts = artifact_name.split("-", 2)
    if len(parts) >= 3 and parts[0] == "ort":
        return parts[2]
    return artifact_name


def find_archives(artifacts_dir: Path) -> List[Path]:
    """Find all archive files in the artifacts directory."""
    # Find .zip files in artifacts/ and artifacts/*/.
    return list(artifacts_dir.glob("*.zip")) + list(artifacts_dir.glob("*/*.zip"))


def main():
    """Generate manifest JSON for all artifacts."""
    artifacts_dir = Path("artifacts")

    if not artifacts_dir.exists():
        print("Error: artifacts/ directory not found")
        return

    # Find all archives.
    archives = find_archives(artifacts_dir)

    if not archives:
        print("Warning: No archives found in artifacts/")
        return

    # Process each archive.
    manifest = {}
    for archive in sorted(archives):
        print(f"Processing {archive}...")
        metadata = process_artifact(archive)
        if metadata:
            artifact_name = strip_version_prefix(archive.stem).lower()
            manifest[artifact_name] = metadata

    # Write manifest.
    manifest_path = Path("manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest generated: {manifest_path}")
    print(f"Total artifacts: {len(manifest)}")


if __name__ == "__main__":
    main()