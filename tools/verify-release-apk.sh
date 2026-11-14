#!/usr/bin/env bash
set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/tools/signing.sh"
source "$ROOT/tools/android-toolchain.sh"
[ "$#" = 1 ] || kiosk_fail 'Usage: bash tools/verify-release-apk.sh /path/to/release.apk'
kiosk_toolchain "$ROOT"
kiosk_verify_release "$1"
