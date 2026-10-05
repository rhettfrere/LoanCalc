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

echo [1/3] Syncing dependencies...
uv sync --extra build || exit /b 1

echo [2/3] Running tests...
uv run --extra build pytest -q || exit /b 1

echo [3/3] Compiling with Nuitka (icon: src\loancalc\resources\loancalc.ico)...
uv run --extra build python build.py %* || exit /b 1

echo.
echo Done. See the build\ folder.
endlocal
