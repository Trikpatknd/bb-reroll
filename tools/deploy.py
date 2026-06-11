#!/usr/bin/env python3
"""Build the mod zip from the CURRENT branch and copy it into Battle Brothers.

  python tools/deploy.py            # build + deploy (refuses on 'main')
  python tools/deploy.py --force    # deploy even from 'main'
  python tools/deploy.py --dry-run  # build + report, do NOT copy

The deploy target lives in deploy_config.json (gitignored) — copy
deploy_config.example.json and set "bb_data_dir". Deploying from 'main' is
refused by default: the installed mod should track the testing branch during
development so a stable-branch checkout doesn't silently overwrite a tested
build. Restart Battle Brothers after deploying — mods load only at launch.
"""
import json
import shutil
import sys
from pathlib import Path

from buildutil import read_version, git_branch
from build_zip import build_zip, DST

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "deploy_config.json"
EXAMPLE = ROOT / "deploy_config.example.json"


def _load_target() -> Path:
    if not CONFIG.exists():
        raise SystemExit(
            f"No {CONFIG.name} found. Copy {EXAMPLE.name} to {CONFIG.name} and set "
            '"bb_data_dir" to your Battle Brothers data folder.'
        )
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    target = data.get("bb_data_dir")
    if not target:
        raise SystemExit(f'{CONFIG.name} is missing "bb_data_dir".')
    return Path(target)


def main(argv):
    force = "--force" in argv
    dry = "--dry-run" in argv

    branch = git_branch()
    version = read_version()

    if branch == "main" and not force:
        raise SystemExit(
            f"Refusing to deploy from branch 'main' (v{version}). The installed mod "
            "should track the testing branch during development. Re-run with --force "
            "if you really mean to deploy the main branch."
        )
    if branch == "main":
        print(f"WARNING: deploying from 'main' (v{version}) because --force was given.")

    build_zip()

    if dry:
        print(f"[dry-run] built v{version} on branch '{branch}'; not copying.")
        return

    target_dir = _load_target()
    if not target_dir.exists():
        raise SystemExit(f"BB data folder not found: {target_dir}")
    dest = target_dir / DST.name
    shutil.copy2(DST, dest)
    print(f"Deployed v{version} (branch '{branch}') -> {dest}")
    print("Restart Battle Brothers — mods load only at launch.")


if __name__ == "__main__":
    main(sys.argv[1:])
