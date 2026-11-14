param(
    [string]$Serial,
    [switch]$Run
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
    & $bash tests/build_session7_fixtures.sh
    Assert-Exit 'Build isolated Session seven APKs'
    $fixture = (Get-Content -LiteralPath "$repo/tmp/session7-tests/fixture-path.txt" -Raw).Trim()
    $fixture = (& $bash -c 'cygpath -am "$1"' -- $fixture).Trim()
    Assert-Exit 'Resolve fixture path'
    Write-Output "Test-only APKs: $fixture"
    if (!$Run) { return }
    $state = & $adb -s $Serial get-state
    Assert-Exit 'Selected tablet state'
    if ($state.Trim() -ne 'device') { throw 'Selected tablet is not authorized/online.' }
    & $adb -s $Serial install -r -t "$fixture/session7-fixture.apk"
    Assert-Exit 'Install separate test-only fixture'
    & $adb -s $Serial install -r -t "$fixture/session7-tests.apk"
    Assert-Exit 'Install separate instrumentation'
    $component = 'com.example.webkiosk.session7tests/com.example.webkiosk.session7tests.SessionResetDeviceTest'
    foreach ($phase in @('isolation', 'restart')) {
        if ($phase -eq 'restart') {
            & $adb -s $Serial shell am force-stop com.example.webkiosk.session7fixture
            Assert-Exit 'Stop only the isolated fixture process'
        }
        $output = & $adb -s $Serial shell am instrument -w -r -e phase $phase $component 2>&1
        $result = $LASTEXITCODE
        $output | Tee-Object -FilePath "$repo/tmp/session7-tests/$phase-results.txt"
        if ($result -ne 0 -or !(($output -join "`n") -match 'INSTRUMENTATION_RESULT: session7_status=PASS')) {
            throw "Session seven $phase checks failed; inspect $phase-results.txt."
        }
    }
    Write-Output 'Passed requested isolated Session seven checks; review remaining real-network and production acceptance.'
} finally {
    Pop-Location
}
