@echo off
pushd "%~dp0"
echo ================================================================
echo   Googlebook OS - Factory Reset / Data Reset
echo ================================================================
echo This will delete your current VM userdata overlay and reset
echo Googlebook OS back to its clean initial state.
echo.
set /p CONFIRM="Are you sure you want to proceed? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo Reset cancelled.
    popd
    pause
    exit /b 0
)

if exist "prepared\userdata.qcow2" (
    del /f /q "prepared\userdata.qcow2"
    echo Userdata deleted successfully.
)

if exist "qemu\qemu-img.exe" (
    "qemu\qemu-img.exe" create -f qcow2 -F qcow2 -b "base.qcow2" "prepared\userdata.qcow2"
    echo Fresh userdata.qcow2 created from base.qcow2!
)
echo Reset complete. Next launch will start with clean desktop setup.
popd
pause
