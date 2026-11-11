# Kiosk remediation plan: nine implementation sessions

- Prepared: November 11, 2026
- Reviewed baseline: `97a7b97`
- Repository: Android-Kiosk-Lock-Task-App
- Status: Session 1 device acceptance passed for the launcher; lock-task provisioning remains unverified. Session 2 code and artifact checks passed; device acceptance is pending. Sessions 3-9 are pending.

## Purpose and scope

Resolve the nine findings from the repository review, with one issue assigned to each session. Each session should leave a reviewable change, focused test evidence, and a clear handoff.

The findings came from source review and inspection of the packaged APK. The review confirmed its manifest, defined classes, and signing certificate. It did not reproduce failures on a tablet, rebuild the application, or test a macOS package. Start each implementation session by reproducing the relevant failure where practical.

This document is a plan. None of its implementation steps or acceptance tests have been completed merely because they appear here. It does not authorize a production device wipe, a signing-key migration, or deployment.

## Session tracker

Keep the issue numbers stable when recording work or opening separate chats.

| Session | Issue | Main result | Implementation | Acceptance |
| --- | --- | --- | --- | --- |
| 1 | Launcher class mismatch | Home resolves to a class included in the APK | Device verified | Passed on Lenovo TB336FU; lock-task provisioning unverified |
| 2 | Missing Wi-Fi permission | Wi-Fi screen opens and handles permission states | Code/artifact verified | Pending tablet tests |
| 3 | Navigation allowlist bypass | Only approved HTTPS hosts are accepted | Pending | Pending |
| 4 | Exposed APK signing key | Protected release signing and a documented migration path | Pending | Pending |
| 5 | Setup disables required apps | Required apps remain available; restoration preserves prior state | Pending | Pending |
| 6 | Background time bypasses inactivity expiry | Expired sessions reset before content becomes visible | Pending | Pending |
| 7 | Session reset retains history or cookies | Reset removes the prior browsing session before a new one starts | Pending | Pending |
| 8 | Setup reports success after failure | Setup stops on failure and verifies the selected device | Pending | Pending |
| 9 | Incomplete macOS build and package | The APK includes its receiver and is bundled where the GUI expects it | Pending | Pending |

### Order and dependencies

Sessions 1 through 9 can follow the review order. Keep these dependencies explicit:

- Session 1 establishes a usable home screen for later tablet tests.
- Session 2 fixes a separate crash in the Wi-Fi flow that session 5 must exercise.
- Session 3 introduces a testable navigation policy that session 7 must preserve.
- Session 4 can complete signing code and fresh-device tests separately from an existing-device migration. Do not mark migration complete without installed-device evidence.
- Sessions 5 and 8 both change desktop provisioning. Session 5 owns which packages may change; session 8 owns device selection, command handling, and success/failure decisions.
- Session 6 owns expiry timing. Session 7 owns the reset operation. Passing session 6 alone does not prove session isolation.
- Session 9 uses the signing behavior from session 4 and the command handling from session 8.

## Working rules for every session

1. Read this plan and any current repository instructions. Check the active branch, recent commits, and local edits. If continuing against a remote branch, fetch it when available and compare before changing code.
2. Preserve unrelated changes. At the reviewed baseline, the IDE configuration directory and module file were already untracked.
3. Reproduce the issue with synthetic data on a designated test device or fixture. Do not submit real Equity or Maxient reports as test data.
4. Make the smallest complete change for the assigned issue. Add tests that exercise observable behavior, especially a failure case that the old code mishandles.
5. Build the affected artifact and inspect or run that artifact. A source change or successful package build alone does not prove tablet behavior.
6. Update this tracker and the relevant session evidence entry. Distinguish code verified, artifact verified, device verified, and pending checks.
7. Review the diff and record the commit or branch. Only mark acceptance passed when all required checks for that session have passed.

The repository currently uses manual APK build scripts, not a checked-in Gradle project, and has no tracked test suite. Retain that build path for this work. Add a small test harness where a session needs one; a full build-system migration is outside these nine issues.

For Python tests, prefer the standard-library `unittest` runner and mocked command results. Keep tests independent of a live ADB connection. A future `python -m unittest discover -s tests -v` command requires those tests to be created first. Follow the execution environment's Python configuration requirements.

### Common checks

Run these from the clone root:

```powershell
git status --short --branch
git log -1 --oneline
git diff --check
```

Check each shell script separately; passing several filenames to one `bash -n` invocation does not check all of them:

```powershell
$KioskShellScripts = @(
    'build-apk.sh',
    'build-apk-mac.sh',
    'package-win.sh',
    'package-mac.sh',
    'setup-tools-mac.sh'
)
foreach ($KioskScript in $KioskShellScripts) {
    & bash -n $KioskScript
    if ($LASTEXITCODE -ne 0) { throw "Syntax check failed: $KioskScript" }
}
```

On Windows, use Git Bash and the selected JDK/Android SDK for `bash build-apk.sh`. This build deletes and recreates the build directory. Preserve any baseline artifact needed for comparison outside that directory first. Do not run device setup as a substitute for a build check.

The following inspection commands use the SDK version observed during the review. Adjust the SDK/tool paths to an installed, deliberately selected version:

```powershell
$KioskSdk = Join-Path $env:LOCALAPPDATA 'Android/Sdk'
$KioskBuildTools = Join-Path $KioskSdk 'build-tools/36.0.0'
$KioskApk = Join-Path (Get-Location) 'build/CU-Denver-Equity-Kiosk.apk'
$KioskAapt2 = Join-Path $KioskBuildTools 'aapt2.exe'
& $KioskAapt2 dump badging $KioskApk
& $KioskAapt2 dump xmltree --file AndroidManifest.xml $KioskApk
```

For device commands, set an explicit serial and use it for every operation. Confirm that the serial identifies the designated test tablet before any installation or configuration change:

```powershell
$KioskAdb = Join-Path $KioskSdk 'platform-tools/adb.exe'
$KioskSerial = 'REPLACE_WITH_TEST_DEVICE_SERIAL'
& $KioskAdb devices -l
& $KioskAdb -s $KioskSerial get-state
```

The intended acceptance target is the Lenovo tablet running Android 15. Record the actual device model, Android version, APK hash, and signing-certificate fingerprint. Testing that tablet does not certify the declared minimum SDK of 21 or every Android version.

## Session 1 - Correct the launcher class

**Finding:** [AndroidManifest.xml](app/src/main/AndroidManifest.xml) declares `.kiosklauncher.LauncherActivity` under `com.example.webkiosk`. [LauncherActivity.java](app/src/main/java/com/example/kiosklauncher/LauncherActivity.java) declares `com.example.kiosklauncher`. APK inspection confirmed the same mismatch.

### Execute

1. Reproduce the failed home launch on the test tablet and capture the activity launch result and relevant crash log.
2. Use the fully qualified existing class name, `com.example.kiosklauncher.LauncherActivity`, in the manifest.
3. Change the home component passed by [kiosk-manager.py](kiosk-manager.py) to `com.example.webkiosk/com.example.kiosklauncher.LauncherActivity`. Search for every reference to the old component.
4. Add a lightweight artifact check that resolves manifest component names and verifies that the corresponding classes are defined in the APK. Include the launcher and admin receiver.
5. Rebuild the APK. Confirm that the packaged manifest and class table agree.

### Test

- The artifact check fails against the baseline mismatch and passes against the corrected build.
- Install the rebuilt APK on the test device, then run:
  ```powershell
  & $KioskAdb -s $KioskSerial shell am start -W -n 'com.example.webkiosk/com.example.kiosklauncher.LauncherActivity'
  & $KioskAdb -s $KioskSerial shell cmd package set-home-activity 'com.example.webkiosk/com.example.kiosklauncher.LauncherActivity'
  & $KioskAdb -s $KioskSerial shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME
  ```
- Launch Home, enter the kiosk, and return to Home through the supported back flow.
- Restart the test tablet and verify that its configured home screen opens without a class-loading crash.

**Complete when:** The corrected APK contains the declared launcher, explicit launch succeeds, and Home works after restart. Record unresolved lock-task/provisioning failures separately; do not mask them with a successful explicit activity launch.

## Session 2 - Fix Wi-Fi permission handling

**Finding:** [WifiSettingsActivity.java](app/src/main/java/com/example/webkiosk/WifiSettingsActivity.java) queries the active network on Android 12+ without declaring `ACCESS_NETWORK_STATE` in [AndroidManifest.xml](app/src/main/AndroidManifest.xml).

### Execute

1. Reproduce opening the Wi-Fi screen with Wi-Fi enabled and capture the permission exception.
2. Declare `android.permission.ACCESS_NETWORK_STATE`. It is a normal manifest permission; do not add a runtime prompt for it.
3. Review the separate requirements for reading the SSID and adding a network. An unavailable or redacted SSID must not be treated as proof that the tablet is disconnected.
4. Handle missing services, denied access, and invalid SSID/passphrase input with an actionable message. Validate input before building a network suggestion; do not allow builder exceptions to close the activity.
5. Preserve the existing runtime permission flow where needed and avoid displaying or logging network passwords.

### Test

- Inspect the rebuilt APK to confirm the new permission is packaged.
- Open the Wi-Fi screen with Wi-Fi off, on but disconnected, and connected.
- Deny and then grant the requested runtime permission; the screen remains usable in both cases.
- Exercise an open network, a valid WPA2 test network, an invalid password length, and an unavailable/redacted SSID.
- Verify actual connectivity separately from a successful suggestion submission; the API accepting a suggestion is not proof of connection.

**Complete when:** The screen opens reliably on the Android 15 test tablet, permission/input failures do not crash it, and a test network can be used or its remaining approval requirements are accurately reported.

## Session 3 - Enforce the navigation policy

**Finding:** The hostname suffix check in [MainActivity.java](app/src/main/java/com/example/webkiosk/MainActivity.java) accepts look-alike hosts such as `attackerucdenver.edu`, and does not require HTTPS.

### Execute

1. Extract one small navigation-policy helper with deterministic host/scheme checks and focused host-side tests. Keep it usable without an Android device.
2. Accept only HTTPS URLs whose normalized host equals an approved domain or ends with a dot followed by that domain. Preserve the current approved domains unless a separate product decision changes them.
3. Reject missing/malformed hosts and unsupported schemes. Apply the policy to every app-controlled navigation path, including any legacy callback retained for supported Android versions.
4. Disable cleartext traffic in the manifest and retain mixed-content blocking.
5. Keep external navigation visibly blocked. Verify redirects against the same policy; do not relax the allowlist to make an unrelated test pass.

### Test

| Input | Expected |
| --- | --- |
| `https://ucdenver.edu/` and `https://www.ucdenver.edu/offices/equity` | Allow |
| `https://cm.maxient.com/` | Allow |
| A valid subdomain of either approved domain | Allow under the existing subdomain policy |
| `https://attackerucdenver.edu/` | Block |
| `https://ucdenver.edu.attacker.example/` | Block |
| `https://cm.maxient.com.attacker.example/` | Block |
| `https://ucdenver.edu@attacker.example/` | Block |
| `http://www.ucdenver.edu/` | Block |
| Missing host, malformed URL, `file:`, `content:`, `intent:`, or `javascript:` navigation | Block |
| Uppercase HTTPS scheme/approved hostname | Same result after normalization |

Run the host-side cases before and after the fix. On the tablet, verify approved links, blocked links, an approved-to-disallowed redirect, and the intended Equity-to-Maxient flow using synthetic data. Confirm that initial loads and future reset loads use approved URLs.

**Complete when:** Boundary-case tests pass and the actual WebView enforces the same policy. Record any required external service that the current policy blocks rather than silently approving it.

## Session 4 - Protect release signing and plan migration

**Finding:** The distributed APK's signing certificate matches the private key in [debug.keystore](debug.keystore). [build-apk.sh](build-apk.sh) and [build-apk-mac.sh](build-apk-mac.sh) use that key and its known password.

### Execute

1. Inventory signing identities used by existing installations and record the current APK certificate fingerprint. The reviewed fingerprint was:
   `CC:FB:B9:FE:8D:73:E3:7D:F1:36:19:75:C6:5D:FA:84:AB:1E:B7:BE:48:FC:31:C9:31:B6:39:0C:83:B6:D1:02`.
2. Separate development and release signing. Keep development keys untracked; require an external protected key for release builds.
3. Make release signing fail when credentials are missing. Do not fall back to the exposed key. Use protected secret/environment/file inputs without printing passwords or placing private keys in artifacts.
4. Give release artifacts explicit version metadata and maintain increasing version codes for supported updates.
5. Update both build scripts and release workflows to consume a verified release APK. Verify its signature and certificate before desktop packaging.
6. Remove the exposed key from current tracked files and add appropriate ignore rules after the replacement and migration approach are established. Deleting it from the latest commit does not make the historical key secret again.
7. Document the supported path for existing device-owner installations. Test fresh enrollment and any proposed update/migration separately. A device-owner application cannot be casually uninstalled as a recovery step; plan any re-enrollment or reset explicitly. Do not assume signing lineage alone removes the risk of an already exposed key.

### Test

- Development builds still work with a separate development identity.
- Release builds fail clearly when the protected key or password is missing.
- Verify the actual release APK with `apksigner verify --print-certs`; its certificate differs from the exposed certificate.
- Search source, logs, bundles, and tracked files for accidentally included private keys or passwords.
- On a fresh test deployment, install the new release and provision device ownership.
- Verify a normal subsequent update signed by the new key.
- Verify that an APK signed with the old key cannot update that fresh new-key deployment.
- Test any existing-installation migration on a disposable enrolled device before scheduling fleet work.

**Complete when:** Signing code and fresh-device tests pass, and the existing-device migration is either verified or explicitly recorded as pending operational acceptance. Do not mark fleet migration complete based on a newly signed APK.

## Session 5 - Preserve required apps during setup

**Finding:** The package-disabling loop in [kiosk-manager.py](kiosk-manager.py) exempts only the kiosk and Clock. It can disable Chrome and Settings even though the kiosk exposes them.

### Execute

1. Replace broad launcher enumeration followed by disablement with an explicit, reviewed package policy for the target tablet.
2. Preserve the kiosk, Chrome, Settings, active keyboard, required accessibility services, and system dependencies. Do not disable an unfamiliar package merely because it has a launcher activity.
3. Record original enabled states for packages this setup actually changes. Record no Wi-Fi credentials or browsing data.
4. Restore only setup's own changes and their original states. Do not enable every package that happened to be disabled before setup.
5. Make the operation repeatable. A second setup run must preserve the first run's original-state record rather than overwrite it with the already-modified state.
6. Coordinate with session 8's command-result handling. At minimum, failed package changes must be reported accurately in this session.

### Test

- Mock package discovery to include Chrome, Settings, keyboard, accessibility services, unknown packages, and approved optional apps.
- Assert that required/unknown packages never receive a disable command.
- Start with an unrelated app already disabled; setup and restoration must leave it disabled.
- Run setup twice, then restore; only setup's changes are undone.
- On the test tablet, open Chrome, system Wi-Fi Settings, and the custom Wi-Fi screen from the launcher while using the intended lock-task configuration.
- Verify that the keyboard and required accessibility functions remain usable.

**Complete when:** Required apps work after setup, package changes follow the explicit policy, and restoration preserves pre-existing disabled states.

## Session 6 - Count background time toward expiry

**Finding:** [MainActivity.java](app/src/main/java/com/example/webkiosk/MainActivity.java) cancels the inactivity callback on pause and starts a new three-minute period on resume.

### Execute

1. Track the last actual user interaction with a monotonic clock. Lifecycle callbacks must not count as user activity.
2. On resume, compare elapsed time before revealing the old page. If expired, invoke the reset operation and keep prior content covered until reset completes.
3. Schedule only the remaining interval for an unexpired session. Cancel callbacks when appropriate without losing the expiry decision.
4. Define process recreation and reboot behavior. A fresh process with untrusted session age must start a cleared session rather than restore a sensitive page.
5. Pair WebView pause/resume calls correctly and prevent duplicate callbacks.
6. Use a controllable clock or test timeout for automated tests. Keep the production timeout at three minutes.

### Test

- Foreground inactivity triggers expiry at the configured threshold.
- Genuine interaction extends the deadline; pause/resume alone does not.
- Resume just before expiry: only the remaining interval is available.
- Resume at or after expiry: old content never becomes interactable.
- On the test tablet, open a synthetic form, turn the screen off for more than three minutes, then return.
- Repeat through a background transition, activity recreation, and process restart.
- Confirm that the timing fix invokes reset once. Verify the reset's data isolation in session 7.

**Complete when:** Timing tests and tablet lifecycle checks show that elapsed background time expires the session before old content is shown. Session isolation remains dependent on session 7.

## Session 7 - Make reset remove the old browsing session

**Finding:** [MainActivity.java](app/src/main/java/com/example/webkiosk/MainActivity.java) clears history before loading the start page and starts navigation without waiting for asynchronous cookie deletion.

### Execute

1. Consolidate timeout, explicit exit, and fresh-session initialization around one reset operation.
2. Cover or disable the old content, stop its navigation, and prevent new requests while resetting.
3. Wait for cookie deletion to complete before loading the next session. Clear the relevant WebView storage and cache.
4. Prefer disposing of the old WebView and creating a newly configured instance to retaining an old form document. Preserve the navigation/security configuration from session 3.
5. Ensure that the new homepage is the only usable history entry. If retaining a WebView, clear its history after replacement navigation has committed or finished, not just before it starts.
6. Handle concurrent reset requests, activity destruction, and failed homepage loads. Old callbacks must not reopen prior content or operate on a destroyed WebView.
7. Do not rely on `onDestroy()` for privacy cleanup; process termination may skip it. Clear stale persisted session state before the next session makes network requests.

### Test

Use an isolated test build and synthetic pages/cookies; do not enter actual report data. A test fixture may use `loadDataWithBaseURL` or a controlled test navigation policy, but production allowlist checks must remain separately covered.

- Enter a synthetic marker into a form, create test cookies/storage, and navigate through multiple pages.
- Trigger reset and press Back repeatedly; the old form and marker must never return.
- Delay the cookie-deletion callback; verify that the next-session page does not load early.
- Confirm that a controlled endpoint or fixture observes no previous-session cookie after reset.
- Repeat with an offline homepage, rapid repeated resets, rotation, app exit, and process restart.
- Verify both timeout-triggered and explicit-exit resets.
- Confirm that approved navigation still works and blocked navigation remains blocked.

**Complete when:** The actual WebView cannot recover the previous session through history, cookies, retained form state, or restart, including when reset encounters a network failure.

## Session 8 - Make provisioning stop on failure

**Finding:** [kiosk-manager.py](kiosk-manager.py) accepts the empty ADB device-list header, ignores several failed commands, and can announce setup success without a working kiosk.

### Execute

1. Parse ADB device rows and their exact states. Ignore the header; reject zero authorized devices and require explicit selection when more than one is available.
2. Bind every subsequent command to the selected serial. Apply the same selection discipline to other management actions.
3. Replace shell-built command strings with argument lists where practical. Parse policy/package output in Python rather than piping through Windows-only `findstr`; preserve paths containing spaces.
4. Make setup a sequence of steps with explicit results. Stop after installation, ownership, home-selection, or required configuration failure.
5. Verify the exact device-owner component. A message containing "already" is not proof that this application owns the device.
6. Verify the configured home, required package states, and actual lock-task policy before success. Ensure policy configuration can be applied on an already-enrolled device rather than relying only on the initial admin-enabled callback.
7. Remove automatic uninstall on signature mismatch. Report a signing/migration problem for the session 4 procedure instead.
8. Route UI updates through Tk's main event loop and prevent overlapping setup operations. Keep ADB calls testable without opening the GUI.
9. Apply equivalent failure reporting to [setup-kiosk.bat](setup-kiosk.bat), or have it delegate to the same tested provisioning logic. Do not leave the CLI claiming success under conditions the GUI rejects.

### Test

Create host-side tests using a fake ADB runner; never invoke a real reset or uninstall during these tests.

- Empty device list, unauthorized/offline device, multiple devices, explicit valid selection, and disconnection mid-setup.
- Install timeout, install failure, signature mismatch, another device owner, failed home selection, failed package change, and missing lock-task permission.
- Assert that dependent steps stop after failure and that no completion dialog reports success.
- Assert that every device command includes the selected serial.
- Assert that signature mismatch never triggers uninstall.
- Run the success path and a second setup pass; verify the final state rather than matching generic output text.
- Exercise equivalent CLI failures and nonzero exit status.
- On the test tablet, complete a real setup and inspect ownership, Home, package availability, and actual lock-task operation.

**Complete when:** Mocked failure paths fail predictably, the CLI and GUI report consistent results, and real-device setup reaches and verifies the intended state.

## Session 9 - Repair macOS compilation and packaging

**Finding:** [build-apk-mac.sh](build-apk-mac.sh) omits the device-admin receiver from its source list. [package-mac.sh](package-mac.sh) and the [macOS workflow](.github/workflows/build-dmg.yml) do not bundle the APK at the path used by the frozen GUI in [kiosk-manager.py](kiosk-manager.py). Both omissions belong to the original ninth issue.

### Execute

1. Include `KioskDeviceAdminReceiver.java` in the macOS APK build. Keep its source inventory and supported Java compilation settings aligned with the Windows build.
2. Add the APK to PyInstaller's bundled data at `CU-Denver-Equity-Kiosk.apk` under the frozen application's resource root. A separate folder beside the app in the DMG does not satisfy the GUI lookup.
3. Make the same change in the local packaging script and CI workflow. Preserve the standalone APK copy only if it remains useful for manual installation.
4. Add artifact checks for required APK component classes and bundled resource availability. Fail packaging if either check fails.
5. Use session 4's selected signing mode and session 8's platform-independent command handling. Prefer one shared packaging entry point so CI and local packaging do not drift.

### Test

- Run syntax checks and a clean APK build on macOS.
- Inspect the resulting APK: the manifest's receiver and launcher must both have defined classes.
- Build the app/DMG, then copy the app to a location outside the repository and run it there.
- Confirm that bundled ADB and APK are found without any source checkout, working-directory dependency, or sibling APK folder.
- Exercise device discovery and setup with the designated tablet; verify that no Windows-only command pipeline is required.
- Compare local and CI artifact checks. Record macOS version, CPU architecture, JDK, SDK, and build-tool versions.
- Record platforms or architectures not exercised; do not infer Intel or Apple Silicon acceptance from the other.

**Complete when:** A clean macOS build includes the receiver and the relocated packaged app can install its own bundled APK and complete the supported setup flow.

## Evidence and handoff

For each session, record the following in its own short entry below or in a linked issue-specific repository document:

- Session number, date, branch/commit, and files changed.
- Baseline reproduction and the observed failure.
- Tests added and exact commands executed.
- Artifact hash and signing identity where relevant.
- Device/platform used and observed results.
- Any failure, blocker, deferred migration, or acceptance test not run.
- The next session's dependencies or changed assumptions.

Use these status values: **Pending**, **Implemented**, **Code/artifact verified**, **Device verified**, or **Blocked**, with a reason. A missing platform or device check stays pending; it is not a passing test.

### Reusable next-session prompt

> Read REMEDIATION_PLAN.md and implement session N only, incorporating prior completed sessions. Verify the current checkout and instructions first. Reproduce the issue where practical, make the scoped changes, add focused behavioral tests, and validate the affected artifact. Preserve unrelated files. Update the tracker and evidence with exact outcomes and any device/macOS checks not run. Stop before production deployment, device wipes, or an unverified signing-key migration.

### Session evidence entries

### Session 1 — November 11, 2026

- Status: **Device verified**; launcher acceptance passed on the test tablet. Branch `master`, baseline `97a7b97`; changes remain uncommitted. Fetch of `origin` showed no newer commit.
- Changed the manifest launcher and the manager's Home component; added `tools/check_apk_components.py` and `tests/test_apk_components.py`. Original tracked APK remains unchanged. The rebuilt APK is `build/CU-Denver-Equity-Kiosk-session1.apk` (untracked build output).
- Baseline reproduction: the original `build/CU-Denver-Equity-Kiosk.apk` has SHA-256 `37dd5190c673162e212da7c5b881c8ed06f5fde9a397349ac41ff8dac1befd34`. The artifact checker exited 1, reporting missing `com.example.webkiosk.kiosklauncher.LauncherActivity` and the expected Home declaration. On the test tablet, the existing installation produced `ClassNotFoundException` for that class after an explicit start; `am start -W` itself returned `Status: ok`, so the crash buffer was necessary to establish the failure.
- Built in a temporary copy with `C:\Program Files\Git\bin\bash.exe <temporary-copy>/build-apk.sh`, using Android SDK build-tools 36.0.0, platform android-37.0 and Android Studio JBR. The compiler and signer emitted warnings but the build succeeded. This avoids deleting the existing build directory.
- `C:/Users/cruzmars/AppData/Local/Python/pythoncore-3.14-64/python.exe -B -m unittest discover -s tests -v`: 3 tests passed using the configured Python 3.14 interpreter. `C:/Users/cruzmars/AppData/Local/Python/pythoncore-3.14-64/python.exe -B tools/check_apk_components.py build/CU-Denver-Equity-Kiosk-session1.apk --aapt2 C:/Users/cruzmars/AppData/Local/Android/Sdk/build-tools/36.0.0/aapt2.exe`: failed on the original APK as above and passed on the new APK, confirming all declared activity/receiver classes including Home and admin receiver. The checker reads the actual DEX class definitions, not references.
- New APK SHA-256: `0f15e0a20f1dc6a57016f43a0ee5769ceed7f9aa77f8cf682665f56202e3802e`. `java -jar <SDK>/build-tools/36.0.0/lib/apksigner.jar verify --print-certs <apk>` succeeded; SHA-256 certificate digest `CC:FB:B9:FE:8D:73:E3:7D:F1:36:19:75:C6:5D:FA:84:AB:1E:B7:BE:48:FC:31:C9:31:B6:39:0C:83:B6:D1:02`. This is the existing exposed debug identity; protected release signing is Session 4.
- All five shell scripts passed individual `bash -n` checks. `git diff --check` passed.
- The user confirmed the designated test tablet: Lenovo TB336FU, Android 16, ADB serial `HNY0HQ2P`. `adb -s HNY0HQ2P install -r build/CU-Denver-Equity-Kiosk-session1.apk` succeeded; the installed APK SHA-256 matched the rebuilt artifact. `adb -s HNY0HQ2P shell am start -W -n com.example.webkiosk/com.example.kiosklauncher.LauncherActivity` returned `Status: ok`, and `adb -s HNY0HQ2P shell cmd package set-home-activity com.example.webkiosk/com.example.kiosklauncher.LauncherActivity` succeeded. HOME resolution and the visible launcher UI identified the corrected component. Tapping the launcher button opened `MainActivity`, and Back returned to the visible launcher. The tablet has TestDPC as device owner and `mLockTaskModeState=NONE`; lock-task operation is not verified. After the user approved the system update and restart, `adb -s HNY0HQ2P reboot` succeeded. The tablet reconnected, reported `sys.boot_completed=1`, and its build fingerprint changed from `Lenovo/TB336FU/TB336FU:16/BP2A.250605.031.A3/251230_085:user/release-keys` to `Lenovo/TB336FU/TB336FU:16/BP2A.250605.031.A3/260404_193:user/release-keys`. After dismissing the lock screen, the corrected launcher appeared automatically with its Home button visible; HOME resolution still named the corrected component. The post-restart crash-buffer check found no kiosk class-loading crash. Android update_engine service was unavailable for a separate updater-status check; the updated build and successful boot were verified.
- Session 2 can use this artifact for testing on the designated tablet. A working explicit launch alone must not be treated as proof of provisioning or lock-task operation.

### Session 2 — November 11, 2026

- Status: **Code/artifact verified**; device acceptance remains pending. Branch `master`, baseline `97a7b97`, changes uncommitted; `git fetch origin` succeeded and `git rev-list --left-right --count HEAD...origin/master` reported `0 0`. Preserved Session 1 changes.
- Changed `app/src/main/AndroidManifest.xml`, `app/src/main/java/com/example/webkiosk/WifiSettingsActivity.java`, added `WifiInput.java` and `tests/WifiInputTest.java`, and included the helper in both manual APK build scripts. Android's network state permission is normal and has no runtime prompt. The separate existing nearby Wi-Fi/location prompt is retained; SSID access can still be redacted. Active Wi-Fi status is considered separately from SSID visibility. Missing services, denied access, invalid SSID/WPA2 input and suggestion builder/submission exceptions show a message. A submitted suggestion is not reported as a confirmed connection.
- Baseline device reproduction was not performed: `adb devices -l` returned no devices. The previous session identified Lenovo TB336FU, Android 16, serial `HNY0HQ2P`; this session did not verify that device or its current state.
- Built in an isolated temporary copy using `C:\Program Files\Git\bin\bash.exe <temporary-copy>/build-apk.sh`, Android SDK build-tools 36.0.0, platform android-37.0 and Android Studio JBR. `aapt2 dump permissions <apk>` showed `android.permission.ACCESS_NETWORK_STATE`. The retained test APK is `build/CU-Denver-Equity-Kiosk-session2.apk`, SHA-256 `11cee3693428966bbbeaa986737d8181f6f728dd6a5eb6fc2fb6ec39a737f3f5`; `apksigner verify --print-certs` succeeded with the existing exposed debug certificate SHA-256 `ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102`. This is not a release artifact; signing remediation is Session 4.
- Focused test: `javac -d <temporary-directory> app/src/main/java/com/example/webkiosk/WifiInput.java tests/WifiInputTest.java` followed by `java -cp <temporary-directory> com.example.webkiosk.WifiInputTest` passed, including empty and multibyte SSIDs, open and WPA2 passwords, length boundaries, and redacted SSIDs. The SDK-backed `tools/check_apk_components.py <apk> --aapt2 <SDK>/build-tools/36.0.0/aapt2.exe` passed. `python -B -m unittest discover -s tests -v` passed 3 existing tests. Both changed build scripts passed individual `bash -n`; `git diff --check` passed. Editor diagnostics could not resolve Android classes and generated `R` in this manual-build project, while the Android SDK build compiled successfully.
- Still required: reproduce baseline if practical; exercise Wi-Fi off/on/disconnected/connected, deny and grant permission, open and WPA2 test networks, invalid password, redacted SSID, approval and actual connectivity. Do not mark acceptance passed based on suggestion submission. Session 5 still depends on this device verification.
- Follow-up: the user connected the previously designated Lenovo TB336FU, serial `HNY0HQ2P`, Android 16. `adb -s HNY0HQ2P install -r build/CU-Denver-Equity-Kiosk-session2.apk` succeeded; `sha256sum` of the installed base APK matched `11cee3693428966bbbeaa986737d8181f6f728dd6a5eb6fc2fb6ec39a737f3f5`. `dumpsys package` showed `ACCESS_NETWORK_STATE` granted and both `NEARBY_WIFI_DEVICES` and `ACCESS_FINE_LOCATION` denied at the time of inspection. Wi-Fi was enabled. The device was at its lock screen, so the Wi-Fi UI and network acceptance cases remain pending; installation and permission inspection do not constitute acceptance.
