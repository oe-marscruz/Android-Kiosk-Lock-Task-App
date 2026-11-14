# APK signing and device migration

Session 4 implementation, November 13, 2026. Production signing and device migration are **pending operational acceptance**. Disposable signing fixtures are not approved releases.

## Compromised identity

The removed repository key, the tracked legacy APK, and the installed kiosk APK on Lenovo TB336FU `HNY0HQ1J` all have certificate SHA-256:

```text
ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102
```

Treat this identity as compromised permanently. Removing the current key does not remove historical copies, downloaded bundles, or old scratch builds. Do not sign another production APK with it. History rewriting is not a credential rotation and is outside this change. The retained legacy APKs support comparison only; the release gate rejects their certificate.

Read-only inventory on November 13 confirmed that the connected tablet's installed APK hash is `94747b52f7c9751aeb28302ec359b0e02b49d9cbf65d68c9b5c74ee5a53583c0`, matching the Session 3 APK. `adb -s HNY0HQ1J shell dpm list-owners` reported **TestDPC** (`com.afwsamples.testdpc/.DeviceAdminReceiver`) as device owner. This does not establish how other tablets are enrolled. No installation, ownership change, uninstall, reboot or reset was performed for Session 4.

## Development builds

Run either entry point from Git Bash on Windows or Bash on macOS:

```bash
bash build-apk.sh development
# On a Mac:
bash build-apk-mac.sh development
```

Both use [the shared builder](tools/build-apk-common.sh), [tool discovery](tools/android-toolchain.sh), and [signing checks](tools/signing.sh). Set `KIOSK_JDK`, `KIOSK_ANDROID_SDK`, `KIOSK_BUILD_TOOLS`, or `KIOSK_PLATFORM` when automatic discovery is unsuitable. The setup scripts' build-tools 35.0.0 remain supported; 36.0.0 is preferred and was tested on Windows.

A new local development key is generated under ignored `.local-signing/development.p12`. It has a public development-only password and a clearly labeled certificate. Development APKs are debuggable, default to version code `1` / name `0.0.0-dev`, and land under ignored `build/development/`. This identity differs from the historical exposed key and cannot update its installations. Never use it for production. Preserve this local key only when continuity on a disposable development installation matters.

Build intermediates use unique directories under ignored `tmp/`; building no longer deletes the entire build directory or prior session APKs. Output is promoted only after signature verification. A failed rebuild can leave an older verified output in place, so check the build exit status and recorded artifact hash before using any output.

The navigation instrumentation runner now requires explicit `-TargetApk`, `-TestKeystore`, `-TestKeyAlias`, `-TestStorePassFile` and `-TestKeyPassFile` inputs. The test and target APKs must have matching signing identities. Use a disposable development installation for future tests; do not give production signing credentials to an instrumentation job. The historical Session 3 command without these inputs is intentionally superseded. A differently signed development APK cannot replace the already installed legacy APK with `install -r`.

## Protected release builds

An authorized key custodian must create the actual production key outside the checkout in an access-controlled location, retain an encrypted recoverable backup, and record its public certificate fingerprint through an independent trusted channel. Do not put key/password files into source control, release assets, desktop bundles, logs, chat, or artifact uploads. Ignore patterns provide a backstop; operating-system ACLs, backup, custody, and GitHub environment protection still need operational configuration.

Set these non-secret inputs and protected file locations in the build shell. Paths below are examples to replace; no production identity has been selected by this change:

```bash
export KIOSK_RELEASE_KEYSTORE='/protected/location/kiosk-release.p12'
export KIOSK_RELEASE_KEY_ALIAS='approved-release-alias'
export KIOSK_RELEASE_STORE_PASS_FILE='/protected/location/store.pass'
export KIOSK_RELEASE_KEY_PASS_FILE='/protected/location/key.pass'
export KIOSK_RELEASE_CERT_SHA256='REPLACE_WITH_INDEPENDENTLY_APPROVED_64_HEX_DIGEST'
export KIOSK_VERSION_CODE='REPLACE_WITH_NEXT_INTEGER'
export KIOSK_PREVIOUS_VERSION_CODE='REPLACE_WITH_PREVIOUS_DEPLOYED_INTEGER'
export KIOSK_VERSION_NAME='REPLACE_WITH_APPROVED_VERSION_NAME'
bash build-apk.sh release
# Or on a Mac: bash build-apk-mac.sh release
```

Each password file contains one UTF-8/ASCII line with no BOM. The two paths may name the same file when both passwords are identical. Passwords are passed through `apksigner` file inputs, never printed or placed directly on its command line. Key and password files must be nonempty regular files outside the checkout; direct symlinks and files under linked checkout parents are rejected. On Windows, key custody must also prohibit alternate junction/drive aliases into the checkout. Do not enable shell tracing or run credential commands in a recording terminal.

Release builds require the approved fingerprint and explicit version metadata. Version codes are integers from 1 to 2100000000 and must exceed the recorded prior code. Use prior code `0` only for the first enrollment under the new identity. The prior value is an operator input: this code compares it, but cannot independently know the fleet's maximum installed code. Consult and update the release ledger before each build; CI environment review must check these values.

The resulting path is `build/release/CU-Denver-Equity-Kiosk-release-v<VERSION_CODE>.apk`. Verification requires a valid signature, exactly one signer, the independently pinned certificate, the expected package/version, and a non-debuggable APK. The exposed fingerprint and the development identity are rejected. Both build entry points use this check. A valid signature alone does not prove fresh enrollment, kiosk operation, or update compatibility on a tablet.

## Desktop packaging and CI

Package only an already reviewed release APK:

```bash
export KIOSK_RELEASE_APK='/absolute/path/to/reviewed-release.apk'
# Keep the approved certificate/version variables above; no private key is needed.
bash tools/verify-release-apk.sh "$KIOSK_RELEASE_APK"
bash package-win.sh
# Or on a Mac: bash package-mac.sh
```

The Windows packager stages the supplied APK under ignored `dist/build/`; the Mac packager uses a unique ignored `tmp/package-mac.*` directory. They verify those staged bytes and pass that file to PyInstaller at the root path the frozen GUI expects. They do not build another APK or fall back to the repository binary. The Mac DMG's separate manual APK is the same staged file. Do not point the input variable at the staging destination itself. Verification happens before Python installation or desktop bundling. Running the Python GUI directly from source requires an explicit `KIOSK_RELEASE_APK`; that source route does not independently verify its release identity.

Mac packaging also checks manifest/DEX component definitions, bundles ADB as a native binary, and runs the relocated frozen app's resource check before creating the DMG. It compares the bundled APK's SHA-256 with the verified staging input and executes only `adb version`. The resource check does not prove device discovery, setup, or full GUI acceptance. Toolchain and resource reports are retained under `dist/macos-evidence/` and uploaded by the Mac workflow. See [Session 9](REMEDIATION_PLAN.md#session-9---november-13-2026) for verified results and remaining Mac/tablet tests.

The [Windows workflow](.github/workflows/build-exe.yml) and [Mac workflow](.github/workflows/build-dmg.yml) now run by manual dispatch. Set an independently approved `KIOSK_RELEASE_CERT_SHA256` variable on a protected GitHub environment named `release`; configure its required reviewers and allowed branches in repository settings. Supply an HTTPS URL for the reviewed release APK and the approved current/prior version values. The workflows download the APK, verify it, invoke the same packaging scripts, and upload only the desktop artifact. They do not receive private signing keys. Automatic rolling publication of the historical APK has been removed; neither updated workflow publishes a GitHub Release. Existing published binaries remain historical and need a separately authorized withdrawal/replacement decision.

GitHub Actions execution, actual Windows EXE behavior and actual macOS build/DMG behavior have not been validated by local shell/signing tests. Session 9 still owns full macOS packaging acceptance. Shared source lists now include the admin receiver on both platforms because release builds must contain the declared components.

## Existing-installation migration

1. Inventory every device by explicit serial: model/OS, installed APK hash, certificate fingerprint, version code, actual device-owner component, management authority, recovery access, and operational owner. Record whether the kiosk or another DPC owns it. Do not assume the connected TestDPC tablet represents the fleet.
2. Approve a new protected identity, backup/recovery owner, artifact hash, and release ledger entry. Archive required configuration separately; never export browsing history, cookies, report content, or Wi-Fi passwords as migration evidence.
3. On a designated disposable **fresh** device, install the new-key release and provision the kiosk receiver as device owner through the approved enrollment procedure. Test Home, kiosk, Chrome/Wi-Fi, network flows, ownership, lock task and restart under explicit device/restart authorization. A successful install alone is insufficient.
4. Build a higher-code release with the same new key, install with `adb -s <confirmed-serial> install -r <new-apk>`, and verify the installed hash/certificate/version and kiosk behavior. Record the outcome.
5. On that disposable new-key installation, attempt an update APK for the same package signed by the **old exposed identity**, using a higher version code so the failure demonstrates signature rejection rather than downgrade prevention. Require `INSTALL_FAILED_UPDATE_INCOMPATIBLE` (or the OS's explicit signing mismatch), then confirm the new-key installation and device owner remain intact. An arbitrary different-key fixture is useful preparation but does not replace this old-key acceptance test.
6. For a kiosk-owned legacy device, the default migration proposal is a scheduled, explicitly approved reset and fresh enrollment with the new identity. Test this process on a disposable enrolled device before scheduling fleet work. Verify recovery, configuration, ownership, new-key updates and old-key rejection. Do not try to casually uninstall an active device-owner package, clear its data, transfer ownership, or use a factory-reset command without a separately approved device-specific procedure.
7. If another DPC owns the device (as on the inventoried TestDPC tablet), have the management owner review replacement/re-enrollment options. Do not remove TestDPC, assume ownership can be transferred, or infer that replacing a non-owner kiosk package is authorized or sufficient. A same-package APK under an unrelated new key is not an in-place update of the old signature.
8. Signing lineage alone is not the accepted recovery plan for an exposed key. Any proposed alternative must explicitly assess whether the compromised key can still authorize updates on each supported OS, how rollback/recovery works, and prove those behaviors before fleet acceptance. Do not claim this change revokes historical trust.

No device migration has been performed. A reset/re-enrollment is not a rollback to the exposed identity; recovery should use the protected new key and approved recovery enrollment. If the new key is lost or enrollment fails, stop and use the approved recovery process rather than re-enabling compromised signing.

## Release ledger and acceptance

There are **no approved production releases under the new identity yet**. Add production entries here or in the approved external release register after key-custodian review. Record version code/name, prior deployed maximum, APK SHA-256, certificate SHA-256, custody/backup reference (no secrets), date, approver and acceptance evidence. Disposable test versions 100/101 are excluded.

Pending acceptance:

- Production key custody, backup, independent fingerprint approval and CI environment configuration.
- Real release build and protected-key artifact review.
- Fresh device-owner enrollment with the new key; normal higher-version update; explicit rejection of the old key.
- Disposable enrolled-device migration and recovery rehearsal; then a separately approved fleet schedule.
- Live desktop packaging/CI and macOS checks, preserving Session 9's remaining acceptance scope.

Run the SDK-backed host contract tests from Git Bash, supplying a writable temporary directory **outside** the checkout:

```bash
bash tests/test_signing.sh '/external/temporary/directory'
```

These tests create clearly labeled two-day disposable keys, build real APKs through both entry points, and exercise missing credentials, certificate/version checks, tampering, development identity separation, packaging rejection, and password-log scanning. They never install an APK or modify an enrolled device. Inspect [the remediation evidence](REMEDIATION_PLAN.md) for the actual results and limits of this session.
