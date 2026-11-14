# CU Denver Equity — Android Kiosk Lock Task Mode

A complete toolkit for locking a Lenovo Tab K11 Gen 2 (Android 15) tablet into kiosk mode, displaying the [CU Denver Office of Equity](https://www.ucdenver.edu/offices/equity) website. Includes a portable Windows GUI for non-technical users, a custom Android launcher, and macOS build support.

[![Download Windows .exe](https://img.shields.io/badge/Download-Windows%20.exe-2d5a8f?style=for-the-badge&logo=windows)](https://github.com/TriBrigadeMars/Android-Kiosk-Lock-Task-App/releases/latest/download/CU-Denver-Equity-Kiosk-Manager.exe)

**Direct download:** [CU-Denver-Equity-Kiosk-Manager.exe](https://github.com/TriBrigadeMars/Android-Kiosk-Lock-Task-App/releases/latest/download/CU-Denver-Equity-Kiosk-Manager.exe) — a single self-contained file (bundles ADB and the kiosk APK). No install needed: double-click it, connect the tablet via USB, and click **Setup Kiosk**.

---

## Architecture

**Release signing status:** Historical APKs and desktop downloads use an exposed signing identity. Replacement production signing and device migration are pending. Read [the signing and migration guide](SIGNING.md) before deployment; local development APKs are for disposable test installations.

```
Desktop PC                          Lenovo Tablet (Android 15)
┌─────────────────────────┐         ┌──────────────────────────────┐
│  Kiosk-Manager.exe      │         │  Lock Task Mode (active)      │
│  (self-contained)       │  USB    │                               │
│  ┌───────────────────┐  │ ◄───── │  ┌─────────────────────────┐  │
│  │ Setup Kiosk       │  │  ADB   │  │ Custom Launcher (Home)  │  │
│  │ Exit Kiosk        │  │        │  │  ⏰ Clock + 1 app icon  │  │
│  │ Restore Apps      │  │        │  │  No app drawer           │  │
│  │ Remote Management │  │        │  └───────────┬─────────────┘  │
│  │ Factory Reset     │  │        │              ↕                │
│  │ Fullscreen/Dark   │  │        │  ┌───────────┴─────────────┐  │
│  │ Accessibility     │  │        │  │ Kiosk WebView App       │  │
│  └───────────────────┘  │        │  │ ucdenver.edu domain     │  │
└─────────────────────────┘        │  │ cm.maxient.com domain   │  │
                                   │  │ Fullscreen immersive    │  │
                                   │  └─────────────────────────┘  │
                                   │                               │
                                   │  Allowlisted: kiosk, Chrome, │
                                   │  WiFi settings                │
                                   │  Device owner: kiosk app      │
                                   └──────────────────────────────┘
```

---

## Quick Start

### What you need
- Windows 10/11 PC
- USB cable (data-capable, not charge-only)
- Lenovo Tab K11 Gen 2

### On the tablet (one-time)
1. Enable Developer Options: **Settings → About Tablet → tap Build Number 7 times**
2. Enable USB Debugging: **Settings → System → Developer Options → USB Debugging → ON**
3. Remove all Google accounts: **Settings → Passwords & Accounts → remove each one**

### Deploy
1. Connect tablet via USB — accept the debugging prompt
2. Double-click `dist/CU-Denver-Equity-Kiosk-Manager.exe`
3. Refresh devices and select the tablet serial when more than one is connected.
4. Unlock the tablet and click **Setup Kiosk**. Setup installs the selected APK, verifies the exact owner, preserves required apps, configures Home, and opens the launcher to apply policy.
5. Require **Setup Complete**. This is shown only after ownership, Home, required package states, lock-task packages/features, and active managed lock task have been verified. A failure can leave partial changes; inspect the tablet before retrying. Unknown Android diagnostic formats fail verification.

From source, provide a reviewed APK through `KIOSK_RELEASE_APK` before launching the GUI. Windows command-line setup delegates to the same provisioning engine and returns a nonzero exit code on failure:

```powershell
.\setup-kiosk.bat --serial TABLET_SERIAL --apk "C:\Reviewed Builds\kiosk.apk"
# If ADB is installed elsewhere, add: --adb "C:\Android SDK\platform-tools\adb.exe"
.\.venv\Scripts\python.exe provisioning.py verify --serial TABLET_SERIAL
.\exit-kiosk.bat --serial TABLET_SERIAL
```

The batch wrappers use the project virtual environment if available, otherwise the Windows Python launcher (`py -3`). They do not build an APK or reuse an older artifact after a failed build. The frozen GUI uses its bundled, release-verified APK. Signing mismatch stops setup and refers to [the migration guide](SIGNING.md); setup never automatically uninstalls the kiosk or resets a device. Provisioning supports foreground Android user 0. Verification requires the kiosk, Chrome, Settings and the required clock package to be installed and available. Read-only `provisioning.py devices` lists exact connection states; `verify` makes no device changes. `restore` restores only this tool's recorded optional-package changes for the selected serial.

---

## Desktop GUI Reference

The `.exe` is a single 36 MB file — no installer, no dependencies. It bundles ADB and the kiosk APK inside.

| Button | What it does |
|--------|-------------|
| **🔒 Setup Kiosk** | Verifies the selected device, installs the reviewed APK, enrolls/verifies the owner, applies reviewed package changes, configures Home, and verifies active lock task |
| **🔓 Exit Kiosk** | Requests a force-stop and verifies lock task is inactive; device-owner policy remains installed |
| **📱 Restore Setup Changes** | Restores only optional packages this tool changed on the selected tablet, preserving previously disabled apps |
| **🌐 Setup Remote Management** | Guided wizard for Android Management API enrollment |
| **⚠ Factory Reset Tablet** | Wipes tablet to factory state (double confirmation) |
| **🗖 Fullscreen (F11)** | Toggles fullscreen (Esc to exit) |
| **🌙 Dark Mode** | Toggles dark theme |
| **♿ Accessibility** | 40% larger text, high-contrast focus indicators |

---

## Android Kiosk App

### Kiosk Activity (`MainActivity.java`)
- Fullscreen immersive WebView locked to `ucdenver.edu` and `cm.maxient.com`
- Domain locking — external navigation blocked with toast message
- Error resilience — custom error page with Retry button on load failure
- Back gesture/hardware key — navigates WebView history; returns to launcher at start page
- Auto lock task entry on resume with lifecycle race prevention
- Memory management — WebView paused on background, properly destroyed on exit

### Custom Launcher (`LauncherActivity.java`)
- Navy blue home screen with live clock, kiosk app icon, and **Chrome** / **WiFi Settings** buttons
- No app drawer — users cannot access any other apps
- Clean Android lifecycle with clock handler cleanup

### WiFi Settings (`WifiSettingsActivity.java`)
- Lets users add WiFi credentials (SSID + password) if the tablet drops off the network
- Uses the Android 10+ `WifiNetworkSuggestion` API; the system prompts the user to approve the network
- Runtime permission handling (`NEARBY_WIFI_DEVICES` on Android 13+, `ACCESS_FINE_LOCATION` on Android 10-12)
- Reachable from an "Add WiFi Network" button on the launcher and a small overlay button in the kiosk app

### Lock Task Mode & Device Owner (`KioskDeviceAdminReceiver.java`)
- The kiosk app is provisioned as the **device owner** so it can manage the lock task allowlist itself
- On launch it calls `setLockTaskPackages()` to allowlist the kiosk app, **Google Chrome** (`com.android.chrome`), and the **system WiFi settings** (`com.android.settings`)
- The launcher and kiosk app expose **Chrome** and **WiFi Settings** buttons so these can be opened while in lock task mode

---

## Release downloads and builds

Historical downloads may contain the exposed signing identity. Session 4 replaces automatic rolling publication with manually dispatched packaging of an independently verified release APK. No production release under the replacement identity has been approved yet.

See [APK signing and device migration](SIGNING.md) for protected key inputs, certificate verification, version codes, desktop packaging, CI configuration, and existing-device migration. Do not use a repository APK or a development APK for a new production deployment.

For a local development build, run the platform setup script first, then:

```bash
bash build-apk.sh development
# On macOS:
bash build-apk-mac.sh development
```

Development builds use an ignored local identity and cannot update the old exposed-key installation. Packaging requires an already built, reviewed release APK through `KIOSK_RELEASE_APK` plus the approved certificate and version metadata described in the signing guide. Use `bash package-win.sh` or `bash package-mac.sh`; both verify the APK before invoking PyInstaller.

The GitHub Actions workflows now accept an HTTPS release APK URL by manual dispatch, verify its certificate and metadata against the protected `release` environment, and upload a desktop artifact for review. They do not publish a rolling GitHub Release. Actual Windows/macOS package acceptance and replacement of historical downloads remain pending.

The macOS packager uses a PyInstaller directory-based `.app` with bundled ADB and the reviewed APK. It checks the APK's manifest against its DEX component definitions before bundling. It then copies the app outside the checkout and runs `--check-bundle` before creating the DMG or adding the optional manual-install APK. That check uses the GUI's resource paths, verifies the APK hash, and executes only `adb version`; it does not discover or configure tablets. The local script and CI use this same packaging path. [Session 9 evidence](REMEDIATION_PLAN.md#session-9---november-13-2026) distinguishes host checks from pending macOS acceptance.

On a Mac, use Python 3.12 with Tkinter and set `KIOSK_PYTHON` to that interpreter if it is not `python3`. The packager installs the pinned [PyInstaller requirement](requirements-macos-build.txt). Supply the reviewed release APK and signing metadata from [the signing guide](SIGNING.md), then run `bash package-mac.sh`. Resource-check and toolchain reports are written under `dist/macos-evidence/`. The workflow also prepares a clean development APK compilation check on its Mac runner; a workflow definition is not evidence of a successful run. Relocated GUI use, tablet discovery/setup, and each supported Mac architecture still require acceptance.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| App crashes | Verify internet on tablet; rebuild APK and reinstall |
| "Device not connected" | Use data-capable USB cable; re-enable USB Debugging; run `adb kill-server && adb devices` |
| Cannot set device owner | Remove ALL Google accounts from tablet; check no other device admin active |
| Back gesture fails | Swipe from bottom edge to reveal nav bar temporarily |
| Launcher shows app drawer | Re-run Setup Kiosk; the kiosk app manages the lock task allowlist automatically |

---

## Project Files

```
├── app/src/main/            # Android app source
├── build/                   # Pre-built APK
├── kiosk-manager.py         # Desktop GUI (Python/tkinter)
├── build-apk.sh/mac.sh      # APK compilation scripts
├── setup-tools.bat/mac.sh   # Toolchain downloaders
├── setup-kiosk.bat           # CLI deploy script
├── exit-kiosk.bat            # CLI exit script
├── package-mac.sh            # macOS .dmg builder
├── package-win.sh            # Windows .exe builder
├── .github/workflows/        # CI/CD (builds macOS .dmg + Windows .exe)
├── debug.keystore           # APK signing key
├── README.md                # This file
└── LICENSE                  # MIT
```

## Quick Command Reference

```bash
# Connect to tablet
adb devices

# Set device owner
adb shell dpm set-device-owner com.example.webkiosk/.KioskDeviceAdminReceiver

# Exit kiosk mode
adb shell am force-stop com.example.webkiosk

# Hide/restore apps
adb shell pm disable-user --user 0 <package>
adb shell pm enable <package>

# List hidden apps
adb shell pm list packages -d

# Check lock task allowlist
adb shell dumpsys device_policy | grep LockTaskPolicy

# Factory reset
adb shell recovery --wipe_data
```
