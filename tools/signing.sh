#!/usr/bin/env bash
# Do not enable shell tracing: callers handle password-file locations.
set +x

kiosk_fail() { echo "ERROR: $*" >&2; exit 1; }

kiosk_native_path() {
    if command -v cygpath >/dev/null 2>&1; then cygpath -am "$1"; else printf '%s\n' "$1"; fi
}

kiosk_certificate_pin() {
    CERT_PIN="$(printf '%s' "${KIOSK_RELEASE_CERT_SHA256:-}" | tr -d ':' | tr '[:upper:]' '[:lower:]')"
    [[ "$CERT_PIN" =~ ^[0-9a-f]{64}$ ]] || kiosk_fail 'Set KIOSK_RELEASE_CERT_SHA256 to the independently approved SHA-256 certificate fingerprint.'
    [ "$CERT_PIN" != ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102 ] || kiosk_fail 'The exposed signing certificate is forbidden for release.'
}

kiosk_version() {
    local code="$1"
    [[ "$code" =~ ^[1-9][0-9]{0,9}$ ]] && [ "$code" -le 2100000000 ] || kiosk_fail 'Version code must be an integer from 1 to 2100000000.'
}

kiosk_release_metadata() {
    VERSION_CODE="${KIOSK_VERSION_CODE:-}"
    VERSION_NAME="${KIOSK_VERSION_NAME:-}"
    kiosk_version "$VERSION_CODE"
    [[ "$VERSION_NAME" =~ ^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$ ]] || kiosk_fail 'Set KIOSK_VERSION_NAME (1-64 letters, digits, dot, underscore, plus or hyphen).'
    local previous="${KIOSK_PREVIOUS_VERSION_CODE:-}"
    if [ "$previous" != 0 ]; then kiosk_version "$previous"; fi
    [ "$VERSION_CODE" -gt "$previous" ] || kiosk_fail 'Release version code must exceed KIOSK_PREVIOUS_VERSION_CODE from the release ledger.'
    kiosk_certificate_pin
}

kiosk_external_file() {
    local path="$1" root="$2" resolved
    [ -n "$path" ] && [ -s "$path" ] && [ ! -L "$path" ] || kiosk_fail 'Release key/password files must be nonempty regular external files (no symlinks).'
    [ -f "$path" ] || kiosk_fail 'Release credential input is not a regular file.'
    resolved="$(cd -P "$(dirname "$path")" && pwd)/$(basename "$path")"
    # Windows paths are case-insensitive; cd -P also resolves linked parent directories.
    case "$(printf '%s/' "$resolved" | tr '[:upper:]' '[:lower:]')" in
        "$(printf '%s/' "$root" | tr '[:upper:]' '[:lower:]')"*) kiosk_fail 'Keep release key/password files outside the checkout.' ;;
    esac
}

kiosk_prepare_signing() {
    local root="$1" mode="$2"
    case "$mode" in
        development)
            VERSION_CODE="${KIOSK_VERSION_CODE:-1}"
            VERSION_NAME="${KIOSK_VERSION_NAME:-0.0.0-dev}"
            kiosk_version "$VERSION_CODE"
            KEYSTORE="$root/.local-signing/development.p12"
            KEY_ALIAS=kiosk-development
            ;;
        release)
            kiosk_release_metadata
            KEYSTORE="${KIOSK_RELEASE_KEYSTORE:-}"
            KEY_ALIAS="${KIOSK_RELEASE_KEY_ALIAS:-}"
            [ -n "$KEY_ALIAS" ] || kiosk_fail 'Set KIOSK_RELEASE_KEY_ALIAS.'
            kiosk_external_file "$KEYSTORE" "$root"
            kiosk_external_file "${KIOSK_RELEASE_STORE_PASS_FILE:-}" "$root"
            kiosk_external_file "${KIOSK_RELEASE_KEY_PASS_FILE:-}" "$root"
            [ "$KEY_ALIAS" != kiosk-development ] || kiosk_fail 'The development key alias is forbidden for release.'
            ;;
        *) kiosk_fail 'Usage: build-apk[-mac].sh [development|release]' ;;
    esac
}

kiosk_sign_apk() {
    local mode="$1" unsigned="$2" output="$3"
    if [ "$mode" = development ]; then
        if [ ! -f "$KEYSTORE" ]; then
            (umask 077; mkdir -p "$(dirname "$KEYSTORE")"
             "$JDK/bin/keytool" -genkeypair -keystore "$KEYSTORE" -storetype PKCS12 \
                -alias "$KEY_ALIAS" -keyalg RSA -keysize 3072 -validity 3650 \
                -storepass development-only -keypass development-only \
                -dname 'CN=Kiosk Development Only, O=Local Development, C=US')
        fi
        "$JDK/bin/java" -jar "$BUILD_TOOLS/lib/apksigner.jar" sign \
            --ks "$KEYSTORE" --ks-key-alias "$KEY_ALIAS" --ks-pass pass:development-only \
            --out "$output" "$unsigned"
        "$JDK/bin/java" -jar "$BUILD_TOOLS/lib/apksigner.jar" verify "$output"
    else
        local store_pass_file key_pass_file
        local key_pass_args=()
        # MSYS does not translate paths embedded in apksigner's file: argument.
        store_pass_file="$(kiosk_native_path "$KIOSK_RELEASE_STORE_PASS_FILE")"
        key_pass_file="$(kiosk_native_path "$KIOSK_RELEASE_KEY_PASS_FILE")"
        # apksigner consumes successive lines when both options name one file.
        # Omitting --key-pass reuses the store password for a shared input file.
        if [ "$store_pass_file" != "$key_pass_file" ]; then
            key_pass_args=(--key-pass "file:$key_pass_file")
        fi
        "$JDK/bin/java" -jar "$BUILD_TOOLS/lib/apksigner.jar" sign \
            --ks "$KEYSTORE" --ks-key-alias "$KEY_ALIAS" \
            --ks-pass "file:$store_pass_file" ${key_pass_args[@]+"${key_pass_args[@]}"} \
            --out "$output" "$unsigned" </dev/null
        if ! kiosk_verify_release "$output"; then
            rm -f -- "$output" "$output.idsig"
            kiosk_fail 'Release verification failed; rejected APK removed.'
        fi
    fi
}

kiosk_verify_release() (
    local apk="$1" report badging digest count
    kiosk_release_metadata
    [ -f "$apk" ] || kiosk_fail 'Release APK does not exist.'
    report="$("$JDK/bin/java" -jar "$BUILD_TOOLS/lib/apksigner.jar" verify --verbose --print-certs "$apk")" || kiosk_fail 'APK signature verification failed.'
    count="$(printf '%s\n' "$report" | sed -n 's/^Number of signers: //p')"
    [ "$count" = 1 ] || kiosk_fail 'Release must have exactly one signer.'
    digest="$(printf '%s\n' "$report" | sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | tr '[:upper:]' '[:lower:]')"
    [ "$digest" = "$CERT_PIN" ] || kiosk_fail 'APK certificate does not match the approved release fingerprint.'
    printf '%s\n' "$report" | grep -Fq 'Signer #1 certificate DN: CN=Kiosk Development Only' && kiosk_fail 'Development certificate is forbidden for release.'
    badging="$("$BUILD_TOOLS/aapt2" dump badging "$apk")" || kiosk_fail 'APK metadata could not be read.'
    printf '%s\n' "$badging" | grep -q '^application-debuggable' && kiosk_fail 'Debuggable APK is forbidden for release.'
    case "$badging" in
        "package: name='com.example.webkiosk' versionCode='$VERSION_CODE' versionName='$VERSION_NAME' "*) ;;
        *) kiosk_fail 'APK package/version differs from the approved release metadata.' ;;
    esac
    echo "Verified release: versionCode=$VERSION_CODE versionName=$VERSION_NAME certificateSHA256=$digest"
)
