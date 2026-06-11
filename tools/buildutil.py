"""Shared build helpers. The repo-root VERSION file is the single source of
truth for the version string; the .nut, the embedded template, the deploy zip
manifest, and the GUI all derive from it.

Importable from the other tools/ scripts because Python puts a script's own
directory on sys.path[0] when you run `python tools/<script>.py`.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
NUT = ROOT / "mod" / "bb_reroll_dump.nut"

# Matches the `Version = "..."` slot inside the ::BBReroll table in the .nut.
_VER_RE = re.compile(r'(Version\s*=\s*")[^"]*(")')


def read_version() -> str:
    """The authoritative version string from the repo-root VERSION file."""
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def stamp_nut_version(nut_text: str, version: str) -> str:
    """Return nut_text with its `Version = "..."` slot set to `version`."""
    new, n = _VER_RE.subn(r"\g<1>" + version + r"\g<2>", nut_text, count=1)
    if n == 0:
        raise RuntimeError(
            'Could not find a `Version = "..."` line in the .nut to stamp.'
        )
    return new


def stamp_nut_file(version: str | None = None) -> bool:
    """Stamp the on-disk .nut to match VERSION. Returns True if it changed.

    Writing the real version back into the .nut keeps every downstream path
    (embed_nut, build_zip, the GUI's rebuild_zip) producing a correctly
    versioned artifact without needing build-time placeholder substitution.
    Only writes when the version actually differs, so routine builds don't
    dirty the tree.
    """
    version = version or read_version()
    text = NUT.read_text(encoding="utf-8")
    stamped = stamp_nut_version(text, version)
    if stamped != text:
        NUT.write_text(stamped, encoding="utf-8")
        return True
    return False


def git_branch() -> str:
    """Current git branch, or 'unknown' if git isn't available / not a repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"
