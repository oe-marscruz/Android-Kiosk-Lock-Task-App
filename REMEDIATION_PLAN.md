# Kiosk remediation plan: nine implementation sessions

- Prepared: November 11, 2026
- Reviewed baseline: `97a7b97`
- Repository: Android-Kiosk-Lock-Task-App
- Status: Session 1 device acceptance passed for the launcher; lock-task provisioning remains unverified. Session 2 code/artifact checks passed; device acceptance is pending. Session 3 navigation policy passed synthetic tablet tests; live Equity-to-Maxient acceptance is pending because the tablet has no active network. Session 4 signing code and disposable APK fixture checks passed; production key custody, fresh enrollment, updates and migration acceptance are pending. Session 6 timing code, host tests and APK builds passed; tablet lifecycle acceptance is pending. Session 7 reset code, host tests and APK builds passed; actual WebView isolation acceptance is pending. Session 9 code, host fixtures and Android APK checks passed on Windows; actual macOS build/DMG and tablet acceptance remain pending. Sessions 5 and 8 remain pending in this tracker.

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
| 3 | Navigation allowlist bypass | Only approved HTTPS hosts are accepted | Device verified with synthetic WebView pages | Pending live Equity-to-Maxient check: no active network |
| 4 | Exposed APK signing key | Protected release signing and a documented migration path | Code/artifact verified with disposable keys | Pending production key, fresh enrollment, update/rejection tests and migration |
| 5 | Setup disables required apps | Required apps remain available; restoration preserves prior state | Pending | Pending |
| 6 | Background time bypasses inactivity expiry | Expired sessions reset before content becomes visible | Code/artifact verified; 14 host timing checks passed | Pending designated-tablet lifecycle tests |
| 7 | Session reset retains history or cookies | Reset removes the prior browsing session before a new one starts | Code/artifact verified; 12 cleanup host checks passed | Pending designated-tablet isolation tests |
| 8 | Setup reports success after failure | Setup stops on failure and verifies the selected device | Pending | Pending |
| 9 | Incomplete macOS build and package | The APK includes its receiver and is bundled where the GUI expects it | Code/artifact verified on Windows; synthetic packaging checks passed | Pending real macOS build, relocated app/DMG and designated-tablet setup |

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

### Session 9 - November 13, 2026

- **Status: Code/artifact verified on Windows; real macOS and tablet acceptance pending.** Branch `codex/session-9-macos`, created from `codex/session-8-provisioning` at `73fbb46`. `git fetch --all --prune` succeeded after sandbox escalation; `git rev-list --left-right --count HEAD...origin/master` returned `2 0`. The inherited Session 3-8 working-tree edits, IDE files and APKs were preserved. This session made no commit, push, release publication or device changes.
- Baseline source reproduction: committed `build-apk-mac.sh` omitted `KioskDeviceAdminReceiver.java`; committed `package-mac.sh` lacked an APK bundle-data argument. Inherited Session 4 work had already corrected both through the shared compiler inventory and a bundle-data input. Those partial repairs were retained. The remaining inherited packaging path had no manifest/DEX gate and no check of the relocated frozen resources. No old-code macOS runtime reproduction was possible on this Windows host.
- [package-mac.sh](package-mac.sh) now stages a reviewed release input in its own ignored scratch directory, retains Session 4 certificate/version/signature verification, and invokes [the existing APK component checker](tools/check_apk_components.py) before installing Python build dependencies or freezing. It uses [pinned PyInstaller](requirements-macos-build.txt), a directory-based `.app`, an APK at the frozen resource root and ADB as a native binary. The shared build helper already includes the receiver and the same Java 11 settings for both build entry points; its source inventory was not duplicated.
- [bundle_resources.py](bundle_resources.py) supplies the GUI's resource paths and its `--check-bundle` command. Frozen mode uses only the bundled APK, independent of the source environment or working directory. The check requires nonempty bundled resources, permits PyInstaller's internal macOS Frameworks-to-Resources links, rejects resources resolving outside the bundle, checks APK structure/hash, and runs only `adb version` with a timeout. It writes a JSON report and fails with a nonzero status. It starts no GUI, ADB server, device discovery or provisioning. Direct source execution cannot pass as frozen acceptance.
- Packaging copies the `.app` outside the checkout and runs that command with the source APK and Python path environment removed, before adding the optional sibling manual APK and before DMG creation. Failure stops packaging. The sibling APK is copied from the same verified stage. The script saves resource/toolchain reports under `dist/macos-evidence/` and avoids the old fixed shared `/tmp/kiosk-dmg` directory. No real `.app` or DMG was created here.
- [The macOS workflow](.github/workflows/build-dmg.yml) retains the shared local packaging entry point and manual release inputs. It now prepares host regression tests, synthetic packaging tests, a clean development APK build/component check on the Mac runner, and evidence uploads. These workflow steps were **not dispatched or run** in this session. Python 3.12/JDK 17 and SDK platform 35/build-tools 36.0.0 are selected for CI; the actual Mac version and CPU architecture must come from a successful runner or local report.
- Host command: `.venv/Scripts/python.exe -B -m unittest discover -s tests -v`. Final result: **46 discovered, 44 passed, 2 skipped**. The 13 new resource cases cover bundled paths, missing/changed/corrupt resources, ADB error/timeout/unexpected output, JSON/CLI status, source rejection and internal/external symlinks. The two symlink cases skipped because Windows denied symbolic-link creation with `WinError 1314`; they remain unverified here. An initial test mock also intercepted Python's platform probing; the mock was isolated before the passing final run. Existing provisioning/package-policy tests remained green.
- Packaging command: `C:/Program Files/Git/bin/bash.exe tests/test_macos_packaging.sh`. Final result: **4 synthetic orchestration checks passed**: signature failure, missing-component failure and relocated-resource failure stop before DMG creation; a valid fixture executes signature -> component -> dependency -> freeze -> relocated-check -> DMG in order. Paths contain spaces, the relocated process has no source APK environment variable and no sibling APK directory. These use fake Mac/PyInstaller/signing tools, **not a real app or DMG**. Logs: `tmp/session9-packaging.vA3HHNXG` (a later final rerun may have another unique fixture directory). The initial host fixture lacked Mac's `shasum`; the synthetic toolset and stage-reached assertions were corrected before the passing run.
- Actual APK build: set `KIOSK_VERSION_CODE=9009`, `KIOSK_VERSION_NAME=0.0.0-session9`, then run `C:/Program Files/Git/bin/bash.exe build-apk-mac.sh development`. Build passed on Windows x64 using Android Studio JBR **25.0.4**, SDK platform **android-37.0**, build-tools **36.0.0**, with the existing Java/deprecation/native-access warnings. This exercises the Mac entry point and shared Android compiler path on Windows; it is **not a macOS build**.
- Artifact: [development-v9009.apk](build/development/CU-Denver-Equity-Kiosk-development-v9009.apk), SHA-256 **`93ea8ecdacd2d3438c042d41d10af34673552f37806eb52845e8fffc0b77fa62`**. `java -jar <SDK>/build-tools/36.0.0/lib/apksigner.jar verify --print-certs <apk>` passed, with development certificate SHA-256 **`998fadc6d1efe6da78ce155d73c2cb229af28a110882caaa4f07ae08db948161`**. This is a development test artifact, not an approved release or legacy-installation update.
- `.venv/Scripts/python.exe -B tools/check_apk_components.py build/development/CU-Denver-Equity-Kiosk-development-v9009.apk --aapt2 <SDK>/build-tools/36.0.0/aapt2.exe` passed for all declared activities/receiver, including Home and admin. `.venv/Scripts/python.exe -B tmp/session9-tests/check_artifacts.py` also passed: it verified the built APK, produced an unsigned component-only fixture with the receiver definition renamed in DEX and corrected DEX checksums, confirmed rejection naming the missing receiver, confirmed that source launch returns failure for frozen acceptance, and rechecked the original APK's unchanged SHA-256 **`37dd5190c673162e212da7c5b881c8ed06f5fde9a397349ac41ff8dac1befd34`**. The fixture is not a signature or installability test. SDK/JDK/interpreter access required normal-account escalation after sandbox denial.
- Final checks: each of `package-mac.sh`, `build-apk-mac.sh`, `build-apk.sh`, `tools/build-apk-common.sh`, `tools/android-toolchain.sh` and `tests/test_macos_packaging.sh` passed its own `bash -n`; `git diff --check` passed. Final Python/YAML editor diagnostics were clear. The final synthetic packaging rerun after adding the outside-checkout relocation guard passed all four cases, with logs in `tmp/session9-packaging.AGsCKuXe`.
- **Pending acceptance:** On a clean Mac with the intended architecture, Python 3.12/Tkinter, selected JDK/SDK and independently reviewed release inputs from [SIGNING.md](SIGNING.md), run the host tests and `bash build-apk-mac.sh development`, inspect its components, then run `bash package-mac.sh`. Review `dist/macos-evidence/` and require its resource report to say `PASS`. Mount the produced DMG, copy only the app to Applications or another directory outside the checkout, launch its GUI from an unrelated working directory, and confirm ADB/APK availability without a sibling APK. After confirming the current designated tablet and device-change authorization, exercise discovery, explicit serial selection and actual setup; inspect owner, Home, required packages and active lock task. Record macOS/CPU/JDK/SDK versions, release APK hash/certificate and results. Neither Intel nor Apple Silicon, Gatekeeper/GUI launch, real ADB discovery, signing migration, or device setup was certified here. Earlier sessions' acceptance status is unchanged.

### Session 1 — November 11, 2026

- Status: **Device verified**; launcher acceptance passed on the test tablet. Baseline `97a7b97`; the Session 1 source and checker are committed on `codex/session-2-wifi` in the follow-up commit after Session 2. Fetch of `origin` showed no newer commit at the time of testing.
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

### Session 3 - November 12, 2026

- Status: **Device verified** for the navigation policy using synthetic WebView pages; live-site acceptance remains pending as detailed in the tablet results below. Work is on `codex/session-3-navigation`, based on `73fbb46`, with Session 1/2 changes retained. `git fetch origin` succeeded; `git rev-list --left-right --count HEAD...origin/master` reported `2 0` before these edits. Session 3 changes are uncommitted. Existing IDE files and original/Session 1/Session 2 APKs were preserved; their APK hashes were compared before and after the isolated build.
- Added [NavigationPolicy.java](app/src/main/java/com/example/webkiosk/NavigationPolicy.java) and [NavigationPolicyTest.java](tests/NavigationPolicyTest.java). Updated [MainActivity.java](app/src/main/java/com/example/webkiosk/MainActivity.java), [LauncherActivity.java](app/src/main/java/com/example/kiosklauncher/LauncherActivity.java), [AndroidManifest.xml](app/src/main/AndroidManifest.xml), and both [Windows](build-apk.sh) and [macOS](build-apk-mac.sh) APK source lists. No unrelated session fixes were attempted.
- Policy: HTTPS only; normalized hostname must equal `ucdenver.edu` or `cm.maxient.com`, or end in a dot followed by either domain. Scheme/hostname case and a single terminal DNS dot are normalized. Missing/malformed hosts, credentials in authority, invalid ports, unsupported schemes, and look-alike suffixes are rejected. The approved domain list is unchanged.
- Applied the shared policy to both modern and legacy WebView override callbacks, initial/reset loads, Retry, history Back, main-frame request interception (including POST/app-initiated requests that may skip the override callback), and a page-start fallback. Denials display a fixed message without reflecting query strings. Retry validates before revealing a hidden page. The manifest disables cleartext; mixed-content blocking is retained. The launcher's app-initiated Chrome URL now uses the same checked Equity homepage instead of Google. Chrome's subsequent independent browsing is outside the WebView policy; browser-wide managed URL restrictions would require separate work.
- Baseline reproduction: a host-side fixture extracted the original approved-domain array, start URL and suffix predicate from `git show HEAD:app/src/main/java/com/example/webkiosk/MainActivity.java`. It used `java.net.URI` to supply hosts to the original predicate, so this was a predicate reproduction, not a full Android URI/WebView reproduction. Against the final 54-case suite it failed 15 cases, including `https://attackerucdenver.edu/` and `http://www.ucdenver.edu/`. The corrected policy passed all 54 cases, covering the plan's table plus credentials, malformed authorities, escapes, invalid ports, DNS-root dots, and the actual configured homepage.
- Host commands used Android Studio JBR at `C:/Program Files/Android/Android Studio/jbr/bin`: `javac -d tmp/session3-policy-tests app/src/main/java/com/example/webkiosk/NavigationPolicy.java tests/NavigationPolicyTest.java`, then `java -cp tmp/session3-policy-tests com.example.webkiosk.NavigationPolicyTest` (54 passed). The extracted baseline fixture was compiled to `tmp/session3-baseline` with the same test class and run with `java -cp tmp/session3-baseline com.example.webkiosk.NavigationPolicyTest` (expected exit 1; 15/54 failures). `WifiInputTest` also passed, and `C:/Users/cruzmars/AppData/Local/Python/pythoncore-3.14-64/python.exe -B -m unittest discover -s tests -v` passed all 3 existing tests. All five shell scripts passed individual Git Bash `-n` checks. `git diff --check` passed. Final editor diagnostics reported unresolved Android imports and generated `R` in the launcher; the SDK-backed manual build compiled it successfully. The other checked files had no reported editor diagnostics.
- Pre-device build: copied the app, Windows build script and existing development key into `C:/Users/cruzmars/AndroidStudioProjects/Android-Kiosk-Lock-Task-App/tmp/session3-final-9724ffe0d72547598c95ad01f5595db3`; ran `C:/Program Files/Git/bin/bash.exe C:/Users/cruzmars/AndroidStudioProjects/Android-Kiosk-Lock-Task-App/tmp/session3-final-9724ffe0d72547598c95ad01f5595db3/build-apk.sh`. This confines the build script's cleaning operation to the isolated copy. SDK build-tools `36.0.0`, platform `android-37.0`, and Android Studio JBR were used. Java/deprecated API and signer native-access warnings were emitted; the build succeeded. No macOS runtime build was performed.
- Pre-device artifact, subsequently replaced by the device-tested build below: [CU-Denver-Equity-Kiosk-session3.apk](build/CU-Denver-Equity-Kiosk-session3.apk), SHA-256 `1b86f4f1e53de799ad01edbe9da9f4f914615822c00c935adf4d94809d6a37a7`. `java -jar C:/Users/cruzmars/AppData/Local/Android/Sdk/build-tools/36.0.0/lib/apksigner.jar verify --print-certs build/CU-Denver-Equity-Kiosk-session3.apk` passed with the existing debug certificate SHA-256 `ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102`; protected release signing remains Session 4. `aapt2 dump xmltree --file AndroidManifest.xml build/CU-Denver-Equity-Kiosk-session3.apk` confirmed `usesCleartextTraffic=false`. `python -B tools/check_apk_components.py build/CU-Denver-Equity-Kiosk-session3.apk --aapt2 C:/Users/cruzmars/AppData/Local/Android/Sdk/build-tools/36.0.0/aapt2.exe` passed for all manifest components. The existing DEX reader also confirmed an actual `com.example.webkiosk.NavigationPolicy` class definition in the artifact.
- Initial device check: `C:/Users/cruzmars/AppData/Local/Android/Sdk/platform-tools/adb.exe devices -l` returned no devices. No Session 3 APK was installed and no device settings were changed. The previously designated Lenovo TB336FU / `HNY0HQ2P` must be confirmed connected and unlocked before device tests; its current OS/build was not verified in this session.
- At the initial handoff, still required for acceptance: exercise approved links and subdomains, visibly blocked look-alikes/unsupported schemes/HTTP, approved-to-disallowed redirects (including form/POST cases), the Equity-to-Maxient flow using synthetic data, initial/reset loads, Retry and Back in the actual WebView, and the launcher's approved Chrome start URL. Record any required service blocked by the current domains without broadening them. Host tests and an APK build do not establish these tablet results or minimum-SDK behavior.
- Session 7 must preserve the shared navigation helper, both callbacks, guarded load/history/retry paths, request/page-start guards, cleartext prohibition and mixed-content blocking when configuring any replacement WebView. Sessions 6/7 inactivity and session-isolation acceptance remain separate.

#### Session 3 device-test follow-up - November 12, 2026

- The user connected a tablet and authorized proceeding. `adb devices -l` identified a single authorized Lenovo TB336FU with serial `HNY0HQ1J`, which differs from the previously designated `HNY0HQ2P`. Device designation was requested before installation, as required by this plan; the user subsequently confirmed `HNY0HQ1J` and unlocked it. The results below supersede this preparation checkpoint. Read-only `adb -s HNY0HQ1J shell getprop` checks reported Android 16 and fingerprint `Lenovo/TB336FU/TB336FU:16/BP2A.250605.031.A3/260804_321:user/release-keys`. The current WebView is `com.google.android.webview` version `140.0.7339.207`. Keyguard reported `showing=true` and `inputRestricted=true`. `pm path com.example.webkiosk` returned no package path. No installation or tablet configuration change was performed during this inspection.
- Added the test-only [instrumentation manifest](tests/android/AndroidManifest.xml), [NavigationDeviceTest.java](tests/android/NavigationDeviceTest.java), and [PowerShell runner](tools/run_navigation_device_tests.ps1). Running `./tools/run_navigation_device_tests.ps1` built `tmp/navigation-device-tests/navigation-tests.apk` successfully using the installed SDK/JBR. The test APK contains the instrumentation and host-case test class; the navigation-policy implementation itself comes from the installed production APK, not from a test replacement. The production APK hash remains `1b86f4f1e53de799ad01edbe9da9f4f914615822c00c935adf4d94809d6a37a7`.
- The harness delegates navigation callbacks to the installed app's real WebViewClient and serves synthetic pages only after the production request policy permits them. Separate containment records a failure and prevents an unintended external request if production fails to block a synthetic destination. Coverage is prepared for the 54 policy cases on the Android runtime, approved/blocked links, JavaScript/meta redirects, approved/disallowed synthetic POSTs, the production Retry/Back/reset paths, the legacy callback, and the visible block Toast. It uses accessibility automation without suppressing existing accessibility services. At this preparation checkpoint these device checks had been built but had **not run**; subsequent results are recorded below.
- After designation and unlocking, run `./tools/run_navigation_device_tests.ps1 -Serial HNY0HQ1J -Run -LiveFlow`. This installs the already-verified Session 3 APK and a separate test-only APK, runs instrumentation, and records output in `tmp/navigation-device-tests/results.txt`. `-LiveFlow` additionally follows public approved Equity/report links toward Maxient using GET navigation only; it does not submit a report. Synthetic fixture results and the live-flow result are reported separately. If another tablet is designated, substitute its confirmed serial explicitly. Confirm the instrumentation result and the live-flow outcome before changing acceptance status; a built harness is not a passed device test.

#### Session 3 tablet results - November 12-13, 2026

- Device: user-confirmed Lenovo TB336FU, serial `HNY0HQ1J`, Android 16, fingerprint `Lenovo/TB336FU/TB336FU:16/BP2A.250605.031.A3/260804_321:user/release-keys`, Android System WebView `140.0.7339.207`. The user confirmed the different serial and unlocked the device before installation. No Home selection, device-owner provisioning, restart, lock-setting change, or report submission was performed.
- The first Android run reproduced one desktop/runtime discrepancy: `https://bad_label.ucdenver.edu/` was rejected by the desktop URI parser but accepted by Android's parser. [NavigationPolicy.java](app/src/main/java/com/example/webkiosk/NavigationPolicy.java) now validates DNS labels explicitly: ASCII letters/digits/hyphens, nonempty labels, no leading/trailing hyphen, at most 63 characters per label and 253 per normalized hostname. [NavigationPolicyTest.java](tests/NavigationPolicyTest.java) now has **61 cases**, including hostname/label length boundaries. All 61 passed both the selected desktop JBR and the installed app's Android runtime. The instrumentation APK does not package a replacement navigation policy.
- The Back test initially assumed every Back operation selects the immediately adjacent entry. Actual traces showed WebView skipping a programmatically visited fixture and reaching the earlier, disallowed POST error entry; the app correctly hid that content. This is consistent with Chromium's [history-skipping implementation](https://chromium.googlesource.com/chromium/src/+/9f1690722a709f5d70fcde00e05c36076614215e/content/browser/renderer_host/navigation_controller_impl.cc). Trying the native offset API did not change this behavior, so that ineffective production change was removed. The final harness separately verifies denied skipped-history content and normal Back after an actual touch on a rendered link. Production Back retains the shared policy precheck and page-start guard.
- Final instrumented run: `./tools/run_navigation_device_tests.ps1 -Serial HNY0HQ1J -Run -LiveFlow` reported `session3_status=PASS`, `session3_checks=21`, and `INSTRUMENTATION_CODE: -1`. Those 21 grouped checks include all 61 Android policy inputs; allowed root/subdomain links for both approved domains; blocked look-alikes, suffix attacks, credentials-to-attacker and HTTP; blocked JavaScript and meta-refresh redirects; allowed/blocked synthetic POSTs; Retry keeping a denied page hidden; blocked skipped-history content; touch-driven approved Back; approved Retry; reset to the approved configured homepage; the legacy callback's HTTP rejection; and a `Navigation blocked` Toast observed through an accessibility event. The test containment counter remained zero: it did not have to compensate for an unsafe production decision.
- The harness delegates the installed app's callbacks and serves self-contained synthetic pages after production approval, so no synthetic POST marker is submitted to a real institution or attacker site. The app's original WebViewClient and original screen-awake flag are restored after instrumentation. The runner wakes the test screen and asks Android to dismiss the keyguard if permitted; it does not disable authentication or change persistent screen-lock settings. Native network/server redirects were not exercised by these synthetic JavaScript/meta tests. This Android 16 exercise does not certify the minimum SDK or an older WebView.
- Final test APK: [CU-Denver-Equity-Kiosk-session3.apk](build/CU-Denver-Equity-Kiosk-session3.apk), SHA-256 **`94747b52f7c9751aeb28302ec359b0e02b49d9cbf65d68c9b5c74ee5a53583c0`**. Built with the existing manual Windows path in `tmp/session3-device-8c6a74536da2494c95bfe04f403020ae`, SDK build-tools 36.0.0, platform android-37.0 and Android Studio JBR. Before reusing that build, every app file was compared byte-for-byte with the isolated source copy. `adb -s HNY0HQ1J shell pm path com.example.webkiosk` followed by `adb -s HNY0HQ1J shell sha256sum <returned-base.apk-path>` confirmed the installed APK has the same hash. `apksigner verify --print-certs` passed, with the existing debug certificate SHA-256 `ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102`. This remains a development test build; release signing is Session 4. The APK component checker passed for all declared activities and the admin receiver. The editor still cannot resolve the Android classpath in activity files; the SDK-backed APK and instrumentation builds compile successfully.
- **Remaining operational blocker:** the live phase returned `session3_live_status=PENDING_LOAD_ERROR_-2`, with `https://www.ucdenver.edu/offices/equity` showing `Webpage not available`. Read-only diagnostics showed `Active default network: none`, Wi-Fi enabled, airplane mode `0`, and `ping: unknown host` for both `www.ucdenver.edu` and `cm.maxient.com`. The workstation independently resolved `www.ucdenver.edu` to `192.133.11.1`; this tablet failure was not an allowlist denial. The user was asked to connect the tablet to an Internet-enabled Wi-Fi network. No network password was requested/read and no allowlist expansion was made.
- Acceptance remains pending for the live Equity-to-Maxient flow and any additional required real-service redirects. Chrome is installed, and its app-initiated URL is guarded in source, but the actual launcher-to-Chrome start was not exercised while the user may be connecting Wi-Fi. After connectivity is available, rerun the command above, verify the live phase reaches Maxient without submitting a report, and verify the launcher's approved Chrome destination. Keep the synthetic result separate from those live results. Raw instrumentation output is at `tmp/navigation-device-tests/results.txt`; this entry preserves its substantive outcome if scratch output is removed. Session 6/7 lifecycle and data-isolation acceptance remain separate.
- Cleanup: `adb -s HNY0HQ1J uninstall com.example.webkiosk.navigationtests` returned `Success`; subsequent `pm path` checks confirmed the test-only package was removed and the kiosk package remains installed. The runner reinstalls its test APK when live testing resumes. A final network check still reported `Active default network: none`.

### Session 4 - November 13, 2026

- Status: **Code/artifact verified with disposable signing fixtures; operational acceptance pending.** Work is uncommitted on `codex/session-4-signing`, branched from `73fbb46` while preserving the existing Session 3 edits, IDE files and prior APKs. `git fetch origin` succeeded; the remote default is `origin/master`, and `git rev-list --left-right --count HEAD...origin/master` reported `2 0`. No remote branch was pushed, CI workflow executed, release published, or tablet modified.
- Confirmed the finding using actual public certificates: exporting the public certificate from the removed root `debug.keystore` and hashing its DER bytes gave `ccfbb9fe8d73e37df1361975c65dfa84ab1eb7be48fc31c931b6390c83b6d102`. `apksigner verify --print-certs build/CU-Denver-Equity-Kiosk.apk` and the tablet's pulled installed APK reported that same fingerprint. The baseline tracked APK remains byte-for-byte unchanged with SHA-256 `37dd5190c673162e212da7c5b881c8ed06f5fde9a397349ac41ff8dac1befd34`; it is historical evidence, not an approved release.
- Read-only device inventory: `adb devices -l` reported Lenovo TB336FU `HNY0HQ1J`; `adb -s HNY0HQ1J shell getprop ro.build.version.release` reported Android 16. `adb -s HNY0HQ1J shell pm path com.example.webkiosk` located the installed APK; `adb -s HNY0HQ1J pull <returned-base.apk-path> tmp/session4-inventory/installed.apk` copied only that application binary for certificate/hash inspection. Its SHA-256 is `94747b52f7c9751aeb28302ec359b0e02b49d9cbf65d68c9b5c74ee5a53583c0`, matching Session 3. `adb -s HNY0HQ1J shell dpm list-owners` showed TestDPC (`com.afwsamples.testdpc/.DeviceAdminReceiver`) as device owner. No install, uninstall, enrollment, Home change, reset, reboot, network configuration or report submission occurred. Fleet signing identities remain uninventoried.
- [Both](build-apk.sh) [builders](build-apk-mac.sh) now use [one APK build path](tools/build-apk-common.sh), [tool discovery](tools/android-toolchain.sh), and [signing policy](tools/signing.sh). Development generates a new ignored `.local-signing/development.p12` identity and debuggable APKs under `build/development/`. Release requires an external key, alias, password-file inputs, an independently approved SHA-256 certificate pin, explicit version code/name, and a supplied prior code. It fails without these inputs and rejects the exposed fingerprint; no legacy-key fallback exists. The release output is promoted only after verification. Passwords use file inputs, and shell tracing is disabled. OS ACLs, key backup and custody still require operational setup.
- Release metadata is supplied to `aapt2`; codes must be 1-2100000000 and exceed the prior deployed value. Version names compare literally, including dots. The prior code comes from the operator's release ledger; there is no claim that the script independently discovers the fleet maximum. Unique intermediates under `tmp/` replace recursive cleaning of the entire build directory, preserving previous session artifacts. A failed rebuild can leave an older verified final output; check exit status and hash before use.
- [Release verification](tools/verify-release-apk.sh) checks the actual APK signature, exactly one signer, the pinned certificate, package `com.example.webkiosk`, expected version and absence of the debuggable flag. Development and exposed identities are forbidden. [Windows packaging](package-win.sh) and [Mac packaging](package-mac.sh) now require `KIOSK_RELEASE_APK`, stage and verify it before Python installation/bundling, and consume those staged bytes. They no longer build another APK or select the repository binary. The Mac frozen-app APK inclusion and receiver source list are shared prerequisites for this release path; actual Mac packaging remains Session 9 acceptance.
- Both [Windows](.github/workflows/build-exe.yml) and [Mac](.github/workflows/build-dmg.yml) workflows now use manual dispatch, an HTTPS reviewed-APK URL, approved version inputs, and the `KIOSK_RELEASE_CERT_SHA256` variable from the named `release` environment. They verify the APK before packaging, upload only desktop artifacts, and have read-only repository permissions. Automatic publication of the historical APK has been removed. Required reviewers/branch restrictions and the approved environment variable have **not** been configured by this session; merely naming the environment in YAML does not establish protection. Existing published binaries have not been withdrawn.
- Deleted the exposed root key from the working tree and added ignore rules for signing keys/password files and generated development/release APKs. Historical Git copies and pre-existing ignored Session 3 scratch copies remain compromised; deleting the current key does not revoke them. Updated the [navigation test runner](tools/run_navigation_device_tests.ps1) to require explicit target APK and matching test-signing inputs instead of the removed key. Its old command in Session 3 evidence is superseded. The modified runner was syntax/diagnostic checked but not run against the tablet. Use a disposable development identity for future instrumentation; do not hand production credentials to a test job.
- Added [SIGNING.md](SIGNING.md) with build/verification/packaging commands, key-custody requirements, CI configuration, an empty production release ledger, device-owner-aware migration and recovery steps, and separate acceptance gates. Updated [README.md](README.md) to remove obsolete automatic-release and unverified manual-packaging instructions. The migration proposal for legacy kiosk-owned devices is separately approved reset/re-enrollment, rehearsed on a disposable enrolled device. The inventoried TestDPC ownership must be reviewed with its management owner. Uninstalling an active owner, signing lineage, or simply producing a newly signed APK is not accepted proof of migration.
- Test command: `C:/Program Files/Git/bin/bash.exe tests/test_signing.sh C:/Users/cruzmars/AppData/Local/Temp/vscode-agent-codex-sandbox-5j7vyV`. Final run passed **27 signing checks** in [the SDK-backed harness](tests/test_signing.sh), with summarized results at `tmp/session4-tests/results.txt`. It built a real development APK and real fixture releases through both entry points on Windows. It exercised missing key/password/configuration, exposed/wrong certificates, distinct development signing, wrong passwords at the signer, unsigned/tampered APKs, literal version-name checks, missing/reused/decreasing version codes, checkout-contained credential rejection, and both packagers refusing development/missing inputs. It tested both shared and distinct password files and found no fixture password in captured build/test logs. The tests caught and corrected Windows `file:` path conversion and `apksigner`'s sequential reading when two password options name the same file.
- Final **disposable** certificate SHA-256: `ac106c578dbe4dc136f65326701707d770103bed0000b50b6ca27f7ad3525f72`. Fixture outputs (ignored, not production releases): `build/release/CU-Denver-Equity-Kiosk-release-v100.apk`, version `100` / `1.0.0-fixture`, SHA-256 `4d0b5f4ab5a94c9b54955a13d1baaaa79998006c58cf2edfa6ffdc6d3ec60551`; and `build/release/CU-Denver-Equity-Kiosk-release-v101.apk`, version `101` / `1.0.1-fixture`, SHA-256 `19ef514acb54147af2368931419babe5dd1c9deeaba5cd764fb9a154d4615854`. Both verify against that fixture pin and have increasing metadata; this does **not** prove an installed-device update. Disposable two-day keys/passwords are outside the checkout at `C:/Users/cruzmars/AppData/Local/Temp/vscode-agent-codex-sandbox-5j7vyV/kiosk-signing-tests.qmspwQl6`. They must not be adopted for production. No production identity was generated or approved.
- Build tools: Git Bash, Android Studio JBR, Android SDK build-tools 36.0.0 and platform android-37.0. Builds emitted the existing Java/deprecation/native-access warnings and completed. The Python component checker verified every manifest activity and admin receiver in both built fixture APKs. The configured Python 3.14.6 standard-library test suite passed all 3 existing tests. Each of the five top-level shell scripts and five new shell scripts passed its own `bash -n` check. Both workflow YAML files parsed successfully; assertions confirmed manual dispatch, the `release` environment and read-only permissions. Editor diagnostics reported no errors for the workflows and changed PowerShell runner. `git diff --check` passed.
- A scan of 41 tracked/nonignored source files found no private-key files or PEM private-key blocks; both fixture APK ZIPs contained no key/password files. Captured fixture build/test logs contained no fixture password. No desktop bundles or production signing logs were generated, so they were not scanned. Baseline and Session 1/2/3 APK hashes were compared before/after and remained unchanged. The tracked baseline APK SHA-256 is `37dd5190c673162e212da7c5b881c8ed06f5fde9a397349ac41ff8dac1befd34`.
- **Still required for Session 4 acceptance:** an approved protected production key and recoverable backup; independent certificate pin approval and CI environment controls; an actual protected-key release; fresh kiosk device-owner enrollment on an explicitly designated disposable device; a higher-code same-new-key update; rejection of a higher-code APK signed with the exposed old key while preserving the new installation/ownership; disposable legacy-owner migration and recovery rehearsal; and separate fleet authorization/scheduling. Real Windows/macOS desktop packaging and GitHub workflow execution remain unverified. This session provides code and fixture evidence only and does not complete fleet migration or other sessions' tablet acceptance.

### Session 6 - November 13, 2026

- **Status: Code and artifacts verified; tablet lifecycle acceptance pending.** Branch: `codex/session-6-inactivity`, created from the existing `codex/session-5-preserve-apps` working tree at `73fbb46`. All work remains uncommitted, including inherited Session 3-5 changes. Earlier edits and generated artifacts were preserved. `git fetch origin` succeeded after sandbox escalation; `git rev-list --left-right --count HEAD...origin/master` reported `2 0`. No changes were pushed.
- Confirmed the timing defect in the existing activity: pause removed the timeout callback, and resume posted a new full 180000 ms interval regardless of prior inactivity. [InactivityDeadline.java](app/src/main/java/com/example/webkiosk/InactivityDeadline.java) now tracks activity with an injectable monotonic clock. Production uses `SystemClock.elapsedRealtime()`, which includes device sleep; the production timeout remains **180000 ms**. Lifecycle and page callbacks do not record user interaction. Resume schedules the remaining interval, and input arriving at/after expiry cannot revive the old session. A backwards clock discontinuity fails closed.
- [MainActivity.java](app/src/main/java/com/example/webkiosk/MainActivity.java) covers, disables and removes WebView content from accessibility while paused or resetting. Resume checks the deadline before resuming expired content, and touch/key/generic-motion/trackball dispatch checks it before forwarding input. Timeout callbacks recheck the deadline, and scheduling removes prior callbacks. Old callbacks are ignored after WebView replacement or destruction.
- Fresh activity creation, including process restart/recreation/reboot, starts a cleared session and does not restore WebView state or trust a previous process's elapsed-clock timestamp. To keep old content covered through reset, the timing path waits for cookie deletion, discards the old WebView, recreates it with the existing navigation/settings configuration, and reveals the replacement after a permitted page finishes or a native load-error screen is ready. Cleanup failure keeps the cover in place. A completed fresh load starts the next session deadline. These supporting reset changes are necessary for the Session 6 visibility guarantee; **they do not establish Session 7 acceptance**. Session 7 must still verify history, cookies/storage, explicit exit, errors and concurrent reset behavior. The explicit-exit and destruction paths still need Session 7 review.
- [InactivityDeadlineTest.java](tests/InactivityDeadlineTest.java) passed **14 checks** covering foreground boundaries, exact expiry, expired input, prolonged background time, genuine interaction, remaining-time scheduling inputs, new-session initialization and clock regression. Command: compile it and the production deadline with the installed Android Studio JBR into `tmp/session6-tests`, then run `java -cp tmp/session6-tests com.example.webkiosk.InactivityDeadlineTest`. Regression checks passed: **61 navigation policy cases**, the existing Wi-Fi input/SSID tests, and **9 Python unittest cases** using the configured Python 3.14.6 environment. `python -m unittest discover -s tests -v` passed. The actual executable is `.venv/Scripts/python.exe`, selected through the environment tools.
- Build commands: `C:/Program Files/Git/bin/bash.exe build-apk.sh development` and `./tools/run_inactivity_device_tests.ps1` (without `-Run`). The shared manual builder now includes the deadline class. Final development APK: [CU-Denver-Equity-Kiosk-session6.apk](build/development/CU-Denver-Equity-Kiosk-session6.apk), SHA-256 **`f7176d2a80cb31540e0c05619defc323fc3b05ae681455c7fe735032e31751ed`**. This is a development artifact, not a production release or an authorized update to a legacy-signed installation. SDK build-tools 36.0.0, platform android-37.0 and Android Studio JBR compiled it successfully. The APK component checker verified every activity and admin receiver; DEX inspection confirmed the deadline and activity classes; signature verification passed with the independent development identity `998fadc6d1efe6da78ce155d73c2cb229af28a110882caaa4f07ae08db948161`.
- Added the [test-only manifest](tests/android/Session6Manifest.xml), [lifecycle instrumentation](tests/android/InactivityDeviceTest.java), [fixture builder](tests/build_session6_fixtures.sh) and [PowerShell runner](tools/run_inactivity_device_tests.ps1). The builder compiles current production Java sources into `com.example.webkiosk.session6fixture`, with test-only labeling and no Home category, plus instrumentation in `com.example.webkiosk.session6tests`. These can coexist with the installed kiosk and do not require uninstalling it or adopting its compromised signing identity. Both APKs compiled and passed signature/package/DEX checks. Final build directory: `tmp/session6-fixture.2Qvu3TZT`; fixture SHA-256 `97194c4d79fc3ecc2da022d7f0ed5c2e42df57251e5b4b1502683aad342b8805`; instrumentation SHA-256 `7a24e10bc5bcbefd2f19885473015960366c491de64e402bea29d1241a2e7f16`. The instrumentation APK contains tests rather than replacement production classes. These are **built but unrun** tests.
- Prepared instrumentation covers a synthetic form, unchanged interaction time across direct pause/resume, genuine input, near-expiry resume, expiry on resume/foreground callback/key input, one WebView replacement despite repeated input, actual background return through the fixture's Wi-Fi activity, activity recreation, and a separately restarted fixture process with a locally seeded synthetic cookie. Timing scenarios age the in-memory interaction timestamp while retaining the production timeout. Optional `-ScreenOff` adds a real 181-second screen-off interval. Synthetic HTML uses `loadDataWithBaseURL` and the installed fixture's production WebViewClient. It does not submit a report. Public homepage GETs may occur before the fixture replaces the document. The screen-off helper preserves existing accessibility services and does not change lock settings. These prepared cases require execution and may need test-harness corrections based on actual device behavior.
- Updated the existing [navigation instrumentation](tests/android/NavigationDeviceTest.java) to observe the current WebView after reset, retain each original client as its own delegate, and wait for fresh-session initialization. This maintains the navigation harness's intended use with the new lifecycle implementation; its updated Java compiled against the Android SDK, but its device suite was **not rerun**. The existing Windows navigation runner still requires explicit matching signing inputs from Session 4.
- Validation: both changed shell helpers passed individual `bash -n` checks; the new PowerShell runner passed parser checks and ran successfully in build-only mode; `git diff --check` passed with the repository's normal CRLF handling. An exploratory `core.autocrlf=false` override treated existing CRLF files as whitespace errors; unrelated line endings were preserved. Editor diagnostics still report the manual project's missing Android classpath/generated `R` in the activity; SDK-backed production and instrumentation compilation succeeded. Existing Java/deprecation/native-access build warnings remain.
- Read-only `adb devices -l` identified one authorized Lenovo TB336FU, serial **`HNY0HQ1J`**. Current designation and permission for installations/screen-off/process-restart tests were requested and remain pending at this checkpoint. No APK was installed, application stopped, device restarted, Home changed or device policy modified during this session. An initial sandbox ADB failure was resolved through normal-account escalation, which started the workstation's ADB daemon for the inventory.
- **Next step after designation/authorization:** unlock the tablet and run `./tools/run_inactivity_device_tests.ps1 -Serial HNY0HQ1J -Run -ScreenOff`. This installs only the two separate test packages, exercises lifecycle cases and a 181-second screen-off interval, then force-stops/restarts only the isolated fixture for the restart phase. It writes `tmp/session6-tests/device-results.txt` and `tmp/session6-tests/restart-results.txt`; require `session6_status=PASS` in both and review all results before changing the tracker. A signature/install failure must be reported without uninstalling the installed kiosk. Remove only these test packages after approved testing using `adb -s HNY0HQ1J uninstall com.example.webkiosk.session6tests` and `adb -s HNY0HQ1J uninstall com.example.webkiosk.session6fixture`. Full Session 6 tablet acceptance, real scheduled foreground expiry, repeat-reset behavior under load and minimum-SDK/older-WebView behavior remain unverified. Session 7 data-isolation acceptance remains separate.

### Session 7 - November 13, 2026

- **Status: Code, host tests and built artifacts verified; tablet isolation acceptance pending.** Branch: `codex/session-7-session-reset`, created from the existing Session 6 working tree at `73fbb46`. Inherited Session 3-6 edits, generated APKs and IDE files were preserved. `git fetch origin` succeeded with sandbox escalation, and `git rev-list --left-right --count HEAD...origin/master` returned `2 0`. All implementation work remains uncommitted; nothing was pushed.
- Static reproduction against the inherited activity confirmed that explicit exit invoked asynchronous cookie deletion and immediately launched Home, leaving the old activity available. Destruction independently invoked global deletion, which could race a replacement activity. The earlier timeout path waited for cookie removal but retained its old renderer until that callback. No old-code tablet reproduction was performed in this session.
- [MainActivity.java](app/src/main/java/com/example/webkiosk/MainActivity.java) now routes fresh creation, timeout and explicit exit through one reset path. It covers/disables the old content, blocks its network access, disables JavaScript, stops navigation, clears cache/history/form data/SSL decisions, removes the WebView from its parent and destroys it **before** shared-store cleanup starts. The blank replacement has state saving disabled and cannot load the homepage until cleanup completes. Its client rejects retired-view requests and callbacks. The existing HTTPS navigation policy and WebView security settings are reapplied to each replacement.
- [SessionCleanup.java](app/src/main/java/com/example/webkiosk/SessionCleanup.java) serializes process-wide asynchronous cleanup across activity recreation. Superseded/cancelled owners cannot load content; duplicate completions are ignored. A queued latest request waits for the previous cleanup to finish and then performs its own cleanup. Synchronous cleanup failure never opens content. Repeated timeout reset requests are coalesced. Explicit exit can supersede a pending reset and waits for cleanup before its Home transition and `finish()`.
- Cleanup suspends cookie acceptance, clears the WebView database's form and HTTP-auth/username/password stores, requests WebStorage deletion, waits for cookie deletion, flushes it, verifies no cookies remain, and waits for an empty WebStorage origins result before opening content. Cookie acceptance resumes only for the new browsing session. `removeAllCookies` returning false is not treated as failure if the cookie store is empty. Cleanup failure, missing completion, or a nonempty store leaves the activity covered; there is no fallback that reveals old content. A missing asynchronous completion currently requires process restart to retry. These API calls and guards are implementation evidence, **not proof of deletion on an actual WebView provider**. Service-worker/CacheStorage/IndexedDB behavior and in-flight renderer writes still require provider-specific device assessment before declaring full storage isolation.
- Destruction cancels that activity's completion and retires its view; it does not issue global cookie/storage deletion that could erase a newer activity's session. Fresh process/activity initialization always clears before its first app-controlled navigation and never restores old WebView state. The manifest makes MainActivity `singleTask` to avoid parallel live browsing activities sharing one cookie jar; a new launch intent starts a fresh reset. Lock-task/Home interactions with this launch mode remain a tablet acceptance item.
- Replacement-load completion clears history after navigation. Main-frame network/HTTP failures select the native error view; the API 21-22 legacy network-error callback is retained. Retry loads the approved homepage, including when a failed page has no usable URL. Destruction and stale callbacks cannot reopen the old form. Older Android/WebView behavior is unverified.
- Host command: `C:/Program Files/Git/bin/bash.exe tests/run_session7_host_tests.sh`. Passed **12 cleanup checks**, **14 inactivity timing checks**, **61 navigation-policy cases**, and the existing Wi-Fi input/SSID tests. Cleanup cases cover delayed completion, no overlapping global cleanup, latest-request selection, duplicate/stale callbacks, destroyed-owner cancellation, failure remaining closed, subsequent recovery and reentrant requests. Python regression command: `.venv/Scripts/python.exe -m unittest discover -s tests -v`; all **9 tests passed**. The configured environment is Python 3.14.6. Both test commands required normal-account escalation because the sandbox could not read the installed SDK/interpreter.
- Build commands: `C:/Program Files/Git/bin/bash.exe build-apk.sh development` and `./tools/run_session_reset_device_tests.ps1` (build-only, without `-Run`). Both completed with SDK build-tools 36.0.0, platform android-37.0 and Android Studio JBR. Existing Java/deprecation/native-access warnings remain. An initial instrumentation compile failure from attempting to construct the SDK's nonpublic `WebResourceError` was corrected; the callback fixture passes an unused error argument instead. The final instrumented sources compiled successfully.
- Development artifact: [CU-Denver-Equity-Kiosk-session7.apk](build/development/CU-Denver-Equity-Kiosk-session7.apk), identical to the final development-v1 output, SHA-256 **`256acae7e5de9276612e4e54918f08dd25091c188fca59ae2e6f27c0bffb9284`**. Signature verification passed with the existing development certificate **`998fadc6d1efe6da78ce155d73c2cb229af28a110882caaa4f07ae08db948161`**, distinct from the exposed legacy certificate. This is not a protected-key production release or an authorized update to the legacy-signed kiosk.
- [SessionResetDeviceTest.java](tests/android/SessionResetDeviceTest.java), [Session7Manifest.xml](tests/android/Session7Manifest.xml), [fixture builder](tests/build_session7_fixtures.sh), and [PowerShell runner](tools/run_session_reset_device_tests.ps1) prepare separate test-only packages `com.example.webkiosk.session7fixture` and `com.example.webkiosk.session7tests`. The fixture compiles current production sources under a separate manifest identity, has backup disabled and no Home category. The instrumentation APK contains test classes, not substitute production classes. It seeds a synthetic form, persistent/HttpOnly cookies, local/session storage and multiple history entries. Prepared cases exercise timeout reset, delayed completion in the shared cleanup queue, repeated resets, retired callbacks/requests, Back history, fixture-visible cookies/storage, failed-homepage callbacks/retry, activity recreation during cleanup, explicit exit and process restart. The native failure case injects a main-frame error callback; it does not establish actual offline networking behavior. The Home intent is intercepted by an instrumentation monitor to avoid launching an unrelated Home activity. Synthetic pages retain the production WebViewClient and allowlist. Public homepage GETs may occur before the fixture replaces the document; no real reports are entered or submitted.
- Final fixture directory: `tmp/session7-fixture.Ii8hpg6k`. Fixture APK SHA-256 **`0f47acf5b531cedbbaeb33226a301a5d5082c24d1a972fbeffe90ad6fb428e0d`**; instrumentation APK SHA-256 **`55b1ad66a6ec6aa50136cad91cab5e44892522912de1397c5ac863d141619caa`**. Both signatures verified against the same development identity. Packaged-manifest and DEX inspection confirmed the expected package identities, all activity/receiver classes, cleanup/deadline/policy classes, instrumentation target, `singleTask`, test-only fixture flag and absent fixture Home category. Inspection results are in `tmp/session7-tests/artifact-results.json`; the scratch verifier is `tmp/verify_session7.py`. Its initial launch-mode assertion assumed a different aapt2 output format; direct manifest inspection established `launchMode=2`, and the corrected final verifier passed.
- Each changed/new shell script passed its own `bash -n` check. The PowerShell runner passed parser checks and completed in build-only mode. `git diff --check` passed. Editor diagnostics still report the manual project's missing Android SDK/generated-R classpath in MainActivity; SDK-backed compilation of production and instrumentation sources succeeded. The cleanup helper, instrumentation source and PowerShell runner had no editor diagnostics. The preserved baseline APK hash remains `37dd5190c673162e212da7c5b881c8ed06f5fde9a397349ac41ff8dac1befd34`, and the preserved Session 6 snapshot remains `f7176d2a80cb31540e0c05619defc323fc3b05ae681455c7fe735032e31751ed`, matching their earlier recorded values.
- **Not run:** actual WebView device tests, actual offline/HTTP-error navigation, real Home/lock-task exit, live Equity-to-Maxient behavior, process-restart storage acceptance, or older Android/provider tests. Confirmation was requested to designate Lenovo TB336FU serial `HNY0HQ1J` for installation, fixture recreation/exit and fixture-only process restart. That authorization remains pending. This session ran no ADB commands and installed/stopped/reconfigured no device applications. Session 7 acceptance remains pending, and earlier sessions' acceptance status is unchanged.
- **Next step after confirming the current device and authorization:** unlock the test tablet and run `./tools/run_session_reset_device_tests.ps1 -Serial HNY0HQ1J -Run`. This builds and installs only the separate test packages, runs isolation checks, force-stops only the fixture, and runs the restart phase. Require `INSTRUMENTATION_RESULT: session7_status=PASS` in both `tmp/session7-tests/isolation-results.txt` and `tmp/session7-tests/restart-results.txt`, then inspect every result. These are prepared, unrun tests and may need harness corrections based on device behavior. Report signature/install failures without uninstalling the installed kiosk. After authorized testing, remove only the test packages using `adb -s HNY0HQ1J uninstall com.example.webkiosk.session7tests` and `adb -s HNY0HQ1J uninstall com.example.webkiosk.session7fixture`. Verify real network failures and Home/lock-task behavior separately before marking acceptance passed.
