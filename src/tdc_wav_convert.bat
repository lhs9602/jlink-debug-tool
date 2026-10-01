@echo off
rem tdc_wav_convert.bat - converts WAV files for injection (16 kHz, mono, 24-bit PCM). Works without J-Link.
rem Drag WAV files onto this file, or double-click it and pick files in the dialog.
rem Converted files go to the data folder next to this file, named <name>_16k.wav.
rem The peak level is set to the microphone level (about -50.5 dBFS). The output text shows the change.
rem Options pass through to tdc_wav_convert.py (e.g. --keep-level, --peak -40, -o out.wav).
rem Python: TDC_PYTHON (full path to python.exe or pythonw.exe) if set, else python on PATH, else the py launcher.
rem No parentheses blocks here: a dropped file name may contain parentheses.
rem ASCII only: cmd.exe reads batch files in the console code page.
setlocal
set TDC_PY=python
rem "python -c" instead of "where python": the Microsoft Store stub is found by where but does not run.
python -c "" >nul 2>nul || set TDC_PY=py -3
if defined TDC_PYTHON set TDC_PY="%TDC_PYTHON:pythonw.exe=python.exe%"
if not defined TDC_PYTHON python -c "" >nul 2>nul || py -3 -c "" >nul 2>nul || echo [tdc_wav_convert] Python was not found. Install 64-bit Python with "Add python.exe to PATH" checked.
%TDC_PY% "%~dp0tdc_wav_convert.py" %*
set TDC_RC=%ERRORLEVEL%
echo.
pause
exit /b %TDC_RC%
