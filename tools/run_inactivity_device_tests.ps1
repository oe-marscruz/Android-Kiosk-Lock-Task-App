param(
    [string]$Serial,
    [switch]$Run,
    [switch]$ScreenOff
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$bash = 'C:/Program Files/Git/bin/bash.exe'
$adb = Join-Path $env:LOCALAPPDATA 'Android/Sdk/platform-tools/adb.exe'
function Assert-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed with exit $LASTEXITCODE" }
}
if ($Run -and !$Serial) { throw 'Supply the currently user-confirmed test tablet with -Serial.' }
Push-Location $repo
try {
    & $bash tests/build_session6_fixtures.sh
    Assert-Exit 'Build isolated Session six fixture and instrumentation'
    $fixture = (Get-Content -LiteralPath "$repo/tmp/session6-tests/fixture-path.txt" -Raw).Trim()
    # Git Bash writes an MSYS path; convert through its path utility before native tools.
    $fixture = (& $bash -c 'cygpath -am "$1"' -- $fixture).Trim()
    Assert-Exit 'Resolve fixture path'
    Write-Output "Test-only APKs: $fixture"
    if (!$Run) { return }
    $state = & $adb -s $Serial get-state
    Assert-Exit 'Selected tablet state'
    if ($state.Trim() -ne 'device') { throw 'Selected tablet is not authorized/online.' }
    & $adb -s $Serial install -r -t "$fixture/session6-fixture.apk"
    Assert-Exit 'Install separate test-only fixture'
    & $adb -s $Serial install -r -t "$fixture/session6-tests.apk"
    Assert-Exit 'Install separate instrumentation'
    & $adb -s $Serial shell input keyevent KEYCODE_WAKEUP
    Assert-Exit 'Wake tablet'
    & $adb -s $Serial shell wm dismiss-keyguard
    Assert-Exit 'Request keyguard dismissal without changing lock settings'
    $screen = if ($ScreenOff) { 'true' } else { 'false' }
    $component = 'com.example.webkiosk.session6tests/com.example.webkiosk.session6tests.InactivityDeviceTest'
    $output = & $adb -s $Serial shell am instrument -w -r -e screenOff $screen $component 2>&1
    $result = $LASTEXITCODE
    $output | Tee-Object -FilePath "$repo/tmp/session6-tests/device-results.txt"
    if ($result -ne 0 -or !(($output -join "`n") -match 'INSTRUMENTATION_RESULT: session6_status=PASS')) {
        throw 'Session six lifecycle suite failed; inspect device-results.txt.'
    }
    & $adb -s $Serial shell am force-stop com.example.webkiosk.session6fixture
    Assert-Exit 'Stop only the isolated fixture process'
    $output = & $adb -s $Serial shell am instrument -w -r -e phase restart $component 2>&1
    $result = $LASTEXITCODE
    $output | Tee-Object -FilePath "$repo/tmp/session6-tests/restart-results.txt"
    if ($result -ne 0 -or !(($output -join "`n") -match 'INSTRUMENTATION_RESULT: session6_status=PASS')) {
        throw 'Session six process-restart suite failed; inspect restart-results.txt.'
    }
    Write-Output 'Passed requested Session six fixture checks. Production kiosk acceptance and Session seven isolation remain separate.'
} finally {
    Pop-Location
}
