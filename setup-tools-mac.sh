#!/bin/bash
# macOS: Download ADB, JDK, and Android SDK for kiosk toolchain
set -e
cd "$(dirname "$0")"
echo "============================================"
echo " Kiosk Toolchain Setup — macOS"
echo "============================================"

PLATFORM_TOOLS_URL="https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
CMDLINE_TOOLS_URL="https://dl.google.com/android/repository/commandlinetools-mac-13114758_latest.zip"
JDK_URL="https://api.adoptium.net/v3/binary/latest/17/ga/mac/aarch64/jdk/hotspot/normal/eclipse"

# --- ADB Platform Tools ---
if [ ! -f "platform-tools/adb" ]; then
    echo "[1/4] Downloading Android Platform Tools for macOS..."
    curl -L -o /tmp/platform-tools.zip "$PLATFORM_TOOLS_URL"
    unzip -o /tmp/platform-tools.zip -d .
    rm /tmp/platform-tools.zip
    echo "    Platform Tools installed."
else
    echo "[1/4] Platform Tools already installed."
fi

# --- JDK 17 ---
if [ ! -d "jdk" ] || [ -z "$(ls -A jdk 2>/dev/null)" ]; then
    echo "[2/4] Downloading JDK 17 for macOS..."
    mkdir -p jdk
    curl -L -o /tmp/jdk.tar.gz "$JDK_URL"
    tar -xzf /tmp/jdk.tar.gz -C jdk --strip-components=1
    rm /tmp/jdk.tar.gz
    echo "    JDK 17 installed."
else
    echo "[2/4] JDK 17 already installed."
fi

# --- Android SDK Command-Line Tools ---
if [ ! -f "android-sdk/cmdline-tools/latest/bin/sdkmanager" ]; then
    echo "[3/4] Downloading Android SDK Command-Line Tools..."
    curl -L -o /tmp/cmdline-tools.zip "$CMDLINE_TOOLS_URL"
    mkdir -p android-sdk/cmdline-tools
    unzip -o /tmp/cmdline-tools.zip -d android-sdk/cmdline-tools
    mv android-sdk/cmdline-tools/cmdline-tools android-sdk/cmdline-tools/latest 2>/dev/null || true
    rm /tmp/cmdline-tools.zip
    echo "    SDK Command-Line Tools installed."
else
    echo "[3/4] SDK Command-Line Tools already installed."
fi

# --- Install SDK packages ---
echo "[4/4] Installing Android SDK packages (platform + build-tools)..."
export ANDROID_SDK_ROOT="$(pwd)/android-sdk"
JDK_HOME=$(ls -d jdk/*/Contents/Home 2>/dev/null || ls -d jdk/Contents/Home 2>/dev/null || echo "jdk")
export JAVA_HOME="$(pwd)/$JDK_HOME"

if [ ! -f "$ANDROID_SDK_ROOT/platforms/android-35/android.jar" ] ||
   [ ! -f "$ANDROID_SDK_ROOT/build-tools/36.0.0/aapt2" ]; then
    echo y | "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_SDK_ROOT" --licenses 2>/dev/null || true
    "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_SDK_ROOT" "platforms;android-35" "build-tools;35.0.0" "build-tools;36.0.0"
fi

if [ ! -f "$ANDROID_SDK_ROOT/platforms/android-35/android.jar" ]; then
    echo "    ERROR: Android platform 35 is missing." >&2
    exit 1
fi
if [ ! -f "$ANDROID_SDK_ROOT/build-tools/36.0.0/aapt2" ]; then
    echo "    ERROR: Android Build Tools 36.0.0 is missing." >&2
    exit 1
fi
echo "    SDK packages installed successfully."

echo ""
echo "============================================"
echo " SETUP COMPLETE"
echo "============================================"
echo ""
echo "Next: python3 kiosk-manager.py"
echo ""
