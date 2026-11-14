#!/usr/bin/env bash
# SDK-backed signing contract tests. Creates disposable keys, never a production identity.
set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/tools/signing.sh"
source "$ROOT/tools/android-toolchain.sh"
[ "$#" = 1 ] || kiosk_fail 'Pass an external writable fixture parent directory.'
fixture_parent="$(cd "$1" && pwd -P)"
kiosk_toolchain "$ROOT"
FIXTURE="$(mktemp -d "$fixture_parent/kiosk-signing-tests.XXXXXXXX")"
mkdir -p "$ROOT/tmp/session4-tests"
LOG="$ROOT/tmp/session4-tests/results.txt"
: > "$LOG"
passed=0
expect_fail() {
    local label="$1"; shift
    if ("$@") > "$FIXTURE/failure.log" 2>&1; then
        echo "FAIL: $label unexpectedly succeeded" | tee -a "$LOG"; exit 1
    fi
    passed=$((passed + 1)); echo "PASS: $label" | tee -a "$LOG"
}
pass() { passed=$((passed + 1)); echo "PASS: $1" | tee -a "$LOG"; }

unset KIOSK_VERSION_CODE KIOSK_VERSION_NAME KIOSK_PREVIOUS_VERSION_CODE KIOSK_RELEASE_CERT_SHA256
unset KIOSK_RELEASE_KEYSTORE KIOSK_RELEASE_KEY_ALIAS KIOSK_RELEASE_STORE_PASS_FILE KIOSK_RELEASE_KEY_PASS_FILE
for builder in build-apk.sh build-apk-mac.sh; do
    expect_fail "$builder rejects missing release configuration" bash "$ROOT/$builder" release
done
umask 077
printf '%s\n' 'session4-disposable-fixture-only' > "$FIXTURE/store.pass"
export KIOSK_RELEASE_KEYSTORE="$FIXTURE/release.p12"
export KIOSK_RELEASE_KEY_ALIAS=kiosk-release-fixture
export KIOSK_RELEASE_STORE_PASS_FILE="$FIXTURE/store.pass"
export KIOSK_RELEASE_KEY_PASS_FILE="$FIXTURE/store.pass"
export KIOSK_VERSION_CODE=100 KIOSK_VERSION_NAME=1.0.0-fixture KIOSK_PREVIOUS_VERSION_CODE=0
"$JDK/bin/keytool" -genkeypair -keystore "$KIOSK_RELEASE_KEYSTORE" -storetype PKCS12 \
    -alias "$KIOSK_RELEASE_KEY_ALIAS" -keyalg RSA -keysize 3072 -validity 2 \
    -storepass:file "$FIXTURE/store.pass" -keypass:file "$FIXTURE/store.pass" \
    -dname 'CN=Disposable Session 4 Fixture, O=Tests Only, C=US'
"$JDK/bin/keytool" -exportcert -keystore "$KIOSK_RELEASE_KEYSTORE" \
    -alias "$KIOSK_RELEASE_KEY_ALIAS" -storepass:file "$FIXTURE/store.pass" -file "$FIXTURE/cert.der"
export KIOSK_RELEASE_CERT_SHA256="$(sha256sum "$FIXTURE/cert.der" | cut -d ' ' -f 1)"
PIN="$KIOSK_RELEASE_CERT_SHA256"
expect_fail 'missing keystore' env KIOSK_RELEASE_KEYSTORE= bash "$ROOT/build-apk.sh" release
expect_fail 'missing password file' env KIOSK_RELEASE_STORE_PASS_FILE= bash "$ROOT/build-apk-mac.sh" release
expect_fail 'missing key password file' env KIOSK_RELEASE_KEY_PASS_FILE= bash "$ROOT/build-apk.sh" release
expect_fail 'exposed certificate pin' env KIOSK_RELEASE_CERT_SHA256=ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102 bash "$ROOT/build-apk.sh" release
expect_fail 'reused version code' env KIOSK_PREVIOUS_VERSION_CODE=100 bash "$ROOT/build-apk.sh" release
expect_fail 'decreasing version code' env KIOSK_PREVIOUS_VERSION_CODE=101 bash "$ROOT/build-apk.sh" release
expect_fail 'missing previous version code' env KIOSK_PREVIOUS_VERSION_CODE= bash "$ROOT/build-apk.sh" release
expect_fail 'invalid version name' env KIOSK_VERSION_NAME="bad' metadata" bash "$ROOT/build-apk.sh" release
expect_fail 'checkout password file' env KIOSK_RELEASE_STORE_PASS_FILE="$ROOT/README.md" bash "$ROOT/build-apk.sh" release

bash "$ROOT/build-apk.sh" development > "$FIXTURE/development-build.log" 2>&1
DEV="$ROOT/build/development/CU-Denver-Equity-Kiosk-development-v100.apk"
"$JDK/bin/java" -jar "$BUILD_TOOLS/lib/apksigner.jar" verify --print-certs "$DEV" > "$FIXTURE/development-certificate.txt"
DEV_PIN="$(sed -n 's/^Signer #1 certificate SHA-256 digest: //p' "$FIXTURE/development-certificate.txt")"
[ "$DEV_PIN" != "$PIN" ] && [ "$DEV_PIN" != ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102 ]
pass 'development build has a separate identity'
expect_fail 'development APK with its own pinned certificate' env KIOSK_RELEASE_CERT_SHA256="$DEV_PIN" bash "$ROOT/tools/verify-release-apk.sh" "$DEV"

bash "$ROOT/build-apk.sh" release > "$FIXTURE/release-build.log" 2>&1
RELEASE="$ROOT/build/release/CU-Denver-Equity-Kiosk-release-v100.apk"
bash "$ROOT/tools/verify-release-apk.sh" "$RELEASE" | tee -a "$LOG"
pass 'Windows entry point produces a verified protected-file-signed release fixture'
expect_fail 'wrong certificate pin' env KIOSK_RELEASE_CERT_SHA256="$DEV_PIN" bash "$ROOT/tools/verify-release-apk.sh" "$RELEASE"
expect_fail 'wrong version metadata' env KIOSK_VERSION_NAME=1.0.1-fixture bash "$ROOT/tools/verify-release-apk.sh" "$RELEASE"
expect_fail 'version names compare literally (dots cannot match other characters)' env KIOSK_VERSION_NAME=1.0.0.fixture bash "$ROOT/tools/verify-release-apk.sh" "$RELEASE"
expect_fail 'legacy exposed-key APK' bash "$ROOT/tools/verify-release-apk.sh" "$ROOT/build/CU-Denver-Equity-Kiosk.apk"

cp "$RELEASE" "$FIXTURE/tampered.apk"
printf '%s\n' 'tampered' > "$FIXTURE/tamper.txt"
"$JDK/bin/jar" uf "$FIXTURE/tampered.apk" -C "$FIXTURE" tamper.txt
expect_fail 'tampered signed APK' bash "$ROOT/tools/verify-release-apk.sh" "$FIXTURE/tampered.apk"
unsigned="$(ls -td "$ROOT/tmp/apk-release."* | head -1)/aligned.apk"
expect_fail 'unsigned APK' bash "$ROOT/tools/verify-release-apk.sh" "$unsigned"
printf '%s\n' 'incorrect-fixture-password' > "$FIXTURE/wrong.pass"
expect_fail 'wrong password at actual signer' env KIOSK_RELEASE_STORE_PASS_FILE="$FIXTURE/wrong.pass" \
    bash -c 'set -e; source "$1/tools/signing.sh"; source "$1/tools/android-toolchain.sh"; kiosk_prepare_signing "$1" release; kiosk_toolchain "$1"; kiosk_sign_apk release "$2" "$3"' \
    _ "$ROOT" "$unsigned" "$FIXTURE/wrong-password.apk"

export KIOSK_VERSION_CODE=101 KIOSK_VERSION_NAME=1.0.1-fixture KIOSK_PREVIOUS_VERSION_CODE=100
cp "$FIXTURE/store.pass" "$FIXTURE/key.pass"
export KIOSK_RELEASE_KEY_PASS_FILE="$FIXTURE/key.pass"
bash "$ROOT/build-apk-mac.sh" release > "$FIXTURE/mac-entry-build.log" 2>&1
bash "$ROOT/tools/verify-release-apk.sh" "$ROOT/build/release/CU-Denver-Equity-Kiosk-release-v101.apk" | tee -a "$LOG"
pass 'macOS entry point uses separate password files and increasing version metadata (Windows host)'

# A packaging failure must precede Python/tool installation or desktop bundling.
for packager in package-win.sh package-mac.sh; do
    expect_fail "$packager rejects development APK" env KIOSK_RELEASE_APK="$DEV" bash "$ROOT/$packager"
    expect_fail "$packager rejects missing APK input" env KIOSK_RELEASE_APK= bash "$ROOT/$packager"
done
if grep -Rq -F 'session4-disposable-fixture-only' "$LOG" "$FIXTURE/"*.log; then
    kiosk_fail 'Fixture password leaked to captured logs.'
fi
pass 'captured build/test logs contain no fixture password'
echo "$passed signing checks passed. Fixture artifacts are NOT production releases." | tee -a "$LOG"
echo "External disposable fixture directory: $FIXTURE"
