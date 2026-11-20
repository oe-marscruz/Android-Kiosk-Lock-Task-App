# Remote Staff Control: Architecture (v0.5)

Status: **v0.6, P0 GATE PASSED** (review #5: PASS-WITH-CHANGES). Should-fix items J01–J05 are merged. This is the baseline for the P1a freeze.

| Version | Review | Result | Fixes |
|---|---|---|---|
| v0.1 | #1 | FAIL | F01–F12 |
| v0.2 | #2 | FAIL | G01–G09 |
| v0.3 | #3 | FAIL | H01–H09 |
| v0.4 | #4 | FAIL (1 blocker: remote exit) | I02–I06, plus remote `exit_kiosk` removed from v1 |
| v0.5 | #5 | **PASS-WITH-CHANGES** | J01–J05, merged here |

The sources are in `reviews/` and `fixes/`, and §9 records how the lead reconciled them. No remote implementation merges until GPT-6.2-sol passes the review gate. P1, the Gradle migration (`b53269e`), has landed on the feature branch.

## 1. Decisions (fixed by the project owner, 2026-11-20)

| Topic | Decision |
|---|---|
| Network | A cloud relay on an OCI VM. Tablets and staff desktops both **dial out** over WSS. Tablets never listen for inbound connections. |
| Build | Gradle (AGP 9.4.1, Gradle 9.8.2, committed wrapper). `build-apk.sh` and `build-apk-mac.sh` are thin wrappers. Done in P1. |
| IdP | **Duo SSO**, used as an OIDC IdP through a Generic OIDC RP, in front of Oracle Cloud. P5a uses a user-owned Duo trial in `trial` mode with a local relay. P5b uses CU's tenant in `production` mode, changing configuration only. |
| Delivery | Work goes on the fork `oe-marscruz/...`, and PRs target `TriBrigadeMars/master`. |
| Support policy | **Attended-only** by default: a person at the tablet must opt in locally before staff can see content or send input. The Equity office must confirm this (§8). |
| v1 scope | One staff attachment per tablet. Kiosk-window capture uses accessibility only, with projection off. `navigate`, **`enter_kiosk` and `exit_kiosk` are reserved and always denied**. Exiting and re-entering kiosk mode are supervised local USB actions (§2.2), and remote exit is deferred to v2 (Appendix A). Staff login and wipe each have their own gate, and both default to off. Device scope comes from a principal mapping only. |

## 2. Components

```
 Staff PC (Win10/11)                 OCI VM                              Tablet (Android 15, Device Owner)
┌──────────────────────┐   HTTPS   ┌───────────────────────────────┐  WSS  ┌──────────────────────────────────┐
│ kiosk-manager.py     │──────────►│ Caddy :443 (TLS, ACME,         │◄──────│ RemoteAgentService (specialUse)  │
│  + kiosk_remote/     │    WSS    │   URI/header-free access log)  │       │ KioskA11yService (window capture │
│  - browser login,    │◄────────►│   └► aiohttp 127.0.0.1:<port>  │       │   + kiosk-scoped gestures)       │
│    step-up, handoff  │           │      relay/: OIDC RP, sessions,│       │ MainActivity: student WebView    │
│  - Tk viewer         │           │      registry, live authz,     │       │   (ALLOWED_DOMAINS unchanged),   │
│  - USB/ADB (existing)│           │      attachments, socket-writer│       │   lock-task owner, native panels │
└──────────▲───────────┘           │      fence, audit (SQLite)     │       │ AdminCommandHandler (DPM)        │
           └── system browser ──► Duo SSO ◄── OIDC code+PKCE ──────┘       │ EnrollmentSetupReceiver (DUMP)   │
                                                                             └──────────────────────────────────┘
```

### 2.1 Relay (`relay/`, new)
- Python 3.12+ and aiohttp. aiohttp binds **only `127.0.0.1`**, and only Caddy is exposed. A single process handles up to about 50 tablets. SQLite holds the registry, sessions, transactions, step-up grants, enrollment secrets (stored as verifiers) and the audit log. Sockets and attachments live in process memory.
- **Ownership.**
  - The lead owns `relay/app.py` (`create_app`), `config.py`, `migrations/`, `deploy/` and the composition tests.
  - P2 owns `relay/auth/`, `store.py` and `SecurityServices`.
  - P3 owns `relay/ws.py`, which covers attachments, queues, routing and the socket writers.
  - Shared contracts change only with lead review.
  - `create_app` validates the config and applies migrations before it accepts any traffic, and fails startup if either step fails.
- **Contracts** (`relay/contracts.py`, frozen at P1a). The relay builds contexts while holding the ordering lock, from authenticated connections and authoritative state, never from client claims. IDs that arrive on the wire are only lookup keys. Deadlines use the relay's monotonic clock. Any mismatch between a snapshot and live state means the relay rebuilds the context or denies the request.

```python
@dataclass(frozen=True)
class Principal: issuer: str; subject: str
@dataclass(frozen=True)
class StaffSession: session_id: str; principal: Principal; display_name: str; expires_at: datetime
@dataclass(frozen=True)
class WsAttachContext:
    device_id: str; socket_id: str; attachment_id: str | None; grant_id: str | None
    lease_deadline: float | None; grant_deadline: float | None
    maintenance_active: bool; policy_revision: int; requested_mode: Literal["status", "kiosk"]
@dataclass(frozen=True)
class WsCommandContext:
    device_id: str; socket_id: str; attachment_id: str; grant_id: str | None
    lease_deadline: float; grant_deadline: float | None; maintenance_active: bool; policy_revision: int
@dataclass(frozen=True)
class HttpMgmtContext:
    device_id: str | None; target_session_id: str | None; from_group: str | None; to_group: str | None
    policy_revision: int
@dataclass(frozen=True)
class StepUpContext:
    device_id: str; socket_id: str; attachment_id: str; grant_id: str
    lease_deadline: float; grant_deadline: float; maintenance_active: bool; policy_revision: int
Ctx = WsAttachContext | WsCommandContext | HttpMgmtContext | StepUpContext

class SecurityServices(Protocol):
    async def authenticate_staff(self, token: str) -> StaffSession: ...
    async def start_device_challenge(self, device_id: str, socket_id: str) -> tuple[str, str]: ...
    async def verify_device_proof(self, device_id: str, socket_id: str, sig: bytes) -> DeviceIdentity: ...
    async def authorize(self, session_id: str, op: str, ctx: Ctx) -> Decision: ...
    async def consume_step_up(self, session_id: str, op: str, step_up_id: str, ctx: StepUpContext) -> Decision: ...
    async def revoke_session(self, session_id: str) -> None: ...
    async def revoke_device(self, device_id: str) -> None: ...
    async def audit(self, event: AuditEvent) -> None: ...  # raises → caller must not dispatch
# DeviceIdentity, Decision, AuditEvent and ConnectionCloser are unchanged from v0.3.
```

  Each op requires a specific context variant and specific targets. A wrong variant, a missing target or an extra target is denied.
- **`policy_revision` and ordering.**
  - `policy_revision` is a monotonic counter. It is published atomically with every successful config reload, every session or device revocation, and every reassignment, before the affected locks are released. A failed reload leaves the old revision in place.
  - Policy and session mutations, device revocation, attachment transitions and the final authorize → audit → enqueue step are serialized per device. Global changes take the affected device locks in a deterministic order.
  - Before a mutation reports success, the affected queues are purged and the affected sockets and attachments are closed. A durable revocation stays in force even if that cleanup fails.
  - If authoritative state or the audit store is unavailable, the relay fails closed.
- **Socket-writer fence.**
  - Every outgoing command, frame and scoped event carries trusted routing metadata: device, socket, session, attachment, grant, op, and the revision at enqueue time.
  - Each socket has a single writer. Immediately before `ws.send`, that writer takes the per-device ordering lock again and re-authorizes the item against current state: revision, session, scope, socket and attachment ownership, grant and lease deadlines, and maintenance state. It holds the lock through a **bounded** send.
  - A stalled or failed send closes the socket.
  - If a mutation commits after an item is queued but before it is written, the item is dropped or re-authorized.
  - Bytes already handed to the transport can't be recalled.
  - Content-free cleanup notifications use a separate, non-scoped path.
- **Admission vs. writer commit.**
  - **Admission** checks:
    - authentication and envelope validity
    - op, targets, session, role and scope
    - socket and attachment ownership
    - lease, grant, maintenance and gate
    - rate, queue, dedup and deadline limits
    
    It then builds the routing metadata. For `wipe`, admission checks the step-up binding and freshness but does **not** consume it. Neither admission nor enqueue gives permission to send.
  - **Writer commit.** There is one path for every scoped item. Under the per-device lock, without releasing it, the writer runs these steps in order:
    1. Final live authorization: ordinary authority plus the local grant. It never consumes the step-up and never requires it to be already consumed.
    2. For `wipe` only: one atomic `consume_step_up`. Nothing else consumes it.
    3. A durable intent audit, including destructive intent.
    4. A bounded `ws.send`.
  - **Failures.**
    - If authorization is denied, has expired, can't be checked, or consumption fails, the item is dropped without sending, and the step-up isn't consumed.
    - An audit failure prevents the send. A step-up that was already consumed stays consumed.
    - A send that stalls or fails closes the socket. Once a send has been attempted, any command without a definitive ack is `OUTCOME_UNKNOWN`. The step-up is never restored and the command is never replayed.
- **Management ordering.** Authorization and mutation happen as one ordered operation, not a check followed by a separate write.
  - The relay acquires the affected session and device locks in a single documented, deterministic order that writers, policy changes, expiry and revocations all share. Under those locks it resolves state, builds `HttpMgmtContext`, authorizes, and atomically commits the mutation together with its audit record.
  - Session revocation locks the actor, the target and every affected device. Under those locks it resolves the target's **entire** current scope, and the actor needs authority over all of it. If the affected set changes, the relay retries the lock acquisition.
  - If state is unavailable or the audit write fails, the operation is denied and rolled back.
- **Config.** Values come from env or a protected file. Secrets come only from env or a protected file and are never committed. Unknown or invalid values fail startup.
  - `DEPLOYMENT_MODE` is required: `trial` or `production`.
    - `trial` accepts only the configured trial issuer and RP.
    - `production` rejects any trial issuer, config or trust bundle.
  - `STAFF_LOGIN_ENABLED=false` (default) keeps staff login off.
    - In production, enabling it requires recorded, approved P5b evidence bound to the exact issuer, RP, effective base policy and `OIDC_REQUIRED_AMR`. The evidence must include negative tests for bypassed and skipped MFA. Any change to those inputs invalidates the evidence.
    - While the switch is off, every staff auth endpoint denies, existing staff sessions are rejected, and staff sockets are closed under the ordering rules.
  - `PUBLIC_BASE_URL`, `OIDC_ISSUER` (exact match for both the discovery `issuer` and the token `iss`), `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_ALLOWED_ALGS` (asymmetric only), `OIDC_REQUIRED_AMR` (must not be empty).
  - `ROLE_SOURCE=principal` is the **only v1 source**. `ACCESS_MAP` maps `(iss, sub)` to `{role, groups[], audit_wide}`.
    - Each device belongs to exactly one configured group.
    - `ROLE_SOURCE=group` is rejected until there is a live membership source with defined freshness and invalidation.
    - There is no email fallback.
  - `DEVICE_AUTH_AUDIENCE`, and `REMOTE_SUPPORT_POLICY` = `attended_only` (default) or `status_admin`.
  - `DESTRUCTIVE_ACTIONS_ENABLED=false` gates wipe. Enabling it requires P5b fresh-factor evidence.
  - There is no exit gate in v1. `enter_kiosk` and `exit_kiosk` are denied no matter what the configuration says. v1 has no USB maintenance marker and no remotely controlled maintenance window.
  - Limits: `CMD_QUEUE_MAX=32`, `CMD_RATE_PER_S=20`, `CMD_DEADLINE_S=5`, `LEASE_IDLE_S=60`, `APPROVAL_TIMEOUT_S=60`, `GRANT_MAX_S=300`, `SESSION_ABS_H=8`, `SESSION_IDLE_MIN=30`, `FRAME_MAX_AGE_MS=1000`, `FRAME_RING=8`, `CMD_TRANSIT_BUDGET_MS=1000`, `ACK_RESULT_WINDOW_S` (a bounded window for late acks).
- **Logging.**
  - The Caddy log uses `format filter` with `request>uri delete`, `request>headers delete` and `resp_headers delete`.
  - `log_credentials` is never enabled, and the `uri` handler is never used for redaction.
  - The aiohttp access logger, a subclass of `AbstractAccessLogger`, logs only the route template (or `unknown`), the method, the status and the duration.
  - App and error logs never contain any of: tokens, codes, state, CSRF tokens, verifiers, cookies, status secrets, signatures, command args, frames or raw URLs.

### 2.2 Tablet agent (inside the existing APK, package `com.example.webkiosk`)
- **Manifest additions (P4).**

```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_SPECIAL_USE" />
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
<service android:name=".remote.KioskA11yService" android:exported="true"
    android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE">
    <intent-filter><action android:name="android.accessibilityservice.AccessibilityService" /></intent-filter>
    <meta-data android:name="android.accessibilityservice" android:resource="@xml/kiosk_a11y_service" />
</service>
<service android:name=".remote.RemoteAgentService" android:exported="false"
    android:foregroundServiceType="specialUse">
    <property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
        android:value="Maintains the outbound connection for attended kiosk support" />
</service>
<receiver android:name=".remote.BootReceiver" android:exported="false">
    <intent-filter><action android:name="android.intent.action.BOOT_COMPLETED" /></intent-filter>
</receiver>
<receiver android:name=".remote.EnrollmentSetupReceiver" android:exported="true"
    android:permission="android.permission.DUMP" />
```

  - `MainActivity` gains a dedicated, app-private `taskAffinity` and `launchMode="singleTask"`.
  - `lockTaskMode` on `MainActivity`, `LauncherActivity` and `WifiSettingsActivity` changes from `if_whitelisted` to `normal`. This switch is **gated** (§7, P4 gates).
  - Projection components are added only by a future build that has projection enabled.
- **`remote/KioskA11yService`** (`res/xml/kiosk_a11y_service.xml`). Config: event types `typeWindowStateChanged|typeWindowsChanged`, `feedbackGeneric`, `flagRetrieveInteractiveWindows`, `canRetrieveWindowContent`, `canPerformGestures`, `canTakeScreenshot`, `notificationTimeout=100`.
  - `caps.a11y` is reported only after `onServiceConnected`. `caps.window_capture` additionally requires API 34+.
  - Screenshot errors:
    - secure window: stop and report `secure_window`
    - interval too short: back off with bounded pacing
    - invalid window or display: stop and revalidate
    - no access: clear readiness
    - any other error: stop and retry, with a bound
  - Every `HardwareBuffer` is closed on every path.
- **`remote/RemoteAgentService`** keeps one outbound WSS connection, starts after first unlock, and never uses MediaProjection.
- **Native panels owned by `MainActivity`.** No separate activity, notification, overlay or background launch is used.
  - **Support approval.** A kiosk `attach_open` is delivered in-process to the visible, resumed, focused `MainActivity`, which shows the staff member's name with **Allow / Deny**. If the activity isn't visible, the request stays pending until the local approval deadline, then is denied. It is never auto-granted.
  - **Banner and Stop.** A native, non-interactive, non-dismissable banner reads "CU staff connected: <name>", using the authenticated name as plain text (64 characters max). A local **Stop** control sits beside it. The banner must be confirmed visible before any capture or input.
  - **Enrollment panel.** Covered under §3.2. While it is open, support and input are blocked, and capture is invalidated.
  - Approval, banner, Stop and enrollment controls are all outside the remote-input region.
- **Tablet lease** (§4 lifecycle).
  - The tablet learns about every attachment, in both `status` and `kiosk` mode, through `attach_open{attachment_id, mode, display_name?, lease_ms}`, `lease_renewed{attachment_id, lease_ms}` and `detach{attachment_id}`.
  - Each lease deadline is the local `elapsedRealtime()` at receipt plus `lease_ms`. The relay sends no absolute times.
  - The tablet checks the lease before every scoped operation and schedules expiry itself. If renewal is withheld, the lease expires locally even when no `detach` ever arrives.
  - The local approval deadline and the grant deadline are separate and are never extended by lease renewal.
  - **Grant window.** When the person taps Allow, the grant is a fixed window of `elapsedRealtime() + GRANT_MAX_S` (300 s), and the tablet reports the remaining time in `support_granted`. The relay sets its own deadline from that report. Neither substantive ops, lease renewal nor a same-mode attach extends the grant. Once it expires, staff need a new kiosk attachment and a fresh local approval.
  - **Terminal events.**
    - When a lease expires, in either mode, the tablet sends `attachment_expired{attachment_id, reason:"lease_expired"}`.
    - When a grant expires, Stop is pressed, or any boundary invalidation happens, it sends `support_stopped{attachment_id, reason}`, using a reason from the closed registry (§4).
    - The tablet cleans up locally first and doesn't retry delivery after a disconnect.
    - The relay applies these events under the device lock. A duplicate or stale event is harmless.
  - Disconnect clears all attachment state. Stale or expired IDs are never revived.
  - **Wipe reservations** (§4) are destroyed on expiry, release, disconnect, restart or invalidation.
- **Kiosk boundary and capture.**
  - **Content region.** For a granted attachment, the service resolves the foreground `MainActivity` window and the WebView bounds. It records excluded rectangles, each with its full hit area: the native Chrome and Wi-Fi buttons, the banner, Stop, the panels, and any other overlapping native control. It then picks a **content rect**: a non-empty axis-aligned rectangle inside the visible WebView that is disjoint from every exclusion. Unknown bounds fail closed.
  - **Shareable-page generation.** Increments on every WebView navigation, page load, URL change and sensitive-state change, even when the page returns to the same state.
  - **Event counter.** A monotonic counter that increments on navigation, page load, URL change, sensitive-state change, obscuration, Stop, suspend, screen-off and every other invalidation. Updates to it, the request snapshot, callback validation, ring insertion and invalidation are all serialized.
  - **Capture request.** Before calling `takeScreenshotOfWindow`, the service checks that the grant, attachment, window, banner, geometry and shareable state are all live. It then records `{request_uptime_ms = SystemClock.uptimeMillis(), grant_id, attachment_id, window_id, generation, shareable_page_generation, event_counter}`.
  - **Callback.** The service revalidates the live boundary and requires every recorded value to still match. Any change drops the result before it is encoded, retained or sent. `ScreenshotResult.getTimestamp()` is **never** used for safety or age, because AOSP Android 15 stamps it when the callback arrives.
  - **Publication fence.** A frame passes through these steps in order:
    1. callback
    2. validate the snapshot and the live boundary (serialized)
    3. drop it unless `0 ≤ uptimeMillis() − request_uptime_ms ≤ FRAME_MAX_AGE_MS`
    4. crop and encode
    5. **under the same serialization, immediately before writing to the WSS socket**, recheck the whole snapshot, the event counter, the boundary, the lease, the grant and the age
    6. a bounded write, while still holding the serialization
    
    If any invalidation happens while the frame is being encoded, the frame is discarded. A write that fails or times out also discards the frame and fails closed. Only frames that pass step 5 can enter the ring or be written.
  - **Ring.** The ring holds the last `FRAME_RING` published frames, each with `capture_uptime_ms = request_uptime_ms`, its frame identity, the content rect and the exclusions. The frame is cropped to the content rect before JPEG encoding.
  - **Invalidation.** Any of the following revokes the grant, clears the ring and the tablet's display reference, discards queued frames and input, and requires fresh local approval. It also invalidates the desktop's displayed reference.
    - focus loss or obscuration
    - a sensitive or unknown state
    - a generation change
    - Stop
    - lease or grant expiry
    - detach or disconnect
    - service failure
    - banner loss
    - suspend or screen-off
    - maintenance start
    - the enrollment panel opening
  - **Sensitive states.** Defined by a tablet-side allowlist. Unknown states fail closed. Staff must leave sensitive workflows before support begins.
  - **In-flight gestures.** On invalidation, new dispatch is blocked immediately. An in-flight gesture is cancelled only if cancellation has been verified safe on the K11. Otherwise remote touch is **disabled for that build** (P3k).
- **Lock-task ownership** (P4, verified at P3k).
  - **Who starts and stops it.** Only `MainActivity` does. Outside maintenance, HOME (`LauncherActivity`) launches `MainActivity` with `FLAG_ACTIVITY_NEW_TASK`, reusing its `singleTask` task. It never uses `MULTIPLE_TASK` or `NEW_DOCUMENT`. Boot and package replacement reconcile state and use the same launch path.
  - **Establishing ownership.** This happens only on a controlled transition. All of the following must hold: `MainActivity` is resumed and `isTaskRoot()`, the app is Device Owner, `isLockTaskPermitted()` is true, the keyguard is unlocked, and the global state is `NONE`.
    1. Record the boot count and `getTaskId()`.
    2. Call `startLockTask()`.
    3. Require `LOCK_TASK_MODE_LOCKED` with the same resumed root and the same task ID.
    4. Persist that identity atomically.
  - **What doesn't count as ownership.** `PINNED`, an exception, a pre-existing `LOCKED` state, or a duplicate or unknown root are all failures.
  - **Re-checking on resume.** On every resume, recheck the boot count, task ID, task root, allowlist and `LOCKED` state, and match the ID against `ActivityManager.getAppTasks()` / `AppTask.getTaskInfo()`. A global `LOCKED` state alone never proves ownership. Never stop a task whose ownership is unverified. If the ownership invariant can't be re-established, report a recovery failure; supervised recovery is required.
  - The cached `mInLockTask` flag is removed.
  - At the WebView history root, Back stays inside the kiosk, and `exitToHome()` is unreachable from Back.
- **Supervised USB exit and re-entry (v1).** A person stays at the tablet throughout.
  - **Exit.**
    - Connect an authorized USB host and select the intended device.
    - Run `exit-kiosk.bat` or the manager's Exit Kiosk action. Both force-stop `com.example.webkiosk`, and neither writes a marker.
    - Verify that the global lock-task state is `NONE`. A force-stop or a success message on its own is **not** proof that the tablet has left lock task.
    - Neither exit nor Restore All Apps removes Device Owner. Never use Device Admin deactivation to exit.
  - **Re-entry.**
    - Unlock the tablet, then run `adb -s <serial> shell am start -a android.intent.action.MAIN -c android.intent.category.HOME -n com.example.webkiosk/com.example.kiosklauncher.LauncherActivity`.
    - HOME launches `MainActivity` through the controlled transition. Verify `LOCKED`, the same resumed root and task ID, the persisted identity checked against `getAppTasks()`, and `status.owner_verified=true`. A global `LOCKED` on its own is not enough.
    - If any check fails, keep the tablet supervised and report a recovery failure.
  - **Script changes (P4).**
    - `exit-kiosk.bat` and `kiosk-manager.py` must:
      - select one authorized device
      - check ADB and force-stop failures
      - verify `NONE`
      - report failures rather than claiming success unconditionally
      - drop the Device Admin deactivation advice
      - print the re-entry command and its checks
    - Restore All Apps must report its enumeration and per-package failures, and warn that it enables **every** disabled package.
- **`remote/AdminCommandHandler`** maps a fixed set of ops to DPM calls. There is no shell access.
- **Isolation and navigation.**
  - Staff SSO never runs on the tablet. `ALLOWED_DOMAINS` (`ucdenver.edu`, `cm.maxient.com`, label-bounded subdomains) is unchanged.
  - One canonical URI policy applies to both app-initiated loads and `shouldOverrideUrlLoading`: HTTPS only, a valid host, no userinfo, and a lowercase exact or dot-delimited subdomain match.
  - `kiosk_home` takes no arguments and loads only the compiled `equity_home` (`START_URL`) after the policy check.
  - `kiosk_back` takes no arguments. On the WebView thread it checks `canGoBack()`, validates the previous `copyBackForwardList()` item, and then calls `goBack()`. If any of this is uncertain it sends a negative ack. It never launches an activity.
  - POST and redirect confinement is a release gate (§5.7).

### 2.3 Desktop controller (`kiosk-manager.py` and the new `kiosk_remote/`)
- **`kiosk_remote/auth.py`** handles login (§3.1) and step-up (§3.3).
  - Before opening any `start_url` in the browser, it parses the URL strictly. The URL must be HTTPS with exactly the configured relay scheme, host and effective port. It must have no userinfo and no fragment, and the raw path must start with `/auth/start/`, with no encoded separators or dot segments. If any check fails, it aborts without opening a browser.
- **`kiosk_remote/tls.py`** is a single context factory: `ssl.create_default_context(cafile=certifi.where())`, `CERT_REQUIRED`, `check_hostname=True`.
  - It is used for HTTPS (through a dedicated `urllib` opener with the verified HTTPS handler) and for WSS (`websockets.asyncio.client.connect(..., ssl=ctx)`).
  - **Redirects:** requests that carry credentials or session material never follow them, same-origin included. Every 3xx is terminal.
    - `urllib` uses an `HTTPRedirectHandler` subclass whose `redirect_request` raises `HTTPError`.
    - For websockets 17.4, `WEBSOCKETS_MAX_REDIRECTS=1` is set before the client module is imported, overriding any inherited value. This has to be re-verified on every upgrade.
  - There is no unverified retry. A test CA can only be loaded through a separate test bundle.
- **`kiosk_remote/client.py`** is the WSS client. Its first message is `staff_auth`.
- **`kiosk_remote/viewer.py`** shows the attachment state, the frames, kiosk Back/Home, and admin buttons according to role.
  - **Display boundary.** Viewer state and invalidation are serialized on the **Tk thread**. WSS events from the asyncio thread go into a thread-safe queue that `root.after` polls, and decoded results are marshalled back the same way. For each frame:
    1. On Tk, disable input.
    2. Decode off the UI thread.
    3. On Tk, check that the attachment and grant are current and live.
    4. Commit the frame as the displayed reference.
    5. Send `frame_displayed{attachment_id, grant_id, frame_id, generation}` without blocking.
    6. On Tk, **recheck** that the attachment and grant are still live, and that the displayed reference is still this frame.
    7. Only if every check passes, enable input.
    
    If the send fails, the display is invalidated and input stays disabled. Late frames for a released, stale or replaced attachment or grant are rejected. A delayed decode or continuation can't revive an invalidated or replaced attachment or grant.
  - Any invalidation clears the displayed reference and disables input, including while a decode or commit is still pending.
  - Clicks in the letterbox are rejected.
- The existing USB/ADB features remain. A failed USB install never triggers an uninstall: `kiosk-manager.py` was fixed in P1 and `setup-kiosk.bat` in `9b6946e`.
- **Packaging.**
  - CPython **3.14.10 x64** (3.12 now gets source-only security releases), PyInstaller 6.20.0, websockets 17.4, Pillow 13.0.0 and certifi 2026.10.23.
  - `requirements-win.lock` pins every dependency with a hash, installed with `--require-hashes --only-binary=:all:`.
  - Platform-Tools **37.0.3** comes from `platform-tools_r37.0.3-win.zip`, SHA-256 `89d108360a3bf2924d3bea837239edaccc22fd6ff5befd3787c4348a9fe4f09d`. The build verifies the digest before extracting and never uses `-latest`.
  - The certifi `cacert.pem` is bundled.
  - Signing: Authenticode with SHA-256 and RFC 3161 (`/tr`, `/td SHA256`).
  - Staff are never told to bypass SmartScreen.

## 3. Authentication & authorization

### 3.1 Staff login (desktop ↔ relay ↔ Duo SSO)
The relay is the OIDC confidential client. Its callback is `PUBLIC_BASE_URL/auth/callback`, and the desktop handoff follows RFC 8252 §§7.3 and 8.3 and RFC 9700. Every endpoint below requires `STAFF_LOGIN_ENABLED` and the mode rules in §2.1.

1. **Desktop setup.** The desktop creates random `state_d` and `verifier_d` (32 bytes each, base64url without padding) and computes `challenge_d = b64url(SHA-256(verifier_d))`. **Before** anything else, it binds an exclusive listener on `127.0.0.1:0`, using `SO_EXCLUSIVEADDRUSE` on Windows and never `SO_REUSEADDR`. If the bind fails, login aborts.
2. **Register the transaction.** The desktop calls `POST /auth/transactions {port, state_d, challenge_d}`.
   - The relay requires a port from 1 to 65535 and canonical 43-character base64url values, and rejects unknown or duplicate fields.
   - It returns `{start_url}` pointing to `/auth/start/<start_id>`, with a 256-bit `start_id` that expires after 5 minutes.
   - The desktop validates `start_url` (§2.3) before opening it in the browser.
3. **Browser binding.** `GET /auth/start/<id>` checks the transaction without consuming it.
   - It sets the cookie `__Host-rc_<id>` to a random 256-bit binding, with `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=300` and no Domain. Only the cookie's hash is stored, and a repeat GET doesn't rebind.
   - It serves a confirmation form containing a CSRF token.
   - `POST /auth/continue {start_id, csrf}` requires the cookie, the CSRF token and the exact `Origin`, then atomically moves the transaction from pending to oidc.
4. **Duo round trip.** The relay uses its own `state`, `nonce` and PKCE verifier, and sends `scope=openid email profile` with an S256 challenge.
   - `GET /auth/callback` requires a matching `state`, the same cookie and an unexpired in-progress transaction. It claims the transaction atomically, then exchanges the code using client auth and PKCE.
   - ID token checks:
     - signature against the pinned JWKS, using an allowed algorithm
     - exact `iss`
     - `aud` contains the client ID
     - `azp` equals the client ID if present, and is required when there are multiple audiences
     - `exp` and `iat` within the bounded skew
     - `nonce` matches, and `sub` is present
     - `amr` contains a value from `OIDC_REQUIRED_AMR`
   - MFA is never inferred.
   - The principal `(iss, sub)` must resolve through `ACCESS_MAP`.
   - Any failure ends the transaction, and the cookie is deleted.
5. **Loopback handoff.** The relay mints a single-use `code` (256-bit, valid 60 s) bound to `challenge_d` and the principal, and redirects to `http://127.0.0.1:<port>/cb?code=…&state=<state_d>`.
   - The desktop accepts only `GET /cb` with exactly one `code` and a matching `state_d`. Bad requests are rejected without closing the listener.
   - Request size and read time are bounded, and the Tk UI is never blocked.
   - The listener closes on success, cancel or after 5 minutes.
6. **Session token.** The desktop calls `POST /auth/token {code, verifier_d}`.
   - The relay checks S256 and consumes the code atomically. A wrong verifier doesn't consume a valid code, and the code can produce at most one session.
   - The result is an opaque 256-bit session token: 8 h absolute lifetime, 30 min idle, stored as a hash, revocable.
   - The desktop keeps it in memory only. Duo tokens never leave the relay.
7. **Live expiry.** The limits also apply to open sockets. Idle time is measured from the last authorized substantive op; pings, frames, status messages, acks, denials and `lease_renew` don't reset it. On expiry, logout or revocation, the relay closes the session's sockets and releases its attachments. Re-authenticating never restores anything.

All auth responses, the loopback page included, send `Cache-Control: no-store` and `Referrer-Policy: no-referrer` and load no third-party resources. All of them are rate-limited.

**P5a origin.** P5a runs in `trial` mode, with the relay and Caddy on the Arch box using `tls internal` and `PUBLIC_BASE_URL=https://localhost:<port>`. The exact URI is registered with Duo. Caddy's root is trusted in the test browser and in a trial-only desktop bundle. If Duo rejects localhost, use a temporary public hostname with ACME. Remove the trial trust and any exposure afterwards.

### 3.2 Tablet credential (device ↔ relay)
- **Supervised trigger.** During attended USB setup, kiosk-manager sends `adb shell am broadcast -n com.example.webkiosk/.remote.EnrollmentSetupReceiver -a com.example.webkiosk.action.BEGIN_ENROLLMENT`. It sends no extras and no secrets.
  - **What `DUMP` actually gates.** It is a **privileged-sender** gate, checked on the sender. It trusts shell and every UID holding `DUMP`, including platform and privileged holders and any app explicitly granted `DUMP` over ADB. Ordinary apps can't grant it to themselves.
  - **Receiver checks.** The receiver requires the exact action, no extras, and this app being the active Device Owner. On API 34+, if `getSentFromUid()` returns a known UID, it must be `SHELL_UID`.
  - **Missing UID.** `INVALID_UID` is accepted only under the `DUMP` gate. Android 15's `am broadcast` has no option for sharing the sender's identity, so it isn't evidence of shell or USB.
  - **Handoff to the activity.** The receiver signals the resumed, focused `MainActivity` in-process. Otherwise it fails.
  - **Human presence.** A person at the tablet must tap **Start** before any key is generated. Start confirms someone is physically present; it does not authenticate them.
  - **Holder audit.** `DUMP` holders are audited at setup (§5.3).
- **Enrollment panel states.** **Start** → **Generating key** → **Request created** (request ID and full fingerprint shown) → **Waiting for admin** → **Finish enrollment** → **Proving key** → **Active**.
  - **Timing.** The panel lives for 5 minutes from opening, and that is never extended. The request expires 10 minutes after the relay creates it. Whichever deadline is earlier applies.
  - **Closing.** Focus loss, process death, Cancel or the deadline closes the panel and abandons the attempt. A new attempt needs a new supervised trigger.
  - **Finish.** Finish is enabled only after the authenticated status call reports `approved`. Only `device_ready` completes the panel.
- **Request.**
  1. Start creates a fresh EC P-256 Keystore alias for this attempt.
  2. The tablet calls `POST /enroll/requests {spki_der_b64, security_level}`. The relay returns `{request_id, device_id, fingerprint, expires_at, status_secret}`. The `status_secret` is a 256-bit request-scoped bearer, returned once over HTTPS.
     - The tablet keeps it in private memory only, and never displays it, logs it or sends it over WSS.
     - It authorizes only checking status and abandoning *this* request.
     - The relay stores only a verifier.
  3. The tablet shows `request_id` and the SHA-256 of the DER SPKI, formatted as 32 uppercase hex pairs separated by colons.
- **Approval.** An admin assigns the request to a group they administer, compares the full fingerprint on the physical tablet, and approves (§3.4). Approval doesn't activate the device.
- **Status.**
  - The tablet polls `GET /enroll/requests/<id>/status` with `Authorization: Bearer <status_secret>`, using bounded backoff. The response is `{state, expires_at}`, where `state` is one of `pending`, `approved`, `active`, `rejected`, `expired`, `revoked` or `abandoned`.
  - An unknown ID or a wrong or missing secret gets the same generic `401`. The secret never appears in a URL.
  - Tombstones keep the verifier for a bounded window so the tablet can learn the final outcome.
- **Activation.** **Finish** runs the WSS proof below. The relay moves `approved → active` atomically only if the proof is valid and the original TTL hasn't passed. If `device_ready` is lost, a status of `active` plus a fresh proof recovers it. Retries use fresh challenges and stay within both deadlines.
- **Durable state (crash safety).**
  - **The record.** One app-private SharedPreferences file holds **either** an unfinished marker `{attempt_id, alias, request_may_exist: bool, fingerprint?, request_id?, quarantined: bool}` **or** an active credential `{device_id, alias}`.
    - The fingerprint is the SHA-256 of the DER SPKI, in the display format.
    - The status secret and the private key are never stored in this record.
    - A single in-process owner serializes all access. Every write uses a synchronous `Editor.commit()` off the UI thread, never `apply()`.
    - If a commit fails or its result is uncertain, the socket is closed and recovery starts from durable state.
  - **Commit order after Start:**
    1. Marker with `request_may_exist=false` and `quarantined=false`, before the key is generated.
    2. Generate the key, then commit its **fingerprint**.
    3. Commit `request_may_exist=true` **before** attempting `POST /enroll/requests`. This flag is never reverted.
    4. After a successful response, commit `request_id`.
    5. On a matching `device_ready`, atomically commit `{device_id, alias}` and remove the marker. Only then: show Active, send `hello`, and allow remote use.
  - **Restart**, decided only from the durable record. While a marker exists, remote use and new enrollment are blocked.

| Durable state | Recovery |
|---|---|
| Marker, `request_may_exist=false` | Dispatch is ruled out. Preserve the fingerprint if it's missing, delete the alias, verify `containsAlias` is false, then remove the marker. If any step fails, keep the marker and retry |
| Marker, `request_may_exist=true` | A dispatch, or even a proof, may have happened. Commit `quarantined=true`, preserve the fingerprint before deleting the alias, and verify the deletion. Keep the marker until an authorized reconciliation is done |
| Missing, invalid or inconsistent marker | Fail closed and quarantine. If the device can't be identified, keep the marker for an administrator to investigate |
| Complete credential, no marker | Normal device authentication. Don't delete the alias |

  - **Ground rules.**
    - A crash in the middle of a commit leaves either the complete old record or the complete new one.
    - An alias is never deleted before its fingerprint has been durably saved.
    - An unauthenticated status or a generic WSS failure never clears quarantine.
- **Supervised quarantine reconciliation.**
  - **Trigger.** A separate supervised USB trigger, behind the same `DUMP`, action, no-extras, Device Owner, sender and focus checks as enrollment, opens a **quarantine panel**. It shows the full fingerprint and the request ID if there is one. It can't start enrollment.
  - **Desktop side.** At the tablet, the admin compares the fingerprint, then runs `POST /enroll/reconcile` (§3.4) from the desktop and watches it succeed.
  - **Clearing.** The admin then physically taps **Clear quarantine**. The tablet rechecks the same marker and confirms the alias is absent, then removes the marker. The tablet never accepts the relay's response directly as authorization.
  - **When it stays quarantined.** A failure, a changed marker, a missing fingerprint, or an offline or uncertain result leaves the quarantine in place.
- **Cleanup.**
  - **When.** On cancel, focus loss, process death, expiry, rejection or key replacement.
  - **Marker first.** This is the durable marker described above.
  - **Abandon.** The tablet sends an idempotent `POST /enroll/requests/<id>/abandon` while it still has the secret. Pending or approved becomes `abandoned`, the challenges are invalidated, and if activation raced ahead, the identity is revoked.
  - **Delete the key.** The tablet calls `KeyStore.deleteEntry(alias)` and verifies the key is gone with `containsAlias`. New enrollment and remote use stay blocked until cleanup succeeds.
  - **Uncertain outcome.** If activation might have succeeded and abandon can't be authenticated, the device stays locally unusable until an admin revokes the orphan.
- **StrongBox.** If `FEATURE_STRONGBOX_KEYSTORE` is present, the tablet tries `setIsStrongBoxBacked(true)`. On `StrongBoxUnavailableException` it creates a fresh non-StrongBox key. It reports `KeyInfo.getSecurityLevel()`. A software key requires `accept_software=true` at approval. This is informational, not attestation.
- **Device auth (WSS).**
  1. The tablet sends `device_auth_start{device_id}`.
  2. The relay replies `device_challenge{audience, nonce}`, with a 32-byte nonce bound to the socket and valid for 60 s.
  3. The tablet signs `"CU-DENVER-KIOSK-DEVICE-AUTH" ‖ 0x00 ‖` the fields `"1"`, `audience`, `device_id`, `nonce`, each length-prefixed (u32 big-endian) UTF-8, using `SHA256withECDSA`. It sends `device_auth_proof{device_id, sig}`.
  4. The challenge is consumed on first use.
  5. On success the relay sends `device_ready{device_id}`, and the tablet then sends `hello`.
  6. **Every** failure, whether the device is unknown, pending or revoked, gets the same `DEVICE_AUTH_FAILED` and close.
  - While an enrollment attempt is live, the tablet relies on its authenticated status call to decide whether to wait, offer Finish, retry or stop. Outside enrollment, an auth failure stops automatic retries.
- **States.**
  - `pending → approved` needs the physical comparison plus admin approval.
  - `approved → active` happens on a valid proof within the TTL.
  - `rejected`, `expired` and `abandoned` are terminal.
  - Any non-revoked state can move to `revoked`: tombstone written, challenges invalidated, socket closed, attachment ended, queue discarded.
  - There is one active socket per device.
  - A revoked or abandoned key or ID is never reactivated.

### 3.3 Authorization, support policy, attachments & step-up
- **Live authority.** Roles are cumulative: admin includes operator, which includes viewer. Authority is checked at admission, at enqueue and at the socket writer (§2.1).
  - A **grant** is a tablet-issued local approval that is unexpired, unrevoked, and bound to the current session, device and kiosk attachment. Pending, denied, expired or stopped approvals are **no grant**.
  - The tablet independently rechecks its grant, its lease and the boundary.
- **Policy table.** `*` means any value. `G` means a valid grant and `N` means no grant. Anything not listed is denied.

| Op | Min role | Attachment held | Grant | Policy | Decision / conditions |
|---|---|---|---|---|---|
| `list_devices` | viewer | * | * | * | Allowed. In-scope devices only, content-free state |
| `attach{status\|kiosk}` | viewer | none | N | * | Allowed in scope, subject to the lease rules. Kiosk only *requests* approval |
| `attach{status\|kiosk}` | viewer | status | N | * | Owning session and socket only. Same mode returns the current state with no extension. Kiosk replaces the attachment and requests approval |
| `attach{status\|kiosk}` | viewer | kiosk | * | * | Owning session and socket only. Same mode returns the current state with no extension. Status replaces the attachment and revokes the grant |
| `detach`, `lease_renew` | viewer | status/kiosk | * | * | Owning session plus the current `attachment_id` |
| frames, `frame_displayed` | viewer | kiosk | G | * | After the banner and boundary checks |
| `tap`, `swipe`, `long_press`, `kiosk_back`, `kiosk_home`, `reload_kiosk` | operator | kiosk | G | * | Coordinate ops also need a valid frame binding (§4) |
| `lock_now`, `reboot` | admin | kiosk | G | * | Allowed |
| `kiosk_home`, `reload_kiosk` | operator | status | N | `status_admin` | Allowed |
| `lock_now`, `reboot` | admin | status | N | `status_admin` | Allowed |
| `wipe` | admin | kiosk | G | * | `DESTRUCTIVE_ACTIONS_ENABLED`, confirmation, and a step-up consumed at dispatch |
| `enter_kiosk`, `exit_kiosk` | — | — | — | — | **Denied in v1** (reserved; see Appendix A) |
| enrollment list, assign, approve, reject | admin | — | — | * | §3.4 |
| device revoke, scope reassignment | admin | — | — | * | In scope. Reassignment needs authority over both groups |
| session revoke | admin | — | — | * | Only if the target's whole current scope is within the admin's |
| audit read | admin | — | — | * | In-scope events. Device-less events need `audit_wide` |
| logout | viewer | — | — | * | Own session |
| `navigate`, unknown | — | — | — | — | Denied |

  - **Status-admin exceptions.** The only `status_admin` exceptions are the four ops above, on a status lease. Neither policy allows unattended wipe or exit.
  - **Errors.**
    - `FORBIDDEN`: role or scope.
    - `LEASE_BUSY`: another owner holds the attachment.
    - `LEASE_REQUIRED`: the attachment is absent, expired or mismatched.
    - `GRANT_REQUIRED`: no valid grant.
    - `DISABLED_BY_POLICY`: blocked by policy or a gate.
- **Attachment lifecycle.**
  - **Basics.** There is at most one live attachment per tablet. Its states are `none`, `status`, `pending_approval`, `granted` and `released`, and `released` is terminal for that ID.
  - **IDs.** The relay mints a fresh 128-bit `attachment_id` on every acquisition and never reuses one. The ID is not a credential.
  - **Lease.** `LEASE_IDLE_S` counts from acquisition, from the last authorized substantive op, or from an accepted `lease_renew`. Renewal doesn't extend consent or the session idle timer.
  - **Telling the tablet.** Every acquisition sends `attach_open`. Every renewal sends `lease_renewed` before any work that depends on it is forwarded. `lease_ms` is the relay's remaining lease, capped at `LEASE_IDLE_S`.

| From | Trigger (atomic) | To | Side effects |
|---|---|---|---|
| none | authorized `attach{status}` | status | Mint an ID, start the lease, send `attach_open{mode:status}`, reply `attach_result` |
| none | authorized `attach{kiosk}` | pending_approval | Mint an ID, start the lease, send `attach_open{mode:kiosk, display_name}`. The tablet starts its local approval deadline |
| status | same owner requests kiosk | pending_approval | `detach(old)`, then `attach_open(new, kiosk)`. Nothing carries over |
| pending_approval / granted | same owner requests status | status | `detach(old)`, which stops the prompt, capture and input and clears queues, then `attach_open(new, status)` |
| any live | same owner, same mode | unchanged | Return the current state. Nothing is extended |
| any live | different owner | unchanged | `LEASE_BUSY` |
| pending_approval | matching `support_granted` before all deadlines | granted | Bind the grant and notify the owner |
| pending_approval | deny, no UI, or timeout | released | Notify. Late replies are ignored |
| granted | Stop, grant expiry, or §2.2 invalidation | released | Stop capture and input, discard queues, notify |
| any live | detach, lease expiry (relay **or** tablet), disconnect, session end, role or scope removal, device revocation, maintenance start | released | Invalidate everything. Unacked dispatched commands become `OUTCOME_UNKNOWN` |
| any live | valid `lease_renew` | unchanged | Reset the lease, send `lease_renewed` |

  Each transition commits before its notifications are sent. Nothing is restored after a reconnect or a relay restart.
- **Step-up for wipe**, the only step-up op in v1.
  1. **Initiation.** The desktop confirms the exact device and op, generates fresh `state_d`, `verifier_d` and `challenge_d`, and opens an exclusive listener. It then calls `POST /auth/step-up/transactions {device_id, op, port, state_d, challenge_d, confirmed:true}` with the session bearer.
     - Under the device lock, the relay resolves the device's **current kiosk attachment owned by this same session and its live socket**, with a valid grant and lease, and builds a `StepUpContext`.
     - The transaction is bound to the principal, session, device, op, confirmation, socket, attachment and grant.
     - Only one step-up may be pending per (session, device, op). A second one gets `409`.
  2. **Browser binding.** The relay runs the §3.1 browser binding with `max_age=0`. It doesn't also send `prompt=login`, since Duo documents the two as equivalent.
  3. **Callback checks.** The §3.1 checks, plus:
     - the same `(iss, sub)`
     - an accepted `amr`
     - a numeric `auth_time` that is at or after initiation, at most 5 minutes old, and no further in the future than the allowed skew
     
     **A missing `auth_time` denies the step-up.** `amr` plus `auth_time` still don't prove a fresh second factor, so P5a and P5b must establish that.
  4. **Loopback handoff.** The code is valid for 60 s or less.
  5. **Redemption.** The desktop calls `POST /auth/step-up/token {code, verifier_d}` with the **original bearer**.
     - The relay re-resolves the attachment and compares the bindings, then rechecks freshness, authority and the gate.
     - It returns a single-use `step_up_id` (stored as a hash) that expires at the earlier of `auth_time` + 5 min and the session's expiry.
  6. **Dispatch.** Dispatch uses the two-phase wipe reservation (§4). Step-up consumption happens only at the `execute` writer commit (§2.1). It re-resolves and compares the attachment, consumes atomically, and audits before the send.
     - Replacement, disconnect, expiry or revocation invalidates the transaction and the grant.
     - A consumed grant is never restored.
  - The base login gate isn't enough for these ops. Trial results never enable production gates.
- **Audit.** The log is append-only and written only by the relay. Each event records:
  - `event_id` and UTC time
  - `(iss, sub)` and `session_id`
  - `device_id` and op
  - decision and reason
  - `command_id` and outcome
  
  It covers:
  - sessions, attachments and leases
  - local grant, deny and stop
  - enrollment assignment, approval, rejection and abandonment
  - revocations and denials
  - every step-up stage
  - destructive intent, recorded **before** dispatch, and its outcome
  
  It never contains secrets, raw URLs, command arguments, frames or student content. If the audit write fails, the op isn't dispatched.

### 3.4 Management HTTP API
- **Conventions.**
  - JSON bodies reject unknown and duplicate fields.
  - Admin routes take a `Bearer` session token, never a query token, and check authorization live at execution.
  - Every response sets `no-store`.
  - Errors: `400 INVALID_REQUEST`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `410 EXPIRED`, `429 RATE_LIMITED`, `503 UNAVAILABLE`.
  - Unknown or out-of-scope targets return `404`.
  - Denials are audited. A mutation fails if its audit write fails, and the change is rolled back.
  - Cursors are opaque and integrity-protected, and each page rechecks scope.
- **Enrollment scope.**
  - **Who sees what.** Unassigned pending requests are visible to admins who can assign at least one group, with limited fields only. Once a request is assigned, only admins of that group can see it.
  - **Assignment.** `PUT /devices/<id>/scope` targets a group the admin administers. Reassigning needs authority over both groups.
  - **Approval** requires all of: a pending, assigned, unexpired request; current authority over the group; a full fingerprint match; and software-key consent if the key is software-backed.
  - **Atomicity.** Assignment and approval each run as one transaction with live authority, state, TTL and scope checks plus the audit write. Competing operations are serialized with conditional updates.
  - **Revoked devices** can't be reassigned.

| Route | Auth; request | Success |
|---|---|---|
| `POST /enroll/requests` | unauthenticated supervised tablet; `{spki_der_b64, security_level}` | `201 {request_id, device_id, fingerprint, expires_at, status_secret}` |
| `GET /enroll/requests/<id>/status` | `Bearer <status_secret>` | `200 {state, expires_at}` |
| `POST /enroll/requests/<id>/abandon` | `Bearer <status_secret>`; `{}` | `200 {request_id, state}` (idempotent) |
| `GET /enroll/requests?cursor&limit` | admin | `200 {items:[{request_id, device_id, fingerprint, security_level, group_id\|null, expires_at}], next_cursor}` |
| `PUT /devices/<device_id>/scope` | admin; `{group_id}` | `200 {device_id, group_id}` |
| `POST /enroll/requests/<id>/approve` | admin; `{fingerprint, accept_software}` | `200 {request_id, device_id, group_id, state:"approved"}` |
| `POST /enroll/requests/<id>/reject` | admin; `{}` | `200 {request_id, state:"rejected"}` |
| `GET /audit?cursor&limit` | admin | `200 {items:[AuditEvent…], next_cursor}` |
| `POST /devices/<device_id>/revoke` | admin; `{}` | `200 {device_id, state:"revoked"}` |
| `POST /sessions/<session_id>/revoke` | admin; `{}` | `200 {session_id, state:"revoked"}` |
| `POST /enroll/reconcile` | admin; `{fingerprint, request_id?}` | `200 {fingerprint, request_id?, outcome:"cleared"}`. Clearance is returned **only** after an authoritative search by fingerprint, matching the request ID if one is given. Every match must be in the admin's live scope and confirmed absent or terminal, or else revoked through the normal fencing. The search is serialized against enrollment and activation, and fingerprint tombstones are kept. A mismatch, ambiguity, an incomplete inventory or an out-of-scope match never clears. If the audit write fails, everything rolls back. The operation is idempotent |
| `POST /auth/logout` | own session; `{}` | `200 {state:"logged_out"}` |
| §3.1 and §3.3 auth and step-up routes | as specified | |

A status secret is never accepted as a staff session. A state conflict returns `409`, and an expired request returns `410`.

## 4. Wire protocol (v1)
WSS carries JSON control messages and binary frames. The authoritative definition is `docs/remote-control/protocol/v1.schema.json` together with `v1.md`. The lead owns both, and they are frozen at P1a, with fixtures and an error and reason registry checked in CI.

Every message uses the envelope `{"v":1,"type":…,"id":…}`. Replies echo the request `id`; unsolicited events use `id:null`. Unknown versions, types, fields or codes fail closed. Scoped messages in both directions pass the socket-writer fence (§2.1).

- **Staff handshake.**
  - Within 10 s, the first and only pre-auth message must be `staff_auth{token}`. The relay replies `staff_ready{session_id, display_name, expires_at}`.
  - It never echoes the token, and never accepts it from a URL or query string.
  - Any other message, a bad token, or a timeout gets a generic error and the socket is closed.
- **Device handshake.** `device_auth_start` → `device_challenge` → `device_auth_proof` → `device_ready`, then the device sends `hello{device_id, app_version, caps}`.
- **IDs.** The envelope `id` is used **only** to match a request with its reply. `command_id` is a separate field, carried unchanged on both hops. Deduplication is keyed by `(attachment_id, command_id)` and never by the envelope `id`.
- **Staff → relay.**
  - `list_devices`
  - `attach{device_id, mode}`, `detach{device_id, attachment_id}`, `lease_renew{device_id, attachment_id}`
  - `frame_displayed{attachment_id, grant_id, frame_id, generation}`
  - `cmd{id, command_id, device_id, attachment_id, op, args, grant_id?, frame_id?, generation?, step_up_id?}`
  - `logout`
- **Relay → staff.**
  - `staff_ready`, `devices{items:[{device_id, state, caps}], next_cursor}`
  - `attach_result{device_id, attachment_id, mode, state}`, `detach_result`, `lease_renew_result{…, expires_at}`
  - `support_pending`, `support_granted{…, grant_id, expires_at}`, `support_stopped{…, reason}`, `attachment_ended{…, reason}`
  - `device_status`, `device_disconnected`
  - `cmd_result{device_id, attachment_id, command_id, state, error}`
  - binary `frame`, `error`, `session_ended`, `logout_result`
- **Relay → device.**
  - `device_challenge`, `device_ready`
  - `attach_open{attachment_id, mode, display_name?, lease_ms}`, `lease_renewed{attachment_id, lease_ms}`, `detach{attachment_id}`
  - `frame_displayed`
  - `cmd{id, command_id, attachment_id, op, args, deadline_ms, grant_id?, frame_id?, generation?}`
  - `reserve{command_id, op:"wipe", attachment_id, ttl_ms}`, `execute{reservation_id, command_id, attachment_id}`
- **Device → relay.**
  - `hello`
  - `status{lock_task_state, owner_verified, destination_id|null, battery, wifi, caps}`. No URL is ever included.
  - `support_pending`, `support_granted{attachment_id, grant_id, remaining_ms}`, `support_stopped{attachment_id, reason}`, `attachment_expired{attachment_id, reason}`
  - `reserved{command_id, attachment_id, reservation_id}`
  - `ack{command_id, attachment_id, ok, err}` (unsolicited terminal result), binary `frame`
- **Terminal results.**
  - The relay accepts an `ack` only from the authenticated device connection that the dispatch was recorded against, and only if both IDs match. It records the result once.
  - A tablet may still send an `ack` after release, for work it had already dispatched. That ack never restores authority, and its content is never forwarded to a replacement attachment.
  - A late ack that arrives after `OUTCOME_UNKNOWN` has been reported is audited but doesn't change the reported result.
  - Dedup tombstones are kept for `ACK_RESULT_WINDOW_S`.
- **Relay frame fence.** Frames and `frame_displayed` are forwarded only for the current, live kiosk attachment and grant. This is checked again at the serialized writer, and queued frames are purged on invalidation. After invalidation, the tablet ignores late display acks, so they never re-establish a reference.
- **`deadline_ms`.** This is a positive relative TTL, at most `CMD_DEADLINE_S`.
  - The relay starts the deadline at admission and sends whatever remains when it writes the message.
  - The tablet starts its own deadline from `elapsedRealtime()` at receipt, and rejects the command at or after that point, including immediately before dispatch.
  - The transit budget is `CMD_TRANSIT_BUDGET_MS`. It is a deployment assumption that the tablet can't verify. Within it, the tablet may overrun the relay deadline by at most that amount.
- **Frames.** Each frame is a 1-byte type, then a header `{attachment_id, grant_id, frame_id, generation, width, height}`, then the JPEG of the content rect. Capture time is tablet-local metadata (`request_uptime_ms`), never sent by or trusted from the desktop.
- **Coordinate commands.** `tap{x,y}`, `long_press{x,y}` and `swipe{x1,y1,x2,y2,ms}` carry all four binding IDs on both hops, and the relay doesn't change them. Coordinates are finite values in [0,1], relative to the crop.
  - Immediately before dispatch the tablet atomically checks all of the following:
    - the live lease, grant, deadline, window and banner
    - a ring record that matches all four IDs, **is the latest acknowledged displayed frame**, and has the current generation, window, rect and exclusions
    - `0 ≤ uptimeMillis() − capture_uptime_ms ≤ FRAME_MAX_AGE_MS`
    - every point of the path, interpolation included, lies inside the content rect and outside every exclusion
  - Validation, invalidation and dispatch are serialized.
  - `dispatchGesture` only reports submission. The callback decides the outcome; if there is none, the result is `OUTCOME_UNKNOWN`.
  - A display ack for an older or unknown frame can't roll the reference back.
- **Other ops.** `kiosk_back`, `kiosk_home`, `reload_kiosk`, `lock_now`, `reboot` and `wipe` take no arguments. `navigate`, `enter_kiosk` and `exit_kiosk` are reserved and always denied (`DISABLED_BY_POLICY`).
- **Wipe reservation.** Wipe is two-phase. It doesn't depend on synchronized clocks or on a transit bound.
  1. **Reserve.** After normal authorization, and before the step-up is consumed, the relay sends `reserve{…, ttl_ms}`. `ttl_ms` is no more than the remaining command deadline.
     - The tablet checks the kiosk attachment, lease, grant and policy, and deduplicates the request.
     - It creates an unpredictable, single-use `reservation_id`, bound to the command, the attachment and this connection, with a local monotonic expiry.
     - It replies `reserved`.
  2. **Execute.** At the execute writer (§2.1), the relay checks:
     - the binding
     - authorization
     - the gate
     - its own deadline
     - the matching reservation
     
     Then it **consumes the step-up**, audits, and sends `execute{reservation_id}` with a bounded send. It never consumes the step-up for a missing or stale reservation.
  3. **Tablet dispatch.** Immediately before dispatch, the tablet atomically checks that the reservation is unused and hasn't reached its local expiry. It also rechecks the attachment, lease, grant and policy. It marks the reservation used, then calls `wipeDevice(0)`.
     - A duplicate `reserve` returns the same reservation while it's still live. A duplicate `execute` never dispatches again.
     - If the outcome is uncertain, it is `OUTCOME_UNKNOWN`.
  
  Ordinary commands keep the receipt-relative `deadline_ms` and the transit assumption.
- **Wipe transitions** for one `(attachment_id, command_id)`. Every relay writer check and send holds the §2.1 device lock. A failure before the send is never `OUTCOME_UNKNOWN`.

| Transition | Writer check | Consume step-up | Mark dispatch | Intent audit | Deadline recheck |
|---|---|---|---|---|---|
| admitted → reserve_sent | Rebuild the live context: session, role, scope, device, socket, attachment, lease, grant, maintenance, gate | No | No | No | Before the send. `ttl_ms` and the send timeout are both capped at the remaining budget |
| reserve_sent → reserved | Match the authenticated connection, both IDs and the reservation | No | No | No | A response at or after the relay deadline is rejected |
| reserved → execute_committing | Repeat the live checks. The reservation must match. Validate and consume the step-up atomically | **Yes, once** | No | No | Before consumption |
| execute_committing → execute_sent | Runs after the audit write succeeds | Already consumed | **Correlation is registered before the send attempt** | **Yes, before the recheck** | **After the audit write**, recheck the session, lease, grant and command deadlines. The send timeout is capped at the remaining budget. If the budget is ≤0, nothing is sent |
| execute_sent → terminal | The ack must come from the original authenticated connection and match both IDs | No | Already registered | Outcome recorded | The tablet checks its reservation expiry immediately before dispatch |
| any earlier state → terminal | Denial, expiry, disconnect, a failed consumption or a failed audit prevents the execute | Consumed only if consumption already succeeded. Never restored | No | Only if the audit write succeeded | Expiry → `rejected_expired`, anything else → `failed` |

  - **What `execute_sent` means.** It means a send was *attempted*, including one that failed or stalled. If the send fails or stalls, the socket is closed.
  - **Ack mapping.**
    - A definitive success → `ok`.
    - `RESERVATION_EXPIRED` → `rejected_expired`.
    - Any other negative ack → `failed`.
    - Only an attempted execute that never gets a definitive ack is `OUTCOME_UNKNOWN`.
  - **Plain wipe commands.** The relay never emits a plain `cmd{op:"wipe"}`, and the tablet rejects one without dispatching it.
  - **Tablet-side `execute` checks.**
    - The tablet checks `execute{reservation_id, command_id, attachment_id}` against the reservation and the connection.
    - If the reservation has expired or is unknown, the tablet sends `ack{command_id, attachment_id, ok:false, err:"RESERVATION_EXPIRED"}` and doesn't wipe.
    - A duplicate `execute` never dispatches twice.
  - **Late acks.** A late ack from the original connection after `OUTCOME_UNKNOWN` only reconciles the audit record.
- **Terminal reasons** for `support_stopped` and `attachment_ended`. This is a closed registry. The desktop shows a fixed local string and never page content.

| Reason | Origin | Desktop shows |
|---|---|---|
| `local_stop` | tablet | Support stopped locally |
| `grant_expired` | tablet or relay | Support approval expired |
| `lease_expired` | tablet or relay | Attachment expired |
| `focus_lost` | tablet | Kiosk lost focus |
| `obscured` | tablet | Kiosk obscured |
| `sensitive_state` | tablet | Kiosk unavailable for sharing (also covers unknown states) |
| `geometry_changed` | tablet | Kiosk view changed (also covers navigation, page load and URL generation) |
| `banner_lost` | tablet | Support banner unavailable |
| `suspend` / `screen_off` | tablet | Tablet suspended / screen off |
| `service_failure` | tablet | Tablet service unavailable |
| `enrollment_opened` | tablet | Enrollment opened |
| `detached` / `disconnected` | relay | Attachment ended / Connection lost |
| `revoked` | relay | Access revoked (also covers session end and device revocation) |
| `policy_changed` | relay | Support policy changed (also covers scope, role or policy changes) |

  - **Validation.** The relay checks each tablet reason against its permitted origin, and rejects unknown reasons.
  - **Races.** The first serialized terminal transition wins.
  - **Stale IDs.** Stale or duplicate IDs never affect a replacement attachment.
  - **Connection loss** clears the viewer, whether or not a terminal event arrives.
- **Admission.**
  - Queues and dedup are scoped to `(attachment_id, command_id)` on both the relay and the tablet, with atomic reservation and outcomes retained for the attachment's lifetime.
    - A duplicate returns the recorded outcome.
    - The same ID with different content returns `DUPLICATE_ID_CONFLICT`.
    - When the retained set is full, new commands are rejected.
  - Limits: 32 queued per device, 20/s per session, 5 s deadline. Exceeding them returns `OVERLOADED`.
  - Under pressure, frames are dropped, never commands.
  - On invalidation or replacement, queued work is discarded.
  - A dispatched command with no ack resolves to `OUTCOME_UNKNOWN` and is never replayed.
- **Errors.** `{"v":1,"type":"error","id":<req|null>,"error":{"code"}}`. The registry codes are:
  - Auth and policy: `UNAUTHENTICATED`, `FORBIDDEN`, `SESSION_EXPIRED`, `DISABLED_BY_POLICY`, `DEVICE_AUTH_FAILED`.
  - Attachment and grant: `LEASE_BUSY`, `LEASE_REQUIRED`, `GRANT_REQUIRED`, `ATTACHMENT_STALE`, `GRANT_STALE`.
  - Frame binding: `FRAME_UNKNOWN`, `FRAME_NOT_DISPLAYED`, `FRAME_EXPIRED`, `GENERATION_STALE`, `GESTURE_OUT_OF_BOUNDS`.
  - Admission and delivery: `OVERLOADED`, `DEADLINE_EXCEEDED`, `DUPLICATE_ID_CONFLICT`, `OUTCOME_UNKNOWN`, `DISCONNECTED`, `RESERVATION_EXPIRED` (also valid as a negative-ack `err`).
  - Message validity: `UNSUPPORTED`, `INVALID_MESSAGE`.
  
  Errors never contain secrets, URLs, args or stack traces.
- **Admin semantics.**
  - **`wipe`** calls `DevicePolicyManager.wipeDevice(0)` and is rejected below API 34. Intent is audited first. The ack doesn't prove the reset completed.
  - **`exit_kiosk`** is denied in v1. Maintenance exit is a supervised local USB action (`exit-kiosk.bat`). The remote design is deferred to Appendix A.

## 5. Android 15 edge cases
1. **Screen view.**
   - v1 uses **only** locally approved, request-bound, window-scoped a11y capture on API 34+, cropped to the content rect.
   - Projection, if it comes later, needs fresh local consent per session. Neither Device Owner nor a11y can accept that consent.
   - Android 15 QPR1+ adds the projection chip and auto-stop on lock.
   - Gesture containment is enforced by the app and is a P3k gate.
2. **Lock task and system UI.**
   - On the K11, record the deployed `setLockTaskFeatures` flags, immersive mode and overlay behaviour.
   - Test the baseline, `SYSTEM_INFO` and `BLOCK_ACTIVITY_START_IN_TASK`.
   - `setLockTaskFeatures` controls system UI only; it doesn't control re-entry.
   - Verify the panels under the deployed flags.
3. **Supervised setup.**
   1. **Accessibility.** **Append** our component to `enabled_accessibility_services`, keeping every existing entry, and set `accessibility_enabled=1`. Read both back and confirm the service binds.
      - If that fails, use the supervised Settings flow and approve restricted settings. If it still fails, setup fails.
      - `setPermittedAccessibilityServices` takes package names. Leave a null policy alone, and keep any existing entries.
   2. **`DUMP` holder audit.** Enumerate installed packages for every relevant user, and record each package's granted permissions (including per-user grants) from `dumpsys package` against an approved baseline. `pm list permissions -f` shows the permission definition only, not who holds it. Investigate unexpected holders and remove them before enrollment, and repeat the audit after package changes.
   3. **Reboot** and verify the settings persisted.
   4. **Lock down debugging.** Disable USB and wireless debugging, revoke authorizations, and verify the old host can't connect.
4. **FGS.** v1 has only the `specialUse` agent.
   - The projection order is:
     1. local visible activity
     2. `createScreenCaptureIntent`
     3. consent
     4. start the `mediaProjection` FGS
     5. `getMediaProjection`
     6. register the callback
     7. one VirtualDisplay
   - Consent is single-use, and there is no auto-restart.
5. **Boot.** `BootReceiver` handles `BOOT_COMPLETED` only, using credential-encrypted storage. On boot it:
   - starts the agent
   - verifies Device Owner policy
   - reconciles maintenance
   - launches the owner through the controlled path
   
   Failures are reported. Boot-time foreground-service type limits still apply, and delivery may be delayed.
6. **Idle and network.**
   - **Battery.** Report `isIgnoringBatteryOptimizations` at setup.
   - **Reconnect.** Keep one connection and use full-jitter backoff from 1 s to 60 s. The default-network callback triggers a single attempt.
   - **Auth failure.** A generic WSS auth failure stops reconnecting. During a live enrollment attempt, the bounded authenticated status recovery (§3.2) applies instead.
   - **Reachability.** A 25 s ping isn't a reachability guarantee through Doze. The relay marks a device offline after missed heartbeats.
7. **Network security and WebView confinement.**
   - Relay traffic is HTTPS/WSS only, and the relay is not added to `ALLOWED_DOMAINS`.
   - Inventory the student flows, then replace `usesCleartextTraffic=true` with a network-security-config that denies cleartext.
   - **Release gate:** POST and redirect confinement must be enforced at a trusted web boundary, such as CSP `form-action` plus controlled redirects. If that can't be proven, **remote-control release is blocked**.
8. **minSdk.** It stays at 21. Features are gated at runtime: gestures need 24, window screenshots need 34.

## 6. Root vs. Device Owner capability matrix

| Capability | Device Owner + A11y (+MP later) | ADB (supervised USB) | Needs true root / system signature |
|---|---|---|---|
| Lock task / kiosk allowlist | ✅ DPC `setLockTaskPackages`; `MainActivity` owns lock task through controlled transitions | Provisions the Device Owner | — |
| Reboot, lock, wipe | ✅ DPM; `wipeDevice(0)` on API 34+ | Device-dependent | — |
| Silent install/uninstall | ✅ PackageInstaller (DO) | ✅ | — |
| Wi-Fi, user restrictions, policies | ✅ DPM | partial | — |
| Remote touch input | ✅ A11y `dispatchGesture`, kiosk-scoped and frame-bound | ✅ `input` | Silent injection without A11y (INJECT_EVENTS) |
| Screen view | ✅ A11y kiosk-window screenshot, API 34+, best effort, local opt-in | ✅ `screencap`/`screenrecord` | Silent full-fps capture with no consent or indicator |
| Arbitrary shell | ❌ (by design) | ✅ shell UID | uid 0, /system edits |
| Other apps' data, /system, kernel | ❌ | ❌ | ✅ |

Rooting a locked-bootloader Lenovo would trip verified boot and Play Integrity, so it is out of scope.

## 7. Phases

| Phase | Owner | Deliverable | Verification |
|---|---|---|---|
| P0 | Lead | This document, reviewed | Review gate |
| P1 ✅ | Android agent | Gradle migration, wrappers, fail-closed release signing, `apk-info.txt`, safe USB install, CI on Gradle (`b53269e`, plus `9b6946e` for `setup-kiosk.bat`) | `assembleDebug`, badging identical, signer checks, 5 unit tests |
| P1b | Android agent | **Publication gate** (§7.2). It must merge, with its matrix passing, before **any** remote implementation merges, including P2's `relay/` on its own | Full class × event matrix in CI |
| P1a | Lead + P2/P3 | Freeze `contracts.py`, `protocol/v1.schema.json`, `v1.md`, the fixtures and the registry. Fixture drafting may start earlier | Both owners review the same commit, recorded in HANDOFF |
| P2 | Auth & Security agent | `relay/auth/` and `store.py`: §3.1–§3.4, including live authorization, revision publication and enrollment status/abandon | pytest with a mock OIDC IdP and JWKS, plus ruff |
| P3 | Desktop/Relay agent | `relay/ws.py`: attachments, lifecycle messages, queues, socket-writer fence. `kiosk_remote/`: auth, tls (redirect rejection, `start_url` validation), client, viewer | pytest with a fake tablet. Writer-race barriers. TLS and redirect negative tests |
| P3i | Lead | Compose P2 and P3: `create_app`, config, migrations, `deploy/` | Mock IdP → relay → fake tablet. Caddy checks: loopback backend, sentinel log redaction, live expiry and revocation |
| P3k | Android agent + user | **K11 feasibility spike** | See "P3k checks" below |
| P4 | Android agent | Agent, enrollment, kiosk capture and input, DPM commands, lock-task ownership and manifest switch, within capabilities P3k verified | Unit tests, mock relay, API 35 emulator, K11 checkpoint, §7.1 upgrade. See "P4 manifest-switch gates" below |
| P5a | Lead + user | `trial` mode, Duo trial, local relay | Trial login turned on for testing. Record sanitized `amr`, `auth_time`, policy, and the bypass, skipped-MFA and remembered-device results. Step-up with a harmless substitute op. Wipe stays off |
| P5b | Lead + user + CU OIT | CU tenant, `production` mode | Approve the evidence for issuer, RP, base policy and `amr` meaning, including negative tests, **before** enabling staff login. Separately prove `auth_time` and a fresh factor under `max_age=0` before enabling the wipe gate |
| P6 | Desktop agent | Locked, signed Windows x64 release | CI signs and verifies. §7.3 run on the CU images |

**P3k checks** (on the K11):
- content-rect crop and exclusions
- request-bound capture across navigation, Stop and suspend
- gesture containment through invalidation; if containment fails, remote touch is disabled
- a11y enablement and persistence
- the panels under the deployed flags
- `DUMP` gate: the shell route works, an ordinary app is denied, holder inventory, debugging lockdown
- enrollment through Finish, including cancel and expiry cleanup
- lock-task ownership: HOME, boot, upgrade
- that the wipe reservation's local deadline is enforced, and that its single use holds across disconnect and restart
- boot behaviour
- the projection dialog

**P4 manifest-switch gates** (on the K11):
- cold boot through first unlock to the verified owner
- signed in-place upgrade
- the student HOME, Back, Chrome and Settings/Wi-Fi paths
- no unintended second locked task, or unlocked task

**Order.**
1. P1 → P1b.
2. P1a must be settled before P2 and P3, which then run in parallel. P1b must merge before any P2, P3 or P4 code.
3. P3i and P3k both come before P4.
4. If the K11 fails a check, that path is disabled. The emulator never stands in for the K11.

### 7.1 APK signing & fleet upgrade
- **Inventory.** On each tablet, run `adb shell pm path` and `adb pull`, then `apksigner verify --print-certs`. Record the device, version and signer. Today's CI creates a fresh debug key for each run.
- **Custody.**
  - The release key comes from `KIOSK_KEYSTORE_B64`, `KIOSK_KEYSTORE_PASS` and `KIOSK_KEYSTORE_ALIAS`, and the approved fingerprint from the repository variable `KIOSK_CERT_SHA256`.
  - A release build fails if any of these is missing or the fingerprint doesn't match. It never auto-generates a key.
  - PR builds are debug only.
  - Key rotation uses a v3 lineage (`apksigner rotate`). A lineage can't recover a key that's already lost.
- **USB install.** `adb install -r`. On any failure, stop and report. Never uninstall. This is implemented in `kiosk-manager.py` and `setup-kiosk.bat`.
- **Unrecoverable signer.** Use supervised per-device reprovisioning:
  1. Record the device and check FRP.
  2. Revoke its relay identity.
  3. Factory reset it.
  4. Install the approved APK.
  5. Provision Device Owner and lock task.
  6. Re-enroll.
- **Upgrade acceptance (K11).**
  1. Record the device, the installed version and signer, the Device Owner, the allowlist, the task identity and the device-key fingerprint.
  2. On a locked tablet, use the matching signer to `adb install -r` a higher version, then reboot. Verify that the owner and allowlist are unchanged and that the controlled ownership is re-established, with `LOCKED` and `status.owner_verified=true`. Verify that the **same** key signs a fresh challenge.
  3. On a separate fixture, do the supervised USB exit (§2.2) and verify `NONE`. Then `install -r` the higher version while the tablet is exited. Reboot, do the supervised re-entry, and run the ownership checks again. Verify the owner, allowlist and key.
  4. Attempt an incompatibly signed upgrade and confirm that it fails without uninstalling.

### 7.2 Publication gate (P1b)
- **Classification.** Each candidate is classified on three axes: capability (`usb-only` or `remote-capable`), APK (`release` or `debug`), and Windows exe (`authenticode-signed` or `unsigned`).
  - `REMOTE_FEATURES` must be exactly `0` or `1`.
  - CI inspects both the checkout and the package contents against a maintained inventory. If `relay/`, `kiosk_remote/` or remote Android code is present, the candidate is remote-capable. A mismatch or an unknown layout fails.
- **Verification.**
  - **APK.** Verify independently with `apksigner verify --print-certs` and a hash, and compare the result to `apk-info.txt`. A release APK also needs the approved fingerprint. Debug is never relabelled as release.
  - **Every final EXE.** Extract the APK without executing anything, using a pinned PyInstaller extractor, after signing if the EXE is signed. This applies to unsigned USB-debug EXEs too. Require exactly the expected APK, with a matching hash and signer.
  - **DMG.** Mount the final DMG read-only and verify every APK copy inside it.
  - **Record** the commit, class, digests and fingerprints.
- **Windows signing and publisher.**
  - **Sign** with SHA-256 and RFC 3161 (`/tr`, `/td SHA256`).
  - **Verify** with `signtool verify /v /pa /all /tw`. Any warning or error fails the check, even if the exit code is 0.
  - **Signer.** Enumerate every signature on the final EXE. Each signer thumbprint must equal the non-empty repository variable `WINDOWS_SIGNER_THUMBPRINT`. A missing pin, an unmatched signer or an extra unverifiable signature fails.
  - **Timestamps.** For each signature, a pinned PKCS#7 parser (pinned by version and digest) must find an RFC 3161 token (OID `1.3.6.1.4.1.311.3.3.1`) and validate:
    - the token's signature
    - the TSA chain
    - the time
    - the message imprint against that signature's value
    
    A legacy-only timestamp fails. Neither SignTool's verbose output nor `TimeStamperCertificate` proves the protocol type.
  - **Evidence** is bound to the EXE digest.
  - A signing failure never falls back to unsigned.
- **Default-deny matrices.** Each platform is evaluated **independently**, after its own classification and verification. A denial on one platform doesn't deny the other. Everything not listed is denied: every artifact or other upload, release creation or edit, and asset deletion, including from helpers and post-actions.

| Windows event and ref | Class | Allowed mutation |
|---|---|---|
| `push`, default branch | usb / debug / unsigned | Restricted internal upload |
| `push`, default branch | usb / release / signed | Labelled public prerelease |
| `push`, `refs/tags/v*` | usb / release / signed | Labelled versioned release |
| `push`, `refs/tags/v*` | remote / release / signed | Labelled versioned release, only with P0, P5b, §5.7, fleet-upgrade and §7.3 gates bound to the commit and final digest |
| `pull_request` targeting the default branch | usb or remote / **debug** / unsigned | **PR test artifact** (§8.2 decision): a GitHub Actions artifact on that PR run, kept 14 days, carrying the debug warning. Never a release |

| macOS event and ref | Class | Allowed mutation |
|---|---|---|
| `push`, default branch or `refs/tags/v*` | usb / debug or usb / release | Restricted internal upload |
| `push`, default branch or `refs/tags/v*` | remote / release | Restricted internal upload, **only after P0 and §5.7 pass**, bound to the commit and final DMG digest |
| `pull_request` targeting the default branch | usb or remote / **debug** | **PR test artifact**: Actions artifact, kept 14 days, with the debug warning |

  - **No public DMG.** There are no public DMG releases. A remote debug build is denied on both platforms.
  - **What's denied.** `workflow_dispatch`, unknown classes, failed or missing checks, any release build on a PR, and every unlisted case are all denied.
  - **PR test artifacts** (user decision, 2026-11-20):
    - **Visibility.** The repo is public, so these artifacts are readable by anyone with read access. The user accepts this.
    - **Content.** They are debug builds only, never release-signed.
    - **Permissions and secrets.** PR jobs keep `contents: read`, get no secrets, and never create or modify releases.
    - **Debug-only on PRs.** Remote-capable debug builds are allowed on PRs because every remote gate (staff login, wipe, touch) is off by default. They must still never be installed on fleet tablets.
  - **Internal uploads** need a verified, independently access-restricted `PRIVATE_ARTIFACT_DESTINATION`. If it's unset or invalid, nothing is uploaded.
- **Candidate handoff.** The final bytes stay in the eligible job.
  - Build, sign, verify, classify and publish all happen in **one job per platform**.
  - Step outputs default to deny.
  - Each mutation step checks:
    - its own allow output
    - that verification succeeded
    - `github.event_name`
    - the exact ref
    - the final digest, immediately before the mutation
  - No artifact upload is ever used as a handoff between jobs.
  - Only an eligible release job gets `contents: write`.
  - PRs get no secrets and no write permission. They may only upload the debug test artifact.
  - Secrets are never tested directly in `if:`.
- **Release names.**
  - **The `latest` tag.** The old workflow publishes a release tagged **`latest`**. Normal builds never edit, replace or delete it. Retiring it is a separately authorized operation: a protected environment that requires approval.
  - **The `latest` selector.** GitHub's `/releases/latest/download/<asset>` URL, which the README uses, is a **selector**. It picks the newest release that isn't a draft or prerelease.
    - A labelled prerelease never becomes "latest".
    - A versioned `v*` release can, and it then redirects the README link even though the legacy tag stays untouched.
    - If the selected release doesn't have the named asset, the link fails. It doesn't fall back to the legacy asset.

### 7.3 Windows release gate (P6)
- **Acceptance images.** CU IT provides and maintains `CU-WIN10-<build>` and `CU-WIN11-<build>`, both x64.
  - Each record lists the exact OS build and edition, browser and version, proxy/PAC, endpoint/AV policy, and standard-user status.
  - Any change needs a new record and a rerun.
- **Setup on each image.**
  - Run as a standard user with no admin rights and no Python installed.
  - Freshly download the same final signed candidate and verify its SHA-256.
  - Run `signtool verify /v /pa /all /tw`. Any warning fails. Check the pinned publisher and the RFC 3161 token for each signature (§7.2).
  - Record the SmartScreen and Defender results.
  - Start with no tablet attached.
- **Flow.** Against staging and an enrolled test tablet, as an in-scope operator:
  1. Log in and list devices.
  2. Request a kiosk attachment and get local approval on the tablet.
  3. Display a frame. **Only if the K11 touch-containment approval (P3k) is recorded for this build**, tap a safe target. On a view-only build, assert that touch is rejected (`DISABLED_BY_POLICY`).
  4. Detach, then log out.
  5. Log in again, cancel, and let one attempt time out. The listener must close each time.
- **Listener and TLS.**
  - The listener binds `127.0.0.1` only. A competing bind fails, and it isn't reachable remotely.
  - TLS negative tests use the isolated test bundle.
  - Redirect negative tests run against the frozen, packaged EXE, with `WEBSOCKETS_MAX_REDIRECTS` applied before the client module is imported.
- **The gate fails** on any inbound firewall prompt or rule change, any UAC prompt, or a SmartScreen block.
- **Evidence.** Record the image record, date, tester, commit, candidate SHA-256, signature result, staging config, tablet build, and each step with its outcome. Never record credentials, tokens or sensitive frames.

## 8. Open questions for the user / stakeholders (not blocking P1a drafting)
1. **Equity office:** Do you approve `attended_only` as the default? Do you want `status_admin` (unattended reload, home, lock and reboot)? Which states can be shared, and which workflows are sensitive? Is the banner wording acceptable?
2. **Fleet signing and the public download:** Which keys signed the deployed tablets? (The §7.1 inventory answers this.) **Decided on 2026-11-20:**
   - Internal test builds are delivered as **PR test artifacts** on GitHub (§7.2). Each one carries this warning: "**Debug APK, not a fleet release. Each CI run may use a different signing key, so updates to existing installations can fail. Do not uninstall or reset to force an update. Inventory the installed signer and follow supervised recovery.**" Windows builds add "**Unsigned executable.**"
   - The legacy `latest` tag, its asset and the README `/releases/latest` link are **kept, not retired**. Normal builds still never modify them.
3. **Remote exit and re-entry (scope cut):** v1 denies remote `exit_kiosk` and `enter_kiosk`. Both are supervised local USB actions. **Accepted by the user on 2026-11-20: deferred to v2 (Appendix A).**
4. **Windows code signing:** Does CU have an Authenticode identity?
5. **CU OIT (P5b):** We need the issuer, the RP registration (callback `https://<relay>/auth/callback`), the `amr` values and what they mean, `auth_time`, confirmation that MFA is forced under `max_age=0` (including for remembered devices), and how bypass and skip are handled.
6. **OCI:** What are the VM hostname and DNS, and who maintains them?
7. **Web boundary (§5.7):** Can the Equity and Maxient origins provide CSP `form-action` and controlled redirects?
8. **Duo trial (P5a):** Does it accept an `https://localhost:<port>` redirect?
9. **CU IT (P6):** Which Win10 and Win11 x64 builds, editions, browser versions, proxy/PAC and endpoint/AV policies represent staff desktops? Will you provide and maintain both acceptance images and the standard-user accounts?

## 9. Reconciliation notes (lead)

**v0.2**
- `key{}` and `set_url` became `kiosk_back`, `kiosk_home` and the reserved `navigate`.
- Projection is off.
- One attachment per tablet.
- A single `ACCESS_MAP`.
- `status` carries no URL.

**v0.3**
- **Approval UI.** Native panels in `MainActivity` replace `SupportApprovalActivity`.
- **Enrollment trigger.** The `DUMP` receiver gate was added.
- **Gates.** `EXIT_KIOSK_ENABLED` and `DESTRUCTIVE_ACTIONS_ENABLED` are separate gates. *(The exit gate is superseded in v0.5 and moved to Appendix A.)*
- **Manifest switch.** The `normal` lockTaskMode change moved to P4.
- **Live authority.** Authority is checked live, and devices are scoped by group.
- **Publication gate.** It became P1b.

**v0.4**

*Tablet lifecycle (H01):*
- The tablet lifecycle replaces `support_request` with `attach_open`, `lease_renewed` and `detach`.
- The tablet lease uses `elapsedRealtime()`, so it keeps running through sleep. Frame age uses `uptimeMillis()`. These are different clocks for different purposes, and suspend invalidates the grant anyway.

*Authorization contexts (H02):*
- Typed context variants replace the v0.3 `AuthzContext`.
- `consume_step_up` now takes a `StepUpContext`, and step-up is bound to the owning WSS attachment.
- `ROLE_SOURCE=group` is rejected in v1. The v0.3 group claim source had no defined freshness. Group *membership of devices*, which is relay config, remains.

*Enrollment (H03, H06):*
- H03's request-scoped `status_secret` lets a pending tablet learn its state without exposing the registry over WSS. WSS failures stay generic.
- H06 corrects the v0.3 claim that the `DUMP` gate meant "only shell". The local Start tap is now required.

*Capture timing (H04):*
- `capture_uptime_ms` now comes from the request time, not from `getTimestamp()`.

*Lock-task ownership and exit (H05):*
- Ownership is a controlled-transition invariant (`isTaskRoot` + task ID + `getAppTasks`). Android exposes no public way to query which task is locked.
- `SCHEDULE_EXACT_ALARM` is added. Remote exit depends on exact-alarm access, which Device Owner status doesn't grant automatically. *(Superseded in v0.5: moved to Appendix A.)*

*Login gating and desktop safety (H07):*
- `DEPLOYMENT_MODE` and `STAFF_LOGIN_ENABLED` were added, giving three independent gates: base login, wipe and exit.
- The `WEBSOCKETS_MAX_REDIRECTS=1` behaviour is pinned to websockets 17.4 and must be re-tested on every upgrade.

*Publishing (H08):*
- Public prereleases and Actions artifacts on a public repository are not "internal". This becomes a user decision (§8.2) rather than a silent default.

*Packaging (H09):*
- The desktop moves from Python 3.12 to 3.14.10, because 3.12 no longer ships Windows binaries. The relay can stay on 3.12+, since it runs on Linux.

**v0.5**
- **Remote `exit_kiosk` removed from v1** (blocker #4.1). Revocable exact-alarm access can defeat the re-lock deadline, and no v1 gate can rule that out. `EXIT_KIOSK_ENABLED`, `SCHEDULE_EXACT_ALARM`, `MaintenanceAlarmReceiver` and the exit P3k evidence have all moved to Appendix A.
  - *(Superseded in v0.6: `enter_kiosk` is now also reserved and denied, and re-entry is supervised over USB.)*
  - The lock-task ownership work (§2.2) stays, because the P4 manifest switch still depends on it.
- **I02, writer commit.** Admission validates and the writer commits, and the step-up is consumed only at the writer, never anywhere else. Management operations use the same deterministic lock order.
- **I03, terminal messages and deadlines.**
  - `GRANT_MAX_S=300` is a fixed grant window.
  - The tablet sends `attachment_expired` and `support_stopped`.
  - `command_id` is separated from the envelope `id`.
  - Acks carry both IDs.
  - **Two-phase wipe reservation:** the step-up is consumed only at `execute`, and the tablet enforces the deadline locally.
- **I04, frame fence.** Frames are fenced through publication on the tablet, relay and desktop. Late display acks are ignored.
- **I05, enrollment durable state.** An uncertain activation goes to durable quarantine until an admin reconciles it, and is never cleared automatically.
- **I06, publishing.** A default-deny publication matrix, a private destination that must be verified, separately authorized retirement of the legacy asset, a pinned Windows publisher, and per-signature RFC 3161 validation.

**v0.6** (review #5 should-fix items, gate passed)
- **J01, reserved ops.** `enter_kiosk` is reserved and denied, the same as `exit_kiosk`. The supervised USB exit and re-entry procedure and its verification are in §2.2. The §7.1 upgrade fixture no longer assumes a maintenance marker.
- **J02, wipe states.** The wipe flow is a phase-by-phase table. Only `execute` consumes the step-up and audits. Deadlines are rechecked after the audit, and correlation is registered before the send attempt. `RESERVATION_EXPIRED` was added, and a plain wipe `cmd` is rejected on both sides.
- **J03, termination reasons and viewer order.** A closed registry of terminal reasons, plus a serialized Tk viewer sequence with a recheck after `frame_displayed`.
- **J04, crash-safe enrollment.**
  - `request_may_exist` is committed before the POST, and the fingerprint is kept before the key is deleted.
  - Recovery is driven by a table.
  - There's a supervised quarantine panel, `POST /enroll/reconcile`, and a physical **Clear quarantine** tap.
- **J05, publishing.**
  - Windows and macOS each have their own matrix.
  - Remote macOS staging is gated on P0 and §5.7.
  - Each platform runs as a single job, with no cross-job handoff.
  - The legacy `latest` tag is distinguished from the `/releases/latest` selector.
  - The internal debug warning is restored.

## Appendix A. Remote `exit_kiosk` (deferred to v2; NOT implemented in v1)

Review #4 found a blocker in the design below. Exact-alarm access can be revoked, and revoking it cancels the recovery alarm, so the kiosk could be left unlocked. None of the P3k scenarios exercised this path.

v2 may enable remote exit only after both of these are true:
- **Recovery.** One of these holds:
  - per-device evidence that maintenance can't revoke the recovery mechanism, or
  - an independent recovery trigger that still meets the deadline after revocation.
- **Evidence binding.** Each piece of evidence is bound to the deployed build and policy.

The v0.4 design is kept here for reference:

  - **`exit_kiosk`, in order:**
    1. Revoke the attachment, grant, capture and input.
    2. Persist the maintenance generation, the boot count and a fixed `elapsedRealtime()` deadline (+10 min). A repeat exit is rejected, and the deadline is never extended.
    3. Check `canScheduleExactAlarms()`, then call `AlarmManager.setExactAndAllowWhileIdle(ELAPSED_REALTIME_WAKEUP, deadline, immutable explicit PendingIntent → MaintenanceAlarmReceiver)`, unique to this generation. The call must return normally. That proves the system accepted the request, not that the alarm will be delivered.
    4. Only then does the verified resumed owner call `stopLockTask()`. The tablet requires `NONE` before acking.
    
    If scheduling or stopping fails, the exit is cancelled and recovery starts. Exact-alarm access isn't automatic for a Device Owner. If it's unavailable, exit is denied and the kiosk stays locked. An inexact alarm is only a backup recovery trigger.
  - **During the window:**
    - `MainActivity.onResume` checks durable state and **must not** call `startLockTask()`.
    - HOME shows maintenance controls and doesn't auto-lock.
    - `enter_kiosk` ends the window early.
  - **Recovery.**
    - **Triggers.** The alarm, service start, activity create or resume, HOME, package replacement, and boot after first unlock all trigger reconciliation.
    - **Fail closed.** Process restart or update cancels maintenance and reconciles. A reboot, or an invalid boot count, fails closed.
    - **Re-lock.** Recovery invalidates the window and launches the owner, then repeats the controlled ownership transition. `recovery_pending` persists until that succeeds.
    - **Stale alarms** from an older generation are ignored.
    - **Failure.** A blocked launch is reported and needs supervised local recovery.
