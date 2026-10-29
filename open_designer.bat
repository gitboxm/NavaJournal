@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\pyside6-designer.exe (
  echo Qt Designer was not found. Run setup.bat first.
  pause
  exit /b 1
)
start "Qt Designer" .venv\Scripts\pyside6-designer.exe
