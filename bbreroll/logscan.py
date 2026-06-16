"""Log-line recognition for BB's log.html — shared by the GUI's live watcher
and its connect-time tail scan, and unit-testable without tkinter.

Every pattern here must match a line the .nut actually emits (see
mod/bb_reroll_dump.nut); tests in tests/test_logscan.py pin them against the
exact emitted strings so the two can't silently drift apart.
"""
import re

# ── live-watch patterns ──
MATCH_RE    = re.compile(r"\[BBREROLL2\]\s+\*\*\*\s+MATCH\s+at\s+iter\s+(\d+)\s+seed=(\S+?)(?:\s+\(verified\))?\s+\*\*\*")
PROGRESS_RE = re.compile(r"\[BBREROLL2\]\s+iter\s+(\d+)/(\d+)")
START_RE    = re.compile(r"\[BBREROLL2\]\s+brute force start")
# Mod logs this when a candidate triggers the authoritative world rebuild.
# v3.4.6+ wording is "candidate ... — confirming"; older builds said
# "stars-pass ... — verifying". Match both so the verify LED works either way.
VERIFY_RE   = re.compile(r"\[BBREROLL2\]\s+iter\s+(\d+)\s+(?:candidate|stars-pass)\s+seed=(\S+)")
# Init line, written once at BB launch (after Legends loads). Doubles as the
# "mod is loaded" signal and the source of the installed mod version.
INIT_RE     = re.compile(r"\[BBREROLL\]\s+mod queued \(v([0-9][0-9A-Za-z.\-]*)\)")
# Clean-finish marker emitted just before the loop throws its sentinel.
FINISH_RE   = re.compile(r"\[BBREROLL2\]\s+\*\*\*\s+FINISH:\s+(.+?)\s+\*\*\*")
# Dependency self-check failure (Phase 5). Captures the missing-mod list.
DEPCHECK_RE = re.compile(r"\[BBREROLL2\]\s+BB Reroll: missing required mod\(s\): (.+?)\. BB Reroll needs")
# Non-sentinel exception passed through by the startNewCampaign catch (Phase 2).
UNEXPECTED_RE = re.compile(r"\[BBREROLL2\]\s+UNEXPECTED exception in startNewCampaign[^:]*:\s*(\S.*)")

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return _TAG_RE.sub("", s)


def analyze_tail(text: str) -> dict:
    """Classify already-written log content (GUI connected late, BB launched
    first, or the GUI was reopened after a run).

    BB truncates log.html on every launch, so the tail is normally the current
    session. If an init line exists, only events AFTER the last init count —
    anything before it belongs to an older session that survived in the same
    file. Without an init line, the whole text is considered.

    Returns {mod_version, finished, missing_deps, unexpected} (None when absent).
    """
    inits = list(INIT_RE.finditer(text))
    version = inits[-1].group(1) if inits else None
    scope = text[inits[-1].end():] if inits else text

    finishes = list(FINISH_RE.finditer(scope))
    depchecks = list(DEPCHECK_RE.finditer(scope))
    unexpecteds = list(UNEXPECTED_RE.finditer(scope))
    return {
        "mod_version": version,
        "finished": finishes[-1].group(1) if finishes else None,
        "missing_deps": depchecks[-1].group(1) if depchecks else None,
        "unexpected": unexpecteds[-1].group(1) if unexpecteds else None,
    }
