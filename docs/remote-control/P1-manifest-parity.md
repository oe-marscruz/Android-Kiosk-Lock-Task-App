# P1 manifest parity

The Gradle-built APK differs from the old APK in two manifest details:

- The application has `extractNativeLibs=true`. The app has no native libraries to extract, so this has no effect on its behavior or component resolution.
- The HOME/launcher activity is written as `com.example.kiosklauncher.LauncherActivity`. The old relative activity name resolves against the manifest package to the same fully qualified class. Android resolves the same component and intent filters; the spelling does not change launcher selection.

This conclusion follows from Android manifest name resolution and the role of `extractNativeLibs`; it has not been confirmed here by comparing `aapt2 dump xmltree` output for both APKs. Device verification remains necessary because preferred HOME selection and device-owner state are held on the device.

## K11 checkpoint for P3k/P4

Use an APK signed for an in-place upgrade and record the results on the provisioned K11:

1. Run `adb install -r <apk>` and confirm success. Run `adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME` and confirm the default HOME is `com.example.kiosklauncher/.LauncherActivity` (or its fully qualified equivalent).
2. Run `adb shell dpm list-owners` and confirm the device owner still lists `com.example.kiosklauncher/.KioskDeviceAdminReceiver`.
3. Exercise the normal kiosk entry and authorized exit, and confirm lock-task engages and exits as expected. Verify the student HOME and approved Chrome and Settings/Wi-Fi paths as required by the P4 gates.
