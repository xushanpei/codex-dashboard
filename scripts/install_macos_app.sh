#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/Codex Dashboard.app"
DEST=${CODEX_DASHBOARD_APP_DEST:-"$HOME/Applications/Codex Dashboard.app"}

if [ ! -x "$APP/Contents/MacOS/CodexDashboard" ]; then
  sh "$ROOT/scripts/build_menu_bar.sh"
fi
mkdir -p "$(dirname "$DEST")"
ditto "$APP" "$DEST"
if [ "${CODEX_DASHBOARD_NO_OPEN:-0}" != "1" ]; then
  open "$DEST"
fi
echo "Codex Dashboard 已安装到 $DEST"
