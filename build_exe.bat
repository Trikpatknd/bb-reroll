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

python tools\embed_nut.py
if errorlevel 1 (
    echo Failed to regenerate bbreroll/mod_template.py.
    exit /b 1
)

python tools\build_zip.py
if errorlevel 1 (
    echo Failed to build mod_bb_reroll_dump.zip.
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
echo Run it directly; on first Save ^& Deploy it creates mod\
echo bb_reroll_dump.nut next to the .exe (or in this project dir
echo in dev mode) and copies the .zip to your BB data folder.
echo ============================================================
endlocal
