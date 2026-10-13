#!/usr/bin/env bash
# Build the .plugin file: clean caches, strict structure check, CLI validation, zip (dev/ and .git excluded).
# Usage: dev/build.sh OUT_DIR
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); OUT=${1:-$ROOT/..}
find "$ROOT" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$ROOT"/agents/*.md "$ROOT"/skills/website-team/roles/
python3 "$ROOT/dev/check_plugin.py" "$ROOT"
python3 "$ROOT/dev/test_hook.py" | tail -1
claude plugin validate "$ROOT/.claude-plugin/plugin.json" | tail -1
V=$(python3 -c "import json;print(json.load(open('$ROOT/.claude-plugin/plugin.json'))['version'])")
F="$OUT/website-team-$V.plugin"; rm -f "$F"
(cd "$ROOT" && zip -qr "$F" . -x ".git/*" -x ".gitignore" -x "dev/*" -x "*.DS_Store" -x "*/__pycache__/*")
echo "built $F ($(unzip -l "$F" | tail -1 | awk '{print $2}') files)"; sha256sum "$F"
