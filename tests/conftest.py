"""Make the repo root and tools/ importable from tests without installing
the project. build_zip.py imports its sibling buildutil.py, so tools/ must be
on sys.path too.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "tools"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
