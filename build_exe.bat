@echo off
REM Build bb_reroll_gui.exe — single-file standalone GUI.
REM Output: dist\bb_reroll_gui.exe

setlocal
cd /d "%~dp0"

REM The exe holds the Python that builds it: 3.15 from python.org is about 1.6-1.9x faster than 3.10.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import sys; sys.exit(sys.version_info[:2] != (3, 15))"
if errorlevel 1 (
    echo This build needs Python 3.15 from python.org.
    exit /b 1
)

"%PY%" -m pip install -r requirements.txt >nul
if errorlevel 1 (
    echo Failed to install Python dependencies.
    exit /b 1
)

"%PY%" -m PyInstaller --noconfirm gui.spec
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)

echo.
echo ============================================================
echo Built: dist\bb_reroll_gui.exe
echo Run it directly. It finds your Battle Brothers install by
echo itself and reads the game's own files - nothing is copied
echo into the game and nothing has to be extracted.
echo ============================================================
endlocal
