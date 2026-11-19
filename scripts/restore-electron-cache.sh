#!/usr/bin/env bash
# Join the vendored Electron zips. Each part is under the 100 MiB git limit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HASH="f71d58b9535ad2f1d90f09dd91a30fea648c4fe7e710e38a47d6983edd09e53f"
DEST="$ROOT/vendor/electron-cache/$HASH"
PARTS="$ROOT/vendor/electron-cache/parts"
mkdir -p "$DEST"
for name in electron-v35.7.5-linux-x64.zip electron-v35.7.5-win32-x64.zip; do
  if [[ -f "$DEST/$name" ]]; then
    continue
  fi
  cat "$PARTS/$name".part-* > "$DEST/$name"
done
