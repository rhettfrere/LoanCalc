#!/usr/bin/env bash
# Build LoanCalc into a macOS app bundle: build/LoanCalc.app
# Usage:  ./build_apple.sh            (or: bash build_apple.sh)
#         ./build_apple.sh --clean
#         ./build_apple.sh --console  (prints how to run with Terminal output)

set -eo pipefail
cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "[!] build_apple.sh must be run on macOS. Use build.bat on Windows."
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "[!] uv is not on PATH. Install it from https://astral.sh/uv"
    exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
    echo "[!] Nuitka needs the Xcode Command Line Tools. Run: xcode-select --install"
    exit 1
fi

echo "[1/3] Syncing dependencies..."
uv sync --extra build

echo "[2/3] Running tests..."
uv run --extra build pytest -q

echo "[3/3] Compiling with Nuitka..."
uv run --extra build python build.py "$@"

echo
echo "Done. Launch with: open build/LoanCalc.app"
