@echo off
rem Build GoogleBooksDownloader.exe with PyInstaller.
rem Run from the project folder. Output lands in dist\
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Building ... this takes a few minutes.
"%PY%" -m PyInstaller build.spec --noconfirm --clean --distpath dist --workpath build
if errorlevel 1 goto FAIL

echo.
echo Done: dist\GoogleBooksDownloader.exe
dir /b dist
pause
exit /b 0

:FAIL
echo Build FAILED - see the output above.
pause
exit /b 1
