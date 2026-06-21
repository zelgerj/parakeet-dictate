#!/usr/bin/env bash
# Builds "dist/Parakeet Dictate.app" (unsigned) from source.
# Usage (from the repo root):  ./packaging/build_app.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"

echo "==> Generating icon (optional)"
"$VENV/bin/python" packaging/make_icon.py || echo "   (icon skipped)"

echo "==> Removing old build artifacts"
rm -rf build "dist/Parakeet Dictate.app"

echo "==> PyInstaller build"
"$VENV/bin/pyinstaller" --noconfirm packaging/ParakeetDictate.spec

echo "==> Done: dist/Parakeet Dictate.app"
