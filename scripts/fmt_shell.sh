#!/usr/bin/env bash
# Format all shell scripts using shfmt with .editorconfig settings
#
# Usage: ./scripts/fmt_shell.sh [--check]
#   --check: Only check formatting without modifying files (exit 1 if unformatted)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

if [[ "${1:-}" == "--check" ]]; then
    echo "Checking shell script formatting..."
    if ! shfmt -d .; then
        echo "Some files are not properly formatted. Run './scripts/fmt_shell.sh' to fix."
        exit 1
    fi
    echo "All shell scripts are properly formatted."
else
    echo "Formatting shell scripts..."
    shfmt -w .
    echo "Done."
fi
