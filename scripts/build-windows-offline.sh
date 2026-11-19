#!/usr/bin/env bash
# Rebuild the Windows installer from vendored caches. No network after the caches exist.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/restore-electron-cache.sh"
export ELECTRON_CACHE="$ROOT/vendor/electron-cache"
export ELECTRON_BUILDER_CACHE="$ROOT/vendor/electron-builder-cache"
export CSC_IDENTITY_AUTO_DISCOVERY=false
cd "$ROOT/frontend"
npm ci --offline --cache "$ROOT/vendor/npm-cache"
npm run dist:win
echo "Installers are in frontend/release"
