@echo off
pushd "%~dp0"
python "launcher\launch_googlebook.py" --gpu virgl %*
if errorlevel 1 (
    echo.
    echo If 'python' is not found, please ensure Python 3.10+ is installed and added to PATH.
    pause
)
popd
