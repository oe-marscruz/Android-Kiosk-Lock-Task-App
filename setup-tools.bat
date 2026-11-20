@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Kiosk Toolchain Setup
echo ============================================
echo.
echo This downloads ADB, JDK 17, and Android SDK (approx. 500 MB).
echo Only needed once per machine.
echo.

set /p CONFIRM="Continue? (y/n): "
if /i not "%CONFIRM%"=="y" exit /b 0

REM --- ADB Platform Tools ---
if not exist "platform-tools\adb.exe" (
    echo [1/4] Downloading Android Platform Tools...
    curl -L -o platform-tools.zip "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    powershell -Command "Expand-Archive -Path platform-tools.zip -DestinationPath . -Force"
    del platform-tools.zip
    echo         Platform Tools installed.
) else (
    echo [1/4] Platform Tools already installed.
)

REM --- JDK 17 ---
if not exist "jdk\jdk-17.0.20+8\bin\java.exe" (
    echo [2/4] Downloading JDK 17...
    curl -L -o jdk.zip "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse"
    powershell -Command "Expand-Archive -Path jdk.zip -DestinationPath jdk -Force"
    del jdk.zip
    echo         JDK 17 installed.
) else (
    echo [2/4] JDK 17 already installed.
)

REM --- Android SDK Command-Line Tools ---
if not exist "android-sdk\cmdline-tools\latest\bin\sdkmanager.bat" (
    echo [3/4] Downloading Android SDK Command-Line Tools...
    curl -L -o cmdline-tools.zip "https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip"
    if not exist "android-sdk\cmdline-tools" mkdir "android-sdk\cmdline-tools"
    powershell -Command "Expand-Archive -Path cmdline-tools.zip -DestinationPath android-sdk\cmdline-tools -Force"
    move android-sdk\cmdline-tools\cmdline-tools android-sdk\cmdline-tools\latest 2>nul
    del cmdline-tools.zip
    echo         SDK Command-Line Tools installed.
) else (
    echo [3/4] SDK Command-Line Tools already installed.
)

REM --- Install SDK packages ---
echo [4/4] Installing Android SDK packages (platform + build-tools)...
set "JDK=%~dp0jdk"
for /d %%d in ("%JDK%\jdk-17*") do set "JAVA_HOME=%%d"
set "SDK_ROOT=%~dp0android-sdk"

if exist "android-sdk\platforms\android-35\android.jar" if exist "android-sdk\build-tools\36.0.0\aapt2.exe" goto verify_sdk

echo y | powershell -Command "$env:JAVA_HOME='%JAVA_HOME%'; $input | & '%SDK_ROOT%\cmdline-tools\latest\bin\sdkmanager.bat' --sdk_root='%SDK_ROOT%' --licenses" >nul 2>&1
powershell -Command "$env:JAVA_HOME='%JAVA_HOME%'; & '%SDK_ROOT%\cmdline-tools\latest\bin\sdkmanager.bat' --sdk_root='%SDK_ROOT%' 'platforms;android-35' 'build-tools;35.0.0' 'build-tools;36.0.0'" >nul 2>&1

:verify_sdk
if not exist "android-sdk\platforms\android-35\android.jar" (
    echo [ERROR] Android platform 35 is missing.
    exit /b 1
)
if not exist "android-sdk\build-tools\36.0.0\aapt2.exe" (
    echo [ERROR] Android Build Tools 36.0.0 is missing.
    exit /b 1
)
echo         SDK packages installed successfully.

echo.
echo ============================================
echo  SETUP COMPLETE
echo ============================================
echo.
echo Next: Run setup-kiosk.bat to configure the tablet.
echo.
pause
