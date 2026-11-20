#!/bin/bash
# Build the CU Denver Equity Kiosk APK with Gradle (Linux, macOS, Windows Git Bash).
#
# Release: set KIOSK_KEYSTORE, KIOSK_KEYSTORE_PASS and KIOSK_KEYSTORE_ALIAS
#          (optionally KIOSK_CERT_SHA256 to pin the signer certificate).
# Debug:   none of them set; signed with the local Android debug key.
# A partial set is an error. NEVER commit a keystore or its password.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="CU-Denver-Equity-Kiosk"
OUT_DIR="$SCRIPT_DIR/build"

# Windows JVMs need C:/... paths; cygpath exists only under Git Bash/MSYS/Cygwin.
native_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi
}

# Toolchains downloaded by setup-tools.bat / setup-tools-mac.sh, if not already configured.
if [ -z "${JAVA_HOME:-}" ]; then
  for candidate in "$SCRIPT_DIR"/jdk/Contents/Home "$SCRIPT_DIR"/jdk/jdk-*/Contents/Home "$SCRIPT_DIR"/jdk/jdk-*; do
    if [ -x "$candidate/bin/java" ] || [ -x "$candidate/bin/java.exe" ]; then
      export JAVA_HOME="$(native_path "$candidate")"
      break
    fi
  done
fi
if [ -z "${ANDROID_HOME:-}${ANDROID_SDK_ROOT:-}" ] && [ ! -f local.properties ] && [ -d "$SCRIPT_DIR/android-sdk" ]; then
  export ANDROID_HOME="$(native_path "$SCRIPT_DIR/android-sdk")"
fi

set_count=0
for var in KIOSK_KEYSTORE KIOSK_KEYSTORE_PASS KIOSK_KEYSTORE_ALIAS; do
  [ -n "${!var:-}" ] && set_count=$((set_count + 1))
done
case "$set_count" in
  3) VARIANT=release TASK=assembleRelease
     export KIOSK_KEYSTORE="$(native_path "$KIOSK_KEYSTORE")" ;;
  0) VARIANT=debug TASK=assembleDebug ;;
  *) echo "ERROR: set all of KIOSK_KEYSTORE, KIOSK_KEYSTORE_PASS, KIOSK_KEYSTORE_ALIAS, or none." >&2
     exit 1 ;;
esac

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$APP_NAME.apk" "$OUT_DIR/apk-info.txt"

echo "=== Building $VARIANT APK ==="
bash ./gradlew --no-daemon "$TASK"

GRADLE_OUT="$SCRIPT_DIR/app/build/outputs/apk/$VARIANT"
cp "$GRADLE_OUT/app-$VARIANT.apk" "$OUT_DIR/$APP_NAME.apk"
cp "$GRADLE_OUT/apk-info.txt" "$OUT_DIR/apk-info.txt"

echo ""
echo "=== SUCCESS ($VARIANT) ==="
if [ "$VARIANT" = debug ]; then
  echo "DEBUG-SIGNED APK: for development and USB testing only, never for fleet release."
fi
echo "APK ready: build/$APP_NAME.apk"
cat "$OUT_DIR/apk-info.txt"
