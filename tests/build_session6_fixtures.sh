#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/tools/signing.sh"
source "$ROOT/tools/android-toolchain.sh"
kiosk_prepare_signing "$ROOT" development
kiosk_toolchain "$ROOT"
out="$(mktemp -d "$ROOT/tmp/session6-fixture.XXXXXXXX")"
app="$ROOT/app/src/main"
mkdir -p "$out/gen" "$out/classes" "$out/test-classes" "$out/test-dex" "$ROOT/tmp/session6-tests"

# Only the manifest identity changes; compile the current production Java sources.
# Fully qualify components so renaming cannot point at nonexistent fixture classes.
sed -e 's/package="com.example.webkiosk"/package="com.example.webkiosk.session6fixture"/' \
    -e 's/android:name="\./android:name="com.example.webkiosk./g' \
    -e 's/<application/<application android:testOnly="true"/' \
    -e 's/android:label="CU Denver Equity"/android:label="Kiosk Session 6 Fixture"/' \
    -e 's/android.intent.category.HOME/android.intent.category.DEFAULT/' \
    "$app/AndroidManifest.xml" > "$out/AndroidManifest.xml"
"$BUILD_TOOLS/aapt2" compile --dir "$app/res" -o "$out/resources.zip"
"$BUILD_TOOLS/aapt2" link -o "$out/app-unsigned.apk" -I "$ANDROID_JAR" \
    --manifest "$out/AndroidManifest.xml" --java "$out/gen" --custom-package com.example.webkiosk \
    --min-sdk-version 21 --target-sdk-version 35 --debug-mode \
    -R "$out/resources.zip" --auto-add-overlay
"$JDK/bin/javac" -source 11 -target 11 -cp "$ANDROID_JAR" -d "$out/classes" \
    "$out/gen/com/example/webkiosk/R.java" "$app/java/com/example/webkiosk/"*.java \
    "$app/java/com/example/kiosklauncher/"*.java
"$JDK/bin/java" -cp "$BUILD_TOOLS/lib/d8.jar" com.android.tools.r8.D8 --min-api 21 \
    --lib "$ANDROID_JAR" --output "$out/classes" \
    "$out/classes/com/example/webkiosk/"*.class "$out/classes/com/example/kiosklauncher/"*.class
"$JDK/bin/jar" uf "$out/app-unsigned.apk" -C "$out/classes" classes.dex
"$BUILD_TOOLS/zipalign" -f -p 4 "$out/app-unsigned.apk" "$out/app-aligned.apk"
kiosk_sign_apk development "$out/app-aligned.apk" "$out/session6-fixture.apk"

"$JDK/bin/javac" -source 11 -target 11 -cp "$ANDROID_JAR" -d "$out/test-classes" \
    "$ROOT/tests/android/InactivityDeviceTest.java"
"$BUILD_TOOLS/aapt2" link -o "$out/test-unsigned.apk" -I "$ANDROID_JAR" \
    --manifest "$ROOT/tests/android/Session6Manifest.xml" --min-sdk-version 26 --target-sdk-version 35
"$JDK/bin/java" -cp "$BUILD_TOOLS/lib/d8.jar" com.android.tools.r8.D8 --min-api 26 \
    --lib "$ANDROID_JAR" --output "$out/test-dex" \
    "$out/test-classes/com/example/webkiosk/session6tests/"*.class
"$JDK/bin/jar" uf "$out/test-unsigned.apk" -C "$out/test-dex" classes.dex
"$BUILD_TOOLS/zipalign" -f -p 4 "$out/test-unsigned.apk" "$out/test-aligned.apk"
kiosk_sign_apk development "$out/test-aligned.apk" "$out/session6-tests.apk"
printf '%s\n' "$out" > "$ROOT/tmp/session6-tests/fixture-path.txt"
echo "Session six fixture APKs: $out"
