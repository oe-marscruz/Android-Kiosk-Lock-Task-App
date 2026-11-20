# Remote Staff Control: Architecture (v0.1, draft for review)

Status: **DRAFT**. No implementation phase may merge until the GPT-6.2-sol review gate passes.

## 1. Decisions (fixed by the project owner, 2026-11-20)

| Topic | Decision |
|---|---|
| Network | Cloud relay on an Oracle Cloud (OCI) VM. Tablets and staff desktops both **dial out** over WSS (TLS 1.2+). No inbound ports open on tablets. |
| Build | Migrate the APK build to Gradle (AGP, wrapper committed). `build-apk.sh` stays as a thin wrapper so CLI and CI keep working. |
| IdP | **Duo SSO** is the OIDC identity provider, in front of Oracle Cloud. Duo MFA runs inside the IdP flow. |
| Delivery | Branches go to the fork `oe-marscruz/...`. PRs target `TriBrigadeMars/master`. |

## 2. Components

```
 Staff PC (Win10/11)                 OCI VM                          Tablet (Android 15, Device Owner)
┌──────────────────────┐    WSS    ┌──────────────────────────┐   WSS   ┌──────────────────────────────┐
│ kiosk-manager.py     │◄────────►│ relay/ (Python, aiohttp) │◄──────►│ RemoteAgentService (FGS)      │
│  + remote/ client    │  staff   │  - OIDC confidential RP  │ device │  - DPM admin commands         │
│  - system browser    │  session │  - session tokens        │  cred  │  KioskA11yService             │
│    login (loopback)  │  token   │  - device registry       │        │  - dispatchGesture (touch)    │
│  - Tk viewer + input │          │  - authz + audit log     │        │  - takeScreenshot (fallback)  │
│  - USB/ADB (existing)│          │  - frame/command routing │        │  ScreenCaptureService (MP)    │
└──────────────────────┘          └───────────┬──────────────┘        │ MainActivity (student WebView │
           ▲ browser redirect                 │ OIDC code flow        │   — untouched allowlist)      │
           └──────────────── Duo SSO (OIDC + Duo MFA) ◄───────────────┘ └──────────────────────────────┘
```

### 2.1 Relay (`relay/`, new)
- Python 3.12 and aiohttp. It runs behind Caddy, which terminates TLS with ACME certs, on the OCI VM. systemd unit and Caddyfile templates live in `relay/deploy/`.
- **It is the only OIDC client.** It's a *confidential* client of Duo SSO, so the client secret stays on the server and never ships in the Windows .exe or the APK.
- State: SQLite holds the device registry, audit log and revoked sessions. In-memory dicts hold live sockets. One process is fine for under 50 tablets.
- Configuration comes from env and a config file: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` (env or file only), `ALLOWED_GROUPS`, `PUBLIC_BASE_URL`.

### 2.2 Tablet agent (inside the existing APK, package `com.example.webkiosk`)
- `remote/RemoteAgentService`: a foreground service with type `specialUse` (plus `mediaProjection` while streaming). It keeps one outbound WSS connection to the relay, reconnects with jittered backoff, and starts on `BOOT_COMPLETED` and from the Device Owner receiver.
- `remote/KioskA11yService`: an AccessibilityService that provides `dispatchGesture` for tap, swipe and long-press, `performGlobalAction` for BACK and HOME, and `takeScreenshot()` (API 30+) for **consent-free low-fps view (about 2–3 fps)**.
- `remote/ScreenCaptureService`: MediaProjection, a VirtualDisplay, ImageReader, then JPEG frames. This is the higher-fps path and needs a consent dialog every session (see §5).
- `remote/AdminCommandHandler`: maps a fixed set of commands to DPM calls. Arbitrary shell execution is never allowed.
- **Isolation:** staff SSO never runs on the tablet. `MainActivity`, `ALLOWED_DOMAINS` and the student WebView stay unchanged. The agent has no UI the student can reach.

### 2.3 Desktop controller (`kiosk-manager.py` and the new `kiosk_remote/` package)
- `kiosk_remote/auth.py`: login. It opens the system browser to `relay/auth/start` and receives the result on a 127.0.0.1 loopback redirect (RFC 8252 §7.3).
- `kiosk_remote/client.py`: a WSS client (`websockets` library) for the device list, the viewer stream and commands.
- `kiosk_remote/viewer.py`: a Tk Toplevel that renders JPEG frames with Pillow. Mouse events map to normalized coordinates and go out as gesture commands. It also has buttons for BACK, HOME, Reload kiosk, Reboot, Lock and Exit kiosk.
- The existing USB/ADB features stay exactly as they are. The remote features are a new "Remote" section in the UI.
- Packaging: PyInstaller, built with the existing `build-exe.yml` and `package-win.sh`. New deps: `websockets`, `Pillow`, `certifi`. The CA bundle is pinned via certifi, so it doesn't depend on the Win10 cert store.

## 3. Authentication & authorization

### 3.1 Staff login (desktop ↔ relay ↔ Duo SSO)
1. The desktop generates `state_d` and a PKCE-style `verifier_d`. It starts a loopback listener on a random port and opens a browser to
   `https://relay/auth/start?redirect_port=P&state=state_d&challenge=S256(verifier_d)`.
2. The relay starts an OIDC Authorization Code + PKCE flow with Duo SSO. It uses its own `state`, `nonce` and `code_verifier`, and its fixed redirect `https://relay/auth/callback`.
3. The user signs in with CU credentials and Duo pushes MFA. The relay receives the code, exchanges it with the client secret, and validates the ID token: signature via JWKS, `iss`, `aud`, `exp`, `nonce`, and `amr`/`acr` where Duo supplies them, to confirm MFA.
4. The relay checks the user's groups against `ALLOWED_GROUPS`, or an allowlist of emails if Duo doesn't release groups. It then mints a **one-time handoff code**, valid for 60 s and bound to `challenge`, and redirects the browser to `http://127.0.0.1:P/cb?code=…&state=state_d`.
5. The desktop checks `state_d` and POSTs `code` and `verifier_d` to `relay/auth/token`. It receives a **relay session token**: opaque, 256-bit random, 8 h TTL with a 30 min idle timeout, revocable, and stored server-side as a hash.
6. The desktop keeps the token **in memory only**. It's never written to disk, and an optional "remember" mode is out of scope for v1.

Duo/OIDC tokens never leave the relay. The desktop holds only a relay session token it can revoke.

### 3.2 Tablet credential (device ↔ relay)
- **Enrollment (over USB, during the existing kiosk setup):** `kiosk-manager.py` asks the relay for a single-use **enrollment code**. This needs a staff session, and the code expires in 10 minutes. It pushes the code to the tablet with `adb shell am broadcast` to a receiver gated on a `signature|privileged` permission check plus a shell-UID check, or with `dpm`-scoped app restrictions.
- The tablet generates an **EC P-256 keypair in Android Keystore**, non-exportable and StrongBox-backed when available. It registers the public key, the code and its `device_id` with the relay.
- **Connecting:** the relay sends a nonce and the tablet signs it. There's no long-lived bearer secret on the device.
- To revoke a device, delete it from the registry. A factory reset destroys the key.

### 3.3 Authorization & audit
- Roles: `viewer` can watch only. `operator` can watch, send touch input and use navigation. `admin` adds DPM commands (reboot, lock, exit kiosk, wipe). Roles map from IdP groups in relay config.
- Every session start and end and every command is logged with user, device, time and command (no frame data). Admins can read the log, and nothing else can write it.
- **Wipe and exit-kiosk** need a second confirmation in the desktop and a fresh login within the last 5 min (`auth_time` check).
- **Tablet-side notice:** while a staff session is active, a non-dismissable overlay banner reads "CU staff connected: <name>". This covers privacy and transparency for students using the kiosk.

## 4. Wire protocol (v1)
WSS, JSON control messages and binary frames. Every message has `{"v":1,"type":...,"id":...}`.
- device → relay: `hello{device_id, sig, app_version, caps}`, `frame` (binary: 1-byte type, then JPEG), `ack{id, ok, err}`, `status{lock_task, url, battery, wifi}`.
- staff → relay: `list_devices`, `attach{device_id, mode:"a11y"|"projection"}`, `detach`, `cmd{device_id, op, args}`.
- `op` is an allowlist: `tap{x,y}`, `swipe{x1,y1,x2,y2,ms}`, `long_press{x,y}`, `key{BACK|HOME|RECENTS}`, `reload_kiosk`, `set_url{path}` (must pass the same `ALLOWED_DOMAINS` check), `lock_now`, `reboot`, `exit_kiosk`, `enter_kiosk`, `wipe`.
- Coordinates are normalized to [0,1] and scaled on the tablet. The relay rate-limits commands to 20/s per session and enforces backpressure by dropping frames, never commands.

## 5. Android 15 edge cases (explicit)
1. **MediaProjection consent:** Android 14+ shows a consent dialog for every capture session, and Android 15 adds a status-bar chip and the option to share a single app. Device Owner **cannot** skip it. We default to **A11y `takeScreenshot()`** (no consent, about 3 fps, 333 ms minimum interval) and offer the MediaProjection mode on request. In that mode someone at the tablet taps "Start", or the a11y service accepts the dialog. Accepting it from a11y is **disabled by default** and flagged for review.
2. **Lock task and system dialogs:** in lock task mode the projection dialog (SystemUI) must be able to show. We need to verify on the device that `setLockTaskFeatures` allows it. It might need `LOCK_TASK_FEATURE_SYSTEM_INFO` or the dialog might be blocked. **Device verification checkpoint.**
3. **Enabling accessibility:** Android 13+ "restricted settings" blocks sideloaded apps from being enabled through the UI. During USB setup we use `adb shell settings put secure enabled_accessibility_services …`, and the DPO calls `setPermittedAccessibilityServices` to include our service. If an OS update or the user turns it off, the agent reports `caps.a11y=false`.
4. **FGS types (API 34+):** declare `FOREGROUND_SERVICE_SPECIAL_USE` and `FOREGROUND_SERVICE_MEDIA_PROJECTION`. A mediaProjection FGS must be started *after* consent. `specialUse` needs the `<property>` justification.
5. **Background start and boot:** use a `BOOT_COMPLETED` receiver to start the FGS. Android 15 forbids starting some FGS types from BOOT_COMPLETED (dataSync, camera, mediaPlayback, phoneCall, mediaProjection, microphone). `specialUse` is allowed. **Verify on the device.**
6. **Doze/standby:** the Device Owner adds the app to the battery-optimization allowlist, and the relay's 25 s ping keeps NAT mappings alive.
7. **Network security config:** the agent's traffic is HTTPS/WSS only. The relay host isn't added to `ALLOWED_DOMAINS`, because that list only gates the WebView. `usesCleartextTraffic` gets narrowed with a network-security-config.
8. **minSdk:** raise it from 21 to **30**, because `takeScreenshot` and Keystore features need it. The fleet is a single model on Android 15.

## 6. Root vs. Device Owner capability matrix

| Capability | Device Owner + A11y + MP (this design) | ADB (USB, or adb-over-relay later) | Needs true root / system signature |
|---|---|---|---|
| Lock task / kiosk allowlist | ✅ DPM | ✅ `dpm` | — |
| Reboot, lock, wipe | ✅ DPM | ✅ | — |
| Install/uninstall apps silently | ✅ PackageInstaller (DO) | ✅ | — |
| Wi-Fi config, user restrictions, policies | ✅ DPM | partial | — |
| Remote touch input | ✅ A11y `dispatchGesture` | ✅ `input` | Silent injection without A11y (INJECT_EVENTS) |
| Screen view | ✅ A11y screenshot (~3 fps) / MP (consent per session) | ✅ `screencap`/`screenrecord` | Silent full-fps capture with no consent or indicator |
| Arbitrary shell | ❌ (by design) | ✅ shell UID | uid 0 shell, /system edits |
| Read other apps' data, modify /system, kernel | ❌ | ❌ | ✅ |

Rooting a locked-bootloader Lenovo would trip verified boot and Play Integrity, so it's out of scope.

## 7. Phases

| Phase | Owner (sub-agent) | Deliverable | Verification on Arch |
|---|---|---|---|
| P0 | Lead | This document, reviewed | Review gate |
| P1 | Android agent | Gradle migration with an identical manifest and behaviour, `build-apk.sh` wrapper, CI updated | `./gradlew assembleDebug` on Arch; diff of the APK manifest (`aapt2 dump`) before and after |
| P2 | Auth & Security agent | `relay/` auth: OIDC RP, handoff and session tokens, device enrollment and challenge, roles, audit | pytest with a **mock OIDC IdP** (local JWKS); ruff |
| P3 | Desktop/Relay agent | relay WSS routing and protocol; `kiosk_remote/` client, viewer and login; kiosk-manager "Remote" tab | pytest with a fake device; desktop runs headless or under Xvfb on Arch against a local relay |
| P4 | Android agent | Agent service, A11y, screenshot stream, DPM commands, enrollment, consent-gated MP | Unit tests; a mock relay plus emulator (API 35); **device checkpoint** on the K11 |
| P5 | Lead + user | **Interactive checkpoint:** the user logs in with real CU Duo SSO against a staging relay | User-driven; no credentials in chat |
| P6 | Desktop agent | Windows 10/11 PyInstaller packaging, then verification | CI `windows-latest` plus a manual Win10 run |

P2 and P3 share `relay/` and are split by module: P2 owns `relay/auth/` and `relay/store.py`, P3 owns `relay/ws.py` and the protocol. P1 must land before P4.

## 8. Open questions for the user (not blocking P1–P3)
- What's the Duo SSO OIDC issuer URL? CU OIT registers a "Generic OIDC Relying Party" app: redirect `https://<relay>/auth/callback`, scopes `openid email profile` and a groups claim if available.
- What's the OCI VM's hostname/DNS name, and who maintains the VM?
- Is the student-visible "staff connected" banner acceptable, or does the Equity office's policy require something else?
