#!/usr/bin/env python3
"""Build mod/mod_bb_reroll_dump.zip from mod/bb_reroll_dump.nut.

BB's mod-hooks loader requires the .nut inside scripts/!mods_preload/.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "mod" / "bb_reroll_dump.nut"
DST  = ROOT / "mod" / "mod_bb_reroll_dump.zip"

DST.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(SRC, arcname="scripts/!mods_preload/bb_reroll_dump.nut")
print(f"Built {DST.relative_to(ROOT)} ({DST.stat().st_size} bytes)")
