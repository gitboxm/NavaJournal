@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo Nava Journal - Development Setup
echo ==========================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher 'py' was not found.
  echo Install Python 3.13 x64 from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
if not exist .venv (
  py -3.13 -m venv .venv
  if errorlevel 1 (
    echo Could not create a Python 3.13 environment.
    echo Confirm Python 3.13 x64 is installed, then retry.
    pause
    exit /b 1
  )
)
echo Installing required packages. This may take several minutes on a slow connection.
call .venv\Scripts\python.exe -m pip install --disable-pip-version-check --timeout 120 --retries 10 -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Setup complete. Double-click run.bat to launch the app.
pause
exit /b 0
:failed
echo.
echo Installation failed. Check the internet connection and error above.
pause
exit /b 1
