# P0 review #2: GPT-6.2-sol (high), verdict FAIL

This reviews ARCHITECTURE.md v0.2 at commit c0d5ff6. P1 (Gradle and USB-install safety) may start. P1a may draft but must not freeze. The P0 gate still blocks merges.

| Review #1 finding | Status | Why |
|---|---|---|
| F01 kiosk boundary | PARTIAL | The command path is missing the frame and grant fields needed for enforcement on the tablet |
| F02 navigation | RESOLVED | |
| F03 enrollment | PARTIAL | The scope model can't assign a device ID it generated before approval |
| F04 browser/desktop binding | RESOLVED | |
| F05 MFA/step-up | PARTIAL | Step-up has no authenticated initiation or redemption contract |
| F06 live authz | PARTIAL | The policy matrix and the lease lifecycle disagree |
| F07 projection | RESOLVED | |
| F08 a11y/SDK | PARTIAL | The binding permission, intent filter and metadata declaration were dropped |
| F09 boot/recovery | PARTIAL | Maintenance exit assumes the app can stop the active lock task and restore it reliably |
| F10 phases/integration | PARTIAL | The typed contract can't enforce live session and dispatch rules |
| F11 fleet upgrade | RESOLVED | |
| F12 Windows | RESOLVED | |

## New findings

1. **Blocker · §§3.3, 4, 8.1, 9: unattended command rules conflict.**
   - `status_admin` names four exceptions, but the matrix lets `enter_kiosk` run on any lease. The destructive row also leaves out local approval, despite the attended-only rule.
   - Make one exhaustive policy table keyed by role, mode, grant and policy, and restrict the four exceptions to `status` leases.
   - If `enter_kiosk` needs a recovery path without a grant, allow it only to end an active maintenance window.
   - State the consent requirements for `wipe` and `exit_kiosk` explicitly, next to step-up.
   - Keep `navigate` reserved. Define `kiosk_home` as a load of `equity_home` that takes no arguments, and make `kiosk_back` use only validated WebView history. The current Back handler can launch the home activity (MainActivity.java:237).

2. **Blocker · §§3.3, 4, 9: the single attachment has no complete lifecycle.**
   - `attach{kiosk}` both requires a lease and starts the approval that makes the lease usable. A passive viewer has no defined op that keeps the 60 s lease alive.
   - Define atomic transitions for status, pending approval, granted and released, including mode changes by the same owner and competing attaches. Put a bound on approval time.
   - Define an explicit viewer renewal that keeps the lease alive without extending local consent or the staff session's idle timer.
   - Carry an attachment ID through support requests, replies and detach, so a late approval can't bind to a replacement attachment.

3. **Blocker · §§2.2, 4: the tablet can't validate the advertised frame binding.**
   - The relay-to-tablet `cmd` drops `frame_id` and `generation`. Coordinate commands must carry the attachment, grant, frame and generation IDs on both hops, validated against capture metadata retained on the tablet and the tablet's monotonic clock.
   - Define "delivery" at the desktop display boundary. Tolerate frame replacement by explicitly rejecting stale references.
   - Tie queued work and deduplication to the attachment.
   - Verify that the JPEG and the gesture region exclude the native controls that currently overlap the WebView.
   - Disable touch if the K11 can't contain in-flight gestures across focus or geometry changes.

4. **Blocker · §§2.1, 3.2–3.3, 4: the wire and security interfaces can't enforce the matrix end to end.**
   - Freeze the authenticated staff WSS handshake, the device proof-success reply, the relay-to-staff responses, and the HTTP routes for enrollment approval, audit and revocation.
   - Define who can assign a pending, relay-generated device ID to a managed scope before approval.
   - Give dispatch a live session and policy check that is serialized with revocation and command forwarding. A frozen `StaffSession.grant` on its own can't enforce immediate scope removal.

5. **Blocker · §§3.1, 3.3: step-up has no authenticated desktop completion flow.**
   - Start step-up with an authenticated request bound to the existing session, device and exact op.
   - Redeem the browser handoff with the original session and the desktop verifier. Return a step-up grant only after rechecking freshness, current authorization and the feature flag.
   - Keep the P5b gate for fresh MFA on remembered devices.

6. **Blocker for remote `exit_kiosk` · §§4, 5.5, 7/P3k: maintenance recovery can leave the kiosk unlocked.**
   - The design calls `stopLockTask()` without saying which activity started lock task, and the current activity keeps a cached lock-task flag.
   - Specify which activity owns the transition, check the actual lock-task state, and verify re-entry on expiry, process death and reboot.
   - Keep remote exit disabled, separately from wipe, until the K11 passes those checks.

7. **Should-fix · §§2.2, 5.3, 7/P3k: specify the Android setup and approval entry points.**
   - Restore the accessibility service manifest declaration from F08.
   - Render the pending approval through the visible kiosk activity, and require supervised local setup to reach enrollment.
   - Verify both paths under the deployed lock-task flags.

8. **Should-fix · §§2.1, 2.3, 3.1, 7/P5a, 7.2: carry the auth transport requirements into deployment and desktop tests.**
   - Redact the `/auth/start/<start_id>` path values and credential headers in Caddy and app logs.
   - Specify the browser-trusted HTTPS callback origin for the local Duo trial.
   - Apply certificate and hostname validation to desktop HTTPS and WSS, and test both on CU's supported Windows images.

9. **Should-fix · §§7, 7.1–7.2, 8.2: assign the publication gate before remote code lands.**
   - The Windows workflow publishes on both default-branch pushes and version tags. Give P1 explicit ownership of artifact classification.
   - Require verification of the embedded APK's signer and digest in both packages.
   - Gate both Windows publishing paths before a remote-capable build can reach them.
   - Record the decision on interim USB-only artifacts in §8.2.
