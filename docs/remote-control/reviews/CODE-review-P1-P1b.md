# Code review: P1 + P1b (GPT-6.2-sol, high). Verdict: FAIL

Scope: `b73fb49` against `c9cfde6`. Checks run: 28 unit tests, actionlint, and an offline assembleDebug. The reviewer also compared badging, the manifests and the signers. Fixes are delegated to Terra (finding Kn → fixes in code).

1. **Blocker: release signing doesn't require the approved fingerprint.**
   - `app/build.gradle.kts:56` checks the fingerprint only when one is supplied, and only through assembleRelease.
   - Fix: before every release packaging or signing task, validate the keystore alias cert against a mandatory, well-formed pin.
   - Keep the check on the final APK. A missing pin must be a classifier error.
2. **Blocker: signing secrets are reachable outside the trust boundary.**
   - A same-repo PR can modify the workflows.
   - Both `workflow_dispatch` paths pass signing secrets to whatever ref is selected.
   - Fix: move the Android and Windows credentials into protected environments restricted to approved refs.
   - Make dispatch debug-only.
   - Write secrets to unique, restricted temp paths, and clean them up on failure.
3. **Blocker: the Gradle migration breaks updates for tablets signed with the retained `local_debug.keystore`.**
   - Fix: reuse an existing legacy local key for local debug builds. PR builds stay on fresh debug keys.
   - Verify `adb install -r` on a fixture whose signer matches.
4. **Blocker: batch setup can continue after a failed build or install.**
   - Fix: stop when the build exits nonzero.
   - Capture adb's exit code.
   - Match the output with an exact line, `findstr /x /c:"Success"`, and use a per-run log.
   - Apply the same exact-line check in Python.
5. **Blocker: package verification can accept APK copies it never inspected.**
   - Duplicate names collapse in the PyInstaller TOC dict.
   - The DMG check skips archives it can't parse, and a symlinked `Kiosk-APK` folder slips through.
   - Fix: reject duplicate raw TOC entries.
   - Require a regular file for the expected APK.
   - Fail on an unreadable expected app archive.
   - Require the expected DEX layout before an empty scan counts as evidence.
6. **Blocker: PR artifact eligibility trusts the signing labels.**
   - `variant=debug` is accepted without checking the debug signer's identity.
   - An unsigned marker is accepted without examining the EXE.
   - Fix: confirm both independently, and reject missing or inconsistent evidence.
7. **Should-fix: the release matrix is incomplete.**
   - The callee's `contents: read` caps the tag caller's write permission.
   - Fix: keep release publication disabled until write permission is inherited and RFC 3161 is validated.
   - Disable asset overwrites.
   - Check the actual PR base and merge ref at both upload steps.
   - The default-branch prerelease, the macOS tag trigger and the CI matrix check are all absent.
8. **Should-fix: toolchain and manifest parity.**
   - The manifest gains `extractNativeLibs=true`, and the HOME component is now fully qualified. Verify launcher selection on a device.
   - Update `setup-tools.bat` and `setup-tools-mac.sh` to install and verify Build Tools 36.0.0, which AGP 9.4 requires.
