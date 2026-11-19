#!/usr/bin/env bash
# Build the Linux desktop installers (AppImage and deb).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npm run dist:linux
echo "Installers are in frontend/release"
