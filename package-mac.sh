#!/usr/bin/env bash
set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$ROOT"
APP_NAME=CU-Denver-Equity-Kiosk-Manager
PYTHON="${KIOSK_PYTHON:-python3}"

[ "$(uname -s)" = Darwin ] || { echo 'ERROR: Run macOS packaging on a Mac.' >&2; exit 1; }
[ -n "${KIOSK_RELEASE_APK:-}" ] || { echo 'ERROR: Set KIOSK_RELEASE_APK to a protected-key release APK.' >&2; exit 1; }
[ -x platform-tools/adb ] || { echo 'ERROR: Run setup-tools-mac.sh to install macOS ADB.' >&2; exit 1; }

mkdir -p "$ROOT/tmp" "$ROOT/dist"
WORK="$(mktemp -d "$ROOT/tmp/package-mac.XXXXXXXX")"
STAGED_APK="$WORK/CU-Denver-Equity-Kiosk.apk"
cp "$KIOSK_RELEASE_APK" "$STAGED_APK"
bash tools/verify-release-apk.sh "$STAGED_APK"
source tools/android-toolchain.sh
kiosk_toolchain "$ROOT"
"$PYTHON" tools/check_apk_components.py "$STAGED_APK" --aapt2 "$BUILD_TOOLS/aapt2"
APK_SHA256="$(shasum -a 256 "$STAGED_APK" | awk '{print $1}')"

"$PYTHON" -m pip install -r requirements-macos-build.txt
"$PYTHON" -m PyInstaller --noconfirm --clean --onedir --windowed \
    --name "$APP_NAME" --distpath "$ROOT/dist" \
    --workpath "$WORK/pyinstaller" --specpath "$WORK" \
    --add-binary "$ROOT/platform-tools/adb:platform-tools" \
    --add-data "$STAGED_APK:." \
    --osx-bundle-identifier edu.ucdenver.equity-kiosk-manager \
    "$ROOT/kiosk-manager.py"

# Check the app outside the checkout before adding the optional sibling APK.
DMG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kiosk-dmg.XXXXXXXX")"
trap 'rm -rf -- "$DMG_DIR"' EXIT
DMG_DIR="$(cd "$DMG_DIR" && pwd -P)"
case "$DMG_DIR/" in "$ROOT/"*) echo 'ERROR: Relocation directory must be outside the checkout.' >&2; exit 1;; esac
ditto "$ROOT/dist/$APP_NAME.app" "$DMG_DIR/$APP_NAME.app"
(
    cd "$DMG_DIR"
    unset KIOSK_RELEASE_APK PYTHONPATH PYTHONHOME
    "$DMG_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME" --check-bundle \
        --expected-apk-sha256 "$APK_SHA256" --report "$WORK/relocated-resources.json"
)
cat "$WORK/relocated-resources.json"

{
    sw_vers
    uname -m
    "$JDK/bin/java" -version 2>&1
    cat "$BUILD_TOOLS/source.properties"
    cat "$PLATFORM/source.properties"
    "$PYTHON" -m PyInstaller --version
} > "$WORK/toolchain.txt"
mkdir -p "$ROOT/dist/macos-evidence"
cp "$WORK/relocated-resources.json" "$WORK/toolchain.txt" "$ROOT/dist/macos-evidence/"

mkdir -p "$DMG_DIR/Kiosk-APK"
cp "$STAGED_APK" "$DMG_DIR/Kiosk-APK/"
cat > "$DMG_DIR/README.txt" << 'EOF'
CU Denver Equity - Kiosk Manager

Drag the app to Applications and launch it there.
The app includes ADB and its reviewed release APK.
Kiosk-APK contains the same APK for manual installation.
Connect the designated test tablet and accept USB debugging before setup.
Device ownership, enrollment and signing migration require separate acceptance.
EOF
hdiutil create -volname 'CU Denver Equity Kiosk Manager' \
    -srcfolder "$DMG_DIR" -ov -format UDZO "$WORK/$APP_NAME.dmg"
cp "$WORK/$APP_NAME.dmg" "$ROOT/$APP_NAME.dmg"
echo "DMG ready: $ROOT/$APP_NAME.dmg"
echo "Relocated resource and toolchain evidence: $ROOT/dist/macos-evidence"
