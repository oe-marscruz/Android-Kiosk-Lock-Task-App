param(
    [string]$Serial,
    [string]$TargetApk,
    [string]$TestKeystore,
    [string]$TestKeyAlias,
    [string]$TestStorePassFile,
    [string]$TestKeyPassFile,
    [switch]$Run,
    [switch]$LiveFlow
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
foreach ($inputFile in @($TargetApk, $TestKeystore, $TestStorePassFile, $TestKeyPassFile)) {
    if (!$inputFile -or !(Test-Path -LiteralPath $inputFile -PathType Leaf)) {
        throw 'Supply -TargetApk, -TestKeystore, -TestKeyAlias, -TestStorePassFile and -TestKeyPassFile. Test and target APKs must use the same signing identity; the exposed repository key has been removed.'
    }
}
if (!$TestKeyAlias) { throw 'Specify -TestKeyAlias for the target APK signing identity.' }
$out = Join-Path $repo 'tmp/navigation-device-tests'
$jdk = 'C:/Program Files/Android/Android Studio/jbr/bin'
$sdk = Join-Path $env:LOCALAPPDATA 'Android/Sdk'
$tools = Join-Path $sdk 'build-tools/36.0.0'
$androidJar = Join-Path $sdk 'platforms/android-37.0/android.jar'
$adb = Join-Path $sdk 'platform-tools/adb.exe'
foreach ($dir in @($out, "$out/compile-only", "$out/classes", "$out/dex")) {
    [System.IO.Directory]::CreateDirectory($dir) | Out-Null
}
function Assert-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed with exit $LASTEXITCODE" }
}
# Compile against the policy API, but package only tests; runtime calls use the installed APK.
& "$jdk/javac.exe" -source 11 -target 11 -cp $androidJar -d "$out/compile-only" "$repo/app/src/main/java/com/example/webkiosk/NavigationPolicy.java"
Assert-Exit 'Policy compile-only API'
& "$jdk/javac.exe" -source 11 -target 11 -cp "$androidJar;$out/compile-only" -d "$out/classes" "$repo/tests/NavigationPolicyTest.java" "$repo/tests/android/NavigationDeviceTest.java"
Assert-Exit 'Instrumentation compilation'
& "$tools/aapt2.exe" link -o "$out/unsigned.apk" -I $androidJar --manifest "$repo/tests/android/AndroidManifest.xml" --min-sdk-version 26 --target-sdk-version 35
Assert-Exit 'Test manifest linking'
$classes = @(Get-ChildItem -LiteralPath "$out/classes" -Recurse -Filter '*.class' | Select-Object -ExpandProperty FullName)
& "$jdk/java.exe" -cp "$tools/lib/d8.jar" com.android.tools.r8.D8 --lib $androidJar --classpath "$out/compile-only" --min-api 26 --output "$out/dex" $classes
Assert-Exit 'Test DEX conversion'
& "$jdk/jar.exe" uf "$out/unsigned.apk" -C "$out/dex" classes.dex
Assert-Exit 'Test APK assembly'
& "$tools/zipalign.exe" -f -p 4 "$out/unsigned.apk" "$out/aligned.apk"
Assert-Exit 'Test APK alignment'
$keyPassArgs = @()
if ((Resolve-Path -LiteralPath $TestStorePassFile).Path -ne (Resolve-Path -LiteralPath $TestKeyPassFile).Path) {
    $keyPassArgs = @('--key-pass', "file:$TestKeyPassFile")
}
& "$jdk/java.exe" -jar "$tools/lib/apksigner.jar" sign --ks $TestKeystore --ks-pass "file:$TestStorePassFile" @keyPassArgs --ks-key-alias $TestKeyAlias --out "$out/navigation-tests.apk" "$out/aligned.apk"
Assert-Exit 'Test APK signing'
Write-Output "Test APK: $out/navigation-tests.apk"
if (!$Run) { return }
if (!$Serial) { throw 'Specify the user-confirmed test device with -Serial before -Run' }
$state = & $adb -s $Serial get-state
Assert-Exit 'Selected device state'
if ($state.Trim() -ne 'device') { throw 'Selected device is not authorized/online' }
& $adb -s $Serial install -r $TargetApk
Assert-Exit 'Session 3 target installation'
& $adb -s $Serial install -r -t "$out/navigation-tests.apk"
Assert-Exit 'Test-only APK installation'
# Waking/dismissing an unsecured keyguard does not disable device lock settings.
& $adb -s $Serial shell input keyevent KEYCODE_WAKEUP
Assert-Exit 'Wake test tablet'
& $adb -s $Serial shell wm dismiss-keyguard
Assert-Exit 'Dismiss keyguard if permitted'
$live = if ($LiveFlow) { 'true' } else { 'false' }
$instrumentationOutput = & $adb -s $Serial shell am instrument -w -r -e runLiveFlow $live 'com.example.webkiosk.navigationtests/com.example.webkiosk.navigationtests.NavigationDeviceTest' 2>&1
$instrumentationExit = $LASTEXITCODE
$instrumentationOutput | Tee-Object -FilePath "$out/results.txt"
if ($instrumentationExit -ne 0 -or !(($instrumentationOutput -join "`n") -match 'INSTRUMENTATION_RESULT: session3_status=PASS')) {
    throw "Navigation device tests failed; inspect $out/results.txt"
}
