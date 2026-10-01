@echo off
rem run_tdc_debug_jlink.bat - J-Link debug tool launcher (double-click to start).
rem Starts run_tdc_debug_jlink.py in this folder with pythonw (no console window), then this window closes at once.
rem The tool code is read at every start, so edited tool code takes effect without any build step.
rem Arguments pass through to run_tdc_debug_jlink.py (e.g. --ini other.ini).
rem Python: TDC_PYTHON (full path to pythonw.exe or python.exe) if set, else pythonw on PATH, else the pyw launcher.
rem Errors at start are shown in a message box. For console output run:  python run_tdc_debug_jlink.py
rem ASCII only: cmd.exe reads batch files in the console code page.
setlocal
pushd "%~dp0"
if defined TDC_PYTHON set "TDC_PYW=%TDC_PYTHON:python.exe=pythonw.exe%"

if defined TDC_PYTHON (
    start "" "%TDC_PYW%" run_tdc_debug_jlink.py %*
) else (
    where pythonw >nul 2>nul
    if errorlevel 1 (
        where pyw >nul 2>nul
        if errorlevel 1 (
            echo [run_tdc_debug_jlink] Python was not found.
            echo Install 64-bit Python with "Add python.exe to PATH" checked, then run this file again.
            pause
        ) else (
            start "" pyw -3 run_tdc_debug_jlink.py %*
        )
    ) else (
        start "" pythonw run_tdc_debug_jlink.py %*
    )
)
popd
