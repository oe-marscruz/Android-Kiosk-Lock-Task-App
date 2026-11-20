@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "ADB=platform-tools\adb.exe"

echo ============================================
echo  CU Denver Equity - Kiosk Setup
echo ============================================
echo.

REM Check if ADB exists
if not exist "%ADB%" (
    echo [ERROR] ADB not found at %ADB%
    echo Run setup-tools.bat first to install the SDK.
    pause
    exit /b 1
)

echo [1/4] Checking device connection...
"%ADB%" devices 2>nul | findstr "device$" >nul
if errorlevel 1 (
    echo [ERROR] No device connected. Please:
    echo   1. Enable USB Debugging on your tablet
    echo   2. Connect via USB and accept the prompt
    echo   3. Run this script again
    pause
    exit /b 1
)
echo         Device connected.

echo [2/4] Building and installing the kiosk APK...
del /q "build\CU-Denver-Equity-Kiosk.apk" 2>nul
if exist "build\CU-Denver-Equity-Kiosk.apk" (
    echo [ERROR] Could not remove the previous APK.
    exit /b 1
)
call bash build-apk.sh
if errorlevel 1 (
    echo [ERROR] APK build failed.
    pause
    exit /b 1
)
if not exist "build\CU-Denver-Equity-Kiosk.apk" (
    echo [ERROR] APK build failed.
    pause
    exit /b 1
)
rem Never uninstall on failure: a Device Owner app cannot be removed, and a
rem signer mismatch means this tablet needs the signer inventory/reprovisioning
rem procedure (docs/remote-control/ARCHITECTURE.md section 7.1).
set "INSTALL_LOG=%TEMP%\kiosk-install-%RANDOM%%RANDOM%.log"
"%ADB%" install -r "build\CU-Denver-Equity-Kiosk.apk" > "%INSTALL_LOG%" 2>&1
set "INSTALL_RC=%ERRORLEVEL%"
findstr /i /c:"INSTALL_FAILED_UPDATE_INCOMPATIBLE" "%INSTALL_LOG%" >nul
if not errorlevel 1 (
    type "%INSTALL_LOG%"
    echo [ERROR] The installed kiosk app was signed with a different key.
    echo         Do NOT uninstall it. Record the installed signer and follow the
    echo         reprovisioning procedure before continuing.
    pause
    exit /b 1
)
findstr /x /c:"Success" "%INSTALL_LOG%" >nul
if errorlevel 1 goto install_failed
if not "%INSTALL_RC%"=="0" goto install_failed
goto install_succeeded
:install_failed
(
    type "%INSTALL_LOG%"
    echo [ERROR] APK install failed. Setup stopped; nothing was uninstalled.
    pause
    exit /b 1
)
:install_succeeded
del "%INSTALL_LOG%" 2>nul
echo         Kiosk APK installed successfully.

echo [3/4] Setting kiosk app as device owner...
"%ADB%" shell dpm set-device-owner com.example.webkiosk/.KioskDeviceAdminReceiver 2>&1 | findstr /i /c:"Success" /c:"already" >nul
if errorlevel 1 (
    echo [WARNING] Could not set device owner. It may already be set.
    echo         If Test DPC was the previous device owner, you may need to factory reset first.
) else (
    echo         Kiosk app is now the device owner.
)

echo [4/4] Verifying lock task allowlist...
REM The kiosk app configures the allowlist on first launch.
"%ADB%" shell dumpsys device_policy 2>nul | findstr "com.example.webkiosk" >nul
if errorlevel 1 (
    echo [WARNING] App might not be allowlisted yet. Open the kiosk app once
    echo         so it can configure Chrome and WiFi settings for lock task mode.
) else (
    echo         App is allowlisted for lock task mode.
)

echo.
echo ============================================
echo  SETUP COMPLETE
echo ============================================
echo.
echo To enter kiosk mode, tap the "CU Denver Equity"
echo app icon on your tablet's home screen.
echo.
echo Chrome and WiFi settings can now run in lock task mode.
echo.
echo To exit kiosk mode, run: exit-kiosk.bat
echo.
pause
