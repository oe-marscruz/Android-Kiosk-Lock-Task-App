# P0 review #4: GPT-6.2-sol (high), verdict FAIL (one blocker)

This review covers ARCHITECTURE.md v0.4 at `b06be93`.
- P1b may proceed.
- P1a may draft now and freeze once findings 2–5 are addressed.
- Keep `exit_kiosk` reserved and denied until finding 1 is closed.

## Prior findings

| Finding | Status | Reason |
|---|---|---|
| #3.1 Tablet lifecycle | PARTIAL | Grant duration, tablet expiry reporting and destructive-command freshness still need a contract |
| #3.2 Live authz | PARTIAL | Management ordering and final step-up consumption are still ambiguous |
| #3.3 Enrollment | PARTIAL | Durable success versus cleanup is undefined |
| #3.4 Async capture | PARTIAL | Validation of the final send after encoding is unspecified |
| #3.5 Lock task / exit | PARTIAL | The exit gate doesn't cover losing exact-alarm access |
| #3.6 DUMP gate | RESOLVED | |
| #3.7 Login / redirects | RESOLVED | |
| #3.8 Publication | PARTIAL | Some push and upload cases still need explicit denial |
| #3.9 Windows acceptance | RESOLVED | The Platform-Tools digest matched |
| #2.2 / #2.3 / #2.4 / #2.6 / #2.9, F01 / F03 / F06 / F09 / F10 | PARTIAL | These map onto findings 1–6 below |
| #2.7 Android setup / approval | RESOLVED | |

## Findings

1. **Blocker · §§2.1, 4, 5.3, 7/P3k, 9: remote exit can leave the kiosk unlocked.**
   - Exact-alarm access granted during setup can be revoked later. Revoking it cancels future exact alarms and stops the app.
   - All three P3k scenarios can pass while this path stays open.
   - **Fix:** require per-device evidence that maintenance can't revoke the recovery mechanism, or an independent recovery trigger that still meets the deadline after revocation. Otherwise keep exit disabled.

2. **Should-fix · §§2.1, 3.3–3.4, 4: define the authorization commit at the writer.**
   - At the writer, run one ordered sequence: final check, step-up consumption, durable intent audit, then a bounded send.
   - A grant that has already been consumed can't satisfy a second generic check.
   - Put management authorization and mutation under the same ordering, including target-session scope.
   - Add barrier fixtures for revocation, scope change and expiry after enqueue.

3. **Should-fix · §§2.2, 3.3, 4: freeze terminal messages and execution deadlines.**
   - Define the grant lifetime, renewal on substantive ops, and tablet expiry reporting for both modes.
   - Separate envelope IDs from command IDs, and put `attachment_id` in device acks.
   - A TTL measured from receipt can't enforce the relay's deadline across network delay. For wipe and exit, require a single-use tablet reservation with a local monotonic deadline, established before the relay dispatches.

4. **Should-fix · §§2.2–2.3, 4, 5.1: fence frames through publication.**
   - Drop over-age callbacks.
   - Recheck the request snapshot immediately before the tablet writes an encoded frame.
   - Reject late frames and display acks that arrive after invalidation.

5. **Should-fix · §§3.2, 3.4, 5.6: make enrollment completion crash-safe.**
   - Write the marker with the key alias before generating the key, and add the request ID once the request exists.
   - On `device_ready`, atomically commit the active credential and retire the marker before reporting success.
   - Add crash fixtures for both sides of that commit.

6. **Should-fix · §§7.2–7.3, 8.2: make every publication path default-deny.**
   - Gate both workflows' artifact uploads and release changes on the exact event and class.
   - With no private destination available, suppress internal uploads.
   - Keep legacy asset retirement under its own authorization.
   - Verify the expected Authenticode publisher, and inspect each signature's RFC 3161 timestamp separately.

7. **Gated · §§2.3, 3.1, 3.3, 7/P5b, 7.3: keep the existing gates.**
   - Duo `auth_time` and fresh-factor checks remain under P5b.
   - Check websockets' `MAX_REDIRECTS=1` in the frozen EXE.
   - Make the Windows tap test conditional on K11 touch being approved, and verify rejection on a view-only build.
