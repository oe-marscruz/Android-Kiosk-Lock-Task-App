@echo off
setlocal
cd /d "%~dp0"
REM Supply --serial TABLET and --apk "C:\Reviewed Builds\kiosk.apk" for setup.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "%~dp0provisioning.py" setup %*
) else (
    py -3 "%~dp0provisioning.py" setup %*
)
exit /b %errorlevel%
