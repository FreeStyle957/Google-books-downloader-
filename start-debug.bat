@echo off
rem Same as start.bat but with a visible console, for troubleshooting.
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
) else (
  python "%~dp0app.py"
)
pause
