# Handoff log: remote staff control

This file lets a cold agent pick up the work. The fallback lead is Codex `gpt-6.2-sol` with reasoningEffort `high` and serviceTier `default`.

## Fixed decisions
See ARCHITECTURE.md §1. Branch `feat/remote-staff-control` on the fork `oe-marscruz/Android-Kiosk-Lock-Task-App` (remote `origin`). Upstream is `TriBrigadeMars/...` (remote `upstream`), base c9cfde6.
Never hardcode or ask for credentials in chat. Real Duo SSO login happens only at the P5 interactive checkpoint, done by the user.
Don't touch the user's local checkout ~/StudioProjects/Android-Kiosk-Lock-Task-App. It has uncommitted work.

## Status
- [x] P0 drafted (ARCHITECTURE.md v0.1)
- [ ] P0 review gate (GPT-6.2-sol)
- [ ] P1 Gradle migration
- [ ] P2 relay auth
- [ ] P3 relay routing + desktop client
- [ ] P4 Android agent
- [ ] P5 interactive SSO checkpoint (user)
- [ ] P6 Windows packaging/verification

## Environment notes (Arch dev box)
- ~/Android/Sdk has build-tools 36.0.0 and platforms android-37.0 only. Install platform 35 and build-tools 35 via sdkmanager.
- `java` and `adb` aren't on PATH. Use Android Studio's bundled JBR.
