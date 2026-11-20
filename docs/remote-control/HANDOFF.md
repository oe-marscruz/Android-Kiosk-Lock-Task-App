# Handoff log: remote staff control

This file lets a cold agent pick up the work. The fallback lead is Codex `gpt-6.2-sol` with reasoningEffort `high` and serviceTier `default`.

## Fixed decisions
See ARCHITECTURE.md §1. Branch `feat/remote-staff-control` on the fork `oe-marscruz/Android-Kiosk-Lock-Task-App` (remote `origin`). Upstream is `TriBrigadeMars/...` (remote `upstream`), base c9cfde6.
Never hardcode or ask for credentials in chat. Real Duo SSO login happens only at the P5 interactive checkpoint, done by the user.
Don't touch the user's local checkout ~/StudioProjects/Android-Kiosk-Lock-Task-App. It has uncommitted work.

## Status
- [x] P0 drafted (v0.1). Review #1 FAILED (reviews/P0-review-1.md)
- [x] 12 fixes (fixes/F01–F12.md, Codex gpt-6.1-terra high/priority) merged into ARCHITECTURE v0.2. Reconciliation notes are in §9
- [x] P0 review #2: FAIL (reviews/P0-review-2.md, 6 blockers + 3 should-fix)
- [x] 9 fixes (fixes/G01–G09.md, Terra high/priority) merged into ARCHITECTURE v0.3. Reconciliation in §9
- [x] P0 review #3: FAIL (reviews/P0-review-3.md, 5 blockers + 4 should-fix)
- [x] 9 fixes (fixes/H01–H09.md) merged into ARCHITECTURE v0.4; reconciliation in §9
- [x] P0 review #4: FAIL with 1 blocker (remote exit). Remote exit removed from v1; I02–I06 merged into v0.5
- [x] P0 review #5: **PASS-WITH-CHANGES, so the gate is passed** (reviews/P0-review-5.md)
- [x] Should-fix J01–J05 merged into ARCHITECTURE v0.6, the P1a freeze baseline
- [x] P1b publication gate (0fd33fd) + PR test artifacts (b73fb49)
- [x] P1 Gradle migration and signing/upgrade safety (b53269e), plus setup-kiosk.bat no-uninstall fix (9b6946e)
- [ ] P1a contract freeze (record the reviewed commit ID here)
  - P1a drafted at dc582f2; freeze pending review.
- [ ] P2 relay security
- [ ] P3 relay routing and desktop
- [ ] P3i composed integration and deploy verification
- [ ] P3k physical K11 feasibility spike (user + tablet)
- [ ] P4 Android agent
- [ ] P5a Duo trial tenant (user) / P5b CU tenant (user + OIT)
- [ ] P6 Windows packaging and release gate

## Environment notes (Arch dev box)
- ~/Android/Sdk has build-tools 36.0.0 and platforms android-37.0 only. Install platform 35 and build-tools 35 via sdkmanager.
- `java` and `adb` aren't on PATH. Use Android Studio's bundled JBR.

## Policy notes
- Default policy is attended support: local opt-in on the tablet is required before any screen capture. Unattended mode may only expose status and non-content admin commands. This is pending confirmation from the Equity office.
- Duo testing: P5a uses a user-owned Duo trial tenant with a local relay. P5b uses CU's tenant, which needs only a config change.

## Lead handoff (2026-11-20). Opus is near its usage limit, so DeepSeek V4.1 Flash (Command Code GOAT, thinking high) takes over

**State at handoff**
- **Branch** `feat/remote-staff-control` on the fork `origin`, pushed at `b73fb49`. The architecture is ARCHITECTURE.md v0.6, and the P0 gate has passed.
- **Done:**
  - P1 (`b53269e`): Gradle and fail-closed signing.
  - `9b6946e`: `setup-kiosk.bat` no longer uninstalls.
  - P1b (`0fd33fd`): default-deny publication gate.
  - `b73fb49`: PR test artifacts.
- **Running when the lead switched:**
  1. **P1a contract freeze.** Claude agent, shared checkout. It is producing `relay/contracts.py`, `docs/remote-control/protocol/*`, fixtures, `tests/test_protocol_fixtures.py`, `.github/workflows/protocol.yml`, and `REMOTE_FEATURES` flipped to 1. The work is committed locally and NOT pushed. It is a draft until a reviewer passes it.
  2. **Code review gate for P1 and P1b.** GLM-5.3 Flash (high, Command Code GOAT), read-only. It is checking the open question from the partial Sol review: the old and new APKs have different signer fingerprints, and their binary manifests differ in the launcher component.

**User rules, binding on the new lead**
- **Review gate.** No phase is finalized or merged without a review.
  - Normal reviewer: Codex `gpt-6.2-sol`, high effort.
  - While Codex is over its usage limit (resets 12:23 PM): GLM-5.3 Flash, high, Command Code GOAT. That is `pi` / `commandcode/z-ai/glm-5.3-flash`.
- **Fixes for review findings.** Each finding gets its own subagent.
  - Normal fixer: Codex `gpt-6.1-terra`, reasoningEffort high, serviceTier priority.
  - If Terra fails: GLM 5.3 High (non-flash). Ask the user first, because Command Code lists only the flash model.
- **Credentials.** Never ask for credentials in chat. Real Duo login happens only at P5a/P5b, done by the user.
- **Pull requests.** PRs go from the fork to `TriBrigadeMars/master`. Open a draft PR only after the P1/P1b code review passes.
- **Delegation.** Don't use worktree isolation; it fails here. Agents share the checkout and stage files by explicit path.

**Next steps**
1. **When the GLM review returns:** record it in `reviews/CODE-review-P1-P1b.md`. Send each blocker or should-fix finding to its own fixer, then re-review.
2. **When P1a returns:** push it. Then run a contract review of `relay/contracts.py`, `protocol/v1.schema.json`, `v1.md` and the fixtures against ARCHITECTURE v0.6 §2.1, §3, §4. Freeze only after it passes, and record the freeze SHA here.
3. **After both reviews pass:**
   - Open a draft PR to upstream.
   - Start P2 (relay auth) and P3 (relay ws plus `kiosk_remote`) in parallel, following ARCHITECTURE §7 ownership.
   - P3k (the K11 spike) needs the user and the physical tablet.

**Open items:**
- **CU OIT, P5b:** issuer and claims.
- **OCI:** VM hostname.
- **Equity office:** policy decisions.
- **CU IT:** Windows test images.
- **Signing:** the Authenticode certificate and the release keystore, plus the `KIOSK_CERT_SHA256` repo variable.

### Update: the P1/P1b code review (GPT-6.2-sol) returned FAIL with 6 blockers
- The review is at `reviews/CODE-review-P1-P1b.md` (`cce0bc0`). The duplicate GLM review was cancelled.
- **Wave 1 is running.** Each item has its own Terra fixer. The fixers commit locally and do not push:
  - K1: release fingerprint pin, in gradle and build-apk.sh
  - K2: secrets in a protected environment, in the workflows and release README
  - K4: setup stops on a failed build or install, in setup-kiosk.bat, kiosk-manager.py and tests
  - K5: strict APK inspection, in the classifier and tests
  - K8: build-tools 36 plus a manifest parity doc, in setup-tools*
- **Wave 2 starts after wave 1.** Each item depends on a wave-1 change to the same file:
  - **K3**, after K1: keep reusing the legacy `local_debug.keystore` for local debug builds. PR builds keep using a fresh debug key. Verify `install -r` against a fixture signed with the matching key.
  - **K6**, after K5: independently confirm the APK's debug signer identity and the EXE's unsigned status. Reject missing or inconsistent evidence.
  - **K7**, after K2: keep release publication disabled until write permission is inherited and RFC 3161 timestamps are validated. Disable asset overwrites. Check the PR base and merge ref at both upload steps.
- **When all of K1–K8 are in:** push them, then run a new GPT-6.2-sol re-review of P1/P1b. After it passes, open a draft PR to upstream.
- **P1a contract review** is running on GLM-5.3 Flash (high). If it returns FREEZE, record the freeze SHA here.
- **Progress:**
  - **Done:** K2 `a2a3da1`, K4 `8da4e98`, K8 `ef4f52b`, K5 `1e8c896`, and the lead's `f079723` fixing the dpm findstr.
  - **Running:** K1, plus K6 and K7.
  - **Still to start:** K3, once K1 lands.
  - **Operator step for the user:** set up the `release-signing` environment (see release/README-publication.md).
  - **Check on real Windows:** K4's `findstr /x` (Wine ignores the `/x` flag).
