@echo off
set "DASHBOARD_ROOT=%~dp0.."
set "DASHBOARD_PYTHON=%DASHBOARD_ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%DASHBOARD_PYTHON%" (
  echo 请先运行 py -3 scripts\install_windows.py
  exit /b 1
)
start "" "%DASHBOARD_PYTHON%" "%DASHBOARD_ROOT%\scripts\windows_tray.py"
