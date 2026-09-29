@echo off
set "PULSE_ROOT=%~dp0.."
set "PULSE_PYTHON=%PULSE_ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PULSE_PYTHON%" (
  echo 请先运行 py -3 scripts\install_windows.py
  exit /b 1
)
start "" "%PULSE_PYTHON%" "%PULSE_ROOT%\scripts\windows_tray.py"
