#!/usr/bin/env python3
"""Build mod/mod_bb_reroll_dump.zip from mod/bb_reroll_dump.nut.

BB's mod-hooks loader requires the .nut inside scripts/!mods_preload/. We also
stamp the repo-root VERSION into the .nut first and drop a BBRR_MANIFEST.json
at the zip root (version + build date + branch) so the deployed artifact is
self-describing. The manifest lives outside scripts/ so BB's loader ignores it.
"""
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from buildutil import read_version, stamp_nut_file, git_branch

ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "mod" / "bb_reroll_dump.nut"
DST  = ROOT / "mod" / "mod_bb_reroll_dump.zip"


def build_zip() -> dict:
    """Stamp the .nut, build the deploy zip, return the manifest dict."""
    version = read_version()
    if stamp_nut_file(version):
        print(f"Stamped .nut version -> {version}")

    branch = git_branch()
    manifest = {
        "mod": "bb_reroll_dump",
        "version": version,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "branch": branch,
    }

    DST.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(SRC, arcname="scripts/!mods_preload/bb_reroll_dump.nut")
        z.writestr("BBRR_MANIFEST.json", json.dumps(manifest, indent=2))

    print(f"Built {DST.relative_to(ROOT)} (v{version}, branch={branch}, {DST.stat().st_size} bytes)")
    return manifest


if __name__ == "__main__":
    build_zip()
