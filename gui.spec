# PyInstaller spec for bb_reroll_gui
# Build with:  pyinstaller --noconfirm gui.spec
# Output:      dist/bb_reroll_gui.exe

# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas  = []
datas += collect_data_files("customtkinter")   # ship the CTK theme JSON files
datas += [("VERSION", ".")]                     # single-source version string, read at runtime

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["plyer.platforms.win.notification"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="bb_reroll_gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
