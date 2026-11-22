#!/bin/bash
# Збирає самостійний "Apple TV Remote.app" (Python всередині) і пакує його в zip для друзів.
set -e
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q pyatv "srptools<2" pillow pyinstaller pyobjc-framework-MediaPlayer

rm -rf build dist "Apple TV Remote.spec" "Apple TV Remote.zip"

pyinstaller --noconfirm --clean --windowed \
  --name "Apple TV Remote" \
  --icon AppIcon.icns \
  --osx-bundle-identifier local.appletv.remote \
  --add-data "icon.png:." \
  --collect-all pyatv \
  --collect-all zeroconf \
  --hidden-import PIL._tkinter_finder \
  --hidden-import MediaPlayer \
  --hidden-import AppKit \
  --hidden-import Foundation \
  appletv_remote.py

APP="dist/Apple TV Remote.app"
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSLocalNetworkUsageDescription string Пошук і керування Apple TV у домашній мережі" "$PLIST" 2>/dev/null || true

# після зміни Info.plist підпис треба оновити (ad-hoc)
codesign --force --deep --sign - "$APP"

ditto -c -k --sequesterRsrc --keepParent "$APP" "Apple TV Remote.zip"

echo ""
echo "Готово:"
echo "  застосунок: $(pwd)/$APP"
echo "  для друга:  $(pwd)/Apple TV Remote.zip"
open dist
