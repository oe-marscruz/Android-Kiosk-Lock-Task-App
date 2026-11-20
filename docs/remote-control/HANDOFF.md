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
- [ ] P0 review #5 (gpt-6.2-sol high), then the gate passes
- [x] P1 Gradle migration and signing/upgrade safety (b53269e), plus setup-kiosk.bat no-uninstall fix (9b6946e)
- [ ] P1b publication gate (must merge before any P3/P4 code)
- [ ] P1a contract freeze (record the reviewed commit ID here)
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
