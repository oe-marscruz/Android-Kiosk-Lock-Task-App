#!/bin/bash
# Windows: Build and package the Kiosk Manager into a self-contained .exe
# Run this in Git Bash after running setup-tools.bat
set -e
set +x
cd "$(dirname "$0")"

APP_NAME="CU-Denver-Equity-Kiosk-Manager"

# Stage the exact verified bytes; never rebuild or pick a repository debug APK.
[ -n "${KIOSK_RELEASE_APK:-}" ] || { echo 'ERROR: Set KIOSK_RELEASE_APK to a protected-key release APK.' >&2; exit 1; }
mkdir -p dist/build
cp "$KIOSK_RELEASE_APK" dist/build/CU-Denver-Equity-Kiosk.apk
bash tools/verify-release-apk.sh dist/build/CU-Denver-Equity-Kiosk.apk

echo "============================================"
echo " Building $APP_NAME.exe for Windows"
echo "============================================"

# Step 0: Check prerequisites
if [ ! -f "platform-tools/adb.exe" ]; then
    echo "ERROR: platform-tools not found. Run setup-tools.bat first."
    exit 1
fi

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python not found."
    exit 1
fi
PY="python"
command -v python >/dev/null 2>&1 || PY="python3"

# Step 1: APK already staged and verified above.

# Step 2: Install PyInstaller if needed
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    echo "[2/4] Installing PyInstaller..."
    "$PY" -m pip install pyinstaller
else
    echo "[2/4] PyInstaller already installed."
fi

# Step 3: Build the .exe
echo "[3/4] Building Windows executable..."
rm -rf dist/"$APP_NAME" build/"$APP_NAME" "$APP_NAME".spec 2>/dev/null || true

"$PY" -m PyInstaller --onefile --windowed --name "$APP_NAME" \
    --add-data "platform-tools;platform-tools" \
    --add-data "dist/build/CU-Denver-Equity-Kiosk.apk;." \
    kiosk-manager.py

# Step 4: Cleanup
echo "[4/4] Cleaning up..."
rm -rf build/"$APP_NAME" "$APP_NAME".spec

echo ""
echo "============================================"
echo " SUCCESS"
echo "============================================"
echo "EXE created: dist/$APP_NAME.exe"
ls -lh "dist/$APP_NAME.exe"
echo ""
echo "Distribute this .exe to end users."
echo "They just need to:"
echo "  1. Double-click the .exe"
echo "  2. Connect the tablet via USB"
echo "  3. Click Setup Kiosk"
