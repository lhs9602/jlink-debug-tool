@echo off
rem run_tdc_debug_jlink.bat - J-Link debug tool launcher (double-click to start).
rem Runs run_tdc_debug_jlink.py in this folder with Python every time, so edited tool code takes effect
rem without any build step. Arguments pass through to run_tdc_debug_jlink.py (e.g. --ini other.ini).
rem Python: TDC_PYTHON (full path to python.exe) if set, else python on PATH, else the py launcher.
rem ASCII only: cmd.exe reads batch files in the console code page.
setlocal
title tdc_debug_jlink
pushd "%~dp0"

if defined TDC_PYTHON (
    "%TDC_PYTHON%" run_tdc_debug_jlink.py %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        py -3 run_tdc_debug_jlink.py %*
    ) else (
        python run_tdc_debug_jlink.py %*
    )
)
set "TDC_RC=%ERRORLEVEL%"

rem Keep the window open on failure so the error can be read
if not "%TDC_RC%"=="0" (
    echo.
    echo [run_tdc_debug_jlink] stopped with exit code %TDC_RC%.
    echo If a module is missing, install the packages once:  python -m pip install -r requirements.txt
    pause
)
popd
exit /b %TDC_RC%
