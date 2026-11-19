#!/usr/bin/env bash
# Install the vendored Windows wheels into the embeddable runtime. No network.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$ROOT/backend/.venv/bin/pip" ]]; then
  PIP=("$ROOT/backend/.venv/bin/pip")
else
  PIP=(python3 -m pip)
fi
PY="$ROOT/vendor/windows/python"
TARGET="$PY/Lib/site-packages"
mkdir -p "$TARGET"
"${PIP[@]}" install \
  --no-index \
  --find-links "$ROOT/vendor/wheelhouse" \
  --platform win_amd64 \
  --python-version 3.12 \
  --implementation cp \
  --abi cp312 \
  --only-binary=:all: \
  --target "$TARGET" \
  -r "$ROOT/vendor/requirements-windows.txt"
cp "$ROOT/vendor/windows/sitecustomize.py" "$TARGET/sitecustomize.py"
printf 'python312.zip\r\n.\r\nLib\\site-packages\r\nimport site\r\n' > "$PY/python312._pth"
find "$PY" -type d -name __pycache__ -prune -exec rm -rf {} +
echo "Windows runtime ready at $PY"
