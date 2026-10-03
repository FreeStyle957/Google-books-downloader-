@echo off
rem Google Books Downloader - start from source (no console window).
rem For the packaged build just double-click GoogleBooksDownloader.exe instead.
setlocal
cd /d "%~dp0"

set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PYW%" goto RUNW
if exist "%PY%" goto RUN
goto NOPY

:RUNW
start "" "%PYW%" "%~dp0app.py"
exit /b 0

:RUN
start "" "%PY%" "%~dp0app.py"
exit /b 0

:NOPY
echo No virtualenv found. Create one first:
echo   python -m venv .venv
echo   .venv\Scripts\pip install -r requirements.txt
pause
exit /b 1
