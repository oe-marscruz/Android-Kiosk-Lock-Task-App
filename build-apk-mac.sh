#!/bin/bash
# macOS build script for CU Denver Equity Kiosk APK
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find JDK (may be in different locations)
if [ -d "$SCRIPT_DIR/jdk/Contents/Home" ]; then
    JDK="$SCRIPT_DIR/jdk/Contents/Home"
elif [ -d "$SCRIPT_DIR/jdk" ]; then
    JDK=$(ls -d "$SCRIPT_DIR/jdk/"jdk-*/Contents/Home 2>/dev/null | head -1)
    [ -z "$JDK" ] && JDK="$SCRIPT_DIR/jdk"
else
    JDK="$JAVA_HOME"
fi

SDK="$SCRIPT_DIR/android-sdk"
BUILD_TOOLS="$SDK/build-tools/35.0.0"
PLATFORM="$SDK/platforms/android-35"
ANDROID_JAR="$PLATFORM/android.jar"

OUT_DIR="$SCRIPT_DIR/build"
GEN_DIR="$OUT_DIR/gen"
OBJ_DIR="$OUT_DIR/obj"

APP_DIR="$SCRIPT_DIR/app/src/main"
MANIFEST="$APP_DIR/AndroidManifest.xml"
JAVA_SRC="$APP_DIR/java/com/example/webkiosk/MainActivity.java"
WIFI_SRC="$APP_DIR/java/com/example/webkiosk/WifiSettingsActivity.java"
WIFI_INPUT_SRC="$APP_DIR/java/com/example/webkiosk/WifiInput.java"
LAUNCHER_SRC="$APP_DIR/java/com/example/kiosklauncher/LauncherActivity.java"
RES_DIR="$APP_DIR/res"

APP_NAME="CU-Denver-Equity-Kiosk"
KEYSTORE="$SCRIPT_DIR/debug.keystore"

export JAVA_HOME="$JDK"

echo "=== Cleaning ==="
rm -rf "$OUT_DIR"
mkdir -p "$GEN_DIR" "$OBJ_DIR"

echo "=== Compiling resources ==="
"$BUILD_TOOLS/aapt2" compile \
  --dir "$RES_DIR" \
  -o "$OBJ_DIR/resources.zip"

echo "=== Linking resources ==="
"$BUILD_TOOLS/aapt2" link \
  -o "$OUT_DIR/$APP_NAME-unaligned.apk" \
  -I "$ANDROID_JAR" \
  --manifest "$MANIFEST" \
  --java "$GEN_DIR" \
  --min-sdk-version 21 \
  --target-sdk-version 35 \
  -R "$OBJ_DIR/resources.zip" \
  --auto-add-overlay

echo "=== Compiling Java ==="
"$JDK/bin/javac" \
  -d "$OBJ_DIR" \
  -cp "$ANDROID_JAR" \
  "$GEN_DIR/com/example/webkiosk/R.java" \
  "$JAVA_SRC" \
  "$WIFI_SRC" \
  "$WIFI_INPUT_SRC" \
  "$LAUNCHER_SRC"

echo "=== Converting to DEX ==="
"$JDK/bin/java" -cp "$BUILD_TOOLS/lib/d8.jar" com.android.tools.r8.D8 \
  --lib "$ANDROID_JAR" \
  --output "$OBJ_DIR" \
  "$OBJ_DIR/com/example/webkiosk/"*.class \
  "$OBJ_DIR/com/example/kiosklauncher/"*.class

echo "=== Adding DEX to APK ==="
cd "$OBJ_DIR"
"$JDK/bin/jar" uf "$OUT_DIR/$APP_NAME-unaligned.apk" classes.dex
cd "$SCRIPT_DIR"

echo "=== Aligning APK ==="
"$BUILD_TOOLS/zipalign" -f -p 4 \
  "$OUT_DIR/$APP_NAME-unaligned.apk" \
  "$OUT_DIR/$APP_NAME-aligned.apk"

echo "=== Signing APK ==="
if [ ! -f "$KEYSTORE" ]; then
  echo "=== Generating debug keystore ==="
  "$JDK/bin/keytool" -genkey -v \
    -keystore "$KEYSTORE" \
    -alias androiddebugkey \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass android \
    -keypass android \
    -dname "CN=Android Debug, O=Android, C=US"
fi

"$JDK/bin/java" -jar "$BUILD_TOOLS/lib/apksigner.jar" sign \
  --ks "$KEYSTORE" \
  --ks-pass pass:android \
  --ks-key-alias androiddebugkey \
  --out "$OUT_DIR/$APP_NAME.apk" \
  "$OUT_DIR/$APP_NAME-aligned.apk"

echo ""
echo "=== SUCCESS ==="
echo "APK ready: build/$APP_NAME.apk"
ls -lh "$OUT_DIR/$APP_NAME.apk"
