#!/usr/bin/env bash
source "$ROOT/tools/signing.sh"
source "$ROOT/tools/android-toolchain.sh"

kiosk_build_apk() {
    [ "$#" -le 1 ] || kiosk_fail 'Usage: build-apk[-mac].sh [development|release]'
    local mode="${1:-development}" work app output
    kiosk_prepare_signing "$ROOT" "$mode"
    kiosk_toolchain "$ROOT"
    app="$ROOT/app/src/main"
    mkdir -p "$ROOT/tmp" "$ROOT/build/$mode"
    work="$(mktemp -d "$ROOT/tmp/apk-$mode.XXXXXXXX")"
    mkdir -p "$work/gen" "$work/obj"
    output="$ROOT/build/$mode/CU-Denver-Equity-Kiosk-$mode-v$VERSION_CODE.apk"
    local link_flags=()
    [ "$mode" != development ] || link_flags+=(--debug-mode)

    "$BUILD_TOOLS/aapt2" compile --dir "$app/res" -o "$work/resources.zip"
    "$BUILD_TOOLS/aapt2" link -o "$work/unsigned.apk" -I "$ANDROID_JAR" \
        --manifest "$app/AndroidManifest.xml" --java "$work/gen" \
        --min-sdk-version 21 --target-sdk-version 35 \
        --version-code "$VERSION_CODE" --version-name "$VERSION_NAME" \
        ${link_flags[@]+"${link_flags[@]}"} -R "$work/resources.zip" --auto-add-overlay

    "$JDK/bin/javac" -source 11 -target 11 -d "$work/obj" -cp "$ANDROID_JAR" \
        "$work/gen/com/example/webkiosk/R.java" \
        "$app/java/com/example/webkiosk/MainActivity.java" \
        "$app/java/com/example/webkiosk/WifiSettingsActivity.java" \
        "$app/java/com/example/webkiosk/WifiInput.java" \
        "$app/java/com/example/webkiosk/NavigationPolicy.java" \
        "$app/java/com/example/webkiosk/InactivityDeadline.java" \
        "$app/java/com/example/webkiosk/SessionCleanup.java" \
        "$app/java/com/example/webkiosk/KioskDeviceAdminReceiver.java" \
        "$app/java/com/example/kiosklauncher/LauncherActivity.java"
    "$JDK/bin/java" -cp "$BUILD_TOOLS/lib/d8.jar" com.android.tools.r8.D8 \
        --min-api 21 --lib "$ANDROID_JAR" --output "$work/obj" \
        "$work/obj/com/example/webkiosk/"*.class \
        "$work/obj/com/example/kiosklauncher/"*.class
    "$JDK/bin/jar" uf "$work/unsigned.apk" -C "$work/obj" classes.dex
    "$BUILD_TOOLS/zipalign" -f -p 4 "$work/unsigned.apk" "$work/aligned.apk"
    kiosk_sign_apk "$mode" "$work/aligned.apk" "$work/signed.apk"
    cp "$work/signed.apk" "$output"
    echo "APK ready: $output"
}
