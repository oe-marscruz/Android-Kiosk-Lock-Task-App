# P0 review #5: GPT-6.2-sol (high), verdict PASS-WITH-CHANGES

This review covers ARCHITECTURE.md v0.5 at `d6f6043`. There are no blockers, so **the P0 gate is passed.**
- P1b may start now.
- P1a may draft now, and freezes after findings 1–4 are reflected in the contracts and fixtures.

| Review #4 finding | Status | Note |
|---|---|---|
| 1 remote exit | RESOLVED | v1 always denies remote exit and removes its alarm permission, receiver and recovery gate. |
| 2 writer commit | PARTIAL | See finding 2. |
| 3 terminal and deadlines | PARTIAL | See finding 2. |
| 4 frame fence | PARTIAL | See finding 3. |
| 5 enrollment | PARTIAL | See finding 4. |
| 6 publication | PARTIAL | See finding 5. |

## Findings

1. **Should-fix · §§2.2, 3.3, 4, 7.1, 9: reserve `enter_kiosk` in v1 and use supervised local re-entry.**
   - The USB script force-stops the app and writes no maintenance marker.
   - Remove both of `enter_kiosk`'s allow rows.
   - Define the local exit and re-entry procedure for the P4 upgrade fixture.

2. **Should-fix · §§2.1, 3.3, 4: freeze wipe as phase-specific writer and result transitions.**
   - `reserve` uses the live writer check, without consuming the step-up or marking a dispatch.
   - Reject a plain `cmd{op:"wipe"}` from relay to tablet.
   - Only `execute` consumes and audits.
   - Recheck deadlines after the audit write, and cap the send at the remaining time budget.
   - Register dispatch correlation before the execute send is attempted.
   - Define the negative ack for a known-expired reservation, and keep both IDs on it.
   - Use `OUTCOME_UNKNOWN` only after an execute attempt that got no definitive ack.
   - A late ack only reconciles the audit record.
   - Add barrier fixtures for expiry during the audit write, release, and a late ack.

3. **Should-fix · §§2.2–2.3, 3.3, 4: complete the invalidation contract.**
   - Add a terminal reason for boundary invalidations other than Stop or expiry.
   - Serialize the Tk display commit and input enablement with invalidation, including a recheck after sending `frame_displayed`.
   - Test invalidation during decode, and between the ack and input enablement.

4. **Should-fix · §3.2: make the quarantine decision recoverable.**
   - Persist `request_may_exist` before the POST.
   - Preserve the fingerprint before deleting the alias.
   - Keep the marker until deletion is verified and any required admin reconciliation is done.
   - If durable state can't rule out a dispatch, quarantine.
   - Carry I05's crash fixtures forward.

5. **Should-fix · §§7.2, 8.2: make the publication matrix executable.**
   - Evaluate each platform independently.
   - State which gates apply to private remote macOS staging, given the §5.7 release gate.
   - Distinguish the legacy `latest` tag from GitHub's `/releases/latest` selector, which the README uses.
   - Keep the final bytes in the eligible job, or use a verified private handoff that itself obeys the upload policy.
   - Restore the warning for internal USB debug builds.

6. **Gated: carry forward review #4's acceptance conditions.**
   - Production login and wipe stay off until there's CU OIT evidence.
   - Touch stays off until there's K11 containment evidence.
   - Make the Windows tap test conditional on that approval.
   - Assert touch rejection on view-only builds.
   - Run the redirect negative tests against the frozen EXE.

7. **Nit: clean up deferred-exit references.**
   - Delete the exact-alarm setup placeholder.
   - Change P5a to say "wipe stays off".
   - Mark the v0.3/v0.4 exit and alarm notes as superseded.
