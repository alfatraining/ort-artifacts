#!/usr/bin/env python3

"""
Archive artifacts script - Creates ZIP archives while preserving symlinks.

This script recursively archives a directory into a ZIP file, critically preserving
symbolic links as links (not resolving them to their targets).
"""

import argparse
import os
import stat
import sys
import zipfile
from pathlib import Path


def create_archive_with_symlinks(input_dir: Path, output_file: Path) -> None:
    """
    Create a ZIP archive of a directory, preserving symlinks.

    Args:
        input_dir: Directory to archive
        output_file: Path to the output ZIP file

    Raises:
        FileNotFoundError: If input_dir does not exist
        NotADirectoryError: If input_dir is not a directory
        OSError: If there are permission issues or other I/O errors
    """
    # Validate input directory
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Create the ZIP archive
    with zipfile.ZipFile(output_file, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Walk the directory tree
        for root, dirs, files in os.walk(input_dir):
            root_path = Path(root)

            # Process all entries (files and directories)
            all_entries = dirs + files

            for entry in all_entries:
                full_path = root_path / entry

                # Get file stats without following symlinks
                st = os.lstat(full_path)

                # Calculate the archive name (relative path from input_dir)
                try:
                    arcname = str(full_path.relative_to(input_dir))
                except ValueError:
                    # Should not happen, but handle gracefully
                    arcname = entry

                # Normalize path separators for ZIP format (always use forward slash)
                arcname = arcname.replace(os.sep, "/")

                # Check if this is a symbolic link
                if stat.S_ISLNK(st.st_mode):
                    # Read the symlink target
                    link_target = os.readlink(full_path)

                    # Create ZipInfo with symlink attributes
                    zip_info = zipfile.ZipInfo(arcname)
                    zip_info.create_system = 3  # Unix system
                    zip_info.external_attr = (
                        st.st_mode << 16
                    )  # Preserve all attributes including symlink bit

                    # Write symlink target as the file content
                    zf.writestr(zip_info, link_target)

                    print(f"Added symlink: {arcname} -> {link_target}")

                elif stat.S_ISDIR(st.st_mode):
                    # Directory entry - ensure it ends with /
                    if not arcname.endswith("/"):
                        arcname += "/"

                    zip_info = zipfile.ZipInfo(arcname)
                    zip_info.create_system = 3  # Unix system
                    zip_info.external_attr = (
                        st.st_mode << 16
                    ) | 0x10  # MS-DOS directory flag

                    # Write empty content for directory
                    zf.writestr(zip_info, "")

                    print(f"Added directory: {arcname}")

                elif stat.S_ISREG(st.st_mode):
                    # Regular file
                    zip_info = zipfile.ZipInfo.from_file(full_path, arcname)
                    zip_info.create_system = 3  # Unix system
                    zip_info.external_attr = (
                        st.st_mode << 16
                    )  # Preserve file permissions

                    # Read and write file content
                    with open(full_path, "rb") as f:
                        zf.writestr(
                            zip_info, f.read(), compress_type=zipfile.ZIP_DEFLATED
                        )

                    print(f"Added file: {arcname}")

                else:
                    # Other file types (sockets, devices, etc.) - skip with warning
                    print(f"Warning: Skipping special file: {arcname}", file=sys.stderr)

    print(f"\nArchive created successfully: {output_file}")
    print(f"Archive size: {output_file.stat().st_size:,} bytes")


def main() -> int:
    """
    Main entry point for the script.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = argparse.ArgumentParser(
        description="Create a ZIP archive of a directory while preserving symlinks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ./my_dir ./output.zip
  %(prog)s /path/to/source /path/to/archive.zip
        """,
    )

    parser.add_argument(
        "input_dir",
        type=Path,
        help="Input directory to archive (will be archived recursively)",
    )

    parser.add_argument(
        "output_file",
        type=Path,
        help="Output ZIP file path",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (currently always verbose)",
    )

    args = parser.parse_args()

    try:
        create_archive_with_symlinks(args.input_dir, args.output_file)
        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    except NotADirectoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    except PermissionError as e:
        print(f"Error: Permission denied - {e}", file=sys.stderr)
        return 1

    except OSError as e:
        print(f"Error: I/O error - {e}", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"Error: Unexpected error - {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
