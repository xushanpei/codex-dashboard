#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/Codex Pulse.app"
DEST=${CODEX_PULSE_APP_DEST:-"$HOME/Applications/Codex Pulse.app"}

if [ ! -x "$APP/Contents/MacOS/CodexPulse" ]; then
  sh "$ROOT/scripts/build_menu_bar.sh"
fi
mkdir -p "$(dirname "$DEST")"
ditto "$APP" "$DEST"
if [ "${CODEX_PULSE_NO_OPEN:-0}" != "1" ]; then
  open "$DEST"
fi
echo "Codex Dashboard 已安装到 $DEST"
