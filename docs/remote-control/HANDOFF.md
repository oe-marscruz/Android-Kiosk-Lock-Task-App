# Handoff log: remote staff control

This file lets a cold agent pick up the work. The fallback lead is Codex `gpt-6.2-sol` with reasoningEffort `high` and serviceTier `default`.

## Fixed decisions
See ARCHITECTURE.md §1. Branch `feat/remote-staff-control` on the fork `oe-marscruz/Android-Kiosk-Lock-Task-App` (remote `origin`). Upstream is `TriBrigadeMars/...` (remote `upstream`), base c9cfde6.
Never hardcode or ask for credentials in chat. Real Duo SSO login happens only at the P5 interactive checkpoint, done by the user.
Don't touch the user's local checkout ~/StudioProjects/Android-Kiosk-Lock-Task-App. It has uncommitted work.

## Status
- [x] P0 drafted (ARCHITECTURE.md v0.1)
- [x] P0 review #1: FAIL (reviews/P0-review-1.md, 7 blockers + 5 should-fix)
- [ ] P0 fixes: 12 parallel Codex gpt-6.1-terra (high, priority) fixers, each writing fixes/FNN.md. The lead merges them into ARCHITECTURE v0.2, then a new gpt-6.2-sol re-review runs
- [ ] P0 review gate PASS
- [ ] P1 Gradle migration
- [ ] P2 relay auth
- [ ] P3 relay routing + desktop client
- [ ] P4 Android agent
- [ ] P5 interactive SSO checkpoint (user)
- [ ] P6 Windows packaging/verification

## Environment notes (Arch dev box)
- ~/Android/Sdk has build-tools 36.0.0 and platforms android-37.0 only. Install platform 35 and build-tools 35 via sdkmanager.
- `java` and `adb` aren't on PATH. Use Android Studio's bundled JBR.

## Policy notes
- Default policy is attended support: local opt-in on the tablet is required before any screen capture. Unattended mode may only expose status and non-content admin commands. This is pending confirmation from the Equity office.
- Duo testing: P5a uses a user-owned Duo trial tenant with a local relay. P5b uses CU's tenant, which needs only a config change.
