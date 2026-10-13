@echo off
REM Build bb_reroll_gui.exe — single-file standalone GUI.
REM Output: dist\bb_reroll_gui.exe

setlocal
cd /d "%~dp0"

pip install -r requirements.txt >nul
if errorlevel 1 (
    echo Failed to install Python dependencies.
    exit /b 1
)

pyinstaller --noconfirm gui.spec
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
