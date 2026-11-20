# P0 review #3: GPT-6.2-sol (high), verdict FAIL

This is a review of ARCHITECTURE.md v0.3 at `d508dfa`.

- P1a may draft fixtures, but must not freeze yet.
- P2 and P3 are on hold until the lease, authorization and enrollment contracts are settled.
- P1 can continue its Gradle migration as long as behavior is preserved.

## Prior findings

| Finding | Status | Reason |
|---|---|---|
| #2.1 policy/navigation | RESOLVED | |
| #2.2 attachment lifecycle | PARTIAL | The tablet has no status-lease or renewal message. |
| #2.3 frame binding | PARTIAL | Async capture lacks a post-callback boundary check. |
| #2.4 wire/live authz | PARTIAL | Underspecified: `AuthzContext`, management target scope, and ordering at the socket writer. |
| #2.5 step-up | RESOLVED | |
| #2.6 maintenance exit | PARTIAL | Global lock state can't establish owner-task recovery. |
| #2.7 Android setup/approval | PARTIAL | The receiver trust model needs correction. |
| #2.8 auth transport/logging | RESOLVED | |
| #2.9 publication gate | PARTIAL | Ambiguous: manual events, unsigned-package verification, timestamp enforcement. |
| #1 F01 boundary | PARTIAL | Screenshot callbacks need binding to capture-time state. |
| #1 F03 enrollment | PARTIAL | The tablet has no approval → activation transition it can execute. |
| #1 F05 MFA/step-up | RESOLVED | |
| #1 F06 live authz | PARTIAL | Group freshness and transport-boundary revocation have no contract. |
| #1 F08 a11y/SDK | RESOLVED | |
| #1 F09 boot/recovery | PARTIAL | Re-entry needs owner-task verification and an enforceable deadline. |
| #1 F10 integration | PARTIAL | P2 and P3 need a shared enforcement contract. |

## Findings

1. **Blocker · §§3.3, 4: the tablet can't enforce the attachment lifecycle.**
   - `attach{status}` sends the tablet nothing, and renewal only updates the relay, yet the tablet is supposed to check and expire the current lease on its own.
   - The policy table says `attach` needs no attachment, but the transition table allows same-owner mode changes.
   - Fix: define a relay→tablet lifecycle for both modes, with explicit open, renew and close messages. The tablet keeps its own monotonic expiry, and the consent deadline is tracked separately.
   - Define which clock `deadline_ms` uses and what it means.
   - Make same-owner transitions explicit in the policy table.
   - Freeze fixtures for a withheld renewal, a delayed detach, and `enter_kiosk` with a status-only lease.

2. **Blocker · §§2.1, 3.3–3.4, 4, 9: `AuthzContext` and the forwarding boundary are incomplete.**
   - A mode, a grant-valid boolean and a maintenance flag can't establish ownership, lease identity or freshness across async calls.
   - `authorize` has no typed targets for group reassignment or for revoking a target session.
   - Fix: freeze trusted context variants carrying the current socket, attachment and grant IDs, their deadlines, and the policy revision.
   - Define how an HTTP step-up resolves the WSS attachment that owns it.
   - Fence commands, frames and scoped events at the actual socket writer, so a revocation or scope change takes effect there.
   - Test the race where a mutation wins after enqueue but before the write.
   - Use principal mapping for v1, unless P1a defines an authoritative live group source and how it gets invalidated.

3. **Blocker · §§3.2, 3.4, 5.6: enrollment can stop before activation.**
   - A pending tablet gets a generic auth failure, and auth failure stops retries. After the desktop approves, nothing tells the tablet to start the proof.
   - Fix: add a local **Finish enrollment** action after admin approval, with bounded retry inside the original request TTL.
   - Define cleanup on cancel, on expiry, and when the key is replaced.
   - Make assignment and approval atomic, including the state and scope checks.
   - Assigned pending requests are visible only in scope.

4. **Blocker · §§2.2, 4, 5.1: bind async capture to the state at request time.**
   - `ScreenshotResult.getTimestamp()` uses non-sleep uptime. On Android 15, AOSP stamps window results when the callback arrives, so the timestamp can't show when the pixels became safe to share.
   - Fix: record the grant, window, geometry and shareable-page generation at request time, and recheck all of them before retaining, encoding or sending the result.
   - Drop any callback that crosses a navigation, obscuration, Stop or suspend.
   - Use the request-start uptime as the conservative age bound.
   - Clear the display reference together with the ring.

5. **Blocker for the P4 lock-task rollout and remote exit · §§2.2, 4, 5.5, 7/P3k–P4, 9: verify the owner task and bound maintenance.**
   - `normal` plus an explicit `startLockTask()` from the foreground allowlisted root task does reach `LOCKED`. Moving the manifest change to P4 keeps the migration behavior-preserving.
   - The problem: a device-wide `LOCKED` doesn't prove that `MainActivity` owns the locked task.
   - Fix: specify how the task is created and reused from HOME, at boot and after an upgrade. Guard against auto-lock on resume during maintenance.
   - Require a working wakeup mechanism before lock task is stopped.
   - Keep exit disabled until the K11 proves deadline recovery in three cases: another app in the foreground, after process death, and after an update.
   - Gate the P4 manifest switch on cold-boot, signed-upgrade and student-path tests, including the Chrome and Settings allowlist.

6. **Should-fix · §§2.2, 3.2, 5.3, 7/P3k, 9: describe DUMP as a privileged-sender gate.**
   - The receiver permission checks the **sender**. Shell holds DUMP, and ordinary apps can't self-grant it.
   - However, a third-party APK that requests DUMP can be given a development grant by privileged tooling.
   - On Android 15, AOSP returns `INVALID_UID` (-1) for the documented `am broadcast`, because that command leaves identity sharing off.
   - Fix: keep the UID check where it's available, and document that the unknown-UID path trusts DUMP-capable senders.
   - On the K11, verify that the shell route works, that an ordinary app is denied, and which apps hold DUMP. Enforce debugging lockdown after setup.

7. **Should-fix · §§2.3, 3.1, 3.3, 7/P5b: make the production login gate explicit.**
   - Require CU evidence of the base RP policy and the accepted MFA values before **any** staff login is enabled, including negative tests for bypassed and skipped MFA. The stronger fresh-factor requirement still applies to wipe and exit.
   - Reject redirects on native HTTPS/WSS requests that carry credentials.
   - Validate `start_url` against the configured relay origin before launching the browser.

8. **Should-fix · §§7, 7.2–7.3, 8.2, 9: close the P1b publication matrix.**
   - P1b must land before **any** remote implementation merges, including P2, because `relay/` on its own triggers classification.
   - `workflow_dispatch` needs an explicit publish rule.
   - Verify the embedded APK in every final EXE, including the unsigned exception.
   - Require proof of an RFC 3161 timestamp, and treat SignTool warnings as failures.
   - A prerelease label on a public repository still leaves the download public. Use restricted distribution if internal-only access is required, and check how new and legacy assets are handled.

9. **Should-fix · §§2.3, 7.3: name CU's Windows acceptance images.**
   - Pin the exact Python patch version and the bundled Platform Tools version.
   - Test the candidate hash on CU's supported Win10 and Win11 x64 images, with their browser, proxy and endpoint policies, as a standard user: login, attach, frame display and logout.
