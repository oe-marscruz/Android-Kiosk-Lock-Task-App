#!/usr/bin/env bash
set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
source "$ROOT/tools/build-apk-common.sh"
kiosk_build_apk "$@"
