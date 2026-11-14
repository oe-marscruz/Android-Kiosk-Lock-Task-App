#!/usr/bin/env bash
# Host orchestration fixtures; these do not create a real macOS application.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
mkdir -p "$ROOT/tmp"
FIXTURE="$(mktemp -d "$ROOT/tmp/session9-packaging.XXXXXXXX")"
CASE_ROOT="$FIXTURE/checkout with spaces"
mkdir -p "$CASE_ROOT/tools" "$CASE_ROOT/platform-tools" "$CASE_ROOT/fake-bin" \
    "$CASE_ROOT/fake-jdk/bin" "$CASE_ROOT/build-tools" "$CASE_ROOT/platform"
cp "$ROOT/package-mac.sh" "$CASE_ROOT/package-mac.sh"
printf 'synthetic APK\n' > "$CASE_ROOT/input with spaces.apk"
printf 'synthetic tool version\n' > "$CASE_ROOT/build-tools/source.properties"
cp "$CASE_ROOT/build-tools/source.properties" "$CASE_ROOT/platform/source.properties"
cat > "$CASE_ROOT/tools/verify-release-apk.sh" << 'EOF'
set -eu
echo signature >> "$CASE_ROOT/calls"
[ "${FAIL_STAGE:-}" != signature ]
EOF
cat > "$CASE_ROOT/tools/android-toolchain.sh" << 'EOF'
kiosk_toolchain() {
    JDK="$1/fake-jdk"
    BUILD_TOOLS="$1/build-tools"
    PLATFORM="$1/platform"
}
EOF
cat > "$CASE_ROOT/fake-bin/python" << 'EOF'
#!/usr/bin/env bash
set -eu
if [ "$1" = tools/check_apk_components.py ]; then
    echo components >> "$CASE_ROOT/calls"
    cmp "$2" "$KIOSK_RELEASE_APK"
    [ "${FAIL_STAGE:-}" != components ]
elif [ "$2" = pip ]; then
    echo pip >> "$CASE_ROOT/calls"
elif [ "${3:-}" = --version ]; then
    echo fixture-pyinstaller
else
    echo pyinstaller >> "$CASE_ROOT/calls"
    while [ "$#" -gt 0 ]; do
        case "$1" in --name) name="$2"; shift;; --distpath) dest="$2"; shift;; esac
        shift
    done
    mkdir -p "$dest/$name.app/Contents/MacOS"
    cat > "$dest/$name.app/Contents/MacOS/$name" << 'APP'
#!/usr/bin/env bash
set -eu
echo relocated >> "$CASE_ROOT/calls"
[ "$PWD" != "$CASE_ROOT" ]
[ -z "${KIOSK_RELEASE_APK:-}" ]
[ ! -d Kiosk-APK ]
[ "${FAIL_STAGE:-}" != relocated ]
[ "$1" = --check-bundle ] && [ "$2" = --expected-apk-sha256 ] && [ "$4" = --report ]
printf '{"status":"PASS","fixture":true}\n' > "$5"
APP
    chmod +x "$dest/$name.app/Contents/MacOS/$name"
fi
EOF
cat > "$CASE_ROOT/fake-bin/uname" << 'EOF'
#!/usr/bin/env bash
if [ "$1" = -s ]; then echo Darwin; else echo fixture-architecture; fi
EOF
cat > "$CASE_ROOT/fake-bin/ditto" << 'EOF'
#!/usr/bin/env bash
cp -R "$1" "$2"
EOF
cat > "$CASE_ROOT/fake-bin/hdiutil" << 'EOF'
#!/usr/bin/env bash
echo dmg >> "$CASE_ROOT/calls"
printf 'synthetic DMG\n' > "${!#}"
EOF
cat > "$CASE_ROOT/fake-bin/shasum" << 'EOF'
#!/usr/bin/env bash
printf '%064d  %s\n' 0 "$3"
EOF
for file in platform-tools/adb fake-jdk/bin/java fake-bin/sw_vers; do
    printf '#!/usr/bin/env bash\necho fixture-version\n' > "$CASE_ROOT/$file"
done
chmod +x "$CASE_ROOT/fake-bin/"* "$CASE_ROOT/platform-tools/adb" "$CASE_ROOT/fake-jdk/bin/java"
export CASE_ROOT
export PATH="$CASE_ROOT/fake-bin:$PATH"
export KIOSK_PYTHON="$CASE_ROOT/fake-bin/python"
export KIOSK_RELEASE_APK="$CASE_ROOT/input with spaces.apk"
for stage in signature components relocated; do
    : > "$CASE_ROOT/calls"
    if FAIL_STAGE="$stage" bash "$CASE_ROOT/package-mac.sh" > "$FIXTURE/$stage.log" 2>&1; then
        echo "FAIL: $stage was accepted"; exit 1
    fi
    grep -qx "$stage" "$CASE_ROOT/calls" || { echo "FAIL: $stage was not exercised"; exit 1; }
    if grep -qx dmg "$CASE_ROOT/calls"; then echo "FAIL: DMG created after $stage failure"; exit 1; fi
    if [ "$stage" != relocated ] && grep -qx pyinstaller "$CASE_ROOT/calls"; then
        echo "FAIL: bundling started after $stage failure"; exit 1
    fi
    echo "PASS: $stage failure stops packaging"
done
: > "$CASE_ROOT/calls"
bash "$CASE_ROOT/package-mac.sh" > "$FIXTURE/success.log" 2>&1
printf 'signature\ncomponents\npip\npyinstaller\nrelocated\ndmg\n' > "$FIXTURE/expected-calls"
cmp "$FIXTURE/expected-calls" "$CASE_ROOT/calls"
test -s "$CASE_ROOT/dist/macos-evidence/relocated-resources.json"
test -s "$CASE_ROOT/CU-Denver-Equity-Kiosk-Manager.dmg"
echo 'PASS: shared packaging path checks relocated app before DMG creation (synthetic tools)'
echo "Fixture logs: $FIXTURE"
