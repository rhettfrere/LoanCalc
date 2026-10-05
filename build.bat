@echo off
REM Build LoanCalc into a single distributable .exe.
REM Usage:  build.bat          (standalone folder)
REM         build.bat --onefile

setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [!] uv is not on PATH. Install it from https://astral.sh/uv
    exit /b 1
)

echo [1/2] Syncing dependencies...
uv sync --extra build || exit /b 1

echo [2/2] Compiling with Nuitka...
uv run python build.py %* || exit /b 1

echo.
echo Done. See the build\ folder.
endlocal
