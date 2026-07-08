@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 public_gui.py
  goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
  python public_gui.py
  goto :eof
)
echo Python 3 is required. Install Python from https://www.python.org/downloads/ and run this file again.
pause
