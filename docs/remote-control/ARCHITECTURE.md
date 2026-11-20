# Remote Staff Control: Architecture (v0.3)

Status: **DRAFT v0.3**. History:
- v0.1 failed review #1. Fixes F01–F12 were merged into v0.2.
- v0.2 failed review #2. Fixes G01–G09 are merged here.

The source texts are in `reviews/` and `fixes/`. §9 records the lead's reconciliation decisions. No phase merges until GPT-6.2-sol passes the review gate.

## 1. Decisions (fixed by the project owner, 2026-11-20)

| Topic | Decision |
|---|---|
| Network | A cloud relay on an OCI VM. Tablets and staff desktops both **dial out** over WSS. Tablets have no inbound listener. |
| Build | Migrate to Gradle with AGP and a committed wrapper. `build-apk.sh` and `build-apk-mac.sh` become thin wrappers. |
| IdP | **Duo SSO** is the OIDC IdP, via a Generic OIDC RP, in front of Oracle Cloud. P5a tests against a user-owned Duo trial with a local relay. P5b moves to CU's tenant by configuration only. |
| Delivery | Work goes on the fork `oe-marscruz/...`, with PRs into `TriBrigadeMars/master`. |
| Support policy | **Attended-only** by default: a person at the tablet must opt in locally before staff can see content or send input. The Equity office must confirm this (§8). |
| Scope of v1 | One staff attachment per tablet. Kiosk-window capture uses accessibility only; projection is off. `navigate` is reserved. Wipe and exit are each behind their own gate, and both are off by default. |

## 2. Components

```
 Staff PC (Win10/11)                 OCI VM                              Tablet (Android 15, Device Owner)
┌──────────────────────┐   HTTPS   ┌───────────────────────────────┐  WSS  ┌──────────────────────────────────┐
│ kiosk-manager.py     │──────────►│ Caddy :443 (TLS, ACME,         │◄──────│ RemoteAgentService (specialUse)  │
│  + kiosk_remote/     │    WSS    │   URI/header-free access log)  │       │ KioskA11yService (window capture │
│  - browser login,    │◄────────►│   └► aiohttp 127.0.0.1:<port>  │       │   + kiosk-scoped gestures)       │
│    step-up, handoff  │           │      relay/: OIDC RP, sessions,│       │ MainActivity: student WebView    │
│  - Tk viewer         │           │      registry, live authz,     │       │   (ALLOWED_DOMAINS unchanged),   │
│  - USB/ADB (existing)│           │      attachments, routing,     │       │   lock-task owner, native panels:│
└──────────▲───────────┘           │      audit (SQLite)            │       │   support approval, banner+Stop, │
           │                       └──────────────┬────────────────┘       │   enrollment                     │
           └── system browser ──► Duo SSO ◄────────┘ OIDC code+PKCE         │ AdminCommandHandler (DPM)        │
                                                                             │ EnrollmentSetupReceiver (shell)  │
                                                                             └──────────────────────────────────┘
```

### 2.1 Relay (`relay/`, new)
- Python 3.12 and aiohttp. aiohttp binds **only `127.0.0.1`**; Caddy alone exposes HTTPS/WSS. One process serves fewer than 50 tablets. SQLite holds the registry, sessions, transactions, step-up grants and audit. Live sockets and attachments live in the process.
- **Ownership.** The lead owns `relay/app.py` (`create_app(config) -> web.Application`), `relay/config.py`, the versioned `relay/migrations/`, `relay/deploy/` (systemd, Caddyfile, config examples) and the composition tests. P2 owns `relay/auth/`, `relay/store.py` and `SecurityServices`. P3 owns `relay/ws.py`, attachments, queues and routing. Shared contracts change only with lead review. `create_app` validates config and applies migrations before accepting traffic, and a failure in either prevents startup.
- **Contracts** (`relay/contracts.py`, frozen at P1a). `StaffSession` is an identity reference only. Authority is resolved live on every dispatch.

```python
@dataclass(frozen=True)
class Principal: issuer: str; subject: str
@dataclass(frozen=True)
class StaffSession: session_id: str; principal: Principal; display_name: str; expires_at: datetime
@dataclass(frozen=True)
class DeviceIdentity: device_id: str
@dataclass(frozen=True)
class Decision: allowed: bool; error_code: str | None
@dataclass(frozen=True)
class AuditEvent: principal: Principal | None; session_id: str | None; device_id: str | None; op: str; decision: str; reason: str | None; command_id: str | None; outcome: str | None

class SecurityServices(Protocol):
    async def authenticate_staff(self, token: str) -> StaffSession: ...
    async def start_device_challenge(self, device_id: str, socket_id: str) -> tuple[str, str]: ...  # (audience, nonce)
    async def verify_device_proof(self, device_id: str, socket_id: str, sig: bytes) -> DeviceIdentity: ...
    async def authorize(self, session_id: str, device_id: str | None, op: str, ctx: "AuthzContext") -> Decision: ...
    async def consume_step_up(self, session_id: str, device_id: str, op: str, step_up_id: str) -> Decision: ...
    async def revoke_session(self, session_id: str) -> None: ...
    async def revoke_device(self, device_id: str) -> None: ...
    async def audit(self, event: AuditEvent) -> None: ...  # raises → caller must not dispatch
class ConnectionCloser(Protocol):
    async def close_session(self, session_id: str) -> None: ...
    async def close_device(self, device_id: str) -> None: ...
# AuthzContext: attachment mode/state, local-grant validity, maintenance-active flag; supplied by P3 from live state.
```

- **Ordering.** These steps are serialized per device: policy and session mutations, device revocation, attachment transitions, and the final authorization → audit → enqueue-to-device step. Global and session changes take the affected device locks in a deterministic order.
  - If a revocation or scope removal wins, nothing is forwarded afterwards under the removed authority.
  - Work already forwarded can't be recalled.
  - Queued work is purged and affected sockets and attachments are closed **before** a mutation reports success. A persistent revocation stays in effect even if closing fails.
  - If state or the audit store is unavailable, the relay fails closed.
- **Config.** Values come from env or a protected file. Secrets come only from env or a protected file and are never committed. Unknown or invalid values fail startup.
  - `PUBLIC_BASE_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`.
  - `OIDC_ISSUER` must be matched exactly by both the discovery `issuer` and the token `iss`. Endpoints and JWKS come only from that discovery document.
  - `OIDC_ALLOWED_ALGS`: a non-empty list of asymmetric algorithms. `none`, symmetric algorithms and token-inferred algorithms are rejected.
  - `OIDC_REQUIRED_AMR`: a non-empty set. There is no permissive default.
  - `ACCESS_MAP`: maps a principal to `{role, groups[], audit_wide}`. It is keyed either by `(iss, sub)` (`ROLE_SOURCE=principal`) or by values of `ROLE_GROUP_CLAIM` (`ROLE_SOURCE=group`); exactly one source is used. Each device belongs to exactly one **group** (§3.4). An unmapped, ambiguous or empty principal is denied. There is no email fallback. If the current group membership or policy can't be established, the relay denies.
  - `DEVICE_AUTH_AUDIENCE`.
  - `REMOTE_SUPPORT_POLICY`: `attended_only` (default) or `status_admin`.
  - `DESTRUCTIVE_ACTIONS_ENABLED=false` gates **wipe**. Turning it on needs recorded P5b evidence for this issuer, RP and policy.
  - `EXIT_KIOSK_ENABLED=false` gates **exit_kiosk**. Turning it on needs P5b evidence **and** passing K11 recovery evidence from P3k for the deployed build. Any change to those inputs turns the gate off until it is re-verified.
  - Limits: `CMD_QUEUE_MAX=32`, `CMD_RATE_PER_S=20`, `CMD_DEADLINE_S=5`, `LEASE_IDLE_S=60`, `APPROVAL_TIMEOUT_S=60`, `SESSION_ABS_H=8`, `SESSION_IDLE_MIN=30`, `FRAME_MAX_AGE_MS=1000`, `FRAME_RING=8`.
- **Logging.** The Caddy access log uses:

```caddyfile
log {
    format filter {
        request>uri delete
        request>headers delete
        resp_headers delete
    }
}
```

  - `log_credentials` is never enabled, and the `uri` handler is never used for redaction.
  - The aiohttp `access_log_class` is a subclass of `AbstractAccessLogger`. It logs only the canonical route template (or `unknown`), the method from an allowlist, the status and the duration. It never logs the raw path, query, headers, body or exception text.
  - App and error logs never contain tokens, codes, state, CSRF, verifiers, cookies, signatures, command args, frames or raw URLs.

### 2.2 Tablet agent (inside the existing APK, package `com.example.webkiosk`)
- **Manifest additions.** These are applied in P4.

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

  - `FOREGROUND_SERVICE_MEDIA_PROJECTION` and `ScreenCaptureService` are added only by a future build that has projection enabled.
- `remote/KioskA11yService` (`res/xml/kiosk_a11y_service.xml`):

```xml
<accessibility-service xmlns:android="http://schemas.android.com/apk/res/android"
    android:accessibilityEventTypes="typeWindowStateChanged|typeWindowsChanged"
    android:accessibilityFeedbackType="feedbackGeneric"
    android:accessibilityFlags="flagRetrieveInteractiveWindows"
    android:canRetrieveWindowContent="true"
    android:canPerformGestures="true"
    android:canTakeScreenshot="true"
    android:notificationTimeout="100" />
```

  - `caps.a11y` is true only after `onServiceConnected`. `caps.window_capture` additionally requires API 34+.
  - Screenshot error handling:
    - secure window: stop and report `secure_window`
    - interval too short: drop the request and use bounded pacing
    - invalid window or display: stop and revalidate
    - no access: clear readiness
    - anything else: stop and retry with a bound
  - Every `ScreenshotResult` hardware buffer is closed after use.
  - The 333 ms AOSP interval is a throttle, so 2–3 fps is best effort.
- `remote/RemoteAgentService`: one outbound WSS connection. It starts after first unlock (§5.5) and never uses MediaProjection.
- **Native panels owned by `MainActivity`.** There is no separate activity, notification, system overlay or background launch.
  - **Support approval panel.** A support request is delivered in-process to the visible, resumed, focused `MainActivity`, which shows "Allow / Deny" for the named staff member above the WebView. If no eligible activity is visible, the request stays pending until `APPROVAL_TIMEOUT_S` and is then denied. It is never auto-granted on resume.
  - **Banner and Stop.** A native, non-interactive, non-dismissable banner reads "CU staff connected: <name>". The name is the relay-authenticated display name, plain text, at most 64 characters. A separate local **Stop** control sits beside it. The banner must be confirmed visible before any capture or input.
  - **Enrollment panel.** Shown only after the supervised USB trigger (§3.2). It has local Start and Cancel, expires after 5 minutes, and closes on focus loss, process death, cancel or completion. While it is open, support and remote input are blocked.
  - The approval, banner, Stop and enrollment controls are all outside the remote-input region.
- **Kiosk boundary and capture.**
  - **Content region.** For each granted attachment, `KioskA11yService` resolves the foreground `MainActivity` window and the WebView bounds in screen coordinates. It records excluded rectangles: the native Chrome and Wi-Fi buttons, the banner, Stop, the panels and any other overlapping native control, each with its full hit area. It then picks a non-empty axis-aligned **content rect** that lies wholly inside the visible WebView and touches none of the exclusions. If any of these bounds is unknown, it fails closed.
  - **Frames.** The window screenshot is cropped to the content rect before JPEG encoding, so no excluded pixels are ever encoded. If the mapping between screenshot and screen can't be established, no frame is sent and touch is disabled.
  - **Generation.** The geometry generation changes whenever the window, focus, bounds, exclusions, scale, rotation or visibility changes.
  - **Frame ring.** The tablet keeps a ring of the last `FRAME_RING` frames for the attachment, each recorded as `{attachment_id, grant_id, frame_id, generation, window_id, capture_uptime_ms = ScreenshotResult.getTimestamp(), content_rect, excluded_rects}`. The ring is cleared on invalidation, detach, disconnect or grant expiry. Suspend or screen lock invalidates the grant.
  - **Invalidation.** Any of these immediately revokes the local grant, stops capture, discards queued frames and input, and requires fresh local approval:
    - focus loss or obscuration
    - a sensitive or unknown state
    - a generation change
    - local Stop
    - grant or lease expiry
    - detach or disconnect
    - service failure
    - banner loss
    - maintenance start
    - the enrollment panel opening
  - **Sensitive states.** These come from a tablet-side allowlist of shareable states, and unknown states fail closed. Local staff must leave sensitive workflows, such as a Maxient report form, before support starts.
  - **In-flight gestures.** On invalidation, new dispatch is blocked immediately. An in-flight gesture is cancelled only if a cancellation method has been verified safe on the K11; `dispatchGesture` has no documented standalone cancel. If containment from invalidation through completion can't be proven, **remote touch is disabled for that build** (P3k). Capture may remain if it is independently safe.
- **Lock-task ownership** (P4, verified at P3k).
  - `MainActivity` is the only owner. Its root task calls `startLockTask()`, and only that resumed activity calls `stopLockTask()`. An authorized exit is routed through an internal, non-exported path to the resumed owner. If that fails, the exit fails.
  - The cached `mInLockTask` is removed. After each transition the activity reads `ActivityManager.getLockTaskModeState()`, and only `LOCK_TASK_MODE_LOCKED` counts as success (`PINNED` does not). Before starting it confirms it is Device Owner and `isLockTaskPermitted()`, and it never starts while the keyguard is locked.
  - `lockTaskMode` on `MainActivity`, `LauncherActivity` and `WifiSettingsActivity` changes from `if_whitelisted` to `normal`, so launching HOME or Wi-Fi during maintenance can't silently create a locked task. `always` is not used.
  - At the WebView history root, Back stays in the kiosk. The existing `exitToHome()` path is not reachable from Back.
- `remote/AdminCommandHandler` maps a fixed set of ops to DPM calls. There is no shell.
- **Isolation and navigation.**
  - Staff SSO never runs on the tablet, and `ALLOWED_DOMAINS` (`ucdenver.edu`, `cm.maxient.com`, label-bounded subdomains) is unchanged.
  - One canonical URI policy applies to both app-initiated loads and `shouldOverrideUrlLoading`: HTTPS only, a valid host, no userinfo, and a lowercase exact-domain or dot-delimited subdomain match.
  - `kiosk_home` takes no arguments. It loads only the compiled `equity_home` destination (`START_URL`) after the policy check.
  - `kiosk_back` takes no arguments. On the WebView thread it checks `canGoBack()`, takes the previous item from `copyBackForwardList()`, validates its URL, and then calls `goBack()`. If there is no previous item, the URL is invalid, the history has changed, or anything is uncertain, it sends a negative ack. It never launches HOME or an activity, and never accepts a URL.
  - The navigation callback is not a confinement boundary, so POST and redirect confinement is a release gate (§5.7).

### 2.3 Desktop controller (`kiosk-manager.py` and the new `kiosk_remote/`)
- `kiosk_remote/auth.py`: login (§3.1) and step-up (§3.3), each through the system browser, a transaction registered with the relay, and an exclusive `127.0.0.1` listener.
- `kiosk_remote/tls.py`: a single factory, `ssl.create_default_context(cafile=certifi.where())`, with `CERT_REQUIRED` and `check_hostname=True`. Every HTTPS call (`urllib`/`http.client` with `context=`) and every WSS connection (`websockets.asyncio.client.connect(..., ssl=ctx)`) uses it. There is no unverified retry. A test CA is accepted only through a separate test bundle that production configuration can't select.
- `kiosk_remote/client.py`: the WSS client, with first-message `staff_auth` (§4).
- `kiosk_remote/viewer.py`: shows the attachment state (pending, granted or stopped, with the reason), the frames, and the kiosk-scoped Back/Home and per-role admin buttons. There are no global HOME, BACK or RECENTS controls.
  - **Display boundary.** For each new frame, the viewer disables input, decodes it, installs it in the visible widget and commits the update on the Tk thread. It then sends `frame_displayed{attachment_id, grant_id, frame_id, generation}`, and only after that re-enables input for that frame. The displayed reference is cleared on hide, detach, disconnect or a render failure.
  - **Pointer mapping.** Pointer positions are mapped through the bounds of the displayed image. Clicks in the letterbox area are rejected, never clamped.
- The existing USB/ADB features remain. The USB install never auto-uninstalls (§7.1).
- **Packaging.**
  - CPython 3.12 x64 at an exact patch release, PyInstaller 6.20.0, websockets 17.4, Pillow 13.0.0 and certifi 2026.10.23.
  - `requirements-win.lock` pins every package with a hash, installed with `--require-hashes --only-binary=:all:`. The certifi `cacert.pem` is bundled.
  - The release is Authenticode-signed with SHA-256 and an RFC 3161 timestamp, then checked with `signtool verify /pa /all`.
  - Staff are never told to bypass SmartScreen.

## 3. Authentication & authorization

### 3.1 Staff login (desktop ↔ relay ↔ Duo SSO)
The relay is the OIDC confidential client, and its callback is fixed at `PUBLIC_BASE_URL/auth/callback`. The desktop handoff is a separate app protocol (RFC 8252 §§7.3, 8.3; RFC 9700).

1. The desktop generates random `state_d` and `verifier_d` (32 bytes, base64url without padding) and sets `challenge_d = b64url(SHA-256(verifier_d))`. **Before** any registration or browser launch, it creates an IPv4 socket, sets `SO_EXCLUSIVEADDRUSE` on Windows (never `SO_REUSEADDR`), binds `127.0.0.1:0` and listens. If the bind fails, login aborts.
2. The desktop calls `POST /auth/transactions {port, state_d, challenge_d}`.
   - The relay validates the port (an integer, 1–65535) and requires both values to be canonical 43-character base64url strings. Unknown or duplicate fields are rejected.
   - It stores the transaction under a random 256-bit `start_id` for 5 minutes and returns `{start_url: PUBLIC_BASE_URL/auth/start/<start_id>}`. It never accepts a redirect URL or hostname.
   - The desktop opens the returned URL in the system browser.
3. `GET /auth/start/<start_id>` checks the transaction without consuming it.
   - It sets the cookie `__Host-rc_<start_id>` to a random 256-bit binding, with `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=300` and no Domain. The relay stores only a hash, and a repeat GET doesn't rebind.
   - It serves a confirmation form carrying a CSRF token bound to the transaction and the cookie.
   - `POST /auth/continue {start_id, csrf}` requires the cookie, the CSRF token and the exact relay `Origin`. It atomically moves the transaction from pending to oidc.
4. The relay generates its own OIDC `state`, `nonce` and PKCE verifier and redirects to Duo with `response_type=code`, the fixed `redirect_uri`, `scope=openid email profile`, `state`, `nonce` and `code_challenge` (S256).
   - `GET /auth/callback` requires a single matching `state`, the same cookie and an unexpired in-progress transaction. It claims the transaction atomically, then exchanges the code using client authentication and the PKCE verifier.
   - **ID token checks:**
     - the signature verifies against the pinned JWKS, using an allowed algorithm
     - `iss` matches exactly
     - `aud` contains the client ID
     - `azp` equals the client ID if present (required when there are multiple audiences)
     - `exp` and `iat` are within bounded skew
     - `nonce` matches and `sub` is non-empty
     - `amr` contains a value from `OIDC_REQUIRED_AMR`
   - MFA is never inferred from a successful login or from `acr`.
   - The principal is `(iss, sub)`, and `ACCESS_MAP` must resolve it.
   - Any failure ends the transaction without a handoff. The cookie is deleted on completion or error.
5. The relay mints a single-use handoff `code` (256-bit, valid 60 s) bound to `challenge_d` and the principal. It redirects to `http://127.0.0.1:<port>/cb?code=…&state=<state_d>`, built only from the literal address, the validated port and the fixed path.
   - The desktop accepts only `GET /cb` with exactly one `code` and a matching `state_d`. A bad request is rejected without closing the listener.
   - Request size and read time are bounded, and the Tk UI is never blocked.
   - The listener closes on success, on cancel or after 5 minutes.
6. The desktop calls `POST /auth/token {code, verifier_d}`.
   - The relay checks the S256 match and consumes the code atomically. A wrong verifier doesn't consume a valid code, and at most one session is ever issued.
   - The response is an opaque 256-bit session token, valid 8 h absolute with a 30 min idle timeout, stored hashed on the relay and revocable.
   - The desktop keeps the token **in memory only**. Duo tokens never leave the relay.
7. **Live expiry.** The absolute and idle limits also apply to open sockets. Idle time is measured from the last authorized, substantive operation; pings, frames, status messages, acks, denials and `lease_renew` don't reset it. On expiry, logout or revocation the socket is closed and the attachment released. Re-authenticating never restores an attachment.

All auth responses, including the loopback page, send `Cache-Control: no-store` and `Referrer-Policy: no-referrer` and load no third-party resources. Registration, continuation and redemption are rate-limited.

**P5a callback origin.** The relay and Caddy run on the Arch dev box with `tls internal`, and `PUBLIC_BASE_URL=https://localhost:<port>`. The exact callback URI is registered in the trial Duo RP. Caddy's local root is trusted in the test browser, and in a trial-only desktop test bundle; the production bundle stays unchanged. If Duo rejects localhost, use a temporary public hostname with ACME pointing at the local Caddy. In both cases the trial trust and any exposure are removed afterwards.

### 3.2 Tablet credential (device ↔ relay)
- **Supervised trigger.** During attended USB setup, with the kiosk visible and debugging temporarily authorized, kiosk-manager runs:
  `adb shell am broadcast -n com.example.webkiosk/.remote.EnrollmentSetupReceiver -a com.example.webkiosk.action.BEGIN_ENROLLMENT`
  - It sends no extras and no secrets.
  - The system only delivers to holders of `android.permission.DUMP`, which shell has and ordinary apps can't obtain.
  - The receiver also checks the exact action, that there are no extras, and that this app is the active Device Owner. On API 34+ it checks `getSentFromUid() == SHELL_UID` when the UID is available, as defence in depth.
  - It signals the resumed, focused `MainActivity` in-process and never launches an activity. Otherwise it fails and staff retry.
  - Anyone with authorized ADB can open the panel. That still doesn't give them a secret or let them skip the physical comparison.
- **Enrollment.**
  1. The tablet user taps Start in the panel, which generates an Android Keystore EC P-256 key.
  2. The tablet calls `POST /enroll/requests {spki_der_b64, security_level}` (§3.4). The relay validates P-256 and returns a random 128-bit `request_id` and `device_id`, lowercase hex. The request stays `pending` for 10 minutes and is rate-limited and capped.
  3. The tablet shows `request_id` and the `SHA-256` of the exact DER SPKI, as 32 uppercase hex pairs joined by colons.
  4. An admin assigns the request to a group they administer (§3.4), compares the whole fingerprint on the physical tablet, and approves. Approval alone doesn't activate the device.
- **StrongBox.** If `FEATURE_STRONGBOX_KEYSTORE` is present, the tablet tries `setIsStrongBoxBacked(true)`. If that throws `StrongBoxUnavailableException` or the feature is missing, it makes a fresh non-StrongBox key. It reports `KeyInfo.getSecurityLevel()`, and a software key needs `accept_software=true` on approval. The report is informational, not attestation.
- **Device auth on each WSS connection.**
  1. The tablet sends `device_auth_start{device_id}`. If the device is `approved` or `active`, the relay replies with `device_challenge{audience, nonce}`: a 32-byte nonce, bound to the socket, valid for 60 s on a monotonic clock. The tablet rejects an unexpected `audience`.
  2. The tablet signs `"CU-DENVER-KIOSK-DEVICE-AUTH" ‖ 0x00 ‖` the fields `"1"`, `audience`, `device_id` and `nonce`, each as UTF-8 prefixed with a u32 big-endian length, using `SHA256withECDSA` (DER). It sends `device_auth_proof{device_id, sig}` with the signature base64url-encoded.
  3. The relay consumes the challenge on the first attempt. On success it replies `device_ready{device_id}`, after which the tablet sends `hello`. On failure it sends a generic `DEVICE_AUTH_FAILED` and closes.
- **States.**
  - `pending → approved` requires the physical comparison plus admin approval.
  - `approved → active` happens atomically on a valid proof within 10 minutes of the request being created.
  - A request can be `rejected` or can expire.
  - Any non-revoked state can go to `revoked`. That writes a tombstone, invalidates challenges, closes the socket, ends the attachment and discards queued commands, serialized per §2.1.
  - A device has at most one active socket; a new connection closes the old one.
  - A revoked key or ID is never reactivated. Re-enrollment always issues a new key, request and ID.

### 3.3 Authorization, support policy, attachments & step-up
- **Live authority.** Roles are cumulative: admin ⊇ operator ⊇ viewer. The current role, groups, policy, attachment and grant are checked at admission and again immediately before forwarding, under the §2.1 ordering. A valid **grant** is a tablet-issued local approval that is unexpired, unrevoked, and bound to the current session, device and kiosk attachment. Pending, denied, expired or stopped approvals are **no grant**. The tablet independently rechecks its grant and the boundary.
- **Complete policy table.** `*` means any value. `G` means a valid grant and `N` means no grant. Anything not listed is denied.

| Op | Min role | Attachment | Grant | Policy | Decision / conditions |
|---|---|---|---|---|---|
| `list_devices` | viewer | * | * | * | Allowed. Returns only in-scope devices, with content-free state. |
| `attach{status}` / `attach{kiosk}` | viewer | — | N | * | Allowed in scope, subject to the lease rules. Kiosk mode only requests approval. |
| `detach`, `lease_renew` | viewer | status/kiosk | * | * | Owning session and current `attachment_id` only. |
| frames, `frame_displayed` | viewer | kiosk | G | * | After the banner and boundary checks. |
| `tap`, `swipe`, `long_press`, `kiosk_back`, `kiosk_home`, `reload_kiosk` | operator | kiosk | G | * | Coordinate ops also need a valid frame binding (§4). |
| `lock_now`, `reboot`, `enter_kiosk` | admin | kiosk | G | * | Allowed. |
| `kiosk_home`, `reload_kiosk` | operator | status | N | `status_admin` | Allowed. |
| `lock_now`, `reboot` | admin | status | N | `status_admin` | Allowed. |
| `enter_kiosk` | admin | status | N | * | **Only** to end an active maintenance window. Otherwise denied. |
| `wipe` | admin | kiosk | G | * | Needs `DESTRUCTIVE_ACTIONS_ENABLED`, desktop confirmation and a step-up consumed at dispatch. |
| `exit_kiosk` | admin | kiosk | G | * | Needs `EXIT_KIOSK_ENABLED`, desktop confirmation and a step-up consumed at dispatch. |
| enrollment list/assign/approve/reject | admin | — | — | * | §3.4 scope rules, plus the physical fingerprint comparison for approval. |
| device revoke, scope reassignment | admin | — | — | * | In scope. Reassignment needs authority over both groups. |
| session revoke | admin | — | — | * | Only when the target's entire current scope is within the admin's. |
| audit read | admin | — | — | * | In-scope device events. Events with no device need `audit_wide`. |
| logout | viewer | — | — | * | Own session only. |
| `navigate`, unknown ops | — | — | — | — | Denied (`navigate` is reserved in v1). |

  - The `status_admin` exceptions are exactly `reload_kiosk`, `kiosk_home`, `lock_now` and `reboot`, and only on a status lease. Neither policy allows an unattended wipe or exit.
  - Error codes: `FORBIDDEN` (role or scope), `LEASE_REQUIRED`, `GRANT_REQUIRED`, `DISABLED_BY_POLICY` (policy or feature gate). Denials are never dispatched.
- **Attachment lifecycle.** A tablet has at most one live attachment. It is bound to the device connection, one staff session and one socket. Its states are `none`, `status`, `pending_approval`, `granted` and `released`. `released` is terminal for that ID, and the slot then returns to `none`.
  - The relay mints an `attachment_id` (128-bit, 32 lowercase hex characters) on every acquisition, never reuses one, and returns it to the owner. The ID is not a credential.
  - Every message scoped to an attachment is checked against the current ID, socket, device and session. Stale IDs are rejected or dropped.
  - **Lease.** `LEASE_IDLE_S` runs from acquisition, from the last authorized substantive op, or from an accepted `lease_renew{device_id, attachment_id}`. Renewing does **not** extend local consent, the approval deadline or the session idle timer. A late renewal can't revive an expired lease.
  - **Approval timeout.** A pending approval expires at the earliest of `APPROVAL_TIMEOUT_S`, the lease expiry and the session expiry. The tablet enforces its own prompt and grant deadlines on a monotonic clock.

| From | Trigger (atomic) | To | Side effects |
|---|---|---|---|
| none | authorized `attach{status}`, device connected | status | Mint ID, start the lease, return `attach_result`. |
| none | authorized `attach{kiosk}`, device connected | pending_approval | Mint ID, start the lease and approval deadline, send `support_request{attachment_id, display_name}`. No content yet. |
| status | same owner requests kiosk | pending_approval | Release the old ID, mint a new one, send `detach(old)` then `support_request(new)`. Nothing carries over. |
| pending_approval / granted | same owner requests status | status | Release the old ID, mint a new one, send `detach(old)`, stop the prompt, capture and input, clear queues. |
| any live | same owner, same mode | unchanged | Return the current ID and state. No deadline is extended. |
| any live | a different owner attaches | unchanged | `LEASE_BUSY`. |
| pending_approval | matching `support_granted`, before all deadlines, after local Allow and visible banner | granted | Bind the grant to the ID and notify the owner. |
| pending_approval | deny, no UI, or timeout | released | Notify the owner with the reason. Late replies are ignored. |
| granted | local Stop, grant expiry, or §2.2 invalidation | released | Stop capture and input, discard queues, notify. |
| any live | detach, lease expiry, either disconnect, session expiry/logout/revocation, role or scope removal, device revocation, maintenance start | released | Invalidate the ID and grant, discard work, notify the reachable peer. Unacked dispatched commands become `OUTCOME_UNKNOWN`. |
| any live | valid `lease_renew` | unchanged | Reset the lease deadline only. |

  - A transition commits before any notification or forwarding is sent.
  - Nothing is restored after a reconnect or a relay restart.
  - A stale `support_granted` can never bind to a replacement attachment.
- **Step-up for wipe and exit_kiosk.**
  1. The desktop shows the exact device and op and asks for confirmation. It then generates fresh `state_d`, `verifier_d` and `challenge_d` and opens an exclusive listener (§3.1 step 1).
     - It calls `POST /auth/step-up/transactions {device_id, op, port, state_d, challenge_d, confirmed:true}` with the **session bearer**.
     - The relay checks the session, live authorization, attachment and grant, and the gate for that op.
     - Only one pending step-up is allowed per (session, device, op), and a competing request gets `409`.
     - The response is `{start_url}`.
  2. The relay runs the §3.1 browser binding (cookie, CSRF, Origin, OIDC state, nonce and PKCE) with `max_age=0`. It doesn't also send `prompt=login`, since Duo documents the two as equivalent.
  3. At the callback, the ID token gets the full §3.1 checks, plus:
     - the same `(iss, sub)` as the session
     - an accepted `amr`
     - a numeric `auth_time` that is at or after initiation, no more than 5 minutes old, and not in the future beyond the skew
     
     **If `auth_time` is missing, the step-up is denied.** Duo's Generic RP guide doesn't document it, and P5 must show it's there. An `amr` value plus a fresh `auth_time` still don't prove a fresh second factor. P5a and P5b must establish that, including for remembered devices and bypass.
  4. The relay issues a loopback handoff code. It is valid for at most 60 s and never longer than the transaction or the freshness window.
  5. The desktop calls `POST /auth/step-up/token {code, verifier_d}` with the **original session bearer**.
     - The relay rechecks freshness, authorization, policy and the gate.
     - It returns a single-use `step_up_id` (opaque, 256-bit, stored hashed), bound to the principal, session, device, op, the confirmation and `auth_time`.
     - The `step_up_id` expires at the earlier of `auth_time` + 5 minutes or the session expiry. Idle expiry and revocation also kill it.
  6. The command carries `step_up_id`. At dispatch the relay rechecks everything, then atomically consumes the step-up. The audit intent is written before forwarding. A consumed step-up is never restored, so a retry needs a new confirmation and a new step-up.
- **Audit.** The log is append-only and written only by the relay. Each event records:
  - `event_id`, UTC time
  - `(iss, sub)`, `session_id`
  - `device_id`, op
  - decision, reason
  - `command_id`, outcome
  
  It covers:
  - sessions, attachments and leases
  - local grant, deny and stop
  - enrollment assignment, approval and rejection
  - revocations
  - denials
  - step-up initiation, callback, redemption and consumption
  - destructive intent (recorded **before** dispatch) and outcome
  
  It never stores tokens, codes, verifiers, state, cookies, signatures, raw URLs, command args, frames or student content. If writing the audit entry fails, the privileged op is not dispatched.

### 3.4 Management HTTP API
- **Conventions.**
  - JSON bodies reject unknown and duplicate fields.
  - Admin routes need `Authorization: Bearer <session token>`; a token is never accepted in the query string. Live authorization is checked at execution.
  - Responses are `Cache-Control: no-store`.
  - Errors are `{"error":{"code"}}`, with: `400 INVALID_REQUEST`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `410 EXPIRED`, `429 RATE_LIMITED`, `503 UNAVAILABLE`.
  - An unknown or out-of-scope target returns `404`.
  - Denials are audited, and a mutation fails closed if the audit write fails.
  - Cursors are opaque, bounded, integrity-protected, and bound to the caller and filters. Every page rechecks authorization.
- **Groups.** A device belongs to exactly one group from `ACCESS_MAP`. A pending request starts unassigned.
  - Admins can list pending requests, but see only the request ID, device ID, fingerprint, security level, group and expiry.
  - An admin can assign only a group they administer. Reassigning needs authority over both the old and new groups and immediately invalidates the affected attachments.
  - Revoked devices can't be reassigned.

| Route | Auth; request | Success |
|---|---|---|
| `POST /enroll/requests` | Unauthenticated supervised tablet; `{spki_der_b64, security_level}` | `201 {request_id, device_id, fingerprint, expires_at}` |
| `GET /enroll/requests?cursor&limit` | admin | `200 {items:[{request_id, device_id, fingerprint, security_level, group_id\|null, expires_at}], next_cursor}` |
| `PUT /devices/<device_id>/scope` | admin; `{group_id}` | `200 {device_id, group_id}` |
| `POST /enroll/requests/<id>/approve` | admin; `{fingerprint, accept_software}` | `200 {request_id, device_id, group_id, state:"approved"}` |
| `POST /enroll/requests/<id>/reject` | admin; `{}` | `200 {request_id, state:"rejected"}` |
| `GET /audit?cursor&limit` | admin | `200 {items:[AuditEvent…], next_cursor}` |
| `POST /devices/<device_id>/revoke` | admin; `{}` | `200 {device_id, state:"revoked"}` after the tombstone and cleanup |
| `POST /sessions/<session_id>/revoke` | admin; `{}` | `200 {session_id, state:"revoked"}` |
| `POST /auth/logout` | own session; `{}` | `200 {state:"logged_out"}` |
| §3.1 `/auth/transactions`, `/auth/start/…`, `/auth/continue`, `/auth/callback`, `/auth/token`; §3.3 `/auth/step-up/transactions`, `/auth/step-up/token` | as specified | |

Repeating a revoke or logout is safe. An incompatible state or a fingerprint mismatch returns `409`, and an expired request returns `410`.

## 4. Wire protocol (v1)
WSS carries JSON control messages and binary frames. The authoritative definition is `docs/remote-control/protocol/v1.schema.json` together with `v1.md`. The lead owns both. They are frozen at P1a, with fixtures and an error/reason registry checked in CI. Every message has the envelope `{"v":1,"type":…,"id":…}`. Replies echo the request `id`, and unsolicited events use `id:null`. Unknown versions, types, fields and codes fail closed.

- **Staff handshake.** The WSS connection starts unauthenticated. Within 10 s the first and only pre-auth message must be `staff_auth{token}`, never a URL or query string. The relay replies `staff_ready{session_id, display_name, expires_at}` and never echoes the token. Any other pre-auth message, a bad token, or a timeout gets a generic error and a close. Size and rate are capped.
- **Device handshake** (§3.2): `device_auth_start` → `device_challenge` → `device_auth_proof` → `device_ready`. The device then sends `hello{device_id, app_version, caps}`.
- **Staff → relay:**
  - `list_devices`
  - `attach{device_id, mode:"status"|"kiosk"}`, `detach{device_id, attachment_id}`, `lease_renew{device_id, attachment_id}`
  - `frame_displayed{attachment_id, grant_id, frame_id, generation}`
  - `cmd{id, device_id, attachment_id, op, args, grant_id?, frame_id?, generation?, step_up_id?}`
  - `logout`
- **Relay → staff:**
  - `staff_ready`, `devices{items:[{device_id, state, caps}], next_cursor}` (content-free states: online, offline, maintenance)
  - `attach_result{device_id, attachment_id, mode, state}`, `detach_result`, `lease_renew_result{…, expires_at}`
  - `support_pending`, `support_granted{…, grant_id, expires_at}`, `support_stopped{…, reason}`, `attachment_ended{…, reason}`
  - `device_status`, `device_disconnected`
  - `cmd_result{device_id, attachment_id, command_id, state, error}`. A result does not mean a destructive action finished.
  - binary `frame`, `error`, `session_ended`, `logout_result`
- **Relay → device:** `device_challenge`, `device_ready`, `support_request{attachment_id, display_name}`, `frame_displayed`, `cmd{id, attachment_id, op, args, deadline_ms, grant_id?, frame_id?, generation?}` and `detach{attachment_id}`.
- **Device → relay:** `hello`, `status{lock_task_state, maintenance_until, destination_id|null, battery, wifi, caps}` (no URL), `support_pending|granted|stopped{attachment_id,…}`, `ack{id, ok, err}` and binary `frame`.
- **Frames.** A frame is a 1-byte type, then a header `{attachment_id, grant_id, frame_id, generation, width, height}`, then the JPEG of the content rect. Capture time is metadata kept on the tablet and is never taken from the desktop.
- **Coordinate commands** (`tap{x,y}`, `long_press{x,y}`, `swipe{x1,y1,x2,y2,ms}`) carry `attachment_id, grant_id, frame_id, generation` on **both hops**. The relay passes them through unchanged. Coordinates are finite values in [0,1], relative to the JPEG crop, and `ms` is bounded.
  - **Tablet validation.** Immediately before dispatch, the tablet atomically checks:
    - the live attachment and grant, the deadline, the foreground window and the visible banner
    - that a ring record matches all four IDs, **is the latest acknowledged displayed frame**, and has the current generation, window, rect and exclusions
    - that `0 ≤ uptimeMillis() − capture_uptime_ms ≤ FRAME_MAX_AGE_MS`
    - that every point of the gesture path, including interpolation, lies inside the content rect and outside every exclusion
    
    Validation, invalidation and dispatch are serialized. `dispatchGesture` reports submission, not completion, so its callback decides the outcome. If there's no outcome, it's `OUTCOME_UNKNOWN`.
  - **Display acks.** An ack for an older or unknown frame can't roll back the latest accepted display reference.
- **Other ops:** `kiosk_back`, `kiosk_home`, `reload_kiosk`, `lock_now`, `reboot`, `enter_kiosk`, `exit_kiosk` and `wipe` (no arguments). `navigate{destination_id}` is reserved. Unknown ops or fields, or URL-like values, get a negative ack.
- **Admission.**
  - Queues and deduplication are scoped to `(attachment_id, command_id)` on both the relay and the tablet. IDs are reserved atomically, and outcomes are kept for the life of the attachment.
    - A duplicate returns the recorded or pending outcome.
    - The same ID with different content returns `DUPLICATE_ID_CONFLICT`.
    - When retention is full, new commands are rejected.
  - Per-device queue limit is 32, with 20/s per session and a 5 s deadline. Overflow returns `OVERLOADED`.
  - Frames are dropped under backpressure; commands never are.
  - On invalidation, detach, replacement, disconnect or lease loss, queued commands and acks are discarded and never migrate.
  - A dispatched command without an ack returns `OUTCOME_UNKNOWN` and is never replayed.
- **Errors** use `{"v":1,"type":"error","id":<req|null>,"error":{"code"}}`. The registry codes are:
  - Auth and policy: `UNAUTHENTICATED`, `FORBIDDEN`, `SESSION_EXPIRED`, `DISABLED_BY_POLICY`, `DEVICE_AUTH_FAILED`
  - Attachment and grant: `LEASE_BUSY`, `LEASE_REQUIRED`, `GRANT_REQUIRED`, `ATTACHMENT_STALE`, `GRANT_STALE`
  - Frame binding: `FRAME_UNKNOWN`, `FRAME_NOT_DISPLAYED`, `FRAME_EXPIRED`, `GENERATION_STALE`, `GESTURE_OUT_OF_BOUNDS`
  - Admission and delivery: `OVERLOADED`, `DEADLINE_EXCEEDED`, `DUPLICATE_ID_CONFLICT`, `OUTCOME_UNKNOWN`, `DISCONNECTED`
  - Message validity: `UNSUPPORTED`, `INVALID_MESSAGE`
  
  Errors never contain secrets, URLs, args or stack traces.
- **Admin semantics.**
  - `wipe`: `DevicePolicyManager.wipeDevice(0)`, rejected below API 34. The intent is audited first, and the ack doesn't prove the reset completed.
  - `exit_kiosk`:
    - **Persist.** Before stopping, the tablet atomically saves the maintenance generation, a fixed `elapsedRealtime()` deadline (+10 min) and `Settings.Global.BOOT_COUNT`. A repeat exit is rejected, and the deadline is never extended.
    - **Stop.** It revokes the attachment and grant, then the owner calls `stopLockTask()`. The tablet confirms `LOCK_TASK_MODE_NONE` before acking. A failure or ambiguous state cancels maintenance and starts recovery.
    - **During the window.** HOME (`LauncherActivity`) shows maintenance controls and doesn't auto-lock. Outside the window it routes to `MainActivity` for recovery and doesn't offer Chrome or Settings while recovery is pending.
  - `enter_kiosk` cancels the window early.
  - **Recovery.** Expiry fires a persisted wakeup trigger. Reconciliation also runs on service start, on activity create and resume, on HOME entry, after a package is replaced, and at boot after first unlock.
    - Process death or an app update cancels maintenance. A reboot, or a missing or changed boot count, fails closed.
    - A wall-clock change can't extend the window.
    - Recovery-pending persists until `LOCKED` is observed. A blocked launch is reported and needs supervised local recovery.

## 5. Android 15 edge cases
1. **Screen view.**
   - v1 uses **only** locally approved, window-scoped accessibility capture on API 34+, cropped to the content rect. There is no whole-display fallback.
   - Projection, if a future build enables it, needs fresh consent per session from a person at the tablet. Neither Device Owner nor accessibility can accept it on their behalf.
   - Android 14 added single-app sharing. Android 15 **QPR1+** adds the status-bar chip and auto-stop on lock.
   - Gestures target the whole touchscreen, so containment is enforced by the app (§2.2, §4). It is a P3k gate.
2. **Lock task and system UI.** On the K11, record the deployed `setLockTaskFeatures` flags and the immersive and overlay behaviour. Test the baseline, `LOCK_TASK_FEATURE_SYSTEM_INFO` and `LOCK_TASK_FEATURE_BLOCK_ACTIVITY_START_IN_TASK`. `setLockTaskFeatures` controls system UI while locked; it does not control re-entry. Verify the in-activity approval panel and enrollment panel under the deployed flags. Projection stays off for any build where its dialog, indicator or Stop fails.
3. **Supervised accessibility enablement** (attended USB setup).
   1. **Append** `com.example.webkiosk/.remote.KioskA11yService` to `enabled_accessibility_services` only if it is absent, keeping every existing entry. Then set `accessibility_enabled=1`, read both settings back, and confirm the service binds.
   2. If that fails, use the supervised Settings flow, approving restricted settings if prompted. If it still fails, setup fails.
   3. `setPermittedAccessibilityServices` takes **package names** and doesn't enable a service. Leave a null policy alone. If a non-null policy exists, add our package while keeping the others.
   4. Reboot and verify everything persisted.
   5. Disable USB debugging and revoke the debugging authorizations.
4. **FGS.** Only the `specialUse` agent exists in v1. The future projection order is:
   1. A local visible activity calls `createScreenCaptureIntent()`.
   2. A person at the tablet approves.
   3. The `mediaProjection` FGS starts.
   4. `getMediaProjection()` is called.
   5. A `MediaProjection.Callback` is registered.
   6. One VirtualDisplay is created.
   
   Consent is single-use, teardown is idempotent, and there is no auto-restart.
5. **Boot.** `BootReceiver` handles `BOOT_COMPLETED` only (no `LOCKED_BOOT_COMPLETED`), using credential-encrypted storage. It starts the `specialUse` agent, restores and verifies Device Owner policy, runs maintenance reconciliation, and launches the owner. A blocked launch or failed lock is reported.
   - The Device Owner exemption from FGS background-start limits applies, but the boot type restrictions still apply.
   - Delivery may be delayed. P3k verifies this.
6. **Idle and network.**
   - Report `isIgnoringBatteryOptimizations` at setup. If it's off, use the supervised Settings exemption.
   - Keep one connection. Back off with full jitter, 1 s up to 60 s, and reset after a stable connection. The default-network callback triggers a single attempt. Auth failures stop retrying.
   - The 25 s ping keeps NAT alive but doesn't guarantee reachability through Doze. The relay marks the device offline after missed heartbeats.
7. **Network security and WebView confinement.**
   - Relay traffic is HTTPS/WSS only, and the relay is not added to `ALLOWED_DOMAINS`.
   - Inventory the student flows, then replace `usesCleartextTraffic=true` with a network-security-config that denies cleartext and documents any single-host exception.
   - **Release gate:** POST and redirect confinement must be enforced at a trusted web boundary, such as CSP `form-action` plus controlled redirects on each form-serving origin. If it can't be proven, **remote-control release is blocked**.
8. **minSdk.** P1 keeps 21. Runtime gates: gestures need 24, window screenshots need 34.

## 6. Root vs. Device Owner capability matrix

| Capability | Device Owner + A11y (+MP later) | ADB (supervised USB) | Needs true root / system signature |
|---|---|---|---|
| Lock task / kiosk allowlist | ✅ The DPC sets packages (`setLockTaskPackages`); `MainActivity` owns lock task | Provisions the Device Owner during setup | — |
| Reboot, lock, wipe | ✅ DPM; `wipeDevice(0)` on API 34+ | Device-dependent | — |
| Silent install/uninstall | ✅ PackageInstaller (DO) | ✅ | — |
| Wi-Fi, user restrictions, policies | ✅ DPM | partial | — |
| Remote touch input | ✅ A11y `dispatchGesture`, kiosk-scoped and frame-bound | ✅ `input` | Silent injection without A11y (INJECT_EVENTS) |
| Screen view | ✅ A11y kiosk-window screenshot, API 34+, best effort, local opt-in | ✅ `screencap`/`screenrecord` | Silent full-fps capture with no consent or indicator |
| Arbitrary shell | ❌ (by design) | ✅ shell UID | uid 0, /system edits |
| Other apps' data, /system, kernel | ❌ | ❌ | ✅ |

Rooting a locked-bootloader Lenovo trips verified boot and Play Integrity, so it is out of scope.

## 7. Phases

| Phase | Owner | Deliverable | Verification |
|---|---|---|---|
| P0 | Lead | This document, reviewed | Review gate |
| P1 | Android agent | Gradle migration with identical manifest and behaviour. `build-apk.sh` and `build-apk-mac.sh` wrappers. Release signing fails closed. `apk-info.txt`. Safe USB install. CI on Gradle | `assembleDebug` on Arch, `aapt2` diff, signer checks, install-failure test |
| P1b | Android agent | **Publication gate** (§7.2): `REMOTE_FEATURES` classification and inventory, embedded-APK verification in the exe and DMG, gating of both Windows publish paths. **Must merge before any P3 or P4 code merges** | The full class × event matrix in CI |
| P1a | Lead + P2/P3 | Freeze `contracts.py`, `protocol/v1.schema.json`, `v1.md`, fixtures and the error/reason registry | Both owners review the same commit, recorded in HANDOFF |
| P2 | Auth & Security agent | `relay/auth/` and `store.py`: §3.1, §3.2, §3.3 step-up, §3.4 routes, live authz, revocation, audit | pytest with a mock OIDC IdP and JWKS, plus ruff |
| P3 | Desktop/Relay agent | `relay/ws.py` (attachments, leases, queues, routing, ordering) and `kiosk_remote/` (auth, tls, client, viewer) | pytest with a fake tablet. Desktop against a local relay under Xvfb. TLS negative tests with trustme |
| P3i | Lead | Compose P2 and P3: `create_app`, config, migrations, `deploy/` | Mock IdP → relay → fake tablet. Caddy checks: loopback-only backend, sentinel log redaction, live expiry and revocation through Caddy |
| P3k | Android agent + user | **K11 feasibility spike** | On a provisioned K11, check: content-rect crop and exclusions; gesture containment through invalidation (otherwise touch is disabled); a11y enable and persistence; the approval and enrollment panels under deployed flags; the `DUMP`-gated broadcast; lock-task ownership, maintenance expiry, process death, reboot and update during maintenance (the `EXIT_KIOSK_ENABLED` evidence); boot; the projection dialog |
| P4 | Android agent | Agent, enrollment, kiosk capture and input, DPM commands, lock-task ownership changes, within P3k-verified capabilities | Unit tests, mock relay, API 35 emulator. K11 checkpoint plus the §7.1 upgrade test |
| P5a | Lead + user | Duo trial with the local relay (§3.1 P5a origin) | The user logs in. Record sanitized `amr` and `auth_time`, remembered-device and bypass behaviour, and step-up with a harmless substitute op. Both gates stay off |
| P5b | Lead + user + CU OIT | CU tenant, configuration only | OIT confirms the issuer, algs, `sub` stability, `amr`, `auth_time`, forced MFA under `max_age=0`, and the mapping. Negative tests are repeated |
| P6 | Desktop agent | Locked, Authenticode-signed Windows x64 release | CI signs and verifies. §7.3 manual gate on Win10 **and** Win11 |

Order: P1 → P1b, and P1a, before the parallel P2/P3 work. P3i comes before P4. P3k comes before P4. If a K11 check fails, that path is disabled; an emulator pass never stands in for the K11.

### 7.1 APK signing & fleet upgrade
- **Inventory.** For each tablet, run `adb shell pm path` and `adb pull`, then `apksigner verify --print-certs`. Record the device, version and signer. Today's Windows CI creates a fresh `local_debug.keystore` on every run, so deployed tablets may carry signing keys that can't be recovered.
- **Custody.**
  - The keystore comes from `KIOSK_KEYSTORE_B64`, `KIOSK_KEYSTORE_PASS` and `KIOSK_KEYSTORE_ALIAS`. CI decodes it to a restricted temp file and deletes it after use. An encrypted offline backup has a named custodian.
  - A release build **fails closed** if the material is missing or the certificate doesn't match the approved fingerprint (`KIOSK_CERT_SHA256`). It never auto-generates a key.
  - PR builds are debug only.
  - Rotation uses a v3 lineage (`apksigner rotate`). A lineage can't recover a key that's already lost.
- **USB install.** Install with `adb install -r`. On `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, or any other failure, **stop and report**. Never uninstall.
- **Unrecoverable signer.** Reprovision supervised, one device at a time:
  1. Record the device and check FRP.
  2. Revoke its relay identity.
  3. Factory reset it.
  4. Install the approved APK.
  5. Provision the Device Owner and restore lock task.
  6. Re-enroll it and verify.
- **Upgrade acceptance (K11).** Record the owner, allowlist and key fingerprint. Run `install -r` with a higher version, both normally and **during a maintenance window**, then reboot. Confirm that the owner and allowlist are unchanged, `LOCKED` is observed, recovery works, and a fresh challenge is signed by the **same** key. Then try an incompatibly signed APK and confirm it reports the failure without uninstalling.

### 7.2 Publication gate (P1b)
- **Classification.** Each candidate has three fields: capability (`usb-only` or `remote-capable`), APK (`release` or `debug`), and on Windows the exe (`authenticode-signed` or `unsigned`).
  - `REMOTE_FEATURES` must be exactly `0` or `1`.
  - CI inspects the checkout and the package contents. If `relay/`, `kiosk_remote/` or remote Android code is present, the candidate is remote-capable even when the flag says otherwise. A mismatch or an unknown layout fails.
- **Verification.**
  - Check `apk-info.txt` against an independent `apksigner verify --print-certs` and hash. A release also needs the approved fingerprint. A debug build is never relabelled as release.
  - Extract the embedded APK from the **final signed** exe with a pinned PyInstaller extractor, without running it, and verify the digest and signer. Verify the exe with `signtool verify /pa /all`.
  - Mount the DMG read-only and verify every APK copy in it.
  - Missing, extra or stale copies fail. Record the commit, class, digests and fingerprints.
- **Matrix.**
  - **Windows default-branch push → rolling `latest`:**
    - Only `usb-only` + debug + unsigned may publish, as a **prerelease** titled `USB-only debug — internal testing — unsigned` with asset `kiosk-manager-usb-debug-unsigned.exe` and the §8.2 warning.
    - `usb-only` + release + signed may publish a labelled prerelease.
    - Remote-capable builds never update `latest`.
    - If a check fails, the existing `latest` is left untouched.
  - **Windows `v*` tag:**
    - Needs a release APK and a verified signed exe. Anything debug or unsigned publishes nothing.
    - Remote-capable releases also need P0, P5b, §5.7, fleet-upgrade and §7.3 evidence tied to the commit and package digest.
  - **macOS:** internal CI artifacts only (`macos-usb-debug-internal`, `macos-usb-release-internal`, `macos-remote-release-internal`). Remote debug builds publish nothing. There are no public DMG releases.
  - **Secrets** are never used directly in `if:`. They're exposed via env and their presence is tested in steps.
  - **PR jobs** get no release secrets and no write permission.

### 7.3 Windows release gate (P6)
- Do a fresh download on Win10 x64 and on Win11 x64, as a standard user with no admin, no Python installed and no tablet attached.
- Run `signtool verify /pa /all` and record the OS build, the hash, and the SmartScreen and Defender results.
- Launch the app. Run login against staging, log out, log in again, cancel, and let it time out. Confirm the port closes each time.
- The listener must be on `127.0.0.1` only. A competing bind must fail, and it must not be reachable remotely.
- TLS: a valid certificate succeeds over both HTTPS and WSS. An untrusted, expired or hostname-mismatched certificate fails over both, using the isolated test bundle against the packaged exe.
- The gate fails if there's any inbound firewall prompt or rule change, any UAC prompt, or a SmartScreen block that stops normal use.

## 8. Open questions for the user / stakeholders (not blocking P1–P3)
1. **Equity office:** Do you approve `attended_only` as the default? Should `status_admin` be enabled, allowing unattended reload, home, lock and reboot? Which kiosk states may be shared, and how do we identify the sensitive workflows? Is the banner wording acceptable?
2. **Fleet signing:** Which keys signed the deployed tablets? (The §7.1 inventory answers this.) *Interim decision, pending your confirmation:* keep the rolling `latest` as an internal-testing **prerelease** that is USB-only, debug-signed and unsigned. It must carry this warning: "Debug APK, unsigned executable, not a fleet release. Each CI run may use a different signing key, so updates to existing installations can fail. Do not uninstall or reset to force an update. Inventory the installed signer and follow supervised recovery." Retire it once a stable signer and signed distribution exist.
3. **Windows code signing:** Does CU have an Authenticode identity? Until it does, remote-capable builds stay internal-only.
4. **CU OIT (P5b):** We need the Duo issuer, the RP registration (callback `https://<relay>/auth/callback`), the `amr` values, `auth_time`, the groups or principal mapping, and confirmation that MFA is forced under `max_age=0`, including for remembered devices.
5. **OCI:** What is the VM hostname and DNS, and who maintains it?
6. **Web boundary (§5.7):** Can the Equity and Maxient origins provide CSP `form-action` and controlled redirects?
7. **Duo trial (P5a):** Does the trial tenant accept an `https://localhost:<port>` redirect URI? If not, we use a temporary public hostname instead.

## 9. Reconciliation notes (lead)

**v0.2 (from F01–F12)**
- `key{…}` and `set_url` were replaced by `kiosk_back`, `kiosk_home` and the reserved `navigate`.
- Projection is off in v1.
- One attachment per tablet.
- A single `ACCESS_MAP`.
- `status` carries no URL.

**v0.3 (from G01–G09)**
- **Approval UI.** G01 still named `SupportApprovalActivity`. It was replaced by G07's native panels inside `MainActivity`, because a separate activity launch could be blocked by lock task or background-activity-start rules.
- **Enrollment receiver.** G07 gated `EnrollmentSetupReceiver` on `getSentFromUid()` alone. That method returns `INVALID_UID` unless the sender opts in to share its identity, and `am broadcast` may not opt in. The lead added the system-enforced `android:permission="android.permission.DUMP"` as the primary gate (shell holds it, ordinary apps can't), and kept the UID check as defence in depth. Both are verified at P3k.
- **Exit gate.** G06 added a separate `EXIT_KIOSK_ENABLED` gate, and G01 and G05 now reference it. Wipe keeps `DESTRUCTIVE_ACTIONS_ENABLED`.
- **Lock-task attribute.** G06's change from `if_whitelisted` to `normal` changes student-facing lock-task behaviour. It is scheduled in **P4** behind P3k evidence, not in P1, which must stay behaviour-identical.
- **Contracts.** G04's live-authorization contract replaces the grant field in `StaffSession`. `authorize` takes an `AuthzContext` (attachment, grant, maintenance) from P3, so G01's table can be evaluated in one place. `consume_step_up` takes `step_up_id`, not `grant_id`, to avoid clashing with the local grant.
- **Groups.** G04's group-based scope replaces v0.2's static device lists in `ACCESS_MAP`.
- **Error codes.** The registry is the union of the v0.2, G02, G03 and G04 codes, with HTTP-only codes listed in §3.4.
- **Publication gate.** G09 assigned it to P1, but P1 had already started, so it became its own phase, **P1b**. It still has to merge before any P3 or P4 code.
- **Maintenance invalidation.** Maintenance start invalidates the attachment (G06 + G02). The enrollment panel invalidates capture (G07 + G03).
