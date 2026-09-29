#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$HOME/plugins/codex-pulse"
if [ ! -f "$DEST/.codex-plugin/plugin.json" ]; then
  echo "先通过 plugin-creator 创建个人插件目录和 marketplace 条目。" >&2
  exit 1
fi
rsync -a --exclude dist --exclude .git --exclude .github --exclude .agents --exclude .venv --exclude __pycache__ "$ROOT/" "$DEST/"
python3 - "$DEST" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
path = root / '.mcp.json'
data = json.loads(path.read_text())
data['mcpServers']['codex-pulse']['command'] = sys.executable
data['mcpServers']['codex-pulse']['args'] = [str(root / 'scripts/mcp_server.py')]
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
PY
echo "已同步到 $DEST"
