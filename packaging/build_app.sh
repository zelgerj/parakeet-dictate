#!/usr/bin/env bash
# Baut "dist/Parakeet Dictate.app" (unsigniert) aus dem Source.
# Nutzung (aus der Repo-Wurzel):  ./packaging/build_app.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"

echo "==> Icon erzeugen (optional)"
"$VENV/bin/python" packaging/make_icon.py || echo "   (Icon übersprungen)"

echo "==> Alte Build-Artefakte entfernen"
rm -rf build "dist/Parakeet Dictate.app"

echo "==> PyInstaller-Build"
"$VENV/bin/pyinstaller" --noconfirm packaging/ParakeetDictate.spec

echo "==> Fertig: dist/Parakeet Dictate.app"
