#!/bin/bash
# ──────────────────────────────────────────────────────────────────
# build_app.sh — Builds Sadakalawe.app in the project directory
#
# Usage:   bash build_app.sh
# Output:  Sadakalawe.app  (right here, drag it to your Dock)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Sadakalawe"
APP_DIR="$SCRIPT_DIR/$APP_NAME.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"
RES_DIR="$APP_DIR/Contents/Resources"

echo ""
echo "  Building $APP_NAME.app …"
echo "  Project: $SCRIPT_DIR"
echo ""

# ── Clean previous build ──────────────────────────────────────────
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RES_DIR"

# ── Info.plist ────────────────────────────────────────────────────
cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Sadakalawe</string>
  <key>CFBundleDisplayName</key>       <string>Sadakalawe Sales</string>
  <key>CFBundleExecutable</key>        <string>Sadakalawe</string>
  <key>CFBundleIdentifier</key>        <string>com.sadakalawe.sales</string>
  <key>CFBundleVersion</key>           <string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleSignature</key>         <string>????</string>
  <key>LSMinimumSystemVersion</key>    <string>12.0</string>
  <key>NSHumanReadableCopyright</key>  <string>© 2026 Sadakalawe Enterprises</string>
  <key>LSUIElement</key>               <false/>
  <key>NSHighResolutionCapable</key>   <true/>
</dict>
</plist>
PLIST

# ── Executable shell script ────────────────────────────────────────
# The script lives at Sadakalawe.app/Contents/MacOS/Sadakalawe.
# Three levels up (../../..) is the project root — works wherever the .app
# is placed, as long as it stays inside the project folder.
cat > "$MACOS_DIR/$APP_NAME" << 'EXEC'
#!/bin/bash
# Resolve project directory (three levels up from Contents/MacOS/)
PROJECT="$(cd "$(dirname "$0")/../../.." && pwd)"
LOG="$PROJECT/sadakalawe.log"

# Activate virtual environment
PYTHON="$PROJECT/venv/bin/python3"
LAUNCHER="$PROJECT/launcher.py"

if [ ! -f "$PYTHON" ]; then
  osascript -e "tell app \"System Events\" to display dialog \"Python venv not found at:\n$PYTHON\n\nRun: python3 -m venv venv && pip install -r requirements.txt\" buttons {\"OK\"} default button \"OK\" with icon caution"
  exit 1
fi

if [ ! -f "$LAUNCHER" ]; then
  osascript -e "tell app \"System Events\" to display dialog \"Launcher not found at:\n$LAUNCHER\" buttons {\"OK\"} default button \"OK\" with icon caution"
  exit 1
fi

exec "$PYTHON" "$LAUNCHER" >> "$LOG" 2>&1
EXEC

chmod +x "$MACOS_DIR/$APP_NAME"

# ── Icon ──────────────────────────────────────────────────────────
# Try to build a proper .icns from static/logo.png
LOGO="$SCRIPT_DIR/static/logo.png"
ICNS="$RES_DIR/$APP_NAME.icns"
ICONSET=$(mktemp -d)

if [ -f "$LOGO" ]; then
  echo "  Converting logo.png → .icns …"
  ICONSET_DIR="$ICONSET/icon.iconset"
  mkdir -p "$ICONSET_DIR"

  # Generate all required icon sizes
  for SIZE in 16 32 64 128 256 512 1024; do
    sips -z $SIZE $SIZE "$LOGO" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}.png" \
      > /dev/null 2>&1 || true
  done
  # Retina @2x variants
  for SIZE in 16 32 64 128 256 512; do
    DOUBLE=$((SIZE * 2))
    sips -z $DOUBLE $DOUBLE "$LOGO" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}@2x.png" \
      > /dev/null 2>&1 || true
  done

  iconutil -c icns "$ICONSET_DIR" -o "$ICNS" > /dev/null 2>&1 || true

  if [ -f "$ICNS" ]; then
    echo "  Icon created: $ICNS"
    # Tell plist about the icon
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string $APP_NAME" \
      "$APP_DIR/Contents/Info.plist" > /dev/null 2>&1 || true
  fi
fi

rm -rf "$ICONSET"

# ── Done ──────────────────────────────────────────────────────────
echo ""
echo "  ✅  Built: $APP_DIR"
echo ""
echo "  What to do next:"
echo "  1. Right-click Sadakalawe.app → Open (first time, to bypass Gatekeeper)"
echo "  2. After that, double-click normally or drag it to your Dock"
echo ""
