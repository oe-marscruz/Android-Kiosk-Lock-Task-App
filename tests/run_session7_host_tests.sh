#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/tools/android-toolchain.sh"
kiosk_toolchain "$ROOT"
out="$ROOT/tmp/session7-tests/host"
mkdir -p "$out"
app="$ROOT/app/src/main/java/com/example/webkiosk"
"$JDK/bin/javac" -d "$out" \
    "$app/SessionCleanup.java" "$ROOT/tests/SessionCleanupTest.java" \
    "$app/InactivityDeadline.java" "$ROOT/tests/InactivityDeadlineTest.java" \
    "$app/NavigationPolicy.java" "$ROOT/tests/NavigationPolicyTest.java" \
    "$app/WifiInput.java" "$ROOT/tests/WifiInputTest.java"
for suite in SessionCleanupTest InactivityDeadlineTest NavigationPolicyTest WifiInputTest; do
    "$JDK/bin/java" -cp "$out" "com.example.webkiosk.$suite"
done
