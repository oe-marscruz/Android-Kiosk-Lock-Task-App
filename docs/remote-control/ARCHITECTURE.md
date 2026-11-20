# Remote Staff Control: Architecture (v0.2)

Status: **DRAFT v0.2**. This version folds in review #1 (`reviews/P0-review-1.md`, FAIL) using fixes `fixes/F01–F12.md`, reconciled by the lead (see §9). No phase merges until GPT-6.2-sol passes the review gate.

## 1. Decisions (fixed by the project owner, 2026-11-20)

| Topic | Decision |
|---|---|
| Network | Cloud relay on an OCI VM. Tablets and staff desktops both **dial out** over WSS. Tablets have no inbound listener. |
| Build | Migrate to Gradle (AGP, committed wrapper). `build-apk.sh` and `build-apk-mac.sh` become thin wrappers. |
| IdP | **Duo SSO** is the OIDC IdP (Generic OIDC RP) in front of Oracle Cloud. Testing order: user-owned Duo trial tenant with a local relay first (P5a), then CU's tenant through a configuration change only (P5b). |
| Delivery | Branches go to the fork `oe-marscruz/...`, with PRs into `TriBrigadeMars/master`. |
| Default support policy | **Attended-only.** A person at the tablet must opt in locally before staff can see screen content or send input. The Equity office must confirm this (§8). |

## 2. Components

```
 Staff PC (Win10/11)                 OCI VM                              Tablet (Android 15, Device Owner)
┌──────────────────────┐   HTTPS   ┌───────────────────────────────┐  WSS  ┌──────────────────────────────────┐
│ kiosk-manager.py     │──────────►│ Caddy :443 (TLS, ACME)         │◄──────│ RemoteAgentService (specialUse)  │
│  + kiosk_remote/     │    WSS    │   └► aiohttp 127.0.0.1:<port>  │       │ KioskA11yService (window capture │
│  - browser login +   │◄────────►│      relay/: OIDC RP, sessions,│       │   + kiosk-scoped gestures)       │
│    127.0.0.1 handoff │           │      registry, authz, leases,  │       │ SupportApprovalActivity (local   │
│  - Tk viewer         │           │      routing, audit (SQLite)   │       │   opt-in, banner, Stop, enroll)  │
│  - USB/ADB (existing)│           └──────────────┬────────────────┘       │ AdminCommandHandler (DPM)        │
└──────────▲───────────┘                          │ OIDC code+PKCE          │ MainActivity (student WebView,   │
           └── system browser ──► Duo SSO ◄────────┘                         │   ALLOWED_DOMAINS unchanged)     │
                                                                             └──────────────────────────────────┘
```

### 2.1 Relay (`relay/`, new)
- Python 3.12 and aiohttp. aiohttp binds **only `127.0.0.1`**, and Caddy alone exposes HTTPS/WSS. One process serves fewer than 50 tablets. SQLite holds the registry, sessions, audit and transactions. Live sockets, attachments and leases are process-local.
- **Ownership.** The lead owns `relay/app.py` (`create_app(config) -> web.Application`), `relay/config.py`, versioned `relay/migrations/`, `relay/deploy/` (systemd, Caddyfile, config examples) and composition tests. P2 owns `relay/auth/`, `relay/store.py` and the implementation of `relay/contracts.py`. P3 owns `relay/ws.py`, attachments, leases, queues and routing. Shared contracts change only with lead review. `create_app` validates config and applies migrations before accepting traffic, and a failure prevents startup.
- **Contracts** (`relay/contracts.py`, frozen at P1a). These are project interfaces, not library APIs:

```python
@dataclass(frozen=True)
class Principal: issuer: str; subject: str
@dataclass(frozen=True)
class Grant: role: Literal["viewer","operator","admin"]; device_scope: frozenset[str]; audit_wide: bool
@dataclass(frozen=True)
class StaffSession: session_id: str; principal: Principal; display_name: str; grant: Grant; expires_at: datetime
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
    async def authorize(self, session: StaffSession, device_id: str | None, op: str) -> Decision: ...
    async def consume_step_up(self, session: StaffSession, device_id: str, op: str, grant_id: str) -> Decision: ...
    async def revoke_session(self, session_id: str) -> None: ...
    async def revoke_device(self, device_id: str) -> None: ...
    async def audit(self, event: AuditEvent) -> None: ...  # raises → caller must not dispatch
class ConnectionCloser(Protocol):
    async def close_session(self, session_id: str) -> None: ...
    async def close_device(self, device_id: str) -> None: ...
```

- The relay is authoritative for roles, scope, sessions, attachments, leases, admission and audit. Policy changes and revocations apply to live sockets immediately. If authoritative state or the audit store is unavailable, the relay fails closed.
- **Config.** Values come from env or a protected file. Secrets come only from env or a protected file and are never committed. Unknown or invalid values fail startup.
  - `PUBLIC_BASE_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`.
  - `OIDC_ISSUER` is the exact HTTPS issuer. The discovery `issuer` and the token's `iss` must equal it exactly. Endpoints and JWKS come only from that discovery document. The relay never discovers anything from a token claim.
  - `OIDC_ALLOWED_ALGS` is a nonempty list of asymmetric algorithms. `none`, symmetric algorithms and anything inferred from a token are rejected.
  - `OIDC_REQUIRED_AMR` is a nonempty set of accepted MFA evidence values. There is no permissive default.
  - `ACCESS_MAP` maps a principal to `{role, device_scope, audit_wide}`. It is keyed either by `(iss, sub)` (`ROLE_SOURCE=principal`) or by values of `ROLE_GROUP_CLAIM` (`ROLE_SOURCE=group`). Exactly one source is configured. An unmapped, ambiguous or empty-scope principal is denied. There is no email fallback.
  - `DEVICE_AUTH_AUDIENCE` is a string that identifies this relay deployment.
  - `REMOTE_SUPPORT_POLICY` is `attended_only` (default) or `status_admin`. See §3.3.
  - `DESTRUCTIVE_ACTIONS_ENABLED` defaults to `false`. Enabling it requires recorded P5b evidence for this issuer, RP and policy. Any change to those inputs requires disabling it and verifying again.
  - Limits (v1 defaults): `CMD_QUEUE_MAX=32`, `CMD_RATE_PER_S=20`, `CMD_DEADLINE_S=5`, `LEASE_IDLE_S=60`, `SESSION_ABS_H=8`, `SESSION_IDLE_MIN=30`.
- Logging: query strings on auth paths, cookies, codes, state, CSRF tokens, verifiers, tokens, signatures, command args, frames and raw URLs are redacted or never logged. This applies to both the app and Caddy logs.

### 2.2 Tablet agent (inside the existing APK, package `com.example.webkiosk`)
- `remote/RemoteAgentService` is a `specialUse` foreground service that holds one outbound WSS connection. It starts after first unlock (§5.5) and never touches MediaProjection.
- `remote/KioskA11yService` provides kiosk-scoped gestures and **window-scoped capture**. On API 34+ it calls `takeScreenshotOfWindow()` only for the verified foreground `MainActivity` window, with no fallback to a whole-display screenshot. Throughput of 2–3 fps is best effort, because AOSP throttles screenshots at 333 ms. Its config:

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
  - `caps.a11y` becomes true only after `onServiceConnected` and is cleared on unbind or loss of access. `caps.window_capture` additionally requires API 34+.
  - Screenshot errors are handled as follows:
    - Secure window: stop and report `secure_window`.
    - Interval too short: drop the request and use bounded pacing.
    - Invalid window or display: stop, then re-resolve the window and revalidate the boundary.
    - No access: clear readiness.
    - Any other error: stop and use bounded retry.
  - Hardware buffers are always closed. Stale frames are never sent.
- `remote/SupportApprovalActivity` is native support UI that is reachable only when staff request support. The student has no path into it.
  - **Local opt-in.** For each named staff support session, a person at the tablet taps Allow. The approval is bound to that session and device, has a time limit, and can't be granted by remote input or auto-accepted. It doesn't persist across a disconnect or a new session. Deny, timeout or missing UI all fail closed.
  - **Banner.** A native, non-interactive, non-dismissable banner reads "CU staff connected: <name>". The name is the relay-authenticated display name, plain text, at most 64 chars, never treated as markup. A separate local **Stop** control sits beside it. Capture and input start only once the banner is confirmed visible.
  - **Enrollment screen.** Shown only during supervised USB setup (§3.2).
- **Kiosk boundary.** Remote view and input apply only to the `MainActivity` WebView content area while it's the foreground window. Chrome, the launcher, Wi-Fi screens, system UI, dialogs, the native overlay buttons, the banner and Stop are all outside it. The tablet enforces this boundary itself, even if the relay is compromised.
  - **Invalidation.** Any of the following immediately revokes the local grant, stops capture, discards queued frames and input, and requires fresh local approval:
    - focus loss or obscuration
    - a sensitive or unknown state
    - window or geometry change
    - local Stop
    - grant or lease expiry
    - disconnect
    - service failure
    - banner loss
  - **Rechecks.** The boundary is checked again when a capture completes and immediately before each dispatch.
  - **Sensitive states** are defined by a tablet-side allowlist of shareable states, and unknown states fail closed. Local staff must leave sensitive workflows (for example a Maxient report form) before starting support. Masking is not assumed to work until it's verified on the device.
- `remote/ScreenCaptureService` (MediaProjection) is **disabled in v1** (`PROJECTION_ENABLED=false` at build time). It is specified in §5.1–5.2 so that a later build can enable it only after it passes the K11 checkpoint and the same window boundary.
- `remote/AdminCommandHandler` maps a fixed set of ops to DPM calls. There is no arbitrary shell.
- **Isolation and navigation.**
  - Staff SSO never runs on the tablet. `MainActivity` keeps `ALLOWED_DOMAINS` (`ucdenver.edu`, `cm.maxient.com`, label-bounded subdomains) unchanged.
  - Remote navigation never takes a URL, path, query or fragment, and never launches Chrome or an intent. It resolves a **fixed destination ID** that is compiled into the APK. v1 has only `equity_home`, which equals `START_URL`.
  - One canonical URI policy applies to both app-initiated loads and `shouldOverrideUrlLoading`:
    - HTTPS only
    - a valid host
    - no userinfo
    - a lowercase exact-domain or dot-delimited subdomain match
  - The callback alone is not a confinement boundary. It doesn't fire for app-initiated loads or POSTs, and it doesn't see redirect hops. POST and redirect confinement is a **release gate** (§5.7).

### 2.3 Desktop controller (`kiosk-manager.py` and the new `kiosk_remote/` package)
- `kiosk_remote/auth.py` handles login through the system browser. It uses a relay-registered transaction and an exclusive `127.0.0.1` loopback listener (§3.1).
- `kiosk_remote/client.py` is the WSS client. TLS goes through `ssl.create_default_context(cafile=certifi.where())`, with `CERT_REQUIRED` and `check_hostname=True` and no fallback to an unverified connection.
- `kiosk_remote/viewer.py` is a Tk viewer that shows:
  - the state: pending local approval, granted, or stopped with a reason
  - the frames
  - input mapped to the normalized coordinates of the last displayed frame
  - the kiosk-scoped buttons Back and Home
  - admin buttons per role and policy
  
  There are no global HOME, BACK or RECENTS controls.
- The existing USB/ADB features remain, with one change from F11: the USB install never auto-uninstalls (§7.1).
- **Packaging.**
  - Pinned stack: CPython 3.12 x64 (exact patch pinned in CI), PyInstaller 6.20.0, websockets 17.4, Pillow 13.0.0, certifi 2026.10.23.
  - `requirements-win.lock` holds exact versions and SHA-256 hashes for every direct and transitive dependency. It installs with `pip install --require-hashes --only-binary=:all:`, and drift fails CI. The certifi `cacert.pem` is bundled.
  - The `.exe` is Authenticode-signed (SHA-256, RFC 3161 timestamp) and checked with `signtool verify /pa /all`.
  - Without CU's signing identity, CI builds only an **unsigned internal test artifact** for remote-control builds (§8).
  - SmartScreen may still warn on a signed build. Staff are never told to bypass it.

## 3. Authentication & authorization

### 3.1 Staff login (desktop ↔ relay ↔ Duo SSO)
The relay is the OIDC confidential client, with a fixed callback at `PUBLIC_BASE_URL/auth/callback`. The desktop handoff is a separate app protocol (RFC 8252 §§7.3, 8.3; RFC 9700).

1. The desktop generates random `state_d` and `verifier_d` (32 bytes each, base64url without padding), and sets `challenge_d = b64url(SHA-256(verifier_d))`. **Before** any registration or browser launch, it creates an IPv4 socket, sets `SO_EXCLUSIVEADDRUSE` on Windows (never `SO_REUSEADDR`), binds `127.0.0.1:0` and listens. A bind failure aborts the login.
2. `POST /auth/transactions {port, state_d, challenge_d}` validates:
   - `port` is an integer in 1–65535
   - both values are canonical 43-character base64url strings
   - there are no unknown or duplicate fields
   
   The relay stores the transaction under a random 256-bit `start_id` with a 5-minute TTL and returns `{start_url: PUBLIC_BASE_URL/auth/start/<start_id>}`. It never accepts a redirect URL or hostname from the client. The desktop then opens `start_url`.
3. `GET /auth/start/<start_id>` checks the transaction without consuming it.
   - It sets the cookie `__Host-rc_<start_id>` to a random 256-bit browser binding, with `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=300` and no Domain. The relay stores a hash of the binding. A repeat GET does not rebind.
   - It serves a confirmation form carrying a CSRF token bound to the transaction and cookie.
   - `POST /auth/continue {start_id, csrf}` requires the matching cookie, the CSRF token and the exact relay `Origin`. It atomically moves the transaction from pending to oidc.
4. The relay generates its own OIDC `state`, `nonce` and PKCE verifier and redirects to Duo with `response_type=code`, the fixed `redirect_uri`, `scope=openid email profile`, `state`, `nonce` and `code_challenge` (S256).
   - `GET /auth/callback` requires exactly one matching `state`, the same browser cookie and an unexpired in-progress transaction. The relay claims the transaction atomically and then exchanges the code using client auth and the PKCE verifier.
   - **ID token validation:**
     - the signature verifies against the pinned-issuer JWKS, using an allowed alg
     - `iss` matches exactly, `aud` contains the client ID, and `azp`, if present, equals the client ID (required when `aud` has more than one value)
     - `exp` and `iat` are valid, with bounded skew
     - `nonce` matches, and `sub` is nonempty
     - `amr` contains at least one value from `OIDC_REQUIRED_AMR`
   - MFA is never inferred from a successful login or from `acr`.
   - The principal is `(iss, sub)`, and `ACCESS_MAP` resolves its role and scope. Any failure ends the transaction, and no handoff is issued. The cookie is deleted on completion or error.
5. The relay mints a single-use handoff `code` (256-bit, 60 s TTL) bound to `challenge_d` and the principal. It redirects to `http://127.0.0.1:<port>/cb?code=…&state=<state_d>`, built only from the literal address, the validated decimal port and the fixed path.
   - The desktop accepts only `GET /cb` with exactly one `code` and a matching `state_d`. Bad requests are rejected without closing the listener.
   - Request size and read time are limited, and the Tk UI is never blocked.
   - The listener closes on success, on cancel, or after 5 minutes.
6. `POST /auth/token {code, verifier_d}` atomically checks the code, verifies the S256 match, consumes the code and creates a session. A wrong verifier does not consume a valid code, and concurrent redemption yields at most one session. The relay returns an opaque 256-bit session token (8 h absolute, 30 min idle). The token is stored server-side as a hash, can be revoked, and lives **in memory only** on the desktop. Duo tokens never leave the relay.
7. **Live expiry.** The absolute and idle limits apply to open sockets too.
   - Idle time is measured from the last authorized, substantive staff operation. Pings, frames, status messages, acks and denied requests don't reset it.
   - On expiry, logout or revocation, the relay closes the socket and releases attachments and leases.
   - Re-authenticating never restores an attachment.

All auth responses, including the loopback page, send `Cache-Control: no-store` and `Referrer-Policy: no-referrer` and load no third-party resources. Registration, continuation and redemption are rate-limited.

### 3.2 Tablet credential (device ↔ relay)
- **Supervised enrollment.**
  1. During USB setup, the native enrollment screen generates an Android Keystore EC P-256 signing key. No credential travels through ADB, a broadcast or app restrictions.
  2. The tablet POSTs the DER SPKI to `POST /enroll/requests` over HTTPS. The relay validates P-256 and creates a random 128-bit `request_id` and `device_id` (lowercase hex). It stores them as `pending` with a 10-minute TTL, rate-limited and capped.
  3. The tablet displays the `request_id` and `SHA-256` of the exact DER SPKI, as 32 uppercase hex pairs separated by colons.
  4. An admin with the device in scope compares the whole value on the physical tablet with the desktop display, then calls `POST /enroll/requests/<request_id>/approve`. The approval is audited with the admin, time, request ID and fingerprint.
  5. Approval alone does not activate the key.
- **StrongBox.** If `FEATURE_STRONGBOX_KEYSTORE` is present, enrollment tries `setIsStrongBoxBacked(true)`. On `StrongBoxUnavailableException`, or if the feature is absent, it generates a fresh key without StrongBox. It reports `KeyInfo.getSecurityLevel()` (strongbox, tee or software) to the admin, and a software key needs explicit admin approval. This report is informational, not attestation.
- **Device auth on each WSS connection.**
  1. The connection starts unauthenticated. The tablet sends `device_auth_start{device_id}`.
  2. If the device is `approved` or `active`, the relay replies `device_challenge{audience, nonce}`, where the nonce is 32 random bytes in base64url. The nonce is bound to the socket, expires after 60 s on a monotonic clock and is cleared on disconnect.
  3. The tablet rejects any `audience` that doesn't equal its configured value.
  4. The tablet signs: `"CU-DENVER-KIOSK-DEVICE-AUTH"`, then `0x00`, then for each of `"1"`, `audience`, `device_id` and `nonce`, its UTF-8 bytes prefixed with a u32 big-endian length. It uses `SHA256withECDSA` (DER) and sends `device_auth_proof{device_id, sig}` with the signature in base64url.
  5. The challenge is consumed on the first proof attempt, whether it succeeds or fails.
  6. Only after success does the tablet send `hello{device_id, app_version, caps}`.
- **State machine.** `pending → approved` happens through a physical comparison plus admin approval.
  - A valid proof moves `approved → active` atomically, within 10 minutes of request creation. Each reconnect needs a fresh proof. There is at most one active socket per device, and a new one closes the old.
  - Any non-revoked state can move to `revoked`. Revocation writes a tombstone, invalidates challenges, closes the socket, ends attachments and leases, and discards queued commands. It is serialized with proof and routing.
  - A revoked key or ID can never be reactivated. Re-enrollment always uses a new key, request and ID.

### 3.3 Authorization, support policy & audit
- Roles are cumulative: admin ⊇ operator ⊇ viewer. Scope is checked for every op and again just before a queued command is forwarded. Removing a role or scope immediately ends the affected attachments and leases.
- **Support policy.**
  - Under `attended_only`, every content and command op needs an active local support grant (§4). Without one, staff see only the device list and online, offline or maintenance state.
  - Under `status_admin`, `reload_kiosk`, `kiosk_home`, `lock_now` and `reboot` may also run on a `status` attachment without a local grant.
  - Frames, touch input and navigation other than `kiosk_home` always need a grant.
  - `wipe` and `exit_kiosk` always need step-up, and stay disabled until `DESTRUCTIVE_ACTIONS_ENABLED`.
- **Attachments and lease.** Each tablet has at most one attachment (`status` or `kiosk` mode), which acts as its lease. Acquiring it is atomic, and a competing request gets `LEASE_BUSY`.
  - The lease is bound to the session, socket and device. It expires after `LEASE_IDLE_S` without an authorized op, or immediately on detach, disconnect, session expiry, logout, revocation, role or scope removal, or device disconnect.
  - It never transfers automatically.
  - v1 has only one staff viewer per tablet, so the banner names exactly one person.

| Op | Min role | Scope + conditions |
|---|---|---|
| `list_devices` | viewer | Returns only in-scope devices. Content-free status. |
| `attach{mode:"status"}`, `detach` | viewer | In scope. Takes the lease. |
| `attach{mode:"kiosk"}` (frames) | viewer | In scope, holds the lease, **local grant** |
| `tap`, `swipe`, `long_press`, `kiosk_back`, `kiosk_home` | operator | In scope, lease, local grant. Under `status_admin`, `kiosk_home` is also allowed with a status lease. |
| `reload_kiosk` | operator | In scope, lease, plus a local grant **or** `status_admin` |
| `lock_now`, `reboot`, `enter_kiosk` | admin | In scope, lease, plus a local grant **or** `status_admin` (`enter_kiosk` needs only a lease) |
| `exit_kiosk`, `wipe` | admin | In scope and lease, plus `DESTRUCTIVE_ACTIONS_ENABLED`, a desktop confirmation and a single-use step-up grant |
| Approve enrollment | admin | Pending request with an assigned device in scope, after the physical fingerprint comparison |
| Revoke device | admin | In scope |
| Revoke staff session | admin | Allowed only when the target's whole scope is within the admin's. Self-logout is always allowed. |
| Read audit | admin | In-scope device events. Events with no device need `audit_wide`. |

- **Step-up (wipe and exit_kiosk).**
  1. The desktop asks for confirmation, then the relay runs a new transaction-bound code flow (§3.1 steps 2–5) with `max_age=0` and its own state, nonce and PKCE.
  2. The result must show the same `(iss, sub)`, current admin authorization and an accepted `amr`. `auth_time` must be no earlier than the step-up request, no more than 5 minutes old and not in the future beyond the allowed skew. **If `auth_time` is missing, the step-up is denied.** Duo's Generic RP guide doesn't document `auth_time`, so P5 has to show it's present.
  3. The relay issues an opaque single-use `step_up_id` bound to the principal, session, device and op. It expires at whichever comes first: 5 minutes after `auth_time`, or the session's expiry.
  4. At dispatch the step-up is consumed atomically, after authorization, the feature flag and the confirmation are checked again.
- **Audit.** The log is append-only and written only by the relay. Each event records:
  - event ID and UTC time
  - `(iss, sub)` and session ID
  - device ID and op
  - decision and reason code
  - command ID and outcome
  
  It covers:
  - sessions, attachments and leases
  - local grant, deny and stop (with the reason)
  - enrollment approval and revocations
  - denials
  - destructive intent, recorded **before** dispatch, and its outcome
  
  It never records tokens, codes, signatures, raw URLs, command args, frames or student content. If an audit write fails, a privileged op is not dispatched.

## 4. Wire protocol (v1)
WSS carries JSON control messages and binary frames. The authoritative definition is `docs/remote-control/protocol/v1.schema.json` plus `v1.md` (owned by the lead and frozen at P1a, with fixtures checked in CI). Every message has the envelope `{"v":1,"type":…,"id":…}`.

- **Device → relay:** `device_auth_start`, `device_auth_proof`, then `hello{device_id, app_version, caps}` and `status{lock_task, maintenance_until, destination_id|null, battery, wifi, caps}`.
  - `status` carries **no URL**.
  - The device also sends `support_pending`, `support_granted{grant_id, expires_at}`, `support_stopped{reason}`, `ack{id, ok, err}` and binary `frame`.
- **Relay → device:** `device_challenge{audience, nonce}`, `support_request{session_ref, display_name}`, `cmd{id, op, args, deadline_ms, grant_id?}` and `detach`.
- **Staff → relay:** `list_devices`, `attach{device_id, mode:"status"|"kiosk"}`, `detach`, `cmd{id, device_id, op, args, grant_id?, frame_id?, generation?, step_up_id?}` and `logout`.
- **Frames.** A frame has a 1-byte type, then a header `{grant_id, frame_id (monotonic), generation (window/geometry), captured_at}`, then the JPEG.
  - Input is accepted only against the latest delivered frame, captured at most 1 s earlier, with the same grant, window, generation and content-area bounds.
  - The whole gesture path must stay inside the WebView content area. It's checked again immediately before dispatch.
  - Stale, replayed, out-of-bounds or uncertain input is rejected. If safe dispatch can't be established, remote touch is disabled.
- **Ops.** `tap{x,y}`, `swipe{x1,y1,x2,y2,ms}`, `long_press{x,y}`, `kiosk_back`, `kiosk_home`, `reload_kiosk`, `lock_now`, `reboot`, `enter_kiosk`, `exit_kiosk` and `wipe`. Coordinates are normalized to [0,1].
  - `navigate{destination_id}` is reserved: v1 has only `equity_home`, which `kiosk_home` already covers.
  - Unknown ops or fields, and URL-like values, get a negative ack and are never reinterpreted.
- **Grant semantics.** `attach{kiosk}` only *requests* support. The relay forwards it with the authenticated display name. The tablet creates the grant, and the relay binds it to the session, device and lease but can never create or extend it. The tablet uses a monotonic deadline.
- **Admission.**
  - Command IDs are unique per session and kept with their outcome for the whole session. They're reserved atomically before admission.
    - A duplicate ID returns the recorded or pending outcome.
    - The same ID with different content returns `DUPLICATE_ID_CONFLICT`.
    - When the retained-ID store is full, new commands are rejected.
  - Each command gets a 5 s deadline. Queues hold 32 per device, with a limit of 20 per second per session. Overflow returns `OVERLOADED`.
  - Under backpressure, frames are dropped, never commands.
  - Commands are never replayed after a disconnect or lease loss. A dispatched command with no ack returns `OUTCOME_UNKNOWN` and is never retried. The tablet deduplicates commands per connection and rejects expired ones.
- **Errors.** Errors use `{"v":1,"type":"error","id":<req|null>,"error":{"code":…}}`. The codes are:
  - `FORBIDDEN`, `SESSION_EXPIRED`
  - `LEASE_BUSY`, `LEASE_REQUIRED`, `GRANT_REQUIRED`
  - `OVERLOADED`, `DEADLINE_EXCEEDED`, `DUPLICATE_ID_CONFLICT`, `OUTCOME_UNKNOWN`
  - `DISCONNECTED`, `DEVICE_AUTH_FAILED`
  - `UNSUPPORTED`, `INVALID_MESSAGE`, `DISABLED_BY_POLICY`
  
  Retry and close semantics come from the registry. Errors never contain secrets, URLs or stack traces.
- **Admin semantics.**
  - `wipe` calls `DevicePolicyManager.wipeDevice(0)` and is rejected below API 34. Its intent is audited first, and an ack doesn't prove the reset finished.
  - `exit_kiosk` opens a fixed **10-minute maintenance window**, which repeats and disconnects don't extend.
    - The deadline is persisted using elapsedRealtime. Before exit, capture and input stop, then `stopLockTask()`.
    - `enter_kiosk` ends the window early.
    - At expiry, or on reboot or process restart, the kiosk re-enters lock task. A failure is retried on the next service start and reported.

## 5. Android 15 edge cases
1. **Screen view.**
   - v1 uses **only** locally approved, window-scoped a11y capture on API 34+. Unsupported or unverifiable devices report it unavailable, and there's no whole-display fallback.
   - MediaProjection (when a future build enables it) needs fresh consent per session, tapped by a person at the tablet. Neither Device Owner nor a11y can accept that dialog. A remote request is only a request.
   - Behaviour by version: Android 14 added single-app sharing. Android 15 **QPR1+** adds the status-bar chip and stops projection when the screen locks, so neither should be assumed on earlier Android 15 builds.
   - Android gestures target the whole touchscreen, so kiosk containment is enforced by the app and needs the K11 checkpoint.
2. **Lock task and system dialogs.** On the K11, record the deployed `setLockTaskFeatures` flags, immersive mode and overlay behaviour. Test the baseline, `LOCK_TASK_FEATURE_SYSTEM_INFO` and `LOCK_TASK_FEATURE_BLOCK_ACTIVITY_START_IN_TASK`. Neither flag is assumed to make the consent dialog work, and the kiosk boundary is never loosened to make projection work. If the dialog, indicator or stop control fails, projection stays off for that build.
3. **Supervised a11y enablement.** This happens during attended USB setup:
   1. Read `enabled_accessibility_services`. **Append** `com.example.webkiosk/.remote.KioskA11yService` only if it's missing, keeping every existing entry. Set `accessibility_enabled=1`, read both settings back and confirm the service actually binds.
   2. If that fails, use the supervised Settings flow, including restricted-settings approval. If it still fails, setup fails.
   3. `setPermittedAccessibilityServices` takes **package names** and doesn't enable anything. Leave a null (unrestricted) policy alone. If a policy exists, add our package to it and keep the others.
   4. Reboot and verify that everything persisted.
   5. Then turn off USB debugging and revoke debugging authorizations. They're re-enabled only during supervised maintenance.
4. **FGS.** The manifest declares:
   - permissions `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE` and `FOREGROUND_SERVICE_MEDIA_PROJECTION`
   - `RemoteAgentService` with type `specialUse` and the `PROPERTY_SPECIAL_USE_FGS_SUBTYPE` justification
   - `ScreenCaptureService` with type `mediaProjection`
   
   The projection order is:
   1. A visible local activity calls `createScreenCaptureIntent()`.
   2. A person at the tablet approves.
   3. The projection FGS starts and is promoted to foreground.
   4. `getMediaProjection()` is called.
   5. A `MediaProjection.Callback` is registered.
   6. One VirtualDisplay is created.
   
   Each consent is used once and never persisted. Teardown is idempotent, with no automatic restart.
5. **Boot.** A `RECEIVE_BOOT_COMPLETED` receiver starts only the `specialUse` agent after first unlock, using credential-encrypted storage and no `LOCKED_BOOT_COMPLETED`. The Device Owner's FGS background-start exemption applies, but the boot type restrictions still do: Android 15 forbids starting a `mediaProjection` FGS from BOOT_COMPLETED. After boot the tablet restores kiosk policy and lock task. Delivery can be delayed, which the K11 test verifies.
6. **Idle and network.**
   - During setup, check `isIgnoringBatteryOptimizations` and report it. If needed, use the supervised Settings exemption flow. No DPM API is assumed to edit the Doze allowlist.
   - The tablet keeps one connection. On loss it backs off exponentially with full jitter (1 s initial, 60 s cap) and resets the backoff after a stable connection. A default-network callback triggers a single reconnect attempt.
   - An authentication failure stops retries until config or enrollment changes.
   - A 25 s ping keeps NAT mappings alive but **cannot** guarantee reachability through suspend or Doze. The relay marks a tablet offline after missed heartbeats.
7. **Network security and WebView confinement.** Relay traffic is HTTPS/WSS only, and the relay host is not added to `ALLOWED_DOMAINS`.
   - **Cleartext.** Inventory real student flows, then replace `usesCleartextTraffic=true` with a network-security-config that denies cleartext. Any needed exception is documented, scoped to one host and tested.
   - **Release gate.** POST and redirect confinement is enforced at a trusted web boundary, such as CSP `form-action` and controlled redirects on each form-serving allowed origin. Callback checks are defence in depth. If that boundary can't be controlled and proven, WebView confinement is marked unverified and **remote-control release is blocked**. The student flows themselves are left unchanged.
8. **minSdk.** P1 keeps minSdk 21. Features are gated at runtime: `dispatchGesture` at 24, display screenshots at 30 (unused for viewing) and window screenshots at 34. Keystore and StrongBox are not reasons to raise minSdk.

## 6. Root vs. Device Owner capability matrix

| Capability | Device Owner + A11y (+MP later) | ADB (supervised USB) | Needs true root / system signature |
|---|---|---|---|
| Lock task / kiosk allowlist | ✅ The DPC sets packages (`setLockTaskPackages`) and the activity enters lock task | Provisions the device owner during setup | — |
| Reboot, lock, wipe | ✅ DPM. `wipeDevice(0)` on API 34+ | Device-dependent. Don't rely on a recovery wipe | — |
| Silent install/uninstall | ✅ PackageInstaller (DO) | ✅ | — |
| Wi-Fi, user restrictions, policies | ✅ DPM | partial | — |
| Remote touch input | ✅ A11y `dispatchGesture`, kiosk-scoped by the app | ✅ `input` | Silent injection without A11y (INJECT_EVENTS) |
| Screen view | ✅ A11y kiosk-window screenshot, API 34+, best effort, local opt-in. MP is later and needs per-session local consent | ✅ `screencap`/`screenrecord` | Silent full-fps capture with no consent or indicator |
| Arbitrary shell | ❌ (by design) | ✅ shell UID | uid 0, /system edits |
| Other apps' data, /system, kernel | ❌ | ❌ | ✅ |

Rooting a locked-bootloader Lenovo would trip verified boot and Play Integrity, so it's out of scope.

## 7. Phases

| Phase | Owner | Deliverable | Verification |
|---|---|---|---|
| P0 | Lead | This document, reviewed | Review gate |
| P1 | Android agent | Gradle migration with an identical manifest and behaviour. Wrappers for `build-apk.sh` and `build-apk-mac.sh`. Release signing fails closed (§7.1). Safe USB install with no auto-uninstall. CI updated | `./gradlew assembleDebug` on Arch. `aapt2 dump badging/xmltree` diff. Signer verification and install-failure checks |
| P1a | Lead + P2/P3 | Freeze `relay/contracts.py`, `protocol/v1.schema.json` and `v1.md`, fixtures and the error registry | Both owners review the same commit, which is recorded in HANDOFF |
| P2 | Auth & Security agent | `relay/auth/` and `store.py`: login (§3.1), enrollment and device auth (§3.2), authz, step-up, revocation, audit | pytest with a mock OIDC IdP and JWKS, plus ruff |
| P3 | Desktop/Relay agent | `relay/ws.py` (attachments, leases, queues, routing) and `kiosk_remote/` (auth, client, viewer) | pytest with a fake tablet. Desktop against a local relay (Xvfb) |
| P3i | Lead | Compose P2 and P3: `create_app`, config, migrations, `deploy/` | Mock IdP → relay → fake tablet test. Caddy deploy checks: loopback-only backend, live expiry and revocation through Caddy |
| P3k | Android agent + user | **K11 feasibility spike** | On a provisioned K11: window capture and boundary, a11y enable and persistence, local opt-in UI in lock task, boot and recovery, projection dialog under lock task. Unsupported paths are disabled |
| P4 | Android agent | Agent, enrollment, kiosk capture and input, DPM commands, within the capabilities P3k verified | Unit tests, a mock relay and the API 35 emulator. K11 checkpoint, including the in-place upgrade (§7.1) |
| P5a | Lead + user | User-owned Duo trial tenant with a local relay | The user logs in interactively. Record sanitized claims (`amr`, `auth_time`), remembered-device and bypass behaviour, and step-up with a harmless substitute op. Destructive actions stay off |
| P5b | Lead + user + CU OIT | CU tenant, configuration change only | OIT confirms the issuer, algs, `sub` stability, `amr`, `auth_time`, forced MFA under `max_age=0`, and the group or principal mapping. Positive and negative tests are repeated |
| P6 | Desktop agent | A locked, Authenticode-signed Windows x64 release | CI signs and verifies. The manual gate (§7.2) runs on Win10 **and** Win11 |

P1a comes before the parallel P2/P3 work. P3i integrates before P4. P1 and P3k come before P4. A failed K11 check disables that path. Emulator results never substitute for the K11.

### 7.1 APK signing & fleet upgrade
- **Inventory first.** For every tablet, run `adb shell pm path` and `adb pull`, then `apksigner verify --print-certs`. Record the device, version and signer SHA-256. Today's Windows CI generates a fresh `local_debug.keystore` on each hosted runner, so deployed tablets may carry signing keys that can't be recovered.
- **Custody.** The production keystore lives in the CI secret `KIOSK_KEYSTORE_B64`, together with `KIOSK_KEYSTORE_PASS` and `KIOSK_KEYSTORE_ALIAS`. CI decodes it to a restricted temporary file and removes it after use. An encrypted offline backup has a named custodian.
  - A release build **fails closed** if the material is missing or its certificate doesn't match the approved fingerprint. It never generates a release key automatically.
  - Untrusted and PR builds use debug keys, are labelled debug, and are never packaged for fleet release.
  - Each release publishes its APK digest, certificate fingerprint and version.
- **Rotation.** Use an APK Signature Scheme v3 lineage (`apksigner rotate`). A lineage can't recover a key that's already lost.
- **USB install.** The install runs `adb install -r` and checks the output. On `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, or any other failure, it **stops and reports**. It never uninstalls, because a Device Owner app can't be uninstalled while active.
- **Unrecoverable signer.** Tablets whose signer can't be recovered get supervised per-device reprovisioning:
  1. Record the device and its configuration, and check FRP credentials.
  2. Revoke its relay identity.
  3. Factory reset it with the approved procedure.
  4. Install the approved APK.
  5. Provision the Device Owner over USB and restore lock task.
  6. Re-enroll it (§3.2) and verify.
- **Upgrade acceptance (K11).** Record the owner, allowlist and enrolled key fingerprint. Then `install -r` a higher version, reboot, and confirm the owner and allowlist are unchanged, lock task works, and a fresh challenge is signed by the **same** key. Then install an incompatibly signed APK and confirm the failure report: no uninstall, and setup halts.
- macOS packaging consumes the same approved release APK and verifies its digest and signer.

### 7.2 Windows release gate (P6)
- Download fresh on Win10 x64 and on Win11 x64. Use a standard user, with no admin, no Python and no tablet attached.
- Check the signature and timestamp with `signtool verify /pa /all`. Record the OS build, hash, and SmartScreen and Defender results.
- Launch the app and confirm it handles having no device gracefully.
- Run the Duo login against staging, then log out and log in again. Test cancel and timeout, and confirm the port closes.
- The listener must be on `127.0.0.1` only. A competing bind must fail, and the port must not be reachable remotely.
- The gate fails if there's any inbound-firewall prompt or rule change, any UAC prompt, or a SmartScreen block that prevents normal use.
- The TLS test must pass: a valid certificate works, and untrusted, expired and hostname-mismatched certificates are rejected for both HTTPS and WSS.

## 8. Open questions for the user / stakeholders (not blocking P1–P3)
1. **Equity office:** Does it approve the default `attended_only` policy? Should `status_admin` be enabled (unattended reload, home, lock and reboot)? Which kiosk states may be shared, and how are sensitive workflows identified? Is the "CU staff connected" banner wording acceptable?
2. **Fleet signing:** Which keys signed the deployed tablets, and are they recoverable? (The inventory in §7.1 answers this per tablet.) Until `KIOSK_KEYSTORE_B64` is configured, should CI keep publishing the rolling USB-only `.exe` with a debug-signed APK, labelled as such?
3. **Windows code signing:** Does CU have an Authenticode signing identity? If not, remote-control builds stay internal-test only.
4. **CU OIT (P5b):** The Duo issuer and Generic OIDC RP registration with callback `https://<relay>/auth/callback`. The claims: `amr` values, `auth_time`, and groups or principal mapping. Whether MFA is forced under `max_age=0`, including for remembered devices.
5. **OCI:** The VM hostname and DNS name, and who maintains it.
6. **Web boundary (§5.7):** Can the Equity and Maxient origins provide CSP `form-action` and controlled redirects? If not, remote control can't be released.

## 9. Reconciliation notes (lead)
- `key{BACK|HOME|RECENTS}` (v0.1, F02, F06) became `kiosk_back`/`kiosk_home` (F01). `set_url` became `navigate{destination_id}` (F02), which is reserved because v1 covers it with `kiosk_home`. F06's matrix row moved to the new op names.
- F01 disables projection in v1, and F07's projection spec is kept behind `PROJECTION_ENABLED=false`. `attach` modes are `status|kiosk`. The `projection` mode is reserved and returns `DISABLED_BY_POLICY`.
- F06 allowed many viewers per tablet. v1 narrows that to one attachment per tablet, which is also the lease, so the local banner and grant name exactly one staff member and the lease model stays simple.
- F05's role mapping is extended with F06's device scope into the single `ACCESS_MAP`. F06's unnamed config keys are now named (§2.1).
- F03 replaces the old `hello{sig}`. `status` dropped `url` in favour of `destination_id` (F01/F06: no raw URLs).
- `REMOTE_SUPPORT_POLICY=status_admin` now has a defined op set (§3.3), so F01's "explicitly authorized non-content admin commands" is concrete.
