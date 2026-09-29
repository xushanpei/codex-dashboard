#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/Codex Pulse.app"
ARCH_DIR="$ROOT/dist/architectures"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$ARCH_DIR"
xcrun swiftc -target arm64-apple-macosx13.0 "$ROOT/menu-bar/CodexPulse.swift" -o "$ARCH_DIR/CodexPulse-arm64"
xcrun swiftc -target x86_64-apple-macosx13.0 "$ROOT/menu-bar/CodexPulse.swift" -o "$ARCH_DIR/CodexPulse-x86_64"
xcrun lipo -create "$ARCH_DIR/CodexPulse-arm64" "$ARCH_DIR/CodexPulse-x86_64" -output "$APP/Contents/MacOS/CodexPulse"
xcrun lipo "$APP/Contents/MacOS/CodexPulse" -verify_arch arm64 x86_64
cp "$ROOT/scripts/collector.py" "$APP/Contents/Resources/collector.py"
cp "$ROOT/scripts/account_status.py" "$APP/Contents/Resources/account_status.py"
cp "$ROOT/assets/codex-mark.png" "$APP/Contents/Resources/codex-mark.png"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>local.codex.pulse</string>
  <key>CFBundleName</key><string>Codex Pulse</string>
  <key>CFBundleExecutable</key><string>CodexPulse</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
echo "$APP"
