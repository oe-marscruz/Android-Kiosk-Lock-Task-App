#!/usr/bin/env bash
# Shared by APK builds and the desktop packaging signature gate.
kiosk_toolchain() {
    local root="$1"
    JDK="${KIOSK_JDK:-${JAVA_HOME:-}}"
    if [ -z "$JDK" ]; then
        if [ -d "$root/jdk/jdk-17.0.20+8" ]; then
            JDK="$root/jdk/jdk-17.0.20+8"
        elif [ -d "$root/jdk/Contents/Home" ]; then
            JDK="$root/jdk/Contents/Home"
        elif [ -d 'C:/Program Files/Android/Android Studio/jbr' ]; then
            JDK='C:/Program Files/Android/Android Studio/jbr'
        elif [ -x /usr/libexec/java_home ]; then
            JDK="$(/usr/libexec/java_home)"
        fi
    fi
    SDK="${KIOSK_ANDROID_SDK:-${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}}"
    if [ -z "$SDK" ]; then
        if [ -d "$root/android-sdk" ]; then
            SDK="$root/android-sdk"
        elif [ -d "${LOCALAPPDATA:-}/Android/Sdk" ]; then
            SDK="$LOCALAPPDATA/Android/Sdk"
        elif [ -d "$HOME/Library/Android/sdk" ]; then
            SDK="$HOME/Library/Android/sdk"
        fi
    fi
    BUILD_TOOLS="${KIOSK_BUILD_TOOLS:-$SDK/build-tools/36.0.0}"
    if [ -z "${KIOSK_BUILD_TOOLS:-}" ] && [ ! -d "$BUILD_TOOLS" ] && [ -d "$SDK/build-tools/35.0.0" ]; then
        BUILD_TOOLS="$SDK/build-tools/35.0.0"
    fi
    PLATFORM="${KIOSK_PLATFORM:-$SDK/platforms/android-35}"
    if [ -z "${KIOSK_PLATFORM:-}" ] && [ ! -f "$PLATFORM/android.jar" ] && [ -f "$SDK/platforms/android-37.0/android.jar" ]; then
        PLATFORM="$SDK/platforms/android-37.0"
    fi
    ANDROID_JAR="$PLATFORM/android.jar"
    export JAVA_HOME="$JDK"
    [ -f "$JDK/bin/java" ] || [ -f "$JDK/bin/java.exe" ] || { echo 'ERROR: Set KIOSK_JDK to a JDK.' >&2; exit 1; }
    [ -f "$BUILD_TOOLS/lib/apksigner.jar" ] || { echo 'ERROR: Set KIOSK_BUILD_TOOLS to an installed Android SDK build-tools directory.' >&2; exit 1; }
}
