#!/bin/bash
# macOS entry point; the build is shared with build-apk.sh.
exec bash "$(dirname "$0")/build-apk.sh" "$@"
